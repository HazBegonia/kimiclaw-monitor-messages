"""Unit tests for src/wecom_bot_client.py (frame construction, ack matching,
timeout, auth failure, kicked connection)."""
import json
from pathlib import Path

import pytest

from src.wecom_bot_client import (CMD_SEND_MSG, CMD_SUBSCRIBE, EVENT_DISCONNECTED,
    WecomBotAuthError, WecomBotClient, WecomBotKickedError, WecomBotSendFailedError,
    WecomBotTimeoutError, WecomGroupBotClient, WecomPrivateBotClient, _FakeWS,
    make_client_from_secrets)


def _client_with(frames, *, bot_id="bot1", secret="sec1"):
    ws = _FakeWS()
    ws.queue.extend(frames)
    return WecomGroupBotClient(bot_id, secret, connect_timeout=1.0, ack_timeout=1.0, transport=lambda: ws), ws


def _ok_ack(req_id, *, errcode=0, errmsg="ok"):
    return {"headers": {"req_id": req_id}, "errcode": errcode, "errmsg": errmsg}


def _send_req_id(ws):
    """Extract the req_id of the first aibot_send_msg frame sent."""
    for frame in ws.sent:
        if frame.get("cmd") == CMD_SEND_MSG:
            return frame["headers"]["req_id"]
    raise AssertionError("no send_msg frame was sent")


@pytest.mark.parametrize(
    ("client_class", "chatid", "chat_type"),
    [(WecomGroupBotClient, "chat-123", 2), (WecomPrivateBotClient, "LiFeiFan", 1)],
)
def test_successful_send_constructs_correct_frames_and_returns_ack(client_class, chatid, chat_type):
    # Both subclasses share this transport; only their protocol target type differs.
    class AutoAck:
        def __init__(self):
            self.sent = []
            self._waiting_auth = None
            self._waiting_send = None
            self.timeout = 1.0

        def settimeout(self, t):
            self.timeout = t

        def send(self, raw):
            frame = json.loads(raw)
            self.sent.append(frame)
            if frame.get("cmd") == CMD_SUBSCRIBE:
                self._waiting_auth = frame["headers"]["req_id"]
            elif frame.get("cmd") == CMD_SEND_MSG:
                self._waiting_send = frame["headers"]["req_id"]

        def recv(self):
            if self._waiting_auth is not None:
                req = self._waiting_auth
                self._waiting_auth = None
                return json.dumps(_ok_ack(req))
            if self._waiting_send is not None:
                req = self._waiting_send
                self._waiting_send = None
                return json.dumps(_ok_ack(req))
            raise TimeoutError("unexpected recv")

        def close(self):
            pass

    auto = AutoAck()
    client = client_class("bot1", "sec1", ack_timeout=1.0, transport=lambda: auto)
    result = client.send_markdown(chatid, "**hello**")
    assert result["errcode"] == 0

    subscribe = auto.sent[0]
    assert subscribe["cmd"] == CMD_SUBSCRIBE
    assert subscribe["headers"]["req_id"].startswith(CMD_SUBSCRIBE + "_")
    assert subscribe["body"] == {"bot_id": "bot1", "secret": "sec1"}

    send = auto.sent[1]
    assert send["cmd"] == CMD_SEND_MSG
    assert send["body"]["chatid"] == chatid
    assert send["body"]["chat_type"] == chat_type
    assert send["body"]["msgtype"] == "markdown"
    assert send["body"]["markdown"]["content"] == "**hello**"


def test_base_client_requires_a_concrete_target_class():
    with pytest.raises(TypeError):
        WecomBotClient("bot1", "sec1")


def test_invalid_chat_type_is_rejected_before_reading_credentials(tmp_path):
    with pytest.raises(ValueError, match="chat_type"):
        make_client_from_secrets(tmp_path / "secrets.json", chat_type=0)


def test_auth_ack_matched_by_req_id_and_unrelated_frames_skipped():
    class Fake:
        def __init__(self):
            self.sent = []
            self.timeout = 1.0
            self.auth_req = None
            self.send_req = None
            self.recv_calls = 0

        def settimeout(self, t):
            self.timeout = t

        def send(self, raw):
            frame = json.loads(raw)
            self.sent.append(frame)
            if frame.get("cmd") == CMD_SUBSCRIBE:
                self.auth_req = frame["headers"]["req_id"]
            else:
                self.send_req = frame["headers"]["req_id"]

        def recv(self):
            # unrelated callback first (only one stale callback), then acks
            self.recv_calls += 1
            if self.recv_calls == 1:
                return json.dumps(
                    {"cmd": "aibot_msg_callback", "headers": {"req_id": "x"}, "body": {}}
                )
            if self.auth_req is not None:
                req, self.auth_req = self.auth_req, None
                return json.dumps(_ok_ack(req))
            return json.dumps(_ok_ack(self.send_req))

        def close(self):
            pass

    fake = Fake()
    client = WecomGroupBotClient("b", "s", ack_timeout=1.0, transport=lambda: fake)
    client.send_markdown("c", "hi")
    assert fake.auth_req is None
    assert fake.recv_calls == 3  # callback + auth ack + send ack


def test_timeout_waiting_for_ack_is_failure():
    class NeverAck:
        def __init__(self):
            self.timeout = 1.0

        def settimeout(self, t):
            self.timeout = t

        def send(self, raw):
            pass

        def recv(self):
            raise TimeoutError("socket timeout")

        def close(self):
            pass

    client = WecomGroupBotClient("b", "s", connect_timeout=1.0, ack_timeout=0.2, transport=lambda: NeverAck())
    with pytest.raises(WecomBotTimeoutError):
        client.send_markdown("c", "hi")


def test_auth_failure_is_visible():
    ws = _FakeWS()
    ws.queue.append(_ok_ack("anything", errcode=85001, errmsg="bad secret"))
    # auth req_id is generated at runtime; the ack matcher compares the exact
    # req_id, so an exact-match ack must echo it: drive with AutoAck-like fake.
    class BadAuth:
        def __init__(self):
            self.sent = []
            self.timeout = 1.0

        def settimeout(self, t):
            self.timeout = t

        def send(self, raw):
            self.sent.append(json.loads(raw))

        def recv(self):
            req = self.sent[-1]["headers"]["req_id"]
            return json.dumps({"headers": {"req_id": req}, "errcode": 85001, "errmsg": "invalid secret"})

        def close(self):
            pass

    client = WecomGroupBotClient("b", "wrong", ack_timeout=1.0, transport=lambda: BadAuth())
    with pytest.raises(WecomBotAuthError) as exc:
        client.send_markdown("c", "hi")
    assert exc.value.errcode == 85001
    assert "secret" in (exc.value.errmsg or "")


def test_send_rejected_by_server_reported_as_failed():
    class RejectSend:
        def __init__(self):
            self.sent = []
            self.timeout = 1.0

        def settimeout(self, t):
            self.timeout = t

        def send(self, raw):
            self.sent.append(json.loads(raw))

        def recv(self):
            frame = self.sent[-1]
            req = frame["headers"]["req_id"]
            if frame.get("cmd") == CMD_SUBSCRIBE:
                return json.dumps(_ok_ack(req))
            return json.dumps({"headers": {"req_id": req}, "errcode": 12345, "errmsg": "not in group"})

        def close(self):
            pass

    client = WecomGroupBotClient("b", "s", ack_timeout=1.0, transport=lambda: RejectSend())
    with pytest.raises(WecomBotSendFailedError) as exc:
        client.send_markdown("c", "hi")
    assert exc.value.errcode == 12345
    assert "not in group" in (exc.value.errmsg or "")


def test_disconnected_event_during_send_is_not_success():
    class Kicked:
        def __init__(self):
            self.sent = []
            self.timeout = 1.0

        def settimeout(self, t):
            self.timeout = t

        def send(self, raw):
            self.sent.append(json.loads(raw))

        def recv(self):
            frame = self.sent[-1]
            req = frame["headers"]["req_id"]
            if frame.get("cmd") == CMD_SUBSCRIBE:
                return json.dumps(_ok_ack(req))
            return json.dumps(
                {"cmd": "aibot_event_callback", "headers": {"req_id": "x"},
                 "body": {"event": {"eventtype": EVENT_DISCONNECTED}}}
            )

        def close(self):
            pass

    client = WecomGroupBotClient("b", "s", ack_timeout=1.0, transport=lambda: Kicked())
    with pytest.raises(WecomBotKickedError):
        client.send_markdown("c", "hi")


def test_socket_closed_after_finish(tmp_path, monkeypatch):
    closed_flag = {"closed": False}

    class Manual:
        def __init__(self):
            self.sent = []
            self.timeout = 1.0
            self._wait_auth = None
            self._wait_send = None

        def settimeout(self, t):
            self.timeout = t

        def send(self, raw):
            frame = json.loads(raw)
            self.sent.append(frame)
            if frame.get("cmd") == CMD_SUBSCRIBE:
                self._wait_auth = frame["headers"]["req_id"]
            else:
                self._wait_send = frame["headers"]["req_id"]

        def recv(self):
            if self._wait_auth:
                req, self._wait_auth = self._wait_auth, None
                return json.dumps(_ok_ack(req))
            req = self._wait_send
            return json.dumps(_ok_ack(req))

        def close(self):
            closed_flag["closed"] = True

    ws = Manual()
    client = WecomGroupBotClient("b", "s", ack_timeout=1.0, transport=lambda: ws)
    client.send_markdown("c", "hi")
    assert closed_flag["closed"] is True


@pytest.mark.parametrize(
    ("chat_type", "expected_class"),
    [(None, WecomGroupBotClient), (1, WecomPrivateBotClient), (2, WecomGroupBotClient)],
)
def test_make_client_from_secrets_selects_target_class(tmp_path, chat_type, expected_class):
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({"botId": "b1", "secret": "s1"}), encoding="utf-8")
    kwargs = {} if chat_type is None else {"chat_type": chat_type}

    client = make_client_from_secrets(secrets, **kwargs)

    assert isinstance(client, expected_class)
    assert client._bot_id == "b1"
    assert client._secret == "s1"


def test_make_client_from_secrets_requires_fields(tmp_path):
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({"botId": ""}), encoding="utf-8")
    with pytest.raises(ValueError):
        make_client_from_secrets(secrets)
    with pytest.raises(OSError):  # missing file is FileNotFoundError
        make_client_from_secrets(tmp_path / "missing.json")