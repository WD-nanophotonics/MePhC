import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.plaquette_domain import (
    PLAQUETTE_BOUNDARY_ONLY,
    PLAQUETTE_INTERIOR_INCOMPLETE,
    PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED,
    PLAQUETTE_SUBSPACE_REQUIRED,
    SAMPLED_INTERIOR_AUTHORIZATION_SCOPE,
    qualify_plaquette_boundary,
    qualify_plaquette_interior,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds


POINTS = ((0, 0), (1, 0), (1, 1), (0, 1))


def vertex(point, frame, values, indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=tuple(float(item) for item in point),
        frame=frame,
        eigenvalues=tuple(values),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": "E4B"},
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


def contexts(gap=5.0):
    return [ExternalIsolationContext((gap,), (gap,), {"source": "E4B"}) for _ in range(4)]


def boundary(frame, values=(0.0,), indices=None, edge_contexts=None):
    vertices = [vertex(point, frame, values, indices) for point in POINTS]
    return qualify_plaquette_boundary(vertices, edge_contexts or contexts(), thresholds=thresholds())


def test_smooth_rank_one_square_and_exact_center_qualify_sampled_interior():
    result = qualify_plaquette_interior(
        boundary([[1], [0]]),
        vertex((0.5, 0.5), [[1], [0]], (0.0,)),
        contexts(),
    )
    assert result.status == PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED
    assert result.is_qualified
    assert len(result.spoke_results) == 4
    assert result.authorization_scope == SAMPLED_INTERIOR_AUTHORIZATION_SCOPE


def test_exact_degenerate_rank_two_is_u2_invariant_at_corners_and_center():
    base = np.eye(4, 2, dtype=complex)
    rng = np.random.default_rng(20260819)
    for _ in range(5):
        corners = []
        for point in POINTS:
            gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
            corners.append(vertex(point, base @ gauge, (0.0, 0.0)))
        b = qualify_plaquette_boundary(corners, contexts(), thresholds=thresholds())
        center_gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        result = qualify_plaquette_interior(
            b,
            vertex((0.5, 0.5), base @ center_gauge, (0.0, 0.0)),
            contexts(),
        )
        assert result.status == PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED


def test_rank_one_center_external_gap_loss_requires_subspace():
    result = qualify_plaquette_interior(
        boundary([[1], [0]]),
        vertex((0.5, 0.5), [[1], [0]], (0.0,)),
        contexts(gap=0.1),
    )
    assert result.status == PLAQUETTE_SUBSPACE_REQUIRED


def test_continuity_failing_spoke_preserves_boundary_only_authorization():
    b = boundary([[1], [0]])
    result = qualify_plaquette_interior(
        b,
        vertex((0.5, 0.5), [[0], [1]], (0.0,)),
        contexts(),
    )
    assert result.status == PLAQUETTE_BOUNDARY_ONLY
    assert result.spoke_results[0].transport_link is None


def test_missing_spoke_evidence_is_incomplete():
    spoke_contexts = contexts()
    spoke_contexts[1] = None
    result = qualify_plaquette_interior(
        boundary([[1], [0]]),
        vertex((0.5, 0.5), [[1], [0]], (0.0,)),
        spoke_contexts,
    )
    assert result.status == PLAQUETTE_INTERIOR_INCOMPLETE


def test_incomplete_or_unqualified_boundary_is_never_upgraded():
    incomplete_contexts = contexts()
    incomplete_contexts[0] = None
    incomplete_boundary = boundary([[1], [0]], edge_contexts=incomplete_contexts)
    incomplete = qualify_plaquette_interior(
        incomplete_boundary,
        vertex((0.5, 0.5), [[1], [0]], (0.0,)),
        contexts(),
    )
    assert incomplete.status == PLAQUETTE_INTERIOR_INCOMPLETE

    unqualified_vertices = [vertex(point, [[1], [0]], (0.0,)) for point in POINTS]
    unqualified_vertices[2] = vertex(POINTS[2], [[0], [1]], (0.0,))
    unqualified_boundary = qualify_plaquette_boundary(unqualified_vertices, contexts(), thresholds=thresholds())
    unqualified = qualify_plaquette_interior(
        unqualified_boundary,
        vertex((0.5, 0.5), [[1], [0]], (0.0,)),
        contexts(),
    )
    assert unqualified.status == PLAQUETTE_BOUNDARY_ONLY


def test_wrong_center_geometry_rank_ambient_and_degenerate_polygon_fail_closed():
    b = boundary([[1], [0]])
    with pytest.raises(ValueError, match="arithmetic mean"):
        qualify_plaquette_interior(b, vertex((0.6, 0.5), [[1], [0]], (0.0,)), contexts())
    with pytest.raises(ValueError, match="rank"):
        qualify_plaquette_interior(b, vertex((0.5, 0.5), np.eye(2), (0.0, 0.0)), contexts())

    collinear = [vertex((i, 0), [[1], [0]], (0.0,)) for i in range(4)]
    collinear_boundary = qualify_plaquette_boundary(collinear, contexts(), thresholds=thresholds())
    with pytest.raises(ValueError, match="nondegenerate"):
        qualify_plaquette_interior(
            collinear_boundary,
            vertex((1.5, 0), [[1], [0]], (0.0,)),
            contexts(),
        )


def test_solver_permutations_phases_and_serialization_do_not_add_global_authorization():
    phased = [
        vertex(point, np.array([[np.exp(1j * phase)], [0]], dtype=complex), (0.0,), (index + 10,))
        for index, (point, phase) in enumerate(zip(POINTS, (0.2, -0.4, 0.7, -0.9)))
    ]
    b = qualify_plaquette_boundary(phased, contexts(), thresholds=thresholds())
    result = qualify_plaquette_interior(
        b,
        vertex((0.5, 0.5), [[np.exp(0.33j)], [0]], (0.0,), (99,)),
        contexts(),
    )
    encoded = json.dumps(result.to_dict())
    assert json.loads(encoded)["authorization_scope"] == SAMPLED_INTERIOR_AUTHORIZATION_SCOPE
    for forbidden in ("physical_band_id", "branch_id", "adiabatic_band_id", "berry", "wilson", "chern", "curvature"):
        assert forbidden not in encoded.lower()
    assert not result.spoke_results[0].overlap.singular_values.flags.writeable
