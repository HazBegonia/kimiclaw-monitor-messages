"""Deterministic importance rules engine for the intranet notifier.

The engine reads `config/triage-rules.json` every round (hot reload: edits take
effect on the next round without restarting), validates it, and evaluates
structured facts (diff / error) into push decisions. No LLM anywhere.

Rule file self-healing (design D5): when the rules file is missing, un-parseable
or schema-invalid, the engine keeps using the last successfully loaded rules and
emits a `RulesFileCorrupt` self-error fact. The default rules (and the shipped
config, which lists `read_rules` in push.errors.phases) match that fact, so the
group receives a "rule file corrupt" alert instead of silent failure. With no
last-good at all (first ever run), built-in defaults are used — which also
classify the self-error fact as important.

Precedence for error facts (mirrors skills/intranet-message-triage/SKILL.md):
  1. errorType in push.errors.errorTypes OR phase in push.errors.phases
     -> IMPORTANT (monitor-self errors are never suppressed as jitter)
  2. suppress.isolatedRetryableError and retryable and statePreserved
     -> jitter: NOT important, UNLESS this (monitorId, phase) hit the
        repeatEscalation window & threshold -> IMPORTANT
  3. otherwise -> unmatched.error (default "silent" -> not important)

Reserved fields parsed but NOT evaluated in v1:
  - push.errors.consecutiveFetchFailures
  - suppress.filenamePatterns
  - semantic
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

RULES_FILENAME = "config/triage-rules.json"

# Built-in defaults used only when no last-good rules exist yet.
DEFAULT_RULES: dict[str, Any] = {
    "push": {
        "diff": {"added": True, "removed": True},
        "errors": {
            "errorTypes": ["PageValidationError"],
            "phases": ["read_config", "write_state", "write_snapshot_log", "read_rules"],
            "consecutiveFetchFailures": 0,
            "repeatEscalation": {"windowSeconds": 1800, "threshold": 3},
        },
    },
    "suppress": {"isolatedRetryableError": True, "filenamePatterns": []},
    "unmatched": {"diff": "push", "error": "silent"},
    "semantic": {"enabled": False},
}

SELF_ERROR_FACT = "RulesFileCorrupt"


class RulesCorruptError(ValueError):
    """Raised when the rules file cannot be used (missing/bad JSON/bad schema)."""


def _expect_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise RulesCorruptError(f"{path} must be a boolean, got {type(value).__name__}")
    return value


def _expect_non_negative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RulesCorruptError(f"{path} must be a non-negative integer")
    return value


def _expect_list_of_str(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise RulesCorruptError(f"{path} must be an array of strings")
    return list(value)


def validate_rules(data: Any) -> dict[str, Any]:
    """Validate the parsed rules structure; raise RulesCorruptError on failure."""
    if not isinstance(data, dict):
        raise RulesCorruptError("rules root must be an object")
    push = data.get("push")
    if not isinstance(push, dict):
        raise RulesCorruptError("rules.push must be an object")
    pdiff = push.get("diff")
    if not isinstance(pdiff, dict):
        raise RulesCorruptError("rules.push.diff must be an object")
    _expect_bool(pdiff.get("added"), "push.diff.added")
    _expect_bool(pdiff.get("removed"), "push.diff.removed")
    perr = push.get("errors")
    if not isinstance(perr, dict):
        raise RulesCorruptError("rules.push.errors must be an object")
    _expect_list_of_str(perr.get("errorTypes"), "push.errors.errorTypes")
    _expect_list_of_str(perr.get("phases"), "push.errors.phases")
    if perr.get("consecutiveFetchFailures") is not None:
        _expect_non_negative_int(perr.get("consecutiveFetchFailures"), "push.errors.consecutiveFetchFailures")
    esc = perr.get("repeatEscalation")
    if not isinstance(esc, dict):
        raise RulesCorruptError("rules.push.errors.repeatEscalation must be an object")
    window = _expect_non_negative_int(esc.get("windowSeconds", 1800), "repeatEscalation.windowSeconds")
    threshold = _expect_non_negative_int(esc.get("threshold", 3), "repeatEscalation.threshold")
    if window <= 0 or threshold <= 0:
        raise RulesCorruptError("repeatEscalation.windowSeconds/threshold must be positive")
    sup = data.get("suppress")
    if not isinstance(sup, dict):
        raise RulesCorruptError("rules.suppress must be an object")
    if sup.get("isolatedRetryableError") is not None:
        _expect_bool(sup.get("isolatedRetryableError"), "suppress.isolatedRetryableError")
    if sup.get("filenamePatterns") is not None:
        _expect_list_of_str(sup.get("filenamePatterns"), "suppress.filenamePatterns")
    unmatched = data.get("unmatched")
    if not isinstance(unmatched, dict):
        raise RulesCorruptError("rules.unmatched must be an object")
    for key, allowed in (("diff", ("push", "silent")), ("error", ("push", "silent"))):
        val = unmatched.get(key, "silent")
        if val not in allowed:
            raise RulesCorruptError(f"rules.unmatched.{key} must be one of {allowed}")
    return data


def load_rules(path: Path) -> dict[str, Any]:
    """Parse and validate the rules file; raise RulesCorruptError on any issue."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RulesCorruptError(f"invalid JSON: {e}") from e
    return validate_rules(data)


class RulesEngine:
    """Hot-reloading rules evaluator with last-good fallback and jitter counters."""

    def __init__(self, rules_path: Path, *, now: Optional[float] = None):
        self._path = rules_path
        self._last_good: dict[str, Any] = DEFAULT_RULES
        self._loaded_once = False
        self._window_counts: dict[tuple[str, str], list[float]] = {}
        self._now = now  # test hook; None => time.time()

    # ---- reload / self-heal ----

    def reload(self) -> list[dict[str, Any]]:
        """Read and validate the rules file.

        Returns a list of self-error facts (empty when the file is fine).
        On failure keeps the last good rules and returns one RulesFileCorrupt
        fact with phase "read_rules" (matched as important by the shipped rules).
        """
        try:
            self._last_good = load_rules(self._path)
            self._loaded_once = True
            return []
        except (RulesCorruptError, OSError, UnicodeDecodeError) as e:
            fact = {
                "eventId": SELF_ERROR_FACT,
                "detectedAt": self._iso_now(),
                "monitorId": "notifier-self",
                "phase": "read_rules",
                "errorType": SELF_ERROR_FACT,
                "message": f"triage rules file corrupt: {e}",
                "retryable": False,
                "statePreserved": False,
                "path": str(self._path),
            }
            return [fact]

    # ---- fact evaluation ----

    def _now_ts(self) -> float:
        return time.time() if self._now is None else self._now

    def _iso_now(self) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

    def evaluate_diff(self, fact: dict[str, Any]) -> tuple[bool, str]:
        """fact: {monitorId, detectedAt, added:[str], removed:[str]}"""
        rules = self._last_good
        added = fact.get("added") or []
        removed = fact.get("removed") or []
        suppress_patterns = rules.get("suppress", {}).get("filenamePatterns") or []
        important = False
        reason = "unmatched"
        # Reserved in v1: filenamePatterns suppression is parsed but not applied.
        if added and rules.get("push", {}).get("diff", {}).get("added"):
            important, reason = True, "added"
        elif removed and rules.get("push", {}).get("diff", {}).get("removed"):
            important, reason = True, "removed"
        elif not added and not removed and rules.get("unmatched", {}).get("diff", "push") == "push":
            important, reason = True, "unmatched-diff"
        return important, reason

    def evaluate_error(self, fact: dict[str, Any]) -> tuple[bool, str]:
        """fact: {monitorId, phase, errorType, message, retryable, statePreserved,
        (detectedAt|detected_at)}"""
        rules = self._last_good
        err_cfg = rules.get("push", {}).get("errors", {})
        monitor_id = str(fact.get("monitorId") or "")
        phase = str(fact.get("phase") or "")
        error_type = str(fact.get("errorType") or "")
        retryable = bool(fact.get("retryable"))
        state_preserved = bool(fact.get("statePreserved"))

        # 1. monitor-self errors always important
        if error_type in err_cfg.get("errorTypes", []) or phase in err_cfg.get("phases", []):
            return True, "error-match"

        # 2. isolated retryable jitter suppression with window escalation
        suppress = rules.get("suppress", {}).get("isolatedRetryableError", True)
        if suppress and retryable and state_preserved:
            esc = err_cfg.get("repeatEscalation", {})
            window = esc.get("windowSeconds", 1800)
            threshold = esc.get("threshold", 3)
            ts = self._fact_ts(fact)
            key = (monitor_id, phase)
            bucket = self._window_counts.setdefault(key, [])
            bucket.append(ts)
            bucket[:] = [t for t in bucket if t >= ts - window]
            if len(bucket) >= threshold:
                return True, "escalated-jitter"
            return False, "isolated-jitter"

        # 3. unmatched fallback
        if rules.get("unmatched", {}).get("error", "silent") == "push":
            return True, "unmatched-error"
        return False, "unmatched-error-silent"

    def _fact_ts(self, fact: dict[str, Any]) -> float:
        detected = fact.get("detectedAt") or fact.get("detected_at")
        if detected:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(str(detected))
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        return self._now_ts()