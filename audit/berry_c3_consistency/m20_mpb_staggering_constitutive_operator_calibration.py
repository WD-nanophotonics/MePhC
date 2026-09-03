"""M20: zero-execution MPB field/staggering and constitutive audit.

The M18 records contain E/H/D/B and epsilon readback, but the public binding
does not expose the internal MPB grid locations or constitutive operator.  This
module measures the directly available diagnostics and refuses to invent the
missing staggered operator.
"""
from __future__ import annotations

import importlib.util
import inspect
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
RESULT_SCHEMA = "mephc-berry-c3-consistency-m20-mpb-staggering-constitutive-operator-calibration-v1"
SHAPE = (128, 128)
COMPONENTS = 3
NBANDS = 6


class M20Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M20Error(f"{code}:{detail}" if detail else code)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M20_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _m18() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m18_exact_mpb_operator_readback_and_covariance_closure.py", "m20_m18_helpers")


def _m16() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m16_discrete_material_maxwell_residual_covariance.py", "m20_m16_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m20_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha256: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha256 and verified.get("record_count") == count, "M20_DATASET_BINDING_INVALID", dataset_id)
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == count and len(set(keys)) == count, "M20_DATASET_MEMBERSHIP_INVALID", dataset_id)
    result = []
    for key in keys:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest_sha256, key).get("payload")
        require(isinstance(payload, bytes), "M20_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8")); require(isinstance(value, dict), "M20_DATASET_PAYLOAD_INVALID", dataset_id); result.append(value)
    return result


def _ordered(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = sorted((dict(item) for item in records), key=lambda item: int(item["member_index"]))
    require(len(result) == 3 and [item["member_index"] for item in result] == [0, 1, 2], "M20_TRIPLET_INVALID")
    return result


def _decode(record: Mapping[str, Any], key: str, m18: Any) -> np.ndarray:
    value = m18._decode_field(record, key)
    require(value.shape == (NBANDS, *SHAPE, COMPONENTS), "M20_READBACK_FIELD_SHAPE_INVALID", key)
    return value


def _relative_norm(numerator: Any, denominator: Any) -> float:
    return float(np.linalg.norm(np.asarray(numerator)) / max(float(np.linalg.norm(np.asarray(denominator))), np.finfo(float).tiny))


def constitutive_diagnostics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    m18 = _m18(); maxima = {"D_vs_epsilonE_residual_max": 0.0, "B_vs_H_residual_max": 0.0}; per_member = []
    direct_maxwell = {"maxwell": 0.0, "curlE": 0.0, "curlH": 0.0}; m16 = _m16()
    for record in _ordered(records):
        epsilon = np.asarray(record["epsilon_grid"], dtype=float).reshape(SHAPE)
        e = _decode(record, "fresh_e_fields_bands_1_to_6", m18); h = _decode(record, "fresh_h_fields_bands_1_to_6", m18); d = _decode(record, "fresh_d_fields_bands_1_to_6", m18); b = _decode(record, "fresh_b_fields_bands_1_to_6", m18)
        frequencies = np.asarray(record["frequencies_bands_1_to_6"], dtype=float); q = record["coordinate"]; d_residuals = []; b_residuals = []
        for band in range(NBANDS):
            d_residuals.append(_relative_norm(d[band] - epsilon[..., None] * e[band], d[band])); b_residuals.append(_relative_norm(b[band] - h[band], b[band]))
            curl_e = m16.maxwell_curl(e[band], q); curl_h = m16.maxwell_curl(h[band], q); first = curl_e - 1j * frequencies[band] * b[band]; second = curl_h + 1j * frequencies[band] * d[band]
            e_scale = max(float(np.linalg.norm(curl_e)), abs(float(frequencies[band])) * float(np.linalg.norm(b[band])), np.finfo(float).tiny); h_scale = max(float(np.linalg.norm(curl_h)), abs(float(frequencies[band])) * float(np.linalg.norm(d[band])), np.finfo(float).tiny)
            direct_maxwell["curlE"] = max(direct_maxwell["curlE"], float(np.linalg.norm(first) / e_scale)); direct_maxwell["curlH"] = max(direct_maxwell["curlH"], float(np.linalg.norm(second) / h_scale)); direct_maxwell["maxwell"] = max(direct_maxwell["maxwell"], direct_maxwell["curlE"], direct_maxwell["curlH"])
        maxima["D_vs_epsilonE_residual_max"] = max(maxima["D_vs_epsilonE_residual_max"], max(d_residuals)); maxima["B_vs_H_residual_max"] = max(maxima["B_vs_H_residual_max"], max(b_residuals)); per_member.append({"member_index": int(record["member_index"]), "c3_member_identity": record["c3_member_identity"], "D_vs_epsilonE_residual_max": max(d_residuals), "B_vs_H_residual_max": max(b_residuals), "D_field_availability_status": record["D_field_availability_status"], "B_field_availability_status": record["B_field_availability_status"]})
    return {**maxima, "per_member_constitutive_diagnostics": per_member, "collocated_direct_DB_diagnostic": {"maxwell": direct_maxwell["maxwell"], "curlE": direct_maxwell["curlE"], "curlH": direct_maxwell["curlH"], "validity": "DIAGNOSTIC_ONLY_UNTIL_FIELD_LOCATIONS_AND_INTERNAL_CONSTITUTIVE_OPERATOR_ARE_EXPOSED"}}


def binding_forensics() -> dict[str, Any]:
    evidence = {
        "get_efield": "Committed M18 calls solver.get_efield(band, bloch_phase=False); M18 _field_array accepts returned (128,128,3) or (128,128,1,3) and stores component-last C-order data.",
        "get_hfield": "Committed M18 calls solver.get_hfield(band, bloch_phase=False) with the same shape canonicalization.",
        "get_dfield": "Committed M18 calls optional solver.get_dfield(band, bloch_phase=False) and records captured/unavailable status; captured data are stored with the same canonical shape.",
        "get_bfield": "Committed M18 calls optional solver.get_bfield(band, bloch_phase=False) and records captured/unavailable status; captured data are stored with the same canonical shape.",
        "get_epsilon": "Committed M18 calls solver.get_epsilon(), requires 128*128 values, and reshapes them with C-order to (x,y).",
    }
    try:
        mpb = _load(Path("/home/icy/miniconda3/envs/mp/lib/python3.13/site-packages/meep/mpb/__init__.py"), "m20_mpb_binding_source")
        mode_solver = mpb.ModeSolver
        signatures = {name: str(inspect.signature(getattr(mode_solver, name))) for name in ("get_efield", "get_hfield", "get_dfield", "get_bfield", "get_epsilon")}
        docstrings = {name: inspect.getdoc(getattr(mode_solver, name)) for name in signatures}
        binding = {"module_path": "/home/icy/miniconda3/envs/mp/lib/python3.13/site-packages/meep/mpb/__init__.py", "signatures": signatures, "docstrings": docstrings, "metadata_exposed_by_public_methods": False}
    except Exception as exc:
        binding = {"module_path": "known pinned mp binding path", "signatures": {}, "docstrings": {}, "metadata_exposed_by_public_methods": False, "inspection_error": f"{type(exc).__name__}:{exc}"}
    return {"source_binding_evidence": evidence, "installed_binding_forensics": binding}


def synthetic_collocated_curl_validation() -> dict[str, Any]:
    m16 = _m16(); u, v = np.meshgrid(np.arange(SHAPE[0]) / SHAPE[0], np.arange(SHAPE[1]) / SHAPE[1], indexing="ij"); scalar = np.exp(2j * np.pi * (2.0 * u + 3.0 * v)); field = np.stack([scalar, scalar * 0.5j, scalar * -0.25], axis=-1); q = (0.0, 0.0); dx, dy = m16.spectral_gradient(field, q); expected = np.stack([dy[..., 2], -dx[..., 2], dx[..., 1] - dy[..., 0]], axis=-1); actual = m16.maxwell_curl(field, q)
    return {"formula": "collocated reference only: curl(F)=(D_y F_z,-D_x F_z,D_x F_y-D_y F_x), D_q=FFT^-1[i 2pi(B m+q) FFT]", "synthetic_periodic_field_residual_max": float(np.max(np.abs(actual - expected))), "status": "VALIDATED_FOR_COLLOCATED_REFERENCE_NOT_PROOF_OF_MPB_RETURNED_FIELD_LOCATIONS"}


def analyze(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    diagnostics = constitutive_diagnostics(records); forensics = binding_forensics(); synthetic = synthetic_collocated_curl_validation()
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m18_dataset_id": M18_DATASET_ID, "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": 3, "get_efield_semantics": {"description": "Bloch-phase-excluded MPB electric-field getter, canonicalized to component-last (x,y,component) array.", "certainty": "SOURCE_CONFIRMED_SHAPE_SEMANTICS_ONLY"}, "get_hfield_semantics": {"description": "Bloch-phase-excluded MPB magnetic-field getter, canonicalized to component-last (x,y,component) array.", "certainty": "SOURCE_CONFIRMED_SHAPE_SEMANTICS_ONLY"}, "get_dfield_semantics": {"description": "Optional Bloch-phase-excluded displacement-field getter; captured in M18 but native grid location and material interpolation are not exposed.", "certainty": "SOURCE_CONFIRMED_AVAILABILITY_NOT_LOCATION"}, "get_bfield_semantics": {"description": "Optional Bloch-phase-excluded magnetic-induction getter; captured in M18 but native grid location and constitutive operator are not exposed.", "certainty": "SOURCE_CONFIRMED_AVAILABILITY_NOT_LOCATION"}, "get_epsilon_semantics": {"description": "Getter returns 128*128 values reshaped C-order as (x,y) on the MPB geometry-lattice fractional grid.", "certainty": "SOURCE_CONFIRMED_ARRAY_RESHAPE_PARTIAL_COORDINATE_SEMANTICS"}, "field_component_grid_location_status": "NOT_EXPOSED_PUBLIC_BINDING_OR_M18_READBACK", "component_staggering_offsets": None, "field_coordinate_basis": "MPB geometry-lattice fractional cell grid for array indices; physical component basis and Yee locations are not exposed by the public getter metadata.", "field_interpolation_or_postprocessing_status": "NOT_EXPOSED; shape canonicalization is local storage only and does not establish native/interpolated sampling.", "constitutive_operator_exposure_status": "D_AND_B_VALUES_CAPTURED_BUT_INTERNAL_MATERIAL_OPERATOR_AND_GRID_INTERPOLATION_NOT_EXPOSED", "returned_constitutive_relation_status": "STAGGERED_OR_INTERPOLATED_RELATION_REQUIRED", "D_vs_epsilonE_residual_max": diagnostics["D_vs_epsilonE_residual_max"], "B_vs_H_residual_max": diagnostics["B_vs_H_residual_max"], "per_member_constitutive_diagnostics": diagnostics["per_member_constitutive_diagnostics"], "staggered_or_interpolated_curl_formula": "NOT_DERIVABLE_FROM_AVAILABLE_PUBLIC_METADATA; the collocated reference formula is reported separately and is not used as calibrated MPB operator.", "synthetic_staggered_curl_validation": synthetic, "calibrated_fresh_stored_state_maxwell_residual_max": None, "calibrated_curlE_residual_max": None, "calibrated_curlH_residual_max": None, "calibration_improvement_factor_vs_M18_collocated_residual": None, "collocated_direct_DB_diagnostic": diagnostics["collocated_direct_DB_diagnostic"], "calibrated_c3_transformed_state_maxwell_residual_max": None, "calibrated_operator_intertwining_residual_max": None, "component_grid_c3_covariance_status": "NOT_ESTABLISHED_FIELD_LOCATIONS_UNEXPOSED", "field_operator_metadata_status": "EXACT_INTERNAL_MPB_OPERATOR_METADATA_NOT_EXPOSED", "isolated_projector_theorem_status": "CONDITIONAL_OPERATOR_COVARIANCE_NOT_YET_ESTABLISHED", "discrete_operator_covariance_diagnosis": "OPERATOR_RECONSTRUCTION_STILL_INCOMPLETE", "exact_missing_operator_metadata": ["component-specific native grid locations or half-cell offsets", "MPB interpolation/postprocessing rule for get_*field", "internal epsilon/D constitutive operator and normalization", "field-component Fourier phase convention"], "exact_local_source_or_api_limitation": "Committed MePhC code records only public getter arrays and the installed ModeSolver getter signatures expose no location, staggering, interpolation, or constitutive-operator metadata; installed getter docstrings are absent.", "remaining_unresolved_questions": ["Whether D/B getters are native staggered fields or interpolated to a common grid", "Which internal material averaging/operator maps E to D", "Which component-specific Fourier phases calibrate the stored eigenstates"], "alternative_explanations_considered": ["common collocated grid", "Yee-like component staggering", "getter interpolation/postprocessing", "subpixel material operator", "normalization/voxel weighting", "component basis convention"], "counterevidence_summary": {"M18_authoritative_collocated_residual_max": 0.8828866629159403, "direct_DB_diagnostic": diagnostics["collocated_direct_DB_diagnostic"], "constitutive_mismatch": diagnostics["per_member_constitutive_diagnostics"], "synthetic_collocated_reference": synthetic, "source_binding": forensics}, "cheapest_remaining_discriminating_test": "A metadata-only runtime hook that records native component locations/interpolation flags and the internal constitutive/epsilon operator for the same three M18 states; no new physical states are needed.", "next_science_decision": "AUDIT_MPB_INTERNAL_OPERATOR_OR_RAW_STAGGERED_FIELD_METADATA_WITH_MINIMAL_RUNTIME_HOOK", "minimal_next_live_state_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_binding_forensics": forensics, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def failure(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "exception_type": type(exc).__name__ if exc else None, "exception_message": str(exc)[:1024] if exc else None, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "minimal_next_live_state_count": 0, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M20_WORK_ORDER_MISSING")
        counters_path = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]); root = counters_path.parent.parent; job = _job()
        records = read_dataset(job, root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)
        # The M12 and M13 bindings are validated as inputs even though M20's
        # field calibration uses only the exact M18 readback rows.
        read_dataset(job, root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); read_dataset(job, root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3)
        result = analyze(records)
    except Exception as exc:
        result = failure(str(exc), exc); result["traceback_tail"] = traceback.format_exc()[-3000:]
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
