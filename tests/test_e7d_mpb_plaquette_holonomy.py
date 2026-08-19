import json
from dataclasses import replace

import meep as mp
import meep.mpb as mpb
import numpy as np
import pytest

from mephc.mpb_spectral import adapt_mpb_h_envelopes
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED
from mephc.plaquette_domain import (
    PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED,
    PLAQUETTE_REFINEMENT_INCOMPLETE,
    PLAQUETTE_REFINEMENT_UNQUALIFIED,
    PLAQUETTE_REFINEMENT_RANK_UNSTABLE,
    PlaquetteRefinementThresholds,
)
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.wilson_geometry import WILSON_INPUT_UNQUALIFIED, WILSON_LOOP_QUALIFIED, compose_wilson_transport

E3 = SubspaceQualificationThresholds(.9, .45, .3, .05)
E4C = PlaquetteRefinementThresholds(.9, .45, .3, .1)


def snapshot(k, frequencies, *, vectors=None):
    bands = len(frequencies)
    fields = np.zeros((bands, 1, 1, 3), complex)
    if vectors is None:
        for i in range(min(bands, 3)):
            fields[i, 0, 0, i] = 1
    else:
        fields[:] = vectors
    return adapt_mpb_h_envelopes(k, tuple(frequencies), fields)


def static_levels(*, rank=1, center_external=None):
    levels = []
    selections = []
    for h in (.02, .01, .005):
        corners = tuple(
            snapshot(k, (0.0, 1.0) if rank == 1 else (0.0, 5.0, 10.0))
            for k in ((.1-h,.2-h),(.1+h,.2-h),(.1+h,.2+h),(.1-h,.2+h))
        )
        if rank == 1:
            center_frequencies = (0.0, 1.0 if center_external is None else center_external)
            center = snapshot((.1, .2), center_frequencies)
            selection = (0,)
        else:
            center = snapshot((.1, .2), (0.0, 5.0, 10.0))
            selection = (0, 1)
        levels.append(corners + (center,))
        selections.append((selection,) * 5)
    return tuple(levels), tuple(selections)


def e7c_static(*, rank=1, center_external=None):
    levels, selections = static_levels(rank=rank, center_external=center_external)
    return qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )


def test_static_e7d_reuses_exact_e4a_evidence_and_e5a_result():
    source = e7c_static()
    result = compose_mpb_plaquette_holonomy(source, require_live=False)
    assert source.status == PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED
    assert result.status == (WILSON_LOOP_QUALIFIED,) * 3
    assert result.path_results[0].vertices is source.boundary_results[0].vertices
    assert result.path_results[0].edge_results is source.boundary_results[0].edge_results
    assert result.path_results[0].external_contexts is source.boundary_results[0].external_contexts
    for path, wilson in zip(result.path_results, result.wilson_results):
        direct = compose_wilson_transport(path)
        assert wilson is not direct
        assert wilson.status == direct.status
        assert np.allclose(wilson.product, direct.product)
        assert np.isclose(wilson.determinant_phase, direct.determinant_phase)


def test_unqualified_e7c_exposes_no_wilson_products():
    source = e7c_static(center_external=.01)
    assert source.status == PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED
    result = compose_mpb_plaquette_holonomy(source, require_live=False)
    assert all(wilson.status == WILSON_INPUT_UNQUALIFIED for wilson in result.wilson_results)
    assert all(wilson.product is None for wilson in result.wilson_results)
    assert result.is_qualified is False


def test_live_gate_and_static_result_never_live_qualified():
    source = e7c_static()
    with pytest.raises(ValueError, match="live"):
        compose_mpb_plaquette_holonomy(source)
    result = compose_mpb_plaquette_holonomy(source, require_live=False)
    assert result.is_live_qualified is False


def test_reverse_and_cyclic_corner_adapters_preserve_closed_loop_invariants():
    levels, selections = static_levels(rank=2)
    forward_source = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    reverse_levels = tuple(tuple(level[index] for index in (3, 2, 1, 0, 4)) for level in levels)
    reverse_selections = tuple(tuple(selection[index] for index in (3, 2, 1, 0, 4)) for selection in selections)
    cyclic_levels = tuple(tuple(level[index] for index in (1, 2, 3, 0, 4)) for level in levels)
    cyclic_selections = tuple(tuple(selection[index] for index in (1, 2, 3, 0, 4)) for selection in selections)
    reverse = compose_mpb_plaquette_holonomy(
        qualify_mpb_plaquette(reverse_levels, reverse_selections, (.02, .01, .005), thresholds=E3, refinement_thresholds=E4C, require_live=False),
        require_live=False,
    )
    cyclic = compose_mpb_plaquette_holonomy(
        qualify_mpb_plaquette(cyclic_levels, cyclic_selections, (.02, .01, .005), thresholds=E3, refinement_thresholds=E4C, require_live=False),
        require_live=False,
    )
    forward = compose_mpb_plaquette_holonomy(forward_source, require_live=False)
    for fwd, rev, cyc in zip(forward.wilson_results, reverse.wilson_results, cyclic.wilson_results):
        assert np.allclose(rev.product, fwd.product.conj().T)
        assert np.allclose(np.sort_complex(cyc.eigenvalues), np.sort_complex(fwd.eigenvalues))
        assert np.isclose(cyc.trace, fwd.trace)
        assert np.isclose(cyc.determinant, fwd.determinant)


def test_rank_two_static_gauge_and_serialization_guard():
    source = e7c_static(rank=2)
    result = compose_mpb_plaquette_holonomy(source, require_live=False)
    assert result.is_qualified
    assert result.rank if hasattr(result, "rank") else True
    serialized = json.dumps(result.to_dict()).lower()
    for forbidden in ("berry curvature", "phase-over-area", "chern", "matrix logarithm", "local non-abelian curvature", "observable-convergence", "production-authorization", "physical_band_id", "branch_id", "adiabatic_band_id"):
        assert forbidden not in serialized
    assert result.wilson_results[0].product.flags.writeable is False


def test_live_three_level_holonomy_and_phase_callback_invariance():
    def make_levels(phase_callback=None):
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
        selections = (((0,),) * 5,) * 3
        return tuple(levels), selections

    base_levels, selections = make_levels()
    phased_levels, phased_selections = make_levels(mpb.fix_hfield_phase)
    base_source = qualify_mpb_plaquette(base_levels, selections, (.02, .01, .005), thresholds=E3, refinement_thresholds=E4C)
    phased_source = qualify_mpb_plaquette(phased_levels, phased_selections, (.02, .01, .005), thresholds=E3, refinement_thresholds=E4C)
    base = compose_mpb_plaquette_holonomy(base_source)
    phased = compose_mpb_plaquette_holonomy(phased_source)
    assert all(status == WILSON_LOOP_QUALIFIED for status in base.status)
    for left, right in zip(base.wilson_results, phased.wilson_results):
        assert np.allclose(np.sort_complex(left.eigenvalues), np.sort_complex(right.eigenvalues), atol=1e-6)
        assert np.isclose(left.trace, right.trace, atol=1e-6)
        assert np.isclose(left.determinant, right.determinant, atol=1e-6)
        assert np.isclose(left.determinant_phase, right.determinant_phase, atol=1e-6)


def test_solver_order_permutation_preserves_e7d_invariants():
    levels, selections = static_levels(rank=2)
    permuted_levels = tuple(
        tuple(
            adapt_mpb_h_envelopes(snapshot_value.k_point, tuple(snapshot_value.frequencies[::-1]), snapshot_value.h_fields[::-1])
            for snapshot_value in level
        )
        for level in levels
    )
    permuted_selections = tuple(tuple((1, 0) for _ in level) for level in permuted_levels)
    base = compose_mpb_plaquette_holonomy(
        qualify_mpb_plaquette(levels, selections, (.02, .01, .005), thresholds=E3, refinement_thresholds=E4C, require_live=False),
        require_live=False,
    )
    permuted = compose_mpb_plaquette_holonomy(
        qualify_mpb_plaquette(permuted_levels, permuted_selections, (.02, .01, .005), thresholds=E3, refinement_thresholds=E4C, require_live=False),
        require_live=False,
    )
    for left, right in zip(base.wilson_results, permuted.wilson_results):
        assert left.status == right.status == WILSON_LOOP_QUALIFIED
        assert np.allclose(np.sort_complex(left.eigenvalues), np.sort_complex(right.eigenvalues))
        assert np.isclose(left.trace, right.trace)
        assert np.isclose(left.determinant, right.determinant)


def test_all_nonqualified_e7c_statuses_expose_no_products():
    source = e7c_static()
    for status in (
        PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED,
        PLAQUETTE_REFINEMENT_INCOMPLETE,
        PLAQUETTE_REFINEMENT_UNQUALIFIED,
        PLAQUETTE_REFINEMENT_RANK_UNSTABLE,
    ):
        altered = replace(source, refinement_result=replace(source.refinement_result, status=status))
        result = compose_mpb_plaquette_holonomy(altered, require_live=False)
        assert all(item.product is None for item in result.wilson_results)
        assert result.is_qualified is False
