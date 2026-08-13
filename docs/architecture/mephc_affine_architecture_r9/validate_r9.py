from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
LOCKED_SHA = "ec660f973d65c330bf582143d5adbfa086f6d62b71968dc2e1973292bcc877d6"


class ValidationError(RuntimeError):
    pass


def check(condition, message):
    if not condition:
        raise ValidationError(message)


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True).strip()


def validate_bundle(check_git=True):
    contract_bytes = (ROOT / "authoritative_contract.json").read_bytes()
    check(hashlib.sha256(contract_bytes).hexdigest() == LOCKED_SHA, "BLOCKED_COMPATIBILITY: contract SHA")
    contract = json.loads(contract_bytes)
    check(contract["contract_id"] == "mephc-affine-architecture-r9-perturbative-order-grid-floor-adjudication", "BLOCKED_COMPATIBILITY: contract id")
    check(contract["delivery"]["r10_authorized"] is False, "BLOCKED_SCOPE_EXPANSION: unauthorized scope")
    required = list(contract["required_evidence"])
    for name in required:
        if name.endswith("/"):
            check((ROOT / name.rstrip("/")).is_dir(), f"BLOCKED_COMPATIBILITY: missing directory {name}")
        else:
            check((ROOT / name).is_file(), f"BLOCKED_COMPATIBILITY: missing {name}")

    pre = load("preflight.json")
    check(pre["contract_sha256"] == LOCKED_SHA, "BLOCKED_COMPATIBILITY: preflight SHA")
    check(pre["remote_main"] == contract["starting_refs"], "BLOCKED_COMPATIBILITY: starting refs")
    check(pre["protected_paths_unchanged"] is True, "BLOCKED_COMPATIBILITY: protected paths")
    check(pre["runtime"]["python"] == contract["runtime"]["python"], "BLOCKED_RUNTIME: python")
    check(pre["runtime"]["solver"] == contract["runtime"]["solver"], "BLOCKED_RUNTIME: solver")
    check(float(pre["runtime"]["solver_tolerance"]) == 1e-7, "BLOCKED_RUNTIME: tolerance")
    protected = load("protected_digest_check.json")
    check(protected["verified"] is True, "BLOCKED_COMPATIBILITY: protected digest")
    check("PASS_R8_EVIDENCE_VALIDATOR" in protected["r8_validator"], "BLOCKED_COMPATIBILITY: R8 inheritance validator")

    inheritance = load("r8_inheritance.json")
    check(inheritance == contract["r8_inheritance"], "BLOCKED_COMPATIBILITY: R8 inheritance mutation")
    check(inheritance["resolved_count"] == 0 and inheritance["target_denominator"] == 6, "BLOCKED_COMPATIBILITY: R8 relabel")

    analytic = load("analytic_selection_rule.json")
    check(analytic["first_order_label"] == "FIRST_ORDER_ZERO_MEAN_SELECTION_RULE_SUPPORTED", "BLOCKED_COMPATIBILITY: analytic label")
    check(analytic["momentum_cycle_label"] == "CUBIC_ODD_TERM_ALLOWED_NOT_GUARANTEED", "BLOCKED_COMPATIBILITY: cubic label")
    check(analytic["zero_mean_verified"] is True and abs(analytic["zero_mean"]) < 1e-15, "BLOCKED_COMPATIBILITY: zero mean")
    check(set(analytic["discrete_fourier_components"]) == {"0", "1", "2"}, "BLOCKED_COMPATIBILITY: DFT components")
    check(analytic["full_formal_maxwell_proof_claimed"] is False, "BLOCKED_SCOPE_EXPANSION: analytic overclaim")

    posthoc = load("r8_posthoc_all_band_diagnostic.json")
    check(posthoc["fresh_solver_calls"] == 0 and posthoc["all_18_channels"], "BLOCKED_COMPATIBILITY: posthoc scope")
    check(len(posthoc["rows"]) == 18 and all(row["label"] == "POSTHOC_NONQUALIFYING_DIAGNOSTIC" for row in posthoc["rows"]), "BLOCKED_COMPATIBILITY: posthoc channels")
    check(posthoc["r8_remains_resolved_count"] == 0 and posthoc["r8_remains_target_denominator"] == 6, "BLOCKED_COMPATIBILITY: R8 posthoc relabel")

    geometry = load("geometry_controls.json")
    check(geometry["all_required_checks_pass"] and geometry["tested_amplitudes"] == [0.02, -0.02], "BLOCKED_COMPATIBILITY: geometry controls")
    check(all(row["pass"] and row["periodicity"]["verified"] and row["jacobian"]["positive"] and row["no_overlap_or_pathology"] for row in geometry["rows"]), "BLOCKED_COMPATIBILITY: geometry pathology")

    raw = load("raw_response_spectra.json")
    levels = [-0.02, -0.01, -0.005, -0.0025, 0.0, 0.0025, 0.005, 0.01, 0.02]
    resolutions = sorted(int(key) for key in raw["resolutions"])
    check(resolutions in ([20, 24, 32, 40], [20, 24, 32, 40, 48]), "BLOCKED_COMPATIBILITY: resolutions")
    for resolution in resolutions:
        check(set(float(key) for key in raw["resolutions"][str(resolution)]) == set(levels), "BLOCKED_COMPATIBILITY: amplitude ladder")
        for amplitude in levels:
            data = raw["resolutions"][str(resolution)][str(amplitude)]
            check(set(data) == {"q1", "q2", "q3"}, "BLOCKED_COMPATIBILITY: q channels")
            check(all(len(data[q]) == 6 for q in data), "BLOCKED_COMPATIBILITY: band channels")
    r8_raw = json.loads((REPO / "docs/architecture/mephc_affine_architecture_r8/raw_response_spectra.json").read_text(encoding="utf-8"))
    for amplitude in ("0.0", "0.0025", "-0.0025", "0.005", "-0.005"):
        check(raw["resolutions"]["20"][amplitude] == r8_raw["resolutions"]["20"][amplitude], "BLOCKED_COMPATIBILITY: R8 reuse mutation")

    controls = load("uniform_translation_controls.json")
    control_resolutions = [24, 32, 40] + ([48] if 48 in resolutions else [])
    for resolution in control_resolutions:
        check(set(controls[str(resolution)]) == {"0.005", "0.02"}, "BLOCKED_COMPATIBILITY: control deltas")
        for delta in ("0.005", "0.02"):
            control = controls[str(resolution)][delta]
            check(control["geometry_equivalent"] is True, "BLOCKED_COMPATIBILITY: translation equivalence")
            check(set(control["spectra"]) == {delta, str(-float(delta))}, "BLOCKED_COMPATIBILITY: translation signs")

    solver = load("solver_execution.json")
    expected_calls = 56 if 48 in resolutions else 43
    check(solver["fresh_solver_call_count"] == expected_calls and len(solver["fresh_calls"]) == expected_calls, "BLOCKED_COMPATIBILITY: solver call count")
    check(solver["reused_r8_solver_call_count"] == 5, "BLOCKED_COMPATIBILITY: R8 reuse count")
    check(solver["resolution_48_ran"] == (48 in resolutions) and solver["resolution_above_48_ran"] is False, "BLOCKED_COMPATIBILITY: resolution policy")
    for call in solver["fresh_calls"]:
        check(call["solver"] == "meep.mpb.ModeSolver" and call["solver_tolerance"] == 1e-7, "BLOCKED_RUNTIME: solver ledger")
        check(call["resolution"] <= 48, "BLOCKED_COMPATIBILITY: resolution above 48")
        check(call["q_points"] == ["q1", "q2", "q3"] and call["bands"] == [1, 2, 3, 4, 5, 6], "BLOCKED_COMPATIBILITY: channel ledger")
    if 48 in resolutions:
        check(sum(call["resolution"] == 48 for call in solver["fresh_calls"]) == 13, "BLOCKED_COMPATIBILITY: 48 call policy")

    guard = load("band_identity_guard.json")
    check(guard["pass"] and len(guard["rows"]) > 0 and all(row["pass"] for row in guard["rows"]), "BLOCKED_BAND_IDENTITY_GUARD: band guard")
    quantities = load("response_by_resolution_and_amplitude.json")
    for resolution in resolutions:
        check(len(quantities[str(resolution)]) == 18, "BLOCKED_COMPATIBILITY: response channel drop")
        check({(row["q_point"], row["band_ordinal"]) for row in quantities[str(resolution)]} == {(q, b) for q in ["q1", "q2", "q3"] for b in range(1, 7)}, "BLOCKED_COMPATIBILITY: response subset")

    convergence = load("high_resolution_convergence.json")
    expected_pair = [40, 48] if 48 in resolutions else [32, 40]
    check(convergence["final_pair"] == expected_pair and len(convergence["channels"]) == 18, "BLOCKED_COMPATIBILITY: convergence pair/channels")
    mechanism = load("mechanism_adjudication.json")
    check(mechanism["channel_count"] == 18 and mechanism["r8_remains_0_of_6"] is True, "BLOCKED_COMPATIBILITY: mechanism channel count")
    check(mechanism["first_order_label"] == "FIRST_ORDER_ZERO_MEAN_SELECTION_RULE_SUPPORTED", "BLOCKED_COMPATIBILITY: mechanism first-order label")
    check(mechanism["cubic_allowed_label"] == "CUBIC_ODD_TERM_ALLOWED_NOT_GUARANTEED", "BLOCKED_COMPATIBILITY: mechanism cubic label")
    terminal = mechanism["terminal_state"]
    check(terminal in contract["scientific_terminal_states"], "BLOCKED_COMPATIBILITY: terminal state")
    check(terminal == "BLOCKED_ODD_RESPONSE_ORDER_UNRESOLVED", "BLOCKED_ODD_RESPONSE_ORDER_UNRESOLVED: unexpected closure")
    check(mechanism["eligible_odd_channels"] == 1 and mechanism["cubic_support_count"] == 0 and mechanism["linear_support_count"] == 1, "BLOCKED_ODD_RESPONSE_ORDER_UNRESOLVED: support counts")

    scope = load("change_scope.json")
    check(scope["production_changes"] == [] and scope["fresh_trilatt_solver_calls"] == 0 and scope["r10_authorized"] is False, "BLOCKED_SCOPE_EXPANSION: scope")
    trilatt = load("trilatt_hold.json")
    check(trilatt["fresh_mpb_solver_calls"] == 0 and trilatt["production_change"] is False, "BLOCKED_SCOPE_EXPANSION: TriLatt")
    completion = load("completion.json")
    check(completion["scientific_terminal_state"] == terminal and completion["channel_denominator"] == 18, "BLOCKED_COMPATIBILITY: completion")
    check(completion["fresh_solver_call_count"] == expected_calls and completion["completion_gmail_required"] is False, "BLOCKED_COMPATIBILITY: completion ledger")

    for name in ("README.md", "known_limits.md", "validation_report.md"):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        check(not any(word.lower() in text for word in contract["forbidden_claims"]), f"BLOCKED_SCOPE_EXPANSION: forbidden claim in {name}")

    manifest = load("artifact_manifest.json")
    integrity = load("integrity.json")
    check(manifest["payload_parent"] == integrity["payload_parent"] == completion["payload_parent"], "BLOCKED_COMPATIBILITY: seal parent")
    check(hashlib.sha256((ROOT / "artifact_manifest.json").read_bytes()).hexdigest() == integrity["manifest_sha256"], "BLOCKED_COMPATIBILITY: manifest hash")
    for item in manifest["files"]:
        check(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"], "BLOCKED_COMPATIBILITY: artifact hash")
    check(integrity["payload_files_sha256"] == {item["path"]: item["sha256"] for item in manifest["files"]}, "BLOCKED_COMPATIBILITY: integrity map")
    if check_git:
        head = git("rev-parse", "HEAD")
        names = git("show", "--format=", "--name-only", head).splitlines()
        check(set(names) == {
            "docs/architecture/mephc_affine_architecture_r9/artifact_manifest.json",
            "docs/architecture/mephc_affine_architecture_r9/completion.json",
            "docs/architecture/mephc_affine_architecture_r9/integrity.json",
        }, "BLOCKED_COMPATIBILITY: post-seal record scope")
    return {
        "status": "PASS_R9_EVIDENCE_VALIDATOR",
        "terminal_state": terminal,
        "eligible_odd_channels": mechanism["eligible_odd_channels"],
        "cubic_support_count": mechanism["cubic_support_count"],
        "linear_support_count": mechanism["linear_support_count"],
        "resolution_pair": expected_pair,
        "fresh_solver_call_count": expected_calls,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(validate_bundle(check_git=True), sort_keys=True))
    except (ValidationError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
