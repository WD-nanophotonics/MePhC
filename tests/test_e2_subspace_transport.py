import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.subspace_transport import (
    DEFAULT_VALIDATION_TOLERANCE,
    SubspaceOverlap,
    SubspaceTransportError,
    parallel_transport_link,
    subspace_overlap,
)


def subspace(frame, *, k_point=(0.0,), indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=k_point,
        frame=frame,
        eigenvalues=tuple(float(i) for i in range(frame.shape[1])),
        solver_indices=tuple(indices or range(frame.shape[1])),
        metadata={"fixture": "E2"},
    )


def rotation(theta):
    return np.array([[np.cos(theta), np.sin(theta)], [-np.sin(theta), np.cos(theta)]], dtype=complex)


def test_identical_rank_two_subspaces_have_zero_angles_and_aligned_frames():
    basis = np.eye(3, 2, dtype=complex)
    left = subspace(basis, k_point=(0.0,))
    right = subspace(basis @ rotation(0.41), k_point=(0.1,))
    overlap = subspace_overlap(left, right)
    assert overlap.is_equal_dimension
    assert np.allclose(overlap.singular_values, [1.0, 1.0], atol=1e-13)
    assert np.allclose(overlap.principal_angles, [0.0, 0.0], atol=1e-13)
    link = parallel_transport_link(left, right)
    assert link.min_singular_value > 1.0 - 1e-13
    assert np.allclose(link.aligned_right_frame(right), left.frame, atol=1e-13)
    wrong_ambient = subspace(np.eye(4, 2), k_point=right.k_point)
    with pytest.raises(ValueError):
        link.aligned_right_frame(wrong_ambient)


def test_gauge_covariance_for_overlap_and_polar_link():
    left_frame = np.array([[1, 0], [0, 1], [0, 0], [0, 0]], dtype=complex)
    right_frame = np.array([
        [np.cos(0.23), 0,],
        [0, np.cos(0.31)],
        [np.sin(0.23), 0],
        [0, np.sin(0.31)],
    ], dtype=complex)
    left = subspace(left_frame, k_point=(0.0,))
    right = subspace(right_frame, k_point=(0.2,))
    left_rotated = subspace(left_frame @ rotation(0.7), k_point=(0.0,))
    right_rotated = subspace(right_frame @ rotation(-0.4), k_point=(0.2,))
    original_overlap = subspace_overlap(left, right)
    rotated_overlap = subspace_overlap(left_rotated, right_rotated)
    g_left = left.frame.conj().T @ left_rotated.frame
    g_right = right.frame.conj().T @ right_rotated.frame
    expected_matrix = g_left.conj().T @ original_overlap.matrix @ g_right
    assert np.allclose(rotated_overlap.matrix, expected_matrix, atol=1e-13)
    original_link = parallel_transport_link(left, right)
    rotated_link = parallel_transport_link(left_rotated, right_rotated)
    expected_unitary = g_left.conj().T @ original_link.unitary @ g_right
    assert np.allclose(rotated_link.unitary, expected_unitary, atol=1e-13)
    assert np.allclose(rotated_overlap.singular_values, original_overlap.singular_values, atol=1e-13)
    assert np.allclose(rotated_overlap.principal_angles, original_overlap.principal_angles, atol=1e-13)


def test_n1_limit_is_normalized_complex_overlap():
    left = subspace([[1], [0]], k_point=(0.0,))
    right = subspace([[np.exp(0.37j) * 0.8], [0.6]], k_point=(0.1,))
    overlap = subspace_overlap(left, right)
    link = parallel_transport_link(left, right)
    expected = overlap.matrix[0, 0] / abs(overlap.matrix[0, 0])
    assert np.allclose(link.unitary[0, 0], expected, atol=1e-13)


def test_nearly_parallel_rank_one_principal_angle():
    theta = 0.003
    left = subspace([[1], [0]], k_point=(0.0,))
    right = subspace([[np.cos(theta)], [np.sin(theta)]], k_point=(theta,))
    overlap = subspace_overlap(left, right)
    assert np.isclose(overlap.singular_values[0], np.cos(theta), atol=1e-13)
    assert np.isclose(overlap.principal_angles[0], theta, atol=1e-13)


def test_orthogonal_overlap_is_valid_but_transport_fails():
    left = subspace([[1], [0]], k_point=(0.0,))
    right = subspace([[0], [1]], k_point=(1.0,))
    overlap = subspace_overlap(left, right)
    assert np.isclose(overlap.singular_values[0], 0.0, atol=1e-13)
    assert np.isclose(overlap.principal_angles[0], np.pi / 2, atol=1e-13)
    with pytest.raises(SubspaceTransportError):
        parallel_transport_link(left, right)


def test_minimum_singular_value_boundary_and_below_boundary():
    threshold = 0.25
    left = subspace([[1], [0]], k_point=(0.0,))
    right = subspace([[threshold], [np.sqrt(1 - threshold**2)]], k_point=(1.0,))
    observed = subspace_overlap(left, right).min_singular_value
    assert parallel_transport_link(left, right, min_singular_value=observed).dimension == 1
    with pytest.raises(SubspaceTransportError):
        parallel_transport_link(left, right, min_singular_value=observed + 1e-8)


def test_unequal_dimensions_plain_overlap_allowed_transport_rejected():
    left = subspace(np.eye(3, 1), k_point=(0.0,))
    right = subspace(np.eye(3, 2), k_point=(0.2,))
    overlap = subspace_overlap(left, right)
    assert overlap.matrix.shape == (1, 2)
    assert overlap.singular_values.size == 1
    with pytest.raises(SubspaceTransportError):
        parallel_transport_link(left, right)


def test_ambient_dimension_mismatch_rejected_but_different_k_points_allowed():
    left = subspace(np.eye(3, 1), k_point=(0.0,))
    right = subspace(np.eye(4, 1), k_point=(0.3,))
    with pytest.raises(ValueError):
        subspace_overlap(left, right)
    same_ambient_different_k = subspace([[1], [0], [0]], k_point=(0.3,))
    assert subspace_overlap(left, same_ambient_different_k).right_k_point == (0.3,)
    assert parallel_transport_link(left, same_ambient_different_k).dimension == 1


def test_singular_equal_dimensional_overlap_fails_closed_for_transport():
    left = subspace(np.eye(3, 2), k_point=(0.0,))
    right = subspace(np.array([[1, 0], [0, 0], [0, 1]], dtype=complex), k_point=(1.0,))
    overlap = subspace_overlap(left, right)
    assert np.isclose(overlap.min_singular_value, 0.0, atol=1e-13)
    with pytest.raises(SubspaceTransportError):
        parallel_transport_link(left, right)


def test_result_arrays_are_read_only_and_json_safe():
    left = subspace(np.eye(3, 2), k_point=(0.0,))
    right = subspace(np.eye(3, 2) @ rotation(0.2), k_point=(0.1,))
    overlap = subspace_overlap(left, right)
    link = parallel_transport_link(left, right)
    assert overlap.matrix.flags.writeable is False
    assert overlap.singular_values.flags.writeable is False
    assert overlap.principal_angles.flags.writeable is False
    assert link.overlap.flags.writeable is False
    assert link.unitary.flags.writeable is False
    encoded_overlap = json.dumps(overlap.to_dict(include_matrix=True), sort_keys=True)
    encoded_link = json.dumps(link.to_dict(include_matrices=True), sort_keys=True)
    assert json.loads(encoded_overlap)["matrix"]
    assert json.loads(encoded_link)["unitary"]


def test_nondefault_validation_tolerance_is_stored_and_used_consistently():
    matrix = np.array([[1]], dtype=complex)
    with pytest.raises(SubspaceTransportError):
        SubspaceOverlap(
            left_k_point=(0.0,), right_k_point=(0.1,),
            left_dimension=1, right_dimension=1, ambient_dimension=1,
            matrix=matrix, singular_values=np.array([1.0 + 2e-10]),
            principal_angles=np.array([0.0]),
            validation_tolerance=DEFAULT_VALIDATION_TOLERANCE,
        )
    overlap = SubspaceOverlap(
        left_k_point=(0.0,), right_k_point=(0.1,),
        left_dimension=1, right_dimension=1, ambient_dimension=1,
        matrix=matrix, singular_values=np.array([1.0 + 2e-10]),
        principal_angles=np.array([0.0]), validation_tolerance=1e-9,
    )
    assert overlap.validation_tolerance == 1e-9
    assert overlap.to_dict()["validation_tolerance"] == 1e-9


def test_transport_does_not_expose_branch_or_wilson_semantics():
    import mephc.subspace_transport as transport

    assert not hasattr(transport, "track_bands")
    assert not hasattr(transport, "wilson_loop")
    assert not hasattr(transport, "berry_curvature")
