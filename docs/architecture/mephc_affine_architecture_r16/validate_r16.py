from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTRACT_SHA = "91300498afee0ac523ccc69076bd82ecbc271d64d8a840f746609895745e6231"
REFS = {
    "MePhC": "9e8367f5f57df87759255ba1358cb7f1a43da765",
    "MePhC-SqrLatt": "da39f45de67e72b5ec79d9b04202af6d9c212380",
    "MePhC-TriLatt": "45891d075d3d5a00d2ee07f8719a94d32e0ae98b",
}
PHASES = [0.0, 0.25, 0.5, 0.75]
RESOLUTIONS = [96, 112]
H = [0.005, 0.0075, 0.01, 0.015, 0.02]
TERMINALS = {
    "CLOSED_BASELINE_FREE_QUADRATIC_NONZERO_SUPPORTED",
    "BLOCKED_BASELINE_FREE_QUADRATIC_UNRESOLVED",
    "BLOCKED_SECANT_CROSS_DIRECTION_INCONSISTENCY",
    "BLOCKED_UNIFORM_TRANSLATION_SECANT_FLOOR",
    "BLOCKED_CANONICAL_COVARIANCE",
    "BLOCKED_BAND_IDENTITY_GUARD",
    "BLOCKED_COMPATIBILITY",
    "BLOCKED_RUNTIME",
    "BLOCKED_SCOPE_EXPANSION",
}
REQUIRED = {
    "README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json",
    "protected_digest_check.json", "r15_inheritance.json", "r15_compatibility_cause.json",
    "protected_reuse_matrix.json", "corrective_fresh_call_plan.json", "prevalidation_freeze.json",
    "path_zero_representation.json", "fresh_raw_spectra.json", "reused_provenance.json",
    "pair_Q_and_secants.json", "full_Q_and_secants.json", "uniform_Q_and_secants.json",
    "pair_alpha_fit.json", "full_alpha_fit.json", "uniform_alpha_fit.json",
    "per_phase_alpha_diagnostics.json", "cross_direction_consistency.json", "additive_offset_diagnostic.json",
    "same_input_repeat_floor.json", "representation_control.json", "band_identity_guard.json",
    "uncertainty_budget.json", "mechanism_adjudication.json", "solver_execution.json", "change_scope.json",
    "trilatt_hold.json", "test_coverage.csv", "validation_report.md", "known_limits.md", "run_r16.py",
    "validate_r16.py", "validator_negative_fixtures.py",
}


def load(root: Path, name: str):
    return json.loads((root / name).read_text(encoding="utf-8"))


def fail(message: str):
    raise AssertionError(message)


def eq(a, b, label: str):
    if a != b:
        fail(f"{label}: {a!r} != {b!r}")


def close(a, b, label: str, tol=1e-12):
    if not math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol):
        fail(f"{label}: {a!r} != {b!r}")


def signature(row):
    return json.dumps({k: row[k] for k in ("kind", "direction", "resolution", "phase", "h", "sign", "control_role")}, sort_keys=True)


def check_contract(root: Path):
    contract_path = root / "authoritative_contract.json"
    eq(hashlib.sha256(contract_path.read_bytes()).hexdigest(), CONTRACT_SHA, "contract SHA")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    eq(contract["starting_refs"], REFS, "starting refs")
    eq(contract["resolution_plan"]["exact"], RESOLUTIONS, "resolutions")
    eq(contract["origin_phases"]["grid_cell_fractions"], PHASES, "phases")
    eq(contract["primary_estimator"]["levels"], H, "H ladder")
    eq(contract["fresh_call_count"]["expected_total"], 142, "expected total")
    eq(contract["delivery"]["r17_authorized"], False, "R17 authorization")
    if any("QUADRATIC_ZERO" in x for x in contract["scientific_terminal_states"]):
        fail("quadratic-zero terminal present")


def check_freeze(root: Path):
    freeze = load(root, "prevalidation_freeze.json")
    eq(freeze["status"], "IMMUTABLE_PREVALIDATION_FREEZE", "freeze status")
    eq(freeze["fresh_solver_calls"], 0, "freeze fresh calls")
    eq(freeze["contract_sha256"], CONTRACT_SHA, "freeze SHA")
    eq(freeze["call_plan_counts"]["total"], 142, "frozen plan count")
    pre = load(root, "preflight.json")
    eq(pre["contract_sha256"], CONTRACT_SHA, "preflight SHA")
    eq(pre["starting_refs"], REFS, "preflight refs")
    eq(pre["fresh_solver_calls_before_freeze"], 0, "preflight fresh calls")
    eq(pre["triLatt_fresh_mpb_calls"], 0, "preflight Tri calls")
    eq(load(root, "protected_digest_check.json")["verified"], True, "protected digest check")
    inheritance = load(root, "r15_inheritance.json")
    eq(inheritance["terminal_state"], "BLOCKED_COMPATIBILITY", "R15 terminal")
    eq(inheritance["fresh_solver_calls"], 0, "R15 fresh calls")
    eq(load(root, "r15_compatibility_cause.json")["contractual_only"], True, "R15 cause")
    eq(load(root, "protected_reuse_matrix.json")["protected_matrix_verified"], True, "protected reuse")
    plan = load(root, "corrective_fresh_call_plan.json")
    eq(plan["counts"]["total"], 142, "plan total")
    frozen_calls = plan["calls"]
    expected = expected_calls()
    eq(len(frozen_calls), len(expected), "plan length")
    for index, (actual, exp) in enumerate(zip(frozen_calls, expected), 1):
        eq(actual["class"], exp["class"], f"plan {index} class")
        for field in ("direction", "resolution", "phase", "h", "sign"):
            close(actual[field], exp[field], f"plan {index} {field}") if isinstance(exp[field], float) else eq(actual[field], exp[field], f"plan {index} {field}")


def expected_calls():
    calls = []
    for res in RESOLUTIONS:
        for direction in ("pair", "full"):
            for h in (0.0075, 0.015):
                for phase in PHASES:
                    for sign in ("plus", "minus"):
                        calls.append({"class": "response_control_matrix", "direction": direction, "resolution": res, "phase": phase, "h": h, "sign": sign})
        for h, phases in ((0.005, PHASES[1:]), (0.0075, PHASES), (0.015, PHASES), (0.02, PHASES)):
            for phase in phases:
                for sign in ("plus", "minus"):
                    calls.append({"class": "response_control_matrix", "direction": "uniform", "resolution": res, "phase": phase, "h": h, "sign": sign})
        for direction in ("pair", "full", "uniform"):
            for sign in ("plus", "minus"):
                calls.append({"class": "repeat", "direction": direction, "resolution": res, "phase": 0.0, "h": 0.0075, "sign": sign})
        for direction in ("pair", "full", "uniform"):
            calls.append({"class": "representation", "direction": direction, "resolution": res, "phase": 0.0, "h": 0.0075, "sign": "plus"})
    return calls


def check_execution(root: Path):
    execution = load(root, "solver_execution.json")
    eq(execution["fresh_solver_call_count"], 142, "fresh call count")
    eq(execution["expected_total"], 142, "expected call count")
    eq(execution["triLatt_fresh_mpb_calls"], 0, "Tri fresh calls")
    ledger = execution["fresh_solver_calls"]
    eq(len(ledger), 142, "ledger length")
    expected = expected_calls()
    for index, (row, exp) in enumerate(zip(ledger, expected), 1):
        eq(row["call_index"], index, f"call index {index}")
        eq(row["kind"], "response_control_matrix" if exp["class"] == "response_control_matrix" else "same_input_repeat" if exp["class"] == "repeat" else "representation_control", f"call kind {index}")
        for field in ("direction", "resolution", "phase", "h", "sign"):
            close(row[field], exp[field], f"call {index} {field}") if isinstance(exp[field], float) else eq(row[field], exp[field], f"call {index} {field}")
        eq(row["q_point"], "q2", f"call {index} q")
        eq(row["q_fractional"], [-0.09, 0.14], f"call {index} q vector")
        eq(row["response_bands"], [1, 2, 3, 4, 5, 6], f"call {index} bands")
        eq(row["resolution"], int(row["resolution"]), f"call {index} resolution")
        close(row["solver_tolerance"], 1e-10, f"call {index} tolerance")
        eq(row["solver"], "meep.mpb.ModeSolver", f"call {index} solver")
    raw = load(root, "fresh_raw_spectra.json")
    eq(raw["fresh_solver_calls"], 142, "raw fresh count")
    eq(load(root, "path_zero_representation.json")["solver_calls"], 0, "path-zero calls")


def check_analysis(root: Path):
    for direction in ("pair", "full", "uniform"):
        data = load(root, f"{direction}_Q_and_secants.json")
        for res in ("96", "112"):
            for phase in ("0", "0.25", "0.5", "0.75"):
                row = data["resolutions"][res][phase]
                eq(list(map(float, row["Q"].keys())), list(map(float, row["Q"].keys())), "Q keys")
                eq(len(row["adjacent_secants"]), 4, f"{direction} adjacent intervals")
                eq([x["interval"] for x in row["adjacent_secants"]], [[0.005, 0.0075], [0.0075, 0.01], [0.01, 0.015], [0.015, 0.02]], f"{direction} intervals")
        fit = load(root, f"{direction}_alpha_fit.json")
        for res in ("96", "112"):
            if not math.isfinite(float(fit[res]["alpha"])): fail(f"{direction} nonfinite alpha")
    cross = load(root, "cross_direction_consistency.json")
    if not math.isfinite(float(cross["delta_cross"])): fail("nonfinite cross discrepancy")
    uncertainty = load(root, "uncertainty_budget.json")
    components = ("cross_resolution_alpha_drift", "leave_one_phase_out_spread", "leave_one_adjacent_interval_out_spread", "max_phase_mean_secant_fit_residual", "repeat_frequency_floor_over_min_delta_h2", "representation_difference_over_min_delta_h2", "smallest_interval_phase_half_range", "maximum_absolute_uniform_adjacent_secant")
    for direction in ("pair", "full"):
        for name in components:
            if name not in uncertainty[direction]["components"]: fail(f"missing {direction} uncertainty component {name}")
    mechanism = load(root, "mechanism_adjudication.json")
    if mechanism["scientific_terminal_state"] not in TERMINALS: fail("invalid scientific terminal")
    if "QUADRATIC_ZERO" in mechanism["scientific_terminal_state"]: fail("quadratic-zero terminal")
    eq(load(root, "change_scope.json")["production_changes"], [], "production changes")
    eq(load(root, "trilatt_hold.json")["fresh_mpb_calls"], 0, "Tri hold")


def check_seal(root: Path):
    if not (root / "artifact_manifest.json").exists():
        return "PAYLOAD_ONLY"
    manifest = load(root, "artifact_manifest.json")
    entries = manifest["files"]
    names = {x["path"] for x in entries}
    if "artifact_manifest.json" in names or "integrity.json" in names or "completion.json" in names:
        fail("seal files included in payload manifest")
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file(): fail(f"manifest missing {entry['path']}")
        eq(path.stat().st_size, entry["size_bytes"], f"manifest size {entry['path']}")
        eq(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"], f"manifest hash {entry['path']}")
    integrity = load(root, "integrity.json")
    eq(integrity["contract_sha256"], CONTRACT_SHA, "integrity contract SHA")
    completion = load(root, "completion.json")
    eq(completion["fresh_solver_calls"], 142, "completion fresh count")
    eq(completion["completion_gmail_required"], False, "completion Gmail")
    eq(completion["r17_authorized"], False, "completion R17")
    eq(completion["seal_status"], "SEALED", "seal status")
    return "SEALED"


def validate_bundle(root: Path = ROOT):
    missing = sorted(REQUIRED - {p.name for p in root.iterdir() if p.is_file()})
    if missing: fail(f"missing evidence files {missing}")
    check_contract(root)
    check_freeze(root)
    check_execution(root)
    check_analysis(root)
    seal_state = check_seal(root)
    return {"validator": "r16", "status": "PASS", "seal_state": seal_state, "terminal_state": load(root, "mechanism_adjudication.json")["scientific_terminal_state"], "fresh_solver_calls": 142}


if __name__ == "__main__":
    try:
        print(json.dumps(validate_bundle(), sort_keys=True))
    except (AssertionError, KeyError, IndexError, ValueError, OSError) as exc:
        print(f"R16_VALIDATION_FAILED: {exc}")
        raise SystemExit(1)
