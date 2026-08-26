#!/home/icy/miniconda3/envs/mp/bin/python
"""Transactional, fail-closed materializer for typed MePhC change jobs."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path, PurePosixPath
from typing import Any
ROOT=Path("/home/icy/MePhC"); PYTHON=Path("/home/icy/miniconda3/envs/mp/bin/python")
class Failure(RuntimeError):
    def __init__(self,code:str,detail:str): self.code,self.detail=code,detail; super().__init__(f"{code}: {detail}")
def digest(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def run(*args:str,check:bool=True)->subprocess.CompletedProcess[str]:
    value=subprocess.run(args,cwd=ROOT,text=True,encoding="utf-8",stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if check and value.returncode: raise Failure("CHANGE_COMMAND_FAILED",value.stderr.strip() or value.stdout.strip())
    return value
def git(*args:str)->str: return run("/usr/bin/git",*args).stdout.strip()
def atomic(path:Path,data:bytes)->None:
    path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle: handle.write(data); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary,path)
def write_json(path:Path,value:dict[str,Any])->None: atomic(path,(json.dumps(value,sort_keys=True,indent=2)+"\n").encode())
def safe_path(value:str)->Path:
    pure=PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or pure.parts[0] in {".git",".relayctl"} or "\\" in value: raise Failure("CHANGE_PATH_INVALID",value)
    cursor=ROOT
    for part in pure.parts:
        cursor/=part
        if cursor.is_symlink(): raise Failure("CHANGE_SYMLINK_FORBIDDEN",value)
    return cursor
def tests(values:Any)->list[str]:
    if not isinstance(values,list) or not values: raise Failure("CHANGE_TESTS_INVALID","non-empty test list required")
    for value in values:
        if not isinstance(value,str) or value.startswith("-"): raise Failure("CHANGE_TESTS_INVALID",repr(value))
        part=value.split("::",1)[0]; path=safe_path(part)
        if PurePosixPath(part).parts[:1] != ("tests",) or path.suffix != ".py" or not path.is_file(): raise Failure("CHANGE_TESTS_INVALID",value)
    return values
def load(job_dir:Path)->tuple[dict[str,Any],list[dict[str,Any]],list[str]]:
    job=json.loads((job_dir/"job.json").read_text(encoding="utf-8")); unsigned={k:v for k,v in job.items() if k!="payload_sha256"}
    expected=digest(json.dumps(unsigned,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
    if job.get("operation")!="change" or job.get("payload_sha256")!=expected: raise Failure("CHANGE_JOB_INVALID",str(job_dir))
    change=job.get("change"); records=change.get("files") if isinstance(change,dict) else None
    if not isinstance(records,list) or not records: raise Failure("CHANGE_FILES_INVALID","files required")
    normalized=[]; seen=set()
    for item in records:
        keys={"path","expected_preimage_sha256","expected_postimage_sha256","content_utf8"}
        if not isinstance(item,dict) or set(item)!=keys: raise Failure("CHANGE_FILE_SCHEMA_INVALID",repr(item))
        path=safe_path(item["path"]); folded=item["path"].casefold()
        if folded in seen: raise Failure("CHANGE_PATH_COLLISION",item["path"])
        seen.add(folded)
        try: data=item["content_utf8"].encode("utf-8")
        except (AttributeError,UnicodeEncodeError) as exc: raise Failure("CHANGE_UTF8_INVALID",item["path"]) from exc
        if digest(data)!=item["expected_postimage_sha256"]: raise Failure("CHANGE_POSTIMAGE_MISMATCH",item["path"])
        normalized.append({**item,"absolute":path,"data":data})
    message=change.get("commit_message")
    if not isinstance(message,str) or not message.strip() or "\n" in message or len(message)>120: raise Failure("CHANGE_COMMIT_MESSAGE_INVALID",repr(message))
    return job,normalized,tests(change.get("tests"))
def baseline(job:dict[str,Any],files:list[dict[str,Any]])->None:
    if Path.cwd().resolve()!=ROOT or Path(sys.executable).resolve()!=PYTHON.resolve(): raise Failure("CHANGE_RUNTIME_MISMATCH",f"cwd={Path.cwd()} python={sys.executable}")
    if git("rev-parse","HEAD")!=job["expected_head"]: raise Failure("HEAD_MOVED",job["expected_head"])
    main=git("ls-remote","origin","refs/heads/main").split()[0]
    if main!=job["change"]["expected_main"]: raise Failure("MAIN_MOVED",f"expected={job['change']['expected_main']} actual={main}")
    if git("status","--porcelain","--untracked-files=all"): raise Failure("CHANGE_DIRTY_BASELINE","worktree must be clean")
    if git("symbolic-ref","--short","HEAD") in {"main","master"}: raise Failure("CHANGE_MAIN_BRANCH_FORBIDDEN","main")
    for item in files:
        path=item["absolute"]
        if path.exists() and not path.is_file(): raise Failure("CHANGE_PATH_INVALID",item["path"])
        actual=digest(path.read_bytes()) if path.is_file() else "MISSING"
        if actual!=item["expected_preimage_sha256"]: raise Failure("CHANGE_PREIMAGE_MISMATCH",f"{item['path']}: {actual}")
def backup(job_dir:Path,files:list[dict[str,Any]])->None:
    root=job_dir/"change-backup"; root.mkdir(exist_ok=False); manifest=[]
    for index,item in enumerate(files):
        existed=item["absolute"].is_file(); name=f"{index:04d}.bin"
        if existed: atomic(root/name,item["absolute"].read_bytes())
        manifest.append({"path":item["path"],"existed":existed,"backup":name if existed else None})
    write_json(root/"manifest.json",{"files":manifest})
def restore(job_dir:Path)->None:
    manifest_path=job_dir/"change-backup"/"manifest.json"
    if not manifest_path.is_file(): return
    paths=[]
    for item in json.loads(manifest_path.read_text())["files"]:
        path=safe_path(item["path"]); paths.append(item["path"])
        if item["existed"]: atomic(path,(manifest_path.parent/item["backup"]).read_bytes())
        elif path.exists(): path.unlink()
    run("/usr/bin/git","restore","--staged","--",*paths,check=False)
def changed()->set[str]:
    return set(filter(None,git("diff","--name-only").splitlines()))|set(filter(None,git("ls-files","--others","--exclude-standard").splitlines()))
def apply(job_dir:Path)->dict[str,Any]:
    job,files,target_tests=load(job_dir); baseline(job,files); backup(job_dir,files); journal=job_dir/"change-journal.json"; write_json(journal,{"phase":"backed_up","expected_head":job["expected_head"]})
    try:
        for item in files: atomic(item["absolute"],item["data"])
        write_json(journal,{"phase":"written","expected_head":job["expected_head"]})
        expected_paths={item["path"] for item in files}
        if changed()!=expected_paths: raise Failure("CHANGE_UNEXPECTED_DIFF",repr(sorted(changed())))
        result=run(str(PYTHON),"-m","pytest","-q",*target_tests,check=False); (job_dir/"change-test.log").write_text(result.stdout+result.stderr,encoding="utf-8")
        if result.returncode: raise Failure("CHANGE_TEST_FAILED",f"returncode={result.returncode}")
        run("/usr/bin/git","add","--",*sorted(expected_paths)); run("/usr/bin/git","commit","-m",job["change"]["commit_message"]); final=git("rev-parse","HEAD")
        write_json(journal,{"phase":"committed","expected_head":job["expected_head"],"final_commit":final})
        attestation={"schema":"mephc-change-attestation-v1","job_id":job["job_id"],"base_head":job["expected_head"],"final_commit":final,"files":{x["path"]:x["expected_postimage_sha256"] for x in files},"tests":target_tests,"test_returncode":0}; write_json(job_dir/"change-attestation.json",attestation); return attestation
    except Exception:
        if git("rev-parse","HEAD")==job["expected_head"]: restore(job_dir)
        raise
def recover(job_dir:Path)->int:
    journal_path=job_dir/"change-journal.json"
    if not journal_path.is_file(): return 2
    journal=json.loads(journal_path.read_text()); actual=git("rev-parse","HEAD")
    if journal.get("phase")=="committed" and actual==journal.get("final_commit") and not git("status","--porcelain","--untracked-files=all"): return 0
    if actual==journal.get("expected_head"): restore(job_dir); return 3
    return 2
def transact(job_dir:Path)->int:
    state_path=job_dir/"materializer-state.json"; write_json(state_path,{"state":"running"})
    try:
        value=apply(job_dir); write_json(state_path,{"state":"succeeded","final_commit":value["final_commit"]}); return 0
    except Exception as exc:
        try:
            journal=job_dir/"change-journal.json"
            if journal.is_file() and git("rev-parse","HEAD")==json.loads(journal.read_text()).get("expected_head"): restore(job_dir)
        except Exception: pass
        code=exc.code if isinstance(exc,Failure) else "CHANGE_INTERNAL_ERROR"
        write_json(state_path,{"state":"failed","error_code":code,"detail":repr(exc)})
        return 2

def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("mode",choices=("apply","recover","transact")); parser.add_argument("job_directory"); args=parser.parse_args()
    try:
        if args.mode=="recover": return recover(Path(args.job_directory))
        value=apply(Path(args.job_directory)); print(json.dumps({"event":"change_committed",**value},sort_keys=True)); return 0
        if args.mode=="transact": return transact(Path(args.job_directory))
    except Failure as exc: print(json.dumps({"event":"change_failed","error_code":exc.code,"detail":exc.detail},sort_keys=True)); return 2
    except Exception as exc: print(json.dumps({"event":"change_failed","error_code":"CHANGE_INTERNAL_ERROR","detail":repr(exc)},sort_keys=True)); return 2
if __name__=="__main__": raise SystemExit(main())
