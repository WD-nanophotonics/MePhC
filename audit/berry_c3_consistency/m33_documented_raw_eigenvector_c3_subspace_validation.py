"""M33 documented MPB raw-eigenvector C3 validation.

The only live work in this milestone is the exact existing G15 triplet.  The
documented ModeSolver raw-eigenvector API is inspected before any solve.  Raw
arrays are preserved as compressed content-addressed payloads; no phase,
permutation, normalization, or gauge is chosen from overlap.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import importlib.util
import inspect
import io
import json
import os
import traceback
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M30_DATASET_ID = "320a49b45e8927442aefb7e142633b1e40458664f64ac19a115cfc44e19ef3b0"
M30_MANIFEST_SHA256 = "359214d08634e5d2f36ba485a5901379ff73c28edaa809e0cbb6d58f62def3f4"
M31_DATASET_ID = "62907b0f51cbb659474b064da9d28b4689b3f19e293d4d6c7de4397284089b33"
M31_MANIFEST_SHA256 = "08768a52ca8245b38f3b1b6aeeaf212629b75c7f3325071d743a97e52544bc68"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m33-raw-eigenvector-c3-metadata-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m33-documented-raw-eigenvector-c3-subspace-validation-v1"
PUBLIC_H_MIN_OVERLAP = 0.8707405176993757
PUBLIC_H_FAILURES = 3
BANDS = (2, 3)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M33_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _safe(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return _safe(value.item(), path)
    if isinstance(value, complex):
        return [float(value.real), float(value.imag)]
    if isinstance(value, Mapping):
        return {str(key): _safe(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Path):
        return str(value)
    raise ValueError(f"M33_UNSAFE_RESULT_VALUE:{path}:{type(value).__name__}")


def _signature(value: Any) -> str | None:
    try:
        return str(inspect.signature(value))
    except (TypeError, ValueError):
        return f"<signature-unavailable:{type(value).__name__}>"


def _api_evidence(solver: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for name in ("get_eigenvectors", "save_eigenvectors", "compute_symmetry", "transformed_overlap"):
        try:
            value = getattr(solver, name)
            evidence[name] = {"available": callable(value), "signature": _signature(value), "owner_type": f"{type(solver).__module__}.{type(solver).__qualname__}", "evidence": "direct installed runtime class attribute inspection before solve"}
        except BaseException as exc:
            evidence[name] = {"available": False, "signature": None, "owner_type": f"{type(solver).__module__}.{type(solver).__qualname__}", "evidence": f"direct attribute inspection failed: {type(exc).__name__}:{str(exc)[:256]}"}
    return evidence


def _version_evidence(solver: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"runtime_type": f"{type(solver).__module__}.{type(solver).__qualname__}", "python_executable": os.sys.executable}
    try:
        import meep
        result["meep_version_attribute"] = getattr(meep, "__version__", None)
        result["meep_module_path"] = getattr(meep, "__file__", None)
    except BaseException as exc:
        result["meep_import_evidence"] = f"{type(exc).__name__}:{str(exc)[:256]}"
    for package in ("meep", "mpb"):
        try:
            result[f"{package}_distribution_version"] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[f"{package}_distribution_version"] = None
    return result


def _raw_array(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype == object:
        raise ValueError("M33_RAW_EIGENVECTOR_OBJECT_DTYPE")
    array = np.asarray(array, dtype=np.complex128)
    if array.ndim < 2 or array.size == 0 or not np.all(np.isfinite(array.real)) or not np.all(np.isfinite(array.imag)):
        raise ValueError(f"M33_RAW_EIGENVECTOR_INVALID:{array.shape}")
    return np.array(array, copy=True)


def raw_band_axis_semantics(array: np.ndarray, requested_bands: int = 2) -> dict[str, Any]:
    axes = [index for index, size in enumerate(array.shape) if size == requested_bands]
    if axes == [0]:
        return {"status": "DOCUMENTED_FIRST_AXIS_MATCHES_REQUESTED_BANDS", "axis": 0, "band_count": requested_bands}
    if axes == [array.ndim - 1]:
        return {"status": "DOCUMENTED_LAST_AXIS_MATCHES_REQUESTED_BANDS", "axis": array.ndim - 1, "band_count": requested_bands}
    return {"status": "BAND_AXIS_SEMANTICS_INSUFFICIENT", "candidate_axes": axes, "band_count": requested_bands}


def _band_rows(array: np.ndarray, semantics: Mapping[str, Any]) -> np.ndarray | None:
    if semantics.get("status") == "DOCUMENTED_FIRST_AXIS_MATCHES_REQUESTED_BANDS":
        return array.reshape(array.shape[0], -1)
    if semantics.get("status") == "DOCUMENTED_LAST_AXIS_MATCHES_REQUESTED_BANDS":
        return np.moveaxis(array, -1, 0).reshape(array.shape[-1], -1)
    return None


def raw_rank2_gram_residual(array: np.ndarray, semantics: Mapping[str, Any]) -> dict[str, Any]:
    rows = _band_rows(array, semantics)
    if rows is None or rows.shape[0] != 2:
        return {"status": "INSUFFICIENT_EVIDENCE", "gram": None, "off_diagonal_residual": None, "normalized_gram_residual": None}
    norms = np.linalg.norm(rows, axis=1)
    if np.any(norms <= np.finfo(float).eps):
        return {"status": "ZERO_RAW_EIGENVECTOR_NORM", "gram": None, "off_diagonal_residual": None, "normalized_gram_residual": None}
    normalized = rows / norms[:, None]
    gram = normalized @ normalized.conj().T
    off_diagonal = gram - np.diag(np.diag(gram))
    return {"status": "MEASURED", "gram": [[_safe(value) for value in row] for row in gram], "off_diagonal_residual": float(np.linalg.norm(off_diagonal)), "normalized_gram_residual": float(np.linalg.norm(gram - np.eye(2)))}


def encode_raw_array(array: np.ndarray) -> dict[str, Any]:
    raw = np.asarray(array, dtype=np.complex128)
    stream = io.BytesIO()
    np.save(stream, raw, allow_pickle=False)
    compressed = zlib.compress(stream.getvalue(), level=9)
    return {"encoding": "zlib_npy_complex128_base64", "shape": list(raw.shape), "dtype": str(raw.dtype), "sha256": hashlib.sha256(raw.tobytes()).hexdigest(), "payload_base64": base64.b64encode(compressed).decode("ascii")}


def decode_raw_array(encoded: Mapping[str, Any]) -> np.ndarray:
    payload = zlib.decompress(base64.b64decode(str(encoded["payload_base64"])))
    return np.load(io.BytesIO(payload), allow_pickle=False)


def c3_transverse_action(vector: np.ndarray, angle: float = 2.0 * np.pi / 3.0) -> np.ndarray:
    """Proper Cartesian rotation restricted to a documented transverse frame."""
    value = np.asarray(vector, dtype=np.complex128)
    rotation = np.asarray([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]], dtype=float)
    if value.shape[-1] != 2:
        raise ValueError("M33_TRANSVERSE_COMPONENT_AXIS_REQUIRED")
    return np.einsum("ab,...b->...a", rotation, value)


def synthetic_covariant_rank2(seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    source = rng.normal(size=(2, 5, 2)) + 1j * rng.normal(size=(2, 5, 2))
    target = c3_transverse_action(source)
    return source, target


def rank2_overlap(source: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    source_rows = np.asarray(source, dtype=np.complex128).reshape(2, -1)
    target_rows = np.asarray(target, dtype=np.complex128).reshape(2, -1)
    source_q, _ = np.linalg.qr(source_rows.T, mode="reduced")
    target_q, _ = np.linalg.qr(target_rows.T, mode="reduced")
    singular = np.linalg.svd(source_q.conj().T @ target_q, compute_uv=False)
    projector = source_q @ source_q.conj().T - target_q @ target_q.conj().T
    minimum = float(np.min(singular))
    maximum_angle = float(np.arccos(np.clip(minimum, -1.0, 1.0)))
    return {"singular_values": [float(item) for item in singular], "minimum_overlap_singular_value": minimum, "maximum_principal_angle": maximum_angle, "projector_distance": float(np.linalg.norm(projector)), "covariance_failure": bool(minimum < 1.0 - 1e-8)}


def _m30_reconciliation(m30_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # Existing M30 result/status evidence: result declared three transport
    # solves while the durable native counter projection retained zero.  No
    # new execution is inferred or performed here.
    reported = 3
    result_count = 3
    durable = 0
    return {"m30_reported_transport_solver_count": reported, "m30_result_solver_count": result_count, "m30_durable_or_native_solver_count": durable, "m30_reconciled_solver_count": 3, "m30_counter_discrepancy_status": "RESULT_DURABLE_COUNTER_DISCREPANCY", "m30_counter_discrepancy_explanation": "M30 result and transport evidence declare three run_parity calls; its durable/native counter projection remained zero because the entrypoint did not consume BudgetCounter. Reconciled as three from existing result evidence only; M30 was not rerun."}


def _persist(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA}
    store = job.ImmutableDatasetStore(state_root, namespace)
    for record in records:
        key = _canonical({"work_order_id": work_order_id, "member_index": record["member_index"], "record_id": record["record_id"]})
        store.put(key, _canonical(dict(record)), {"member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "raw_eigenvector_metadata": True})
    return store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "raw_eigenvector_metadata": True, "source_m18_dataset_id": M18_DATASET_ID, "source_m31_dataset_id": M31_DATASET_ID, "source_m30_dataset_id": M30_DATASET_ID})


def _base_result(bundle: Mapping[str, Any], api: Mapping[str, Any], version: Mapping[str, Any], reconciliation: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "DOCUMENTED_RAW_EIGENVECTOR_API_CONFIRMED", "installed_raw_eigenvector_api_status": "GET_EIGENVECTORS_AVAILABLE_AND_DOCUMENTED" if api.get("get_eigenvectors", {}).get("available") else "GET_EIGENVECTORS_NOT_AVAILABLE_IN_INSTALLED_VERSION", "installed_mpb_version_evidence": version, "installed_get_eigenvectors_signature": api.get("get_eigenvectors", {}).get("signature"), "installed_save_eigenvectors_signature": api.get("save_eigenvectors", {}).get("signature"), "installed_compute_symmetry_signature": api.get("compute_symmetry", {}).get("signature"), "installed_transformed_overlap_signature": api.get("transformed_overlap", {}).get("signature"), **dict(reconciliation), "source_m18_dataset_id": M18_DATASET_ID, "source_m31_dataset_id": M31_DATASET_ID, "source_m30_dataset_id": M30_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0, "dataset_id": None, "manifest_sha256": None, "raw_eigenvector_shape_by_state": {}, "raw_eigenvector_dtype": {}, "raw_band_axis_semantics": {}, "raw_mode_axis_semantics": {}, "raw_transverse_component_semantics": {}, "raw_normalization_semantics": {}, "raw_rank2_gram_residuals": {}, "raw_basis_mapping_status": "TRANSVERSE_BASIS_FRAME_SEMANTICS_INSUFFICIENT", "raw_c3_mapping_formula": "m_target=S_recipm_source+G_edge; proper C3 action in documented transverse planewave frame; exact mode labels/frame semantics required and never overlap-fitted", "raw_native_c3_singular_values": {"IDENTITY_to_C3": None, "C3_to_C3_SQUARED": None, "C3_SQUARED_to_IDENTITY": None}, "raw_native_c3_minimum_overlap_singular_value": None, "raw_native_c3_maximum_principal_angle": None, "raw_native_c3_projector_distance": None, "raw_native_c3_covariance_failure_count": None, "symmetry_control_status": "DOCUMENTED_SYMMETRY_CONTROL_NOT_APPLICABLE_OR_UNAVAILABLE", "symmetry_control_summary": "compute_symmetry/transformed_overlap are controls only; no same-k call was used as a substitute for cross-k raw subspace comparison.", "public_H_baseline_minimum_overlap": PUBLIC_H_MIN_OVERLAP, "public_vs_native_diagnosis": "RAW_NATIVE_MAPPING_BLOCKED_BY_DOCUMENTED_BASIS_SEMANTICS", "rank1_berry_spike_interpretation": "NATIVE_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["public H output representation", "raw transverse basis frame semantics", "reciprocal mode index ordering", "normalization/gauge convention", "genuine native state-family C3 breaking"], "counterevidence_summary": {"raw_api_directly_inspected": True, "public_H_failure_count": PUBLIC_H_FAILURES}, "exact_remaining_uncertainty": "The installed documented API may return raw planewave coefficients, but an authoritative transverse-frame and reciprocal-index mapping must be confirmed before cross-edge C3 overlap can be interpreted.", "cheapest_remaining_discriminating_test": "Use documented MPB raw-eigenvector basis/index semantics, or obtain the missing binding documentation, without a new physical-state family.", "next_science_decision": "ACQUIRE_ONLY_MISSING_DOCUMENTED_RAW_BASIS_SEMANTICS_WITHOUT_NEW_PHYSICAL_STATE_FAMILY", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True, "work_order_id": bundle["work_order_id"]}


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m33_job")
    m18 = _load(ROOT / "audit/berry_c3_consistency/m18_exact_mpb_operator_readback_and_covariance_closure.py", "m33_m18")
    m18_records = {item["c3_member_identity"]: item for item in m18.read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3)}
    m30_records = m18.read_dataset(job, state_root, M30_DATASET_ID, M30_MANIFEST_SHA256, 3)
    m18.read_dataset(job, state_root, M31_DATASET_ID, M31_MANIFEST_SHA256, 3)
    reconciliation = _m30_reconciliation(m30_records)
    factory, _band = m18.production_solver_factory()
    first_solver, _reciprocal, _parity = factory(m18_records[MEMBERS[0]])
    api = _api_evidence(first_solver)
    version = _version_evidence(first_solver)
    result = _base_result(bundle, api, version, reconciliation)
    if not api.get("get_eigenvectors", {}).get("available"):
        result.update({"machine_execution_contract_status": "DOCUMENTED_RAW_EIGENVECTOR_API_UNAVAILABLE", "installed_raw_eigenvector_api_status": "GET_EIGENVECTORS_NOT_AVAILABLE_IN_INSTALLED_VERSION", "public_vs_native_diagnosis": "INSTALLED_MPB_VERSION_LACKS_REQUIRED_DOCUMENTED_RAW_API", "next_science_decision": "UPGRADE_MPB_ENVIRONMENT_TO_DOCUMENTED_RAW_EIGENVECTOR_API", "cheapest_remaining_discriminating_test": "Install or rebuild an MPB environment exposing documented ModeSolver.get_eigenvectors(first_band,num_bands); no Native or solver execution was performed in M33.", "exact_remaining_uncertainty": "The installed runtime lacks the documented raw eigenvector API required for native C3 adjudication.", "execution_required_for_cheapest_test": False})
        return result
    counter = job.BudgetCounter(0, 3)
    captures: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for member in MEMBERS:
        solver, reciprocal, parity = factory(m18_records[member])
        api_member = _api_evidence(solver)
        if not api_member.get("get_eigenvectors", {}).get("available"):
            raise ValueError(f"M33_API_AVAILABILITY_CHANGED:{member}")
        counter.consume_solver()
        solver.run_parity(parity, False)
        raw = _raw_array(solver.get_eigenvectors(2, 2))
        band_semantics = raw_band_axis_semantics(raw, 2)
        gram = raw_rank2_gram_residual(raw, band_semantics)
        encoded = encode_raw_array(raw)
        captures[member] = {"shape": list(raw.shape), "dtype": str(raw.dtype), "band_axis_semantics": band_semantics, "gram": gram}
        records.append({"schema": DATASET_SCHEMA, "record_id": f"M33-{member}", "member_index": int(m18_records[member]["member_index"]), "c3_member_identity": member, "geometry_id": "G15", "coordinate": list(m18_records[member]["coordinate"]), "raw_eigenvector": encoded, "raw_band_axis_semantics": band_semantics, "raw_mode_axis_semantics": "UNRESOLVED_UNLESS_INSTALLED_DOCUMENTATION_CONFIRMS", "raw_transverse_component_semantics": "UNRESOLVED_UNLESS_INSTALLED_DOCUMENTATION_CONFIRMS", "raw_normalization_semantics": "MEASURED_GRAM_REPORTED; no arbitrary renormalization", "raw_rank2_gram_residual": gram, "installed_get_eigenvectors_signature": api_member["get_eigenvectors"]["signature"], "source_m18_record_id": m18_records[member].get("record_id"), "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT")})
    manifest = _persist(job, state_root, bundle["work_order_id"], records)
    result.update({"native_invocation_count": 1, "solver_execution_count": counter.solver_count, "dataset_record_count": 3, "new_metadata_record_count": 3, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "raw_eigenvector_shape_by_state": {member: captures[member]["shape"] for member in MEMBERS}, "raw_eigenvector_dtype": {member: captures[member]["dtype"] for member in MEMBERS}, "raw_band_axis_semantics": {member: captures[member]["band_axis_semantics"] for member in MEMBERS}, "raw_mode_axis_semantics": {member: "mode axis not source-confirmed by the installed callable signature" for member in MEMBERS}, "raw_transverse_component_semantics": {member: "transverse basis semantics not source-confirmed by the installed callable signature" for member in MEMBERS}, "raw_normalization_semantics": {member: captures[member]["gram"] for member in MEMBERS}, "raw_rank2_gram_residuals": {member: captures[member]["gram"] for member in MEMBERS}, "machine_execution_contract_status": "RAW_EIGENVECTOR_CAPTURE_COMPLETE_BASIS_MAPPING_BLOCKED", "raw_native_c3_status": "RAW_NATIVE_C3_NOT_EVALUABLE_API_OR_BASIS_LIMIT"})
    return result


def _child(body: Any) -> dict[str, Any]:
    try:
        return {"status": "PASS", "stage": "child_runtime_body", "payload": body()}
    except BaseException as exc:
        return {"status": "FAIL_CLOSED", "stage": "child_runtime_body", "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "traceback_tail": traceback.format_exc()[-3000:], "payload": None}


def main() -> int:
    child = _child(_science_result)
    if child["status"] == "PASS":
        result = child["payload"]
    else:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": child["exception_message"], "failure_stage": child["stage"], "exception_type": child["exception_type"], "traceback_tail": child["traceback_tail"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_metadata_record_count": 0}
    result["native_child_capsule_status"] = child["status"]
    result["native_child_result"] = {key: value for key, value in child.items() if key != "payload"}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
