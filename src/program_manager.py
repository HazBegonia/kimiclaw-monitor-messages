from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.io import Output, ProgramOutput

ROOT = Path(__file__).resolve().parent.parent
PROGRAM = ROOT / "program"
LOGS = ROOT / "logs/program-control"
TEMPLATE = ROOT / "config/program-output-template.json"
load_dotenv(PROGRAM / ".env")


def registered() -> list[str]:
    raw = os.getenv("BASH", "").strip()
    if not raw:
        return []
    items = json.loads(raw) if raw.startswith("[") else raw.replace(",", " ").split()
    return [Path(item).name for item in items]


def pids(script: str) -> list[int]:
    pattern = rf"bash .*program/{re.escape(script)}"
    result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(pid) for pid in result.stdout.split()]


def running() -> list[dict]:
    return [
        {"script": script, "pid": pid}
        for script in registered()
        for pid in pids(script)
    ]


def add_message(result: dict, key: str, output: str = "", **values) -> dict:
    return ProgramOutput(TEMPLATE).message(result, key, output, **values)


def write_log(
    event: str,
    script: str | None,
    result: str,
    pid: list[int] | None = None,
    *,
    question: str | None = None,
    error: str = "",
) -> None:
    fields = {
        "event": event,
        "script": script,
        "question": question,
        "pids": pid or [],
        "result": result,
        "running": running(),
    }
    if error:
        fields["error"] = error
    Output.write_jsonl(
        LOGS,
        fields,
        now=datetime.now(timezone.utc).astimezone(),
        time_field="time",
        timespec="seconds",
    )


def check_script(script: str) -> str:
    script = Path(script).name
    if script not in registered() or not (PROGRAM / script).is_file():
        raise ValueError(f"脚本未在 program/.env 的 BASH 中注册：{script}")
    return script


def status() -> dict:
    current = running()
    scripts = registered()
    return {
        "ok": True,
        "registered": scripts,
        "running": current,
        "message": ProgramOutput(TEMPLATE).status(scripts, current),
    }


def start(script: str, arguments: list[str], *, question: str | None = None) -> dict:
    script = check_script(script)
    existing = pids(script)
    if existing:
        write_log("start", script, "already_running", existing, question=question)
        return add_message(
            {"ok": True, "script": script, "alreadyRunning": True, "pids": existing},
            "alreadyRunning", script=script, pids=",".join(map(str, existing)),
        )
    output_dir = LOGS / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{script}-{int(time.time())}.log"
    with output.open("ab") as file:
        process = subprocess.Popen(
            ["/bin/bash", str(PROGRAM / script), *arguments],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    write_log("start", script, "started", [process.pid], question=question)
    time.sleep(0.1)
    preview = output.read_text(encoding="utf-8", errors="replace")[-2000:]
    return add_message(
        {
            "ok": True,
            "script": script,
            "alreadyRunning": False,
            "process": {"pid": process.pid, "status": "running", "outputLog": str(output)},
        },
        "started", output=preview, script=script, pid=process.pid,
    )


def stop(script: str, *, question: str | None = None) -> dict:
    script = check_script(script)
    existing = pids(script)
    if not existing:
        write_log("stop", script, "not_running", question=question)
        return add_message(
            {"ok": True, "script": script, "stopped": False, "reason": "not_running"},
            "notRunning", script=script,
        )
    for pid in existing:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(50):
        if not pids(script):
            break
        time.sleep(0.1)
    stopped = not pids(script)
    write_log("stop", script, "stopped" if stopped else "stop_timeout", existing, question=question)
    return add_message(
        {"ok": True, "script": script, "stopped": stopped, "pids": existing},
        "stopped" if stopped else "stopTimeout",
        script=script, pids=",".join(map(str, existing)),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", help="original user request to include in the operation log")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    start_parser = commands.add_parser("start")
    start_parser.add_argument("script")
    start_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    stop_parser = commands.add_parser("stop")
    stop_parser.add_argument("script")
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = status()
            write_log("status", None, "ok", question=args.question)
        elif args.command == "start":
            result = start(args.script, args.arguments, question=args.question)
        else:
            result = stop(args.script, question=args.question)
        Output.emit_result(result)
        return 0
    except (ValueError, OSError) as error:
        write_log(
            args.command,
            getattr(args, "script", None),
            "error",
            question=args.question,
            error=str(error),
        )
        result = ProgramOutput(TEMPLATE).message(
            {"ok": False, "error": str(error)}, "error", error=error
        )
        Output.emit_result(result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
