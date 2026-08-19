import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.path_domain import (
    PATH_AUTHORIZATION_SCOPE,
    PATH_INCOMPLETE,
    PATH_SINGLE_BAND_QUALIFIED,
    PATH_SUBSPACE_REQUIRED,
    PATH_SUBSPACE_QUALIFIED,
    PATH_UNQUALIFIED,
    qualify_ordered_path,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds


POINTS = ((0,), (1,), (2,), (3,))


def vertex(point, frame, values, indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=tuple(float(item) for item in point),
        frame=frame,
        eigenvalues=tuple(values),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": "E4D"},
    )


def thresholds(**overrides):
    values = {
        "min_singular_value": 0.9,
        "max_principal_angle": 0.5,
        "max_projector_distance": 0.8,
        "min_external_gap": 1.0,
    }
    values.update(overrides)
    return SubspaceQualificationThresholds(**values)


def contexts(count, gap=5.0):
    return [ExternalIsolationContext((gap,), (gap,), {"source": "E4D"}) for _ in range(count)]


def test_smooth_open_rank_one_path_uses_exactly_n_minus_one_edges():
    vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    result = qualify_ordered_path(vertices, contexts(3), thresholds=thresholds(), closed=False)
    assert result.status == PATH_SINGLE_BAND_QUALIFIED
    assert len(result.edge_results) == 3
    assert result.edges[-1].right_k_point == vertices[-1].k_point
    assert result.authorization_scope == PATH_AUTHORIZATION_SCOPE


def test_smooth_closed_path_adds_final_edge_to_original_first_vertex():
    vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    result = qualify_ordered_path(vertices, contexts(4), thresholds=thresholds(), closed=True)
    assert result.status == PATH_SINGLE_BAND_QUALIFIED
    assert len(result.edge_results) == 4
    assert result.edge_results[-1].right_k_point == vertices[0].k_point


def test_exact_degenerate_rank_two_path_is_u2_invariant():
    base = np.eye(4, 2, dtype=complex)
    rng = np.random.default_rng(20260819)
    for _ in range(5):
        vertices = []
        for index, point in enumerate(POINTS):
            gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
            vertices.append(vertex(point, base @ gauge, (0.0, 0.0), (index + 3, index + 9)))
        result = qualify_ordered_path(vertices, contexts(4), thresholds=thresholds(), closed=True)
        assert result.status == PATH_SUBSPACE_QUALIFIED


def test_solver_permutations_and_u1_phases_do_not_change_path_decision():
    vertices = [
        vertex(point, np.array([[np.exp(1j * phase)], [0]], dtype=complex), (0.0,), (20 - index,))
        for index, (point, phase) in enumerate(zip(POINTS, (0.2, -0.4, 0.7, -0.9)))
    ]
    result = qualify_ordered_path(vertices, contexts(3), thresholds=thresholds(), closed=False)
    assert result.status == PATH_SINGLE_BAND_QUALIFIED


def test_missing_context_is_incomplete():
    aligned = contexts(3)
    aligned[1] = None
    vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    result = qualify_ordered_path(vertices, aligned, thresholds=thresholds(), closed=False)
    assert result.status == PATH_INCOMPLETE
    assert result.edge_results[1].status == "NUMERICALLY_INCOMPLETE"


def test_rank_one_external_isolation_loss_returns_subspace_required():
    vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    result = qualify_ordered_path(vertices, contexts(3, gap=0.1), thresholds=thresholds(), closed=False)
    assert result.status == PATH_SUBSPACE_REQUIRED


def test_continuity_failure_preserves_failing_edge_and_path_unqualified():
    vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    vertices[2] = vertex(POINTS[2], [[0], [1]], (0.0,))
    result = qualify_ordered_path(vertices, contexts(3), thresholds=thresholds(), closed=False)
    assert result.status == PATH_UNQUALIFIED
    assert result.edge_results[1].transport_link is None


def test_invalid_counts_or_vertex_dimensions_fail_before_qualification():
    vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    with pytest.raises(ValueError, match="at least two"):
        qualify_ordered_path(vertices[:1], [], thresholds=thresholds(), closed=False)
    with pytest.raises(ValueError, match="context count"):
        qualify_ordered_path(vertices, contexts(2), thresholds=thresholds(), closed=False)
    mixed = list(vertices)
    mixed[2] = vertex(POINTS[2], np.eye(3, 2), (0.0, 0.0))
    with pytest.raises(ValueError, match="fixed rank"):
        qualify_ordered_path(mixed, contexts(3), thresholds=thresholds(), closed=False)


def test_path_result_is_json_safe_and_does_not_authorize_observables():
    vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    result = qualify_ordered_path(vertices, contexts(4), thresholds=thresholds(), closed=True)
    encoded = json.dumps(result.to_dict())
    assert json.loads(encoded)["authorization_scope"] == PATH_AUTHORIZATION_SCOPE
    for forbidden in ("physical_band_id", "branch_id", "adiabatic_band_id", "berry", "wilson", "chern", "curvature", "transport_product"):
        assert forbidden not in encoded.lower()
