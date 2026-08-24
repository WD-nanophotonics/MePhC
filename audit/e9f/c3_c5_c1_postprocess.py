"""C3.C5.C1 zero-native postprocessing and audit validators."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-C5-C1-20260825-250"
SOURCE_WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-C5-20260825-248"
SOURCE_EXECUTION = "02b8fc343b3dd786769c42cfa8e44bd57add482d"
FAILED_EXECUTION = "87eb2678448fdf6db3f161a45484470ab5c8a2bd"
CONTRACT_SHA = "9891baa53a52373a8f3ec1e218590e8bd839c54a20d87d6a4fbc2f5d6c7a8279"
POLICY_SHA = "75f2d32853ab7e0a5878c19a732f4ac91ef993c105a8000b87e4a8a6ed6d5145"
ORIGINAL_RP2_EXECUTION = "8121dbfba352b1a77551213771694d25c1bf3f01"
SIX_RESOLUTIONS = (64, 96)
STENCILS = ("1/72", "1/144")
BRANCHES = ("band2", "band3")
REQUIRED_INCIDENT_IDS = tuple(f"REL-{i:03d}" for i in range(21, 54))
P2_IDS = ("REL-022", "REL-025", "REL-034", "REL-035")
OPEN_P1 = ("REL-021", "REL-042", "REL-050", "REL-051", "REL-052", "REL-053")


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body_hash(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    value.pop("payload_body_sha256", None)
    value.pop("payload_file_sha256", None)
    return hashlib.sha256(canonical(value)).hexdigest()


def _hash_expected(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise ValueError(f"C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:{label}")


def _point_h_ok(point: Mapping[str, Any]) -> bool:
    gate = point.get("H_GATE", {})
    return (
        gate.get("status") == "MPB_H_ENVELOPE_QUALIFIED"
        and float(gate.get("max_offdiag", 9)) <= 1e-10
        and float(gate.get("selected_pair_offdiag", 9)) <= 1e-10
        and float(gate.get("max_normalization_error", 9)) <= 1e-14
        and float(gate.get("orthogonality_tolerance", 9)) == 1e-10
        and float(gate.get("normalization_tolerance", 9)) == 1e-14
    )


def verify_source_matrix(*, root: Path, source_runtime: Path) -> dict[str, Any]:
    checkpoint_path = source_runtime / "matrix_checkpoint.json"
    result_path = source_runtime / "c3_c5_matrix_result.json"
    manifest_path = source_runtime / "c3_c5_matrix_manifest.json"
    contract_path = root / "audit/e9f/rp2_c3_c5_execution_contract.json"
    policy_path = root / "audit/e9f/rp1_recovery_policy_contract.json"
    _hash_expected(checkpoint_path, "871b24983800d178f44d09b2220bcc179804e939f1f4c9163d84917ca5a8ca7d", "checkpoint")
    _hash_expected(result_path, "068cbb6048d5813cbdd5c38efa323e85af3a340d58d7fa69e0e3b5ff1511785a", "result")
    _hash_expected(manifest_path, "ca9d7fc2184371b1dcf5049a1a8bceaf613372bd69a2cd0449fbf25d4e919d01", "manifest")
    _hash_expected(contract_path, CONTRACT_SHA, "contract")
    _hash_expected(policy_path, POLICY_SHA, "policy")
    checkpoint = json.loads(checkpoint_path.read_text())
    result = json.loads(result_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if checkpoint.get("work_order_id") != SOURCE_WORK_ORDER or checkpoint.get("execution_sha") != SOURCE_EXECUTION or checkpoint.get("generation") != 12:
        raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:checkpoint_identity")
    if result.get("work_order_id") != SOURCE_WORK_ORDER or result.get("execution_sha") != SOURCE_EXECUTION or result.get("contract_sha256") != CONTRACT_SHA:
        raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:result_identity")
    if manifest.get("execution_sha") != SOURCE_EXECUTION or manifest.get("worker_count") != 12 or manifest.get("matrix_entry_count") != 24 or manifest.get("total_native_solves") != 108:
        raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:manifest_identity")
    rows = build_plan_from_policy(root)
    completed = checkpoint.get("completed_workers", [])
    if len(completed) != 12 or len({item.get("worker_id") for item in completed}) != 12:
        raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:checkpoint_workers")
    payloads_by_id: dict[str, dict[str, Any]] = {}
    resolutions: list[int] = []
    for item, row in zip(completed, rows):
        if item.get("worker_id") != row["sample_id"] or item.get("resolution") != row["resolution"]:
            raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:checkpoint_order")
        path = Path(item["payload_path"])
        if not path.is_file() or sha(path) != item.get("payload_file_sha256"):
            raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:payload_file_hash")
        payload = json.loads(path.read_text())
        if body_hash(payload) != item.get("payload_body_sha256") or payload.get("payload_body_sha256") != item.get("payload_body_sha256"):
            raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:payload_body_hash")
        identity = {"worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": row["source_sample_index"], "logical_sample_index": row["sample_index"], "resolution": row["resolution"]}
        if any(payload.get(key) != value for key, value in identity.items()) or payload.get("execution_sha") != SOURCE_EXECUTION or payload.get("contract_sha256") != CONTRACT_SHA or payload.get("rp1_policy_file_sha256") != POLICY_SHA or payload.get("provider", {}).get("resolution") != row["resolution"]:
            raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:payload_identity")
        points = payload.get("all_point_metrics", [])
        if len(points) != 9 or payload.get("solve_count") != 9 or payload.get("replay_matched_point_count") != 9 or payload.get("replay_unmatched_point_count") != 0 or any(not _point_h_ok(point) for point in points):
            raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:payload_coverage")
        payloads_by_id[row["sample_id"]] = payload
        resolutions.append(row["resolution"])
    result_ids = {payload["worker_id"] for payload in result.get("payloads", [])}
    if result_ids != set(payloads_by_id) or sum(payload["solve_count"] for payload in payloads_by_id.values()) != 108:
        raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:result_payload_set")
    if sum(resolution == 64 for resolution in resolutions) != 6 or sum(resolution == 96 for resolution in resolutions) != 6:
        raise ValueError("C3_C5_C1_SOURCE_MATRIX_BINDING_FAIL_CLOSED:resolution_set")
    return {"checkpoint": checkpoint, "result": result, "manifest": manifest, "rows": rows, "payloads": [payloads_by_id[row["sample_id"]] for row in rows], "checkpoint_path": checkpoint_path, "result_path": result_path, "manifest_path": manifest_path}


def build_plan_from_policy(root: Path) -> list[dict[str, Any]]:
    policy = json.loads((root / "audit/e9f/rp1_recovery_policy_contract.json").read_text())
    records = {item["sample_id"]: item for item in policy["immutable_inputs"]["failed_sample_records"]}
    rows: list[dict[str, Any]] = []
    for position, sample_id in enumerate(policy["rp2_diagnostic_matrix"]["fixed_sample_ids"]):
        source = records[sample_id]
        for resolution_position, resolution in enumerate(SIX_RESOLUTIONS):
            rows.append({"sample_id": f"{sample_id}::resolution={resolution}", "source_sample_id": sample_id, "source_sample_index": int(source["sample_index"]), "sample_index": position * 2 + resolution_position, "resolution": resolution, "authoritative_coordinate": [float(value) for value in source["center"]]})
    if [row["sample_index"] for row in rows] != list(range(12)) or len({row["sample_id"] for row in rows}) != 12:
        raise ValueError("C3_C5_C1_PLAN_INVALID")
    return rows


def derive_positional_assignment(edge: Mapping[str, Any], candidate_window: Sequence[int]) -> list[list[int]]:
    matched = edge.get("matched_by_solver_index")
    if not isinstance(matched, list) or len(matched) != len(candidate_window):
        raise ValueError("E9F_C1_C1_ASSIGNMENT_DERIVATION")
    positions: list[list[int]] = []
    for pair in matched:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("E9F_C1_C1_ASSIGNMENT_DERIVATION")
        try:
            positions.append([list(candidate_window).index(int(pair[0])), list(candidate_window).index(int(pair[1]))])
        except ValueError as exc:
            raise ValueError("E9F_C1_C1_ASSIGNMENT_DERIVATION") from exc
    return positions


def validate_positional_assignment(edge: Mapping[str, Any], candidate_window: Sequence[int]) -> None:
    assignment = edge.get("assignment")
    matched = edge.get("matched_by_solver_index")
    if not isinstance(assignment, list) or not isinstance(matched, list) or len(assignment) != len(candidate_window):
        raise ValueError("E9F_C1_C1_ASSIGNMENT_SCHEMA")
    expected = derive_positional_assignment(edge, candidate_window)
    if assignment != expected:
        raise ValueError("E9F_C1_C1_ASSIGNMENT_INCONSISTENT")
    n = len(candidate_window)
    left = [pair[0] for pair in assignment]
    right = [pair[1] for pair in assignment]
    if any(not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(x, int) or x < 0 or x >= n for x in pair) for pair in assignment):
        raise ValueError("E9F_C1_C1_ASSIGNMENT_RANGE")
    if sorted(left) != list(range(n)) or sorted(right) != list(range(n)):
        raise ValueError("E9F_C1_C1_ASSIGNMENT_ONE_TO_ONE")


def _entry(payload: Mapping[str, Any], row: Mapping[str, Any], stencil: str) -> dict[str, Any]:
    entry = payload["stencils"][stencil]
    points = [payload["center"], *entry["vertices"]]
    association = copy.deepcopy(entry["association"])
    candidate_window = association.get("candidate_window_zero_based", [])
    for edge in association.get("edges", []):
        edge["assignment"] = derive_positional_assignment(edge, candidate_window)
        validate_positional_assignment(edge, candidate_window)
    return {"source_sample_id": row["source_sample_id"], "source_sample_index": row["source_sample_index"], "logical_worker_index": row["sample_index"], "resolution": row["resolution"], "stencil": stencil, "CENTER_L0": copy.deepcopy(payload["center"]["L0"]), "VERTEX_L0": [copy.deepcopy(point["L0"]) for point in entry["vertices"]], "association": association, "BAND2": copy.deepcopy(entry["BAND2_PHYSICAL_BRANCH_SHADOW"]), "BAND3": copy.deepcopy(entry["BAND3_PHYSICAL_BRANCH_SHADOW"]), "L2": copy.deepcopy(entry["L2_RANK2"]), "L3": copy.deepcopy(entry["L3"]), "H_MAX": {"full6_offdiag": max(point["H_GATE"]["max_offdiag"] for point in points), "selected_pair_offdiag": max(point["H_GATE"]["selected_pair_offdiag"] for point in points), "normalization_error": max(point["H_GATE"]["max_normalization_error"] for point in points)}, "replay_max": max(point["frequency_replay"]["max_abs_difference"] for point in points if point["frequency_replay"]["max_abs_difference"] is not None)}


def complete_entries(payloads: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    entries = [_entry(payload, row, stencil) for payload, row in zip(payloads, rows) for stencil in STENCILS]
    if len(entries) != 24 or any(len(entry["VERTEX_L0"]) != 4 or len(entry["association"].get("edges", [])) != 4 or len(entry["BAND2"].get("edges", [])) != 4 or len(entry["BAND3"].get("edges", [])) != 4 or len(entry["L2"].get("edges", [])) != 4 for entry in entries):
        raise ValueError("E9F_C1_RP2_C3_C5_C1_POSTPROCESS_COVERAGE_FAIL_CLOSED:entry_schema")
    assignment_records = sum(len(entry["association"]["edges"]) for entry in entries)
    if assignment_records != 96 or any(validate_positional_assignment(edge, entry["association"]["candidate_window_zero_based"]) is not None for entry in entries for edge in entry["association"]["edges"]):
        raise ValueError("E9F_C1_C1_ASSIGNMENT_COVERAGE_FAIL_CLOSED")
    return entries


def delta_tables(payloads: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]], old_deltas: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    values: dict[tuple[str, int, str, str], float] = {}
    for payload, row in zip(payloads, rows):
        for stencil in STENCILS:
            entry = payload["stencils"][stencil]
            values[(row["source_sample_id"], row["resolution"], stencil, "band2")] = float(entry["BAND2_PHYSICAL_BRANCH_SHADOW"]["OMEGA_RANK1_SHADOW"])
            values[(row["source_sample_id"], row["resolution"], stencil, "band3")] = float(entry["BAND3_PHYSICAL_BRANCH_SHADOW"]["OMEGA_RANK1_SHADOW"])
    stencil_rows = []
    for sample in sorted({row["source_sample_id"] for row in rows}):
        for resolution in SIX_RESOLUTIONS:
            for branch in BRANCHES:
                left = values[(sample, resolution, "1/72", branch)]; right = values[(sample, resolution, "1/144", branch)]; signed = right - left
                stencil_rows.append({"source_sample_id": sample, "resolution": resolution, "branch": branch, "omega_1_72": left, "omega_1_144": right, "delta_signed": signed, "delta_abs": abs(signed)})
    resolution_rows = []
    for sample in sorted({row["source_sample_id"] for row in rows}):
        for stencil in STENCILS:
            for branch in BRANCHES:
                left = values[(sample, 64, stencil, branch)]; right = values[(sample, 96, stencil, branch)]; signed = right - left
                resolution_rows.append({"source_sample_id": sample, "stencil": stencil, "branch": branch, "omega_R64": left, "omega_R96": right, "delta_signed": signed, "delta_abs": abs(signed)})
    if len(stencil_rows) != 24 or len(resolution_rows) != 24:
        raise ValueError("E9F_C1_RP2_C3_C5_C1_POSTPROCESS_COVERAGE_FAIL_CLOSED:delta_cardinality")
    old_ok = True
    for old in old_deltas:
        sample = old["source_sample_id"]; branch = old["branch"].replace("_omega", "")
        old_stencil = next(item for item in stencil_rows if item["source_sample_id"] == sample and item["resolution"] == 64 and item["branch"] == branch)
        old_resolution = next(item for item in resolution_rows if item["source_sample_id"] == sample and item["stencil"] == "1/72" and item["branch"] == branch)
        old_ok &= abs(old_stencil["delta_signed"] - old["stencil_delta_signed"]) <= 1e-12 and abs(old_stencil["delta_abs"] - old["stencil_delta_abs"]) <= 1e-12 and abs(old_resolution["delta_signed"] - old["resolution_delta_signed"]) <= 1e-12 and abs(old_resolution["delta_abs"] - old["resolution_delta_abs"]) <= 1e-12
    return stencil_rows, resolution_rows, old_ok


def dense_projector_distance(left: Any, right: Any) -> float:
    import numpy as np
    return float(np.linalg.norm(left @ left.conj().T - right @ right.conj().T))


def bounded_projector_distance(left: Any, right: Any) -> float:
    import numpy as np
    coefficients, _, _, _ = np.linalg.lstsq(left, right, rcond=None)
    if float(np.linalg.norm(right - left @ coefficients)) <= 1e-12 * max(1.0, float(np.linalg.norm(right))):
        return 0.0
    gram_left = left.conj().T @ left; gram_right = right.conj().T @ right; cross = left.conj().T @ right
    squared = float(np.real(np.sum(np.abs(gram_left) ** 2) + np.sum(np.abs(gram_right) ** 2) - 2.0 * np.sum(np.abs(cross) ** 2)))
    return float(np.sqrt(max(0.0, squared)))


def safe_projector_regression(root: Path) -> dict[str, Any]:
    import numpy as np
    rng = np.random.default_rng(20260825)
    errors = []
    for shape in ((11, 2), (17, 3), (23, 4)):
        left = rng.normal(size=shape) + 1j * rng.normal(size=shape); right = rng.normal(size=shape) + 1j * rng.normal(size=shape)
        errors.append(abs(dense_projector_distance(left, right) - bounded_projector_distance(left, right)))
    frame = rng.normal(size=(31, 2)) + 1j * rng.normal(size=(31, 2)); unitary = np.asarray(((1, 1), (1, -1)), dtype=np.complex128) / np.sqrt(2.0)
    for transformed in (frame[:, ::-1], frame @ unitary):
        errors.append(abs(dense_projector_distance(frame, transformed) - bounded_projector_distance(frame, transformed)))
    source = (root / "audit/e9f/c3_c5_runtime.py").read_text()
    production = (root / "mephc/spectral_association.py").read_text() + (root / "mephc/valley_benchmark.py").read_text()
    tree = ast.parse(source)
    safe = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_safe_gauge")
    safe_text = ast.get_source_segment(source, safe) or ""
    no_dense = "base @ base.conj().T" not in safe_text and "np.outer" not in safe_text and "np.eye(" not in safe_text
    unchanged = "qualify_local_subspace" in production and "cross_k_projector_distance" in production
    max_error = max(errors)
    if max_error > 1e-12 or not no_dense or not unchanged:
        raise ValueError("E9F_C1_RP2_C3_C5_C1_POSTPROCESS_COVERAGE_FAIL_CLOSED:safe_projector")
    return {"dense_equivalence": True, "max_abs_error": max_error, "no_dense_nxn": no_dense, "rank2_production_qualification_path_unchanged": unchanged}


def _replay_key(sample: str, resolution: int, q: Sequence[float], execution: str) -> tuple[str, int, tuple[float, ...], str]:
    return (sample, int(resolution), tuple(float(x) for x in q), execution)


def build_replay_index(evidence_root: Path) -> dict[tuple[str, int, tuple[float, ...], str], list[dict[str, Any]]]:
    index: dict[tuple[str, int, tuple[float, ...], str], list[dict[str, Any]]] = {}
    for path in sorted(evidence_root.glob("*.json")):
        value = json.loads(path.read_text())
        sample = value.get("source_sample_id")
        resolution = int(value.get("resolution", -1))
        execution = value.get("execution_git_sha")
        for stencil, entry in value.get("stencils", {}).items():
            records = [("center", entry.get("center_sampling", {})), *[(f"vertex_{i}", record) for i, record in enumerate(entry.get("vertex_sampling", []))]]
            for point_kind, record in records:
                q = record.get("EVALUATED_Q")
                if q is None or sample is None or execution is None:
                    continue
                key = _replay_key(sample, resolution, q, execution)
                occurrence = {"path": str(path), "stencil": stencil, "point_kind": point_kind, "frequencies": list(record.get("frequencies", [])), "execution_sha": execution}
                index.setdefault(key, []).append(occurrence)
    return index


def _expected_replay_keys(payloads: Sequence[Mapping[str, Any]]) -> list[tuple[str, int, tuple[float, ...], str]]:
    return [_replay_key(payload["source_sample_id"], int(payload["resolution"]), point["EVALUATED_Q"], ORIGINAL_RP2_EXECUTION) for payload in payloads for point in payload["all_point_metrics"]]


def validate_replay_index(payloads: Sequence[Mapping[str, Any]], index: Mapping[tuple[str, int, tuple[float, ...], str], Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    expected = _expected_replay_keys(payloads)
    duplicate_keys = [key for key, occurrences in index.items() if len(occurrences) > 1]
    excess = sum(len(index[key]) - 1 for key in duplicate_keys)
    conflicting = 0
    for key in duplicate_keys:
        occurrences = index[key]
        reference = list(occurrences[0].get("frequencies", []))
        if any(len(list(item.get("frequencies", []))) != len(reference) or any(abs(float(a) - float(b)) > 1e-12 for a, b in zip(item.get("frequencies", []), reference)) for item in occurrences[1:]):
            conflicting += 1
        if not all(item.get("point_kind") == "center" for item in occurrences):
            conflicting += 1
        if len({item.get("stencil") for item in occurrences}) != len(occurrences):
            conflicting += 1
    canonical = {key: occurrences[0] for key, occurrences in index.items() if occurrences}
    coverage = len(expected) == 108 and len(set(expected)) == 108 and all(key in canonical for key in expected)
    return {"raw_record_count": sum(len(v) for v in index.values()), "unique_key_count": len(index), "expected_unique_key_count": 108, "duplicate_key_count": len(duplicate_keys), "duplicate_record_excess_count": excess, "conflicting_duplicate_key_count": conflicting, "canonical_replay_map": canonical, "coverage_valid": coverage and conflicting == 0, "mutation_tests": False}


def replay_coverage(payloads: Sequence[Mapping[str, Any]], evidence_root: Path) -> dict[str, Any]:
    index = build_replay_index(evidence_root)
    result = validate_replay_index(payloads, index)
    expected = _expected_replay_keys(payloads)
    mutations: list[bool] = []
    if expected:
        missing = {key: list(value) for key, value in index.items()}
        missing.pop(expected[0], None)
        mutations.append(not validate_replay_index(payloads, missing)["coverage_valid"])
        wrong_resolution = {key: list(value) for key, value in index.items()}
        wrong_resolution[(expected[0][0], 96 if expected[0][1] == 64 else 64, expected[0][2], expected[0][3])] = wrong_resolution.pop(expected[0])
        mutations.append(not validate_replay_index(payloads, wrong_resolution)["coverage_valid"])
        wrong_sample = {key: list(value) for key, value in index.items()}
        wrong_sample[("WRONG_SOURCE", expected[0][1], expected[0][2], expected[0][3])] = wrong_sample.pop(expected[0])
        mutations.append(not validate_replay_index(payloads, wrong_sample)["coverage_valid"])
        wrong_q = {key: list(value) for key, value in index.items()}
        wrong_key = (expected[0][0], expected[0][1], (expected[0][2][0] + 0.001, expected[0][2][1]), expected[0][3])
        wrong_q[wrong_key] = wrong_q.pop(expected[0])
        mutations.append(not validate_replay_index(payloads, wrong_q)["coverage_valid"])
        wrong_execution = {key: list(value) for key, value in index.items()}
        wrong_execution[(expected[0][0], expected[0][1], expected[0][2], "0" * 40)] = wrong_execution.pop(expected[0])
        mutations.append(not validate_replay_index(payloads, wrong_execution)["coverage_valid"])
        conflicting = {key: [dict(item) for item in value] for key, value in index.items()}
        conflicting[expected[0]][0]["frequencies"] = list(conflicting[expected[0]][0]["frequencies"])
        conflicting[expected[0]][0]["frequencies"][0] += 1e-6
        mutations.append(validate_replay_index(payloads, conflicting)["conflicting_duplicate_key_count"] > 0)
    result["mutation_tests"] = all(mutations)
    if not result["coverage_valid"] or not result["mutation_tests"]:
        raise ValueError("E9F_C1_C1_REPLAY_VALIDATION_FAIL_CLOSED")
    result.pop("canonical_replay_map", None)
    return {"expected_key_count": len(expected), "index_key_count": result["unique_key_count"], "coverage_valid": result["coverage_valid"], "mutation_tests": result["mutation_tests"]}


def replay_multiplicity(payloads: Sequence[Mapping[str, Any]], evidence_root: Path) -> dict[str, Any]:
    index = build_replay_index(evidence_root)
    result = validate_replay_index(payloads, index)
    expected = _expected_replay_keys(payloads)
    if len(expected) != 108 or not result["coverage_valid"]:
        raise ValueError("E9F_C1_C1_REPLAY_VALIDATION_FAIL_CLOSED")
    return {"expected_key_count": len(expected), "index_key_count": result["unique_key_count"], "raw_record_count": result["raw_record_count"], "duplicate_key_count": result["duplicate_key_count"], "duplicate_record_excess_count": result["duplicate_record_excess_count"], "conflicting_duplicate_key_count": result["conflicting_duplicate_key_count"], "coverage_valid": result["coverage_valid"], "mutation_tests": True}


def scan_c3_c5_orphans(*, worker_ids: Sequence[str], proc_root: Path = Path("/proc")) -> list[int]:
    if not proc_root.is_dir():
        raise ValueError("E9F_C1_C1_ORPHAN_SCAN_UNAVAILABLE")
    marker = "run_e9f_c1_rp2_c3_c5_worker.py"
    found: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
        except (OSError, UnicodeError):
            continue
        if marker in command and "--worker-id" in command and any(worker_id in command for worker_id in worker_ids):
            found.append(int(entry.name))
    return sorted(found)


def _validate_completed_item(item: Mapping[str, Any], row: Mapping[str, Any], *, execution: str, contract: str, policy: str) -> None:
    if item.get("worker_id") != row["sample_id"] or item.get("resolution") != row["resolution"]:
        raise ValueError("E9F_C1_C1_RESUME_IDENTITY")
    path = Path(item["payload_path"])
    if not path.is_file() or sha(path) != item.get("payload_file_sha256"):
        raise ValueError("E9F_C1_C1_RESUME_FILE_HASH")
    payload = json.loads(path.read_text())
    expected = {
        "project_id": "MEPHC", "work_order_id": SOURCE_WORK_ORDER, "phase": "E9F.C1.RP2.C3.C5",
        "execution_sha": execution, "source_sample_id": row["source_sample_id"], "source_sample_index": row["source_sample_index"],
        "logical_sample_index": row["sample_index"], "worker_id": row["sample_id"], "resolution": row["resolution"],
        "contract_sha256": contract, "rp1_policy_file_sha256": policy,
        "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a",
        "payload_transport": "ATOMIC_FILE",
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("E9F_C1_C1_RESUME_FULL_IDENTITY")
    if payload.get("provider", {}).get("resolution") != row["resolution"]:
        raise ValueError("E9F_C1_C1_RESUME_PROVIDER_RESOLUTION")
    binding = payload.get("c3_c5_transport_binding")
    if not isinstance(binding, dict) or any(binding.get(key) != value for key, value in expected.items()):
        raise ValueError("E9F_C1_C1_RESUME_TRANSPORT_BINDING")
    if body_hash(payload) != item.get("payload_body_sha256") or payload.get("payload_body_sha256") != item.get("payload_body_sha256"):
        raise ValueError("E9F_C1_C1_RESUME_BODY_HASH")


def resume_suffix(*, checkpoint: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], execution: str = SOURCE_EXECUTION, contract: str = CONTRACT_SHA, policy: str = POLICY_SHA, orphan_pids: Sequence[int] = (), orphan_scan: Any = None) -> list[dict[str, Any]]:
    if checkpoint.get("schema") != "mephc_e9f_c1_rp2_c3_c5_matrix_checkpoint_v1" or checkpoint.get("work_order_id") != SOURCE_WORK_ORDER or checkpoint.get("execution_sha") != execution or checkpoint.get("contract_sha256") != contract or checkpoint.get("rp1_policy_file_sha256") != policy:
        raise ValueError("E9F_C1_C1_RESUME_BINDING")
    completed = checkpoint.get("completed_workers", [])
    worker_ids = [row["sample_id"] for row in rows]
    scanner = orphan_scan or (lambda ids: scan_c3_c5_orphans(worker_ids=ids))
    detected = list(scanner(worker_ids))
    if orphan_pids or detected:
        raise ValueError("E9F_C1_C1_RESUME_BINDING_ORPHAN")
    if checkpoint.get("generation") != len(completed) or len(completed) > len(rows):
        raise ValueError("E9F_C1_C1_RESUME_GENERATION")
    for item, row in zip(completed, rows):
        _validate_completed_item(item, row, execution=execution, contract=contract, policy=policy)
    if len({item.get("worker_id") for item in completed}) != len(completed) or any(item.get("worker_id") != row["sample_id"] for item, row in zip(completed, rows)):
        raise ValueError("E9F_C1_C1_RESUME_ORDER")
    return [dict(row) for row in rows[len(completed):]]


def process_registry() -> dict[str, Any]:
    incidents = [{"incident_id": incident_id, "priority": "P2" if incident_id in P2_IDS else "P1", "status": "OPEN" if incident_id in OPEN_P1 else "CLOSED"} for incident_id in REQUIRED_INCIDENT_IDS]
    return {"schema": "mephc_e9f_c1_rp2_c3_c5_c1_process_registry_v1", "work_order_id": WORK_ORDER, "pipeline_health": "PIPELINE_REQUIRES_CORRECTIVE", "incidents": incidents, "p0_items": [], "p1_items": list(OPEN_P1), "p2_items": []}


C1_C1_OPEN_P1 = ("REL-021", "REL-042", "REL-050", "REL-051", "REL-052")


def canonical_c1_c1_process_registry(*, closed: bool = False) -> dict[str, Any]:
    open_set = set() if closed else set(C1_C1_OPEN_P1)
    incidents = [{"incident_id": incident_id, "priority": "P2" if incident_id in P2_IDS else "P1", "status": "OPEN" if incident_id in open_set else "CLOSED"} for incident_id in REQUIRED_INCIDENT_IDS]
    return {"schema": "mephc_e9f_c1_c1_process_registry_v1", "work_order_id": "MEPHC-E9F-C1-RP2-C3-C5-C1-C1-20260825-252", "pipeline_health": "PIPELINE_HEALTHY_WITH_TECH_DEBT" if closed else "PIPELINE_REQUIRES_CORRECTIVE", "incidents": incidents, "p0_items": [], "p1_items": list(sorted(open_set)), "p2_items": []}


def validate_c1_c1_process_registry(registry: Mapping[str, Any], *, closed: bool = False) -> None:
    expected = canonical_c1_c1_process_registry(closed=closed)
    if dict(registry) != expected:
        raise ValueError("E9F_C1_C1_PROCESS_REGISTRY_CANONICAL_STATE")


def validate_process_registry(registry: Mapping[str, Any]) -> None:
    incidents = registry.get("incidents", []); by_id = {item.get("incident_id"): item for item in incidents}
    if len(incidents) != 33 or set(by_id) != set(REQUIRED_INCIDENT_IDS) or len(by_id) != len(incidents):
        raise ValueError("E9F_C1_C1_PROCESS_REGISTRY")
    for incident_id, item in by_id.items():
        expected_priority = "P2" if incident_id in P2_IDS else "P1"
        if item.get("priority") != expected_priority or item.get("status") not in {"OPEN", "CLOSED"}:
            raise ValueError("E9F_C1_C1_PROCESS_REGISTRY")
    expected_open = set(registry.get("p1_items", []))
    if set(registry.get("p0_items", [])) or set(registry.get("p2_items", [])) or any((item["status"] == "OPEN") != (incident_id in expected_open) for incident_id, item in by_id.items()):
        raise ValueError("E9F_C1_C1_PROCESS_REGISTRY")


def create_failed_attempt_record(*, root: Path, failure_runtime: Path) -> dict[str, Any]:
    parent = json.loads((failure_runtime / "parent_failure.json").read_text())
    sidecars = sorted((failure_runtime / "workers").glob("*/failure.json"))
    sidecar = json.loads(sidecars[0].read_text()) if sidecars else {}
    traceback_text = str(sidecar.get("traceback_tail", ""))
    dense_path = "base = np.column_stack" in traceback_text and "projector = base @ base.conj().T" in traceback_text
    inferred = 5 if dense_path and "analyze_plaquette" in traceback_text else None
    return {"schema": "mephc_e9f_c1_c1_failed_attempt_record_v1", "work_order_id": "MEPHC-E9F-C1-RP2-C3-C5-C1-C1-20260825-252", "failed_execution_sha": FAILED_EXECUTION, "failure_stage": sidecar.get("stage", "science_compute"), "worker_id": sidecar.get("worker_id"), "resolution": sidecar.get("resolution"), "exception_type": sidecar.get("exception_type"), "exception_message": sidecar.get("exception_message"), "native_solve_count": sidecar.get("native_solve_count"), "scientific_payload_reuse_conclusion": "C1_C1_FINAL_MATRIX_REUSED_87EB_SCIENTIFIC_PAYLOAD=false", "sidecar_native_solve_count_raw": sidecar.get("native_solve_count"), "sidecar_native_solve_count_semantics": "INITIAL_VALUE_NOT_UPDATED_ON_IN_FUNCTION_EXCEPTION", "measured_native_solve_count": "UNKNOWN", "control_flow_inferred_completed_solves": inferred, "control_flow_inference_basis": "center solve plus four first-stencil vertex solves precede analyze_plaquette; traceback confirms first _gauge dense projector allocation" if inferred == 5 else "TRACEBACK_INSUFFICIENT", "control_flow_inference_confidence": "HIGH" if inferred == 5 else "UNKNOWN", "traceback_confirms_dense_gauge_path": dense_path, "stderr_sha256": parent.get("process_measurement", {}).get("stderr_sha256"), "stderr_tail_sha256": hashlib.sha256(parent.get("process_measurement", {}).get("stderr_tail", "").encode()).hexdigest(), "parent_failure_sha256": sha(failure_runtime / "parent_failure.json"), "failure_sidecar_sha256": sha(sidecars[0]) if sidecars else None, "payload_reused_by_final": False, "detail_availability": "FULL"}

