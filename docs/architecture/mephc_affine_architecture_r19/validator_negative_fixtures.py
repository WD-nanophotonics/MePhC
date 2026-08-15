#!/usr/bin/env python3
import json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).parent
def fixture(name,mut):
 with tempfile.TemporaryDirectory(prefix="r19-negative-") as t:
  d=Path(t)/"bundle";shutil.copytree(ROOT,d,ignore=shutil.ignore_patterns("__pycache__","*.pyc","logs"));mut(d);p=subprocess.run([sys.executable,str(d/"validate_r19.py"),"--root",str(d)],capture_output=True)
  if p.returncode==0:raise SystemExit("fixture passed: "+name)
  print(json.dumps({"case":name,"status":"REJECTED"},sort_keys=True))
fixture("q-phase mutation",lambda d:d.joinpath("bloch_boundary_definition.json").write_text(json.dumps({**json.loads(d.joinpath("bloch_boundary_definition.json").read_text()),"q2":[0.09,0.14]}),encoding="utf-8"))
fixture("zero-solver mutation",lambda d:d.joinpath("solver_execution.json").write_text(json.dumps({**json.loads(d.joinpath("solver_execution.json").read_text()),"mpb_or_meep_independent_solver_calls":1}),encoding="utf-8"))
print(json.dumps({"status":"PASS","fixtures":2},sort_keys=True))
