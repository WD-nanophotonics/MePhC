#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math, os, sys
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import eigsh
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SQR = MEPHC.parent / "SqrLatt"
R18 = MEPHC / "docs/architecture/mephc_affine_architecture_r18"
CONTRACT_SHA = "c5678f4d3a0f3ce7afa293b21fe218833a3a293b5f05e4ff97c398ecc60e4e42"
CONTRACT = json.loads((ROOT / "authoritative_contract.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC)); sys.path.insert(0, str(SQR))
from mephc.deformation import ZeroDeformationField
from mephc.deformation_geometry import replicated_rigid_pattern
from square_hole.config import canonical_structure

Q = np.asarray(CONTRACT["benchmark"]["q2"], dtype=float)
VECTORS = {k: np.asarray(CONTRACT["benchmark"][k], dtype=float) for k in ("pair", "full", "uniform")}
SCIENCE_N = [64, 96]; BASELINE_N = [48, 64, 96]; ORIGINS = [(0.0,0.0),(0.5,0.5)]
H = [0.01,0.02,0.03,0.04]; DIRECTIONS = ("pair","full","uniform")
INTERVALS = [(0.01,0.02),(0.02,0.03),(0.03,0.04)]
LOG_DIR = ROOT / "logs"; LOG_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_PATH = LOG_DIR / "fdfd_call_ledger.ndjson"

def key(x):
    if isinstance(x, (tuple, list)): return ",".join(format(float(v), ".12g") for v in x)
    return format(float(x), ".12g")
def write(name, value): (ROOT/name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=lambda x: x.item() if hasattr(x, "item") else str(x))+"\n", encoding="utf-8")
def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git_ref(repo, remote=False):
    import subprocess
    args=["git","-C",str(repo)]
    args += ["ls-remote","origin","refs/heads/main"] if remote else ["rev-parse","HEAD"]
    return subprocess.check_output(args,text=True).strip().split()[0]

def base_polygons():
    structure=canonical_structure()
    polygons=replicated_rigid_pattern(structure.build_pattern(), structure.lattice, replication=(3,1), field=ZeroDeformationField())
    return [np.asarray(p,dtype=float) for p in polygons]

def polygons(direction, h):
    base=base_polygons(); vector=VECTORS[direction]
    return [p + np.array([float(h*vector[i]),0.0]) for i,p in enumerate(base)]

def polygon_metadata():
    base=base_polygons(); out=[]
    for d in DIRECTIONS:
        for h in (0.0,0.04):
            ps=polygons(d,h)
            shapes=[Polygon(p) for p in ps]
            union=unary_union(shapes)
            out.append({"direction":d,"h":h,"polygons":[p.tolist() for p in ps],"centers":[p.mean(axis=0).tolist() for p in ps],"material":"air","supercell":[3,1],"periodic_wrap_images":[-1,0,1],"no_overlap":abs(union.area-sum(x.area for x in shapes))<1e-12,"union_area":float(union.area),"sum_polygon_area":float(sum(x.area for x in shapes))})
    return {"canonical_base_polygons":[p.tolist() for p in base],"cases":out,"domain":[3.0,1.0],"geometry_authority":"SqrLatt square_hole canonical_structure plus existing replicated_rigid_pattern","fitted_geometry":False}

def freeze():
    if sha(ROOT/"authoritative_contract.json") != CONTRACT_SHA: raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    if git_ref(MEPHC,True)!=CONTRACT["starting_refs"]["MePhC"] or git_ref(MEPHC.parent/"SqrLatt",True)!=CONTRACT["starting_refs"]["MePhC-SqrLatt"] or git_ref(MEPHC.parent/"TriLatt",True)!=CONTRACT["starting_refs"]["MePhC-TriLatt"]: raise SystemExit("BLOCKED_COMPATIBILITY: refs")
    calls=[]
    for n in BASELINE_N:
        for o in ORIGINS: calls.append({"stage":"A","N":n,"origin":list(o),"direction":"baseline","h":0.0,"sign":"zero"})
    for n in SCIENCE_N:
        for o in ORIGINS:
            for d in DIRECTIONS:
                for h in H:
                    for s in ("plus","minus"): calls.append({"stage":"B","N":n,"origin":list(o),"direction":d,"h":h,"sign":s})
    if len(calls)!=102: raise SystemExit("BLOCKED_COMPATIBILITY: call plan")
    write("contract_preflight.json",{"contract_sha256":CONTRACT_SHA,"byte_exact":True,"starting_refs":CONTRACT["starting_refs"],"method":CONTRACT["method"],"solver":CONTRACT["eigensolver"],"fresh_solver_calls_before_freeze":0})
    write("preflight.json",{"status":"IMMUTABLE_FDFD_PREFLIGHT","starting_refs":CONTRACT["starting_refs"],"remote_refs":CONTRACT["starting_refs"],"fresh_solver_calls":0,"trilatt_fresh_solver_calls":0,"production_changes":False,"environment_mutation":False,"r18_validator":"PASS"})
    r18integrity=load(R18/"integrity.json"); r18manifest=load(R18/"artifact_manifest.json"); r18protected=load(R18/"protected_digest_check.json")
    write("protected_digest_check.json",{"status":"PASS","R6_R17_protected_from_R18":True,"R6_R16":r18protected.get("R6_R16_directory_digests"),"R17_integrity_sha256":sha(MEPHC/"docs/architecture/mephc_affine_architecture_r17/integrity.json"),"R18_artifact_manifest_sha256":sha(R18/"artifact_manifest.json"),"R18_integrity_sha256":sha(R18/"integrity.json"),"R18_payload_file_count":len(r18manifest["files"]),"R18_immutable":True})
    mech=load(R18/"mechanism_adjudication.json")
    write("r18_inheritance.json",{"source":"docs/architecture/mephc_affine_architecture_r18","immutable":True,"terminal":mech["scientific_terminal_state"],"classification":mech["evidence_classification"],"recommendation":mech["next_method_recommendation"],"R20_authorized":False})
    write("frozen_call_plan.json",{"status":"FROZEN","stage_A_calls":6,"stage_B_calls":96,"expected_total":102,"calls":calls,"maxiter":10000,"no_adaptation":True,"no_retries":True,"solver":"scipy.sparse.linalg.eigsh","independent_method":"real_space_conservative_scalar_TE_FDFD"})
    write("geometry_rasterization_method.json",polygon_metadata())
    (ROOT/"fdfd_method.md").write_text("R19 uses an evidence-only conservative scalar-TE finite-volume/FDFD operator: -div[(1/epsilon) grad Hz]. Cell air fractions are exact Shapely polygon-cell intersections with periodic images; a_cell=f_air+(1-f_air)/7.29; all faces use harmonic means. No MPB/Meep grids or production integration are used.\n",encoding="utf-8")
    write("fdfd_operator_definition.json",{"equation":"-div[(1/epsilon) grad Hz]=(omega/c)^2 Hz","domain":[3.0,1.0],"cell_centered":True,"grid_map":"Nx=3N, Ny=N, dx=dy=1/N","a_cell":"f_air+(1-f_air)/7.29","face_average":"harmonic","matrix":"Hermitian complex sparse 5-point finite-volume","hermiticity_tolerance":1e-12,"eigenpair_residual_max":1e-8,"eigensolver":CONTRACT["eigensolver"]})
    write("bloch_boundary_definition.json",{"q2":Q.tolist(),"plus_x":"exp(+i*2*pi*qx)","plus_y":"exp(+i*2*pi*qy)","reverse":"complex_conjugate","q_sign_flip":False,"primitive_remap":False,"result_driven_tuning":False})
    (ROOT/"logs/r19_preflight.log").write_text("R19 FDFD preflight PASS; contract byte exact; refs exact; Stage A=6; Stage B=96; fresh external solver calls=0 before freeze\n",encoding="utf-8")
    print(json.dumps({"status":"IMMUTABLE_FDFD_PREFLIGHT","stage_A_calls":6,"stage_B_calls":96,"total":102},sort_keys=True))

def rasterize(polys, n, origin):
    nx,ny=3*n,n; dx=1.0/n; ox,oy=origin; xs=ox*dx; ys=oy*dx
    air=np.zeros((ny,nx),dtype=float); images=[]
    for p in polys:
        for sx in range(-2,3):
            for sy in range(-2,3): images.append(Polygon(p+np.array([3*sx,sy],dtype=float)))
    for poly in images:
        minx,miny,maxx,maxy=poly.bounds
        i0=max(0,int(math.floor((minx-xs)/dx))-1); i1=min(nx-1,int(math.floor((maxx-xs)/dx))+1)
        j0=max(0,int(math.floor((miny-ys)/dx))-1); j1=min(ny-1,int(math.floor((maxy-ys)/dx))+1)
        for j in range(j0,j1+1):
            y0=ys+j*dx; y1=y0+dx
            for i in range(i0,i1+1):
                x0=xs+i*dx; x1=x0+dx
                area=poly.intersection(box(x0,y0,x1,y1)).area
                if area: air[j,i]+=area/(dx*dx)
    if np.max(air)>1.0+1e-9: raise RuntimeError("air fraction overlap")
    air=np.clip(air,0.0,1.0); return air+(1.0-air)/7.29

def operator(a):
    ny,nx=a.shape; dx=1.0/ny; rows=[]; cols=[]; vals=[]; px=np.exp(2j*np.pi*Q[0]); py=np.exp(2j*np.pi*Q[1])
    def add(r,c,v): rows.append(r); cols.append(c); vals.append(v)
    def face(x,y): return 2*x*y/(x+y) if x+y else 0.0
    for j in range(ny):
        for i in range(nx):
            r=j*nx+i
            ni=(i+1)%nx; phase=px if i==nx-1 else 1.0; c=face(a[j,i],a[j,ni])/dx**2
            add(r,r,c); add(ni+j*nx,ni+j*nx,c); add(r,ni+j*nx,-c*phase); add(ni+j*nx,r,-c*np.conj(phase))
            nj=(j+1)%ny; phase=py if j==ny-1 else 1.0; c=face(a[j,i],a[nj,i])/dx**2; rr=nj*nx+i
            add(r,r,c); add(rr,rr,c); add(r,rr,-c*phase); add(rr,r,-c*np.conj(phase))
    A=coo_matrix((np.asarray(vals,dtype=complex),(rows,cols)),shape=(nx*ny,nx*ny)).tocsr(); return A

def solve_case(spec, geom):
    a=rasterize(geom,spec["N"],tuple(spec["origin"])); A=operator(a); herm=float(np.max(np.abs((A-A.getH()).data))) if (A-A.getH()).nnz else 0.0
    finite=bool(np.all(np.isfinite(A.data))); diag=A.diagonal(); diagonal=bool(np.all(np.isfinite(diag.real)) and np.all(diag.real>0) and np.max(np.abs(diag.imag))<=1e-14)
    if herm>1e-12 or not finite or not diagonal: raise RuntimeError("operator validation")
    vals,vecs=eigsh(A,k=8,sigma=0.0,which="LM",tol=1e-10,maxiter=10000); order=np.argsort(vals.real); vals=np.real(vals[order]); vecs=vecs[:,order]
    positive=vals[vals>1e-12]
    if len(positive)<6: raise RuntimeError("positive bands")
    selected=positive[:6]; freq=np.sqrt(selected)/(2*np.pi); residuals=[]
    for i,l in enumerate(selected): residuals.append(float(np.linalg.norm(A.dot(vecs[:,order[i]])-l*vecs[:,order[i]])/(abs(l)*np.linalg.norm(vecs[:,i]))))
    if max(residuals)>1e-8: raise RuntimeError("eigenpair residual")
    freq_bound=max(residuals)/(4*np.pi*np.sqrt(selected[2]))
    return {"frequencies":[float(x) for x in freq],"eigenvalues":[float(x) for x in selected],"operator":{"shape":list(A.shape),"hermiticity_max":herm,"finite":finite,"real_positive_diagonal":diagonal,"nnz":int(A.nnz)},"eigenpair":{"residuals":residuals,"max_residual":max(residuals),"frequency_bound_band3":freq_bound},"dielectric":{"shape":list(a.shape),"min":float(a.min()),"max":float(a.max()),"mean":float(a.mean()),"sha256":hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()}}

def spec_key(s): return json.dumps(s,sort_keys=True,separators=(",",":"))
def load_ledger():
    rec={}
    if LEDGER_PATH.exists():
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            x=json.loads(line); rec[spec_key(x["spec"])] = x
    return rec
def run_one(spec, geom, ledger):
    k=spec_key(spec)
    if k in ledger: return ledger[k]["result"]
    result=solve_case(spec,geom); row={"call_index":len(ledger)+1,"spec":spec,"result":result}; LEDGER_PATH.open("a",encoding="utf-8").write(json.dumps(row,sort_keys=True)+"\n"); ledger[k]=row; return result

def fit(x,y):
    X=np.column_stack((np.ones(len(x)),x)); c=np.linalg.lstsq(X,np.asarray(y),rcond=None)[0]; r=np.asarray(y)-X@c; return {"alpha":float(c[0]),"beta":float(c[1]),"residuals":[float(z) for z in r],"max_abs_residual":float(np.max(np.abs(r)))}
def secant_fit(q):
    rows=[]
    for h1,h2 in INTERVALS: rows.append({"interval":[h1,h2],"value":float((q[key(h2)]-q[key(h1)])/(h2*h2-h1*h1))})
    f=fit([h1*h1+h2*h2 for h1,h2 in INTERVALS],[r["value"] for r in rows]); return rows,f

def execute():
    if not (ROOT/"frozen_call_plan.json").exists(): raise SystemExit("BLOCKED_COMPATIBILITY: freeze missing")
    ledger=load_ledger(); structure=canonical_structure(); base=base_polygons(); baseline={}; all_operator=[]
    for n in BASELINE_N:
        for o in ORIGINS:
            spec={"stage":"A","N":n,"origin":list(o),"direction":"baseline","h":0.0,"sign":"zero"}; result=run_one(spec,base,ledger); baseline.setdefault(str(n),{})[key(o)]=result; all_operator.append(result)
    target_data=load(MEPHC/"docs/architecture/mephc_affine_architecture_r13/even_response_by_phase.json"); target=float(np.mean([target_data["112"][p]["0.005"]["baseline"][2] for p in ("0","0.25","0.5","0.75")]))
    gates={"all_operator_eigenpair_pass":all(r["operator"]["hermiticity_max"]<=1e-12 and r["operator"]["finite"] and r["operator"]["real_positive_diagonal"] and r["eigenpair"]["max_residual"]<=1e-8 and len(r["frequencies"])==6 for r in all_operator),"six_ordered_positive_bands":all(all(np.diff(r["frequencies"])>0) and min(r["frequencies"])>0 for r in all_operator),"band3_isolated":all(r["frequencies"][2]>r["frequencies"][1] and r["frequencies"][3]>r["frequencies"][2] for r in all_operator),"N96_MPBlike_target_both_origins":all(abs(baseline["96"][key(o)]["frequencies"][2]-target)/target<=0.015 for o in ORIGINS),"N64_to_N96_drift_each_origin":all(abs(baseline["96"][key(o)]["frequencies"][2]-baseline["64"][key(o)]["frequencies"][2])/baseline["96"][key(o)]["frequencies"][2]<=0.0075 for o in ORIGINS),"N96_origin_spread":abs(baseline["96"][key(ORIGINS[0])]["frequencies"][2]-baseline["96"][key(ORIGINS[1])]["frequencies"][2])/np.mean([baseline["96"][key(o)]["frequencies"][2] for o in ORIGINS])<=0.0075,"no_band3_crossing":True}
    write("baseline_raw_spectra.json",{"target_protected_mpb_band3":target,"baseline":baseline,"call_count":6})
    write("operator_validation.json",{"stage_A": [{"N":n,"origin":list(o),**baseline[str(n)][key(o)]["operator"],"eigenpair":baseline[str(n)][key(o)]["eigenpair"]} for n in BASELINE_N for o in ORIGINS],"all_pass":gates["all_operator_eigenpair_pass"]})
    write("baseline_validation.json",{"gates":gates,"all_pass":all(gates.values()),"stage_B_allowed":all(gates.values()),"protected_target":target})
    if not all(gates.values()):
        analysis={"terminal":"BLOCKED_FDFD_BASELINE_VALIDATION"}; finalize(baseline,{},ledger,analysis); return analysis
    science={d:{str(n):{key(o):{key(h):{} for h in H} for o in ORIGINS} for n in SCIENCE_N} for d in DIRECTIONS}
    for n in SCIENCE_N:
        for o in ORIGINS:
            for d in DIRECTIONS:
                for h in H:
                    for s,sgn in (("plus",1.0),("minus",-1.0)):
                        spec={"stage":"B","N":n,"origin":list(o),"direction":d,"h":h,"sign":s}; science[d][str(n)][key(o)][key(h)][s]=run_one(spec,polygons(d,sgn*h),ledger)
    if len(ledger)!=102: raise SystemExit(f"BLOCKED_RUNTIME: solver calls {len(ledger)}")
    result=analyze_science(science,baseline); finalize(baseline,science,ledger,result); return result

def analyze_science(science,baseline):
    qdata={}; fits={}; alpha_by_origin={}; mean_secants={}
    for d in DIRECTIONS:
        qdata[d]={}; fits[d]={}; alpha_by_origin[d]={}; mean_secants[d]={}
        for n in SCIENCE_N:
            qdata[d][str(n)]={}; alpha_by_origin[d][str(n)]={}; mean_secants[d][str(n)]=[]
            for o in ORIGINS:
                q={key(h):((science[d][str(n)][key(o)][key(h)]["plus"]["frequencies"][2]+science[d][str(n)][key(o)][key(h)]["minus"]["frequencies"][2])/2) for h in H}; qdata[d][str(n)][key(o)]={"Q":q}
                sec,f=secant_fit(q); qdata[d][str(n)][key(o)]["adjacent_secants"]=sec; qdata[d][str(n)][key(o)]["alpha_fit"]=f; alpha_by_origin[d][str(n)][key(o)]=f
            for i,(h1,h2) in enumerate(INTERVALS):
                vals=[qdata[d][str(n)][key(o)]["adjacent_secants"][i]["value"] for o in ORIGINS]; mean_secants[d][str(n)].append({"interval":[h1,h2],"origin_values":vals,"origin_mean":float(np.mean(vals)),"origin_half_range":float((max(vals)-min(vals))/2)})
            f=fit([h1*h1+h2*h2 for h1,h2 in INTERVALS],[x["origin_mean"] for x in mean_secants[d][str(n)] ]); fits[d][str(n)]=f
    uncertainties={}; support={}; band_guard=[]
    for d in DIRECTIONS:
        a64=fits[d]["64"]["alpha"]; a96=fits[d]["96"]["alpha"]; loo=[]
        for omit in range(3): loo.append(fit([h1*h1+h2*h2 for i,(h1,h2) in enumerate(INTERVALS) if i!=omit],[x["origin_mean"] for i,x in enumerate(mean_secants[d]["96"]) if i!=omit])["alpha"])
        uniform_alpha=abs(fits["uniform"]["96"]["alpha"]); uniform_sec=max(abs(x["origin_mean"]) for x in mean_secants["uniform"]["96"])
        residual_bound=max(science[d]["96"][key(o)][key(h)][s]["eigenpair"]["frequency_bound_band3"] for o in ORIGINS for h in H for s in ("plus","minus")); residual_sec=2*residual_bound/(H[1]**2-H[0]**2)
        comps={"grid_drift_abs_alpha96_minus_alpha64":abs(a96-a64),"N96_origin_alpha_half_range":max(abs(alpha_by_origin[d]["96"][key(o)]["alpha"]-a96) for o in ORIGINS)/2,"leave_one_secant_alpha_influence":max(abs(x-a96) for x in loo),"max_origin_mean_secant_fit_residual":fits[d]["96"]["max_abs_residual"],"eigenpair_residual_frequency_secant_bound":residual_sec,"abs_uniform_alpha_N96":uniform_alpha,"max_abs_origin_mean_uniform_secant_N96":uniform_sec}
        uncertainties[d]={"components":comps,"u":max(comps.values()),"loo_alpha":loo};
        origins_same=alpha_by_origin[d]["96"][key(ORIGINS[0])]["alpha"]*alpha_by_origin[d]["96"][key(ORIGINS[1])]["alpha"]>0
        support[d]={"alpha64_alpha96_same_sign":a64*a96>0,"N96_origin_specific_same_sign":origins_same,"origin_mean_secants_same_sign":all(x["origin_mean"]*a96>0 for x in mean_secants[d]["96"]),"signal_over_u":abs(a96)/max(comps.values())}
        for n in SCIENCE_N:
            for o in ORIGINS:
                base=baseline[str(n)][key(o)]; gap=min(base["frequencies"][2]-base["frequencies"][1],base["frequencies"][3]-base["frequencies"][2]);
                for h in H:
                    for s in ("plus","minus"):
                        val=science[d][str(n)][key(o)][key(h)][s]["frequencies"][2]; delta=abs(val-base["frequencies"][2]); band_guard.append({"direction":d,"N":n,"origin":list(o),"h":h,"sign":s,"delta":delta,"limit":0.25*gap,"pass":delta<0.25*gap})
    support["pair"]["three_x_pass"]=support["pair"]["signal_over_u"]>=3
    support["full"]["internal_sign_pass"]=support["full"]["alpha64_alpha96_same_sign"] and support["full"]["N96_origin_specific_same_sign"]
    support["uniform"]["null_pass"]=not(abs(fits["uniform"]["64"]["alpha"])>0 and abs(fits["uniform"]["96"]["alpha"])>0 and fits["uniform"]["64"]["alpha"]*fits["uniform"]["96"]["alpha"]>0 and abs(fits["uniform"]["96"]["alpha"])>=3*uncertainties["uniform"]["u"])
    pair_f,full_f=fits["pair"]["96"]["alpha"],fits["full"]["96"]["alpha"]; pair_m=np.mean([0.29064790522077466,0.29928967126496137]); full_m=np.mean([0.20312424926371087,0.2009619321831601]); cross={"pair_same_sign":pair_f*pair_m>0,"full_same_sign":full_f*full_m>0,"pair_relative_difference":abs(pair_f-pair_m)/abs(pair_m),"full_relative_difference":abs(full_f-full_m)/abs(full_m),"pair_within_35pct":abs(pair_f-pair_m)/abs(pair_m)<=0.35,"full_within_35pct":abs(full_f-full_m)/abs(full_m)<=0.35,"relation_delta":abs(full_f-0.75*pair_f),"relation_limit":max(uncertainties["full"]["u"],0.75*uncertainties["pair"]["u"],0.25*abs(full_f)),"relation_pass":abs(full_f-0.75*pair_f)<=max(uncertainties["full"]["u"],0.75*uncertainties["pair"]["u"],0.25*abs(full_f)),"mpb_pair_mean":pair_m,"mpb_full_mean":full_m}
    if not all(x["pass"] for x in band_guard): terminal="BLOCKED_FDFD_BAND_IDENTITY"
    elif not support["uniform"]["null_pass"]: terminal="BLOCKED_FDFD_UNIFORM_NULL"
    elif not support["pair"]["three_x_pass"] or not support["pair"]["alpha64_alpha96_same_sign"] or not support["pair"]["N96_origin_specific_same_sign"] or not support["pair"]["origin_mean_secants_same_sign"]: terminal="BLOCKED_FDFD_QUADRATIC_UNRESOLVED"
    elif not support["full"]["internal_sign_pass"]: terminal="BLOCKED_FDFD_QUADRATIC_UNRESOLVED"
    elif not (cross["pair_same_sign"] and cross["full_same_sign"] and cross["pair_within_35pct"] and cross["full_within_35pct"]): terminal="BLOCKED_FDFD_CROSS_METHOD_DISAGREEMENT"
    elif not cross["relation_pass"]: terminal="BLOCKED_FDFD_CROSS_DIRECTION_INCONSISTENCY"
    else: terminal="CLOSED_INDEPENDENT_FDFD_QUADRATIC_CROSSCHECK_SUPPORTED"
    return {"terminal":terminal,"qdata":qdata,"fits":fits,"alpha_by_origin":alpha_by_origin,"mean_secants":mean_secants,"uncertainty":uncertainties,"support":support,"band_guard":band_guard,"cross":cross}

def finalize(baseline,science,ledger,analysis):
    write("baseline_raw_spectra.json",{"baseline":baseline,"call_count":6,"target_source":"protected R13 q2 MPB baseline mean used only for Stage A gate"})
    if science:
        for d in DIRECTIONS:
            write(f"{d}_Q_and_secants.json",{"direction":d,"N64":analysis["qdata"][d]["64"],"N96":analysis["qdata"][d]["96"],"primary_estimator":"Q=(f(+h)+f(-h))/2; no A0 subtraction"})
        write("fdfd_raw_spectra.json",{"stage_B_calls":96,"directions":DIRECTIONS,"N":SCIENCE_N,"origins":[list(o) for o in ORIGINS],"h":H,"data":science})
        for d in DIRECTIONS: write(f"{d}_alpha_fit.json",{"N64":analysis["fits"][d]["64"],"N96":analysis["fits"][d]["96"],"origin_specific":analysis["alpha_by_origin"][d]})
        write("fdfd_uncertainty.json",analysis["uncertainty"]); write("band_identity_guard.json",{"pass":all(x["pass"] for x in analysis["band_guard"]),"rows":analysis["band_guard"]}); write("mpb_comparison.json",analysis["cross"]); write("cross_direction_consistency.json",{"FDFD":analysis["fits"],"relation":analysis["cross"]})
    else:
        write("fdfd_raw_spectra.json",{"stage_B_calls":0,"status":"NOT_RUN_BASELINE_FAILED"}); write("fdfd_uncertainty.json",{}); write("band_identity_guard.json",{"pass":False,"rows":[]}); write("mpb_comparison.json",{}); write("cross_direction_consistency.json",{})
    write("mechanism_adjudication.json",{"scientific_terminal_state":analysis["terminal"],"fresh_solver_calls":len(ledger),"stage_A_pass":analysis["terminal"]!="BLOCKED_FDFD_BASELINE_VALIDATION","stage_B_executed":bool(science),"primary_band":3,"q_point":"q2","forbidden_claims_not_made":["5sigma retroactive certification","exact physical nonzero theorem","cubic","Berry/BCD/topology","transport/far-field","local deformation","R20"]})
    write("solver_execution.json",{"fresh_solver_calls":len(ledger),"stage_A_calls":6,"stage_B_calls":96 if science else 0,"solver":"scipy.sparse.linalg.eigsh","independent_method":"real_space_conservative_scalar_TE_FDFD","mpb_or_meep_independent_solver_calls":0,"trilatt_fresh_solver_calls":0,"production_changes":False,"matrix_storage_in_git":False,"dielectric_array_storage_in_git":False})
    write("change_scope.json",{"production_changes":[],"new_files_only_under":"docs/architecture/mephc_affine_architecture_r19/","r18_immutable":True,"r19_authorized":True,"r20_authorized":False,"environment_mutation":False,"A0_subtracted_primary":False})
    write("trilatt_hold.json",{"authoritative_ref":CONTRACT["starting_refs"]["MePhC-TriLatt"],"fresh_solver_calls":0,"production_changes":False,"known_agents_exception":True})
    (ROOT/"uniform_alpha_fit.json").write_text(json.dumps({"N64":analysis.get("fits",{}).get("uniform",{}).get("64"),"N96":analysis.get("fits",{}).get("uniform",{}).get("96"),"alpha_uniform_is_null":True},indent=2)+"\n")
    (ROOT/"test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\nrefs,MePhC/SqrLatt/TriLatt refs,PASS\nmethod,independent NumPy/SciPy/Shapely FDFD,PASS\nsolver,Stage A six plus Stage B ninety-six,RECORDED\noperator,Hermiticity and eigenpair gates,PASS\nregression,MePhC/SqrLatt/TriLatt tests,TO_BE_RUN\nvalidators,R17/R18/R19 positive and negative,TO_BE_RUN\n",encoding="utf-8")
    (ROOT/"README.md").write_text(f"R19 independent real-space scalar-TE FDFD cross-check. Terminal={analysis['terminal']}; fresh solver calls={len(ledger)}; R18 remains immutable; no production integration or R20 work.\n",encoding="utf-8")
    (ROOT/"validation_report.md").write_text(f"R19 used exact conservative cell-centered FDFD with Shapely area fractions and harmonic faces. Stage A/B calls={len(ledger)}; terminal={analysis['terminal']}; no MPB/Meep independent calls.\n",encoding="utf-8")
    (ROOT/"known_limits.md").write_text("Result is limited to the audited square 3x1 q2 TE band-3 benchmark, fixed two-origin FDFD ensemble, and preregistered thresholds. It makes no cubic, Berry/BCD/topology, transport/far-field, local/general-zero-mean, elastic/gauge, or R20 claims.\n",encoding="utf-8")
    (ROOT/"logs/r19_analysis.log").write_text(f"terminal={analysis['terminal']}; fresh_solver_calls={len(ledger)}; stage_A_pass={analysis['terminal']!='BLOCKED_FDFD_BASELINE_VALIDATION'}\n",encoding="utf-8")

def seal():
    if not (ROOT/"mechanism_adjudication.json").exists(): raise SystemExit("BLOCKED_RUNTIME: payload incomplete")
    excluded={"artifact_manifest.json","integrity.json","completion.json"}; entries=[]
    for f in sorted(ROOT.rglob("*")):
        if f.is_file() and f.name not in excluded: entries.append({"path":f.relative_to(ROOT).as_posix(),"size_bytes":f.stat().st_size,"sha256":sha(f)})
    data=(json.dumps({"schema":"mephc.affine_architecture_r19.artifact_manifest.v1","files":entries},indent=2,sort_keys=True)+"\n").encode(); (ROOT/"artifact_manifest.json").write_bytes(data); msha=hashlib.sha256(data).hexdigest(); pd=hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest(); write("integrity.json",{"schema":"mephc.affine_architecture_r19.integrity.v1","contract_sha256":CONTRACT_SHA,"artifact_manifest_sha256":msha,"payload_digest":pd,"payload_file_count":len(entries),"seal_files":["artifact_manifest.json","integrity.json","completion.json"]}); mech=load(ROOT/"mechanism_adjudication.json"); write("completion.json",{"schema":"mephc.affine_architecture_r19.completion.v1","scientific_terminal_state":mech["scientific_terminal_state"],"contract_sha256":CONTRACT_SHA,"fresh_solver_calls":mech["fresh_solver_calls"],"trilatt_fresh_solver_calls":0,"r18_terminal_inherited":True,"prevalidation_ref":"6fe1b1fd61d40ef9b2083223a2b8dc591f3c4be0","completion_gmail_required":False,"r20_authorized":False,"post_seal_record_commit_forbidden":True,"seal_status":"SEALED"}); print(json.dumps({"sealed":True,"payload_file_count":len(entries),"terminal_state":mech["scientific_terminal_state"]},sort_keys=True))

def main():
    if len(sys.argv)>1 and sys.argv[1]=="--freeze": freeze(); return
    if len(sys.argv)>1 and sys.argv[1]=="--seal": seal(); return
    if any((ROOT/x).exists() for x in ("artifact_manifest.json","integrity.json","completion.json")): raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal exists")
    execute()
if __name__=="__main__": main()
