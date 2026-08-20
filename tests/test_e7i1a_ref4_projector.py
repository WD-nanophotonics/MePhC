import numpy as np

from mephc.eigenspace import EigenSubspace


def frame(k, n=40):
    rng = np.random.default_rng(1000 + k)
    q, _ = np.linalg.qr(rng.normal(size=(n, k)) + 1j * rng.normal(size=(n, k)))
    return q[:, :k]


def subspace(matrix):
    k = matrix.shape[1]
    return EigenSubspace((0.0, 0.0), matrix, tuple(range(k)), tuple(range(k)), {"test": "REF4"})


def test_low_rank_projector_distance_matches_dense_for_ranks_and_gauges():
    for rank in (1, 2, 3, 4):
        left = frame(rank)
        right = np.roll(frame(rank), 1, axis=0)
        phase = np.exp(1j * np.linspace(0.1, 0.9, rank))
        right = right @ np.diag(phase)
        lhs = subspace(left)
        rhs = subspace(right)
        dense = float(np.linalg.norm(lhs.projector_matrix() - rhs.projector_matrix(), ord="fro"))
        assert abs(lhs.projector_distance(rhs) - dense) <= 1e-12


def test_low_rank_projector_distance_handles_identical_and_orthogonal_frames():
    identical = subspace(frame(3))
    assert identical.projector_distance(identical) <= 1e-14
    left = np.eye(6, dtype=complex)[:, :3]
    right = np.eye(6, dtype=complex)[:, 3:]
    assert subspace(left).projector_distance(subspace(right)) == np.sqrt(6.0)


def test_projector_distance_does_not_materialize_ambient_square():
    left = frame(2, n=20000)
    right = frame(2, n=20000)
    value = subspace(left).projector_distance(subspace(right))
    assert np.isfinite(value)
