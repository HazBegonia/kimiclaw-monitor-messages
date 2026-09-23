"""Resident deterministic notifier: consume collector artifacts -> rule engine
-> aggregate one markdown -> push via WeCom smart-bot WebSocket client.

Replaces the OpenClaw LLM triage loop with a 0-token deterministic pipeline
(change: retire-openclaw-py-notifier). The interface with the collector is the
same log directories + `state/notify-state.json` cursor it already maintains.

Since change share-ff-bot-connection the push goes through the bot tool layer
(`src/bot_tool.py`): it owns the shared FF connection choreography (connect ->
send -> disconnect -> revive the Claw companion, failure backoff). This loop
only calls `bot_tool.push_markdown()` and, each round, the debt-settling
`bot_tool.ensure_companion_alive()`.

Loop contract (spec py-notifier-loop):
  - process only artifacts after the push cursor; a missing/corrupt cursor is
    an EMPTY cursor (process everything from the start, never silently skip)
  - importance decided purely by config/triage-rules.json (hot-read each round)
  - one aggregated markdown per round, at most one message
  - cursor advances ONLY after a successful send (or when nothing important)
  - send failure -> JSONL record in logs/intranet-notify/, cursor untouched,
    retried per the tool layer's persisted backoff (at-least-once, never
    duplicated)
  - --dry-run renders and prints, never connects, never advances
  - --once runs a single round and exits nonzero on failure
  - resident single-instance lock (state/notifier-resident.lock), watchdog-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src import bot_tool
from src.intranet_filename_monitor import (acquire_resident_lock, refresh_resident_lock,
    release_resident_lock)  # reuse verified lock code; collector file stays untouched
from src.triage_rules import RulesEngine

TIME_ZONE = ZoneInfo("Asia/Shanghai")
MARKDOWN_LIMIT_BYTES = 20480
SECTION_LIMIT = 15
ERROR_LINE_LIMIT = 80

DEFAULTS: dict[str, Any] = {
    "chatid": "",
    "secretsFile": "state/secrets/wecom-bot.json",
    "pollIntervalSeconds": 5,
    "diffLogDir": "logs/intranet-diff",
    "errorLogDir": "logs/intranet-error",
    "notifyLogDir": "logs/intranet-notify",
    "stateFile": "state/notify-state.json",
    "rulesFile": "config/triage-rules.json",
    "lockFile": "state/notifier-resident.lock",
    "botToolStateFile": "state/bot-tool-state.json",
    "sourceUrl": "",
    "timeouts": {"connect": 10, "ack": 15},
}


def _now() -> datetime:
    return datetime.now(TIME_ZONE)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{time.time_ns()}")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------- config

def load_config(path: Path) -> dict[str, Any]:
    """Load notifier config with defaults; validate the critical values."""
    cfg = dict(DEFAULTS)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"notifier config must be an object: {path}")
        cfg.update(data)
        if "timeouts" in data:
            if not isinstance(data["timeouts"], dict):
                raise ValueError("config.timeouts must be an object")
            cfg["timeouts"] = {**DEFAULTS["timeouts"], **data["timeouts"]}
    if not str(cfg.get("chatid") or "").strip():
        raise ValueError("config.chatid is required (target group)")
    for key in ("diffLogDir", "errorLogDir", "notifyLogDir", "stateFile", "rulesFile", "lockFile", "secretsFile"):
        if not str(cfg.get(key) or "").strip():
            raise ValueError(f"config.{key} is required")
    interval = cfg.get("pollIntervalSeconds")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("config.pollIntervalSeconds must be a positive number")
    cfg["pollIntervalSeconds"] = float(interval)
    return cfg


# ---------------------------------------------------------------- cursor

def empty_cursor() -> dict[str, Any]:
    return {"diffCursor": None, "errorCursor": {"date": None, "offset": 0}}


def load_cursor(path: Path) -> dict[str, Any]:
    """Missing or corrupt cursor -> empty cursor (never silently skip artifacts)."""
    if not path.exists():
        return empty_cursor()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("cursor root must be an object")
        diff = data.get("diffCursor")
        if diff is not None and not isinstance(diff, str):
            raise ValueError("diffCursor must be a string")
        ec = data.get("errorCursor")
        if isinstance(ec, dict):
            date = ec.get("date")
            offset = ec.get("offset", 0)
            if date is not None and not isinstance(date, str):
                raise ValueError("errorCursor.date must be a string")
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValueError("errorCursor.offset must be a non-negative integer")
            return {"diffCursor": diff, "errorCursor": {"date": date, "offset": int(offset)}}
        if ec is not None:
            raise ValueError("errorCursor must be an object")
        return {"diffCursor": diff, "errorCursor": {"date": None, "offset": 0}}
    except (OSError, json.JSONDecodeError, ValueError):
        return empty_cursor()


def save_cursor(path: Path, cursor: dict[str, Any]) -> None:
    body = json.dumps(cursor, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(path, body)


# ---------------------------------------------------------------- collect

def list_new_diff_files(diff_dir: Path, diff_cursor: str | None) -> list[Path]:
    if not diff_dir.exists():
        return []
    files = sorted(p for p in diff_dir.glob("*.log") if p.is_file())
    if not diff_cursor:
        return files
    return [p for p in files if p.name > diff_cursor]


def parse_diff_log(path: Path) -> dict[str, Any]:
    """Parse a collector diff log into a structured fact.

    Supports both formats the collector has written over time:
      - header lines: monitorId / detectedAt / fingerprints
      - newer: "added:" / "removed:" sections with "- name" entries
      - older: "changedFields:" with "- root_files: {...json...}"
    """
    fact: dict[str, Any] = {"monitorId": "", "detectedAt": None, "added": [], "removed": []}
    in_added = in_removed = in_changed = False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.rstrip()
        if line.startswith("monitorId:"):
            fact["monitorId"] = line.split(":", 1)[1].strip()
        elif line.startswith("detectedAt:"):
            fact["detectedAt"] = line.split(":", 1)[1].strip()
        elif line.strip() == "added:":
            in_added, in_removed, in_changed = True, False, False
        elif line.strip() == "removed:":
            in_added, in_removed, in_changed = False, True, False
        elif line.strip().startswith("changedFields:"):
            in_added, in_removed, in_changed = False, False, True
        elif line.startswith("- ") and in_added:
            fact["added"].append(line[2:].strip())
        elif line.startswith("- ") and in_removed:
            fact["removed"].append(line[2:].strip())
        elif line.startswith("- ") and in_changed:
            name, _, raw_json = line[2:].partition(": ")
            if name.strip() == "root_files":
                try:
                    payload = json.loads(raw_json)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    fact["added"] = [str(x) for x in payload.get("added", [])]
                    fact["removed"] = [str(x) for x in payload.get("removed", [])]
    if not fact["monitorId"]:
        fact["monitorId"] = "intranet-root"  # older logs predate monitorId
    return fact


def _parse_error_jsonl(line: str) -> dict[str, Any] | None:
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict):
        return None
    return {
        "monitorId": str(rec.get("monitorId") or ""),
        "detectedAt": rec.get("detectedAt") or None,
        "phase": str(rec.get("phase") or ""),
        "errorType": str(rec.get("errorType") or ""),
        "message": str(rec.get("message") or ""),
        "retryable": bool(rec.get("retryable")),
        "statePreserved": bool(rec.get("statePreserved")),
    }


def collect_new_errors(error_dir: Path, err_cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read error JSONL after the cursor. Returns (facts, cursor_pointing_to_EOF)."""
    cur_date = err_cursor.get("date")
    start_offset = int(err_cursor.get("offset", 0)) if cur_date else 0
    if not error_dir.exists():
        return [], {"date": cur_date, "offset": start_offset}
    facts: list[dict[str, Any]] = []
    end_date, end_offset = cur_date, start_offset
    for path in sorted(p for p in error_dir.glob("*.log") if p.is_file()):
        date = path.stem
        if cur_date and date < cur_date:
            continue
        offset = start_offset if (cur_date and date == cur_date) else 0
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for idx in range(offset, len(lines)):
            if not lines[idx].strip():
                continue
            fact = _parse_error_jsonl(lines[idx])
            if fact is not None:
                facts.append(fact)
        end_date, end_offset = date, len(lines)
    return facts, {"date": end_date, "offset": end_offset}


def collect(cfg: dict[str, Any], cursor: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Collect new diff + error facts and the end-cursor covering everything read."""
    diff_dir = Path(str(cfg["diffLogDir"]))
    diff_files = list_new_diff_files(diff_dir, cursor.get("diffCursor"))
    diffs = [parse_diff_log(p) for p in diff_files]
    errors, error_end = collect_new_errors(
        Path(str(cfg["errorLogDir"])),
        cursor.get("errorCursor") or {"date": None, "offset": 0},
    )
    new_cursor = {
        "diffCursor": diff_files[-1].name if diff_files else cursor.get("diffCursor"),
        "errorCursor": error_end,
    }
    return {"diffs": diffs, "errors": errors}, new_cursor


# ---------------------------------------------------------------- render

def _error_line(fact: dict[str, Any]) -> str:
    """One error entry: `<HH:mm> [phase] errorType: message`, truncated so the
    FINAL rendered line (including the "- " prefix added by the section
    formatter) stays within ERROR_LINE_LIMIT characters."""
    max_len = ERROR_LINE_LIMIT - 2  # reserve space for the "- " prefix
    dt = fact.get("detectedAt")
    line = ""
    if dt:
        try:
            parsed = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
            line = f"{parsed:%H:%M} [{fact.get('phase')}] {fact.get('errorType')}: {fact.get('message')}"
        except ValueError:
            pass
    if not line:
        line = f"[{fact.get('phase')}] {fact.get('errorType')}: {fact.get('message')}"
    return line if len(line) <= max_len else line[:max_len]


def _fmt_section(title: str, items: list[str], unit: str = "个", tick: bool = False, cap: int = SECTION_LIMIT) -> str:
    lines = [f"【{title} {len(items)} {unit}】"]
    for item in items[:cap]:
        lines.append(f"- `{item}`" if tick else f"- {item}")
    if len(items) > cap:
        lines.append(f"…另有 {len(items) - cap} 个，共 {len(items)} 个")
    return "\n".join(lines)


def render_markdown(important_diffs: list[dict[str, Any]], important_errors: list[dict[str, Any]], source_url: str) -> str:
    """Aggregate one round's important facts into the existing markdown template,
    staying under the 20480 UTF-8 byte cap (sections shrink when needed)."""
    timestamp = ""
    all_detected = [f.get("detectedAt") for f in important_diffs + important_errors if f.get("detectedAt")]
    if all_detected:
        newest = str(max(all_detected))
        try:
            timestamp = datetime.fromisoformat(newest.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            timestamp = newest

    added = sorted({name for f in important_diffs for name in f.get("added", [])})
    removed = sorted({name for f in important_diffs for name in f.get("removed", [])})
    error_lines = [_error_line(f) for f in important_errors]

    def build(cap: int) -> str:
        parts = [f"**内网监控告警** {timestamp}" + (f"\n> 来源: {source_url}" if source_url else "")]
        if added:
            parts.append(_fmt_section("新增文件", added, tick=True, cap=cap))
        if removed:
            parts.append(_fmt_section("删除文件", removed, tick=True, cap=cap))
        if error_lines:
            parts.append(_fmt_section("监控错误", error_lines, unit="条", cap=cap))
        return "\n".join(parts)

    for cap in (SECTION_LIMIT, 12, 10, 8, 6, 4, 3, 2, 1):
        body = build(cap)
        if len(body.encode("utf-8")) <= MARKDOWN_LIMIT_BYTES:
            return body
    body = build(0) + "\n…（正文超长，已截断）"
    if len(body.encode("utf-8")) > MARKDOWN_LIMIT_BYTES:
        body = body.encode("utf-8")[:MARKDOWN_LIMIT_BYTES].decode("utf-8", errors="ignore") + "\n…（正文超长，已截断）"
    return body


# ---------------------------------------------------------------- notify log

def write_notify_log(cfg: dict[str, Any], stage: str, fields: dict[str, Any]) -> None:
    log_dir = Path(str(cfg["notifyLogDir"]))
    log_dir.mkdir(parents=True, exist_ok=True)
    record = {"detectedAt": _now().isoformat(), "stage": stage, **fields}
    target = log_dir / f"{_now():%Y-%m-%d}.log"
    with target.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------- round

class RoundOutcome:
    def __init__(self, action: str, *, diffs: int = 0, errors: int = 0, message: str | None = None, error: str = ""):
        self.action = action  # "silent" | "sent" | "dry-run" | "failed"
        self.diffs = diffs
        self.errors = errors
        self.message = message
        self.error = error


def run_round(
    cfg: dict[str, Any],
    engine: RulesEngine,
    cursor: dict[str, Any],
    *,
    dry_run: bool = False,
    push: Callable[[str], None] | None = None,
) -> RoundOutcome:
    """One round: hot-reload rules, collect, evaluate, aggregate, push-or-advance.

    `push` is the tool layer's push_markdown (owns connection, companion
    restore and failure backoff). Cursor file is written on 'silent'/'sent'
    only; 'failed' leaves it untouched so the next round retries the same batch.
    """
    self_error_facts = engine.reload()  # [] or a RulesFileCorrupt fact (matched by current rules)
    facts, end_cursor = collect(cfg, cursor)

    important_diffs: list[dict[str, Any]] = []
    important_errors: list[dict[str, Any]] = []
    for fact in facts["diffs"]:
        important, _ = engine.evaluate_diff(fact)
        if important:
            important_diffs.append(fact)
    for fact in facts["errors"] + self_error_facts:
        important, _ = engine.evaluate_error(fact)
        if important:
            important_errors.append(fact)

    outcome = RoundOutcome(
        "silent",
        diffs=len(facts["diffs"]),
        errors=len(facts["errors"]) + len(self_error_facts),
    )

    if not important_diffs and not important_errors:
        save_cursor(Path(str(cfg["stateFile"])), end_cursor)  # silent advance: nothing worth pushing
        return outcome

    content = render_markdown(important_diffs, important_errors, str(cfg.get("sourceUrl") or ""))
    outcome.message = content
    if dry_run or push is None:
        outcome.action = "dry-run"
        outcome.diffs = len(important_diffs)
        outcome.errors = len(important_errors)
        return outcome

    try:
        push(content)
    except Exception as e:  # send failure, backoff rejection, tool-layer error ...
        outcome.action = "failed"
        outcome.error = f"{type(e).__name__}: {e}"
        outcome.diffs = len(important_diffs)
        outcome.errors = len(important_errors)
        write_notify_log(cfg, "wecom-send", {
            "error": outcome.error,
            "contentDigest": content[:80],
            "pendingDiff": len(facts["diffs"]),
            "pendingErrors": len(facts["errors"]) + len(self_error_facts),
        })
        return outcome  # cursor untouched -> retried per tool-layer backoff

    save_cursor(Path(str(cfg["stateFile"])), end_cursor)
    write_notify_log(cfg, "notify-send", {"contentDigest": content[:80], "pendingDiff": 0, "pendingErrors": 0})
    outcome.action = "sent"
    outcome.diffs = len(important_diffs)
    outcome.errors = len(important_errors)
    return outcome


# ---------------------------------------------------------------- CLI

def _build_push(cfg: dict[str, Any], config_path: Path) -> Callable[[str], None]:
    state_path = Path(str(cfg["botToolStateFile"]))
    return lambda text: bot_tool.push_markdown(text, config_path=config_path, state_path=state_path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("config/notifier.json"))
    p.add_argument("--once", action="store_true", help="run a single round and exit (nonzero on failure)")
    p.add_argument("--interval", type=float, default=None, help="override poll interval seconds")
    p.add_argument("--dry-run", action="store_true", help="render and print only; never connect or advance cursor")
    args = p.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"notifier config error: {e}", file=sys.stderr)
        return 2

    engine = RulesEngine(Path(str(cfg["rulesFile"])))
    interval = args.interval if args.interval is not None else cfg["pollIntervalSeconds"]
    resident = not args.once and not args.dry_run
    lock_owner = None if not resident else acquire_resident_lock(Path(str(cfg["lockFile"])), interval)
    if lock_owner is None and resident:
        print("another notifier instance holds the lock; exiting silently", flush=True)
        return 0

    try:
        while True:
            # settle any unpaid companion-restore debt first (crash insurance);
            # dry-run must stay side-effect free
            if not args.dry_run:
                try:
                    bot_tool.ensure_companion_alive(state_path=Path(str(cfg["botToolStateFile"])))
                except Exception as e:
                    write_notify_log(cfg, "companion-restore", {"error": f"{type(e).__name__}: {e}"})
            cursor = load_cursor(Path(str(cfg["stateFile"])))
            try:
                outcome = run_round(cfg, engine, cursor, dry_run=args.dry_run, push=None if args.dry_run else _build_push(cfg, args.config))
            except Exception as e:
                outcome = RoundOutcome("failed", error=f"{type(e).__name__}: {e}")
                write_notify_log(cfg, "wecom-send", {"error": outcome.error, "contentDigest": "", "pendingDiff": -1, "pendingErrors": -1})
            if outcome.action == "failed":
                print(f"notifier round failed: {outcome.error}", file=sys.stderr, flush=True)
                if args.once:
                    return 1
            elif args.dry_run:
                print("\n--- dry-run: would send the following markdown ---\n", flush=True)
                print(outcome.message or "(no important facts)", flush=True)
                print("\n--- end dry-run (nothing sent, cursor not advanced) ---", flush=True)
                if args.once:
                    return 0
            else:
                print(f"notifier round: action={outcome.action} diffs={outcome.diffs} errors={outcome.errors}", flush=True)
                if args.once:
                    return 0
            if not resident:
                return 0
            if not refresh_resident_lock(Path(str(cfg["lockFile"])), lock_owner):
                print("resident lock lost; exiting", file=sys.stderr, flush=True)
                return 1
            time.sleep(interval)
    finally:
        if lock_owner:
            release_resident_lock(Path(str(cfg["lockFile"])), lock_owner)


if __name__ == "__main__":
    raise SystemExit(main())