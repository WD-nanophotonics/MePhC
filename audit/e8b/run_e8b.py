from __future__ import annotations
import argparse,hashlib,json,math,os,pickle,subprocess,sys,tempfile,time
from pathlib import Path
import numpy as np
from .e8b_geometry import STRAINS,WEIGHT_SIGMA,all_states,gh_nodes,check_geometry,solver_geometry,weight_gradient
from mephc.eigenspace import EigenSubspace
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED,PATH_SUBSPACE_QUALIFIED,qualify_ordered_path
from mephc.plaquette_domain import PlaquetteRefinementLevel,PlaquetteRefinementThresholds,qualify_plaquette_boundary,qualify_plaquette_interior,qualify_plaquette_refinement
from mephc.spectral_association import ExternalIsolationContext,SubspaceQualificationThresholds
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED,compose_wilson_transport

R48=48; R64=64; NUM_BANDS=6; TARGET_BAND=0; MIN_GAP=0.05; SOLVER_TOL=1e-7; MESH=3; H=0.001
TRANSPORT=SubspaceQualificationThresholds(0.9,0.45,0.3,MIN_GAP)
REFINEMENT=PlaquetteRefinementThresholds(0.9,0.45,0.3,0.1)
WORK_ORDER="TRILATT-E8B-20260824-162"
D0500_COMMIT="b2d40bcbdd04972bd8cfd7c2eecee45f236c5fc0"
D0500_PATH="tests/test_e7i1a_m1_d0500_regression.py"
D0500_VALUE=-12.1426

def sha_bytes(value): return hashlib.sha256(value).hexdigest()
def sha_json(value): return sha_bytes(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
def root_path(): return Path(__file__).resolve().parents[2]
def git_head(): return subprocess.check_output(["git","rev-parse","HEAD"],cwd=root_path(),text=True).strip()
def source_binding():
    blob=subprocess.check_output(["git","show",f"{D0500_COMMIT}:{D0500_PATH}"],cwd=root_path())
    return {"source_file":D0500_PATH,"source_commit":D0500_COMMIT,"source_sha256":sha_bytes(blob),"historical_local_berry_value":D0500_VALUE,"historical_local_berry_units":"OMEGA_Q","binding_status":"VERIFIED_WITH_COORDINATE_CONVENTION"}

def self_check():
    assert check_geometry()
    states=all_states()
    z=states["0.0"]
    assert np.allclose(np.asarray(z["K_cart"]),[0.0,-2.0/3.0],rtol=0,atol=1e-14)
    assert all(abs(float(x["det_F"])-1.0)<1e-14 for x in states.values())
    for n in (3,5):
        assert abs(sum(x["probability"] for x in gh_nodes(n))-1.0)<1e-14
        assert len(gh_nodes(n))==n*n
    assert all(np.asarray(x["geometry_digest"]).shape==() for x in states.values())
    assert H>0 and MIN_GAP==0.05 and TARGET_BAND==0
    print("E8B_SOLVER_NEUTRAL_SELF_CHECK=PASS")

def worker_solve(strain,resolution,q,outfile):
    import meep as mp
    from meep import mpb
    from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
    st=all_states()[str(float(strain))]
    geometry,lattice=solver_geometry(st)
    provider=MPBLiveEnergySpectralProvider(geometry=geometry,geometry_lattice=lattice,resolution=int(resolution),num_bands=NUM_BANDS,polarization=mp.TM,default_material=mp.air,eigensolver_tolerance=SOLVER_TOL,deterministic=True,mesh_size=MESH,phase_callback=mpb.fix_efield_phase)
    raw=provider.solve(tuple(float(x) for x in q))
    payload={"k_point":list(raw.k_point),"frequencies":[float(x) for x in raw.frequencies],"vectors":[np.asarray(v,dtype=np.complex128) for v in raw.normalized_vectors],"max_normalization_error":float(raw.max_normalization_error),"max_off_diagonal_gram":float(raw.max_off_diagonal_gram),"orthogonality_status":raw.orthogonality_status,"gram_matrix":np.asarray(raw.gram_matrix)}
    Path(outfile).write_bytes(pickle.dumps(payload,protocol=pickle.HIGHEST_PROTOCOL))

def solve_one(st,res,q,cache,counters):
    key=(st["geometry_digest"],int(res),tuple(float(x) for x in q),"mpb_energy_eh_v1",TARGET_BAND)
    if key in cache:
        counters["cache_hits"]+=1
        return cache[key]
    counters["raw_solver_requests"]+=1
    with tempfile.NamedTemporaryFile(prefix="e8b-node-",suffix=".pkl",delete=False) as h: out=h.name
    cmd=[sys.executable,"-m","audit.e8b.run_e8b","--worker","--strain",str(st["strain"]),"--resolution",str(int(res)),"--qx",str(float(q[0])),"--qy",str(float(q[1])),"--output",out]
    try:
        p=subprocess.run(cmd,cwd=root_path(),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=900)
        if p.returncode!=0:
            counters["solver_failures"]+=1
            raise RuntimeError("E8B isolated MPB node failed: "+p.stderr[-1200:])
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
    f=value["frequencies"]
    return {"label":label,"q":list(q),"resolution":int(res),"frequencies":list(f),"target_frequency":float(f[TARGET_BAND]),"nearest_gap":float(nearest_gap(f)),"target_normalization_error":value["max_normalization_error"],"raw_eh_gram_diagnostic":value["max_off_diagonal_gram"],"normalization_status":"PASS" if value["max_normalization_error"]<=1e-8 else "FAIL","gap_status":"PASS" if nearest_gap(f)>=MIN_GAP else "FAIL","qualified":bool(value["max_normalization_error"]<=1e-8 and nearest_gap(f)>=MIN_GAP)}

def preflight(states,cache,counters):
    rows=[]; passed=True
    for st in states.values():
        for label,q in (("K_CART",st["K_cart"]),("Q_CENTER",st["Q_center"])):
            vals=[]
            for res in (R48,R64):
                value=solve_one(st,res,q,cache,counters)
                row=profile(value,res,label,q); rows.append({"strain":st["strain"],**row}); vals.append(row)
            ok=all(x["qualified"] for x in vals)
            passed=passed and ok
    return passed,rows

def frame(q,value):
    vector=np.asarray(value["vectors"][TARGET_BAND],dtype=np.complex128)
    if not np.all(np.isfinite(vector)) or abs(float(np.vdot(vector,vector).real)-1)>1e-8: return None
    return EigenSubspace(tuple(float(x) for x in q),vector.reshape((-1,1)),(float(value["frequencies"][TARGET_BAND]),),(TARGET_BAND,),{"representation":"mpb_energy_eh_v1","rank":1,"band":0,"lowdin_mixing":False})

def excluded(freq):
    return tuple(float(x) for i,x in enumerate(freq) if i!=TARGET_BAND)

def qualify_local(points,values):
    if any(nearest_gap(v["frequencies"])<MIN_GAP for v in values): return None
    frames=[frame(q,v) for q,v in zip(points,values)]
    if any(x is None for x in frames): return None
    freqs=[v["frequencies"] for v in values]
    contexts=tuple(ExternalIsolationContext(excluded(freqs[i]),excluded(freqs[(i+1)%4]),{"source":"E8B strict rank1 local"}) for i in range(4))
    path=qualify_ordered_path(tuple(frames),contexts,thresholds=TRANSPORT,closed=True,provenance={"work_order":WORK_ORDER})
    wilson=compose_wilson_transport(path)
    boundary=qualify_plaquette_boundary(tuple(frames),contexts,thresholds=TRANSPORT,provenance={"work_order":WORK_ORDER})
    center_q=np.mean(np.asarray(points),axis=0)
    center_value={"frequencies":values[0]["frequencies"],"vectors":values[0]["vectors"]}
    spoke=tuple(ExternalIsolationContext(excluded(v["frequencies"]),excluded(center_value["frequencies"]),{"source":"E8B center spoke"}) for v in values)
    center_frame=frame(center_q,center_value)
    interior=qualify_plaquette_interior(boundary,center_frame,spoke,provenance={"work_order":WORK_ORDER})
    phase=wilson.determinant_phase
    ok=path.status in (PATH_SINGLE_BAND_QUALIFIED,PATH_SUBSPACE_QUALIFIED) and wilson.status==WILSON_LOOP_QUALIFIED and boundary.is_qualified and interior.is_qualified and phase is not None and math.isfinite(float(phase))
    return {"qualified":bool(ok),"phase":None if phase is None else float(phase),"omega_q":None if not ok else float(-phase/(H*H)),"path_status":path.status,"wilson_status":wilson.status,"boundary_status":boundary.status,"interior_status":interior.status}

def local_omega(st,q,cache,counters):
    pts=[(float(q[0]-H/2),float(q[1]-H/2)),(float(q[0]+H/2),float(q[1]-H/2)),(float(q[0]+H/2),float(q[1]+H/2)),(float(q[0]-H/2),float(q[1]+H/2))]
    values=[solve_one(st,R64,p,cache,counters) for p in pts]
    qualified=qualify_local(pts,values)
    if qualified is None: return {"qualified":False,"reason":"strict_local_rank1_gate_failed"}
    return qualified

def historical_local_replay(st,cache,counters):
    q=st["K_cart"]
    pts=[(q[0]-H/2,q[1]-H/2),(q[0]+H/2,q[1]-H/2),(q[0]+H/2,q[1]+H/2),(q[0]-H/2,q[1]+H/2)]
    vals=[solve_one(st,R64,p,cache,counters) for p in pts]
    phases=[]
    for band in (0,1):
        links=[]
        for i in range(4):
            z=np.vdot(vals[i]["vectors"][band],vals[(i+1)%4]["vectors"][band])
            if abs(z)<=0.9: return {"status":"FAIL","reason":"plaquette_overlap_below_0.9"}
            links.append(z/abs(z))
        phases.append(float(np.angle(np.prod(links))))
    anti=(float(-phases[0]/(H*H))-float(-phases[1]/(H*H)))/2
    return {"status":"PASS" if abs(anti-D0500_VALUE)/abs(D0500_VALUE)<=0.02 else "FAIL","anti_omega_q":anti,"reference":D0500_VALUE,"relative_error":abs(anti-D0500_VALUE)/abs(D0500_VALUE)}

def response_for_order(st,order,cache,counters):
    rows=[]; response=np.zeros(2); all_qualified=True
    for node in gh_nodes(order,st["Q_center"]):
        local=local_omega(st,node["node"],cache,counters)
        row={**node,"local":local}
        rows.append(row)
        if not local["qualified"]:
            all_qualified=False
        else:
            response+=node["probability"]*float(local["omega_q"])*weight_gradient(node["delta"])
    coord=None
    if all_qualified:
        G=np.asarray(st["G"],dtype=float); det=float(np.linalg.det(G)); direct=response.copy(); frac=np.zeros(2)
        for node in rows:
            omega=float(node["local"]["omega_q"]); frac+=node["probability"]*(det*omega/det)*(G.T@weight_gradient(node["delta"]))
        mapped=np.linalg.inv(G).T@frac
        coord={"passed":bool(np.linalg.norm(mapped-direct)<=1e-9),"error":float(np.linalg.norm(mapped-direct)),"D_cart_direct":direct.tolist(),"D_fractional":frac.tolist(),"D_cart_from_fractional":mapped.tolist()}
    return {"order":order,"node_count":len(rows),"all_qualified":all_qualified,"response":response.tolist() if all_qualified else None,"nodes":rows,"coordinate_reexpression":coord}

def run(output):
    self_check()
    contract=json.loads((Path(__file__).with_name("e8b_contract.json")).read_text())
    source=source_binding(); states=all_states(); cache={}; counters={"raw_solver_requests":0,"cache_hits":0,"solver_failures":0}
    started=time.monotonic()
    source_ok=source["source_sha256"]==sha_bytes(subprocess.check_output(["git","show",f"{D0500_COMMIT}:{D0500_PATH}"],cwd=root_path()))
    zero=states["0.0"]
    zero_geometry=bool(np.allclose(np.asarray(zero["A"]),np.asarray(contract["source_binding"]["direct_basis"]),rtol=0,atol=1e-14) and np.allclose(np.asarray(zero["K_cart"]),contract["source_binding"]["public_k_cartesian_zero"],rtol=0,atol=1e-14))
    passed,profiles=preflight(states,cache,counters)
    spectral_replay=bool(source_ok and zero_geometry and any(x["strain"]==0.0 and x["label"]=="K_CART" and x["resolution"]==R48 and x["qualified"] for x in profiles))
    local=historical_local_replay(zero,cache,counters)
    local_replay=local["status"]=="PASS"
    full=bool(source_ok and zero_geometry and spectral_replay and local_replay and passed)
    payload={"schema":"trilatt_e8b_result_v1","work_order_id":WORK_ORDER,"source_binding":source,"contract":contract,"current_git_head":git_head(),"states":states,"source_binding_verified":source_ok,"S_ZERO_GEOMETRY_REPLAY":"PASSED" if zero_geometry else "FAILED","S_ZERO_K_SPECTRAL_REPLAY":"PASSED" if spectral_replay else "FAILED","S_ZERO_LOCAL_BERRY_REPLAY":"PASSED" if local_replay else "FAILED","zero_local_replay":local,"preflight":"PASSED" if passed else "FAILED","preflight_rows":profiles,"FULL_QUADRATURE_AUTHORIZED":full,"gh3":None,"gh5":None,"telemetry":{"wall_time_seconds":time.monotonic()-started,**counters}}
    if full:
        for order in (3,5):
            values={str(st["strain"]):response_for_order(st,order,cache,counters) for st in states.values()}
            if order==3: payload["gh3"]=values
            else: payload["gh5"]=values
            if not all(v["all_qualified"] for v in values.values()): break
        payload["telemetry"].update(counters)
    else:
        payload["stop_reason"]="FAIL_CLOSED_BEFORE_GH"
    Path(output).write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"schema":payload["schema"],"preflight":payload["preflight"],"FULL_QUADRATURE_AUTHORIZED":payload["FULL_QUADRATURE_AUTHORIZED"],"current_git_head":payload["current_git_head"],"telemetry":payload["telemetry"]},sort_keys=True))

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-check",action="store_true")
    ap.add_argument("--worker",action="store_true")
    ap.add_argument("--strain",type=float)
    ap.add_argument("--resolution",type=int)
    ap.add_argument("--qx",type=float)
    ap.add_argument("--qy",type=float)
    ap.add_argument("--output",default="audit/e8b/result.json")
    args=ap.parse_args()
    if args.self_check:self_check()
    elif args.worker:worker_solve(args.strain,args.resolution,(args.qx,args.qy),args.output)
    else:run(args.output)
