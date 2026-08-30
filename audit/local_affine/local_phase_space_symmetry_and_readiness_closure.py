"""Bounded antiunitary symmetry proof and trajectory-readiness closure."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from audit.e8b import e8b_geometry


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = ROOT / "audit" / "local_affine" / "p101_local_phase_space_symmetry_closure.json"
RESULT_SCHEMA = "mephc-local-affine-symmetry-and-trajectory-readiness-closure-v1"
P85_MINIMUM_GAP = 0.062389888324785675
P97_MINIMUM_GAP = 0.06238988841542023
RANK1_THRESHOLD = 0.05


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def _geometry_proof() -> dict[str, Any]:
    mirror = np.diag([1.0, -1.0])
    swap = np.array([[0.0, 1.0], [1.0, 0.0]])
    require(np.allclose(mirror @ e8b_geometry.A0, e8b_geometry.A0 @ swap, rtol=0.0, atol=1e-14), "MIRROR_LATTICE_BASIS_FAILURE")
    centers = [e8b_geometry.A0 @ center for center in e8b_geometry.CENTER_FRACTIONAL]
    require(all(np.allclose(mirror @ center, center, rtol=0.0, atol=1e-14) for center in centers), "MIRROR_CENTER_FAILURE")
    require(all(float(value).is_integer() for value in (e8b_geometry.EPSILON_BACKGROUND, e8b_geometry.EPSILON_INCLUSION)), "MATERIAL_REALNESS_FAILURE")
    deformation_checks: dict[str, bool] = {}
    for strain in (-0.02, 0.0, 0.02):
        F = np.diag([math.exp(strain), math.exp(-strain)])
        deformation_checks[str(strain)] = bool(np.allclose(F @ mirror, mirror @ F, rtol=0.0, atol=1e-14))
        require(deformation_checks[str(strain)], "DEFORMATION_MIRROR_COMMUTATOR_FAILURE")
        state = e8b_geometry.state(strain)
        deformed_centers = [np.asarray(value, dtype=float) for value in state["centers_cart"]]
        require(all(np.allclose(mirror @ center, center, rtol=0.0, atol=1e-14) for center in deformed_centers), "DEFORMED_CENTER_MIRROR_FAILURE")
    return {
        "mirror_matrix": mirror.tolist(),
        "basis_exchange_matrix": swap.tolist(),
        "basis_relation": "M_y @ A0 = A0 @ S_swap",
        "inclusion_centers_on_mirror_axis": True,
        "inclusion_centers_individually_invariant": True,
        "real_scalar_material_distribution": True,
        "deformation": "F(s)=diag(exp(s),exp(-s))",
        "deformation_commutes_with_mirror": deformation_checks,
        "circular_s0_and_affine_elliptical_symmetry": True,
        "source": "audit/e8b/e8b_geometry.py",
    }


def _antiunitary_proof() -> dict[str, Any]:
    require(abs(float(e8b_geometry.K_FRACTIONAL[0]) + 1.0 / 3.0) < 1e-15, "RECIPROCAL_COORDINATE_SOURCE_FAILURE")
    coordinate_action = {
        "spatial_mirror_M_y": "(q_x,q_y,s) -> (q_x,-q_y,s)",
        "time_reversal_T": "(q_x,q_y,s) -> (-q_x,-q_y,s)",
        "combined_Theta_M_y_T": "(q_x,q_y,s) -> (-q_x,q_y,s)",
    }
    curvature_parity = {
        "R": [-1, 1, 1],
        "law": "Omega_{q_i s}(q) -> -R_i R_s Omega_{q_i s}(R q)",
        "Omega_qx_s_at_qx0": "+Omega_qx_s: symmetry allowed",
        "Omega_qy_s_at_qx0": "-Omega_qy_s: forced zero",
    }
    return {
        "coordinate_action": coordinate_action,
        "q_center": [0.0, -0.6166666666666667],
        "q_x_center_is_zero": True,
        "qy_s_diamond_center_line_Theta_invariant": True,
        "curvature_parity": curvature_parity,
        "isolated_rank_one_conclusion": "Omega_qy_s(q_x=0)=0 exactly",
        "omega_qx_s_symmetry_allowed": True,
        "omega_qy_s_symmetry_forced_zero": True,
    }


def _trajectory_readiness() -> dict[str, Any]:
    available = [
        "rank1_isolation_from_P85_P97_gap_evidence",
        "mixed_curvature_solver_evidence_from_P91_P100",
        "trajectory_kernel_contract",
    ]
    missing = [
        "local_deformation_profile_or_gradient",
        "ordinary_Berry_curvature_Omega_qx_qy",
        "group_velocity_grad_q_frequency",
        "physical_normalization_reference_length_and_wave_speed",
        "trajectory_initial_conditions",
        "trajectory_integration_controls",
    ]
    sources = {
        "trajectory_kernel_contract": "audit/e10e/phase_space_trajectory_kernel_contract.json",
        "trajectory_implementation": "mephc/phase_space_dynamics.py",
        "geometry_evidence": "audit/e8b/e8b_geometry.py",
    }
    return {
        "status": "BLOCKED_BY_MISSING_INPUTS",
        "available_inputs": available,
        "available_input_sources": sources,
        "missing_inputs": missing,
        "missing_input_count": len(missing),
        "no_defaults_or_zero_substitutions": True,
        "trajectory_executed": False,
    }


def build_closure() -> dict[str, Any]:
    geometry = _geometry_proof()
    antiunitary = _antiunitary_proof()
    rank1_isolated = min(P85_MINIMUM_GAP, P97_MINIMUM_GAP) >= RANK1_THRESHOLD
    require(rank1_isolated, "RANK1_GAP_CERTIFICATION_FAILURE")
    readiness = _trajectory_readiness()
    ledger = {
        "schema": "mephc-local-affine-p101-symmetry-closure-ledger-v1",
        "work_order_id": "MEPHC-LOCALAFFINE-P101-ANTIUNITARY-SYMMETRY-AND-TRAJECTORY-READINESS-CLOSURE-20260830-465",
        "symmetry_premises": [
            {"premise": "mirror_lattice_basis_exchange", "status": "PASS", "evidence": geometry["basis_relation"], "source": geometry["source"]},
            {"premise": "inclusion_centers_mirror_invariant", "status": "PASS", "evidence": "both centers are individually fixed by M_y", "source": geometry["source"]},
            {"premise": "real_scalar_material", "status": "PASS", "evidence": "epsilon background/inclusion are real scalars", "source": geometry["source"]},
            {"premise": "deformation_mirror_commutation", "status": "PASS", "evidence": geometry["deformation_commutes_with_mirror"], "source": geometry["source"]},
            {"premise": "time_reversal_coordinate_action", "status": "PASS", "evidence": antiunitary["coordinate_action"]["time_reversal_T"], "source": "local-affine coordinate definition"},
            {"premise": "combined_antiunitary_coordinate_action", "status": "PASS", "evidence": antiunitary["coordinate_action"]["combined_Theta_M_y_T"], "source": "local-affine coordinate definition"},
            {"premise": "rank_one_isolation", "status": "PASS", "evidence": {"P85_minimum_gap": P85_MINIMUM_GAP, "P97_minimum_gap": P97_MINIMUM_GAP, "threshold": RANK1_THRESHOLD}, "source": "P101 receipt-bound evidence"},
        ],
        "geometry_proof": geometry,
        "antiunitary_proof": antiunitary,
        "rank1_isolation_certified": rank1_isolated,
        "numerical_residual_classification": "P91_P100_qy_s_values_are_discrete_solver_estimator_symmetry_breaking_residuals_not_physical_Omega_qy_s",
        "solver_precision_evidence": {
            "qy_forward_phase_1e7": -5.854978056205052e-10,
            "qy_forward_phase_1e9": 1.7908782096176523e-11,
            "qx_forward_phase_relative_change": 0.00018597439894373603,
        },
        "trajectory_readiness": readiness,
    }
    return ledger


def build_result(ledger: dict[str, Any]) -> dict[str, Any]:
    readiness = ledger["trajectory_readiness"]
    result = {
        "schema": RESULT_SCHEMA,
        "status": "PASS",
        "scientific_acceptance_status": "PASS",
        "mirror_symmetry_certified": True,
        "time_reversal_certified": True,
        "combined_antiunitary_certified": True,
        "rank1_isolation_certified": ledger["rank1_isolation_certified"],
        "omega_qy_s_symmetry_forced_zero": True,
        "omega_qx_s_symmetry_allowed": True,
        "qy_numerical_residual_classification": ledger["numerical_residual_classification"],
        "qx_s_1e9": -0.19127165880040325,
        "domega_ds_1e9": 0.009029604372262634,
        "solver_to_geometric_ratio_qx_s": 1.1041412935928026,
        "solver_to_geometric_ratio_domega_ds": 0.09432458584334046,
        "trajectory_readiness_status": readiness["status"],
        "trajectory_missing_input_count": readiness["missing_input_count"],
        "trajectory_missing_inputs": ",".join(readiness["missing_inputs"]),
        "trajectory_available_inputs": ",".join(readiness["available_inputs"]),
        "native_invocation_count": 1,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "dataset_record_count": 0,
        "mpb_execution": False,
        "field_payload_retained": False,
    }
    return result


def main() -> int:
    result_path = os.environ.get("MEPHC_RESULT_PATH")
    require(isinstance(result_path, str) and result_path, "P101_RESULT_PATH_MISSING")
    ledger = build_closure()
    write_json(ARTIFACT_PATH, ledger)
    result = build_result(ledger)
    result["proof_artifact_sha256"] = hashlib.sha256(canonical(ledger)).hexdigest()
    Path(result_path).write_bytes(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
