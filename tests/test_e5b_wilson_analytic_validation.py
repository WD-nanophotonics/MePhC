import json

import numpy as np
from scipy.linalg import expm

from mephc.eigenspace import EigenSubspace
from mephc.path_domain import PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport


I2 = np.eye(2, dtype=complex)
SIGMA_X = np.array([[0, 1], [1, 0]], dtype=complex)
SIGMA_Z = np.array([[1, 0], [0, -1]], dtype=complex)
X = 1j * 0.8 * SIGMA_X
Y = 1j * 0.6 * SIGMA_Z
POINTS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def thresholds():
    return SubspaceQualificationThresholds(
        min_singular_value=0.9,
        max_principal_angle=0.45,
        max_projector_distance=0.85,
        min_external_gap=1.0,
    )


def context():
    return ExternalIsolationContext((5.0, 5.0), (5.0, 5.0), {"source": "E5B analytic benchmark"})


def frame(u):
    return np.vstack((I2, u)) / np.sqrt(2.0)


def vertex(point, u, index_offset=0):
    return vertex_from_frame(point, frame(u), index_offset=index_offset)


def vertex_from_frame(point, q, index_offset=0):
    return EigenSubspace(
        k_point=point,
        frame=q,
        eigenvalues=(0.0, 0.0),
        solver_indices=(index_offset, index_offset + 1),
        metadata={"fixture": "E5B analytic benchmark"},
    )


def rectangle(generators=(X, Y), index_offset=0):
    first, second = generators
    unitaries = (
        I2,
        expm(first),
        expm(first) @ expm(second),
        expm(second),
    )
    return [vertex(point, unitary, index_offset=index_offset + 2 * i) for i, (point, unitary) in enumerate(zip(POINTS, unitaries))]


def closed_result(vertices):
    return compose_wilson_transport(
        qualify_ordered_path(vertices, [context()] * 4, thresholds=thresholds(), closed=True)
    )


def analytic_links(generators=(X, Y)):
    first, second = generators
    return (
        expm(0.5 * first),
        expm(0.5 * second),
        expm(-0.5 * (expm(-second) @ first @ expm(second))),
        expm(-0.5 * second),
    )


def analytic_reference(generators=(X, Y)):
    result = np.eye(2, dtype=complex)
    for link in analytic_links(generators):
        result = result @ link
    return result


def test_exact_rank_two_edges_qualify_and_match_analytic_wilson_matrix():
    vertices = rectangle()
    path = qualify_ordered_path(vertices, [context()] * 4, thresholds=thresholds(), closed=True)
    assert path.status == PATH_SUBSPACE_QUALIFIED
    assert all(edge.is_qualified and edge.transport_link is not None for edge in path.edge_results)
    result = compose_wilson_transport(path)
    reference = analytic_reference()
    assert result.status == WILSON_LOOP_QUALIFIED
    assert np.allclose(result.product, reference, atol=1e-10)
    assert not np.allclose(reference, np.eye(2), atol=1e-10)


def test_closed_invariants_match_independent_analytic_reference():
    result = closed_result(rectangle())
    reference = analytic_reference()
    eigenvalues = np.linalg.eigvals(reference)
    determinant = np.linalg.det(reference)
    assert np.allclose(np.sort(np.angle(result.eigenvalues)), np.sort(np.angle(eigenvalues)), atol=1e-10)
    assert np.allclose(np.sort(result.eigenphases), np.sort(np.angle(eigenvalues)), atol=1e-10)
    assert np.allclose(result.trace, np.trace(reference), atol=1e-10)
    assert np.allclose(result.determinant, determinant, atol=1e-10)
    assert np.allclose(result.determinant_phase, np.angle(determinant), atol=1e-10)


def test_seeded_local_u2_rotations_preserve_invariants_and_conjugate_at_base():
    rng = np.random.default_rng(20260819)
    local = [np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))[0] for _ in POINTS]
    base = rectangle()
    rotated = [
        vertex_from_frame(point, frame(unitary) @ local[i], index_offset=2 * i)
        for i, (point, unitary) in enumerate(zip(POINTS, (I2, expm(X), expm(X) @ expm(Y), expm(Y))))
    ]
    original = closed_result(base)
    changed = closed_result(rotated)
    base_gauge = frame(I2).conj().T @ rotated[0].frame
    assert np.allclose(changed.product, base_gauge.conj().T @ original.product @ base_gauge, atol=1e-10)
    assert np.allclose(np.sort_complex(changed.eigenvalues), np.sort_complex(original.eigenvalues), atol=1e-10)
    assert np.allclose(changed.trace, original.trace, atol=1e-10)
    assert np.allclose(changed.determinant, original.determinant, atol=1e-10)
    assert np.allclose(changed.determinant_phase, original.determinant_phase, atol=1e-10)


def test_solver_index_permutations_do_not_change_result():
    vertices = rectangle()
    permuted = [
        EigenSubspace(
            k_point=item.k_point,
            frame=item.frame,
            eigenvalues=item.eigenvalues,
            solver_indices=tuple(reversed(item.solver_indices)),
            metadata=item.metadata,
        )
        for item in vertices
    ]
    original = closed_result(vertices)
    changed = closed_result(permuted)
    assert np.allclose(changed.product, original.product, atol=1e-10)
    assert np.allclose(np.sort_complex(changed.eigenvalues), np.sort_complex(original.eigenvalues), atol=1e-10)


def test_cyclic_shift_and_reversal_have_expected_closed_loop_relations():
    vertices = rectangle()
    original = closed_result(vertices)
    shifted = closed_result(vertices[1:] + vertices[:1])
    reversed_path = closed_result([vertices[0], vertices[3], vertices[2], vertices[1]])
    assert np.allclose(np.sort_complex(shifted.eigenvalues), np.sort_complex(original.eigenvalues), atol=1e-10)
    assert np.allclose(shifted.trace, original.trace, atol=1e-10)
    assert np.allclose(shifted.determinant, original.determinant, atol=1e-10)
    assert np.allclose(reversed_path.product, original.product.conj().T, atol=1e-10)


def test_swapped_generators_match_reference_and_are_noncommuting():
    xy = closed_result(rectangle((X, Y)))
    yx = closed_result(rectangle((Y, X)))
    reference_xy = analytic_reference((X, Y))
    reference_yx = analytic_reference((Y, X))
    assert np.allclose(xy.product, reference_xy, atol=1e-10)
    assert np.allclose(yx.product, reference_yx, atol=1e-10)
    assert np.linalg.norm(reference_xy @ reference_yx - reference_yx @ reference_xy) > 1e-6


def test_commuting_generator_control_has_trivial_rectangle_holonomy():
    y_commuting = 1j * 0.6 * SIGMA_X
    result = closed_result(rectangle((X, y_commuting)))
    assert np.allclose(result.product, np.eye(2), atol=1e-10)
    assert np.allclose(analytic_reference((X, y_commuting)), np.eye(2), atol=1e-10)


def test_result_is_readonly_json_safe_and_scope_limited():
    result = closed_result(rectangle())
    try:
        result.product[0, 0] = 4.0
    except ValueError:
        pass
    else:
        raise AssertionError("Wilson product must be read-only")
    encoded = json.dumps(result.to_dict())
    assert json.loads(encoded)["authorization_scope"] == "wilson_transport_only"
    assert "berry" not in encoded.lower()
    assert "chern" not in encoded.lower()
    assert "matrix_log" not in encoded.lower()
