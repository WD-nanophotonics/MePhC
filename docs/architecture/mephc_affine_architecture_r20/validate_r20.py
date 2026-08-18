#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

CONTRACT_SHA = "000cd0b87efc6df50a2af6d98326493d3b016ca818da8bf8368d12728ad715ba"
TERMINALS = {
    "CLOSED_EFFV_INDEPENDENT_QUADRATIC_CROSSCHECK_SUPPORTED",
    "BLOCKED_EFFV_BASELINE_VALIDATION", "BLOCKED_EFFV_TRANSLATION_COVARIANCE",
    "BLOCKED_EFFV_GEOMETRY_ASSIGNMENT", "BLOCKED_EFFV_OPERATOR_VALIDATION",
    "BLOCKED_EFFV_BAND_IDENTITY", "BLOCKED_EFFV_SHAPE_DERIVATIVE_UNRESOLVED",
    "BLOCKED_EFFV_CROSS_METHOD_DISAGREEMENT", "BLOCKED_EFFV_CROSS_DIRECTION_INCONSISTENCY",
    "BLOCKED_EFFV_UNIFORM_NULL", "BLOCKED_RUNTIME", "BLOCKED_COMPATIBILITY", "BLOCKED_SCOPE_EXPANSION",
}
REQUIRED = [
    "README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json",
    "protected_digest_check.json", "r19_inheritance.json", "geometry_site_assignment.json",
    "effv_method.json", "exact_face_integration.json", "bloch_boundary_definition.json",
    "frozen_call_plan.json", "baseline_raw_spectra.json", "baseline_validation.json",
    "translation_covariance_control.json", "operator_validation.json", "effv_raw_spectra.json",
    "pair_Q_and_secants.json", "full_Q_and_secants.json", "uniform_Q_and_secants.json",
    "pair_alpha_fit.json", "full_alpha_fit.json", "uniform_alpha_fit.json", "effv_uncertainty.json",
    "band_identity_guard.json", "r19_vs_r20_discretization.json", "mpb_comparison.json",
    "cross_direction_consistency.json", "mechanism_adjudication.json", "solver_execution.json",
    "change_scope.json", "trilatt_hold.json", "test_coverage.csv", "validation_report.md",
    "known_limits.md", "run_r20.py", "validate_r20.py", "validator_negative_fixtures.py",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def validate_payload(root: Path) -> tuple[bool, list[str]]:
    errors = []
    try:
        contract = json.loads((root / "authoritative_contract.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"contract unreadable: {exc}"]
    if sha(root / "authoritative_contract.json") != CONTRACT_SHA:
        errors.append("contract SHA mismatch")
    for name in REQUIRED:
        if not (root / name).is_file():
            errors.append(f"missing {name}")
    if errors:
        return False, errors
    try:
        preflight = json.loads((root / "preflight.json").read_text(encoding="utf-8"))
        frozen = json.loads((root / "frozen_call_plan.json").read_text(encoding="utf-8"))
        mechanism = json.loads((root / "mechanism_adjudication.json").read_text(encoding="utf-8"))
        baseline = json.loads((root / "baseline_validation.json").read_text(encoding="utf-8"))
        covariance = json.loads((root / "translation_covariance_control.json").read_text(encoding="utf-8"))
        execution = json.loads((root / "solver_execution.json").read_text(encoding="utf-8"))
        geometry = json.loads((root / "geometry_site_assignment.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"payload JSON unreadable: {exc}"]
    if preflight.get("status") != "IMMUTABLE_EFFV_PREFLIGHT": errors.append("preflight status")
    if frozen.get("stage_A_calls") != 12 or frozen.get("stage_B_calls") != 192 or frozen.get("expected_total") != 204 or len(frozen.get("calls", [])) != 204:
        errors.append("fixed call plan mismatch")
    if not geometry.get("pass"): errors.append("geometry assignment failed")
    if mechanism.get("scientific_terminal_state") not in TERMINALS: errors.append("invalid terminal")
    if not baseline.get("all_pass") and mechanism.get("scientific_terminal_state") != "BLOCKED_EFFV_BASELINE_VALIDATION": errors.append("baseline gate/terminal mismatch")
    if mechanism.get("stage_B_calls", 0) == 0 and mechanism.get("scientific_terminal_state") == "CLOSED_EFFV_INDEPENDENT_QUADRATIC_CROSSCHECK_SUPPORTED": errors.append("closed without Stage B")
    if mechanism.get("fresh_solver_calls") != execution.get("fresh_solver_calls"): errors.append("solver ledger mismatch")
    if mechanism.get("fresh_solver_calls") not in (12, 204): errors.append("unexpected eigensolve count")
    if mechanism.get("fresh_solver_calls") == 204 and mechanism.get("stage_B_calls") != 192: errors.append("Stage B count mismatch")
    if covariance.get("eigensolves", 0) != 0: errors.append("covariance used eigensolve")
    if contract.get("delivery", {}).get("r21_authorized") is not False: errors.append("R21 authorization changed")
    if json.loads((root / "change_scope.json").read_text(encoding="utf-8")).get("production_changes") != []: errors.append("production scope changed")
    return not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    ok, errors = validate_payload(args.root)
    result = {"status": "PASS" if ok else "FAIL", "errors": errors}
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
