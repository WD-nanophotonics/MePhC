"""Bounded solver-free reduction runtime for the Thin Input Bundle V2 contract."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from audit.local_affine.local_affine_snapshot_codec import decode_snapshot
from mephc.phase_space_geometry import (
    HState, PhaseSpaceStateIdentity, ReferenceCellIdentity,
    fixed_q_frequency_derivative, h_state_from_normalized_vectors,
    make_mixed_diamond, rank1_mixed_curvature, reverse_mixed_curvature,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "audit" / "local_affine" / "p66_p64_v2_binding_plan.json"
GRAPH_PATH = ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json"
PLAN_SCHEMA = "mephc-local-affine-p66-p64-v2-binding-plan-v1"
SOURCE_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P64-FROZEN-13-STATE-LIVE-ACQUISITION-20260830-428"
THIN_BUNDLE_SCHEMA = "mephc-thin-input-bundle-v1"
RESULT_SCHEMA = "mephc-local-affine-solver-free-two-scale-reduction-v1"
_HEX64 = frozenset("0123456789abcdef")
_IDENTITY_FIELDS = (
    "state_id", "role", "public_q", "s", "canonical_state_identity",
    "canonical_state_identity_sha256", "solver_configuration",
    "reciprocal_metadata", "reference_cell_contract_sha256", "frequencies",
    "raw_norms", "normalized_vector_digest", "request_graph_sha256",
    "science_source_commit", "payload_sha256",
)
_SOLVER_CONFIGURATION = {
    "resolution": 64, "num_bands": 6, "polarization": "TM",
    "eigensolver_tolerance": 1e-7, "mesh_size": 3,
    "deterministic": True, "phase_callback": None,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _finite_vector(value: Any, size: int, code: str) -> tuple[float, ...]:
    array = np.asarray(value, dtype=float)
    _require(array.shape == (size,) and bool(np.all(np.isfinite(array))), code)
    return tuple(float(item) for item in array)


def _vector_digest(vectors: Any) -> str:
    values = [[[float(item.real), float(item.imag)] for item in np.asarray(vector, dtype=np.complex128)] for vector in vectors]
    return hashlib.sha256(_canonical(values)).hexdigest()


def load_binding_plan() -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    _require(plan.get("schema") == PLAN_SCHEMA, "P71_BINDING_PLAN_SCHEMA_INVALID")
    _require(plan.get("source_work_order_id") == SOURCE_WORK_ORDER_ID, "P71_SOURCE_WORK_ORDER_ID_INVALID")
    bindings = plan.get("bindings")
    _require(isinstance(bindings, list) and len(bindings) == 13, "P71_BINDING_COUNT_INVALID")
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    states = graph.get("states")
    _require(graph.get("state_count") == 13 and isinstance(states, list) and len(states) == 13, "P71_GRAPH_INVALID")
    keys: set[str] = set()
    for binding, state in zip(bindings, states):
        _require(all(binding.get(key) == state.get(key) for key in ("state_id", "role", "public_q", "s")), "P71_BINDING_GRAPH_MISMATCH")
        identity = {"work_order_id": SOURCE_WORK_ORDER_ID, "state_id": binding["state_id"], "role": binding["role"], "public_q": binding["public_q"], "s": binding["s"]}
        key = binding.get("record_key_sha256")
        _require(isinstance(key, str) and len(key) == 64 and set(key) <= _HEX64, "P71_RECORD_KEY_FORMAT_INVALID")
        _require(hashlib.sha256(_canonical(identity)).hexdigest() == key, "P71_RECORD_KEY_DERIVATION_INVALID")
        keys.add(key)
    _require(len(keys) == 13, "P71_RECORD_KEYS_NOT_UNIQUE")
    return plan


def load_bundle() -> tuple[dict[str, Any], Path]:
    raw_path = os.environ.get("MEPHC_INPUT_BUNDLE")
    _require(isinstance(raw_path, str) and raw_path, "P71_INPUT_BUNDLE_MISSING")
    bundle_path = Path(raw_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    _require(bundle.get("schema") == THIN_BUNDLE_SCHEMA, "P71_INPUT_BUNDLE_SCHEMA_INVALID")
    contract_sha = os.environ.get("MEPHC_SCIENCE_CONTRACT_SHA256")
    if contract_sha is not None:
        _require(bundle.get("contract_sha256") == contract_sha, "P71_CONTRACT_SHA_MISMATCH")
    _require(isinstance(bundle.get("work_order_id"), str) and bundle["work_order_id"], "P71_WORK_ORDER_ID_INVALID")
    datasets = bundle.get("datasets")
    _require(isinstance(datasets, list) and len(datasets) == 13, "P71_DATASET_BINDINGS_COUNT_INVALID")
    return bundle, bundle_path


def validate_runtime_contract(bundle: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    _require(bundle.get("schema") == THIN_BUNDLE_SCHEMA, "P71_INPUT_SCHEMA_INVALID")
    _require(isinstance(bundle.get("work_order_id"), str) and bundle["work_order_id"], "P71_WORK_ORDER_ID_INVALID")
    datasets = bundle.get("datasets")
    _require(isinstance(datasets, list) and len(datasets) == plan["record_count"], "P71_RECORD_COUNT_INVALID")
    keys = [item.get("record_key_sha256") for item in datasets if isinstance(item, dict)]
    _require(len(keys) == len(set(keys)) == plan["unique_record_key_count"], "P71_RECORD_KEY_SET_INVALID")
    return {"input_work_order_id": bundle["work_order_id"], "source_work_order_id": plan["source_work_order_id"], "source_dataset_id": plan["source_dataset_id"], "source_manifest_sha256": plan["source_manifest_sha256"], "record_count": len(datasets), "binding_plan_schema": plan["schema"]}


def validate_bound_dataset_descriptors(bundle: dict[str, Any], plan: dict[str, Any]) -> None:
    for item in bundle["datasets"]:
        _require(isinstance(item, dict), "P71_DATASET_DESCRIPTOR_INVALID")
        for field in ("dataset_id", "manifest_sha256", "record_key_sha256", "payload_sha256", "payload_size_bytes", "identity", "payload_file"):
            _require(field in item, f"P71_DATASET_DESCRIPTOR_MISSING:{field}")
        _require(item["dataset_id"] == plan["source_dataset_id"], "P71_DATASET_ID_MISMATCH")
        _require(item["manifest_sha256"] == plan["source_manifest_sha256"], "P71_MANIFEST_HASH_MISMATCH")
        key = item["record_key_sha256"]
        _require(isinstance(key, str) and len(key) == 64 and set(key) <= _HEX64, "P71_RECORD_KEY_FORMAT_INVALID")
        payload_sha = item["payload_sha256"]
        _require(isinstance(payload_sha, str) and len(payload_sha) == 64 and set(payload_sha) <= _HEX64, "P71_PAYLOAD_HASH_FORMAT_INVALID")
        _require(isinstance(item["payload_size_bytes"], int) and not isinstance(item["payload_size_bytes"], bool) and item["payload_size_bytes"] >= 0, "P71_PAYLOAD_SIZE_INVALID")
        _require(isinstance(item["identity"], dict), "P71_DATASET_IDENTITY_INVALID")
        _require(isinstance(item["payload_file"], str) and item["payload_file"] and Path(item["payload_file"]).name == item["payload_file"], "P71_PAYLOAD_DESCRIPTOR_INVALID")


def _payload_bytes(bundle_path: Path, item: dict[str, Any]) -> bytes:
    payload = (bundle_path.parent / item["payload_file"]).read_bytes()
    _require(len(payload) == item["payload_size_bytes"], "P71_PAYLOAD_LENGTH_MISMATCH")
    _require(hashlib.sha256(payload).hexdigest() == item["payload_sha256"], "P71_PAYLOAD_HASH_MISMATCH")
    return payload


def _validate_identity_digest(identity: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    for field in _IDENTITY_FIELDS:
        _require(field in identity, f"P71_IDENTITY_FIELD_MISSING:{field}")
    _require(identity["state_id"] == binding["state_id"], "P71_RECORD_STATE_ID_MISMATCH")
    _require(identity["role"] == binding["role"], "P71_RECORD_ROLE_MISMATCH")
    _require(tuple(float(x) for x in identity["public_q"]) == tuple(float(x) for x in binding["public_q"]), "P71_RECORD_PUBLIC_Q_MISMATCH")
    _require(float(identity["s"]) == float(binding["s"]), "P71_RECORD_S_MISMATCH")
    canonical_identity = identity["canonical_state_identity"]
    _require(isinstance(canonical_identity, dict), "P71_CANONICAL_IDENTITY_INVALID")
    _require(hashlib.sha256(_canonical(canonical_identity)).hexdigest() == identity["canonical_state_identity_sha256"], "P71_CANONICAL_IDENTITY_DIGEST_MISMATCH")
    _require(tuple(float(x) for x in canonical_identity["public_q"]) == tuple(float(x) for x in identity["public_q"]), "P71_CANONICAL_PUBLIC_Q_MISMATCH")
    _require(float(canonical_identity["s"]) == float(identity["s"]), "P71_CANONICAL_S_MISMATCH")
    _require(canonical_identity["public_q"] == binding["public_q"] and float(canonical_identity["s"]) == float(binding["s"]), "P71_CANONICAL_BINDING_MISMATCH")
    _require(identity["solver_configuration"] == _SOLVER_CONFIGURATION, "P71_SOLVER_CONFIGURATION_MISMATCH")
    _require(isinstance(identity["science_source_commit"], str) and identity["science_source_commit"], "P71_SOURCE_COMMIT_MISSING")
    return canonical_identity


def _validate_snapshot_identity(snapshot: Any, item: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    identity = item["identity"]
    canonical_identity = _validate_identity_digest(identity, binding)
    _require(identity["payload_sha256"] == item["payload_sha256"], "P71_IDENTITY_PAYLOAD_HASH_MISMATCH")
    _require(identity["request_graph_sha256"] == hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest(), "P71_REQUEST_GRAPH_HASH_MISMATCH")
    provenance = dict(getattr(snapshot, "provenance", {}))
    reference = provenance.get("local_affine_reference_cell_contract")
    _require(isinstance(reference, dict), "P71_REFERENCE_CELL_CONTRACT_MISSING")
    _require(hashlib.sha256(_canonical(reference)).hexdigest() == identity["reference_cell_contract_sha256"], "P71_REFERENCE_CELL_DIGEST_MISMATCH")
    _require(provenance.get("mpb_k_point") == identity["reciprocal_metadata"], "P71_RECIPROCAL_METADATA_MISMATCH")
    frequencies = [float(value) for value in np.asarray(snapshot.frequencies, dtype=float)]
    raw_norms = [float(value) for value in np.asarray(snapshot.raw_norms, dtype=float)]
    _require(frequencies == [float(value) for value in identity["frequencies"]], "P71_FREQUENCY_METADATA_MISMATCH")
    _require(raw_norms == [float(value) for value in identity["raw_norms"]], "P71_RAW_NORM_METADATA_MISMATCH")
    _require(_vector_digest(snapshot.normalized_vectors) == identity["normalized_vector_digest"], "P71_NORMALIZED_VECTOR_DIGEST_MISMATCH")
    return canonical_identity


def validate_record_identity(identity: dict[str, Any], binding: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(identity, dict), "P71_DATASET_IDENTITY_INVALID")
    _require(identity.get("payload_sha256") == descriptor.get("payload_sha256"), "P71_IDENTITY_PAYLOAD_HASH_MISMATCH")
    return _validate_identity_digest(identity, binding)


def _identity(item: dict[str, Any], snapshot: Any, binding: dict[str, Any]) -> PhaseSpaceStateIdentity:
    canonical_identity = _validate_snapshot_identity(snapshot, item, binding)
    reference = snapshot.provenance["local_affine_reference_cell_contract"]
    ref = ReferenceCellIdentity(
        resolution=int(reference["resolution"]), spatial_shape=tuple(int(x) for x in reference["spatial_shape"]), lattice_size=tuple(reference["lattice_size"]),
        component_order=str(reference["component_order"]), component_basis=str(reference["component_basis"]), mu_contract=str(reference["mu_contract"]),
        orientation_sign=int(reference["orientation_sign"]), fractional_material_indexing_identity=str(reference["fractional_material_indexing_identity"]), reference_cell_identity=str(reference["reference_cell_identity"]),
    )
    solver_identity = hashlib.sha256(_canonical(_SOLVER_CONFIGURATION)).hexdigest()
    return PhaseSpaceStateIdentity(
        public_q=_finite_vector(canonical_identity["public_q"], 2, "P71_PUBLIC_Q_INVALID"), s=float(canonical_identity["s"]),
        derived_kappa=_finite_vector(canonical_identity["derived_kappa"], 2, "P71_DERIVED_KAPPA_INVALID"),
        A_s=tuple(tuple(float(x) for x in row) for row in np.asarray(canonical_identity["A_s"], dtype=float)),
        F_s=tuple(tuple(float(x) for x in row) for row in np.asarray(canonical_identity["F_s"], dtype=float)),
        geometry_identity=str(canonical_identity["geometry_digest"]), reference_cell=ref, solver_configuration_identity=solver_identity,
    )


def resolve_states(bundle: dict[str, Any], bundle_path: Path, plan: dict[str, Any]) -> dict[str, HState]:
    by_key = {item["record_key_sha256"]: item for item in bundle["datasets"]}
    _require(len(by_key) == 13, "P71_RECORD_KEYS_NOT_UNIQUE")
    states: dict[str, HState] = {}
    for binding in plan["bindings"]:
        item = by_key.get(binding["record_key_sha256"])
        _require(item is not None, "P71_RECORD_BINDING_MISSING")
        snapshot = decode_snapshot(_payload_bytes(bundle_path, item))
        identity = _identity(item, snapshot, binding)
        states[binding["role"]] = h_state_from_normalized_vectors(identity, snapshot.normalized_vectors[0], frequencies=(float(snapshot.frequencies[0]),), band_indices=(0,))
    _require(len(states) == 13, "P71_STATE_ROLE_SET_INVALID")
    return states


def _diamond(states: dict[str, HState], prefix: str, axis: int, h_q: float, h_s: float) -> Any:
    return make_mixed_diamond(
        plus_q=states[f"{prefix}_PLUS_Q{'X' if axis == 0 else 'Y'}"], minus_q=states[f"{prefix}_MINUS_Q{'X' if axis == 0 else 'Y'}"],
        plus_s=states[f"{prefix}_PLUS_S"], minus_s=states[f"{prefix}_MINUS_S"], axis=axis, h_q=h_q, h_s=h_s,
        q_center=states["CENTER"].identity.public_q, s_center=states["CENTER"].identity.s,
    )


def reduce_states(states: dict[str, HState]) -> dict[str, Any]:
    roles = {"CENTER", "PRIMARY_PLUS_QX", "PRIMARY_MINUS_QX", "PRIMARY_PLUS_QY", "PRIMARY_MINUS_QY", "PRIMARY_PLUS_S", "PRIMARY_MINUS_S", "REFINED_PLUS_QX", "REFINED_MINUS_QX", "REFINED_PLUS_QY", "REFINED_MINUS_QY", "REFINED_PLUS_S", "REFINED_MINUS_S"}
    _require(set(states) == roles, "P71_STATE_ROLE_SET_INVALID")
    primary = {axis: rank1_mixed_curvature(_diamond(states, "PRIMARY", axis, 0.001, 0.02)) for axis in (0, 1)}
    refined = {axis: rank1_mixed_curvature(_diamond(states, "REFINED", axis, 0.0005, 0.01)) for axis in (0, 1)}
    reverse = {axis: reverse_mixed_curvature(_diamond(states, "PRIMARY", axis, 0.001, 0.02)) for axis in (0, 1)}
    derivative_primary = fixed_q_frequency_derivative(states["PRIMARY_PLUS_S"], states["PRIMARY_MINUS_S"], band_index=0, h_s=0.02)
    derivative_refined = fixed_q_frequency_derivative(states["REFINED_PLUS_S"], states["REFINED_MINUS_S"], band_index=0, h_s=0.01)
    deltas = {f"q{axis}": abs(primary[axis].omega_qs - refined[axis].omega_qs) for axis in (0, 1)}
    reverse_ok = all(math.isclose(reverse[axis].omega_qs, -primary[axis].omega_qs, rel_tol=0.0, abs_tol=1e-12) for axis in (0, 1))
    return {"schema": RESULT_SCHEMA, "runtime_status": "BUNDLE_BOUND_SOLVER_FREE_REDUCTION", "state_count": len(states), "rank1_band_index": 0, "primary": {f"q{axis}": value.to_dict() for axis, value in primary.items()}, "refined": {f"q{axis}": value.to_dict() for axis, value in refined.items()}, "primary_refined_abs_delta_omega_qs": deltas, "fixed_q_frequency_derivative": {"primary": derivative_primary, "refined": derivative_refined}, "reverse_sign_check": {"status": "PASS" if reverse_ok else "FAIL", "expected": "reverse omega_qs = -forward omega_qs"}, "finite_result": all(math.isfinite(float(value)) for value in (*deltas.values(), derivative_primary, derivative_refined)), "scientific_acceptance_status": "PASS" if reverse_ok else "FAIL", "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False}


def _future_result(status: str, *, failed_stage: str | None = None, failure_code: str | None = None, exception_type: str | None = None) -> dict[str, Any]:
    result = {"schema": RESULT_SCHEMA, "status": status, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False}
    if failed_stage is not None:
        result.update({"failed_stage": failed_stage, "failure_code": failure_code or "P71_REDUCTION_FAILED", "exception_type": exception_type or "ValueError"})
    return result


def main() -> int:
    result_path = os.environ.get("MEPHC_RESULT_PATH")
    _require(isinstance(result_path, str) and result_path, "P71_RESULT_PATH_MISSING")
    try:
        bundle, bundle_path = load_bundle()
        plan = load_binding_plan()
        provenance = validate_runtime_contract(bundle, plan)
        validate_bound_dataset_descriptors(bundle, plan)
        result = reduce_states(resolve_states(bundle, bundle_path, plan))
        result["provenance"] = provenance
    except Exception as exc:
        result = _future_result("FAIL", failed_stage="bundle-or-reduction", failure_code=str(exc), exception_type=type(exc).__name__)
    Path(result_path).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
