"""E9E.D reducer for bounded f_r=0.4 local Berry maps."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANDS = (0, 1, 2)
TRS_LIMIT = 0.01


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def qualified_value(row):
    return row["qualification_status"] == "QUALIFIED" and row["Omega_over_a2"] is not None


def descriptor(rows, band):
    values = [(row["offset_from_K_prime"], row["bands"][band]["Omega_over_a2"]) for row in rows if qualified_value(row["bands"][band])]
    if not values:
        return {"center_value":None,"max_value":None,"max_location_offset":None,"min_value":None,"min_location_offset":None,"max_abs_value":None,"max_abs_location_offset":None,"positive_pixel_count":0,"negative_pixel_count":0,"reported_pixel_count":0,"unreported_pixel_count":len(rows),"abs_omega_weighted_centroid":None,"abs_omega_second_moment_radius":None}
    center = next((value for offset, value in values if abs(offset[0]) < 1e-15 and abs(offset[1]) < 1e-15), None)
    max_pair = max(values, key=lambda item:item[1])
    min_pair = min(values, key=lambda item:item[1])
    abs_pair = max(values, key=lambda item:abs(item[1]))
    total = sum(abs(value) for _, value in values)
    cx = sum(abs(value) * offset[0] for offset, value in values) / total
    cy = sum(abs(value) * offset[1] for offset, value in values) / total
    moment = math.sqrt(sum(abs(value) * (offset[0]**2 + offset[1]**2) for offset, value in values) / total)
    return {"center_value":center,"max_value":max_pair[1],"max_location_offset":max_pair[0],"min_value":min_pair[1],"min_location_offset":min_pair[0],"max_abs_value":abs_pair[1],"max_abs_location_offset":abs_pair[0],"positive_pixel_count":sum(value>0 for _,value in values),"negative_pixel_count":sum(value<0 for _,value in values),"reported_pixel_count":len(values),"unreported_pixel_count":len(rows)-len(values),"abs_omega_weighted_centroid":[cx,cy],"abs_omega_second_moment_radius":moment}


def compact_band(row):
    return {key:row[key] for key in ("grid_name","grid_i","grid_j","band","public_q","offset_from_K_prime","mpb_fractional_q","center_frequency","minimum_external_gap","E3_status","E4A_status","E4B_status","Wilson_status","Omega_over_a2","Omega_literal_over_a2","qualification_status","failure_reason")}


def shared_distribution(rows):
    shared=[]
    dominant={"1":0,"2":0,"3":0}
    for row in rows:
        if not all(qualified_value(row["bands"][band]) for band in BANDS):
            continue
        values=[row["bands"][band]["Omega_over_a2"] for band in BANDS]
        abs_values=[abs(value) for value in values]
        winner=max(range(3),key=lambda index:abs_values[index])
        dominant[str(winner+1)]+=1
        shared.append({"grid_i":row["grid_i"],"grid_j":row["grid_j"],"public_q":row["public_q"],"absolute_omega":abs_values,"dominant_band":winner+1,"band23_opposite_sign":values[1]*values[2]<0,"band23_both_exceed_band1":abs_values[1]>abs_values[0] and abs_values[2]>abs_values[0]})
    return {"shared_qualified_pixel_count":len(shared),"dominant_band_pixel_counts":dominant,"band23_opposite_sign_pixel_count":sum(row["band23_opposite_sign"] for row in shared),"band23_both_exceed_band1_pixel_count":sum(row["band23_both_exceed_band1"] for row in shared),"shared_pixels":shared}


def reduce_trs(rows):
    result=[]
    maximum=0.0
    for row in rows:
        bands=[]
        for band in BANDS:
            k=row["K"][band]; kp=row["K_prime"][band]
            kval=k["Omega_over_a2"]; kpval=kp["Omega_over_a2"]
            qualified=qualified_value(k) and qualified_value(kp)
            residual=None if not qualified else abs(kval+kpval)
            relative=None if residual is None else residual/max(abs(kval),abs(kpval),1e-15)
            if relative is not None: maximum=max(maximum,relative)
            bands.append({"paper_band":band+1,"K":kval,"K_prime":kpval,"TRS_ABS_RESIDUAL":residual,"TRS_RELATIVE_RESIDUAL":relative,"status":"PASSED" if relative is not None and relative<=TRS_LIMIT else "FAILED"})
        result.append({"offset_in_1_over_72_units":row["offset_in_1_over_72_units"],"bands":bands})
    return result, maximum, all(item["status"]=="PASSED" for row in result for item in row["bands"])


def reduce_r96(rows):
    result=[]
    for row in rows:
        bands=[]
        for band in BANDS:
            r64=row["R64"][band]; r96=row["R96"][band]
            v64=r64["Omega_over_a2"]; v96=r96["Omega_over_a2"]
            bands.append({"paper_band":band+1,"R64_VALUE":v64,"R96_VALUE":v96,"ABS_RESOLUTION_DIFFERENCE":None if v64 is None or v96 is None else abs(v96-v64),"REL_RESOLUTION_DIFFERENCE":None if v64 is None or v96 is None else abs(v96-v64)/max(abs(v64),1e-15),"QUALIFICATION_STATUS_R64":r64["qualification_status"],"QUALIFICATION_STATUS_R96":r96["qualification_status"]})
        result.append({"offset_in_1_over_72_units":row["offset_in_1_over_72_units"],"public_q":row["public_q"],"bands":bands})
    return result


def reduce_tess(rows):
    result=[]
    all_stable=True
    for row in rows:
        per_tess={}; signs=[]; winners=[]
        for tess in (48,96):
            values=[]; qualified=True
            for band in BANDS:
                item=row["tessellations"][str(tess)][band]; values.append(item["Omega_over_a2"]); qualified=qualified and qualified_value(item)
            if qualified:
                signs.append(tuple(1 if value>0 else -1 if value<0 else 0 for value in values)); winners.append(max(range(3),key=lambda index:abs(values[index])))
            per_tess[str(tess)]={"values":values,"qualified":qualified}
        sign_stable=len(signs)==2 and signs[0]==signs[1]
        dominance_stable=len(winners)==2 and winners[0]==winners[1]
        all_stable=all_stable and sign_stable and dominance_stable
        per_tess["sign_stable"]=sign_stable; per_tess["dominant_band_pattern_stable"]=dominance_stable
        result.append({"offset_in_1_over_18_units":row["offset_in_1_over_18_units"],"public_q":row["public_q"],"tessellations":per_tess})
    return result, all_stable


def reduce(raw_path, output_path):
    raw=json.loads(Path(raw_path).read_text(encoding="utf-8-sig"))
    contract=raw["contract"]
    source=raw["source_contract"]
    context=raw["context_map_rows"]; core=raw["core_map_rows"]
    if len(context)!=169 or len(core)!=81: raise RuntimeError("fixed map cardinality violated")
    core_3x3=[row for row in core if abs(row["grid_i"])<=1 and abs(row["grid_j"])<=1]
    core_gate=len(core_3x3)==9 and all(qualified_value(row["bands"][band]) for row in core_3x3 for band in BANDS)
    context_descriptors={f"band_{band+1}":descriptor(context,band) for band in BANDS}
    core_descriptors={f"band_{band+1}":descriptor(core,band) for band in BANDS}
    context_distribution=shared_distribution(context)
    core_distribution=shared_distribution(core)
    trs_rows,max_trs,trs_ok=reduce_trs(raw["trs_rows"])
    r96_rows=reduce_r96(raw["r96_validation_rows"])
    tess_rows,tess_ok=reduce_tess(raw["tessellation_control_rows"])
    replay=raw["exact_k_replay"]; replay_ok=all(item["abs_error"]<=contract["replay"]["tolerance"] for item in replay)
    center=next(row for row in context if row["grid_i"]==0 and row["grid_j"]==0)
    center_values=[center["bands"][band]["Omega_over_a2"] for band in BANDS]
    signs=tuple(1 if value>0 else -1 if value<0 else 0 for value in center_values)
    source_reference=json.loads((ROOT/"audit/e9d/result.json").read_text(encoding="utf-8-sig"))
    source_reference_sha=sha(ROOT/"audit/e9d/result.json")
    source_center=[source_reference["distribution_descriptors"][f"band_{band+1}"]["center_value"] for band in BANDS]
    source_bound=source["binding_policy"]["source_panels_bound"] is True
    band23_opposite=context_distribution["band23_opposite_sign_pixel_count"]>0 and signs[1]*signs[2]<0
    band1_suppressed=abs(center_values[0])<0.5 and abs(source_center[0])>0.5
    band2_reversal=(source_center[1]>0 and center_values[1]<0)
    band23_enhanced=abs(center_values[1])>abs(source_center[1]) and abs(center_values[2])>abs(source_center[2])
    source_classifications={
        "CENTER_SIGN_STRUCTURE":"REPRODUCED" if signs==(-1,-1,1) else "NOT_REPRODUCED",
        "TRIANGLE_PETAL_ISLAND_STRUCTURE":"REPRODUCED" if all(context_descriptors[f"band_{band}"]["reported_pixel_count"]>0 for band in (1,2,3)) and context_descriptors["band_2"]["positive_pixel_count"]>0 and context_descriptors["band_2"]["negative_pixel_count"]>0 and context_descriptors["band_3"]["positive_pixel_count"]>0 and context_descriptors["band_3"]["negative_pixel_count"]>0 else "INSUFFICIENT_SOURCE_SUPPORT",
        "BAND23_OPPOSITE_SIGN_STRUCTURE":"REPRODUCED" if band23_opposite else "NOT_REPRODUCED",
        "PEAK_REGION":"REPRODUCED" if core_descriptors["band_2"]["max_abs_location_offset"] != [0.0,0.0] or core_descriptors["band_3"]["max_abs_location_offset"] != [0.0,0.0] else "INSUFFICIENT_SOURCE_SUPPORT",
        "SPATIAL_CONCENTRATION":"SOURCE_CONSISTENT" if context_descriptors["band_1"]["abs_omega_second_moment_radius"] is not None and context_descriptors["band_2"]["abs_omega_second_moment_radius"] is not None else "INSUFFICIENT_SOURCE_SUPPORT",
        "FR0_TO_FR04_REDISTRIBUTION":"REPRODUCED" if band1_suppressed and band2_reversal and band23_enhanced and band23_opposite else "NOT_REPRODUCED",
        "OVERALL_FR04_DISTRIBUTION_FIDELITY":"SUPPORTED" if source_bound and core_gate and replay_ok and trs_ok and tess_ok else "NOT_SUPPORTED",
        "PAPER_COMPARISON_POLICY":"TREND_FIDELITY_OVER_POINTWISE_NUMERICAL_COINCIDENCE",
    }
    numerical_map=[]
    for grid_name,rows in (("context",context),("core",core)):
        numerical_map.extend({"grid_name":grid_name,"grid_i":row["grid_i"],"grid_j":row["grid_j"],"public_q":row["public_q"],"offset_from_K_prime":row["offset_from_K_prime"],"bands":[compact_band(band) for band in row["bands"]]} for row in rows)
    payload={
        "schema":"trilatt_e9e_d_fr04_local_berry_distribution_result_v1",
        "work_order_id":raw["work_order_id"],"base_sandbox_sha":raw["base_sandbox_sha"],"expected_main_head":raw["expected_main_head"],"calculation_code_git_sha":raw["calculation_code_git_sha"],"contract_sha256":raw["contract_sha256"],"source_contract_sha256":raw["source_contract_sha256"],"raw_result_sha256":sha(raw_path),"source_reference_e9d_result_sha256":source_reference_sha,"source_reference_e9d_work_order":source_reference["work_order_id"],"contract":contract,"source_contract":source,"source_status":raw["source_status"],"self_checks":raw["self_checks"],"geometry":raw["geometry"],"coordinate_preflight":raw["coordinate_preflight"],"map_definition":raw["map_definition"],"distribution_descriptors":{"context":context_descriptors,"core":core_descriptors},"numerical_map":numerical_map,"band_redistribution":{"context":context_distribution,"core":core_distribution},"core_3x3_all_bands_reported":"PASSED" if core_gate else "FAILED","E9E_C_C1_R64_KPRIME_1_144_REPLAY":"PASSED" if replay_ok else "FAILED","exact_k_replay":replay,"r96_validation_center_count":len(r96_rows),"r96_validation":r96_rows,"trs_distribution_control":"PASSED" if trs_ok else "FAILED","max_trs_relative_residual":max_trs,"trs_control":trs_rows,"tessellation_control_point_count":len(tess_rows),"tessellation_sign_structure":"STABLE" if tess_ok else "UNSTABLE","tessellation_control":tess_rows,"source_bound_classifications":source_classifications,"fr0_reference_center_values":source_center,"telemetry":raw["telemetry"],"solver_failures":raw["telemetry"]["solver_failures"],"total_unique_solver_nodes":raw["telemetry"]["solver_requests"],"total_solver_requests":raw["telemetry"]["solver_requests"],"cache_hits":raw["telemetry"]["cache_hits"],"fr0p5_work":"NOT_AUTHORIZED","valley_chern":"NOT_AUTHORIZED","full_bz_chern":"NOT_AUTHORIZED","hbz_integration":"NOT_AUTHORIZED","parameter_sweep":"NOT_AUTHORIZED","production_code_change":False,"main_push":False,"E9E_D_OVERALL":"FR04_LOCAL_BERRY_DISTRIBUTION_READY_FOR_SUPERVISOR_DECISION" if source_bound and core_gate and replay_ok and trs_ok and tess_ok and raw["telemetry"]["solver_failures"]==0 else "FAIL_CLOSED"
    }
    Path(output_path).write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return payload


if __name__=="__main__":
    raw=Path(sys.argv[sys.argv.index("--raw")+1]) if "--raw" in sys.argv else ROOT/"audit/e9e/d_raw_result.json"
    out=Path(sys.argv[sys.argv.index("--output")+1]) if "--output" in sys.argv else ROOT/"audit/e9e/d_result.json"
    payload=reduce(raw,out)
    print(json.dumps({"schema":payload["schema"],"E9E_D_OVERALL":payload["E9E_D_OVERALL"],"raw_result_sha256":payload["raw_result_sha256"]},sort_keys=True))

