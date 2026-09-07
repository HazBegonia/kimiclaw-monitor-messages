import json
from pathlib import Path

import pytest

from src import email_notifier
from src.email_notifier import (build_error_mail, build_version_mail,
    collect_new_diffs, collect_new_errors, load_config, load_state, main)


def _config(tmp_path):
    path = tmp_path / "smtp.local.json"
    path.write_text(json.dumps({
        "host": "smtp.example", "port": 465, "username": "u@qq.com",
        "auth_code": "x", "from": "u@qq.com", "to": ["r@example.com"],
    }), encoding="utf-8")
    return path


def _diff_log(directory, name, added, removed, detected_at="2026-09-07T12:00:00+08:00"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    lines = ["monitorId: intranet-root", f"detectedAt: {detected_at}",
             "previousFingerprint: a", "currentFingerprint: b", "", "changedFields:",
             "- root_files: " + json.dumps({"added": added, "removed": removed}, ensure_ascii=False)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _error_log(directory, date, records):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{date}.log"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


def _error_record(error_type="TimeoutError", phase="fetch_page", at="2026-09-07T11:09:03+08:00"):
    return {"eventId": "e", "detectedAt": at, "phase": phase, "errorType": error_type,
            "message": "offline", "url": "http://example/"}


def _run_main(tmp_path, monkeypatch, sent, extra_args=(), versions=None):
    monkeypatch.setattr(email_notifier, "send", lambda config, subject, body: sent.append((subject, body)))
    vc = tmp_path / "versions.json"
    vc.write_text(json.dumps({"selectedVersions": versions or []}), encoding="utf-8")
    return main(["--config", str(_config(tmp_path)), "--state", str(tmp_path / "notify-state.json"),
                 "--diff-dir", str(tmp_path / "diff"), "--error-dir", str(tmp_path / "err"),
                 "--focus-dir", str(tmp_path / "focus"), "--versions-config", str(vc), *extra_args])


def test_missing_config_degrades_without_sending(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "nope.json"), "--state", str(tmp_path / "s.json")]) == 0
    assert "跳过邮件发送" in capsys.readouterr().err


def test_incomplete_config_degrades(tmp_path, capsys):
    bad = tmp_path / "smtp.local.json"
    bad.write_text(json.dumps({"host": "smtp.example"}), encoding="utf-8")
    assert main(["--config", str(bad), "--state", str(tmp_path / "s.json")]) == 0
    assert "缺少字段" in capsys.readouterr().err


def test_first_run_records_baseline_and_sends_nothing(tmp_path, monkeypatch):
    sent = []
    _diff_log(tmp_path / "diff", "2026-09-01_10-00-00-000.log", ["old.csv"], [])
    assert _run_main(tmp_path, monkeypatch, sent) == 0
    assert sent == []
    state = json.loads((tmp_path / "notify-state.json").read_text(encoding="utf-8"))
    assert state["diffCursor"] == "2026-09-01_10-00-00-000.log"


def test_new_diff_sends_single_summary_and_advances_cursor(tmp_path, monkeypatch):
    sent = []
    _diff_log(tmp_path / "diff", "2026-09-06_10-00-00-000.log", ["a.csv"], [])
    assert _run_main(tmp_path, monkeypatch, sent) == 0  # baseline
    _diff_log(tmp_path / "diff", "2026-09-07_10-00-00-000.log", ["b.csv", "c.csv"], ["a.csv"])
    _diff_log(tmp_path / "diff", "2026-09-07_11-00-00-000.log", ["d.csv"], [])
    assert _run_main(tmp_path, monkeypatch, sent) == 0
    assert len(sent) == 1
    subject, body = sent[0]
    assert subject == "【内网监控】版本更新 · 新增 3 个文件、删除 1 个文件"
    assert "- b.csv" in body and "- d.csv" in body and "- a.csv" in body
    state = json.loads((tmp_path / "notify-state.json").read_text(encoding="utf-8"))
    assert state["diffCursor"] == "2026-09-07_11-00-00-000.log"
    assert _run_main(tmp_path, monkeypatch, sent) == 0  # no new content
    assert len(sent) == 1


def test_errors_aggregate_by_type_and_phase(tmp_path, monkeypatch):
    sent = []
    records = [_error_record(at="2026-09-07T11:09:03+08:00"),
               _error_record(at="2026-09-07T11:18:55+08:00"),
               _error_record("PageValidationError", "validate_page", "2026-09-07T11:20:00+08:00")]
    log = _error_log(tmp_path / "err", "2026-09-07", records)
    assert _run_main(tmp_path, monkeypatch, sent) == 0  # baseline at end of file
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_error_record(at="2026-09-07T12:00:00+08:00"), ensure_ascii=False) + "\n")
    assert _run_main(tmp_path, monkeypatch, sent) == 0
    assert len(sent) == 1
    subject, body = sent[0]
    assert subject == "【内网监控】监控异常 · TimeoutError ×1"
    assert "×1" in body and "11:09" not in body  # only the new record is included
    state = json.loads((tmp_path / "notify-state.json").read_text(encoding="utf-8"))
    assert state["errorCursor"]["offset"] == log.stat().st_size


def test_build_error_mail_groups_and_counts():
    records = [_error_record(at="2026-09-07T11:09:03+08:00"),
               _error_record(at="2026-09-07T11:18:55+08:00"),
               _error_record("PageValidationError", "validate_page", "2026-09-07T11:20:00+08:00")]
    subject, body = build_error_mail(records, "http://example/")
    assert subject == "【内网监控】监控异常 · 2 类共 3 条"
    assert "TimeoutError（fetch_page）×2" in body
    assert "首次：2026-09-07T11:09:03+08:00" in body
    assert "末次：2026-09-07T11:18:55+08:00" in body


def test_send_failure_keeps_cursor_and_exits_zero(tmp_path, monkeypatch):
    _diff_log(tmp_path / "diff", "2026-09-06_10-00-00-000.log", ["a.csv"], [])
    sent = []
    assert _run_main(tmp_path, monkeypatch, sent) == 0  # baseline
    _diff_log(tmp_path / "diff", "2026-09-07_10-00-00-000.log", ["b.csv"], [])
    monkeypatch.setattr(email_notifier, "send", lambda *a: (_ for _ in ()).throw(OSError("smtp down")))
    assert main(["--config", str(_config(tmp_path)), "--state", str(tmp_path / "notify-state.json"),
                 "--diff-dir", str(tmp_path / "diff"), "--error-dir", str(tmp_path / "err"),
                 "--focus-dir", str(tmp_path / "focus")]) == 0
    state = json.loads((tmp_path / "notify-state.json").read_text(encoding="utf-8"))
    assert state["diffCursor"] == "2026-09-06_10-00-00-000.log"


def test_version_detail_lists_matched_files(tmp_path, monkeypatch):
    sent = []
    versions = [{"id": "v2", "match": "103300110002"}]
    assert _run_main(tmp_path, monkeypatch, sent, versions=versions) == 0  # baseline
    _diff_log(tmp_path / "diff", "2026-09-07_10-00-00-000.log",
              ["20260907_103300110002.csv", "20260907_103300110002_opt_Optimal_93002.csv", "other.csv"], [])
    assert _run_main(tmp_path, monkeypatch, sent, versions=versions) == 0
    subject, body = sent[0]
    assert "- v2：新增 2 / 删除 0" in body
    assert "  + 20260907_103300110002.csv" in body
    assert "  + 20260907_103300110002_opt_Optimal_93002.csv" in body
    assert "+ other.csv" not in body  # 未命中版本匹配的文件不进版本明细
    assert "- other.csv" in body  # 但仍出现在上方总清单


def test_send_uses_ssl_login_and_utf8_headers(tmp_path, monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls["connect"] = (host, port)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, user, code):
            calls["login"] = (user, code)
        def sendmail(self, sender, recipients, payload):
            calls["mail"] = (sender, recipients, payload)

    monkeypatch.setattr(email_notifier.smtplib, "SMTP_SSL", FakeSMTP)
    config = json.loads(_config(tmp_path).read_text(encoding="utf-8"))
    email_notifier.send(config, "【内网监控】测试邮件 · 链路正常", "正文内容")
    assert calls["connect"] == ("smtp.example", 465)
    assert calls["login"] == ("u@qq.com", "x")
    assert calls["mail"][0] == "u@qq.com" and calls["mail"][1] == ["r@example.com"]
    assert "utf-8" in calls["mail"][2]
