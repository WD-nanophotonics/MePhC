#!/home/icy/miniconda3/envs/mp/bin/python
"""Fail-closed exact executor for an authorized Windows cleanup plan."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/home/icy/MePhC")
INVENTORY = ROOT / ".relayctl" / "inventory"
COPY_ROOTS = {
 "/mnt/c/Users/icywo/PycharmProjects/AgentRelay",
 "/mnt/c/Users/icywo/PycharmProjects/ChatSequenceRunner",
 "/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows",
 "/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC",
 "/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-SqrLatt",
 "/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-TriLatt",
 "/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-Windows"}

def git(*a: str):
 return subprocess.run(["/usr/bin/git","-C",str(ROOT),*a],text=True,encoding="utf-8",
  errors="replace",stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)

def canonical_sha(plan: dict[str,Any]) -> str:
 value=dict(plan); value.pop("plan_sha256",None)
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
  ensure_ascii=False).encode()).hexdigest()

def file_sha(path: Path) -> str:
 digest=hashlib.sha256()
 with path.open("rb") as stream:
  for chunk in iter(lambda:stream.read(1048576),b""): digest.update(chunk)
 return digest.hexdigest()

def relative(value: str) -> Path:
 path=Path(value)
 if not value or path.is_absolute() or ".." in path.parts:
  raise RuntimeError(f"UNSAFE_DELETE_PATH:{value}")
 return path

def enumerate_files(root: Path) -> set[str]:
 if not root.is_dir() or root.is_symlink():
  raise RuntimeError(f"COPY_ROOT_MISSING_OR_UNSAFE:{root}")
 found=set()
 for directory,names,files in os.walk(root,followlinks=False):
  base=Path(directory)
  for name in names:
   if (base/name).is_symlink(): raise RuntimeError(f"UNPLANNED_SYMLINK:{base/name}")
  for name in files:
   path=base/name
   if path.is_symlink() or not path.is_file(): raise RuntimeError(f"UNSAFE_FILE_TYPE:{path}")
   found.add(path.relative_to(root).as_posix())
 return found

def verify_plan(plan: dict[str,Any], authorized: str) -> None:
 actual=canonical_sha(plan)
 if actual != plan.get("plan_sha256") or actual != authorized:
  raise RuntimeError("PLAN_SHA256_MISMATCH")
 if plan.get("schema")!="mephc-windows-copy-cleanup-plan-v1" or plan.get("active_project")!="MEPHC":
  raise RuntimeError("PLAN_IDENTITY_MISMATCH")
 files,payloads=plan["copy_root_files"],plan["payload_retirement"]
 if len(files)!=plan["copy_root_file_count"] or sum(x["bytes"] for x in files)!=plan["copy_root_bytes"]:
  raise RuntimeError("COPY_TOTAL_MISMATCH")
 if len(payloads)!=plan["payload_retirement_count"] or sum(x["bytes"] for x in payloads)!=plan["payload_retirement_bytes"]:
  raise RuntimeError("PAYLOAD_TOTAL_MISMATCH")

def verify_git(plan: dict[str,Any], expected_main: str) -> str:
 if Path.cwd().resolve()!=ROOT: raise RuntimeError("ROOT_MISMATCH")
 refs={}
 for key,ref in (("head","HEAD"),("sandbox","origin/sandbox"),("main","origin/main")):
  result=git("rev-parse",ref)
  if result.returncode: raise RuntimeError(f"GIT_REF_UNAVAILABLE:{ref}")
  refs[key]=result.stdout.strip()
 if refs["head"]!=refs["sandbox"]: raise RuntimeError("HEAD_NOT_ORIGIN_SANDBOX")
 if refs["main"]!=expected_main: raise RuntimeError("MAIN_MOVED")
 if git("status","--porcelain").stdout: raise RuntimeError("WORKTREE_DIRTY")
 for commit in (plan["archive_commit"],plan["sandbox_head_at_plan"]):
  if git("merge-base","--is-ancestor",commit,refs["sandbox"]).returncode:
   raise RuntimeError(f"COMMIT_NOT_REMOTE_RETAINED:{commit}")
 return refs["sandbox"]

def verify_all(plan: dict[str,Any]) -> None:
 grouped: dict[str,dict[str,dict[str,Any]]]={}
 for item in plan["copy_root_files"]:
  root=item["root"]
  if root not in COPY_ROOTS: raise RuntimeError(f"ROOT_NOT_AUTHORIZED:{root}")
  rel=relative(item["path"]).as_posix()
  if rel in grouped.setdefault(root,{}): raise RuntimeError(f"DUPLICATE_DELETE_PATH:{root}:{rel}")
  grouped[root][rel]=item
 if set(grouped)!=COPY_ROOTS: raise RuntimeError("COPY_ROOT_SET_MISMATCH")
 for root_value,expected in grouped.items():
  root=Path(root_value); actual=enumerate_files(root)
  if actual!=set(expected):
   raise RuntimeError(f"COPY_FILE_SET_MISMATCH:{root}:missing={sorted(set(expected)-actual)[:1]}:extra={sorted(actual-set(expected))[:1]}")
  for rel,item in expected.items():
   path=root/rel
   if path.stat().st_size!=item["bytes"]: raise RuntimeError(f"FILE_SIZE_MISMATCH:{path}")
   if file_sha(path)!=item["sha256"]: raise RuntimeError(f"FILE_SHA256_MISMATCH:{path}")
 for item in plan["payload_retirement"]:
  rel=relative(item["path"])
  if rel.parts[:2]!=("audit","archive"): raise RuntimeError(f"PAYLOAD_PATH_MISMATCH:{rel}")
  path=ROOT/rel
  if path.is_symlink() or not path.is_file(): raise RuntimeError(f"PAYLOAD_MISSING_OR_UNSAFE:{rel}")
  if path.stat().st_size!=item["bytes"] or file_sha(path)!=item["sha256"]:
   raise RuntimeError(f"PAYLOAD_BYTE_MISMATCH:{rel}")
  if git("ls-files","--error-unmatch",rel.as_posix()).returncode:
   raise RuntimeError(f"PAYLOAD_NOT_TRACKED:{rel}")

def atomic_json(path: Path, value: dict[str,Any]) -> None:
 temporary=path.with_suffix(path.suffix+".tmp")
 temporary.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 temporary.replace(path)

def remove_empty(root: Path) -> None:
 if root.exists():
  for directory,_,_ in os.walk(root,topdown=False):
   try: Path(directory).rmdir()
   except OSError: pass

def execute(plan: dict[str,Any], plan_sha: str, head: str) -> Path:
 INVENTORY.mkdir(parents=True,exist_ok=True)
 stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
 cert=INVENTORY/f"windows-copy-cleanup-preflight-{stamp}.json"
 atomic_json(cert,{"schema":"mephc-windows-cleanup-preflight-v1",
  "status":"VERIFIED_BEFORE_FIRST_DELETE","verified_at":datetime.now(timezone.utc).isoformat(),
  "plan_sha256":plan_sha,"sandbox_head":head,
  "copy_root_file_count":plan["copy_root_file_count"],"copy_root_bytes":plan["copy_root_bytes"],
  "payload_retirement_count":plan["payload_retirement_count"],
  "payload_retirement_bytes":plan["payload_retirement_bytes"]})
 progress=INVENTORY/f"windows-copy-cleanup-progress-{plan_sha}.jsonl"
 with progress.open("x",encoding="utf-8") as log:
  for kind,items in (("copy_file_deleted",plan["copy_root_files"]),
                     ("payload_deleted",plan["payload_retirement"])):
   for item in items:
    path=(Path(item["root"])/relative(item["path"]) if kind=="copy_file_deleted"
          else ROOT/relative(item["path"]))
    path.unlink()
    log.write(json.dumps({"kind":kind,"path":str(path),"bytes":item["bytes"],
                         "sha256":item["sha256"]},sort_keys=True)+"\n")
  log.flush(); os.fsync(log.fileno())
 for root in sorted(map(Path,COPY_ROOTS),key=lambda x:len(x.parts),reverse=True): remove_empty(root)
 receipt=INVENTORY/f"windows-copy-cleanup-receipt-{stamp}.json"
 atomic_json(receipt,{"schema":"mephc-windows-copy-cleanup-receipt-v1","status":"SUCCEEDED",
  "completed_at":datetime.now(timezone.utc).isoformat(),"plan_sha256":plan_sha,
  "archive_commit":plan["archive_commit"],"preflight_certificate":str(cert),
  "progress_log":str(progress),"copy_root_file_count":plan["copy_root_file_count"],
  "copy_root_bytes":plan["copy_root_bytes"],"payload_retirement_count":plan["payload_retirement_count"],
  "payload_retirement_bytes":plan["payload_retirement_bytes"]})
 return receipt

def main() -> int:
 parser=argparse.ArgumentParser()
 parser.add_argument("--plan",type=Path,required=True)
 parser.add_argument("--authorized-plan-sha",required=True)
 parser.add_argument("--expected-main",required=True)
 parser.add_argument("--execute",action="store_true")
 args=parser.parse_args()
 if not args.execute: raise SystemExit("EXECUTION_FLAG_REQUIRED")
 plan=json.loads(args.plan.read_text(encoding="utf-8"))
 try:
  verify_plan(plan,args.authorized_plan_sha)
  head=verify_git(plan,args.expected_main)
  verify_all(plan)
  receipt=execute(plan,args.authorized_plan_sha,head)
 except RuntimeError as error: raise SystemExit(str(error)) from error
 print(receipt); return 0

if __name__=="__main__": raise SystemExit(main())
