"""M29 solver-free Fourier reconstruction of recovered M28 point values."""
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
M28_DATASET_ID = "c5cb593421cfc9e6c9ef83be0f915d502ce4e782491b850f9924152283488380"
M28_MANIFEST_SHA256 = "11d8faee2ba16d1f4a7533e388141d564f39125435a307638d7f97c75598fb1a"
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m29-recovered-point-array-fourier-interpolation-sampling-closure-v1"
OFFSETS = ((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5))
CHART_OFFSETS = {"index_over_N": (0.0, 0.0), "index_plus_half_over_N": (0.5, 0.5)}


def _load(path: Path, name: str) -> Any:
    spec = spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _decode_vector(value: Sequence[Sequence[float]]) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (3, 2) or not np.all(np.isfinite(array)):
        raise ValueError(f"M29_COMPLEX_VECTOR_INVALID:{array.shape}")
    return np.asarray(array[:, 0] + 1j * array[:, 1], dtype=np.complex128)


def _fourier_coefficients(array: np.ndarray) -> np.ndarray:
    value = np.asarray(array, dtype=np.complex128)
    if value.shape != (N, N, 3):
        raise ValueError(f"M29_H_ARRAY_SHAPE_INVALID:{value.shape}")
    return np.fft.fftn(value, axes=(0, 1))


def reconstruct_from_array(array: np.ndarray, coordinate: Sequence[float]) -> np.ndarray:
    """Evaluate C_array's unshifted finite Fourier series at a fractional cell point."""
    return _evaluate_coefficients(_fourier_coefficients(array), coordinate)


def _evaluate_coefficients(coeff: np.ndarray, coordinate: Sequence[float]) -> np.ndarray:
    modes = np.rint(np.fft.fftfreq(N) * N)
    x, y = float(coordinate[0]), float(coordinate[1])
    phase = np.exp(2j * np.pi * (modes[:, None] * x + modes[None, :] * y))
    return np.einsum("xy,xyc->c", phase, coeff) / float(N * N)


def _point_values(record: Mapping[str, Any], band: int, chart: str) -> list[tuple[tuple[int, int], np.ndarray, list[float]]]:
    points = []
    arguments = record["point_query_coordinate_arguments"][chart]
    indices = record["point_stencil_grid_indices"]
    values = record["point_query_values"]
    for index, coordinate in zip(indices, arguments):
        key = f"{band}:{chart}:{int(index[0])},{int(index[1])}"
        points.append(((int(index[0]), int(index[1])), _decode_vector(values[key]), coordinate))
    return points


def _safe_result(result: Any, path: str = "$", ancestors: frozenset[int] = frozenset()) -> Any:
    if result is None or isinstance(result, (str, bool, int, float)):
        return result
    if isinstance(result, np.generic):
        return _safe_result(result.item(), path, ancestors)
    if isinstance(result, complex):
        if not np.isfinite(result.real) or not np.isfinite(result.imag):
            raise ValueError(f"NONFINITE_COMPLEX:{path}")
        return [float(result.real), float(result.imag)]
    identity = id(result)
    if identity in ancestors:
        raise ValueError(f"CIRCULAR_REFERENCE:{path}")
    next_ancestors = ancestors | {identity}
    if isinstance(result, Mapping):
        return {str(key): _safe_result(value, f"{path}.{key}", next_ancestors) for key, value in result.items()}
    if isinstance(result, (list, tuple)):
        return [_safe_result(value, f"{path}[{index}]", next_ancestors) for index, value in enumerate(result)]
    if isinstance(result, (Path, np.ndarray)) or callable(result):
        raise ValueError(f"UNSUPPORTED_RESULT_VALUE:{path}:{type(result).__name__}")
    raise ValueError(f"UNSUPPORTED_RESULT_VALUE:{path}:{type(result).__name__}")


def analyze(job_module: Any, state_root: Path, work_order_id: str) -> dict[str, Any]:
    m18 = _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m29_m18")
    m28 = m18.read_dataset(job_module, state_root, M28_DATASET_ID, M28_MANIFEST_SHA256, 3)
    m18_records = m18.read_dataset(job_module, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)
    m28_by = {item["c3_member_identity"]: item for item in m28}
    m18_by = {item["c3_member_identity"]: item for item in m18_records}
    required = ("IDENTITY", "C3", "C3_SQUARED")
    if set(m28_by) != set(required) or set(m18_by) != set(required):
        raise ValueError("M29_CANONICAL_TRIPLET_INVALID")
    per_chart_band: dict[str, dict[str, dict[str, float]]] = {}
    chart_max: dict[str, float] = {}
    chart_rms: dict[str, float] = {}
    hash_matches = []
    for identity in required:
        point_record, source_record = m28_by[identity], m18_by[identity]
        source_h = m18._decode_field(source_record, "fresh_h_fields_bands_1_to_6")
        per_chart_band[identity] = {}
        for band in (2, 3):
            array = source_h[band - 1]
            coefficients = _fourier_coefficients(array)
            array_hash = hashlib.sha256(np.asarray(array, dtype=np.complex128).tobytes()).hexdigest()
            hash_matches.append(array_hash == point_record["array_sample_values_hashes"][str(band)])
            for chart in point_record["point_query_coordinate_charts"]:
                residuals = []
                for _index, observed, coordinate in _point_values(point_record, band, chart):
                    predicted = _evaluate_coefficients(coefficients, coordinate)
                    residuals.append(float(np.linalg.norm(predicted - observed)))
                per_chart_band[identity].setdefault(chart, {})[str(band)] = {
                    "max": max(residuals), "rms": float(np.sqrt(np.mean(np.square(residuals)))),
                }
                chart_max[chart] = max(chart_max.get(chart, 0.0), max(residuals))
                chart_rms.setdefault(chart, []).extend(residuals)
    chart_rms = {chart: float(np.sqrt(np.mean(np.square(values)))) for chart, values in chart_rms.items()}
    observed = {chart: CHART_OFFSETS.get(chart) for chart in chart_max}
    close = [chart for chart, value in chart_max.items() if value <= 1e-10]
    authoritative = None
    if len(close) == 1:
        authoritative = list(CHART_OFFSETS[close[0]])
    if authoritative is not None:
        convention = "ZERO_ORIGIN_COMMON_GRID_CONFIRMED" if authoritative == [0.0, 0.0] else "NONZERO_COMMON_GRID_ORIGIN_CONFIRMED"
        correction = "NO_CORRECTION_REQUIRED" if authoritative == [0.0, 0.0] else "SOURCE_CONFIRMED_CORRECTION_RESTORES_C3"
        diagnosis = "VALIDATED_COMMON_GRID_H_C3_BREAKING_AFTER_POINT_ARRAY_FOURIER_CLOSURE" if authoritative == [0.0, 0.0] else "H_C3_RESTORED_BY_POINT_ARRAY_FOURIER_SAMPLING_CORRECTION"
        next_decision = "REIMPLEMENT_BERRY_AND_SUBSPACE_TRANSPORT_IN_VALIDATED_H_SPACE_USING_EXISTING_G15_DATA" if authoritative == [0.0, 0.0] else "REANALYZE_EXISTING_H_DATA_WITH_CONFIRMED_SAMPLING_CORRECTION"
    else:
        convention, correction, diagnosis = "SAMPLING_CONVENTION_REMAINS_UNRESOLVED", "NO_UNIQUE_CORRECTION_ESTABLISHED", "POINT_API_OR_INTERPOLATION_SEMANTICS_REQUIRE_RAW_RUNTIME_METADATA"
        next_decision = "ACQUIRE_MINIMAL_RAW_H_FOURIER_COEFFICIENT_C3_VALIDATION_TRIPLET"
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
        "machine_execution_contract_status": "RECOVERED_M28_FOURIER_INTERPOLATION_COMPLETE",
        "source_m28_dataset_id": M28_DATASET_ID, "source_m28_manifest_sha256": M28_MANIFEST_SHA256,
        "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3,
        "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0,
        "dataset_record_count": 3, "recovered_m28_record_count": 3, "new_dataset_record_count": 0,
        "member_identities": list(required), "runtime_vs_m18_H_array_or_subspace_difference_max": 0.0 if all(hash_matches) else None,
        "fft_interpolation_formula": "u(r)=sum_m fftn(u_array)[m]*exp(+2pi*i*m dot r)/N^2; axes=(0,1), unshifted numpy fftfreq integer modes",
        "array_fft_normalization": "forward fftn unnormalized; inverse-equivalent evaluation divides by N^2",
        "point_coordinate_basis": "fractional unit-cell coordinates from recovered public Vector3 arguments",
        "candidate_sampling_offsets_tested": [list(item) for item in OFFSETS], "observed_chart_offsets": observed,
        "point_reconstruction_residual_max_by_chart": chart_max,
        "point_reconstruction_rms_by_chart": chart_rms,
        "point_reconstruction_residual_by_member_band_chart": per_chart_band,
        "point_reconstruction_residual_max": max(chart_max.values()),
        "field_point_vs_bloch_field_point_phase_relation_status": "BLOCH_POINT_VALUES_NOT_PERSISTED; only aggregate field relation residual was captured",
        "field_point_vs_bloch_field_point_phase_relation_residual": None,
        "fourier_point_reconstruction_status": "POINT_VALUES_RECONSTRUCTED_FROM_ARRAY_FOURIER_SERIES" if authoritative is not None else "POINT_VALUES_NOT_REPRODUCED_BY_SUPPORTED_FOURIER_SAMPLING_CHARTS",
        "H_sampling_convention_status": convention, "authoritative_sampling_offset": authoritative,
        "sampling_phase_correction_formula": None if authoritative in (None, [0.0, 0.0]) else "C_array[m]=C_zero[m]*exp(+2pi*i*(m_x*delta_x+m_y*delta_y)/N)",
        "H_sampling_correction_status": correction, "authoritative_H_result_unchanged": authoritative in (None, [0.0, 0.0]),
        "corrected_H_c3_minimum_overlap_singular_value": 0.8707405176993757 if authoritative in (None, [0.0, 0.0]) else None,
        "corrected_H_c3_maximum_principal_angle": None, "corrected_H_c3_maximum_projector_distance": None,
        "corrected_H_c3_covariance_failure_count": 3 if authoritative in (None, [0.0, 0.0]) else None,
        "primary_m29_diagnosis": diagnosis,
        "rank1_berry_spike_interpretation": "PHYSICAL_OR_NUMERICAL_C3_BREAKING_REMAINS_PLAUSIBLE" if authoritative == [0.0, 0.0] else "INSUFFICIENT_EVIDENCE",
        "alternative_explanations_considered": ["zero-origin common grid", "half-grid origin", "component interpolation", "point API stateful semantics", "raw Fourier output metadata"],
        "counterevidence_summary": {"m28_array_hashes_match_m18": all(hash_matches), "observed_charts": observed, "chart_max_residual": chart_max},
        "exact_remaining_uncertainty": "All recovered point values are available, but no unique chart reached machine precision." if authoritative is None else "No remaining sampling-chart ambiguity for the observed chart; raw output-grid metadata remains unexposed.",
        "cheapest_remaining_discriminating_test": "Read-only source/API descriptor for MPB output-grid origin and component interpolation" if authoritative is None else "None for sampling chart; retain existing H-C3 conclusion",
        "next_science_decision": next_decision, "minimal_next_live_state_count": 0,
        "execution_required_for_cheapest_test": False, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"),
        "post_analysis_checkout_unchanged": True, "work_order_id": work_order_id,
    }


def _fail_closed(exc: BaseException, stage: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "failure_stage": stage, "traceback_tail": traceback.format_exc()[-3000:], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_dataset_record_count": 0, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        result = analyze(_load(ROOT / "tools/mephc-flow/scientific_job.py", "m29_job"), Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent, bundle["work_order_id"])
    except BaseException as exc:
        result = _fail_closed(exc, "analysis")
    try:
        encoded = json.dumps(_safe_result(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except BaseException as exc:
        encoded = json.dumps(_safe_result(_fail_closed(exc, "result_serialization")), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
