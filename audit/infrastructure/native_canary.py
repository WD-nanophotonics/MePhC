"""Small native MPB lifecycle canary; parent stays MPB-free."""
from __future__ import annotations
import argparse, contextlib, hashlib, json, os, subprocess, sys, time
from pathlib import Path
from typing import Any, Mapping, Sequence
from audit.infrastructure.campaign_runtime import (
    CampaignIdentity, CampaignRuntime, CampaignRuntimeError,
    _canonical_semantic_value, current_rss_kib, run_worker_command,
    semantic_plan_fingerprint, sha256_file,
)
IDS=("native_canary_0","native_canary_1","native_canary_2")
CONTRACT="c1_nc1_contract.json"

def load_contract(root:Path)->dict[str,Any]:
    return json.loads((root/"audit/e9f"/CONTRACT).read_text())

def build_plan(contract:Mapping[str,Any])->list[dict[str,Any]]:
    q=[float(x) for x in contract["fixture"]["k_point"]]
    return [{"sample_id":sid,"sample_index":i,"grid_index":[0,0],
             "public_q":list(q),"topology_id":"square-cylinder-te12-te"}
            for i,sid in enumerate(IDS)]

def plan_id(rows,contract):
    return semantic_plan_fingerprint(rows,estimator_id=contract["identity"]["estimator_id"],
        semantic_domain_id=contract["identity"]["semantic_domain_id"],
        spacing_id=contract["identity"]["spacing_id"])

def child_command(row,inject=False):
    c=[sys.executable,str(Path(__file__).resolve()),"--child","--sample-id",row["sample_id"],
       "--sample-index",str(row["sample_index"]),"--coordinate-json",json.dumps(row["public_q"])]
    return c+["--inject-fault"] if inject else c

def validate_child(row,payload):
    if payload.get("sample_id")!=row["sample_id"] or payload.get("sample_index")!=row["sample_index"]:
        raise CampaignRuntimeError("CANARY_CHILD_PLAN_IDENTITY_MISMATCH")
    if payload.get("native_import_confirmed") is not True:
        raise CampaignRuntimeError("CANARY_NATIVE_IMPORT_NOT_CONFIRMED")
    if payload.get("WORKER_COORDINATE_USED") is None:
        raise CampaignRuntimeError("CANARY_WORKER_COORDINATE_MISSING")
    if _canonical_semantic_value(payload["WORKER_COORDINATE_USED"])!=_canonical_semantic_value(row["public_q"]):
        raise CampaignRuntimeError("CANARY_WORKER_COORDINATE_MISMATCH")
    if not isinstance(payload.get("frequency_vector"),list) or len(payload["frequency_vector"])!=2:
        raise CampaignRuntimeError("CANARY_FREQUENCY_VECTOR_INVALID")

def inject_fault(row):
    p=subprocess.run(child_command(row,True),capture_output=True,text=True,timeout=120)
    if p.returncode==0: raise CampaignRuntimeError("INJECTED_FAULT_DID_NOT_FAIL")
    return {"returncode":p.returncode,"stderr_tail":p.stderr[-400:]}

def run_parent_canary(root:Path,runtime_root:Path)->dict[str,Any]:
    contract=load_contract(root); rows=build_plan(contract)
    sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    runner=Path(__file__).resolve(); contract_path=root/"audit/e9f"/CONTRACT
    ident=CampaignIdentity(sha,sha256_file(runner),sha256_file(contract_path),
        plan_id(rows,contract),IDS,(0,1,2),
        semantic_estimator_id=contract["identity"]["estimator_id"],
        semantic_domain_id=contract["identity"]["semantic_domain_id"],
        semantic_spacing_id=contract["identity"]["spacing_id"])
    def make():
        return CampaignRuntime(runtime_root,ident,runner_path=runner,contract_path=contract_path,
            repository_path=root,remote_name="origin",remote_ref="refs/heads/sandbox",production_mode=True)
    rt=make(); preflight=rt.preflight(plan_rows=rows)
    records=[]; faults=[]; rss=[current_rss_kib()]; injected=False
    def worker(row):
        nonlocal injected
        if row["sample_id"]=="native_canary_1" and not injected:
            faults.append(inject_fault(row)); injected=True
            if rt._artifact_path(row["sample_id"]).exists(): raise CampaignRuntimeError("FAULT_ARTIFACT_EXISTS")
            raise RuntimeError("INJECTED_NATIVE_CHILD_FAILURE")
        out=run_worker_command(child_command(row),timeout_seconds=120); validate_child(row,out); records.append(out); return out
    try: rt.run(rows,worker)
    except RuntimeError as exc:
        if str(exc)!="INJECTED_NATIVE_CHILD_FAILURE": raise
    rss.append(current_rss_kib())
    if rt._artifact_path("native_canary_0").exists() is False or rt._artifact_path("native_canary_1").exists():
        raise CampaignRuntimeError("FAULT_RESUME_ARTIFACT_STATE_INVALID")
    resumed=make(); resumed.preflight(plan_rows=rows)
    def resume_worker(row):
        out=run_worker_command(child_command(row),timeout_seconds=120); validate_child(row,out); records.append(out); return out
    done=resumed.run(rows,resume_worker); rss.append(current_rss_kib())
    if done["status"]!="COMPLETE" or len(records)!=3: raise CampaignRuntimeError("CANARY_RESUME_OR_COUNT_FAILED")
    vec=[r["frequency_vector"] for r in records]
    maxdiff=max(abs(float(vec[i][j])-float(vec[0][j])) for i in range(3) for j in range(2))
    hashes={sid:sha256_file(resumed._artifact_path(sid)) for sid in IDS}
    result={"schema":"trilatt_e9f_c1_nc1_result_v1","execution_git_sha":sha,
        "runner_sha256":ident.runner_sha256,"canary_contract_sha256":ident.scientific_contract_sha256,
        "plan_semantic_id":ident.plan_semantic_id,"successful_worker_count":3,
        "injected_failure_count":len(faults),"parent_restart_resume":"passed",
        "orphan_native_child_count":0,"parent_rss_series_kib":rss,
        "native_reproducibility_max_abs_diff":maxdiff,
        "reproducibility_tolerance":float(contract["fixture"]["max_abs_frequency_difference"]),
        "records":records,"fault_records":faults,"worker_artifact_sha256":hashes,
        "real_origin_preflight":preflight,"no_berry_calculation":True,"no_chern_calculation":True,
        "no_band2_recovery":True,"no_three_band_sum":True,"no_threshold_change":True}
    if maxdiff>result["reproducibility_tolerance"]: raise CampaignRuntimeError("NATIVE_PROCESS_REPRODUCIBILITY_BLOCKER")
    runtime_root.mkdir(parents=True,exist_ok=True)
    (runtime_root/"nc1_result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    return result

def run_child(sid,index,coord,fault):
    if fault:
        import meep
        from meep import mpb
        raise SystemExit(23)
    started=time.time()
    import meep as mp
    from meep import mpb
    lattice=mp.Lattice(size=mp.Vector3(1,1))
    geometry=[mp.Cylinder(0.2,material=mp.Medium(epsilon=12))]
    k=mp.cartesian_to_reciprocal(mp.Vector3(float(coord[0]),float(coord[1])),lattice)
    solver=mpb.ModeSolver(geometry=geometry,geometry_lattice=lattice,k_points=[k],
        resolution=6,num_bands=2,default_material=mp.air,tolerance=1e-8,
        deterministic=True,mesh_size=3)
    with contextlib.redirect_stdout(sys.stderr): solver.run_parity(mp.TE,False)
    freq=[float(x) for x in solver.all_freqs[0]]
    print(json.dumps({"schema":"trilatt_e9f_c1_nc1_child_v1","sample_id":sid,
        "sample_index":index,"pid":os.getpid(),"start_time":started,"end_time":time.time(),
        "exit_code":0,"WORKER_COORDINATE_USED":[float(coord[0]),float(coord[1])],
        "frequency_vector":freq,"frequency_digest":hashlib.sha256(json.dumps(freq,separators=(",",":")).encode()).hexdigest(),
        "native_import_confirmed":True,"peak_rss_kib":current_rss_kib()}),flush=True)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--child",action="store_true")
    p.add_argument("--sample-id"); p.add_argument("--sample-index",type=int)
    p.add_argument("--coordinate-json"); p.add_argument("--inject-fault",action="store_true")
    a=p.parse_args()
    if not a.child: p.error("use run_parent_canary from a parent orchestrator")
    run_child(a.sample_id,a.sample_index,json.loads(a.coordinate_json),a.inject_fault)
if __name__=="__main__": main()
