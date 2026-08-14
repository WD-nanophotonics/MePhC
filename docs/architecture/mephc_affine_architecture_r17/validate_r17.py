#!/usr/bin/env python3
import argparse, hashlib, json, sys
from pathlib import Path

EXPECTED_SHA = "f2a874d2114e38b4e25a45a7b43232f56b66e654abb96eca29b6bdabe341b5eb"
EXPECTED_REFS = {
    "MePhC": "131e3d3cfaec7e630dd3bc683c3ea5ab3354c42f",
    "MePhC-SqrLatt": "da39f45de67e72b5ec79d9b04202af6d9c212380",
    "MePhC-TriLatt": "45891d075d3d5a00d2ee07f8719a94d32e0ae98b",
}
PHASES = [0.125, 0.375, 0.625, 0.875]
LEVELS = [0.005, 0.0075, 0.01, 0.015, 0.02]
DIRECTIONS = ["pair", "full", "uniform"]
REQUIRED = ["authoritative_contract.json", "contract_preflight.json", "preflight.json", "protected_digest_check.json", "r16_inheritance.json", "r16_uniform_max_corrective.json", "ensemble_definition.json", "frozen_fresh_call_plan.json", "prevalidation_freeze.json", "fresh_raw_spectra.json", "pair_Q_and_secants.json", "full_Q_and_secants.json", "uniform_Q_and_secants.json", "pair_alpha_fit.json", "full_alpha_fit.json", "uniform_alpha_fit.json", "per_phase_alpha_diagnostics.json", "ensemble_A_vs_B_comparison.json", "uniform_artifact_transferability.json", "cross_direction_consistency.json", "same_input_repeat_floor.json", "representation_control.json", "band_identity_guard.json", "uncertainty_budget.json", "mechanism_adjudication.json", "solver_execution.json", "change_scope.json", "trilatt_hold.json", "test_coverage.csv", "validation_report.md", "known_limits.md", "run_r17.py", "validate_r17.py", "validator_negative_fixtures.py"]

def load(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))

def fail(errors, cond, message):
    if not cond: errors.append(message)

def validate(root):
    errors = []
    for name in REQUIRED: fail(errors, (root / name).is_file(), f"missing {name}")
    if errors: return errors
    contract_bytes = (root / "authoritative_contract.json").read_bytes()
    fail(errors, hashlib.sha256(contract_bytes).hexdigest() == EXPECTED_SHA, "contract SHA mismatch")
    c = load(root, "authoritative_contract.json")
    fail(errors, c.get("starting_refs") == EXPECTED_REFS, "starting refs mismatch")
    fail(errors, c.get("ensemble_B", {}).get("grid_cell_fractions") == PHASES, "ensemble phases mismatch")
    fail(errors, c.get("levels") == LEVELS, "levels mismatch")
    fail(errors, c.get("expected_calls_without_optional_band_identity_A0") == 258, "expected call count mismatch")
    fail(errors, c.get("optional_band_identity_A0_calls") == 8, "optional A0 contract mismatch")
    freeze = load(root, "prevalidation_freeze.json")
    fail(errors, freeze.get("status") == "IMMUTABLE_PREVALIDATION_FREEZE", "freeze status mismatch")
    fail(errors, freeze.get("fresh_solver_calls") == 0, "freeze executed fresh solver")
    corr = load(root, "r16_uniform_max_corrective.json")
    fail(errors, corr.get("label") == "R16_UNIFORM_MAX_IMPLEMENTATION_UNDERESTIMATE_CONFIRMED", "R16 corrective label missing")
    fail(errors, float(corr.get("literal_max_abs", 0)) >= 0.2850798537483712, "R16 literal max below threshold")
    inherited = load(root, "r16_inheritance.json")
    inherited = c["r16_inheritance"]
    fail(errors, inherited.get("lambda_pair_112") == 0.29064790522077466, "R16 pair inheritance mismatch")
    fail(errors, inherited.get("c2_full_112") == 0.20312424926371087, "R16 full inheritance mismatch")
    pd = load(root, "protected_digest_check.json")
    fail(errors, pd.get("R16_immutable") is True and pd.get("inherited_validators", {}).get("r15", {}).get("returncode") == 0 and pd.get("inherited_validators", {}).get("r16", {}).get("returncode") == 0, "protected digest/validator check failed")
    ed = load(root, "ensemble_definition.json")
    fail(errors, ed.get("grid_cell_fractions") == PHASES and ed.get("ensemble") == "B", "ensemble definition mismatch")
    plan = load(root, "frozen_fresh_call_plan.json")
    fail(errors, len(plan.get("calls", [])) == 258, "frozen plan count mismatch")
    fail(errors, all(x.get("class") != "band_identity_A0" for x in plan.get("calls", [])), "frozen plan includes optional A0")
    se = load(root, "solver_execution.json")
    calls = se.get("fresh_solver_calls", [])
    fail(errors, se.get("fresh_solver_call_count") == 258 and len(calls) == 258, "solver execution count mismatch")
    fail(errors, se.get("expected_total") == 258 and se.get("optional_band_identity_A0_calls") == 0, "solver execution optional A0 mismatch")
    fail(errors, se.get("ensemble") == "B" and se.get("resolutions_used") == [96, 112], "solver execution ensemble/resolution mismatch")
    fail(errors, se.get("triLatt_fresh_mpb_calls") == 0 and not se.get("above_112_ran"), "out-of-scope solver call")
    expected_primary = 240
    fail(errors, se.get("primary_matrix_calls") == expected_primary and se.get("repeat_calls") == 12 and se.get("representation_calls") == 6, "call partition mismatch")
    fail(errors, [x.get("call_index") for x in calls] == list(range(1, 259)), "call ledger indices not contiguous")
    for x in calls:
        fail(errors, x.get("resolution") in (96, 112), "invalid resolution")
        fail(errors, x.get("phase") in PHASES, "invalid phase")
        fail(errors, x.get("direction") in DIRECTIONS, "invalid direction")
        fail(errors, x.get("h") in LEVELS, "invalid level")
        fail(errors, x.get("q_point") == "q2" and x.get("q_fractional") == [-0.09, 0.14], "q mismatch")
        fail(errors, x.get("polarization") == "TE" and x.get("primary_band") == 3 and x.get("requested_bands") == 6, "solver channel mismatch")
        fail(errors, x.get("solver_tolerance") == 1e-10 and x.get("response_bands") == [1,2,3,4,5,6], "solver tolerance/bands mismatch")
    raw = load(root, "fresh_raw_spectra.json")
    fail(errors, raw.get("ensemble") == "B", "raw spectra ensemble mismatch")
    fail(errors, raw.get("fresh_solver_calls") == 258, "raw spectra count mismatch")
    for d in DIRECTIONS:
        q = load(root, f"{d}_Q_and_secants.json")
        fail(errors, q.get("direction") == d and q.get("ensemble") == "B", f"{d} Q metadata mismatch")
        fit = load(root, f"{d}_alpha_fit.json")
        fail(errors, set(fit) == {"96", "112"}, f"{d} alpha resolutions mismatch")
        for r in ("96", "112"):
            block = q["resolutions"][r]
            for p in PHASES:
                entry = block[str(p)]
                fail(errors, len(entry["adjacent_secants"]) == 4, f"{d} secant count mismatch")
                fail(errors, all(item["interval"] == [LEVELS[i], LEVELS[i+1]] for i, item in enumerate(entry["adjacent_secants"])), f"{d} intervals mismatch")
    transfer = load(root, "uniform_artifact_transferability.json")
    fail(errors, "literal_max_abs" in transfer.get("raw_uniform", {}), "uniform raw max missing")
    fail(errors, len(transfer.get("raw_uniform", {}).get("rows", [])) == 16, "uniform raw rows mismatch")
    fail(errors, set(transfer.get("gate_conditions", {})) >= {"uniform_alpha_within_matched", "uniform_no_stable_resolved_nonzero", "raw_uniform_two_interval_sign_mixes"}, "transfer gate incomplete")
    stress = bool(transfer.get("RAW_UNIFORM_STRESS_NONTRANSFERABLE"))
    ub = load(root, "uncertainty_budget.json")
    nine = {"cross_resolution_alpha_drift", "cross_ensemble_alpha_drift", "leave_one_phase_out_spread", "leave_one_interval_out_spread", "max_phase_mean_fit_residual", "repeat_over_min_delta_h2", "representation_over_min_delta_h2", "smallest_interval_phase_half_range", "estimator_matched_uniform_floor"}
    for d in ("pair", "full"):
        comp = ub[d]["components"]
        fail(errors, nine.issubset(comp) and len(comp) == (10 if stress else 9), f"{d} uncertainty component count mismatch")
        fail(errors, ub[d]["u"] == max(comp.values()), f"{d} uncertainty max mismatch")
        fail(errors, ("raw_uniform_max_abs" in comp) == stress, f"{d} raw uniform inclusion mismatch")
    mech = load(root, "mechanism_adjudication.json")
    allowed = {"CLOSED_INDEPENDENT_ENSEMBLE_QUADRATIC_NONZERO_SUPPORTED", "BLOCKED_INDEPENDENT_ENSEMBLE_QUADRATIC_UNRESOLVED", "BLOCKED_UNIFORM_ARTIFACT_TRANSFERABILITY_UNRESOLVED", "BLOCKED_SECANT_CROSS_DIRECTION_INCONSISTENCY", "BLOCKED_UNIFORM_TRANSLATION_NULL_INCONSISTENCY", "BLOCKED_CANONICAL_COVARIANCE", "BLOCKED_BAND_IDENTITY_GUARD", "BLOCKED_COMPATIBILITY", "BLOCKED_RUNTIME", "BLOCKED_SCOPE_EXPANSION"}
    fail(errors, mech.get("scientific_terminal_state") in allowed, "invalid terminal")
    fail(errors, "QUADRATIC_ZERO" not in mech.get("scientific_terminal_state", ""), "forbidden quadratic-zero terminal")
    fail(errors, mech.get("fresh_ensemble") == "B" and mech.get("primary_q_point") == "q2" and mech.get("primary_band") == 3, "mechanism metadata mismatch")
    fail(errors, load(root, "change_scope.json").get("r16_immutable") is True and load(root, "change_scope.json").get("r18_authorized") is False, "scope boundary mismatch")
    if (root / "completion.json").exists():
        integ = load(root, "integrity.json"); manifest = load(root, "artifact_manifest.json"); completion = load(root, "completion.json")
        fail(errors, completion.get("seal_status") == "SEALED" and completion.get("r18_authorized") is False, "completion seal metadata mismatch")
        fail(errors, integ.get("contract_sha256") == EXPECTED_SHA, "integrity contract mismatch")
        fail(errors, integ.get("payload_file_count") == len(manifest.get("files", [])), "manifest count mismatch")
    return errors

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    args = parser.parse_args(); errors = validate(args.root.resolve())
    if errors:
        for e in errors: print("FAIL:", e)
        print(json.dumps({"status":"FAIL","errors":errors}, sort_keys=True)); return 1
    print(json.dumps({"status":"PASS","root":str(args.root.resolve())}, sort_keys=True)); return 0

if __name__ == "__main__": sys.exit(main())
