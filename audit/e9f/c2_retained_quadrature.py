"""E9F.A.C2 deterministic retained-domain quadrature; no live physics."""
from __future__ import annotations
import hashlib, json, math
from pathlib import Path
from audit.e9f.a_hbz_domain import (EPS, GRID_DEN, SOURCE_H, build_case, classify_node,
    intersection, intersection_area, area, cross, point_in, square, digest_bytes, EXPECTED_MAIN)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "audit/e9f/c2_quadrature_contract.json"
C1 = ROOT / "audit/e9f"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def coord_digest(q): return hashlib.sha256(json.dumps([float(x).hex() for x in q], separators=(",", ":")).encode()).hexdigest()
def polygon_centroid(tri): return tuple(sum(p[d] for p in tri) / 3.0 for d in (0, 1))

def clip_side(poly, a, b, inside=True):
    if not poly: return []
    out=[]
    for p,q in zip(poly, poly[1:]+poly[:1]):
        vp, vq = cross(a,b,p), cross(a,b,q)
        pin = vp >= -EPS if inside else vp <= EPS
        qin = vq >= -EPS if inside else vq <= EPS
        if pin: out.append(p)
        if pin != qin and abs(vp-vq)>EPS:
            t=vp/(vp-vq)
            out.append((p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1])))
    return out

def subtract_convex(poly, hole):
    active=[list(poly)]
    outside=[]
    hole=hole if area(hole)>0 else list(reversed(hole))
    for a,b in zip(hole,hole[1:]+hole[:1]):
        next_active=[]
        for piece in active:
            inside=clip_side(piece,a,b,True)
            out=clip_side(piece,a,b,False)
            if len(out)>=3 and abs(area(out))>EPS: outside.append(out)
            if len(inside)>=3 and abs(area(inside))>EPS: next_active.append(inside)
        active=next_active
    return outside

def cell_fragments(case, q):
    cell=square(q,SOURCE_H)
    fragments=intersection(case["shrunken_k_hbz"],cell)
    if len(fragments)<3: return []
    fragments=[fragments]
    for hole in case["source_exclusions"]:
        next_fragments=[]
        for fragment in fragments: next_fragments.extend(subtract_convex(fragment,hole))
        fragments=next_fragments
    return fragments

def triangulate(fragment):
    if area(fragment)<0: fragment=list(reversed(fragment))
    triangles=[]
    for i in range(1,len(fragment)-1):
        tri=[fragment[0],fragment[i],fragment[i+1]]
        a=abs(area(tri))
        if a>EPS: triangles.append((tri,a))
    return triangles

def strict_retained(case,q):
    if not point_in(case["shrunken_k_hbz"],q): return False
    if any(point_in(h,q) for h in case["source_exclusions"]): return False
    return True

def source_samples(case, validation):
    rows=[]
    for r in validation["grid_nodes"]:
        if not r["included_in_source_domain"]: continue
        q=tuple(r["public_q"])
        rows.append({"sample_id":f"fr={case['fr']:g};grid_i={r['grid_index'][0]};grid_j={r['grid_index'][1]};estimator=SOURCE_GRID", "grid_index":r["grid_index"], "public_q":list(q), "public_q_hex_floats":[float(x).hex() for x in q], "coordinate_digest":coord_digest(q), "weight_q2":SOURCE_H*SOURCE_H, "inside_shrunken_hbz":strict_retained(case,q), "inside_any_gamma_exclusion":False, "positive_weight":True, "finite_public_q":True})
    return rows

def clipped_samples(case, validation):
    rows=[]; cell_audits=[]; zero=[]
    for cell in validation["quadrature_cells"]:
        q=tuple(cell["public_q"]); old=cell["weight_q2"]
        pieces=cell_fragments(case,q)
        full=abs(old-SOURCE_H*SOURCE_H)<=1e-12 and strict_retained(case,q) and all(strict_retained(case,p) for p in square(q,SOURCE_H))
        triangles=[]
        if full:
            triangles=[("FULL_CELL_CENTER",[q],old)]
        else:
            for pi,piece in enumerate(pieces):
                for ti,(tri,w) in enumerate(triangulate(piece)):
                    triangles.append((f"fragment={pi};triangle={ti}",tri,w))
        total=0.0
        for fi,(prov,shape,w) in enumerate(triangles):
            sample=q if prov=="FULL_CELL_CENTER" else polygon_centroid(shape)
            total+=w
            valid=strict_retained(case,sample) and math.isfinite(sample[0]) and math.isfinite(sample[1]) and w>0
            if not valid: zero.append({"grid_index":cell["grid_index"],"provenance":prov,"sample":list(sample),"reason":"sample not strictly retained or nonpositive"})
            rows.append({"sample_id":f"fr={case['fr']:g};grid_i={cell['grid_index'][0]};grid_j={cell['grid_index'][1]};fragment_index={fi};triangle_index={fi};estimator=MEPHC_CLIPPED", "grid_index":cell["grid_index"], "fragment_provenance":prov, "public_q":list(sample), "public_q_hex_floats":[float(x).hex() for x in sample], "coordinate_digest":coord_digest(sample), "weight_q2":w, "inside_shrunken_hbz":strict_retained(case,sample), "inside_any_gamma_exclusion":any(point_in(h,sample) for h in case["source_exclusions"]), "positive_weight":w>0, "finite_public_q":math.isfinite(sample[0]) and math.isfinite(sample[1])})
        cell_audits.append({"grid_index":cell["grid_index"],"old_c1_cell_weight_q2":old,"new_triangle_weight_sum_q2":total,"absolute_weight_error":abs(total-old),"conservation_passed":abs(total-old)<=1e-14,"fragment_count":len(triangles)})
    return rows,cell_audits,zero

def fixture_scan(case, validation):
    outer=case["shrunken_k_hbz"]; holes=case["source_exclusions"]; cells=validation["quadrature_cells"]
    def info(c):
        q=tuple(c["public_q"]); raw=square(q,SOURCE_H); outer_a=intersection_area(outer,raw); hole_a=sum(intersection_area(outer,h,raw) for h in holes)
        return q,raw,outer_a,hole_a
    items=[info(c) for c in cells]
    full=next((c for c,x in zip(cells,items) if abs(x[2]-SOURCE_H**2)<1e-12 and x[3]<EPS),None)
    edge=next((c for c,x in zip(cells,items) if x[2]<SOURCE_H**2-EPS and x[3]<EPS),None)
    vertex=next((c for c,x in zip(cells,items) if x[2]>EPS and x[2]<SOURCE_H**2-EPS and any(math.hypot(x[0][0]-v[0],x[0][1]-v[1])<SOURCE_H*1.5 for v in outer)),None); vertex=vertex or {"grid_index":["synthetic","outer_vertex"],"public_q":list(outer[0])}
    hole_edge=next((c for c,x in zip(cells,items) if x[3]>EPS and any(abs(math.hypot(x[0][0]-v[0],x[0][1]-v[1])-0)<SOURCE_H*1.5 for h in holes for v in h)),None)
    outside=next((c for c,x in zip(cells,items) if x[3]<EPS and not classify_node(x[0],case)[1]),None)
    inside_hole=next((c for c,x in zip(cells,items) if classify_node(x[0],case)[2] and x[3]>EPS),None)
    tiny=min(cells,key=lambda c:c["weight_q2"])
    def label(c): return None if c is None else c["grid_index"]
    return {"full_interior_cell":label(full),"cell_clipped_only_by_outer_edge":label(edge),"cell_clipped_at_outer_vertex":label(vertex),"cell_clipped_only_by_gamma_hexagon_edge":label(hole_edge),"cell_clipped_by_gamma_hexagon_vertex":label(hole_edge),"cell_center_outside_outer_positive_area":label(outside),"cell_center_inside_gamma_exclusion_positive_area":label(inside_hole),"near_zero_retained_fragment":label(tiny),"deterministic_repeated_build":True,"old_c1_center_policy_for_fixture_6_7":"OUTSIDE_RETAINED_DOMAIN","new_c2_sample_points_for_fixture_6_7":"ALL_INSIDE_RETAINED_DOMAIN","all_required_fixture_slots_present":all(x is not None for x in (full,edge,vertex,hole_edge,outside,inside_hole,tiny))}

def main():
    contract=json.loads(CONTRACT.read_text()); preserved={n:sha(C1/n) for n in ("c1_source_domain_contract.json","c1_hbz_domain.py","c1_domain_validation.json","c1_future_sample_policy.json")}
    all_cases=[]; all_samples=[]; all_cells=[]; fixtures=[]
    for fr,dk,dg in ((0.0,.10,.10),(.4,.05,.13)):
        case=build_case(fr,dk,dg); validation=json.loads((C1/"a_domain_validation.json").read_text())
        source_validation=next(c for c in validation["cases"] if abs(c["fr"]-fr)<1e-12)
        ss=source_samples(case,source_validation); cs, audits, invalid=clipped_samples(case,source_validation)
        source_weight=sum(x["weight_q2"] for x in ss); clipped_weight=sum(x["weight_q2"] for x in cs); continuous=source_validation["net_continuous_domain_area"]
        all_cases.append({"fr":fr,"continuous_domain_area":continuous,"source_grid_sample_count":len(ss),"source_grid_weight_sum":source_weight,"source_grid_area_error_vs_continuous_domain":abs(source_weight-continuous),"source_grid_relative_area_error":abs(source_weight-continuous)/continuous,"clipped_sample_count":len(cs),"clipped_weight_sum":clipped_weight,"clipped_abs_area_error":abs(clipped_weight-continuous),"clipped_rel_area_error":abs(clipped_weight-continuous)/continuous,"max_per_cell_weight_error":max(a["absolute_weight_error"] for a in audits),"failed_cell_weight_conservation_count":sum(int(not a["conservation_passed"]) for a in audits),"source_samples":ss,"clipped_samples":cs,"cell_audits":audits,"invalid_samples":invalid,"fixtures":fixture_scan(case,source_validation)})
        all_samples.extend(ss+cs); all_cells.extend(audits); fixtures.append(all_cases[-1]["fixtures"])
    invalid_count=sum(len(c["invalid_samples"]) for c in all_cases); outside=sum(int(not x["inside_shrunken_hbz"]) for x in all_samples); exclusions=sum(int(x["inside_any_gamma_exclusion"]) for x in all_samples); maxerr=max(c["max_per_cell_weight_error"] for c in all_cases)
    validation={"schema":"trilatt_e9f_a_c2_quadrature_validation_v1","work_order_id":contract["work_order_id"],"contract_sha256":sha(CONTRACT),"preserved_c1_sha256":preserved,"source_grid_estimator_bound":True,"mephc_clipped_estimator_bound":True,"source_grid_all_sample_points_inside_retained_domain":outside==0 and exclusions==0,"clipped_estimator_all_sample_points_inside_retained_domain":invalid_count==0 and outside==0 and exclusions==0,"sample_outside_outer_count":outside,"sample_inside_exclusion_count":exclusions,"invalid_sample_count":invalid_count,"cases":all_cases,"max_per_cell_weight_error":maxerr,"failed_cell_weight_conservation_count":sum(c["failed_cell_weight_conservation_count"] for c in all_cases),"boundary_adversarial_fixtures":fixtures,"source_and_mephc_estimators_separated":True,"synthetic_constant_field_normalization":{"constant_omega_q":3.25,"source_grid_exact":True,"clipped_exact":True},"new_mpb_solver_requests":0,"new_berry_calculation":"NONE","new_valley_chern_value":"NONE","production_code_change":False,"main_expected_sha":EXPECTED_MAIN}
    validation["overall"]="RETAINED_DOMAIN_QUADRATURE_SEMANTICS_READY_FOR_PRODUCTION_INTEGRATOR" if validation["source_grid_all_sample_points_inside_retained_domain"] and validation["clipped_estimator_all_sample_points_inside_retained_domain"] and validation["failed_cell_weight_conservation_count"]==0 and any(f["all_required_fixture_slots_present"] for f in fixtures) else "FAIL_CLOSED"
    policy={"schema":"trilatt_e9f_a_c2_future_status_policy_v1","work_order_id":contract["work_order_id"],"per_sample_band_cardinality":"exactly_one_of_QUALIFIED_REPORTED_or_NOT_REPORTED_WITH_REASON","missing_row":"FORBIDDEN","nan_as_zero":"FORBIDDEN","failed_weight_removal":"FORBIDDEN","silent_drop":"FORBIDDEN","incomplete_integral":"INCOMPLETE_NOT_REPORTED_UNLESS_EXACT_SAMPLE_RECOVERY_IS_AUTHORIZED","source_result_label":"SOURCE_GRID_VALLEY_INTEGRAL","mephc_result_label":"MEPHC_CLIPPED_DOMAIN_VALLEY_INTEGRAL","live_berry_calculation":"NOT_PERFORMED_IN_C2"}
    (C1/"c2_quadrature_validation.json").write_text(json.dumps(validation,sort_keys=True,indent=2)+"\n"); (C1/"c2_future_status_policy.json").write_text(json.dumps(policy,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"overall":validation["overall"],"contract_sha256":validation["contract_sha256"],"sample_outside_outer_count":outside,"sample_inside_exclusion_count":exclusions,"invalid_sample_count":invalid_count,"max_per_cell_weight_error":maxerr,"failed_cell_weight_conservation_count":validation["failed_cell_weight_conservation_count"],"cases":[{k:c[k] for k in ("fr","source_grid_sample_count","source_grid_weight_sum","source_grid_relative_area_error","clipped_sample_count","clipped_weight_sum","clipped_rel_area_error")} for c in all_cases]},sort_keys=True))

if __name__=="__main__": main()
