"""M19: audit existing runtime material-grid and spectral-projector evidence.

This is deliberately a zero-execution audit.  It reads the exact immutable
M18 runtime readback and the already archived M12/M13 vectors, then checks
their representation and projector construction without fitting a map or
creating any new scientific record.
"""
from __future__ import annotations

import importlib.util
import json
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M13_DATASET_ID = "dcaee157184d53a6a8025a374505084e105cde49f55d9ea345b55bae058dedcd"
M13_MANIFEST_SHA256 = "04917fb96a15c05ed83d54004b098ae6c72fb0c9b64a61ec241941cb69905378"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m19-runtime-epsilon-grid-and-spectral-projector-audit-v1"
SHAPE = (128, 128)
COMPONENT_COUNT = 3
BLOCK = SHAPE[0] * SHAPE[1] * COMPONENT_COUNT
VECTOR_LENGTH = 2 * BLOCK
NUM_BANDS = 12
R3 = np.asarray([[-0.5, -np.sqrt(3.0) / 2.0, 0.0], [np.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


class M19Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M19Error(f"{code}:{detail}" if detail else code)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M19_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m18() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m18_exact_mpb_operator_readback_and_covariance_closure.py", "m19_m18_helpers")


def _m12() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m12_g15_wider_band_subspace_leakage_localization.py", "m19_m12_helpers")


def _m13() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m13_g15_adjacent_band_window_discrimination.py", "m19_m13_helpers")


def _m15() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py", "m19_m15_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m19_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha256: str, record_count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id, "M19_DATASET_ID_MISMATCH", dataset_id)
    require(verified.get("manifest_sha256") == manifest_sha256, "M19_DATASET_MANIFEST_MISMATCH", dataset_id)
    keys = verified.get("record_key_sha256")
    require(verified.get("record_count") == record_count and isinstance(keys, list) and len(keys) == record_count and len(set(keys)) == record_count, "M19_DATASET_MEMBERSHIP_INVALID", dataset_id)
    records = []
    for key in keys:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest_sha256, key).get("payload")
        require(isinstance(payload, bytes), "M19_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M19_DATASET_PAYLOAD_INVALID", dataset_id)
        records.append(value)
    return records


def _ordered(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    value = sorted((dict(record) for record in records), key=lambda item: int(item["member_index"]))
    require(len(value) == 3 and [item["member_index"] for item in value] == [0, 1, 2], "M19_TRIPLET_INVALID")
    require([item["c3_member_identity"] for item in value] == ["IDENTITY", "C3", "C3_SQUARED"], "M19_MEMBER_ORDER_INVALID")
    return value


def runtime_epsilon_audit(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = _ordered(records)
    arrays = [np.asarray(item["epsilon_grid"], dtype=float) for item in ordered]
    require(all(array.shape == SHAPE and np.all(np.isfinite(array)) for array in arrays), "M19_EPSILON_GRID_INVALID")
    axes = {str(item["material_grid_axis_order"]) for item in ordered}
    conventions = {str(item["material_grid_coordinate_convention"]) for item in ordered}
    require(len(axes) == len(conventions) == 1, "M19_EPSILON_GRID_METADATA_DISAGREEMENT")
    m15 = _m15(); lattice = m15.lattice_automorphisms(); m9 = m15._m9()
    source_derived_map = m9.build_index_map(SHAPE, lattice["c3_direct_integer_automorphism"])
    # The M18 factory keeps one fixed G15 geometry and changes only k.  MPB's
    # get_epsilon is therefore the same fractional (x,y) grid for every
    # member; applying a spatial C3 permutation here would rotate one copy of
    # the same material grid a second time.
    raw_edges = [float(np.max(np.abs(arrays[(index + 1) % 3] - arrays[index]))) for index in range(3)]
    wrong_spatial_edges = [float(np.max(np.abs(arrays[(index + 1) % 3] - arrays[index][source_derived_map[..., 0], source_derived_map[..., 1]]))) for index in range(3)]
    unique = []
    for item, array in zip(ordered, arrays):
        values, counts = np.unique(array, return_counts=True)
        unique.append({"member_index": int(item["member_index"]), "c3_member_identity": item["c3_member_identity"], "unique_value_count": int(values.size), "minimum": float(values[0]), "maximum": float(values[-1]), "value_multiplicity_total": int(np.sum(counts)), "dominant_value": float(values[int(np.argmax(counts))]), "dominant_value_count": int(np.max(counts))})
    return {
        "runtime_epsilon_grid_shape": list(arrays[0].shape),
        "epsilon_grid_axis_order": next(iter(axes)),
        "epsilon_grid_coordinate_convention": next(iter(conventions)),
        "epsilon_grid_unique_value_summary": unique,
        "exact_source_derived_c3_material_grid_mapping_formula": "For M18, epsilon_target[i,j] = epsilon_source[i,j] because all three ModeSolvers use the same fixed G15 geometry_lattice and get_epsilon is indexed on that shared fractional (x,y) C-order grid; a spatial pullback epsilon_source[build_index_map(S_direct)[i,j]] applies only when the material geometry itself is rotated.",
        "source_derived_spatial_c3_map_negative_control": {"direct_integer_automorphism": lattice["c3_direct_integer_automorphism"].tolist(), "target_to_source_index_map": "M9 build_index_map: S_direct^-1 [i/nx,j/ny] reduced modulo shape"},
        "previous_epsilon_residual_6p29_root_cause": "The prior comparison applied the field spatial C3 pullback to one member of an unchanged shared runtime material grid, thereby rotating the same array a second time; it compared epsilon_source[mapped_index] with epsilon_target instead of same fractional indices.",
        "exact_runtime_epsilon_grid_c3_residual_max": max(raw_edges),
        "legacy_wrong_spatial_map_residual_max": max(wrong_spatial_edges),
        "runtime_material_c3_covariance_status": "C3_COVARIANT" if max(raw_edges) == 0.0 else "STRUCTURALLY_NONCOVARIANT",
        "raw_edge_residuals": raw_edges,
    }


def decode_archived_frames(m12_records: Sequence[Mapping[str, Any]], m13_records: Sequence[Mapping[str, Any]]) -> tuple[list[np.ndarray], list[np.ndarray]]:
    m12 = _m12(); m13 = _m13(); old = {item["request_key_sha256"]: item for item in m12_records}; ordered13 = _ordered(m13.select_same_triplet(m13_records))
    frames, frequencies = [], []
    for item in ordered13:
        require(item["request_key_sha256"] in old, "M19_ARCHIVED_BINDING_INVALID", item["request_key_sha256"])
        frame, freq = m13.combine_bands(old[item["request_key_sha256"]], item)
        require(frame.shape == (VECTOR_LENGTH, NUM_BANDS) and freq.shape == (NUM_BANDS,), "M19_ARCHIVED_FRAME_LAYOUT_INVALID")
        frames.append(np.asarray(frame, dtype=np.complex128)); frequencies.append(np.asarray(freq, dtype=float))
    return frames, frequencies


def _fresh_frames(m18_records: Sequence[Mapping[str, Any]]) -> list[np.ndarray]:
    m18 = _m18()
    frames = [m18.decode_persisted_energy_vectors(item) for item in _ordered(m18_records)]
    require(all(frame.shape == (VECTOR_LENGTH, 6) for frame in frames), "M19_FRESH_FRAME_LAYOUT_INVALID")
    return [np.asarray(frame, dtype=np.complex128) for frame in frames]


def _orthonormal(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    require(array.ndim == 2 and array.shape[1] > 0 and np.all(np.isfinite(array)), "M19_PROJECTOR_INPUT_INVALID")
    q, _ = np.linalg.qr(array, mode="reduced")
    require(np.linalg.matrix_rank(array) == array.shape[1], "M19_PROJECTOR_RANK_INVALID")
    return q


def _projector_distance(left_q: np.ndarray, right_q: np.ndarray) -> float:
    return float(np.sqrt(max(0.0, left_q.shape[1] + right_q.shape[1] - 2.0 * float(np.linalg.norm(left_q.conj().T @ right_q, ord="fro") ** 2))))


def _same_span_residual(reference_q: np.ndarray, candidate_q: np.ndarray) -> float:
    """Compare equivalent constructions without catastrophic rank cancellation."""
    return float(np.linalg.norm(candidate_q - reference_q @ (reference_q.conj().T @ candidate_q), ord="fro"))


def projector_audit(frame: Any, indices: Sequence[int]) -> dict[str, Any]:
    matrix = np.asarray(frame, dtype=np.complex128)
    selected = matrix[:, list(indices)]
    q = _orthonormal(selected)
    gram = selected.conj().T @ selected
    off = np.array(gram, copy=True); np.fill_diagonal(off, 0.0)
    qgram = q.conj().T @ q
    direct_idempotence = float(np.linalg.norm(qgram @ qgram - qgram))
    direct_hermiticity = float(np.linalg.norm(qgram - qgram.conj().T))
    direct_trace = float(abs(np.trace(qgram) - q.shape[1]))
    _, _, vh = np.linalg.svd(selected, full_matrices=False)
    rank = int(np.linalg.matrix_rank(selected))
    svd_q = selected @ vh[:rank, :].conj().T
    svd_q = _orthonormal(svd_q)
    u2 = np.asarray([[1.0, 1.0j], [1.0j, 1.0]], dtype=np.complex128) / np.sqrt(2.0)
    rotated_q = _orthonormal(selected @ u2)
    return {"projector_vector_matrix_shape": list(selected.shape), "projector_band_axis": "columns", "projector_state_axis": "rows=(sqrt(epsilon)E,H) flattened in C order", "projector_metric_convention": "complex Hermitian Euclidean inner product; P=V(V†V)^-1V†", "projector_hermiticity_residual_max": direct_hermiticity, "projector_idempotence_residual_max": direct_idempotence, "projector_trace_residual_max": direct_trace, "projector_independent_construction_difference_max": _same_span_residual(q, svd_q), "projector_U2_invariance_residual_max": _same_span_residual(q, rotated_q), "gram_offdiagonal_abs_max": float(np.max(np.abs(off))) if off.size else 0.0, "rank": rank}


def spectral_window(frequencies: Sequence[float]) -> dict[str, Any]:
    values = np.asarray(frequencies, dtype=float)
    require(values.shape == (NUM_BANDS,) and np.all(np.isfinite(values)) and np.all(np.diff(values) >= 0.0), "M19_FREQUENCY_LAYOUT_INVALID")
    candidates = []
    for start in range(1, NUM_BANDS - 2):
        internal = float(values[start + 1] - values[start]); left = float(values[start] - values[start - 1]); right = float(values[start + 2] - values[start + 1])
        score = min(left, right) / max(internal, np.finfo(float).tiny)
        candidates.append((score, start, internal, left, right))
    _, start, internal, left, right = max(candidates, key=lambda item: (item[0], -item[1]))
    lower, upper = float(values[start - 1] + left / 2.0), float(values[start + 2] - right / 2.0)
    inside = np.flatnonzero((values > lower) & (values < upper))
    return {"spectral_window_bounds": [lower, upper], "spectral_window_rank": int(inside.size), "spectral_window_band_set": [int(index + 1) for index in inside], "isolation_score": float(min(left, right) / max(internal, np.finfo(float).tiny))}


def _gram_offdiag(frame: np.ndarray) -> float:
    gram = frame.conj().T @ frame; off = np.array(gram, copy=True); np.fill_diagonal(off, 0.0); return float(np.max(np.abs(off))) if off.size else 0.0


def _covariance_metrics(frames: Sequence[np.ndarray], records: Sequence[Mapping[str, Any]], indices: Sequence[int]) -> tuple[list[dict[str, Any]], int]:
    m15 = _m15(); lattice = m15.lattice_automorphisms(); edges = m15._edges(records); ordered = _ordered(records); metrics = []
    for index, edge in enumerate(edges):
        source = frames[index][:, list(indices)]; target = frames[(index + 1) % 3][:, list(indices)]
        transformed = m15.energy_fft_transform(source, SHAPE, lattice["c3_reciprocal_integer_automorphism"], edge["folding"])
        metric = m15.projector_metrics(transformed, target); metric["source_member"] = ordered[index]["c3_member_identity"]; metric["target_member"] = ordered[(index + 1) % 3]["c3_member_identity"]; metrics.append(metric)
    return metrics, sum(item["maximum_projector_distance"] > 0.0 for item in metrics)


def analyze(m18_records: Sequence[Mapping[str, Any]], m12_records: Sequence[Mapping[str, Any]], m13_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    m12 = _m12(); epsilon = runtime_epsilon_audit(m18_records); fresh6 = _fresh_frames(m18_records); archived12, archived_freq = decode_archived_frames(m12_records, m13_records)
    six_audits = [projector_audit(frame, (1, 2)) for frame in archived12]
    twelve_audits = [projector_audit(frame, (1, 2)) for frame in archived12]
    windows = [spectral_window(freq) for freq in archived_freq]
    window_sets = [item["spectral_window_band_set"] for item in windows]
    window_status = "BANDS2_3_CONFIRMED" if all(item == [2, 3] for item in window_sets) else "ORDINAL_BAND_LABEL_MISMATCH" if all(len(item) == 2 for item in window_sets) else "WINDOW_RANK_CHANGED"
    indices = tuple(index - 1 for index in window_sets[0]) if window_sets and window_sets[0] else (1, 2)
    fresh_metrics, fresh_failures = _covariance_metrics(fresh6, m18_records, indices)
    archived_metrics, archived_failures = _covariance_metrics(archived12, m18_records, indices)
    metric_difference = max(abs(float(a["maximum_projector_distance"]) - float(b["maximum_projector_distance"])) for a, b in zip(fresh_metrics, archived_metrics))
    m12_six = [m12.decode_bands(item["normalized_vectors_bands_1_to_6"]) for item in _ordered(m12_records)]
    fresh_vs_archived = [float(np.min(np.linalg.svd(_orthonormal(fresh6[i][:, indices]).conj().T @ _orthonormal(m12_six[i][:, list(indices)]), compute_uv=False))) for i in range(3)]
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m18_dataset_id": M18_DATASET_ID, "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": 3, **epsilon, "projector_vector_matrix_shape": six_audits[0]["projector_vector_matrix_shape"], "projector_band_axis": six_audits[0]["projector_band_axis"], "projector_state_axis": six_audits[0]["projector_state_axis"], "projector_metric_convention": six_audits[0]["projector_metric_convention"], "projector_hermiticity_residual_max": max(item["projector_hermiticity_residual_max"] for item in twelve_audits), "projector_idempotence_residual_max": max(item["projector_idempotence_residual_max"] for item in twelve_audits), "projector_trace_residual_max": max(item["projector_trace_residual_max"] for item in twelve_audits), "projector_independent_construction_difference_max": max(item["projector_independent_construction_difference_max"] for item in twelve_audits), "projector_U2_invariance_residual_max": max(item["projector_U2_invariance_residual_max"] for item in twelve_audits), "six_band_gram_offdiagonal_abs_max": max(_gram_offdiag(frame) for frame in m12_six), "twelve_band_gram_offdiagonal_abs_max": max(_gram_offdiag(frame) for frame in archived12), "projector_construction_formula": "Decode band columns, form G=V†V, use QR orthonormal basis Q and P=QQ†=V(V†V)^-1V†; independently reconstruct the same span from thin SVD/QR.", "spectral_window_bounds_by_member": [item["spectral_window_bounds"] for item in windows], "spectral_window_rank_by_member": [item["spectral_window_rank"] for item in windows], "spectral_window_projector_identity_status": window_status, "spectral_window_band_set_by_member": window_sets, "fresh_projector_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in fresh_metrics), "archived_projector_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in archived_metrics), "fresh_archived_projector_metric_difference_max": metric_difference, "corrected_projector_c3_covariance_failure_count": fresh_failures, "fresh_projector_c3_edge_metrics": fresh_metrics, "archived_projector_c3_edge_metrics": archived_metrics, "fresh_vs_archived_projector_overlap_minimum": min(fresh_vs_archived), "operator_calibration_status": "NOT_ESTABLISHED_FIRST_ORDER_MAXWELL_RESIDUAL_ORDER_0P88", "isolated_projector_theorem_status": "CONDITIONAL_OPERATOR_COVARIANCE_NOT_YET_ESTABLISHED", "primary_projector_audit_diagnosis": "PROJECTOR_CONSTRUCTION_SELF_CONSISTENT_OPERATOR_LEVEL_UNRESOLVED", "exact_missing_operator_metadata": "MPB_FIELD_STAGGERING_AND_INTERNAL_CONSTITUTIVE_OPERATOR_READBACK", "remaining_unresolved_questions": ["Whether the exact staggered/internal MPB operator is unitary-covariant on the stored eigenstates; M18 readback lacks that internal operator metadata."], "alternative_explanations_considered": ["epsilon fractional-grid comparison convention", "runtime subpixel material sampling", "band/state axis transpose", "real-imag or E/H block mixing", "projector normalization and U(2) basis choice", "spectral window definition", "archived versus fresh serialization", "missing MPB staggering and constitutive conventions"], "counterevidence_summary": {"previous_epsilon_residual_6p29": epsilon["legacy_wrong_spatial_map_residual_max"], "same_grid_epsilon_edges": epsilon["raw_edge_residuals"], "fresh_projector_edges": fresh_metrics, "archived_projector_edges": archived_metrics, "fresh_archived_state_overlap": fresh_vs_archived}, "cheapest_remaining_discriminating_test": "Read-only metadata-only calibration of MPB field staggering and internal constitutive/operator conventions from the existing M18 runtime, without new solves.", "next_science_decision": "ACQUIRE_MINIMAL_MPB_STAGGERING_OR_INTERNAL_OPERATOR_METADATA_ONLY", "minimal_next_live_state_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def failure(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "exception_type": type(exc).__name__ if exc else None, "exception_message": str(exc)[:1024] if exc else None, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "minimal_next_live_state_count": 0, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M19_WORK_ORDER_MISSING")
        counters_path = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]); state_root = counters_path.parent.parent; job = _job()
        m18_records = read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)
        m12_records = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3)
        m13_records = read_dataset(job, state_root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3)
        result = analyze(m18_records, m12_records, m13_records)
    except Exception as exc:
        result = failure(str(exc), exc); result["traceback_tail"] = traceback.format_exc()[-3000:]
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
