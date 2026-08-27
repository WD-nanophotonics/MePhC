#!/home/icy/miniconda3/envs/mp/bin/python
"""Queue client used by the read-only worker to request materialization."""
import hashlib, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_config as config
def atomic(path:Path,data:bytes)->None:
    temporary=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle: handle.write(data); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary,path)
def write_state(path:Path, value:dict)->None:
    atomic(path,(json.dumps(value,sort_keys=True)+"\n").encode())
def broker_age()->float|None:
    try:
        record=json.loads(config.BROKER_HEARTBEAT.read_text(encoding="utf-8-sig"))
        updated=record.get("updated_unix")
        return time.time()-float(updated) if updated is not None else None
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        return None
def main()->int:
    if len(sys.argv)!=3 or sys.argv[1] not in {"transact","recover"}: return 2
    mode=sys.argv[1]; job=Path(sys.argv[2]).resolve(); jobs=config.JOBS.resolve()
    try: job.relative_to(jobs)
    except ValueError: return 2
    raw=(job/"job.json").read_bytes(); marker={"schema":"mephc-materialize-request-v2","job_sha256":hashlib.sha256(raw).hexdigest(),"mode":mode}
    prefix="MATERIALIZE" if mode=="transact" else "MATERIALIZE_RECOVER"
    state_path=job/("materializer-state.json" if mode=="transact" else "materializer-recovery-state.json")
    age=broker_age()
    if age is None or age>20:
        write_state(state_path,{"state":"recovery_required","error_code":"BROKER_UNAVAILABLE_BEFORE_DISPATCH","broker_age_seconds":age})
        return 3
    atomic(job/f"{prefix}_READY",(json.dumps(marker,sort_keys=True)+"\n").encode())
    deadline=time.monotonic()+config.MATERIALIZER_TIMEOUT_SECONDS+30
    while time.monotonic()<deadline:
        phase="awaiting_materializer"
        progress_path=job/"materializer-progress.json"
        if progress_path.is_file():
            try: phase=json.loads(progress_path.read_text()).get("phase",phase)
            except (OSError,json.JSONDecodeError): pass
        write_state(job/"client-progress.json",{"phase":phase,"phase_heartbeat_unix":time.time(),"deadline_unix":time.time()+max(0,deadline-time.monotonic()),"mode":mode})
        if state_path.is_file():
            state=json.loads(state_path.read_text())
            if state.get("state")=="succeeded": return 0
            if state.get("state")=="failed": return 1
            if state.get("state")=="recovery_required": return 3
        age=broker_age()
        if age is None or age>20:
            write_state(state_path,{"state":"recovery_required","error_code":"BROKER_HEARTBEAT_LOST","broker_age_seconds":age})
            return 3
        time.sleep(1)
    write_state(state_path,{"state":"recovery_required","error_code":"MATERIALIZER_CLIENT_TIMEOUT"})
    return 3
if __name__=="__main__": raise SystemExit(main())
