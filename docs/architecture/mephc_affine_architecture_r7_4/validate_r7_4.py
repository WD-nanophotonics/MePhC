"""Contract-first validator for the R7.4 evidence bundle."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
LOCKED_SHA = "60b1979544d6ba3c6fe4840c97f8e291fed1c591836d4b8d52860d2997951a47"
REQUIRED = {"README.md", "authoritative_contract.json", "contract_preflight.json", "preflight.json", "protected_digest_check.json", "representation_geometry_controls.json", "solver_execution.json", "representation_spectra.json", "epsilon_grid_controls.json", "numerical_floor_adjudication.json", "inherited_r7_3_status.json", "change_scope.json", "test_coverage_matrix.csv", "validation_report.md", "known_limits_and_r8.md", "run_r7_4_adjudication.py", "validate_r7_4.py", "validator_negative_fixtures.py", "artifact_manifest.json", "integrity_digests.json", "completion.json"}
CONTROLS = ["canonical_plus_A", "polygon_list_reversed_plus_A", "deterministic_vertex_cycle_and_winding_plus_A", "supercell_vector_wrap_plus_A", "primitive_a1_translated_plus_A", "canonical_minus_A"]
FORBIDDEN = ("berry", "topology", "transport", "far_field", "unfolding", "gauge", "metric", "r8")

class ValidationError(RuntimeError):
    pass

def fail(message):
    raise ValidationError("R7_4_VALIDATION_ERROR: " + message)

def read(name, root=ROOT):
    return json.loads((root / name).read_text(encoding="utf-8"))

def validate_bundle(root=ROOT):
    missing = sorted(name for name in REQUIRED if not (root / name).is_file())
    if missing or not (root / "logs").is_dir():
        fail(f"missing evidence {missing}")
    contract_path = root / "authoritative_contract.json"
    contract_digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    if contract_digest != LOCKED_SHA:
        fail("authoritative contract SHA mismatch")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract["starting_refs"] != {"MePhC": "d51c90bc8d1489139912415af85c0c5a887dc4d2", "MePhC-SqrLatt": "da39f45de67e72b5ec79d9b04202af6d9c212380", "MePhC-TriLatt": "45891d075d3d5a00d2ee07f8719a94d32e0ae98b"}:
        fail("starting refs changed")
    pre = read("contract_preflight.json", root)
    if pre.get("contract_sha256") != LOCKED_SHA or pre.get("starting_refs") != contract["starting_refs"]:
        fail("contract preflight mismatch")
    runtime = read("preflight.json", root)
    if not runtime.get("remote_main_matches_contract") or runtime.get("remote_main") != contract["starting_refs"]:
        fail("remote refs not locked")
    if runtime.get("worktrees", {}).get("MePhC", {}).get("clean") is not True or runtime.get("worktrees", {}).get("MePhC-SqrLatt", {}).get("clean") is not True or runtime.get("worktrees", {}).get("MePhC-TriLatt", {}).get("clean_except") != [" M AGENTS.md"]:
        fail("worktree boundary mismatch")
    if read("protected_digest_check.json", root).get("verified") is not True:
        fail("protected digest check failed")
    inherited = read("inherited_r7_3_status.json", root)
    if inherited.get("resolved_count") != 1 or inherited.get("target_denominator") != 5 or inherited.get("immutable") is not True or inherited.get("response_baseline") != "UNQUALIFIED":
        fail("inherited R7.3 status changed")
    geometry = read("representation_geometry_controls.json", root)
    if geometry.get("all_required_geometry_controls_pass") is not True or geometry.get("full_typed_polygon_material") != "air":
        fail("geometry controls failed")
    if set(geometry.get("controls", {})) != set(CONTROLS):
        fail("fixed control set mismatch")
    if any("center" in json.dumps(item).lower() and "center_only" in json.dumps(item).lower() for item in geometry.get("controls", {}).values()):
        fail("center-only geometry evidence")
    for key, value in geometry.get("comparisons", {}).items():
        if value.get("equivalent") is not True:
            fail(f"geometry comparison failed: {key}")
    execution = read("solver_execution.json", root)
    if execution.get("call_count") != 24 or execution.get("expected_call_count") != 24 or execution.get("fresh_trilatt_solver_calls") != 0 or execution.get("fresh_five_amplitude_response_sweep") is not False:
        fail("solver call ledger violates fixed scope")
    if execution.get("representations") != CONTROLS or execution.get("resolutions") != [12, 16, 20, 24]:
        fail("solver control ladder mismatch")
    calls = execution.get("downstream_calls", [])
    if len(calls) != 24 or any(call.get("downstream") != "MePhC-SqrLatt" or call.get("num_bands") != 6 or call.get("polarization") != "TE" or call.get("resolution") not in [12, 16, 20, 24] for call in calls):
        fail("solver ledger semantic mismatch")
    tolerances = execution.get("solver_tolerance_values", [])
    if len(tolerances) > 1 or (tolerances and tolerances[0] not in (None, 1e-7)):
        fail("solver tolerance mutation or unrecorded value")
    spectra = read("representation_spectra.json", root)
    if spectra.get("q_points") != ["q0", "q1", "q2"] or spectra.get("num_bands") != 6 or set(spectra.get("resolutions", {})) != {"12", "16", "20", "24"}:
        fail("spectral shape or q-point mismatch")
    epsilon = read("epsilon_grid_controls.json", root)
    if epsilon.get("attempted") is not True or epsilon.get("api_state") not in {"AVAILABLE", "EPSILON_GRID_API_UNAVAILABLE"}:
        fail("epsilon control missing")
    adjudication = read("numerical_floor_adjudication.json", root)
    classification = adjudication.get("classification")
    if classification not in {"DISCRETE_OPERATOR_EQUIVALENT_EIGENSOLVER_FLOOR", "DISCRETIZATION_TRANSLATION_REPRESENTATION_FLOOR", "UNEXPLAINED_EQUIVALENCE_MISMATCH"}:
        fail("invalid classification")
    if adjudication.get("scientific_terminal_state") not in contract["scientific_terminal_states"]:
        fail("invalid terminal state")
    if adjudication.get("inherited_r7_3_response_baseline", {}).get("resolved_count") != 1:
        fail("adjudication changed inherited resolved status")
    completion = read("completion.json", root)
    if completion.get("inherited_r7_3_resolved_count") != 1 or completion.get("response_baseline_pass") is not False or completion.get("trilatt_fresh_solver_calls") != 0:
        fail("completion boundary changed")
    if any(re.search(r"\b" + re.escape(word) + r"\b", (root / name).read_text(encoding="utf-8"), re.I) for name in ("README.md", "validation_report.md") for word in FORBIDDEN if word != "r8"):
        fail("forbidden scientific claim in summary")
    if '"response_baseline_pass": true' in json.dumps(adjudication).lower():
        fail("response PASS claim")
    manifest = read("artifact_manifest.json", root)
    integrity = read("integrity_digests.json", root)
    if manifest.get("schema") != "mephc.affine_architecture.r7_4.artifact_manifest.v1" or integrity.get("algorithm") != "sha256":
        fail("seal schema mismatch")
    if set(manifest.get("files", [])) != set(integrity.get("payload", {})):
        fail("seal file sets differ")
    for name, expected in integrity.get("payload", {}).items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            fail(f"payload digest mismatch: {name}")
    if completion.get("payload_parent") == "POST_SEAL_RECORD_COMMIT":
        fail("post-seal record commit semantics")
    return {"terminal_state": adjudication["scientific_terminal_state"], "classification": classification, "call_count": execution["call_count"], "resolved_count": 1}

if __name__ == "__main__":
    try:
        print("PASS_R7_4_EVIDENCE_VALIDATOR " + json.dumps(validate_bundle(), sort_keys=True))
    except ValidationError as exc:
        print(str(exc))
        raise SystemExit(1)
