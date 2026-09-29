"""Unit tests for src/triage_rules.py: rule mapping, self-healing, escalation."""
import json
from pathlib import Path

import pytest

from src.triage_rules import (DEFAULT_RULES, RulesCorruptError, RulesEngine, load_rules,
    validate_rules)

# Business defaults mirroring the shipped config/triage-rules.json. Tests write
# THIS as the rules file; DEFAULT_RULES is only the minimal self-heal set.
BUSINESS_DEFAULTS = {
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


def _write_rules(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _engine(tmp_path) -> tuple[RulesEngine, Path]:
    rules = tmp_path / "triage-rules.json"
    _write_rules(rules, BUSINESS_DEFAULTS)
    return RulesEngine(rules), rules


def _err_fact(**kw):
    base = {
        "monitorId": "intranet-root",
        "phase": "fetch_page",
        "errorType": "TimeoutError",
        "message": "timed out",
        "retryable": True,
        "statePreserved": True,
        "detectedAt": "2026-09-18T14:56:43+08:00",
    }
    base.update(kw)
    return base


# ---- mapping against the current SKILL.md rules (task 3.1) ----

def test_diff_added_is_important(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    assert engine.evaluate_diff({"monitorId": "intranet-root", "added": ["a.csv"], "removed": []}) == (True, "added")


def test_diff_removed_is_important(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    assert engine.evaluate_diff({"monitorId": "intranet-root", "added": [], "removed": ["a.csv"]})[0] is True


def test_empty_diff_falls_back_to_unmatched_push(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    # default unmatched.diff = "push"
    assert engine.evaluate_diff({"monitorId": "intranet-root", "added": [], "removed": []})[0] is True


def test_pg_validation_error_is_important(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    fact = _err_fact(errorType="PageValidationError", message="page signature failed", retryable=True, statePreserved=True)
    assert engine.evaluate_error(fact)[0] is True


def test_self_error_phases_are_important(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    for phase in ("read_config", "write_state", "write_snapshot_log", "read_rules"):
        fact = _err_fact(phase=phase, errorType="WhateverError")
        assert engine.evaluate_error(fact)[0] is True, phase


def test_isolated_jitter_is_suppressed(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    assert engine.evaluate_error(_err_fact())[0] is False


def test_repeat_jitter_escalates_within_window(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    first = engine.evaluate_error(_err_fact(detectedAt="2026-09-18T14:56:43+08:00"))
    second = engine.evaluate_error(_err_fact(detectedAt="2026-09-18T14:58:43+08:00"))
    third = engine.evaluate_error(_err_fact(detectedAt="2026-09-18T15:00:43+08:00"))
    assert first[0] is False and second[0] is False
    assert third == (True, "escalated-jitter")


def test_escalation_is_per_monitor_and_phase(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    for _ in range(3):
        engine.evaluate_error(_err_fact(detectedAt="2026-09-18T14:56:43+08:00"))
    # different monitorId does not share the counter
    fact = _err_fact(monitorId="other-monitor", detectedAt="2026-09-18T14:56:43+08:00")
    assert engine.evaluate_error(fact)[0] is False


def test_window_prunes_old_entries(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    # two entries long outside the 1800s window, then two inside
    engine.evaluate_error(_err_fact(detectedAt="2026-09-18T01:00:00+08:00"))
    engine.evaluate_error(_err_fact(detectedAt="2026-09-18T01:10:00+08:00"))
    engine.evaluate_error(_err_fact(detectedAt="2026-09-18T15:00:43+08:00"))
    # without pruning there would be 3+ entries; pruning leaves only 2 -> suppressed
    assert engine.evaluate_error(_err_fact(detectedAt="2026-09-18T15:05:43+08:00"))[0] is False


def test_unmatched_error_is_silent_by_default(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    fact = _err_fact(errorType="OddError", phase="some_phase", retryable=False, statePreserved=False)
    assert engine.evaluate_error(fact)[0] is False


def test_unmatched_error_can_be_pushed_via_rules(tmp_path):
    engine, rules = _engine(tmp_path)
    config = json.loads(rules.read_text(encoding="utf-8"))
    config["unmatched"]["error"] = "push"
    _write_rules(rules, config)
    engine.reload()
    fact = _err_fact(errorType="OddError", phase="some_phase", retryable=False, statePreserved=False)
    assert engine.evaluate_error(fact)[0] is True


def test_critical_error_beats_jitter_suppression(tmp_path):
    """PageValidationError with retryable/statePreserved must stay important."""
    engine, _ = _engine(tmp_path)
    engine.reload()
    fact = _err_fact(errorType="PageValidationError", retryable=True, statePreserved=True)
    assert engine.evaluate_error(fact)[0] is True


# ---- self-healing (task 3.2) ----

def test_corrupt_rules_keeps_last_good_and_emits_self_error(tmp_path):
    engine, rules = _engine(tmp_path)
    engine.reload()
    rules.write_text("{ this is not json", encoding="utf-8")
    self_facts = engine.reload()
    assert len(self_facts) == 1
    fact = self_facts[0]
    assert fact["phase"] == "read_rules"
    assert fact["errorType"] == "RulesFileCorrupt"
    # the fact is judged IMPORTANT by the retained rules
    assert engine.evaluate_error(fact)[0] is True
    # normal evaluation still works with last-good
    assert engine.evaluate_diff({"added": ["a.csv"], "removed": []})[0] is True


def test_missing_rules_file_uses_defaults_and_reports(tmp_path):
    engine = RulesEngine(tmp_path / "nope.json")
    self_facts = engine.reload()
    assert len(self_facts) == 1
    assert engine.evaluate_error(self_facts[0])[0] is True
    # minimal defaults carry no business semantics: a normal diff is NOT important
    assert engine.evaluate_diff({"monitorId": "m", "added": ["x.csv"], "removed": []})[0] is False


def test_empty_rules_file_is_corrupt(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text("", encoding="utf-8")
    engine = RulesEngine(path)
    self_facts = engine.reload()
    assert len(self_facts) == 1


def test_schema_validation(tmp_path):
    path = tmp_path / "rules.json"
    engine = RulesEngine(path)
    for bad in (
        {"push": {"diff": {"added": "yes"}}},
        {"push": {"errors": {"errorTypes": "PageValidationError"}}},
        {"unmatched": {"diff": "maybe"}},
        {"push": {"errors": {"repeatEscalation": {"windowSeconds": 0, "threshold": 3}}}},
        [],
    ):
        _write_rules(path, bad)
        self_facts = engine.reload()
        assert len(self_facts) == 1, bad


def test_hot_reload_picks_up_changes_without_restart(tmp_path):
    engine, rules = _engine(tmp_path)
    engine.reload()
    fact = _err_fact(errorType="OddError", phase="p", retryable=False, statePreserved=False)
    assert engine.evaluate_error(fact)[0] is False
    rules.write_text(json.dumps({**BUSINESS_DEFAULTS, "push": {**BUSINESS_DEFAULTS["push"], "errors": {**BUSINESS_DEFAULTS["push"]["errors"], "errorTypes": ["PageValidationError", "OddError"]}}}, ensure_ascii=False), encoding="utf-8")
    engine.reload()
    assert engine.evaluate_error(fact)[0] is True


def test_validate_rules_accepts_shipped_config():
    from pathlib import Path as P

    shipped = P("config") / "triage-rules.json"
    assert shipped.exists(), "shipped rules file must exist"
    data = json.loads(shipped.read_text(encoding="utf-8-sig"))
    validate_rules(data)


# ---- filename suppression (change: ff-config-assistant) ----

def _engine_with_patterns(tmp_path, patterns):
    engine, rules = _engine(tmp_path)
    config = json.loads(rules.read_text(encoding="utf-8"))
    config["suppress"]["filenamePatterns"] = patterns
    _write_rules(rules, config)
    engine.reload()
    return engine


def test_filename_patterns_partially_suppress(tmp_path):
    engine = _engine_with_patterns(tmp_path, ["*tmp*"])
    fact = {"monitorId": "m", "added": ["a-tmp-1.csv", "b.csv"], "removed": []}
    assert engine.evaluate_diff(fact) == (True, "added")
    filtered = engine.filter_diff_fact(fact)
    assert filtered["added"] == ["b.csv"]
    assert filtered["suppressedFilenames"] == 1


def test_filename_patterns_all_suppressed_not_important(tmp_path):
    engine = _engine_with_patterns(tmp_path, ["*tmp*"])
    fact = {"monitorId": "m", "added": ["a-tmp-1.csv"], "removed": []}
    # all names suppressed -> not important, even though unmatched.diff defaults to push
    assert engine.evaluate_diff(fact) == (False, "suppressed-by-pattern")
    assert fact["added"] == ["a-tmp-1.csv"]  # evaluate must not mutate the fact


def test_empty_patterns_leave_fact_untouched(tmp_path):
    engine, _ = _engine(tmp_path)
    engine.reload()
    fact = {"monitorId": "m", "added": ["a-tmp-1.csv"], "removed": []}
    filtered = engine.filter_diff_fact(fact)
    assert filtered["added"] == ["a-tmp-1.csv"]
    assert filtered["suppressedFilenames"] == 0


# ---- unknown-field rejection (change: ff-config-assistant) ----

def test_unknown_fields_make_rules_corrupt(tmp_path):
    engine, rules = _engine(tmp_path)
    engine.reload()
    config = json.loads(rules.read_text(encoding="utf-8"))
    for extra in (
        {"semantic": {"enabled": False}},
        {"push": {"errors": {"consecutiveFetchFailures": 0}}},
    ):
        merged = json.loads(json.dumps(config))
        for key, value in extra.items():
            if isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        _write_rules(rules, merged)
        self_facts = engine.reload()
        assert len(self_facts) == 1, extra
        assert self_facts[0]["errorType"] == "RulesFileCorrupt"


def test_validate_rules_rejects_unknown_keys():
    with pytest.raises(RulesCorruptError):
        validate_rules({**DEFAULT_RULES, "semantic": {"enabled": False}})
    with pytest.raises(RulesCorruptError):
        bad = json.loads(json.dumps(DEFAULT_RULES))
        bad["push"]["errors"]["consecutiveFetchFailures"] = 0
        validate_rules(bad)


# ---- filename include filter (change: config-first-decoupling) ----

def _engine_with_include(tmp_path, include, suppress=None):
    engine, rules = _engine(tmp_path)
    config = json.loads(rules.read_text(encoding="utf-8"))
    config["push"]["diff"]["filenameIncludePatterns"] = include
    if suppress is not None:
        config["suppress"]["filenamePatterns"] = suppress
    _write_rules(rules, config)
    engine.reload()
    return engine


def test_include_keeps_only_matching_names(tmp_path):
    engine = _engine_with_include(tmp_path, ["*103300110002*"])
    fact = {"monitorId": "m", "added": ["a-103300110002.csv", "b.csv"], "removed": []}
    assert engine.evaluate_diff(fact) == (True, "added")
    filtered = engine.filter_diff_fact(fact)
    assert filtered["added"] == ["a-103300110002.csv"]
    assert filtered["suppressedFilenames"] == 1
    assert fact["added"] == ["a-103300110002.csv", "b.csv"]  # evaluate must not mutate


def test_include_filtering_everything_is_not_important(tmp_path):
    engine = _engine_with_include(tmp_path, ["*103300110002*"])
    fact = {"monitorId": "m", "added": ["b.csv"], "removed": []}
    assert engine.evaluate_diff(fact) == (False, "suppressed-by-pattern")


def test_include_empty_keeps_current_behavior(tmp_path):
    engine = _engine_with_include(tmp_path, [])
    fact = {"monitorId": "m", "added": ["b.csv"], "removed": []}
    assert engine.evaluate_diff(fact) == (True, "added")
    filtered = engine.filter_diff_fact(fact)
    assert filtered["added"] == ["b.csv"]
    assert filtered["suppressedFilenames"] == 0


def test_suppress_runs_before_include(tmp_path):
    engine = _engine_with_include(tmp_path, ["*103300110002*"], suppress=["*tmp*"])
    fact = {"monitorId": "m", "added": ["a-tmp-103300110002.csv", "b-103300110002.csv"], "removed": []}
    filtered = engine.filter_diff_fact(fact)
    # suppress drops the tmp name even though it matches the include pattern
    assert filtered["added"] == ["b-103300110002.csv"]
    assert filtered["suppressedFilenames"] == 1


def test_include_patterns_must_be_list_of_str(tmp_path):
    engine, rules = _engine(tmp_path)
    engine.reload()
    config = json.loads(rules.read_text(encoding="utf-8"))
    config["push"]["diff"]["filenameIncludePatterns"] = "*103300110002*"
    _write_rules(rules, config)
    self_facts = engine.reload()
    assert len(self_facts) == 1
    assert self_facts[0]["errorType"] == "RulesFileCorrupt"