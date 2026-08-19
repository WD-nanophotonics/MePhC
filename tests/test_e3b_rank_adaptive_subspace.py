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
    qualify_rank_adaptive_subspace,
)


def sub(k, frame, values, indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=(float(k),),
        frame=frame,
        eigenvalues=tuple(values),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": "E3B"},
    )


def thresholds():
    return SubspaceQualificationThresholds(
        min_singular_value=0.9,
        max_principal_angle=0.5,
        max_projector_distance=0.8,
        min_external_gap=1.0,
    )


def context(gap=5.0):
    return ExternalIsolationContext((gap,), (gap,), {"source": "E3B-test"})


def candidate(rank, left, right, ctx=None, label="candidate"):
    return RankAdaptiveCandidate(rank, left, right, ctx, {"label": label})


def test_rank_one_failure_recovers_at_rank_two_and_preserves_attempts():
    low = candidate(1, sub(0, [[1], [0], [0]], (0,)), sub(1, [[0], [1], [0]], (0,)), context(), "rank1")
    high = candidate(2, sub(0, np.eye(3, 2), (0, 0)), sub(1, np.eye(3, 2), (0, 0)), context(), "rank2")
    result = qualify_rank_adaptive_subspace([low, high], thresholds=thresholds(), candidate_family_complete=True)
    assert result.status == SUBSPACE_REQUIRES_ENLARGEMENT
    assert result.initial_rank == 1
    assert result.attempted_ranks == (1, 2)
    assert result.recommended_rank == 2
    assert result.selected_result.status == SUBSPACE_QUALIFIED
    assert [item.candidate_provenance[0]["label"] for item in result.attempts] == ["rank1", "rank2"]


def test_rank_two_failure_recovers_at_smallest_rank_three():
    low = candidate(2, sub(0, np.eye(4, 2), (0, 0)), sub(1, np.eye(4)[:, [0, 2]], (0, 0)), context(), "rank2")
    high = candidate(3, sub(0, np.eye(4, 3), (0, 0, 0)), sub(1, np.eye(4)[:, [0, 1, 2]], (0, 0, 0)), context(), "rank3")
    result = qualify_rank_adaptive_subspace([low, high], thresholds=thresholds(), candidate_family_complete=True)
    assert result.status == SUBSPACE_REQUIRES_ENLARGEMENT
    assert result.recommended_rank == 3
    assert result.attempted_ranks == (2, 3)


def test_qualified_initial_rank_is_not_spuriously_enlarged():
    first = candidate(1, sub(0, [[1], [0]], (0,)), sub(1, [[1], [0]], (0,)), context())
    larger = candidate(2, sub(0, np.eye(2), (0, 0)), sub(1, np.eye(2), (0, 0)), context())
    result = qualify_rank_adaptive_subspace([first, larger], thresholds=thresholds(), candidate_family_complete=True)
    assert result.status == SUBSPACE_QUALIFIED
    assert result.attempted_ranks == (1,)
    assert result.recommended_rank == 1


def test_complete_family_with_external_entanglement_requires_disentanglement():
    only = candidate(1, sub(0, [[1], [0]], (0,)), sub(1, [[1], [0]], (0,)), context(0.2))
    result = qualify_rank_adaptive_subspace([only], thresholds=thresholds(), candidate_family_complete=True)
    assert result.status == DISENTANGLEMENT_REQUIRED
    assert result.transport_link is None


def test_incomplete_external_evidence_remains_numeric_incomplete():
    only = candidate(1, sub(0, [[1], [0]], (0,)), sub(1, [[1], [0]], (0,)))
    result = qualify_rank_adaptive_subspace([only], thresholds=thresholds(), candidate_family_complete=True)
    assert result.status == NUMERICALLY_INCOMPLETE
    assert result.transport_link is None


def test_same_rank_qualified_alternatives_are_not_arbitrarily_selected():
    first = candidate(1, sub(0, [[1], [0], [0]], (0,)), sub(1, [[1], [0], [0]], (0,)), context(), "a")
    second = candidate(1, sub(0, [[0], [1], [0]], (0,)), sub(1, [[0], [1], [0]], (0,)), context(), "b")
    result = qualify_rank_adaptive_subspace([[first, second]], thresholds=thresholds(), candidate_family_complete=True)
    assert result.status == DISENTANGLEMENT_REQUIRED
    assert result.recommended_rank is None
    assert result.selected_result is None
    assert result.attempts[0].selected_index is None


def test_non_nested_ladder_is_rejected_before_evaluation():
    low = candidate(1, sub(0, [[1], [0], [0]], (0,)), sub(1, [[1], [0], [0]], (0,)), context())
    high = candidate(2, sub(0, np.eye(3)[:, [1, 2]], (0, 0)), sub(1, np.eye(3)[:, [0, 1]], (0, 0)), context())
    with pytest.raises(ValueError, match="not nested"):
        qualify_rank_adaptive_subspace([low, high], thresholds=thresholds(), candidate_family_complete=False)


def test_exact_local_rotations_do_not_change_rank_decision_and_result_is_json_safe():
    base = np.eye(4, 2, dtype=complex)
    rng = np.random.default_rng(17)
    left_rotation, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
    right_rotation, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
    first = candidate(2, sub(0, base, (0, 0)), sub(1, base, (0, 0)), context())
    rotated = candidate(2, sub(0, base @ left_rotation, (0, 0)), sub(1, base @ right_rotation, (0, 0)), context())
    reference = qualify_rank_adaptive_subspace([first], thresholds=thresholds(), candidate_family_complete=False)
    transformed = qualify_rank_adaptive_subspace([rotated], thresholds=thresholds(), candidate_family_complete=False)
    assert transformed.status == reference.status == SUBSPACE_QUALIFIED
    assert np.allclose(
        transformed.attempts[0].results[0].overlap.singular_values,
        reference.attempts[0].results[0].overlap.singular_values,
    )
    assert json.loads(json.dumps(transformed.to_dict()))
    assert not transformed.attempts[0].results[0].overlap.singular_values.flags.writeable
