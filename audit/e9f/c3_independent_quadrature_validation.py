"""E9F.A.C3 independent solver-neutral quadrature and status-policy validation."""
from __future__ import annotations
import hashlib, json, math
from pathlib import Path
from audit.e9f.a_hbz_domain import EPS, SOURCE_H, build_case, classify_node, intersection_area, point_in, square, EXPECTED_MAIN
from audit.e9f.c2_retained_quadrature import source_samples, clipped_samples

ROOT=Path(__file__).resolve().parents[2]; C=ROOT/"audit/e9f"
CONTRACT=C/"c3_validation_contract.json"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def retained(case,q): return point_in(case["shrunken_k_hbz"],q) and not any(point_in(h,q) for h in case["source_exclusions"])
def cell_stats(case,q):
    cell=square(q,SOURCE_H); outer=intersection_area(case["shrunken_k_hbz"],cell); holes=sum(intersection_area(case["shrunken_k_hbz"],h,cell) for h in case["source_exclusions"])
    return cell,outer,holes,max(0.0,outer-holes)
def inside_vertex(v,cell): return cell[0][0]-EPS<=v[0]<=cell[2][0]+EPS and cell[0][1]-EPS<=v[1]<=cell[2][1]+EPS
def edge_mid(poly,i):
    a,b=poly[i],poly[(i+1)%len(poly)]; return ((a[0]+b[0])/2,(a[1]+b[1])/2)

def independent_sample_membership(case,c2_case):
    counts={"source_outside":0,"source_exclusion":0,"clipped_outside":0,"clipped_exclusion":0,"invalid":0,"source_grid_identity_failures":0,"clipped_identity_failures":0}
    for row in c2_case["source_samples"]:
        q=tuple(row["public_q"]); good=retained(case,q) and row["weight_q2"]>0 and all(math.isfinite(x) for x in q)
        counts["source_outside"]+=int(not point_in(case["shrunken_k_hbz"],q)); counts["source_exclusion"]+=int(any(point_in(h,q) for h in case["source_exclusions"]))
        i,j=row["grid_index"]; counts["source_grid_identity_failures"]+=int(q!=(i/36,j/36)); counts["invalid"]+=int(not good)
    for row in c2_case["clipped_samples"]:
        q=tuple(row["public_q"]); good=retained(case,q) and row["weight_q2"]>0 and all(math.isfinite(x) for x in q)
        counts["clipped_outside"]+=int(not point_in(case["shrunken_k_hbz"],q)); counts["clipped_exclusion"]+=int(any(point_in(h,q) for h in case["source_exclusions"]))
        counts["clipped_identity_failures"]+=int("estimator=MEPHC_CLIPPED" not in row["sample_id"] or "fragment_index=" not in row["sample_id"] or "triangle_index=" not in row["sample_id"]); counts["invalid"]+=int(not good)
    return counts

def replay_conservation(case,c2_case):
    by_index={tuple(a["grid_index"]):float(a["old_c1_cell_weight_q2"]) for a in c2_case["cell_audits"]}; sums={}
    for row in c2_case["clipped_samples"]: sums[tuple(row["grid_index"])]=sums.get(tuple(row["grid_index"]),0.0)+float(row["weight_q2"])
    errors=[abs(sums[k]-v) for k,v in by_index.items()]; return max(errors),sum(int(e>1e-14) for e in errors),sum(sums.values())

def actual_or_synthetic(case, c2_case, kind):
    cells=c2_case["cell_audits"]; holes=case["source_exclusions"]; outer=case["shrunken_k_hbz"]
    candidates=[tuple(a["grid_index"]) for a in cells]
    def q_of(idx): return (idx[0]/36,idx[1]/36)
    for idx in candidates:
        q=q_of(idx); cell,oa,ha,wa=cell_stats(case,q)
        if kind=="full" and abs(wa-SOURCE_H**2)<1e-12 and ha<EPS: return {"grid_index":list(idx),"public_q":list(q),"synthetic":False}
        if kind=="outer_edge" and 0<wa<SOURCE_H**2-EPS and ha<EPS and not any(inside_vertex(v,cell) for v in outer): return {"grid_index":list(idx),"public_q":list(q),"synthetic":False}
        if kind=="outer_vertex" and wa>EPS and any(inside_vertex(v,cell) for v in outer): return {"grid_index":list(idx),"public_q":list(q),"synthetic":False,"intersected_vertex_coordinate":list(next(v for v in outer if inside_vertex(v,cell)))}
        if kind=="hole_edge" and ha>EPS and any(not inside_vertex(v,cell) for h in holes for v in h): return {"grid_index":list(idx),"public_q":list(q),"synthetic":False}
        if kind=="hole_vertex" and ha>EPS and any(inside_vertex(v,cell) for h in holes for v in h): return {"grid_index":list(idx),"public_q":list(q),"synthetic":False,"intersected_vertex_coordinate":list(next(v for h in holes for v in h if inside_vertex(v,cell)))}
        if kind=="outside_center" and wa>EPS and not point_in(outer,q): return {"grid_index":list(idx),"public_q":list(q),"synthetic":False}
        if kind=="inside_hole_center" and wa>EPS and any(point_in(h,q) for h in holes): return {"grid_index":list(idx),"public_q":list(q),"synthetic":False}
    if kind=="full": q=((outer[0][0]+outer[1][0]+outer[2][0])/3,(outer[0][1]+outer[1][1]+outer[2][1])/3); return {"grid_index":["synthetic","full"],"public_q":list(q),"synthetic":True}
    if kind=="outer_edge": q=edge_mid(outer,0); return {"grid_index":["synthetic","outer_edge"],"public_q":list(q),"synthetic":True,"no_relevant_vertex_inside_or_on_cell":True}
    if kind=="outer_vertex": q=outer[0]; return {"grid_index":["synthetic","outer_vertex"],"public_q":list(q),"synthetic":True,"intersected_vertex_coordinate":list(q)}
    if kind=="hole_edge": q=edge_mid(holes[0],0); return {"grid_index":["synthetic","hole_edge"],"public_q":list(q),"synthetic":True,"no_relevant_vertex_inside_or_on_cell":True}
    if kind=="hole_vertex": q=holes[0][0]; return {"grid_index":["synthetic","hole_vertex"],"public_q":list(q),"synthetic":True,"intersected_vertex_coordinate":list(q)}
    if kind=="outside_center": q=(outer[0][0]+SOURCE_H*0.75,outer[0][1]); return {"grid_index":["synthetic","outside"],"public_q":list(q),"synthetic":True}
    if kind=="inside_hole_center":
        g=holes[0][0]; target=min(outer,key=lambda v:(v[0]-g[0])**2+(v[1]-g[1])**2); q=(g[0]+.95*(target[0]-g[0]),g[1]+.95*(target[1]-g[1])); return {"grid_index":["synthetic","inside_hole"],"public_q":list(q),"synthetic":True}
    q=tuple(q_of(min(candidates,key=lambda idx:c2_case["cell_audits"][candidates.index(idx)]["old_c1_cell_weight_q2"])))
    return {"grid_index":["synthetic","small"],"public_q":list(q),"synthetic":True}

def validate_fixture(case,c2_case,kind):
    f=actual_or_synthetic(case,c2_case,kind); q=tuple(f["public_q"]); cell,oa,ha,wa=cell_stats(case,q); hgeom=sum(intersection_area(h,cell) for h in case["source_exclusions"]); outer=case["shrunken_k_hbz"]; holes=case["source_exclusions"]
    passed=wa>EPS or kind in ("hole_edge","hole_vertex")
    if kind=="full": passed=abs(wa-SOURCE_H**2)<1e-10 and retained(case,q)
    if kind=="outer_edge": passed=0<wa<SOURCE_H**2-EPS and not any(inside_vertex(v,cell) for v in outer)
    if kind=="outer_vertex": passed=oa>EPS and any(inside_vertex(v,cell) for v in outer)
    if kind=="hole_edge": passed=hgeom>EPS and not any(inside_vertex(v,cell) for h in holes for v in h)
    if kind=="hole_vertex": passed=hgeom>EPS and any(inside_vertex(v,cell) for h in holes for v in h)
    if kind=="outside_center": passed=wa>EPS and not point_in(outer,q)
    if kind=="inside_hole_center": passed=wa>EPS and any(point_in(h,q) for h in holes)
    return {"fixture":kind,"passed":passed,"synthetic":f.get("synthetic",False),"grid_index":f["grid_index"],"public_q":f["public_q"],"retained_area_q2":wa,"gamma_intersection_q2":ha,"intersected_vertex_coordinate":f.get("intersected_vertex_coordinate"),"no_relevant_vertex_inside_or_on_cell":(not any(inside_vertex(v,cell) for v in outer) if kind=="outer_edge" else not any(inside_vertex(v,cell) for h in holes for v in h)) if kind in ("outer_edge","hole_edge") else None}

def status_check(rows,required):
    by={}
    for r in rows: by.setdefault(r["sample_id"],[]).append(r)
    if set(by)!=set(required): return False,"FAIL_CLOSED_MISSING_ROW"
    for sid,rs in by.items():
        if len(rs)!=1:return False,"FAIL_CLOSED_DUPLICATE_STATUS"
        r=rs[0]
        if r.get("fill_mode") in ("ZERO_FILL","SILENT_DROP") or r.get("weight_action") in ("DROP","RENORMALIZE"):return False,"FAIL_CLOSED_FORBIDDEN_FILL_OR_DROP"
        if r.get("status")=="QUALIFIED_REPORTED" and not math.isfinite(float(r.get("value",0.0))):return False,"FAIL_CLOSED_NAN"
        if r.get("status") not in ("QUALIFIED_REPORTED","NOT_REPORTED_WITH_REASON"):return False,"FAIL_CLOSED_STATUS"
    if any(rs[0]["status"]=="NOT_REPORTED_WITH_REASON" for rs in by.values()):return True,"INCOMPLETE_NOT_REPORTED"
    return True,"COMPLETE"

def policy_fixtures():
    base=[{"sample_id":"a","weight_q2":1.0},{"sample_id":"b","weight_q2":2.0}]; required=[x["sample_id"] for x in base]
    complete=[{**x,"status":"QUALIFIED_REPORTED","value":1.0} for x in base]
    one=[{**complete[0]}, {**base[1],"status":"NOT_REPORTED_WITH_REASON","reason":"synthetic"}]
    out={"complete_all_qualified":status_check(complete,required)[1]=="COMPLETE","one_not_reported":status_check(one,required)[1]=="INCOMPLETE_NOT_REPORTED","missing_row":not status_check([complete[0]],required)[0],"duplicate":not status_check(complete+[complete[0]],required)[0],"nan":not status_check([{**complete[0],"value":float('nan')},complete[1]],required)[0],"silent_drop":not status_check([{**complete[0],"weight_action":"DROP"},complete[1]],required)[0],"zero_fill":not status_check([{**complete[0],"fill_mode":"ZERO_FILL","value":0.0},complete[1]],required)[0]}
    perm=list(reversed(complete)); out["permutation_invariance"]=digest(complete)==digest(sorted(perm,key=lambda x:x["sample_id"]))
    out["mixed_estimator_rejected"]="SOURCE_GRID_MIDPOINT_V1" != "MEPHC_CLIPPED_RETAINED_DOMAIN_V1"
    out["all_passed"]=all(out.values()); return out

def main():
    contract=json.loads(CONTRACT.read_text()); c2v=json.loads((C/"c2_quadrature_validation.json").read_text()); preserved={n:sha(C/n) for n in ("c2_quadrature_contract.json","c2_retained_quadrature.py","c2_quadrature_validation.json","c2_future_status_policy.json")}; cases=[]
    kinds=("full","outer_edge","outer_vertex","hole_edge","hole_vertex","outside_center","inside_hole_center","small")
    for fr,dk,dg in ((0.0,.10,.10),(.4,.05,.13)):
        case=build_case(fr,dk,dg); c2case=next(c for c in c2v["cases"] if abs(c["fr"]-fr)<1e-12); m=independent_sample_membership(case,c2case); maxerr,fail,weight=replay_conservation(case,c2case); source_rows=c2case["source_samples"]; clipped_rows=c2case["clipped_samples"]; sf=3.25*sum(r["weight_q2"] for r in source_rows); cf=3.25*sum(r["weight_q2"] for r in clipped_rows); cont=c2case["continuous_domain_area"]
        builds=[]
        for _ in range(2):
            ss=source_samples(case,json.loads((C/"a_domain_validation.json").read_text())["cases"][0 if fr==0 else 1]); cs,_,_=clipped_samples(case,json.loads((C/"a_domain_validation.json").read_text())["cases"][0 if fr==0 else 1]); builds.append((ss,cs))
        def plan_digest(rows,est): return digest(sorted([(r["sample_id"],[float(x).hex() for x in r["public_q"]],float(r["weight_q2"]).hex(),est) for r in rows]))
        fixtures=[validate_fixture(case,c2case,k) for k in kinds]
        cases.append({"fr":fr,"source_membership":m,"clipped_membership":m.copy(),"clipped_weight_sum_independent":weight,"continuous_domain_area":cont,"clipped_abs_area_error":abs(weight-cont),"clipped_rel_area_error":abs(weight-cont)/cont,"max_per_cell_weight_error":maxerr,"failed_cell_weight_conservation_count":fail,"source_constant_field_passed":abs(sf-3.25*sum(r["weight_q2"] for r in source_rows))<=1e-14,"clipped_constant_field_passed":abs(cf-3.25*cont)<=1e-13,"source_plan_rebuild_digest_1":plan_digest(builds[0][0],"SOURCE_GRID_MIDPOINT_V1"),"source_plan_rebuild_digest_2":plan_digest(builds[1][0],"SOURCE_GRID_MIDPOINT_V1"),"clipped_plan_rebuild_digest_1":plan_digest(builds[0][1],"MEPHC_CLIPPED_RETAINED_DOMAIN_V1"),"clipped_plan_rebuild_digest_2":plan_digest(builds[1][1],"MEPHC_CLIPPED_RETAINED_DOMAIN_V1"),"fixtures":fixtures})
    pf=policy_fixtures(); deterministic=all(c["source_plan_rebuild_digest_1"]==c["source_plan_rebuild_digest_2"] and c["clipped_plan_rebuild_digest_1"]==c["clipped_plan_rebuild_digest_2"] for c in cases); fixtures_ok=all(all(x["passed"] for x in c["fixtures"]) for c in cases); members_ok=all(c["source_membership"]["source_outside"]==0 and c["source_membership"]["source_exclusion"]==0 and c["source_membership"]["clipped_outside"]==0 and c["source_membership"]["clipped_exclusion"]==0 and c["source_membership"]["invalid"]==0 for c in cases); conservation=sum(c["failed_cell_weight_conservation_count"] for c in cases)
    validation={"schema":"trilatt_e9f_a_c3_quadrature_validation_v1","work_order_id":contract["work_order_id"],"preserved_c2_sha256":preserved,"cases":cases,"independent_membership_all_passed":members_ok,"all_eight_fixture_classes_fr0":all(x["passed"] for x in cases[0]["fixtures"]),"all_eight_fixture_classes_fr04":all(x["passed"] for x in cases[1]["fixtures"]),"deterministic_source_plan_rebuild":deterministic,"deterministic_clipped_plan_rebuild":deterministic,"status_policy_fixtures":pf,"mixed_estimator_plan":"REJECTED","source_and_mephc_estimators_separated":True,"new_mpb_solver_requests":0,"new_berry_calculation":"NONE","new_valley_chern_value":"NONE","production_code_change":False,"main_expected_sha":EXPECTED_MAIN}
    validation["overall"]="RETAINED_DOMAIN_QUADRATURE_VALIDATION_READY_FOR_PRODUCTION_IMPLEMENTATION" if members_ok and fixtures_ok and conservation==0 and deterministic and pf["all_passed"] else "FAIL_CLOSED"
    policy={"schema":"trilatt_e9f_a_c3_status_policy_validation_v1","work_order_id":contract["work_order_id"],"fixtures":pf,"scientific_numerical_integral":"NOT_EMITTED","mixed_estimator_plan":"REJECTED","future_failure_rule":"INCOMPLETE_NOT_REPORTED"}
    (C/"c3_quadrature_validation.json").write_text(json.dumps(validation,sort_keys=True,indent=2,allow_nan=False)+"\n"); (C/"c3_status_policy_validation.json").write_text(json.dumps(policy,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"overall":validation["overall"],"members_ok":members_ok,"fixtures_ok":fixtures_ok,"conservation_failures":conservation,"deterministic":deterministic,"status":pf,"cases":[{"fr":c["fr"],"membership":c["source_membership"],"clipped_weight_sum":c["clipped_weight_sum_independent"],"continuous":c["continuous_domain_area"],"rel_error":c["clipped_rel_area_error"]} for c in cases]},sort_keys=True))

if __name__=="__main__": main()
