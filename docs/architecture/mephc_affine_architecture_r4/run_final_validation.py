
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import os, subprocess, sys, json

bundle=Path("/home/icy/MePhC/docs/architecture/mephc_affine_architecture_r4")
logdir=bundle/"logs"; logdir.mkdir(exist_ok=True)
py="/home/icy/miniconda3/envs/mp/bin/python"
env=os.environ.copy(); env["PYTHONPATH"]="/home/icy/MePhC:/home/icy/SqrLatt"
commands=[
 ("compileall.log",[py,"-m","compileall","-q","/home/icy/MePhC/mephc","/home/icy/SqrLatt"],"/home/icy/MePhC"),
 ("mephc_tests.log",[py,"-m","unittest","discover","-s","/home/icy/MePhC/tests","-q"],"/home/icy/MePhC"),
 ("trilatt_tests.log",[py,"-m","unittest","discover","-s","/home/icy/TriLatt/tests","-q"],"/home/icy/TriLatt"),
 ("sqrlatt_tests.log",[py,"-m","unittest","discover","-s","/home/icy/SqrLatt/tests","-q"],"/home/icy/SqrLatt"),
 ("r31_validator.log",[py,"/home/icy/MePhC/docs/architecture/mephc_affine_architecture_r3_1/validate_r3_1.py","--check-bundle","--bundle-root","/home/icy/MePhC/docs/architecture/mephc_affine_architecture_r3_1"],"/home/icy/MePhC"),
 ("git_diff_check_mephc.log",["git","-C","/home/icy/MePhC","diff","--check","38a865b76c57d2dbaef3305dc1dee446c9c6043a","HEAD"],"/home/icy/MePhC"),
 ("git_diff_check_sqrlatt.log",["git","-C","/home/icy/SqrLatt","diff","--check","8a1e4534a48e01a83996fb199ccd55e0983e72b2","HEAD"],"/home/icy/SqrLatt"),
]
results=[]
for name,cmd,cwd in commands:
    p=subprocess.run(cmd,text=True,capture_output=True,env=env,cwd=cwd)
    (logdir/name).write_text(p.stdout+("\n[stderr]\n"+p.stderr if p.stderr else ""),encoding="utf-8")
    results.append({"id":name.removesuffix(".log"),"command":" ".join(cmd),"status":"PASS" if p.returncode==0 else "FAIL","exit_code":p.returncode,"log_path":"logs/"+name})
(bundle/"final_validation_commands.json").write_text(json.dumps({"schema":"mephc.r4.final_validation.v1","created_at":datetime.now(timezone.utc).isoformat(),"commands":results,"status":"PASS" if all(x["status"]=="PASS" for x in results) else "FAIL"},indent=2)+"\n")
if not all(x["status"]=="PASS" for x in results):
    raise SystemExit(1)
print("R4 final validation commands PASS")
