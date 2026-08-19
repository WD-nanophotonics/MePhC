import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.spectral_association import (
    DISENTANGLEMENT_REQUIRED,
    NUMERICALLY_INCOMPLETE,
    SUBSPACE_CONTINUITY_UNQUALIFIED,
    SUBSPACE_NOT_ISOLATED,
    SUBSPACE_QUALIFIED,
    SUBSPACE_REQUIRES_ENLARGEMENT,
    ExternalIsolationContext,
    RankAdaptiveCandidate,
    SubspaceQualificationThresholds,
    qualify_local_subspace,
    qualify_rank_adaptive_subspace,
)


def make_sub(k, frame, eigenvalues, indices=None, source="E3C"):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=(float(k),),
        frame=frame,
        eigenvalues=tuple(eigenvalues),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": source},
    )


def thresholds(**overrides):
    values = {
        "min_singular_value": 0.9,
        "max_principal_angle": 0.5,
        "max_projector_distance": 0.8,
        "min_external_gap": 0.2,
    }
    values.update(overrides)
    return SubspaceQualificationThresholds(**values)


def isolated(gap=5.0):
    return ExternalIsolationContext((gap,), (gap,), {"source": "E3C"})


def test_avoided_crossing_coarse_overlap_fails_but_refined_adiabatic_steps_qualify():
    delta = 0.25

    def state(k):
        eigenvalues, vectors = np.linalg.eigh(np.array([[k, delta], [delta, -k]], dtype=float))
        return make_sub(k, vectors[:, :1], eigenvalues[:1], source="avoided-crossing")

    coarse_left, coarse_right = state(-1.0), state(1.0)
    coarse = qualify_local_subspace(
        coarse_left,
        coarse_right,
        thresholds=thresholds(min_singular_value=0.95, max_principal_angle=0.35),
        external_context=ExternalIsolationContext((float(np.linalg.eigvalsh([[1, delta], [delta, -1]])[1]),),
                                                   (float(np.linalg.eigvalsh([[1, delta], [delta, -1]])[1]),)),
    )
    assert coarse.status == SUBSPACE_CONTINUITY_UNQUALIFIED
    assert coarse.transport_link is None

    grid = np.linspace(-1.0, 1.0, 33)
    links = []
    for left_k, right_k in zip(grid[:-1], grid[1:]):
        left, right = state(left_k), state(right_k)
        left_excluded = float(np.linalg.eigvalsh([[left_k, delta], [delta, -left_k]])[1])
        right_excluded = float(np.linalg.eigvalsh([[right_k, delta], [delta, -right_k]])[1])
        links.append(qualify_local_subspace(
            left,
            right,
            thresholds=thresholds(min_singular_value=0.9, max_principal_angle=0.4),
            external_context=ExternalIsolationContext((left_excluded,), (right_excluded,)),
        ))
    assert all(item.is_qualified for item in links)
    assert all(item.transport_link is not None for item in links)
    assert "physical_band_id" not in links[0].to_dict()


def test_exact_crossing_rank_one_loses_external_isolation_and_rank_two_is_gauge_invariant():
    rank_one = make_sub(0, [[1], [0]], (0.0,), (7,))
    excluded_rank_one = ExternalIsolationContext((0.0,), (0.0,))
    failed = qualify_local_subspace(
        rank_one,
        make_sub(0, [[1], [0]], (0.0,), (9,)),
        thresholds=thresholds(),
        external_context=excluded_rank_one,
    )
    assert failed.status == SUBSPACE_NOT_ISOLATED
    assert failed.transport_link is None

    base = np.eye(2, dtype=complex)
    reference = qualify_local_subspace(
        make_sub(0, base, (0.0, 0.0), (7, 8)),
        make_sub(0, base, (0.0, 0.0), (9, 10)),
        thresholds=thresholds(),
        external_context=isolated(),
    )
    assert reference.status == SUBSPACE_QUALIFIED
    rng = np.random.default_rng(20260819)
    for _ in range(6):
        left_gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        right_gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        result = qualify_local_subspace(
            make_sub(0, base @ left_gauge, (0.0, 0.0), (11, 3)),
            make_sub(0, base @ right_gauge, (0.0, 0.0), (4, 12)),
            thresholds=thresholds(),
            external_context=isolated(),
        )
        assert result.status == reference.status
        assert np.allclose(result.overlap.singular_values, reference.overlap.singular_values)
        assert result.projector_distance == pytest.approx(reference.projector_distance)


def test_moving_rank_two_projector_matches_direct_diagnostics_under_local_u2_gauges():
    angle = 0.2
    left_frame = np.eye(4, 2, dtype=complex)
    right_frame = np.column_stack([
        np.array([1, 0, 0, 0], dtype=complex),
        np.array([0, np.cos(angle), np.sin(angle), 0], dtype=complex),
    ])
    result = qualify_local_subspace(
        make_sub(0, left_frame, (1.0, 1.0)),
        make_sub(1, right_frame, (1.0, 1.0)),
        thresholds=thresholds(min_singular_value=0.9, max_principal_angle=0.3, max_projector_distance=0.4),
        external_context=isolated(gap=3.0),
    )
    assert result.status == SUBSPACE_QUALIFIED
    assert np.allclose(result.overlap.singular_values, (1.0, np.cos(angle)))
    assert result.overlap.max_principal_angle == pytest.approx(angle)
    assert result.projector_distance == pytest.approx(np.sqrt(2.0) * np.sin(angle))

    rng = np.random.default_rng(314159)
    for _ in range(5):
        left_gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        right_gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        gauged = qualify_local_subspace(
            make_sub(0, left_frame @ left_gauge, (1.0, 1.0), (20, 4)),
            make_sub(1, right_frame @ right_gauge, (1.0, 1.0), (8, 17)),
            thresholds=thresholds(min_singular_value=0.9, max_principal_angle=0.3, max_projector_distance=0.4),
            external_context=isolated(gap=3.0),
        )
        assert gauged.status == result.status
        assert np.allclose(gauged.overlap.singular_values, result.overlap.singular_values)
        assert gauged.projector_distance == pytest.approx(result.projector_distance)


def test_solver_order_and_u1_phase_do_not_change_subspace_decision():
    left = make_sub(0, np.eye(3, 2), (1.0, 1.0), (1, 2))
    right = make_sub(1, np.eye(3, 2), (1.0, 1.0), (4, 5))
    permuted = make_sub(1, np.eye(3, 2) @ np.diag([np.exp(0.37j), np.exp(-0.81j)]), (1.0, 1.0), (5, 4))
    first = qualify_local_subspace(left, right, thresholds=thresholds(), external_context=isolated())
    second = qualify_local_subspace(left, permuted, thresholds=thresholds(), external_context=isolated())
    assert first.status == second.status == SUBSPACE_QUALIFIED
    assert np.allclose(first.overlap.singular_values, second.overlap.singular_values)
    assert first.projector_distance == pytest.approx(second.projector_distance)


def test_e3b_boundaries_remain_fail_closed_and_incomplete_family_is_not_disentanglement():
    def cand(rank, left, right, context=None):
        return RankAdaptiveCandidate(rank, left, right, context, {"rank": rank})

    low = cand(1, make_sub(0, [[1], [0], [0]], (0,)), make_sub(1, [[0], [1], [0]], (0,)), isolated())
    high = cand(2, make_sub(0, np.eye(3, 2), (0, 0)), make_sub(1, np.eye(3, 2), (0, 0)), isolated())
    enlarged = qualify_rank_adaptive_subspace([low, high], thresholds=thresholds(), candidate_family_complete=True)
    assert enlarged.status == SUBSPACE_REQUIRES_ENLARGEMENT
    assert enlarged.recommended_rank == 2

    first = cand(1, make_sub(0, [[1], [0], [0]], (0,)), make_sub(1, [[1], [0], [0]], (0,)), isolated())
    second = cand(1, make_sub(0, [[0], [1], [0]], (0,)), make_sub(1, [[0], [1], [0]], (0,)), isolated())
    ambiguous = qualify_rank_adaptive_subspace([[first, second]], thresholds=thresholds(), candidate_family_complete=True)
    assert ambiguous.status == DISENTANGLEMENT_REQUIRED
    assert ambiguous.transport_link is None

    incomplete = qualify_rank_adaptive_subspace([cand(1, first.left, first.right)], thresholds=thresholds(), candidate_family_complete=False)
    assert incomplete.status == NUMERICALLY_INCOMPLETE


def test_near_singular_overlap_has_no_transport_and_non_nested_ladder_rejects_both_endpoints():
    epsilon = 1e-8
    near = qualify_local_subspace(
        make_sub(0, [[1], [0]], (0,)),
        make_sub(1, [[epsilon], [np.sqrt(1 - epsilon**2)]], (0,)),
        thresholds=thresholds(min_singular_value=0.1, max_principal_angle=np.pi / 2, max_projector_distance=2.0),
        external_context=isolated(),
    )
    assert near.status == SUBSPACE_CONTINUITY_UNQUALIFIED
    assert near.transport_link is None

    low = RankAdaptiveCandidate(1, make_sub(0, [[1], [0], [0]], (0,)), make_sub(1, [[1], [0], [0]], (0,)), isolated())
    high = RankAdaptiveCandidate(2, make_sub(0, np.eye(3)[:, [1, 2]], (0, 0)), make_sub(1, np.eye(3)[:, [1, 2]], (0, 0)), isolated())
    with pytest.raises(ValueError, match="not nested"):
        qualify_rank_adaptive_subspace([low, high], thresholds=thresholds(), candidate_family_complete=False)


def test_e3_results_are_json_safe_read_only_and_do_not_authorize_global_objects():
    left = make_sub(0, np.eye(3, 2), (0, 0))
    right = make_sub(1, np.eye(3, 2), (0, 0))
    candidate = RankAdaptiveCandidate(2, left, right, isolated())
    result = qualify_rank_adaptive_subspace([candidate], thresholds=thresholds(), candidate_family_complete=False)
    json.loads(json.dumps(result.to_dict()))
    assert not result.attempts[0].results[0].overlap.singular_values.flags.writeable
    serialized = json.dumps(result.to_dict())
    for forbidden in ("physical_band_id", "branch_id", "adiabatic_band_id", "berry", "wilson", "plaquette"):
        assert forbidden not in serialized.lower()
