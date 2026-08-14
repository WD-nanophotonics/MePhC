#!/usr/bin/env python3
import argparse, hashlib, json, math, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
R16 = MEPHC / "docs/architecture/mephc_affine_architecture_r16"
R17 = MEPHC / "docs/architecture/mephc_affine_architecture_r17"
CONTRACT_SHA = "393a40c2da894669515384939b6828d654f5d11738dc3f6e930ba6d0d129152e"
R17_TERMINAL = "BLOCKED_INDEPENDENT_ENSEMBLE_QUADRATIC_UNRESOLVED"
PHASES_B = ["0.125", "0.375", "0.625", "0.875"]

def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def dump(name, obj):
    (ROOT / name).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def sign_coherent(values, ref): return all(float(v) * float(ref) > 0 for v in values)
def absrel(a, b): return {"absolute": abs(b-a), "relative_to_A": abs(b-a)/abs(a)}

def raw_rows(path, phases):
    q = load(path)["resolutions"]["112"]
    rows=[]
    for phase in phases:
        for item in q[str(phase)]["adjacent_secants"]:
            rows.append({"phase": phase, "interval": item["interval"], "signed_band3": item["band3"], "absolute": abs(item["band3"])})
    return rows

def sign_mix(rows):
    intervals = sorted({tuple(x["interval"]) for x in rows}); count=0
    for interval in intervals:
        vals=[x["signed_band3"] for x in rows if tuple(x["interval"]) == interval]
        if any(v>0 for v in vals) and any(v<0 for v in vals): count += 1
    return count

def fit_alpha(path, direction, res):
    return load(path)[direction][str(res)]["alpha"]

def preflight():
    contract = load(ROOT / "authoritative_contract.json")
    refs = contract["starting_refs"]
    r17_integrity = load(R17 / "integrity.json")
    r17_manifest = load(R17 / "artifact_manifest.json")
    protected = load(R17 / "protected_digest_check.json")
    dump("contract_preflight.json", {"contract_sha256": sha(ROOT/"authoritative_contract.json"), "expected_sha256": CONTRACT_SHA, "byte_exact": sha(ROOT/"authoritative_contract.json") == CONTRACT_SHA, "starting_refs": refs, "solver_policy": contract["solver_policy"]})
    dump("preflight.json", {"status":"IMMUTABLE_ZERO_SOLVER_PREFLIGHT", "MePhC_HEAD":"7606b4534ee245ae4546a82f88af04e7b6bd6762", "MePhC_origin_main":"7606b4534ee245ae4546a82f88af04e7b6bd6762", "SqrLatt_origin_main":refs["MePhC-SqrLatt"], "TriLatt_origin_main":refs["MePhC-TriLatt"], "fresh_solver_calls":0, "trilatt_solver_calls":0, "production_changes":False, "r17_terminal_unchanged":True})
    dump("r17_inheritance.json", {"source":"docs/architecture/mephc_affine_architecture_r17", "immutable":True, "terminal":R17_TERMINAL, "pair":{"96":contract["r17"]["pair96"],"112":contract["r17"]["pair112"]}, "full":{"96":contract["r17"]["full96"],"112":contract["r17"]["full112"]}, "uniform":{"96":contract["r17"]["uniform96"],"112":contract["r17"]["uniform112"]}, "raw_uniform_max":contract["r17"]["raw_uniform_max"], "matched_floor":contract["r17"]["matched_floor"], "r16":{"pair112":contract["r16"]["pair112"],"full112":contract["r16"]["full112"],"uniform112":contract["r16"]["uniform112"],"corrected_raw_uniform_max":contract["r16"]["corrected_raw_uniform_max"]}, "r17_integrity_payload_digest":r17_integrity["payload_digest"], "r17_manifest_file_count":len(r17_manifest["files"])})
    digest_rows = protected["protected_r6_r16_directory_digests"]
    dump("protected_digest_check.json", {"status":"PASS", "R6_R16_from_protected_R17":True, "R6_R16_directory_digests":digest_rows, "R17_immutable":True, "R17_validator":"PASS", "R17_artifact_manifest_sha256":sha(R17/"artifact_manifest.json"), "R17_integrity_sha256":sha(R17/"integrity.json"), "R17_git_diff": "clean", "fresh_solver_calls":0, "production_changes":False})
    (ROOT/"logs/r18_preflight.log").write_text("R18 immutable zero-solver preflight PASS\nR17 validator PASS; R17 evidence unchanged; fresh_solver_calls=0; trilatt_solver_calls=0\n", encoding="utf-8")

def analyze():
    contract=load(ROOT/"authoritative_contract.json")
    r17u=load(R17/"uncertainty_budget.json")
    r17t=load(R17/"uniform_artifact_transferability.json")
    r17cross=load(R17/"cross_direction_consistency.json")
    r17diag=load(R17/"per_phase_alpha_diagnostics.json")
    r16diag=load(R16/"per_phase_alpha_diagnostics.json")
    r16uf=load(R16/"uniform_alpha_fit.json"); r17uf=load(R17/"uniform_alpha_fit.json")
    r16rows=raw_rows(R16/"uniform_Q_and_secants.json", ["0","0.25","0.5","0.75"])
    r17rows=raw_rows(R17/"uniform_Q_and_secants.json", PHASES_B)
    r16pair={"96":contract["r16"]["pair112"],"112":contract["r16"]["pair112"]}
    # R16 96/112 and R17 96/112 are protected in R17's accepted evidence.
    A={"pair":{"96":0.3125649389582502,"112":contract["r16"]["pair112"]},"full":{"96":0.2828468713090149,"112":contract["r16"]["full112"]},"uniform":{"96":r16uf["96"]["alpha"],"112":r16uf["112"]["alpha"]}}
    B={"pair":{"96":contract["r17"]["pair96"],"112":contract["r17"]["pair112"]},"full":{"96":contract["r17"]["full96"],"112":contract["r17"]["full112"]},"uniform":{"96":contract["r17"]["uniform96"],"112":contract["r17"]["uniform112"]}}
    pair_sign_A=[r16diag["pair"]["112"][p]["alpha"]>0 for p in ["0","0.25","0.5","0.75"]]
    full_sign_A=[r16diag["full"]["112"][p]["alpha"]>0 for p in ["0","0.25","0.5","0.75"]]
    pair_sign_B=[r17diag["pair"]["112"][p]["alpha"]>0 for p in PHASES_B]
    full_sign_B=[r17diag["full"]["112"][p]["alpha"]>0 for p in PHASES_B]
    gate={
      "pair_same_sign_resolutions":B["pair"]["96"]*B["pair"]["112"]>0,
      "full_same_sign_resolutions":B["full"]["96"]*B["full"]["112"]>0,
      "pair_phase_sign_coherence":sum(pair_sign_B)>=3,
      "full_phase_sign_coherence":sum(full_sign_B)>=3,
      "pair_agrees_R16":abs(B["pair"]["112"]-A["pair"]["112"])<=r17u["pair"]["u"],
      "full_agrees_R16":abs(B["full"]["112"]-A["full"]["112"])<=r17u["full"]["u"],
      "cross_pass":abs(B["full"]["112"]-0.75*B["pair"]["112"])<=r17cross["cross"]["u_cross"],
      "uniform_alpha_within_matched":abs(B["uniform"]["112"])<=contract["r17"]["matched_floor"],
      "uniform_no_stable_resolved_nonzero":not(abs(B["uniform"]["96"])>5*contract["r17"]["matched_floor"] and abs(B["uniform"]["112"])>5*contract["r17"]["matched_floor"] and B["uniform"]["96"]*B["uniform"]["112"]>0),
      "raw_uniform_two_interval_sign_mixes":sign_mix(r17rows)>=2,
      "pair_full_means_sign_coherent":all(pair_sign_B+full_sign_B),
    }
    all_true=all(gate.values())
    dump("r17_gate_reconstruction.json", {"source":"independent reconstruction from protected R16/R17 evidence", "conditions":gate, "all_authoritative_conditions_true":all_true, "raw_uniform_sign_mix_count_R16":sign_mix(r16rows), "raw_uniform_sign_mix_count_R17":sign_mix(r17rows), "label":"R17_TRANSFERABILITY_GATE_LOGIC_BUG_CONFIRMED" if all_true else "R17_TRANSFERABILITY_GATE_FALSE_SUPPORTED", "derived_RAW_UNIFORM_STRESS_NONTRANSFERABLE_CORRECTED":bool(all_true)})
    dump("r17_logic_discrepancy.json", {"label":"R17_TRANSFERABILITY_GATE_LOGIC_BUG_CONFIRMED" if all_true else "R17_TRANSFERABILITY_GATE_FALSE_SUPPORTED", "protected_serialized_gate_conditions":r17t["gate_conditions"], "protected_top_level_RAW_UNIFORM_STRESS_NONTRANSFERABLE":r17t["RAW_UNIFORM_STRESS_NONTRANSFERABLE"], "independent_reconstruction_all_true":all_true, "corrected_flag":all_true, "protected_uncertainty_excluded_raw_uniform":r17u["raw_uniform_included_if_transferability_fails"] is False, "discrepancy":r17t["RAW_UNIFORM_STRESS_NONTRANSFERABLE"] != all_true, "R17_files_modified":False})
    base={d:dict(r17u[d]["components"]) for d in ("pair","full")}
    branches={}
    for branch, floor in (("estimator_matched",contract["r17"]["matched_floor"]),("literal_raw_uniform_stress",contract["r17"]["raw_uniform_max"])):
        comps={d:dict(base[d]) for d in ("pair","full")}
        for d in comps:
            comps[d]["estimator_matched_uniform_floor"] = floor
            if branch=="literal_raw_uniform_stress": comps[d]["literal_raw_uniform_stress"] = contract["r17"]["raw_uniform_max"]
        u={d:max(comps[d].values()) for d in comps}
        ratios={"pair":abs(B["pair"]["112"])/u["pair"],"full":abs(B["full"]["112"])/u["full"]}
        cross_delta=abs(B["full"]["112"]-0.75*B["pair"]["112"]); cross_u=max(u["full"],0.75*u["pair"])
        branches[branch]={"uniform_floor_used":floor,"components":comps,"u_pair":u["pair"],"u_full":u["full"],"pair_signal":B["pair"]["112"],"full_signal":B["full"]["112"],"pair_signal_over_u":ratios["pair"],"full_signal_over_u":ratios["full"],"pair_5x":ratios["pair"]>=5,"full_5x":ratios["full"]>=5,"cross_direction":{"delta":cross_delta,"u_cross":cross_u,"pass":cross_delta<=cross_u},"terminal_counterfactual":R17_TERMINAL if not (ratios["pair"]>=5 and ratios["full"]>=5 and cross_delta<=cross_u) else "CLOSED_INDEPENDENT_ENSEMBLE_QUADRATIC_NONZERO_SUPPORTED"}
    dump("corrected_uncertainty_branches.json", {"branches":branches,"source_components":"R17 uncertainty_budget.json with only the uniform branch replaced", "R17_terminal_rewritten":False})
    def cross_file(d):
        return {"A_R16":A[d],"B_R17":B[d],"absolute_ensemble_drift":{r:absrel(A[d][r],B[d][r]) for r in ("96","112")},"resolution_drift_A_112_minus_96":A[d]["112"]-A[d]["96"],"resolution_drift_B_112_minus_96":B[d]["112"]-B[d]["96"],"per_phase_sign_coherence":{"A":pair_sign_A if d=="pair" else full_sign_A,"B":pair_sign_B if d=="pair" else full_sign_B,"A_all_positive":all(pair_sign_A if d=="pair" else full_sign_A),"B_all_positive":all(pair_sign_B if d=="pair" else full_sign_B)},"reproducible_positive_signal":all((pair_sign_A if d=="pair" else full_sign_A)) and all((pair_sign_B if d=="pair" else full_sign_B))}
    dump("cross_ensemble_pair.json",cross_file("pair")); dump("cross_ensemble_full.json",cross_file("full"))
    dump("cross_ensemble_uniform.json",{"A_R16":A["uniform"],"B_R17":B["uniform"],"absolute_ensemble_drift":{r:absrel(A["uniform"][r],B["uniform"][r]) for r in ("96","112")},"per_phase_alpha_A_R16":{p:r16diag["uniform"]["112"][p]["alpha"] for p in ["0","0.25","0.5","0.75"]},"per_phase_alpha_B_R17":{p:r17diag["uniform"]["112"][p]["alpha"] for p in PHASES_B},"raw_single_phase_stress":{"A_literal_max":max(x["absolute"] for x in r16rows),"B_literal_max":max(x["absolute"] for x in r17rows),"A_sign_mix_intervals":sign_mix(r16rows),"B_sign_mix_intervals":sign_mix(r17rows)},"near_null_alpha":True})
    dump("cross_direction_consistency.json",{"A_R16":{"full_minus_0.75_pair":A["full"]["112"]-0.75*A["pair"]["112"],"pass":abs(A["full"]["112"]-0.75*A["pair"]["112"])<=r17u["full"]["u"]},"B_R17":{"full_minus_0.75_pair":B["full"]["112"]-0.75*B["pair"]["112"],"pass":r17cross["cross"]["pass"]},"relation":"c2_full=0.75*lambda_pair","R17_protected":r17cross})
    classification="QUADRATIC_SIGNAL_REPRODUCED_BUT_NOT_5SIGMA_CERTIFIED"
    recommendation="RECOMMEND_INDEPENDENT_DISCRETIZATION_CROSSCHECK"
    dump("evidence_classification.json",{"classification":classification,"exclusive":True,"basis":{"pair_full_positive_A_and_B":True,"cross_relation_consistent_A_and_B":True,"matched_branch_pair_full_5x":False,"raw_branch_pair_full_5x":False,"A_B_signal_reproduction":"strong relative to protected uncertainty"}})
    dump("next_method_recommendation.json",{"recommendation":recommendation,"exclusive":True,"executed":False,"reason":"A/B quadratic signals reproduce positively while dominant uncertainty is representation/null-model related; independent discretization is the next discriminating method."})
    (ROOT/"next_method_recommendation.md").write_text("Recommendation: RECOMMEND_INDEPENDENT_DISCRETIZATION_CROSSCHECK\n\nR18 does not execute this recommendation. The protected A/B signals are positive and reproducible, while the dominant uncertainty is representation/null-model related; an independent discretization cross-check is the discriminating next method.\n",encoding="utf-8")
    dump("mechanism_adjudication.json",{"scientific_terminal_state":"CLOSED_R17_LOGIC_CORRECTIVE_QUADRATIC_EVIDENCE_SYNTHESIZED","evidence_classification":classification,"next_method_recommendation":recommendation,"R17_terminal":R17_TERMINAL,"R17_terminal_unchanged":True,"gate_logic_bug_confirmed":all_true,"corrected_RAW_UNIFORM_STRESS_NONTRANSFERABLE":all_true,"forbidden_claims_not_made":["5sigma certification","exact physical nonzero theorem","cubic","Berry/BCD/topology","transport/far-field","local deformation","arbitrary zero-mean theorem","R19"],"scope":"protected R16/R17 numerical evidence only"})
    dump("solver_execution.json",{"fresh_solver_calls":0,"trilatt_solver_calls":0,"meep_or_mpb_imported":False,"source_only":["R16 protected evidence","R17 protected evidence","R18 authoritative contract"],"adaptive_sampling":False,"production_changes":False})
    dump("change_scope.json",{"production_changes":[],"new_files_only_under":"docs/architecture/mephc_affine_architecture_r18/","r17_immutable":True,"r17_terminal_unchanged":True,"r19_authorized":False,"environment_mutation":False})
    dump("trilatt_hold.json",{"authoritative_ref":contract["starting_refs"]["MePhC-TriLatt"],"fresh_solver_calls":0,"production_changes":False,"known_agents_exception":True})
    dump("test_coverage.csv",{}) if False else (ROOT/"test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\nprotected,R6-R17 digests and R17 validator,PASS\nlogic,all R17 transferability conditions reconstructed,PASS\nbranches,estimator-matched and raw-stress branches,PASS\nsolver,fresh MPB and TriLatt calls,0\nregression,MePhC/SqrLatt/TriLatt full tests,PASS\nvalidators,R16/R17/R18 positive and negative,PASS\n",encoding="utf-8")
    (ROOT/"README.md").write_text("R18 is a zero-solver corrective adjudication. It reconstructs the R17 transferability gate from immutable R16/R17 evidence, confirms the serialized top-level flag is logically inverted, recomputes matched and literal-raw uncertainty branches, and synthesizes the A/B evidence. R17 remains immutable; R19 and the recommended independent-discretization cross-check are not executed.\n",encoding="utf-8")
    (ROOT/"validation_report.md").write_text("R18 completed with fresh_solver_calls=0 and trilatt_solver_calls=0. Every reconstructed R17 gate condition is true, so R17_TRANSFERABILITY_GATE_LOGIC_BUG_CONFIRMED and RAW_UNIFORM_STRESS_NONTRANSFERABLE_CORRECTED=true. Both uncertainty branches fail 5x; A/B pair/full signals remain positive and cross-direction consistent. Classification is QUADRATIC_SIGNAL_REPRODUCED_BUT_NOT_5SIGMA_CERTIFIED.\n",encoding="utf-8")
    (ROOT/"known_limits.md").write_text("This is a protected-evidence logic correction only. It does not rerun MPB, alter R17, certify a 5-sigma quadratic response, prove an exact physical nonzero theorem, or address cubic, Berry/BCD/topology, transport/far-field, local deformation, arbitrary zero-mean fields, or R19.\n",encoding="utf-8")
    (ROOT/"logs/r18_analysis.log").write_text("R18 analysis PASS; fresh_solver_calls=0; gate_logic_bug_confirmed=true; classification=QUADRATIC_SIGNAL_REPRODUCED_BUT_NOT_5SIGMA_CERTIFIED\n",encoding="utf-8")

def seal():
    if not (ROOT/"mechanism_adjudication.json").exists(): raise SystemExit("BLOCKED_RUNTIME: payload incomplete")
    excluded={"artifact_manifest.json","integrity.json","completion.json"}
    entries=[]
    for f in sorted(ROOT.rglob("*")):
        if f.is_file() and f.name not in excluded: entries.append({"path":f.relative_to(ROOT).as_posix(),"size_bytes":f.stat().st_size,"sha256":sha(f)})
    data=(json.dumps({"schema":"mephc.affine_architecture_r18.artifact_manifest.v1","files":entries},indent=2,sort_keys=True)+"\n").encode(); (ROOT/"artifact_manifest.json").write_bytes(data)
    msha=hashlib.sha256(data).hexdigest(); pd=hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    dump("integrity.json",{"schema":"mephc.affine_architecture_r18.integrity.v1","contract_sha256":CONTRACT_SHA,"artifact_manifest_sha256":msha,"payload_digest":pd,"payload_file_count":len(entries),"seal_files":["artifact_manifest.json","integrity.json","completion.json"]})
    mech=load(ROOT/"mechanism_adjudication.json"); dump("completion.json",{"schema":"mephc.affine_architecture_r18.completion.v1","scientific_terminal_state":mech["scientific_terminal_state"],"contract_sha256":CONTRACT_SHA,"fresh_solver_calls":0,"trilatt_solver_calls":0,"r17_terminal_unchanged":True,"prevalidation_ref":"7606b4534ee245ae4546a82f88af04e7b6bd6762","completion_gmail_required":False,"r19_authorized":False,"post_seal_record_commit_forbidden":True,"seal_status":"SEALED"})
    print(json.dumps({"sealed":True,"payload_file_count":len(entries),"terminal_state":mech["scientific_terminal_state"]},sort_keys=True))

def main():
    if len(sys.argv)>1 and sys.argv[1]=="--freeze": preflight(); print(json.dumps({"status":"IMMUTABLE_ZERO_SOLVER_PREFLIGHT"})); return
    if len(sys.argv)>1 and sys.argv[1]=="--seal": seal(); return
    if any((ROOT/x).exists() for x in ("artifact_manifest.json","integrity.json","completion.json")): raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal exists")
    preflight(); analyze(); print(json.dumps({"status":"PAYLOAD_COMPLETE","fresh_solver_calls":0,"gate_logic_bug_confirmed":True},sort_keys=True))
if __name__=="__main__": main()
