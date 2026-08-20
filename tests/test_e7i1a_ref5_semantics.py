from dataclasses import replace
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from mephc.berry_scale_convergence import (
    LocalBerryConvergenceGrid,
    LocalBerryConvergenceSample,
    annotate_neighbor_changes,
)
from mephc.isolation_profile import ScaleAwareIsolationMetrics, ScaleAwareIsolationProfile
from mephc.mpb_berry_estimator import estimate_mpb_rank1_berry_curvature
from mephc.plaquette_semantics import (
    CENTERED_CCW,
    LEGACY_FORWARD_CCW,
    build_local_plaquette,
    polygon_signed_area,
)


def test_centered_and_legacy_geometry_are_explicit_and_provenanced():
    centered = build_local_plaquette((1.0, 2.0), 0.2, 0.4, convention=CENTERED_CCW)
    legacy = build_local_plaquette((1.0, 2.0), 0.2, 0.4, convention=LEGACY_FORWARD_CCW)
    assert centered.geometric_center == pytest.approx((1.0, 2.0))
    assert legacy.geometric_center == pytest.approx((1.1, 2.2))
    assert centered.signed_area == pytest.approx(0.08)
    assert legacy.to_dict()["convention"] == LEGACY_FORWARD_CCW
    assert legacy.to_dict()["ordered_vertices"] == [list(point) for point in legacy.ordered_vertices]


def test_constant_linear_and_quadratic_field_semantics_are_solver_neutral():
    geometry = build_local_plaquette((0.3, -0.2), (0.2, 0.05), (-0.03, 0.15))
    center = np.asarray(geometry.geometric_center)
    omega0, gradient = 1.25, np.array((0.4, -0.7))
    assert omega0 + np.dot(gradient, center) == pytest.approx(
        omega0 + np.dot(gradient, np.asarray(geometry.requested_k))
    )
    vertices = np.asarray(geometry.ordered_vertices)
    quadratic_vertex_mean = float(np.mean(np.sum(vertices * vertices, axis=1)))
    expected_quadratic_mean = float(np.dot(center, center) + (
        np.dot(geometry.dx, geometry.dx) + np.dot(geometry.dy, geometry.dy)
    ) / 4.0)
    assert quadratic_vertex_mean == pytest.approx(expected_quadratic_mean)


def test_orientation_reversal_reverses_signed_area_but_not_a_consistently_oriented_phase():
    geometry = build_local_plaquette((0.0, 0.0), 0.2)
    reversed_area = polygon_signed_area(tuple(reversed(geometry.ordered_vertices)))
    assert reversed_area == pytest.approx(-geometry.signed_area)
    omega = 0.75
    assert -(-omega * geometry.signed_area) / geometry.signed_area == pytest.approx(omega)
    assert -(omega * reversed_area) / reversed_area == pytest.approx(-omega)


def test_resolution_step_grid_records_neighbors_without_finest_wins_rule():
    samples = tuple(LocalBerryConvergenceSample(r, h, 1.0 + h + r / 1000.0, "QUALIFIED")
                    for r in (32, 64) for h in (0.02, 0.01))
    annotated = annotate_neighbor_changes(samples)
    grid = LocalBerryConvergenceGrid(
        annotated, CENTERED_CCW, "periodic_h_bloch_envelope",
        provenance={"selection_policy": "explicit_stability_window_only"},
    )
    assert len(grid.samples) == 4
    assert all(sample.neighboring_step_change is not None for sample in grid.samples)
    assert grid.to_dict()["steps"] == [0.02, 0.01]
    assert "smallest" not in str(grid.to_dict()).lower()


def test_scale_aware_candidate_is_additive_and_reference_ladder_is_explicit():
    profile = ScaleAwareIsolationProfile(
        min_relative_gap=0.01, min_motion_ratio=3.0,
        min_solver_uncertainty_ratio=10.0, min_singular_value=0.9,
        max_principal_angle=0.45, max_projector_distance=0.3,
    )
    cases = {
        "degeneracy": (0.0, 0.2, 0.1, 1e-4, 0.99, 0.01, 0.02, False),
        "massless_dirac": (0.0, 0.2, 0.1, 1e-4, 0.99, 0.01, 0.02, False),
        "weak_honeycomb": (0.009, 0.3, 0.001, 1e-4, 0.99, 0.01, 0.02, True),
        "d0500_reference": (0.05, 0.8, 0.005, 1e-4, 0.99, 0.01, 0.02, True),
        "synthetic_entangled_e3": (0.2, 0.8, 0.01, 1e-4, 0.2, 0.9, 0.8, False),
    }
    for name, values in cases.items():
        metrics = ScaleAwareIsolationMetrics(
            absolute_gap=values[0], reference_frequency=values[1],
            local_spectral_motion=values[2], solver_uncertainty=values[3],
            min_singular_value=values[4], max_principal_angle=values[5],
            max_projector_distance=values[6],
        )
        assert profile.evaluate(metrics).passed is values[7], name


def test_exact_center_degeneracy_withholds_scalar_curvature_but_preserves_loop_input():
    fixture_path = Path(__file__).with_name("test_e7e_mpb_berry_estimator.py")
    spec = importlib.util.spec_from_file_location("e7e_ref5_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(fixture)
    base = fixture.dirac_e7d()
    source = base.source_result
    changed_levels = []
    for level in source.snapshots:
        frequencies = np.array(level[4].frequencies, copy=True)
        frequencies[1] = frequencies[0]
        center = replace(level[4], frequencies=frequencies)
        changed_levels.append(tuple(level[:4]) + (center,))
    degenerate_source = replace(source, snapshots=tuple(changed_levels))
    degenerate = replace(base, source_result=degenerate_source)
    result = estimate_mpb_rank1_berry_curvature(degenerate, require_live=False)
    assert all(level.curvature_estimate is None for level in result.levels)
    assert all(level.status == "BERRY_DEGENERATE_POINT_UNQUALIFIED" for level in result.levels)
    assert all(level.wilson_phase is not None and level.signed_area is not None for level in result.levels)
