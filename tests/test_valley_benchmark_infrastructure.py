import math

import numpy as np
import pytest

from mephc.valley_benchmark import (
    DELTA_K_VALUES,
    INTEGRATION_SPACING_Q,
    MEPHC_PERIODIC_VORONOI_K_BASIN,
    PAPER_STYLE_TRUNCATED_K_HBZ,
    centered_ccw_plaquette_requests,
    build_identity_coordinate_preflight,
    integrate_sampled_field,
    mephc_periodic_voronoi_k_basin,
    paper_style_truncated_k_hbz,
    plan_cache_requests,
    reduce_trend,
    sample_domain,
    triangular_benchmark_anchors,
    PhysicalSolveIdentity,
    PhysicalSolveCache,
)
from mephc.valley_reference_geometry import (
    REFERENCE_AIR_FILL_FRACTION,
    TRIANGULAR_CELL_AREA,
    build_triangular_reference_geometry,
)


def test_geometry_endpoints_and_fixed_fill_are_deterministic():
    triangle = build_triangular_reference_geometry(0.0)
    circle = build_triangular_reference_geometry(0.5)
    rounded = build_triangular_reference_geometry(0.4)
    assert triangle.shape_kind == "triangle"
    assert circle.shape_kind == "circle"
    assert rounded.shape_kind == "rounded_triangle"
    assert len(triangle.vertices) == 3
    assert len(circle.vertices) == 96
    for geometry in (triangle, rounded, circle):
        assert geometry.cell_area == pytest.approx(TRIANGULAR_CELL_AREA)
        assert geometry.air_area / geometry.cell_area == pytest.approx(REFERENCE_AIR_FILL_FRACTION, abs=5e-13)
        assert geometry.geometry_digest == build_triangular_reference_geometry(geometry.fr).geometry_digest


def test_coordinate_preflight_binds_round_trip_k_kp_and_orientation():
    preflight = build_identity_coordinate_preflight()
    assert preflight.round_trip_residual == pytest.approx(0.0)
    assert preflight.k_label_mapping_bound
    assert preflight.kp_time_reversal_bound
    assert preflight.positive_orientation
    assert preflight.ready
    assert preflight.delta_k_to_public_q(1.0 / 36.0) == pytest.approx((1.0 / 36.0, 0.0))
    assert len(preflight.mapping_digest) == 64


def test_reference_domains_are_explicit_and_fr049_has_no_paper_preset():
    fr00 = paper_style_truncated_k_hbz(fr=0.0, delta_k=0.10, delta_gamma=0.10)
    fr04 = paper_style_truncated_k_hbz(fr=0.4, delta_k=0.05, delta_gamma=0.13)
    assert fr00.domain_id.startswith(PAPER_STYLE_TRUNCATED_K_HBZ)
    assert fr04.domain_id.startswith(PAPER_STYLE_TRUNCATED_K_HBZ)
    assert len(fr00.exclusions) == 3
    assert len(fr04.exclusions) == 3
    assert fr00.area_q > 0.0
    assert fr04.area_q > 0.0
    assert fr00.digest != fr04.digest
    with pytest.raises(ValueError):
        paper_style_truncated_k_hbz(fr=0.49, delta_k=0.05, delta_gamma=0.13)


def test_mephc_domain_preserves_sealed_area_and_identity():
    domain = mephc_periodic_voronoi_k_basin()
    assert domain.domain_id == "PERIODIC_RECIPROCAL_METRIC_VORONOI_BASIN_K"
    assert domain.area_q == pytest.approx(1.0 / math.sqrt(3.0), rel=0.0, abs=1e-12)
    assert domain.classify((2.0 / 3.0, 0.0)) == "RETAINED"
    assert len(domain.digest) == 64


def test_domain_sampling_spacing_is_deterministic_and_declared_exclusions_are_reported():
    domain = paper_style_truncated_k_hbz(fr=0.0, delta_k=0.10, delta_gamma=0.10)
    first = sample_domain(domain, 1.0 / 36.0)
    second = sample_domain(domain, 1.0 / 36.0)
    assert first.to_dict() == second.to_dict()
    assert first.center_count > 0
    assert first.declared_exclusion_count == 3
    assert sum(first.weights) == pytest.approx(first.retained_area_q)


def test_synthetic_integration_and_unexpected_mask_fail_closed():
    sample = sample_domain(mephc_periodic_voronoi_k_basin(), 1.0 / 18.0)
    constant = integrate_sampled_field(sample, [2.0] * sample.center_count)
    assert constant == pytest.approx(2.0 * sample.retained_area_q)
    assert integrate_sampled_field(sample, [1.0] * sample.center_count, orientation_sign=-1) == pytest.approx(-sample.retained_area_q)
    with pytest.raises(ValueError, match="unexpected interior mask"):
        integrate_sampled_field(sample, [1.0] * sample.center_count, unexpected_mask_reasons=("band_gap",))
def test_centered_plaquette_planner_preserves_nominal_and_canonical_identity():
    requests = centered_ccw_plaquette_requests(((0.0, 0.0), (0.2, 0.0)), 0.2)
    assert len(requests) == 8
    assert requests[0].nominal_center_q == (0.0, 0.0)
    assert requests[0].nominal_vertex_q == (-0.1, -0.1)
    assert requests[0].canonical_periodic_vertex_q == pytest.approx((0.9, 0.9))
    plan = plan_cache_requests(requests)
    assert plan.raw_vertex_requests == 8
    assert plan.canonical_unique_vertices == 6
    assert plan.cache_hits == 2
    assert plan.cache_hit_fraction == pytest.approx(0.25)


def test_cache_identity_includes_physical_q_without_display_rounding_and_excludes_sampling_controls():
    common = dict(
        geometry_digest="g" * 64,
        material_reference_digest="m" * 64,
        coordinate_mapping_digest="c" * 64,
        resolution=64,
        num_bands=4,
        polarization="TE",
        provider_representation="mpb_live_energy_eh_v1",
        eigensolver_tolerance=1e-7,
        deterministic=True,
        mesh_size=3,
    )
    left = PhysicalSolveIdentity(evaluated_q=(0.1234567890123, 0.2), **common)
    right = PhysicalSolveIdentity(evaluated_q=(0.1234567890124, 0.2), **common)
    assert left.cache_key != right.cache_key
    cache = PhysicalSolveCache()
    cache.register(left)
    with pytest.raises(ValueError, match="cache identity collision"):
        cache.register(right, claimed_key=left.cache_key)


def test_trend_reducer_is_nonstatistical_and_fail_closed():
    confirmed = reduce_trend(0.0, 1.0, delta_C_delta_k=0.1, delta_C_integration=0.1, delta_C_resolution=0.1, delta_C_domain=0.1, direction_stable=True)
    unresolved = reduce_trend(0.0, 0.2, delta_C_delta_k=0.1, delta_C_integration=0.1, delta_C_resolution=0.1, delta_C_domain=0.1, direction_stable=True)
    unqualified = reduce_trend(0.0, 1.0, delta_C_delta_k=0.0, delta_C_integration=0.0, delta_C_resolution=0.0, delta_C_domain=0.0, direction_stable=True, identity_or_qualification_status="UNQUALIFIED")
    assert confirmed.status == "TREND_CONFIRMED"
    assert unresolved.status == "NUMERICALLY_UNRESOLVED"
    assert unqualified.status == "PHYSICALLY_UNQUALIFIED"


def test_anchor_specs_encode_triangular_first_and_exact_symmetry_prohibition():
    anchors = triangular_benchmark_anchors()
    assert [anchor.anchor_id for anchor in anchors] == [
        "TRI_TPC_FR00", "TRI_TPC_FR04", "TRI_TPC_NEAR_SYMMETRY_FR049", "CIR_TPC_EXACT_SYMMETRY_FR050"
    ]
    assert all(anchor.family in {"Tri-TPC", "Cir-TPC"} for anchor in anchors)
    assert anchors[-1].rank1_prohibited_at_target
    assert not anchors[2].paper_domain_available


def test_independent_ladders_are_explicit():
    assert DELTA_K_VALUES == pytest.approx((1 / 72, 1 / 36, 1 / 18))
    assert INTEGRATION_SPACING_Q == pytest.approx((1 / 18, 1 / 36, 1 / 72))
    assert DELTA_K_VALUES != INTEGRATION_SPACING_Q
