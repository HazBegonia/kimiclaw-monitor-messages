"""Resident polling monitor for configurable fields in an intranet HTML page."""
from __future__ import annotations
import argparse, hashlib, json, re, sys, time, uuid
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

def _write_state(path: Path, snapshot: dict[str,object], checked_at: datetime):
    d={"checkedAt":checked_at.isoformat(),"snapshot":snapshot,"fingerprint":fingerprint(snapshot)}
    if "root_files" in snapshot:d["files"]=snapshot["root_files"]
    _atomic_write(path,json.dumps(d,ensure_ascii=False,indent=2)+"\n")

def _next_log_path(log_dir: Path, dt: datetime)->Path:
    s=dt.strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]; p=log_dir/f"{s}.log"; i=1
    while p.exists():p=log_dir/f"{s}-{i:03d}.log"; i+=1
    return p

def load_selected_versions(path: Path | None) -> list[dict[str, str]]:
    """Load and validate configured version selectors from JSON."""
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
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
        result.append({"id": version_id, "match": match})
    return result

def filter_version_files(files: Iterable[str], selected_versions: Iterable[dict[str, str]]) -> dict[str, list[str]]:
    files = list(files)
    return {v["id"]: sorted(name for name in files if v["match"] in name) for v in selected_versions}

def write_snapshot_log(log_dir: Path, version: dict[str, str], files: Iterable[str], detected_at: datetime | None = None) -> Path:
    dt = detected_at or datetime.now(TIME_ZONE)
    names = sorted(files)
    lines = [f"monitorId: intranet-focus-{version['id']}", f"detectedAt: {dt.isoformat()}", f"versionId: {version['id']}", f"match: {version['match']}", f"count: {len(names)}", "", "files:"]
    lines.extend(f"- {name}" for name in names)
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
        if selected_versions:
            phase = "write_snapshot_log"
            for version, names in filter_version_files(files, selected_versions).items():
                spec = next(v for v in selected_versions if v["id"] == version)
                operation_path = focus_log_dir / version
                snapshot_path = write_snapshot_log(focus_log_dir, spec, names, dt)
                written_paths.append(str(snapshot_path)); version_logs.append(str(snapshot_path))
        if prev is None:
            phase = "write_state"; operation_path = state_path; _write_state(state_path,snap,dt); written_paths.append(str(state_path))
            return {"baseline":True,"added":[],"removed":[],"log":None,"versionLogs":version_logs,"count":len(files),"bytes":nbytes,"duration":duration}
        phase = "write_diff_log"; operation_path = log_dir; diff=diff_snapshots(prev.get("snapshot",{}),snap); log=write_diff_log(log_dir,diff,dt,monitor_id=monitor_id,previous_fingerprint=prev.get("fingerprint","") ,current_fingerprint=fingerprint(snap));
        if log:
            written_paths.append(str(log))
        phase = "write_state"; operation_path = state_path; _write_state(state_path,snap,dt)
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
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--url",default=DEFAULT_URL); p.add_argument("--interval",type=float,default=DEFAULT_INTERVAL); p.add_argument("--timeout",type=float,default=DEFAULT_TIMEOUT); p.add_argument("--confirm-polls",type=int,default=1); p.add_argument("--state",type=Path,default=Path("state/intranet-files.json")); p.add_argument("--log-dir",type=Path,default=Path("logs/intranet-diff")); p.add_argument("--focus-log-dir",type=Path,default=Path("logs/intranet-focus")); p.add_argument("--error-log-dir",type=Path,default=DEFAULT_ERROR_LOG_DIR); p.add_argument("--versions-config",type=Path,default=Path("config/intranet-versions.json")); p.add_argument("--profile",type=Path,help="JSON field profile"); p.add_argument("--event-url"); p.add_argument("--event-token"); p.add_argument("--outbox",type=Path,default=Path("state/openclaw-pending")); p.add_argument("--once",action="store_true"); a=p.parse_args(argv)
    if a.interval<=0 or a.timeout<=0 or a.confirm_polls<=0:print("--interval, --timeout and --confirm-polls must be positive",file=sys.stderr); return 2
    exit_code=0
    while True:
        try:
            if a.event_url: deliver_pending(a.outbox,a.event_url,a.timeout,a.event_token)
            try:
                profile=json.loads(a.profile.read_text(encoding="utf-8")) if a.profile else None
                versions=load_selected_versions(a.versions_config)
            except Exception as e:
                record_error(a.error_log_dir, monitor_id="intranet-root", mode="once" if a.once else "resident", phase="read_config", error=e, path=a.profile or a.versions_config, state_preserved=a.state.exists())
                raise
            r=run_once(a.url,a.state,a.log_dir,a.timeout,event_url=a.event_url,outbox=a.outbox,event_token=a.event_token,profile=profile,confirm_polls=a.confirm_polls,selected_versions=versions,focus_log_dir=a.focus_log_dir,error_log_dir=a.error_log_dir,mode="once" if a.once else "resident")
            if r["baseline"]:print(f"baseline saved: {r['count']} files",flush=True)
            elif r["log"]:print(f"diff: {r['log']}",flush=True)
        except Exception as e:
            print(f"scan failed: {e}",file=sys.stderr,flush=True)
            exit_code=1
        if a.once:return exit_code
        time.sleep(a.interval)
if __name__=="__main__":raise SystemExit(main())
