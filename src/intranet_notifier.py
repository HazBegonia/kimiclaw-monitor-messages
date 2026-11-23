from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src import bot_tool
from src.intranet_filename_monitor import (acquire_resident_lock, refresh_resident_lock,
    release_resident_lock)  # reuse verified lock code; collector file stays untouched
from src.io import ChatLogger, IntranetOutput, Output
from src.triage_rules import RulesEngine

TIME_ZONE = ZoneInfo(os.getenv("TIME_ZONE", "Asia/Shanghai"))

DEFAULTS: dict[str, Any] = {
    "chatid": "",
    "secretsFile": "state/secrets/wecom-bot.json",
    "pollIntervalSeconds": 5,
    "diffLogDir": "logs/intranet-diff",
    "errorLogDir": "logs/intranet-error",
    "notifyLogDir": "logs/intranet-notify",
    "stateFile": "state/notify-state.json",
    "rulesFile": "config/triage-rules.json",
    "templateFile": "config/notify-template.json",
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
    for key in ("diffLogDir", "errorLogDir", "notifyLogDir", "stateFile", "rulesFile", "templateFile", "lockFile", "secretsFile"):
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


# ---------------------------------------------------------------- notify log

def write_notify_log(cfg: dict[str, Any], stage: str, fields: dict[str, Any]) -> None:
    Output.write_jsonl(
        Path(str(cfg["notifyLogDir"])),
        {"stage": stage, **fields},
        now=_now(),
        time_field="detectedAt",
    )


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
        important, _ = engine.evaluate_diff(fact)  # judges the RAW fact (suppression-aware)
        if important:
            important_diffs.append(engine.filter_diff_fact(fact))  # render without suppressed names
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

    content = IntranetOutput.from_file(Path(str(cfg["templateFile"]))).render(
        important_diffs, important_errors, str(cfg.get("sourceUrl") or "")
    )
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
        Output.emit_text(f"notifier config error: {e}", error=True)
        return 2

    engine = RulesEngine(Path(str(cfg["rulesFile"])))
    interval = args.interval if args.interval is not None else cfg["pollIntervalSeconds"]
    resident = not args.once and not args.dry_run
    lock_owner = None if not resident else acquire_resident_lock(Path(str(cfg["lockFile"])), interval)
    if lock_owner is None and resident:
        Output.emit_text("another notifier instance holds the lock; exiting silently")
        return 0

    try:
        while True:
            # settle any unpaid companion-restore debt first (crash insurance);
            # dry-run must stay side-effect free
            if not args.dry_run:
                try:
                    added = ChatLogger().sync()
                    if added:
                        Output.emit_text(f"chat log: added {added} record(s)")
                except Exception as e:
                    write_notify_log(cfg, "chat-log", {"error": f"{type(e).__name__}: {e}"})
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
                Output.emit_text(f"notifier round failed: {outcome.error}", error=True)
                if args.once:
                    return 1
            elif args.dry_run:
                Output.emit_text("\n--- dry-run: would send the following markdown ---\n")
                Output.emit_text(outcome.message or "(no important facts)")
                Output.emit_text("\n--- end dry-run (nothing sent, cursor not advanced) ---")
                if args.once:
                    return 0
            else:
                Output.emit_text(f"notifier round: action={outcome.action} diffs={outcome.diffs} errors={outcome.errors}")
                if args.once:
                    return 0
            if not resident:
                return 0
            if not refresh_resident_lock(Path(str(cfg["lockFile"])), lock_owner):
                Output.emit_text("resident lock lost; exiting", error=True)
                return 1
            time.sleep(interval)
    finally:
        if lock_owner:
            release_resident_lock(Path(str(cfg["lockFile"])), lock_owner)


if __name__ == "__main__":
    raise SystemExit(main())