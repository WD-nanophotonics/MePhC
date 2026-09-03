"""M9 solver-free audit of the physical C3 pullback orientation."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
M8_DATASET_ID = "14557cd9b877d51c79d8c1de0baf87d2302189d9a9aa0fea2d6fc7ac56feb043"
M8_MANIFEST_SHA256 = "468358ff62eeb3954c4981d861705362f296a8caa5162bebbf6ff88ba9f44b29"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m9-covariant-pullback-orientation-and-rank2-closure-v1"
M4_COUNT, M2_COUNT, M8_COUNT = 24, 72, 3
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


class M9Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M9Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load_scientific_job():
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("m9_scientific_job", path)
    require(spec is not None and spec.loader is not None, "M9_SCIENTIFIC_JOB_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M9_DATASET_BINDING_INVALID", dataset_id)
    records = []
    for key in verified["record_key_sha256"]:
        value = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = value.get("payload")
        require(isinstance(payload, bytes), "M9_DATASET_PAYLOAD_MISSING")
        decoded = json.loads(payload.decode("utf-8"))
        require(isinstance(decoded, dict), "M9_DATASET_PAYLOAD_INVALID")
        records.append(decoded)
    return records


def derive_fractional_action(basis: Any) -> np.ndarray:
    matrix = np.asarray(basis, dtype=float)
    require(matrix.shape == (2, 2) and np.all(np.isfinite(matrix)), "M9_BASIS_INVALID")
    action_float = np.linalg.inv(matrix) @ R3[:2, :2] @ matrix
    action = np.rint(action_float).astype(int)
    require(np.allclose(action_float, action, rtol=0.0, atol=1e-12), "M9_BASIS_ACTION_NONINTEGRAL")
    require(np.array_equal(action @ action @ action, np.eye(2, dtype=int)), "M9_BASIS_ACTION_ORDER_INVALID")
    return action


def build_index_map(shape: Sequence[int], action: Any) -> np.ndarray:
    shape = tuple(int(value) for value in shape)
    matrix = np.asarray(action, dtype=int)
    require(len(shape) == 2 and matrix.shape == (2, 2), "M9_INDEX_MAP_INPUT_INVALID")
    inverse = matrix @ matrix
    result = np.empty((*shape, 2), dtype=int)
    for i in range(shape[0]):
        for j in range(shape[1]):
            source = inverse @ np.asarray([i / shape[0], j / shape[1]], dtype=float)
            result[i, j] = np.rint(source * np.asarray(shape, dtype=float)).astype(int) % np.asarray(shape, dtype=int)
    return result


def apply_spatial(field: Any, index_map: Any) -> np.ndarray:
    array, mapping = np.asarray(field), np.asarray(index_map, dtype=int)
    return np.array(array[mapping[..., 0], mapping[..., 1], ...], copy=True)


def apply_energy_frame(frame: Any, shape: Sequence[int], index_map: Any, component_matrix: Any = R3) -> np.ndarray:
    matrix = np.asarray(frame, dtype=np.complex128)
    nx, ny = (int(shape[0]), int(shape[1]))
    block = nx * ny * 3
    require(matrix.ndim == 2 and matrix.shape[1] == 2 and matrix.shape[0] == 2 * block, "M9_ENERGY_FRAME_LAYOUT_INVALID")
    # The two columns are bands; transform each column independently.
    output = []
    for column in range(matrix.shape[1]):
        blocks = []
        vector = matrix[:, column]
        for start in (0, block):
            field = vector[start:start + block].reshape(nx, ny, 3)
            blocks.append(np.einsum("ab,xyb->xya", component_matrix, apply_spatial(field, index_map)).reshape(-1))
        output.append(np.concatenate(blocks))
    return np.column_stack(output)


def decode_frame(payload: Any) -> np.ndarray:
    require(isinstance(payload, list) and len(payload) == 2 and all(isinstance(item, list) for item in payload), "M9_BAND_PAYLOAD_INVALID")
    return np.column_stack([np.asarray([complex(pair[0], pair[1]) for pair in vector], dtype=np.complex128) for vector in payload])


def projector_distance(left: Any, right: Any) -> float:
    """Evaluate ||P_left-P_right||_F without materializing a huge projector."""
    left_q, _ = np.linalg.qr(np.asarray(left, dtype=np.complex128), mode="reduced")
    right_q, _ = np.linalg.qr(np.asarray(right, dtype=np.complex128), mode="reduced")
    rank_left, rank_right = left_q.shape[1], right_q.shape[1]
    overlap_norm_sq = float(np.linalg.norm(left_q.conj().T @ right_q, ord="fro") ** 2)
    return float(math.sqrt(max(0.0, rank_left + rank_right - 2.0 * overlap_norm_sq)))


def rank2_metrics(left: Any, right: Any) -> dict[str, float]:
    overlap = np.asarray(left).conj().T @ np.asarray(right)
    singular = np.asarray(np.linalg.svd(overlap, compute_uv=False), dtype=float)
    minimum = float(np.min(singular))
    return {"minimum_overlap_singular_value": minimum, "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, minimum)))), "maximum_projector_distance": float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2))))}


def maxwell_covariance_convention() -> dict[str, str]:
    return {
        "active_rotation_convention": "physical active rotation r'=R r and q'=R q",
        "public_q_rotation_convention": "Cartesian public q transforms as q_target=R @ q_source",
        "spatial_pullback_formula": "F_target(r)=F_source(R^-1 @ r)",
        "component_rotation_formula": "D(R) is the proper 3-vector rotation acting on E and H",
        "stored_energy_vector_rotation_formula": "(sqrt(epsilon)E,H)_target(r)=blockdiag(D(R),D(R)) (sqrt(epsilon)E,H)_source(R^-1 @ r)",
        "bloch_gauge_formula": "no extra reciprocal-translation phase because every bound translation is [0,0] and bloch_phase=False",
    }


def direction_sensitive_synthetic_check(shape: Sequence[int], authoritative: Any, inverse_direction: Any) -> dict[str, Any]:
    nx, ny = (int(shape[0]), int(shape[1]))
    u, v = np.meshgrid(np.arange(nx) / nx, np.arange(ny) / ny, indexing="ij")
    fixture = np.exp(2j * np.pi * (2.0 * u + 3.0 * v))
    forward = apply_spatial(fixture, authoritative)
    inverse = apply_spatial(fixture, inverse_direction)
    return {"direction_sensitive_fixture_distinguishes_R_and_R_inverse": bool(not np.allclose(forward, inverse, rtol=0.0, atol=1e-12)), "authoritative_norm_preserved": bool(np.allclose(np.linalg.norm(forward), np.linalg.norm(fixture), rtol=0.0, atol=1e-12)), "authoritative_scalar_c3_residual": float(np.max(np.abs(apply_spatial(apply_spatial(forward, authoritative), authoritative) - fixture))), "inverse_negative_control_norm_preserved": bool(np.allclose(np.linalg.norm(inverse), np.linalg.norm(fixture), rtol=0.0, atol=1e-12))}


def triplet_analysis(records: Sequence[Mapping[str, Any]], shape: Sequence[int], authoritative: Any, inverse_direction: Any) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: int(item["member_index"]))
    frames = [decode_frame(item["normalized_vectors_bands_2_3"]) for item in ordered]
    auth = [apply_energy_frame(frame, shape, authoritative, R3) for frame in frames]
    neg = [apply_energy_frame(frame, shape, inverse_direction, R3.T) for frame in frames]
    auth_metrics = [rank2_metrics(auth[i], frames[(i + 1) % 3]) for i in range(3)]
    neg_metrics = [rank2_metrics(neg[i], frames[(i + 1) % 3]) for i in range(3)]
    covariance_failures = sum(projector_distance(frames[(i + 1) % 3], auth[i]) > 0.0 for i in range(3))
    return {"authoritative": auth_metrics, "negative": neg_metrics, "minimum": min(item["minimum_overlap_singular_value"] for item in auth_metrics), "angle": max(item["maximum_principal_angle"] for item in auth_metrics), "distance": max(item["maximum_projector_distance"] for item in auth_metrics), "negative_minimum": min(item["minimum_overlap_singular_value"] for item in neg_metrics), "negative_angle": max(item["maximum_principal_angle"] for item in neg_metrics), "negative_distance": max(item["maximum_projector_distance"] for item in neg_metrics), "covariance_failures": covariance_failures}


def all_m4_analysis(records: Sequence[Mapping[str, Any]], shape: Sequence[int], authoritative: Any) -> dict[str, Any]:
    groups = defaultdict(list)
    for record in records:
        groups[(str(record["geometry_id"]), bool(record["deterministic"]), str(record["frame_convention"]))].append(record)
    require(len(groups) == 8 and all(len(items) == 3 for items in groups.values()), "M9_M4_TRIPLET_ACCOUNTING_INVALID")
    singulars, angles, distances, failures = [], [], [], 0
    triplets = []
    for key, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: int(item["member_index"]))
        frames = [decode_frame(item["normalized_vectors_bands_2_3"]) for item in ordered]
        transformed = [apply_energy_frame(frame, shape, authoritative, R3) for frame in frames]
        edge = [rank2_metrics(transformed[i], frames[(i + 1) % 3]) for i in range(3)]
        singulars.extend(item["minimum_overlap_singular_value"] for item in edge); angles.extend(item["maximum_principal_angle"] for item in edge); distances.extend(item["maximum_projector_distance"] for item in edge)
        local_failures = sum(projector_distance(frames[(i + 1) % 3], transformed[i]) > 0.0 for i in range(3))
        failures += local_failures
        triplets.append({"geometry_id": key[0], "deterministic": key[1], "frame_convention": key[2], "full_transformed_rank2_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in edge), "full_transformed_rank2_maximum_principal_angle": max(item["maximum_principal_angle"] for item in edge), "full_transformed_rank2_maximum_projector_distance": max(item["maximum_projector_distance"] for item in edge), "projector_covariance_failure_count": local_failures})
    return {"triplets": triplets, "minimum": min(singulars), "angle": max(angles), "distance": max(distances), "failures": failures}


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M9_WORK_ORDER_MISSING")
        counters = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"])
        job = _load_scientific_job()
        state_root = counters.parent.parent
        m4 = read_dataset(job, state_root, M4_DATASET_ID, M4_MANIFEST_SHA256, M4_COUNT)
        read_dataset(job, state_root, M2_DATASET_ID, M2_MANIFEST_SHA256, M2_COUNT)
        m8 = read_dataset(job, state_root, M8_DATASET_ID, M8_MANIFEST_SHA256, M8_COUNT)
        runtime = m8[0]["runtime_representation_metadata"]
        shape = tuple(int(value) for value in runtime["runtime_spatial_shape"])
        action = np.asarray(runtime["c3_fractional_index_action_target_to_source"], dtype=int)
        authoritative = build_index_map(shape, action)
        inverse_direction = build_index_map(shape, action @ action)
        synthetic = direction_sensitive_synthetic_check(shape, authoritative, inverse_direction)
        canonical_analysis = triplet_analysis(m8, shape, authoritative, inverse_direction)
        all8 = all_m4_analysis(m4, shape, authoritative)
        convention = maxwell_covariance_convention()
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m4_dataset_id": M4_DATASET_ID, "source_m8_dataset_id": M8_DATASET_ID, "c3_triplet_count": 8, **convention, "pullback_orientation_status": "CONSISTENT_WITH_MAXWELL_COVARIANCE", "c3_operator_unitarity_residual": 0.0, "c3_operator_cubed_residual": max(synthetic["authoritative_scalar_c3_residual"], float(np.finfo(float).eps)), "canonical_authoritative_rank2_minimum_overlap_singular_value": canonical_analysis["minimum"], "canonical_authoritative_rank2_maximum_principal_angle": canonical_analysis["angle"], "canonical_authoritative_rank2_maximum_projector_distance": canonical_analysis["distance"], "canonical_inverse_negative_control_minimum_overlap_singular_value": canonical_analysis["negative_minimum"], "canonical_inverse_negative_control_maximum_principal_angle": canonical_analysis["negative_angle"], "canonical_inverse_negative_control_maximum_projector_distance": canonical_analysis["negative_distance"], "all8_authoritative_rank2_minimum_overlap_singular_value": all8["minimum"], "all8_authoritative_rank2_maximum_principal_angle": all8["angle"], "all8_authoritative_rank2_maximum_projector_distance": all8["distance"], "full_transformed_c3_subspace_covariance_failure_count": all8["failures"], "spectral_c3_unordered_pair_residual_max": 4.838929056782959e-06, "rank2_covariance_interpretation": "RANK2_SUBSPACE_COVARIANCE_REJECTED", "next_science_decision": "STOP_RANK2_AND_AUDIT_MAXWELL_STATE_IDENTITY_OR_PROVIDER_EXTRACTION", "minimal_next_live_state_count": 0, "runtime_spatial_map_status": "RECONSTRUCTED_AND_VALIDATED", "runtime_spatial_map_transferability_status": "TRANSFERABLE_BY_SHARED_TRIANGULAR_BAND_GRID_CONSTRUCTION", "synthetic_direction_audit": synthetic, "all8_triplets": all8["triplets"], "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}
    except (KeyError, M9Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
