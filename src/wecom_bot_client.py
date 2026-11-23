from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
WS_URL = os.getenv("WS_URL", "wss://openws.work.weixin.qq.com")

CMD_SUBSCRIBE = os.getenv("CMD_SUBSCRIBE", "aibot_subscribe")
CMD_PING = os.getenv("CMD_PING", "ping")
CMD_SEND_MSG = os.getenv("CMD_SEND_MSG", "aibot_send_msg")
CMD_CALLBACK = os.getenv("CMD_CALLBACK", "aibot_msg_callback")
CMD_EVENT_CALLBACK = os.getenv("CMD_EVENT_CALLBACK", "aibot_event_callback")
EVENT_DISCONNECTED = os.getenv("EVENT_DISCONNECTED", "disconnected_event")


class WecomBotError(Exception):
    """Base class for all client failures. `errcode`/`errmsg` are optional."""

    def __init__(self, errcode: int | None = None, errmsg: str | None = None, detail: str | None = None):
        self.errcode = errcode
        self.errmsg = errmsg
        self.detail = detail
        super().__init__(detail or (f"errcode={errcode} errmsg={errmsg}" if errmsg else "wecom bot error"))


class WecomBotConnectionError(WecomBotError):
    """Raw websocket connect failed (DNS, TLS, network)."""


class WecomBotAuthError(WecomBotError):
    """Auth ack arrived with errcode != 0 (wrong botId/secret). Credential
    errors must never be silently swallowed or retried forever."""


class WecomBotSendFailedError(WecomBotError):
    """Send ack arrived with errcode != 0 (ban/moved-out-of-group/rate limit/...)."""


class WecomBotTimeoutError(WecomBotError):
    """Timeout waiting for an ack; the send must be reported as failed, never
    as a half-success."""


class WecomBotKickedError(WecomBotError):
    """Server sent `disconnected_event: a new connection for the same botId took
    over this connection before our send was acked. The send must be recorded
    as failed (no false success)."""


def _req_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


class _FakeWS:
    """Minimal stand-in so unit tests can inject canned frames."""

    def __init__(self):
        self.sent: list[dict[str, Any]] = []
        self.queue: list[dict[str, Any]] = []

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def recv(self) -> str:
        if not self.queue:
            raise TimeoutError("no more canned frames")
        return json.dumps(self.queue.pop(0), ensure_ascii=False)

    def close(self) -> None:
        pass


class WecomBotClient:
    """On-demand proactive-push client for one send cycle per use.

    Threading model: single-threaded use; one instance owns one socket at a time.
    """

    def __init__(
        self,
        bot_id: str,
        secret: str,
        *,
        ws_url: str = WS_URL,
        connect_timeout: float = 10.0,
        ack_timeout: float = 15.0,
        transport: Callable[..., Any] | None = None,
        extra_auth_body: dict[str, Any] | None = None,
    ):
        self._bot_id = bot_id
        self._secret = secret
        self._ws_url = ws_url
        self._connect_timeout = connect_timeout
        self._ack_timeout = ack_timeout
        self._transport = transport
        self._extra_auth_body = dict(extra_auth_body or {})
        self._ws: Any = None

    # ---- transport helpers (individually patchable in tests) ----

    def _connect(self) -> Any:
        if self._transport is not None:
            ws = self._transport()
            ws.settimeout(self._connect_timeout)
            return ws
        from websocket import create_connection

        ws = create_connection(self._ws_url or WS_URL, timeout=self._connect_timeout, enable_multithread=False)
        return ws

    def _send_frame(self, frame: dict[str, Any]) -> None:
        self._ws.send(json.dumps(frame, ensure_ascii=False))

    def _recv_frame(self) -> dict[str, Any] | None:
        """Blocking receive of one JSON frame; None when the socket is closed."""
        raw = self._ws.recv()
        if not raw:
            return None
        return json.loads(raw)

    def _close(self) -> None:
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None

    # ---- protocol ----

    def _wait_ack(self, req_id: str, what: str) -> dict[str, Any]:
        """Wait for the ack whose headers.req_id == req_id, skipping callbacks.

        Raises WecomBotKickedError on disconnected_event (connection was stolen
        by a newer connection for the same botId), WecomBotTimeoutError on timeout.
        """
        deadline = time.monotonic() + self._ack_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WecomBotTimeoutError(detail=f"timed out waiting for {what} ack (req_id={req_id})")
            try:
                frame = self._recv_frame()
            except WecomBotError:
                raise  # transport-level errors propagate; caller records failure
            except Exception as e:  # socket timeout / closed socket
                raise WecomBotTimeoutError(detail=f"{what} ack did not arrive: {type(e).__name__}: {e}")
            if frame is None:
                raise WecomBotTimeoutError(detail=f"{what} ack did not arrive (socket closed)")
            cmd = frame.get("cmd")
            if cmd == CMD_EVENT_CALLBACK:
                event_type = (frame.get("body") or {}).get("event", {}).get("eventtype") or ""
                if event_type == EVENT_DISCONNECTED:
                    raise WecomBotKickedError(detail="disconnected_event: a newer connection for the same botId took over this one")
                continue  # skip other events
            if frame.get("headers", {}).get("req_id") == req_id:
                return frame
            # unrelated frame (e.g. stray callback); keep waiting

    def send_markdown(self, chatid: str, content: str) -> dict[str, Any]:
        """Run one on-demand send cycle. Returns the send ack on success.

        Raises WecomBotError subclasses on failure (connection/auth/timeout/kicked).
        Callers convert failures into a failure record and keep the cursor untouched.
        """
        self._ws = self._connect()
        try:
            # 1. auth frame
            auth_req = _req_id(CMD_SUBSCRIBE)
            self._send_frame(
                {
                    "cmd": CMD_SUBSCRIBE,
                    "headers": {"req_id": auth_req},
                    "body": {"bot_id": self._bot_id, "secret": self._secret, **self._extra_auth_body},
                }
            )
            ack = self._wait_ack(auth_req, "auth")
            if ack.get("errcode") != 0:
                raise WecomBotAuthError(errcode=ack.get("errcode"), errmsg=str(ack.get("errmsg") or ""), detail="authentication failed (check botId/secret)")

            # 2. proactive push frame
            send_req = _req_id(CMD_SEND_MSG)
            self._send_frame(
                {
                    "cmd": CMD_SEND_MSG,
                    "headers": {"req_id": send_req},
                    "body": {"chatid": chatid, "msgtype": "markdown", "markdown": {"content": content}},
                }
            )
            send_ack = self._wait_ack(send_req, "send")
            if send_ack.get("errcode") != 0:
                raise WecomBotSendFailedError(errcode=send_ack.get("errcode"), errmsg=str(send_ack.get("errmsg") or ""), detail="proactive push rejected by server")
            return send_ack
        finally:
            self._close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._close()
        return False


def make_client_from_secrets(
    secrets_path,
    *,
    connect_timeout: float = 10.0,
    ack_timeout: float = 15.0,
    extra_auth_body: dict[str, Any] | None = None,
) -> WecomBotClient:
    """Factory reading botId/secret from a JSON file (gitignore-covered path)."""
    from pathlib import Path

    data = json.loads(Path(str(secrets_path).replace("\\", "/")).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not str(data.get("botId", "")).strip() or not str(data.get("secret", "")).strip():
        raise ValueError(f"secrets file must contain botId and secret: {secrets_path}")
    return WecomBotClient(
        str(data["botId"]).strip(),
        str(data["secret"]).strip(),
        connect_timeout=connect_timeout,
        ack_timeout=ack_timeout,
        extra_auth_body=extra_auth_body,
    )