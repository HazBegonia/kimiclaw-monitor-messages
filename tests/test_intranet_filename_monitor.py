import json
import os
import time
from datetime import datetime
from pathlib import Path

from src.intranet_filename_monitor import (diff_filenames, filter_version_files,
    load_monitors_config, load_selected_versions, parse_filenames, record_error, run_once, write_diff_log, validate_page)


def test_parse_python_directory_listing_filters_non_root_links():
    html = '''<a href="a.csv">a.csv</a><a href="sub/">sub/</a><a href="?C=N;O=D">sort</a>'''
    assert parse_filenames(html) == {"a.csv"}


def test_diff_reports_only_filename_set_changes():
    assert diff_filenames({"a.csv", "b.csv"}, {"b.csv", "c.csv"}) == {
        "added": ["c.csv"],
        "removed": ["a.csv"],
    }


def test_first_scan_is_silent_baseline_and_second_unchanged_scan_writes_no_log(tmp_path, monkeypatch):
    html = '<a href="a.csv">a.csv</a>'
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: parse_filenames(html))
    state = tmp_path / "state.json"
    logs = tmp_path / "logs"
    first = run_once("http://example/", state, logs, 1)
    second = run_once("http://example/", state, logs, 1)
    assert first["baseline"] is True
    assert second["log"] is None
    assert not logs.exists()


def test_changed_filenames_write_log_without_file_content(tmp_path, monkeypatch):
    values = iter([{"a.csv"}, {"a.csv", "new.csv"}])
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: next(values))
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    run_once("http://example/", state, logs, 1)
    result = run_once("http://example/", state, logs, 1)
    path = Path(result["log"])
    assert path.name.endswith(".log")
    assert "new.csv" in path.read_text(encoding="utf-8")
    assert "csv content" not in path.read_text(encoding="utf-8")
    assert json.loads(state.read_text(encoding="utf-8"))["files"] == ["a.csv", "new.csv"]


def test_timestamp_collision_gets_sequence_suffix(tmp_path):
    stamp = datetime(2026, 9, 4, 13, 42, 8, 37_000, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
    diff = {"added": ["a.csv"], "removed": []}
    first = write_diff_log(tmp_path, diff, stamp)
    second = write_diff_log(tmp_path, diff, stamp)
    assert first.name == "2026-09-04_13-42-08-037.log"
    assert second.name == "2026-09-04_13-42-08-037-001.log"


def test_failed_scan_keeps_last_good_state_and_writes_no_log(tmp_path, monkeypatch):
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a.csv"})
    run_once("http://example/", state, logs, 1, error_log_dir=tmp_path / "errors")
    monkeypatch.setattr(
        "src.intranet_filename_monitor.fetch_filenames",
        lambda *_: (_ for _ in ()).throw(TimeoutError("offline")),
    )
    try:
        run_once("http://example/", state, logs, 1, error_log_dir=tmp_path / "errors")
    except TimeoutError:
        pass
    assert json.loads(state.read_text(encoding="utf-8"))["files"] == ["a.csv"]
    assert not logs.exists()


def test_successful_empty_listing_reports_removed_files(tmp_path, monkeypatch):
    values = iter([{"a.csv"}, set()])
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: next(values))
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    run_once("http://example/", state, logs, 1)
    result = run_once("http://example/", state, logs, 1)
    assert result["removed"] == ["a.csv"]


def test_validate_page_rejects_non_directory_or_truncated_html():
    with __import__("pytest").raises(RuntimeError):
        validate_page("<html><title>Error</title><h1>Error</h1></html>")
    with __import__("pytest").raises(RuntimeError):
        validate_page("<html><title>Directory listing for /</title><h1>Directory listing for /</h1>")


def test_event_id_is_stable_for_same_change(tmp_path, monkeypatch):
    values = iter([{"a.csv"}, {"a.csv", "b.csv"}])
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: next(values))
    sent = []
    monkeypatch.setattr("src.intranet_filename_monitor._send_event", lambda *args: sent.append(args[1]))
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    run_once("http://example/", state, logs, 1)
    run_once("http://example/", state, logs, 1, event_url="http://event", outbox=tmp_path / "outbox")
    assert len(sent) == 1
    assert sent[0]["event_id"]

def test_load_versions_and_filter_multiple_selectors(tmp_path):
    config = tmp_path / "versions.json"
    config.write_text(json.dumps({"selectedVersions": [
        {"id": "v1", "match": "103300110002"},
        {"id": "v2", "match": "103300110003"},
    ]}), encoding="utf-8")
    versions = load_selected_versions(config)
    assert filter_version_files(["a_103300110002.csv", "b_103300110003.csv"], versions) == {
        "v1": ["a_103300110002.csv"], "v2": ["b_103300110003.csv"]}

def test_version_snapshot_written_only_on_change_with_before_after(tmp_path, monkeypatch):
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a_103300110002.csv"})
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    versions = [{"id": "103300110002", "match": "103300110002"}]
    focus = tmp_path / "focus"
    first = run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=focus)
    second = run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=focus)  # unchanged
    snapshots = sorted((focus / "103300110002").glob("*.log"))
    assert first["versionLogs"] and not second["versionLogs"]        # only change events write a snapshot
    assert len(snapshots) == 1
    baseline = snapshots[0].read_text(encoding="utf-8")
    assert "before:" in baseline and "after:" in baseline
    assert "beforeCount: 0" in baseline and "afterCount: 1" in baseline
    assert "a_103300110002.csv" in baseline
    assert not logs.exists()
    # a real change writes ONE log containing BOTH full lists
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a_103300110002.csv", "b_103300110002.csv"})
    third = run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=focus)
    snapshots = sorted((focus / "103300110002").glob("*.log"))
    assert len(third["versionLogs"]) == 1 and len(snapshots) == 2
    text = snapshots[-1].read_text(encoding="utf-8")
    before_block, after_block = text.split("after:", 1)
    assert "addedCount: 1" in text and "removedCount: 0" in text
    assert "beforeCount: 1" in text and "afterCount: 2" in text
    assert before_block.count("- ") == 1                             # full before list: a
    assert after_block.count("- ") == 2                              # full after list: a + b
    assert "a_103300110002.csv" in text and "b_103300110002.csv" in text

def test_failed_scan_does_not_write_version_snapshot(tmp_path, monkeypatch):
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    versions = [{"id": "v1", "match": "1033"}]
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a_1033.csv"})
    run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=tmp_path / "focus", error_log_dir=tmp_path / "errors")
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: (_ for _ in ()).throw(TimeoutError("offline")))
    try:
        run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=tmp_path / "focus", error_log_dir=tmp_path / "errors")
    except TimeoutError:
        pass
    assert len(list((tmp_path / "focus" / "v1").glob("*.log"))) == 1


def test_failed_scan_writes_daily_raw_error_and_preserves_state(tmp_path, monkeypatch):
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a.csv"})
    run_once("http://example/", state, logs, 1, error_log_dir=tmp_path / "errors")
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: (_ for _ in ()).throw(TimeoutError("Bearer secret-token")))
    with __import__("pytest").raises(TimeoutError):
        run_once("http://user:pass@example/path?token=secret", state, logs, 1, error_log_dir=tmp_path / "errors")
    error_file = list((tmp_path / "errors").glob("*.log"))[0]
    rows = [json.loads(line) for line in error_file.read_text(encoding="utf-8").splitlines()]
    row = rows[-1]
    assert {"eventId", "detectedAt", "monitorId", "mode", "phase", "errorType", "message", "path", "url", "statePreserved", "retryable"} <= row.keys()
    assert row["phase"] == "fetch_page"
    assert row["statePreserved"] is True
    assert "secret-token" not in row["message"]
    assert "token=secret" not in row["url"]
    assert json.loads(state.read_text(encoding="utf-8"))["files"] == ["a.csv"]


def test_record_error_falls_back_to_stderr_when_directory_unwritable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    result = record_error(tmp_path / "errors", monitor_id="intranet-root", mode="once", phase="write_state", error=RuntimeError("oops"), url="http://example/?token=hidden")
    assert result is None
    assert "error log unavailable" in capsys.readouterr().err


def test_page_validation_failure_is_logged_with_validation_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.intranet_filename_monitor.fetch_page",
        lambda *_: ("<html><title>Error</title><h1>Error</h1></html>", 42, 0.01),
    )
    with __import__("pytest").raises(RuntimeError):
        run_once(
            "http://example/",
            tmp_path / "state.json",
            tmp_path / "logs",
            1,
            error_log_dir=tmp_path / "errors",
        )
    row = json.loads(next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8"))
    assert row["phase"] == "validate_page"


def test_main_once_returns_nonzero_after_recording_scan_error(tmp_path):
    from src.intranet_filename_monitor import main

    code = main(["--once", "--url", "http://127.0.0.1:1/", "--error-log-dir", str(tmp_path / "errors")])
    assert code == 1
    row = json.loads(next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8"))
    assert row["mode"] == "once"
    assert row["phase"] == "fetch_page"


def test_main_records_malformed_versions_config(tmp_path):
    from src.intranet_filename_monitor import main

    config = tmp_path / "versions.json"
    config.write_text("{broken", encoding="utf-8")
    code = main(["--once", "--versions-config", str(config), "--error-log-dir", str(tmp_path / "errors")])
    assert code == 1
    row = json.loads(next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8"))
    assert row["phase"] == "read_config"
    assert row["path"] == str(config)


def test_malformed_state_and_state_write_failure_are_recorded(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a.csv"})
    with __import__("pytest").raises(json.JSONDecodeError):
        run_once("http://example/", state, tmp_path / "logs", 1, error_log_dir=tmp_path / "errors")
    row = json.loads(next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8"))
    assert row["phase"] == "read_state"
    assert row["statePreserved"] is False

    monkeypatch.setattr("src.intranet_filename_monitor._write_state", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    state.unlink()
    with __import__("pytest").raises(OSError):
        run_once("http://example/", state, tmp_path / "logs", 1, error_log_dir=tmp_path / "errors")
    rows = [json.loads(line) for line in next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["phase"] == "write_state"
    assert rows[-1]["path"] == str(state)


def _listing_html(*names):
    links = "".join(f'<a href="{n}">{n}</a>' for n in names)
    return f"<html><title>Directory listing for /</title><h1>Directory listing for /</h1>{links}</html>"


def test_main_single_target_matches_legacy_behavior(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page",
        lambda url, timeout: (_listing_html("a.csv"), 100, 0.01))
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": [{"id": "intranet-root", "url": "http://example/"}]}), encoding="utf-8")
    args = ["--once", "--monitors-config", str(cfg), "--log-dir", str(tmp_path / "logs"),
            "--focus-log-dir", str(tmp_path / "focus"), "--error-log-dir", str(tmp_path / "errors")]
    assert main(args) == 0
    state = json.loads((tmp_path / "state" / "intranet-files-intranet-root.json").read_text(encoding="utf-8"))
    assert state["files"] == ["a.csv"]
    assert main(args) == 0  # second unchanged scan writes no diff log
    assert not (tmp_path / "logs").exists()


def test_main_multi_target_state_isolation(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    pages = {"http://a/": _listing_html("a.csv"), "http://b/": _listing_html("b.csv")}
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page",
        lambda url, timeout: (pages[url], len(pages[url]), 0.01))
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": [
        {"id": "t1", "url": "http://a/"}, {"id": "t2", "url": "http://b/"}]}), encoding="utf-8")
    args = ["--once", "--monitors-config", str(cfg), "--log-dir", str(tmp_path / "logs"),
            "--focus-log-dir", str(tmp_path / "focus"), "--error-log-dir", str(tmp_path / "errors")]
    assert main(args) == 0
    assert json.loads((tmp_path / "state" / "intranet-files-t1.json").read_text(encoding="utf-8"))["files"] == ["a.csv"]
    assert json.loads((tmp_path / "state" / "intranet-files-t2.json").read_text(encoding="utf-8"))["files"] == ["b.csv"]
    pages["http://a/"] = _listing_html("a.csv", "new.csv")
    assert main(args) == 0
    logs = list((tmp_path / "logs").glob("*.log"))
    assert len(logs) == 1
    content = logs[0].read_text(encoding="utf-8")
    assert "monitorId: t1" in content and "new.csv" in content
    assert json.loads((tmp_path / "state" / "intranet-files-t2.json").read_text(encoding="utf-8"))["files"] == ["b.csv"]


def test_main_single_target_failure_does_not_block_others(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    def fake_fetch(url, timeout):
        if url == "http://bad/":
            raise TimeoutError("offline")
        return _listing_html("b.csv"), 100, 0.01
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page", fake_fetch)
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": [
        {"id": "bad", "url": "http://bad/"}, {"id": "good", "url": "http://b/"}]}), encoding="utf-8")
    code = main(["--once", "--monitors-config", str(cfg), "--log-dir", str(tmp_path / "logs"),
                 "--focus-log-dir", str(tmp_path / "focus"), "--error-log-dir", str(tmp_path / "errors")])
    assert code == 1
    rows = [json.loads(line) for line in next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["monitorId"] == "bad" and rows[-1]["phase"] == "fetch_page"
    assert json.loads((tmp_path / "state" / "intranet-files-good.json").read_text(encoding="utf-8"))["files"] == ["b.csv"]


def test_main_records_broken_monitors_config(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not fetch")))
    cfg = tmp_path / "monitors.json"
    cfg.write_text("{broken", encoding="utf-8")
    code = main(["--once", "--monitors-config", str(cfg), "--error-log-dir", str(tmp_path / "errors")])
    assert code == 1
    row = json.loads(next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8"))
    assert row["phase"] == "read_config"
    assert row["path"] == str(cfg)
    assert not (tmp_path / "state").exists()


def test_main_records_missing_monitors_config(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not fetch")))
    missing = tmp_path / "no-such.json"
    code = main(["--once", "--monitors-config", str(missing), "--error-log-dir", str(tmp_path / "errors")])
    assert code == 1
    row = json.loads(next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8"))
    assert row["phase"] == "read_config"
    assert not (tmp_path / "state").exists()


def test_load_monitors_config_validation(tmp_path):
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": [
        {"id": "t1", "url": "http://a/", "profile": {"root_files": {"type": "link_set", "extension": ".csv"}}}]}), encoding="utf-8")
    assert load_monitors_config(cfg)[0]["id"] == "t1"
    cfg.write_text(json.dumps({"targets": [{"id": "t1"}, {"id": "t1", "url": "http://a/"}]}), encoding="utf-8")
    with __import__("pytest").raises(ValueError):
        load_monitors_config(cfg)
    cfg.write_text(json.dumps({"targets": []}), encoding="utf-8")
    assert load_monitors_config(cfg) == []


def _empty_versions_config(tmp_path):
    path = tmp_path / "versions.json"
    path.write_text(json.dumps({"selectedVersions": []}), encoding="utf-8")
    return path


def test_main_once_rejects_empty_monitors_config(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": []}), encoding="utf-8")
    assert main(["--once", "--monitors-config", str(cfg), "--versions-config", str(_empty_versions_config(tmp_path)),
                 "--error-log-dir", str(tmp_path / "errors")]) == 1
    row = json.loads(next((tmp_path / "errors").glob("*.log")).read_text(encoding="utf-8"))
    assert row["phase"] == "read_config"


def test_main_resident_exits_quietly_when_lock_is_live(tmp_path, monkeypatch, capsys):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    lock = tmp_path / "state" / "monitor-resident.lock"
    lock.parent.mkdir()
    lock.write_text(json.dumps({"pid": 123, "heartbeat": time.time(), "owner": "other"}), encoding="utf-8")
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page", lambda *_: (_ for _ in ()).throw(AssertionError("must not fetch")))
    assert main([]) == 0
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
    assert lock.exists()


def test_main_resident_takes_over_stale_lock(tmp_path, monkeypatch):
    import pytest
    from src.intranet_filename_monitor import main

    monkeypatch.chdir(tmp_path)
    lock = tmp_path / "state" / "monitor-resident.lock"
    lock.parent.mkdir()
    lock.write_text(json.dumps({"pid": 123, "heartbeat": time.time() - 10, "owner": "stale"}), encoding="utf-8")
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": [{"id": "t1", "url": "http://example/"}]}), encoding="utf-8")
    message = _triage_msg(tmp_path)
    seen = []
    def scan(*args, **kwargs):
        data = json.loads(lock.read_text(encoding="utf-8"))
        seen.append(data)
        return {"baseline": True, "count": 0, "log": None}
    monkeypatch.setattr("src.intranet_filename_monitor.run_once", scan)
    refreshed = []
    def stop_after_refresh(_):
        refreshed.append(json.loads(lock.read_text(encoding="utf-8")))
        raise KeyboardInterrupt()
    monkeypatch.setattr("src.intranet_filename_monitor.time.sleep", stop_after_refresh)
    with pytest.raises(KeyboardInterrupt):
        main(["--interval", "1", "--monitors-config", str(cfg), "--versions-config", str(_empty_versions_config(tmp_path)),
              "--triage-message-file", str(message)])
    assert seen and seen[0]["pid"] == os.getpid() and seen[0]["owner"] != "stale"
    assert refreshed[0]["owner"] == seen[0]["owner"]
    assert refreshed[0]["heartbeat"] >= seen[0]["heartbeat"]
    assert not lock.exists()


def test_main_resident_idles_for_empty_monitors_config(tmp_path, monkeypatch, capsys):
    import pytest
    from src.intranet_filename_monitor import main

    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": []}), encoding="utf-8")
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page", lambda *_: (_ for _ in ()).throw(AssertionError("must not fetch")))
    monkeypatch.setattr("src.intranet_filename_monitor.record_error", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not log")))
    monkeypatch.setattr("src.intranet_filename_monitor.wake_triage", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not wake")))
    monkeypatch.setattr("src.intranet_filename_monitor.time.sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        main(["--monitors-config", str(cfg), "--versions-config", str(_empty_versions_config(tmp_path)),
              "--triage-message-file", str(_triage_msg(tmp_path))])
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
    assert not (tmp_path / "state" / "monitor-resident.lock").exists()


def _triage_msg(tmp_path):
    msg = tmp_path / "triage-message.txt"
    msg.write_text("triage instruction", encoding="utf-8")
    return msg


def test_main_no_new_output_does_not_wake(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a.csv"})
    calls = []
    monkeypatch.setattr("src.intranet_filename_monitor.spawn_triage_agent", lambda *a, **k: calls.append(a) or True)
    argv = ["--once", "--url", "http://example/", "--triage-message-file", str(_triage_msg(tmp_path))]
    assert main(argv) == 0
    assert main(argv) == 0
    assert calls == []


def test_main_wakes_once_on_new_diff(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    values = iter([{"a.csv"}, {"a.csv", "b.csv"}])
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: next(values))
    calls = []
    monkeypatch.setattr("src.intranet_filename_monitor.spawn_triage_agent", lambda *a, **k: calls.append(a) or True)
    argv = ["--once", "--url", "http://example/", "--triage-message-file", str(_triage_msg(tmp_path))]
    assert main(argv) == 0
    assert calls == []
    assert main(argv) == 0
    assert len(calls) == 1


def test_main_wakes_on_scan_error(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames",
        lambda *_: (_ for _ in ()).throw(TimeoutError("offline")))
    calls = []
    monkeypatch.setattr("src.intranet_filename_monitor.spawn_triage_agent", lambda *a, **k: calls.append(a) or True)
    argv = ["--once", "--url", "http://example/", "--triage-message-file", str(_triage_msg(tmp_path))]
    assert main(argv) == 1
    assert len(calls) == 1
    assert list((tmp_path / "logs" / "intranet-error").glob("*.log"))


def test_main_merges_multi_target_wake_into_one(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    pages = iter([_listing_html("a.csv")] * 2 + [_listing_html("a.csv", "b.csv")] * 2)
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_page", lambda *_: (next(pages), 100, 0.1))
    calls = []
    monkeypatch.setattr("src.intranet_filename_monitor.spawn_triage_agent", lambda *a, **k: calls.append(a) or True)
    cfg = tmp_path / "monitors.json"
    cfg.write_text(json.dumps({"targets": [
        {"id": "t1", "url": "http://a/", "profile": {"root_files": {"type": "link_set", "extension": ".csv"}}},
        {"id": "t2", "url": "http://b/", "profile": {"root_files": {"type": "link_set", "extension": ".csv"}}}]}), encoding="utf-8")
    argv = ["--once", "--monitors-config", str(cfg), "--triage-message-file", str(_triage_msg(tmp_path))]
    assert main(argv) == 0
    assert calls == []
    assert main(argv) == 0
    assert len(calls) == 1


def test_wake_failure_queues_and_retry_clears_outbox(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    values = iter([{"a.csv"}, {"a.csv", "b.csv"}, {"a.csv", "b.csv"}, {"a.csv", "b.csv"}])
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: next(values))
    box = {"fail": True}
    monkeypatch.setattr("src.intranet_filename_monitor.spawn_triage_agent", lambda *a, **k: not box["fail"])
    argv = ["--once", "--url", "http://example/", "--triage-message-file", str(_triage_msg(tmp_path))]
    assert main(argv) == 0
    assert main(argv) == 0
    outbox = tmp_path / "state" / "openclaw-pending"
    queued = list(outbox.glob("*.json"))
    assert len(queued) == 1
    assert json.loads(queued[0].read_text(encoding="utf-8"))["event_id"]
    main(argv)
    assert len(list(outbox.glob("*.json"))) == 1
    box["fail"] = False
    main(argv)
    assert not list(outbox.glob("*.json"))


def test_wake_event_dedup_by_marks(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import wake_triage
    monkeypatch.setattr("src.intranet_filename_monitor.spawn_triage_agent", lambda *a, **k: False)
    outbox = tmp_path / "outbox"
    wake_triage(["diff:t1:x.log"], outbox, "msg")
    wake_triage(["diff:t1:x.log"], outbox, "msg")
    assert len(list(outbox.glob("*.json"))) == 1
    wake_triage(["diff:t1:y.log"], outbox, "msg")
    assert len(list(outbox.glob("*.json"))) == 2


def test_wake_disabled_when_message_file_missing(tmp_path, monkeypatch):
    from src.intranet_filename_monitor import main
    monkeypatch.chdir(tmp_path)
    values = iter([{"a.csv"}, {"a.csv", "b.csv"}])
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: next(values))
    calls = []
    monkeypatch.setattr("src.intranet_filename_monitor.spawn_triage_agent", lambda *a, **k: calls.append(a) or True)
    argv = ["--once", "--url", "http://example/", "--triage-message-file", str(tmp_path / "missing.txt")]
    assert main(argv) == 0
    assert main(argv) == 0
    assert calls == []
