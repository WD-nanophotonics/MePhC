"""E9E.E bounded at-K/K-prime structural-parameter Berry trend runner."""
from __future__ import annotations
import hashlib, json, math, resource, subprocess, sys, time
from pathlib import Path
import meep as mp
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from audit.e9e.a_rounded_triangle_geometry import build_geometry, validate_geometry
from audit.e9e.run_spectral_embedding import make_lattice, make_solver_geometry, polygon_case
from audit.e9e.run_berry_evolution import (
    BANDS, K_PUBLIC, KPRIME_PUBLIC, MESH_SIZE, R96, REFINEMENT,
    SOLVER_TOLERANCE, TRANSPORT, solve_at, stencil_evidence,
)
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.plaquette_domain import PlaquetteRefinementLevel, qualify_plaquette_refinement

WORK_ORDER="TRILATT-E9E-E-20260824-199"
NEW_FR=(0.1,0.2,0.3)
EXPECTED_MAIN="5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
BASE_SANDBOX="9bb5b4f90b998ecca9a26eff437300156a30a413"
FR0_SHA="abf4eb1785ff18a56be3002d9d4859bd0ed65c3b4212589b0f811e82c5850a83"
FR04_SHA="c3c04c9dc5ea73ef7e8dbb59b5755d9eb5aed700bc5ad942e64089337fc60827"
TRS_LIMIT=0.01
REPLAY_TOL=1e-7
FINE_SIDES=(1.0/72.0,1.0/144.0,1.0/288.0)
FINE_LABELS=("1/72","1/144","1/288")


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def git_head(): return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
def make_provider(fr,resolution,tessellation):
    geom=polygon_case(fr,tessellation)
    return MPBLiveEnergySpectralProvider(geometry=list(make_solver_geometry(geom)),geometry_lattice=make_lattice(),resolution=resolution,num_bands=6,polarization=mp.TE,default_material=mp.Medium(epsilon=7.0225),eigensolver_tolerance=SOLVER_TOLERANCE,deterministic=True,mesh_size=MESH_SIZE),geom

def simple_value(e):
    return {k:v for k,v in e.items() if not k.startswith("_")}

def solve_spectrum(provider,preflight,q,cache,counters,tag):
    return solve_at(provider,preflight,q,R96,cache,counters,tag)

def fine_evidence(center,side,label,band,resolution,provider,preflight,cache,counters,tag):
    value=stencil_evidence(center,side,band,resolution,provider,preflight,cache,counters,tag)
    value["stencil_label"]=label
    return value

def fine_e4c(primary,reference,fine,band,center_name):
    levels=tuple(PlaquetteRefinementLevel(boundary=item["_boundary"], interior=item["_interior"], step=side, provenance={"source":"E9E.E fine ladder","band":band,"center":center_name,"label":FINE_LABELS[index]}) for index,(item,side) in enumerate(zip((primary,reference,fine),FINE_SIDES)))
    result=qualify_plaquette_refinement(levels,thresholds=REFINEMENT,provenance={"source":"E9E.E final-pair 1/144-to-1/288 E4C","band":band,"center":center_name}).to_dict()
    return {"status":result["status"],"authorization_granted":bool(result["authorization_granted"]),"qualified":bool(all(item["_basic_qualified"] for item in (primary,reference,fine)) and result["authorization_granted"]),"metrics":result["metrics"],"thresholds":result["thresholds"],"levels":result["levels"]}
def berry_center(center_name,center,provider,preflight,cache,counters,tag):
    levels={}
    for band in BANDS:
        values=[fine_evidence(center,S,L,band,R96,provider,preflight,cache,counters,tag) for S,L in zip(FINE_SIDES,FINE_LABELS)]
        refinement=fine_e4c(values[0],values[1],values[2],band,center_name)
        levels[str(band+1)]={"band":band+1,"levels":[simple_value(v) for v in values],"E4C":refinement,"qualified":bool(refinement["qualified"]),"trend_value_1_288":values[2]["omega_over_a2_wilson"] if refinement["qualified"] else None}
    return levels

def trs(k,kp):
    rows=[]; maximum=0.0
    for band in BANDS:
        a=k[str(band+1)]["trend_value_1_288"]; b=kp[str(band+1)]["trend_value_1_288"]
        residual=None if a is None or b is None else abs(a+b)
        relative=None if residual is None else residual/max(abs(a),abs(b),1e-15)
        if relative is not None: maximum=max(maximum,relative)
        rows.append({"band":band+1,"K":a,"K_prime":b,"abs_residual":residual,"relative_residual":relative,"status":"PASSED" if relative is not None and relative<=TRS_LIMIT else "FAILED"})
    return {"bands":rows,"max_relative_residual":maximum,"status":"PASSED" if all(row["status"]=="PASSED" for row in rows) else "FAILED"}

def spectrum_record(fr,center_name,center,provider,preflight,cache,counters,tag):
    snap=solve_spectrum(provider,preflight,center,cache,counters,tag)
    f=snap["frequencies"]
    return {"center":center_name,"q":list(center),"frequencies":list(f),"gap21":float(f[1]-f[0]),"gap32":float(f[2]-f[1]),"mpb_fractional_q":snap["record"]["mpb_fractional_q"]}

def self_checks(contract,source,preflight,endpoint0,endpoint04):
    geometries={str(fr):validate_geometry(build_geometry(fr)) for fr in NEW_FR}
    checks={
        "FR_SAMPLE_SET_EXACT":contract["ordered_series"]==["0.0_EXISTING","0.1_NEW","0.2_NEW","0.3_NEW","0.4_EXISTING"],
        "NO_ADAPTIVE_FR_POINTS":contract["new_fr_values"]==[0.1,0.2,0.3],
        "FR0_EVIDENCE_REUSED":sha(ROOT/"audit/e9d/result.json")==FR0_SHA and endpoint0["source"]=="EXISTING_SEALED",
        "FR0P4_EVIDENCE_REUSED":sha(ROOT/"audit/e9e/c1_optimized_fine_stencil_result.json")==FR04_SHA and endpoint04["source"]=="EXISTING_SEALED",
        "CONSTANT_AREA_GEOMETRY":all(g["all_checks_passed"] for g in geometries.values()),
        "C3_SYMMETRY":all(g["checks"]["C3_SYMMETRY"] for g in geometries.values()),
        "PUBLIC_CARTESIAN_GEOMETRY_FIRST":all(g["checks"]["PUBLIC_CARTESIAN_GEOMETRY_FIRST"] for g in geometries.values()),
        "MPB_REAL_SPACE_CONVERSION_EXACTLY_ONCE":all(g["checks"]["MPB_CONVERSION_EXACTLY_ONCE"] for g in geometries.values()),
        "PRELIGHT":bool(preflight.ready) and preflight.round_trip_residual<=1e-12,
        "NO_FR0P5":contract["authorization"]["fr0p5_work"] is False,
        "NO_BERRY_MAP":contract["authorization"]["berry_field_map"] is False,
        "NO_CHERN":contract["authorization"]["valley_chern"] is False and contract["authorization"]["full_bz_chern"] is False and contract["authorization"]["hbz_integration"] is False,
        "NO_PARAMETER_FITTING":contract["authorization"]["parameter_fitting"] is False,
        "SOURCE_BINDING":source["binding_policy"]["source_bound"] is True,
        "PHYSICAL_MODEL":contract["model"]["f_r_range"]==[0.0,0.5] and contract["model"]["solver_tessellation"]==96,
    }
    if not all(checks.values()): raise RuntimeError(f"E9E.E self-check failed: {checks}")
    return checks,geometries

def endpoint_series():
    d0=json.loads((ROOT/"audit/e9d/result.json").read_text(encoding="utf-8-sig"))
    row=next(row for row in d0["numerical_map"] if row["grid_i"]==0 and row["grid_j"]==0)
    bands0=row["bands"]
    d04=json.loads((ROOT/"audit/e9e/c1_optimized_fine_stencil_result.json").read_text(encoding="utf-8-sig"))
    bands04=d04["results"]["R96_TESS96"]["PUBLIC_K_PRIME"]
    f0=[float(b["frequency_at_center"]) for b in bands0]
    w0=[float(b["Omega_over_a2"]) for b in bands0]
    f04=list(map(float,bands04["0"]["levels"][2]["center_frequencies"]))
    w04=[float(bands04[str(b)]["levels"][2]["omega_over_a2_wilson"]) for b in BANDS]
    return {"fr":0.0,"source":"EXISTING_SEALED","center":"PUBLIC_K_PRIME","frequencies":f0,"gap21":f0[1]-f0[0],"gap32":f0[2]-f0[1],"omega_1_36":w0,"omega_1_72":None,"omega_1_144":None,"omega_1_288":None,"e4c":["SEALED_PAPER_STENCIL_ONLY","SEALED_PAPER_STENCIL_ONLY","SEALED_PAPER_STENCIL_ONLY"]},{"fr":0.4,"source":"EXISTING_SEALED","center":"PUBLIC_K_PRIME","frequencies":f04,"gap21":f04[1]-f04[0],"gap32":f04[2]-f04[1],"omega_1_288":w04,"e4c":["SEALED","SEALED","SEALED"]}

def run(output,contract_path):
    started=time.monotonic(); contract=json.loads(contract_path.read_text(encoding="utf-8-sig")); source=json.loads((ROOT/"audit/e9e/e_source_trend_contract.json").read_text(encoding="utf-8-sig")); ep0,ep04=endpoint_series(); preflight=build_triangular_coordinate_preflight(); checks,geometries=self_checks(contract,source,preflight,ep0,ep04); new=[]; control_cache={}; control_counters={"solver_requests":0,"cache_hits":0,"solver_failures":0}
    for fr in NEW_FR:
        provider,geom=make_provider(fr,R96,96); cache={}; counters={"solver_requests":0,"cache_hits":0,"solver_failures":0}; tag=f"fr={fr:.1f}|R96|T96"
        spectra_k=spectrum_record(fr,"PUBLIC_K",K_PUBLIC,provider,preflight,cache,counters,tag); spectra_kp=spectrum_record(fr,"PUBLIC_K_PRIME",KPRIME_PUBLIC,provider,preflight,cache,counters,tag)
        berry_k=berry_center("PUBLIC_K",K_PUBLIC,provider,preflight,cache,counters,tag); berry_kp=berry_center("PUBLIC_K_PRIME",KPRIME_PUBLIC,provider,preflight,cache,counters,tag); tr=trs(berry_k,berry_kp)
        new.append({"fr":fr,"source":"NEW_LIVE","geometry":{"analytic_boundary_digest":geom["analytic_boundary_digest"],"polygon_area":geom["polygon_area"],"analytic_area":geom["analytic_area"],"relative_area_error":geom["relative_area_error_to_analytic"],"c3_symmetry":geom["c3_vertex_symmetry"]},"spectra":{"K":spectra_k,"K_prime":spectra_kp},"berry":{"K":berry_k,"K_prime":berry_kp},"trs":tr,"telemetry":counters})
    # Resolution control at f_r=0.2, K-prime, side 1/144.
    fr=0.2; p64,g64=make_provider(fr,64,96); p96,g96=make_provider(fr,96,96); c64={}; c96={}; res_rows=[]
    for band in BANDS:
        a=fine_evidence(KPRIME_PUBLIC,FINE_SIDES[1],FINE_LABELS[1],band,64,p64,preflight,c64,control_counters,"fr=0.2|R64|T96"); b=fine_evidence(KPRIME_PUBLIC,FINE_SIDES[1],FINE_LABELS[1],band,96,p96,preflight,c96,control_counters,"fr=0.2|R96|T96"); res_rows.append({"band":band+1,"R64":simple_value(a),"R96":simple_value(b),"sign_pattern_stable":a["omega_over_a2_wilson"] is not None and b["omega_over_a2_wilson"] is not None and (a["omega_over_a2_wilson"]>0)==(b["omega_over_a2_wilson"]>0)})
    # Tessellation control at f_r=0.3, R64, K-prime, side 1/144.
    fr=0.3; p48,g48=make_provider(fr,64,48); p96t,g96t=make_provider(fr,64,96); c48={}; c96t={}; tess_rows=[]
    for band in BANDS:
        a=fine_evidence(KPRIME_PUBLIC,FINE_SIDES[1],FINE_LABELS[1],band,64,p48,preflight,c48,control_counters,"fr=0.3|R64|T48"); b=fine_evidence(KPRIME_PUBLIC,FINE_SIDES[1],FINE_LABELS[1],band,64,p96t,preflight,c96t,control_counters,"fr=0.3|R64|T96"); tess_rows.append({"band":band+1,"TESS48":simple_value(a),"TESS96":simple_value(b),"sign_stable":a["omega_over_a2_wilson"] is not None and b["omega_over_a2_wilson"] is not None and (a["omega_over_a2_wilson"]>0)==(b["omega_over_a2_wilson"]>0)})
    payload={"schema":"trilatt_e9e_e_fr_parameter_trend_raw_v1","work_order_id":WORK_ORDER,"base_sandbox_sha":BASE_SANDBOX,"expected_main_head":EXPECTED_MAIN,"calculation_code_git_sha":git_head(),"source_contract_sha256":sha(ROOT/"audit/e9e/e_source_trend_contract.json"),"calculation_contract_sha256":sha(contract_path),"endpoint_series":[ep0,ep04],"endpoint_sha256":{"fr0":FR0_SHA,"fr0p4":FR04_SHA},"source_contract":source,"contract":contract,"self_checks":checks,"geometry_self_checks":geometries,"new_results":new,"resolution_control":{"fr":0.2,"rows":res_rows},"tessellation_control":{"fr":0.3,"rows":tess_rows},"telemetry":{"wall_time_seconds":time.monotonic()-started,"peak_rss_kib":int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),"solver_requests":sum(x["telemetry"]["solver_requests"] for x in new)+control_counters["solver_requests"],"cache_hits":sum(x["telemetry"]["cache_hits"] for x in new)+control_counters["cache_hits"],"solver_failures":sum(x["telemetry"]["solver_failures"] for x in new)+control_counters["solver_failures"]},"berry_field_map":"NOT_AUTHORIZED","fr0p5_work":"NOT_AUTHORIZED","valley_chern":"NOT_AUTHORIZED","full_bz_chern":"NOT_AUTHORIZED","hbz_integration":"NOT_AUTHORIZED","parameter_fitting":"NOT_AUTHORIZED"}
    Path(output).write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8"); return payload

if __name__=="__main__":
    contract_path=ROOT/"audit/e9e/e_parameter_trend_contract.json"
    if "--self-check" in sys.argv:
        c=json.loads(contract_path.read_text(encoding="utf-8-sig")); s=json.loads((ROOT/"audit/e9e/e_source_trend_contract.json").read_text(encoding="utf-8-sig")); ep0,ep04=endpoint_series(); pf=build_triangular_coordinate_preflight(); checks,_=self_checks(c,s,pf,ep0,ep04); print(json.dumps(checks,sort_keys=True))
    else:
        out=Path(sys.argv[sys.argv.index("--output")+1]) if "--output" in sys.argv else ROOT/"audit/e9e/e_raw_result.json"; p=run(out,contract_path); print(json.dumps({"schema":p["schema"],"calculation_code_git_sha":p["calculation_code_git_sha"],"telemetry":p["telemetry"]},sort_keys=True))





