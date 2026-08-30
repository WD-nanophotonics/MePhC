"""Bounded solver-free reduction runtime for the Thin Input Bundle V2 contract."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
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
_REQUIRED_REFERENCE_CELL_FIELDS = (
    "representation", "bloch_phase_excluded", "resolution", "spatial_shape",
    "lattice_size", "component_order", "component_basis", "mu_contract",
    "orientation_sign", "fractional_material_indexing_identity",
    "reference_cell_identity",
)


class ReferenceCellContractDiagnosticError(ValueError):
    """Bounded reference-cell metadata failure that preserves state context."""

    def __init__(
        self,
        code: str,
        *,
        state_id: Any,
        role: Any,
        observed_type: str,
        missing_fields: tuple[str, ...] = (),
        observed_keys: tuple[str, ...] = (),
    ) -> None:
        self.code = code
        self.state_id = str(state_id) if state_id is not None else "<unknown>"
        self.role = str(role) if role is not None else None
        self.observed_type = observed_type
        self.missing_fields = missing_fields
        self.observed_keys = observed_keys
        details = [code, f"state_id={self.state_id}", f"observed_type={observed_type}"]
        if self.role is not None:
            details.append(f"role={self.role}")
        if missing_fields:
            details.append(f"missing_fields={','.join(missing_fields)}")
        if observed_keys:
            details.append(f"observed_keys={','.join(observed_keys)}")
        super().__init__(";".join(details))


class ReferenceCellIdentityDiagnosticError(ValueError):
    """Bounded reference-cell identity value/type failure with state context."""

    def __init__(
        self,
        code: str,
        *,
        state_id: Any,
        role: Any,
        mismatch_fields: tuple[str, ...],
        observed_values: dict[str, Any],
        observed_types: dict[str, str],
    ) -> None:
        self.code = code
        self.state_id = str(state_id) if state_id is not None else "<unknown>"
        self.role = str(role) if role is not None else "<unknown>"
        self.mismatch_fields = tuple(sorted(mismatch_fields))
        self.observed_values = observed_values
        self.observed_types = observed_types
        details = [
            code, f"state_id={self.state_id}", f"role={self.role}",
            f"mismatch_fields={','.join(self.mismatch_fields)}",
        ]
        super().__init__(";".join(details))


class ReverseOrientationDiagnosticError(ValueError):
    """Bounded first-diamond reverse-orientation failure diagnostics."""

    def __init__(self, *, diamond: str, diagnostics: dict[str, float]) -> None:
        self.code = "P72_REVERSE_ORIENTATION_SIGN_MISMATCH"
        self.diamond = diamond
        self.diagnostics = diagnostics
        super().__init__(f"{self.code};diamond={diamond}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _normalize_runtime_provenance(value: Any) -> Any:
    """Build a detached P64-canonical view of frozen JSON-safe provenance."""
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            _require(isinstance(key, str), "P78_PROVENANCE_KEY_INVALID")
            normalized[key] = _normalize_runtime_provenance(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_normalize_runtime_provenance(item) for item in value]
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        _require(math.isfinite(value), "P78_PROVENANCE_NONFINITE_FLOAT")
        return value
    raise ValueError("P78_PROVENANCE_VALUE_UNSUPPORTED")


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


def _reference_cell_contract(snapshot: Any, *, state_id: Any = None, role: Any = None) -> Mapping[str, Any]:
    provenance = _normalize_runtime_provenance(getattr(snapshot, "provenance", {}))
    _require(isinstance(provenance, dict), "P78_PROVENANCE_ROOT_INVALID")
    reference = provenance.get("local_affine_reference_cell_contract")
    observed_type = type(reference).__name__
    if not isinstance(reference, Mapping):
        code = "P71_REFERENCE_CELL_CONTRACT_MISSING" if reference is None else "P74_REFERENCE_CELL_CONTRACT_NOT_MAPPING"
        raise ReferenceCellContractDiagnosticError(
            code, state_id=state_id, role=role, observed_type=observed_type,
        )
    observed_keys = tuple(sorted(str(key) for key in reference.keys()))
    missing_fields = tuple(sorted(set(_REQUIRED_REFERENCE_CELL_FIELDS) - set(reference)))
    if missing_fields:
        raise ReferenceCellContractDiagnosticError(
            "P72_REFERENCE_CELL_FIELD_MISSING", state_id=state_id, role=role,
            observed_type=observed_type, missing_fields=missing_fields,
            observed_keys=observed_keys,
        )
    return reference


def _bounded_identity_value(field: str, value: Any) -> Any:
    if field == "spatial_shape":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return ",".join(str(item)[:32] for item in value)
        return f"{type(value).__name__}:{_bounded_text(value)}"
    if isinstance(value, str):
        return value[:128]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"{type(value).__name__}:{_bounded_text(value)}"


def _bounded_text(value: Any) -> str:
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        text = type(value).__name__
    return text[:128]


def _validate_reference_cell_identity_values(reference: Mapping[str, Any], *, state_id: Any, role: Any) -> None:
    expected = {
        "representation": "mpb_periodic_h_l2_v1",
        "bloch_phase_excluded": True,
        "resolution": 64,
        "spatial_shape": [64, 64],
    }
    mismatch_fields = tuple(sorted(
        field for field, expected_value in expected.items()
        if type(reference[field]) is not type(expected_value) or reference[field] != expected_value
    ))
    if mismatch_fields:
        observed_values = {field: _bounded_identity_value(field, reference[field]) for field in expected}
        observed_types = {field: type(reference[field]).__name__ for field in expected}
        raise ReferenceCellIdentityDiagnosticError(
            "P72_REFERENCE_CELL_IDENTITY_INVALID", state_id=state_id, role=role,
            mismatch_fields=mismatch_fields, observed_values=observed_values,
            observed_types=observed_types,
        )


def validate_snapshot_structure(snapshot: Any, *, state_id: Any = None, role: Any = None) -> None:
    _require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3, "P72_SNAPSHOT_SHAPE_INVALID")
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    raw_norms = np.asarray(snapshot.raw_norms, dtype=float)
    _require(frequencies.shape == (6,) and bool(np.all(np.isfinite(frequencies))) and bool(np.all(frequencies > 0.0)), "P72_FREQUENCIES_INVALID")
    _require(raw_norms.shape == (6,) and bool(np.all(np.isfinite(raw_norms))) and bool(np.all(raw_norms > 0.0)), "P72_RAW_NORMS_INVALID")
    _require(len(snapshot.normalized_vectors) == 6, "P72_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        _require(values.ndim == 1 and bool(np.all(np.isfinite(values))) and math.isclose(float(np.linalg.norm(values)), 1.0, rel_tol=0.0, abs_tol=1e-10), "P72_VECTOR_INVALID")
    gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
    _require(gram.shape == (6, 6) and bool(np.all(np.isfinite(gram))), "P72_GRAM_INVALID")
    provenance = _normalize_runtime_provenance(getattr(snapshot, "provenance", {}))
    _require(isinstance(provenance, dict), "P78_PROVENANCE_ROOT_INVALID")
    _require(provenance.get("representation") == "mpb_periodic_h_l2_v1", "P72_REPRESENTATION_INVALID")
    reference = _reference_cell_contract(snapshot, state_id=state_id, role=role)
    _validate_reference_cell_identity_values(reference, state_id=state_id, role=role)
    _require(reference["component_order"] == "supplied final axis order" and reference["component_basis"] == "LAB_CARTESIAN" and reference["mu_contract"] == "MU1_NONMAGNETIC" and reference["orientation_sign"] == 1, "P72_REFERENCE_CELL_PHYSICS_INVALID")


def _validate_snapshot_identity(snapshot: Any, item: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    identity = item["identity"]
    canonical_identity = _validate_identity_digest(identity, binding)
    validate_snapshot_structure(snapshot, state_id=identity.get("state_id"), role=identity.get("role"))
    _require(identity["payload_sha256"] == item["payload_sha256"], "P71_IDENTITY_PAYLOAD_HASH_MISMATCH")
    _require(identity["request_graph_sha256"] == hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest(), "P71_REQUEST_GRAPH_HASH_MISMATCH")
    provenance = _normalize_runtime_provenance(getattr(snapshot, "provenance", {}))
    _require(isinstance(provenance, dict), "P78_PROVENANCE_ROOT_INVALID")
    _require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3, "P72_SNAPSHOT_SHAPE_INVALID")
    frequencies_array = np.asarray(snapshot.frequencies, dtype=float)
    raw_norms_array = np.asarray(snapshot.raw_norms, dtype=float)
    _require(frequencies_array.shape == (6,) and bool(np.all(np.isfinite(frequencies_array))) and bool(np.all(frequencies_array > 0.0)), "P72_FREQUENCIES_INVALID")
    _require(raw_norms_array.shape == (6,) and bool(np.all(np.isfinite(raw_norms_array))) and bool(np.all(raw_norms_array > 0.0)), "P72_RAW_NORMS_INVALID")
    _require(len(snapshot.normalized_vectors) == 6, "P72_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        _require(values.ndim == 1 and bool(np.all(np.isfinite(values))) and math.isclose(float(np.linalg.norm(values)), 1.0, rel_tol=0.0, abs_tol=1e-10), "P72_VECTOR_INVALID")
    gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
    _require(gram.shape == (6, 6) and bool(np.all(np.isfinite(gram))), "P72_GRAM_INVALID")
    reference = _reference_cell_contract(snapshot, state_id=identity.get("state_id"), role=identity.get("role"))
    _validate_reference_cell_identity_values(reference, state_id=identity.get("state_id"), role=identity.get("role"))
    _require(reference["component_order"] == "supplied final axis order" and reference["component_basis"] == "LAB_CARTESIAN" and reference["mu_contract"] == "MU1_NONMAGNETIC" and reference["orientation_sign"] == 1, "P72_REFERENCE_CELL_PHYSICS_INVALID")
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
    f_matrix = np.asarray(canonical_identity["F_s"], dtype=float)
    _require(f_matrix.shape == (2, 2) and bool(np.all(np.isfinite(f_matrix))), "P72_F_S_INVALID")
    _require(float(np.linalg.det(f_matrix)) > 0.0, "P72_DET_F_NONPOSITIVE")
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
    validate_cross_state_reference_cells(states)
    return states


def validate_cross_state_reference_cells(states: dict[str, HState]) -> None:
    reference_keys = {state.identity.reference_cell.compatibility_key() for state in states.values()}
    _require(len(reference_keys) == 1, "P72_REFERENCE_CELL_CROSS_STATE_MISMATCH")


def _reverse_orientation_diagnostics(name: str, forward: Any, reverse: Any) -> dict[str, float]:
    phase_sum = float(forward.phase + reverse.phase)
    omega_sum = float(forward.omega_qs + reverse.omega_qs)
    return {
        f"reverse_diag_{name}_forward_phase": float(forward.phase),
        f"reverse_diag_{name}_reverse_phase": float(reverse.phase),
        f"reverse_diag_{name}_forward_omega_qs": float(forward.omega_qs),
        f"reverse_diag_{name}_reverse_omega_qs": float(reverse.omega_qs),
        f"reverse_diag_{name}_signed_area_qs": float(forward.signed_area_qs),
        f"reverse_diag_{name}_minimum_link_singular_value_forward": float(forward.minimum_link_singular_value),
        f"reverse_diag_{name}_minimum_link_singular_value_reverse": float(reverse.minimum_link_singular_value),
        f"reverse_diag_{name}_maximum_link_principal_angle_forward": float(forward.maximum_link_principal_angle),
        f"reverse_diag_{name}_maximum_link_principal_angle_reverse": float(reverse.maximum_link_principal_angle),
        f"reverse_diag_{name}_direct_phase_sum": phase_sum,
        f"reverse_diag_{name}_direct_omega_sum": omega_sum,
        f"reverse_diag_{name}_wrapped_phase_sum": math.atan2(math.sin(phase_sum), math.cos(phase_sum)),
        f"reverse_diag_{name}_phase_antipode_distance": min(abs(abs(float(forward.phase)) - math.pi), abs(abs(float(reverse.phase)) - math.pi)),
        f"reverse_diag_{name}_absolute_reverse_phase_residual": abs(phase_sum),
        f"reverse_diag_{name}_absolute_reverse_omega_residual": abs(omega_sum),
    }


def _machine_precision_tolerance(value: float, derived: float) -> float:
    return math.ulp(float(value)) + math.ulp(float(derived))


def _reverse_omega_tolerance(signed_area_qs: float) -> float:
    _require(math.isfinite(float(signed_area_qs)) and float(signed_area_qs) != 0.0, "P82_SIGNED_AREA_ZERO_OR_NONFINITE")
    return 1e-12 / abs(float(signed_area_qs))


def _diamond(states: dict[str, HState], prefix: str, axis: int, h_q: float, h_s: float) -> Any:
    return make_mixed_diamond(
        plus_q=states[f"{prefix}_PLUS_Q{'X' if axis == 0 else 'Y'}"], minus_q=states[f"{prefix}_MINUS_Q{'X' if axis == 0 else 'Y'}"],
        plus_s=states[f"{prefix}_PLUS_S"], minus_s=states[f"{prefix}_MINUS_S"], axis=axis, h_q=h_q, h_s=h_s,
        q_center=states["CENTER"].identity.public_q, s_center=states["CENTER"].identity.s,
    )


def reduce_states(states: dict[str, HState]) -> dict[str, Any]:
    roles = {"CENTER", "PRIMARY_PLUS_QX", "PRIMARY_MINUS_QX", "PRIMARY_PLUS_QY", "PRIMARY_MINUS_QY", "PRIMARY_PLUS_S", "PRIMARY_MINUS_S", "REFINED_PLUS_QX", "REFINED_MINUS_QX", "REFINED_PLUS_QY", "REFINED_MINUS_QY", "REFINED_PLUS_S", "REFINED_MINUS_S"}
    _require(set(states) == roles, "P71_STATE_ROLE_SET_INVALID")
    diamonds = {
        "primary_qx": _diamond(states, "PRIMARY", 0, 0.001, 0.02),
        "primary_qy": _diamond(states, "PRIMARY", 1, 0.001, 0.02),
        "refined_qx": _diamond(states, "REFINED", 0, 0.0005, 0.01),
        "refined_qy": _diamond(states, "REFINED", 1, 0.0005, 0.01),
    }
    forward = {name: rank1_mixed_curvature(diamond) for name, diamond in diamonds.items()}
    reverse = {name: reverse_mixed_curvature(diamond) for name, diamond in diamonds.items()}
    for name in diamonds:
        left, right = forward[name], reverse[name]
        _require(all(math.isfinite(float(value)) for value in (left.phase, left.omega_qs, left.signed_area_qs, left.minimum_link_singular_value, left.maximum_link_principal_angle, right.phase, right.omega_qs, right.signed_area_qs, right.minimum_link_singular_value, right.maximum_link_principal_angle)), "P72_NONFINITE_WILSON_RESULT")
        diagnostics = _reverse_orientation_diagnostics(name, left, right)
        _require(left.signed_area_qs != 0.0 and right.signed_area_qs != 0.0, "P82_SIGNED_AREA_ZERO_OR_NONFINITE")
        _require(left.signed_area_qs == right.signed_area_qs, "P82_SIGNED_AREA_FORWARD_REVERSE_MISMATCH")
        omega_tolerance = _reverse_omega_tolerance(float(left.signed_area_qs))
        diagnostics[f"reverse_diag_{name}_omega_reverse_abs_tolerance"] = omega_tolerance
        if not math.isclose(right.phase, -left.phase, rel_tol=0.0, abs_tol=1e-12):
            raise ReverseOrientationDiagnosticError(diamond=name, diagnostics=diagnostics)
        for phase, omega in ((left.phase, left.omega_qs), (right.phase, right.omega_qs)):
            derived_omega = -float(phase) / float(left.signed_area_qs)
            _require(abs(float(omega) - derived_omega) <= _machine_precision_tolerance(float(omega), derived_omega), "P82_OMEGA_PHASE_CONSISTENCY_MISMATCH")
        if not math.isclose(right.omega_qs, -left.omega_qs, rel_tol=0.0, abs_tol=omega_tolerance):
            raise ReverseOrientationDiagnosticError(diamond=name, diagnostics=diagnostics)
    derivative_primary = fixed_q_frequency_derivative(states["PRIMARY_PLUS_S"], states["PRIMARY_MINUS_S"], band_index=0, h_s=0.02)
    derivative_refined = fixed_q_frequency_derivative(states["REFINED_PLUS_S"], states["REFINED_MINUS_S"], band_index=0, h_s=0.01)
    def relative_delta(left: float, right: float) -> float | None:
        denominator = abs(left) + abs(right)
        return None if denominator <= 0.0 else 2.0 * abs(left - right) / denominator

    scalars = {
        "omega_qx_s_primary": forward["primary_qx"].omega_qs, "omega_qx_s_refined": forward["refined_qx"].omega_qs,
        "omega_qy_s_primary": forward["primary_qy"].omega_qs, "omega_qy_s_refined": forward["refined_qy"].omega_qs,
        "domega_ds_primary": derivative_primary, "domega_ds_refined": derivative_refined,
    }
    absolute = {
        "abs_delta_omega_qx_s": abs(scalars["omega_qx_s_primary"] - scalars["omega_qx_s_refined"]),
        "abs_delta_omega_qy_s": abs(scalars["omega_qy_s_primary"] - scalars["omega_qy_s_refined"]),
        "abs_delta_domega_ds": abs(derivative_primary - derivative_refined),
    }
    relative = {
        "relative_delta_omega_qx_s": relative_delta(scalars["omega_qx_s_primary"], scalars["omega_qx_s_refined"]),
        "relative_delta_omega_qy_s": relative_delta(scalars["omega_qy_s_primary"], scalars["omega_qy_s_refined"]),
        "relative_delta_domega_ds": relative_delta(derivative_primary, derivative_refined),
    }
    result = {"schema": RESULT_SCHEMA, "runtime_status": "BUNDLE_BOUND_SOLVER_FREE_REDUCTION", "state_count": len(states), "rank1_band_index": 0, "two_scale_reduction_status": "ESTIMATES_AVAILABLE", "scientific_acceptance_status": "PASS", "reverse_diamond_count": 4, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False, **scalars, **absolute, **relative}
    for name, value in forward.items():
        result[f"forward_wilson_phase_{name}"] = value.phase
        result[f"minimum_link_singular_value_{name}"] = value.minimum_link_singular_value
        result[f"maximum_link_principal_angle_{name}"] = value.maximum_link_principal_angle
    for name, value in reverse.items():
        result[f"reverse_wilson_phase_{name}"] = value.phase
    return result


def _future_result(status: str, *, failed_stage: str | None = None, failure_code: str | None = None, exception_type: str | None = None, diagnostic: ReferenceCellContractDiagnosticError | ReferenceCellIdentityDiagnosticError | None = None) -> dict[str, Any]:
    result = {"schema": RESULT_SCHEMA, "status": status, "scientific_acceptance_status": "PASS" if status == "PASS" else "FAIL", "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False}
    if failed_stage is not None:
        result.update({"failed_stage": failed_stage, "failure_code": failure_code or (diagnostic.code if diagnostic is not None else "P71_REDUCTION_FAILED"), "exception_type": exception_type or "ValueError"})
    if isinstance(diagnostic, ReferenceCellContractDiagnosticError):
        result.update({
            "failed_state_id": diagnostic.state_id,
            "reference_cell_missing_fields": ",".join(diagnostic.missing_fields),
            "reference_cell_observed_keys": ",".join(diagnostic.observed_keys),
        })
        if diagnostic.observed_type != "dict" or not diagnostic.missing_fields:
            result["reference_cell_observed_type"] = diagnostic.observed_type
        if diagnostic.role is not None:
            result["failed_role"] = diagnostic.role
    elif isinstance(diagnostic, ReferenceCellIdentityDiagnosticError):
        result.update({
            "failed_state_id": diagnostic.state_id,
            "failed_role": diagnostic.role,
            "reference_cell_identity_mismatch_fields": ",".join(diagnostic.mismatch_fields),
        })
        for field in ("representation", "bloch_phase_excluded", "resolution", "spatial_shape"):
            result[f"reference_cell_observed_{field}"] = diagnostic.observed_values[field]
            result[f"reference_cell_observed_{field}_type"] = diagnostic.observed_types[field]
    elif isinstance(diagnostic, ReverseOrientationDiagnosticError):
        result["reverse_diag_failed_diamond"] = diagnostic.diamond
        result.update(diagnostic.diagnostics)
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
        diagnostic = exc if isinstance(exc, (ReferenceCellContractDiagnosticError, ReferenceCellIdentityDiagnosticError, ReverseOrientationDiagnosticError)) else None
        result = _future_result(
            "FAIL", failed_stage="bundle-or-reduction", failure_code=diagnostic.code if diagnostic is not None else str(exc),
            exception_type=type(exc).__name__, diagnostic=diagnostic,
        )
    Path(result_path).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
