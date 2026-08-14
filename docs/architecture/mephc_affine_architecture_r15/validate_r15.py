from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SHA = "1345b7e7485c4efbc170111a4d86eb489684cf233cedae86897567e2a6d56cad"
REFS = {"MePhC": "0c22cc82d8b285c08fc2f2432d6d5aa4d347d7e1", "MePhC-SqrLatt": "da39f45de67e72b5ec79d9b04202af6d9c212380", "MePhC-TriLatt": "45891d075d3d5a00d2ee07f8719a94d32e0ae98b"}
TERMINALS = {"CLOSED_BASELINE_FREE_QUADRATIC_NONZERO_SUPPORTED", "BLOCKED_BASELINE_FREE_QUADRATIC_UNRESOLVED", "BLOCKED_SECANT_CROSS_DIRECTION_INCONSISTENCY", "BLOCKED_UNIFORM_TRANSLATION_SECANT_FLOOR", "BLOCKED_CANONICAL_COVARIANCE", "BLOCKED_BAND_IDENTITY_GUARD", "BLOCKED_COMPATIBILITY", "BLOCKED_RUNTIME", "BLOCKED_SCOPE_EXPANSION"}
PHASES = ["0", "0.25", "0.5", "0.75"]
H = [0.005, 0.0075, 0.01, 0.015, 0.02]


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def fail(message):
    raise AssertionError(message)


def eq(a, b, label):
    if a != b:
        fail(f"{label}: {a!r} != {b!r}")


def close(a, b, label, tol=1e-12):
    if not math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol):
        fail(f"{label}: {a!r} != {b!r}")


def check_contract(contract=None):
    if contract is None:
        contract = load("authoritative_contract.json")
        eq(hashlib.sha256((ROOT / "authoritative_contract.json").read_bytes()).hexdigest(), SHA, "contract SHA")
    eq(contract["starting_refs"], REFS, "starting refs")
    eq(contract["resolution_plan"]["exact"], [96, 112], "resolutions")
    eq(contract["magnitude_ladder"]["fresh_exact"], [0.0075, 0.015], "fresh magnitudes")
    eq(contract["magnitude_ladder"]["combined"], H, "combined magnitudes")
    eq(contract["origin_phases"]["grid_cell_fractions"], [0.0, 0.25, 0.5, 0.75], "phases")
    eq(contract["fresh_matrix"]["expected_total_fresh_calls"], 112, "fresh call count")
    eq(contract["path_zero"]["solver_calls"], 0, "path-zero calls")
    eq(contract["benchmark"]["q2"], [-0.09, 0.14], "q2")
    eq(contract["benchmark"]["bands"], [1, 2, 3, 4, 5, 6], "bands")
    eq(contract["benchmark"]["primary_band"], 3, "primary band")
    eq(contract["scientific_terminal_states"], list(contract["scientific_terminal_states"]), "terminal list")
    if any("QUADRATIC_ZERO_SUPPORTED" in x and "NONZERO" not in x for x in contract["scientific_terminal_states"]):
        fail("quadratic-zero terminal present")
    eq(contract["delivery"]["r16_authorized"], False, "R16 authorization")


def check_prevalidation():
    pre = load("preflight.json")
    eq(pre["contract_sha256"], SHA, "preflight contract SHA")
    eq(pre["starting_refs"], REFS, "preflight refs")
    eq(pre["prevalidation_status"], "BLOCKED_COMPATIBILITY", "prevalidation status")
    eq(pre["fresh_solver_calls_before_freeze"], 0, "prevalidation fresh calls")
    eq(pre["triLatt_fresh_mpb_calls"], 0, "Tri calls")
    if not pre["protected_paths_unchanged"]: fail("protected paths changed")
    protected = load("protected_digest_check.json")
    eq(protected["verified"], True, "protected digest verification")
    if any("VALIDATOR_EXCEPTION" in str(v) for v in protected["inherited_validators"].values()): fail("inherited validator exception")
    diag = load("posthoc_baseline_free_diagnostic.json")
    eq(diag["label"], "POSTHOC_NONQUALIFYING_DIAGNOSTIC", "diagnostic label")
    eq(diag["source_solver_calls"], 0, "diagnostic calls")
    eq(diag["expected_match_abs_tol_1e-12"], True, "protected secants")
    freeze = load("prevalidation_freeze.json")
    eq(freeze["status"], "IMMUTABLE_PREVALIDATION_FREEZE", "freeze status")
    eq(freeze["fresh_solver_calls"], 0, "freeze fresh calls")
    eq(freeze["contract_sha256"], SHA, "freeze contract SHA")
    plan = load("frozen_fresh_call_plan.json")
    eq(plan["fresh_levels"], [0.0075, 0.015], "frozen fresh levels")
    eq(plan["expected_total_fresh_calls"], 112, "frozen call count")
    eq(plan["stop_before_fresh_solver"], True, "freeze stop")


def check_payload_if_present():
    mechanism_path = ROOT / "mechanism_adjudication.json"
    if not mechanism_path.exists():
        return "PREVALIDATION_ONLY"
    mech = load("mechanism_adjudication.json")
    terminal = mech["scientific_terminal_state"]
    if terminal not in TERMINALS: fail(f"invalid terminal {terminal}")
    if "QUADRATIC_ZERO_SUPPORTED" in terminal and "NONZERO" not in terminal: fail("zero terminal")
    eq(terminal, "BLOCKED_COMPATIBILITY", "compatibility terminal")
    solver = load("solver_execution.json")
    eq(solver["fresh_solver_call_count"], 0, "fresh solver count")
    eq(solver["triLatt_fresh_mpb_calls"], 0, "Tri fresh calls")
    if load("fresh_raw_spectra.json")["fresh_solver_calls"] != 0: fail("fresh spectra present after blocker")
    return terminal


def main():
    check_contract()
    check_prevalidation()
    terminal = check_payload_if_present()
    print(json.dumps({"validator": "r15", "status": "PASS", "terminal_state": terminal, "contract_sha256": SHA}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, IndexError, ValueError) as exc:
        print(f"R15_VALIDATION_FAILED: {exc}")
        raise SystemExit(1)
