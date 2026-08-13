from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
LOCKED_SHA = "73f128dd4a52d4b313e2c8bce1a929f1f3111dad800b5fb8cf3d69172733ef91"


class ValidationError(RuntimeError):
    pass


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def check(condition, message):
    if not condition:
        raise ValidationError(message)


def git(*args):
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True).strip()


def validate_bundle(check_git=True):
    contract_bytes = (ROOT / "authoritative_contract.json").read_bytes()
    check(hashlib.sha256(contract_bytes).hexdigest() == LOCKED_SHA, "BLOCKED_COMPATIBILITY: authoritative contract SHA")
    contract = json.loads(contract_bytes)
    check(contract["contract_id"].endswith("odd-response"), "BLOCKED_COMPATIBILITY: contract id")
    check(not contract["delivery"]["r9_authorized"], "BLOCKED_SCOPE_EXPANSION: unauthorized scope")

    required = [
        "contract_preflight.json", "preflight.json", "two_by_two_obstruction.json",
        "geometry_activity.json", "sign_inequivalence_candidates.json",
        "baseline_spectra.json", "baseline_target_freeze.json", "freeze_commit.json",
        "raw_response_spectra.json", "band_identity_guard.json",
        "odd_response_by_resolution.json", "differential_convergence.json",
        "resolved_targets.json", "odd_scaling_diagnostic.json",
        "r7_4_floor_reference.json", "trilatt_hold.json", "change_scope.json",
        "solver_execution.json", "completion.json",
    ]
    for name in required:
        check((ROOT / name).is_file(), f"BLOCKED_COMPATIBILITY: missing {name}")

    preflight = load("preflight.json")
    check(preflight["remote_main"] == contract["starting_refs"], "BLOCKED_COMPATIBILITY: starting refs")
    check(preflight["protected_paths_verified"] is True, "BLOCKED_COMPATIBILITY: protected paths")
    check(preflight["runtime"]["solver"] == "meep.mpb.ModeSolver", "BLOCKED_RUNTIME: solver")
    check(float(preflight["runtime"]["solver_tolerance"]) == 1e-7, "BLOCKED_RUNTIME: tolerance")
    check(preflight["runtime"]["python"] == "/home/icy/miniconda3/envs/mp/bin/python", "BLOCKED_RUNTIME: python")

    obstruction = load("two_by_two_obstruction.json")
    check(obstruction["result"] == contract["two_by_two_obstruction"]["required_result"], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: 2x2 result")
    check(obstruction["mpb_calls"] == 0 and obstruction["finite_geometry_regression_pass"], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: obstruction evidence")

    activity = load("geometry_activity.json")
    check(activity["replication"] == [3, 1], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: replication")
    check(activity["all_required_checks_pass"], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: geometry activity")
    check(activity["geometry_digest_count"] == 5, "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: geometry digest count")
    check(activity["plus_minus_site_sign_reversal"] and activity["half_sign_reversal"], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: sign reversal")
    check(activity["periodicity"]["verified"] and activity["jacobian"]["all_positive"], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: periodicity/Jacobian")
    check(activity["motif_shape_material_unchanged"], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: motif mutation")

    candidates = load("sign_inequivalence_candidates.json")
    check(candidates["candidate_count"] == 6 and not candidates["matching_candidates"], "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: matching candidate")
    check(candidates["status"] == "SIGN_INEQUIVALENT_UNDER_ENUMERATED_VERIFIED_OPERATIONS", "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE: status")
    check(candidates["tolerance"] == 1e-10, "BLOCKED_COMPATIBILITY: symmetry tolerance")

    baseline = load("baseline_spectra.json")
    check(baseline["amplitude"] == 0.0 and not baseline["nonzero_amplitudes_present"], "BLOCKED_COMPATIBILITY: baseline contamination")
    check(list(map(int, baseline["resolutions"].keys())) == [12, 16, 20], "BLOCKED_COMPATIBILITY: baseline resolutions")
    check(baseline["call_count"] == 3 and len(baseline["calls"]) == 3, "BLOCKED_COMPATIBILITY: baseline call count")
    check(all(float(call["amplitude"]) == 0.0 for call in baseline["calls"]), "BLOCKED_COMPATIBILITY: nonzero in baseline")

    frozen = load("baseline_target_freeze.json")
    targets = [tuple(row) for row in frozen["frozen_targets"]]
    check(targets == [("q1", 1), ("q1", 2), ("q2", 1), ("q2", 2), ("q3", 1), ("q3", 2)], "BLOCKED_BASELINE_TARGET_ISOLATION: target list")
    check(frozen["target_count"] == 6 and frozen["required_target_count"] == 6, "BLOCKED_BASELINE_TARGET_ISOLATION: target count")
    check(frozen["baseline_only"] and not frozen["nonzero_spectra_present"], "BLOCKED_BASELINE_TARGET_ISOLATION: freeze contamination")

    freeze = load("freeze_commit.json")
    check(freeze["nonzero_spectra_in_freeze_commit"] is False and not freeze["nonzero_paths_in_freeze_commit"], "BLOCKED_BASELINE_TARGET_ISOLATION: freeze metadata")
    if check_git:
        check(git("cat-file", "-t", freeze["freeze_commit_sha"]) == "commit", "BLOCKED_BASELINE_TARGET_ISOLATION: freeze commit missing")
        names = git("show", "--format=", "--name-only", freeze["freeze_commit_sha"]).splitlines()
        check(not any("raw_response_spectra" in name or "odd_response" in name for name in names), "BLOCKED_BASELINE_TARGET_ISOLATION: nonzero path in freeze commit")

    raw = load("raw_response_spectra.json")
    resolutions = raw["resolutions"]
    check(raw["baseline_reused"] and raw["nonzero_amplitudes"] == [0.005, -0.005, 0.0025, -0.0025], "BLOCKED_COMPATIBILITY: response amplitudes")
    check(set(resolutions) in ({"12", "16", "20"}, {"12", "16", "20", "24"}), "BLOCKED_COMPATIBILITY: response resolution set")
    expected_count = 15 if "24" not in resolutions else 20
    check(raw["call_count"] == expected_count, "BLOCKED_COMPATIBILITY: response call count")
    for resolution in ("12", "16", "20"):
        check(set(resolutions[resolution]) == {"0.0", "0.005", "-0.005", "0.0025", "-0.0025"}, "BLOCKED_COMPATIBILITY: mandatory signed amplitudes")
    if "24" in resolutions:
        check(set(resolutions["24"]) == {"0.0", "0.005", "-0.005", "0.0025", "-0.0025"}, "BLOCKED_COMPATIBILITY: resolution 24 policy")

    guard = load("band_identity_guard.json")
    check(guard["pass"] and all(row["pass"] for rows in guard["rows"].values() for row in rows), "BLOCKED_BAND_IDENTITY_GUARD: guard")
    convergence = load("differential_convergence.json")
    check(convergence["final_pair"] in ([16, 20], [20, 24]), "BLOCKED_COMPATIBILITY: differential pair")
    check(all(row["full_pass"] and row["half_pass"] for row in convergence["final"]), "BLOCKED_ODD_RESPONSE_UNRESOLVED: differential convergence")

    resolved = load("resolved_targets.json")
    check([tuple((row["q_point"], row["band_ordinal"])) for row in resolved["targets"]] == targets, "BLOCKED_COMPATIBILITY: response-dependent targets")
    count = int(resolved["resolved_count"])
    check(count == sum(bool(row["resolved"]) for row in resolved["targets"]), "BLOCKED_ODD_RESPONSE_UNRESOLVED: resolved count")
    check(resolved["terminal_state"] in contract["scientific_terminal_states"], "BLOCKED_COMPATIBILITY: terminal state")
    expected_terminal = "PASS_SIGN_INEQUIVALENT_ODD_RESPONSE_BASELINE" if count >= 2 else "BLOCKED_ODD_RESPONSE_UNRESOLVED"
    check(resolved["terminal_state"] == expected_terminal, "BLOCKED_ODD_RESPONSE_UNRESOLVED: terminal policy")

    solver = load("solver_execution.json")
    check(solver["call_count"] == expected_count and solver["tri_latt_solver_calls"] == 0, "BLOCKED_COMPATIBILITY: solver ledger")
    check(solver["solver"] == "meep.mpb.ModeSolver" and solver["solver_tolerance"] == 1e-7, "BLOCKED_RUNTIME: solver ledger")
    trilatt = load("trilatt_hold.json")
    check(trilatt["fresh_mpb_solver_calls"] == 0 and not trilatt["production_change"], "BLOCKED_SCOPE_EXPANSION: TriLatt")
    scope = load("change_scope.json")
    check(scope["production_changes"] == [] and not scope["r9_authorized"], "BLOCKED_SCOPE_EXPANSION: production scope")
    completion = load("completion.json")
    check(completion["scientific_terminal_state"] == expected_terminal, "BLOCKED_COMPATIBILITY: completion state")
    check(completion["frozen_targets"] == frozen["frozen_targets"] and completion["target_denominator"] == 6, "BLOCKED_COMPATIBILITY: completion targets")
    check(completion["completion_gmail_required"] is False and completion["r9_authorized"] is False, "BLOCKED_SCOPE_EXPANSION: completion scope")

    forbidden = contract["forbidden_claims"]
    for name in ("README.md", "known_limits.md", "validation_report.md"):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        check(not any(claim.lower() in text for claim in forbidden), f"BLOCKED_SCOPE_EXPANSION: forbidden claim in {name}")
    return {"status": "PASS_R8_EVIDENCE_VALIDATOR", "terminal_state": expected_terminal, "resolved_count": count, "target_count": 6, "solver_call_count": expected_count}


if __name__ == "__main__":
    try:
        print(json.dumps(validate_bundle(check_git=True), sort_keys=True))
    except (ValidationError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
