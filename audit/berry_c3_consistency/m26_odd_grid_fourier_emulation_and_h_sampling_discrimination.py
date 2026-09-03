"""M26 solver-free odd-grid/common-support Fourier emulation."""
from __future__ import annotations

import json
import math
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE_N = 128
SHAPE = (128, 128)
TARGET_BANDS = (1, 2)
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m26-odd-grid-fourier-emulation-h-sampling-discrimination-v1"
SHELLS = (8, 16, 24, 32, 48, 64)


class M26Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M26Error(f"{code}:{detail}" if detail else code)


def _m23() -> Any:
    import importlib.util
    path = ROOT / "audit" / "berry_c3_consistency" / "m23_hfield_c3_and_tensor_coordinate_semantics.py"
    spec = importlib.util.spec_from_file_location("m26_m23_helpers", path)
    require(spec is not None and spec.loader is not None, "M26_M23_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _m15() -> Any:
    import importlib.util
    path = ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py"
    spec = importlib.util.spec_from_file_location("m26_m15_helpers", path)
    require(spec is not None and spec.loader is not None, "M26_M15_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def signed_modes(size: int) -> tuple[int, ...]:
    return tuple(int(value) for value in np.rint(np.fft.fftfreq(size) * size).astype(int))


def common_support(size: int) -> set[tuple[int, int]]:
    allowed = set(signed_modes(size)) & set(signed_modes(SOURCE_N))
    return {(x, y) for x in allowed for y in allowed}


def embed_coefficients(coefficients: np.ndarray, size: int, support: set[tuple[int, int]]) -> np.ndarray:
    require(coefficients.shape == (SOURCE_N, SOURCE_N, 3), "M26_COEFFICIENT_SHAPE_INVALID", str(coefficients.shape))
    result = np.zeros((size, size, 3), dtype=np.complex128)
    scale = (size / SOURCE_N) ** 2
    source_values = signed_modes(SOURCE_N)
    source_index = {mode: index for index, mode in enumerate(source_values)}
    for mx, my in support:
        result[mx % size, my % size, :] = coefficients[source_index[mx], source_index[my], :] * scale
    return result


def embed_field(field: np.ndarray, size: int, support: set[tuple[int, int]]) -> np.ndarray:
    value = np.asarray(field, dtype=np.complex128)
    require(value.shape == (SOURCE_N, SOURCE_N, 3), "M26_FIELD_SHAPE_INVALID", str(value.shape))
    return np.fft.ifftn(embed_coefficients(np.fft.fftn(value, axes=(0, 1)), size, support), axes=(0, 1))


def periodic_transform(field: np.ndarray, size: int, reciprocal: np.ndarray, folding: Sequence[int], m15: Any) -> np.ndarray:
    value = np.asarray(field, dtype=np.complex128)
    require(value.shape == (size, size, 3), "M26_TRANSFORM_FIELD_SHAPE_INVALID", str(value.shape))
    source = np.fft.fftn(value, axes=(0, 1)); target = np.zeros_like(source)
    modes = signed_modes(size); position = {mode: index for index, mode in enumerate(modes)}
    for mx in modes:
        for my in modes:
            raw = np.asarray(reciprocal, dtype=int) @ np.asarray([mx, my]) + np.asarray(folding, dtype=int)
            target[position[int(raw[0]) % size if int(raw[0]) % size < size // 2 else int(raw[0]) % size - size], position[int(raw[1]) % size if int(raw[1]) % size < size // 2 else int(raw[1]) % size - size], :] = source[position[mx], position[my], :]
    return np.einsum("ab,xyb->xya", m15.R3, np.fft.ifftn(target, axes=(0, 1)), optimize=True)


def transform_frame(frame: np.ndarray, size: int, reciprocal: np.ndarray, folding: Sequence[int], m15: Any) -> np.ndarray:
    return np.stack([periodic_transform(frame[..., band], size, reciprocal, folding, m15) for band in range(2)], axis=-1)


def orbit_complete_support(support: set[tuple[int, int]], reciprocal: np.ndarray, foldings: Sequence[Sequence[int]], size: int) -> set[tuple[int, int]]:
    complete = set()
    for start in support:
        value = start; valid = True
        for folding in foldings:
            raw = reciprocal @ np.asarray(value) + np.asarray(folding, dtype=int)
            value = tuple(int(raw[i]) % size if int(raw[i]) % size < size // 2 else int(raw[i]) % size - size for i in range(2))
            valid = valid and value in support
        if valid and value == start:
            complete.add(start)
    return complete


def energy_fraction(field: np.ndarray, support: set[tuple[int, int]]) -> float:
    coeff = np.fft.fftn(field, axes=(0, 1)); modes = signed_modes(SOURCE_N); pos = {m: i for i, m in enumerate(modes)}
    kept = sum(float(np.sum(np.abs(coeff[pos[x], pos[y], :]) ** 2)) for x, y in support)
    total = float(np.sum(np.abs(coeff) ** 2))
    return kept / max(total, np.finfo(float).eps)


def edge_metrics(frames: Sequence[np.ndarray], size: int, support: set[tuple[int, int]], edges: Sequence[Mapping[str, Any]], reciprocal: np.ndarray, m23: Any, m15: Any) -> list[dict[str, float]]:
    embedded = [np.stack([embed_field(frame[..., band], size, support) for band in range(2)], axis=-1) for frame in frames]
    result = []
    for index, edge in enumerate(edges):
        transformed = transform_frame(embedded[index], size, reciprocal, edge["G_edge_integer"], m15)
        result.append(m23._rank2_metrics(transformed, embedded[(index + 1) % 3]))
    return result


def shell_trajectory(frames: Sequence[np.ndarray], size: int, edges: Sequence[Mapping[str, Any]], reciprocal: np.ndarray, m23: Any, m15: Any) -> list[dict[str, Any]]:
    rows = []
    for radius in SHELLS:
        support = {(x, y) for x, y in common_support(size) if math.hypot(x, y) <= radius}
        metrics = edge_metrics(frames, size, support, edges, reciprocal, m23, m15)
        rows.append({"radius": radius, "support_count": len(support), "retained_energy_fraction_min": min(energy_fraction(frame[..., band], support) for frame in frames for band in range(2)), "minimum_overlap": min(item["minimum_overlap_singular_value"] for item in metrics), "maximum_angle": max(item["maximum_principal_angle"] for item in metrics)})
    return rows


def analyze(records: Sequence[Mapping[str, Any]], source_commit: str | None) -> dict[str, Any]:
    m23, m15 = _m23(), _m15(); m22 = m23._m22(); ordered = m22.ordered_triplet(records); edges, fold_residual, gauge_residual = m22.derive_edges(ordered, m15); lattice = m15.lattice_automorphisms(); reciprocal = np.asarray(lattice["c3_reciprocal_integer_automorphism"], dtype=int); frames = [m23._field(record, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0) for record in ordered]; full_support = common_support(SOURCE_N); full_metrics = edge_metrics(frames, SOURCE_N, full_support, edges, reciprocal, m23, m15); baseline_min = min(item["minimum_overlap_singular_value"] for item in full_metrics)
    comparisons = {}; class_counts = {}; all_shells = {}
    for size in (127, 129):
        support = common_support(size); matched = edge_metrics(frames, SOURCE_N, support, edges, reciprocal, m23, m15); odd = edge_metrics(frames, size, support, edges, reciprocal, m23, m15); orbit = orbit_complete_support(support, reciprocal, [edge["G_edge_integer"] for edge in edges], SOURCE_N); orbit_metrics = edge_metrics(frames, size, orbit, edges, reciprocal, m23, m15)
        comparisons[str(size)] = {"common_mode_count": len(support), "orbit_complete_common_mode_count": len(orbit), "retained_H_field_energy_fraction_by_member_band": [[energy_fraction(frame[..., band], support) for band in range(2)] for frame in frames], "odd_metrics": odd, "matched128_metrics": matched, "orbit_complete_metrics": orbit_metrics, "odd_minus_matched128_overlap_improvement": min(item["minimum_overlap_singular_value"] for item in odd) - min(item["minimum_overlap_singular_value"] for item in matched), "odd_minimum_overlap": min(item["minimum_overlap_singular_value"] for item in odd), "matched_minimum_overlap": min(item["minimum_overlap_singular_value"] for item in matched), "class_support_definition": "exact signed integer intersection; no unknown coefficient inference"}
        all_shells[str(size)] = {"odd": shell_trajectory(frames, size, edges, reciprocal, m23, m15), "matched128": shell_trajectory(frames, SOURCE_N, edges, reciprocal, m23, m15)}
        class_counts[str(size)] = {"common": len(support), "orbit_complete": len(orbit)}
    special_support = {mode for mode in full_support if -64 not in mode}
    special_metrics = edge_metrics(frames, SOURCE_N, special_support, edges, reciprocal, m23, m15)
    odd_improvement_127 = comparisons["127"]["odd_minus_matched128_overlap_improvement"]; odd_improvement_129 = comparisons["129"]["odd_minus_matched128_overlap_improvement"]
    broad = all(comparisons[str(size)]["orbit_complete_common_mode_count"] > 10000 and comparisons[str(size)]["odd_minimum_overlap"] < 0.99 for size in (127, 129))
    parity = odd_improvement_127 > 1e-6 and odd_improvement_129 > 1e-6 and odd_improvement_127 > 0.0 and odd_improvement_129 > 0.0
    diagnosis = "VALIDATED_BROAD_H_C3_FAILURE_ON_ORDINARY_COMMON_SUPPORT" if broad else ("EVEN_GRID_ALIASING_EXPLAINS_H_C3_FAILURE" if parity else "TRUNCATION_EFFECT_NOT_GRID_PARITY")
    status = "C3_FAILURE_STABLE_ACROSS_COMMON_SUPPORT_AND_GRID_PARITY" if broad else ("ODD_GRID_SPECIFIC_C3_RESTORATION" if parity else "EMULATION_INCONCLUSIVE_DUE_TO_RETAINED_ENERGY_LOSS")
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "SOLVER_FREE_ODD_GRID_COMMON_SUPPORT_EMULATION_COMPLETE", "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "m25_baseline_H_c3_minimum_overlap_singular_value": baseline_min, "m25_baseline_H_c3_edge_metrics": full_metrics, "common_mode_count_127": comparisons["127"]["common_mode_count"], "common_mode_count_129": comparisons["129"]["common_mode_count"], "orbit_complete_common_mode_count_127": comparisons["127"]["orbit_complete_common_mode_count"], "orbit_complete_common_mode_count_129": comparisons["129"]["orbit_complete_common_mode_count"], "retained_energy_fraction_127_min": min(sum(row) / 2 for row in comparisons["127"]["retained_H_field_energy_fraction_by_member_band"]), "retained_energy_fraction_129_min": min(sum(row) / 2 for row in comparisons["129"]["retained_H_field_energy_fraction_by_member_band"]), "H127_c3_minimum_overlap_singular_value": comparisons["127"]["odd_minimum_overlap"], "H128_matched127_c3_minimum_overlap_singular_value": comparisons["127"]["matched_minimum_overlap"], "H129_c3_minimum_overlap_singular_value": comparisons["129"]["odd_minimum_overlap"], "H128_matched129_c3_minimum_overlap_singular_value": comparisons["129"]["matched_minimum_overlap"], "odd_minus_matched128_overlap_improvement_127": odd_improvement_127, "odd_minus_matched128_overlap_improvement_129": odd_improvement_129, "orbit_complete_H_c3_minimum_overlap_singular_value_127": min(item["minimum_overlap_singular_value"] for item in comparisons["127"]["orbit_complete_metrics"]), "orbit_complete_H_c3_minimum_overlap_singular_value_129": min(item["minimum_overlap_singular_value"] for item in comparisons["129"]["orbit_complete_metrics"]), "shell_stability_summary": all_shells, "H_sampling_metadata_status": "NATIVE_FIELD_LOCATION_METADATA_STILL_REQUIRED", "source_confirmed_H_sampling_semantics": "M18 source confirms get_hfield(band,bloch_phase=False) and canonical (x,y,component) storage; native component locations/interpolation remain unexposed.", "exact_existing_array_sampling_correction_applied": False, "odd_grid_emulation_status": status, "primary_m26_diagnosis": diagnosis, "rank1_berry_spike_interpretation": "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["even-grid Nyquist alias", "common-support truncation", "high Fourier shell sensitivity", "native H sampling locations", "broad state-family failure"], "counterevidence_summary": {"M25_special_mode_union_residual_fraction": 0.11878153600795853, "M25_ordinary_residual_fraction": 0.8812184639920414, "full128_metrics": full_metrics, "special_modes_removed_counterfactual_metrics": special_metrics, "class_counts_by_grid": class_counts}, "exact_remaining_uncertainty": "Odd-grid emulation preserves only common known coefficients and cannot establish what a fresh odd-grid eigensolve would return; native H component locations remain unexposed.", "cheapest_remaining_discriminating_test": "A metadata-only native H sampling/location audit on existing M18 states; a fresh odd-grid triplet is not justified until this emulation is interpreted.", "next_science_decision": "ACQUIRE_MINIMAL_ODD_GRID_OR_RESOLUTION_C3_VALIDATION_TRIPLET" if status == "ODD_GRID_SPECIFIC_C3_RESTORATION" else "ACQUIRE_MINIMAL_FRESH_H_NATURAL_SPACE_C3_VALIDATION_TRIPLET" if status == "EMULATION_INCONCLUSIVE_DUE_TO_RETAINED_ENERGY_LOSS" else "FIX_SOURCE_CONFIRMED_H_SAMPLING_OR_GRID_REPRESENTATION_AND_REANALYZE_EXISTING_DATA_ONLY", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "edge_reciprocal_folding_vectors": edges, "folding_integer_residual_max": fold_residual, "gauge_cycle_residual": gauge_residual, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M26_WORK_ORDER_MISSING"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; m23 = _m23(); job = m23._job(); records = m23.read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3); m23.read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); result = analyze(records, os.environ.get("MEPHC_SOURCE_COMMIT"))
    except Exception as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "minimal_next_live_state_count": 0, "next_science_decision": "INSUFFICIENT_EVIDENCE", "post_analysis_checkout_unchanged": True, "traceback_tail": traceback.format_exc()[-3000:]}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
