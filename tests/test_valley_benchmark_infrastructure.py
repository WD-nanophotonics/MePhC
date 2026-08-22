import math
from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from mephc.valley_benchmark import (
    DELTA_K_VALUES,
    INTEGRATION_SPACING_Q,
    MEPHC_PERIODIC_VORONOI_K_BASIN,
    PAPER_STYLE_TRUNCATED_K_HBZ,
    centered_ccw_plaquette_requests,
    build_identity_coordinate_preflight,
    build_triangular_coordinate_preflight,
    fractional_periodic_equivalent,
    reduce_anchor_readiness,
    periodic_equivalent,
    reciprocal_basis_from_real_space,
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
    assert unresolved.status == "TREND_QUALIFIED"
    assert unqualified.status == "PHYSICALLY_UNQUALIFIED"
    assert reduce_trend(0.0, 0.0, delta_C_delta_k=0.1, delta_C_integration=0.1, delta_C_resolution=0.1, delta_C_domain=0.1, direction_stable=True).status == "NUMERICALLY_UNRESOLVED"
    assert reduce_trend(0.0, 0.2, delta_C_delta_k=0.1, delta_C_integration=0.1, delta_C_resolution=0.1, delta_C_domain=0.1, direction_stable=False).status == "NUMERICALLY_UNRESOLVED"


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


def test_periodic_voronoi_is_analytic_and_rotationally_equivalent():
    domain = mephc_periodic_voronoi_k_basin()
    expected = {(0.0, 0.0), (1.0, -1.0 / math.sqrt(3.0)), (1.0, 1.0 / math.sqrt(3.0))}
    assert {tuple(round(value, 12) for value in point) for point in domain.vertices} == {
        tuple(round(value, 12) for value in point) for point in expected
    }
    angle = math.pi / 5.0
    rotation = ((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle)))
    rotate = lambda point: tuple(float(value) for value in np.asarray(rotation) @ np.asarray(point))
    basis = np.asarray(reciprocal_basis_from_real_space(((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0))))
    rotation_matrix = np.asarray(rotation)
    rotated = mephc_periodic_voronoi_k_basin(
        period_basis=tuple(tuple(float(value) for value in row) for row in rotation_matrix @ basis),
        k=tuple(float(value) for value in rotation_matrix @ np.asarray((2.0 / 3.0, 0.0))),
        kp=tuple(float(value) for value in rotation_matrix @ np.asarray((-2.0 / 3.0, 0.0))),
    )
    transformed_vertices = {tuple(round(float(value), 10) for value in rotation_matrix @ np.asarray(point)) for point in domain.vertices}
    rotated_vertices = {tuple(round(value, 10) for value in point) for point in rotated.vertices}
    assert rotated.area_q == pytest.approx(domain.area_q, abs=1e-12)
    assert rotated_vertices == transformed_vertices
    assert rotated.digest != domain.digest
    original_sample = sample_domain(domain, 1.0 / 72.0)
    rotated_sample = sample_domain(rotated, 1.0 / 72.0)
    original_values = [1.2 + 0.3 * point[0] - 0.7 * point[1] for point in original_sample.centers]
    rotated_values = [
        1.2 + 0.3 * float((rotation_matrix.T @ np.asarray(point))[0]) - 0.7 * float((rotation_matrix.T @ np.asarray(point))[1])
        for point in rotated_sample.centers
    ]
    original_flux = integrate_sampled_field(original_sample, original_values)
    rotated_flux = integrate_sampled_field(rotated_sample, rotated_values)
    assert rotated_flux == pytest.approx(original_flux, abs=2e-4)


def test_nonidentity_coordinate_preflight_and_two_axis_mapping():
    preflight = build_triangular_coordinate_preflight()
    assert np.asarray(preflight.public_period_basis) == pytest.approx(np.asarray(preflight.mpb_reciprocal_basis))
    assert preflight.public_q_to_mpb((2.0 / 3.0, 0.0)) == pytest.approx((1.0 / 3.0, 1.0 / 3.0))
    off_axis = (0.17, -0.23)
    assert preflight.mpb_to_public_q(preflight.public_q_to_mpb(off_axis)) == pytest.approx(off_axis)
    reciprocal = reciprocal_basis_from_real_space(((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0)))
    translated = np.asarray(off_axis) + np.asarray(reciprocal) @ np.asarray((1.0, -2.0))
    assert periodic_equivalent(off_axis, translated, reciprocal)
    assert fractional_periodic_equivalent((1.0 / 3.0, 1.0 / 3.0), (4.0 / 3.0, -2.0 / 3.0))
    x_vector, y_vector = preflight.delta_k_vectors_to_public_q(0.1)
    assert x_vector == pytest.approx((0.1, 0.0))
    assert y_vector == pytest.approx((0.0, 0.1))
    with pytest.raises(ValueError, match="provenance"):
        centered_ccw_plaquette_requests(((0.0, 0.0),), (x_vector, y_vector), period_basis=preflight.public_period_basis)
    requests = centered_ccw_plaquette_requests(((0.0, 0.0),), (x_vector, y_vector), period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest)
    assert requests[0].coordinate_mapping_digest == preflight.mapping_digest
    assert requests[0].period_basis_digest != "UNBOUND"
    points = np.asarray([request.nominal_vertex_q for request in requests])
    assert abs(float((points[1][0] - points[0][0]) * (points[2][1] - points[1][1]) - (points[1][1] - points[0][1]) * (points[2][0] - points[1][0]))) > 0.0


def test_geometric_quadrature_integrates_linear_and_smooth_fields():
    domain = mephc_periodic_voronoi_k_basin()
    centroid = np.asarray(domain.polygon.centroid.coords[0])
    sample = sample_domain(domain, 1.0 / 36.0)
    x_integral = integrate_sampled_field(sample, [point[0] for point in sample.centers])
    y_integral = integrate_sampled_field(sample, [point[1] for point in sample.centers])
    assert x_integral == pytest.approx(centroid[0] * domain.area_q, abs=2e-3)
    assert y_integral == pytest.approx(centroid[1] * domain.area_q, abs=2e-3)
    coarse = integrate_sampled_field(sample_domain(domain, 1.0 / 18.0), [point[0] ** 2 + point[1] ** 2 for point in sample_domain(domain, 1.0 / 18.0).centers])
    fine_sample = sample_domain(domain, 1.0 / 72.0)
    fine = integrate_sampled_field(fine_sample, [point[0] ** 2 + point[1] ** 2 for point in fine_sample.centers])
    assert abs(fine - coarse) < 2e-3


def test_geometry_and_material_contracts_fail_closed_until_semantics_are_bound():
    unresolved = build_triangular_reference_geometry(0.4)
    assert unresolved.paper_parameter_equivalence == "UNRESOLVED"
    assert not unresolved.live_reference_solve_ready
    reference = build_triangular_reference_geometry(0.0)
    assert reference.reference_material_semantics == "RELATIVE_PERMITTIVITY"
    assert reference.mpb_epsilon_value == pytest.approx(2.65)
    assert reference.material_contract_status == "REFERENCE_BOUND"
    assert reference.live_reference_solve_ready
    alternate = build_triangular_reference_geometry(0.0, material_semantics="REFRACTIVE_INDEX")
    assert alternate.mpb_epsilon_value == pytest.approx(2.65 ** 2)
    assert alternate.material_contract_status == "NON_REFERENCE_ANALOGUE"
    assert not alternate.live_reference_solve_ready


def test_sample_weights_are_geometric_and_not_renormalized():
    domain = paper_style_truncated_k_hbz(fr=0.4, delta_k=0.05, delta_gamma=0.13)
    sample = sample_domain(domain, 1.0 / 72.0)
    assert sum(sample.weights) == pytest.approx(domain.area_q, abs=1e-12)
    assert len(set(round(weight, 12) for weight in sample.weights)) > 1


def test_circle_physical_identity_is_analytic_and_independent_of_display_polygon():
    circle = build_triangular_reference_geometry(0.5)
    assert circle.primitive_kind == "circle"
    assert circle.air_area == pytest.approx(math.pi * circle.analytic_radius ** 2)
    assert circle.polygonization_area_error != pytest.approx(0.0, abs=1e-12)
    perturbed_display = replace(circle, vertices=tuple((x * 0.99, y * 0.99) for x, y in circle.vertices))
    assert perturbed_display.geometry_digest == circle.geometry_digest
    rounded = build_triangular_reference_geometry(0.4)
    perturbed_intermediate = replace(rounded, vertices=tuple((x * 0.99, y * 0.99) for x, y in rounded.vertices))
    assert perturbed_intermediate.boundary_digest != rounded.boundary_digest
    assert perturbed_intermediate.geometry_digest != rounded.geometry_digest


def test_quadrature_elements_have_domain_provenance_and_in_domain_evaluation_points():
    domain = paper_style_truncated_k_hbz(fr=0.4, delta_k=0.05, delta_gamma=0.13)
    sample = sample_domain(domain, 1.0 / 36.0)
    assert len(sample.element_ids) == sample.center_count
    assert len(sample.element_vertices) == sample.center_count
    assert len(sample.spacing_provenance) == sample.center_count
    assert all(domain.polygon.covers(Point(point)) for point in sample.centers)
    assert all(Polygon(vertices).covers(Point(center)) for vertices, center in zip(sample.element_vertices, sample.centers))
    assert sum(sample.weights) == pytest.approx(domain.area_q, abs=1e-10)


def test_anchor_readiness_is_computed_from_runtime_contracts():
    anchors = triangular_benchmark_anchors()
    preflight = build_triangular_coordinate_preflight()
    ready = reduce_anchor_readiness(
        anchors[0],
        build_triangular_reference_geometry(0.0),
        coordinate_preflight_ready=True,
        domain_available=True,
    )
    assert ready.status == "REFERENCE_READY"
    geometry_unresolved = reduce_anchor_readiness(
        anchors[1],
        build_triangular_reference_geometry(0.4),
        coordinate_preflight_ready=True,
        domain_available=True,
    )
    assert geometry_unresolved.status == "PROJECT_STRESS_ONLY"
    stress = reduce_anchor_readiness(
        anchors[2],
        build_triangular_reference_geometry(0.49),
        coordinate_preflight_ready=True,
        domain_available=True,
    )
    assert stress.status == "PROJECT_STRESS_ONLY"
    coordinate_unresolved = reduce_anchor_readiness(
        anchors[0],
        build_triangular_reference_geometry(0.0),
        coordinate_preflight_ready=False,
        domain_available=True,
    )
    assert coordinate_unresolved.status == "COORDINATE_UNRESOLVED"
    assert reduce_anchor_readiness(
        anchors[-1],
        build_triangular_reference_geometry(0.5),
        coordinate_preflight_ready=True,
        domain_available=False,
    ).status == "RANK1_PROHIBITED"
    assert preflight.ready
    assert reduce_anchor_readiness(
        anchors[0],
        replace(build_triangular_reference_geometry(0.0), orientation_source_status="UNRESOLVED"),
        coordinate_preflight_ready=True,
        domain_available=True,
    ).status == "GEOMETRY_UNRESOLVED"
