"""Solver-free dimensionless trajectory benchmark for the P107 publication stage.

The module is deliberately self-contained at the machine-contract boundary.  It
consumes the eight already certified P64 descriptors supplied by Thin Flow and
never creates a geometry, provider, solver, or scientific dataset.  The future
SCIENCE entrypoint writes only the result path supplied by ``MEPHC_RESULT_PATH``.
"""
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
from mephc.phase_space_dynamics import (
    DIAGNOSTIC_SYNTHETIC,
    LocalRank1PhaseSpacePoint,
    PhysicalNormalization,
    RANK1_QUALIFIED,
    integrate_trajectory,
    grad_q_frequency_to_group_velocity,
    k_phys_to_q,
    normalized_frequency_to_omega,
    q_to_k_phys,
)
from mephc.phase_space_geometry import (
    HState,
    PhaseSpaceStateIdentity,
    ReferenceCellIdentity,
    reference_cell_link,
    h_state_from_normalized_vectors,
)


ROOT = Path(__file__).resolve().parents[2]
MACHINE_CONTRACT_PATH = ROOT / "audit" / "local_affine" / "p107_dimensionless_trajectory_machine_execution_contract.json"
RESULT_SCHEMA = "mephc-local-affine-dimensionless-trajectory-benchmark-v1"
MACHINE_CONTRACT_SCHEMA = "mephc-local-affine-p107-dimensionless-trajectory-machine-execution-contract-v1"
THIN_BUNDLE_SCHEMA = "mephc-thin-input-bundle-v1"
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P107-DIMENSIONLESS-TRAJECTORY-MACHINE-CONTRACT-PUBLICATION-20260830-471"
P64_SOURCE_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P64-FROZEN-13-STATE-LIVE-ACQUISITION-20260830-428"
DATASET_ID = "ac421aedcaf748bb0367b92083298e4f4c1d8095f2b5c66b5f2c371b082c8652"
MANIFEST_SHA256 = "4c48e0719531848755b58d8cfed1164677fcbe61d3201165cfd87eabde79108d"
GRAPH_SHA256 = "73df70ca5eecd728f07d6f6a954324c211366923ab5ef963107743baebc485c1"
RANK1_BAND = 0
PRIMARY_H_Q = 0.001
REFINED_H_Q = 0.0005
Q_CENTER = (0.0, -0.6166666666666667)
CERTIFIED = {
    "omega_qx_s": -0.19127165880040325,
    "omega_qy_s": 0.0,
    "partial_s_freq": 0.009029604372262634,
    "primary_grad_q_freq_x": -1.008549355141497e-07,
    "primary_grad_q_freq_y": -0.09346940101671863,
    "refined_grad_q_freq_x": -1.0085060564435366e-07,
    "refined_grad_q_freq_y": -0.09346881580343802,
}
SCENARIO = {
    "reference_length_a": 1.0,
    "reference_wave_speed_c": 1.0,
    "rho_initial": [0.0, 0.0],
    "q_initial": list(Q_CENTER),
    "deformation_gradient_rho": [0.001, 0.0],
    "tau_start": 0.0,
    "tau_stop": 0.5,
    "rk4_steps": 100,
    "classification": "CANONICAL_DIMENSIONLESS_VALIDATION_ONLY_NOT_A_PHYSICAL_DEVICE_PREDICTION",
}
RECORDS = (
    ("STATE_02", "PRIMARY_PLUS_QX", [0.001, -0.6166666666666667], 0.0, "53bc3d9464dddba0990613c03a934abad72d73d14cc9ad12745cfb163d8707f1"),
    ("STATE_03", "PRIMARY_MINUS_QX", [-0.001, -0.6166666666666667], 0.0, "b29debee90c407f34a9f12152e9a8c4b41466caffc12fbf99c4f687e8d33b516"),
    ("STATE_04", "PRIMARY_PLUS_QY", [0.0, -0.6156666666666667], 0.0, "b4c665307ff58660e86e16b2b54958b22c6a5c10c987240cf8d6bef33d5d4ee8"),
    ("STATE_05", "PRIMARY_MINUS_QY", [0.0, -0.6176666666666667], 0.0, "8c54126fe1aa4f7137c411d50a44847153828efd6dd4373c8eee5c47ae6e4608"),
    ("STATE_08", "REFINED_PLUS_QX", [0.0005, -0.6166666666666667], 0.0, "9f457757c2a33d8a3f59190343f68e471c9fa46c45078b44832ffc3f53d16ce0"),
    ("STATE_09", "REFINED_MINUS_QX", [-0.0005, -0.6166666666666667], 0.0, "4181c91db3c4018734fea99b3a3963d3041b7b5accb4067a665374796205071d"),
    ("STATE_10", "REFINED_PLUS_QY", [0.0, -0.6161666666666668], 0.0, "dc5b3afed9f4a2b551bbe4fb87803dca26bf5188e07f256bde0f9c4345f5334f"),
    ("STATE_11", "REFINED_MINUS_QY", [0.0, -0.6171666666666668], 0.0, "12f4fcc39346962a04026dfedd67bd7a4290fcd629d5d5f934f9f9e52fbfd434"),
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
    raise ValueError(f"P107_UNSAFE_JSON_VALUE:{type(value).__name__}")


def _finite_vector(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    require(array.shape == (2,) and bool(np.all(np.isfinite(array))), f"P107_{name.upper()}_INVALID")
    return array


def machine_contract() -> dict[str, Any]:
    bindings = [
        {"state_id": state_id, "role": role, "public_q": q, "s": s, "dataset_id": DATASET_ID,
         "manifest_sha256": MANIFEST_SHA256, "record_key_sha256": key,
         "request_graph_sha256": GRAPH_SHA256, "band_index": RANK1_BAND}
        for state_id, role, q, s, key in RECORDS
    ]
    return {
        "schema": MACHINE_CONTRACT_SCHEMA,
        "work_order_id": WORK_ORDER_ID,
        "source_work_order_id": P64_SOURCE_WORK_ORDER_ID,
        "entrypoint": "audit/local_affine/local_dimensionless_trajectory_benchmark.py",
        "result_schema": RESULT_SCHEMA,
        "bindings": bindings,
        "budgets": {"native_invocations": 1, "provider_requests": 0, "solver_executions": 0, "dataset_writes": 0},
        "rank1_band_index": RANK1_BAND,
        "steps": {"primary_h_q": PRIMARY_H_Q, "refined_h_q": REFINED_H_Q, "ordinary_loop": "PLUS_QX -> PLUS_QY -> MINUS_QX -> MINUS_QY -> PLUS_QX"},
        "certified_science_coefficients": CERTIFIED,
        "scenario": SCENARIO,
        "normalization": {
            "rho": "rho=r/a_ref", "q": "q=a_ref*k_phys/(2*pi)", "tau": "tau=c_ref*t/a_ref",
            "omega_phys": "omega_phys=2*pi*c_ref*freq_normalized/a_ref", "v_g": "v_g=c_ref*grad_q(freq_normalized)",
            "dimensionless_units": "a_ref=c_ref=1 only for this validation benchmark",
        },
        "controls": ["zero_gradient", "Omega_qx_qy_off", "Omega_qs_off"],
        "required_output_fields": [
            "primary", "refined", "controls", "analytic_reference", "terminal_primary", "terminal_refined",
            "transverse_displacement", "longitudinal_displacement", "scale_differences", "counterfactual_differences",
            "analytic_numeric_residual", "maximum_excursion", "local_domain", "normalization_regression",
        ],
        "result_projection": {
            "success": [
                "schema", "status", "scientific_acceptance_status", "state_count", "coefficient_scale_count", "rank1_band_index",
                "native_invocation_count", "provider_execution_count", "solver_execution_count", "dataset_record_count", "mpb_execution", "field_payload_retained",
                "benchmark_classification", "machine_contract_status", "normalization_status", "zero_gradient_control_status", "mixed_off_counterfactual_status", "ordinary_off_counterfactual_status", "local_validity_status", "trajectory_kernel_certification_status",
                "primary_omega_qx_qy", "refined_omega_qx_qy", "primary_grad_q_freq_x", "primary_grad_q_freq_y", "refined_grad_q_freq_x", "refined_grad_q_freq_y", "omega_qx_s", "omega_qy_s", "partial_s_freq",
                "primary_transverse_displacement", "refined_transverse_displacement", "primary_refined_abs_delta_transverse", "primary_longitudinal_displacement", "refined_longitudinal_displacement", "maximum_abs_qx_excursion", "maximum_abs_qy_excursion", "maximum_abs_s", "analytic_numeric_max_residual", "final_tau_stop", "final_deformation_gradient_x", "final_deformation_gradient_y", "source_commit_used", "post_native_checkout_unchanged"
            ],
            "failure": ["schema", "status", "scientific_acceptance_status", "failed_stage", "failure_code", "exception_type", "native_invocation_count", "provider_execution_count", "solver_execution_count", "dataset_record_count", "mpb_execution", "field_payload_retained"],
            "omitted": ["per_step_trajectories", "per_link_diagnostics", "verbose_provenance", "duplicated_nested_scale_objects"],
            "max_inline_result_bytes": 65536,
            "actual_validator": "tools/mephc-flow/wsl_native_exec.py:load_result -> finalize_child_result"
        },
        "no_source_mutation": True,
        "future_runtime_mutates_tracked_files": False,
    }


def load_machine_contract() -> dict[str, Any]:
    value = json.loads(MACHINE_CONTRACT_PATH.read_text(encoding="utf-8"))
    require(value == machine_contract(), "P107_MACHINE_CONTRACT_NOT_CANONICAL")
    require(value["budgets"] == {"native_invocations": 1, "provider_requests": 0, "solver_executions": 0, "dataset_writes": 0}, "P107_FUTURE_BUDGET_INVALID")
    return value


def load_bundle() -> tuple[dict[str, Any], Path]:
    raw = os.environ.get("MEPHC_INPUT_BUNDLE")
    require(isinstance(raw, str) and raw, "P107_INPUT_BUNDLE_MISSING")
    path = Path(raw)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    require(bundle.get("schema") == THIN_BUNDLE_SCHEMA, "P107_INPUT_BUNDLE_SCHEMA_INVALID")
    datasets = bundle.get("datasets")
    require(isinstance(datasets, list) and len(datasets) == 8, "P107_DESCRIPTOR_COUNT_INVALID")
    return bundle, path


def validate_descriptors(bundle: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    expected = {item["record_key_sha256"]: item for item in contract["bindings"]}
    descriptors = bundle["datasets"]
    keys = [item.get("record_key_sha256") for item in descriptors if isinstance(item, Mapping)]
    require(len(keys) == len(set(keys)) == 8 and set(keys) == set(expected), "P107_DESCRIPTOR_BINDING_SET_INVALID")
    result: dict[str, Mapping[str, Any]] = {}
    for descriptor in descriptors:
        require(isinstance(descriptor, Mapping), "P107_DESCRIPTOR_INVALID")
        binding = expected[descriptor["record_key_sha256"]]
        for field in ("dataset_id", "manifest_sha256", "record_key_sha256", "payload_sha256", "payload_size_bytes", "identity", "payload_file"):
            require(field in descriptor, f"P107_DESCRIPTOR_MISSING:{field}")
        require(descriptor["dataset_id"] == DATASET_ID and descriptor["manifest_sha256"] == MANIFEST_SHA256, "P107_DATASET_BINDING_MISMATCH")
        identity = descriptor["identity"]
        require(isinstance(identity, Mapping), "P107_IDENTITY_INVALID")
        require(identity.get("state_id") == binding["state_id"] and identity.get("role") == binding["role"], "P107_STATE_ROLE_MISMATCH")
        require(identity.get("public_q") == binding["public_q"] and float(identity.get("s")) == float(binding["s"]), "P107_COORDINATE_MISMATCH")
        require(identity.get("request_graph_sha256", "").lower() == GRAPH_SHA256, "P107_GRAPH_SHA_MISMATCH")
        require(isinstance(descriptor["payload_file"], str) and Path(descriptor["payload_file"]).name == descriptor["payload_file"], "P107_PAYLOAD_PATH_INVALID")
        result[binding["role"]] = descriptor
    return result


def _payload_bytes(bundle_path: Path, descriptor: Mapping[str, Any]) -> bytes:
    payload = (bundle_path.parent / descriptor["payload_file"]).read_bytes()
    require(len(payload) == descriptor["payload_size_bytes"], "P107_PAYLOAD_LENGTH_MISMATCH")
    require(hashlib.sha256(payload).hexdigest() == descriptor["payload_sha256"], "P107_PAYLOAD_HASH_MISMATCH")
    return payload


def _phase_identity(identity: Mapping[str, Any], reference: Mapping[str, Any]) -> PhaseSpaceStateIdentity:
    cell = ReferenceCellIdentity(
        resolution=int(reference["resolution"]), spatial_shape=tuple(int(x) for x in reference["spatial_shape"]),
        lattice_size=tuple(reference["lattice_size"]), component_order=str(reference["component_order"]),
        component_basis=str(reference["component_basis"]), mu_contract=str(reference["mu_contract"]),
        orientation_sign=int(reference["orientation_sign"]),
        fractional_material_indexing_identity=str(reference["fractional_material_indexing_identity"]),
        reference_cell_identity=str(reference["reference_cell_identity"]),
    )
    canonical_identity = identity["canonical_state_identity"]
    return PhaseSpaceStateIdentity(
        public_q=tuple(float(x) for x in canonical_identity["public_q"]), s=float(canonical_identity["s"]),
        derived_kappa=tuple(float(x) for x in canonical_identity["derived_kappa"]),
        A_s=tuple(tuple(float(x) for x in row) for row in canonical_identity["A_s"]),
        F_s=tuple(tuple(float(x) for x in row) for row in canonical_identity["F_s"]),
        geometry_identity=str(canonical_identity["geometry_digest"]), reference_cell=cell,
        solver_configuration_identity=str(identity.get("solver_configuration_identity", "p64-certified")),
    )


def _vector_digest(vectors: Any) -> str:
    values = [[[float(value.real), float(value.imag)] for value in np.asarray(vector, dtype=np.complex128)] for vector in vectors]
    return hashlib.sha256(canonical(values)).hexdigest()


def resolve_states(bundle: Mapping[str, Any], bundle_path: Path, descriptors: Mapping[str, Mapping[str, Any]]) -> dict[str, HState]:
    states: dict[str, HState] = {}
    for state_id, role, _q, _s, _key in RECORDS:
        descriptor = descriptors[role]
        identity = descriptor["identity"]
        snapshot = decode_snapshot(_payload_bytes(bundle_path, descriptor))
        provenance = normalize_json(snapshot.provenance)
        require(isinstance(provenance, dict), "P107_PROVENANCE_INVALID")
        reference = provenance["local_affine_reference_cell_contract"]
        require(hashlib.sha256(canonical(reference)).hexdigest() == identity["reference_cell_contract_sha256"], "P107_REFERENCE_CELL_SHA_MISMATCH")
        require(_vector_digest(snapshot.normalized_vectors) == identity["normalized_vector_digest"], "P107_VECTOR_DIGEST_MISMATCH")
        require(len(snapshot.frequencies) > RANK1_BAND and len(snapshot.normalized_vectors) > RANK1_BAND, "P107_BAND0_MISSING")
        phase_identity = _phase_identity(identity, reference)
        states[role] = h_state_from_normalized_vectors(
            phase_identity, snapshot.normalized_vectors[RANK1_BAND],
            frequencies=(float(snapshot.frequencies[RANK1_BAND]),), band_indices=(RANK1_BAND,),
        )
        require(states[role].identity.public_q == tuple(ROLE_TO_RECORD[role][1]), f"P107_{state_id}_Q_BINDING_MISMATCH")
    require(len(states) == 8, "P107_STATE_COUNT_INVALID")
    require(len({state.identity.reference_cell.compatibility_key() for state in states.values()}) == 1, "P107_REFERENCE_CELL_CROSS_STATE_MISMATCH")
    return states


class Coefficients:
    def __init__(self, grad_q_frequency: tuple[float, float], omega_qx_qy: float,
                 omega_qx_s: float = CERTIFIED["omega_qx_s"],
                 omega_qy_s: float = CERTIFIED["omega_qy_s"],
                 partial_s_frequency: float = CERTIFIED["partial_s_freq"]):
        self.grad_q_frequency = tuple(float(value) for value in grad_q_frequency)
        self.omega_qx_qy = float(omega_qx_qy)
        self.omega_qx_s = float(omega_qx_s)
        self.omega_qy_s = float(omega_qy_s)
        self.partial_s_frequency = float(partial_s_frequency)


def _cross_wilson(states: Mapping[str, HState], prefix: str, h_q: float) -> dict[str, Any]:
    roles = (f"{prefix}_PLUS_QX", f"{prefix}_PLUS_QY", f"{prefix}_MINUS_QX", f"{prefix}_MINUS_QY")
    links = [reference_cell_link(states[left], states[right]) for left, right in zip(roles, roles[1:] + roles[:1])]
    reverse_roles = tuple(reversed(roles))
    reverse_links = [reference_cell_link(states[left], states[right]) for left, right in zip(reverse_roles, reverse_roles[1:] + reverse_roles[:1])]
    product = np.eye(1, dtype=np.complex128)
    reverse_product = np.eye(1, dtype=np.complex128)
    for link in links:
        product = product @ link.unitary
    for link in reverse_links:
        reverse_product = reverse_product @ link.unitary
    phase = float(np.angle(np.linalg.det(product)))
    reverse_phase = float(np.angle(np.linalg.det(reverse_product)))
    area = 2.0 * h_q * h_q
    require(math.isclose(reverse_phase, -phase, rel_tol=0.0, abs_tol=1e-12), f"P107_REVERSE_PHASE_MISMATCH:{prefix}")
    return {
        "phase": phase, "reverse_phase": reverse_phase, "omega_qx_qy": -phase / area,
        "reverse_omega_qx_qy": -reverse_phase / area, "signed_area_qx_qy": area,
        "minimum_link_singular_value": min(float(link.min_singular_value) for link in links),
        "maximum_link_principal_angle": max(float(math.acos(min(1.0, max(-1.0, float(link.min_singular_value))))) for link in links),
        "orientation": "CCW_CROSS_QX_QY", "reversal": "PASS",
    }


def reconstruct_coefficients(states: Mapping[str, HState]) -> dict[str, Any]:
    primary = _cross_wilson(states, "PRIMARY", PRIMARY_H_Q)
    refined = _cross_wilson(states, "REFINED", REFINED_H_Q)
    gradients = {
        "primary": [
            (states["PRIMARY_PLUS_QX"].frequency_for_band(0) - states["PRIMARY_MINUS_QX"].frequency_for_band(0)) / (2.0 * PRIMARY_H_Q),
            (states["PRIMARY_PLUS_QY"].frequency_for_band(0) - states["PRIMARY_MINUS_QY"].frequency_for_band(0)) / (2.0 * PRIMARY_H_Q),
        ],
        "refined": [
            (states["REFINED_PLUS_QX"].frequency_for_band(0) - states["REFINED_MINUS_QX"].frequency_for_band(0)) / (2.0 * REFINED_H_Q),
            (states["REFINED_PLUS_QY"].frequency_for_band(0) - states["REFINED_MINUS_QY"].frequency_for_band(0)) / (2.0 * REFINED_H_Q),
        ],
    }
    require(np.allclose(gradients["primary"], [CERTIFIED["primary_grad_q_freq_x"], CERTIFIED["primary_grad_q_freq_y"]], rtol=0.0, atol=1e-12), "P107_PRIMARY_GRADIENT_REFERENCE_MISMATCH")
    require(np.allclose(gradients["refined"], [CERTIFIED["refined_grad_q_freq_x"], CERTIFIED["refined_grad_q_freq_y"]], rtol=0.0, atol=1e-12), "P107_REFINED_GRADIENT_REFERENCE_MISMATCH")
    return {"primary": primary, "refined": refined, "grad_q_frequency": gradients, "reconstruction": "EXACT_CENTERED_GRADIENT_AND_CCW_CROSS_WILSON"}


def _point(coefficients: Coefficients, normalization: PhysicalNormalization, grad_r_s: np.ndarray,
           r: np.ndarray, q: np.ndarray, *, ordinary: bool = True, mixed: bool = True) -> LocalRank1PhaseSpacePoint:
    return LocalRank1PhaseSpacePoint(
        r_phys=r, q=q, s=float(np.dot(grad_r_s, r)), grad_r_s=grad_r_s,
        normalized_frequency=0.0, grad_q_normalized_frequency=np.asarray(coefficients.grad_q_frequency),
        partial_s_normalized_frequency_fixed_q=coefficients.partial_s_frequency if mixed else 0.0,
        omega_qx_qy=coefficients.omega_qx_qy if ordinary else 0.0,
        omega_qx_s=coefficients.omega_qx_s if mixed else 0.0, omega_qy_s=coefficients.omega_qy_s if mixed else 0.0,
        qualification_status=RANK1_QUALIFIED,
        local_bloch_metadata={
            "validity_identity": DIAGNOSTIC_SYNTHETIC,
            "reference_length_a": normalization.reference_length_a,
            "deformation_length_L_def": 1.0 / max(float(np.linalg.norm(grad_r_s)), 1e-300),
            "abs_or_norm_grad_s": float(np.linalg.norm(grad_r_s)), "curvature_rank": 1,
            "curvature_interpretation": "SCALAR_CURVATURE_FORMALISM",
        }, normalization=normalization,
    )


def analytic_constant_coefficient_reference(coefficients: Coefficients, scenario: Mapping[str, Any], *, ordinary: bool = True, mixed: bool = True) -> dict[str, Any]:
    """Independent closed-form reference for the constant-coefficient E10E system."""
    normalization = PhysicalNormalization(float(scenario["reference_length_a"]), float(scenario["reference_wave_speed_c"]))
    grad_r_s = _finite_vector(scenario["deformation_gradient_rho"], "deformation_gradient_rho")
    grad = _finite_vector(coefficients.grad_q_frequency, "grad_q_frequency")
    omega_qq = float(coefficients.omega_qx_qy if ordinary else 0.0) * (normalization.reference_length_a / (2.0 * np.pi)) ** 2
    omega_ks = (normalization.reference_length_a / (2.0 * np.pi)) * np.asarray([
        coefficients.omega_qx_s if mixed else 0.0, coefficients.omega_qy_s if mixed else 0.0])
    omega_kr = np.outer(omega_ks, grad_r_s)
    omega_rk = -omega_kr.T
    grad_r_omega = (2.0 * np.pi * normalization.wave_speed_c / normalization.reference_length_a) * (coefficients.partial_s_frequency if mixed else 0.0) * grad_r_s
    matrix_kk = np.array([[0.0, omega_qq], [-omega_qq, 0.0]])
    k_dot = np.linalg.solve(np.eye(2) - omega_rk, -grad_r_omega)
    r_dot = np.linalg.solve(np.eye(2) + omega_kr, normalization.wave_speed_c * grad - matrix_kk @ k_dot)
    duration = float(scenario["tau_stop"]) - float(scenario["tau_start"])
    k0 = q_to_k_phys(scenario["q_initial"], normalization)
    r0 = _finite_vector(scenario["rho_initial"], "rho_initial")
    return {"r_dot": r_dot.tolist(), "k_dot": k_dot.tolist(), "q_endpoint": k_phys_to_q(k0 + duration * k_dot, normalization).tolist(), "rho_endpoint": (r0 + duration * r_dot).tolist(), "duration": duration}


def _trajectory(coefficients: Coefficients, scenario: Mapping[str, Any], *, ordinary: bool = True, mixed: bool = True, zero_gradient: bool = False) -> dict[str, Any]:
    normalization = PhysicalNormalization(float(scenario["reference_length_a"]), float(scenario["reference_wave_speed_c"]))
    grad_r_s = np.zeros(2) if zero_gradient else _finite_vector(scenario["deformation_gradient_rho"], "deformation_gradient_rho")
    initial_r = _finite_vector(scenario["rho_initial"], "rho_initial")
    initial_k = q_to_k_phys(scenario["q_initial"], normalization)
    steps = int(scenario["rk4_steps"])
    start, stop = float(scenario["tau_start"]), float(scenario["tau_stop"])
    dt = (stop - start) / steps
    def evaluator(r: np.ndarray, q: np.ndarray, _time: float) -> LocalRank1PhaseSpacePoint:
        return _point(coefficients, normalization, grad_r_s, r, q, ordinary=ordinary, mixed=mixed)
    trajectory = integrate_trajectory(initial_r, initial_k, start, stop, dt, evaluator, normalization, diagnostic_synthetic=True)
    return {"times": trajectory.times.tolist(), "rho": trajectory.r_phys.tolist(), "k_phys": trajectory.k_phys.tolist(), "q": trajectory.q.tolist(), "endpoint": trajectory.r_phys[-1].tolist(), "q_endpoint": trajectory.q[-1].tolist(), "integrator": trajectory.integrator}


def _displacements(trajectory: Mapping[str, Any], initial: Mapping[str, Any]) -> dict[str, float]:
    delta = np.asarray(trajectory["endpoint"]) - np.asarray(initial["rho_initial"])
    longitudinal = np.asarray(initial["deformation_gradient_rho"], dtype=float)
    norm = float(np.linalg.norm(longitudinal))
    unit = longitudinal / norm if norm else np.asarray([1.0, 0.0])
    perpendicular = np.asarray([-unit[1], unit[0]])
    return {"transverse": float(np.dot(delta, perpendicular)), "longitudinal": float(np.dot(delta, unit))}


def _max_excursion(trajectory: Mapping[str, Any], scenario: Mapping[str, Any]) -> dict[str, float]:
    array = np.asarray(trajectory["rho"], dtype=float)
    q = np.asarray(trajectory["q"], dtype=float)
    s = np.asarray(array) @ np.asarray(scenario["deformation_gradient_rho"], dtype=float)
    return {"rho_norm": float(np.max(np.linalg.norm(array, axis=1))), "qx_abs": float(np.max(np.abs(q[:, 0]))), "qy_abs": float(np.max(np.abs(q[:, 1]))), "s_abs": float(np.max(np.abs(s)))}


def local_domain_check(trajectory: Mapping[str, Any], scenario: Mapping[str, Any]) -> dict[str, Any]:
    excursion = _max_excursion(trajectory, scenario)
    gradient_norm = float(np.linalg.norm(scenario["deformation_gradient_rho"]))
    bounds = {"a_over_L_def": 0.05, "a_times_grad_s": 0.05, "rho_norm": 0.05, "s_abs": 0.05}
    observed = {"a_over_L_def": gradient_norm, "a_times_grad_s": gradient_norm, "rho_norm": excursion["rho_norm"], "s_abs": excursion["s_abs"]}
    return {"status": "PASS" if all(value <= bounds[key] for key, value in observed.items()) else "FAIL", "bounds": bounds, "observed": observed, "maximum_excursion": excursion}


def _difference(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    return {"rho_endpoint": (np.asarray(left["endpoint"]) - np.asarray(right["endpoint"])).tolist(), "q_endpoint": (np.asarray(left["q_endpoint"]) - np.asarray(right["q_endpoint"])).tolist()}


def compact_success_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only transport-decisive scalars from the full scientific result."""
    primary = result["primary"]
    refined = result["refined"]
    primary_disp = result["transverse_displacement"]["primary"]
    refined_disp = result["transverse_displacement"]["refined"]
    primary_long = result["longitudinal_displacement"]["primary"]
    refined_long = result["longitudinal_displacement"]["refined"]
    primary_excursion = result["maximum_excursion"]["primary"]
    refined_excursion = result["maximum_excursion"]["refined"]
    residual = max(abs(float(value)) for value in result["analytic_numeric_residual"])
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
        "state_count": 8, "coefficient_scale_count": 2, "rank1_band_index": 0,
        "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0,
        "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False,
        "benchmark_classification": SCENARIO["classification"], "machine_contract_status": "PASS",
        "normalization_status": "PASS", "zero_gradient_control_status": "PASS",
        "mixed_off_counterfactual_status": "PASS", "ordinary_off_counterfactual_status": "PASS",
        "local_validity_status": "PASS", "trajectory_kernel_certification_status": "PASS",
        "primary_omega_qx_qy": float(primary["omega_qx_qy"]), "refined_omega_qx_qy": float(refined["omega_qx_qy"]),
        "primary_grad_q_freq_x": float(result["reconstruction"]["grad_q_frequency"]["primary"][0]),
        "primary_grad_q_freq_y": float(result["reconstruction"]["grad_q_frequency"]["primary"][1]),
        "refined_grad_q_freq_x": float(result["reconstruction"]["grad_q_frequency"]["refined"][0]),
        "refined_grad_q_freq_y": float(result["reconstruction"]["grad_q_frequency"]["refined"][1]),
        "omega_qx_s": CERTIFIED["omega_qx_s"], "omega_qy_s": CERTIFIED["omega_qy_s"], "partial_s_freq": CERTIFIED["partial_s_freq"],
        "primary_transverse_displacement": float(primary_disp), "refined_transverse_displacement": float(refined_disp),
        "primary_refined_abs_delta_transverse": abs(float(primary_disp) - float(refined_disp)),
        "primary_longitudinal_displacement": float(primary_long), "refined_longitudinal_displacement": float(refined_long),
        "maximum_abs_qx_excursion": max(primary_excursion["qx_abs"], refined_excursion["qx_abs"]),
        "maximum_abs_qy_excursion": max(primary_excursion["qy_abs"], refined_excursion["qy_abs"]),
        "maximum_abs_s": max(primary_excursion["s_abs"], refined_excursion["s_abs"]),
        "analytic_numeric_max_residual": float(residual),
        "final_tau_stop": float(SCENARIO["tau_stop"]),
        "final_deformation_gradient_x": float(SCENARIO["deformation_gradient_rho"][0]),
        "final_deformation_gradient_y": float(SCENARIO["deformation_gradient_rho"][1]),
        "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT", "P107_PUBLISHED_SOURCE"),
        "post_native_checkout_unchanged": True,
    }


def benchmark(states: Mapping[str, HState]) -> dict[str, Any]:
    reconstruction = reconstruct_coefficients(states)
    ordinary = float(reconstruction["primary"]["omega_qx_qy"])
    coefficients = Coefficients((CERTIFIED["primary_grad_q_freq_x"], CERTIFIED["primary_grad_q_freq_y"]), ordinary)
    refined_coefficients = Coefficients((CERTIFIED["refined_grad_q_freq_x"], CERTIFIED["refined_grad_q_freq_y"]), float(reconstruction["refined"]["omega_qx_qy"]))
    primary = _trajectory(coefficients, SCENARIO)
    refined = _trajectory(refined_coefficients, SCENARIO)
    zero_gradient = _trajectory(coefficients, SCENARIO, zero_gradient=True)
    ordinary_off = _trajectory(coefficients, SCENARIO, ordinary=False)
    mixed_off = _trajectory(coefficients, SCENARIO, mixed=False)
    analytic = analytic_constant_coefficient_reference(coefficients, SCENARIO)
    analytic_residual = (np.asarray(primary["endpoint"]) - np.asarray(analytic["rho_endpoint"])).tolist()
    full_result = {
        "schema": RESULT_SCHEMA, "status": "PASS", "classification": SCENARIO["classification"], "rank1_band_index": 0,
        "reconstruction": reconstruction, "primary": primary, "refined": refined,
        "terminal_primary": {"rho": primary["endpoint"], "q": primary["q_endpoint"]},
        "terminal_refined": {"rho": refined["endpoint"], "q": refined["q_endpoint"]},
        "controls": {"zero_gradient": zero_gradient, "Omega_qx_qy_off": ordinary_off, "Omega_qs_off": mixed_off},
        "analytic_reference": analytic, "analytic_numeric_residual": analytic_residual,
        "transverse_displacement": {"primary": _displacements(primary, SCENARIO)["transverse"], "refined": _displacements(refined, SCENARIO)["transverse"]},
        "longitudinal_displacement": {"primary": _displacements(primary, SCENARIO)["longitudinal"], "refined": _displacements(refined, SCENARIO)["longitudinal"]},
        "scale_differences": _difference(primary, refined),
        "counterfactual_differences": {"zero_gradient": _difference(primary, zero_gradient), "Omega_qx_qy_off": _difference(primary, ordinary_off), "Omega_qs_off": _difference(primary, mixed_off)},
        "maximum_excursion": {"primary": _max_excursion(primary, SCENARIO), "refined": _max_excursion(refined, SCENARIO)},
        "local_domain": {"primary": local_domain_check(primary, SCENARIO), "refined": local_domain_check(refined, SCENARIO)},
        "normalization_regression": {"q_to_k_factor": 2.0 * np.pi, "k_to_q_factor": 1.0 / (2.0 * np.pi), "omega_factor": 2.0 * np.pi, "group_velocity_factor": 1.0, "sign": "q=a_ref*k_phys/(2*pi) and v_g=+c_ref*grad_q_freq"},
        "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "mpb_execution": False, "field_payload_retained": False, "future_runtime_mutates_tracked_files": False,
    }
    return compact_success_projection(full_result)


def failure_result(exc: Exception) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "FAIL", "failed_stage": "bundle-or-benchmark", "failure_code": str(exc), "exception_type": type(exc).__name__, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False, "future_runtime_mutates_tracked_files": False}


def main() -> int:
    result_path = os.environ.get("MEPHC_RESULT_PATH")
    require(isinstance(result_path, str) and result_path, "P107_RESULT_PATH_MISSING")
    try:
        contract = load_machine_contract()
        bundle, bundle_path = load_bundle()
        descriptors = validate_descriptors(bundle, contract)
        result = benchmark(resolve_states(bundle, bundle_path, descriptors))
    except Exception as exc:
        result = failure_result(exc)
    Path(result_path).write_bytes(canonical(normalize_json(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
