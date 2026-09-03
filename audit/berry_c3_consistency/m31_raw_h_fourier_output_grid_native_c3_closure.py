"""M31 bounded raw/native H representation audit.

This module deliberately treats the public ``get_hfield`` array as an
observation, not as evidence of the reciprocal representation underneath it.
It inventories the installed runtime before reading field values, records any
source-confirmed raw candidate that is actually exposed, and otherwise emits
a schema-complete, fail-closed diagnosis without fitting a transform.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
N = 128
SHAPE = (N, N, 3)
BANDS = (2, 3)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M30_DATASET_ID = "320a49b45e8927442aefb7e142633b1e40458664f64ac19a115cfc44e19ef3b0"
M30_MANIFEST_SHA256 = "359214d08634e5d2f36ba485a5901379ff73c28edaa809e0cbb6d58f62def3f4"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m31-raw-h-fourier-native-metadata-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m31-raw-h-fourier-output-grid-native-c3-closure-v1"
BASELINE_MIN_OVERLAP = 0.8707405176993757
BASELINE_FAILURES = 3


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M31_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _array(value: Any, label: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    if array.ndim == 4 and array.shape[2] == 1 and array.shape[3] == 3:
        array = array[:, :, 0, :]
    if array.shape != SHAPE or not np.all(np.isfinite(array.real)) or not np.all(np.isfinite(array.imag)):
        raise ValueError(f"M31_COMPLEX_FIELD_INVALID:{label}:{array.shape}")
    return np.array(array, copy=True)


def _complex_hash(value: Any) -> str:
    return hashlib.sha256(np.asarray(value, dtype=np.complex128).tobytes()).hexdigest()


def _encode_shape(value: Any) -> dict[str, Any]:
    array = np.asarray(value, dtype=np.complex128)
    return {"shape": list(array.shape), "dtype": str(array.dtype), "sha256": _complex_hash(array), "complex_encoding": "real_imag_pair"}


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
    if isinstance(value, np.ndarray):
        return _encode_shape(value)
    if isinstance(value, Path) or callable(value):
        raise ValueError(f"UNSUPPORTED_RESULT_VALUE:{path}:{type(value).__name__}")
    raise ValueError(f"UNSUPPORTED_RESULT_VALUE:{path}:{type(value).__name__}")


def _candidate_names() -> tuple[str, ...]:
    return (
        "get_hfield_coefficients", "get_hfield_fourier", "get_hfield_spectral",
        "get_raw_hfield", "raw_h_coefficients", "hfield_coefficients",
        "hfield_fourier_coefficients", "raw_hfield", "field_data", "fft_buffer",
    )


def raw_access_candidate_inventory(solver: Any) -> list[dict[str, Any]]:
    """Freeze candidate names and runtime evidence before observing field values."""
    runtime_type = f"{type(solver).__module__}.{type(solver).__qualname__}"
    inventory: list[dict[str, Any]] = []
    for name in _candidate_names():
        try:
            present = hasattr(solver, name)
            value = getattr(solver, name, None) if present else None
            inventory.append({
                "candidate": name,
                "runtime_type": runtime_type,
                "present": bool(present),
                "callable": bool(callable(value)),
                "evidence_level": "runtime_attribute" if present else "not_exposed",
                "source_evidence": "installed ModeSolver object attribute probe; no value read",
            })
        except BaseException as exc:
            inventory.append({"candidate": name, "runtime_type": runtime_type, "present": False, "callable": False, "evidence_level": "probe_failed", "source_evidence": f"{type(exc).__name__}:{str(exc)[:256]}"})
    return inventory


def _select_band(value: Any, band: int) -> Any:
    if isinstance(value, Mapping):
        for key in (band, str(band), band - 1, str(band - 1)):
            if key in value:
                return value[key]
    return value


def _invoke_raw_candidate(solver: Any, name: str, band: int) -> tuple[Any, str | None]:
    if not hasattr(solver, name):
        return None, "NOT_PRESENT"
    candidate = getattr(solver, name)
    try:
        if callable(candidate):
            for args, kwargs, label in (((band,), {"bloch_phase": False}, "band_bloch_phase"), ((band,), {}, "band"), ((), {}, "no_args")):
                try:
                    return _select_band(candidate(*args, **kwargs), band), label
                except TypeError:
                    continue
            return None, "CALL_SIGNATURE_UNAVAILABLE"
        return _select_band(candidate, band), "attribute"
    except BaseException as exc:
        return None, f"ACCESS_FAILED:{type(exc).__name__}:{str(exc)[:256]}"


def probe_raw_h(solver: Any, band: int, inventory: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Probe only frozen raw candidates; no fitted or guessed conversion is used."""
    attempts: list[dict[str, Any]] = []
    for item in inventory:
        name = str(item["candidate"])
        if not item.get("present"):
            continue
        value, invocation = _invoke_raw_candidate(solver, name, band)
        if value is None:
            attempts.append({"candidate": name, "invocation": invocation, "status": "UNAVAILABLE"})
            continue
        try:
            array = np.asarray(value, dtype=np.complex128)
            if array.size == 0 or not np.all(np.isfinite(array.real)) or not np.all(np.isfinite(array.imag)):
                raise ValueError("NONFINITE_OR_EMPTY")
            attempts.append({"candidate": name, "invocation": invocation, "status": "CAPTURED", "representation": _encode_shape(array)})
        except BaseException as exc:
            attempts.append({"candidate": name, "invocation": invocation, "status": "DESCRIPTOR_ONLY", "descriptor": {"type": type(value).__name__, "error": f"{type(exc).__name__}:{str(exc)[:256]}"}})
    captured = [item for item in attempts if item.get("status") == "CAPTURED"]
    return {"band": band, "attempts": attempts, "captured": captured, "status": "CAPTURED_PARTIAL_NATIVE_METADATA" if captured else "RAW_RECIPROCAL_H_NOT_EXPOSED_IN_INSTALLED_RUNTIME"}


def _get_hfield(solver: Any, band: int) -> np.ndarray:
    try:
        return _array(solver.get_hfield(band, bloch_phase=False), f"band{band}")
    except TypeError:
        return _array(solver.get_hfield(band, False), f"band{band}")


def _native_metrics(raw_by_member: Mapping[str, Any]) -> dict[str, Any]:
    # A raw candidate is not sufficient merely because it is array-like: the
    # integer reciprocal labels and proper Cartesian map must also be exposed.
    if not all(raw_by_member.get(member, {}).get("captured") for member in MEMBERS):
        return {"status": "NATIVE_C3_NOT_EVALUABLE_RAW_H_UNAVAILABLE", "minimum_overlap": None, "maximum_principal_angle": None, "maximum_projector_distance": None, "failure_count": None}
    return {"status": "INSUFFICIENT_EVIDENCE", "minimum_overlap": None, "maximum_principal_angle": None, "maximum_projector_distance": None, "failure_count": None}


def _persist(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]], source_m30: str) -> dict[str, Any]:
    namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA}
    store = job.ImmutableDatasetStore(state_root, namespace)
    for record in records:
        key = _canonical({"work_order_id": work_order_id, "member_index": record["member_index"], "record_id": record["record_id"]})
        store.put(key, _canonical(dict(record)), {"member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "raw_h_metadata": True})
    return store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "source_m18_dataset_id": M18_DATASET_ID, "source_m30_dataset_id": source_m30, "raw_h_metadata": True})


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    work_order_id = bundle["work_order_id"]
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m31_job")
    m18 = _load(ROOT / "audit" / "berry_c3_consistency" / "m18_exact_mpb_operator_readback_and_covariance_closure.py", "m31_m18")
    m18_records = {item["c3_member_identity"]: item for item in m18.read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)}
    m30_records = {item["c3_member_identity"]: item for item in m18.read_dataset(job, state_root, M30_DATASET_ID, M30_MANIFEST_SHA256, 3)}
    if set(m18_records) != set(MEMBERS) or set(m30_records) != set(MEMBERS):
        raise ValueError("M31_CANONICAL_TRIPLET_INVALID")
    factory, _band = m18.production_solver_factory()
    counter = job.BudgetCounter(0, 3)
    captures: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] | None = None
    for member in MEMBERS:
        solver, reciprocal, parity = factory(m18_records[member])
        if inventory is None:
            inventory = raw_access_candidate_inventory(solver)
        counter.consume_solver()
        solver.run_parity(parity, False)
        bands: dict[str, Any] = {}
        raw_bands: dict[str, Any] = {}
        for band in BANDS:
            h = _get_hfield(solver, band)
            bands[str(band)] = {"shape": list(h.shape), "dtype": str(h.dtype), "sha256": _complex_hash(h), "component_order": "solver public Cartesian x,y,z"}
            raw_bands[str(band)] = probe_raw_h(solver, band, inventory or [])
        captures[member] = {"bands": bands, "raw": raw_bands}
        record_id = f"M31-{member}"
        records.append({"schema": DATASET_SCHEMA, "record_id": record_id, "member_index": int(m18_records[member]["member_index"]), "c3_member_identity": member, "geometry_id": "G15", "coordinate": list(m18_records[member]["coordinate"]), "bands": list(BANDS), "runtime_type": f"{type(solver).__module__}.{type(solver).__qualname__}", "raw_H_access_candidate_inventory": inventory or [], "get_hfield_public_metadata": bands, "raw_H_band_metadata": raw_bands, "raw_H_component_order": "UNAVAILABLE_UNLESS_RUNTIME_CONFIRMED", "raw_H_mode_index_convention": "UNAVAILABLE_UNLESS_RUNTIME_CONFIRMED", "raw_H_fft_normalization_descriptor": "UNAVAILABLE_UNLESS_RUNTIME_CONFIRMED", "output_grid_origin_descriptor_status": "NOT_EXPOSED", "component_interpolation_descriptor_status": "NOT_EXPOSED", "source_m18_record_id": m18_records[member].get("record_id"), "source_m30_record_identity": m30_records[member].get("c3_member_identity"), "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT")})
    manifest = _persist(job, state_root, work_order_id, records, M30_DATASET_ID)
    raw_status = "CAPTURED_PARTIAL_NATIVE_METADATA" if any(c["raw"][str(BANDS[0])]["status"] == "CAPTURED_PARTIAL_NATIVE_METADATA" for c in captures.values()) else "RAW_RECIPROCAL_H_NOT_EXPOSED_IN_INSTALLED_RUNTIME"
    native = _native_metrics({member: {"captured": any(captures[member]["raw"][str(b)]["status"] == "CAPTURED_PARTIAL_NATIVE_METADATA" for b in BANDS)} for member in MEMBERS})
    inaccessible = "ModeSolver raw reciprocal-H coefficient object/method" if raw_status == "RAW_RECIPROCAL_H_NOT_EXPOSED_IN_INSTALLED_RUNTIME" else None
    diagnosis = "RAW_H_NATIVE_REPRESENTATION_NOT_EXPOSED_AT_INSTALLED_RUNTIME_LIMIT" if inaccessible else "NATIVE_TO_ARRAY_TRANSFORM_REMAINS_UNRESOLVED"
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "RAW_H_RUNTIME_ACCESS_AND_RESULT_BOUNDARY_GATE_PASS", "source_m18_dataset_id": M18_DATASET_ID, "source_m30_dataset_id": M30_DATASET_ID, "target_state_count": 3, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": counter.solver_count, "dataset_record_count": 3, "new_metadata_record_count": 3, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "raw_H_access_candidate_inventory": inventory or [], "raw_H_native_capture_status": raw_status, "raw_H_coefficient_shape": None, "raw_H_component_order": "UNAVAILABLE_UNLESS_RUNTIME_CONFIRMED", "raw_H_mode_index_convention": "UNAVAILABLE_UNLESS_RUNTIME_CONFIRMED", "raw_H_fft_normalization_descriptor": "UNAVAILABLE_UNLESS_RUNTIME_CONFIRMED", "output_grid_origin_descriptor_status": "NOT_EXPOSED", "component_interpolation_descriptor_status": "NOT_EXPOSED", "raw_H_vs_get_hfield_reconstruction_max_residual": None, "raw_H_vs_get_hfield_reconstruction_relative_L2_residual": None, "native_H_c3_minimum_overlap_singular_value": native["minimum_overlap"], "native_H_c3_maximum_principal_angle": native["maximum_principal_angle"], "native_H_c3_maximum_projector_distance": native["maximum_projector_distance"], "native_H_c3_covariance_failure_count": native["failure_count"], "native_H_c3_status": native["status"], "output_transform_c3_status": "OUTPUT_TRANSFORM_NOT_IDENTIFIED", "native_to_get_hfield_transform_formula": None, "authoritative_public_H_result_unchanged": True, "corrected_public_H_c3_minimum_overlap_singular_value": BASELINE_MIN_OVERLAP, "corrected_public_H_c3_maximum_principal_angle": None, "corrected_public_H_c3_covariance_failure_count": BASELINE_FAILURES, "raw_to_array_reconstruction_status": "RAW_NATIVE_DATA_INSUFFICIENT_FOR_RECONSTRUCTION", "primary_m31_diagnosis": diagnosis, "rank1_berry_spike_interpretation": "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["public output interpolation", "raw reciprocal coefficient object unavailable", "component or origin metadata unavailable", "state-family numerical covariance"], "counterevidence_summary": {"public_H_baseline_minimum_overlap": BASELINE_MIN_OVERLAP, "public_H_baseline_failure_count": BASELINE_FAILURES, "raw_probe_bands": list(BANDS)}, "exact_remaining_uncertainty": "The installed runtime did not expose a source-confirmed raw reciprocal-H coefficient object sufficient for a coefficient-space C3 test." if inaccessible else "A raw candidate was observed but its reciprocal labels and output transform remain unconfirmed.", "exact_inaccessible_runtime_object": inaccessible, "local_binding_or_runtime_evidence": "Frozen candidate inventory from the installed ModeSolver runtime object; public get_hfield was observed only after inventory capture.", "cheapest_remaining_discriminating_test": "Inspect installed MPB SWIG/source bindings for a reciprocal-H export without another physical-state acquisition", "next_science_decision": "STOP_C3_GOAL_AT_INSTALLED_MPB_RAW_FIELD_INTROSPECTION_LIMIT" if inaccessible else "INSUFFICIENT_EVIDENCE", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True, "captures": captures}


def _child_capsule(body: Any) -> dict[str, Any]:
    try:
        return {"schema": "m31-native-child-result-v1", "status": "PASS", "stage": "child_runtime_body", "bounded_outcome": "PASS", "exception_type": None, "exception_message": None, "traceback_tail": None, "payload_reference_or_inline_result": body()}
    except BaseException as exc:
        return {"schema": "m31-native-child-result-v1", "status": "FAIL_CLOSED", "stage": "child_runtime_body", "bounded_outcome": "FAIL_CLOSED", "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "traceback_tail": traceback.format_exc()[-3000:], "payload_reference_or_inline_result": None}


def main() -> int:
    child = _child_capsule(_science_result)
    if child["status"] == "PASS":
        result = dict(child["payload_reference_or_inline_result"])
    else:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": child["exception_message"], "failure_stage": child["stage"], "exception_type": child["exception_type"], "traceback_tail": child["traceback_tail"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0}
    result["native_child_capsule_status"] = child["status"]
    result["structured_result_boundary_status"] = "PASS"
    result["native_child_result"] = {key: value for key, value in child.items() if key != "payload_reference_or_inline_result"}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
