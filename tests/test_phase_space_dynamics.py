from __future__ import annotations

import numpy as np
import pytest

from mephc.phase_space_dynamics import (
    DIAGNOSTIC_SYNTHETIC,
    LocalBlochValidityError,
    LocalRank1PhaseSpacePoint,
    NormalizationContractError,
    PhysicalNormalization,
    RANK1_QUALIFIED,
    RankScopeError,
    TransverseShiftDefinitionError,
    first_order_dynamics,
    integrate_trajectory,
    k_phys_to_q,
    monitor_local_bloch,
    q_to_k_phys,
    solve_pointwise_dynamics,
    transverse_shift,
)


def point(normalization, *, qualification=RANK1_QUALIFIED, grad=(0.01, -0.005), berry=(0.2, -0.1),
          metadata=None):
    return LocalRank1PhaseSpacePoint(
        r_phys=[0.0, 0.0], q=[0.1, -0.1], s=0.0, grad_r_s=grad,
        normalized_frequency=0.8, grad_q_normalized_frequency=[0.3, 0.2],
        partial_s_normalized_frequency_fixed_q=0.4, omega_qx_qy=0.1,
        omega_qx_s=berry[0], omega_qy_s=berry[1], qualification_status=qualification,
        local_bloch_metadata=metadata or {
            "validity_identity": DIAGNOSTIC_SYNTHETIC,
            "reference_length_a": normalization.reference_length_a,
            "deformation_length_L_def": 100.0,
            "abs_or_norm_grad_s": float(np.linalg.norm(grad)),
            "curvature_rank": 1,
            "curvature_interpretation": "SCALAR_CURVATURE_FORMALISM",
        }, normalization=normalization,
    )


def test_normalization_and_exact_pointwise_equations():
    normalization = PhysicalNormalization(2.0, 3.0)
    q = np.array([0.2, -0.4])
    assert np.allclose(k_phys_to_q(q_to_k_phys(q, normalization), normalization), q)
    local = point(normalization)
    result = solve_pointwise_dynamics(local)
    first = first_order_dynamics(local)
    assert result.k_dot.shape == (2,)
    assert result.r_dot.shape == (2,)
    assert np.all(np.isfinite(result.r_dot))
    assert first.r_dot_first_order.shape == (2,)


def test_rank_scope_and_local_bloch_fail_closed():
    normalization = PhysicalNormalization(1.0, 1.0)
    with pytest.raises(RankScopeError):
        solve_pointwise_dynamics(point(normalization, qualification="RANK2_TRACE_ONLY"))
    bad = point(normalization, metadata={
        "validity_identity": "PRODUCTION_POLICY", "reference_length_a": 1.0,
        "deformation_length_L_def": 10.0, "abs_or_norm_grad_s": 0.01,
        "curvature_rank": 1, "curvature_interpretation": "SCALAR_CURVATURE_FORMALISM",
    })
    with pytest.raises(LocalBlochValidityError):
        monitor_local_bloch(bad)


def test_fixed_step_trajectory_and_explicit_transverse_projection():
    normalization = PhysicalNormalization(1.0, 1.0)

    def evaluator(r, q, time):
        return LocalRank1PhaseSpacePoint(
            r_phys=r, q=q, s=0.0, grad_r_s=[0.0, 0.0], normalized_frequency=0.8,
            grad_q_normalized_frequency=[0.2, 0.1], partial_s_normalized_frequency_fixed_q=0.0,
            omega_qx_qy=0.0, omega_qx_s=0.0, omega_qy_s=0.0,
            qualification_status=RANK1_QUALIFIED,
            local_bloch_metadata={"validity_identity": DIAGNOSTIC_SYNTHETIC,
                                  "reference_length_a": 1.0, "deformation_length_L_def": 100.0,
                                  "abs_or_norm_grad_s": 0.0, "curvature_rank": 1,
                                  "curvature_interpretation": "SCALAR_CURVATURE_FORMALISM"},
            normalization=normalization)

    trajectory = integrate_trajectory([0.0, 0.0], [0.0, 0.0], 0.0, 1.0, 0.25,
                                      evaluator, normalization)
    assert np.allclose(trajectory.r_phys[-1], [0.2, 0.1], atol=1e-13)
    assert trajectory.integrator == "CLASSICAL_RK4_FIXED_STEP_V1"
    assert np.isclose(transverse_shift([1.0, 0.25], [0.0, 0.0], [1.0, 0.0]), 0.25)
    with pytest.raises(TransverseShiftDefinitionError):
        transverse_shift([1.0, 0.0], [0.0, 0.0], [2.0, 0.0])


def test_normalization_rejects_non_two_dimensional_contract():
    with pytest.raises(NormalizationContractError):
        PhysicalNormalization(1.0, 1.0, spatial_dimension=3)
