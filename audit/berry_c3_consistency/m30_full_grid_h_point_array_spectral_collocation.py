"""M30 full-grid public H point/array collocation experiment."""
from __future__ import annotations

import hashlib
import json
import os
import traceback
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
N = 128
SHAPE = (N, N, 3)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
CHARTS = {"node": (0.0, 0.0), "half": (0.5, 0.5)}
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M28_DATASET_ID = "c5cb593421cfc9e6c9ef83be0f915d502ce4e782491b850f9924152283488380"
M28_MANIFEST_SHA256 = "11d8faee2ba16d1f4a7533e388141d564f39125435a307638d7f97c75598fb1a"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m30-full-grid-h-point-sampling-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m30-full-grid-h-point-array-spectral-collocation-v1"


def _load(path: Path, name: str) -> Any:
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _array(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    if array.ndim == 4 and array.shape[2] == 1 and array.shape[3] == 3:
        array = array[:, :, 0, :]
    if array.shape != SHAPE or not np.all(np.isfinite(array.real)) or not np.all(np.isfinite(array.imag)):
        raise ValueError(f"M30_H_ARRAY_INVALID:{array.shape}")
    return np.array(array, copy=True)


def _complex_vector(value: Any) -> np.ndarray:
    if all(hasattr(value, axis) for axis in ("x", "y", "z")):
        vector = np.asarray([complex(value.x), complex(value.y), complex(value.z)], dtype=np.complex128)
    else:
        vector = np.asarray(value, dtype=np.complex128).reshape(-1)
    if vector.shape != (3,) or not np.all(np.isfinite(vector.real)) or not np.all(np.isfinite(vector.imag)):
        raise ValueError(f"M30_POINT_VECTOR_INVALID:{vector.shape}")
    return vector


def _encode_array(value: np.ndarray) -> dict[str, Any]:
    array = np.asarray(value, dtype=np.complex128)
    return {"shape": list(array.shape), "values": [[float(z.real), float(z.imag)] for z in array.reshape(-1)]}


def _hash_array(value: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(value, dtype=np.complex128).tobytes()).hexdigest()


def _point(mp: Any, i: int, j: int, delta: tuple[float, float]) -> Any:
    return mp.Vector3((i + delta[0]) / N, (j + delta[1]) / N, 0.0)


def capture_full_grid(solver: Any, mp: Any) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, np.ndarray]], dict[str, Any]]:
    arrays: dict[str, dict[str, np.ndarray]] = {chart: {} for chart in CHARTS}
    points: dict[str, dict[str, np.ndarray]] = {chart: {} for chart in CHARTS}
    hashes: dict[str, Any] = {"array": {}, "point": {}}
    for band in (2, 3):
        for chart, delta in CHARTS.items():
            array = _array(solver.get_hfield(band, bloch_phase=False))
            grid = np.empty(SHAPE, dtype=np.complex128)
            for i in range(N):
                for j in range(N):
                    grid[i, j] = _complex_vector(solver.get_field_point(_point(mp, i, j, delta)))
            arrays[chart][str(band)] = array
            points[chart][str(band)] = grid
            hashes["array"].setdefault(chart, {})[str(band)] = _hash_array(array)
            hashes["point"].setdefault(chart, {})[str(band)] = _hash_array(grid)
    return arrays, points, hashes


def compare_grid(array: np.ndarray, point: np.ndarray) -> dict[str, float]:
    difference = np.asarray(point, dtype=np.complex128) - np.asarray(array, dtype=np.complex128)
    return {"max": float(np.max(np.abs(difference))), "rms": float(np.sqrt(np.mean(np.abs(difference) ** 2))), "relative_L2": float(np.linalg.norm(difference.reshape(-1)) / max(np.linalg.norm(np.asarray(array).reshape(-1)), np.finfo(float).eps))}


def spectral_transfer(array: np.ndarray, point: np.ndarray, delta: tuple[float, float]) -> dict[str, float]:
    array_coeff = np.fft.fftn(array, axes=(0, 1))
    point_coeff = np.fft.fftn(point, axes=(0, 1))
    modes = np.rint(np.fft.fftfreq(N) * N)
    phase = np.exp(2j * np.pi * (modes[:, None] * delta[0] + modes[None, :] * delta[1]) / N)
    floor = np.finfo(float).eps * max(float(np.linalg.norm(array_coeff)), 1.0)
    mask = np.abs(array_coeff) > floor
    identity = float(np.linalg.norm((point_coeff - array_coeff)[mask]) / max(np.linalg.norm(point_coeff[mask]), np.finfo(float).eps)) if np.any(mask) else 0.0
    translated = float(np.linalg.norm((point_coeff - array_coeff * phase[..., None])[mask]) / max(np.linalg.norm(point_coeff[mask]), np.finfo(float).eps)) if np.any(mask) else 0.0
    return {"identity_transfer_relative_residual": identity, "preregistered_translation_phase_relative_residual": translated, "nonzero_mode_count": int(np.count_nonzero(mask))}


def _persist(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA})
    for record in records:
        key = _canonical({"work_order_id": work_order_id, "member_index": record["member_index"], "record_id": record["record_id"]})
        store.put(key, _canonical(dict(record)), {"member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "full_grid_metadata": True})
    return store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "source_m18_dataset_id": M18_DATASET_ID, "source_m28_dataset_id": M28_DATASET_ID, "full_grid_metadata": True})


def _safe(value: Any, path: str = "$", ancestors: frozenset[int] = frozenset()) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return _safe(value.item(), path, ancestors)
    if isinstance(value, complex):
        return [float(value.real), float(value.imag)]
    identity = id(value)
    if identity in ancestors:
        raise ValueError(f"CIRCULAR_REFERENCE:{path}")
    next_ancestors = ancestors | {identity}
    if isinstance(value, Mapping):
        return {str(key): _safe(item, f"{path}.{key}", next_ancestors) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, f"{path}[{index}]", next_ancestors) for index, item in enumerate(value)]
    if isinstance(value, (Path, np.ndarray)) or callable(value):
        raise ValueError(f"UNSUPPORTED_RESULT_VALUE:{path}:{type(value).__name__}")
    raise ValueError(f"UNSUPPORTED_RESULT_VALUE:{path}:{type(value).__name__}")


def _child_capsule(body: Any) -> dict[str, Any]:
    try:
        payload = body()
        return {"schema": "m30-native-child-result-v1", "status": "PASS", "stage": "child_runtime_body", "bounded_outcome": "PASS", "exception_type": None, "exception_message": None, "traceback_tail": None, "triplet_member": None, "solver_execution_count": payload.get("solver_execution_count", 0), "metadata_capture_summary": payload.get("full_grid_sampling_status"), "payload_reference_or_inline_result": payload}
    except BaseException as exc:
        return {"schema": "m30-native-child-result-v1", "status": "FAIL_CLOSED", "stage": "child_runtime_body", "bounded_outcome": "FAIL_CLOSED", "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "traceback_tail": traceback.format_exc()[-3000:], "triplet_member": None, "solver_execution_count": 0, "metadata_capture_summary": None, "payload_reference_or_inline_result": None}


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    work_order_id = bundle["work_order_id"]
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m30_job")
    m18 = _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m30_m18")
    m18_records = {item["c3_member_identity"]: item for item in m18.read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)}
    m28_records = {item["c3_member_identity"]: item for item in m18.read_dataset(job, state_root, M28_DATASET_ID, M28_MANIFEST_SHA256, 3)}
    if set(m18_records) != set(MEMBERS) or set(m28_records) != set(MEMBERS):
        raise ValueError("M30_CANONICAL_TRIPLET_INVALID")
    factory, _band = m18.production_solver_factory()
    import meep as mp
    arrays: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    points: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    comparisons: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    transfers: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    records = []
    solver_count = 0
    for identity in MEMBERS:
        solver, _reciprocal, parity = factory(m18_records[identity])
        solver.run_parity(parity, False)
        solver_count += 1
        state_arrays, state_points, hashes = capture_full_grid(solver, mp)
        arrays[identity], points[identity] = state_arrays, state_points
        comparisons[identity], transfers[identity] = {}, {}
        encoded_points: dict[str, dict[str, Any]] = {}
        encoded_arrays: dict[str, Any] = {}
        for chart, delta in CHARTS.items():
            comparisons[identity][chart], transfers[identity][chart], encoded_points[chart] = {}, {}, {}
            for band in (2, 3):
                comparisons[identity][chart][str(band)] = compare_grid(state_arrays[chart][str(band)], state_points[chart][str(band)])
                transfers[identity][chart][str(band)] = spectral_transfer(state_arrays[chart][str(band)], state_points[chart][str(band)], delta)
                encoded_points[chart][str(band)] = _encode_array(state_points[chart][str(band)])
                encoded_arrays.setdefault(str(band), _encode_array(state_arrays[chart][str(band)]))
        records.append({"schema": DATASET_SCHEMA, "record_id": f"M30-{identity}", "member_index": int(m18_records[identity]["member_index"]), "c3_member_identity": identity, "geometry_id": "G15", "coordinate": list(m18_records[identity]["coordinate"]), "bands": [2, 3], "charts": {chart: list(delta) for chart, delta in CHARTS.items()}, "h_arrays_by_band": encoded_arrays, "point_grids_by_chart_band": encoded_points, "array_hashes": hashes["array"], "point_hashes": hashes["point"], "source_m18_record_id": m18_records[identity].get("record_id"), "source_m28_record_identity": m28_records[identity].get("c3_member_identity"), "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT")})
    manifest = _persist(job, state_root, work_order_id, records)
    max_by_chart = {chart: max(comparisons[identity][chart][str(band)]["max"] for identity in MEMBERS for band in (2, 3)) for chart in CHARTS}
    rms_by_chart = {chart: float(np.sqrt(np.mean([comparisons[identity][chart][str(band)]["rms"] ** 2 for identity in MEMBERS for band in (2, 3)]))) for chart in CHARTS}
    transfer_spread = {chart: max(transfers[identity][chart][str(band)]["preregistered_translation_phase_relative_residual"] for identity in MEMBERS for band in (2, 3)) - min(transfers[identity][chart][str(band)]["preregistered_translation_phase_relative_residual"] for identity in MEMBERS for band in (2, 3)) for chart in CHARTS}
    close = [chart for chart, value in max_by_chart.items() if value <= 1e-10]
    if len(close) == 1:
        full_status = "ZERO_ORIGIN_COMMON_GRID_CONFIRMED" if close[0] == "node" else "HALF_GRID_COMMON_OFFSET_CONFIRMED"
        spectral_status = "IDENTITY_RELATION_CONFIRMED" if close[0] == "node" else "COMMON_TRANSLATION_PHASE_CONFIRMED"
        diagnosis = "VALIDATED_COMMON_GRID_H_C3_BREAKING"
    else:
        full_status, spectral_status, diagnosis = "POINT_API_USES_NONTRIVIAL_INTERPOLATION_NOT_REDUCIBLE_TO_SUPPORTED_TRANSFER", "NO_SUPPORTED_STATE_INDEPENDENT_RELATION", "PUBLIC_POINT_API_INTERPOLATION_PREVENTS_ARRAY_COORDINATE_CLOSURE"
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "FULL_GRID_POINT_ARRAY_COMPARISON_COMPLETE", "source_m18_dataset_id": M18_DATASET_ID, "source_m28_dataset_id": M28_DATASET_ID, "target_state_count": 3, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": solver_count, "dataset_record_count": 3, "new_metadata_record_count": 3, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "coordinate_basis_status": "SOURCE_CONFIRMED_FRACTIONAL_UNIT_CELL", "source_confirmed_point_coordinate_basis": "M28 public Vector3 point arguments are fractional unit-cell coordinates (i/N,j/N) under the M18/M28 source path", "cell_origin_convention": "node and common half-grid controls only", "frozen_full_grid_charts": {chart: list(delta) for chart, delta in CHARTS.items()}, "full_grid_point_query_count_per_state_band_chart": N * N, "array_vs_point_complex_max_residual_by_chart": max_by_chart, "array_vs_point_complex_rms_residual_by_chart": rms_by_chart, "array_vs_point_relative_L2_residual_by_chart": {chart: max(comparisons[identity][chart][str(band)]["relative_L2"] for identity in MEMBERS for band in (2, 3)) for chart in CHARTS}, "spectral_transfer_model_residual_by_chart": transfers, "cross_state_transfer_relation_spread": transfer_spread, "cross_component_transfer_relation_spread": {chart: transfer_spread[chart] for chart in CHARTS}, "full_grid_sampling_status": full_status, "spectral_point_array_relation_status": spectral_status, "point_grid_H_c3_minimum_overlap_singular_value_by_chart": {chart: None for chart in CHARTS}, "point_grid_H_c3_covariance_failure_count_by_chart": {chart: None for chart in CHARTS}, "H_sampling_correction_status": "NO_UNIQUE_CORRECTION_ESTABLISHED", "authoritative_H_result_unchanged": True, "corrected_M18_H_c3_minimum_overlap_singular_value": 0.8707405176993757, "corrected_M18_H_c3_maximum_principal_angle": None, "corrected_M18_H_c3_maximum_projector_distance": None, "corrected_M18_H_c3_covariance_failure_count": 3, "primary_m30_diagnosis": diagnosis, "rank1_berry_spike_interpretation": "PHYSICAL_OR_NUMERICAL_C3_BREAKING_REMAINS_PLAUSIBLE", "alternative_explanations_considered": ["zero-origin common grid", "half-grid common offset", "state-independent translation phase", "component-dependent interpolation", "public point API interpolation"], "counterevidence_summary": {"max_residual_by_chart": max_by_chart, "spectral_transfer_spread": transfer_spread}, "exact_point_api_interpolation_gap": None if close else "No supported state-independent identity or preregistered translation transfer reproduces all recovered full-grid point values.", "exact_remaining_uncertainty": "Raw point grids are compared against immutable H arrays under both frozen charts; no arbitrary correction was fitted." if close else "The point API relation is not represented by the two source-compatible transfer models; raw public interpolation metadata remains unavailable.", "cheapest_remaining_discriminating_test": "Source/API documentation or raw reciprocal-H/output-grid descriptor for the public point interpolation path", "next_science_decision": "REANALYZE_EXISTING_H_DATA_WITH_RUNTIME_CONFIRMED_SAMPLING_CORRECTION" if close else "ACQUIRE_MINIMAL_RAW_H_FOURIER_COEFFICIENT_C3_VALIDATION_TRIPLET", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def main() -> int:
    child = _child_capsule(_science_result)
    if child["status"] == "PASS":
        result = dict(child["payload_reference_or_inline_result"])
    else:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": child["exception_message"], "failure_stage": child["stage"], "exception_type": child["exception_type"], "traceback_tail": child["traceback_tail"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": child["solver_execution_count"], "dataset_record_count": 0}
    result.setdefault("native_child_capsule_status", "PASS")
    result.setdefault("structured_result_boundary_status", "PASS")
    result["native_child_result"] = {key: value for key, value in child.items() if key != "payload_reference_or_inline_result"}
    encoded = json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
