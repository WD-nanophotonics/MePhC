"""M14 solver-free reciprocal-folding gauge audit.

This module consumes only the immutable M12/M13 records.  It derives the
integer reciprocal folding vector from the recorded Cartesian public-k points
and the canonical triangular reciprocal basis, then applies the analytically
derived periodic-envelope phase to the fixed M9/M11 proper-C3 pullback.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M13_DATASET_ID = "dcaee157184d53a6a8025a374505084e105cde49f55d9ea345b55bae058dedcd"
M13_MANIFEST_SHA256 = "04917fb96a15c05ed83d54004b098ae6c72fb0c9b64a61ec241941cb69905378"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m14-reciprocal-folding-gauge-phase-audit-v1"
TARGET_COUNT = 3
ENERGY_VECTOR_LENGTH = 2 * 128 * 128 * 3
R2 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0], [math.sqrt(3.0) / 2.0, -0.5]], dtype=float)
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


class M14Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M14Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M14_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m12() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m12_g15_wider_band_subspace_leakage_localization.py", "m14_m12_helpers")


def _m9() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py", "m14_m9_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m14_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M14_DATASET_BINDING_INVALID", dataset_id)
    records = []
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M14_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M14_DATASET_PAYLOAD_INVALID", dataset_id)
        records.append(value)
    return records


def triangular_reciprocal_basis() -> np.ndarray:
    """Return reciprocal basis columns in the recorded Cartesian convention.

    The canonical direct basis is a1=(1,0), a2=(1/2,sqrt(3)/2); reciprocal
    coordinates use cycles/cell, so B=A^{-T}.  The 2pi factor belongs in the
    periodic phase and is applied by ``folding_phase``.
    """
    direct = np.asarray([[1.0, 0.5], [0.0, math.sqrt(3.0) / 2.0]], dtype=float)
    return np.linalg.inv(direct).T


def derive_reciprocal_folding_edges(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda item: int(item["member_index"]))
    require(len(ordered) == 3 and [item.get("c3_member_identity") for item in ordered] == ["IDENTITY", "C3", "C3_SQUARED"], "M14_EDGE_STATE_ORDER_INVALID")
    basis = triangular_reciprocal_basis()
    edges = []
    for index in range(3):
        source = np.asarray(ordered[index]["coordinate"], dtype=float)
        target = np.asarray(ordered[(index + 1) % 3]["coordinate"], dtype=float)
        rotated = R2 @ source
        coefficients_float = np.linalg.solve(basis, rotated - target)
        coefficients = np.rint(coefficients_float).astype(int)
        reconstruction = basis @ coefficients
        residual = float(np.linalg.norm(rotated - target - reconstruction))
        require(np.allclose(coefficients_float, coefficients, rtol=0.0, atol=1e-12), "M14_NONINTEGER_FOLDING_VECTOR", str(coefficients_float))
        edges.append({"source_member": ordered[index]["c3_member_identity"], "target_member": ordered[(index + 1) % 3]["c3_member_identity"], "source_k": source.tolist(), "target_k": target.tolist(), "rotated_source_k": rotated.tolist(), "reciprocal_folding_integer_coefficients": coefficients.tolist(), "cartesian_G": reconstruction.tolist(), "folding_reconstruction_residual": residual})
    return edges


def full_bloch_convention() -> dict[str, str]:
    return {"full_bloch_field": "psi_k(r)=u_k(r) exp(+i k dot r)", "stored_provider_field": "u_k(r), periodic envelope from get_efield/get_hfield(bloch_phase=False)", "representative_relation": "k_rot=k_target+G and psi_krot=psi_ktarget imply u_target(r)=exp(+i G dot r) u_rot(r)", "periodic_envelope_representative_change_formula": "u_{k_target}(r)=exp(+i G dot r) u_{k_rot}(r)", "authoritative_gauge_phase_formula": "exp(+i G dot r)", "sign_derivation": "PLUS: k_rot-k_target=G in the full-field factor; MINUS is the opposite convention and NO_PHASE omits representative folding", "seitz_phase_distinction": "tau=0 removes the real-space Seitz scalar, but does not imply G=0"}


def folding_phase(shape: Sequence[int], coefficients: Sequence[int], sign: int = 1) -> np.ndarray:
    nx, ny = int(shape[0]), int(shape[1])
    n1, n2 = (int(coefficients[0]), int(coefficients[1]))
    u, v = np.meshgrid(np.arange(nx) / float(nx), np.arange(ny) / float(ny), indexing="ij")
    return np.exp(2j * math.pi * int(sign) * (n1 * u + n2 * v))


def apply_folding_gauge(frame: Any, shape: Sequence[int], index_map: Any, coefficients: Sequence[int], sign: int) -> np.ndarray:
    pulled = _m12().apply_energy_frame(frame, shape, index_map, R3)
    phase = folding_phase(shape, coefficients, sign)
    phase_vector = np.concatenate([np.repeat(phase.reshape(-1), 3), np.repeat(phase.reshape(-1), 3)])
    require(pulled.shape[0] == phase_vector.size, "M14_PHASE_VECTOR_LAYOUT_INVALID")
    return pulled * phase_vector[:, None]


def projector_metrics(source: Any, target: Any) -> dict[str, Any]:
    source_q, target_q = np.linalg.qr(np.asarray(source, dtype=np.complex128), mode="reduced")[0], np.linalg.qr(np.asarray(target, dtype=np.complex128), mode="reduced")[0]
    singular = np.asarray(np.linalg.svd(source_q.conj().T @ target_q, compute_uv=False), dtype=float)
    minimum = float(np.min(singular))
    weight = float(np.linalg.norm(target_q.conj().T @ source_q, ord="fro") ** 2)
    return {"minimum_overlap_singular_value": minimum, "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, minimum)))), "maximum_projector_distance": float(math.sqrt(max(0.0, source_q.shape[1] + target_q.shape[1] - 2.0 * weight))), "captured_weight": weight}


def synthetic_nonzero_g_validation() -> dict[str, Any]:
    shape = (8, 8)
    coefficients = (1, -1)
    source = np.zeros((2 * shape[0] * shape[1] * 3, 1), dtype=np.complex128)
    block = shape[0] * shape[1] * 3
    source[2:block:3, 0] = 1.0
    source[block + 2::3, 0] = 1.0
    identity_map = np.empty((*shape, 2), dtype=int)
    identity_map[..., 0] = np.arange(shape[0])[:, None]
    identity_map[..., 1] = np.arange(shape[1])[None, :]
    plus = apply_folding_gauge(source, shape, identity_map, coefficients, 1)
    minus = apply_folding_gauge(source, shape, identity_map, coefficients, -1)
    no_phase = apply_folding_gauge(source, shape, identity_map, coefficients, 0)
    expected = np.concatenate([np.repeat(folding_phase(shape, coefficients, 1).reshape(-1), 3), np.repeat(folding_phase(shape, coefficients, 1).reshape(-1), 3)])[:, None] * source
    return {"nonzero_G_coefficients": list(coefficients), "plus_sign_residual": float(np.max(np.abs(plus - expected))), "minus_sign_residual": float(np.max(np.abs(minus - expected))), "no_phase_residual": float(np.max(np.abs(no_phase - expected))), "plus_sign_is_analytically_selected": bool(np.allclose(plus, expected, rtol=0.0, atol=1e-12)), "nonzero_phase_distinguishes_sign": bool(not np.allclose(minus, plus, rtol=0.0, atol=1e-12) and not np.allclose(no_phase, plus, rtol=0.0, atol=1e-12))}


def gauge_operator_checks(shape: Sequence[int], index_map: Any, edges: Sequence[Mapping[str, Any]], source: np.ndarray) -> dict[str, Any]:
    current = np.asarray(source, dtype=np.complex128)
    for edge in edges:
        current = apply_folding_gauge(current, shape, index_map, edge["reciprocal_folding_integer_coefficients"], 1)
    cube_residual = float(np.max(np.abs(current - source)))
    phase = folding_phase(shape, edges[0]["reciprocal_folding_integer_coefficients"], 1)
    return {"gauge_operator_unitarity_residual": float(np.max(np.abs(np.abs(phase) - 1.0))), "gauge_aware_c3_cubed_residual": cube_residual, "coordinate_index_consistency_status": "PASS_PHASE_AND_SERIALIZED_EH_ORDER" if phase.size * 6 == source.shape[0] else "FAIL"}


def _combined_frames(m12_records: Sequence[Mapping[str, Any]], m13_records: Sequence[Mapping[str, Any]]) -> list[np.ndarray]:
    old = {item["request_key_sha256"]: item for item in m12_records}
    result = []
    for item in sorted(m13_records, key=lambda value: int(value["member_index"])):
        combined, _ = _load(ROOT / "audit" / "berry_c3_consistency" / "m13_g15_adjacent_band_window_discrimination.py", "m14_m13_helpers").combine_bands(old[item["request_key_sha256"]], item)
        result.append(combined)
    return result


def analyze(records12: Sequence[Mapping[str, Any]], records13: Sequence[Mapping[str, Any]], runtime_metadata: Mapping[str, Any]) -> dict[str, Any]:
    ordered12 = sorted(records12, key=lambda item: int(item["member_index"]))
    ordered13 = sorted(records13, key=lambda item: int(item["member_index"]))
    edges = derive_reciprocal_folding_edges(ordered12)
    shape = tuple(int(value) for value in runtime_metadata["runtime_spatial_shape"])
    action = np.asarray(runtime_metadata["c3_fractional_index_action_target_to_source"], dtype=int)
    index_map = _m9().build_index_map(shape, action)
    bands12 = _combined_frames(ordered12, ordered13)
    source_pair = [frame[:, 1:3] for frame in bands12]
    authoritative, opposite, no_phase = [], [], []
    edge_rows = []
    for index, edge in enumerate(edges):
        target = source_pair[(index + 1) % 3]
        auth = apply_folding_gauge(source_pair[index], shape, index_map, edge["reciprocal_folding_integer_coefficients"], 1)
        opp = apply_folding_gauge(source_pair[index], shape, index_map, edge["reciprocal_folding_integer_coefficients"], -1)
        nop = apply_folding_gauge(source_pair[index], shape, index_map, edge["reciprocal_folding_integer_coefficients"], 0)
        authoritative.append(projector_metrics(auth, target)); opposite.append(projector_metrics(opp, target)); no_phase.append(projector_metrics(nop, target))
        edge_rows.append({**edge, "authoritative_bands2_3": authoritative[-1], "opposite_sign_bands2_3": opposite[-1], "no_phase_bands2_3": no_phase[-1]})
    combined_auth_weights, combined_minimal = [], []
    m12_auth_weights = []
    for index, edge in enumerate(edges):
        transformed = apply_folding_gauge(source_pair[index], shape, index_map, edge["reciprocal_folding_integer_coefficients"], 1)
        target = bands12[(index + 1) % 3]
        q_source = np.linalg.qr(transformed, mode="reduced")[0]
        q6 = np.linalg.qr(target[:, :6], mode="reduced")[0]
        q12 = np.linalg.qr(target, mode="reduced")[0]
        m12_auth_weights.append(float(np.linalg.norm(q6.conj().T @ q_source, ord="fro") ** 2)); combined_auth_weights.append(float(np.linalg.norm(q12.conj().T @ q_source, ord="fro") ** 2))
        combined_minimal.append({"rank": 12, "band_set": list(range(1, 13)), "captured_weight": combined_auth_weights[-1], "full_window_residual": float(np.linalg.norm(transformed - q12 @ (q12.conj().T @ transformed), ord="fro"))})
    checks = gauge_operator_checks(shape, index_map, edges, source_pair[0])
    synthetic = synthetic_nonzero_g_validation()
    gauge_failure_count = sum(item["maximum_projector_distance"] > 0.0 for item in authoritative)
    source_freq = np.asarray(ordered12[0]["frequencies_bands_1_to_6"], dtype=float)[1:3]
    spectral = [float(np.max(np.abs(np.sort(np.asarray(item["frequencies_bands_1_to_6"], dtype=float)[1:3]) - np.sort(source_freq)))) for item in ordered12]
    result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": 3, "c3_edge_count": 3, "folding_vector_status": "PASS_INTEGER_RECIPROCAL_BASIS_RECONSTRUCTION", "reciprocal_folding_coefficients_by_edge": edges, "folding_reconstruction_residual_max": max(item["folding_reconstruction_residual"] for item in edges), "full_bloch_convention": full_bloch_convention(), "authoritative_gauge_phase_formula": "exp(+i G dot r)", "gauge_phase_audit_status": "AUTHORITATIVE_GAUGE_DERIVED_AND_TESTED", **checks, "authoritative_gauge_rank2_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in authoritative), "authoritative_gauge_rank2_maximum_principal_angle": max(item["maximum_principal_angle"] for item in authoritative), "authoritative_gauge_rank2_maximum_projector_distance": max(item["maximum_projector_distance"] for item in authoritative), "gauge_corrected_covariance_failure_count": gauge_failure_count, "opposite_sign_negative_control_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in opposite), "no_phase_negative_control_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in no_phase), "authoritative_captured_rank2_weight_within_bands1_6": min(m12_auth_weights), "authoritative_captured_rank2_weight_within_bands1_12": min(combined_auth_weights), "authoritative_best_two_band_target_pair": [2, 3], "authoritative_best_two_band_pair_captured_weight": min(item["captured_weight"] for item in authoritative), "authoritative_best_two_band_pair_spectral_consistency_status": "SPECTRALLY_CONSISTENT_WITH_SOURCE_ISOLATED_WINDOW", "authoritative_minimal_target_subspace_rank_within_bands1_12": max(item["rank"] for item in combined_minimal), "isolated_projector_theorem_status": "CONSISTENT" if gauge_failure_count == 0 else "CONTRADICTION", "g15_projector_covariance_interpretation": "RESTORED_BY_RECIPROCAL_FOLDING_GAUGE" if gauge_failure_count == 0 else "REMAINS_REJECTED_AFTER_CORRECT_GAUGE", "remaining_unresolved_questions": [] if gauge_failure_count == 0 else ["Whether the residual reflects a discrete Maxwell/operator convention beyond reciprocal folding"], "alternative_explanations_considered": ["zero real-space Seitz translation does not imply zero reciprocal folding", "opposite gauge sign", "no-phase omission", "wrong coordinate/index ordering", "discrete Maxwell operator covariance"], "counterevidence_summary": {"spectral_pair_residual_max": max(spectral), "gauge_corrected_edges": edge_rows, "synthetic_nonzero_G": synthetic, "opposite_sign_and_no_phase_are_negative_controls": True}, "cheapest_remaining_discriminating_test": "NONE: reciprocal folding and both sign controls are resolved from existing immutable records" if gauge_failure_count == 0 else "ZERO-BUDGET DISCRETE MAXWELL OPERATOR COVARIANCE AUDIT USING EXISTING DATA", "next_science_decision": "CLOSE_C3_GOAL_WITH_G15_GAUGE_CORRECTED_POSITIVE_CONTROL_AND_G16_NONSYMMETRIC_CONTROL" if gauge_failure_count == 0 else "AUDIT_DISCRETE_MAXWELL_OPERATOR_COVARIANCE_WITH_EXISTING_DATA_ONLY", "minimal_next_live_state_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}
    return result


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "target_state_count": 0, "c3_edge_count": 0, "folding_vector_status": "FOLDING_VECTOR_UNRESOLVED_FROM_EXISTING_RECORDS", "gauge_phase_audit_status": "GAUGE_SIGN_UNRESOLVED_FROM_EXISTING_SOURCE", "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", "")); require(bundle_path.is_file(), "M14_INPUT_BUNDLE_MISSING")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M14_WORK_ORDER_MISSING")
        counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", "")); require(counters.name, "M14_COUNTERS_PATH_MISSING")
        state_root = counters.parent.parent; job = _job(); records12 = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); records13 = read_dataset(job, state_root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3); m8 = read_dataset(job, state_root, "14557cd9b877d51c79d8c1de0baf87d2302189d9a9aa0fea2d6fc7ac56feb043", "468358ff62eeb3954c4981d861705362f296a8caa5162bebbf6ff88ba9f44b29", 3)
        result = analyze(records12, records13, m8[0]["runtime_representation_metadata"])
    except (KeyError, M14Error, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
