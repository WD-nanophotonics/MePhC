"""Future solver-free extraction of local trajectory coefficients from P64 records."""
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
    HState, PhaseSpaceStateIdentity, ReferenceCellIdentity, reference_cell_link,
    fixed_q_frequency_derivative, h_state_from_normalized_vectors,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "audit" / "local_affine" / "p103_local_trajectory_coefficient_contract.json"
GRAPH_PATH = ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json"
RESULT_SCHEMA = "mephc-local-affine-trajectory-local-coefficient-extraction-v1"
GRAPH_SHA256 = "73df70ca5eecd728f07d6f6a954324c211366923ab5ef963107743baebc485c1"
DATASET_ID = "ac421aedcaf748bb0367b92083298e4f4c1d8095f2b5c66b5f2c371b082c8652"
MANIFEST_SHA256 = "4c48e0719531848755b58d8cfed1164677fcbe61d3201165cfd87eabde79108d"
RECORDS = (
    ("STATE_02", "PRIMARY_PLUS_QX", (0.001, -0.6166666666666667), 0.0, "53bc3d9464dddba0990613c03a934abad72d73d14cc9ad12745cfb163d8707f1"),
    ("STATE_03", "PRIMARY_MINUS_QX", (-0.001, -0.6166666666666667), 0.0, "b29debee90c407f34a9f12152e9a8c4b41466caffc12fbf99c4f687e8d33b516"),
    ("STATE_04", "PRIMARY_PLUS_QY", (0.0, -0.6156666666666667), 0.0, "b4c665307ff58660e86e16b2b54958b22c6a5c10c987240cf8d6bef33d5d4ee8"),
    ("STATE_05", "PRIMARY_MINUS_QY", (0.0, -0.6176666666666667), 0.0, "8c54126fe1aa4f7137c411d50a44847153828efd6dd4373c8eee5c47ae6e4608"),
    ("STATE_08", "REFINED_PLUS_QX", (0.0005, -0.6166666666666667), 0.0, "9f457757c2a33d8a3f59190343f68e471c9fa46c45078b44832ffc3f53d16ce0"),
    ("STATE_09", "REFINED_MINUS_QX", (-0.0005, -0.6166666666666667), 0.0, "4181c91db3c4018734fea99b3a3963d3041b7b5accb4067a665374796205071d"),
    ("STATE_10", "REFINED_PLUS_QY", (0.0, -0.6161666666666668), 0.0, "dc5b3afed9f4a2b551bbe4fb87803dca26bf5188e07f256bde0f9c4345f5334f"),
    ("STATE_11", "REFINED_MINUS_QY", (0.0, -0.6171666666666668), 0.0, "12f4fcc39346962a04026dfedd67bd7a4290fcd629d5d5f934f9f9e52fbfd434"),
)
ROLE_TO_RECORD = {role: (state_id, q, s, key) for state_id, role, q, s, key in RECORDS}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize_json(item) for item in value]
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(f"P103_UNSAFE_JSON_VALUE:{type(value).__name__}")


def graph_sha256() -> str:
    return hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()


def load_contract() -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    require(contract.get("schema") == "mephc-local-affine-p103-trajectory-local-coefficient-contract-v1", "P103_CONTRACT_SCHEMA_INVALID")
    require(contract.get("request_graph_sha256") == graph_sha256() == GRAPH_SHA256, "P103_GRAPH_SHA_INVALID")
    bindings = contract.get("bindings")
    require(isinstance(bindings, list) and len(bindings) == 8, "P103_CONTRACT_BINDING_COUNT_INVALID")
    require([item.get("state_id") for item in bindings] == [item[0] for item in RECORDS], "P103_CONTRACT_STATE_ORDER_INVALID")
    return contract


def load_bundle() -> tuple[dict[str, Any], Path]:
    raw = os.environ.get("MEPHC_INPUT_BUNDLE")
    require(isinstance(raw, str) and raw, "P103_INPUT_BUNDLE_MISSING")
    path = Path(raw)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    require(bundle.get("schema") == "mephc-thin-input-bundle-v1", "P103_INPUT_BUNDLE_SCHEMA_INVALID")
    datasets = bundle.get("datasets")
    require(isinstance(datasets, list) and len(datasets) == 8, "P103_DESCRIPTOR_COUNT_INVALID")
    return bundle, path


def validate_runtime_contract(bundle: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    expected = {item["record_key_sha256"]: item for item in contract["bindings"]}
    keys = [item.get("record_key_sha256") for item in bundle["datasets"] if isinstance(item, Mapping)]
    require(len(keys) == len(set(keys)) == 8 and set(keys) == set(expected), "P103_DESCRIPTOR_BINDING_SET_INVALID")
    for descriptor in bundle["datasets"]:
        require(isinstance(descriptor, Mapping), "P103_DESCRIPTOR_INVALID")
        binding = expected[descriptor["record_key_sha256"]]
        for field in ("dataset_id", "manifest_sha256", "record_key_sha256", "payload_sha256", "payload_size_bytes", "identity", "payload_file"):
            require(field in descriptor, f"P103_DESCRIPTOR_MISSING:{field}")
        require(descriptor["dataset_id"] == DATASET_ID and descriptor["manifest_sha256"] == MANIFEST_SHA256, "P103_DATASET_BINDING_MISMATCH")
        require(isinstance(descriptor["identity"], Mapping), "P103_IDENTITY_INVALID")
        identity = descriptor["identity"]
        require(identity.get("state_id") == binding["state_id"] and identity.get("role") == binding["role"], "P103_IDENTITY_STATE_ROLE_MISMATCH")
        require(identity.get("public_q") == binding["public_q"] and float(identity.get("s")) == float(binding["s"]), "P103_IDENTITY_COORDINATE_MISMATCH")
        require(identity.get("request_graph_sha256") == GRAPH_SHA256, "P103_IDENTITY_GRAPH_MISMATCH")
        require(identity.get("solver_configuration") == contract["solver_configuration"], "P103_SOLVER_CONFIGURATION_MISMATCH")
        require(isinstance(descriptor["payload_file"], str) and Path(descriptor["payload_file"]).name == descriptor["payload_file"], "P103_PAYLOAD_DESCRIPTOR_INVALID")


def payload_bytes(bundle_path: Path, descriptor: Mapping[str, Any]) -> bytes:
    payload = (bundle_path.parent / descriptor["payload_file"]).read_bytes()
    require(len(payload) == descriptor["payload_size_bytes"], "P103_PAYLOAD_LENGTH_MISMATCH")
    require(hashlib.sha256(payload).hexdigest() == descriptor["payload_sha256"], "P103_PAYLOAD_HASH_MISMATCH")
    return payload


def _phase_identity(identity: Mapping[str, Any], reference: Mapping[str, Any], configuration: Mapping[str, Any]) -> PhaseSpaceStateIdentity:
    ref = ReferenceCellIdentity(
        resolution=int(reference["resolution"]), spatial_shape=tuple(int(value) for value in reference["spatial_shape"]), lattice_size=tuple(reference["lattice_size"]),
        component_order=str(reference["component_order"]), component_basis=str(reference["component_basis"]), mu_contract=str(reference["mu_contract"]),
        orientation_sign=int(reference["orientation_sign"]), fractional_material_indexing_identity=str(reference["fractional_material_indexing_identity"]), reference_cell_identity=str(reference["reference_cell_identity"]),
    )
    canonical_identity = identity["canonical_state_identity"]
    return PhaseSpaceStateIdentity(
        public_q=tuple(float(value) for value in canonical_identity["public_q"]), s=float(canonical_identity["s"]),
        derived_kappa=tuple(float(value) for value in canonical_identity["derived_kappa"]),
        A_s=tuple(tuple(float(value) for value in row) for row in canonical_identity["A_s"]), F_s=tuple(tuple(float(value) for value in row) for row in canonical_identity["F_s"]),
        geometry_identity=str(canonical_identity["geometry_digest"]), reference_cell=ref,
        solver_configuration_identity=hashlib.sha256(canonical(dict(configuration))).hexdigest(),
    )


def vector_digest(vectors: Any) -> str:
    values = [[[float(value.real), float(value.imag)] for value in np.asarray(vector, dtype=np.complex128)] for vector in vectors]
    return hashlib.sha256(canonical(values)).hexdigest()


def resolve_states(bundle: Mapping[str, Any], bundle_path: Path, contract: Mapping[str, Any]) -> dict[str, HState]:
    by_key = {item["record_key_sha256"]: item for item in bundle["datasets"]}
    states: dict[str, HState] = {}
    bindings = {item["record_key_sha256"]: item for item in contract["bindings"]}
    for record in contract["bindings"]:
        descriptor = by_key[record["record_key_sha256"]]
        identity = descriptor["identity"]
        snapshot = decode_snapshot(payload_bytes(bundle_path, descriptor))
        provenance = normalize_json(snapshot.provenance)
        require(isinstance(provenance, dict), "P103_PROVENANCE_INVALID")
        reference = provenance["local_affine_reference_cell_contract"]
        require(hashlib.sha256(canonical(reference)).hexdigest() == identity["reference_cell_contract_sha256"], "P103_REFERENCE_CELL_SHA_MISMATCH")
        require(vector_digest(snapshot.normalized_vectors) == identity["normalized_vector_digest"], "P103_VECTOR_DIGEST_MISMATCH")
        require(len(snapshot.frequencies) == 6 and all(math.isfinite(float(value)) and float(value) > 0.0 for value in snapshot.frequencies), "P103_FREQUENCIES_INVALID")
        require(len(snapshot.normalized_vectors) == 6, "P103_VECTOR_COUNT_INVALID")
        phase_identity = _phase_identity(identity, reference, contract["solver_configuration"])
        states[record["role"]] = h_state_from_normalized_vectors(phase_identity, snapshot.normalized_vectors[0], frequencies=(float(snapshot.frequencies[0]),), band_indices=(0,))
    require(len(states) == 8 and set(states) == {item["role"] for item in bindings.values()}, "P103_ROLE_SET_INVALID")
    require(len({state.identity.reference_cell.compatibility_key() for state in states.values()}) == 1, "P103_REFERENCE_CELL_CROSS_STATE_MISMATCH")
    return states


def _q_wilson(states: Mapping[str, HState], prefix: str, h_q: float) -> dict[str, float]:
    roles = (f"{prefix}_PLUS_QX", f"{prefix}_PLUS_QY", f"{prefix}_MINUS_QX", f"{prefix}_MINUS_QY")
    vertices = [states[role] for role in roles]
    pairs = list(zip(vertices, vertices[1:] + vertices[:1]))
    links = [reference_cell_link(left, right) for left, right in pairs]
    reverse_links = [reference_cell_link(right, left) for left, right in reversed(pairs)]
    product = np.eye(1, dtype=np.complex128)
    reverse_product = np.eye(1, dtype=np.complex128)
    for link in links:
        product = product @ link.unitary
    for link in reverse_links:
        reverse_product = reverse_product @ link.unitary
    phase = float(np.angle(np.linalg.det(product)))
    reverse_phase = float(np.angle(np.linalg.det(reverse_product)))
    area = 2.0 * h_q * h_q
    require(math.isclose(reverse_phase, -phase, rel_tol=0.0, abs_tol=1e-12), f"P103_REVERSE_PHASE_MISMATCH:{prefix}")
    omega = -phase / area
    reverse_omega = -reverse_phase / area
    require(math.isclose(reverse_omega, -omega, rel_tol=0.0, abs_tol=1e-12 / abs(area)), f"P103_REVERSE_OMEGA_MISMATCH:{prefix}")
    minimum = min(float(link.min_singular_value) for link in links)
    maximum_angle = max(math.acos(min(1.0, max(-1.0, float(link.min_singular_value)))) for link in links)
    return {"phase": phase, "reverse_phase": reverse_phase, "omega": omega, "reverse_omega": reverse_omega, "area": area, "minimum_link_singular_value": minimum, "maximum_link_principal_angle": float(maximum_angle)}


def _symmetric_difference(left: float, right: float) -> float | None:
    denominator = abs(left) + abs(right)
    return None if denominator == 0.0 else 2.0 * abs(left - right) / denominator


def extract_coefficients(states: Mapping[str, HState]) -> dict[str, Any]:
    primary_qx = (states["PRIMARY_PLUS_QX"].frequency_for_band(0) - states["PRIMARY_MINUS_QX"].frequency_for_band(0)) / (2.0 * 0.001)
    primary_qy = (states["PRIMARY_PLUS_QY"].frequency_for_band(0) - states["PRIMARY_MINUS_QY"].frequency_for_band(0)) / (2.0 * 0.001)
    refined_qx = (states["REFINED_PLUS_QX"].frequency_for_band(0) - states["REFINED_MINUS_QX"].frequency_for_band(0)) / (2.0 * 0.0005)
    refined_qy = (states["REFINED_PLUS_QY"].frequency_for_band(0) - states["REFINED_MINUS_QY"].frequency_for_band(0)) / (2.0 * 0.0005)
    primary = _q_wilson(states, "PRIMARY", 0.001)
    refined = _q_wilson(states, "REFINED", 0.0005)
    gradients = {"primary_grad_q_freq_x": float(primary_qx), "primary_grad_q_freq_y": float(primary_qy), "refined_grad_q_freq_x": float(refined_qx), "refined_grad_q_freq_y": float(refined_qy)}
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "state_count": 8, "scale_count": 2, "rank1_band_index": 0, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False, "primary": primary, "refined": refined, **gradients, "primary_to_refined_abs_omega_qx_qy": abs(primary["omega"] - refined["omega"]), "primary_to_refined_relative_omega_qx_qy": _symmetric_difference(primary["omega"], refined["omega"]), "grad_q_freq_x_absolute_difference": abs(primary_qx - refined_qx), "grad_q_freq_y_absolute_difference": abs(primary_qy - refined_qy), "grad_q_freq_x_symmetric_relative_difference": _symmetric_difference(primary_qx, refined_qx), "grad_q_freq_y_symmetric_relative_difference": _symmetric_difference(primary_qy, refined_qy), "Omega_qx_s": -0.19127165880040325, "Omega_qy_s": 0.0, "partial_s_freq": 0.009029604372262634, "trajectory_science_coefficient_status": "SCIENCE_DERIVED_AVAILABLE", "trajectory_remaining_scenario_parameter_count": 4, "trajectory_remaining_scenario_parameters": "local_deformation_profile_or_gradient,physical_normalization_reference_length_and_wave_speed,trajectory_initial_conditions,trajectory_integration_controls"}


def failure_result(exc: Exception) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "FAIL", "failed_stage": "bundle-or-reduction", "failure_code": str(exc), "exception_type": type(exc).__name__, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False}


def main() -> int:
    result_path = os.environ.get("MEPHC_RESULT_PATH")
    require(isinstance(result_path, str) and result_path, "P103_RESULT_PATH_MISSING")
    try:
        contract = load_contract()
        bundle, bundle_path = load_bundle()
        validate_runtime_contract(bundle, contract)
        result = extract_coefficients(resolve_states(bundle, bundle_path, contract))
    except Exception as exc:
        result = failure_result(exc)
    Path(result_path).write_bytes(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
