#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
CONTRACT_SHA = "631d8468b5e9d33b657d0c2456cdebf3b76534ae000468ddbc3c313cc01b249d"
REQUIRED = [
    "README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json", "protected_digest_check.json", "r20_inheritance.json", "quadrature_definition.json", "frozen_call_plan.json", "prevalidation_freeze.json", "baseline_raw_spectra.json", "baseline_validation.json", "operator_validation.json", "shifted_raw_spectra.json", "pair_Q_and_secants.json", "full_Q_and_secants.json", "uniform_Q_and_secants.json", "pair_alpha_fit.json", "full_alpha_fit.json", "uniform_alpha_fit.json", "quadrature_A_vs_B.json", "quadrature_transferability.json", "quadrature_uncertainty.json", "band_identity_guard.json", "mpb_comparison.json", "cross_direction_consistency.json", "mechanism_adjudication.json", "solver_execution.json", "change_scope.json", "trilatt_hold.json", "test_coverage.csv", "validation_report.md", "known_limits.md", "run_r21.py", "validate_r21.py", "validator_negative_fixtures.py", "artifact_manifest.json", "integrity.json", "completion.json",
]
TERMINALS = {"CLOSED_SHIFTED_QUADRATURE_EFFV_CROSSCHECK_SUPPORTED", "BLOCKED_SHIFTED_QUADRATURE_BASELINE", "BLOCKED_SHIFTED_QUADRATURE_BAND_IDENTITY", "BLOCKED_ORIGIN_QUADRATURE_TRANSFERABILITY", "BLOCKED_SHIFTED_QUADRATURE_RESPONSE_UNRESOLVED", "BLOCKED_SHIFTED_QUADRATURE_UNIFORM_NULL", "BLOCKED_SHIFTED_QUADRATURE_CROSS_METHOD_DISAGREEMENT", "BLOCKED_SHIFTED_QUADRATURE_CROSS_DIRECTION_INCONSISTENCY", "BLOCKED_RUNTIME", "BLOCKED_COMPATIBILITY", "BLOCKED_SCOPE_EXPANSION"}
B = {(0.125, 0.125), (0.375, 0.375), (0.625, 0.625), (0.875, 0.875)}
EXPECTED = {"MePhC": "43944f21dc464b14c24f56348e5db597bc1741de", "MePhC-SqrLatt": "da39f45de67e72b5ec79d9b04202af6d9c212380", "MePhC-TriLatt": "45891d075d3d5a00d2ee07f8719a94d32e0ae98b"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_ref(repo: Path, remote: bool = False) -> str:
    args = ["git", "-C", str(repo)] + (["ls-remote", "origin", "refs/heads/main"] if remote else ["rev-parse", "HEAD"])
    return subprocess.check_output(args, text=True).strip().split()[0]


def validate_payload(root: Path) -> tuple[bool, list[str]]:
    errors = []
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        return False, [f"missing {name}" for name in missing]
    try:
        contract = json.loads((root / "authoritative_contract.json").read_text())
        frozen = json.loads((root / "frozen_call_plan.json").read_text())
        baseline = json.loads((root / "baseline_validation.json").read_text())
        transfer = json.loads((root / "quadrature_transferability.json").read_text())
        uncertainty = json.loads((root / "quadrature_uncertainty.json").read_text())
        band = json.loads((root / "band_identity_guard.json").read_text())
        mechanism = json.loads((root / "mechanism_adjudication.json").read_text())
        execution = json.loads((root / "solver_execution.json").read_text())
        completion = json.loads((root / "completion.json").read_text())
        manifest = json.loads((root / "artifact_manifest.json").read_text())
        integrity = json.loads((root / "integrity.json").read_text())
    except Exception as exc:
        return False, [f"JSON unreadable: {exc}"]
    if sha(root / "authoritative_contract.json") != CONTRACT_SHA: errors.append("contract SHA mismatch")
    if contract.get("starting_refs") != EXPECTED: errors.append("starting refs mismatch")
    if contract.get("delivery", {}).get("r22_authorized") is not False: errors.append("R22 authorization changed")
    if frozen.get("status") != "FROZEN" or frozen.get("stage_A_calls") != 8 or frozen.get("stage_B_calls") != 192 or frozen.get("expected_total") != 200 or len(frozen.get("calls", [])) != 200: errors.append("fixed call plan mismatch")
    for call in frozen.get("calls", []):
        origin = tuple(call.get("origin", []))
        if call.get("stage") == "A" and (call.get("N") not in (96, 128) or call.get("direction") != "baseline" or call.get("h") != 0.0 or origin not in B): errors.append("invalid Stage A call")
        if call.get("stage") == "B" and (call.get("N") not in (96, 128) or call.get("direction") not in ("pair", "full", "uniform") or call.get("h") not in (0.01, 0.02, 0.03, 0.04) or call.get("sign") not in ("plus", "minus") or origin not in B): errors.append("invalid Stage B call")
    if not baseline.get("all_pass") or not baseline.get("stage_B_allowed"): errors.append("baseline gate failed")
    if not band.get("pass"): errors.append("band identity gate failed")
    if mechanism.get("scientific_terminal_state") not in TERMINALS: errors.append("invalid terminal")
    if execution.get("fresh_solver_calls") != mechanism.get("fresh_solver_calls"): errors.append("solver ledger mismatch")
    if execution.get("fresh_solver_calls") != 200 or execution.get("stage_A_calls") != 8 or execution.get("stage_B_calls") != 192: errors.append("solver count mismatch")
    if execution.get("mpb_or_meep_independent_solver_calls") != 0 or execution.get("trilatt_fresh_solver_calls") != 0: errors.append("forbidden solver calls")
    if transfer.get("all_pass") and any(uncertainty.get(d, {}).get("raw_origin_alpha_half_range_included") for d in ("pair", "full")): errors.append("raw origin floor incorrectly included")
    if not transfer.get("all_pass") and not all("protected_R20_raw_origin_half_range" in uncertainty.get(d, {}).get("components", {}) for d in ("pair", "full")): errors.append("raw origin floor missing")
    if mechanism.get("RAW_ORIGIN_EXCURSION_NONTRANSFERABLE_TO_QUADRATURE_MEAN") != transfer.get("all_pass"): errors.append("transferability record mismatch")
    if json.loads((root / "change_scope.json").read_text()).get("production_changes") != []: errors.append("production scope changed")
    if json.loads((root / "trilatt_hold.json").read_text()).get("authoritative_ref") != EXPECTED["MePhC-TriLatt"]: errors.append("TriLatt hold mismatch")
    if completion.get("seal_status") != "SEALED" or completion.get("contract_sha256") != CONTRACT_SHA or completion.get("fresh_solver_calls") != 200: errors.append("completion seal mismatch")
    listed = {x["path"]: x["sha256"] for x in manifest.get("files", [])}
    if "artifact_manifest.json" in listed or "integrity.json" in listed or "completion.json" in listed: errors.append("seal files included in payload manifest")
    if integrity.get("artifact_manifest_sha256") != sha(root / "artifact_manifest.json"): errors.append("manifest digest mismatch")
    return not errors, errors


def main() -> None:
    ok, errors = validate_payload(ROOT)
    print(json.dumps({"status": "PASS" if ok else "FAIL", "errors": errors}, sort_keys=True))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
