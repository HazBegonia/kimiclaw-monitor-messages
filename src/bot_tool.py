"""WeCom bot tool layer (facade) for the shared FF long connection.

change: share-ff-bot-connection. One FF botId is time-shared between this
layer (on-demand short-lived push connection) and Claw's wecom plugin
(resident @-message receiver). The server allows exactly one live connection
per botId (a new connection kicks the old one), and the plugin deliberately
never reconnects after being kicked — so this layer owns the whole
"give the line back" choreography:

  - push_markdown(text): connect (wecom_bot_client) -> send -> disconnect ->
    immediately revive Claw via `openclaw config set channels.wecom.enabled`
    false -> true (config edit triggers the gateway's channel hot-reload)
  - debt ledger state/bot-tool-state.json: pendingRestore {kickedAt, dueAt} is
    written BEFORE connecting and cleared only after a successful revive, so a
    crashed push process cannot leave the companion permanently offline;
    ensure_companion_alive() settles due debts from the resident loop
  - send backoff sendBackoff {failCount, nextRetryAt}: 5s -> 30s -> 5m capped,
    persisted, cleared on success; push_markdown refuses to connect while a
    backoff is still pending (kick-storm protection)

Credentials and chatid are read by this layer itself
(state/secrets/wecom-bot.json, config/notifier.json); callers never touch
credentials, protocol frames, or connection objects.

Extension points (not implemented this change):
  - dump_inbox(): inbox dump for @-message compensation during push windows
  - new channels (DingTalk, email, ...): add same-shaped entry points here so
    existing callers stay unchanged
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.wecom_bot_client import make_client_from_secrets

TIME_ZONE = ZoneInfo("Asia/Shanghai")

DEFAULT_CONFIG_PATH = Path("config/notifier.json")
DEFAULT_STATE_PATH = Path("state/bot-tool-state.json")

CLI_TIMEOUT_SECONDS = 60.0   # per `openclaw config set` invocation
RESTORE_GRACE_SECONDS = 3.0  # dueAt headroom so an in-flight push restores first
BACKOFF_TABLE_SECONDS = (5.0, 30.0, 300.0)  # 5s -> 30s -> 5m cap


class BotToolError(Exception):
    """Base class for tool-layer failures (config, ledger, orchestration)."""


class BotToolBackoffError(BotToolError):
    """A previous send failure's backoff has not expired; refuse to connect."""


# ---------------------------------------------------------------- ledger

def _empty_ledger() -> dict[str, Any]:
    return {"pendingRestore": None, "sendBackoff": {"failCount": 0, "nextRetryAt": None}}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_ledger(path: Path) -> dict[str, Any]:
    """Read the debt/backoff ledger; a missing or corrupt file is an EMPTY ledger."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _empty_ledger()
    if not isinstance(data, dict):
        return _empty_ledger()
    ledger = _empty_ledger()
    debt = data.get("pendingRestore")
    if isinstance(debt, dict) and isinstance(debt.get("kickedAt"), str) and _is_number(debt.get("dueAt")):
        ledger["pendingRestore"] = {"kickedAt": debt["kickedAt"], "dueAt": float(debt["dueAt"])}
    backoff = data.get("sendBackoff")
    if isinstance(backoff, dict):
        fail_count = backoff.get("failCount")
        next_retry = backoff.get("nextRetryAt")
        if isinstance(fail_count, int) and not isinstance(fail_count, bool) and fail_count >= 0 \
                and (next_retry is None or _is_number(next_retry)):
            ledger["sendBackoff"] = {
                "failCount": fail_count,
                "nextRetryAt": None if next_retry is None else float(next_retry),
            }
    return ledger


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    """Atomic replace: temp file + os.replace, so a crash never leaves a torn file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{time.time_ns()}")
    try:
        tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------- restore

def _restore_companion(
    *,
    cli_resolve: Callable[[str], str | None] = shutil.which,
    cli_run: Callable[..., Any] = subprocess.run,
    timeout: float = CLI_TIMEOUT_SECONDS,
) -> bool:
    """Toggle channels.wecom.enabled false->true to hot-reload the gateway's
    wecom channel (the plugin never reconnects on its own after being kicked).

    Returns True only when both CLI writes succeeded; any failure (CLI missing,
    timeout, nonzero exit) keeps the debt for a later ensure_companion_alive().
    """
    # CreateProcess does not resolve extensionless shims -> which() finds openclaw.cmd
    exe = cli_resolve("openclaw") or "openclaw.cmd"
    ok = True
    for value in ("false", "true"):
        try:
            proc = cli_run(
                [exe, "config", "set", "channels.wecom.enabled", "--json", value],
                capture_output=True,
                timeout=timeout,
            )
        except Exception:
            ok = False  # timeout / spawn failure; still attempt the second write
            continue
        if getattr(proc, "returncode", 1) != 0:
            ok = False
    return ok


# ---------------------------------------------------------------- config

def _load_push_config(path: Path) -> dict[str, Any]:
    """Tool layer reads chatid/secrets path/timeouts itself; callers stay dumb."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise BotToolError(f"notifier config unreadable: {path}: {e}") from e
    if not isinstance(data, dict):
        raise BotToolError(f"notifier config must be an object: {path}")
    chatid = str(data.get("chatid") or "").strip()
    if not chatid:
        raise BotToolError("config.chatid is required (target group)")
    secrets_file = str(data.get("secretsFile") or "state/secrets/wecom-bot.json").strip()
    timeouts = data.get("timeouts") if isinstance(data.get("timeouts"), dict) else {}
    return {
        "chatid": chatid,
        "secretsFile": secrets_file,
        "connectTimeout": float(timeouts.get("connect", 10)),
        "ackTimeout": float(timeouts.get("ack", 15)),
    }


# ---------------------------------------------------------------- public API

def push_markdown(
    text: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    client_factory: Callable[[], Any] | None = None,
    cli_resolve: Callable[[str], str | None] = shutil.which,
    cli_run: Callable[..., Any] = subprocess.run,
    now: Callable[[], float] = time.time,
) -> None:
    """Push one markdown message to the target group, then revive the companion.

    Raises on send failure (callers keep their cursor and retry per the
    persisted backoff). A failed revive never fails the push: the debt stays in
    the ledger for ensure_companion_alive().
    """
    cfg = _load_push_config(Path(config_path))
    state_path = Path(state_path)
    ledger = load_ledger(state_path)
    backoff = ledger["sendBackoff"]
    if backoff["nextRetryAt"] is not None and now() < backoff["nextRetryAt"]:
        raise BotToolBackoffError(
            f"send backoff in effect ({backoff['failCount']} failures), "
            f"retry not before {datetime.fromtimestamp(backoff['nextRetryAt'], TIME_ZONE).isoformat()}"
        )
    if client_factory is None:
        client_factory = lambda: make_client_from_secrets(  # noqa: E731
            Path(cfg["secretsFile"]),
            connect_timeout=cfg["connectTimeout"],
            ack_timeout=cfg["ackTimeout"],
        )

    # Debt BEFORE connecting: the connect itself kicks the companion.
    ledger["pendingRestore"] = {
        "kickedAt": datetime.now(TIME_ZONE).isoformat(),
        "dueAt": now() + RESTORE_GRACE_SECONDS,
    }
    save_ledger(state_path, ledger)

    send_error: BaseException | None = None
    try:
        client_factory().send_markdown(cfg["chatid"], text)
    except Exception as e:
        send_error = e

    # We took the line, we give it back: restore runs on success AND failure,
    # strictly after our own connection is closed (send_markdown closes it).
    if _restore_companion(cli_resolve=cli_resolve, cli_run=cli_run):
        ledger["pendingRestore"] = None

    if send_error is None:
        ledger["sendBackoff"] = {"failCount": 0, "nextRetryAt": None}
    else:
        fail_count = backoff["failCount"] + 1
        delay = BACKOFF_TABLE_SECONDS[min(fail_count - 1, len(BACKOFF_TABLE_SECONDS) - 1)]
        ledger["sendBackoff"] = {"failCount": fail_count, "nextRetryAt": now() + delay}
    save_ledger(state_path, ledger)

    if send_error is not None:
        raise send_error


def ensure_companion_alive(
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    cli_resolve: Callable[[str], str | None] = shutil.which,
    cli_run: Callable[..., Any] = subprocess.run,
    now: Callable[[], float] = time.time,
) -> None:
    """Settle an unpaid, due restore debt (crash insurance). No-op when there is
    no debt or it is not due yet. CLI/gateway failure keeps the debt for the
    next round and never raises.
    """
    state_path = Path(state_path)
    ledger = load_ledger(state_path)
    debt = ledger["pendingRestore"]
    if debt is None or now() < debt["dueAt"]:
        return
    if _restore_companion(cli_resolve=cli_resolve, cli_run=cli_run):
        ledger["pendingRestore"] = None
        save_ledger(state_path, ledger)


def dump_inbox() -> None:
    """Reserved extension point: dump the bot inbox (push-window @-message
    compensation). Not implemented in this change."""
    return None
