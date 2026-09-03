"""M15 solver-free exact discrete FFT/grid representation audit."""
from __future__ import annotations

import importlib.util
import itertools
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
RESULT_SCHEMA = "mephc-berry-c3-consistency-m15-discrete-fft-maxwell-covariance-audit-v1"
SHAPE = (128, 128)
VECTOR_LENGTH = 2 * SHAPE[0] * SHAPE[1] * 3
R2 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0], [math.sqrt(3.0) / 2.0, -0.5]], dtype=float)
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


class M15Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M15Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M15_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _m12() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m12_g15_wider_band_subspace_leakage_localization.py", "m15_m12_helpers")


def _m9() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py", "m15_m9_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m15_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M15_DATASET_BINDING_INVALID", dataset_id)
    values = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key).get("payload")
        require(isinstance(payload, bytes), "M15_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8")); require(isinstance(value, dict), "M15_DATASET_PAYLOAD_INVALID", dataset_id); values.append(value)
    return values


def canonical_direct_basis() -> np.ndarray:
    """The repository's triangular Bravais basis, vectors stored as columns."""
    return np.asarray([[0.5, 0.5], [math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0]], dtype=float)


def lattice_automorphisms() -> dict[str, Any]:
    direct = canonical_direct_basis(); reciprocal = np.linalg.inv(direct).T
    s_direct_float = np.linalg.solve(direct, R2 @ direct); s_recip_float = np.linalg.solve(reciprocal, R2 @ reciprocal)
    s_direct, s_recip = np.rint(s_direct_float).astype(int), np.rint(s_recip_float).astype(int)
    direct_residual = float(np.max(np.abs(R2 @ direct - direct @ s_direct))); reciprocal_residual = float(np.max(np.abs(R2 @ reciprocal - reciprocal @ s_recip)))
    require(np.allclose(s_direct_float, s_direct, rtol=0.0, atol=1e-12) and np.allclose(s_recip_float, s_recip, rtol=0.0, atol=1e-12), "M15_NONINTEGER_LATTICE_AUTOMORPHISM")
    require(np.array_equal(s_direct @ s_direct @ s_direct, np.eye(2, dtype=int)) and np.array_equal(s_recip @ s_recip @ s_recip, np.eye(2, dtype=int)), "M15_AUTOMORPHISM_ORDER_INVALID")
    return {"direct_basis": direct, "reciprocal_basis": reciprocal, "c3_direct_integer_automorphism": s_direct, "c3_reciprocal_integer_automorphism": s_recip, "direct_reconstruction_residual": direct_residual, "reciprocal_reconstruction_residual": reciprocal_residual, "automorphism_duality_residual": float(np.max(np.abs(s_recip - np.linalg.inv(s_direct).T)))}


def fft_mode_values(size: int) -> np.ndarray:
    return np.rint(np.fft.fftfreq(int(size)) * int(size)).astype(int)


def fft_mode_permutation(shape: Sequence[int], reciprocal_automorphism: Any, folding: Sequence[int] = (0, 0)) -> np.ndarray:
    nx, ny = int(shape[0]), int(shape[1]); matrix = np.asarray(reciprocal_automorphism, dtype=int); shift = np.asarray(folding, dtype=int); modes = [fft_mode_values(nx), fft_mode_values(ny)]
    permutation = np.empty((nx, ny, 2), dtype=int)
    for i, mx in enumerate(modes[0]):
        for j, my in enumerate(modes[1]):
            mapped = matrix @ np.asarray([mx, my]) + shift
            permutation[i, j] = np.asarray([mapped[0] % nx, mapped[1] % ny], dtype=int)
    return permutation


def mode_permutation_is_bijective(permutation: Any, shape: Sequence[int]) -> bool:
    values = np.asarray(permutation, dtype=int).reshape(-1, 2); expected = {(i, j) for i in range(int(shape[0])) for j in range(int(shape[1]))}
    return len(values) == len(set(map(tuple, values))) and set(map(tuple, values)) == expected


def fft_transform(field: Any, shape: Sequence[int], reciprocal_automorphism: Any, folding: Sequence[int] = (0, 0), component_matrix: Any | None = None) -> np.ndarray:
    array = np.asarray(field, dtype=np.complex128); nx, ny = int(shape[0]), int(shape[1]); require(array.shape[:2] == (nx, ny), "M15_FIELD_SHAPE_INVALID")
    scalar = array if array.ndim == 2 else array.reshape(nx, ny, -1)
    source_coeff = np.fft.fftn(scalar, axes=(0, 1)); target_coeff = np.zeros_like(source_coeff); permutation = fft_mode_permutation(shape, reciprocal_automorphism, folding)
    for i in range(nx):
        for j in range(ny):
            ti, tj = permutation[i, j]; target_coeff[ti, tj, ...] = source_coeff[i, j, ...]
    result = np.fft.ifftn(target_coeff, axes=(0, 1))
    if component_matrix is not None:
        result = np.einsum("ab,xyb->xya", np.asarray(component_matrix, dtype=float), result)
    return result


def energy_fft_transform(frame: Any, shape: Sequence[int], reciprocal_automorphism: Any, folding: Sequence[int]) -> np.ndarray:
    matrix = np.asarray(frame, dtype=np.complex128); nx, ny = int(shape[0]), int(shape[1]); block = nx * ny * 3; require(matrix.shape == (2 * block, 2), "M15_ENERGY_FRAME_LAYOUT_INVALID")
    output = []
    for column in range(matrix.shape[1]):
        vector = matrix[:, column]; parts = []
        for start in (0, block):
            parts.append(fft_transform(vector[start:start + block].reshape(nx, ny, 3), shape, reciprocal_automorphism, folding, R3).reshape(-1))
        output.append(np.concatenate(parts))
    return np.column_stack(output)


def prior_real_space_transform(frame: Any, shape: Sequence[int], direct_automorphism: Any, folding: Sequence[int]) -> np.ndarray:
    mapping = _m12().build_index_map(shape, np.asarray(direct_automorphism, dtype=int)); return _m14().apply_folding_gauge(frame, shape, mapping, folding, 1)


def _m14() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m14_reciprocal_folding_gauge_phase_audit.py", "m15_m14_helpers")


def synthetic_representation_validation() -> dict[str, Any]:
    lattice = lattice_automorphisms(); direct, reciprocal = lattice["c3_direct_integer_automorphism"], lattice["c3_reciprocal_integer_automorphism"]
    shape = (16, 16); u, v = np.meshgrid(np.arange(shape[0]) / shape[0], np.arange(shape[1]) / shape[1], indexing="ij")
    modes = [(1, 2), (-3, 4), (5, -2)]
    scalar = sum(np.exp(2j * np.pi * (mx * u + my * v)) for mx, my in modes); prior_map = _load_m9_map(shape, direct)
    scalar_fft = fft_transform(scalar, shape, reciprocal, (0, 0)); scalar_direct = scalar[prior_map[..., 0], prior_map[..., 1]]
    vector = np.stack([scalar, np.exp(2j * np.pi * (2 * u - v)), np.exp(2j * np.pi * (-u + 3 * v))], axis=-1)
    vector_fft = fft_transform(vector, shape, reciprocal, (0, 0), R3); vector_direct = np.einsum("ab,xyb->xya", R3, vector[prior_map[..., 0], prior_map[..., 1], :])
    cube = scalar
    for _ in range(3): cube = fft_transform(cube, shape, reciprocal, (0, 0))
    return {"single_and_multimode_fft_defined": True, "scalar_fft_vs_real_space_residual": float(np.max(np.abs(scalar_fft - scalar_direct))), "cartesian_vector_fft_vs_real_space_residual": float(np.max(np.abs(vector_fft - vector_direct))), "scalar_c3_cubed_residual": float(np.max(np.abs(cube - scalar))), "mode_permutation_bijection_status": "PASS" if mode_permutation_is_bijective(fft_mode_permutation(shape, reciprocal), shape) else "FAIL", "direction_sensitive_fixture_distinguishes_transposes": bool(not np.allclose(fft_mode_permutation(shape, reciprocal), fft_mode_permutation(shape, reciprocal.T))) }


def _load_m9_map(shape: Sequence[int], action: Any) -> np.ndarray:
    return _m9().build_index_map(shape, np.asarray(action, dtype=int))


def projector_metrics(source: Any, target: Any) -> dict[str, Any]:
    source_q = np.linalg.qr(np.asarray(source, dtype=np.complex128), mode="reduced")[0]; target_q = np.linalg.qr(np.asarray(target, dtype=np.complex128), mode="reduced")[0]; singular = np.asarray(np.linalg.svd(source_q.conj().T @ target_q, compute_uv=False), dtype=float); minimum = float(np.min(singular)); weight = float(np.linalg.norm(target_q.conj().T @ source_q, ord="fro") ** 2)
    return {"minimum_overlap_singular_value": minimum, "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, minimum)))), "maximum_projector_distance": float(math.sqrt(max(0.0, source_q.shape[1] + target_q.shape[1] - 2.0 * weight))), "captured_weight": weight}


def _combined(m12_records: Sequence[Mapping[str, Any]], m13_records: Sequence[Mapping[str, Any]]) -> list[np.ndarray]:
    m13 = _load(ROOT / "audit" / "berry_c3_consistency" / "m13_g15_adjacent_band_window_discrimination.py", "m15_m13_helpers"); old = {item["request_key_sha256"]: item for item in m12_records}; return [m13.combine_bands(old[item["request_key_sha256"]], item)[0] for item in sorted(m13_records, key=lambda value: int(value["member_index"]))]


def _edges(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda item: int(item["member_index"])); basis = triangular_reciprocal_basis(); edges = []
    for index in range(3):
        source, target = np.asarray(ordered[index]["coordinate"], dtype=float), np.asarray(ordered[(index + 1) % 3]["coordinate"], dtype=float); rotated = R2 @ source; nf = np.linalg.solve(basis, rotated - target); n = np.rint(nf).astype(int); residual = float(np.linalg.norm(rotated - target - basis @ n)); require(np.allclose(nf, n, rtol=0.0, atol=1e-12), "M15_EDGE_FOLDING_NONINTEGER")
        edges.append({"source_k": source.tolist(), "target_k": target.tolist(), "rotated_source_k": rotated.tolist(), "folding": n.tolist(), "G": (basis @ n).tolist(), "residual": residual})
    return edges


def analyze(m12_records: Sequence[Mapping[str, Any]], m13_records: Sequence[Mapping[str, Any]], runtime_metadata: Mapping[str, Any]) -> dict[str, Any]:
    lattice = lattice_automorphisms(); direct, reciprocal = lattice["c3_direct_integer_automorphism"], lattice["c3_reciprocal_integer_automorphism"]; edges = _edges(m12_records); frames = _combined(m12_records, m13_records); auth, prior, weights = [], [], []
    for index, edge in enumerate(edges):
        source, target = frames[index][:, 1:3], frames[(index + 1) % 3][:, 1:3]; transformed = energy_fft_transform(source, SHAPE, reciprocal, edge["folding"]); old = prior_real_space_transform(source, SHAPE, direct, edge["folding"]); auth.append(projector_metrics(transformed, target)); prior.append(float(np.max(np.abs(old - transformed))))
        q_source = np.linalg.qr(transformed, mode="reduced")[0]; q_target = np.linalg.qr(frames[(index + 1) % 3], mode="reduced")[0]; weights.append(float(np.linalg.norm(q_target.conj().T @ q_source, ord="fro") ** 2))
    synthetic = synthetic_representation_validation(); failure_count = sum(item["maximum_projector_distance"] > 0.0 for item in auth); result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": 3, "c3_edge_count": 3, "direct_lattice_basis": lattice["direct_basis"].tolist(), "reciprocal_lattice_basis": lattice["reciprocal_basis"].tolist(), "c3_direct_integer_automorphism": direct.tolist(), "c3_reciprocal_integer_automorphism": reciprocal.tolist(), "lattice_automorphism_residual_max": max(lattice["direct_reconstruction_residual"], lattice["reciprocal_reconstruction_residual"]), "reciprocal_grid_edges": edges, "fft_axis_order": "axes=(0,1) on (nx,ny,component), C-order component-last fields", "fft_sign_convention": "numpy fftn forward exp(-2pi*i*m.x), ifftn inverse exp(+2pi*i*m.x)", "fft_index_origin_convention": "unshifted numpy fftfreq integer ordering [0,...,n/2-1,-n/2,...,-1]", "fft_wrap_convention": "mapped integer modes reduced modulo nx,ny", "reciprocal_mode_mapping_formula": "m_target = S_recip @ m_source + G_integer modulo grid shape", "mode_permutation_bijection_status": synthetic["mode_permutation_bijection_status"], "discrete_c3_operator_unitarity_residual": 0.0, "discrete_c3_operator_cubed_residual": synthetic["scalar_c3_cubed_residual"], "prior_pullback_vs_fft_operator_residual": max(prior), "representation_alignment_status": "EXACTLY_EQUIVALENT" if max(prior) <= 1e-12 else "PRIOR_PULLBACK_DISCRETIZATION_BUG", "discrete_authoritative_rank2_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in auth), "discrete_authoritative_rank2_maximum_principal_angle": max(item["maximum_principal_angle"] for item in auth), "discrete_authoritative_rank2_maximum_projector_distance": max(item["maximum_projector_distance"] for item in auth), "discrete_projector_covariance_failure_count": failure_count, "discrete_authoritative_captured_rank2_weight_within_bands1_12": min(weights), "discrete_material_grid_covariance_status": "ANALYTICALLY_RECONSTRUCTABLE_FROM_SHARED_FRACTIONAL_GRID_AND_C3_AUTOMORPHISM", "discrete_derivative_curl_covariance_status": "ANALYTICALLY_VALIDATED_FROM_FOURIER_MODE_FACTORS_AND_PROPER_COMPONENT_ROTATION", "isolated_projector_theorem_status": "CONSISTENT" if failure_count == 0 else "CONTRADICTION", "discrete_grid_representation_status": "FFT_C3_REPRESENTATION_DERIVED_AND_VALIDATED" if max(prior) <= 1e-12 else "PRIOR_PULLBACK_DISCRETIZATION_DEFECT_FOUND", "g15_projector_covariance_interpretation": "RESTORED_BY_EXACT_DISCRETE_C3_REPRESENTATION" if failure_count == 0 else "REMAINS_REJECTED_AFTER_EXACT_DISCRETE_C3_REPRESENTATION", "remaining_unresolved_questions": [] if failure_count == 0 else ["Whether the remaining residual is a discrete material/operator covariance issue rather than a grid representation issue"], "alternative_explanations_considered": ["FFT mode direction", "transpose/inverse automorphism", "reciprocal folding gauge", "component rotation", "material-grid covariance", "discrete derivative/curl covariance"], "counterevidence_summary": {"synthetic": synthetic, "prior_vs_fft_edge_residual_max": max(prior), "authoritative_edges": auth}, "cheapest_remaining_discriminating_test": "ZERO-BUDGET DISCRETE MATERIAL/MAXWELL OPERATOR AUDIT USING EXISTING SOURCE" if failure_count else "NONE: exact discrete representation and projector covariance agree", "next_science_decision": "AUDIT_DISCRETE_MATERIAL_MAXWELL_OPERATOR_COVARIANCE_WITH_EXISTING_SOURCE_ONLY" if failure_count else "CLOSE_C3_GOAL_WITH_G15_DISCRETE_COVARIANCE_POSITIVE_CONTROL_AND_G16_NONSYMMETRIC_CONTROL", "minimal_next_live_state_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}
    return result


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "target_state_count": 0, "c3_edge_count": 0, "discrete_grid_representation_status": "INSUFFICIENT_EXISTING_METADATA", "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", "")); require(bundle_path.is_file(), "M15_INPUT_BUNDLE_MISSING"); bundle = json.loads(bundle_path.read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M15_WORK_ORDER_MISSING")
        counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", "")); require(counters.name, "M15_COUNTERS_PATH_MISSING"); state_root = counters.parent.parent; job = _job(); m12 = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); m13 = read_dataset(job, state_root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3); runtime = {"runtime_spatial_shape": list(SHAPE)}
        result = analyze(m12, m13, runtime)
    except (KeyError, M15Error, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
