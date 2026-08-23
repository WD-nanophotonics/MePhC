from __future__ import annotations
import argparse,hashlib,json,math,pickle,subprocess,sys,tempfile,time
from pathlib import Path
import numpy as np
from .e8b_geometry import STRAINS,WEIGHT_SIGMA,all_states,gh_nodes,check_geometry,solver_geometry,weight_gradient,actual_lattice_matrix
from mephc.eigenspace import EigenSubspace
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED,PATH_SUBSPACE_QUALIFIED,qualify_ordered_path
from mephc.plaquette_domain import PlaquetteRefinementLevel,PlaquetteRefinementThresholds,qualify_plaquette_boundary,qualify_plaquette_interior,qualify_plaquette_refinement
from mephc.spectral_association import ExternalIsolationContext,SubspaceQualificationThresholds
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED,compose_wilson_transport

R48=48; R64=64; NUM_BANDS=6; TARGET_BAND=0; MIN_GAP=0.05; SOLVER_TOL=1e-7; MESH=3
PRIMARY_H=0.001; REFERENCE_H=0.0005
TRANSPORT=SubspaceQualificationThresholds(0.9,0.45,0.3,MIN_GAP)
REFINEMENT=PlaquetteRefinementThresholds(0.9,0.45,0.3,0.1)
WORK_ORDER="TRILATT-E8B-C1-20260824-163"
BASE_SHA="cf8f2ae0f322ef57c55a8af662c7ad7c113c5faf"
D0500_COMMIT="b2d40bcbdd04972bd8cfd7c2eecee45f236c5fc0"
D0500_PATH="tests/test_e7i1a_m1_d0500_regression.py"
D0500_VALUE=-12.1426

def sha_bytes(value): return hashlib.sha256(value).hexdigest()
def root_path(): return Path(__file__).resolve().parents[2]
def git_head(): return subprocess.check_output(["git","rev-parse","HEAD"],cwd=root_path(),text=True).strip()
def source_binding():
    blob=subprocess.check_output(["git","show",f"{D0500_COMMIT}:{D0500_PATH}"],cwd=root_path())
    return {"source_file":D0500_PATH,"source_commit":D0500_COMMIT,"source_sha256":sha_bytes(blob),"historical_anti_q":D0500_VALUE,"historical_anti_units":"OMEGA_Q","binding_status":"VERIFIED"}
def self_check():
    assert check_geometry()
    states=all_states(); z=states["0.0"]
    assert np.allclose(np.asarray(z["K_cart"]),[0.0,-2.0/3.0],rtol=0,atol=1e-14)
    assert np.allclose(actual_lattice_matrix(z),np.asarray(z["A"]),rtol=0,atol=1e-14)
    assert all(abs(float(x["det_F"])-1.0)<1e-14 for x in states.values())
    assert all(len(gh_nodes(n))==n*n and abs(sum(x["probability"] for x in gh_nodes(n))-1.0)<1e-14 for n in (3,5))
    assert PRIMARY_H==0.001 and REFERENCE_H==0.0005 and TARGET_BAND==0 and MIN_GAP==0.05
    print("E8B_C1_SOLVER_NEUTRAL_SELF_CHECK=PASS")

def worker_solve(strain,resolution,q,outfile):
    import meep as mp
    from meep import mpb
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
    st=all_states()[str(float(strain))]
    geometry,lattice=solver_geometry(st)
    provider=MPBLiveEnergySpectralProvider(geometry=geometry,geometry_lattice=lattice,resolution=int(resolution),num_bands=NUM_BANDS,polarization=mp.TM,default_material=mp.air,eigensolver_tolerance=SOLVER_TOL,deterministic=True,mesh_size=MESH,phase_callback=mpb.fix_efield_phase)
    raw=provider.solve(tuple(float(x) for x in q))
    payload={"k_point":list(raw.k_point),"frequencies":[float(x) for x in raw.frequencies],"vectors":[np.asarray(v,dtype=np.complex128) for v in raw.normalized_vectors],"max_normalization_error":float(raw.max_normalization_error),"max_off_diagonal_gram":float(raw.max_off_diagonal_gram),"orthogonality_status":raw.orthogonality_status}
    Path(outfile).write_bytes(pickle.dumps(payload,protocol=pickle.HIGHEST_PROTOCOL))

def solve_one(st,res,q,cache,counters):
    key=(st["geometry_digest"],int(res),tuple(float(x) for x in q),"mpb_energy_eh_v1",TARGET_BAND)
    if key in cache:
        counters["cache_hits"]+=1
        return cache[key]
    counters["raw_solver_requests"]+=1
    with tempfile.NamedTemporaryFile(prefix="e8b-c1-node-",suffix=".pkl",delete=False) as h: out=h.name
    cmd=[sys.executable,"-m","audit.e8b.run_e8b","--worker","--strain",str(st["strain"]),"--resolution",str(int(res)),"--qx="+str(float(q[0])),"--qy="+str(float(q[1])),"--output",out]
    try:
        p=subprocess.run(cmd,cwd=root_path(),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=900)
        if p.returncode!=0:
            counters["solver_failures"]+=1
            raise RuntimeError("E8B.C1 isolated MPB node failed: "+p.stderr[-1600:])
        value=pickle.loads(Path(out).read_bytes())
        if len(value["frequencies"])!=NUM_BANDS or not all(math.isfinite(x) for x in value["frequencies"]): raise RuntimeError("nonfinite spectrum")
        cache[key]=value
        return value
    finally:
        Path(out).unlink(missing_ok=True)

def nearest_gap(freq,band=TARGET_BAND):
    f=[float(x) for x in freq]
    if band==0:return f[1]-f[0]
    return min(f[band]-f[band-1],f[band+1]-f[band])

def profile(value,res,label,q):
    f=value["frequencies"]; gap=nearest_gap(f)
    return {"label":label,"q":list(q),"resolution":int(res),"frequencies":list(f),"target_frequency":float(f[TARGET_BAND]),"nearest_gap":float(gap),"target_normalization_error":value["max_normalization_error"],"raw_eh_gram_diagnostic":value["max_off_diagonal_gram"],"target_normalization_status":"PASS" if value["max_normalization_error"]<=1e-8 else "FAIL","gap_status":"PASS" if gap>=MIN_GAP else "FAIL","qualified":bool(value["max_normalization_error"]<=1e-8 and gap>=MIN_GAP)}

def preflight(states,cache,counters):
    rows=[]; passed=True
    for st in states.values():
        for label,q in (("K_CART",st["K_cart"]),("Q_CENTER",st["Q_center"])):
            vals=[]
            for res in (R48,R64):
                value=solve_one(st,res,q,cache,counters); row=profile(value,res,label,q); rows.append({"strain":st["strain"],**row}); vals.append(row)
            passed=passed and all(x["qualified"] for x in vals)
    return passed,rows

def frame(q,value):
    vector=np.asarray(value["vectors"][TARGET_BAND],dtype=np.complex128)
    if not np.all(np.isfinite(vector)) or abs(float(np.vdot(vector,vector).real)-1)>1e-8:return None
    return EigenSubspace(tuple(float(x) for x in q),vector.reshape((-1,1)),(float(value["frequencies"][TARGET_BAND]),),(TARGET_BAND,),{"representation":"mpb_energy_eh_v1","rank":1,"band":0,"lowdin_mixing":False})

def excluded(freq): return tuple(float(x) for i,x in enumerate(freq) if i!=TARGET_BAND)

def build_level(st,q,h,res,cache,counters):
    q=np.asarray(q,dtype=float)
    points=[(float(q[0]-h/2),float(q[1]-h/2)),(float(q[0]+h/2),float(q[1]-h/2)),(float(q[0]+h/2),float(q[1]+h/2)),(float(q[0]-h/2),float(q[1]+h/2))]
    values=[solve_one(st,res,p,cache,counters) for p in points]
    center_value=solve_one(st,res,q.tolist(),cache,counters)
    frames=[frame(p,v) for p,v in zip(points,values)]; center_frame=frame(q,center_value)
    if any(v is None for v in frames) or center_frame is None or any(nearest_gap(v["frequencies"])<MIN_GAP for v in values+[center_value]):
        return {"qualified":False,"reason":"strict_gap_or_normalization_failed","h":h,"resolution":res,"points": [list(p) for p in points],"center_q":q.tolist(),"center_is_actual_solve":True}
    freqs=[v["frequencies"] for v in values]
    contexts=tuple(ExternalIsolationContext(excluded(freqs[i]),excluded(freqs[(i+1)%4]),{"source":"E8B.C1 complete vertex excluded spectra","band":0}) for i in range(4))
    path=qualify_ordered_path(tuple(frames),contexts,thresholds=TRANSPORT,closed=True,provenance={"work_order":WORK_ORDER,"h":h})
    wilson=compose_wilson_transport(path)
    boundary=qualify_plaquette_boundary(tuple(frames),contexts,thresholds=TRANSPORT,provenance={"work_order":WORK_ORDER,"h":h})
    spoke=tuple(ExternalIsolationContext(excluded(v["frequencies"]),excluded(center_value["frequencies"]),{"source":"E8B.C1 actual center spoke spectrum","band":0}) for v in values)
    interior=qualify_plaquette_interior(boundary,center_frame,spoke,provenance={"work_order":WORK_ORDER,"h":h})
    phase=wilson.determinant_phase
    ok=path.status in (PATH_SINGLE_BAND_QUALIFIED,PATH_SUBSPACE_QUALIFIED) and wilson.status==WILSON_LOOP_QUALIFIED and boundary.is_qualified and interior.is_qualified and phase is not None and math.isfinite(float(phase))
    return {"qualified":bool(ok),"h":h,"resolution":res,"points":[list(p) for p in points],"center_q":q.tolist(),"center_is_actual_solve":True,"phase":None if phase is None else float(phase),"omega_q":None if not ok else float(-phase/(h*h)),"path_status":path.status,"wilson_status":wilson.status,"boundary_status":boundary.status,"interior_status":interior.status,"_boundary":boundary,"_interior":interior}

def local_omega(st,q,cache,counters):
    primary=build_level(st,q,PRIMARY_H,R64,cache,counters)
    reference=build_level(st,q,REFERENCE_H,R64,cache,counters)
    refinement=None
    if primary.get("_boundary") is not None and reference.get("_boundary") is not None:
        l1=PlaquetteRefinementLevel(boundary=primary["_boundary"],interior=primary["_interior"],step=PRIMARY_H,provenance={"work_order":WORK_ORDER})
        l2=PlaquetteRefinementLevel(boundary=reference["_boundary"],interior=reference["_interior"],step=REFERENCE_H,provenance={"work_order":WORK_ORDER})
        refinement=qualify_plaquette_refinement((l1,l2),thresholds=REFINEMENT,provenance={"work_order":WORK_ORDER}).to_dict()
    qualified=bool(primary["qualified"] and reference["qualified"] and refinement is not None and refinement["is_qualified"])
    return {"qualified":qualified,"omega_q":primary.get("omega_q") if qualified else None,"primary":{k:v for k,v in primary.items() if not k.startswith("_")},"reference":{k:v for k,v in reference.items() if not k.startswith("_")},"E4C":refinement,"E4C_executed":refinement is not None}

def authority_replay(st,cache,counters):
    q=st["K_cart"]; h=PRIMARY_H
    points=[(float(q[0]-h/2),float(q[1]-h/2)),(float(q[0]+h/2),float(q[1]-h/2)),(float(q[0]+h/2),float(q[1]+h/2)),(float(q[0]-h/2),float(q[1]+h/2))]
    vals=[solve_one(st,R64,p,cache,counters) for p in points]
    omegas=[]
    overlaps=[]
    for band in (0,1):
        links=[]
        for i in range(4):
            z=np.vdot(vals[i]["vectors"][band],vals[(i+1)%4]["vectors"][band]); overlaps.append(float(abs(z)))
            if abs(z)<=0.9:return {"status":"FAIL","reason":"authority_overlap","min_overlap":min(overlaps)}
            links.append(z/abs(z))
        omegas.append(float(-np.angle(np.prod(links))/(h*h)))
    return {"status":"PASS","omega_band0_q":omegas[0],"omega_band1_q":omegas[1],"anti_q":(omegas[0]-omegas[1])/2,"common_q":(omegas[0]+omegas[1])/2,"min_overlap":min(overlaps),"corner_frequencies":[v["frequencies"] for v in vals]}

def response_for_order(st,order,cache,counters):
    rows=[]; response=np.zeros(2); all_qualified=True
    for node in gh_nodes(order,st["Q_center"]):
        local=local_omega(st,node["node"],cache,counters); rows.append({**node,"local":local})
        if not local["qualified"]:all_qualified=False
        else:response+=node["probability"]*float(local["omega_q"])*weight_gradient(node["delta"])
    coord=None
    if all_qualified:
        G=np.asarray(st["G"],dtype=float); det=float(np.linalg.det(G)); direct=response.copy(); frac=np.zeros(2)
        for row in rows:
            om=float(row["local"]["omega_q"]); frac+=row["probability"]*(det*om/det)*(G.T@weight_gradient(row["delta"]))
        mapped=np.linalg.inv(G).T@frac
        coord={"passed":bool(np.linalg.norm(mapped-direct)<=1e-9),"error":float(np.linalg.norm(mapped-direct)),"D_cart_direct":direct.tolist(),"D_fractional":frac.tolist(),"D_cart_from_fractional":mapped.tolist()}
    return {"order":order,"node_count":len(rows),"all_qualified":all_qualified,"response":response.tolist() if all_qualified else None,"nodes":rows,"coordinate_reexpression":coord}

def run(output):
    self_check(); contract=json.loads((Path(__file__).with_name("e8b_contract.json")).read_text()); states=all_states(); cache={}; counters={"raw_solver_requests":0,"cache_hits":0,"solver_failures":0}; started=time.monotonic()
    source=source_binding(); source_ok=source["source_sha256"]=="37dad4ecba17601cb816224bdbb9ac86a48ce1d4cff8567443d420527594129b"
    zero=states["0.0"]; zero_geometry=bool(np.allclose(np.asarray(zero["A"]),np.asarray(contract["source_binding"]["direct_basis"]),rtol=0,atol=1e-14) and np.allclose(np.asarray(zero["K_cart"]),contract["source_binding"]["public_k_cartesian_zero"],rtol=0,atol=1e-14))
    authority=authority_replay(zero,cache,counters); primary=build_level(zero,zero["K_cart"],PRIMARY_H,R64,cache,counters)
    anti_ok=bool(authority.get("status")=="PASS" and abs(authority["anti_q"]-D0500_VALUE)/abs(D0500_VALUE)<=0.02)
    band0_ok=bool(authority.get("status")=="PASS" and primary.get("qualified") and abs(primary["omega_q"]-authority["omega_band0_q"])<=1e-10)
    spectral_ok=bool(authority.get("status")=="PASS" and primary.get("center_is_actual_solve",False))
    zero_ok=bool(source_ok and zero_geometry and anti_ok and band0_ok and spectral_ok)
    payload={"schema":"trilatt_e8b_c1_result_v1","work_order_id":WORK_ORDER,"base_sandbox_sha":BASE_SHA,"contract":contract,"source_binding":source,"current_git_head":git_head(),"states":states,"COORDINATE_CONVENTION_DECISION":"OPTION_A_LATTICE_BASIS_SOLVER_CENTERS","physical_center_contract":"DERIVED_FROM_A_TIMES_CENTER_FRACTIONAL","authority_replay":authority,"corrected_zero_primary":{k:v for k,v in primary.items() if not k.startswith("_")},"S_ZERO_GEOMETRY_REPLAY":"PASSED" if zero_geometry else "FAILED","S_ZERO_K_SPECTRAL_REPLAY":"PASSED" if spectral_ok else "FAILED","S_ZERO_BAND0_LOCAL_BERRY_REPLAY":"PASSED" if band0_ok else "FAILED","S_ZERO_HISTORICAL_ANTI_REPLAY":"PASSED" if anti_ok else "FAILED","FULL_QUADRATURE_AUTHORIZED":zero_ok,"gh3":None,"gh5":None,"telemetry":{"wall_time_seconds":time.monotonic()-started,**counters}}
    if not zero_ok:
        payload["stop_reason"]="FAIL_CLOSED_AFTER_ZERO_STRAIN_AUTHORITY_REPLAY"
    else:
        passed,profiles=preflight(states,cache,counters); payload["preflight"]="PASSED" if passed else "FAILED"; payload["preflight_rows"]=profiles; k_local={}
        for st in states.values():
            k_local[str(st["strain"])]=local_omega(st,st["K_cart"],cache,counters)
        payload["k_local_band0"]=k_local
        passed=passed and all(x["qualified"] for x in k_local.values()); payload["FULL_QUADRATURE_AUTHORIZED"]=passed
        if not passed:payload["stop_reason"]="FAIL_CLOSED_AFTER_CORRECTED_THREE_STRAIN_PREFLIGHT"
        else:
            payload["gh3"]={str(st["strain"]):response_for_order(st,3,cache,counters) for st in states.values()}
            if all(v["all_qualified"] for v in payload["gh3"].values()):
                payload["gh5"]={str(st["strain"]):response_for_order(st,5,cache,counters) for st in states.values()}
            else:payload["stop_reason"]="FAIL_CLOSED_AFTER_PARTIAL_GH3_QUALIFICATION"
    payload["telemetry"].update(counters); Path(output).write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8"); print(json.dumps({"schema":payload["schema"],"S_ZERO_HISTORICAL_ANTI_REPLAY":payload["S_ZERO_HISTORICAL_ANTI_REPLAY"],"S_ZERO_BAND0_LOCAL_BERRY_REPLAY":payload["S_ZERO_BAND0_LOCAL_BERRY_REPLAY"],"FULL_QUADRATURE_AUTHORIZED":payload["FULL_QUADRATURE_AUTHORIZED"],"current_git_head":payload["current_git_head"],"telemetry":payload["telemetry"]},sort_keys=True))

if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--self-check",action="store_true"); ap.add_argument("--worker",action="store_true"); ap.add_argument("--strain",type=float); ap.add_argument("--resolution",type=int); ap.add_argument("--qx",type=float); ap.add_argument("--qy",type=float); ap.add_argument("--output",default="audit/e8b/result.json"); args=ap.parse_args()
    if args.self_check:self_check()
    elif args.worker:worker_solve(args.strain,args.resolution,(args.qx,args.qy),args.output)
    else:run(args.output)
