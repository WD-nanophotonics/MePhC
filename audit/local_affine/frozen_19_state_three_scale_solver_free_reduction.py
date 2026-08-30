"""Bounded solver-free three-scale reduction for the P86 Thin Flow contract."""
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
PLAN_PATH = ROOT / "audit" / "local_affine" / "p86_three_scale_19_state_binding_plan.json"
P64_GRAPH_PATH = ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json"
P85_GRAPH_PATH = ROOT / "audit" / "local_affine" / "p84_third_scale_6_state_request_graph.json"
PLAN_SCHEMA = "mephc-local-affine-p86-three-scale-19-state-binding-plan-v1"
P64_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P64-FROZEN-13-STATE-LIVE-ACQUISITION-20260830-428"
P85_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P85-THIRD-SCALE-SIX-STATE-LIVE-ACQUISITION-20260830-449"
THIN_BUNDLE_SCHEMA = "mephc-thin-input-bundle-v1"
RESULT_SCHEMA = "mephc-local-affine-solver-free-three-scale-reduction-v1"
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
_P83_REFERENCE = {
    "omega_qx_s_primary": -0.191020640274069,
    "omega_qx_s_refined": -0.19120388321536833,
    "omega_qy_s_primary": -3.528260452898002e-05,
    "omega_qy_s_refined": 3.5836998125982074e-05,
    "domega_ds_primary": 0.009019148867474985,
    "domega_ds_refined": 0.009027508885504909,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _bounded_scalar(value: Any, *, limit: int = 128) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return value if len(value) <= limit else value[: limit - 3] + "..."


class DescriptorGraphMismatchError(ValueError):
    """Bounded evidence for a graph identity mismatch before reduction."""

    code = "P86_DESCRIPTOR_GRAPH_MISMATCH"

    def __init__(
        self,
        *,
        descriptor_index: int | None,
        record_key_sha256: str | None,
        dataset_id: str | None,
        expected_state_id: str | None,
        expected_role: str | None,
        expected_graph_group: str | None,
        expected_request_graph_sha256: str | None,
        observed_request_graph_sha256: str | None,
        observed_request_graph_source: str,
        binding_index: int | None = None,
    ) -> None:
        self.descriptor_index = descriptor_index
        self.record_key_sha256 = _bounded_scalar(record_key_sha256)
        self.dataset_id = _bounded_scalar(dataset_id)
        self.expected_state_id = _bounded_scalar(expected_state_id)
        self.expected_role = _bounded_scalar(expected_role)
        self.expected_graph_group = _bounded_scalar(expected_graph_group)
        self.expected_request_graph_sha256 = _bounded_scalar(expected_request_graph_sha256)
        self.observed_request_graph_sha256 = _bounded_scalar(observed_request_graph_sha256)
        self.observed_request_graph_source = _bounded_scalar(observed_request_graph_source) or "unknown"
        self.binding_index = binding_index
        super().__init__(self.code)

    def as_diagnostic(self) -> dict[str, Any]:
        return {
            "descriptor_index": self.descriptor_index,
            "record_key_sha256": self.record_key_sha256,
            "dataset_id": self.dataset_id,
            "expected_state_id": self.expected_state_id,
            "expected_role": self.expected_role,
            "expected_graph_group": self.expected_graph_group,
            "expected_request_graph_sha256": self.expected_request_graph_sha256,
            "observed_request_graph_sha256": self.observed_request_graph_sha256,
            "observed_request_graph_source": self.observed_request_graph_source,
            "binding_index": self.binding_index,
        }


def _normalize_runtime_provenance(value: Any) -> Any:
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


def _vector_digest(vectors: Any) -> str:
    values = [[[float(item.real), float(item.imag)] for item in np.asarray(vector, dtype=np.complex128)] for vector in vectors]
    return hashlib.sha256(_canonical(values)).hexdigest()


def _graph_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_graph_metadata(binding: Mapping[str, Any] | None, binding_index: int | None) -> dict[str, Any]:
    if binding_index is None or not 0 <= binding_index < 19:
        return {"group": None, "sha": None, "state_id": None, "role": None}
    graph_path = P64_GRAPH_PATH if binding_index < 13 else P85_GRAPH_PATH
    state_id = binding.get("state_id") if isinstance(binding, Mapping) else None
    role = binding.get("role") if isinstance(binding, Mapping) else None
    group = "P64_13_STATE" if binding_index < 13 else "P85_6_STATE"
    return {
        "group": group,
        "sha": _graph_sha(graph_path),
        "state_id": state_id if isinstance(state_id, str) else None,
        "role": role if isinstance(role, str) else None,
    }


def _raise_descriptor_graph_mismatch(
    *,
    descriptor_index: int | None,
    binding_index: int | None,
    binding: Mapping[str, Any] | None,
    record_key_sha256: Any,
    dataset_id: Any,
    observed_request_graph_sha256: Any,
    observed_request_graph_source: str,
) -> None:
    expected = _expected_graph_metadata(binding, binding_index)
    raise DescriptorGraphMismatchError(
        descriptor_index=descriptor_index,
        record_key_sha256=record_key_sha256 if isinstance(record_key_sha256, str) else None,
        dataset_id=dataset_id if isinstance(dataset_id, str) else None,
        expected_state_id=expected["state_id"],
        expected_role=expected["role"],
        expected_graph_group=expected["group"],
        expected_request_graph_sha256=expected["sha"],
        observed_request_graph_sha256=observed_request_graph_sha256 if isinstance(observed_request_graph_sha256, str) else None,
        observed_request_graph_source=observed_request_graph_source,
        binding_index=binding_index,
    )


def validate_binding_plan_graphs(plan: Mapping[str, Any]) -> None:
    bindings = plan.get("bindings")
    _require(isinstance(bindings, list), "P86_BINDING_LIST_INVALID")
    for binding_index, binding in enumerate(bindings):
        _require(isinstance(binding, dict), "P86_BINDING_INVALID")
        expected = _expected_graph_metadata(binding, binding_index)
        observed = binding.get("request_graph_sha256")
        if not isinstance(observed, str) or observed.lower() != expected["sha"]:
            _raise_descriptor_graph_mismatch(
                descriptor_index=None,
                binding_index=binding_index,
                binding=binding,
                record_key_sha256=binding.get("record_key_sha256"),
                dataset_id=binding.get("dataset_id"),
                observed_request_graph_sha256=observed,
                observed_request_graph_source="binding_plan",
            )


def load_binding_plan() -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    _require(plan.get("schema") == PLAN_SCHEMA, "P86_BINDING_PLAN_SCHEMA_INVALID")
    _require(plan.get("record_count") == 19 and plan.get("unique_record_key_count") == 19, "P86_BINDING_PLAN_COUNT_INVALID")
    datasets = plan.get("datasets")
    _require(isinstance(datasets, list) and len(datasets) == 2, "P86_DATASET_SET_INVALID")
    dataset_pairs = {(item.get("dataset_id"), item.get("manifest_sha256")) for item in datasets if isinstance(item, dict)}
    _require(len(dataset_pairs) == 2, "P86_DATASET_PAIR_DUPLICATE")
    bindings = plan.get("bindings")
    _require(isinstance(bindings, list) and len(bindings) == 19, "P86_BINDING_LIST_INVALID")
    _require([item.get("state_id") for item in bindings] == [f"STATE_{index:02d}" for index in range(1, 20)], "P86_BINDING_ORDER_INVALID")
    validate_binding_plan_graphs(plan)
    keys: set[str] = set()
    for index, binding in enumerate(bindings):
        _require(isinstance(binding, dict), "P86_BINDING_INVALID")
        _require((binding.get("dataset_id"), binding.get("manifest_sha256")) in dataset_pairs, "P86_BINDING_DATASET_PAIR_INVALID")
        key = binding.get("record_key_sha256")
        _require(isinstance(key, str) and len(key) == 64 and set(key.lower()) <= _HEX64, "P86_RECORD_KEY_FORMAT_INVALID")
        key_work_order = P64_WORK_ORDER_ID if index < 13 else P85_WORK_ORDER_ID
        identity = {"work_order_id": key_work_order, "state_id": binding["state_id"], "role": binding["role"], "public_q": binding["public_q"], "s": binding["s"]}
        _require(hashlib.sha256(_canonical(identity)).hexdigest() == key.lower(), "P86_RECORD_KEY_DERIVATION_INVALID")
        keys.add(key.lower())
    _require(len(keys) == 19, "P86_RECORD_KEYS_NOT_UNIQUE")
    return plan


def load_bundle() -> tuple[dict[str, Any], Path]:
    raw_path = os.environ.get("MEPHC_INPUT_BUNDLE")
    _require(isinstance(raw_path, str) and raw_path, "P86_INPUT_BUNDLE_MISSING")
    bundle_path = Path(raw_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    _require(bundle.get("schema") == THIN_BUNDLE_SCHEMA, "P86_INPUT_BUNDLE_SCHEMA_INVALID")
    contract_sha = os.environ.get("MEPHC_SCIENCE_CONTRACT_SHA256")
    if contract_sha is not None:
        _require(bundle.get("contract_sha256") == contract_sha, "P86_CONTRACT_SHA_MISMATCH")
    _require(isinstance(bundle.get("work_order_id"), str) and bundle["work_order_id"], "P86_WORK_ORDER_ID_INVALID")
    datasets = bundle.get("datasets")
    _require(isinstance(datasets, list) and len(datasets) == 19, "P86_DATASET_DESCRIPTOR_COUNT_INVALID")
    return bundle, bundle_path


def validate_runtime_contract(bundle: dict[str, Any], plan: dict[str, Any]) -> None:
    datasets = bundle["datasets"]
    keys = [item.get("record_key_sha256") for item in datasets if isinstance(item, dict)]
    _require(len(keys) == len(set(keys)) == 19, "P86_DESCRIPTOR_KEYS_NOT_UNIQUE")
    bindings = {item["record_key_sha256"]: item for item in plan["bindings"]}
    _require(set(keys) == set(bindings), "P86_DESCRIPTOR_BINDING_SET_INVALID")
    validate_binding_plan_graphs(plan)
    binding_indexes = {item["record_key_sha256"]: index for index, item in enumerate(plan["bindings"])}
    for descriptor_index, descriptor in enumerate(datasets):
        _require(isinstance(descriptor, dict), "P86_DESCRIPTOR_INVALID")
        record_key = descriptor.get("record_key_sha256")
        binding = bindings.get(record_key)
        _require(binding is not None, "P86_DESCRIPTOR_BINDING_MISSING")
        binding_index = binding_indexes[record_key]
        for field in ("dataset_id", "manifest_sha256", "record_key_sha256", "payload_sha256", "payload_size_bytes", "identity", "payload_file"):
            _require(field in descriptor, f"P86_DESCRIPTOR_MISSING:{field}")
        _require(descriptor["dataset_id"] == binding["dataset_id"] and descriptor["manifest_sha256"] == binding["manifest_sha256"], "P86_DESCRIPTOR_DATASET_MISMATCH")
        identity = descriptor["identity"]
        observed_graph = identity.get("request_graph_sha256") if isinstance(identity, Mapping) else None
        expected = _expected_graph_metadata(binding, binding_index)
        if not isinstance(identity, Mapping) or observed_graph != binding["request_graph_sha256"] or not isinstance(observed_graph, str) or observed_graph.lower() != expected["sha"]:
            _raise_descriptor_graph_mismatch(
                descriptor_index=descriptor_index,
                binding_index=binding_index,
                binding=binding,
                record_key_sha256=record_key,
                dataset_id=descriptor.get("dataset_id"),
                observed_request_graph_sha256=observed_graph,
                observed_request_graph_source="descriptor_identity",
            )
        _require(isinstance(descriptor["payload_file"], str) and Path(descriptor["payload_file"]).name == descriptor["payload_file"], "P86_PAYLOAD_DESCRIPTOR_INVALID")


def _payload_bytes(bundle_path: Path, item: dict[str, Any]) -> bytes:
    payload = (bundle_path.parent / item["payload_file"]).read_bytes()
    _require(len(payload) == item["payload_size_bytes"], "P86_PAYLOAD_LENGTH_MISMATCH")
    _require(hashlib.sha256(payload).hexdigest() == item["payload_sha256"], "P86_PAYLOAD_HASH_MISMATCH")
    return payload


def _validate_identity_digest(identity: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    for field in _IDENTITY_FIELDS:
        _require(field in identity, f"P86_IDENTITY_FIELD_MISSING:{field}")
    _require(identity["state_id"] == binding["state_id"] and identity["role"] == binding["role"], "P86_IDENTITY_STATE_ROLE_MISMATCH")
    _require(tuple(float(x) for x in identity["public_q"]) == tuple(float(x) for x in binding["public_q"]) and float(identity["s"]) == float(binding["s"]), "P86_IDENTITY_COORDINATE_MISMATCH")
    canonical_identity = identity["canonical_state_identity"]
    _require(isinstance(canonical_identity, dict), "P86_CANONICAL_IDENTITY_INVALID")
    _require(hashlib.sha256(_canonical(canonical_identity)).hexdigest() == identity["canonical_state_identity_sha256"], "P86_CANONICAL_IDENTITY_DIGEST_MISMATCH")
    _require(tuple(float(x) for x in canonical_identity["public_q"]) == tuple(float(x) for x in identity["public_q"]) and float(canonical_identity["s"]) == float(identity["s"]), "P86_CANONICAL_BINDING_MISMATCH")
    _require(identity["solver_configuration"] == _SOLVER_CONFIGURATION, "P86_SOLVER_CONFIGURATION_MISMATCH")
    return canonical_identity


def _reference_cell_contract(snapshot: Any, state_id: str, role: str) -> Mapping[str, Any]:
    provenance = _normalize_runtime_provenance(getattr(snapshot, "provenance", {}))
    _require(isinstance(provenance, dict), "P78_PROVENANCE_ROOT_INVALID")
    reference = provenance.get("local_affine_reference_cell_contract")
    fields = ("representation", "bloch_phase_excluded", "resolution", "spatial_shape", "lattice_size", "component_order", "component_basis", "mu_contract", "orientation_sign", "fractional_material_indexing_identity", "reference_cell_identity")
    _require(isinstance(reference, dict) and all(field in reference for field in fields), "P86_REFERENCE_CELL_FIELD_MISSING")
    _require(reference["representation"] == "mpb_periodic_h_l2_v1" and reference["bloch_phase_excluded"] is True and reference["resolution"] == 64 and reference["spatial_shape"] == [64, 64], "P86_REFERENCE_CELL_IDENTITY_INVALID")
    _require(reference["component_order"] == "supplied final axis order" and reference["component_basis"] == "LAB_CARTESIAN" and reference["mu_contract"] == "MU1_NONMAGNETIC" and reference["orientation_sign"] == 1, "P86_REFERENCE_CELL_PHYSICS_INVALID")
    return reference


def _validate_snapshot_identity(snapshot: Any, item: dict[str, Any], binding: dict[str, Any], graph_path: Path) -> dict[str, Any]:
    identity = item["identity"]
    canonical_identity = _validate_identity_digest(identity, binding)
    _require(identity["payload_sha256"] == item["payload_sha256"], "P86_IDENTITY_PAYLOAD_HASH_MISMATCH")
    _require(identity["request_graph_sha256"] == _graph_sha(graph_path), "P86_REQUEST_GRAPH_HASH_MISMATCH")
    provenance = _normalize_runtime_provenance(snapshot.provenance)
    _require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3, "P86_SNAPSHOT_SHAPE_INVALID")
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    raw_norms = np.asarray(snapshot.raw_norms, dtype=float)
    _require(frequencies.shape == (6,) and bool(np.all(np.isfinite(frequencies))) and bool(np.all(frequencies > 0.0)), "P86_FREQUENCIES_INVALID")
    _require(raw_norms.shape == (6,) and bool(np.all(np.isfinite(raw_norms))) and bool(np.all(raw_norms > 0.0)), "P86_RAW_NORMS_INVALID")
    _require(len(snapshot.normalized_vectors) == 6, "P86_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        _require(bool(np.all(np.isfinite(values))) and math.isclose(float(np.linalg.norm(values)), 1.0, rel_tol=0.0, abs_tol=1e-10), "P86_VECTOR_INVALID")
    gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
    _require(gram.shape == (6, 6) and bool(np.all(np.isfinite(gram))), "P86_GRAM_INVALID")
    _require(provenance.get("representation") == "mpb_periodic_h_l2_v1", "P86_REPRESENTATION_INVALID")
    reference = _reference_cell_contract(snapshot, identity["state_id"], identity["role"])
    _require(hashlib.sha256(_canonical(reference)).hexdigest() == identity["reference_cell_contract_sha256"], "P86_REFERENCE_CELL_DIGEST_MISMATCH")
    _require(provenance.get("mpb_k_point") == identity["reciprocal_metadata"], "P86_RECIPROCAL_METADATA_MISMATCH")
    _require([float(value) for value in frequencies] == [float(value) for value in identity["frequencies"]], "P86_FREQUENCY_METADATA_MISMATCH")
    _require([float(value) for value in raw_norms] == [float(value) for value in identity["raw_norms"]], "P86_RAW_NORM_METADATA_MISMATCH")
    _require(_vector_digest(snapshot.normalized_vectors) == identity["normalized_vector_digest"], "P86_VECTOR_DIGEST_MISMATCH")
    return canonical_identity


def _identity(item: dict[str, Any], snapshot: Any, binding: dict[str, Any], graph_path: Path) -> PhaseSpaceStateIdentity:
    canonical_identity = _validate_snapshot_identity(snapshot, item, binding, graph_path)
    reference = _normalize_runtime_provenance(snapshot.provenance)["local_affine_reference_cell_contract"]
    ref = ReferenceCellIdentity(
        resolution=int(reference["resolution"]), spatial_shape=tuple(int(x) for x in reference["spatial_shape"]), lattice_size=tuple(reference["lattice_size"]),
        component_order=str(reference["component_order"]), component_basis=str(reference["component_basis"]), mu_contract=str(reference["mu_contract"]),
        orientation_sign=int(reference["orientation_sign"]), fractional_material_indexing_identity=str(reference["fractional_material_indexing_identity"]), reference_cell_identity=str(reference["reference_cell_identity"]),
    )
    f_matrix = np.asarray(canonical_identity["F_s"], dtype=float)
    _require(f_matrix.shape == (2, 2) and bool(np.all(np.isfinite(f_matrix))) and float(np.linalg.det(f_matrix)) > 0.0, "P86_F_S_INVALID")
    return PhaseSpaceStateIdentity(
        public_q=tuple(float(x) for x in canonical_identity["public_q"]), s=float(canonical_identity["s"]),
        derived_kappa=tuple(float(x) for x in canonical_identity["derived_kappa"]),
        A_s=tuple(tuple(float(x) for x in row) for row in canonical_identity["A_s"]), F_s=tuple(tuple(float(x) for x in row) for row in canonical_identity["F_s"]),
        geometry_identity=str(canonical_identity["geometry_digest"]), reference_cell=ref,
        solver_configuration_identity=hashlib.sha256(_canonical(_SOLVER_CONFIGURATION)).hexdigest(),
    )


def resolve_states(bundle: dict[str, Any], bundle_path: Path, plan: dict[str, Any]) -> dict[str, HState]:
    by_key = {item["record_key_sha256"]: item for item in bundle["datasets"]}
    states: dict[str, HState] = {}
    for binding in plan["bindings"]:
        item = by_key[binding["record_key_sha256"]]
        graph_path = P64_GRAPH_PATH if binding["state_id"] <= "STATE_13" else P85_GRAPH_PATH
        snapshot = decode_snapshot(_payload_bytes(bundle_path, item))
        identity = _identity(item, snapshot, binding, graph_path)
        states[binding["role"]] = h_state_from_normalized_vectors(identity, snapshot.normalized_vectors[0], frequencies=(float(snapshot.frequencies[0]),), band_indices=(0,))
    _require(len(states) == 19, "P86_STATE_ROLE_SET_INVALID")
    _require(len({state.identity.reference_cell.compatibility_key() for state in states.values()}) == 1, "P86_REFERENCE_CELL_CROSS_STATE_MISMATCH")
    return states


def _diamond(states: dict[str, HState], prefix: str, axis: int, h_q: float, h_s: float) -> Any:
    return make_mixed_diamond(
        plus_q=states[f"{prefix}_PLUS_Q{'X' if axis == 0 else 'Y'}"], minus_q=states[f"{prefix}_MINUS_Q{'X' if axis == 0 else 'Y'}"],
        plus_s=states[f"{prefix}_PLUS_S"], minus_s=states[f"{prefix}_MINUS_S"], axis=axis, h_q=h_q, h_s=h_s,
        q_center=states["CENTER"].identity.public_q, s_center=states["CENTER"].identity.s,
    )


def _third_diamond(states: dict[str, HState], axis: int) -> Any:
    return make_mixed_diamond(
        plus_q=states["THIRD_PLUS_QX" if axis == 0 else "THIRD_PLUS_QY"],
        minus_q=states["THIRD_MINUS_QX" if axis == 0 else "THIRD_MINUS_QY"],
        plus_s=states["THIRD_PLUS_S"], minus_s=states["THIRD_MINUS_S"], axis=axis,
        h_q=0.00025, h_s=0.005, q_center=states["CENTER"].identity.public_q, s_center=states["CENTER"].identity.s,
    )


def _machine_precision_tolerance(value: float, derived: float) -> float:
    return math.ulp(float(value)) + math.ulp(float(derived))


def _reverse_omega_tolerance(area: float) -> float:
    _require(math.isfinite(float(area)) and float(area) != 0.0, "P82_SIGNED_AREA_ZERO_OR_NONFINITE")
    return 1e-12 / abs(float(area))


def _reverse_pair(name: str, forward: Any, reverse: Any) -> dict[str, Any]:
    values = (forward.phase, forward.omega_qs, forward.signed_area_qs, forward.minimum_link_singular_value, forward.maximum_link_principal_angle, reverse.phase, reverse.omega_qs, reverse.signed_area_qs, reverse.minimum_link_singular_value, reverse.maximum_link_principal_angle)
    _require(all(math.isfinite(float(value)) for value in values), "P86_NONFINITE_WILSON_RESULT")
    _require(float(forward.signed_area_qs) != 0.0 and float(reverse.signed_area_qs) != 0.0 and forward.signed_area_qs == reverse.signed_area_qs, "P86_SIGNED_AREA_INVALID")
    phase_sum = float(forward.phase + reverse.phase)
    area = float(forward.signed_area_qs)
    omega_tolerance = _reverse_omega_tolerance(area)
    diagnostics = {
        f"forward_wilson_phase_{name}": float(forward.phase), f"reverse_wilson_phase_{name}": float(reverse.phase),
        f"reverse_omega_tolerance_{name}": omega_tolerance, f"reverse_phase_residual_{name}": abs(phase_sum),
        f"reverse_omega_residual_{name}": abs(float(forward.omega_qs + reverse.omega_qs)),
        f"minimum_link_singular_value_{name}": float(forward.minimum_link_singular_value),
        f"minimum_link_singular_value_reverse_{name}": float(reverse.minimum_link_singular_value),
        f"maximum_link_principal_angle_{name}": float(forward.maximum_link_principal_angle),
        f"maximum_link_principal_angle_reverse_{name}": float(reverse.maximum_link_principal_angle),
    }
    if not math.isclose(reverse.phase, -forward.phase, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"P86_REVERSE_ORIENTATION_SIGN_MISMATCH:{name}")
    for phase, omega in ((forward.phase, forward.omega_qs), (reverse.phase, reverse.omega_qs)):
        derived = -float(phase) / area
        _require(abs(float(omega) - derived) <= _machine_precision_tolerance(float(omega), derived), "P86_OMEGA_PHASE_CONSISTENCY_MISMATCH")
    _require(math.isclose(reverse.omega_qs, -forward.omega_qs, rel_tol=0.0, abs_tol=omega_tolerance), f"P86_REVERSE_OMEGA_TOLERANCE:{name}")
    return diagnostics


def _relative(left: float, right: float) -> float | None:
    denominator = abs(left) + abs(right)
    return None if denominator <= 0.0 else 2.0 * abs(left - right) / denominator


def _ratio(left: float, right: float) -> float | None:
    return None if right <= 0.0 else left / right


def _signs(values: tuple[float, float, float]) -> str:
    return ",".join("+" if value > 0.0 else "-" if value < 0.0 else "0" for value in values)


def reduce_states(states: dict[str, HState]) -> dict[str, Any]:
    required = {"CENTER", "PRIMARY_PLUS_QX", "PRIMARY_MINUS_QX", "PRIMARY_PLUS_QY", "PRIMARY_MINUS_QY", "PRIMARY_PLUS_S", "PRIMARY_MINUS_S", "REFINED_PLUS_QX", "REFINED_MINUS_QX", "REFINED_PLUS_QY", "REFINED_MINUS_QY", "REFINED_PLUS_S", "REFINED_MINUS_S", "THIRD_PLUS_QX", "THIRD_MINUS_QX", "THIRD_PLUS_QY", "THIRD_MINUS_QY", "THIRD_PLUS_S", "THIRD_MINUS_S"}
    _require(set(states) == required, "P86_STATE_ROLE_SET_INVALID")
    diamonds = {
        "primary_qx": _diamond(states, "PRIMARY", 0, 0.001, 0.02), "primary_qy": _diamond(states, "PRIMARY", 1, 0.001, 0.02),
        "refined_qx": _diamond(states, "REFINED", 0, 0.0005, 0.01), "refined_qy": _diamond(states, "REFINED", 1, 0.0005, 0.01),
        "third_qx": _third_diamond(states, 0), "third_qy": _third_diamond(states, 1),
    }
    forward = {name: rank1_mixed_curvature(diamond) for name, diamond in diamonds.items()}
    reverse = {name: reverse_mixed_curvature(diamond) for name, diamond in diamonds.items()}
    diagnostics: dict[str, Any] = {}
    for name in diamonds:
        diagnostics.update(_reverse_pair(name, forward[name], reverse[name]))
    derivatives = {
        "domega_ds_primary": fixed_q_frequency_derivative(states["PRIMARY_PLUS_S"], states["PRIMARY_MINUS_S"], band_index=0, h_s=0.02),
        "domega_ds_refined": fixed_q_frequency_derivative(states["REFINED_PLUS_S"], states["REFINED_MINUS_S"], band_index=0, h_s=0.01),
        "domega_ds_third": fixed_q_frequency_derivative(states["THIRD_PLUS_S"], states["THIRD_MINUS_S"], band_index=0, h_s=0.005),
    }
    scalars = {"omega_qx_s_primary": forward["primary_qx"].omega_qs, "omega_qx_s_refined": forward["refined_qx"].omega_qs, "omega_qx_s_third": forward["third_qx"].omega_qs, "omega_qy_s_primary": forward["primary_qy"].omega_qs, "omega_qy_s_refined": forward["refined_qy"].omega_qs, "omega_qy_s_third": forward["third_qy"].omega_qs, **derivatives}
    for key, expected in _P83_REFERENCE.items():
        _require(math.isclose(float(scalars[key]), expected, rel_tol=0.0, abs_tol=1e-12), f"P83_REFERENCE_REPRODUCTION:{key}")
    qx = (float(scalars["omega_qx_s_primary"]), float(scalars["omega_qx_s_refined"]), float(scalars["omega_qx_s_third"]))
    qy = (float(scalars["omega_qy_s_primary"]), float(scalars["omega_qy_s_refined"]), float(scalars["omega_qy_s_third"]))
    derivative = tuple(float(scalars[key]) for key in ("domega_ds_primary", "domega_ds_refined", "domega_ds_third"))
    sequences = {"qx_s": qx, "qy_s": qy, "domega_ds": derivative}
    result: dict[str, Any] = {"schema": RESULT_SCHEMA, "runtime_status": "BUNDLE_BOUND_SOLVER_FREE_THREE_SCALE_REDUCTION", "state_count": 19, "rank1_band_index": 0, "scale_count": 3, "three_scale_reduction_status": "ESTIMATES_AVAILABLE", "scientific_acceptance_status": "PASS", "reverse_diamond_count": 6, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False, **scalars, **diagnostics}
    for label, values in sequences.items():
        result[f"{label}_sign_sequence"] = _signs(values)
        result[f"{label}_absolute_magnitude_sequence"] = [abs(value) for value in values]
        result[f"{label}_primary_to_refined_absolute_difference"] = abs(values[0] - values[1])
        result[f"{label}_refined_to_third_absolute_difference"] = abs(values[1] - values[2])
        result[f"{label}_primary_to_refined_relative_difference"] = _relative(values[0], values[1])
        result[f"{label}_refined_to_third_relative_difference"] = _relative(values[1], values[2])
        result[f"{label}_empirical_refinement_difference_ratio"] = _ratio(abs(values[0] - values[1]), abs(values[1] - values[2]))
    return result


def _future_result(status: str, *, failed_stage: str | None = None, failure_code: str | None = None, exception_type: str | None = None, diagnostic: DescriptorGraphMismatchError | None = None) -> dict[str, Any]:
    result = {"schema": RESULT_SCHEMA, "status": status, "scientific_acceptance_status": "PASS" if status == "PASS" else "FAIL", "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False}
    if failed_stage is not None:
        result.update({"failed_stage": failed_stage, "failure_code": failure_code or (diagnostic.code if diagnostic is not None else "P86_REDUCTION_FAILED"), "exception_type": exception_type or (type(diagnostic).__name__ if diagnostic is not None else "ValueError")})
    if diagnostic is not None:
        result.update(diagnostic.as_diagnostic())
    return result


def main() -> int:
    result_path = os.environ.get("MEPHC_RESULT_PATH")
    _require(isinstance(result_path, str) and result_path, "P86_RESULT_PATH_MISSING")
    try:
        bundle, bundle_path = load_bundle()
        plan = load_binding_plan()
        validate_runtime_contract(bundle, plan)
        states = resolve_states(bundle, bundle_path, plan)
        result = reduce_states(states)
    except Exception as exc:
        result = _future_result(
            "FAIL",
            failed_stage="bundle-or-reduction",
            failure_code=exc.code if isinstance(exc, DescriptorGraphMismatchError) else str(exc),
            exception_type=type(exc).__name__,
            diagnostic=exc if isinstance(exc, DescriptorGraphMismatchError) else None,
        )
    Path(result_path).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
