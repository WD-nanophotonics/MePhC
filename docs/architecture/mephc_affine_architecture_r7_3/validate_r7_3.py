"""Contract-first validator for the R7.3 evidence bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
LOCKED_CONTRACT_SHA256 = "c2f9d2c8f1b0742cb032abf8b9bd94172ba49d8bcf1a814342b0b181d684a37a"
REQUIRED = {"README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json", "protected_digest_check.json", "candidate_operations.json", "geometry_sign_equivalence.json", "geometry_negative_fixtures.json", "replay_floor.json", "fresh_solver_execution.json", "raw_spectra.json", "target_differential_by_resolution.json", "differential_convergence.json", "resolved_targets.json", "quadratic_diagnostic.json", "trilatt_hold.json", "change_scope.json", "test_coverage_matrix.csv", "validation_report.md", "known_limits_and_r8.md", "run_r7_3_closure.py", "validate_r7_3.py", "validator_negative_fixtures.py", "completion.json"}


class ValidationError(RuntimeError):
    pass


def read(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def fail(message):
    raise ValidationError("R7_3_VALIDATION_ERROR: " + message)


def validate_bundle(root=ROOT):
    missing = sorted(name for name in REQUIRED if not (root / name).is_file())
    if missing or not (root / "logs").is_dir():
        fail(f"missing required evidence: {missing}; logs_dir={(root / 'logs').is_dir()}")
    contract_path = root / "authoritative_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    if digest != LOCKED_CONTRACT_SHA256:
        fail("authoritative contract SHA-256 mismatch")
    preflight = read(root, "contract_preflight.json")
    derived_fields = ("benchmark", "locked_targets", "target_denominator", "geometry_equivalence", "replay_tolerance", "mandatory_fresh_sqrlatt_resolutions", "fresh_sqrlatt_resolution_ladder", "resolution_24_policy", "accepted_resolution_policy", "differential_convergence", "resolvability", "trilatt_hold", "terminal_states")
    if preflight.get("contract_sha256") != digest or preflight.get("starting_refs") != contract.get("starting_refs") or any(preflight.get(field) != contract.get(field) for field in derived_fields):
        fail("contract preflight is not derived from authoritative_contract.json")
    runtime_preflight = read(root, "preflight.json")
    if not runtime_preflight.get("remote_main_matches_contract"):
        fail("remote main refs were not verified")
    if runtime_preflight.get("remote_main") != contract.get("starting_refs"):
        fail("remote main refs do not equal contract starting refs")
    if runtime_preflight.get("worktrees", {}).get("MePhC", {}).get("clean") is not True or runtime_preflight.get("worktrees", {}).get("MePhC-SqrLatt", {}).get("clean") is not True:
        fail("MePhC or SqrLatt preflight worktree was dirty")
    tri_worktree = runtime_preflight.get("worktrees", {}).get("MePhC-TriLatt", {})
    if tri_worktree.get("clean_except") != ["AGENTS.md"]:
        fail("TriLatt exception is not the exact allowed AGENTS.md exception")
    if read(root, "protected_digest_check.json").get("verified") is not True:
        fail("protected evidence digest check failed")

    geometry = read(root, "geometry_sign_equivalence.json")
    candidate_doc = read(root, "candidate_operations.json")
    tolerance = float(contract["geometry_equivalence"]["tolerance"])
    candidates = candidate_doc.get("candidates", [])
    if candidate_doc.get("candidate_count") != len(candidates) or not candidates:
        fail("candidate operation enumeration is incomplete")
    expected_translations = {tuple(item) for item in contract["geometry_equivalence"]["translations_mod_2x2"]}
    for candidate in candidates:
        if tuple(candidate.get("translation_fractional", [])) not in expected_translations:
            fail("candidate translation is outside the contract")
        if candidate.get("match", {}).get("tolerance") != tolerance:
            fail("geometry tolerance mismatch")
        if not candidate.get("full_structure") if "full_structure" in candidate else False:
            fail("candidate lacks full typed structure evidence")
    if geometry.get("status") not in {"EQUIVALENT_BY_VERIFIED_OPERATION", "NOT_EQUIVALENT_UNDER_ENUMERATED_VERIFIED_OPERATIONS"}:
        fail("invalid geometry terminal result")
    if geometry.get("status") == "EQUIVALENT_BY_VERIFIED_OPERATION":
        matches = geometry.get("matching_candidates", [])
        if not matches or not all(item.get("match", {}).get("equivalent") and item.get("match", {}).get("maximum_coordinate_residual", float("inf")) <= tolerance for item in matches):
            fail("geometry equivalence lacks complete typed residual proof")
        if not all(item.get("transformed_fingerprint") == item.get("target_fingerprint") for item in matches):
            fail("equivalent geometry fingerprints are not stable/equal")
    negative = read(root, "geometry_negative_fixtures.json")
    if not negative or not all(item.get("expected_rejection") and not item.get("equivalent") for item in negative.values()):
        fail("geometry negative fixtures did not reject isolated mutations")

    execution = read(root, "fresh_solver_execution.json")
    calls = execution.get("downstream_calls", [])
    benchmark = contract["benchmark"]
    ladder = set(contract["fresh_sqrlatt_resolution_ladder"])
    mandatory = set(contract["mandatory_fresh_sqrlatt_resolutions"])
    used = {int(item.get("resolution")) for item in calls}
    if execution.get("tri_latt_solver_calls") != contract["trilatt_hold"]["fresh_mpb_solver_calls"] or any(item.get("downstream") != benchmark["downstream"] for item in calls):
        fail("fresh solver execution crossed the TriLatt boundary")
    if 8 in used or not mandatory.issubset(used) or not used.issubset(ladder) or any(value > max(ladder) for value in used):
        fail("resolution execution violates the contract ladder")
    for resolution in used:
        rows = [item for item in calls if int(item["resolution"]) == resolution]
        expected_count = len(benchmark["amplitudes"]) + int(contract["replay_tolerance"]["exact_additional_replays_per_used_resolution"])
        if len(rows) != expected_count:
            fail(f"resolution {resolution} call count is not contract-derived")
        if sorted(item["amplitude"] for item in rows[:len(benchmark["amplitudes"])]) != sorted(benchmark["amplitudes"]):
            fail(f"resolution {resolution} contracted amplitudes mismatch")
        if sum(item["purpose"].startswith("exact_plus_A_replay") for item in rows) != contract["replay_tolerance"]["exact_additional_replays_per_used_resolution"]:
            fail(f"resolution {resolution} replay count mismatch")
        for item in rows:
            if item.get("solver") != contract["runtime"]["solver"] or item.get("polarization") != benchmark["polarization"] or item.get("num_bands") != benchmark["num_bands"] or item.get("q_points") != list(benchmark["q_points"]):
                fail(f"resolution {resolution} solver settings mismatch")

    raw = read(root, "raw_spectra.json")
    raw_resolutions = {int(key) for key in raw}
    if raw_resolutions != used:
        fail("raw spectrum resolutions differ from actual calls")
    amplitude_keys = {str(float(value)) for value in benchmark["amplitudes"]}
    for resolution, by_amp in raw.items():
        if set(by_amp) != amplitude_keys:
            fail(f"raw amplitude set mismatch at {resolution}")
        for values in by_amp.values():
            if len(values) != len(benchmark["q_points"]) or any(len(row) != benchmark["num_bands"] for row in values):
                fail(f"raw spectrum shape mismatch at {resolution}")

    replay = read(root, "replay_floor.json")
    for resolution, item in replay.items():
        if int(resolution) not in used or item.get("additional_replays") != contract["replay_tolerance"]["exact_additional_replays_per_used_resolution"] or item.get("q_points_used") != contract["replay_tolerance"]["q_points_used"]:
            fail(f"replay metadata mismatch at {resolution}")
        expected_tol = max(1e-10, 10.0 * float(item["max_difference"]))
        if item.get("replay_tolerance") != expected_tol:
            fail(f"replay tolerance formula mismatch at {resolution}")

    by_resolution = {int(key): value for key, value in read(root, "target_differential_by_resolution.json").items()}
    target_set = {tuple(item) for item in contract["locked_targets"]}
    for resolution, rows in by_resolution.items():
        if len(rows) != contract["target_denominator"] or {tuple(row["target"]) for row in rows} != target_set:
            fail(f"locked target set/denominator mismatch at {resolution}")
        if len(rows) == 18 or any(row.get("target_denominator") == 18 for row in rows):
            fail("all-band/18-record stage semantics detected")
    differential = read(root, "differential_convergence.json")
    initial = differential.get("initial_16_to_20", [])
    final_pair = tuple(differential.get("final_pair", []))
    if final_pair not in {(16, 20), (20, 24)}:
        fail("invalid final comparison pair")
    initial_pass = all(row.get("status") == "DIFFERENTIAL_CONVERGED" for row in initial)
    if (24 in used) != (not initial_pass):
        fail("resolution 24 policy mismatch")
    if 24 in used and final_pair != (20, 24):
        fail("24 was used without 20-to-24 final pair")
    if 24 not in used and final_pair != (16, 20):
        fail("16-to-20 final pair missing")
    abs_tol = float(contract["differential_convergence"]["absolute"])
    rel_tol = float(contract["differential_convergence"]["relative_fraction"])
    for row in differential.get("targets", []):
        if row.get("tol_A") != max(abs_tol, rel_tol * abs(next(item["even_A"] for item in by_resolution[row["high"]] if item["target"] == row["target"]))):
            fail("full differential tolerance is not contract-derived")
        if row.get("tol_half") != max(abs_tol, rel_tol * abs(next(item["even_half"] for item in by_resolution[row["high"]] if item["target"] == row["target"]))):
            fail("half differential tolerance is not contract-derived")
    resolved = read(root, "resolved_targets.json")
    if resolved.get("denominator") != contract["target_denominator"] or len(resolved.get("targets", [])) != contract["target_denominator"]:
        fail("resolved target denominator mismatch")

    trilatt = read(root, "trilatt_hold.json")
    if trilatt.get("fresh_mpb_solver_calls") != contract["trilatt_hold"]["fresh_mpb_solver_calls"] or trilatt.get("authoritative_ref") != contract["trilatt_hold"]["authoritative_ref"]:
        fail("TriLatt hold violated")
    completion = read(root, "completion.json")
    allowed_states = set(contract["terminal_states"])
    if completion.get("terminal_state") not in allowed_states or completion.get("scientific_terminal_state") not in allowed_states:
        fail("invented terminal state")
    expected_state = "BLOCKED_COMPATIBILITY" if geometry.get("status") != "EQUIVALENT_BY_VERIFIED_OPERATION" else ("BLOCKED_EQUIVALENCE_SPECTRAL_MISMATCH" if not all(item.get("spectral_equivalence") for item in replay.values()) else ("PASS_DIFFERENTIAL_RESPONSE_BASELINE" if resolved.get("resolved_count", 0) >= contract["resolvability"]["minimum_resolved_targets_for_pass"] else "BLOCKED_DIFFERENTIAL_RESPONSE_UNRESOLVED"))
    if completion.get("terminal_state") != expected_state or differential.get("terminal_state") != expected_state:
        fail("terminal state does not follow the contract gates")
    if completion.get("trilatt_fresh_solver_calls") != 0 or completion.get("email_sent") is not False or completion.get("r8_authorized") is not False:
        fail("completion boundary metadata mismatch")
    return {"terminal_state": expected_state, "used_resolutions": sorted(used), "final_pair": list(final_pair), "resolved_count": resolved.get("resolved_count"), "tri_calls": trilatt.get("fresh_mpb_solver_calls")}


def main():
    result = validate_bundle()
    print("PASS_R7_3_EVIDENCE_VALIDATOR", json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
