import json
from datetime import datetime
from pathlib import Path

from src.intranet_filename_monitor import (diff_filenames, filter_version_files,
    load_selected_versions, parse_filenames, run_once, write_diff_log, validate_page)


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
    run_once("http://example/", state, logs, 1)
    monkeypatch.setattr(
        "src.intranet_filename_monitor.fetch_filenames",
        lambda *_: (_ for _ in ()).throw(TimeoutError("offline")),
    )
    try:
        run_once("http://example/", state, logs, 1)
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

def test_selected_version_writes_snapshot_on_unchanged_scans(tmp_path, monkeypatch):
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a_103300110002.csv"})
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    versions = [{"id": "103300110002", "match": "103300110002"}]
    first = run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=tmp_path / "focus")
    second = run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=tmp_path / "focus")
    snapshots = sorted((tmp_path / "focus" / "103300110002").glob("*.log"))
    assert first["versionLogs"] and second["versionLogs"]
    assert len(snapshots) == 2
    assert "a_103300110002.csv" in snapshots[-1].read_text(encoding="utf-8")
    assert not logs.exists()

def test_failed_scan_does_not_write_version_snapshot(tmp_path, monkeypatch):
    state, logs = tmp_path / "state.json", tmp_path / "logs"
    versions = [{"id": "v1", "match": "1033"}]
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: {"a_1033.csv"})
    run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=tmp_path / "focus")
    monkeypatch.setattr("src.intranet_filename_monitor.fetch_filenames", lambda *_: (_ for _ in ()).throw(TimeoutError("offline")))
    try:
        run_once("http://example/", state, logs, 1, selected_versions=versions, focus_log_dir=tmp_path / "focus")
    except TimeoutError:
        pass
    assert len(list((tmp_path / "focus" / "v1").glob("*.log"))) == 1
