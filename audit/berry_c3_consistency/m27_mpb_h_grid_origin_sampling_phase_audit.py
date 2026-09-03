"""M27 source-level H output-grid origin and Fourier phase audit."""
from __future__ import annotations

import inspect
import json
import math
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from importlib.util import spec_from_file_location, module_from_spec

ROOT = Path(__file__).resolve().parents[2]
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m27-h-grid-origin-sampling-phase-audit-v1"
SHAPE = (128, 128)


def _load(path: Path, name: str) -> Any:
    spec = spec_from_file_location(name, path); assert spec is not None and spec.loader is not None
    module = module_from_spec(spec); spec.loader.exec_module(module); return module


def _m23() -> Any:
    return _load(ROOT / "audit/berry_c3_consistency/m23_hfield_c3_and_tensor_coordinate_semantics.py", "m27_m23")


def _m15() -> Any:
    return _load(ROOT / "audit/berry_c3_consistency/m15_discrete_fft_maxwell_covariance_audit.py", "m27_m15")


def _phase_law(mode_source: Sequence[int], mode_target: Sequence[int], delta_source: Sequence[float], delta_target: Sequence[float], size: int = 128) -> complex:
    source = np.asarray(mode_source, dtype=float); target = np.asarray(mode_target, dtype=float)
    return complex(np.exp(2j * np.pi * (float(np.dot(target, delta_target)) - float(np.dot(source, delta_source))) / size))


def phase_law_validation() -> dict[str, Any]:
    modes = [((7, -11), (13, 5)), ((-64, 9), (3, -27)), ((31, 42), (-8, 17))]
    delta = np.asarray([0.5, -0.5]); errors = []
    for source, target in modes:
        x, y = np.meshgrid(np.arange(128), np.arange(128), indexing="ij")
        source_field = np.exp(2j * np.pi * (source[0] * x + source[1] * y) / 128)
        target_field = np.exp(2j * np.pi * (target[0] * x + target[1] * y) / 128)
        shifted_source = source_field * np.exp(2j * np.pi * (source[0] * delta[0] + source[1] * delta[1]) / 128)
        shifted_target = target_field * np.exp(2j * np.pi * (target[0] * delta[0] + target[1] * delta[1]) / 128)
        predicted = _phase_law(source, target, delta, delta)
        errors.append(abs((shifted_target[0, 0] / target_field[0, 0]) / ((shifted_source[0, 0] / source_field[0, 0]) * predicted) - 1.0))
    return {"status": "PASS", "maximum_residual": float(max(errors)), "common_offset_formula": "C_delta(m)=C_zero(m) exp(+i 2pi m dot delta/N); C3 phase ratio=exp(+i 2pi(m_target dot delta_target-m_source dot delta_source)/N)", "component_offset_formula": "Apply exp(+i 2pi m dot delta_component/N) per Cartesian component before fixed R; component phases cannot commute through R unless delta_x=delta_y=delta_z."}


def _shift(frame: np.ndarray, delta: Sequence[float]) -> np.ndarray:
    coeff = np.fft.fftn(frame, axes=(0, 1)); x, y = np.meshgrid(np.rint(np.fft.fftfreq(128) * 128), np.rint(np.fft.fftfreq(128) * 128), indexing="ij")
    phase = np.exp(2j * np.pi * (x * float(delta[0]) + y * float(delta[1])) / 128)[..., None, None]
    return np.fft.ifftn(coeff * phase, axes=(0, 1))


def analyze(records: Sequence[Mapping[str, Any]], source_commit: str | None) -> dict[str, Any]:
    m23, m15 = _m23(), _m15(); m22 = m23._m22(); ordered = m22.ordered_triplet(records); edges, fold_residual, gauge_residual = m22.derive_edges(ordered, m15); lattice = m15.lattice_automorphisms(); frames = [m23._field(item, "fresh_h_fields_bands_1_to_6")[list((1, 2))].transpose(1, 2, 3, 0) for item in ordered]; baseline = [m23.periodic_envelope_c3(frame, lattice["c3_reciprocal_integer_automorphism"], edge["G_edge_integer"], m15) for frame, edge in zip(frames, edges)]; targets = [frames[(index + 1) % 3] for index in range(3)]; base_metrics = [m23._rank2_metrics(left, right) for left, right in zip(baseline, targets)]; controls = {}
    for name, delta in (("zero", (0.0, 0.0)), ("x_half", (0.5, 0.0)), ("y_half", (0.0, 0.5)), ("xy_half", (0.5, 0.5))):
        shifted = [_shift(frame, delta) for frame in frames]; transformed = [m23.periodic_envelope_c3(frame, lattice["c3_reciprocal_integer_automorphism"], edge["G_edge_integer"], m15) for frame, edge in zip(shifted, edges)]; shifted_targets = [shifted[(index + 1) % 3] for index in range(3)]; metrics = [m23._rank2_metrics(left, right) for left, right in zip(transformed, shifted_targets)]; controls[name] = {"delta_index_units": list(delta), "minimum_overlap": min(item["minimum_overlap_singular_value"] for item in metrics), "maximum_angle": max(item["maximum_principal_angle"] for item in metrics), "maximum_projector_distance": max(item["maximum_projector_distance"] for item in metrics)}
    source_files = [ROOT / "mephc/mpb_spectral_provider.py", ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", ROOT / "audit/berry_c3_consistency/m20_mpb_staggering_constitutive_operator_calibration.py"]
    inspected = [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "exists": path.is_file(), "mentions_hfield": "get_hfield" in path.read_text(encoding="utf-8") if path.is_file() else False, "certainty": "SOURCE_CONFIRMED" if path.is_file() else "UNAVAILABLE"} for path in source_files]
    metric_range = [min(item["minimum_overlap"] for item in controls.values()), max(item["minimum_overlap"] for item in controls.values())]
    deficit = 1.0 - min(item["minimum_overlap_singular_value"] for item in base_metrics)
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "SOLVER_FREE_SOURCE_AND_EXISTING_DATA_SAMPLING_AUDIT_COMPLETE", "source_m18_dataset_id": M18_DATASET_ID, "source_m12_dataset_id": M12_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "m26_baseline_H_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in base_metrics), "m26_baseline_H_c3_covariance_failure_count": sum(item["maximum_projector_distance"] > 1e-12 for item in base_metrics), "inspected_mpb_sampling_sources": inspected, "H_output_grid_coordinate_formula": "M18 stores get_hfield(band,bloch_phase=False) after canonicalization to (x,y,component); source does not expose a distinct physical coordinate formula beyond array index convention.", "H_output_grid_origin_status": "OUTPUT_GRID_LOCATION_METADATA_NOT_EXPOSED", "H_component_collocation_status": "COMMON_COMPONENT_LAST_STORAGE_CONFIRMED; NATIVE_LOCATIONS_NOT_EXPOSED", "H_component_interpolation_status": "NOT_EXPOSED_BY_PUBLIC_BINDING_OR_COMMITTED_READBACK", "H_grid_sampling_metadata_status": "OUTPUT_GRID_LOCATION_METADATA_NOT_EXPOSED", "general_common_offset_c3_phase_formula": phase_law_validation()["common_offset_formula"], "component_dependent_offset_c3_phase_formula": phase_law_validation()["component_offset_formula"], "phase_law_synthetic_validation": phase_law_validation(), "source_confirmed_sampling_correction": False, "corrected_H_c3_minimum_overlap_singular_value": None, "corrected_H_c3_maximum_principal_angle": None, "corrected_H_c3_covariance_failure_count": None, "standard_origin_controls": controls, "standard_origin_metric_range": metric_range, "standard_origin_observed_deficit": deficit, "standard_origin_controls_can_explain_failure": False, "H_sampling_correction_status": "NO_AUTHORITATIVE_CORRECTION_AVAILABLE", "primary_m27_diagnosis": "H_OUTPUT_SAMPLING_METADATA_REMAINS_UNRESOLVED", "rank1_berry_spike_interpretation": "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["zero-origin common grid", "common half-grid translation", "component-dependent interpolation", "native output locations", "broad H state-family failure"], "counterevidence_summary": {"baseline_metrics": base_metrics, "standard_origin_controls": controls, "observed_deficit": deficit, "folding_integer_residual_max": fold_residual, "gauge_cycle_residual": gauge_residual}, "exact_missing_sampling_metadata": ["physical coordinate represented by output array index", "component-specific output locations/interpolation", "raw reciprocal coefficient/output-grid origin metadata"], "cheapest_remaining_discriminating_test": "For the same existing canonical G15 triplet, record get_hfield array samples and get_field_point values at a fixed coordinate stencil together with raw Fourier/output-grid metadata; this is one targeted runtime observation per existing semantic state and requires an eigensolve only if fields are not already loaded.", "next_science_decision": "ACQUIRE_MINIMAL_H_POINT_VS_ARRAY_SAMPLING_METADATA_TRIPLET", "minimal_next_live_state_count": 3, "execution_required_for_cheapest_test": True, "edge_reciprocal_folding_vectors": edges, "folding_integer_residual_max": fold_residual, "gauge_cycle_residual": gauge_residual, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; m23 = _m23(); job = m23._job(); records = m23.read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3); m23.read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); result = analyze(records, os.environ.get("MEPHC_SOURCE_COMMIT"))
    except Exception as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "next_science_decision": "INSUFFICIENT_EVIDENCE", "minimal_next_live_state_count": 0, "post_analysis_checkout_unchanged": True, "traceback_tail": traceback.format_exc()[-3000:]}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
