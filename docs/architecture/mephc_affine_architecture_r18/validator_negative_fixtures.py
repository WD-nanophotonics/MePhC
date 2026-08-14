#!/usr/bin/env python3
import json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).parent
def run(name,mut):
 with tempfile.TemporaryDirectory(prefix="r18-negative-") as t:
  d=Path(t)/"bundle";shutil.copytree(ROOT,d,ignore=shutil.ignore_patterns("__pycache__","*.pyc","logs"));mut(d)
  p=subprocess.run([sys.executable,str(d/"validate_r18.py"),"--root",str(d)],capture_output=True,text=True)
  if p.returncode==0:raise SystemExit("fixture passed: "+name)
  print(json.dumps({"case":name,"status":"REJECTED"},sort_keys=True))
run("gate mutation",lambda d:d.joinpath("r17_gate_reconstruction.json").write_text(json.dumps({**json.loads(d.joinpath("r17_gate_reconstruction.json").read_text()),"conditions":{**json.loads(d.joinpath("r17_gate_reconstruction.json").read_text())["conditions"],"cross_pass":False}},indent=2)))
run("solver mutation",lambda d:d.joinpath("solver_execution.json").write_text(json.dumps({**json.loads(d.joinpath("solver_execution.json").read_text()),"fresh_solver_calls":1},indent=2)))
print(json.dumps({"status":"PASS","fixtures":2},sort_keys=True))
