import json

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.plaquette_domain import (
    BOUNDARY_AUTHORIZATION_SCOPE,
    PLAQUETTE_BOUNDARY_INCOMPLETE,
    PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED,
    PLAQUETTE_BOUNDARY_UNQUALIFIED,
    qualify_plaquette_boundary,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds


def vertex(k, frame, values, indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=tuple(float(item) for item in k),
        frame=frame,
        eigenvalues=tuple(values),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": "E4A"},
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
    return [ExternalIsolationContext((gap,), (gap,), {"source": "E4A"}) for _ in range(4)]


def square_vertices(frame, values=(0.0,), indices=None):
    points = ((0, 0), (1, 0), (1, 1), (0, 1))
    return [vertex(point, frame, values, indices) for point in points]


def test_smooth_isolated_rank_one_boundary_qualifies_and_closes_on_first_vertex():
    result = qualify_plaquette_boundary(
        square_vertices([[1], [0]], (0.0,)),
        contexts(),
        thresholds=thresholds(),
        provenance={"fixture": "smooth-boundary"},
    )
    assert result.status == PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED
    assert result.is_qualified
    assert len(result.edge_results) == 4
    assert result.edge_results[3].right_k_point == result.vertices[0].k_point
    assert result.authorization_scope == BOUNDARY_AUTHORIZATION_SCOPE


def test_exact_degenerate_rank_two_is_invariant_under_independent_local_u2_gauges():
    base = np.eye(4, 2, dtype=complex)
    reference = qualify_plaquette_boundary(
        square_vertices(base, (0.0, 0.0), (1, 2)),
        contexts(),
        thresholds=thresholds(),
    )
    assert reference.status == PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED
    rng = np.random.default_rng(20260819)
    for _ in range(6):
        gauged = []
        for point, context_index in zip(((0, 0), (1, 0), (1, 1), (0, 1)), range(4)):
            gauge, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
            gauged.append(vertex(point, base @ gauge, (0.0, 0.0), (7 + context_index, 2 + context_index)))
        result = qualify_plaquette_boundary(gauged, contexts(), thresholds=thresholds())
        assert result.status == reference.status
        assert all(np.allclose(a.overlap.singular_values, b.overlap.singular_values)
                   for a, b in zip(result.edge_results, reference.edge_results))


def test_solver_order_and_u1_phases_do_not_change_boundary_result():
    base = np.eye(3, 1, dtype=complex)
    baseline = qualify_plaquette_boundary(square_vertices(base), contexts(), thresholds=thresholds())
    phased = [
        vertex(point, base * np.exp(phase * 1j), (0.0,), (index + 10,))
        for index, (point, phase) in enumerate(zip(((0, 0), (1, 0), (1, 1), (0, 1)), (0.2, -0.4, 0.7, -0.9)))
    ]
    result = qualify_plaquette_boundary(phased, contexts(), thresholds=thresholds())
    assert baseline.status == result.status == PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED
    assert [edge.status for edge in baseline.edge_results] == [edge.status for edge in result.edge_results]


def test_near_singular_edge_is_boundary_unqualified_without_transport_product():
    bad = square_vertices([[1], [0]], (0.0,))
    bad[1] = vertex((1, 0), [[0], [1]], (0.0,))
    result = qualify_plaquette_boundary(bad, contexts(), thresholds=thresholds())
    assert result.status == PLAQUETTE_BOUNDARY_UNQUALIFIED
    assert all(edge.transport_link is None for edge in result.edge_results if not edge.is_qualified)
    assert "transport_product" not in result.to_dict()


def test_missing_edge_context_is_boundary_incomplete():
    aligned = contexts()
    aligned[2] = None
    result = qualify_plaquette_boundary(
        square_vertices([[1], [0]], (0.0,)),
        aligned,
        thresholds=thresholds(),
    )
    assert result.status == PLAQUETTE_BOUNDARY_INCOMPLETE
    assert result.edge_results[2].status == "NUMERICALLY_INCOMPLETE"


def test_invalid_shape_rank_ambient_and_coordinate_inputs_rejected_before_partial_qualification():
    with pytest.raises(ValueError, match="exactly four"):
        qualify_plaquette_boundary(square_vertices([[1], [0]])[:3], contexts(), thresholds=thresholds())
    with pytest.raises(ValueError, match="exactly four"):
        qualify_plaquette_boundary(square_vertices([[1], [0]]), contexts()[:3], thresholds=thresholds())
    bad_rank = square_vertices(np.eye(3, 2), (0.0, 0.0))
    bad_rank[2] = vertex((1, 1), [[1], [0], [0]], (0.0,))
    with pytest.raises(ValueError, match="fixed rank"):
        qualify_plaquette_boundary(bad_rank, contexts(), thresholds=thresholds())


def test_incompatible_closing_edge_fails_even_when_early_edges_are_valid():
    vertices = square_vertices([[1], [0]], (0.0,))
    vertices[3] = vertex((0, 1), [[0], [1]], (0.0,))
    result = qualify_plaquette_boundary(vertices, contexts(), thresholds=thresholds())
    assert result.status == PLAQUETTE_BOUNDARY_UNQUALIFIED
    assert result.edge_results[3].transport_link is None


def test_boundary_result_is_json_safe_immutable_and_has_no_global_authorization_claims():
    result = qualify_plaquette_boundary(
        square_vertices(np.eye(4, 2), (0.0, 0.0)),
        contexts(),
        thresholds=thresholds(),
    )
    serialized = json.dumps(result.to_dict())
    assert json.loads(serialized)["authorization_scope"] == BOUNDARY_AUTHORIZATION_SCOPE
    assert not result.edge_results[0].overlap.singular_values.flags.writeable
    for forbidden in ("physical_band_id", "branch_id", "adiabatic_band_id", "berry", "wilson", "chern"):
        assert forbidden not in serialized.lower()
