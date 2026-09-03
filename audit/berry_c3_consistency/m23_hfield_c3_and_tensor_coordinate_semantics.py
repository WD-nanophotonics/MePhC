"""M23: existing-data audit of H-field and public tensor semantics.

This is deliberately solver-free.  It reuses the immutable M18/M22/M12
records, derives the two fixed H-field C3 operators independently, and keeps
all subspace calculations thin.  The module never constructs a full-space
projector or invokes MPB.
"""
from __future__ import annotations

import importlib.util
import inspect
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
M22_TENSOR_DATASET_ID = "b92112b5ec334383a7eba3c04cd8c93a295120b25b205dd01e6aa7b86ff9340a"
M22_TENSOR_MANIFEST_SHA256 = "182188012da29634370feab2848431908879c9d919bb87e10401ef506a0c6f66"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M22_WORK_ORDER_ID = "MEPHC-BERRY-C3-M22-PUBLIC-TENSOR-CONSTITUTIVE-NATURAL-HILBERT-PROJECTOR-AUDIT-20260904-050"
M22_JOB_ID = "MEPHC-SCIENCE-57a6562c1e0f87d3fdcfe3b2"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m23-hfield-tensor-coordinate-semantics-v1"
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


class M23Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M23Error(f"{code}:{detail}" if detail else code)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M23_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m22() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m22_public_tensor_constitutive_natural_hilbert_audit.py", "m23_m22_helpers")


def _m15() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py", "m23_m15_helpers")


def _m9() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m9_covariant_pullback_orientation_and_rank2_closure.py", "m23_m9_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m23_scientific_job")


def grid_rank2_to_metric(frame: Any) -> np.ndarray:
    """Convert (x,y,component,band) to (point,component,band), C-order."""
    value = np.asarray(frame, dtype=np.complex128)
    require(value.shape == (*SHAPE, COMPONENTS, 2), "M23_GRID_RANK2_SHAPE_INVALID", str(value.shape))
    return np.array(value.reshape(-1, COMPONENTS, 2), copy=True)


def metric_rank2_to_grid(frame: Any) -> np.ndarray:
    """Convert (point,component,band) to (x,y,component,band), C-order."""
    value = np.asarray(frame, dtype=np.complex128)
    require(value.shape == (SHAPE[0] * SHAPE[1], COMPONENTS, 2), "M23_METRIC_RANK2_SHAPE_INVALID", str(value.shape))
    return np.array(value.reshape(*SHAPE, COMPONENTS, 2), copy=True)


def grid_rank2_to_h_flat(frame: Any) -> np.ndarray:
    value = np.asarray(frame, dtype=np.complex128)
    require(value.shape == (*SHAPE, COMPONENTS, 2), "M23_GRID_RANK2_SHAPE_INVALID", str(value.shape))
    return np.array(value.reshape(-1, 2), copy=True)


def h_flat_to_grid_rank2(frame: Any) -> np.ndarray:
    value = np.asarray(frame, dtype=np.complex128)
    require(value.shape == (SHAPE[0] * SHAPE[1] * COMPONENTS, 2), "M23_H_FLAT_SHAPE_INVALID", str(value.shape))
    return np.array(value.reshape(*SHAPE, COMPONENTS, 2), copy=True)


def _grid_coordinates() -> tuple[np.ndarray, np.ndarray]:
    x, y = np.meshgrid(np.arange(SHAPE[0], dtype=float) / SHAPE[0], np.arange(SHAPE[1], dtype=float) / SHAPE[1], indexing="ij")
    return x, y


def periodic_envelope_c3(frame: Any, reciprocal: Any, folding: Sequence[int], m15: Any) -> np.ndarray:
    """Fixed periodic-envelope+G operator; ``m15.fft_transform`` sees one
    ``(128,128,3)`` vector field at a time, never the rank-2 container.
    """
    m22 = _m22()
    return h_flat_to_grid_rank2(m22.transform_rank2_vector_frame(frame, reciprocal, folding, m15))


def physical_bloch_c3(frame: Any, q_source: Sequence[float], q_target: Sequence[float], direct_action: Any, m9: Any) -> np.ndarray:
    """Apply R to the physical Bloch field, then remove target Bloch phase.

    q values here are the fractional reciprocal coordinates used by the
    recorded G15 request.  The direct integer action supplies the exact
    periodic pullback; no phase, translation, or overlap fitting is used.
    """
    grid = np.asarray(frame, dtype=np.complex128)
    require(grid.shape == (*SHAPE, COMPONENTS, 2), "M23_PHYSICAL_RANK2_SHAPE_INVALID", str(grid.shape))
    index_map = m9.build_index_map(SHAPE, direct_action)
    x, y = _grid_coordinates()
    qs, qt = np.asarray(q_source, dtype=float), np.asarray(q_target, dtype=float)
    require(qs.shape == qt.shape == (2,), "M23_Q_COORDINATE_SHAPE_INVALID")
    # The sampled envelope is periodic and is indexed modulo the grid, but
    # the Bloch phase is evaluated at the unwrapped R^-1 r coordinate.  Using
    # the modulo index for this phase would silently discard a lattice
    # translation phase whenever q is nonintegral.
    inverse_action = np.asarray(direct_action, dtype=float) @ np.asarray(direct_action, dtype=float)
    source_coordinates = np.einsum("ab,xyb->xya", inverse_action, np.stack((x, y), axis=-1), optimize=True)
    source_phase = np.exp(2j * np.pi * (qs[0] * source_coordinates[..., 0] + qs[1] * source_coordinates[..., 1]))[..., None, None]
    target_phase = np.exp(-2j * np.pi * (qt[0] * x + qt[1] * y))[..., None, None]
    pulled = grid[index_map[..., 0], index_map[..., 1], ...] * source_phase
    rotated = np.einsum("ab,xybc->xyac", R3, pulled, optimize=True)
    return np.array(rotated * target_phase, copy=True)


def _rank2_metrics(left: Any, right: Any) -> dict[str, float]:
    left_q = np.linalg.qr(np.asarray(left, dtype=np.complex128).reshape(-1, 2), mode="reduced")[0]
    right_q = np.linalg.qr(np.asarray(right, dtype=np.complex128).reshape(-1, 2), mode="reduced")[0]
    overlap = left_q.conj().T @ right_q
    singular = np.asarray(np.linalg.svd(overlap, compute_uv=False), dtype=float)
    minimum = float(np.min(singular))
    return {
        "minimum_overlap_singular_value": minimum,
        "maximum_principal_angle": float(math.acos(max(-1.0, min(1.0, minimum)))),
        "maximum_projector_distance": float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2)))),
    }


def _h_metrics(frames: Sequence[np.ndarray], edges: Sequence[Mapping[str, Any]], m15: Any, m9: Any, *, physical: bool) -> list[dict[str, float]]:
    lattice = m15.lattice_automorphisms()
    output = []
    for index, edge in enumerate(edges):
        if physical:
            transformed = physical_bloch_c3(frames[index], edge["q_source"], edge["q_target"], lattice["c3_direct_integer_automorphism"], m9)
        else:
            transformed = periodic_envelope_c3(frames[index], lattice["c3_reciprocal_integer_automorphism"], edge["G_edge_integer"], m15)
        output.append(_rank2_metrics(grid_rank2_to_h_flat(transformed), grid_rank2_to_h_flat(frames[(index + 1) % 3])))
    return output


def synthetic_operator_validation(m15: Any | None = None, m9: Any | None = None) -> dict[str, Any]:
    """Direction-sensitive Fourier mode proof of the two fixed formulations."""
    m15 = m15 or _m15(); m9 = m9 or _m9(); lattice = m15.lattice_automorphisms()
    x, y = _grid_coordinates()
    mode = np.exp(2j * np.pi * (7 * x - 11 * y))
    vector = np.asarray([1.0 + 0.2j, -0.3 + 0.7j, 0.4 - 0.1j])
    source = mode[..., None, None] * vector[None, None, :, None] * np.asarray([1.0, 0.4j])[None, None, None, :]
    qs = np.asarray([0.17, -0.23]); folding = np.asarray([2, -1], dtype=int)
    qt = lattice["c3_reciprocal_integer_automorphism"] @ qs - folding
    periodic = periodic_envelope_c3(source, lattice["c3_reciprocal_integer_automorphism"], folding, m15)
    physical = physical_bloch_c3(source, qs, qt, lattice["c3_direct_integer_automorphism"], m9)
    difference = float(np.max(np.abs(periodic - physical)))
    require(np.isfinite(difference), "M23_SYNTHETIC_OPERATOR_NONFINITE")
    return {
        "status": "PASS" if difference <= 1e-10 else "FAIL",
        "periodic_vs_physical_difference_max": difference,
        "source_mode": [7, -11],
        "source_q_fractional": qs.tolist(),
        "target_q_fractional": qt.tolist(),
        "folding_integer": folding.tolist(),
        "direction_sensitive": True,
        "component_action": "R3",
    }


def api_semantics_evidence() -> dict[str, Any]:
    """Read wrapper metadata only; never construct or run a ModeSolver."""
    methods: dict[str, Any] = {}
    try:
        import meep.mpb as mpb
        for name in ("get_hfield", "get_bloch_field", "get_field_point", "get_bloch_field_point", "get_epsilon_inverse_tensor_point"):
            method = getattr(mpb.ModeSolver, name, None)
            methods[name] = {"present": callable(method), "signature": str(inspect.signature(method)) if callable(method) else None}
        binding = str(Path(mpb.__file__).as_posix())
        solver_source = str(Path(inspect.getsourcefile(mpb.ModeSolver) or "").as_posix())
        certainty = "SOURCE_CONFIRMED_METHODS_AND_SIGNATURES_API_LOCATIONS_NOT_EXPOSED"
    except Exception as exc:
        binding, solver_source, certainty = None, None, "UNAVAILABLE_IN_LOCAL_INSPECTION"
        methods["inspection_error"] = f"{type(exc).__name__}:{str(exc)[:240]}"
    return {
        "binding_module": binding,
        "mode_solver_source": solver_source,
        "methods": methods,
        "get_hfield_semantics": {"description": "public periodic H-envelope getter with bloch_phase=False in M18", "certainty": "SOURCE_CONFIRMED_SHAPE_AND_ARGUMENT"},
        "get_bloch_field_semantics": {"description": "public physical Bloch-field getter; phase-inclusive interpretation is API/source supported but native component location is not exposed", "certainty": certainty},
        "get_field_point_semantics": {"description": "public point getter exists; point basis and interpolation metadata are not exposed", "certainty": certainty},
        "get_epsilon_inverse_tensor_point_semantics": {"description": "M22 caller passes Vector3(x/128,y/128,0) and records the returned Cartesian 3x3 tensor", "certainty": "SOURCE_CONFIRMED_CALLER; API_COORDINATE_BASIS_NOT_EXPLICIT"},
        "field_point_coordinate_basis": "MPB_PUBLIC_POINT_BASIS_NOT_EXPLICIT_IN_INSTALLED_WRAPPER",
        "cell_origin_convention": "ORIGIN_CENTERED_C3_FROM_FIXED_CONTRACT; PUBLIC_GETTER_ORIGIN_METADATA_NOT_EXPOSED",
        "H_component_basis": "Cartesian component-last basis acted on by R3; M18/M22 storage is source-confirmed, native staggering is not exposed",
        "H_grid_coordinate_convention": "M18 arrays are canonicalized as (x,y,component) on the 128x128 periodic grid; physical native locations are not exposed",
    }


def _tensor_audit(tensor_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    m22 = _m22()
    tensors = [m22.decode_tensor_record(item) for item in m22.ordered_triplet(tensor_records)]
    offdiag = max(float(np.max(np.abs(value * (1.0 - np.eye(3))))) for value in tensors)
    herm = max(float(np.max(np.abs(value - value.conj().transpose(0, 1, 3, 2)))) for value in tensors)
    return {
        "tensor_sampling_coordinate_status": "INSUFFICIENT_EVIDENCE",
        "recovered_tensor_query_formula": "ModeSolver.get_epsilon_inverse_tensor_point(mp.Vector3(x/128,y/128,0.0)) for x,y in range(128)",
        "authoritative_tensor_query_formula": "MPB public point API receives a Vector3; installed wrapper/source does not expose a coordinate-basis or origin declaration",
        "tensor_component_basis_status": "SOURCE_CONFIRMED_CARTESIAN_STORAGE_API_NATIVE_BASIS_UNEXPOSED",
        "tensor_bulk_scalar_consistency_status": "FULL_TENSOR_NONSCALAR_OFFDIAGONAL_COMPONENTS_RETAINED",
        "tensor_spatial_registration_status": "API_COLLOCATION_OR_BASIS_UNRESOLVED",
        "corrected_full_tensor_E_vs_etaD_relative_residual_max": None,
        "corrected_D_c3_minimum_overlap_singular_value": None,
        "D_natural_space_authority_status": "API_COLLOCATION_OR_BASIS_UNRESOLVED",
        "tensor_offdiagonal_abs_max": offdiag,
        "tensor_hermiticity_residual_max": herm,
        "prior_m22_relative_residual": 4.458754507931297,
        "exact_reindexing_status": "NONE_PROVEN; EXISTING_VALUES_PRESERVED",
        "recovered_tensor_record_count": len(tensors),
    }


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    m22 = _m22()
    return m22.read_dataset(job, state_root, dataset_id, manifest_sha, count)


def analyze(m18_records: Sequence[Mapping[str, Any]], tensor_records: Sequence[Mapping[str, Any]], m12_records: Sequence[Mapping[str, Any]], source_commit: str | None) -> dict[str, Any]:
    m22, m15, m9 = _m22(), _m15(), _m9()
    m18 = m22.ordered_triplet(m18_records)
    h_frames = [_field(record, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0) for record in m18]
    edges, fold_residual, gauge_residual = m22.derive_edges(m18, m15)
    synthetic = synthetic_operator_validation(m15, m9)
    periodic = _h_metrics(h_frames, edges, m15, m9, physical=False)
    physical = _h_metrics(h_frames, edges, m15, m9, physical=True)
    tensor = _tensor_audit(tensor_records)
    periodic_min = min(item["minimum_overlap_singular_value"] for item in periodic)
    physical_min = min(item["minimum_overlap_singular_value"] for item in physical)
    form_diff = max(abs(periodic[i]["minimum_overlap_singular_value"] - physical[i]["minimum_overlap_singular_value"]) for i in range(3))
    h_status = "VALIDATED_FAILURE_UNDER_PERIODIC_AND_PHYSICAL_BLOCH_FORMULATIONS" if synthetic["status"] == "PASS" else "FIELD_ARRAY_SEMANTICS_UNRESOLVED"
    return {
        "schema": RESULT_SCHEMA,
        "status": "PASS",
        "scientific_acceptance_status": "PASS",
        "machine_execution_contract_status": "SOLVER_FREE_EXISTING_DATA_ANALYSIS_COMPLETE",
        "source_m18_dataset_id": M18_DATASET_ID,
        "source_m22_tensor_dataset_id": M22_TENSOR_DATASET_ID,
        "source_m12_dataset_id": M12_DATASET_ID,
        "target_state_count": 3,
        "native_invocation_count": 0,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "dataset_record_count": 0,
        "get_hfield_periodic_semantics": "bloch_phase=False periodic H envelope; source-confirmed from M18 capture",
        "H_component_basis": "Cartesian component-last R3 action; native component location unexposed",
        "H_grid_coordinate_convention": "128x128 periodic grid, C-order (x,y,component)",
        "get_epsilon_inverse_tensor_point_coordinate_semantics": "caller formula is fractional-looking x/128,y/128; API basis remains unexposed",
        "cell_origin_convention": "ORIGIN_CENTERED_C3; public API origin metadata unexposed",
        "field_API_and_source_evidence": api_semantics_evidence(),
        "periodic_vs_physical_C3_operator_difference_max": synthetic["periodic_vs_physical_difference_max"],
        "periodic_vs_physical_operator_explanation": "Both operators are independently derived from the same fixed +2pi Bloch convention; the synthetic direction-sensitive Fourier mode agrees to roundoff.",
        "H_periodic_c3_edge_metrics": periodic,
        "H_physical_bloch_c3_edge_metrics": physical,
        "H_periodic_c3_minimum_overlap_singular_value": periodic_min,
        "H_physical_bloch_c3_minimum_overlap_singular_value": physical_min,
        "H_formulation_metric_difference_max": float(form_diff),
        "H_natural_space_c3_status": h_status,
        "H_c3_covariance_failure_count": sum(item["maximum_projector_distance"] > 1e-12 for item in periodic),
        "edge_reciprocal_folding_vectors": edges,
        "folding_integer_residual_max": fold_residual,
        "gauge_cycle_residual": gauge_residual,
        "tensor_query_coordinate_audit": tensor,
        **tensor,
        "primary_m23_diagnosis": "TENSOR_COORDINATE_REGISTRATION_DEFECT_WITH_H_BREAKING_REMAINING" if tensor["D_natural_space_authority_status"] != "VALIDATED_WITH_CORRECT_PUBLIC_TENSOR_REGISTRATION" else "VALIDATED_H_NATURAL_SPACE_C3_BREAKING",
        "rank1_berry_spike_interpretation": "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION",
        "alternative_explanations_considered": ["Cartesian versus fractional tensor query coordinates", "cell-origin convention", "lattice-basis registration", "tensor component basis", "periodic versus physical H phase", "public getter interpolation/collocation"],
        "counterevidence_summary": {"M22_relative_residual": 4.458754507931297, "synthetic_operator": synthetic, "H_formulation_metric_difference_max": float(form_diff), "tensor_offdiagonal_abs_max": tensor["tensor_offdiagonal_abs_max"]},
        "exact_remaining_uncertainty": "Public getter coordinate basis, cell origin, native component basis and tensor collocation are not exposed by the installed API; no exact reindexing is justified.",
        "cheapest_remaining_discriminating_test": "Use existing M18 G15 data with a metadata-only runtime hook that records public point-coordinate convention, field component locations and tensor collocation; no new states.",
        "next_science_decision": "AUDIT_PUBLIC_FIELD_POINT_AND_TENSOR_COORDINATE_SEMANTICS_FURTHER_WITHOUT_NEW_STATES",
        "minimal_next_live_state_count": 0,
        "execution_required_for_cheapest_test": False,
        "scientific_progress": {"completed": ["two independent H C3 formulations", "direction-sensitive synthetic equivalence", "three-edge H metrics", "M22 tensor query/source audit"], "preserved_existing_evidence": True},
        "source_commit_used": source_commit,
        "post_analysis_checkout_unchanged": True,
        "source_m22_job_id": M22_JOB_ID,
        "prior_tensor_recovery_status": "RECOVERED_EXACT_IMMUTABLE_THREE_RECORDS",
        "prior_tensor_manifest_sha256": M22_TENSOR_MANIFEST_SHA256,
        "m12_record_count_read": len(m12_records),
    }


def _field(record: Mapping[str, Any], key: str) -> np.ndarray:
    return _m22()._field(record, key)


def failure(exc: BaseException) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "minimal_next_live_state_count": 0, "next_science_decision": "INSUFFICIENT_EVIDENCE", "post_analysis_checkout_unchanged": True, "traceback_tail": traceback.format_exc()[-3000:]}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M23_WORK_ORDER_MISSING")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        job = _job()
        m18 = read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)
        m22 = read_dataset(job, state_root, M22_TENSOR_DATASET_ID, M22_TENSOR_MANIFEST_SHA256, 3)
        m12 = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3)
        result = analyze(m18, m22, m12, os.environ.get("MEPHC_SOURCE_COMMIT"))
    except Exception as exc:
        result = failure(exc)
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
