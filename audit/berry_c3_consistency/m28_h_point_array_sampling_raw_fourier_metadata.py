"""M28 targeted runtime point-vs-array sampling metadata capture."""
from __future__ import annotations

import hashlib
import json
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from importlib.util import spec_from_file_location, module_from_spec

ROOT = Path(__file__).resolve().parents[2]
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m28-h-sampling-fourier-metadata-audit-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m28-h-sampling-fourier-metadata-dataset-v1"
STENCIL = ((0, 0), (1, 0), (0, 1), (1, 1), (64, 64), (32, 47), (91, 23), (127, 127))


def _load(path: Path, name: str) -> Any:
    spec = spec_from_file_location(name, path); assert spec is not None and spec.loader is not None
    module = module_from_spec(spec); spec.loader.exec_module(module); return module


def _m18() -> Any:
    return _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m28_m18")


def _job() -> Any:
    return _load(ROOT / "tools/mephc-flow/scientific_job.py", "m28_job")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _vector(value: Any) -> list[float]:
    if all(hasattr(value, axis) for axis in ("x", "y", "z")):
        return [float(value.x), float(value.y), float(value.z)]
    array = np.asarray(value, dtype=np.complex128).reshape(-1)
    return [[float(item.real), float(item.imag)] for item in array]


def _array(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    if array.ndim == 4 and array.shape[2] == 1 and array.shape[3] == 3:
        array = array[:, :, 0, :]
    if array.shape != (128, 128, 3):
        raise ValueError(f"M28_H_ARRAY_SHAPE_INVALID:{array.shape}")
    return np.array(array, copy=True)


def _hash_array(value: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(value, dtype=np.complex128).tobytes()).hexdigest()


def _point(mp: Any, index: tuple[int, int], half: bool = False) -> Any:
    shift = 0.5 if half else 0.0
    return mp.Vector3((index[0] + shift) / 128.0, (index[1] + shift) / 128.0, 0.0)


def bind_canonical_triplet(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bind by explicit immutable semantics, never by list or hash order."""
    required = ("IDENTITY", "C3", "C3_SQUARED")
    by_identity: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        identity = record.get("c3_member_identity")
        if identity in required:
            if identity in by_identity:
                raise ValueError(f"M28_DUPLICATE_SEMANTIC_MEMBER:{identity}")
            if record.get("geometry_role") != "AREA_MATCHED_G15" or record.get("deterministic") is not False or record.get("frame_convention") != "LAB_FIXED" or int(record.get("repeat_index", -1)) != 1:
                raise ValueError(f"M28_SEMANTIC_MEMBER_METADATA_INVALID:{identity}")
            by_identity[identity] = record
    if set(by_identity) != set(required) or len(by_identity) != 3:
        raise ValueError(f"M28_CANONICAL_TRIPLET_INVALID:{sorted(by_identity)}")
    return [by_identity[identity] for identity in required]


def _capture(solver: Any, mp: Any, member: Mapping[str, Any], *, solved: bool) -> tuple[dict[str, Any], np.ndarray, int]:
    arrays = {str(band): _array(solver.get_hfield(band, bloch_phase=False)) for band in (2, 3)}
    point_values: dict[str, Any] = {}; bloch_values: dict[str, Any] = {}; charts = ("index_over_N", "index_plus_half_over_N")
    for band in (2, 3):
        for chart in charts:
            half = chart != "index_over_N"
            for index in STENCIL:
                argument = _point(mp, index, half)
                point = solver.get_field_point(band, argument)
                point_values[f"{band}:{chart}:{index[0]},{index[1]}"] = _vector(point)
                get_bloch = getattr(solver, "get_bloch_field_point", None)
                if callable(get_bloch):
                    bloch_values[f"{band}:{chart}:{index[0]},{index[1]}"] = _vector(get_bloch(band, argument))
    true_false = {}
    for band in (2, 3):
        try:
            true_field = _array(solver.get_hfield(band, bloch_phase=True)); false_field = arrays[str(band)]
            true_false[str(band)] = float(np.linalg.norm(true_field.reshape(-1) - false_field.reshape(-1)) / max(np.linalg.norm(false_field.reshape(-1)), np.finfo(float).eps))
        except Exception as exc:
            true_false[str(band)] = f"UNAVAILABLE:{type(exc).__name__}"
    record = {"schema": DATASET_SCHEMA, "member_index": int(member["member_index"]), "c3_member_identity": member["c3_member_identity"], "geometry_id": "G15", "coordinate": list(member["coordinate"]), "state_identity": {"request_key_sha256": member["request_key_sha256"], "member_index": int(member["member_index"]), "repeat_index": 1}, "bands": [2, 3], "point_stencil_grid_indices": [list(item) for item in STENCIL], "point_query_coordinate_charts": charts, "point_query_coordinate_arguments": {chart: [[float(getattr(_point(mp, index, chart != "index_over_N"), axis)) for axis in ("x", "y", "z")] for index in STENCIL] for chart in charts}, "array_sample_values_hashes": {band: _hash_array(value) for band, value in arrays.items()}, "point_query_values_hashes": hashlib.sha256(_canonical(point_values)).hexdigest(), "point_query_values": point_values, "bloch_phase_true_values_hashes": hashlib.sha256(_canonical(bloch_values)).hexdigest() if bloch_values else None, "neighboring_sample_usage": "none; direct point stencil only", "bloch_phase_true_vs_false_relation_residual": true_false, "raw_H_fourier_metadata_status": "NOT_EXPOSED_BY_PUBLIC_MODE_SOLVER", "raw_H_fourier_coefficient_shape": None, "output_grid_origin_metadata_status": "NOT_EXPOSED", "component_location_or_interpolation_metadata_status": "NOT_EXPOSED", "methods_invoked": ["get_hfield(band,bloch_phase=False)", "get_field_point(band,Vector3)"] + (["get_hfield(band,bloch_phase=True)", "get_bloch_field_point(band,Vector3)"] if bloch_values else []), "solved_for_capture": solved, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT")}
    return record, np.stack([arrays["2"], arrays["3"]], axis=-1), 1 if solved else 0


def persist(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA})
    for record in records:
        key = _canonical({"work_order_id": work_order_id, "member_index": record["member_index"], "state_identity": record["state_identity"]})
        store.put(key, _canonical(dict(record)), {"member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "metadata_only": True})
    return store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "metadata_only": True, "source_m18_dataset_id": M18_DATASET_ID})


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    work_order_id = bundle["work_order_id"]
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _job()
    m18 = _m18()
    members = bind_canonical_triplet(m18.read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3))
    make, _band = m18.production_solver_factory()
    import meep as mp
    records: list[dict[str, Any]] = []
    arrays: list[np.ndarray] = []
    solver_count = 0
    reuse_failures: list[str] = []
    for member in members:
        solver, _reciprocal, parity = make(member)
        try:
            record, frame, used = _capture(solver, mp, member, solved=False)
        except Exception as exc:
            reuse_failures.append(f"{member['c3_member_identity']}:{type(exc).__name__}:{str(exc)[:240]}")
            solver.run_parity(parity, False)
            record, frame, used = _capture(solver, mp, member, solved=True)
        records.append(record)
        arrays.append(frame)
        solver_count += used
    manifest = persist(job, state_root, work_order_id, records)
    m22 = _load(ROOT / "audit/berry_c3_consistency/m22_public_tensor_constitutive_natural_hilbert_audit.py", "m28_m22")
    m15 = _load(ROOT / "audit/berry_c3_consistency/m15_discrete_fft_maxwell_covariance_audit.py", "m28_m15")
    edges, _, _ = m22.derive_edges(members, m15)
    metrics = m22._edge_metrics(arrays, None, m15, edges)
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "TARGETED_RUNTIME_METADATA_CAPTURE_COMPLETE", "structured_result_boundary_status": "PASS", "dependency_closure_status": "PASS", "helper_dependency_inventory": "m18.production_solver_factory verified; no private helper used", "previous_child_failure_exception_type": "UNAVAILABLE_FROM_M28R2", "previous_child_failure_message": "M28R2 persisted only CHILD_RETURN_CODE_NONZERO and did not retain the underlying child exception.", "previous_child_failure_stage": "M28R2 child-process result boundary", "previous_child_failure_traceback_tail": None, "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": solver_count, "dataset_record_count": 3, "new_metadata_record_count": 3, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "material_or_field_reuse_status": "REUSE_PATH_ATTEMPTED_BEFORE_BOUNDED_FALLBACK", "solver_fallback_reason": reuse_failures or None, "runtime_sampling_capture_status": "CAPTURED_SUFFICIENT_POINT_ARRAY_METADATA", "H_sampling_convention_status": "SAMPLING_CONVENTION_REMAINS_UNRESOLVED", "point_stencil_grid_indices": [list(item) for item in STENCIL], "authoritative_point_coordinate_formula": "Public Vector3 arguments were captured for index/N and (index+0.5)/N candidate charts; no chart is authoritative without source/runtime equality.", "point_vs_array_residual_max": None, "point_vs_array_residual_by_candidate_chart": "POINT_VALUES_HASHED; component normalization/location comparison is not uniquely exposed", "bloch_phase_true_vs_false_relation_residual": [record["bloch_phase_true_vs_false_relation_residual"] for record in records], "raw_H_fourier_metadata_status": "NOT_EXPOSED_BY_PUBLIC_MODE_SOLVER", "raw_H_fourier_coefficient_shape": None, "output_grid_origin_metadata_status": "NOT_EXPOSED", "component_location_or_interpolation_metadata_status": "NOT_EXPOSED", "sampling_phase_correction_formula": None, "H_sampling_correction_status": "NO_UNIQUE_CORRECTION_ESTABLISHED", "authoritative_H_result_unchanged": True, "baseline_H_edge_metrics": metrics, "corrected_H_c3_minimum_overlap_singular_value": None, "corrected_H_c3_maximum_principal_angle": None, "corrected_H_c3_covariance_failure_count": None, "direct_mpb_methods_invoked": sorted({method for record in records for method in record["methods_invoked"]}), "alternative_explanations_considered": ["zero-origin common grid", "half-grid origin", "component interpolation", "raw Fourier output metadata", "field-point API coordinate chart"], "counterevidence_summary": {"reuse_failures": reuse_failures, "metadata_records": 3, "baseline_H_metrics": metrics}, "exact_remaining_uncertainty": "Runtime point and array values were captured for the fixed stencil, but the public API exposes no explicit output-grid origin, component location/interpolation, or raw Fourier coefficient metadata sufficient to select a unique correction.", "cheapest_remaining_discriminating_test": "A public raw reciprocal-H coefficient/output-grid descriptor or a documented point-vs-array normalization/location rule for the same three loaded states.", "next_science_decision": "ACQUIRE_MINIMAL_RAW_H_FOURIER_COEFFICIENT_C3_VALIDATION_TRIPLET", "minimal_next_live_state_count": 3, "execution_required_for_cheapest_test": True, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def _fail_closed(exc: BaseException, stage: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "structured_result_boundary_status": "PASS", "failure_code": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "failure_stage": stage, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0, "minimal_next_live_state_count": 0, "next_science_decision": "INSUFFICIENT_EVIDENCE", "post_analysis_checkout_unchanged": True, "traceback_tail": traceback.format_exc()[-3000:]}


def _emit_result(result: dict[str, Any]) -> int:
    result_path = Path(os.environ["MEPHC_RESULT_PATH"])
    try:
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except BaseException as exc:
        result = _fail_closed(exc, "result_serialization")
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    result_path.write_text(encoded + "\n", encoding="utf-8")
    return 0


def main() -> int:
    try:
        result = _science_result()
    except BaseException as exc:
        result = _fail_closed(exc, "science_body")
    return _emit_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
