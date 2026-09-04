"""Resident polling monitor for configurable fields in an intranet HTML page."""
from __future__ import annotations
import argparse, hashlib, json, sys, time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

DEFAULT_URL="http://172.16.30.20:8011/"; DEFAULT_INTERVAL=5.0; DEFAULT_TIMEOUT=10.0; TIME_ZONE=ZoneInfo("Asia/Shanghai")

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
        raise RuntimeError("page signature validation failed")
    if not html.rstrip().lower().endswith("</html>"):
        raise RuntimeError("incomplete HTML page")
    if not parser.hrefs or len(parser.hrefs) < min_links:
        raise RuntimeError("page has too few links")

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

def run_once(url,state_path,log_dir,timeout,*,event_url=None,outbox=None,event_token=None,monitor_id="intranet-root",min_links=0,profile=None,confirm_polls=1,selected_versions=None,focus_log_dir=Path("logs/intranet-focus")):
    dt=datetime.now(TIME_ZONE)
    if profile:
        html,nbytes,duration=fetch_page(url,timeout); validate_page(html,min_links=min_links); snap=parse_fields(html,url,profile)
        files=snap.get("root_files",[])
    else:
        files=fetch_filenames(url,timeout); nbytes=LAST_FETCH_METRICS["bytes"]; duration=LAST_FETCH_METRICS["duration"]; snap={"root_files":sorted(files)}
        if len(files)<min_links:raise RuntimeError("page has too few links")
    for _ in range(max(0, confirm_polls - 1)):
        check = fetch_filenames(url, timeout)
        if sorted(check) != sorted(files):
            raise RuntimeError("page snapshot did not stabilize")
    prev=_read_state(state_path)
    version_logs = []
    if selected_versions:
        for version, names in filter_version_files(files, selected_versions).items():
            spec = next(v for v in selected_versions if v["id"] == version)
            version_logs.append(str(write_snapshot_log(focus_log_dir, spec, names, dt)))
    if prev is None:
        _write_state(state_path,snap,dt)
        return {"baseline":True,"added":[],"removed":[],"log":None,"versionLogs":version_logs,"count":len(files),"bytes":nbytes,"duration":duration}
    diff=diff_snapshots(prev.get("snapshot",{}),snap); log=write_diff_log(log_dir,diff,dt,monitor_id=monitor_id,previous_fingerprint=prev.get("fingerprint","") ,current_fingerprint=fingerprint(snap)); _write_state(state_path,snap,dt)
    if log and event_url:
        event_key=f"{monitor_id}|{prev.get('fingerprint','')}|{fingerprint(snap)}|{Path(log).name}"
        payload={"event_id":hashlib.sha256(event_key.encode()).hexdigest(),"monitor_id":monitor_id,"log_path":str(log),"detected_at":dt.isoformat()}
        try:_send_event(event_url,payload,timeout,event_token)
        except Exception:
            if outbox:outbox.mkdir(parents=True,exist_ok=True); _queue_event(outbox,payload)
    root_diff=diff.get("root_files", {}) if isinstance(diff.get("root_files", {}), dict) else {}
    return {"baseline":False,"added":root_diff.get("added",[]),"removed":root_diff.get("removed",[]),"log":str(log) if log else None,"versionLogs":version_logs,"count":len(files),"bytes":nbytes,"duration":duration}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--url",default=DEFAULT_URL); p.add_argument("--interval",type=float,default=DEFAULT_INTERVAL); p.add_argument("--timeout",type=float,default=DEFAULT_TIMEOUT); p.add_argument("--confirm-polls",type=int,default=1); p.add_argument("--state",type=Path,default=Path("state/intranet-files.json")); p.add_argument("--log-dir",type=Path,default=Path("logs/intranet-diff")); p.add_argument("--focus-log-dir",type=Path,default=Path("logs/intranet-focus")); p.add_argument("--versions-config",type=Path,default=Path("config/intranet-versions.json")); p.add_argument("--profile",type=Path,help="JSON field profile"); p.add_argument("--event-url"); p.add_argument("--event-token"); p.add_argument("--outbox",type=Path,default=Path("state/openclaw-pending")); p.add_argument("--once",action="store_true"); a=p.parse_args(argv)
    if a.interval<=0 or a.timeout<=0 or a.confirm_polls<=0:print("--interval, --timeout and --confirm-polls must be positive",file=sys.stderr); return 2
    exit_code=0
    while True:
        try:
            if a.event_url: deliver_pending(a.outbox,a.event_url,a.timeout,a.event_token)
            profile=json.loads(a.profile.read_text(encoding="utf-8")) if a.profile else None
            versions=load_selected_versions(a.versions_config)
            r=run_once(a.url,a.state,a.log_dir,a.timeout,event_url=a.event_url,outbox=a.outbox,event_token=a.event_token,profile=profile,confirm_polls=a.confirm_polls,selected_versions=versions,focus_log_dir=a.focus_log_dir)
            if r["baseline"]:print(f"baseline saved: {r['count']} files",flush=True)
            elif r["log"]:print(f"diff: {r['log']}",flush=True)
        except Exception as e:
            print(f"scan failed: {e}",file=sys.stderr,flush=True)
            exit_code=1
        if a.once:return exit_code
        time.sleep(a.interval)
if __name__=="__main__":raise SystemExit(main())
