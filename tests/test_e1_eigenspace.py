import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace, RawEigenstate
from mephc.toy_eigensolver import solve_hermitian


def state(vector, *, index=0, value=1.0, k_point=(0.0, 0.25), metadata=None):
    return RawEigenstate(
        k_point=k_point,
        solver_index=index,
        eigenvalue=value,
        vector=vector,
        metadata=metadata or {"source": "test", "nested": {"ok": True}},
    )


def test_raw_state_normalizes_and_serializes_json_safely():
    raw = state([1 + 1j, 2 - 1j], index=4, metadata={"label": "raw", "values": [1, 2.5]})
    assert raw.dimension == 2
    assert np.isclose(np.linalg.norm(raw.vector), 1.0)
    assert raw.solver_index == 4
    assert raw.vector.flags.writeable is False
    with pytest.raises(TypeError):
        raw.metadata["new"] = True
    summary = raw.to_dict()
    assert "vector" not in summary
    with_vector = raw.to_dict(include_vector=True)
    assert json.loads(json.dumps(with_vector, sort_keys=True))["vector"]


def test_raw_state_rejects_malformed_and_zero_vectors():
    with pytest.raises(ValueError):
        state([[1, 0]])
    with pytest.raises(ValueError):
        state([0, 0])
    with pytest.raises(ValueError):
        state(["1", "2"])
    with pytest.raises(ValueError):
        state([np.nan, 1])
    with pytest.raises(ValueError):
        state([1, 2], index=True)
    with pytest.raises(ValueError):
        state([1, 2], metadata={"bad": float("inf")})


def test_one_dimensional_subspace_projector_is_hermitian_idempotent():
    subspace = EigenSubspace.from_states([state([1, 0, 0])])
    projector = subspace.projector_matrix()
    assert subspace.ambient_dimension == 3
    assert subspace.dimension == 1
    assert np.allclose(projector, projector.conj().T, atol=1e-13)
    assert np.allclose(projector @ projector, projector, atol=1e-13)
    assert np.allclose(subspace.project([1, 0, 0]), [1, 0, 0])
    assert np.allclose(subspace.project([0, 1, 0]), [0, 0, 0])
    assert subspace.contains([1, 0, 0])
    assert not subspace.contains([0, 1, 0])


def test_gauge_phase_and_u2_basis_rotation_preserve_projector():
    vector = np.array([1 + 2j, -2 + 1j, 0.5 - 1j])
    first = EigenSubspace.from_states([state(vector)])
    phase = np.exp(0.73j)
    second = EigenSubspace.from_states([state(phase * vector, index=9)])
    assert first.projector_distance(second) < 1e-13

    basis = np.array([[1, 0], [0, 1], [0, 0]], dtype=complex)
    theta = 0.37
    unitary = np.array([
        [np.cos(theta), np.sin(theta)],
        [-np.sin(theta), np.cos(theta)],
    ], dtype=complex)
    left = EigenSubspace((0.0,), basis, (0.0, 0.0), (0, 1), {})
    right = EigenSubspace((0.0,), basis @ unitary, (0.0, 0.0), (7, 8), {})
    assert left.projector_distance(right) < 1e-13
    for candidate in ([0.2, 0.3, 1.0], [1j, -0.4, 0.2j]):
        assert np.allclose(left.project(candidate), right.project(candidate), atol=1e-13)


def test_solver_index_permutation_is_metadata_not_subspace_identity():
    matrix = np.diag([0.0, 0.0, 2.0]).astype(complex)
    ascending = solve_hermitian(matrix, k_point=(0.0, 0.0), solver_order="ascending")
    permuted = solve_hermitian(matrix, k_point=(0.0, 0.0), solver_order="permuted")
    assert [state.solver_index for state in ascending[:2]] != [state.solver_index for state in permuted[:2]]
    first = EigenSubspace.from_states(ascending[:2])
    second = EigenSubspace.from_states(permuted[:2])
    assert first.projector_distance(second) < 1e-13


def test_exact_degeneracy_rotation_has_same_rank_two_projector():
    matrix = np.diag([0.0, 0.0, 2.0]).astype(complex)
    states = solve_hermitian(matrix)
    rotation = np.array([[1, 1j], [1j, 1]], dtype=complex) / np.sqrt(2)
    rotated = states[0].vector[:, None] * rotation[0, :] + states[1].vector[:, None] * rotation[1, :]
    original = EigenSubspace.from_states(states[:2])
    transformed = EigenSubspace((0.0,), rotated, (0.0, 0.0), (100, 101), {})
    assert original.projector_distance(transformed) < 1e-13


def test_rank_deficient_subspace_fails_closed():
    with pytest.raises(ValueError, match="rank deficient"):
        EigenSubspace((0.0,), np.array([[1, 1], [0, 0], [0, 0]], dtype=complex), (0.0, 0.0), (0, 1), {})


def test_different_subspaces_have_nonzero_projector_distance():
    first = EigenSubspace.from_states([state([1, 0, 0])])
    second = EigenSubspace.from_states([state([0, 1, 0])])
    assert first.projector_distance(second) > 1.0
    assert not np.allclose(first.project([1, 0, 0]), second.project([1, 0, 0]))


def test_toy_solver_validates_hermitian_finite_input_and_orders_deterministically():
    matrix = np.array([[1, 1j], [-1j, 2]], dtype=complex)
    ascending = solve_hermitian(matrix)
    descending = solve_hermitian(matrix, solver_order="descending")
    assert tuple(state.eigenvalue for state in ascending) == tuple(sorted(state.eigenvalue for state in ascending))
    assert [state.solver_index for state in descending] == [1, 0]
    with pytest.raises(ValueError):
        solve_hermitian([[0, 1], [0, 0]])
    with pytest.raises(ValueError):
        solve_hermitian([[0, np.nan], [np.nan, 0]])
    with pytest.raises(ValueError):
        solve_hermitian(np.eye(2), solver_order="unknown")


def test_e1_does_not_expose_tracking_or_berry_surfaces():
    import mephc.eigenspace as eigenspace

    assert "meep" not in eigenspace.__dict__
    assert not hasattr(eigenspace, "track_bands")
    assert not hasattr(eigenspace, "parallel_transport")
    assert not hasattr(eigenspace, "wilson_loop")
    assert not hasattr(eigenspace, "physical_band_id")
