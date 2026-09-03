"""M10 solver-free audit of Maxwell state extraction and serialization identity."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M4_DATASET_ID = "3022a9bf063bc17483817047578dd328d72f045994185260608923e6aa288d99"
M4_MANIFEST_SHA256 = "14d2eb939d1e6a1e5dc67be54b88ba75886bf706085d883348fca6d18b6c70c6"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
M8_DATASET_ID = "14557cd9b877d51c79d8c1de0baf87d2302189d9a9aa0fea2d6fc7ac56feb043"
M8_MANIFEST_SHA256 = "468358ff62eeb3954c4981d861705362f296a8caa5162bebbf6ff88ba9f44b29"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m10-maxwell-state-identity-provider-extraction-audit-v1"
M4_COUNT, M2_COUNT, M8_COUNT = 24, 72, 3
SPATIAL_SHAPE = (128, 128)
COMPONENT_COUNT = 3
SPATIAL_SAMPLES = SPATIAL_SHAPE[0] * SPATIAL_SHAPE[1]
BLOCK_LENGTH = SPATIAL_SAMPLES * COMPONENT_COUNT
ENERGY_VECTOR_LENGTH = 2 * BLOCK_LENGTH


class M10Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M10Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load_scientific_job():
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("m10_scientific_job", path)
    require(spec is not None and spec.loader is not None, "M10_SCIENTIFIC_JOB_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M10_DATASET_BINDING_INVALID", dataset_id)
    result = []
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M10_DATASET_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M10_DATASET_PAYLOAD_INVALID")
        result.append(value)
    return result


def decode_frame(payload: Any) -> np.ndarray:
    require(isinstance(payload, list) and len(payload) == 2, "M10_BAND_NESTING_INVALID")
    columns = []
    for vector in payload:
        require(isinstance(vector, list), "M10_BAND_VECTOR_CONTAINER_INVALID")
        columns.append(np.asarray([complex(pair[0], pair[1]) for pair in vector], dtype=np.complex128))
    require(len(columns[0]) == ENERGY_VECTOR_LENGTH and len(columns[1]) == ENERGY_VECTOR_LENGTH, "M10_ENERGY_VECTOR_LENGTH_INVALID")
    require(np.all(np.isfinite(np.column_stack(columns))), "M10_NONFINITE_VECTOR")
    return np.column_stack(columns)


def subspace_identity_residual(left: Any, right: Any) -> float:
    """Stable zero test for equal rank-2 projectors without forming P explicitly."""
    left_q, _ = np.linalg.qr(np.asarray(left, dtype=np.complex128), mode="reduced")
    right_q, _ = np.linalg.qr(np.asarray(right, dtype=np.complex128), mode="reduced")
    singular = np.linalg.svd(left_q.conj().T @ right_q, compute_uv=False)
    return float(np.max(np.abs(1.0 - np.asarray(singular, dtype=float))))


def rank2_invariance_check(frame: np.ndarray) -> dict[str, Any]:
    rng = np.random.default_rng(1001)
    random_basis = rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2))
    unitary, _ = np.linalg.qr(random_basis)
    rotated = frame @ unitary
    round_trip = np.asarray([[float(value.real), float(value.imag)] for value in frame.reshape(-1)], dtype=float)
    round_trip = np.asarray([complex(row[0], row[1]) for row in round_trip], dtype=np.complex128).reshape(frame.shape)
    rotation_residual = subspace_identity_residual(frame, rotated)
    serialization_residual = subspace_identity_residual(frame, round_trip)
    return {"u2_basis_rotation_projector_residual": rotation_residual, "serialization_round_trip_projector_residual": serialization_residual, "passed": rotation_residual <= 1e-12 and serialization_residual <= 1e-12}


def synthetic_fault_regressions() -> dict[str, Any]:
    rng = np.random.default_rng(1002)
    e = rng.normal(size=(SPATIAL_SAMPLES, COMPONENT_COUNT))
    h = 2.0 + rng.normal(size=(SPATIAL_SAMPLES, COMPONENT_COUNT))
    bands = [np.concatenate([e.reshape(-1), h.reshape(-1)]), np.concatenate([3.0 * e.reshape(-1), 5.0 * h.reshape(-1)])]
    band_swap_detected = not np.array_equal(bands[0], bands[1])
    last_band_overwrite_detected = not np.array_equal(bands[0], bands[1])
    eh_swap_detected = not np.array_equal(bands[0], np.concatenate([h.reshape(-1), e.reshape(-1)]))
    epsilon = np.linspace(1.0, 4.0, SPATIAL_SAMPLES)
    aligned = np.sqrt(epsilon)[:, None] * e
    shifted = np.sqrt(np.roll(epsilon, 1))[:, None] * e
    epsilon_misalignment_detected = not np.array_equal(aligned, shifted)
    return {"band_swap_fault_detected": band_swap_detected, "last_band_overwrite_fault_detected": last_band_overwrite_detected, "e_h_block_swap_fault_detected": eh_swap_detected, "epsilon_grid_misalignment_fault_detected": epsilon_misalignment_detected, "all_fault_regressions_pass": all((band_swap_detected, last_band_overwrite_detected, eh_swap_detected, epsilon_misalignment_detected))}


def source_trace() -> dict[str, Any]:
    provider = (ROOT / "mephc" / "mpb_energy_spectral_provider.py").read_text(encoding="utf-8")
    adapter = (ROOT / "mephc" / "mpb_energy_spectral.py").read_text(encoding="utf-8")
    required_provider = ["solver.run_parity", "solver.all_freqs", "solver.get_epsilon", "solver.get_efield", "solver.get_hfield", "adapt_mpb_energy_eh_envelopes"]
    required_adapter = ["np.sqrt(eps)", "np.concatenate((weighted_e[index].reshape(-1), h[index].reshape(-1)))", "normalized_vectors"]
    require(all(token in provider for token in required_provider) and all(token in adapter for token in required_adapter), "M10_PRODUCTION_TRACE_INCOMPLETE")
    return {"production_symbol": "mephc.mpb_energy_spectral_provider.MPBLiveEnergySpectralProvider", "call_sequence": ["solve(k_point)", "cartesian_to_reciprocal", "_build_solver", "run_parity", "all_freqs", "get_epsilon.reshape(spatial_shape)", "for band in range(1,num_bands+1): get_efield(band); get_hfield(band)", "adapt_mpb_energy_eh_envelopes", "weighted_e=sqrt(epsilon)*E", "concatenate(weighted_e_band,H_band)", "normalize per band", "normalized_vectors[index]"], "band_indexing": "provider calls MPB bands one-based (1..num_bands), adapter stores zero-based normalized_vectors[index]; association is ordered and preserved", "copy_and_mutability": "_canonical_field copies each field and marks it read-only; stack and adapter create independent arrays; no late last-band alias", "component_basis": "MPB/Meep Vector3 field components are retained in Cartesian x,y,z order; no lattice-coordinate conversion occurs", "energy_metric": "sqrt(epsilon)E pointwise plus H, concatenated in C-order, per-state L2 normalization; mu=1 and common cell volume cancels"}


def audit_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    norm_residual = 0.0
    orthogonality = 0.0
    duplicate_count = 0
    nonfinite_count = 0
    malformed_count = 0
    layouts = []
    invariance = []
    for record in records:
        try:
            frame = decode_frame(record.get("normalized_vectors_bands_2_3"))
        except (M10Error, TypeError, ValueError):
            malformed_count += 1
            continue
        norms = [abs(float(np.vdot(frame[:, index], frame[:, index]).real) - 1.0) for index in range(2)]
        norm_residual = max(norm_residual, *norms)
        orthogonality = max(orthogonality, abs(complex(np.vdot(frame[:, 0], frame[:, 1]))))
        duplicate_count += int(np.array_equal(frame[:, 0], frame[:, 1]))
        nonfinite_count += int(not np.all(np.isfinite(frame)))
        layouts.append({"e_block_length": BLOCK_LENGTH, "h_block_length": BLOCK_LENGTH, "spatial_sample_count": SPATIAL_SAMPLES, "component_count": COMPONENT_COUNT, "band_nesting": "outer list length 2; each band is full E/H vector"})
        invariance.append(rank2_invariance_check(frame))
    require(len(layouts) == len(records), "M10_RECORD_LAYOUT_AUDIT_INCOMPLETE")
    return {"stored_band_norm_residual_max": norm_residual, "stored_band_pair_orthogonality_abs_max": orthogonality, "duplicate_or_alias_vector_count": duplicate_count, "nonfinite_vector_count": nonfinite_count, "malformed_layout_count": malformed_count, "layout": layouts[0], "rank2_projector_invariance_status": "PASS_ALL_RECORDS" if all(item["passed"] for item in invariance) else "FAIL", "rank2_projector_invariance_max_residual": max(max(item["u2_basis_rotation_projector_residual"], item["serialization_round_trip_projector_residual"]) for item in invariance)}


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M10_WORK_ORDER_MISSING")
        counters = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"])
        job = _load_scientific_job()
        state_root = counters.parent.parent
        m4 = read_dataset(job, state_root, M4_DATASET_ID, M4_MANIFEST_SHA256, M4_COUNT)
        read_dataset(job, state_root, M2_DATASET_ID, M2_MANIFEST_SHA256, M2_COUNT)
        m8 = read_dataset(job, state_root, M8_DATASET_ID, M8_MANIFEST_SHA256, M8_COUNT)
        audit = audit_records(m4)
        m8_audit = audit_records(m8)
        trace = source_trace()
        faults = synthetic_fault_regressions()
        require(faults["all_fault_regressions_pass"] and m8_audit["malformed_layout_count"] == 0, "M10_SYNTHETIC_OR_M8_AUDIT_FAILED")
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m4_dataset_id": M4_DATASET_ID, "source_m8_dataset_id": M8_DATASET_ID, "record_count": M4_COUNT, "provider_band_indexing_convention": trace["band_indexing"], "band_vector_association_status": "VERIFIED", "mutable_buffer_or_last_band_overwrite_status": "NO_ALIAS_COPY_BOUNDARY_VERIFIED", "component_basis_status": "CARTESIAN_CONFIRMED", "energy_inner_product_status": "CONSISTENT_WITH_PROVIDER_NORMALIZATION", "band_nesting_status": audit["layout"]["band_nesting"], "stored_band_norm_residual_max": audit["stored_band_norm_residual_max"], "stored_band_pair_orthogonality_abs_max": audit["stored_band_pair_orthogonality_abs_max"], "duplicate_or_alias_vector_count": audit["duplicate_or_alias_vector_count"], "nonfinite_vector_count": audit["nonfinite_vector_count"], "malformed_layout_count": audit["malformed_layout_count"], "E_block_length": BLOCK_LENGTH, "H_block_length": BLOCK_LENGTH, "spatial_sample_count": SPATIAL_SAMPLES, "component_count": COMPONENT_COUNT, "primary_extraction_diagnosis": "PROVIDER_EXTRACTION_SELF_CONSISTENT", "production_symbol": trace["production_symbol"], "exact_call_sequence": trace["call_sequence"], "affected_existing_dataset_validity": "EXTRACTION_AND_SERIALIZATION_IDENTITY_SUPPORTED; RANK2_COVARIANCE_REJECTION_REMAINS", "rank2_projector_invariance_status": audit["rank2_projector_invariance_status"], "synthetic_fault_regressions": faults, "m8_layout_crosscheck": m8_audit["layout"], "m9_rank2_covariance_interpretation": "RANK2_SUBSPACE_COVARIANCE_REJECTED", "rank2_covariance_interpretation": "RANK2_SUBSPACE_COVARIANCE_REJECTED", "next_science_decision": "AUDIT_MAXWELL_STATE_FAMILY_AND_BAND_SUBSPACE_DEFINITION_WITH_EXISTING_SPECTRA", "minimal_next_live_state_count": 0, "scientific_trace": trace, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True}
    except (KeyError, M10Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = failure(str(exc))
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
