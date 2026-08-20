from dataclasses import replace
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from mephc.berry_scale_convergence import LocalBerryConvergenceSample, annotate_neighbor_changes
from mephc.berry_semantics import CANONICAL_SIGN_CONVENTION
from mephc.mpb_berry_estimator import estimate_mpb_rank1_berry_curvature
from mephc.plaquette_semantics import CENTERED_CCW, LEGACY_FORWARD_CCW, build_local_plaquette


def test_neighbor_deltas_use_coordinate_adjacency_not_minimum_observable_difference():
    samples = tuple(
        LocalBerryConvergenceSample(resolution=resolution, step=step, result=result, qualification="QUALIFIED")
        for resolution in (32, 64, 96)
        for step, result in ((0.01, 0.0), (0.02, 1.0), (0.03, 1.000001))
    )
    annotated = annotate_neighbor_changes(samples)
    center = next(item for item in annotated if item.resolution == 64 and item.step == 0.02)
    assert center.neighboring_step_change is None
    step_deltas = sorted((item.direction, item.step, item.absolute_change) for item in center.neighboring_step_deltas)
    assert step_deltas[0][0:2] == (-1, 0.01) and step_deltas[0][2] == pytest.approx(1.0)
    assert step_deltas[1][0:2] == (1, 0.03) and step_deltas[1][2] == pytest.approx(0.000001)
    assert {(item.direction, item.resolution) for item in center.neighboring_resolution_deltas} == {(-1, 32), (1, 96)}
    assert all(item.provenance["neighbor_selection"] == "coordinate_adjacent_only" for item in annotated)


def test_ccw_conventions_fail_closed_for_negative_nonorthogonal_orientation():
    for convention in (CENTERED_CCW, LEGACY_FORWARD_CCW):
        with pytest.raises(ValueError, match="positive determinant"):
            build_local_plaquette((0.0, 0.0), (1.0, 0.2), (0.1, -1.0), convention=convention)
    geometry = build_local_plaquette((0.0, 0.0), (1.0, 0.2), (-0.1, 1.0), convention=CENTERED_CCW)
    assert geometry.orientation == "CCW"
    assert geometry.signed_area > 0.0


def test_canonical_sign_contract_is_solver_neutral_and_not_paper_inferred():
    geometry = build_local_plaquette((0.0, 0.0), 0.2)
    phase = -0.5
    canonical = -phase / geometry.signed_area / (2.0 * np.pi) ** 2
    assert CANONICAL_SIGN_CONVENTION == "OMEGA = -WILSON_PHASE / SIGNED_AREA / (2*pi)^2"
    assert canonical > 0.0
    reversed_area = -geometry.signed_area
    reversed_phase = -phase
    assert -reversed_phase / reversed_area / (2.0 * np.pi) ** 2 == pytest.approx(canonical)
    assert canonical != pytest.approx(phase / geometry.signed_area / (2.0 * np.pi) ** 2)


def test_unresolved_gap_boundary_and_just_above_tolerance_control():
    fixture_path = Path(__file__).with_name("test_e7e_mpb_berry_estimator.py")
    spec = importlib.util.spec_from_file_location("e7e_ref51_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(fixture)
    base = fixture.dirac_e7d()
    source = base.source_result
    tolerance = float(source.interior_results[0].thresholds.validation_tolerance)

    def with_center_gap(gap: float):
        levels = []
        for level in source.snapshots:
            frequencies = np.array(level[4].frequencies, copy=True)
            frequencies[1] = frequencies[0] + gap
            levels.append(tuple(level[:4]) + (replace(level[4], frequencies=frequencies),))
        return replace(base, source_result=replace(source, snapshots=tuple(levels)))

    unresolved = estimate_mpb_rank1_berry_curvature(with_center_gap(tolerance), require_live=False)
    control = estimate_mpb_rank1_berry_curvature(with_center_gap(tolerance * 1.01), require_live=False)
    assert all(level.status == "BERRY_DEGENERATE_POINT_UNQUALIFIED" for level in unresolved.levels)
    assert all(level.curvature_estimate is None and level.wilson_phase is not None and level.signed_area is not None for level in unresolved.levels)
    assert all(level.status == "BERRY_ESTIMATE_QUALIFIED" for level in control.levels)
    assert all(level.curvature_estimate is not None for level in control.levels)
