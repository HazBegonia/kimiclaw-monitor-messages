"""Aggregate new intranet monitor logs and deliver them as email alerts."""
from __future__ import annotations
import argparse, json, smtplib, sys
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from zoneinfo import ZoneInfo

from src.intranet_filename_monitor import load_selected_versions

TIME_ZONE = ZoneInfo("Asia/Shanghai")
MONITOR_URL = "http://172.16.30.20:8011/"
DEFAULT_CONFIG = Path("config/smtp.local.json")
DEFAULT_STATE = Path("state/notify-state.json")
DEFAULT_DIFF_DIR = Path("logs/intranet-diff")
DEFAULT_FOCUS_DIR = Path("logs/intranet-focus")
DEFAULT_ERROR_DIR = Path("logs/intranet-error")
DEFAULT_VERSIONS_CONFIG = Path("config/intranet-versions.json")
MAX_DETAIL_LINES = 50
REQUIRED_CONFIG_KEYS = ("host", "port", "username", "auth_code", "from", "to")


def load_config(path: Path) -> dict | None:
    if not path.exists():
        print(f"未配置 SMTP（缺少 {path}），跳过邮件发送", file=sys.stderr)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"SMTP 配置 {path} 不是合法 JSON（{error}），跳过邮件发送", file=sys.stderr)
        return None
    missing = [k for k in REQUIRED_CONFIG_KEYS if not data.get(k)]
    if missing or not isinstance(data.get("to"), list):
        print(f"SMTP 配置 {path} 缺少字段 {missing or ['to(需为非空数组)']}，跳过邮件发送", file=sys.stderr)
        return None
    return data


def send(config: dict, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("内网监控", "utf-8")), config["from"]))
    msg["To"] = ", ".join(config["to"])
    msg["Date"] = datetime.now(TIME_ZONE).strftime("%a, %d %b %Y %H:%M:%S %z")
    with smtplib.SMTP_SSL(config["host"], int(config["port"]), timeout=30) as smtp:
        smtp.login(config["username"], config["auth_code"])
        smtp.sendmail(config["from"], list(config["to"]), msg.as_string())


def _try_send(config: dict, subject: str, body: str) -> bool:
    try:
        send(config, subject, body)
        print(f"已发送邮件：{subject}", flush=True)
        return True
    except Exception as error:
        print(f"邮件发送失败（{subject}）：{error}；本次不推进发送位置，下轮重试", file=sys.stderr, flush=True)
        return False


def load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"发送状态 {path} 损坏（{error}），将以当前位置为基线", file=sys.stderr)
        return None
    return {"diffCursor": str(data.get("diffCursor", "")), "errorCursor": data.get("errorCursor") or {"date": "", "offset": 0}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _latest_baseline(diff_dir: Path, error_dir: Path) -> dict:
    diffs = sorted(diff_dir.glob("*.log")) if diff_dir.exists() else []
    errors = sorted(error_dir.glob("*.log")) if error_dir.exists() else []
    error_cursor = {"date": "", "offset": 0}
    if errors:
        last = errors[-1]
        error_cursor = {"date": last.stem, "offset": last.stat().st_size}
    return {"diffCursor": diffs[-1].name if diffs else "", "errorCursor": error_cursor}


def _parse_diff_log(path: Path) -> dict:
    added, removed, changed_fields, detected_at = [], [], [], ""
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("detectedAt:"):
            detected_at = line.split(":", 1)[1].strip()
        elif line in ("added:", "removed:", "changedFields:"):
            section = line[:-1]
        elif line.startswith("- ") and section == "added":
            added.append(line[2:].strip())
        elif line.startswith("- ") and section == "removed":
            removed.append(line[2:].strip())
        elif line.startswith("- ") and section == "changedFields":
            field, _, raw = line[2:].partition(": ")
            try:
                value = json.loads(raw)
            except ValueError:
                value = None
            if isinstance(value, dict) and ("added" in value or "removed" in value):
                added.extend(value.get("added") or [])
                removed.extend(value.get("removed") or [])
            else:
                changed_fields.append(field)
    return {"added": added, "removed": removed, "changedFields": changed_fields, "detectedAt": detected_at}


def collect_new_diffs(diff_dir: Path, cursor: str) -> list[dict]:
    if not diff_dir.exists():
        return []
    out = []
    for path in sorted(diff_dir.glob("*.log")):
        if path.name > cursor:
            parsed = _parse_diff_log(path)
            parsed["path"] = path
            out.append(parsed)
    return out


def _clip(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_DETAIL_LINES:
        return lines
    return lines[:MAX_DETAIL_LINES] + [f"... 另有 {len(lines) - MAX_DETAIL_LINES} 条，见详情日志"]


def build_version_mail(batch: list[dict], versions: list[dict], focus_dir: Path, url: str) -> tuple[str, str]:
    added = sorted({name for item in batch for name in item["added"]})
    removed = sorted({name for item in batch for name in item["removed"]})
    changed_fields = sorted({f for item in batch for f in item["changedFields"]})
    times = sorted(item["detectedAt"] for item in batch if item["detectedAt"])
    parts = []
    if added:
        parts.append(f"新增 {len(added)} 个文件")
    if removed:
        parts.append(f"删除 {len(removed)} 个文件")
    if changed_fields:
        parts.append("字段变化: " + ", ".join(changed_fields))
    subject = "【内网监控】版本更新 · " + ("、".join(parts) if parts else "内容变化")
    lines = ["类型：版本变动", f"监控目标：{url}"]
    if times:
        lines.append(f"时间：{times[0]} ~ {times[-1]}")
    lines.append("")
    if added:
        lines += [f"新增（{len(added)}）："] + [f"- {name}" for name in _clip(added)] + [""]
    if removed:
        lines += [f"删除（{len(removed)}）："] + [f"- {name}" for name in _clip(removed)] + [""]
    if changed_fields:
        lines += ["字段变化："] + [f"- {name}" for name in changed_fields] + [""]
    version_lines = []
    for spec in versions:
        va = [name for name in added if spec["match"] in name]
        vr = [name for name in removed if spec["match"] in name]
        if not va and not vr:
            continue
        entry = f"- {spec['id']}：新增 {len(va)} / 删除 {len(vr)}"
        snapshots = sorted((focus_dir / spec["id"]).glob("*.log")) if (focus_dir / spec["id"]).exists() else []
        if snapshots:
            entry += f"（快照：{snapshots[-1]}）"
        version_lines.append(entry)
        version_lines += [f"  + {name}" for name in _clip(va)]
        version_lines += [f"  - {name}" for name in _clip(vr)]
    if version_lines:
        lines += ["版本明细："] + version_lines + [""]
    lines += ["详情日志："] + [f"- {p}" for p in _clip([str(item["path"]) for item in batch])]
    return subject, "\n".join(lines) + "\n"


def collect_new_errors(error_dir: Path, cursor: dict) -> tuple[list[dict], dict]:
    if not error_dir.exists():
        return [], cursor
    records, new_cursor = [], dict(cursor)
    for path in sorted(error_dir.glob("*.log")):
        if path.stem < str(cursor.get("date", "")):
            continue
        offset = int(cursor.get("offset", 0)) if path.stem == str(cursor.get("date", "")) else 0
        size = path.stat().st_size
        if size <= offset:
            continue
        with path.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            chunk = fh.read()
        for line in chunk.splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        new_cursor = {"date": path.stem, "offset": size}
    return records, new_cursor


def build_error_mail(records: list[dict], url: str) -> tuple[str, str]:
    groups: dict[tuple[str, str], dict] = {}
    for rec in records:
        key = (str(rec.get("errorType", "Unknown")), str(rec.get("phase", "")))
        group = groups.setdefault(key, {"count": 0, "first": "", "last": "", "message": "", "url": ""})
        group["count"] += 1
        at = str(rec.get("detectedAt", ""))
        if not group["first"] or at < group["first"]:
            group["first"] = at
        if at > group["last"]:
            group["last"] = at
        if not group["message"]:
            group["message"] = str(rec.get("message", ""))
        if not group["url"]:
            group["url"] = str(rec.get("url") or "")
    total = sum(g["count"] for g in groups.values())
    if len(groups) == 1:
        (error_type, _), group = next(iter(groups.items()))
        subject = f"【内网监控】监控异常 · {error_type} ×{group['count']}"
    else:
        subject = f"【内网监控】监控异常 · {len(groups)} 类共 {total} 条"
    lines = ["类型：监控异常", f"监控目标：{url}"]
    times = sorted(g["first"] for g in groups.values() if g["first"])
    if times:
        lines.append(f"时间窗口：{times[0]} ~ {max(g['last'] for g in groups.values())}")
    lines.append("")
    for (error_type, phase), group in sorted(groups.items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"{error_type}（{phase}）×{group['count']}")
        lines.append(f"  首次：{group['first']}  末次：{group['last']}")
        if group["message"]:
            lines.append(f"  示例：{group['message']}")
        if group["url"]:
            lines.append(f"  地址：{group['url']}")
        lines.append("")
    lines.append(f"共 {total} 条新错误，{len(groups)} 类。详见日志目录 logs/intranet-error/")
    return subject, "\n".join(lines) + "\n"


def send_test(config: dict) -> bool:
    now = datetime.now(TIME_ZONE).isoformat()
    body = ("这是内网监控告警链路的测试邮件。\n"
            f"发件账号：{config['username']}\n"
            "如收到本邮件，说明 SMTP 配置与投递链路正常。\n"
            f"时间：{now}\n")
    return _try_send(config, "【内网监控】测试邮件 · 链路正常", body)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--state", type=Path, default=DEFAULT_STATE)
    p.add_argument("--diff-dir", type=Path, default=DEFAULT_DIFF_DIR)
    p.add_argument("--focus-dir", type=Path, default=DEFAULT_FOCUS_DIR)
    p.add_argument("--error-dir", type=Path, default=DEFAULT_ERROR_DIR)
    p.add_argument("--versions-config", type=Path, default=DEFAULT_VERSIONS_CONFIG)
    p.add_argument("--url", default=MONITOR_URL)
    p.add_argument("--test", action="store_true", help="发送一封测试邮件后退出（不影响发送状态）")
    a = p.parse_args(argv)
    config = load_config(a.config)
    if config is None:
        return 0
    if a.test:
        return 0 if send_test(config) else 1
    state = load_state(a.state)
    if state is None:
        save_state(a.state, _latest_baseline(a.diff_dir, a.error_dir))
        print("首次运行：已记录当前日志位置为基线，历史内容不补发", flush=True)
        return 0
    sent = 0
    batch = collect_new_diffs(a.diff_dir, state["diffCursor"])
    if batch:
        try:
            versions = load_selected_versions(a.versions_config)
        except Exception as error:
            print(f"版本配置读取失败（{error}），按无版本明细发送", file=sys.stderr)
            versions = []
        subject, body = build_version_mail(batch, versions, a.focus_dir, a.url)
        if _try_send(config, subject, body):
            state["diffCursor"] = batch[-1]["path"].name
            save_state(a.state, state)
            sent += 1
    records, new_error_cursor = collect_new_errors(a.error_dir, state["errorCursor"])
    if records:
        subject, body = build_error_mail(records, a.url)
        if _try_send(config, subject, body):
            state["errorCursor"] = new_error_cursor
            save_state(a.state, state)
            sent += 1
    if not sent:
        print("没有新的变动或异常，未发送邮件", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
