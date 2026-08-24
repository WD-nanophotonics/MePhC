import pytest

from audit.e9f.run_e9f_c1_d1_c1 import (
    corrected_side,
    segment_crosses_outer_boundary,
    segment_enters_gamma_exclusion,
    segment_leaves_outer_domain,
)

OUTER = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
GAMMA = [[(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]]
NO_GAMMA = [[(2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (2.0, 3.0)]]


def test_segment_entirely_inside_does_not_cross_or_leave():
    seg = ((0.2, 0.2), (0.8, 0.8))
    assert not segment_crosses_outer_boundary(seg, OUTER)
    assert not segment_leaves_outer_domain(seg, OUTER)


def test_inside_to_outside_crosses_and_leaves():
    seg = ((0.5, 0.5), (1.5, 0.5))
    assert segment_crosses_outer_boundary(seg, OUTER)
    assert segment_leaves_outer_domain(seg, OUTER)


def test_outside_to_inside_crosses_and_leaves():
    seg = ((-0.5, 0.5), (0.5, 0.5))
    assert segment_crosses_outer_boundary(seg, OUTER)
    assert segment_leaves_outer_domain(seg, OUTER)


def test_outside_to_outside_through_polygon_crosses_and_leaves():
    seg = ((-0.5, 0.5), (1.5, 0.5))
    assert segment_crosses_outer_boundary(seg, OUTER)
    assert segment_leaves_outer_domain(seg, OUTER)


def test_outside_to_outside_avoiding_polygon_does_not_cross():
    seg = ((-0.5, 2.0), (1.5, 2.0))
    assert not segment_crosses_outer_boundary(seg, OUTER)
    assert segment_leaves_outer_domain(seg, OUTER)


def test_inside_parallel_to_boundary_does_not_cross_or_leave():
    seg = ((0.2, 0.2), (0.2, 0.8))
    assert not segment_crosses_outer_boundary(seg, OUTER)
    assert not segment_leaves_outer_domain(seg, OUTER)


def test_boundary_overlap_is_deterministic_contact_without_leaving():
    seg = ((0.0, 0.2), (0.0, 0.8))
    assert segment_crosses_outer_boundary(seg, OUTER)
    assert not segment_leaves_outer_domain(seg, OUTER)


def test_convex_plaquette_inside_has_distinct_boundary_semantics():
    old = {
        "side": 0.2,
        "center": {"q": [0.5, 0.5], "retained_inside": True},
        "vertices": [{"q": [0.4, 0.4]}, {"q": [0.6, 0.4]}, {"q": [0.6, 0.6]}, {"q": [0.4, 0.6]}],
    }
    result = corrected_side(old, OUTER, NO_GAMMA)
    assert not result["plaquette_crosses_outer_boundary"]
    assert not result["plaquette_leaves_outer_domain"]
    assert result["plaquette_fully_retained"]


def test_plaquette_with_outside_vertex_leaves_and_crosses():
    old = {
        "side": 0.2,
        "center": {"q": [0.5, 0.5], "retained_inside": True},
        "vertices": [{"q": [-0.1, 0.4]}, {"q": [0.6, 0.4]}, {"q": [0.6, 0.6]}, {"q": [-0.1, 0.6]}],
    }
    result = corrected_side(old, OUTER, GAMMA)
    assert result["plaquette_crosses_outer_boundary"]
    assert result["plaquette_leaves_outer_domain"]
    assert not result["plaquette_fully_retained"]


def test_gamma_exclusion_crossing_with_outside_endpoints_is_detected():
    seg = ((0.2, 0.5), (0.8, 0.5))
    assert segment_enters_gamma_exclusion(seg, GAMMA)


def test_gamma_exclusion_avoided_is_false():
    seg = ((0.2, 0.2), (0.8, 0.2))
    assert not segment_enters_gamma_exclusion(seg, GAMMA)


def test_inside_outer_endpoints_cannot_be_outer_crossing():
    seg = ((0.1, 0.1), (0.9, 0.9))
    assert not segment_crosses_outer_boundary(seg, OUTER)


@pytest.mark.parametrize("seg", [((0.5, 0.5), (1.5, 0.5)), ((-0.5, 0.5), (0.5, 0.5))])
def test_crossing_direction_is_symmetric(seg):
    assert segment_crosses_outer_boundary(seg, OUTER)
    assert segment_leaves_outer_domain(seg, OUTER)
