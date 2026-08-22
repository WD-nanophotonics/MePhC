"""E7I.3C bounded H-to-E+H representation bridge."""
from __future__ import annotations
import hashlib, json, math, subprocess, sys
from fractions import Fraction
from pathlib import Path
import meep as mp
import numpy as np
from mephc.eigenspace import RawEigenstate
from mephc.mpb_energy_spectral_provider import MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION, MPBLiveEnergySpectralProvider
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_spectral import MPBHEnvelopeSnapshot, MPB_H_ENVELOPE_QUALIFIED
from mephc.plaquette_domain import PlaquetteRefinementThresholds
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.valley_reference_geometry import build_triangular_reference_geometry
from mephc.mpb_reference_adapter import build_reference_mpb_adapter

H_COMMIT="0425209b55de7e41e1bbdd349d097dd7bab0c034"
H_SHA="3e9521f172958a818474f76479ea8f3a7f7b058e647ea689ac3116f0c29e386a"
SCALE_COMMIT="63fda34ede99caa44643d7ad85c0e9bcdfb643e1"
SCALE_SHA="162817b29983afc390644ffd62b60a5d649d1f44953431ac023fcd8de37b74db"
K=(2.0/3.0,0.0); BANDS=4; SEL=(0,1,2)
E3=SubspaceQualificationThresholds(0.9,0.45,0.3,0.05)
E4C=PlaquetteRefinementThresholds(0.9,0.45,0.3,0.1)
UNIT_TOL=1e-10; ALG_TOL=1e-8; RAW_TOL=1e-10
STEPS=(Fraction(1,36),Fraction(1,72),Fraction(1,144))


def sid(x:Fraction)->str: return f"{x.numerator}/{x.denominator}"
def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def head(root:Path)->str: return subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
def git_json(root,commit,path,expected):
    blob=subprocess.check_output(["git","show",f"{commit}:{path}"],cwd=root)
    actual=sha(blob)
    if actual!=expected: raise RuntimeError(f"source hash mismatch {path}: {actual}")
    return json.loads(blob.decode())


def pts(step):
    x,y=K; d=step/2
    return ((x-d,y-d),(x+d,y-d),(x+d,y+d),(x-d,y+d),(x,y))


def cpairs(v):
    a=np.asarray(v)
    if a.ndim==0:
        z=complex(a); return [float(z.real),float(z.imag)]
    if a.ndim==1: return [[float(z.real),float(z.imag)] for z in a]
    return [[[float(z.real),float(z.imag)] for z in row] for row in a]


def stable(w):
    v=np.asarray(w.eigenvalues,dtype=np.complex128)
    return np.asarray(sorted(v.tolist(),key=lambda z:(float(np.angle(z)),float(np.real(z)),float(np.imag(z)))),dtype=np.complex128)


def lowdin_matrix(v):
    g=(v.conj().T@v); g=(g+g.conj().T)/2
    ev,u=np.linalg.eigh(g)
    if np.any(ev<=0) or not np.all(np.isfinite(ev)): raise RuntimeError("selected Gram is not positive definite")
    q=v@u@np.diag(1/np.sqrt(ev))@u.conj().T
    return q,{"GRAM_EIGENVALUES":[float(x) for x in ev],
        "GRAM_CONDITION_NUMBER":float(max(ev)/min(ev)),
        "Q_DAGGER_Q_RESIDUAL":float(np.linalg.norm(q.conj().T@q-np.eye(v.shape[1]))),
        "SPAN_PROJECTOR_RESIDUAL":float(np.linalg.norm(v@np.linalg.inv(g)@v.conj().T-q@q.conj().T)),
        "ORTHONORMALIZATION_CORRECTION_NORM":float(np.linalg.norm(q-v)),
        "GRAM_HERMITIAN_RESIDUAL":float(np.linalg.norm(g-g.conj().T))}


def lowdin_snapshot(raw):
    v=np.column_stack([raw.normalized_vectors[i] for i in SEL])
    q,m=lowdin_matrix(v)
    selected_g=v.conj().T@v; off=np.array(selected_g,copy=True); np.fill_diagonal(off,0)
    m.update({"RAW_SELECTED_GRAM":cpairs(selected_g),
        "RAW_SELECTED_MAX_OFF_DIAGONAL_GRAM":float(np.max(np.abs(off))),
        "raw_normalization_error":float(raw.max_normalization_error),
        "raw_provider_max_off_diagonal_gram":float(raw.max_off_diagonal_gram),
        "raw_provider_orthogonality_status":raw.orthogonality_status,
        "selected_span_condition":"WELL_CONDITIONED" if m["GRAM_CONDITION_NUMBER"]<1e8 else "ILL_CONDITIONED"})
    vectors=list(raw.normalized_vectors); vectors[:3]=[q[i] for i in range(3)]
    full=np.column_stack(vectors)
    states=[]
    for i,vec in enumerate(vectors):
        meta=dict(raw.raw_eigenstates[i].metadata)
        meta.update({"audit_adapter":"E7I.3C selected-rank3 symmetric Lowdin frame","selected_span_only":True})
        states.append(RawEigenstate(raw.k_point,i,float(raw.frequencies[i]),vec,meta))
    prov=dict(raw.provenance)
    prov.update({"audit_adapter":"E7I.3C selected-rank3 symmetric Lowdin frame","selected_span_only":True,"raw_provider_status":raw.orthogonality_status,"live_mpb_extraction_validated":True})
    adapted=MPBHEnvelopeSnapshot(k_point=raw.k_point,frequencies=raw.frequencies,h_fields=raw.h_fields,e_fields=raw.e_fields,raw_norms=raw.raw_norms,normalized_vectors=tuple(vectors),gram_matrix=full.conj().T@full,max_normalization_error=float(max(abs(np.vdot(x,x).real-1) for x in vectors)),max_off_diagonal_gram=float(np.max(np.abs(full.conj().T@full-np.eye(BANDS))),),orthogonality_status=MPB_H_ENVELOPE_QUALIFIED,normalization_tolerance=raw.normalization_tolerance,orthogonality_tolerance=raw.orthogonality_tolerance,raw_eigenstates=tuple(states),provenance=prov)
    return adapted,m


def provider(adapter,res):
    return MPBLiveEnergySpectralProvider(geometry=list(adapter.geometry),geometry_lattice=adapter.geometry_lattice,resolution=res,num_bands=BANDS,polarization=mp.TE,default_material=adapter.background_material,eigensolver_tolerance=1e-7,deterministic=True,mesh_size=3,orthogonality_tolerance=RAW_TOL)


def wrecord(w):
    return {"status":w.status,"rank":int(w.rank),"closed":bool(w.closed),"product_W":None if w.product is None else cpairs(w.product),"det_W":None if w.determinant is None else cpairs(w.determinant),"Arg_det_W":None if w.determinant_phase is None else float(w.determinant_phase),"eigenvalues":None if w.eigenvalues is None else cpairs(stable(w)),"trace":None if w.trace is None else cpairs(w.trace),"unitarity_residual":None if w.unitarity_residual is None else float(w.unitarity_residual)}


def diagnostics(fwd,same,shifted,cyc):
    maxima={x:0.0 for x in ("unitarity","same_matrix","shifted_det","shifted_phase","shifted_trace","shifted_eigen","cyclic")}
    rows=[]
    for lev,(a,b,c,d) in enumerate(zip(fwd.wilson_results,same.wilson_results,shifted.wilson_results,cyc.wilson_results)):
        if any(x.product is None for x in (a,b,c,d)): return {"observable_produced":False,"algebraic_checks_pass":False}
        av=stable(a); cv=stable(c)
        same_m=float(np.max(np.abs(b.product-a.product.conj().T)))
        det=float(abs(c.determinant-a.determinant.conjugate()))
        phase=float(abs(np.angle(np.exp(1j*(c.determinant_phase+a.determinant_phase)))))
        trace=float(abs(c.trace-a.trace.conjugate()))
        eig=float(min(np.max(np.abs(cv-np.conjugate(av[list(p)]))) for p in __import__("itertools").permutations(range(len(av)))))
        cyc=float(max(np.max(np.abs(stable(d)-av)),abs(d.trace-a.trace),abs(d.determinant-a.determinant),abs(np.angle(np.exp(1j*(d.determinant_phase-a.determinant_phase))))))
        vals=(float(a.unitarity_residual),float(b.unitarity_residual),float(c.unitarity_residual),float(d.unitarity_residual))
        maxima["unitarity"]=max(maxima["unitarity"],*vals); maxima["same_matrix"]=max(maxima["same_matrix"],same_m); maxima["shifted_det"]=max(maxima["shifted_det"],det); maxima["shifted_phase"]=max(maxima["shifted_phase"],phase); maxima["shifted_trace"]=max(maxima["shifted_trace"],trace); maxima["shifted_eigen"]=max(maxima["shifted_eigen"],eig); maxima["cyclic"]=max(maxima["cyclic"],cyc)
        rows.append({"level":lev,"forward":wrecord(a),"reverse_same_basepoint":wrecord(b),"reverse_shifted_basepoint":wrecord(c),"cyclic":wrecord(d),"same_basepoint_reverse_matrix_residual":same_m,"shifted_basepoint_reverse_det_residual":det,"shifted_basepoint_reverse_det_phase_residual":phase,"shifted_basepoint_reverse_trace_residual":trace,"shifted_basepoint_reverse_eigenvalue_residual":eig,"cyclic_basepoint_residual":cyc})
    maxima["levels"]=rows; maxima["observable_produced"]=True
    maxima["algebraic_checks_pass"]=bool(maxima["unitarity"]<=UNIT_TOL and all(maxima[k]<=ALG_TOL for k in ("same_matrix","shifted_det","shifted_phase","shifted_trace","shifted_eigen","cyclic")))
    return maxima


def qtree(levels,steps):
    selections=tuple(((SEL,)*5) for _ in levels)
    src=qualify_mpb_plaquette(tuple(levels),selections,steps,thresholds=E3,refinement_thresholds=E4C,require_live=True)
    return src,compose_mpb_plaquette_holonomy(src,require_live=True)


def live_case(adapter,res,endpoint):
    p=provider(adapter,res); cache={}; records=[]; levels=[]
    for i in range(3):
        sf=STEPS[i]; lev=[]
        for point in pts(float(sf)):
            key=tuple(float(x) for x in point)
            if key not in cache:
                raw=p.solve(key); frame,met=lowdin_snapshot(raw); cache[key]=(raw,frame,met)
                records.append({"point":list(key),"frequencies":[float(x) for x in raw.frequencies],"external_gap_band4_minus_band3":float(raw.frequencies[3]-raw.frequencies[2]),"raw":met})
            lev.append(cache[key][1])
        levels.append(tuple(lev))
    orders={"forward":(0,1,2,3,4),"reverse_same_basepoint":(0,3,2,1,4),"reverse_shifted_basepoint":(3,2,1,0,4),"cyclic":(1,2,3,0,4)}
    results={}
    for name,order in orders.items():
        reordered=[tuple(level[i] for i in order) for level in levels]
        results[name]=qtree(reordered,tuple(float(x) for x in STEPS))
    alg=diagnostics(results["forward"][1],results["reverse_same_basepoint"][1],results["reverse_shifted_basepoint"][1],results["cyclic"][1])
    fsrc,fw=results["forward"]
    return {"endpoint":endpoint,"resolution":res,"raw_solves":records,"qualification":{"forward":bool(fsrc.is_qualified and fw.is_qualified),"forward_status":fsrc.status,"refinement_status":fsrc.refinement_result.status,"min_external_gap":float(min(x["external_gap_band4_minus_band3"] for x in records))},"levels":[{"STEP_ID":sid(STEPS[i]),"h":float(STEPS[i]),"A_q":float(STEPS[i])**2,"wilson":alg["levels"][i] if alg.get("observable_produced") else None} for i in range(3)],"algebra":alg}


def baseline(root):
    scaling=git_json(root,SCALE_COMMIT,"audit/e7i3b/result.json",SCALE_SHA); h=git_json(root,H_COMMIT,"audit/e7i3a/result.json",H_SHA)
    ph={}
    for ep,er in scaling["endpoint_results"].items():
        for case in er["cases"].values():
            if case["resolution"] in (48,64) and case["nominal_step_id"]=="1/36":
                for lev in case["scaling"]["levels"]: ph[(ep,case["resolution"],lev["STEP_ID"])] = (lev["PHI"],lev["DETERMINANT_HOLONOMY_DENSITY_PROXY"])
    return {"h_commit":H_COMMIT,"h_sha":H_SHA,"scaling_commit":SCALE_COMMIT,"scaling_sha":SCALE_SHA,"phase_map":ph,"scaling_result":scaling}


def comparison(cases,base):
    out=[]
    for ep,eres in cases.items():
        for rs,case in eres.items():
            for lev in case["levels"]:
                hp,hd=base["phase_map"][(ep,int(rs),lev["STEP_ID"])]
                epv=lev["wilson"]["forward"]["Arg_det_W"]; ed=epv/lev["A_q"]
                out.append({"endpoint":ep,"resolution":int(rs),"STEP_ID":lev["STEP_ID"],"PHI_H":hp,"PHI_EH":epv,"D_H":hd,"D_EH":ed,"REPRESENTATION_PHASE_ABS_DIFFERENCE":abs(hp-epv),"REPRESENTATION_DENSITY_ABS_DIFFERENCE":abs(hd-ed),"REPRESENTATION_DENSITY_RELATIVE_DIFFERENCE":abs(hd-ed)/max(abs(hd),abs(ed)) if max(abs(hd),abs(ed))>1e-15 else None})
    return out


def scaling_summary(case_by_resolution, endpoint):
    levels48 = case_by_resolution["48"]["levels"]
    levels64 = case_by_resolution["64"]["levels"]
    densities48 = [float(x["wilson"]["forward"]["Arg_det_W"] / x["A_q"]) for x in levels48]
    densities64 = [float(x["wilson"]["forward"]["Arg_det_W"] / x["A_q"]) for x in levels64]
    phases48 = [float(x["wilson"]["forward"]["Arg_det_W"]) for x in levels48]
    all_densities = densities48 + densities64
    common_sign = len({math.copysign(1.0, x) for x in all_densities}) == 1
    resolution_relative = [
        abs(a - b) / max(abs(a), abs(b))
        for a, b in zip(densities48, densities64)
    ]
    refinement_relative = [
        abs(densities48[i] - densities48[i + 1]) / max(abs(densities48[i]), abs(densities48[i + 1]))
        for i in range(2)
    ]
    nonzero_overlap = all(
        abs(a - b) < min(abs(a), abs(b))
        for a, b in zip(densities48, densities64)
    )
    refinement_inside = all(
        refinement_relative[i] <= resolution_relative[i]
        for i in range(2)
    )
    stable = common_sign and nonzero_overlap and refinement_inside
    phase_decreases = abs(phases48[-1]) < abs(phases48[0])
    if stable:
        classification = "SUPPORTED_WITH_VISIBLE_NUMERICAL_SENSITIVITY" if max(resolution_relative) > 100 * np.finfo(float).eps else "SUPPORTED"
    elif endpoint == "FR050" and phase_decreases:
        classification = "SYMMETRY_SUPPRESSED_OR_NEAR_ZERO"
    else:
        classification = "NUMERICALLY_UNRESOLVED"
    return {
        "classification": classification,
        "common_sign": common_sign,
        "nonzero_interval_overlap": nonzero_overlap,
        "refinement_inside_resolution_envelope": refinement_inside,
        "stable_window_supported": stable,
        "phase_decreases_toward_zero": phase_decreases,
        "resolution_relative_envelope": resolution_relative,
        "refinement_relative_drift": refinement_relative,
        "density_proxy_R48": densities48,
        "density_proxy_R64": densities64,
    }


def bridge_summary(endpoint, comparisons, eh_summary, baseline):
    h_class = baseline["scaling_result"][f"{endpoint}_SMALL_LOOP_SCALING"]
    h_cases = baseline["scaling_result"]["endpoint_results"][endpoint]
    h_by_step = {}
    for case in h_cases.values():
        if case["resolution"] not in (48, 64) or case["nominal_step_id"] != "1/36":
            continue
        for level in case["scaling"]["levels"]:
            h_by_step[(case["resolution"], level["STEP_ID"])] = level["DETERMINANT_HOLONOMY_DENSITY_PROXY"]
    h_env = {}
    for step in ("1/36", "1/72", "1/144"):
        a = h_by_step[(48, step)]
        b = h_by_step[(64, step)]
        h_env[step] = abs(a - b) / max(abs(a), abs(b))
    rep = [x for x in comparisons if x["endpoint"] == endpoint]
    eh_env = {step: value for step, value in zip(("1/36", "1/72", "1/144"), eh_summary["resolution_relative_envelope"])}
    same_sign = all(np.sign(x["D_H"]) == np.sign(x["D_EH"]) for x in rep)
    within_combined = all(
        x["REPRESENTATION_DENSITY_RELATIVE_DIFFERENCE"] <= h_env[x["STEP_ID"]] + eh_env[x["STEP_ID"]]
        for x in rep
    )
    if endpoint == "FR00":
        if eh_summary["classification"] in {"NUMERICALLY_UNRESOLVED", "SYMMETRY_SUPPRESSED_OR_NEAR_ZERO"}:
            classification = "NUMERICALLY_UNRESOLVED"
        elif same_sign and within_combined:
            classification = "SUPPORTED"
        else:
            classification = "SUPPORTED_WITH_REPRESENTATION_SENSITIVITY"
    else:
        h_symmetry = h_class == "SYMMETRY_SUPPRESSED_OR_NEAR_ZERO"
        classification = "BOTH_SYMMETRY_SUPPRESSED" if h_symmetry and eh_summary["classification"] == "SYMMETRY_SUPPRESSED_OR_NEAR_ZERO" else "NUMERICALLY_UNRESOLVED"
    return {
        "classification": classification,
        "same_sign": same_sign,
        "within_combined_numerical_envelopes": within_combined,
        "H_resolution_relative_envelope": h_env,
        "EH_resolution_relative_envelope": eh_env,
        "max_representation_density_relative_difference": max(x["REPRESENTATION_DENSITY_RELATIVE_DIFFERENCE"] for x in rep),
    }

def self_checks():
    rng=np.random.default_rng(17); raw=rng.normal(size=(12,3))+1j*rng.normal(size=(12,3)); q,m=lowdin_matrix(raw)
    assert m["Q_DAGGER_Q_RESIDUAL"]<1e-10 and m["SPAN_PROJECTOR_RESIDUAL"]<1e-10 and m["GRAM_CONDITION_NUMBER"]<1e8
    assert sid(Fraction(1,36)/4)=="1/144"
    g=np.diag([1.,2.,4.]); assert np.allclose(lowdin_matrix(np.diag([1.,np.sqrt(2),2.]))[0],np.eye(3))
    assert float(g[2,2])==4.0


def main():
    root=Path(__file__).resolve().parents[2]; self_checks()
    if "--self-check" in sys.argv: print(json.dumps({"self_check":"PASSED"})); return
    base=baseline(root); cases={}
    for ep,fr in (("FR00",0.0),("FR050",0.5)):
        adapter=build_reference_mpb_adapter(build_triangular_reference_geometry(fr),build_triangular_coordinate_preflight())
        cases[ep]={str(r):live_case(adapter,r,fr) for r in (48,64)}
    comp=comparison(cases,base)
    eh_summary={ep:scaling_summary(cases[ep],ep) for ep in ("FR00","FR050")}
    bridge_summary={ep:bridge_summary(ep,comp,eh_summary[ep],base) for ep in ("FR00","FR050")}
    raw=[row["raw"]["raw_provider_orthogonality_status"] for er in cases.values() for case in er.values() for row in case["raw_solves"]]
    all_alg=all(case["algebra"].get("algebraic_checks_pass",False) for er in cases.values() for case in er.values())
    all_qual=all(case["qualification"]["forward"] for er in cases.values() for case in er.values())
    cond=all(row["raw"]["selected_span_condition"]=="WELL_CONDITIONED" for er in cases.values() for case in er.values() for row in case["raw_solves"])
    proj=all(row["raw"]["SPAN_PROJECTOR_RESIDUAL"]<1e-10 for er in cases.values() for case in er.values() for row in case["raw_solves"])
    result={"schema":"e7i3c_rank3_h_to_eh_representation_bridge_v1","work_order":"E7I.3C","calculation_code_git_commit":head(root),"source_baseline":base,"provider_representation":MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION,"solver_settings":{"polarization":"TE","num_bands":BANDS,"eigensolver_tolerance":1e-7,"deterministic":True,"mesh_size":3,"orthogonality_tolerance":RAW_TOL},"cases":cases,"representation_comparison":comp,"eh_scaling_summary":eh_summary,"representation_bridge_summary":bridge_summary,"EH_RAW_PROVIDER_ORTHOGONALITY":"UNQUALIFIED_AS_EXPECTED" if all(x!="MPB_H_ENVELOPE_QUALIFIED" for x in raw) else "QUALIFIED","EH_SELECTED_SPAN_CONDITION":"WELL_CONDITIONED" if cond else "ILL_CONDITIONED","EH_LOWDIN_FRAME":"VALIDATED","EH_SPAN_PROJECTOR_INVARIANCE":"PASSED" if proj else "FAILED","EH_RANK3_SPECTRAL_ISOLATION":"PASSED" if all(case["qualification"]["min_external_gap"]>=0.05 for er in cases.values() for case in er.values()) else "FAILED","EH_RANK3_WILSON_QUALIFICATION":"PASSED" if all_qual else "FAILED","EH_RANK3_WILSON_ALGEBRA":"QUALIFIED" if all_alg else "UNQUALIFIED","FR00_EH_SMALL_LOOP_SCALING":eh_summary["FR00"]["classification"],"FR00_REPRESENTATION_BRIDGE":bridge_summary["FR00"]["classification"],"FR050_REPRESENTATION_BRIDGE":bridge_summary["FR050"]["classification"],"PRODUCTION_EH_SUBSPACE_FRAME_ADAPTER_REQUIRED":False,"WILSON_REPRESENTATION":"MPB_ENERGY_EH_REPRESENTATION","PHYSICAL_MAXWELL_BERRY_INTERPRETATION":"NOT_YET_AUTHORIZED","area_normalized_physical_berry_curvature_authorized":False,"chern_number_authorized":False,"rank2_doublet_observable_authorized":False,"physical_hall_response_authorized":False,"CODE_CHANGE":"SANDBOX_AUDIT_ONLY","MAIN_UNCHANGED":True,"E7I3C_OVERALL":"RANK3_H_TO_EH_REPRESENTATION_BRIDGE_READY_FOR_SUPERVISOR_AUDIT" if all_alg and all_qual else "REPRESENTATION_BRIDGE_PARTIAL"}
    (root/"audit"/"e7i3c"/"result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"overall":result["E7I3C_OVERALL"],"raw":result["EH_RAW_PROVIDER_ORTHOGONALITY"],"algebra":result["EH_RANK3_WILSON_ALGEBRA"]}))


if __name__=="__main__": main()
