#!/home/icy/miniconda3/envs/mp/bin/python
"""Queue client used by the read-only worker to request materialization."""
import hashlib, json, os, sys, time
from pathlib import Path
def atomic(path:Path,data:bytes)->None:
    temporary=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle: handle.write(data); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary,path)
def main()->int:
    if len(sys.argv)!=2: return 2
    job=Path(sys.argv[1]).resolve(); jobs=Path("/home/icy/MePhC/.relayctl/runner/jobs").resolve()
    try: job.relative_to(jobs)
    except ValueError: return 2
    raw=(job/"job.json").read_bytes(); marker={"schema":"mephc-materialize-request-v1","job_sha256":hashlib.sha256(raw).hexdigest()}
    atomic(job/"MATERIALIZE_READY",(json.dumps(marker,sort_keys=True)+"\n").encode())
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline:
        state_path=job/"materializer-state.json"
        if state_path.is_file():
            state=json.loads(state_path.read_text())
            if state.get("state")=="succeeded": return 0
            if state.get("state")=="failed": return 1
        time.sleep(1)
    return 2
if __name__=="__main__": raise SystemExit(main())
