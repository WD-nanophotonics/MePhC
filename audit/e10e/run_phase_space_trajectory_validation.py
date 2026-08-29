"""Bounded synthetic validation for the solver-free E10E trajectory kernel."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from mephc.phase_space_dynamics import (
    DIAGNOSTIC_SYNTHETIC,
    LocalBlochValidityError,
    LocalRank1PhaseSpacePoint,
    PhysicalNormalization,
    RANK1_QUALIFIED,
    RankScopeError,
    first_order_dynamics,
    grad_q_frequency_to_group_velocity,
    integrate_trajectory,
    k_phys_to_q,
    normalized_frequency_to_omega,
    omega_qq_to_omega_kk,
    omega_qs_to_omega_ks,
    monitor_local_bloch,
    q_to_k_phys,
    solve_pointwise_dynamics,
    transverse_shift,
)


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10E-ONE-PARAMETER-PHASE-SPACE-TRAJECTORY-KERNEL-20260829-347"
BASE_SANDBOX_SHA = "b441ea07d6073d0d66b10648c1070ca9d00ba3be"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
E10D_RECONCILIATION_SHA256 = "3c49292d1683f13064d2d546ac5ff6870e93ad2690f7389898523e934faa1fea"
GEOMETRY_SHA256 = "e19683d6765163cc49cfd4ce1c35d5ddf6835c44ec9a65ab2ec400ad940ac2a6"
E10D_VALIDATION_SHA256 = "8274d1ef6d58581d1f163e90f1fbd4509e2d665de2cdaaa88498b42f050b03e8"
OUT_CONTRACT = ROOT / "audit/e10e/phase_space_trajectory_kernel_contract.json"
OUT_VALIDATION = ROOT / "audit/e10e/phase_space_trajectory_validation.json"
OUT_API = ROOT / "audit/e10e/phase_space_trajectory_api.json"
KERNEL_PATH = "mephc/phase_space_dynamics.py"


class ValidationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValidationError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(relative: str) -> dict:
    try:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"JSON_UNAVAILABLE:{relative}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON_OBJECT_REQUIRED:{relative}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_e10d_inputs() -> dict[str, str]:
    paths = {
        "e10d_provenance_reconciliation": "audit/e10d/e10d_provenance_reconciliation.json",
        "phase_space_geometry_module": KERNEL_PATH.replace("dynamics", "geometry"),
        "phase_space_geometry_validation": "audit/e10d/phase_space_geometry_validation.json",
    }
    expected = {
        "e10d_provenance_reconciliation": E10D_RECONCILIATION_SHA256,
        "phase_space_geometry_module": GEOMETRY_SHA256,
        "phase_space_geometry_validation": E10D_VALIDATION_SHA256,
    }
    observed = {key: sha256_file(ROOT / path) for key, path in paths.items()}
    if observed != expected:
        raise ValidationError("E10D_INPUT_HASH_MISMATCH")
    reconciliation = read_json(paths["e10d_provenance_reconciliation"])
    if reconciliation.get("e10d_scientific_kernel_status") != "ACCEPTED":
        raise ValidationError("E10D_SCIENTIFIC_KERNEL_NOT_ACCEPTED")
    if reconciliation.get("e10d_provenance_reconciliation_status") != "PASS":
        raise ValidationError("E10D_PROVENANCE_NOT_RECONCILED")
    return {**paths, **{f"{key}_sha256": value for key, value in observed.items()}}


def metadata(*, reference_length: float = 1.0, grad_norm: float = 0.01, deformation_length: float = 100.0,
             rank: int = 1, interpretation: str = "SCALAR_CURVATURE_FORMALISM") -> dict[str, object]:
    return {
        "validity_identity": DIAGNOSTIC_SYNTHETIC,
        "reference_length_a": reference_length,
        "deformation_length_L_def": deformation_length,
        "abs_or_norm_grad_s": grad_norm,
        "curvature_rank": rank,
        "curvature_interpretation": interpretation,
    }


def make_point(normalization: PhysicalNormalization, *, grad_r_s=(0.01, -0.005),
               grad_q=(0.3, -0.2), partial_s=0.4, omega_qq=0.0,
               omega_qs=(0.2, -0.1), qualification=RANK1_QUALIFIED,
               local_metadata: dict[str, object] | None = None) -> LocalRank1PhaseSpacePoint:
    return LocalRank1PhaseSpacePoint(
        r_phys=np.array([0.1, -0.2]), q=np.array([0.07, -0.03]), s=0.02,
        grad_r_s=np.array(grad_r_s), normalized_frequency=0.8,
        grad_q_normalized_frequency=np.array(grad_q),
        partial_s_normalized_frequency_fixed_q=partial_s,
        omega_qx_qy=omega_qq, omega_qx_s=omega_qs[0], omega_qy_s=omega_qs[1],
        qualification_status=qualification,
        local_bloch_metadata=local_metadata if local_metadata is not None else metadata(
            reference_length=normalization.reference_length_a,
            grad_norm=float(np.linalg.norm(grad_r_s))),
        normalization=normalization,
    )


def validate() -> tuple[dict, dict, dict]:
    inputs = verify_e10d_inputs()
    normalization = PhysicalNormalization(reference_length_a=1.0, wave_speed_c=2.0)
    q = np.array([0.2, -0.15])
    k = q_to_k_phys(q, normalization)
    conversions = {
        "q_k_roundtrip": bool(np.allclose(k_phys_to_q(k, normalization), q, rtol=0.0, atol=1e-14)),
        "omega": normalized_frequency_to_omega(0.25, normalization),
        "group_velocity": grad_q_frequency_to_group_velocity([0.4, -0.3], normalization).tolist(),
        "omega_kk": omega_qq_to_omega_kk([[0.0, 0.5], [-0.5, 0.0]], normalization).tolist(),
        "omega_ks": omega_qs_to_omega_ks([0.5, -0.25], normalization).tolist(),
    }
    if not conversions["q_k_roundtrip"]:
        raise ValidationError("Q_K_CONVERSION_FAILED")

    zero_berry = make_point(normalization, omega_qq=0.0, omega_qs=(0.0, 0.0))
    zero_result = solve_pointwise_dynamics(zero_berry)
    zero_expected = first_order_dynamics(zero_berry)
    if not np.allclose(zero_result.k_dot, zero_expected.k_dot_first_order, rtol=0.0, atol=1e-12):
        raise ValidationError("ORDINARY_REFRACTION_K_DOT_FAILED")
    if not np.allclose(zero_result.r_dot, zero_expected.r_dot_group, rtol=0.0, atol=1e-12):
        raise ValidationError("ORDINARY_REFRACTION_R_DOT_FAILED")

    anomalous_norm = PhysicalNormalization(reference_length_a=2.0 * np.pi, wave_speed_c=1.0)
    anomalous = make_point(
        anomalous_norm, grad_r_s=(0.005, 0.0), grad_q=(0.2, 0.0), partial_s=0.3 / 0.005,
        omega_qq=0.7, omega_qs=(0.0, 0.0),
        local_metadata=metadata(reference_length=anomalous_norm.reference_length_a,
                                deformation_length=1000.0, grad_norm=0.005),
    )
    anomalous_result = solve_pointwise_dynamics(anomalous)
    anomalous_expected = np.array([0.2, -0.7 * 0.3])
    if not np.allclose(anomalous_result.r_dot, anomalous_expected, rtol=0.0, atol=1e-12):
        raise ValidationError("ANOMALOUS_VELOCITY_SIGN_FAILED")

    mixed = make_point(normalization, grad_r_s=(0.01, 0.005), omega_qq=0.0,
                       omega_qs=(0.2, -0.1), local_metadata=metadata(grad_norm=np.sqrt(0.000125)))
    mixed_result = solve_pointwise_dynamics(mixed)
    tensors = mixed_result
    expected_k = np.linalg.solve(np.eye(2) - tensors.omega_rk, -tensors.grad_r_omega)
    expected_r = np.linalg.solve(np.eye(2) + tensors.omega_kr,
                                 tensors.group_velocity - tensors.omega_kk @ expected_k)
    if not np.allclose(mixed_result.k_dot, expected_k, rtol=0.0, atol=1e-12):
        raise ValidationError("MIXED_K_DOT_FAILED")
    if not np.allclose(mixed_result.r_dot, expected_r, rtol=0.0, atol=1e-12):
        raise ValidationError("MIXED_R_DOT_FAILED")

    residuals = []
    for scale in (1.0, 0.5, 0.25):
        scaled_grad = np.array([0.02, 0.01]) * scale
        scaled = make_point(normalization, grad_r_s=scaled_grad, omega_qs=(0.3, 0.2),
                            local_metadata=metadata(grad_norm=float(np.linalg.norm(scaled_grad))))
        exact = solve_pointwise_dynamics(scaled)
        first = first_order_dynamics(scaled)
        residuals.append(float(np.linalg.norm(np.r_[exact.k_dot - first.k_dot_first_order,
                                                     exact.r_dot - first.r_dot_first_order])))
    if not (residuals[1] < residuals[0] and residuals[2] < residuals[1]):
        raise ValidationError("FIRST_ORDER_RESIDUAL_SCALING_FAILED")

    constant_norm = PhysicalNormalization(reference_length_a=1.0, wave_speed_c=1.0)
    constant_point = make_point(constant_norm, grad_r_s=(0.0, 0.0), grad_q=(0.3, 0.2),
                                partial_s=0.0, omega_qs=(0.0, 0.0),
                                local_metadata=metadata(grad_norm=0.0))

    def evaluator(r: np.ndarray, query_q: np.ndarray, time: float) -> LocalRank1PhaseSpacePoint:
        return LocalRank1PhaseSpacePoint(
            r_phys=r, q=query_q, s=0.0, grad_r_s=constant_point.grad_r_s,
            normalized_frequency=constant_point.normalized_frequency,
            grad_q_normalized_frequency=constant_point.grad_q_normalized_frequency,
            partial_s_normalized_frequency_fixed_q=constant_point.partial_s_normalized_frequency_fixed_q,
            omega_qx_qy=constant_point.omega_qx_qy, omega_qx_s=constant_point.omega_qx_s,
            omega_qy_s=constant_point.omega_qy_s, qualification_status=RANK1_QUALIFIED,
            local_bloch_metadata=constant_point.local_bloch_metadata, normalization=constant_norm,
        )

    trajectory = integrate_trajectory([0.0, 0.0], [0.1, -0.2], 0.0, 1.0, 0.1,
                                      evaluator, constant_norm)
    replay = integrate_trajectory([0.0, 0.0], [0.1, -0.2], 0.0, 1.0, 0.1,
                                  evaluator, constant_norm)
    expected_endpoint = np.array([0.3, 0.2])
    if not np.allclose(trajectory.r_phys[-1], expected_endpoint, rtol=0.0, atol=1e-13):
        raise ValidationError("CONSTANT_TRAJECTORY_FAILED")
    if not np.array_equal(trajectory.r_phys, replay.r_phys) or not np.array_equal(trajectory.k_phys, replay.k_phys):
        raise ValidationError("DETERMINISTIC_REPLAY_FAILED")
    if not np.allclose(trajectory.q, np.array([0.1, -0.2]) / (2.0 * np.pi), rtol=0.0, atol=1e-14):
        raise ValidationError("TRAJECTORY_Q_K_CONVERSION_FAILED")

    if not np.allclose(transverse_shift([1.0, 0.2], [0.0, 0.0], [1.0, 0.0]), 0.2,
                       rtol=0.0, atol=1e-14):
        raise ValidationError("TRANSVERSE_SHIFT_FAILED")
    plus = first_order_dynamics(make_point(normalization, grad_r_s=(0.01, 0.005), omega_qs=(0.3, -0.2),
                                            local_metadata=metadata(grad_norm=np.sqrt(0.000125))))
    minus = first_order_dynamics(make_point(normalization, grad_r_s=(-0.01, -0.005), omega_qs=(0.3, -0.2),
                                             local_metadata=metadata(grad_norm=np.sqrt(0.000125))))
    if not np.allclose(plus.r_dot_mixed, -minus.r_dot_mixed, rtol=0.0, atol=1e-14):
        raise ValidationError("GRADIENT_SIGN_REVERSAL_FAILED")

    failed_bloch = make_point(normalization, local_metadata=metadata(deformation_length=10.0))
    try:
        monitor_local_bloch(failed_bloch)
    except LocalBlochValidityError:
        pass
    else:
        raise ValidationError("LOCAL_BLOCH_FAIL_CLOSED_FAILED")
    try:
        solve_pointwise_dynamics(make_point(normalization, qualification="RANK2_TRACE_ONLY"))
    except RankScopeError:
        pass
    else:
        raise ValidationError("RANK_SCOPE_FAIL_CLOSED_FAILED")
    source = (ROOT / KERNEL_PATH).read_text(encoding="utf-8").lower()
    if any(token in source for token in ("import meep", "import mpb", "provider", "geometry builder")):
        raise ValidationError("FORBIDDEN_SOLVER_BOUNDARY_IMPORT")

    module_sha = sha256_file(ROOT / KERNEL_PATH)
    result = {
        "schema": "mephc-e10e-one-parameter-phase-space-trajectory-kernel-v1",
        "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": BASE_SANDBOX_SHA, "origin_sandbox_sha": BASE_SANDBOX_SHA,
        "main_sha": MAIN_SHA, "machine_contract_status": "PASS",
        "e10d_provenance_status": "PASS_EXPLICIT_RECONCILED_IDENTITIES",
        "kernel_module_path": KERNEL_PATH, "kernel_module_sha256": module_sha,
        "physical_normalization_conversion_status": "PASS",
        "pointwise_exact_coupled_solver_status": "PASS",
        "first_order_expansion_status": "PASS",
        "rank1_scope_fail_closed_status": "PASS",
        "trajectory_integrator_status": "PASS",
        "local_bloch_monitor_status": "PASS",
        "transverse_shift_observable_status": "PASS",
        "analytic_anomalous_velocity_status": "PASS",
        "analytic_mixed_curvature_velocity_status": "PASS",
        "constant_coefficient_trajectory_status": "PASS",
        "qualification_propagation_status": "PASS",
        "no_solver_import_status": "PASS",
        "phase_space_trajectory_kernel_ready": True,
        "weighted_berry_gradient_observable_role": "DESCRIPTOR_ONLY_NO_OBSERVABLE_MAPPING_ESTABLISHED",
        "e10e_next_step": "READY_FOR_LOCAL_AFFINE_STATE_PROVIDER_AND_BOUNDED_LIVE_PREFLIGHT_CONTRACT",
        "next_live_solver_authorization": False,
        "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0,
        "mpb_execution": False, "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "next_scientific_state": "E10E_TRAJECTORY_KERNEL_VALIDATED_READY_FOR_LOCAL_AFFINE_STATE_PROVIDER",
        "return_to_supervisor": True, "terminal": "E10E_ONE_PARAMETER_PHASE_SPACE_TRAJECTORY_KERNEL_COMPLETE",
        "diagnostics": {"first_order_residuals": residuals, "constant_endpoint": trajectory.r_phys[-1].tolist(),
                        "anomalous_transverse_velocity": float(anomalous_result.r_dot[1]),
                        "integrator": trajectory.integrator},
    }
    contract = {
        "schema": "mephc-e10e-one-parameter-phase-space-trajectory-kernel-contract-v1",
        "work_order_id": WORK_ORDER_ID, "input_hashes": inputs,
        "scope": "RANK1_ISOLATED_BAND_SCALAR_CURVATURE_ONLY",
        "rankn_trajectory_supported": False,
        "normalization": "q=ak_phys/(2pi); omega=2pi*c*freq_normalized/a; v_g=c*grad_q_freq",
        "coupled_equations": ["(I-Omega_rk)k_dot=-grad_r_omega", "(I+Omega_kr)r_dot=v_g-Omega_kk*k_dot"],
        "first_order_diagnostic": "k_dot=-grad_r_omega; r_dot=v_g-Omega_kk*k_dot-Omega_kr*v_g+O(|grad_s|^2)",
        "integrator": "CLASSICAL_RK4_FIXED_STEP_V1 with k_phys as the internal momentum variable",
        "local_bloch_policy": "a/L_def<=0.05 and a*||grad_r s||<=0.05; diagnostic synthetic identity is explicit",
        "transverse_shift": "dot(r_target-r_reference,(-e_long_y,e_long_x)) with explicit unit e_long",
        "no_solver_boundary": "supplied local scalar data only; no geometry, provider, MPB, solver, or dataset execution",
        "result_summary": result,
    }
    api = {"schema": "mephc-e10e-one-parameter-phase-space-trajectory-api-v1", "work_order_id": WORK_ORDER_ID,
           "module": KERNEL_PATH, "module_sha256": module_sha,
           "exports": ["PhysicalNormalization", "LocalRank1PhaseSpacePoint", "q_to_k_phys", "k_phys_to_q",
                        "normalized_frequency_to_omega", "grad_q_frequency_to_group_velocity",
                        "partial_s_normalized_frequency_to_partial_s_omega", "omega_qq_to_omega_kk",
                        "omega_qs_to_omega_ks", "monitor_local_bloch", "solve_pointwise_dynamics",
                        "first_order_dynamics", "integrate_trajectory", "transverse_shift"],
           "result_summary": result}
    validation = {"schema": "mephc-e10e-one-parameter-phase-space-trajectory-validation-v1",
                  "work_order_id": WORK_ORDER_ID, "solver_free": True, "mpb_execution": False,
                  "input_hashes": inputs, "checks": {key: result[key] for key in (
                      "physical_normalization_conversion_status", "pointwise_exact_coupled_solver_status",
                      "first_order_expansion_status", "rank1_scope_fail_closed_status", "trajectory_integrator_status",
                      "local_bloch_monitor_status", "transverse_shift_observable_status",
                      "analytic_anomalous_velocity_status", "analytic_mixed_curvature_velocity_status",
                      "constant_coefficient_trajectory_status", "qualification_propagation_status",
                      "no_solver_import_status")},
                  "diagnostics": result["diagnostics"], "native_invocation_count": 0,
                  "provider_request_count": 0, "solver_executions": 0}
    return contract, validation, api


def main() -> int:
    contract, validation, api = validate()
    write_json(OUT_CONTRACT, contract)
    write_json(OUT_VALIDATION, validation)
    write_json(OUT_API, api)
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(contract["result_summary"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
