"""Resident polling monitor for configurable fields in an intranet HTML page."""
from __future__ import annotations
import argparse, fnmatch, hashlib, json, os, re, shutil, subprocess, sys, time, uuid
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

DEFAULT_URL="http://172.16.30.20:8011/"; DEFAULT_INTERVAL=5.0; DEFAULT_TIMEOUT=10.0; TIME_ZONE=ZoneInfo("Asia/Shanghai")
DEFAULT_ERROR_LOG_DIR = Path("logs/intranet-error")
ERROR_LOG_RETENTION_DAYS = 30
ERROR_LOG_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_TRIAGE_MESSAGE_FILE = Path("config/triage-message.txt")
WAKE_GRACE_SECONDS = 15.0
RESIDENT_LOCK_PATH = Path("state/monitor-resident.lock")

class PageValidationError(RuntimeError):
    """Raised when a fetched page is not a valid directory listing."""

class _DirectoryLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.hrefs=[]; self.title=False; self.h1=False; self.title_text=[]; self.h1_text=[]
    def handle_starttag(self, tag, attrs):
        tag=tag.lower()
        if tag=="a":
            href=dict(attrs).get("href")
            if href:self.hrefs.append(href)
        elif tag=="title": self.title=True
        elif tag=="h1": self.h1=True
    def handle_endtag(self, tag):
        if tag.lower()=="title": self.title=False
        elif tag.lower()=="h1": self.h1=False
    def handle_data(self, data):
        if self.title: self.title_text.append(data)
        if self.h1: self.h1_text.append(data)

def parse_filenames(html: str, base_url: str=DEFAULT_URL)->set[str]:
    p=_DirectoryLinkParser(); p.feed(html); base=urlsplit(base_url); root=base.path.rstrip("/") or "/"; out=set()
    for href in p.hrefs:
        a=urlsplit(urljoin(base_url,href))
        if (a.scheme,a.netloc)!=(base.scheme,base.netloc) or a.query or a.fragment or a.path.endswith("/"): continue
        if not a.path.startswith(root.rstrip("/")+"/"): continue
        rel=unquote(a.path[len(root.rstrip("/"))+1:])
        if rel and "/" not in rel and rel.lower().endswith(".csv"): out.add(rel)
    return out

def parse_fields(html: str, base_url: str=DEFAULT_URL, profile: dict|None=None)->dict[str,object]:
    profile=profile or {"root_files":{"type":"link_set","extension":".csv"}}; out={}; parser=_DirectoryLinkParser(); parser.feed(html); parser.close()
    for name in profile:
        spec=profile[name] or {}
        kind=spec.get("type","link_set") if isinstance(spec,dict) else "link_set"
        if name=="root_files" and kind=="link_set": out[name]=sorted(parse_filenames(html,base_url))
        elif kind=="text" and name in {"title","h1"}:
            values=parser.title_text if name=="title" else parser.h1_text; out[name]=" ".join("".join(values).split())
        else: raise ValueError(f"unsupported field: {name}")
    return out

def validate_page(html: str, *, min_links: int = 0) -> None:
    parser = _DirectoryLinkParser(); parser.feed(html); parser.close()
    title = " ".join("".join(parser.title_text).split())
    h1 = " ".join("".join(parser.h1_text).split())
    if "Directory listing for" not in title or "Directory listing for" not in h1:
        raise PageValidationError("page signature validation failed")
    if not html.rstrip().lower().endswith("</html>"):
        raise PageValidationError("incomplete HTML page")
    if not parser.hrefs or len(parser.hrefs) < min_links:
        raise PageValidationError("page has too few links")

def fingerprint(snapshot: dict[str,object])->str:
    return hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def diff_filenames(previous: Iterable[str], current: Iterable[str])->dict[str,list[str]]:
    old,new=set(previous),set(current); return {"added":sorted(new-old),"removed":sorted(old-new)}

def diff_snapshots(previous: dict[str, object], current: dict[str, object]) -> dict[str, object]:
    changed = {}
    for key in sorted(set(previous) | set(current)):
        if previous.get(key) == current.get(key):
            continue
        if key == "root_files":
            changed[key] = diff_filenames(previous.get(key, []), current.get(key, []))
        else:
            changed[key] = {"previous": previous.get(key), "current": current.get(key)}
    return changed

def _read_state(path: Path):
    if not path.exists(): return None
    d=json.loads(path.read_text(encoding="utf-8"))
    if "snapshot" in d:return d
    files=d.get("files")
    if isinstance(files,list) and all(isinstance(x,str) for x in files):
        s={"root_files":sorted(files)}; return {"snapshot":s,"fingerprint":fingerprint(s),"files":sorted(files)}
    raise ValueError(f"invalid state file: {path}")

def _atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True,exist_ok=True); t=path.with_name(path.name+f".tmp-{time.time_ns()}")
    try:t.write_text(content,encoding="utf-8",newline="\n"); t.replace(path)
    finally:
        if t.exists():t.unlink()

def _redact(value: object, limit: int = 500) -> str:
    """Return a short, credential-free diagnostic string."""
    text = str(value or "")
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(token|authorization|api[_-]?key|password)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", text)
    return text[:limit]

def _safe_url(url: str) -> str:
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        if p.port:
            host = f"{host}:{p.port}"
        return p._replace(netloc=host, query="", fragment="").geturl()
    except Exception:
        return _redact(url, 300)

def _cleanup_error_logs(log_dir: Path, now: datetime, protected: Path | None = None) -> None:
    """Best-effort 30-day and 100MB retention for daily error logs."""
    try:
        files = sorted(log_dir.glob("*.log"))
        cutoff = now.timestamp() - ERROR_LOG_RETENTION_DAYS * 86400
        for path in files:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        files = sorted((p for p in log_dir.glob("*.log") if p.exists()), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= ERROR_LOG_MAX_BYTES:
                break
            if protected is not None and path == protected:
                continue
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
    except Exception:
        return

def record_error(error_log_dir: Path, *, monitor_id: str, mode: str, phase: str,
                 error: BaseException, url: str | None = None, path: Path | None = None,
                 state_preserved: bool = False, retryable: bool = True,
                 detected_at: datetime | None = None,
                 written_paths: Iterable[str] | None = None) -> dict[str, object] | None:
    """Persist one raw technical error; fall back to stderr if persistence fails."""
    dt = detected_at or datetime.now(TIME_ZONE)
    record = {
        "eventId": uuid.uuid4().hex,
        "detectedAt": dt.isoformat(),
        "monitorId": _redact(monitor_id, 120),
        "mode": mode,
        "phase": phase,
        "errorType": type(error).__name__,
        "message": _redact(error),
        "path": _redact(path, 300) if path else None,
        "url": _safe_url(url) if url else None,
        "statePreserved": bool(state_preserved),
        "retryable": bool(retryable),
    }
    if written_paths:
        record["writtenPaths"] = [_redact(item, 300) for item in written_paths]
    try:
        error_log_dir.mkdir(parents=True, exist_ok=True)
        target = error_log_dir / f"{dt.strftime('%Y-%m-%d')}.log"
        with target.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        _cleanup_error_logs(error_log_dir, dt, target)
        return record
    except Exception as log_error:
        print(f"scan error ({phase}): {_redact(error)}; error log unavailable: {_redact(log_error)}", file=sys.stderr, flush=True)
        return None

def _write_state(path: Path, snapshot: dict[str,object], checked_at: datetime, version_files: dict[str, list[str]] | None = None):
    d={"checkedAt":checked_at.isoformat(),"snapshot":snapshot,"fingerprint":fingerprint(snapshot)}
    if "root_files" in snapshot:d["files"]=snapshot["root_files"]
    if version_files:d["versionFiles"]={k:sorted(v) for k,v in version_files.items()}
    _atomic_write(path,json.dumps(d,ensure_ascii=False,indent=2)+"\n")

def _next_log_path(log_dir: Path, dt: datetime)->Path:
    s=dt.strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]; p=log_dir/f"{s}.log"; i=1
    while p.exists():p=log_dir/f"{s}-{i:03d}.log"; i+=1
    return p

def load_selected_versions(path: Path | None) -> list[dict[str, str]]:
    """Load and validate configured version selectors from JSON."""
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    items = data.get("selectedVersions", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("selectedVersions must be an array")
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not str(item.get("id", "")).strip() or not str(item.get("match", "")).strip():
            raise ValueError("each selectedVersions item requires id and match")
        version_id, match = str(item["id"]).strip(), str(item["match"])
        if version_id in {".", ".."} or Path(version_id).name != version_id or version_id in seen:
            raise ValueError("version ids must be unique single path components")
        seen.add(version_id)
        mode = str(item.get("mode", "substring")).strip()
        if mode not in ("substring", "fnmatch"):
            raise ValueError("mode must be 'substring' or 'fnmatch'")
        result.append({"id": version_id, "match": match, "mode": mode})
    return result

def filter_version_files(files: Iterable[str], selected_versions: Iterable[dict[str, str]]) -> dict[str, list[str]]:
    files = list(files)
    def matches(v: dict[str, str], name: str) -> bool:
        if v.get("mode", "substring") == "fnmatch":
            return fnmatch.fnmatch(name, v["match"])
        return v["match"] in name
    return {v["id"]: sorted(name for name in files if matches(v, name)) for v in selected_versions}

def load_monitors_config(path: Path) -> list[dict[str, object]]:
    """Load and validate monitor targets from JSON."""
    if not path.exists():
        raise ValueError(f"monitors config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    items = data.get("targets") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("monitors config requires a targets array")
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each target must be an object")
        target_id, url = str(item.get("id", "")).strip(), str(item.get("url", "")).strip()
        if not target_id or not url:
            raise ValueError("each target requires id and url")
        if target_id in {".", ".."} or Path(target_id).name != target_id or target_id in seen:
            raise ValueError("target ids must be unique single path components")
        seen.add(target_id)
        profile = item.get("profile")
        if profile is not None and not isinstance(profile, dict):
            raise ValueError("target profile must be an object")
        result.append({"id": target_id, "url": url, "profile": profile})
    return result

def _write_resident_lock(path: Path, owner: str) -> None:
    data = {"pid": os.getpid(), "heartbeat": time.time(), "owner": owner}
    _atomic_write(path, json.dumps(data, separators=(",", ":")))

def _read_resident_lock(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None

def acquire_resident_lock(path: Path, interval: float) -> str | None:
    """Atomically acquire the resident lock, replacing only stale lock files."""
    owner = uuid.uuid4().hex
    while True:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = _read_resident_lock(path)
            heartbeat = existing.get("heartbeat") if existing else None
            if isinstance(heartbeat, (int, float)) and time.time() - heartbeat <= interval * 2:
                return None
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        try:
            data = {"pid": os.getpid(), "heartbeat": time.time(), "owner": owner}
            os.write(fd, json.dumps(data, separators=(",", ":")).encode("utf-8"))
        finally:
            os.close(fd)
        return owner

def refresh_resident_lock(path: Path, owner: str) -> bool:
    data = _read_resident_lock(path)
    if not data or data.get("owner") != owner:
        return False
    _write_resident_lock(path, owner)
    return True

def release_resident_lock(path: Path, owner: str) -> None:
    data = _read_resident_lock(path)
    if data and data.get("owner") == owner:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

def write_version_change_log(log_dir: Path, version: dict[str, str], before: Iterable[str], after: Iterable[str], detected_at: datetime | None = None) -> Path:
    """Write ONE audit log when a version's file set changes, containing the FULL
    before list and the FULL after list plus change counts. Only change events
    produce files: an unchanged scan writes nothing for this version."""
    dt = detected_at or datetime.now(TIME_ZONE)
    before_names, after_names = sorted(before), sorted(after)
    added, removed = diff_filenames(before_names, after_names)["added"], diff_filenames(before_names, after_names)["removed"]
    lines = [
        f"monitorId: intranet-focus-{version['id']}",
        f"detectedAt: {dt.isoformat()}",
        f"versionId: {version['id']}",
        f"match: {version['match']}",
        f"changed: true",
        f"addedCount: {len(added)}",
        f"removedCount: {len(removed)}",
        f"beforeCount: {len(before_names)}",
        f"afterCount: {len(after_names)}",
        "", "before:",
    ]
    lines.extend(f"- {name}" for name in before_names)
    lines += ["", "after:"]
    lines.extend(f"- {name}" for name in after_names)
    path = _next_log_path(log_dir / version["id"], dt)
    _atomic_write(path, "\n".join(lines) + "\n")
    return path

def write_diff_log(log_dir: Path, diff: dict[str,object], detected_at: datetime|None=None, *, monitor_id="intranet-root", previous_fingerprint="", current_fingerprint="")->Path|None:
    if "added" in diff or "removed" in diff:
        changed = bool(diff.get("added") or diff.get("removed"))
    else:
        changed = bool(diff)
    if not changed:return None
    dt=detected_at or datetime.now(TIME_ZONE); lines=[f"monitorId: {monitor_id}",f"detectedAt: {dt.isoformat()}",f"previousFingerprint: {previous_fingerprint}",f"currentFingerprint: {current_fingerprint}"]
    if "added" in diff or "removed" in diff:
        lines += ["", "added:"] + [f"- {x}" for x in diff.get("added",[]) ] + ["", "removed:"] + [f"- {x}" for x in diff.get("removed",[]) ]
    else:
        lines += ["", "changedFields:"] + [f"- {name}: {json.dumps(value, ensure_ascii=False)}" for name, value in diff.items()]
    p=_next_log_path(log_dir,dt); _atomic_write(p,"\n".join(lines)+"\n"); return p

def fetch_page(url: str, timeout: float):
    start=time.monotonic(); req=Request(url,headers={"User-Agent":"intranet-web-field-monitor/1.0"})
    with urlopen(req,timeout=timeout) as r:
        status=getattr(r,"status",r.getcode());
        if status!=200:raise RuntimeError(f"request returned HTTP {status}")
        if r.headers.get_content_type() not in ("text/html","application/xhtml+xml"):raise RuntimeError("unexpected content type")
        body=r.read(); charset=r.headers.get_content_charset() or "utf-8"
    return body.decode(charset,errors="replace"),len(body),time.monotonic()-start

LAST_FETCH_METRICS = {"bytes": 0, "duration": 0.0}

def fetch_filenames(url: str, timeout: float)->set[str]:
    html, nbytes, duration = fetch_page(url,timeout)
    validate_page(html)
    LAST_FETCH_METRICS.update(bytes=nbytes, duration=duration)
    return parse_filenames(html,url)

def _send_event(event_url,payload,timeout,token=None):
    h={"Content-Type":"application/json"};
    if token:h["Authorization"]="Bearer "+token
    with urlopen(Request(event_url,data=json.dumps(payload).encode(),headers=h,method="POST"),timeout=timeout) as r:
        if not 200<=getattr(r,"status",r.getcode())<300:raise RuntimeError("event delivery failed")

def _queue_event(outbox,payload):_atomic_write(outbox/(payload["event_id"]+".json"),json.dumps(payload,ensure_ascii=False,indent=2)+"\n")

def deliver_pending(outbox: Path, event_url: str, timeout: float, token: str|None=None) -> int:
    """Retry queued events; successful files are removed."""
    if not outbox.exists(): return 0
    delivered=0
    for path in sorted(outbox.glob("*.json")):
        try:
            _send_event(event_url,json.loads(path.read_text(encoding="utf-8")),timeout,token)
            path.unlink(); delivered += 1
        except Exception:
            continue
    return delivered

def load_triage_message(path: Path) -> str | None:
    """Read the fixed triage instruction; None disables agent wake-up."""
    try:
        if not path.exists(): return None
        text = path.read_text(encoding="utf-8-sig").strip()
        return text or None
    except Exception:
        return None

def spawn_triage_agent(message: str, grace: float = WAKE_GRACE_SECONDS) -> bool:
    """Spawn a one-shot triage agent; True when launched and not failed within grace."""
    kwargs: dict[str, object] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        cli = shutil.which("openclaw") or "openclaw.cmd"
        proc = subprocess.Popen([cli, "agent", "--local", "--agent", "main", "-m", message], **kwargs)
    except Exception as e:
        print(f"triage wake spawn failed: {_redact(e)}", file=sys.stderr, flush=True)
        return False
    try:
        rc = proc.wait(timeout=grace)
        if rc != 0:
            print(f"triage wake agent exited with code {rc}", file=sys.stderr, flush=True)
            return False
        return True
    except subprocess.TimeoutExpired:
        print("triage wake delivered (agent still running)", flush=True)
        return True
    except Exception as e:
        print(f"triage wake wait failed: {_redact(e)}", file=sys.stderr, flush=True)
        return False

def clear_outbox(outbox: Path) -> int:
    """Remove all queued wake events; one successful wake covers the whole backlog."""
    removed = 0
    if not outbox.exists(): return 0
    for path in outbox.glob("*.json"):
        try: path.unlink(); removed += 1
        except Exception: continue
    return removed

def deliver_pending_wake(outbox: Path, message: str, grace: float = WAKE_GRACE_SECONDS) -> int:
    """Retry wake-up once when events are queued; success clears the whole outbox."""
    try:
        if not outbox.exists() or not any(outbox.glob("*.json")): return 0
        if not spawn_triage_agent(message, grace): return 0
        return clear_outbox(outbox)
    except Exception:
        return 0

def wake_triage(marks: list[str], outbox: Path, message: str, grace: float = WAKE_GRACE_SECONDS) -> bool:
    """Spawn triage once for this round's marks; on failure queue a deduped wake event."""
    if not marks: return False
    marks = sorted(marks)
    payload = {
        "event_id": hashlib.sha256("|".join(marks).encode()).hexdigest(),
        "monitor_id": ",".join(sorted({m.split(":")[1] for m in marks})),
        "log_path": next((m.split(":", 2)[2] for m in marks if m.startswith("diff:")), ""),
        "detected_at": datetime.now(TIME_ZONE).isoformat(),
    }
    try:
        if spawn_triage_agent(message, grace):
            clear_outbox(outbox)
            return True
        _queue_event(outbox, payload)
    except Exception:
        pass
    return False

def run_once(url,state_path,log_dir,timeout,*,event_url=None,outbox=None,event_token=None,monitor_id="intranet-root",min_links=0,profile=None,confirm_polls=1,selected_versions=None,focus_log_dir=Path("logs/intranet-focus"),error_log_dir=DEFAULT_ERROR_LOG_DIR,mode="once"):
    dt=datetime.now(TIME_ZONE); phase = "fetch_page"; state_preserved = state_path.exists(); operation_path = None; written_paths = []
    try:
        if profile:
            html,nbytes,duration=fetch_page(url,timeout); phase = "validate_page"; validate_page(html,min_links=min_links); snap=parse_fields(html,url,profile)
            files=snap.get("root_files",[])
        else:
            try:
                files=fetch_filenames(url,timeout)
            except PageValidationError:
                phase = "validate_page"
                raise
            nbytes=LAST_FETCH_METRICS["bytes"]; duration=LAST_FETCH_METRICS["duration"]; snap={"root_files":sorted(files)}
            phase = "validate_page"
            if len(files)<min_links:raise PageValidationError("page has too few links")
        phase = "confirm_poll"
        for _ in range(max(0, confirm_polls - 1)):
            check = fetch_filenames(url, timeout)
            if sorted(check) != sorted(files):
                raise RuntimeError("page snapshot did not stabilize")
        phase = "read_state"
        try:
            prev=_read_state(state_path)
        except Exception:
            state_preserved = False
            raise
        state_preserved = prev is not None
        version_logs = []
        version_files = dict(prev.get("versionFiles", {})) if prev else {}
        if selected_versions:
            phase = "write_snapshot_log"
            for version, after_names in filter_version_files(files, selected_versions).items():
                spec = next(v for v in selected_versions if v["id"] == version)
                before_names = version_files.get(version, [])
                if sorted(before_names) != sorted(after_names):
                    operation_path = focus_log_dir / version
                    snapshot_path = write_version_change_log(focus_log_dir, spec, before_names, after_names, dt)
                    written_paths.append(str(snapshot_path)); version_logs.append(str(snapshot_path))
                    version_files[version] = after_names
        if prev is None:
            phase = "write_state"; operation_path = state_path; _write_state(state_path,snap,dt,version_files); written_paths.append(str(state_path))
            return {"baseline":True,"added":[],"removed":[],"log":None,"versionLogs":version_logs,"count":len(files),"bytes":nbytes,"duration":duration}
        phase = "write_diff_log"; operation_path = log_dir; diff=diff_snapshots(prev.get("snapshot",{}),snap); log=write_diff_log(log_dir,diff,dt,monitor_id=monitor_id,previous_fingerprint=prev.get("fingerprint","") ,current_fingerprint=fingerprint(snap));
        if log:
            written_paths.append(str(log))
        phase = "write_state"; operation_path = state_path; _write_state(state_path,snap,dt,version_files)
        written_paths.append(str(state_path))
        if log and event_url:
            event_key=f"{monitor_id}|{prev.get('fingerprint','')}|{fingerprint(snap)}|{Path(log).name}"
            payload={"event_id":hashlib.sha256(event_key.encode()).hexdigest(),"monitor_id":monitor_id,"log_path":str(log),"detected_at":dt.isoformat()}
            try:_send_event(event_url,payload,timeout,event_token)
            except Exception:
                if outbox:outbox.mkdir(parents=True,exist_ok=True); _queue_event(outbox,payload)
        root_diff=diff.get("root_files", {}) if isinstance(diff.get("root_files", {}), dict) else {}
        return {"baseline":False,"added":root_diff.get("added",[]),"removed":root_diff.get("removed",[]),"log":str(log) if log else None,"versionLogs":version_logs,"count":len(files),"bytes":nbytes,"duration":duration}
    except Exception as error:
        record_error(error_log_dir, monitor_id=monitor_id, mode=mode, phase=phase, error=error, url=url, path=operation_path, state_preserved=state_preserved, written_paths=written_paths)
        raise

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--url"); p.add_argument("--interval",type=float,default=DEFAULT_INTERVAL); p.add_argument("--timeout",type=float,default=DEFAULT_TIMEOUT); p.add_argument("--confirm-polls",type=int,default=1); p.add_argument("--state",type=Path,default=None); p.add_argument("--log-dir",type=Path,default=Path("logs/intranet-diff")); p.add_argument("--focus-log-dir",type=Path,default=Path("logs/intranet-focus")); p.add_argument("--error-log-dir",type=Path,default=DEFAULT_ERROR_LOG_DIR); p.add_argument("--versions-config",type=Path,default=Path("config/intranet-versions.json")); p.add_argument("--monitors-config",type=Path,default=Path("config/monitors.json")); p.add_argument("--profile",type=Path,help="JSON field profile"); p.add_argument("--event-url"); p.add_argument("--event-token"); p.add_argument("--outbox",type=Path,default=Path("state/openclaw-pending")); p.add_argument("--triage-message-file",type=Path,default=DEFAULT_TRIAGE_MESSAGE_FILE); p.add_argument("--once",action="store_true"); a=p.parse_args(argv)
    if a.interval<=0 or a.timeout<=0 or a.confirm_polls<=0:print("--interval, --timeout and --confirm-polls must be positive",file=sys.stderr); return 2
    exit_code=0; mode="once" if a.once else "resident"
    lock_owner = None if a.once else acquire_resident_lock(RESIDENT_LOCK_PATH, a.interval)
    if not a.once and lock_owner is None:
        return 0
    triage_message=load_triage_message(a.triage_message_file)
    triage_warning_pending = triage_message is None
    try:
        while True:
            marks=[]
            try:
                if a.event_url: deliver_pending(a.outbox,a.event_url,a.timeout,a.event_token)
                if triage_message: deliver_pending_wake(a.outbox,triage_message)
                config_path=None
                try:
                    if a.url:
                        targets=[{"id":"intranet-root","url":a.url,"profile":None}]
                    else:
                        config_path=a.monitors_config; targets=load_monitors_config(a.monitors_config)
                    if a.once and not targets:
                        raise ValueError("monitors config requires a non-empty targets array")
                    if a.profile: config_path=a.profile; profile=json.loads(a.profile.read_text(encoding="utf-8-sig"))
                    else: profile=None
                    if a.state and len(targets)>1: config_path=a.state; raise ValueError("--state only supports a single target")
                    config_path=a.versions_config; versions=load_selected_versions(a.versions_config)
                except Exception as e:
                    record_error(a.error_log_dir, monitor_id="intranet-root", mode=mode, phase="read_config", error=e, path=config_path, state_preserved=False)
                    marks.append("error:read_config")
                    raise
                if triage_warning_pending and targets:
                    print(f"triage message file unavailable: {a.triage_message_file}; agent wake disabled",file=sys.stderr,flush=True)
                    triage_warning_pending = False
                for target in targets:
                    state_path=a.state or Path("state")/f"intranet-files-{target['id']}.json"
                    try:
                        r=run_once(target["url"],state_path,a.log_dir,a.timeout,event_url=a.event_url,outbox=a.outbox,event_token=a.event_token,monitor_id=target["id"],profile=target.get("profile") or profile,confirm_polls=a.confirm_polls,selected_versions=versions,focus_log_dir=a.focus_log_dir,error_log_dir=a.error_log_dir,mode=mode)
                        if r["baseline"]:print(f"baseline saved [{target['id']}]: {r['count']} files",flush=True)
                        elif r["log"]:print(f"diff [{target['id']}]: {r['log']}",flush=True); marks.append(f"diff:{target['id']}:{Path(r['log']).name}")
                    except Exception as e:
                        print(f"scan failed [{target['id']}]: {e}",file=sys.stderr,flush=True)
                        marks.append(f"error:{target['id']}")
                        exit_code=1
            except Exception as e:
                print(f"scan failed: {e}",file=sys.stderr,flush=True)
                exit_code=1
            if triage_message and marks: wake_triage(marks,a.outbox,triage_message)
            if a.once:return exit_code
            if not refresh_resident_lock(RESIDENT_LOCK_PATH, lock_owner):
                return 1
            time.sleep(a.interval)
    finally:
        if lock_owner:
            release_resident_lock(RESIDENT_LOCK_PATH, lock_owner)
if __name__=="__main__":raise SystemExit(main())
