#!/usr/bin/env python
"""PoC: WeCom smart-bot long-connection push via WebSocket (single file).

Verifies the four-frame protocol against a dev bot before the real client is
wired into the notifier:

  connect wss -> auth frame (aibot_subscribe) -> ack -> send a markdown
  (aibot_send_msg) -> ack -> close

Frame formats mirror the official @wecom/aibot-node-sdk (MIT) that ships with
the OpenClaw plugin on this machine:

  auth : {cmd:"aibot_subscribe", headers:{req_id}, body:{bot_id, secret}}
  ack  : {headers:{req_id}, errcode:0, errmsg:"ok"}   (echoes req_id prefix)
  push : {cmd:"aibot_send_msg", headers:{req_id}, body:{chatid, msgtype,
         markdown:{content}}}

Usage:
  python scripts/poc_wecom_ws.py --chatid <chatid> [--content TEXT]
  python scripts/poc_wecom_ws.py --chatid <chatid> --limit-probe
  (credentials are read from state/secrets/wecom-bot.json: {"botId", "secret"})
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

WS_URL = "wss://openws.work.weixin.qq.com"
MARKDOWN_LIMIT_BYTES = 20480


class PoCError(RuntimeError):
    pass


def _req_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _read_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        raise PoCError(f"secrets file not found: {path} (copy the template and fill botId/secret)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not str(data.get("botId", "")).strip() or not str(data.get("secret", "")).strip():
        raise PoCError(f"secrets file must contain botId and secret: {path}")
    return {"botId": str(data["botId"]).strip(), "secret": str(data["secret"]).strip()}


def _recv_frame(ws: Any, timeout: float) -> dict[str, Any]:
    """Receive one JSON frame; raises PoCError on timeout / parse failure."""
    ws.settimeout(timeout)
    try:
        raw = ws.recv()
    except Exception as e:  # websocket timeouts surface as WebSocketTimeoutException subclasses
        raise PoCError(f"recv failed/timeout: {e}") from e
    if not raw:
        raise PoCError("recv returned empty frame")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise PoCError(f"frame is not JSON: {e}") from e


def _wait_ack(ws: Any, req_id: str, timeout: float, what: str) -> dict[str, Any]:
    """Wait for the ack frame whose headers.req_id equals req_id."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PoCError(f"timeout waiting for {what} ack (req_id={req_id})")
        frame = _recv_frame(ws, min(remaining, timeout))
        if frame.get("cmd") in ("aibot_msg_callback", "aibot_event_callback"):
            print(f"  [recv] skip callback frame: {frame.get('cmd')}")
            continue
        if frame.get("headers", {}).get("req_id") == req_id:
            return frame
        print(f"  [recv] unrelated frame ignored (req_id={frame.get('headers', {}).get('req_id')})")


def _require_ok(frame: dict[str, Any], what: str) -> None:
    errcode = frame.get("errcode")
    if errcode != 0:
        raise PoCError(f"{what} failed: errcode={errcode} errmsg={frame.get('errmsg')}")
    print(f"  [ok] {what} accepted (errcode=0)")


def run_poc(secrets: dict[str, str], chatid: str, content: str, timeout: float) -> None:
    from websocket import create_connection  # local import: optional dependency

    print(f"[1/4] connecting {WS_URL} ...")
    ws = create_connection(WS_URL, timeout=timeout, enable_multithread=False)
    try:
        # 1. auth frame
        auth_req = _req_id("aibot_subscribe")
        auth_frame = {
            "cmd": "aibot_subscribe",
            "headers": {"req_id": auth_req},
            "body": {"bot_id": secrets["botId"], "secret": secrets["secret"]},
        }
        print("[2/4] sending auth frame ...")
        ws.send(json.dumps(auth_frame))
        ack = _wait_ack(ws, auth_req, timeout, "auth")
        _require_ok(ack, "auth")

        # 2. push frame
        send_req = _req_id("aibot_send_msg")
        send_frame = {
            "cmd": "aibot_send_msg",
            "headers": {"req_id": send_req},
            "body": {
                "chatid": chatid,
                "msgtype": "markdown",
                "markdown": {"content": content},
            },
        }
        print(f"[3/4] sending markdown ({len(content.encode('utf-8'))} bytes) to chatid={chatid} ...")
        ws.send(json.dumps(send_frame))
        send_ack = _wait_ack(ws, send_req, timeout, "send")
        _require_ok(send_ack, "send")

        print(f"[4/4] closing connection ...")
        ws.close()
        print("\nPoC OK: auth + proactive push + ack verified.")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def probe_limit(secrets: dict[str, str], chatid: str, timeout: float) -> None:
    """Send two probe messages: exactly at the 20480-byte limit and over it.
    The second is expected to fail with a non-zero errcode (or the server may
    truncate/accept it — the outcome is printed for the record)."""
    at_limit = "**PoC 字节上限探测**\n" + ("x" * (MARKDOWN_LIMIT_BYTES - len("**PoC 字节上限探测**\n".encode("utf-8"))))
    over_limit = "**PoC 超限探测**\n" + ("y" * (MARKDOWN_LIMIT_BYTES + 1))
    for label, content in (("at-limit", at_limit), ("over-limit", over_limit)):
        print(f"--- probe {label}: {len(content.encode('utf-8'))} bytes ---")
        try:
            run_poc(secrets, chatid, content, timeout)
            print(f"probe {label}: push accepted")
        except PoCError as e:
            print(f"probe {label}: rejected as expected/failed: {e}")
    print("\nlimit probe finished (see outcomes above)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--chatid", required=True, help="target chatid (config/wecom-aibot.json reference or dev test group)")
    p.add_argument("--secrets", type=Path, default=Path("state/secrets/wecom-bot.json"))
    p.add_argument("--content", default="**PoC** 长连接推送测试 OK，通知器将用此通道推送内网监控消息。")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--limit-probe", action="store_true", help="probe the 20480-byte markdown limit instead of a normal push")
    args = p.parse_args(argv)

    try:
        secrets = _read_secrets(args.secrets)
    except PoCError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        if args.limit_probe:
            probe_limit(secrets, args.chatid, args.timeout)
        else:
            run_poc(secrets, args.chatid, args.content, args.timeout)
    except PoCError as e:
        print(f"PoC FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # unexpected (network, websocket lib ...)
        print(f"PoC FAILED (unexpected): {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())