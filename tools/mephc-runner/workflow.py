from __future__ import annotations
import fcntl,hashlib,json,os,time
from pathlib import Path
ROOT=Path("/home/icy/MePhC");RUNTIME=ROOT/".relayctl"/"runner";LEDGER=RUNTIME/"workflow-ledger.json";KNOWN=ROOT/".relayctl"/"outbox"/"MEPHC-WORKFLOW-STATUS-20260826-125331-e3560e9c";RP4B="MEPHC-E9F-C1-RP4-B-20260826-274"
def ensure():
 RUNTIME.mkdir(parents=True,exist_ok=True)
 with (RUNTIME/"workflow.lock").open("a+") as h:
  fcntl.flock(h,fcntl.LOCK_EX)
  if LEDGER.is_file():return json.loads(LEDGER.read_text())
  v={"schema":"mephc-workflow-ledger-v1","workflow_state":"idle_unconfirmed","active_work_order_id":None,"active_response_path":None,"active_response_sha256":None,"pending_job_id":None,"updated_at":time.time()};p=KNOWN/"response.txt"
  if p.is_file() and f"NEXT_WORK_ORDER_ID={RP4B}" in p.read_text(encoding="utf-8-sig"):v.update(workflow_state="available",active_work_order_id=RP4B,active_response_path=str(p),active_response_sha256=hashlib.sha256(p.read_bytes()).hexdigest())
  t=LEDGER.with_name(f".{LEDGER.name}.{os.getpid()}.tmp");t.write_text(json.dumps(v,sort_keys=True)+"\n");os.replace(t,LEDGER);return v
def view():return {k:ensure().get(k) for k in ("workflow_state","active_work_order_id","pending_job_id")}
def active():
 v=ensure();p=v.get("active_response_path")
 if not p:return None
 path=Path(p)
 if hashlib.sha256(path.read_bytes()).hexdigest()!=v["active_response_sha256"]:raise RuntimeError("WORKFLOW_RESPONSE_SHA_MISMATCH")
 return {"workflow_state":v["workflow_state"],"active_work_order_id":v["active_work_order_id"],"source_response_sha256":v["active_response_sha256"],"work_order_text":path.read_text(encoding="utf-8-sig"),"safe_next_tool":"execute_work_order"}
