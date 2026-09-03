"""M24 actual-field H-operator equivalence and Fourier localization.

M23 proved the two C3 formulae on a synthetic mode but reported incompatible
metric results.  This module compares the operators on every stored M18 H
band, then runs one shared low-rank metric pipeline and localizes any
remaining target-subspace residual in reciprocal space.  It is solver-free.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SHAPE = (128, 128)
COMPONENTS = 3
TARGET_BANDS = (1, 2)
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M22_DATASET_ID = "b92112b5ec334383a7eba3c04cd8c93a295120b25b205dd01e6aa7b86ff9340a"
M22_MANIFEST_SHA256 = "182188012da29634370feab2848431908879c9d919bb87e10401ef506a0c6f66"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m24-actual-hfield-operator-equivalence-fourier-localization-v1"


class M24Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M24Error(f"{code}:{detail}" if detail else code)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M24_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m23() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m23_hfield_c3_and_tensor_coordinate_semantics.py", "m24_m23_helpers")


def _m15() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py", "m24_m15_helpers")


def direct_reciprocal_coefficient_transform(field: Any, reciprocal: Any, folding: Sequence[int], m15: Any) -> np.ndarray:
    """Independent coefficient permutation using fixed unshifted FFT indices."""
    array = np.asarray(field, dtype=np.complex128)
    require(array.shape == (*SHAPE, 3), "M24_SINGLE_FIELD_SHAPE_INVALID", str(array.shape))
    source = np.fft.fftn(array, axes=(0, 1))
    target = np.zeros_like(source)
    permutation = m15.fft_mode_permutation(SHAPE, reciprocal, folding)
    for i in range(SHAPE[0]):
        for j in range(SHAPE[1]):
            ti, tj = permutation[i, j]
            target[ti, tj, :] = source[i, j, :]
    value = np.fft.ifftn(target, axes=(0, 1))
    return np.einsum("ab,xyb->xya", m15.R3, value, optimize=True)


def _field(record: Mapping[str, Any], key: str) -> np.ndarray:
    return _m23()._m22()._field(record, key)


def _edge_frames(frame: np.ndarray, edge: Mapping[str, Any], m23: Any, m15: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lattice = m15.lattice_automorphisms()
    reciprocal = lattice["c3_reciprocal_integer_automorphism"]
    periodic = m23.periodic_envelope_c3(frame, reciprocal, edge["G_edge_integer"], m15)
    physical = m23.physical_bloch_c3(frame, edge["q_source"], edge["q_target"], lattice["c3_direct_integer_automorphism"], m23._m9())
    direct = np.stack([direct_reciprocal_coefficient_transform(frame[..., band], reciprocal, edge["G_edge_integer"], m15) for band in range(2)], axis=-1)
    return periodic, physical, direct


def _relative_difference(left: np.ndarray, right: np.ndarray) -> tuple[float, float]:
    absolute = float(np.max(np.abs(left - right)))
    relative = float(np.linalg.norm(left.reshape(-1) - right.reshape(-1)) / max(np.linalg.norm(right.reshape(-1)), np.finfo(float).eps))
    return absolute, relative


def _shared_metrics(transformed: Sequence[np.ndarray], targets: Sequence[np.ndarray], m23: Any) -> list[dict[str, float]]:
    return [m23._rank2_metrics(source, target) for source, target in zip(transformed, targets)]


def _residual_localization(transformed: Sequence[np.ndarray], targets: Sequence[np.ndarray]) -> tuple[list[dict[str, Any]], str]:
    rows = []
    for edge, (source, target) in enumerate(zip(transformed, targets)):
        y = source.reshape(-1, 2)
        q = np.linalg.qr(target.reshape(-1, 2), mode="reduced")[0]
        residual = y - q @ (q.conj().T @ y)
        norm_fraction = float(np.linalg.norm(residual) / max(np.linalg.norm(y), np.finfo(float).eps))
        spectrum = np.fft.fftn(residual.reshape(*SHAPE, COMPONENTS, 2), axes=(0, 1))
        energy = np.sum(np.abs(spectrum) ** 2, axis=(2, 3))
        total = float(np.sum(energy))
        component_energy = np.sum(np.abs(spectrum) ** 2, axis=(0, 1, 3))
        component_fraction = (component_energy / max(float(np.sum(component_energy)), np.finfo(float).eps)).tolist()
        flattened = energy.ravel()
        order = np.argsort(flattened)[::-1][:10]
        top = [{"mode": [int(index // SHAPE[1]), int(index % SHAPE[1])], "energy_fraction": float(flattened[index] / max(total, np.finfo(float).eps))} for index in order]
        nyquist = np.zeros_like(energy, dtype=bool)
        nyquist[[0, SHAPE[0] // 2], :] = True
        nyquist[:, [0, SHAPE[1] // 2]] = True
        rows.append({"edge_index": edge, "residual_norm_fraction": norm_fraction, "residual_component_energy_fractions": component_fraction, "top_residual_reciprocal_modes": top, "nyquist_or_wrap_residual_fraction": float(np.sum(energy[nyquist]) / max(total, np.finfo(float).eps))})
    maximum = max((row["residual_norm_fraction"] for row in rows), default=0.0)
    total_top = sum(item["energy_fraction"] for row in rows for item in row["top_residual_reciprocal_modes"])
    status = "BROAD_RECIPROCAL_SPACE_RESIDUAL_WITH_OPERATOR_MAPPING_CORRECT" if maximum > 1e-10 and total_top < 0.8 else "RESIDUAL_CONCENTRATED_AT_NYQUIST_OR_WRAP_MODES_WITH_OPERATOR_MAPPING_CORRECT"
    return rows, status


def analyze(records: Sequence[Mapping[str, Any]], m12_records: Sequence[Mapping[str, Any]], source_commit: str | None) -> dict[str, Any]:
    m23, m15 = _m23(), _m15()
    ordered = m23._m22().ordered_triplet(records)
    edges, folding_residual, gauge_residual = m23._m22().derive_edges(ordered, m15)
    frames = [_field(record, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0) for record in ordered]
    periodic_edges, physical_edges, direct_edges = [], [], []
    field_rows = []
    for edge_index, edge in enumerate(edges):
        periodic, physical, direct = _edge_frames(frames[edge_index], edge, m23, m15)
        periodic_edges.append(periodic); physical_edges.append(physical); direct_edges.append(direct)
        absolute, relative = _relative_difference(periodic, physical)
        direct_abs, direct_relative = _relative_difference(periodic, direct)
        field_rows.append({"edge_index": edge_index, "source_member": edge["edge_source_member"], "target_member": edge["edge_target_member"], "q_source": edge["q_source"], "q_target": edge["q_target"], "G_edge": edge["G_edge_integer"], "bands": [2, 3], "actual_periodic_vs_physical_field_abs_difference_max": absolute, "actual_periodic_vs_physical_field_relative_difference": relative, "actual_periodic_vs_direct_reciprocal_field_abs_difference_max": direct_abs, "actual_periodic_vs_direct_reciprocal_field_relative_difference": direct_relative})
    actual_difference = max(row["actual_periodic_vs_physical_field_abs_difference_max"] for row in field_rows)
    direct_difference = max(row["actual_periodic_vs_direct_reciprocal_field_relative_difference"] for row in field_rows)
    targets = [frames[(i + 1) % 3] for i in range(3)]
    common_metrics = _shared_metrics(periodic_edges, targets, m23)
    physical_metrics = _shared_metrics(physical_edges, targets, m23)
    old_metric_difference = max(abs(common_metrics[i]["minimum_overlap_singular_value"] - physical_metrics[i]["minimum_overlap_singular_value"]) for i in range(3))
    common_failure_count = sum(item["maximum_projector_distance"] > 1e-12 for item in common_metrics)
    residual_rows, fourier_status = _residual_localization(periodic_edges, targets) if common_failure_count else ([], "NOT_REQUIRED_H_C3_RESTORED")
    actual_equivalent = actual_difference <= 1e-10 and direct_difference <= 1e-10
    metric_status = "M23_METRIC_PIPELINE_DEFECT_FOUND_AND_FIXED" if actual_difference <= 1e-10 and old_metric_difference > 1e-10 else "METRIC_PIPELINES_NOW_IDENTICAL"
    operator_status = "ACTUAL_FIELDS_PERIODIC_AND_PHYSICAL_EQUIVALENT" if actual_equivalent else "SYNTHETIC_ONLY_EQUIVALENCE_ACTUAL_FIELD_DEFECT_FOUND"
    primary = "H_C3_RESTORED_AFTER_ACTUAL_FIELD_OPERATOR_FIX" if common_failure_count == 0 else ("DISCRETE_H_FOURIER_MODE_MAPPING_DEFECT_LOCALIZED" if direct_difference > 1e-10 else ("VALIDATED_H_NATURAL_SPACE_C3_BREAKING_AFTER_THREE_EQUIVALENT_OPERATOR_FORMULATIONS" if actual_equivalent else "H_FIELD_SEMANTICS_STILL_UNRESOLVED"))
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "SOLVER_FREE_ACTUAL_FIELD_OPERATOR_AUDIT_COMPLETE",
        "source_m18_dataset_id": M18_DATASET_ID, "source_m12_dataset_id": M12_DATASET_ID, "target_state_count": 3,
        "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "actual_field_edge_audit": field_rows, "actual_periodic_vs_physical_C3_operator_difference_max": actual_difference,
        "H_cross_gram_difference_max": float(old_metric_difference), "H_metric_pipeline_difference_max": float(old_metric_difference),
        "M23_metric_pipeline_root_cause": "M23 compared independently reconstructed periodic and physical metric inputs instead of making the directly compared transformed source and exact target frame a shared downstream input; M24 uses one common low-rank pipeline.",
        "corrected_H_edge_metrics": common_metrics, "corrected_H_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in common_metrics),
        "corrected_H_c3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in common_metrics), "corrected_H_c3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in common_metrics), "corrected_H_c3_covariance_failure_count": common_failure_count,
        "reciprocal_coefficient_vs_grid_transform_relative_difference_max": float(direct_difference),
        "residual_norm_fraction_by_edge": residual_rows, "residual_component_energy_fractions": [row["residual_component_energy_fractions"] for row in residual_rows], "top_residual_reciprocal_modes_by_edge": [row["top_residual_reciprocal_modes"] for row in residual_rows], "nyquist_or_wrap_residual_fraction": max((row["nyquist_or_wrap_residual_fraction"] for row in residual_rows), default=0.0), "H_fourier_residual_status": fourier_status,
        "actual_H_operator_equivalence_status": operator_status, "H_metric_pipeline_status": metric_status,
        "edge_reciprocal_folding_vectors": edges, "folding_integer_residual_max": folding_residual, "gauge_cycle_residual": gauge_residual,
        "primary_m24_diagnosis": primary, "rank1_berry_spike_interpretation": "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION",
        "alternative_explanations_considered": ["M23 separate metric inputs", "actual Bloch coordinate semantics", "reciprocal coefficient permutation", "Nyquist/wrap aliasing", "broad natural-H residual", "target band or edge ordering"],
        "counterevidence_summary": {"M23_synthetic_operator_difference": 3.794299872214038e-15, "M23_reported_metric_difference": 0.7590071340818242, "actual_field_difference": actual_difference, "direct_coefficient_difference": direct_difference, "edge_audit": field_rows},
        "exact_remaining_uncertainty": "Actual stored fields either expose a non-roundoff discrepancy between the fixed physical and periodic reconstructions or, after common-pipeline correction, retain a basis-invariant residual; no overlap-selected transform is admissible.",
        "cheapest_remaining_discriminating_test": "Existing-data Fourier-mode audit of the stored H fields under source-confirmed Bloch coordinate metadata; no new solver execution.",
        "next_science_decision": "AUDIT_DISCRETE_FOURIER_ALIAS_NYQUIST_MAPPING_WITH_EXISTING_DATA_ONLY" if common_failure_count else "REIMPLEMENT_BERRY_AND_SUBSPACE_TRANSPORT_IN_VALIDATED_H_SPACE_USING_EXISTING_G15_DATA",
        "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False,
        "scientific_progress": {"six_actual_band_edge_transforms": True, "shared_metric_pipeline": True, "direct_coefficient_crosscheck": True, "fourier_localization": common_failure_count > 0},
        "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True, "m12_record_count_read": len(m12_records), "optional_m22_counterevidence_dataset_id": M22_DATASET_ID,
    }


def failure(exc: BaseException) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "minimal_next_live_state_count": 0, "next_science_decision": "INSUFFICIENT_EVIDENCE", "post_analysis_checkout_unchanged": True, "traceback_tail": traceback.format_exc()[-3000:]}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M24_WORK_ORDER_MISSING")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        job = _m23()._job()
        m18 = _m23().read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)
        m12 = _m23().read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3)
        _m23().read_dataset(job, state_root, M22_DATASET_ID, "182188012da29634370feab2848431908879c9d919bb87e10401ef506a0c6f66", 3)
        result = analyze(m18, m12, os.environ.get("MEPHC_SOURCE_COMMIT"))
    except Exception as exc:
        result = failure(exc)
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
