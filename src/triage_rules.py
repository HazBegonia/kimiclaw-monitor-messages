"""Deterministic importance rules engine for the intranet notifier.

The engine reads `config/triage-rules.json` every round (hot reload: edits take
effect on the next round without restarting), validates it, and evaluates
structured facts (diff / error) into push decisions. No LLM anywhere.

Rule file self-healing (design D5): when the rules file is missing, un-parseable
or schema-invalid, the engine keeps using the last successfully loaded rules and
emits a `RulesFileCorrupt` self-error fact. The default rules (and the shipped
config, which lists `read_rules` in push.errors.phases) match that fact, so the
group receives a "rule file corrupt" alert instead of silent failure. With no
last-good at all (first ever run), built-in defaults are used — a minimal
self-heal set whose only job is to classify the self-error fact as important;
business defaults live solely in the shipped config file, not in this module.

Precedence for error facts (mirrors the importance rules):
  1. errorType in push.errors.errorTypes OR phase in push.errors.phases
     -> IMPORTANT (monitor-self errors are never suppressed as jitter)
  2. suppress.isolatedRetryableError and retryable and statePreserved
     -> jitter: NOT important, UNLESS this (monitorId, phase) hit the
        repeatEscalation window & threshold -> IMPORTANT
  3. otherwise -> unmatched.error (default "silent" -> not important)

Diff filename filtering runs BEFORE judging, suppression first then inclusion:
names matching any `suppress.filenamePatterns` fnmatch pattern are removed from
added/removed; then, when `push.diff.filenameIncludePatterns` is non-empty,
names NOT matching any include pattern are removed as well. A diff whose lists
both become empty is NOT important. The notifier filters facts through
`filter_diff_fact` before rendering so pushed bodies never list filtered names
(the body notes the combined filtered count).

Unknown-field rejection: any key outside the agreed schema makes the rules
file corrupt (self-heal + group alert), so a field cannot LOOK configurable
while doing nothing.
"""
from __future__ import annotations

import fnmatch
import json
import time
from pathlib import Path
from typing import Any, Optional

RULES_FILENAME = "config/triage-rules.json"

# Built-in defaults used only when no last-good rules exist yet. Minimal
# self-heal set: its only job is to judge the RulesFileCorrupt self-error fact
# important so the group gets alerted. Business defaults live solely in the
# shipped config/triage-rules.json — keep this set free of business semantics.
DEFAULT_RULES: dict[str, Any] = {
    "push": {
        "diff": {"added": False, "removed": False},
        "errors": {
            "errorTypes": ["RulesFileCorrupt"],
            "phases": ["read_rules"],
            "repeatEscalation": {"windowSeconds": 1800, "threshold": 3},
        },
    },
    "suppress": {"isolatedRetryableError": True, "filenamePatterns": []},
    "unmatched": {"diff": "silent", "error": "silent"},
}

SELF_ERROR_FACT = "RulesFileCorrupt"

# Agreed schema: any key outside these sets makes the rules file corrupt.
_ALLOWED_KEYS: dict[tuple[str, ...], set[str]] = {
    (): {"push", "suppress", "unmatched"},
    ("push",): {"diff", "errors"},
    ("push", "diff"): {"added", "removed", "filenameIncludePatterns"},
    ("push", "errors"): {"errorTypes", "phases", "repeatEscalation"},
    ("push", "errors", "repeatEscalation"): {"windowSeconds", "threshold"},
    ("suppress",): {"isolatedRetryableError", "filenamePatterns"},
    ("unmatched",): {"diff", "error"},
}


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


def _reject_unknown_keys(obj: dict[str, Any], path: tuple[str, ...]) -> None:
    allowed = _ALLOWED_KEYS[path]
    unknown = sorted(set(obj) - allowed)
    if unknown:
        where = ".".join(path) or "rules"
        raise RulesCorruptError(f"{where} has unknown keys: {unknown}")


def validate_rules(data: Any) -> dict[str, Any]:
    """Validate the parsed rules structure; raise RulesCorruptError on failure."""
    if not isinstance(data, dict):
        raise RulesCorruptError("rules root must be an object")
    _reject_unknown_keys(data, ())
    push = data.get("push")
    if not isinstance(push, dict):
        raise RulesCorruptError("rules.push must be an object")
    _reject_unknown_keys(push, ("push",))
    pdiff = push.get("diff")
    if not isinstance(pdiff, dict):
        raise RulesCorruptError("rules.push.diff must be an object")
    _reject_unknown_keys(pdiff, ("push", "diff"))
    _expect_bool(pdiff.get("added"), "push.diff.added")
    _expect_bool(pdiff.get("removed"), "push.diff.removed")
    if pdiff.get("filenameIncludePatterns") is not None:
        _expect_list_of_str(pdiff.get("filenameIncludePatterns"), "push.diff.filenameIncludePatterns")
    perr = push.get("errors")
    if not isinstance(perr, dict):
        raise RulesCorruptError("rules.push.errors must be an object")
    _reject_unknown_keys(perr, ("push", "errors"))
    _expect_list_of_str(perr.get("errorTypes"), "push.errors.errorTypes")
    _expect_list_of_str(perr.get("phases"), "push.errors.phases")
    esc = perr.get("repeatEscalation")
    if not isinstance(esc, dict):
        raise RulesCorruptError("rules.push.errors.repeatEscalation must be an object")
    _reject_unknown_keys(esc, ("push", "errors", "repeatEscalation"))
    window = _expect_non_negative_int(esc.get("windowSeconds", 1800), "repeatEscalation.windowSeconds")
    threshold = _expect_non_negative_int(esc.get("threshold", 3), "repeatEscalation.threshold")
    if window <= 0 or threshold <= 0:
        raise RulesCorruptError("repeatEscalation.windowSeconds/threshold must be positive")
    sup = data.get("suppress")
    if not isinstance(sup, dict):
        raise RulesCorruptError("rules.suppress must be an object")
    _reject_unknown_keys(sup, ("suppress",))
    if sup.get("isolatedRetryableError") is not None:
        _expect_bool(sup.get("isolatedRetryableError"), "suppress.isolatedRetryableError")
    if sup.get("filenamePatterns") is not None:
        _expect_list_of_str(sup.get("filenamePatterns"), "suppress.filenamePatterns")
    unmatched = data.get("unmatched")
    if not isinstance(unmatched, dict):
        raise RulesCorruptError("rules.unmatched must be an object")
    _reject_unknown_keys(unmatched, ("unmatched",))
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

    def _patterns(self) -> list[str]:
        return self._last_good.get("suppress", {}).get("filenamePatterns") or []

    def _include_patterns(self) -> list[str]:
        return self._last_good.get("push", {}).get("diff", {}).get("filenameIncludePatterns") or []

    @staticmethod
    def _suppress(names: list[str], patterns: list[str]) -> tuple[list[str], int]:
        kept = [n for n in names if not any(fnmatch.fnmatch(n, p) for p in patterns)]
        return kept, len(names) - len(kept)

    @staticmethod
    def _include(names: list[str], patterns: list[str]) -> tuple[list[str], int]:
        """Keep only names matching an include pattern; empty patterns keep all."""
        if not patterns:
            return names, 0
        kept = [n for n in names if any(fnmatch.fnmatch(n, p) for p in patterns)]
        return kept, len(names) - len(kept)

    def filter_diff_fact(self, fact: dict[str, Any]) -> dict[str, Any]:
        """Copy of the diff fact with suppressed/include-filtered names removed.

        The notifier applies this before judging/rendering so pushed bodies
        never list filtered names; `suppressedFilenames` records the combined
        count of suppress-dropped and include-dropped names.
        """
        added, dropped_a = self._suppress(list(fact.get("added") or []), self._patterns())
        removed, dropped_r = self._suppress(list(fact.get("removed") or []), self._patterns())
        added, excl_a = self._include(added, self._include_patterns())
        removed, excl_r = self._include(removed, self._include_patterns())
        out = dict(fact)
        out["added"], out["removed"] = added, removed
        out["suppressedFilenames"] = (
            int(fact.get("suppressedFilenames") or 0) + dropped_a + dropped_r + excl_a + excl_r
        )
        return out

    def _now_ts(self) -> float:
        return time.time() if self._now is None else self._now

    def _iso_now(self) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

    def evaluate_diff(self, fact: dict[str, Any]) -> tuple[bool, str]:
        """fact: {monitorId, detectedAt, added:[str], removed:[str]}"""
        rules = self._last_good
        raw_added = list(fact.get("added") or [])
        raw_removed = list(fact.get("removed") or [])
        added, _ = self._suppress(raw_added, self._patterns())
        removed, _ = self._suppress(raw_removed, self._patterns())
        added, _ = self._include(added, self._include_patterns())
        removed, _ = self._include(removed, self._include_patterns())
        if not added and not removed and (raw_added or raw_removed):
            return False, "suppressed-by-pattern"
        important = False
        reason = "unmatched"
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