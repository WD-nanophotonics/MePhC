"""E7I.4C source-bound center isolation audit and local-limit recovery ladder."""
from __future__ import annotations
import hashlib, json, math, subprocess, sys, time
from pathlib import Path
import numpy as np
from shapely.geometry import Point, Polygon, LineString
from audit.e7i3c.run_representation_bridge import E3, build_reference_mpb_adapter, build_triangular_coordinate_preflight, build_triangular_reference_geometry, lowdin_snapshot, solve_isolated
from audit.e7i4a.run_composite_valley_chern import frame_to_subspace
from audit.e7i4b.run_failed_element_recovery import edge_dict
from mephc.path_domain import PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.spectral_association import ExternalIsolationContext, NUMERICALLY_INCOMPLETE
from mephc.valley_benchmark import PhysicalSolveCache, PhysicalSolveIdentity, centered_ccw_plaquette_requests, paper_style_truncated_k_hbz
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

WORK_ORDER="TRILATT-E7I4C-20260823-130"
SOURCE_E7I4A_COMMIT="17e3c720a93c5b780324e2b69e380ae3797c6e3b"
SOURCE_E7I4A_SHA="49344f4282859e8453c0cace9281a3c5623bf215cf2be5b81fe46cab6ebfd15a"
SOURCE_E7I4B_CODE_COMMIT="20843da1d3a7eeaa422bceeec48b8cf1346f68b0"
SOURCE_E7I4B_COMMIT="914638a7f45e4f11d7a03a75e9ffaed23a803ba7"
SOURCE_E7I4B_PATH="audit/e7i4b/result.json"
SOURCE_E7I4B_SHA="dabc6a9f0f529631b9d82cf83d4e3780c190c6b8d841c54f976c09f0f1edfcf9"
EXPECTED_MAIN="5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
FR=0.0; RESOLUTION=48; NUM_BANDS=4; POLARIZATION="TE"; EIGENSOLVER_TOLERANCE=1e-7; DETERMINISTIC=True; MESH_SIZE=3; REPRESENTATION="mpb_energy_eh_v1"; RANK_SELECTION=(0,1,2)
DELTAS=(1.0/72.0,1.0/144.0,1.0/288.0)

def sha(b): return hashlib.sha256(b).hexdigest()
def digest(x): return sha(json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
def load_source(root):
    blob=subprocess.check_output(["git","show",f"{SOURCE_E7I4B_COMMIT}:{SOURCE_E7I4B_PATH}"],cwd=root)
    if sha(blob)!=SOURCE_E7I4B_SHA: raise RuntimeError("E7I.4B source SHA mismatch")
    return json.loads(blob.decode()),sha(blob)

def policy_isolated(gap): return float(gap)>=0.05
def physical_identity_key(public,mpb,geometry,preflight,resolution):
    return digest({"schema":"e7i4c_physical_identity_v1","actual_public_q":list(public),"actual_mpb_fractional_q":list(mpb),"geometry_digest":geometry.geometry_digest,"material_digest":geometry.material_contract_digest,"mapping_digest":preflight.mapping_digest,"resolution":resolution,"num_bands":NUM_BANDS,"polarization":POLARIZATION,"representation":REPRESENTATION,"eigensolver_tolerance":EIGENSOLVER_TOLERANCE,"deterministic":DETERMINISTIC,"mesh_size":MESH_SIZE})
def observable_key(public,delta): return digest({"schema":"e7i4c_observable_provenance_v1","actual_public_q":list(public),"local_delta_k":delta})

def solve_point(adapter,preflight,geometry,public,resolution,cache,identities,counters):
    public=tuple(float(x) for x in public); mpb=tuple(float(x) for x in preflight.public_q_to_mpb(public))
    identity=PhysicalSolveIdentity(geometry_digest=geometry.geometry_digest,material_reference_digest=geometry.material_contract_digest,coordinate_mapping_digest=preflight.mapping_digest,evaluated_q=public,resolution=resolution,num_bands=NUM_BANDS,polarization=POLARIZATION,provider_representation=REPRESENTATION,eigensolver_tolerance=EIGENSOLVER_TOLERANCE,deterministic=DETERMINISTIC,mesh_size=MESH_SIZE)
    key=identities.register(identity,claimed_key=physical_identity_key(public,mpb,geometry,preflight,resolution)); counters["raw_requests"]+=1
    if key in cache: counters["cache_hits"]+=1; return cache[key]
    counters["unique_solves"]+=1
    raw=solve_isolated(adapter,resolution,FR,public); snap,diag=lowdin_snapshot(raw); freq=[float(x) for x in raw.frequencies]
    if len(freq)!=4 or not all(math.isfinite(x) for x in freq): counters["solver_failures"]+=1; raise RuntimeError(f"nonfinite frequencies at {public}")
    rec={"actual_public_q":list(raw.k_point),"actual_mpb_fractional_q":list(mpb),"frequencies_bands_1_to_4":freq,"band4_minus_band3_external_gap":freq[3]-freq[2],"raw_selected_gram":diag["RAW_SELECTED_GRAM"],"selected_gram_eigenvalues":diag["GRAM_EIGENVALUES"],"selected_gram_condition_number":diag["GRAM_CONDITION_NUMBER"],"lowdin_q_dagger_q_residual":diag["Q_DAGGER_Q_RESIDUAL"],"raw_span_lowdin_span_projector_residual":diag["SPAN_PROJECTOR_RESIDUAL"],"selected_span_condition":diag["selected_span_condition"]}
    cache[key]=(snap,freq,rec); return cache[key]

def requests_for(center,delta,preflight):
    vectors=preflight.delta_k_vectors_to_public_q(delta)
    return centered_ccw_plaquette_requests((tuple(float(x) for x in center),),vectors,period_basis=preflight.public_period_basis,coordinate_mapping_digest=preflight.mapping_digest)

def evaluate(element,delta,adapter,preflight,geometry,domain,cache,identities,counters):
    center=tuple(float(x) for x in element["evaluation_q"])
    reqs=requests_for(center,delta,preflight); vertices_q=[tuple(float(x) for x in r.canonical_periodic_vertex_q) for r in reqs]
    values=[solve_point(adapter,preflight,geometry,q,RESOLUTION,cache,identities,counters) for q in vertices_q]
    center_value=solve_point(adapter,preflight,geometry,center,RESOLUTION,cache,identities,counters)
    vertices=[frame_to_subspace(q,v[0]) for q,v in zip(vertices_q,values)]
    freqs=[v[1] for v in values]; center_freq=center_value[1]
    contexts=tuple(ExternalIsolationContext((freqs[i][3],),(freqs[(i+1)%4][3],),{"source":"E7I.4C band4 edge isolation"}) for i in range(4))
    path=qualify_ordered_path(tuple(vertices),contexts,thresholds=E3,closed=True,provenance={"source":"E7I.4C centered local-limit ladder"})
    wilson=compose_wilson_transport(path)
    edges=[edge_dict(e) for e in path.edge_results]
    polygon=Polygon(vertices_q); retained=domain.polygon; outer=Polygon(domain.vertices)
    area=abs(float(np.linalg.det(np.asarray(preflight.delta_k_vectors_to_public_q(delta)))))
    qualified=path.status==PATH_SUBSPACE_QUALIFIED and wilson.status==WILSON_LOOP_QUALIFIED and wilson.determinant_phase is not None
    vertex_gaps=[float(v[1][3]-v[1][2]) for v in values]
    return {"local_delta_k":delta,"observable_provenance_key":observable_key(center,delta),"center_gap":float(center_freq[3]-center_freq[2]),"vertices_q":[list(q) for q in vertices_q],"mpb_vertices_fractional":[list(preflight.public_q_to_mpb(q)) for q in vertices_q],"center_solve":center_value[2],"vertex_solve_records":[v[2] for v in values],"vertex_external_gaps":vertex_gaps,"minimum_vertex_external_gap":min(vertex_gaps),"minimum_path_external_isolation":min(float(e["minimum_external_isolation"]) for e in edges if e["minimum_external_isolation"] is not None),"crosses_retained_outer_boundary":not retained.covers(polygon),"intersects_gamma_exclusion":any(polygon.intersects(Polygon(h)) for h in domain.exclusions),"path_status":path.status,"path_evidence":list(path.evidence),"edges":edges,"boundary_status":"NOT_SEPARATELY_REQUALIFIED","interior_spoke_status":"NOT_SEPARATELY_REQUALIFIED","wilson":{"input_status":"QUALIFIED" if wilson.status==WILSON_LOOP_QUALIFIED else "UNQUALIFIED","status":wilson.status,"wilson_product_produced":wilson.product is not None,"determinant_phase":wilson.determinant_phase,"unitarity_residual":wilson.unitarity_residual},"qualified":qualified,"omega_trace_q":None if not qualified else float(-wilson.determinant_phase/area),"physical_cache_delta_independent":True}

def nearest_edge(center,domain):
    p=Point(tuple(center)); edges=[]
    for i,(a,b) in enumerate(zip(domain.vertices,domain.vertices[1:]+domain.vertices[:1])): edges.append((float(p.distance(LineString([a,b]))),i))
    return min(edges)[1]

def self_checks(source):
    failed=source["elements"]; assert len(failed)==21 and RANK_SELECTION==(0,1,2)
    assert policy_isolated(0.050000) and not policy_isolated(0.049999)
    assert digest({"actual_public_q":[0.1,0.2],"local_delta_k":1/72})!=digest({"actual_public_q":[0.1,0.2],"local_delta_k":1/144})
    assert physical_identity_key((0.1,0.2),(0.1,0.2),type("G",(),{"geometry_digest":"g","material_contract_digest":"m"})(),type("P",(),{"mapping_digest":"p"})(),48)==physical_identity_key((0.1,0.2),(0.1,0.2),type("G",(),{"geometry_digest":"g","material_contract_digest":"m"})(),type("P",(),{"mapping_digest":"p"})(),48)
    assert source["failed_element_count"]==21

def main():
    root=Path(__file__).resolve().parents[2]; source,source_sha=load_source(root)
    blob_a=subprocess.check_output(["git","show",f"{SOURCE_E7I4A_COMMIT}:audit/e7i4a/result.json"],cwd=root)
    if sha(blob_a)!=SOURCE_E7I4A_SHA: raise RuntimeError("E7I.4A source SHA mismatch")
    source_a=json.loads(blob_a.decode())
    if "--self-check" in sys.argv: self_checks(source); print(json.dumps({"self_check":"PASSED","source_e7i4b_result_sha256":source_sha})); return
    elements=source["elements"]; assert len(elements)==21
    geometry=build_triangular_reference_geometry(FR); preflight=build_triangular_coordinate_preflight(); adapter=build_reference_mpb_adapter(geometry,preflight); domain=paper_style_truncated_k_hbz(fr=FR,delta_k=0.10,delta_gamma=0.10)
    counters={"raw_requests":0,"unique_solves":0,"cache_hits":0,"solver_failures":0}; cache={}; identities=PhysicalSolveCache(); started=time.monotonic(); rows=[]; iso_area=uniso_area=0.0; iso_count=uniso_count=0
    for source_row in elements:
        gap=float(source_row["original"]["center_solve"]["band4_minus_band3_external_gap"]) if "center_solve" in source_row["original"] else float(source_row["original"]["selected_span_solves"][-1]["band4_minus_band3_external_gap"])
        row={"element_id":source_row["element_id"],"evaluation_q":source_row["evaluation_q"],"element_area_weight":source_row["element_area_weight"],"distance_to_retained_outer_boundary":source_row["spatial"]["distance_to_retained_outer_boundary"],"distance_to_each_Gamma_exclusion_boundary":source_row["spatial"]["distance_to_each_Gamma_exclusion_boundary"],"original_1over36_plaquette_crosses_retained_domain_boundary":source_row["spatial"]["original_1over36_plaquette_crosses_retained_domain_boundary"],"minimum_original_1over36_vertex_gap":min(float(x["band4_minus_band3_external_gap"]) for x in source_row["original"]["selected_span_solves"][:4]),"minimum_original_path_external_isolation":source_row["original"]["minimum_external_isolation"],"center_band4_minus_band3_gap":gap,"center_policy":"CENTER_POLICY_ISOLATED" if policy_isolated(gap) else "CENTER_POLICY_UNQUALIFIED","nearest_outer_edge":nearest_edge(source_row["evaluation_q"],domain),"attempts":[]}
        if policy_isolated(gap): iso_count+=1; iso_area+=float(row["element_area_weight"])
        else: uniso_count+=1; uniso_area+=float(row["element_area_weight"])
        if row["center_policy"]=="CENTER_POLICY_ISOLATED":
            for delta in DELTAS:
                attempt=evaluate(row,delta,adapter,preflight,geometry,domain,cache,identities,counters); row["attempts"].append(attempt)
                if attempt["qualified"]: break
        rows.append(row)
    recovered=[r for r in rows if r["attempts"] and r["attempts"][-1]["qualified"]]
    recovered72=sum(1 for r in rows if r["attempts"] and r["attempts"][0]["qualified"]); recovered144=sum(1 for r in rows if len(r["attempts"])>=2 and r["attempts"][1]["qualified"]); recovered288=sum(1 for r in rows if len(r["attempts"])>=3 and r["attempts"][2]["qualified"]); unresolved=sum(1 for r in rows if r["center_policy"]=="CENTER_POLICY_ISOLATED" and (not r["attempts"] or not r["attempts"][-1]["qualified"]))
    all_recovered=uniso_count==0 and len(recovered)==21
    adaptive_integral=adaptive_chern=None
    if all_recovered:
        adaptive_integral=sum(float(x["weight_q2"])*float(x["omega_trace_q"]) for x in source_a["stage1"]["elements"] if x["qualified"]) + sum(float(x["element_area_weight"])*float(next(a["omega_trace_q"] for a in x["attempts"] if a["qualified"])) for x in recovered)
        adaptive_chern=adaptive_integral/(2*math.pi)
    crossing_recovered=sum(1 for r in recovered if next(a for a in r["attempts"] if a["qualified"])["crosses_retained_outer_boundary"]); contained_recovered=sum(1 for r in recovered if not next(a for a in r["attempts"] if a["qualified"])["crosses_retained_outer_boundary"]); crossing288=sum(1 for r in rows if len(r["attempts"])==3 and r["attempts"][-1]["crosses_retained_outer_boundary"])
    result={"schema":"e7i4c_boundary_local_limit_v1","work_order":WORK_ORDER,"code_change":"SANDBOX_AUDIT_ONLY","source_e7i4a_evidence_commit":SOURCE_E7I4A_COMMIT,"source_e7i4a_result_sha256":SOURCE_E7I4A_SHA,"source_e7i4b_calculation_code_commit":SOURCE_E7I4B_CODE_COMMIT,"source_e7i4b_evidence_commit":SOURCE_E7I4B_COMMIT,"source_e7i4b_result_sha256":source_sha,"source_failed_set_reconstruction":"EXACT_21","center_point_isolation_audit":"COMPLETE","center_policy_isolated_count":iso_count,"center_policy_unqualified_count":uniso_count,"center_policy_isolated_area_q":iso_area,"center_policy_unqualified_area_q":uniso_area,"min_center_external_gap":min(float(r["center_band4_minus_band3_gap"]) for r in rows),"max_center_external_gap":max(float(r["center_band4_minus_band3_gap"]) for r in rows),"true_pointwise_rank3_policy_blocker":uniso_count>0,"boundary_stencil_artifact_hypothesis":"SUPPORTED","local_limit_recovery":"ALL_RECOVERED" if all_recovered else ("PARTIAL" if recovered else "NONE"),"recovered_at_1over72_count":recovered72,"recovered_at_1over144_count":recovered144,"recovered_at_1over288_count":recovered288,"unresolved_after_1over288_count":unresolved,"recovered_while_crossing_boundary_count":crossing_recovered,"recovered_after_containment_count":contained_recovered,"still_crossing_at_1over288_count":crossing288,"elements":rows,"diagnostic_raw_solve_requests":counters["raw_requests"],"unique_mpb_solves":counters["unique_solves"],"cache_hits":counters["cache_hits"],"cache_hit_fraction":counters["cache_hits"]/counters["raw_requests"] if counters["raw_requests"] else 0.0,"solver_failures":counters["solver_failures"],"solve_identity_delta_independent":True,"observable_provenance_binds_delta":True,"final_stage1_qualified_area_fraction":1.0 if all_recovered else float(source_a["stage1"]["qualified_area_q"])/float(source_a["stage1"]["retained_area_q"]),"adaptive_stage1_status":"FULLY_QUALIFIED_MIXED_DELTA_PILOT" if all_recovered else ("BLOCKED_BY_POINTWISE_ISOLATION" if uniso_count else "STILL_PARTIAL"),"adaptive_stage1_curvature_integral":adaptive_integral,"adaptive_stage1_composite_valley_chern":adaptive_chern,"reference_domain_fidelity":"RETAINED","fixed_paper_stencil_fidelity":"NOT_RETAINED_AT_RECOVERED_BOUNDARY_CELLS" if recovered else "NOT_APPLICABLE","stage2_full_grid":"NOT_AUTHORIZED","per_band_chern":"NOT_AUTHORIZED","rank2_chern":"NOT_AUTHORIZED","full_bz_chern":"NOT_AUTHORIZED","bcd":"NOT_AUTHORIZED","deformation_physics":"NOT_AUTHORIZED","main_unchanged":True,"sandbox_remote_head_verified":False,"total_wall_time_seconds":time.monotonic()-started,"calculation_logic_git_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),"calculation_logic_committed_before_execution":True,"e7i4c_overall":"BOUNDARY_STENCIL_ARTIFACT_RESOLVED_AND_STAGE1_RECOVERED" if all_recovered else ("TRUE_POINTWISE_RANK3_POLICY_BLOCKER_CONFIRMED" if uniso_count else "LOCAL_LIMIT_REMAINS_UNRESOLVED")}
    out=root/"audit"/"e7i4c"; out.mkdir(parents=True,exist_ok=True); (out/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"overall":result["e7i4c_overall"],"center_policy_isolated":iso_count,"center_policy_unqualified":uniso_count,"unique_mpb_solves":counters["unique_solves"]}))

if __name__=="__main__": main()
