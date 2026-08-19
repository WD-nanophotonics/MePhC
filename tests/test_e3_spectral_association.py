import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace, RawEigenstate
from mephc.spectral_association import (
    AMBIGUOUS,
    CLEAR,
    INCOMPLETE,
    NUMERICALLY_INCOMPLETE,
    SINGLE_BAND_QUALIFIED,
    SUBSPACE_CONTINUITY_UNQUALIFIED,
    SUBSPACE_NOT_ISOLATED,
    SUBSPACE_QUALIFIED,
    ExternalIsolationContext,
    RawAssociationThresholds,
    SubspaceQualificationThresholds,
    associate_raw_states,
    qualify_local_subspace,
)


def raw(k_point, solver_index, vector, eigenvalue=0.0):
    return RawEigenstate(
        k_point=(float(k_point),),
        solver_index=solver_index,
        eigenvalue=eigenvalue,
        vector=np.asarray(vector, dtype=complex),
        metadata={"fixture": "E3A"},
    )


def subspace(k_point, frame, eigenvalues, indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=(float(k_point),),
        frame=frame,
        eigenvalues=tuple(eigenvalues),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": "E3A"},
    )


def raw_thresholds():
    return RawAssociationThresholds(
        probability_threshold=0.8,
        margin_threshold=0.2,
        assignment_margin_threshold=0.2,
    )


def local_thresholds():
    return SubspaceQualificationThresholds(
        min_singular_value=0.9,
        max_principal_angle=0.5,
        max_projector_distance=0.8,
        min_external_gap=1.0,
    )


def external(left=(5.0,), right=(5.0,)):
    return ExternalIsolationContext(
        left_excluded_eigenvalues=left,
        right_excluded_eigenvalues=right,
        provenance={"source": "test", "threshold_set": "E3A"},
    )


def test_clear_and_ambiguous_two_by_two_association_preserve_competing_evidence():
    left = [raw(0, 10, [1, 0]), raw(0, 11, [0, 1])]
    clear = associate_raw_states(
        left,
        [raw(1, 20, [1, 0]), raw(1, 21, [0, 1])],
        thresholds=raw_thresholds(),
    )
    assert clear.status == CLEAR
    assert clear.matched_by_solver_index == ((10, 20), (11, 21))
    assert clear.probability_matrix.shape == (2, 2)
    assert clear.second_best_assignment_score is not None

    theta = np.pi / 4
    rotated = np.array([[np.cos(theta), np.sin(theta)], [-np.sin(theta), np.cos(theta)]])
    ambiguous = associate_raw_states(
        left,
        [raw(1, 20, rotated[:, 0]), raw(1, 21, rotated[:, 1])],
        thresholds=RawAssociationThresholds(0.4, 0.1, 0.1),
    )
    assert ambiguous.status == AMBIGUOUS
    assert np.allclose(ambiguous.probability_matrix, 0.5)
    assert ambiguous.second_best_assignment_score is not None
    assert ambiguous.global_assignment_margin == pytest.approx(0.0)


def test_raw_diagnostics_are_invariant_to_tuple_order_and_independent_phases():
    left = [raw(0, 10, [1, 0]), raw(0, 11, [0, 1])]
    right = [raw(1, 20, [1, 1j]), raw(1, 21, [1j, 1])]
    baseline = associate_raw_states(left, right, thresholds=raw_thresholds())
    phase_left = [raw(0, 11, np.exp(0.31j) * np.array([0, 1])), raw(0, 10, np.exp(-0.47j) * np.array([1, 0]))]
    phase_right = [raw(1, 21, np.exp(0.19j) * np.array([1j, 1])), raw(1, 20, np.exp(-0.11j) * np.array([1, 1j]))]
    permuted = associate_raw_states(phase_left, phase_right, thresholds=raw_thresholds())
    assert sorted(baseline.matched_by_solver_index) == sorted(permuted.matched_by_solver_index)
    assert np.allclose(
        sorted(baseline.matched_probabilities),
        sorted(permuted.matched_probabilities),
    )
    assert np.allclose(sorted(baseline.row_margins), sorted(permuted.row_margins))
    assert np.allclose(sorted(baseline.column_margins), sorted(permuted.column_margins))


def test_nonorthogonal_raw_frame_is_rejected_before_any_qr_normalization():
    with pytest.raises(ValueError, match="Gram orthonormal"):
        associate_raw_states(
            [raw(0, 1, [1, 0]), raw(0, 2, [1, 1])],
            [raw(1, 3, [1, 0]), raw(1, 4, [0, 1])],
            thresholds=raw_thresholds(),
        )


def test_exact_degenerate_rank_two_qualification_is_invariant_under_local_u2_rotations():
    base = np.eye(4, 2, dtype=complex)
    reference = qualify_local_subspace(
        subspace(0, base, (0.0, 0.0)),
        subspace(1, base, (0.0, 0.0), indices=(4, 5)),
        thresholds=local_thresholds(),
        external_context=external(),
    )
    assert reference.status == SUBSPACE_QUALIFIED
    rng = np.random.default_rng(90210)
    for _ in range(5):
        left_rotation, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        right_rotation, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        result = qualify_local_subspace(
            subspace(0, base @ left_rotation, (0.0, 0.0)),
            subspace(1, base @ right_rotation, (0.0, 0.0), indices=(4, 5)),
            thresholds=local_thresholds(),
            external_context=external(),
        )
        assert result.status == reference.status
        assert np.allclose(result.overlap.singular_values, reference.overlap.singular_values)
        assert np.allclose(result.overlap.principal_angles, reference.overlap.principal_angles, atol=1e-7)
        assert result.projector_distance == pytest.approx(reference.projector_distance)
        assert result.external_gap == pytest.approx(reference.external_gap)


def test_zero_internal_gap_with_large_external_gap_is_qualified():
    result = qualify_local_subspace(
        subspace(0, np.eye(3, 2), (2.0, 2.0)),
        subspace(1, np.eye(3, 2), (2.0, 2.0)),
        thresholds=local_thresholds(),
        external_context=external(left=(9.0,), right=(9.0,)),
    )
    assert result.status == SUBSPACE_QUALIFIED
    assert result.transport_link is not None


def test_external_gap_below_threshold_returns_not_isolated():
    result = qualify_local_subspace(
        subspace(0, np.eye(3, 2), (0.0, 0.0)),
        subspace(1, np.eye(3, 2), (0.0, 0.0)),
        thresholds=local_thresholds(),
        external_context=external(left=(0.25,), right=(0.25,)),
    )
    assert result.status == SUBSPACE_NOT_ISOLATED
    assert result.transport_link is None


def test_near_singular_overlap_fails_closed_without_transport_link():
    result = qualify_local_subspace(
        subspace(0, [[1], [0]], (0.0,)),
        subspace(1, [[0], [1]], (0.0,)),
        thresholds=SubspaceQualificationThresholds(0.1, np.pi / 2, 2.0, 1.0),
        external_context=external(),
    )
    assert result.status == SUBSPACE_CONTINUITY_UNQUALIFIED
    assert result.transport_link is None


def test_well_isolated_rank_one_pair_reaches_single_band_qualified():
    theta = 0.05
    result = qualify_local_subspace(
        subspace(0, [[1], [0]], (0.0,)),
        subspace(1, [[np.cos(theta)], [np.sin(theta)]], (0.0,)),
        thresholds=SubspaceQualificationThresholds(0.9, 0.1, 0.1, 1.0),
        external_context=external(),
    )
    assert result.status == SINGLE_BAND_QUALIFIED
    assert result.is_qualified
    assert result.transport_link is not None


def test_rectangular_raw_candidate_window_remains_incomplete():
    result = associate_raw_states(
        [raw(0, 1, [1, 0]), raw(0, 2, [0, 1])],
        [raw(1, 3, [1, 0])],
        thresholds=RawAssociationThresholds(0.5, 0.0, 0.0),
    )
    assert result.status == INCOMPLETE
    assert len(result.assignment) == 1


def test_missing_external_context_is_numerically_incomplete():
    result = qualify_local_subspace(
        subspace(0, np.eye(3, 2), (0.0, 0.0)),
        subspace(1, np.eye(3, 2), (0.0, 0.0)),
        thresholds=local_thresholds(),
    )
    assert result.status == NUMERICALLY_INCOMPLETE
    assert result.transport_link is None


def test_result_arrays_are_read_only_and_serialization_is_json_safe():
    raw_result = associate_raw_states(
        [raw(0, 1, [1, 0]), raw(0, 2, [0, 1])],
        [raw(1, 3, [1, 0]), raw(1, 4, [0, 1])],
        thresholds=raw_thresholds(),
    )
    local_result = qualify_local_subspace(
        subspace(0, np.eye(3, 2), (0.0, 0.0)),
        subspace(1, np.eye(3, 2), (0.0, 0.0)),
        thresholds=local_thresholds(),
        external_context=external(),
    )
    assert not raw_result.overlap_matrix.flags.writeable
    assert not raw_result.probability_matrix.flags.writeable
    assert not local_result.overlap.singular_values.flags.writeable
    assert json.loads(json.dumps(raw_result.to_dict()))
    assert json.loads(json.dumps(local_result.to_dict()))
