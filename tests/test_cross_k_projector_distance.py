import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.spectral_association import cross_k_projector_distance


def subspace(k, frame):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=(float(k),),
        frame=frame,
        eigenvalues=tuple(float(i) for i in range(frame.shape[1])),
        solver_indices=tuple(range(frame.shape[1])),
        metadata={"fixture": "cross-k-projector-distance"},
    )


def test_cross_k_distance_matches_dense_projector_difference():
    left = subspace(0.0, np.eye(5, 2))
    right = subspace(1.0, np.column_stack((np.array([1, 1, 0, 0, 0]) / np.sqrt(2), np.array([0, 0, 1, 0, 0]))))
    expected = np.linalg.norm(left.frame @ left.frame.conj().T - right.frame @ right.frame.conj().T, ord="fro")
    assert cross_k_projector_distance(left, right) == pytest.approx(expected)


def test_cross_k_distance_is_invariant_under_independent_u2_gauge_rotations():
    left = subspace(0.0, np.eye(4, 2))
    right = subspace(1.0, np.column_stack((np.array([1, 1, 0, 0]) / np.sqrt(2), np.array([0, 0, 1, 1]) / np.sqrt(2))))
    rng = np.random.default_rng(126)
    q_left, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
    q_right, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
    assert cross_k_projector_distance(left, right) == pytest.approx(
        cross_k_projector_distance(subspace(0.0, left.frame @ q_left), subspace(1.0, right.frame @ q_right))
    )


def test_cross_k_distance_allows_distinct_labels_and_detects_equal_or_different_spans():
    same_left = subspace(0.0, np.eye(3, 2))
    same_right = subspace(1.0, np.eye(3, 2))
    different = subspace(1.0, np.column_stack((np.array([1, 1, 0]) / np.sqrt(2), np.array([0, 0, 1]))))
    assert cross_k_projector_distance(same_left, same_right) == pytest.approx(0.0)
    assert cross_k_projector_distance(same_left, different) > 0.0


def test_cross_k_distance_fails_closed_for_ambient_or_rank_mismatch():
    with pytest.raises(ValueError, match="ambient dimensions"):
        cross_k_projector_distance(subspace(0.0, np.eye(3, 2)), subspace(1.0, np.eye(4, 2)))
    with pytest.raises(ValueError, match="equal ranks"):
        cross_k_projector_distance(subspace(0.0, np.eye(3, 1)), subspace(1.0, np.eye(3, 2)))