import json
from pathlib import Path

from src.io import ChatLogger


def message(event_id, role, text, timestamp):
    content = text
    if role == "assistant":
        content = [
            {"type": "thinking", "thinking": "不应写入日志"},
            {"type": "text", "text": text},
        ]
    return {
        "type": "message",
        "id": event_id,
        "timestamp": timestamp,
        "message": {"role": role, "content": content},
    }


def write_session(sessions_dir, session_id, events):
    path = sessions_dir / f"{session_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def write_index(sessions_dir, entries):
    (sessions_dir / "sessions.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )


def make_template(tmp_path):
    path = tmp_path / "chat-template.json"
    path.write_text(
        Path("templates/chat-log-template.example.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def test_wecom_question_answer_written_once(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    write_index(sessions, {
        "wecom": {"channel": "wecom", "sessionId": "s1"},
        "other": {"channel": "other", "sessionId": "s2"},
    })
    write_session(sessions, "s1", [
        message("q1", "user", "@FF 查看系统信息", "2026-11-23T05:54:54Z"),
        message("a1", "assistant", "这是系统信息", "2026-11-23T05:55:43Z"),
    ])
    write_session(sessions, "s2", [
        message("q2", "user", "其他渠道问题", "2026-11-23T06:00:00Z"),
        message("a2", "assistant", "其他渠道回答", "2026-11-23T06:01:00Z"),
    ])
    logs = tmp_path / "logs"
    logger = ChatLogger(sessions, logs, make_template(tmp_path))

    assert logger.sync() == 1
    records = [
        json.loads(line)
        for line in (logs / "2026-11-23.log").read_text(encoding="utf-8").splitlines()
    ]
    assert records == [{
        "questionTime": "2026-11-23T05:54:54Z",
        "answerTime": "2026-11-23T05:55:43Z",
        "sessionId": "s1",
        "questionId": "q1",
        "answerId": "a1",
        "question": "@FF 查看系统信息",
        "answer": "这是系统信息",
    }]
    assert logger.sync() == 0
    assert len((logs / "2026-11-23.log").read_text(encoding="utf-8").splitlines()) == 1


def test_daily_files_and_unanswered_question(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    write_index(sessions, {
        "wecom": {
            "channel": "wecom",
            "sessionId": "current",
            "usageFamilySessionIds": ["history"],
        },
    })
    write_session(sessions, "history", [
        message("q1", "user", "第一天问题", "2026-11-22T02:00:00Z"),
        message("a1", "assistant", "第一天回答", "2026-11-22T02:01:00Z"),
        message("q2", "user", "第二天问题", "2026-11-23T02:00:00Z"),
        message("a2", "assistant", "第二天回答", "2026-11-23T02:01:00Z"),
        message("q3", "user", "尚未回答", "2026-11-24T02:00:00Z"),
    ])
    logs = tmp_path / "logs"

    assert ChatLogger(sessions, logs, make_template(tmp_path)).sync() == 2
    assert sorted(path.name for path in logs.glob("*.log")) == [
        "2026-11-22.log", "2026-11-23.log",
    ]


def test_custom_template_controls_new_record(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    write_index(sessions, {"wecom": {"channel": "wecom", "sessionId": "s1"}})
    write_session(sessions, "s1", [
        message("q1", "user", "问题", "2026-11-23T02:00:00Z"),
        message("a1", "assistant", "回答", "2026-11-23T02:01:00Z"),
    ])
    template = tmp_path / "custom-template.json"
    template.write_text(json.dumps({
        "answerId": "{{answerId}}",
        "question": "用户：{{question}}",
        "answer": "机器人：{{answer}}",
    }), encoding="utf-8")
    logs = tmp_path / "logs"

    assert ChatLogger(sessions, logs, template).sync() == 1
    record = json.loads((logs / "2026-11-23.log").read_text(encoding="utf-8"))
    assert record == {
        "answerId": "a1",
        "question": "用户：问题",
        "answer": "机器人：回答",
    }
