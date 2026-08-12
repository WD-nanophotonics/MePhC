
"""Run the five required R4 production smoke paths with real MPB calls."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import time

BUNDLE=Path(__file__).resolve().parent
for p in ("/home/icy/MePhC","/home/icy/SqrLatt"):
    if p not in sys.path:
        sys.path.insert(0,p)
import square_hole.config as config
from square_hole.canonical import SquareHoleStructure
import band_structure, berry_curvature, efs
log=[]

class CaseProxy:
    lattice_type=config.lattice_type
    def __init__(self,s): self.s=s
    def canonical_structure(self): return self.s
    def build_pattern(self): return self.s.build_pattern()
    def make_band(self,*,resolution): return self.s.make_band(resolution=resolution)
    def band_path(self): return self.s.band_path()
    def band_path_policy(self): return self.s.band_path_policy()
    def square_grid(self,n,extent=0.5): return self.s.sample_grid(n,extent=extent)
    def c4_quadrant(self,n,extent=1.0): return self.s.c4_quadrant(n,extent=extent)

def shape(x): return list(x.shape) if hasattr(x,"shape") else None

def run(sid,fn,params,checks,domain,symmetry):
    started=time.monotonic()
    e={"id":sid,"status":"FAIL","parameters":params,"command":"PYTHONPATH=/home/icy/MePhC:/home/icy/SqrLatt /home/icy/miniconda3/envs/mp/bin/python docs/architecture/mephc_affine_architecture_r4/run_r4_smokes.py","driver_path":"docs/architecture/mephc_affine_architecture_r4/run_r4_smokes.py","solver":"meep.mpb.ModeSolver","production_entry_traversed":True,"required_assertions":sorted(checks),"assertion_results":{},"numerical_or_shape_summary":{},"domain_policy":domain,"symmetry_policy":symmetry,"log_path":"logs/production_smokes.log","exit_code":1}
    try:
        record=fn()[0]; data=record["data"]; summary={}
        if isinstance(data,dict):
            for k in ("k_points","freqs","bcs","raw_k_points","raw_bcs"):
                if k in data: summary[k+"_shape"]=shape(data[k])
            for k in ("symmetry","domain","path_policy"):
                summary[k]=data.get(k)
        else:
            summary["freqs_shape"]=shape(data.freqs)
            summary["actual_freqs_shape"]=shape(data.actual_freqs)
            summary["domain"]=data.metadata.get("domain")
        e["numerical_or_shape_summary"]=summary
        e["assertion_results"]={name:bool(test(record,summary)) for name,test in checks.items()}
        if not all(e["assertion_results"].values()):
            raise AssertionError(", ".join(k for k,v in e["assertion_results"].items() if not v))
        e["status"]="PASS"; e["exit_code"]=0
    except Exception as exc:
        e["error"]=f"{type(exc).__name__}: {exc}"
    e["duration_seconds"]=round(time.monotonic()-started,6)
    log.append(f"{sid} {e['status']} {e.get('error',json.dumps(e['numerical_or_shape_summary'],default=str,sort_keys=True))}")
    return e

identity=config
affine=CaseProxy(SquareHoleStructure(stretch_factor=1.1,stretch_angle_degrees=17.0))
smokes=[
run("R4-SMOKE-BAND-IDENTITY",lambda:band_structure.compute_band_structure(identity,resolution=2,num_bands=1,n_per_segment=1,run_mode="compute",save=False,save_tmp=False,source_case="r4-smoke"),{"resolution":2,"num_bands":1,"n_per_segment":1,"identity":True},{"freqs_shape":lambda r,s:s.get("freqs_shape")==[4,1],"path_policy":lambda r,s:s.get("path_policy")=="gxm","identity_structure":lambda r,s:r["data"]["canonical_structure"]["geometry_id"]==identity.get_geometry_id()},"legacy_square_gxm","identity_legacy_path"),
run("R4-SMOKE-BAND-AFFINE",lambda:band_structure.compute_band_structure(affine,resolution=2,num_bands=1,n_per_segment=1,run_mode="compute",save=False,save_tmp=False,source_case="r4-smoke"),{"resolution":2,"num_bands":1,"n_per_segment":1,"identity":False,"stretch_factor":1.1,"angle":17.0},{"freqs_shape":lambda r,s:s.get("freqs_shape")==[8,1],"path_policy":lambda r,s:s.get("path_policy")=="generic_current_bz_vertices","affine_structure":lambda r,s:r["data"]["canonical_structure"]["geometry_id"]==affine.canonical_structure().geometry_id()},"current_bz","auto_none"),
run("R4-SMOKE-BERRY-IDENTITY-C4Q",lambda:berry_curvature.compute_berry_curvature(identity,resolution=2,num_bands=1,grid_n=1,grid_extent=1.0,step=0.02,symmetry="auto",run_mode="compute",save=False,save_tmp=False,source_case="r4-smoke"),{"resolution":2,"num_bands":1,"grid_n":1,"grid_extent":1.0,"step":0.02,"symmetry":"auto"},{"bcs_shape":lambda r,s:s.get("bcs_shape")==[1,1],"raw_bcs_shape":lambda r,s:s.get("raw_bcs_shape")==[1,1],"symmetry_c4q":lambda r,s:s.get("symmetry")=="c4q","domain_c4q":lambda r,s:s.get("domain")=="c4_quadrant"},"c4_quadrant_expanded","verified_c4q"),
run("R4-SMOKE-BERRY-AFFINE-RAW",lambda:berry_curvature.compute_berry_curvature(affine,resolution=2,num_bands=1,grid_n=1,grid_extent=0.5,step=0.02,symmetry="auto",run_mode="compute",save=False,save_tmp=False,source_case="r4-smoke"),{"resolution":2,"num_bands":1,"grid_n":1,"grid_extent":0.5,"step":0.02,"symmetry":"auto"},{"bcs_shape":lambda r,s:s.get("bcs_shape")==[1,1],"symmetry_raw_bz":lambda r,s:s.get("symmetry")=="raw_bz","domain_current_bz":lambda r,s:s.get("domain")=="current_bz"},"current_bz","auto_resolves_raw_bz"),
run("R4-SMOKE-EFS-AFFINE",lambda:efs.compute_efs(affine,resolution=2,num_bands=1,grid_n=1,band_index=0,run_mode="compute",save=False,save_tmp=False,source_case="r4-smoke"),{"resolution":2,"num_bands":1,"grid_n":1,"band_index":0},{"freqs_shape":lambda r,s:s.get("freqs_shape")==[1,1],"domain_current_bz":lambda r,s:s.get("domain")=="current_bz"},"current_bz","no_c4_inference"),
]
out={"schema":"mephc.r4.production_smokes.v1","status":"PASS" if all(x["status"]=="PASS" for x in smokes) else "FAIL","required_smoke_ids":[x["id"] for x in smokes],"smokes":smokes,"created_at":datetime.now(timezone.utc).isoformat()}
(BUNDLE/"production_smokes.json").write_text(json.dumps(out,indent=2,default=str)+"\n",encoding="utf-8")
(BUNDLE/"logs"/"production_smokes.log").write_text("\n".join(log)+"\n",encoding="utf-8")
print("R4 production smokes",out["status"])
for x in smokes: print(x["id"],x["status"],x["duration_seconds"],x.get("error",""))
if out["status"]!="PASS": raise SystemExit(1)
