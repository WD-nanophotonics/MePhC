"""E9E.E reducer: source-bound numerical f_r trend, not an internal-pass classifier."""
from __future__ import annotations
import hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def sign(v): return 0 if v is None or v==0 else (1 if v>0 else -1)
def monotone(values,increasing): return all((b>=a if increasing else b<=a) for a,b in zip(values,values[1:]))
def trend_direction(values,increasing):
    if monotone(values,increasing): return "REPRODUCED"
    endpoint=(values[-1]>=values[0]) if increasing else (values[-1]<=values[0])
    directional=sum((b>=a if increasing else b<=a) for a,b in zip(values,values[1:]))
    return "NUMERICALLY_NONMONOTONIC_BUT_SOURCE_DIRECTION_SUPPORTED" if endpoint and directional>=2 else "NOT_REPRODUCED"
def reduce(raw_path,out_path):
    raw=json.loads(Path(raw_path).read_text(encoding="utf-8-sig")); c=raw["contract"]
    ep0,ep04=raw["endpoint_series"]
    ordered=[ep0]
    for item in raw["new_results"]:
        kp=item["berry"]["K_prime"]
        ordered.append({"fr":item["fr"],"source":"NEW_LIVE","gap21":item["spectra"]["K"]["gap21"],"gap32":item["spectra"]["K"]["gap32"],"omega_1_72":[kp[str(b)]["levels"][0]["omega_over_a2_wilson"] if kp[str(b)]["levels"][0]["qualified"] else None for b in range(3)],"omega_1_144":[kp[str(b)]["levels"][1]["omega_over_a2_wilson"] if kp[str(b)]["levels"][1]["qualified"] else None for b in range(3)],"omega_1_288":[kp[str(b)]["levels"][2]["omega_over_a2_wilson"] if kp[str(b)]["levels"][2]["qualified"] else None for b in range(3)],"E4C":["PASSED" if kp[str(b)]["E4C"]["qualified"] else "FAILED" for b in range(3)],"trs_max_relative_residual":item["trs"]["max_relative_residual"],"qualification_all":all(kp[str(b)]["qualified"] for b in range(3))})
    ordered.append({"fr":ep04["fr"],"source":"EXISTING_SEALED","gap21":ep04["gap21"],"gap32":ep04["gap32"],"omega_1_72":None,"omega_1_144":None,"omega_1_288":ep04["omega_1_288"],"E4C":ep04["e4c"],"trs_max_relative_residual":None,"qualification_all":True})
    # f_r=0 has a sealed 1/36 anchor, not a new fine-ladder calculation.
    omega_final=[item["omega_1_288"] if item["omega_1_288"] is not None else item.get("omega_1_36") for item in ordered]
    gap21=[item["gap21"] for item in ordered]; gap32=[item["gap32"] for item in ordered]
    b1=[v[0] for v in omega_final]; b2=[v[1] for v in omega_final]; b3=[v[2] for v in omega_final]
    frs=[item["fr"] for item in ordered]
    sign_change_brackets=[]
    for left,right in zip(ordered,ordered[1:]):
        a=left["omega_1_288"][1] if left["omega_1_288"] is not None else left.get("omega_1_36",[None,None,None])[1]
        b=right["omega_1_288"][1] if right["omega_1_288"] is not None else right.get("omega_1_36",[None,None,None])[1]
        if a is not None and b is not None and a*b<0: sign_change_brackets.append([left["fr"],right["fr"]])
    res_rows=raw["resolution_control"]["rows"]
    res_sign=all(row["sign_pattern_stable"] and row["R64"]["qualification_status"]=="QUALIFIED" and row["R96"]["qualification_status"]=="QUALIFIED" for row in res_rows)
    tess_rows=raw["tessellation_control"]["rows"]
    tess_sign=all(row["sign_stable"] and row["TESS48"]["qualification_status"]=="QUALIFIED" and row["TESS96"]["qualification_status"]=="QUALIFIED" for row in tess_rows)
    tess_dom=all(max(range(3),key=lambda i:abs(row["TESS48"]["omega_over_a2_wilson"]))==max(range(3),key=lambda i:abs(row["TESS96"]["omega_over_a2_wilson"])) for row in tess_rows)
    all_e4c=all(item["qualification_all"] for item in ordered if item["source"]=="NEW_LIVE")
    classifications={
      "OMEGA1_APPROACHES_ZERO":"REPRODUCED" if abs(b1[-1])<abs(b1[0]) else "NOT_REPRODUCED",
      "BAND2_POSITIVE_AT_FR0P1":"REPRODUCED" if b2[1]>0 else "NOT_REPRODUCED",
      "BAND2_SIGN_CHANGE_OVER_0P1_TO_0P4":"REPRODUCED" if b2[1]>0 and b2[-1]<0 else "NOT_REPRODUCED",
      "BAND2_SIGN_CHANGE_SAMPLE_BRACKET":sign_change_brackets if sign_change_brackets else "NOT_BRACKETED",
      "BAND2_NEGATIVE_ENHANCEMENT":"REPRODUCED" if b2[-1]<0 and abs(b2[-1])>abs(b2[1]) else "NOT_REPRODUCED",
      "BAND3_POSITIVE_ENHANCEMENT":"REPRODUCED" if b3[-1]>b3[1]>0 else "NOT_REPRODUCED",
      "GAP21_EVOLUTION":trend_direction(gap21,True),
      "GAP32_EVOLUTION":trend_direction(gap32,False),
      "BAND23_DOMINANCE_EMERGENCE":"REPRODUCED" if abs(b2[-1])>abs(b1[-1]) and abs(b3[-1])>abs(b1[-1]) else "NOT_REPRODUCED",
      "AT_K_PARAMETER_EVOLUTION":"SUPPORTED" if all_e4c and res_sign and tess_sign and tess_dom else "NOT_SUPPORTED",
    }
    payload={"schema":"trilatt_e9e_e_fr_parameter_trend_result_v1","work_order_id":raw["work_order_id"],"base_sandbox_sha":raw["base_sandbox_sha"],"expected_main_head":raw["expected_main_head"],"calculation_code_git_sha":raw["calculation_code_git_sha"],"source_contract_sha256":raw["source_contract_sha256"],"calculation_contract_sha256":raw["calculation_contract_sha256"],"raw_result_sha256":sha(raw_path),"endpoint_sha256":raw["endpoint_sha256"],"source_contract":raw["source_contract"],"contract":c,"self_checks":raw["self_checks"],"ordered_series":ordered,"all_new_fr_all_three_bands_e4c":all_e4c,"resolution_control":raw["resolution_control"],"FR0P2_RESOLUTION_SIGN_PATTERN_STABLE":res_sign,"tessellation_control":raw["tessellation_control"],"FR0P3_TESSELLATION_SIGN_PATTERN_STABLE":tess_sign,"FR0P3_TESSELLATION_DOMINANCE_STABLE":tess_dom,"source_trend_classification":classifications,"source_trend_classification_uses_numerical_series":True,"paper_comparison_policy":"TREND_FIDELITY_OVER_POINTWISE_NUMERICAL_COINCIDENCE","telemetry":raw["telemetry"],"fr0p5_work":"NOT_AUTHORIZED","berry_field_map":"NOT_AUTHORIZED","valley_chern":"NOT_AUTHORIZED","full_bz_chern":"NOT_AUTHORIZED","E9E_E_OVERALL":"SOURCE_BOUND_FR_AT_K_PARAMETER_EVOLUTION_READY_FOR_SUPERVISOR_DECISION" if classifications["AT_K_PARAMETER_EVOLUTION"]=="SUPPORTED" else "FAIL_CLOSED"}
    Path(out_path).write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8"); return payload
if __name__=="__main__":
    raw=Path(sys.argv[sys.argv.index("--raw")+1]) if "--raw" in sys.argv else ROOT/"audit/e9e/e_raw_result.json"; out=Path(sys.argv[sys.argv.index("--output")+1]) if "--output" in sys.argv else ROOT/"audit/e9e/e_result.json"; p=reduce(raw,out); print(json.dumps({"schema":p["schema"],"E9E_E_OVERALL":p["E9E_E_OVERALL"],"raw_result_sha256":p["raw_result_sha256"]},sort_keys=True))
