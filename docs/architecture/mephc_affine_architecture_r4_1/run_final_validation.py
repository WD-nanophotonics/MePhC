"""Explicit R4.1 validation orchestration.

All repository roots and external drivers are supplied by CLI. Runtime paths
are never written to the committed command record.
"""
from __future__ import annotations
import argparse,json,subprocess,sys,time
from pathlib import Path

def run(label, command, cwd=None, env=None):
    started=time.monotonic()
    p=subprocess.run(command,cwd=cwd,text=True,capture_output=True,check=False,env=env)
    elapsed=time.monotonic()-started
    return {"label":label,"command":label+" <explicit-args>","exit_code":p.returncode,"duration_s":round(elapsed,6),"stdout":p.stdout,"stderr":p.stderr}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mephc-root",required=True)
    ap.add_argument("--sqrlatt-root",required=True)
    ap.add_argument("--trilatt-root",required=True)
    ap.add_argument("--r31-validator",required=True)
    ap.add_argument("--r4-smoke-driver",required=True)
    ap.add_argument("--expected-mephc-ref",required=True)
    ap.add_argument("--expected-payload-ref",required=True)
    ap.add_argument("--phase",choices=["preseal","final"],default="final")
    a=ap.parse_args()
    root=Path(__file__).resolve().parent
    py=sys.executable
    mephc=Path(a.mephc_root); sqr=Path(a.sqrlatt_root); tri=Path(a.trilatt_root)
    records=[]
    records.append(run("r4_1_bundle_validation",[py,str(root/"validate_r4_1.py"),"--check-bundle","--bundle-root",str(root)]))
    records.append(run("real_targeted_negative_fixtures",[py,str(root/"run_negative_fixtures.py")]))
    records.append(run("mephc_full_tests",[py,"-m","unittest","discover","-s",str(mephc/"tests"),"-p","test*.py"],cwd=mephc))
    records.append(run("sqrlatt_full_tests",[py,"-m","unittest","discover","-s",str(sqr/"tests"),"-p","test*.py"],cwd=sqr,env={**__import__("os").environ,"PYTHONPATH":str(mephc)+":"+str(sqr)}))
    records.append(run("trilatt_full_tests_readonly",[py,"-m","unittest","discover","-s",str(tri/"tests"),"-p","test*.py"],cwd=tri,env={**__import__("os").environ,"PYTHONPATH":str(mephc)+":"+str(tri)}))
    records.append(run("compileall",[py,"-m","compileall","-q",str(mephc/"mephc"),str(sqr),str(tri)]))
    records.append(run("r3_1_final_validator",[py,str(a.r31_validator),"--check-bundle","--bundle-root",str(mephc/"docs/architecture/mephc_affine_architecture_r3_1")]))
    records.append(run("five_existing_r4_production_smokes",[py,str(a.r4_smoke_driver)]))
    if a.phase=="final":
        records.append(run("r4_1_live_worktree_validation",[py,str(root/"validate_r4_1.py"),"--check-worktrees","--bundle-root",str(root),"--mephc-root",str(mephc),"--sqrlatt-root",str(sqr),"--trilatt-root",str(tri),"--expected-mephc-ref",a.expected_mephc_ref,"--expected-payload-ref",a.expected_payload_ref]))
    records.append(run("git_diff_check",[ "git","-c","core.filemode=false","-C",str(mephc),"diff","--check",a.expected_payload_ref,a.expected_mephc_ref]))
    result={"schema":"mephc.r4_1.orchestration_result.v1","phase":a.phase,"all_passed":all(r["exit_code"]==0 for r in records),"records":records}
    (root/"logs"/f"orchestration_{a.phase}.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))
    return 0 if result["all_passed"] else 1

if __name__=="__main__":
    raise SystemExit(main())
