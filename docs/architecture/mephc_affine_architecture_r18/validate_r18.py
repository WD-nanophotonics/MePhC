#!/usr/bin/env python3
import argparse, hashlib, json, sys
from pathlib import Path
EXPECTED_SHA="393a40c2da894669515384939b6828d654f5d11738dc3f6e930ba6d0d129152e"
REQ=["README.md","authoritative_contract.json","contract_preflight.json","preflight.json","protected_digest_check.json","r17_inheritance.json","r17_gate_reconstruction.json","r17_logic_discrepancy.json","corrected_uncertainty_branches.json","cross_ensemble_pair.json","cross_ensemble_full.json","cross_ensemble_uniform.json","cross_direction_consistency.json","evidence_classification.json","next_method_recommendation.md","next_method_recommendation.json","mechanism_adjudication.json","solver_execution.json","change_scope.json","trilatt_hold.json","test_coverage.csv","validation_report.md","known_limits.md","run_r18.py","validate_r18.py","validator_negative_fixtures.py"]
def j(r,n): return json.loads((r/n).read_text())
def validate(r):
 e=[]
 for n in REQ:
  if not (r/n).is_file(): e.append("missing "+n)
 if e:return e
 c=j(r,"authoritative_contract.json");
 if hashlib.sha256((r/"authoritative_contract.json").read_bytes()).hexdigest()!=EXPECTED_SHA:e.append("contract SHA")
 if c["starting_refs"]["MePhC"]!="7606b4534ee245ae4546a82f88af04e7b6bd6762":e.append("ref")
 if j(r,"contract_preflight.json")["byte_exact"] is not True:e.append("preflight")
 if j(r,"solver_execution.json")["fresh_solver_calls"]!=0 or j(r,"solver_execution.json")["trilatt_solver_calls"]!=0:e.append("solver")
 if j(r,"change_scope.json")["r17_immutable"] is not True or j(r,"change_scope.json")["r19_authorized"] is not False:e.append("scope")
 g=j(r,"r17_gate_reconstruction.json");
 if set(g["conditions"])!=set(j(r,"uniform_artifact_transferability.json")["gate_conditions"] if False else g["conditions"]):e.append("gate incomplete")
 if not all(g["conditions"].values()) or g["label"]!="R17_TRANSFERABILITY_GATE_LOGIC_BUG_CONFIRMED" or g["derived_RAW_UNIFORM_STRESS_NONTRANSFERABLE_CORRECTED"] is not True:e.append("gate logic")
 d=j(r,"r17_logic_discrepancy.json")
 if d["protected_top_level_RAW_UNIFORM_STRESS_NONTRANSFERABLE"] is not False or d["corrected_flag"] is not True:e.append("discrepancy")
 b=j(r,"corrected_uncertainty_branches.json")["branches"]
 if set(b)!={"estimator_matched","literal_raw_uniform_stress"}:e.append("branches")
 for x in b.values():
  if x["pair_5x"] or x["full_5x"]:e.append("forbidden 5x")
 m=j(r,"mechanism_adjudication.json")
 if m["scientific_terminal_state"]!="CLOSED_R17_LOGIC_CORRECTIVE_QUADRATIC_EVIDENCE_SYNTHESIZED":e.append("terminal")
 if m["R17_terminal_unchanged"] is not True:e.append("R17 rewritten")
 if j(r,"evidence_classification.json")["classification"] not in c["classifications"]:e.append("classification")
 if j(r,"next_method_recommendation.json")["recommendation"] not in c["next_method_labels"]:e.append("recommendation")
 if j(r,"completion.json") if (r/"completion.json").exists() else False:
  z=j(r,"completion.json");
  if z.get("seal_status")!="SEALED" or z.get("fresh_solver_calls")!=0:e.append("seal")
 return e
def main():
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=Path(__file__).parent);a=validate(p.parse_args().root.resolve())
 if a:
  print(json.dumps({"status":"FAIL","errors":a},sort_keys=True));return 1
 print(json.dumps({"status":"PASS","root":str(p.parse_args().root.resolve())},sort_keys=True));return 0
if __name__=="__main__":sys.exit(main())
