"""Unit tests for src/intranet_notifier.py: end-to-end loop in tmp dirs."""
import json
import time
from pathlib import Path

import pytest

from src.intranet_filename_monitor import acquire_resident_lock, release_resident_lock
from src.intranet_notifier import (collect, empty_cursor, load_config, load_cursor, parse_diff_log,
    run_round, save_cursor, write_notify_log)
from src.io import MARKDOWN_LIMIT_BYTES, SECTION_LIMIT, IntranetOutput


# ---------------------------------------------------------------- helpers

def make_cfg(tmp_path: Path, *, chatid="chat-1") -> dict:
    template_file = tmp_path / "notify-template.json"
    template_file.write_text(Path("config/notify-template.json").read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "chatid": chatid,
        "secretsFile": str(tmp_path / "secrets.json"),
        "pollIntervalSeconds": 0.01,
        "diffLogDir": str(tmp_path / "diff"),
        "errorLogDir": str(tmp_path / "error"),
        "notifyLogDir": str(tmp_path / "notify"),
        "stateFile": str(tmp_path / "state.json"),
        "rulesFile": str(tmp_path / "rules.json"),
        "templateFile": str(template_file),
        "lockFile": str(tmp_path / "notifier.lock"),
        "sourceUrl": "http://example.test/",
        "timeouts": {"connect": 1, "ack": 1},
    }


def write_rules(cfg: dict):
    # business rules mirroring the shipped config; DEFAULT_RULES is only the
    # minimal self-heal set and must not leak business semantics into tests
    rules = {
        "push": {
            "diff": {"added": True, "removed": True},
            "errors": {
                "errorTypes": ["PageValidationError"],
                "phases": ["read_config", "write_state", "write_snapshot_log", "read_rules"],
                "repeatEscalation": {"windowSeconds": 1800, "threshold": 3},
            },
        },
        "suppress": {"isolatedRetryableError": True, "filenamePatterns": []},
        "unmatched": {"diff": "push", "error": "silent"},
    }
    Path(cfg["rulesFile"]).write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")


def write_diff(cfg: dict, name: str, added=(), removed=(), monitor="intranet-root", detected="2026-09-18T10:00:00+08:00"):
    d = Path(cfg["diffLogDir"])
    d.mkdir(parents=True, exist_ok=True)
    lines = [f"monitorId: {monitor}", f"detectedAt: {detected}", "", "added:", *(f"- {x}" for x in added), "", "removed:", *(f"- {x}" for x in removed)]
    (d / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_error(cfg: dict, date: str, facts: list[dict]):
    e = Path(cfg["errorLogDir"])
    e.mkdir(parents=True, exist_ok=True)
    with (e / f"{date}.log").open("a", encoding="utf-8", newline="\n") as fh:
        for f in facts:
            fh.write(json.dumps(f, ensure_ascii=False, separators=(",", ":")) + "\n")


def err_fact(**kw):
    base = {
        "eventId": "x1", "detectedAt": "2026-09-18T14:56:43+08:00", "monitorId": "intranet-root",
        "phase": "fetch_page", "errorType": "TimeoutError", "message": "timed out",
        "retryable": True, "statePreserved": True,
    }
    base.update(kw)
    return base


def read_notify_log(cfg: dict) -> str:
    """Notify logs are named by the current date; read the single file written."""
    files = list(Path(cfg["notifyLogDir"]).glob("*.log"))
    assert len(files) == 1
    return files[0].read_text(encoding="utf-8")


def no_notify_log_yet(cfg: dict) -> bool:
    notify_dir = Path(cfg["notifyLogDir"])
    return not notify_dir.exists() or not list(notify_dir.glob("*.log"))


class FakePush:
    """Stands in for bot_tool.push_markdown; outcomes: ("ok", None) | ("fail", exc)."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, content):
        self.calls.append(content)
        result = self.outcomes.pop(0) if self.outcomes else ("ok", None)
        if result[0] == "fail":
            raise result[1]


def build_engine(tmp_path, cfg):
    from src.triage_rules import RulesEngine

    write_rules(cfg)
    return RulesEngine(Path(cfg["rulesFile"]))


# ---------------------------------------------------------------- collect

def test_incremental_diff_consumption(tmp_path):
    cfg = make_cfg(tmp_path)
    write_diff(cfg, "2026-09-18_09-00-00-000.log", added=["a.csv"])
    write_diff(cfg, "2026-09-18_10-00-00-000.log", added=["b.csv"])
    write_diff(cfg, "2026-09-18_11-00-00-000.log", added=["c.csv"])
    cursor = {"diffCursor": "2026-09-18_10-00-00-000.log", "errorCursor": {"date": None, "offset": 0}}
    facts, end = collect(cfg, cursor)
    assert len(facts["diffs"]) == 1
    assert end["diffCursor"] == "2026-09-18_11-00-00-000.log"
    facts, end = collect(cfg, {"diffCursor": "2026-09-18_09-00-00-000.log", "errorCursor": {"date": None, "offset": 0}})
    assert len(facts["diffs"]) == 2
    assert end["diffCursor"] == "2026-09-18_11-00-00-000.log"
    assert [f["added"] for f in facts["diffs"]] == [["b.csv"], ["c.csv"]]


def test_cross_day_error_consumption(tmp_path):
    cfg = make_cfg(tmp_path)
    write_error(cfg, "2026-09-16", [err_fact(), err_fact(), err_fact(), err_fact(), err_fact()])
    write_error(cfg, "2026-09-17", [err_fact(), err_fact()])
    cursor = {"diffCursor": None, "errorCursor": {"date": "2026-09-16", "offset": 3}}
    facts, end = collect(cfg, cursor)
    assert len(facts["errors"]) == 4  # 2 remaining from 09-16 + 2 from 09-17
    assert end["errorCursor"] == {"date": "2026-09-17", "offset": 2}


def test_corrupt_cursor_means_empty(tmp_path):
    cfg = make_cfg(tmp_path)
    write_diff(cfg, "2026-09-18_09-00-00-000.log", added=["a.csv"])
    Path(cfg["stateFile"]).write_text("not json{", encoding="utf-8")
    assert load_cursor(Path(cfg["stateFile"])) == empty_cursor()
    facts, end = collect(cfg, load_cursor(Path(cfg["stateFile"])))
    assert len(facts["diffs"]) == 1


def test_parse_diff_both_formats(tmp_path):
    old = tmp_path / "old.log"
    old.write_text(
        "monitorId: intranet-root\ndetectedAt: 2026-09-17T10:31:02+08:00\n\nchangedFields:\n- root_files: {\"added\": [\"a.csv\"], \"removed\": [\"b.csv\"]}\n",
        encoding="utf-8",
    )
    fact = parse_diff_log(old)
    assert fact["added"] == ["a.csv"] and fact["removed"] == ["b.csv"]
    cfg = make_cfg(tmp_path)
    write_diff(cfg, "new.log", added=["c.csv"], removed=["d.csv"])
    fact2 = parse_diff_log(Path(cfg["diffLogDir"]) / "new.log")
    assert fact2["added"] == ["c.csv"] and fact2["removed"] == ["d.csv"]


# ---------------------------------------------------------------- render

def test_render_template_shape(tmp_path):
    cfg = make_cfg(tmp_path)
    output = IntranetOutput.from_file(Path(cfg["templateFile"]))
    diffs = [{"monitorId": "intranet-root", "detectedAt": "2026-09-18T09:30:00+08:00", "added": ["a.csv", "b.csv"], "removed": []}]
    errors = [{"detectedAt": "2026-09-18T09:31:00+08:00", "phase": "fetch_page", "errorType": "TimeoutError", "message": "x" * 300}]
    body = output.render(diffs, errors, cfg["sourceUrl"])
    assert "**内网监控告警** 2026-09-18 09:31" in body
    assert "> 来源: http://example.test/" in body
    assert "【新增文件 2 个】" in body and "- `a.csv`" in body
    assert "【监控错误 1 条】" in body
    # error line stays within 80 chars
    for line in body.splitlines():
        if line.startswith("- 09:") or line.startswith("- ["):
            assert len(line) <= 80


def test_render_section_truncation_and_dedupe(tmp_path):
    cfg = make_cfg(tmp_path)
    output = IntranetOutput.from_file(Path(cfg["templateFile"]))
    added = [f"file_{i:03d}.csv" for i in range(20)]
    diffs = [{"monitorId": "m", "detectedAt": "2026-09-18T09:00:00+08:00", "added": added, "removed": []}]
    body = output.render(diffs, [], "http://x/")
    assert body.count("- `") <= SECTION_LIMIT
    assert "共 20 个" in body


def test_render_byte_cap(tmp_path):
    cfg = make_cfg(tmp_path)
    output = IntranetOutput.from_file(Path(cfg["templateFile"]))
    added = [f"very_long_filename_{i:04d}_with_padding.csv" for i in range(500)]
    diffs = [{"monitorId": "m", "detectedAt": "2026-09-18T09:00:00+08:00", "added": added, "removed": []}]
    body = output.render(diffs, [], "http://x/")
    assert len(body.encode("utf-8")) <= MARKDOWN_LIMIT_BYTES


def test_custom_template_controls_content_and_order(tmp_path):
    cfg = make_cfg(tmp_path)
    output = IntranetOutput.from_file(Path(cfg["templateFile"]))
    template = output.template
    template["header"] = "自定义告警 {{timestamp}}"
    template["source"] = ""
    template["sections"] = [template["sections"][2], template["sections"][0]]
    template["sections"][1]["title"] = "文件数={{count}}"
    template["sections"][1]["item"] = "+ {{item}}"
    diffs = [{"detectedAt": "2026-09-18T09:30:00+08:00", "added": ["a.csv"], "removed": []}]
    errors = [{"detectedAt": "2026-09-18T09:31:00+08:00", "phase": "fetch", "errorType": "Timeout", "message": "slow"}]
    body = output.render(diffs, errors, cfg["sourceUrl"])
    assert body.index("【监控错误 1 条】") < body.index("文件数=1")
    assert "+ a.csv" in body
    assert "来源" not in body and "**内网监控告警**" not in body


def test_template_rejects_unknown_placeholder(tmp_path):
    cfg = make_cfg(tmp_path)
    template_path = Path(cfg["templateFile"])
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["header"] = "{{unknown}}"
    template_path.write_text(json.dumps(template), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported placeholder"):
        IntranetOutput.from_file(template_path)


# ---------------------------------------------------------------- loop

def test_silent_round_advances_cursor(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    write_error(cfg, "2026-09-18", [err_fact()])  # isolated jitter -> not important
    cursor = load_cursor(Path(cfg["stateFile"]))
    out = run_round(cfg, engine, cursor)  # no client factory -> dry-run/silent path
    assert out.action == "silent"
    saved = json.loads(Path(cfg["stateFile"]).read_text(encoding="utf-8"))
    assert saved["errorCursor"] == {"date": "2026-09-18", "offset": 1}


def test_send_success_advances_cursor_and_writes_log(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    write_diff(cfg, "2026-09-18_09-00-00-000.log", added=["a.csv"])
    write_error(cfg, "2026-09-18", [err_fact(errorType="PageValidationError", retryable=True)])
    push = FakePush([("ok", None)])
    out = run_round(cfg, engine, empty_cursor(), push=push)
    assert out.action == "sent"
    assert len(push.calls) == 1
    saved = json.loads(Path(cfg["stateFile"]).read_text(encoding="utf-8"))
    assert saved["diffCursor"] == "2026-09-18_09-00-00-000.log"
    assert '"stage":"notify-send"' in read_notify_log(cfg)


def test_send_failure_keeps_cursor_and_retries_same_batch(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    write_diff(cfg, "2026-09-18_09-00-00-000.log", added=["a.csv"])
    from src.wecom_bot_client import WecomBotTimeoutError

    push = FakePush([("fail", WecomBotTimeoutError(detail="no ack")), ("ok", None)])
    out1 = run_round(cfg, engine, empty_cursor(), push=push)
    assert out1.action == "failed"
    assert not Path(cfg["stateFile"]).exists()  # cursor untouched (never written)

    out2 = run_round(cfg, engine, load_cursor(Path(cfg["stateFile"])), push=push)
    assert out2.action == "sent"
    assert len(push.calls) == 2
    assert push.calls[0] == push.calls[1]  # identical retried content
    saved = json.loads(Path(cfg["stateFile"]).read_text(encoding="utf-8"))
    assert saved["diffCursor"] == "2026-09-18_09-00-00-000.log"
    notify = read_notify_log(cfg)
    # one failure record + exactly one success record: retry did not duplicate
    assert notify.count('"stage":"notify-send"') == 1
    assert notify.count('"stage":"wecom-send"') == 1


def test_backoff_rejection_counts_as_failed_round(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    write_diff(cfg, "2026-09-18_09-00-00-000.log", added=["a.csv"])
    from src.bot_tool import BotToolBackoffError

    push = FakePush([("fail", BotToolBackoffError("send backoff in effect"))])
    out = run_round(cfg, engine, empty_cursor(), push=push)
    assert out.action == "failed"  # cursor untouched; tool layer retries after backoff
    assert not Path(cfg["stateFile"]).exists()


def test_dry_run_never_connects_or_advances(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    write_diff(cfg, "2026-09-18_09-00-00-000.log", added=["a.csv"])
    called = {"n": 0}

    def boom_push(content):
        called["n"] += 1
        raise AssertionError("dry-run must not push")

    out = run_round(cfg, engine, empty_cursor(), dry_run=True, push=boom_push)
    assert out.action == "dry-run" and out.message is not None
    assert called["n"] == 0
    assert not Path(cfg["stateFile"]).exists()  # cursor never written in dry-run
    assert no_notify_log_yet(cfg)


def test_rules_corruption_round_pushes_self_error_and_advances(tmp_path):
    cfg = make_cfg(tmp_path)
    write_rules(cfg)
    engine = build_engine(tmp_path, cfg)
    Path(cfg["rulesFile"]).write_text("{ broken", encoding="utf-8")
    push = FakePush([("ok", None)])
    out = run_round(cfg, engine, empty_cursor(), push=push)
    assert out.action == "sent"
    assert "规则文件损坏" in out.message or "RulesFileCorrupt" in out.message
    assert push.calls  # the corrupt-rules alert was actually pushed


def test_no_double_push_when_only_unimportant(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    write_error(cfg, "2026-09-18", [err_fact(), err_fact()])  # jitter, below threshold
    push = FakePush([("ok", None)])
    out = run_round(cfg, engine, empty_cursor(), push=push)
    assert out.action == "silent"
    assert not push.calls


# ---------------------------------------------------------------- lock

def test_lock_second_instance_quietly_exits(tmp_path):
    cfg = make_cfg(tmp_path)
    lock = Path(cfg["lockFile"])
    owner1 = acquire_resident_lock(lock, 0.05)
    owner2 = acquire_resident_lock(lock, 0.05)
    assert owner1 is not None and owner2 is None
    release_resident_lock(lock, owner1)
    owner3 = acquire_resident_lock(lock, 0.05)
    assert owner3 is not None


def test_lock_stale_takeover(tmp_path):
    cfg = make_cfg(tmp_path)
    lock = Path(cfg["lockFile"])
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 1, "heartbeat": time.time() - 1000, "owner": "dead"}), encoding="utf-8")
    owner = acquire_resident_lock(lock, 5)
    assert owner is not None
    release_resident_lock(lock, owner)


def test_cursor_roundtrip_atomic(tmp_path):
    cfg = make_cfg(tmp_path)
    cursor = {"diffCursor": "2026-09-18_09-00-00-000.log", "errorCursor": {"date": "2026-09-18", "offset": 7}}
    save_cursor(Path(cfg["stateFile"]), cursor)
    assert load_cursor(Path(cfg["stateFile"])) == cursor


# ---- filename suppression end-to-end (change: ff-config-assistant) ----

def _set_patterns(cfg, patterns):
    rules = json.loads(Path(cfg["rulesFile"]).read_text(encoding="utf-8"))
    rules["suppress"]["filenamePatterns"] = patterns
    Path(cfg["rulesFile"]).write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")


def test_suppressed_names_excluded_from_push_body(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    _set_patterns(cfg, ["*tmp*"])
    write_diff(cfg, "2026-09-18_10-00-00-000.log", added=["a-tmp-1.csv", "b.csv"])
    push = FakePush([("ok", None)])
    out = run_round(cfg, engine, empty_cursor(), push=push)
    assert out.action == "sent"
    body = push.calls[0]
    assert "b.csv" in body
    assert "a-tmp-1.csv" not in body
    assert "已按规则忽略 1 个匹配文件名" in body


def test_fully_suppressed_diff_stays_silent(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    _set_patterns(cfg, ["*tmp*"])
    write_diff(cfg, "2026-09-18_10-00-00-000.log", added=["a-tmp-1.csv"])
    push = FakePush([("ok", None)])
    out = run_round(cfg, engine, empty_cursor(), push=push)
    assert out.action == "silent"
    assert push.calls == []
    # cursor still advanced past the suppressed artifact
    assert load_cursor(Path(cfg["stateFile"]))["diffCursor"] == "2026-09-18_10-00-00-000.log"


def test_missing_errors_section_omits_error_details(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    template_path = Path(cfg["templateFile"])
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["sections"] = [s for s in template["sections"] if s["type"] != "errors"]
    template_path.write_text(json.dumps(template, ensure_ascii=False), encoding="utf-8")
    write_error(cfg, "2026-09-18", [err_fact(errorType="PageValidationError")])
    push = FakePush([("ok", None)])
    out = run_round(cfg, engine, empty_cursor(), push=push)
    assert out.action == "sent"
    assert "监控错误" not in push.calls[0]
    assert "PageValidationError" not in push.calls[0]


def test_template_is_reread_for_each_notification(tmp_path):
    cfg = make_cfg(tmp_path)
    engine = build_engine(tmp_path, cfg)
    write_diff(cfg, "2026-09-18_10-00-00-000.log", added=["a.csv"])
    push = FakePush([("ok", None), ("ok", None)])
    run_round(cfg, engine, empty_cursor(), push=push)

    template_path = Path(cfg["templateFile"])
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["header"] = "更新后的告警 {{timestamp}}"
    template_path.write_text(json.dumps(template, ensure_ascii=False), encoding="utf-8")
    write_diff(cfg, "2026-09-18_11-00-00-000.log", added=["b.csv"])
    run_round(cfg, engine, load_cursor(Path(cfg["stateFile"])), push=push)
    assert push.calls[1].startswith("更新后的告警")
