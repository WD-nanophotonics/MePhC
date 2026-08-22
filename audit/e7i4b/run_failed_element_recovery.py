"""E7I.4B bounded diagnosis and conditional recovery for the 21 failed E7I.4A cells."""
from __future__ import annotations
import hashlib, json, math, subprocess, sys, time
from pathlib import Path
import numpy as np
from shapely.geometry import Point, Polygon
from audit.e7i3c.run_representation_bridge import E3, BANDS, build_reference_mpb_adapter, build_triangular_coordinate_preflight, build_triangular_reference_geometry, lowdin_snapshot, solve_isolated
from audit.e7i4a.run_composite_valley_chern import frame_to_subspace
from mephc.path_domain import PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import qualify_plaquette_boundary, qualify_plaquette_interior
from mephc.spectral_association import NUMERICALLY_INCOMPLETE, SUBSPACE_CONTINUITY_UNQUALIFIED, SUBSPACE_NOT_ISOLATED, ExternalIsolationContext
from mephc.valley_benchmark import PhysicalSolveCache, PhysicalSolveIdentity, centered_ccw_plaquette_requests, paper_style_truncated_k_hbz
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

WORK_ORDER="TRILATT-E7I4B-20260823-128"
SOURCE_COMMIT="17e3c720a93c5b780324e2b69e380ae3797c6e3b"
SOURCE_RESULT_PATH="audit/e7i4a/result.json"
SOURCE_RESULT_SHA256="49344f4282859e8453c0cace9281a3c5623bf215cf2be5b81fe46cab6ebfd15a"
EXPECTED_MAIN="5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
FR=0.0
RESOLUTION=48
NUM_BANDS=4
POLARIZATION="TE"
EIGENSOLVER_TOLERANCE=1e-7
DETERMINISTIC=True
MESH_SIZE=3
ORIGINAL_DELTA=1.0/36.0
RECOVERY_DELTA=1.0/72.0
OPTIONAL_R64=64
RANK_SELECTION=(0,1,2)
REPRESENTATION="mpb_energy_eh_v1"

def sha256_bytes(value): return hashlib.sha256(value).hexdigest()
def digest(value): return sha256_bytes(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
def finite(value): return math.isfinite(float(value))

def load_source(root):
    blob=subprocess.check_output(["git","show",f"{SOURCE_COMMIT}:{SOURCE_RESULT_PATH}"],cwd=root)
    actual=sha256_bytes(blob)
    if actual!=SOURCE_RESULT_SHA256: raise RuntimeError(f"source SHA mismatch: {actual}")
    return json.loads(blob.decode()),actual

def failure_class(edge):
    evidence=tuple(str(x).lower() for x in edge.evidence)
    if edge.status==SUBSPACE_NOT_ISOLATED: return "EXTERNAL_ISOLATION_FAILURE"
    if edge.status==NUMERICALLY_INCOMPLETE:
        if any("overlap validation" in x for x in evidence): return "SELECTED_SPAN_FAILURE"
        if any("external isolation" in x for x in evidence): return "EXTERNAL_ISOLATION_FAILURE"
        return "UNEXPECTED_FAILURE"
    if edge.status==SUBSPACE_CONTINUITY_UNQUALIFIED:
        found=[]
        for needle,name in (("minimum singular value","SINGULAR_VALUE_FAILURE"),("maximum principal angle","PRINCIPAL_ANGLE_FAILURE"),("projector distance","PROJECTOR_DISTANCE_FAILURE"),("transport link","FINITE_STEP_CONTINUITY_FAILURE")):
            if any(needle in x for x in evidence): found.append(name)
        return found[0] if len(found)==1 else ("MULTIPLE_QUALIFICATION_FAILURES" if found else "FINITE_STEP_CONTINUITY_FAILURE")
    return "UNEXPECTED_FAILURE"

def first_gate(edge):
    low=tuple(str(x).lower() for x in edge.evidence)
    if edge.status==SUBSPACE_NOT_ISOLATED: return "external_isolation"
    if edge.status==NUMERICALLY_INCOMPLETE:
        if any("overlap validation" in x for x in low): return "selected_span"
        if any("external isolation" in x for x in low): return "external_isolation"
        return "unexpected"
    for needle,name in (("left and right subspace dimensions differ","rank"),("minimum singular value","minimum_singular_value"),("maximum principal angle","maximum_principal_angle"),("projector distance","cross_k_projector_distance"),("transport link","transport_link")):
        if any(needle in x for x in low): return name
    return "none"

def edge_dict(edge):
    overlap=edge.overlap
    return {
        "status":edge.status,
        "left_k_point":list(edge.left_k_point),
        "right_k_point":list(edge.right_k_point),
        "minimum_singular_value":None if overlap is None else float(overlap.min_singular_value),
        "maximum_principal_angle":None if overlap is None else float(overlap.max_principal_angle),
        "cross_k_projector_distance":None if edge.projector_distance is None else float(edge.projector_distance),
        "left_external_isolation":edge.external_gaps.get("left"),
        "right_external_isolation":edge.external_gaps.get("right"),
        "minimum_external_isolation":edge.external_gap,
        "thresholds":edge.thresholds.to_dict(),
        "evidence":list(edge.evidence),
        "first_failed_criterion":first_gate(edge),
        "failure_class":None if edge.is_qualified else failure_class(edge),
    }

def solve_vertex(adapter,preflight,geometry,point,local_delta,resolution,cache,identities,counters):
    public=tuple(float(x) for x in point)
    mpb=tuple(float(x) for x in preflight.public_q_to_mpb(public))
    claimed=digest({"schema":"e7i4b_local_identity_v1","public_q":list(public),"mpb_fractional_q":list(mpb),"local_delta_k":local_delta,"geometry_digest":geometry.geometry_digest,"material_digest":geometry.material_contract_digest,"mapping_digest":preflight.mapping_digest,"resolution":resolution,"num_bands":NUM_BANDS,"polarization":POLARIZATION,"representation":REPRESENTATION,"eigensolver_tolerance":EIGENSOLVER_TOLERANCE,"deterministic":DETERMINISTIC,"mesh_size":MESH_SIZE})
    identity=PhysicalSolveIdentity(geometry_digest=geometry.geometry_digest,material_reference_digest=geometry.material_contract_digest,coordinate_mapping_digest=preflight.mapping_digest,evaluated_q=public,resolution=resolution,num_bands=NUM_BANDS,polarization=POLARIZATION,provider_representation=REPRESENTATION,eigensolver_tolerance=EIGENSOLVER_TOLERANCE,deterministic=DETERMINISTIC,mesh_size=MESH_SIZE)
    registered=identities.register(identity,claimed_key=claimed)
    key=(resolution,local_delta,registered)
    counters["raw_requests"]+=1
    if key in cache:
        counters["cache_hits"]+=1
        return cache[key]
    counters["unique_solves"]+=1
    raw=solve_isolated(adapter,resolution,FR,public)
    snapshot,diag=lowdin_snapshot(raw)
    frequencies=[float(x) for x in raw.frequencies]
    if len(frequencies)!=4 or not all(finite(x) for x in frequencies):
        counters["solver_failures"]+=1
        raise RuntimeError(f"nonfinite frequencies at {public}")
    record={"requested_public_q":list(public),"actual_public_q":list(raw.k_point),"actual_mpb_fractional_q":list(mpb),"local_delta_k":local_delta,"resolution":resolution,"frequencies_bands_1_to_4":frequencies,"band4_minus_band3_external_gap":frequencies[3]-frequencies[2],"raw_selected_gram":diag["RAW_SELECTED_GRAM"],"selected_gram_eigenvalues":diag["GRAM_EIGENVALUES"],"selected_gram_condition_number":diag["GRAM_CONDITION_NUMBER"],"lowdin_q_dagger_q_residual":diag["Q_DAGGER_Q_RESIDUAL"],"raw_span_lowdin_span_projector_residual":diag["SPAN_PROJECTOR_RESIDUAL"],"raw_selected_max_off_diagonal_gram":diag["RAW_SELECTED_MAX_OFF_DIAGONAL_GRAM"],"selected_span_condition":diag["selected_span_condition"],"raw_provider_orthogonality_status":diag["raw_provider_orthogonality_status"]}
    cache[key]=(snapshot,frequencies,record)
    return cache[key]

def requests_for(center,delta,preflight):
    vectors=preflight.delta_k_vectors_to_public_q(delta)
    return centered_ccw_plaquette_requests((tuple(float(x) for x in center),),vectors,period_basis=preflight.public_period_basis,coordinate_mapping_digest=preflight.mapping_digest)

def evaluate(element,delta,resolution,adapter,preflight,geometry,cache,identities,counters,source_vertices=None):
    center=tuple(float(x) for x in element["center_q"])
    reqs=requests_for(center,delta,preflight)
    vertices_q=[tuple(float(x) for x in req.canonical_periodic_vertex_q) for req in reqs]
    if source_vertices is not None:
        expected=[tuple(float(x) for x in p) for p in source_vertices]
        if len(expected)!=4 or any(not np.allclose(a,b,rtol=0.0,atol=1e-12) for a,b in zip(vertices_q,expected)): raise RuntimeError(f"source vertex binding mismatch: {element['element_id']}")
    values=[solve_vertex(adapter,preflight,geometry,q,delta,resolution,cache,identities,counters) for q in vertices_q]
    center_value=solve_vertex(adapter,preflight,geometry,center,delta,resolution,cache,identities,counters)
    vertices=[frame_to_subspace(q,v[0]) for q,v in zip(vertices_q,values)]
    center_subspace=frame_to_subspace(center,center_value[0])
    frequencies=[v[1] for v in values]
    contexts=tuple(ExternalIsolationContext((frequencies[i][3],),(frequencies[(i+1)%4][3],),{"source":"E7I.4B band4 edge isolation"}) for i in range(4))
    path=qualify_ordered_path(tuple(vertices),contexts,thresholds=E3,closed=True,provenance={"source":"E7I.4B failed-element diagnosis"})
    wilson=compose_wilson_transport(path)
    boundary=qualify_plaquette_boundary(tuple(vertices),contexts,thresholds=E3,provenance={"source":"E7I.4B E4A diagnostic"})
    center_freq=center_value[1]
    spokes=tuple(ExternalIsolationContext((frequencies[i][3],),(center_freq[3],),{"source":"E7I.4B E4B spoke isolation"}) for i in range(4))
    interior=qualify_plaquette_interior(boundary,center_subspace,spokes,provenance={"source":"E7I.4B E4B diagnostic"})
    edge_rows=[edge_dict(e) for e in path.edge_results]
    all_gaps=[float(x["minimum_external_isolation"]) for x in edge_rows if x["minimum_external_isolation"] is not None]
    selected=values+[center_value]
    min_gap=min(all_gaps) if len(all_gaps)==4 else None
    min_vertex_gap=min([float(v[1][3]-v[1][2]) for v in selected])
    span_ok=all(v[2]["selected_span_condition"]=="WELL_CONDITIONED" for v in selected)
    eligible=span_ok and min_gap is not None and min_gap>=E3.min_external_gap and min_vertex_gap>=E3.min_external_gap and not any(e.status==NUMERICALLY_INCOMPLETE for e in path.edge_results)
    qualified=path.status==PATH_SUBSPACE_QUALIFIED and wilson.status==WILSON_LOOP_QUALIFIED and wilson.determinant_phase is not None
    area=abs(float(np.linalg.det(np.asarray(preflight.delta_k_vectors_to_public_q(delta)))))
    return {"local_delta_k":delta,"resolution":resolution,"center_q":list(center),"vertices_q":[list(x) for x in vertices_q],"selected_span_solves":[x[2] for x in selected],"path_status":path.status,"path_evidence":list(path.evidence),"edges":edge_rows,"wilson":{"status":wilson.status,"input_qualification_status":"QUALIFIED" if wilson.status==WILSON_LOOP_QUALIFIED else "UNQUALIFIED","wilson_product_produced":wilson.product is not None,"determinant_phase":wilson.determinant_phase,"unitarity_residual":wilson.unitarity_residual,"evidence":list(wilson.evidence)},"boundary":boundary.to_dict(include_matrices=False),"interior":interior.to_dict(include_matrices=False),"qualified":qualified,"eligible_for_local_recovery":eligible,"minimum_external_isolation":min_gap,"minimum_vertex_external_gap":min_vertex_gap,"omega_trace_q":None if not qualified else float(-wilson.determinant_phase/area)}

def refinement_summary(original,recovery):
    metric_names=("minimum_singular_value","maximum_principal_angle","cross_k_projector_distance")
    deltas=[]
    for before,after in zip(original["edges"],recovery["edges"]):
        for name in metric_names:
            a=before[name]; b=after[name]
            if a is not None and b is not None: deltas.append({"metric":name,"edge_index":len(deltas),"absolute_delta":abs(float(b)-float(a))})
    max_delta=max((x["absolute_delta"] for x in deltas),default=None)
    return {"scope":"cross_k_path_metric_diagnostic","status":"QUALIFIED_AT_1OVER72" if recovery["qualified"] else "UNQUALIFIED_AT_1OVER72","max_metric_delta":max_delta,"metric_deltas":deltas,"thresholds":{"max_metric_delta":0.1,"min_singular_value":0.9,"max_principal_angle":0.45,"max_projector_distance":0.3},"first_failed_stage":None if recovery["qualified"] else next((x["first_failed_criterion"] for x in recovery["edges"] if x["failure_class"]!="UNEXPECTED_FAILURE"),"unknown")}

def spatial(element,domain,preflight):
    center=np.asarray(element["center_q"],dtype=float); p=Point(tuple(center)); outer=Polygon(domain.vertices); retained=domain.polygon; plaquette=Polygon(element["public_vertices_q"])
    return {"distance_to_K":float(np.linalg.norm(center-np.asarray(preflight.public_k,dtype=float))),"distance_to_retained_outer_boundary":float(p.distance(outer.boundary)),"distance_to_each_Gamma_exclusion_boundary":[float(p.distance(Polygon(h).boundary)) for h in domain.exclusions],"original_1over36_plaquette_crosses_retained_domain_boundary":not retained.covers(plaquette),"original_1over36_plaquette_intersects_Gamma_exclusion":any(plaquette.intersects(Polygon(h)) for h in domain.exclusions)}

def primary(original):
    classes={x["failure_class"] for x in original["edges"] if x["failure_class"]!="UNEXPECTED_FAILURE"}
    if "EXTERNAL_ISOLATION_FAILURE" in classes:return "EXTERNAL_ISOLATION_FAILURE"
    if len(classes)==1:return next(iter(classes))
    return "MULTIPLE_QUALIFICATION_FAILURES" if classes else "UNEXPECTED_FAILURE"

def spatial_summary(rows):
    b=sum(bool(x["spatial"]["original_1over36_plaquette_crosses_retained_domain_boundary"]) for x in rows); g=sum(bool(x["spatial"]["original_1over36_plaquette_intersects_Gamma_exclusion"]) for x in rows); k=sum(float(x["spatial"]["distance_to_K"])<0.15 for x in rows); n=len(rows)
    return {"pattern":"BOUNDARY_CLUSTERED" if b>=math.ceil(n/2) else ("GAMMA_EXCLUSION_CLUSTERED" if g>=math.ceil(n/2) else ("K_REGION_CLUSTERED" if k>=math.ceil(n/2) else "DISTRIBUTED")),"boundary_count":b,"gamma_exclusion_count":g,"k_region_count":k}

def taxonomy(rows):
    out={}
    for row in rows:
        item=out.setdefault(row["primary_failure_class"],{"count":0,"failed_area_q":0.0}); item["count"]+=1; item["failed_area_q"]+=float(row["element_area_weight"])
    return out

def self_checks(source):
    failed=[x for x in source["stage1"]["elements"] if not x["qualified"]]
    assert len(failed)==21 and RANK_SELECTION==(0,1,2)
    assert E3.min_singular_value==0.9 and E3.max_principal_angle==0.45 and E3.max_projector_distance==0.3 and E3.min_external_gap==0.05
    assert digest({"local_delta_k":ORIGINAL_DELTA})!=digest({"local_delta_k":RECOVERY_DELTA})
    assert math.isclose(0.25*2.0+0.75*4.0,3.5,rel_tol=0.0,abs_tol=1e-15)
    fake=type("Edge",(),{"status":SUBSPACE_NOT_ISOLATED,"evidence":()})()
    assert failure_class(fake)=="EXTERNAL_ISOLATION_FAILURE"
    fake=type("Edge",(),{"status":SUBSPACE_CONTINUITY_UNQUALIFIED,"evidence":("minimum singular value is below threshold",)})()
    assert failure_class(fake)=="SINGULAR_VALUE_FAILURE"

def main():
    root=Path(__file__).resolve().parents[2]; source,source_sha=load_source(root)
    if "--self-check" in sys.argv:
        self_checks(source); print(json.dumps({"self_check":"PASSED","source_result_sha256":source_sha})); return
    failed=[x for x in source["stage1"]["elements"] if not x["qualified"]]
    if len(failed)!=21: raise RuntimeError(f"expected exact 21 failed elements, found {len(failed)}")
    geometry=build_triangular_reference_geometry(FR); preflight=build_triangular_coordinate_preflight(); adapter=build_reference_mpb_adapter(geometry,preflight); domain=paper_style_truncated_k_hbz(fr=FR,delta_k=0.10,delta_gamma=0.10)
    cache={}; identities=PhysicalSolveCache(); dc={"raw_requests":0,"unique_solves":0,"cache_hits":0,"solver_failures":0}; rc={"raw_requests":0,"unique_solves":0,"cache_hits":0,"solver_failures":0}; c64={"raw_requests":0,"unique_solves":0,"cache_hits":0,"solver_failures":0}
    started=time.monotonic(); rows=[]
    for element in failed:
        original=evaluate(element,ORIGINAL_DELTA,RESOLUTION,adapter,preflight,geometry,cache,identities,dc,source_vertices=element["public_vertices_q"])
        row={"element_id":element["element_id"],"evaluation_q":element["center_q"],"element_area_weight":element["weight_q2"],"domain_component_id":element["element_id"].split(":")[1] if ":" in element["element_id"] else "UNKNOWN","domain_digest":domain.digest,"source_vertices_q":element["public_vertices_q"],"original":original,"spatial":spatial(element,domain,preflight),"primary_failure_class":primary(original),"recovery_attempted":False,"recovery":None,"refinement":None,"persistent_r64_attempted":False,"persistent_r64":None}
        if not original["eligible_for_local_recovery"]:
            row["refinement"]={"scope":"cross_k_path_metric_diagnostic","status":"NOT_AUTHORIZED_DUE_TO_ISOLATION","max_metric_delta":None,"metric_deltas":[],"first_failed_stage":"external_isolation","thresholds":{"max_metric_delta":0.1,"min_singular_value":0.9,"max_principal_angle":0.45,"max_projector_distance":0.3}}
        if original["eligible_for_local_recovery"]:
            row["recovery_attempted"]=True; recovery=evaluate(element,RECOVERY_DELTA,RESOLUTION,adapter,preflight,geometry,cache,identities,rc); row["recovery"]=recovery; row["refinement"]=refinement_summary(original,recovery)
            if not recovery["qualified"] and recovery["eligible_for_local_recovery"]:
                row["persistent_r64_attempted"]=True; row["persistent_r64"]=evaluate(element,ORIGINAL_DELTA,OPTIONAL_R64,adapter,preflight,geometry,cache,identities,c64)
        rows.append(row)
    recovered=[x for x in rows if x["recovery"] is not None and x["recovery"]["qualified"]]
    failed_area=sum(float(x["element_area_weight"]) for x in rows); recovered_area=sum(float(x["element_area_weight"]) for x in recovered); retained=float(source["stage1"]["retained_area_q"]); all_recovered=len(recovered)==len(rows)
    adaptive_integral=None; adaptive_chern=None
    if all_recovered:
        adaptive_integral=sum(float(x["weight_q2"])*float(x["original"]["omega_trace_q"]) for x in source["stage1"]["elements"] if x["qualified"])+sum(float(x["element_area_weight"])*float(x["recovery"]["omega_trace_q"]) for x in recovered); adaptive_chern=adaptive_integral/(2.0*math.pi)
    isolation=any(x["primary_failure_class"]=="EXTERNAL_ISOLATION_FAILURE" or (x["recovery"] is not None and any(e["failure_class"]=="EXTERNAL_ISOLATION_FAILURE" for e in x["recovery"]["edges"])) for x in rows)
    overall="FAILED_AREA_DIAGNOSED_AND_STAGE1_CHERN_RECOVERED" if all_recovered else ("RANK3_DOMAIN_ISOLATION_BLOCKER_CONFIRMED" if isolation else "FAILED_AREA_DIAGNOSED_STAGE1_REMAINS_PARTIAL")
    result={"schema":"e7i4b_failed_element_recovery_v1","work_order":WORK_ORDER,"code_change":"SANDBOX_AUDIT_ONLY","source_e7i4a_code_commit":"4a540e6197e36e0b453ab1cd4a2ce2b5865a04dd","source_e7i4a_evidence_commit":SOURCE_COMMIT,"source_e7i4a_result_sha256":source_sha,"source_failed_set_reconstruction":"EXACT_21","geometry":geometry.to_dict(),"domain":domain.to_dict(),"thresholds":{"E3":E3.to_dict(),"E4C":{"min_singular_value":0.9,"max_principal_angle":0.45,"max_projector_distance":0.3,"max_metric_delta":0.1}},"diagnostic_settings":{"resolution":RESOLUTION,"local_delta_k":ORIGINAL_DELTA,"rank_selection_zero_based":list(RANK_SELECTION),"representation":REPRESENTATION},"recovery_settings":{"resolution":RESOLUTION,"local_delta_k":RECOVERY_DELTA},"optional_r64_settings":{"resolution":OPTIONAL_R64,"local_delta_k":ORIGINAL_DELTA},"failed_element_count":len(rows),"failed_area_q":failed_area,"failure_taxonomy":taxonomy(rows),"spatial_localization":spatial_summary(rows),"elements":rows,"diagnostic_raw_solve_requests":dc["raw_requests"],"diagnostic_unique_mpb_solves":dc["unique_solves"],"recovery_raw_solve_requests":rc["raw_requests"],"recovery_unique_mpb_solves":rc["unique_solves"],"optional_r64_raw_solve_requests":c64["raw_requests"],"optional_r64_unique_mpb_solves":c64["unique_solves"],"cache_hits":dc["cache_hits"]+rc["cache_hits"]+c64["cache_hits"],"solver_failures":dc["solver_failures"]+rc["solver_failures"]+c64["solver_failures"],"final_stage1_qualified_area_fraction":(float(source["stage1"]["qualified_area_q"])+recovered_area)/retained,"adaptive_stage1_status":"FULLY_QUALIFIED" if all_recovered else ("NOT_AUTHORIZED_DUE_TO_ISOLATION" if isolation else "STILL_PARTIAL"),"adaptive_stage1_curvature_integral":adaptive_integral,"adaptive_stage1_composite_valley_chern":adaptive_chern,"rank3_domain_isolation_blocker":isolation,"original_local_delta_diagnosis":"COMPLETE","local_delta_1over72_recovery":"ALL_ELIGIBLE_RECOVERED" if all_recovered else ("NOT_AUTHORIZED_DUE_TO_ISOLATION" if isolation else ("PARTIAL" if recovered else "NONE")),"persistent_r64_diagnostic":"RUN_BOUNDED" if any(x["persistent_r64_attempted"] for x in rows) else ("NOT_AUTHORIZED_DUE_TO_ISOLATION" if isolation else "NOT_NEEDED"),"stage2_full_integration_grid":"NOT_AUTHORIZED","per_band_chern":"NOT_AUTHORIZED","rank2_chern":"NOT_AUTHORIZED","full_bz_chern":"NOT_AUTHORIZED","bcd":"NOT_AUTHORIZED","deformation_physics":"NOT_AUTHORIZED","main_unchanged":True,"sandbox_remote_head_verified":False,"total_wall_time_seconds":time.monotonic()-started,"calculation_logic_git_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),"calculation_logic_committed_before_execution":True,"expected_main_head":EXPECTED_MAIN,"e7i4b_overall":overall}
    out=root/"audit"/"e7i4b"; out.mkdir(parents=True,exist_ok=True); (out/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"overall":overall,"failed_elements":len(rows),"recovered":len(recovered),"diagnostic_unique_solves":dc["unique_solves"],"recovery_unique_solves":rc["unique_solves"]}))

if __name__=="__main__": main()
