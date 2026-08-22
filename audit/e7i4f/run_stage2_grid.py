"""E7I.4F conditional Stage-2 1/36 integration grid."""
from __future__ import annotations
import json,math,subprocess,time
from pathlib import Path
from audit.e7i4e.run_complete_stage1_chern import evaluate
from mephc.valley_benchmark import PhysicalSolveCache,paper_style_truncated_k_hbz,sample_domain
from audit.e7i3c.run_representation_bridge import build_reference_mpb_adapter,build_triangular_coordinate_preflight,build_triangular_reference_geometry
FR=0.0; SPACING=1.0/36.0; PRIMARY=1.0/36.0; REF=1.0/72.0; RES=48
def main():
 root=Path(__file__).resolve().parents[2]; geometry=build_triangular_reference_geometry(FR); preflight=build_triangular_coordinate_preflight(); adapter=build_reference_mpb_adapter(geometry,preflight); domain=paper_style_truncated_k_hbz(fr=FR,delta_k=0.10,delta_gamma=0.10); sample=sample_domain(domain,SPACING); cache={}; identities=PhysicalSolveCache(); counters={"raw_requests":0,"unique_solves":0,"cache_hits":0,"solver_failures":0}; rows=[]; start=time.monotonic()
 for i,(center,weight,eid) in enumerate(zip(sample.centers,sample.weights,sample.element_ids)):
  row={"element_id":eid,"evaluation_q":list(center),"weight_q2":float(weight)}
  attempts=[]
  for delta in (PRIMARY,REF,REF/2):
   ref_delta=delta/2
   ev=evaluate(row,delta,ref_delta,adapter,preflight,geometry,cache,identities,counters,{})
   attempts.append({"delta":delta,"ref_delta":ref_delta,"qualified":bool(ev["qualified"]),"profile_passed":bool(ev["profile_passed"]),"refinement_status":None if ev["refinement"] is None else ev["refinement"]["status"]})
   if ev["qualified"]: break
  rows.append({k:v for k,v in ev.items() if not k.startswith("_")} | {"element_id":eid,"weight_q2":float(weight),"evaluation_q":list(center),"adaptive_attempts":attempts})
  if i%100==0: print(json.dumps({"progress":i,"total":sample.center_count}),flush=True)
 qualified=[r for r in rows if r["qualified"]]; integral=None; chern=None
 if len(qualified)==len(rows):
  integral=sum(float(r["weight_q2"])*float(r["omega_trace_q"]) for r in rows); chern=integral/(2*math.pi)
 result={"schema":"e7i4f_stage2_grid_v1","grid_spacing":SPACING,"primary_local_delta":PRIMARY,"reference_delta":REF,"element_count":len(rows),"qualified_element_count":len(qualified),"qualified_area_fraction":sum(float(r["weight_q2"]) for r in qualified)/float(sample.retained_area_q),"retained_area_q":float(sample.retained_area_q),"curvature_integral":integral,"composite_valley_chern":chern,"stage2_status":"FULLY_QUALIFIED" if chern is not None else "PARTIAL","rows":rows,"raw_solve_requests":counters["raw_requests"],"unique_mpb_solves":counters["unique_solves"],"cache_hits":counters["cache_hits"],"cache_hit_fraction":counters["cache_hits"]/counters["raw_requests"] if counters["raw_requests"] else 0.0,"solver_failures":counters["solver_failures"],"wall_time_seconds":time.monotonic()-start,"stage2_observable_class":"FR00_RANK3_COMPOSITE_VALLEY_CHERN_INTEGRATION_GRID_1OVER36_PILOT" if chern is not None else "NOT_REPORTED","stage2_full_grid":"AUTHORIZED_AND_EXECUTED"}
 (root/"audit"/"e7i4f").mkdir(parents=True,exist_ok=True); (root/"audit"/"e7i4f"/"stage2_result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n"); print(json.dumps({"stage2_status":result["stage2_status"],"elements":len(rows),"qualified":len(qualified),"chern":chern}))
if __name__=="__main__": main()
