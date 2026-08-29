"""Solver-neutral rank-1 phase-space dynamics for a supplied local band."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Mapping

import numpy as np


RANK1_TRAJECTORY_SCOPE = "SCALAR_CURVATURE_FORMALISM"
RANKN_TRAJECTORY_SUPPORTED = False
INTEGRATOR_IDENTITY = "CLASSICAL_RK4_FIXED_STEP_V1"
LOCAL_BLOCH_POLICY_IDENTITY = "E10A_PROSPECTIVE_GATES_A_OVER_L_AND_A_GRAD_S_LE_0P05"
RANK1_QUALIFIED = "RANK1_ISOLATED_QUALIFIED"
DIAGNOSTIC_SYNTHETIC = "DIAGNOSTIC_SYNTHETIC"
DEFAULT_CONDITION_LIMIT = 1.0e10
DEFAULT_TOLERANCE = 1.0e-10


class PhaseSpaceDynamicsError(ValueError):
    """Base class for fail-closed local dynamics errors."""


class NormalizationContractError(PhaseSpaceDynamicsError):
    pass


class RankScopeError(PhaseSpaceDynamicsError):
    pass


class LocalPhaseSpacePointError(PhaseSpaceDynamicsError):
    pass


class LocalBlochValidityError(PhaseSpaceDynamicsError):
    pass


class PhaseSpaceMatrixSingularError(PhaseSpaceDynamicsError):
    pass


class TrajectoryEvaluationError(PhaseSpaceDynamicsError):
    pass


class TrajectoryIntegrationError(PhaseSpaceDynamicsError):
    pass


class TransverseShiftDefinitionError(PhaseSpaceDynamicsError):
    pass


def _finite_vector(value: object, dimension: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (dimension,) or not np.all(np.isfinite(array)):
        raise LocalPhaseSpacePointError(f"{name}_MUST_BE_FINITE_{dimension}D_VECTOR")
    return array.copy()


def _finite_scalar(value: object, name: str) -> float:
    try:
        scalar = float(value)
    except (TypeError, ValueError) as exc:
        raise LocalPhaseSpacePointError(f"{name}_MUST_BE_FINITE_SCALAR") from exc
    if not math.isfinite(scalar):
        raise LocalPhaseSpacePointError(f"{name}_MUST_BE_FINITE_SCALAR")
    return scalar


def _readonly_copy(value: np.ndarray) -> np.ndarray:
    result = np.asarray(value, dtype=float).copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class PhysicalNormalization:
    reference_length_a: float
    wave_speed_c: float
    public_q_definition: str = "q=ak_phys/(2pi)"
    normalized_frequency_definition: str = "freq_normalized=omega*a/(2pi*c)"
    spatial_dimension: int = 2

    def __post_init__(self) -> None:
        a = _finite_scalar(self.reference_length_a, "reference_length_a")
        c = _finite_scalar(self.wave_speed_c, "wave_speed_c")
        if a <= 0.0 or c <= 0.0:
            raise NormalizationContractError("REFERENCE_LENGTH_AND_WAVE_SPEED_MUST_BE_POSITIVE")
        if self.spatial_dimension != 2:
            raise NormalizationContractError("SPATIAL_DIMENSION_MUST_BE_TWO")
        if not isinstance(self.public_q_definition, str) or not self.public_q_definition:
            raise NormalizationContractError("PUBLIC_Q_DEFINITION_REQUIRED")
        if not isinstance(self.normalized_frequency_definition, str) or not self.normalized_frequency_definition:
            raise NormalizationContractError("NORMALIZED_FREQUENCY_DEFINITION_REQUIRED")


def q_to_k_phys(q: object, normalization: PhysicalNormalization) -> np.ndarray:
    return _readonly_copy((2.0 * np.pi / normalization.reference_length_a)
                          * _finite_vector(q, 2, "q"))


def k_phys_to_q(k_phys: object, normalization: PhysicalNormalization) -> np.ndarray:
    return _readonly_copy((normalization.reference_length_a / (2.0 * np.pi))
                          * _finite_vector(k_phys, 2, "k_phys"))


def normalized_frequency_to_omega(freq_normalized: object, normalization: PhysicalNormalization) -> float:
    return (2.0 * np.pi * normalization.wave_speed_c / normalization.reference_length_a
            * _finite_scalar(freq_normalized, "normalized_frequency"))


def grad_q_frequency_to_group_velocity(grad_q_frequency: object,
                                       normalization: PhysicalNormalization) -> np.ndarray:
    return _readonly_copy(normalization.wave_speed_c * _finite_vector(grad_q_frequency, 2, "grad_q_frequency"))


def partial_s_normalized_frequency_to_partial_s_omega(partial_s_frequency: object,
                                                       normalization: PhysicalNormalization) -> float:
    return (2.0 * np.pi * normalization.wave_speed_c / normalization.reference_length_a
            * _finite_scalar(partial_s_frequency, "partial_s_normalized_frequency_fixed_q"))


def omega_qq_to_omega_kk(omega_qq: object, normalization: PhysicalNormalization) -> np.ndarray:
    matrix = np.asarray(omega_qq, dtype=float)
    if matrix.shape != (2, 2) or not np.all(np.isfinite(matrix)):
        raise NormalizationContractError("OMEGA_QQ_MUST_BE_FINITE_2_BY_2")
    return _readonly_copy((normalization.reference_length_a / (2.0 * np.pi)) ** 2 * matrix)


def omega_qs_to_omega_ks(omega_qs: object, normalization: PhysicalNormalization) -> np.ndarray:
    return _readonly_copy((normalization.reference_length_a / (2.0 * np.pi))
                          * _finite_vector(omega_qs, 2, "omega_qs"))


@dataclass(frozen=True)
class LocalRank1PhaseSpacePoint:
    r_phys: np.ndarray
    q: np.ndarray
    s: float
    grad_r_s: np.ndarray
    normalized_frequency: float
    grad_q_normalized_frequency: np.ndarray
    partial_s_normalized_frequency_fixed_q: float
    omega_qx_qy: float
    omega_qx_s: float
    omega_qy_s: float
    qualification_status: str
    local_bloch_metadata: Mapping[str, object]
    normalization: PhysicalNormalization

    def __post_init__(self) -> None:
        object.__setattr__(self, "r_phys", _readonly_copy(_finite_vector(self.r_phys, 2, "r_phys")))
        object.__setattr__(self, "q", _readonly_copy(_finite_vector(self.q, 2, "q")))
        object.__setattr__(self, "grad_r_s", _readonly_copy(_finite_vector(self.grad_r_s, 2, "grad_r_s")))
        for name in ("s", "normalized_frequency", "partial_s_normalized_frequency_fixed_q",
                     "omega_qx_qy", "omega_qx_s", "omega_qy_s"):
            object.__setattr__(self, name, _finite_scalar(getattr(self, name), name))
        if not isinstance(self.qualification_status, str) or not self.qualification_status:
            raise LocalPhaseSpacePointError("QUALIFICATION_STATUS_REQUIRED")
        if not isinstance(self.local_bloch_metadata, Mapping):
            raise LocalPhaseSpacePointError("LOCAL_BLOCH_METADATA_REQUIRED")
        object.__setattr__(self, "local_bloch_metadata", dict(self.local_bloch_metadata))


@dataclass(frozen=True)
class PhaseSpaceTensors:
    grad_r_omega: np.ndarray
    group_velocity: np.ndarray
    omega_kk: np.ndarray
    omega_ks: np.ndarray
    omega_kr: np.ndarray
    omega_rk: np.ndarray


@dataclass(frozen=True)
class PointwiseDynamicsResult:
    k_dot: np.ndarray
    r_dot: np.ndarray
    grad_r_omega: np.ndarray
    group_velocity: np.ndarray
    omega_kk: np.ndarray
    omega_ks: np.ndarray
    omega_kr: np.ndarray
    omega_rk: np.ndarray
    condition_number_k: float
    condition_number_r: float
    interpretation: str = RANK1_TRAJECTORY_SCOPE


@dataclass(frozen=True)
class FirstOrderDynamicsResult:
    k_dot_first_order: np.ndarray
    r_dot_group: np.ndarray
    r_dot_kk: np.ndarray
    r_dot_mixed: np.ndarray
    r_dot_first_order: np.ndarray


@dataclass(frozen=True)
class TrajectoryResult:
    times: np.ndarray
    r_phys: np.ndarray
    k_phys: np.ndarray
    q: np.ndarray
    integrator: str = INTEGRATOR_IDENTITY


def monitor_local_bloch(point: LocalRank1PhaseSpacePoint,
                        *, diagnostic_synthetic: bool = False) -> dict[str, float | str]:
    metadata = point.local_bloch_metadata
    identity = metadata.get("validity_identity")
    if diagnostic_synthetic and identity == DIAGNOSTIC_SYNTHETIC:
        return {"status": "PASS", "validity_identity": DIAGNOSTIC_SYNTHETIC}
    required = ("reference_length_a", "deformation_length_L_def", "abs_or_norm_grad_s")
    if any(key not in metadata for key in required):
        raise LocalBlochValidityError("LOCAL_BLOCH_POLICY_FIELDS_REQUIRED")
    a = _finite_scalar(metadata["reference_length_a"], "local_bloch_reference_length_a")
    length = _finite_scalar(metadata["deformation_length_L_def"], "deformation_length_L_def")
    grad_norm = _finite_scalar(metadata["abs_or_norm_grad_s"], "abs_or_norm_grad_s")
    if a <= 0.0 or length <= 0.0 or grad_norm < 0.0:
        raise LocalBlochValidityError("LOCAL_BLOCH_POLICY_VALUES_INVALID")
    if not math.isclose(a, point.normalization.reference_length_a, rel_tol=0.0, abs_tol=DEFAULT_TOLERANCE):
        raise LocalBlochValidityError("LOCAL_BLOCH_REFERENCE_LENGTH_MISMATCH")
    a_over_l = a / length
    a_grad = a * grad_norm
    if a_over_l > 0.05 or a_grad > 0.05:
        raise LocalBlochValidityError("LOCAL_BLOCH_POLICY_GATE_FAILED")
    return {"status": "PASS", "validity_identity": str(identity or "PRODUCTION_POLICY"),
            "a_over_L_def": a_over_l, "a_times_grad_s": a_grad}


def _require_rank1(point: LocalRank1PhaseSpacePoint) -> None:
    if point.qualification_status != RANK1_QUALIFIED:
        raise RankScopeError("RANK1_ISOLATED_QUALIFICATION_REQUIRED")
    rank = point.local_bloch_metadata.get("curvature_rank", 1)
    interpretation = point.local_bloch_metadata.get("curvature_interpretation", RANK1_TRAJECTORY_SCOPE)
    if rank != 1 or interpretation != RANK1_TRAJECTORY_SCOPE:
        raise RankScopeError("RANKN_TRACE_CURVATURE_CANNOT_DRIVE_RANK1_TRAJECTORY")


def phase_space_tensors(point: LocalRank1PhaseSpacePoint) -> PhaseSpaceTensors:
    _require_rank1(point)
    normalization = point.normalization
    grad_r_omega = (partial_s_normalized_frequency_to_partial_s_omega(
        point.partial_s_normalized_frequency_fixed_q, normalization) * point.grad_r_s)
    group_velocity = grad_q_frequency_to_group_velocity(point.grad_q_normalized_frequency, normalization)
    scale_qq = (normalization.reference_length_a / (2.0 * np.pi)) ** 2
    omega = scale_qq * point.omega_qx_qy
    omega_kk = np.array([[0.0, omega], [-omega, 0.0]], dtype=float)
    omega_ks = omega_qs_to_omega_ks([point.omega_qx_s, point.omega_qy_s], normalization)
    omega_kr = np.outer(omega_ks, point.grad_r_s)
    omega_rk = -omega_kr.T
    values = (grad_r_omega, group_velocity, omega_kk, omega_ks, omega_kr, omega_rk)
    if any(not np.all(np.isfinite(value)) for value in values):
        raise LocalPhaseSpacePointError("PHASE_SPACE_TENSORS_NONFINITE")
    if not np.allclose(omega_kk, -omega_kk.T, rtol=0.0, atol=DEFAULT_TOLERANCE):
        raise LocalPhaseSpacePointError("OMEGA_KK_ANTISYMMETRY_FAILED")
    return PhaseSpaceTensors(*(np.asarray(value, dtype=float) for value in values))


def _stable_solve(matrix: np.ndarray, rhs: np.ndarray, label: str,
                  condition_limit: float) -> tuple[np.ndarray, float]:
    if not math.isfinite(condition_limit) or condition_limit <= 1.0:
        raise PhaseSpaceMatrixSingularError("CONDITION_LIMIT_INVALID")
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(rhs)):
        raise PhaseSpaceMatrixSingularError(f"{label}_SYSTEM_NONFINITE")
    condition = float(np.linalg.cond(matrix))
    if not math.isfinite(condition) or condition > condition_limit:
        raise PhaseSpaceMatrixSingularError(f"{label}_SYSTEM_CONDITION_LIMIT_EXCEEDED")
    try:
        solution = np.linalg.solve(matrix, rhs)
    except np.linalg.LinAlgError as exc:
        raise PhaseSpaceMatrixSingularError(f"{label}_SYSTEM_SINGULAR") from exc
    if not np.all(np.isfinite(solution)):
        raise PhaseSpaceMatrixSingularError(f"{label}_SOLUTION_NONFINITE")
    return solution, condition


def solve_pointwise_dynamics(point: LocalRank1PhaseSpacePoint, *,
                             condition_limit: float = DEFAULT_CONDITION_LIMIT,
                             diagnostic_synthetic: bool = False) -> PointwiseDynamicsResult:
    _require_rank1(point)
    monitor_local_bloch(point, diagnostic_synthetic=diagnostic_synthetic)
    tensors = phase_space_tensors(point)
    identity = np.eye(2)
    k_dot, condition_k = _stable_solve(identity - tensors.omega_rk, -tensors.grad_r_omega,
                                        "K_DOT", condition_limit)
    r_dot, condition_r = _stable_solve(identity + tensors.omega_kr,
                                        tensors.group_velocity - tensors.omega_kk @ k_dot,
                                        "R_DOT", condition_limit)
    return PointwiseDynamicsResult(
        *(_readonly_copy(value) for value in (k_dot, r_dot, tensors.grad_r_omega,
                                               tensors.group_velocity, tensors.omega_kk,
                                               tensors.omega_ks, tensors.omega_kr, tensors.omega_rk)),
        condition_k, condition_r,
    )


def first_order_dynamics(point: LocalRank1PhaseSpacePoint) -> FirstOrderDynamicsResult:
    _require_rank1(point)
    monitor_local_bloch(point)
    tensors = phase_space_tensors(point)
    k_dot = -tensors.grad_r_omega
    r_dot_group = tensors.group_velocity
    r_dot_kk = -tensors.omega_kk @ k_dot
    r_dot_mixed = -tensors.omega_kr @ tensors.group_velocity
    return FirstOrderDynamicsResult(
        *(_readonly_copy(value) for value in (k_dot, r_dot_group, r_dot_kk,
                                               r_dot_mixed, r_dot_group + r_dot_kk + r_dot_mixed))
    )


def _stage(evaluator: Callable[[np.ndarray, np.ndarray, float], LocalRank1PhaseSpacePoint],
           r: np.ndarray, k: np.ndarray, time: float,
           normalization: PhysicalNormalization, diagnostic_synthetic: bool) -> tuple[np.ndarray, np.ndarray]:
    q = k_phys_to_q(k, normalization)
    try:
        point = evaluator(r.copy(), q.copy(), float(time))
    except Exception as exc:
        raise TrajectoryEvaluationError("LOCAL_EVALUATOR_FAILED") from exc
    if not isinstance(point, LocalRank1PhaseSpacePoint):
        raise TrajectoryEvaluationError("LOCAL_EVALUATOR_MUST_RETURN_LOCAL_RANK1_PHASE_SPACE_POINT")
    if not np.allclose(point.q, q, rtol=0.0, atol=DEFAULT_TOLERANCE):
        raise TrajectoryEvaluationError("LOCAL_EVALUATOR_Q_IDENTITY_MISMATCH")
    try:
        result = solve_pointwise_dynamics(point, diagnostic_synthetic=diagnostic_synthetic)
    except PhaseSpaceDynamicsError as exc:
        raise TrajectoryEvaluationError(str(exc)) from exc
    return result.r_dot, result.k_dot


def integrate_trajectory(initial_r_phys: object, initial_k_phys: object,
                         t0: float, t1: float, dt: float,
                         evaluator: Callable[[np.ndarray, np.ndarray, float], LocalRank1PhaseSpacePoint],
                         normalization: PhysicalNormalization, *,
                         diagnostic_synthetic: bool = False) -> TrajectoryResult:
    r0 = _finite_vector(initial_r_phys, 2, "initial_r_phys")
    k0 = _finite_vector(initial_k_phys, 2, "initial_k_phys")
    start = _finite_scalar(t0, "t0")
    stop = _finite_scalar(t1, "t1")
    step = _finite_scalar(dt, "dt")
    if step <= 0.0 or stop < start:
        raise TrajectoryIntegrationError("TRAJECTORY_TIME_INTERVAL_INVALID")
    count_float = (stop - start) / step
    count = int(round(count_float))
    if abs(count_float - count) > DEFAULT_TOLERANCE * max(1.0, abs(count_float)):
        raise TrajectoryIntegrationError("TRAJECTORY_INTERVAL_MUST_BE_INTEGER_NUMBER_OF_FIXED_STEPS")
    times = np.linspace(start, stop, count + 1, dtype=float)
    positions = np.empty((count + 1, 2), dtype=float)
    momenta = np.empty((count + 1, 2), dtype=float)
    positions[0] = r0
    momenta[0] = k0
    for index in range(count):
        time = float(times[index])
        r = positions[index].copy()
        k = momenta[index].copy()
        try:
            r1, k1 = _stage(evaluator, r, k, time, normalization, diagnostic_synthetic)
            r2, k2 = _stage(evaluator, r + 0.5 * step * r1, k + 0.5 * step * k1,
                             time + 0.5 * step, normalization, diagnostic_synthetic)
            r3, k3 = _stage(evaluator, r + 0.5 * step * r2, k + 0.5 * step * k2,
                             time + 0.5 * step, normalization, diagnostic_synthetic)
            r4, k4 = _stage(evaluator, r + step * r3, k + step * k3,
                             time + step, normalization, diagnostic_synthetic)
        except TrajectoryEvaluationError:
            raise
        except Exception as exc:
            raise TrajectoryIntegrationError("TRAJECTORY_STAGE_FAILED") from exc
        positions[index + 1] = r + step * (r1 + 2.0 * r2 + 2.0 * r3 + r4) / 6.0
        momenta[index + 1] = k + step * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        if not np.all(np.isfinite(positions[index + 1])) or not np.all(np.isfinite(momenta[index + 1])):
            raise TrajectoryIntegrationError("TRAJECTORY_STATE_NONFINITE")
    q = (normalization.reference_length_a / (2.0 * np.pi)) * momenta
    return TrajectoryResult(_readonly_copy(times), _readonly_copy(positions),
                            _readonly_copy(momenta), _readonly_copy(q))


def transverse_shift(target_endpoint: object, reference_endpoint: object,
                     longitudinal_unit: object, *, tolerance: float = DEFAULT_TOLERANCE) -> float:
    target = _finite_vector(target_endpoint, 2, "target_endpoint")
    reference = _finite_vector(reference_endpoint, 2, "reference_endpoint")
    direction = _finite_vector(longitudinal_unit, 2, "longitudinal_unit")
    norm = float(np.linalg.norm(direction))
    if abs(norm - 1.0) > tolerance:
        raise TransverseShiftDefinitionError("LONGITUDINAL_DIRECTION_MUST_BE_UNIT")
    n_perp = np.array([-direction[1], direction[0]])
    return float(np.dot(target - reference, n_perp))


solve_exact_pointwise_dynamics = solve_pointwise_dynamics
fixed_step_rk4_trajectory = integrate_trajectory
compute_transverse_shift = transverse_shift


__all__ = [
    "PhysicalNormalization", "LocalRank1PhaseSpacePoint", "PhaseSpaceTensors",
    "PointwiseDynamicsResult", "FirstOrderDynamicsResult", "TrajectoryResult",
    "q_to_k_phys", "k_phys_to_q", "normalized_frequency_to_omega",
    "grad_q_frequency_to_group_velocity", "partial_s_normalized_frequency_to_partial_s_omega",
    "omega_qq_to_omega_kk", "omega_qs_to_omega_ks", "monitor_local_bloch",
    "phase_space_tensors", "solve_pointwise_dynamics", "solve_exact_pointwise_dynamics",
    "first_order_dynamics", "integrate_trajectory", "fixed_step_rk4_trajectory",
    "transverse_shift", "compute_transverse_shift", "RANK1_TRAJECTORY_SCOPE",
    "RANKN_TRAJECTORY_SUPPORTED", "RANK1_QUALIFIED", "DIAGNOSTIC_SYNTHETIC",
    "NormalizationContractError", "RankScopeError", "LocalPhaseSpacePointError",
    "LocalBlochValidityError", "PhaseSpaceMatrixSingularError", "TrajectoryEvaluationError",
    "TrajectoryIntegrationError", "TransverseShiftDefinitionError",
]
