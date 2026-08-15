#!/usr/bin/env python3
import argparse,hashlib,json,sys
from pathlib import Path
SHA="c5678f4d3a0f3ce7afa293b21fe218833a3a293b5f05e4ff97c398ecc60e4e42"
REQ=["README.md","authoritative_contract.json","contract_preflight.json","preflight.json","protected_digest_check.json","r18_inheritance.json","fdfd_method.md","fdfd_operator_definition.json","geometry_rasterization_method.json","bloch_boundary_definition.json","frozen_call_plan.json","baseline_raw_spectra.json","baseline_validation.json","operator_validation.json","fdfd_raw_spectra.json","pair_Q_and_secants.json","full_Q_and_secants.json","uniform_Q_and_secants.json","pair_alpha_fit.json","full_alpha_fit.json","uniform_alpha_fit.json","fdfd_uncertainty.json","band_identity_guard.json","mpb_comparison.json","cross_direction_consistency.json","mechanism_adjudication.json","solver_execution.json","change_scope.json","trilatt_hold.json","test_coverage.csv","validation_report.md","known_limits.md","run_r19.py","validate_r19.py","validator_negative_fixtures.py"]
def j(r,n):return json.loads((r/n).read_text())
def validate(r):
 e=[]
 for n in REQ:
  if not (r/n).is_file():e.append("missing "+n)
 if e:return e
 c=j(r,"authoritative_contract.json")
 if hashlib.sha256((r/"authoritative_contract.json").read_bytes()).hexdigest()!=SHA:e.append("contract SHA")
 if c["starting_refs"]["MePhC"]!="6fe1b1fd61d40ef9b2083223a2b8dc591f3c4be0":e.append("ref")
 if j(r,"contract_preflight.json")["byte_exact"] is not True:e.append("preflight")
 if j(r,"solver_execution.json")["fresh_solver_calls"] not in (6,102):e.append("call count")
 if j(r,"solver_execution.json")["mpb_or_meep_independent_solver_calls"]!=0:e.append("forbidden solver")
 if j(r,"change_scope.json")["production_changes"] or j(r,"change_scope.json")["r20_authorized"] is not False:e.append("scope")
 if j(r,"fdfd_operator_definition.json")["face_average"]!="harmonic" or j(r,"fdfd_operator_definition.json")["hermiticity_tolerance"]!=1e-12:e.append("operator contract")
 bd=j(r,"bloch_boundary_definition.json")
 if bd["q2"]!=[-0.09,0.14] or bd["plus_x"]!="exp(+i*2*pi*qx)" or bd["plus_y"]!="exp(+i*2*pi*qy)" or bd["reverse"]!="complex_conjugate":e.append("bloch contract")
 b=j(r,"baseline_validation.json")
 if not b["all_pass"]:e.append("baseline failed")
 p=j(r,"frozen_call_plan.json")
 if p["stage_A_calls"]!=6 or p["stage_B_calls"]!=96 or len(p["calls"])!=102:e.append("plan")
 if not p["no_adaptation"] or p["no_retries"] is not True:e.append("adaptive plan")
 g=j(r,"band_identity_guard.json")
 if g["pass"] is not True:e.append("band identity")
 u=j(r,"fdfd_uncertainty.json")
 for d in ("pair","full"):
  if len(u[d]["components"])!=7:e.append("uncertainty components")
  if "mpb" in json.dumps(u[d]).lower():e.append("MPB uncertainty")
 s=j(r,"mechanism_adjudication.json")
 if s["scientific_terminal_state"] not in c["terminal_states"]:e.append("terminal")
 if s["fresh_solver_calls"]!=102:e.append("science not complete")
 cross=j(r,"mpb_comparison.json")
 if s["scientific_terminal_state"]=="CLOSED_INDEPENDENT_FDFD_QUADRATIC_CROSSCHECK_SUPPORTED":
  if cross["pair_within_35pct"] is not True or cross["full_within_35pct"] is not True:e.append("cross method")
  if cross["relation_pass"] is not True:e.append("cross direction")
 elif s["scientific_terminal_state"]=="BLOCKED_FDFD_CROSS_METHOD_DISAGREEMENT":
  if cross["pair_same_sign"] is not True or cross["full_same_sign"] is not True:e.append("cross sign")
 if (r/"completion.json").exists():
  z=j(r,"completion.json")
  if z["seal_status"]!="SEALED" or z["r20_authorized"] is not False:e.append("seal")
 return e
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,default=Path(__file__).parent);r=ap.parse_args().root.resolve();e=validate(r)
 if e:print(json.dumps({"status":"FAIL","errors":e},sort_keys=True));return 1
 print(json.dumps({"status":"PASS","root":str(r)},sort_keys=True));return 0
if __name__=="__main__":sys.exit(main())
