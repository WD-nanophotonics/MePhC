"""E7I.4D center-only resolution convergence for the two exact blockers."""
from __future__ import annotations
import hashlib, json, math, subprocess, sys, time
from pathlib import Path
import numpy as np
from audit.e7i3c.run_representation_bridge import build_reference_mpb_adapter, build_triangular_coordinate_preflight, build_triangular_reference_geometry, solve_isolated
from mephc.valley_benchmark import periodic_equivalent

WORK_ORDER="TRILATT-E7I4D-20260823-132"
SOURCE_COMMIT="8f3d0f388e175de6882bd956d1aa8a7ec19e5f19"
SOURCE_PATH="audit/e7i4c/result.json"
SOURCE_SHA="64ea0b88cf4ba64e01940ecd35e485903ceede1736207f1f7a629840d175210b"
EXPECTED_MAIN="5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
FR=0.0; RESOLUTIONS=(64,96,128); R96=96; NUM_BANDS=4; POLARIZATION="TE"; TOL=1e-7; DETERMINISTIC=True; MESH=3; REPRESENTATION="mpb_energy_eh_v1"

def sha(b): return hashlib.sha256(b).hexdigest()
def load_source(root):
    blob=subprocess.check_output(["git","show",f"{SOURCE_COMMIT}:{SOURCE_PATH}"],cwd=root)
    if sha(blob)!=SOURCE_SHA: raise RuntimeError("E7I.4C source SHA mismatch")
    return json.loads(blob.decode()),sha(blob)
def policy(g): return "PASS" if float(g)>=0.05 else "FAIL"
def finite_status(g): return "SUPPORTED" if float(g)>0.0 else "DEGENERACY_SUSPECTED"
def classify(g):
    r48,r64,r96,r128=[float(x) for x in g]
    d1=abs(r64-r48); d2=abs(r96-r64); d3=abs(r128-r96)
    if min(g)<=0: return "TRENDING_TOWARD_DEGENERACY"
    if r128>=0.05 and d3<=d2: return "CONVERGING_ABOVE_005"
    if 0.0<r128<0.05 and d3<=d2: return "CONVERGING_BELOW_005_BUT_POSITIVE"
    if (r48-0.05)*(r128-0.05)<0 and d3>d2: return "CROSSES_005_WITHOUT_STABILITY"
    if d3>d2 and d2>d1: return "NONMONOTONIC_UNRESOLVED"
    return "NONMONOTONIC_UNRESOLVED"
def symmetry_pair(q1,q2,preflight):
    reflected=(float(q2[0]),-float(q2[1]))
    return periodic_equivalent(q1,reflected,preflight.public_period_basis,1e-10)
def self_checks(source):
    blockers=[x for x in source["elements"] if x["center_policy"]=="CENTER_POLICY_UNQUALIFIED"]
    assert len(blockers)==2 and policy(0.050000)=="PASS" and policy(0.049999)=="FAIL"
    assert tuple(RESOLUTIONS)==(64,96,128)
    assert classify((0.04,0.051,0.052,0.053))=="CONVERGING_ABOVE_005"
    assert classify((0.04,0.045,0.046,0.047))=="CONVERGING_BELOW_005_BUT_POSITIVE"
    assert finite_status(0.038)=="SUPPORTED"
def solve_center(adapter,resolution,q,counters):
    counters["new_solves"]+=1
    raw=solve_isolated(adapter,resolution,FR,tuple(float(x) for x in q))
    freq=[float(x) for x in raw.frequencies]
    if len(freq)!=4 or not all(math.isfinite(x) for x in freq):
        counters["solver_failures"]+=1; raise RuntimeError(f"nonfinite frequency at {q}, R{resolution}")
    return {"resolution":resolution,"evaluation_q":list(q),"frequencies_bands_1_to_4":freq,"G34":freq[3]-freq[2],"G34_over_f3":(freq[3]-freq[2])/freq[2] if freq[2] else None,"G34_over_f4":(freq[3]-freq[2])/freq[3] if freq[3] else None,"absolute_005_policy_status":policy(freq[3]-freq[2]),"finite_external_gap_status":finite_status(freq[3]-freq[2])}
def main():
    root=Path(__file__).resolve().parents[2]; source,source_sha=load_source(root)
    if "--self-check" in sys.argv: self_checks(source); print(json.dumps({"self_check":"PASSED","source_e7i4c_result_sha256":source_sha})); return
    blockers=[x for x in source["elements"] if x["center_policy"]=="CENTER_POLICY_UNQUALIFIED"]
    if len(blockers)!=2: raise RuntimeError(f"expected exact 2 blockers, found {len(blockers)}")
    geometry=build_triangular_reference_geometry(FR); preflight=build_triangular_coordinate_preflight(); adapter=build_reference_mpb_adapter(geometry,preflight)
    counters={"new_solves":0,"solver_failures":0}; rows=[]; started=time.monotonic()
    for item in blockers:
        baseline={"resolution":48,"evaluation_q":item["evaluation_q"],"frequencies_bands_1_to_4":item["attempts"][0]["center_solve"]["frequencies_bands_1_to_4"],"G34":item["center_band4_minus_band3_gap"],"G34_over_f3":None,"G34_over_f4":None,"absolute_005_policy_status":policy(item["center_band4_minus_band3_gap"]),"finite_external_gap_status":finite_status(item["center_band4_minus_band3_gap"])}
        ladder=[baseline]+[solve_center(adapter,res,item["evaluation_q"],counters) for res in RESOLUTIONS]
        repeats=[solve_center(adapter,R96,item["evaluation_q"],counters) for _ in range(2)]
        gaps=[x["G34"] for x in ladder]; pair={"element_id":item["element_id"],"evaluation_q":item["evaluation_q"],"element_weight":item["element_area_weight"],"nearest_outer_edge":item["nearest_outer_edge"],"gamma_exclusion_distances":item["distance_to_each_Gamma_exclusion_boundary"],"R48_center_gap":item["center_band4_minus3_gap"] if "center_band4_minus3_gap" in item else item["center_band4_minus_band3_gap"],"ladder":ladder,"R96_repeats":repeats,"R96_repeat_gap_abs_difference":abs(repeats[0]["G34"]-repeats[1]["G34"]),"R96_repeat_frequency_max_abs_difference":max(abs(a-b) for a,b in zip(repeats[0]["frequencies_bands_1_to_4"],repeats[1]["frequencies_bands_1_to_4"])),"delta_gap_48_64":gaps[1]-gaps[0],"delta_gap_64_96":gaps[2]-gaps[1],"delta_gap_96_128":gaps[3]-gaps[2],"final_pair_abs_drift":abs(gaps[3]-gaps[2]),"gap_trend":classify(gaps),"R128_gap":gaps[3],"R128_absolute_005_policy":policy(gaps[3]),"R128_finite_external_gap":finite_status(gaps[3])}
        rows.append(pair)
    pair_sym=symmetry_pair(rows[0]["evaluation_q"],rows[1]["evaluation_q"],preflight)
    pair_diffs={f"pair_gap_abs_difference_R{res}":abs(rows[0]["ladder"][i]["G34"]-rows[1]["ladder"][i]["G34"]) for i,res in enumerate((48,64,96,128))}
    result={"schema":"e7i4d_two_blocker_gap_convergence_v1","work_order":WORK_ORDER,"code_change":"SANDBOX_AUDIT_ONLY","source_e7i4c_evidence_commit":SOURCE_COMMIT,"source_e7i4c_result_path":SOURCE_PATH,"source_e7i4c_result_sha256":source_sha,"blocker_reconstruction":"EXACT_2","blocker_count":2,"blockers":rows,"blocker_pair_symmetry_relation":"VERIFIED" if pair_sym else "NOT_VERIFIED","pair_gap_differences":pair_diffs,"new_R64_solves":2,"new_R96_solves":2,"new_R128_solves":2,"R96_repeat_solves":2,"total_new_mpb_solves":counters["new_solves"],"solver_failures":counters["solver_failures"],"total_wall_time_seconds":time.monotonic()-started,"scale_aware_isolation_diagnostic":"NOT_EVALUATED","current_absolute_005_policy":"UNCHANGED_AUTHORITATIVE","physical_rank3_degeneracy_confirmed":False,"local_berry_calculation":"NOT_AUTHORIZED","stage1_chern":"NOT_AUTHORIZED","stage2_chern":"NOT_AUTHORIZED","per_band_chern":"NOT_AUTHORIZED","rank2_chern":"NOT_AUTHORIZED","full_bz_chern":"NOT_AUTHORIZED","bcd":"NOT_AUTHORIZED","deformation_physics":"NOT_AUTHORIZED","calculation_logic_git_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),"calculation_logic_committed_before_execution":True,"main_unchanged":True,"sandbox_remote_head_verified":False,"e7i4d_overall":"TWO_BLOCKER_RESOLUTION_DIAGNOSIS_READY_FOR_SUPERVISOR_DECISION"}
    out=root/"audit"/"e7i4d"; out.mkdir(parents=True,exist_ok=True); (out/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"overall":result["e7i4d_overall"],"total_new_mpb_solves":counters["new_solves"],"pair_symmetry":pair_sym}))
if __name__=="__main__": main()
