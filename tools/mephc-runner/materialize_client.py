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
def main()->int:
    if len(sys.argv)!=3 or sys.argv[1] not in {"transact","recover"}: return 2
    mode=sys.argv[1]; job=Path(sys.argv[2]).resolve(); jobs=config.JOBS.resolve()
    try: job.relative_to(jobs)
    except ValueError: return 2
    raw=(job/"job.json").read_bytes(); marker={"schema":"mephc-materialize-request-v1","job_sha256":hashlib.sha256(raw).hexdigest(),"mode":mode}
    prefix="MATERIALIZE" if mode=="transact" else "MATERIALIZE_RECOVER"
    atomic(job/f"{prefix}_READY",(json.dumps(marker,sort_keys=True)+"\n").encode())
    state_path=job/("materializer-state.json" if mode=="transact" else "materializer-recovery-state.json")
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline:
        if state_path.is_file():
            state=json.loads(state_path.read_text())
            if state.get("state")=="succeeded": return 0
            if state.get("state")=="failed": return 1
        time.sleep(1)
    return 2
if __name__=="__main__": raise SystemExit(main())
