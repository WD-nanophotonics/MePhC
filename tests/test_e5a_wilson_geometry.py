import json
from dataclasses import replace

import numpy as np
import pytest

from mephc.eigenspace import EigenSubspace
from mephc.path_domain import qualify_ordered_path
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.wilson_geometry import (
    WILSON_INPUT_INCOMPLETE,
    WILSON_INPUT_UNQUALIFIED,
    WILSON_LINE_QUALIFIED,
    WILSON_LOOP_QUALIFIED,
    WILSON_TRANSPORT_AUTHORIZATION_SCOPE,
    compose_wilson_transport,
)


POINTS = ((0.0,), (1.0,), (2.0,), (3.0,))


def vertex(point, frame, values=(0.0,), indices=None):
    frame = np.asarray(frame, dtype=complex)
    return EigenSubspace(
        k_point=tuple(float(item) for item in point),
        frame=frame,
        eigenvalues=tuple(values),
        solver_indices=tuple(range(frame.shape[1]) if indices is None else indices),
        metadata={"fixture": "E5A"},
    )


def thresholds(**overrides):
    values = {"min_singular_value": 0.8, "max_principal_angle": 0.7, "max_projector_distance": 0.9, "min_external_gap": 1.0}
    values.update(overrides)
    return SubspaceQualificationThresholds(**values)


def contexts(count, gap=5.0):
    return [ExternalIsolationContext((gap,), (gap,), {"source": "E5A"}) for _ in range(count)]


def rank_one(phases):
    return [vertex(point, [[np.exp(1j * phase)], [0.0]], indices=(i,)) for i, (point, phase) in enumerate(zip(POINTS, phases))]


def rank_two(gauges):
    base = np.eye(4, 2, dtype=complex)
    return [vertex(point, base @ gauge, values=(0.0, 0.0), indices=(i, i + 10)) for i, (point, gauge) in enumerate(zip(POINTS, gauges))]


def test_rank_one_open_line_preserves_order_and_hides_loop_invariants():
    phases = (0.0, 0.2, -0.1, 0.5)
    result = compose_wilson_transport(qualify_ordered_path(rank_one(phases), contexts(3), thresholds=thresholds(), closed=False))
    expected = np.eye(1, dtype=complex)
    for link in result.edge_links:
        expected = expected @ link.unitary
    assert result.status == WILSON_LINE_QUALIFIED
    assert np.allclose(result.product, expected)
    assert result.trace is None and result.determinant is None
    assert result.eigenvalues is None and result.eigenphases is None


def test_rank_one_closed_loop_has_scalar_invariants():
    phases = (0.0, 0.2, -0.1, 0.5)
    result = compose_wilson_transport(qualify_ordered_path(rank_one(phases), contexts(4), thresholds=thresholds(), closed=True))
    assert result.status == WILSON_LOOP_QUALIFIED
    assert np.allclose(result.product, [[1.0]])
    assert np.allclose(result.eigenvalues, [1.0])
    assert np.allclose(result.eigenphases, [0.0])
    assert np.allclose(result.trace, 1.0) and np.allclose(result.determinant, 1.0)


def test_u2_open_line_uses_exact_ordered_link_product():
    rng = np.random.default_rng(20260819)
    gauges = [np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))[0] for _ in POINTS]
    result = compose_wilson_transport(qualify_ordered_path(rank_two(gauges), contexts(3), thresholds=thresholds(), closed=False))
    expected = np.eye(2, dtype=complex)
    for link in result.edge_links:
        expected = expected @ link.unitary
    assert result.status == WILSON_LINE_QUALIFIED
    assert np.allclose(result.product, expected)


def test_u2_closed_loop_conjugation_and_invariants():
    rng = np.random.default_rng(20260820)
    gauges = [np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))[0] for _ in POINTS]
    extra = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))[0]
    base = rank_two(gauges)
    changed_vertices = [vertex(item.k_point, item.frame @ extra, values=(0.0, 0.0), indices=item.solver_indices) for item in base]
    original = compose_wilson_transport(qualify_ordered_path(base, contexts(4), thresholds=thresholds(), closed=True))
    changed = compose_wilson_transport(qualify_ordered_path(changed_vertices, contexts(4), thresholds=thresholds(), closed=True))
    assert np.allclose(changed.product, extra.conj().T @ original.product @ extra, atol=1e-10)
    assert np.allclose(np.sort_complex(changed.eigenvalues), np.sort_complex(original.eigenvalues))
    assert np.allclose(changed.trace, original.trace) and np.allclose(changed.determinant, original.determinant)


def test_degenerate_rank_two_loop_is_identity_and_cyclic_shift_preserves_invariants():
    rng = np.random.default_rng(20260821)
    gauges = [np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))[0] for _ in POINTS]
    result = compose_wilson_transport(qualify_ordered_path(rank_two(gauges), contexts(4), thresholds=thresholds(), closed=True))
    assert np.allclose(result.product, np.eye(2), atol=1e-10)
    phases = (0.0, 0.4, -0.3, 0.9)
    original = compose_wilson_transport(qualify_ordered_path(rank_one(phases), contexts(4), thresholds=thresholds(), closed=True))
    shifted = compose_wilson_transport(qualify_ordered_path(rank_one(phases)[1:] + rank_one(phases)[:1], contexts(4), thresholds=thresholds(), closed=True))
    assert np.allclose(shifted.eigenvalues, original.eigenvalues)
    assert np.allclose(shifted.trace, original.trace) and np.allclose(shifted.determinant, original.determinant)


def test_reverse_path_is_adjoint():
    phases = (0.0, 0.2, -0.1, 0.5)
    forward = compose_wilson_transport(qualify_ordered_path(rank_one(phases), contexts(3), thresholds=thresholds(), closed=False))
    reverse = compose_wilson_transport(qualify_ordered_path(list(reversed(rank_one(phases))), contexts(3), thresholds=thresholds(), closed=False))
    assert np.allclose(reverse.product, forward.product.conj().T, atol=1e-10)


def test_incomplete_unqualified_and_missing_link_fail_closed():
    phases = (0.0, 0.2, -0.1, 0.5)
    missing_context = contexts(3)
    missing_context[1] = None
    incomplete_path = qualify_ordered_path(rank_one(phases), missing_context, thresholds=thresholds(), closed=False)
    incomplete = compose_wilson_transport(incomplete_path)
    assert incomplete.status == WILSON_INPUT_INCOMPLETE and incomplete.product is None
    poor_vertices = rank_one(phases)
    poor_vertices[2] = vertex(POINTS[2], [[0.0], [1.0]], indices=(2,))
    poor = compose_wilson_transport(qualify_ordered_path(poor_vertices, contexts(3), thresholds=thresholds(), closed=False))
    assert poor.status == WILSON_INPUT_UNQUALIFIED and poor.product is None
    good_path = qualify_ordered_path(rank_one(phases), contexts(3), thresholds=thresholds(), closed=False)
    broken = replace(good_path, edge_results=tuple(replace(edge, transport_link=None) for edge in good_path.edge_results))
    failed = compose_wilson_transport(broken)
    assert failed.status == WILSON_INPUT_UNQUALIFIED and failed.product is None


def test_readonly_json_safe_and_no_recompute_for_bad_endpoint():
    phases = (0.0, 0.2, -0.1, 0.5)
    result = compose_wilson_transport(qualify_ordered_path(rank_one(phases), contexts(4), thresholds=thresholds(), closed=True))
    with pytest.raises(ValueError):
        result.product[0, 0] = 2.0
    assert json.loads(json.dumps(result.to_dict()))["authorization_scope"] == WILSON_TRANSPORT_AUTHORIZATION_SCOPE
    path = qualify_ordered_path(rank_one(phases), contexts(3), thresholds=thresholds(), closed=False)
    link = path.edge_results[0].transport_link
    broken_link = replace(link, left_k_point=(99.0,))
    broken = replace(path, edge_results=(replace(path.edge_results[0], transport_link=broken_link),) + path.edge_results[1:])
    assert compose_wilson_transport(broken).product is None
