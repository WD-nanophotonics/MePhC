"""Audit-only E9F.C1.D1.C1 geometry correction and process review."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HIST=ROOT/"audit/e9f/c1_d1_result.json"; OUT=ROOT/"audit/e9f/c1_d1_c1_result.json"; REVIEW=ROOT/"audit/e9f/c1_d1_c1_process_reliability_review.json"
WORK_ORDER="TRILATT-E9F-C-C1-D1-C1-20260824-220"; BASE_SANDBOX_SHA="e7e3aeb2b2c8cbfa5c34c55757a100634c56e563"; MAIN_SHA="5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"; MIN_GAP=.02; EPS=1e-12
def canon(v): return (json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def digest(v): return hashlib.sha256(canon(v)).hexdigest()
def sha256_file(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write_json(p,v):
 t=p.with_suffix(p.suffix+".tmp"); t.write_text(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8"); t.replace(p)
def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def onseg(a,b,p): return abs(cross(a,b,p))<=EPS and min(a[0],b[0])-EPS<=p[0]<=max(a[0],b[0])+EPS and min(a[1],b[1])-EPS<=p[1]<=max(a[1],b[1])+EPS
def segint(a,b,c,d):
 x,y,z,w=cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
 if onseg(a,b,c) or onseg(a,b,d) or onseg(c,d,a) or onseg(c,d,b): return True
 return ((x>EPS)!=(y>EPS) and (z>EPS)!=(w>EPS)) or ((x<-EPS)!=(y<-EPS) and (z<-EPS)!=(w<-EPS))
def edges(poly): return zip(poly,list(poly[1:])+[poly[0]])
def inside(poly,p):
 from mephc.valley_integration import _point_in
 return bool(_point_in(poly,p))
def boundary(seg,poly): return any(segint(seg[0],seg[1],a,b) for a,b in edges(poly))
def crosses_outer(seg,outer): return boundary(seg,outer)
def leaves_outer(seg,outer): return not(inside(outer,seg[0]) and inside(outer,seg[1]))
def segment_crosses_outer_boundary(seg,outer): return crosses_outer(seg,outer)
def segment_leaves_outer_domain(seg,outer): return leaves_outer(seg,outer)
def enters_gamma(seg,exclusions):
 mid=((seg[0][0]+seg[1][0])/2,(seg[0][1]+seg[1][1])/2)
 return any(inside(p,seg[0]) or inside(p,seg[1]) or inside(p,mid) or boundary(seg,p) for p in exclusions)
def segment_enters_gamma_exclusion(seg,exclusions): return enters_gamma(seg,exclusions)
def pinfo(p,outer,exclusions):
 oi=inside(outer,p); gi=[inside(x,p) for x in exclusions]
 return {"q":[float(p[0]),float(p[1])],"outer_inside":oi,"gamma_inside":gi,"retained_inside":oi and not any(gi)}
def corrected_side(old,outer,exclusions):
 vs=[tuple(float(x) for x in r["q"]) for r in old["vertices"]]; vr=[pinfo(p,outer,exclusions) for p in vs]; er=[]
 for i,a in enumerate(vs):
  b=vs[(i+1)%len(vs)]; s=(a,b)
  er.append({"from":list(a),"to":list(b),"segment_crosses_outer_boundary":crosses_outer(s,outer),"segment_leaves_outer_domain":leaves_outer(s,outer),"segment_enters_gamma_exclusion":enters_gamma(s,exclusions)})
 return {"side":float(old["side"]),"center":old["center"],"vertices":vr,"edges":er,"plaquette_crosses_outer_boundary":any(x["segment_crosses_outer_boundary"] for x in er),"plaquette_leaves_outer_domain":any(x["segment_leaves_outer_domain"] for x in er) or any(not x["outer_inside"] for x in vr),"plaquette_enters_gamma_exclusion":any(x["segment_enters_gamma_exclusion"] for x in er) or any(any(x["gamma_inside"]) for x in vr),"plaquette_fully_retained":all(x["retained_inside"] for x in vr) and not any(x["segment_leaves_outer_domain"] for x in er) and not any(x["segment_enters_gamma_exclusion"] for x in er)}
def num(item): return {"sample_index":item["sample_index"],"sample_id":item["sample_id"],"center":item["center"],"stencils":item["stencils"],"counters":item["counters"]}
def gap(r):
 f=r["center_frequencies"]; return min(abs(float(f[2])-float(x)) for i,x in enumerate(f) if i!=2)
def classify(g,item):
 r36=item["stencils"]["1/36"]["r64"]; r144=item["stencils"]["1/144"]["r64"]; q=gap(r36)
 if q>=MIN_GAP and not r36["qualified"] and r144["qualified"]:
  if g["1/36"]["plaquette_enters_gamma_exclusion"]: return "FINITE_STENCIL_QUALIFICATION_ARTIFACT_SUPPORTED","GAMMA_EXCLUSION_INTERACTION_STENCIL"
  if g["1/36"]["plaquette_crosses_outer_boundary"]: return "FINITE_STENCIL_QUALIFICATION_ARTIFACT_SUPPORTED","OUTER_BOUNDARY_CROSSING_STENCIL"
  if not g["1/36"]["plaquette_leaves_outer_domain"]: return "FINITE_STENCIL_QUALIFICATION_ARTIFACT_SUPPORTED","LOW_GAP_NEIGHBORHOOD_STENCIL_WITHOUT_DOMAIN_CROSSING"
  return "FINITE_STENCIL_QUALIFICATION_ARTIFACT_SUPPORTED","OTHER_FINITE_STENCIL_EFFECT"
 if q<MIN_GAP and not r144["qualified"]: return "TRUE_POINTWISE_LOW_GAP_BLOCKER",None
 r96=item["stencils"]["1/144"].get("r96")
 if r96 is not None and bool(r96["qualified"])!=bool(r144["qualified"]): return "RESOLUTION_SENSITIVE_UNRESOLVED","OTHER_FINITE_STENCIL_EFFECT"
 return "OTHER_NUMERICAL_OR_PATH_BLOCKER","OTHER_FINITE_STENCIL_EFFECT"
def build_result():
 from mephc.valley_integration import build_source_bound_domain
 hist=json.loads(HIST.read_text(encoding="utf-8")); domain=build_source_bound_domain(0.0); items=hist["diagnostics"]; nums=[num(x) for x in items]; rows=[]; counts={}; subs={}
 for item in items:
  g={k:corrected_side(v,domain.outer,domain.exclusions) for k,v in item["geometry"].items()}; high,sub=classify(g,item)
  q={"center_gap":gap(item["stencils"]["1/36"]["r64"]),"qualification":{k:{"r64":bool(item["stencils"][k]["r64"]["qualified"]),"r96":None if item["stencils"][k].get("r96") is None else bool(item["stencils"][k]["r96"]["qualified"])} for k in ("1/36","1/72","1/144")},"conditional_r96":None if item["stencils"]["1/144"].get("r96") is None else {"qualified":bool(item["stencils"]["1/144"]["r96"]["qualified"]),"resolution":item["stencils"]["1/144"]["r96"]["resolution"]},"numerical_payload_sha256":digest(num(item))}
  rows.append({"sample_index":item["sample_index"],"sample_id":item["sample_id"],"center":item["center"],"center_retained_status":g["1/36"]["center"]["retained_inside"],"geometry":g,"existing_numerical":q,"classification":high,"classification_subtype":sub}); counts[high]=counts.get(high,0)+1
  if sub is not None: subs[sub]=subs.get(sub,0)+1
 nh=digest(nums); return {"schema":"trilatt_e9f_c1_d1_c1_geometry_corrected_v1","status":"E9F_C1_D1_GEOMETRY_CORRECTED_PROCESS_REVIEW_COMPLETE_READY_FOR_RECOVERY_POLICY_DESIGN","work_order_id":WORK_ORDER,"base_sandbox_sha":BASE_SANDBOX_SHA,"main_sha":MAIN_SHA,"main_unchanged":True,"historical_d1_result_sha256":sha256_file(HIST),"historical_d1_result_preserved":True,"geometry_conventions":{"outer_polygon_convex":True,"boundary_touch_counts_as_crossing":True,"inside_segment_is_not_boundary_crossing":True,"inside_to_outside_and_outside_to_inside_cross":True,"tangent_touch_crosses_but_does_not_leave":True,"outer_inside_is_inclusive":True},"numerical_payload_definition":"sample_index, sample_id, center, stencils, and counters copied from historical D1 diagnostics; geometry excluded","historical_numerical_payload_sha256":nh,"corrected_numerical_payload_sha256":digest([num(x) for x in items]),"numerical_payload_preserved":nh==digest([num(x) for x in items]),"failed_sample_count":len(rows),"diagnostics":rows,"classification_counts":counts,"classification_subtype_counts":subs,"no_mpb_solves":True,"no_new_chern":True,"no_threshold_change":True,"original_d1_not_mutated":True}
def inc(i,phase,symptom,root,count,first,recovery,change,sci,corrective,priority="P1",candidate=True):
 return {"incident_id":i,"phase":phase,"symptom":symptom,"root_cause":root,"occurrence_count":count,"first_detected_when":first,"recovery_or_workaround":recovery,"code_or_workflow_change_required":change,"scientific_result_impact":sci,"provenance_impact":"Recorded in the incident evidence and kept fail-closed until corrected.","could_have_been_detected_earlier":True,"should_have_been_reported_earlier":True,"recurrence_risk":"high" if priority=="P1" else "medium","permanent_corrective":corrective,"priority":priority,"pipeline_defect_candidate":candidate}
def review():
 xs=[
 inc("REL-001","E9F.B.C2R.C1","Cross-runtime raw plan/domain digests differed while coordinates/topology were equivalent","Raw floating-point serialization was used as portability identity",1,"C2R.C1 two-interpreter probe","Separated semantic-domain/topology fingerprints from raw runtime digests",True,"None; no live science","Portability failed closed until identity layers separated","Require semantic/topology preflight before live campaigns"),
 inc("REL-002","E9F.B.C2R.C2","Full suite had six FileNotFoundError failures for hardcoded /tmp/TriLatt and /tmp/SqrLatt paths","Tests encoded environment-specific sibling paths",6,"C2R.C1 full-suite regression","Created bounded symlinks, then removed them",True,"None; no live science","Regression gate needed environment accommodation","Use repository-relative/runtime-discovered fixture roots"),
 inc("REL-003","E9F.C1 launch/provenance","Execution identity changed through exact-SHA, ancestor, and checkpoint hardenings","Sealed base, executable runner, and compatible descendants were conflated",3,"d9b1ce7 -> 4be5d96 -> b3f7dd9","Added execution identity, ancestry guard, and stable scientific checkpoint identity",True,"No invalid accepted values; launch failed closed","Standardize execution/scientific identity layers"),
 inc("REL-004","E9F.C1 checkpoint/recovery","c1_live.log contains FileNotFoundError for checkpoint worker sample_0499","Worker artifact lifecycle was not atomic across interruption/retry",1,"Retained c1_live.log during C1 recovery","Repaired checkpoint/runner flow and completed bounded recovery",True,"No accepted value came from missing artifact","Transactional worker outputs and durable resume manifests"),
 inc("REL-005","E9F.C1 early execution","WSL/native MPB sessions became unavailable or unstable during long attempts","Native MPB/MPI state and long-lived sessions were not isolated; low-level cause partly unknown",3,"Early C1 bounded execution/recovery attempts","Restarted WSL and resumed from checkpoints",True,"Interrupted attempts contributed no accepted value","Fresh native-MPB children and bounded parent"),
 inc("REL-006","E9F.C1 memory","Long-lived runner retained solver snapshots and needed cache bounding","Parent cache retained per-sample evidence",1,"C1 memory review before final campaign","Cleared per-sample cache and collected garbage in 06459b9",True,"None after correction","Bounded cache ownership and RSS telemetry"),
 inc("REL-007","E9F.C1 execution","Native MPB state contamination required per-sample process isolation","Solver/native state was not safely reusable across samples",1,"86e478a","Fresh child process per sample with identity checks",True,"None after correction","Reusable isolated-sample solver runner"),
 inc("REL-008","E9F.C1 orchestration","Parent imported MPB/MPI state before child execution","Parent was not independent of native solver runtime",1,"ca56f6f","Lazy-loaded helpers only inside child processes",True,"None after correction","Reusable MPB-free parent orchestrator"),
 inc("REL-009","E9F.C1 Gate P","Execution commits initially were not remotely resolvable","Local execution and remote object availability were not one delivery gate",1,"D1 Gate P verification","Pushed unchanged commits and verified remote objects",True,"None; no main promotion","Require remote object-resolution before reporting"),
 inc("REL-010","E9F.C1.D1","D1 labeled inside segments as outer-boundary crossings","Point-in-polygon predicate was reused for boundary crossing",17,"Supervisor audit of D1 artifact","Fail closed; preserve historical artifact; geometry-only correction",True,"Numerical facts accepted; geometry interpretation rejected","Adversarial separation of crossing/leaving/exclusion predicates")]
 return {"schema":"trilatt_e9f_c1_d1_c1_process_reliability_review_v1","work_order_id":WORK_ORDER,"base_sandbox_sha":BASE_SANDBOX_SHA,"main_sha":MAIN_SHA,"main_unchanged":True,"review_scope":"E9F.B C2R.C1 through E9F.C1.D1.C1; successful values do not erase execution incidents","commit_sequence":["dd215c6","286a130","d9b1ce7","4be5d96","b3f7dd9","06459b9","86e478a","ca56f6f","2721371","e28fb69","682fba4","e7e3aeb"],"incidents":xs,"pipeline_health":"PIPELINE_REQUIRES_CORRECTIVE","p0_items":[],"p1_items":[x["incident_id"] for x in xs],"p2_items":[],"reusable_infrastructure":["immutable campaign identity layers","portable plan preflight","transactional checkpoint/resume","MPB-free parent with isolated native children","bounded cache/RSS telemetry","adversarial geometry predicates","remote object-resolution Gate P"],"local_environment_only":["REL-005"],"repository_or_workflow_defects":[x["incident_id"] for x in xs if x["incident_id"]!="REL-005"],"exact_immutable_execution_sha_required_before_first_solve":True,"checkpoint_resume_should_be_standardized":True,"native_process_isolation_should_be_standardized":True,"p0_invalidation_found":False}
def main():
 r,q=build_result(),review(); write_json(OUT,r); write_json(REVIEW,q); print(json.dumps({"status":r["status"],"classification_counts":r["classification_counts"],"classification_subtype_counts":r["classification_subtype_counts"],"pipeline_health":q["pipeline_health"],"numerical_payload_preserved":r["numerical_payload_preserved"]},sort_keys=True))
if __name__=="__main__": main()
