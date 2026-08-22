"""E7I.2D diagnostic-only MPB Gram-matrix runner."""
from __future__ import annotations
import contextlib, io, json, math, time
from pathlib import Path
import numpy as np
from meep import mpb
import meep as mp
from mephc.mpb_spectral_provider import _canonical_field, _spatial_shape
from mephc.mpb_reference_adapter import build_reference_mpb_adapter
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.valley_reference_geometry import build_triangular_reference_geometry

K=(2/3,0.0); RESOLUTIONS=(32,48,64); BANDS=4
POINTS={"corner_1":(K[0]-1/72,K[1]-1/72),"corner_2":(K[0]+1/72,K[1]-1/72),"corner_3":(K[0]+1/72,K[1]+1/72),"corner_4":(K[0]-1/72,K[1]+1/72),"center":K}

def _gram(fields, weights=None):
    x=np.asarray(fields,dtype=np.complex128)
    if weights is not None: x=np.sqrt(weights)[None,:,:,None]*x
    vectors=[]; norms=[]
    for band in range(x.shape[0]):
        v=x[band].reshape(-1); n=float(np.sqrt(np.vdot(v,v).real))
        vectors.append(v/n); norms.append(n)
    m=np.column_stack(vectors); g=m.conj().T@m; off=np.array(g,copy=True); np.fill_diagonal(off,0)
    return {"normalization_error":float(max(abs(float(np.vdot(v,v).real)-1) for v in m.T)),"max_off_diagonal":float(np.max(np.abs(off))),"band_2_3_overlap":float(abs(g[1,2])),"gram_diagonal":[float(g[i,i].real) for i in range(g.shape[0])],"bands":int(x.shape[0])}

def _solver(adapter,resolution,tolerance,q):
    lattice=adapter.geometry_lattice
    reciprocal=mp.cartesian_to_reciprocal(mp.Vector3(float(q[0]),float(q[1]),0),lattice)
    solver=mpb.ModeSolver(geometry=list(adapter.geometry),geometry_lattice=lattice,k_points=[reciprocal],resolution=resolution,num_bands=BANDS,default_material=adapter.background_material,tolerance=tolerance,deterministic=True,mesh_size=3)
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        solver.run_parity(mp.TE,False)
    shape=_spatial_shape(lattice,resolution)
    epsilon=np.asarray(solver.get_epsilon(),dtype=float).reshape(shape)
    e=[]; h=[]
    for band in range(1,BANDS+1):
        e.append(_canonical_field(solver.get_efield(band,bloch_phase=False),spatial_shape=shape,band=band))
        h.append(_canonical_field(solver.get_hfield(band,bloch_phase=False),spatial_shape=shape,band=band))
    e=np.stack(e); h=np.stack(h)
    native_names=[name for name in dir(solver) if "eigen" in name.lower()]
    native={"status":"UNAVAILABLE","public_attributes":native_names}
    candidate=getattr(solver,"eigenvectors",None)
    if candidate is not None:
        arr=np.asarray(candidate)
        if arr.ndim>=2 and arr.shape[0]>=BANDS:
            native={"status":"AVAILABLE_UNINTERPRETED","shape":list(arr.shape),"reason":"public array found but cross-band metric not justified"}
    return {"frequencies":[float(x) for x in np.asarray(solver.all_freqs)[0]],"h_only":_gram(h),"e_only":_gram(e,epsilon), "eh_combined":_gram(np.concatenate((np.sqrt(epsilon)[None,:,:,None]*e,h),axis=1)),"native":native}

def _point(adapter,res,tol,q):
    return _solver(adapter,res,tol,q)

def _endpoint(fr,label):
    adapter=build_reference_mpb_adapter(build_triangular_reference_geometry(fr),build_triangular_coordinate_preflight())
    data={"label":label,"adapter":adapter.to_dict(),"K":{},"plaquette_R48":{},"tolerance_probe_R48_K":{}}
    for res in RESOLUTIONS: data["K"][f"R{res}"]=_point(adapter,res,1e-7,K)
    for name,q in POINTS.items(): data["plaquette_R48"][name]=_point(adapter,48,1e-7,q)
    data["tolerance_probe_R48_K"]["tol_1e-7"]=_point(adapter,48,1e-7,K)
    data["tolerance_probe_R48_K"]["tol_1e-10"]=_point(adapter,48,1e-10,K)
    return data

def _classify(data):
    h=[]; eh=[]; byres=[]
    for endpoint in data.values():
        h.extend(endpoint["K"][f"R{r}"]["h_only"]["max_off_diagonal"] for r in RESOLUTIONS)
        eh.extend(endpoint["K"][f"R{r}"]["eh_combined"]["max_off_diagonal"] for r in RESOLUTIONS)
        byres.append(tuple(endpoint["K"][f"R{r}"]["eh_combined"]["max_off_diagonal"] for r in RESOLUTIONS))
    tol_delta=max(abs(x["tolerance_probe_R48_K"]["tol_1e-7"]["eh_combined"]["max_off_diagonal"]-x["tolerance_probe_R48_K"]["tol_1e-10"]["eh_combined"]["max_off_diagonal"]) for x in data.values())
    realspace_improves=all(row[2] < row[0] for row in byres)
    if max(h)<=1e-8 and min(eh)>1e-6 and realspace_improves and tol_delta<1e-6: return "E7I2D_REALSPACE_EH_QUADRATURE_LIMIT_SUPPORTED"
    if max(h)>1e-8 or tol_delta>=1e-6: return "E7I2D_H_SPACE_OR_EIGENSOLVER_ORTHOGONALITY_FAILURE"
    return "E7I2D_MIXED_OR_UNRESOLVED"

def main():
    start=time.time(); result={"schema":"e7i2d_orthogonality_diagnostic_v1","work_order":"E7I.2D","threshold_change":"FORBIDDEN","berry_values":"NOT_EXPOSED","main_unchanged":True}
    try:
        endpoints={"FR00":_endpoint(0.0,"FR00_exact_triangle"),"FR050":_endpoint(0.5,"FR050_exact_circle")}
        result["endpoints"]=endpoints
        result["native_eigenvector_gram"]="UNAVAILABLE_OR_UNINTERPRETED"
        result["classification"]=_classify(endpoints)
        result["recommended_next_action"]="Keep the fixed qualification gate; if further progress is authorized, separately audit MPB field/quadrature representation rather than changing thresholds."
        result["overall"]="E7I2D_REPORT_READY"
    except Exception as exc:
        result.update({"overall":"E7I2D_FAILED_CLEANLY","error_type":type(exc).__name__,"error":str(exc)})
    result["elapsed_seconds"]=time.time()-start
    out=Path(__file__).with_name("result.json"); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"overall":result["overall"],"classification":result.get("classification"),"error":result.get("error"),"elapsed_seconds":result["elapsed_seconds"]},sort_keys=True))
    if result["overall"]!="E7I2D_REPORT_READY": raise SystemExit(2)
if __name__=="__main__": main()
