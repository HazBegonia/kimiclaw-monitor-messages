import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src import program_manager

ROOT = Path(__file__).resolve().parent.parent
DAEMON_SCRIPT = """#!/usr/bin/env bash
trap 'exit 0' TERM
while true; do
  sleep 1
done
"""


def script(tmp_path, content=DAEMON_SCRIPT):
    program = tmp_path / "program"
    program.mkdir(exist_ok=True)
    (program / "worker.sh").write_text(content, encoding="utf-8")
    return program / "worker.sh"


def use_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(program_manager, "ROOT", tmp_path)
    monkeypatch.setattr(program_manager, "PROGRAM", tmp_path / "program")
    monkeypatch.setattr(program_manager, "LOGS", tmp_path / "logs/program-control")
    monkeypatch.setenv("BASH", "worker.sh")


def test_for_each_registered_script_finds_running_process(tmp_path, monkeypatch):
    entry = script(tmp_path)
    use_manager(tmp_path, monkeypatch)
    monkeypatch.setenv("BASH", '["worker.sh","idle.sh"]')
    process = subprocess.Popen(
        ["/bin/bash", str(entry)], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        result = program_manager.status()
        assert result["registered"] == ["worker.sh", "idle.sh"]
        assert result["running"] == [{"script": "worker.sh", "pid": process.pid}]
    finally:
        os.kill(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def test_start_checks_running_then_stops(tmp_path, monkeypatch):
    script(tmp_path)
    use_manager(tmp_path, monkeypatch)
    started = program_manager.start("worker.sh", [])
    try:
        duplicate = program_manager.start("worker.sh", [])
        assert duplicate["alreadyRunning"] is True
        assert duplicate["pids"] == [started["process"]["pid"]]
        assert program_manager.status()["running"][0]["pid"] == started["process"]["pid"]
    finally:
        stopped = program_manager.stop("worker.sh")
    assert stopped["stopped"] is True
    assert program_manager.status()["running"] == []


def test_arguments_are_not_interpreted_as_shell_commands(tmp_path, monkeypatch, capsys):
    script(tmp_path, "#!/usr/bin/env bash\nprintf '<%s>\\n' \"$@\"\n")
    use_manager(tmp_path, monkeypatch)
    marker = tmp_path / "not-created"
    value = f"plain; touch {marker}"
    result = program_manager.start("worker.sh", ["a b", value])
    time.sleep(0.1)
    output = Path(result["process"]["outputLog"]).read_text(encoding="utf-8")
    assert "<a b>" in output and f"<{value}>" in output
    assert "启动成功" in result["message"]
    assert "<a b>" in result["message"] and f"<{value}>" in result["message"]
    assert not marker.exists()


def test_json_template_controls_message(tmp_path, monkeypatch):
    script(tmp_path)
    use_manager(tmp_path, monkeypatch)
    template = tmp_path / "template.json"
    template.write_text(json.dumps({
        "started": "自定义启动：{{script}} / {{pid}}",
        "separator": "\n",
        "output": "自定义输出：{{output}}",
        "stopped": "自定义停止：{{script}} / {{pids}}",
    }), encoding="utf-8")
    monkeypatch.setattr(program_manager, "TEMPLATE", template)
    result = program_manager.start("worker.sh", [])
    try:
        assert result["message"].startswith(f"自定义启动：worker.sh / {result['process']['pid']}")
    finally:
        program_manager.stop("worker.sh")


def test_unregistered_script_is_rejected(tmp_path, monkeypatch):
    script(tmp_path)
    use_manager(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="未在"):
        program_manager.start("other.sh", [])


def test_claw_cli_status_start_stop(tmp_path):
    program = tmp_path / "program"
    program.mkdir()
    (program / "worker.sh").write_text(DAEMON_SCRIPT, encoding="utf-8")
    env = os.environ.copy()
    env["BASH"] = "worker.sh"
    command = [
        sys.executable,
        "-c",
        "import sys; from src import program_manager as m; m.ROOT=m.Path('%s'); m.PROGRAM=m.ROOT/'program'; m.LOGS=m.ROOT/'logs/program-control'; sys.argv=['program_manager', *sys.argv[1:]]; raise SystemExit(m.main())" % tmp_path,
    ]
    started = subprocess.run(
        [*command, "--question", "请启动 worker 脚本", "start", "worker.sh"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    assert json.loads(started.stdout)["process"]["status"] == "running"
    stopped = subprocess.run(
        [*command, "--question", "请停止 worker 脚本", "stop", "worker.sh"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert stopped.returncode == 0
    assert json.loads(stopped.stdout)["stopped"] is True

    failed = subprocess.run(
        [*command, "--question", "启动未注册脚本", "start", "missing.sh"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert failed.returncode == 1
    log_files = list((tmp_path / "logs/program-control").glob("*.log"))
    assert len(log_files) == 1
    records = [json.loads(line) for line in log_files[0].read_text(encoding="utf-8").splitlines()]
    assert [record["question"] for record in records] == [
        "请启动 worker 脚本", "请停止 worker 脚本", "启动未注册脚本",
    ]
    assert records[-1]["result"] == "error"
    assert "未在" in records[-1]["error"]
