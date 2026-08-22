"""E7I.2E bounded solver-native H-space live plaquette smoke."""
from __future__ import annotations
import contextlib,io,json,math,time
from pathlib import Path
import numpy as np
import meep as mp
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_berry_estimator import estimate_mpb_rank1_berry_curvature
from mephc.plaquette_domain import PlaquetteRefinementThresholds
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.mpb_reference_adapter import build_reference_mpb_adapter
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.valley_reference_geometry import build_triangular_reference_geometry

K=(2/3,0.0); BANDS=4; E3=SubspaceQualificationThresholds(.9,.45,.3,.05); E4C=PlaquetteRefinementThresholds(.9,.45,.3,.1)
def points(h):
 x,y=K;d=h/2;return ((x-d,y-d),(x+d,y-d),(x+d,y+d),(x-d,y+d),(x,y))
class Cache:
 def __init__(self,p):self.p=p;self.d={};self.raw=0;self.hits=0
 def solve(self,q):
  k=tuple(float(x) for x in q)
  if k in self.d:self.hits+=1;return self.d[k]
  self.raw+=1;self.d[k]=self.p.solve(k);return self.d[k]
def provider(adapter,res):
 return MPBLiveSpectralProvider(geometry=list(adapter.geometry),geometry_lattice=adapter.geometry_lattice,resolution=res,num_bands=BANDS,polarization=mp.TE,default_material=adapter.background_material,eigensolver_tolerance=1e-7,deterministic=True,mesh_size=3)
def snap_status(snaps):return {"all_orthogonality_qualified":all(s.is_orthogonality_qualified for s in snaps),"points":[list(s.k_point) for s in snaps],"statuses":[s.orthogonality_status for s in snaps],"max_off_diagonal":[s.max_off_diagonal_gram for s in snaps]}
def edge(e):
 d=e.to_dict(include_matrices=False);o=d.get("overlap") or {};return {"status":d["status"],"projector_distance":d["projector_distance"],"external_gaps":d["external_gaps"],"min_singular_value":o.get("min_singular_value"),"max_principal_angle":o.get("max_principal_angle"),"evidence":d["evidence"]}
def chain(cache,delta,band,rank=1):
 hs=(float(delta),float(delta)/2,float(delta)/4);levels=[];sels=[]
 for h in hs:
  ss=tuple(cache.solve(q) for q in points(h));levels.append(ss);sels.append(tuple(((band,) if rank==1 else (1,2),) for _ in range(5)))
 snap=snap_status(levels[0])
 try:
  source=qualify_mpb_plaquette(tuple(levels),tuple(sels),hs,thresholds=E3,refinement_thresholds=E4C)
 except ValueError as exc:
  return {"status":"SNAPSHOT_OR_ASSOCIATION_GATE_FAILED","qualified":False,"rank":rank,"selected_solver_indices":[list(x[0]) for x in sels[0]],"snapshot":snap,"first_failing_gate":str(exc),"refinement_steps":list(hs)}
 hol=compose_mpb_plaquette_holonomy(source)
 data={"status":hol.status[-1],"qualified":bool(hol.is_qualified),"live_qualified":bool(hol.is_live_qualified),"rank":rank,"selected_solver_indices":[[list(z) for z in level] for level in sels],"snapshot":snap,"refinement_steps":list(hs),"levels":[],"first_failing_gate":None}
 for i,(b,inside,m) in enumerate(zip(source.boundary_results,source.interior_results,source.refinement_result.metrics)):
  data["levels"].append({"boundary_status":b.status,"interior_status":inside.status,"edges":[edge(x) for x in b.edge_results],"spokes":[edge(x) for x in inside.spoke_results],"refinement_metric":m.to_dict()})
 if not hol.is_qualified:
  data["first_failing_gate"]=data["levels"][-1]["boundary_status"]+" / "+data["levels"][-1]["interior_status"]+" / "+source.refinement_result.status
  return data
 if rank==1:
  est=estimate_mpb_rank1_berry_curvature(hol);data["bounded_diagnostic_values"]=[{"status":x.status,"wilson_phase":x.wilson_phase,"signed_area":x.signed_area,"omega_q":x.curvature_estimate} for x in est.levels]
 else:
  w=hol.wilson_results[-1];data["bounded_diagnostic_values"]={"wilson_status":w.status,"determinant_phase":w.determinant_phase,"eigenphases":None if w.product is None else [float(x) for x in np.angle(np.linalg.eigvals(np.asarray(w.product)))]}
 return data
def endpoint(fr,label):
 a=build_reference_mpb_adapter(build_triangular_reference_geometry(fr),build_triangular_coordinate_preflight());out={"label":label,"adapter":a.to_dict(),"K_spectra":{},"K_orthogonality":{},"rank1":{},"rank2":None,"counters":[]}
 for r in (32,48,64):
  c=Cache(provider(a,r));s=c.solve(K);out["K_spectra"][f"R{r}"]={"frequencies":[float(x) for x in s.frequencies],"gaps":[float(s.frequencies[i+1]-s.frequencies[i]) for i in range(3)]};out["K_orthogonality"][f"R{r}"]=snap_status((s,));out["counters"].append({"stage":f"K_R{r}","unique_solves":c.raw,"cache_hits":c.hits})
 for r,d in ((48,1/36),(48,1/72),(64,1/36)):
  c=Cache(provider(a,r))
  for b in (0,1,2):out["rank1"][f"band_{b+1}_R{r}_dk_{d:.8f}"]=chain(c,d,b,1)
  out["counters"].append({"stage":f"rank1_R{r}_dk_{d:.8f}","unique_solves":c.raw,"cache_hits":c.hits})
 if fr==.5:
  c=Cache(provider(a,48));out["rank2"]=chain(c,1/36,1,2);out["counters"].append({"stage":"rank2_R48_dk_1_36","unique_solves":c.raw,"cache_hits":c.hits})
 return out
def main():
 start=time.time();result={"schema":"e7i2e_hspace_plaquette_smoke_v1","work_order":"E7I.2E","main_unchanged":True,"threshold_change":"FORBIDDEN","e_plus_h_gate_change":"FORBIDDEN","berry_global":"NOT_AUTHORIZED"}
 try:
  eps={"FR00":endpoint(0.0,"FR00_exact_triangle"),"FR050":endpoint(.5,"FR050_exact_circle")};result["endpoints"]=eps
  h_ok=all(v["K_orthogonality"]["R48"]["all_orthogonality_qualified"] for v in eps.values());qualified=[x["qualified"] for v in eps.values() for x in v["rank1"].values()]+[eps["FR050"]["rank2"]["qualified"]]
  result["FR00_HSPACE_ORTHOGONALITY_STATUS"]="PASSED" if eps["FR00"]["K_orthogonality"]["R48"]["all_orthogonality_qualified"] else "FAILED"
  result["FR050_HSPACE_ORTHOGONALITY_STATUS"]="PASSED" if eps["FR050"]["K_orthogonality"]["R48"]["all_orthogonality_qualified"] else "FAILED"
  result["classification"]="E7I2E_HSPACE_LIVE_PLAQUETTE_QUALIFIED" if any(qualified) else "E7I2E_HSPACE_REPRESENTATION_PASSES_BUT_PHYSICAL_QUALIFICATION_BLOCKED" if h_ok else "E7I2E_HSPACE_UNEXPECTED_FAILURE"
  result["overall"]="E7I2E_REPORT_READY"
 except Exception as exc:result.update({"overall":"E7I2E_FAILED_CLEANLY","error_type":type(exc).__name__,"error":str(exc)})
 result["elapsed_seconds"]=time.time()-start;Path(__file__).with_name("result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n");print(json.dumps({"overall":result["overall"],"classification":result.get("classification"),"error":result.get("error")}))
 if result["overall"]!="E7I2E_REPORT_READY":raise SystemExit(2)
if __name__=="__main__":main()
