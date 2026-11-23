from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
MARKDOWN_LIMIT_BYTES = int(os.getenv("MARKDOWN_LIMIT_BYTES", "20480"))
SECTION_LIMIT = int(os.getenv("SECTION_LIMIT", "15"))
ERROR_LINE_LIMIT = int(os.getenv("ERROR_LINE_LIMIT", "80"))
TIME_ZONE = ZoneInfo(os.getenv("TIME_ZONE", "Asia/Shanghai"))


class Output:
    PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9]*)\s*}}")

    @staticmethod
    def load_json_template(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"output template must be an object: {path}")
        return data

    @classmethod
    def fill_template(cls, text: str, values: dict[str, Any]) -> str:
        return cls.PLACEHOLDER_RE.sub(lambda match: str(values[match.group(1)]), text)

    @staticmethod
    def write_jsonl(
        log_dir: Path,
        fields: dict[str, Any],
        *,
        now: datetime,
        time_field: str | None,
        timespec: str = "microseconds",
    ) -> Path:
        log_dir.mkdir(parents=True, exist_ok=True)
        record = dict(fields)
        if time_field is not None:
            record = {time_field: now.isoformat(timespec=timespec), **record}
        target = log_dir / f"{now:%Y-%m-%d}.log"
        with target.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return target

    @staticmethod
    def emit_text(text: str, *, error: bool = False) -> None:
        print(text, file=sys.stderr if error else sys.stdout, flush=True)

    @classmethod
    def emit_result(cls, result: dict[str, Any]) -> None:
        cls.emit_text(result["message"], error=True)
        print(json.dumps(result, ensure_ascii=False))


class ProgramOutput(Output):
    def __init__(self, template_path: Path):
        self.template_path = template_path

    def message(
        self,
        result: dict[str, Any],
        key: str,
        output: str = "",
        **values: Any,
    ) -> dict[str, Any]:
        template = self.load_json_template(self.template_path)
        message = self.fill_template(template[key], values)
        if output:
            message += template["separator"] + self.fill_template(
                template["output"], {"output": output}
            )
        result["message"] = message
        return result

    def status(self, registered: list[str], running: list[dict[str, Any]]) -> str:
        template = self.load_json_template(self.template_path)
        lines = [
            self.fill_template(template["statusHeader"], {}),
            self.fill_template(
                template["statusRegistered"], {"registered": "、".join(registered) or "无"}
            ),
        ]
        if running:
            lines.append(self.fill_template(template["statusRunning"], {"count": len(running)}))
            lines.extend(self.fill_template(template["statusItem"], item) for item in running)
        else:
            lines.append(self.fill_template(template["statusEmpty"], {}))
        return template["separator"].join(lines)


class IntranetOutput(Output):
    TEXT_FIELDS = {
        "header": {"timestamp"},
        "source": {"sourceUrl"},
        "errorWithTime": {"time", "phase", "errorType", "message"},
        "errorWithoutTime": {"phase", "errorType", "message"},
        "suppressed": {"count"},
        "truncated": set(),
    }
    SECTION_FIELDS = {
        "title": {"count"},
        "item": {"item"},
        "overflow": {"omitted", "count"},
    }

    def __init__(self, template: dict[str, Any]):
        self.template = template

    @classmethod
    def from_file(cls, path: Path) -> IntranetOutput:
        data = cls.load_json_template(path)
        expected = set(cls.TEXT_FIELDS) | {"separator", "sections"}
        template = cls._validate_keys(data, expected, "message template")
        for field, allowed in cls.TEXT_FIELDS.items():
            cls._validate_placeholders(template[field], allowed, f"template.{field}")
        cls._validate_placeholders(template["separator"], set(), "template.separator")
        sections = template["sections"]
        if not isinstance(sections, list):
            raise ValueError("template.sections must be an array")
        seen_types: set[str] = set()
        for index, raw_section in enumerate(sections):
            context = f"template.sections[{index}]"
            section = cls._validate_keys(raw_section, {"type", *cls.SECTION_FIELDS}, context)
            section_type = section["type"]
            if section_type not in {"added", "removed", "errors"}:
                raise ValueError(f"{context}.type must be added, removed, or errors")
            if section_type in seen_types:
                raise ValueError(f"template.sections contains duplicate type: {section_type}")
            seen_types.add(section_type)
            for field, allowed in cls.SECTION_FIELDS.items():
                cls._validate_placeholders(section[field], allowed, f"{context}.{field}")
        return cls(template)

    @staticmethod
    def _validate_keys(value: Any, expected: set[str], context: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{context} must be an object")
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        if missing or unknown:
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown: {', '.join(unknown)}")
            raise ValueError(f"{context} has invalid fields ({'; '.join(details)})")
        return value

    @classmethod
    def _validate_placeholders(cls, text: Any, allowed: set[str], context: str) -> None:
        if not isinstance(text, str):
            raise ValueError(f"{context} must be a string")
        for name in cls.PLACEHOLDER_RE.findall(text):
            if name not in allowed:
                raise ValueError(f"{context} uses unsupported placeholder: {{{{{name}}}}}")
        remainder = cls.PLACEHOLDER_RE.sub("", text)
        if "{{" in remainder or "}}" in remainder:
            raise ValueError(f"{context} contains a malformed placeholder")

    def _error_line(self, fact: dict[str, Any]) -> str:
        values = {
            "time": "",
            "phase": fact.get("phase") or "",
            "errorType": fact.get("errorType") or "",
            "message": fact.get("message") or "",
        }
        field = "errorWithoutTime"
        detected_at = fact.get("detectedAt")
        if detected_at:
            try:
                parsed = datetime.fromisoformat(str(detected_at).replace("Z", "+00:00"))
                values["time"] = f"{parsed:%H:%M}"
                field = "errorWithTime"
            except ValueError:
                pass
        line = self.fill_template(self.template[field], values)
        max_len = ERROR_LINE_LIMIT - 2
        return line if len(line) <= max_len else line[:max_len]

    def _format_section(self, section: dict[str, Any], items: list[str], cap: int) -> str:
        lines = []
        title = self.fill_template(section["title"], {"count": len(items)})
        if title:
            lines.append(title)
        for item in items[:cap]:
            rendered = self.fill_template(section["item"], {"item": item})
            if rendered:
                lines.append(rendered)
        if len(items) > cap:
            overflow = self.fill_template(
                section["overflow"], {"omitted": len(items) - cap, "count": len(items)}
            )
            if overflow:
                lines.append(overflow)
        return "\n".join(lines)

    @staticmethod
    def _utf8_prefix(text: str, limit: int) -> str:
        return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")

    def render(
        self,
        important_diffs: list[dict[str, Any]],
        important_errors: list[dict[str, Any]],
        source_url: str,
    ) -> str:
        timestamp = ""
        all_detected = [
            fact.get("detectedAt")
            for fact in important_diffs + important_errors
            if fact.get("detectedAt")
        ]
        if all_detected:
            newest = str(max(all_detected))
            try:
                timestamp = datetime.fromisoformat(newest.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                timestamp = newest

        items_by_type = {
            "added": sorted({name for fact in important_diffs for name in fact.get("added", [])}),
            "removed": sorted({name for fact in important_diffs for name in fact.get("removed", [])}),
            "errors": [self._error_line(fact) for fact in important_errors],
        }
        suppressed = sum(int(fact.get("suppressedFilenames") or 0) for fact in important_diffs)

        def build(cap: int) -> str:
            parts = []
            header = self.fill_template(self.template["header"], {"timestamp": timestamp})
            if header:
                parts.append(header)
            if source_url:
                source = self.fill_template(self.template["source"], {"sourceUrl": source_url})
                if source:
                    parts.append(source)
            for section in self.template["sections"]:
                items = items_by_type[section["type"]]
                if items:
                    rendered = self._format_section(section, items, cap)
                    if rendered:
                        parts.append(rendered)
            if suppressed:
                note = self.fill_template(self.template["suppressed"], {"count": suppressed})
                if note:
                    parts.append(note)
            return self.template["separator"].join(parts)

        for cap in (SECTION_LIMIT, 12, 10, 8, 6, 4, 3, 2, 1):
            body = build(cap)
            if len(body.encode("utf-8")) <= MARKDOWN_LIMIT_BYTES:
                return body
        suffix = (
            self.template["separator"] + self.template["truncated"]
            if self.template["truncated"]
            else ""
        )
        suffix_bytes = len(suffix.encode("utf-8"))
        if suffix_bytes >= MARKDOWN_LIMIT_BYTES:
            return self._utf8_prefix(suffix, MARKDOWN_LIMIT_BYTES)
        return self._utf8_prefix(build(0), MARKDOWN_LIMIT_BYTES - suffix_bytes) + suffix


class ChatLogger(Output):
    def __init__(
        self,
        sessions_dir: Path = Path.home() / ".openclaw/agents/main/sessions",
        log_dir: Path = Path("logs/chat"),
        template_path: Path = Path("config/chat-log-template.json"),
    ):
        self.sessions_dir = sessions_dir
        self.log_dir = log_dir
        self.template_path = template_path

    @staticmethod
    def _text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(part["text"])
                for part in content
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
            )
        return ""

    def _session_files(self) -> list[Path]:
        index_path = self.sessions_dir / "sessions.json"
        if not index_path.exists():
            return []
        index = json.loads(index_path.read_text(encoding="utf-8"))
        session_ids: set[str] = set()
        for entry in index.values():
            if not isinstance(entry, dict) or entry.get("channel") != "wecom":
                continue
            session_id = entry.get("sessionId")
            if isinstance(session_id, str):
                session_ids.add(session_id)
            history = entry.get("usageFamilySessionIds")
            if isinstance(history, list):
                session_ids.update(item for item in history if isinstance(item, str))
        return [
            path
            for session_id in sorted(session_ids)
            for path in sorted(self.sessions_dir.glob(f"{session_id}.jsonl*"))
            if path.is_file()
        ]

    def _pairs(self, path: Path) -> list[dict[str, Any]]:
        session_id = path.name.split(".jsonl", 1)[0]
        pairs = []
        pending: dict[str, Any] | None = None
        with path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "message":
                    continue
                message = event.get("message")
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                if role == "user":
                    pending = event
                elif role == "assistant" and pending is not None:
                    answer = self._text(message)
                    if not answer.strip():
                        continue
                    question_event = pending
                    pending = None
                    pairs.append({
                        "questionTime": question_event.get("timestamp"),
                        "answerTime": event.get("timestamp"),
                        "sessionId": session_id,
                        "questionId": question_event.get("id"),
                        "answerId": event.get("id"),
                        "question": self._text(question_event["message"]),
                        "answer": answer,
                    })
        return pairs

    def _seen_answers(self) -> set[str]:
        seen = set()
        if not self.log_dir.exists():
            return seen
        for path in self.log_dir.glob("*.log"):
            with path.open(encoding="utf-8") as file:
                for line in file:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    answer_id = record.get("answerId")
                    if isinstance(answer_id, str):
                        seen.add(answer_id)
        return seen

    def _render(self, pair: dict[str, Any], template: dict[str, Any]) -> dict[str, str]:
        if "answerId" not in template:
            raise ValueError("chat log template requires answerId for deduplication")
        return {
            field: self.fill_template(text, pair)
            for field, text in template.items()
        }

    def sync(self) -> int:
        seen = self._seen_answers()
        pairs = [
            pair
            for path in self._session_files()
            for pair in self._pairs(path)
            if pair.get("answerId") not in seen
        ]
        if not pairs:
            return 0
        template = self.load_json_template(self.template_path)
        written = 0
        for pair in sorted(pairs, key=lambda item: str(item["answerTime"])):
            try:
                answered_at = datetime.fromisoformat(
                    str(pair["answerTime"]).replace("Z", "+00:00")
                ).astimezone(TIME_ZONE)
            except ValueError:
                continue
            record = self._render(pair, template)
            self.write_jsonl(self.log_dir, record, now=answered_at, time_field=None)
            written += 1
        return written


def main() -> int:
    Output.emit_text(f"chat log: added {ChatLogger().sync()} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
