import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.plaquette_domain import (
    IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE,
    PLAQUETTE_BOUNDARY_ONLY,
    PLAQUETTE_INTERIOR_INCOMPLETE,
    PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED,
    PlaquetteRefinementLevel,
    PlaquetteRefinementThresholds,
    qualify_plaquette_boundary,
    qualify_plaquette_interior,
    qualify_plaquette_refinement,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds


CENTER = np.array([0.5, 0.5])


def vertex(point, frame, values, indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=tuple(float(item) for item in point),
        frame=frame,
        eigenvalues=tuple(values),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": "E4C"},
    )


def e3_thresholds(**overrides):
    values = {
        "min_singular_value": 0.9,
        "max_principal_angle": 0.5,
        "max_projector_distance": 0.8,
        "min_external_gap": 1.0,
    }
    values.update(overrides)
    return SubspaceQualificationThresholds(**values)


def contexts(gap=5.0):
    return [ExternalIsolationContext((gap,), (gap,), {"source": "E4C"}) for _ in range(4)]


def make_level(scale, frame, values=(0.0,), step=None, edge_contexts=None, spoke_contexts=None, center=None):
    center = CENTER if center is None else np.asarray(center, dtype=float)
    offsets = np.array([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]) * scale
    points = center + offsets
    vertices = [vertex(point, frame, values) for point in points]
    boundary = qualify_plaquette_boundary(
        vertices,
        edge_contexts or contexts(),
        thresholds=e3_thresholds(),
    )
    interior = qualify_plaquette_interior(
        boundary,
        vertex(center, frame, values),
        spoke_contexts or contexts(),
    )
    return PlaquetteRefinementLevel(
        boundary=boundary,
        interior=interior,
        step=scale if step is None else step,
        provenance={"scale": scale},
    )


def refinement_thresholds(**overrides):
    values = {
        "min_singular_value": 0.9,
        "max_principal_angle": 0.5,
        "max_projector_distance": 0.8,
        "max_metric_delta": 1e-8,
        "geometry_tolerance": 1e-8,
    }
    values.update(overrides)
    return PlaquetteRefinementThresholds(**values)


def test_three_decreasing_rank_one_levels_qualify_identity_refinement():
    levels = [make_level(scale, np.array([[1], [0]], dtype=complex)) for scale in (1.0, 0.5, 0.25)]
    result = qualify_plaquette_refinement(levels, thresholds=refinement_thresholds())
    assert result.status == "PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED"
    assert result.is_qualified
    assert result.authorization_scope == IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE
    assert len(result.metrics) == 3


def test_rank_two_gauge_rotations_at_every_level_remain_qualified():
    base = np.eye(4, 2, dtype=complex)
    rng = np.random.default_rng(20260819)
    levels = []
    for scale in (1.0, 0.5, 0.25):
        corners = []
        for point in CENTER + np.array([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]) * scale:
            gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
            corners.append(vertex(point, base @ gauge, (0.0, 0.0)))
        boundary = qualify_plaquette_boundary(corners, contexts(), thresholds=e3_thresholds())
        center_gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
        interior = qualify_plaquette_interior(
            boundary,
            vertex(CENTER, base @ center_gauge, (0.0, 0.0)),
            contexts(),
        )
        levels.append(PlaquetteRefinementLevel(boundary, interior, scale))
    result = qualify_plaquette_refinement(levels, thresholds=refinement_thresholds(max_metric_delta=1e-6))
    assert result.status == "PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED"


def test_rank_change_fails_closed_explicitly():
    levels = [
        make_level(1.0, np.array([[1], [0]], dtype=complex)),
        make_level(0.5, np.eye(3, 2, dtype=complex), values=(0.0, 0.0)),
    ]
    result = qualify_plaquette_refinement(levels, thresholds=refinement_thresholds())
    assert result.status == "PLAQUETTE_REFINEMENT_RANK_UNSTABLE"
    assert not result.authorization_granted


def test_incomplete_or_unqualified_level_propagates_without_upgrade():
    missing = contexts()
    missing[0] = None
    levels = [
        make_level(1.0, np.array([[1], [0]], dtype=complex)),
        make_level(0.5, np.array([[1], [0]], dtype=complex), edge_contexts=missing),
    ]
    incomplete = qualify_plaquette_refinement(levels, thresholds=refinement_thresholds())
    assert incomplete.status == "PLAQUETTE_REFINEMENT_INCOMPLETE"

    bad_spokes = contexts()
    levels = [
        make_level(1.0, np.array([[1], [0]], dtype=complex)),
        make_level(0.5, np.array([[1], [0]], dtype=complex), spoke_contexts=bad_spokes, center=(0.5, 0.5)),
    ]
    # Make the second sampled center incompatible with the rank-one boundary.
    bad_center = vertex(CENTER, [[0], [1]], (0.0,))
    b = levels[1].boundary
    interior = qualify_plaquette_interior(b, bad_center, contexts())
    levels[1] = PlaquetteRefinementLevel(b, interior, 0.5)
    unqualified = qualify_plaquette_refinement(levels, thresholds=refinement_thresholds())
    assert unqualified.status == "PLAQUETTE_REFINEMENT_UNQUALIFIED"


def test_nonmonotonic_steps_and_nonhomothetic_geometry_are_rejected():
    levels = [make_level(1.0, [[1], [0]]), make_level(0.5, [[1], [0]])]
    levels[1] = PlaquetteRefinementLevel(levels[1].boundary, levels[1].interior, 1.0)
    with pytest.raises(ValueError, match="strictly decreasing"):
        qualify_plaquette_refinement(levels, thresholds=refinement_thresholds())

    levels = [make_level(1.0, [[1], [0]]), make_level(0.5, [[1], [0]])]
    warped = list(levels[1].boundary.vertices)
    warped[0] = vertex((0.2, 0.25), [[1], [0]], (0.0,))
    warped[2] = vertex((0.8, 0.75), [[1], [0]], (0.0,))
    boundary = qualify_plaquette_boundary(warped, contexts(), thresholds=e3_thresholds())
    interior = qualify_plaquette_interior(boundary, vertex(CENTER, [[1], [0]], (0.0,)), contexts())
    levels[1] = PlaquetteRefinementLevel(boundary, interior, 0.5)
    with pytest.raises(ValueError, match="homothetic|declared refinement"):
        qualify_plaquette_refinement(levels, thresholds=refinement_thresholds())


def test_final_quality_and_final_pair_stability_thresholds_are_enforced():
    levels = [make_level(1.0, [[1], [0]]), make_level(0.5, [[1], [0]]), make_level(0.25, [[1], [0]])]
    result = qualify_plaquette_refinement(
        levels,
        thresholds=refinement_thresholds(min_singular_value=1.1),
    )
    assert result.status == "PLAQUETTE_REFINEMENT_UNQUALIFIED"
    assert not result.authorization_granted


def test_serialization_preserves_level_metrics_without_observable_authorization():
    levels = [make_level(1.0, [[1], [0]]), make_level(0.5, [[1], [0]])]
    result = qualify_plaquette_refinement(levels, thresholds=refinement_thresholds())
    encoded = json.dumps(result.to_dict())
    assert json.loads(encoded)["authorization_scope"] == IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE
    for forbidden in ("berry", "wilson", "chern", "transport_product", "physical_band_id", "branch_id", "full_interior"):
        assert forbidden not in encoded.lower()
