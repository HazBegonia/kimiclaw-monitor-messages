"""Unit tests for src/bot_tool.py: push orchestration, companion restore,
debt ledger, send backoff. wecom client and openclaw CLI are mocked out."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import bot_tool
from src.bot_tool import (BotToolBackoffError, BotToolError, ensure_companion_alive,
    load_ledger, push_markdown, save_ledger)
from src.wecom_bot_client import WecomBotTimeoutError


# ---------------------------------------------------------------- helpers

def make_config(tmp_path: Path, *, chatid="chat-1") -> Path:
    cfg = tmp_path / "notifier.json"
    cfg.write_text(json.dumps({
        "chatid": chatid,
        "secretsFile": str(tmp_path / "secrets.json"),
        "timeouts": {"connect": 1, "ack": 1},
    }), encoding="utf-8")
    (tmp_path / "secrets.json").write_text(json.dumps({"botId": "b1", "secret": "s1"}), encoding="utf-8")
    return cfg


class FakeClient:
    """Stands in for WecomBotClient; outcomes: ("ok", None) | ("fail", exc)."""

    def __init__(self, outcomes=(), on_send=None):
        self.outcomes = list(outcomes)
        self.calls = []
        self.on_send = on_send

    def send_markdown(self, chatid, content):
        self.calls.append((chatid, content))
        if self.on_send:
            self.on_send()
        result = self.outcomes.pop(0) if self.outcomes else ("ok", None)
        if result[0] == "fail":
            raise result[1]
        return {"errcode": 0}


class FakeRun:
    """Stands in for subprocess.run; records argv, returns/raises per script."""

    def __init__(self, results=(), on_call=None):
        self.results = list(results)
        self.on_call = on_call
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.on_call:
            self.on_call()
        result = self.results.pop(0) if self.results else SimpleNamespace(returncode=0)
        if isinstance(result, BaseException):
            raise result
        return result


def make_now(start=1_000_000.0):
    box = {"t": start}
    return lambda: box["t"], box


def make_paths(tmp_path: Path):
    return make_config(tmp_path), tmp_path / "bot-tool-state.json"


# ---------------------------------------------------------------- push flow

def test_push_full_flow_sends_then_restores_and_clears(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, _ = make_now()
    events = []
    client = FakeClient(on_send=lambda: events.append("send"))
    run = FakeRun(on_call=lambda: events.append("cli"))

    push_markdown("**hi**", config_path=config_path, state_path=state_path,
                  client_factory=lambda: client, cli_resolve=lambda n: "/fake/openclaw.cmd",
                  cli_run=run, now=now)

    assert client.calls == [("chat-1", "**hi**")]
    # toggle sequence: false then true, resolved executable, explicit timeout
    assert [c[0][1:] for c in run.calls] == [
        ["config", "set", "channels.wecom.enabled", "--json", "false"],
        ["config", "set", "channels.wecom.enabled", "--json", "true"],
    ]
    assert all(c[0][0] == "/fake/openclaw.cmd" for c in run.calls)
    assert all(c[1].get("timeout") == bot_tool.CLI_TIMEOUT_SECONDS for c in run.calls)
    assert events == ["send", "cli", "cli"]  # restore strictly after the send
    # ledger settled: no debt, backoff zeroed
    assert load_ledger(state_path) == {"pendingRestore": None, "sendBackoff": {"failCount": 0, "nextRetryAt": None}}


def test_push_writes_debt_before_connecting(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, _ = make_now()

    def during_send():
        debt = load_ledger(state_path)["pendingRestore"]
        assert debt is not None and debt["dueAt"] > now()

    client = FakeClient(on_send=during_send)
    push_markdown("x", config_path=config_path, state_path=state_path,
                  client_factory=lambda: client, cli_run=FakeRun(), now=now)


def test_send_failure_still_restores_and_backs_off(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, _ = make_now()
    client = FakeClient([("fail", WecomBotTimeoutError(detail="no ack"))])
    run = FakeRun()

    with pytest.raises(WecomBotTimeoutError):
        push_markdown("x", config_path=config_path, state_path=state_path,
                      client_factory=lambda: client, cli_run=run, now=now)

    assert len(run.calls) == 2  # restore attempted despite the failed send
    ledger = load_ledger(state_path)
    assert ledger["pendingRestore"] is None  # restore succeeded -> debt cleared
    assert ledger["sendBackoff"]["failCount"] == 1
    assert ledger["sendBackoff"]["nextRetryAt"] == pytest.approx(1_000_005.0)


def test_push_rejects_while_backoff_pending(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, _ = make_now()
    save_ledger(state_path, {"pendingRestore": None, "sendBackoff": {"failCount": 2, "nextRetryAt": 1_000_100.0}})
    client = FakeClient()
    run = FakeRun()

    with pytest.raises(BotToolBackoffError):
        push_markdown("x", config_path=config_path, state_path=state_path,
                      client_factory=lambda: client, cli_run=run, now=now)
    assert not client.calls  # never connected
    assert not run.calls  # nothing kicked -> nothing to restore
    assert load_ledger(state_path)["sendBackoff"]["failCount"] == 2  # unchanged


def test_backoff_progression_and_reset_on_success(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, clock = make_now()
    client = FakeClient([("fail", WecomBotTimeoutError(detail="t"))] * 3 + [("ok", None)])

    def attempt():
        push_markdown("x", config_path=config_path, state_path=state_path,
                      client_factory=lambda: client, cli_run=FakeRun(), now=now)

    with pytest.raises(WecomBotTimeoutError):
        attempt()
    assert load_ledger(state_path)["sendBackoff"]["nextRetryAt"] == pytest.approx(1_000_005.0)  # +5s
    clock["t"] += 5
    with pytest.raises(WecomBotTimeoutError):
        attempt()
    assert load_ledger(state_path)["sendBackoff"]["nextRetryAt"] == pytest.approx(1_000_035.0)  # +30s
    clock["t"] += 30
    with pytest.raises(WecomBotTimeoutError):
        attempt()
    assert load_ledger(state_path)["sendBackoff"]["nextRetryAt"] == pytest.approx(1_000_335.0)  # +300s cap
    clock["t"] += 300
    attempt()  # succeeds
    assert load_ledger(state_path)["sendBackoff"] == {"failCount": 0, "nextRetryAt": None}
    attempt()  # no backoff delay after reset
    assert len(client.calls) == 5


def test_backoff_survives_process_restart(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, _ = make_now()
    client = FakeClient([("fail", WecomBotTimeoutError(detail="t"))])
    with pytest.raises(WecomBotTimeoutError):
        push_markdown("x", config_path=config_path, state_path=state_path,
                      client_factory=lambda: client, cli_run=FakeRun(), now=now)
    # "restart": fresh call, state only from the ledger file
    with pytest.raises(BotToolBackoffError):
        push_markdown("x", config_path=config_path, state_path=state_path,
                      client_factory=lambda: FakeClient(), cli_run=FakeRun(), now=now)


# ---------------------------------------------------------------- restore debt

def test_ensure_companion_alive_settles_due_debt(tmp_path):
    _, state_path = make_paths(tmp_path)
    now, _ = make_now()
    save_ledger(state_path, {"pendingRestore": {"kickedAt": "2026-09-19T10:00:00+08:00", "dueAt": 999_990.0},
                             "sendBackoff": {"failCount": 0, "nextRetryAt": None}})
    run = FakeRun()
    ensure_companion_alive(state_path=state_path, cli_run=run, now=now)
    assert len(run.calls) == 2
    assert load_ledger(state_path)["pendingRestore"] is None


def test_ensure_companion_alive_no_debt_is_noop(tmp_path):
    _, state_path = make_paths(tmp_path)
    now, _ = make_now()
    run = FakeRun()
    ensure_companion_alive(state_path=state_path, cli_run=run, now=now)  # no ledger file at all
    assert not run.calls


def test_ensure_companion_alive_ignores_debt_not_yet_due(tmp_path):
    _, state_path = make_paths(tmp_path)
    now, _ = make_now()
    save_ledger(state_path, {"pendingRestore": {"kickedAt": "2026-09-19T10:00:00+08:00", "dueAt": 1_000_003.0},
                             "sendBackoff": {"failCount": 0, "nextRetryAt": None}})
    run = FakeRun()
    ensure_companion_alive(state_path=state_path, cli_run=run, now=now)
    assert not run.calls
    assert load_ledger(state_path)["pendingRestore"] is not None  # debt kept


def test_cli_failure_keeps_debt_and_does_not_raise(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, _ = make_now()
    client = FakeClient()  # send itself succeeds
    failing = FakeRun([SimpleNamespace(returncode=1), subprocess.TimeoutExpired(cmd="openclaw", timeout=60)])

    push_markdown("x", config_path=config_path, state_path=state_path,
                  client_factory=lambda: client, cli_run=failing, now=now)  # must not raise

    debt = load_ledger(state_path)["pendingRestore"]
    assert debt is not None  # unpaid debt persisted
    # a later round with a healthy CLI settles it
    run = FakeRun()
    ensure_companion_alive(state_path=state_path, cli_run=run, now=lambda: debt["dueAt"] + 1)
    assert len(run.calls) == 2
    assert load_ledger(state_path)["pendingRestore"] is None


def test_cli_missing_keeps_debt(tmp_path):
    _, state_path = make_paths(tmp_path)
    now, _ = make_now()
    save_ledger(state_path, {"pendingRestore": {"kickedAt": "2026-09-19T10:00:00+08:00", "dueAt": 0.0},
                             "sendBackoff": {"failCount": 0, "nextRetryAt": None}})
    # CLI not installed / not spawnable: both writes fail with OSError
    failing = FakeRun([FileNotFoundError("openclaw.cmd"), FileNotFoundError("openclaw.cmd")])
    ensure_companion_alive(state_path=state_path, cli_resolve=lambda n: None, cli_run=failing, now=now)
    assert len(failing.calls) == 2
    assert load_ledger(state_path)["pendingRestore"] is not None  # debt kept, no exception


# ---------------------------------------------------------------- ledger healing

def test_corrupt_ledger_is_empty_and_self_heals(tmp_path):
    config_path, state_path = make_paths(tmp_path)
    now, _ = make_now()
    state_path.write_text("not json{", encoding="utf-8")
    assert load_ledger(state_path) == {"pendingRestore": None, "sendBackoff": {"failCount": 0, "nextRetryAt": None}}
    run = FakeRun()
    ensure_companion_alive(state_path=state_path, cli_run=run, now=now)
    assert not run.calls  # empty ledger -> no-op
    client = FakeClient()
    push_markdown("x", config_path=config_path, state_path=state_path,
                  client_factory=lambda: client, cli_run=run, now=now)
    healed = json.loads(state_path.read_text(encoding="utf-8"))
    assert healed == {"pendingRestore": None, "sendBackoff": {"failCount": 0, "nextRetryAt": None}}


def test_garbage_debt_fields_dropped(tmp_path):
    _, state_path = make_paths(tmp_path)
    state_path.write_text(json.dumps({
        "pendingRestore": {"kickedAt": 123, "dueAt": "soon"},  # wrong types
        "sendBackoff": {"failCount": -1, "nextRetryAt": "x"},
    }), encoding="utf-8")
    assert load_ledger(state_path) == {"pendingRestore": None, "sendBackoff": {"failCount": 0, "nextRetryAt": None}}


def test_dump_inbox_reserved_noop():
    assert bot_tool.dump_inbox() is None


def test_bad_config_raises_tool_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"chatid": ""}), encoding="utf-8")
    with pytest.raises(BotToolError):
        push_markdown("x", config_path=bad, state_path=tmp_path / "s.json",
                      client_factory=lambda: FakeClient(), cli_run=FakeRun())
