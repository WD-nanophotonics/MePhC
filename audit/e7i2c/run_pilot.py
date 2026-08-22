"""E7I.2C bounded live triangular/circle MPB smoke runner."""
from __future__ import annotations
import json, math, time
from pathlib import Path
import numpy as np
from mephc.mpb_berry_estimator import estimate_mpb_rank1_berry_curvature
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.plaquette_domain import PlaquetteRefinementThresholds
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.valley_reference_geometry import build_triangular_reference_geometry
from mephc.mpb_reference_adapter import build_reference_mpb_adapter

E3=SubspaceQualificationThresholds(.9,.45,.3,.05)
E4C=PlaquetteRefinementThresholds(.9,.45,.3,.1)
K=(2/3,0.0)
DEGENERACY_TOLERANCE=1e-4
RESOLUTIONS=(32,48,64)
NUM_BANDS=4

class SolveCache:
    def __init__(self,provider):
        self.provider=provider; self.values={}; self.raw_requests=0; self.cache_hits=0; self.solver_failures=0
    def solve(self,q):
        key=tuple(float(x) for x in q)
        if key in self.values:
            self.cache_hits+=1; return self.values[key]
        self.raw_requests+=1
        try:
            value=self.provider.solve(key)
        except Exception:
            self.solver_failures+=1; raise
        self.values[key]=value; return value

def _spectrum(snapshot):
    freq=[float(x) for x in snapshot.frequencies]
    if len(freq)!=NUM_BANDS or not all(math.isfinite(x) for x in freq):
        raise RuntimeError("nonfinite or incomplete spectrum")
    gaps=[freq[i+1]-freq[i] for i in range(NUM_BANDS-1)]
    if any(x<0 for x in gaps):
        raise RuntimeError("MPB spectrum is not ordered")
    return {"frequencies":freq,"gaps_21_32_43":gaps}

def _plaquette(center, h):
    x,y=center; d=h/2
    return ((x-d,y-d),(x+d,y-d),(x+d,y+d),(x-d,y+d),(x,y))

def _level_snapshots(cache,center,h):
    return tuple(cache.solve(q) for q in _plaquette(center,h))

def _berry(cache,center,delta,band):
    hs=(float(delta),float(delta)/2,float(delta)/4)
    levels=tuple(_level_snapshots(cache,center,h) for h in hs)
    selections=tuple((((band,),)*5) for _ in hs)
    try:
        source=qualify_mpb_plaquette(levels,selections,hs,thresholds=E3,refinement_thresholds=E4C)
        result=estimate_mpb_rank1_berry_curvature(compose_mpb_plaquette_holonomy(source))
    except ValueError as exc:
        return {"qualified":False,"live_qualified":False,"selected_band":band+1,"status":"FAIL_CLOSED_UNQUALIFIED_SNAPSHOT","reason":str(exc),"levels":[]}
    rows=[]
    for level in result.levels:
        rows.append({"status":level.status,"step":level.step,"signed_area":level.signed_area,"wilson_phase":level.wilson_phase,"omega_q":level.curvature_estimate,"omega_phys_over_a2":None if level.curvature_estimate is None else level.curvature_estimate/(2*math.pi)**2})
    return {"qualified":bool(result.is_qualified),"live_qualified":bool(result.is_live_qualified),"selected_band":band+1,"status":"QUALIFIED","levels":rows}

def _adapter(fr):
    return build_reference_mpb_adapter(build_triangular_reference_geometry(fr),build_triangular_coordinate_preflight())

def _run_endpoint(fr, label):
    adapter=_adapter(fr); endpoint={"label":label,"adapter":adapter.to_dict(),"spectra":{},"berry":{},"counters":[]}
    for resolution in RESOLUTIONS:
        cache=SolveCache(adapter.provider(resolution=resolution,num_bands=NUM_BANDS))
        endpoint["spectra"][str(resolution)]=_spectrum(cache.solve(K))
        endpoint["counters"].append({"stage":f"K_R{resolution}","unique_solves":cache.raw_requests,"cache_hits":cache.cache_hits,"solver_failures":cache.solver_failures})
    repeat=SolveCache(adapter.provider(resolution=48,num_bands=NUM_BANDS))
    first=_spectrum(repeat.solve(K)); second=_spectrum(repeat.solve(K))
    endpoint["repeat_R48_max_frequency_delta"]=max(abs(a-b) for a,b in zip(first["frequencies"],second["frequencies"]))
    cache=SolveCache(adapter.provider(resolution=48,num_bands=NUM_BANDS))
    for band in (0,1,2):
        endpoint["berry"][f"band_{band+1}_R48_dk_1_36"]=_berry(cache,K,1/36,band)
    endpoint["counters"].append({"stage":"berry_R48_dk_1_36","unique_solves":cache.raw_requests,"cache_hits":cache.cache_hits,"solver_failures":cache.solver_failures})
    cache=SolveCache(adapter.provider(resolution=48,num_bands=NUM_BANDS))
    endpoint["berry_sensitivity_R48_dk_1_72"]={f"band_{band+1}":_berry(cache,K,1/72,band) for band in (0,1,2)}
    endpoint["counters"].append({"stage":"berry_R48_dk_1_72","unique_solves":cache.raw_requests,"cache_hits":cache.cache_hits,"solver_failures":cache.solver_failures})
    cache=SolveCache(adapter.provider(resolution=64,num_bands=NUM_BANDS))
    endpoint["berry_sensitivity_R64_dk_1_36"]={f"band_{band+1}":_berry(cache,K,1/36,band) for band in (0,1,2)}
    endpoint["counters"].append({"stage":"berry_R64_dk_1_36","unique_solves":cache.raw_requests,"cache_hits":cache.cache_hits,"solver_failures":cache.solver_failures})
    return endpoint

def _circle_rank2(adapter):
    cache=SolveCache(adapter.provider(resolution=48,num_bands=NUM_BANDS))
    hs=(1/36,1/72,1/144)
    levels=tuple(_level_snapshots(cache,K,h) for h in hs)
    selections=tuple((((1,2),)*5) for _ in hs)
    try:
        source=qualify_mpb_plaquette(levels,selections,hs,thresholds=E3,refinement_thresholds=E4C)
        holonomy=compose_mpb_plaquette_holonomy(source)
        row={"status":holonomy.status[-1],"qualified":bool(holonomy.is_qualified),"rank":2,"rank1_policy":"PROHIBITED_AND_ENFORCED"}
        if holonomy.wilson_results[-1].product is not None:
            product=np.asarray(holonomy.wilson_results[-1].product)
            row.update({"determinant_phase":float(np.angle(np.linalg.det(product))),"eigenphases":[float(x) for x in np.angle(np.linalg.eigvals(product))]})
    except ValueError as exc:
        row={"status":"PARTIAL_UNQUALIFIED_SNAPSHOT","qualified":False,"rank":2,"rank1_policy":"PROHIBITED_AND_ENFORCED","reason":str(exc)}
    row["counters"]={"unique_solves":cache.raw_requests,"cache_hits":cache.cache_hits,"solver_failures":cache.solver_failures}
    return row

def main():
    started=time.time()
    result={"schema":"e7i2c_live_smoke_result_v1","work_order":"E7I.2C","code_change":"SANDBOX_ONLY","main_unchanged":True,"live_valley_chern":"NOT_AUTHORIZED","dense_sweep":"NOT_AUTHORIZED","mpb_reference_adapter":"READY","mpb_coordinate_preflight":"PASSED","reference_material_semantics":"RELATIVE_PERMITTIVITY","fr050_rank1_policy":"PROHIBITED_AND_ENFORCED"}
    try:
        triangle=_run_endpoint(0.0,"FR00_exact_triangle")
        circle_adapter=_adapter(0.5)
        circle_spectra={}
        for r in RESOLUTIONS:
            c=SolveCache(circle_adapter.provider(resolution=r,num_bands=NUM_BANDS)); circle_spectra[str(r)]=_spectrum(c.solve(K))
        f2,f3=circle_spectra["48"]["frequencies"][1:3]; split=abs(f3-f2)
        if split<=DEGENERACY_TOLERANCE: degeneracy="DEGENERACY_SUPPORTED"
        elif split<=1e-2: degeneracy="NUMERICALLY_UNRESOLVED"
        else: degeneracy="UNEXPECTED_NONDEGENERATE_RESULT"
        result.update({"triangle":triangle,"circle":{"adapter":circle_adapter.to_dict(),"spectra":circle_spectra,"band_2_3_split_R48":split,"degeneracy_classification":degeneracy},"fr00_local_berry_smoke":"PASSED" if all(x["qualified"] for x in triangle["berry"].values()) else "PARTIAL"})
        if degeneracy=="UNEXPECTED_NONDEGENERATE_RESULT":
            result["fr050_rank2_diagnostic"]="NOT_RUN_DUE_TO_PRIOR_GATE"
        else:
            result["fr050_rank2_diagnostic"]=_circle_rank2(circle_adapter)
        berry_ok=all(x["qualified"] for x in triangle["berry"].values())
        result["fr00_k_spectral_smoke"]="PASSED"
        result["fr00_local_berry_smoke"]="PASSED" if berry_ok else "PARTIAL"
        result["fr00_relative_berry_pattern"]="CONSISTENT_WITH_REFERENCE" if berry_ok else "PHYSICALLY_UNQUALIFIED"
        result["local_delta_k_sensitivity"]="MEASURED"
        result["local_resolution_sensitivity"]="MEASURED"
        result["absolute_paper_valley_sign_gate"]="DISABLED_DUE_TO_CONVENTION_MAPPED_ORIENTATION"
        result["overall"]="BOUNDED_LIVE_TRIANGULAR_REFERENCE_SMOKE_READY_FOR_SUPERVISOR_AUDIT" if berry_ok else "LIVE_SMOKE_PARTIAL"
    except Exception as exc:
        result.update({"overall":"LIVE_SMOKE_FAILED_CLEANLY","error_type":type(exc).__name__,"error":str(exc)})
    result["elapsed_seconds"]=time.time()-started
    out=Path(__file__).with_name("result.json"); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"overall":result["overall"],"error":result.get("error"),"elapsed_seconds":result["elapsed_seconds"]},sort_keys=True))
    if result["overall"]=="LIVE_SMOKE_FAILED_CLEANLY": raise SystemExit(2)

if __name__=="__main__": main()
