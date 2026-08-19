import json
from dataclasses import replace
import importlib.util

import meep as mp
import meep.mpb as mpb
import numpy as np
import pytest

from mephc.mpb_spectral import adapt_mpb_h_envelopes
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_berry_estimator import estimate_mpb_rank1_berry_curvature
from mephc.plaquette_domain import (
    PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED,
    PlaquetteRefinementThresholds,
)
from mephc.spectral_association import SubspaceQualificationThresholds

E3 = SubspaceQualificationThresholds(.9, .45, .3, .05)
E4C = PlaquetteRefinementThresholds(.9, .45, .3, .1)
LIVE_ESTIMATE_TOLERANCE = 2e-4


def snapshot(k, frequencies, fields):
    return adapt_mpb_h_envelopes(k, tuple(frequencies), fields)


def static_levels(rank=1):
    levels = []
    selections = []
    for h in (.02, .01, .005):
        points = ((.1-h,.2-h),(.1+h,.2-h),(.1+h,.2+h),(.1-h,.2+h),(.1,.2))
        fields = np.zeros((3, 1, 1, 3), complex)
        fields[0, 0, 0, 0] = 1
        fields[1, 0, 0, 1] = 1
        fields[2, 0, 0, 2] = 1
        levels.append(tuple(snapshot(point, (0.0, 5.0, 10.0), fields) for point in points))
        selections.append(((0,),) * 5 if rank == 1 else ((0, 1),) * 5)
    return tuple(levels), tuple(selections)


def e7d_static(rank=1):
    levels, selections = static_levels(rank)
    source = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    return compose_mpb_plaquette_holonomy(source, require_live=False)


def live_levels(phase_callback=None):
    provider = MPBLiveSpectralProvider(
        geometry=[mp.Cylinder(.2, material=mp.Medium(epsilon=12))],
        geometry_lattice=mp.Lattice(size=mp.Vector3(1, 1)),
        resolution=6, num_bands=2, polarization=mp.TE,
        default_material=mp.air, eigensolver_tolerance=1e-7,
        deterministic=True, mesh_size=3, phase_callback=phase_callback,
    )
    levels = []
    for h in (.02, .01, .005):
        points = ((.17-h,.23-h),(.17+h,.23-h),(.17+h,.23+h),(.17-h,.23+h),(.17,.23))
        levels.append(tuple(provider.solve(point) for point in points))
    return tuple(levels), (((0,),) * 5,) * 3


def live_e7d(phase_callback=None):
    levels, selections = live_levels(phase_callback)
    source = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C,
    )
    return compose_mpb_plaquette_holonomy(source)


def dirac_lower_frame(q, *, tau=1.0, mass=.7, velocity=1.0, phase=0.0):
    qx, qy = q
    dx, dy = tau * velocity * qx, velocity * qy
    radius = np.sqrt(dx * dx + dy * dy + mass * mass)
    theta = np.arccos(mass / radius)
    phi = np.arctan2(dy, dx)
    # This is the lower eigenframe in the sigma_y basis used by this fixture.
    frame = np.array([
        -np.exp(1j * phi) * np.sin(theta / 2.0),
        np.cos(theta / 2.0),
        0.0,
    ], dtype=complex)
    return frame * np.exp(1j * phase)


def dirac_snapshot(q, *, phase=0.0, order=(0, 1, 2)):
    qx, qy = q
    radius = np.sqrt(qx * qx + qy * qy + .7 * .7)
    lower = dirac_lower_frame(q, phase=phase)
    upper = np.array([
        np.exp(1j * np.arctan2(qy, qx)) * np.cos(np.arccos(.7 / radius) / 2.0),
        np.sin(np.arccos(.7 / radius) / 2.0),
        0.0,
    ], dtype=complex)
    fields = np.zeros((3, 1, 1, 3), complex)
    fields[0, 0, 0] = lower
    fields[1, 0, 0] = upper
    fields[2, 0, 0, 2] = 1.0
    frequencies = np.array((-radius, radius, 10.0))
    return snapshot(q, frequencies[list(order)], fields[list(order)])


def dirac_e7d(*, phases=None, order=(0, 1, 2), reverse=False):
    center = np.array((.31, .27))
    levels = []
    selections = []
    for level, h in enumerate((.08, .04, .02)):
        points = [
            center + np.array(offset) * h
            for offset in ((-1,-1),(1,-1),(1,1),(-1,1),(0,0))
        ]
        phase_values = phases[level] if phases is not None else (0.0,) * 5
        levels.append(tuple(
            dirac_snapshot(point, phase=phase_values[index], order=order)
            for index, point in enumerate(points)
        ))
        selected_index = order.index(0)
        selections.append(((selected_index,),) * 5)
    if reverse:
        levels = tuple(tuple(level[index] for index in (3,2,1,0,4)) for level in levels)
        selections = tuple(tuple(selection[index] for index in (3,2,1,0,4)) for selection in selections)
    source = qualify_mpb_plaquette(
        tuple(levels), tuple(selections), (.08, .04, .02),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    assert source.status == PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED
    return compose_mpb_plaquette_holonomy(source, require_live=False)


def test_analytic_dirac_sign_and_refinement_error_decrease():
    result = estimate_mpb_rank1_berry_curvature(dirac_e7d(), require_live=False)
    expected = -.7 / (2.0 * (.7 * .7 + .31 * .31 + .27 * .27) ** 1.5)
    errors = [abs(value - expected) for value in result.estimates]
    assert result.is_qualified
    assert result.is_live_qualified is False
    assert errors[-1] < errors[0]
    assert abs(result.estimates[-1] - expected) < 2e-3


def test_orientation_reversal_reverses_phase_and_area_but_preserves_estimate():
    forward = estimate_mpb_rank1_berry_curvature(dirac_e7d(), require_live=False)
    reverse_result = estimate_mpb_rank1_berry_curvature(dirac_e7d(reverse=True), require_live=False)
    for left, right in zip(forward.levels, reverse_result.levels):
        assert right.signed_area == pytest.approx(-left.signed_area)
        assert right.wilson_phase == pytest.approx(-left.wilson_phase)
        assert right.curvature_estimate == pytest.approx(left.curvature_estimate)


def test_independent_u1_vertex_phases_preserve_estimates():
    rng = np.random.default_rng(20260819)
    phases = tuple(tuple(rng.uniform(-np.pi, np.pi) for _ in range(5)) for _ in range(3))
    base = estimate_mpb_rank1_berry_curvature(dirac_e7d(), require_live=False)
    gauged = estimate_mpb_rank1_berry_curvature(dirac_e7d(phases=phases), require_live=False)
    assert np.allclose(base.estimates, gauged.estimates, atol=1e-10)


def test_solver_order_permutation_preserves_estimates():
    base = estimate_mpb_rank1_berry_curvature(dirac_e7d(), require_live=False)
    permuted = estimate_mpb_rank1_berry_curvature(
        dirac_e7d(order=(1, 0, 2)), require_live=False
    )
    assert np.allclose(base.estimates, permuted.estimates, atol=1e-10)


def test_live_mpb_estimates_are_finite_at_all_three_levels():
    result = estimate_mpb_rank1_berry_curvature(live_e7d())
    assert result.is_qualified and result.is_live_qualified
    assert all(np.isfinite(value) for value in result.estimates)


def test_live_phase_callback_preserves_estimates():
    base = estimate_mpb_rank1_berry_curvature(live_e7d())
    phased = estimate_mpb_rank1_berry_curvature(live_e7d(mpb.fix_hfield_phase))
    assert np.allclose(base.estimates, phased.estimates, atol=LIVE_ESTIMATE_TOLERANCE)


def test_live_orientation_reversal_preserves_curvature():
    levels, selections = live_levels()
    source = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C,
    )
    reverse_levels = tuple(tuple(level[i] for i in (3,2,1,0,4)) for level in levels)
    reverse_selections = tuple(tuple(sel[i] for i in (3,2,1,0,4)) for sel in selections)
    reverse_source = qualify_mpb_plaquette(
        reverse_levels, reverse_selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C,
    )
    forward = estimate_mpb_rank1_berry_curvature(compose_mpb_plaquette_holonomy(source))
    reverse_result = estimate_mpb_rank1_berry_curvature(compose_mpb_plaquette_holonomy(reverse_source))
    assert np.allclose(forward.estimates, reverse_result.estimates, atol=LIVE_ESTIMATE_TOLERANCE)


def test_symmetry_zero_is_only_a_diagnostic():
    result = estimate_mpb_rank1_berry_curvature(live_e7d())
    assert np.isfinite(result.estimates[-1])
    assert "observable-convergence" not in json.dumps(result.to_dict()).lower()


def test_fail_closed_rank_live_and_unqualified_inputs():
    with pytest.raises(ValueError, match="live"):
        estimate_mpb_rank1_berry_curvature(e7d_static())
    rank_two = estimate_mpb_rank1_berry_curvature(e7d_static(rank=2), require_live=False)
    assert all(item is None for item in rank_two.estimates)
    assert all(status == "BERRY_UNSUPPORTED_RANK" for status in rank_two.status)
    unqualified = replace(
        e7d_static().source_result,
        refinement_result=replace(
            e7d_static().source_result.refinement_result,
            status="PLAQUETTE_REFINEMENT_UNQUALIFIED",
        ),
    )
    bad_source = estimate_mpb_rank1_berry_curvature(
        compose_mpb_plaquette_holonomy(unqualified, require_live=False),
        require_live=False,
    )
    assert not bad_source.is_qualified
    assert all(value is None for value in bad_source.estimates)


def test_branch_zero_area_mixed_orientation_and_serialization_guards():
    base = e7d_static()
    branch_wilson = replace(
        base.wilson_results[0], determinant_phase=np.pi - 1e-8
    )
    branch_source = replace(
        base, wilson_results=(branch_wilson,) + base.wilson_results[1:]
    )
    branch = estimate_mpb_rank1_berry_curvature(
        branch_source, require_live=False, branch_safety_margin=1e-6
    )
    assert branch.status[0] == "BERRY_PHASE_BRANCH_AMBIGUOUS"
    assert branch.estimates[0] is None

    zero_vertices = tuple(replace(vertex, k_point=(0.0, 0.0)) for vertex in base.source_result.boundary_results[0].vertices)
    zero_boundary = replace(base.source_result.boundary_results[0], vertices=zero_vertices)
    zero_source = replace(
        base.source_result,
        boundary_results=(zero_boundary,) + base.source_result.boundary_results[1:],
    )
    zero_path = replace(base.path_results[0], vertices=zero_vertices)
    zero_holonomy = replace(base, source_result=zero_source, path_results=(zero_path,) + base.path_results[1:])
    zero = estimate_mpb_rank1_berry_curvature(zero_holonomy, require_live=False)
    assert zero.status[0] == "BERRY_ZERO_AREA"
    assert zero.estimates[0] is None

    mixed_vertices = tuple(reversed(base.source_result.boundary_results[1].vertices))
    mixed_boundary = replace(base.source_result.boundary_results[1], vertices=mixed_vertices)
    mixed_source = replace(
        base.source_result,
        boundary_results=(base.source_result.boundary_results[0], mixed_boundary) + base.source_result.boundary_results[2:],
    )
    mixed_path = replace(base.path_results[1], vertices=mixed_vertices)
    mixed_holonomy = replace(base, source_result=mixed_source, path_results=(base.path_results[0], mixed_path) + base.path_results[2:])
    mixed = estimate_mpb_rank1_berry_curvature(mixed_holonomy, require_live=False)
    assert "BERRY_MIXED_ORIENTATION" in mixed.status

    encoded = json.dumps(base.to_dict()).lower()
    for forbidden in ("observable-convergence", "chern", "matrix logarithm", "local non-abelian curvature", "production-authorization", "global map"):
        assert forbidden not in encoded
