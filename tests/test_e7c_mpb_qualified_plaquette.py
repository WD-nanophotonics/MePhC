import json
from dataclasses import replace
import numpy as np
import pytest
import meep as mp
import meep.mpb as mpb
from mephc.mpb_spectral import adapt_mpb_h_envelopes
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.plaquette_domain import (PlaquetteRefinementThresholds, PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED, PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED)

E3=SubspaceQualificationThresholds(.9,.45,.3,.05)
E4C=PlaquetteRefinementThresholds(.9,.45,.3,.1)
def static(k,bands=2):
 f=np.zeros((bands,1,1,3),complex); f[0,0,0,0]=1
 if bands>1:f[1,0,0,1]=1
 if bands>2:f[2,0,0,2]=1
 return adapt_mpb_h_envelopes(k,tuple(range(0,5*bands,5)),f)
def static_levels(bands=2):
 out=[]; sels=[]
 for h in (.02,.01,.005):
  out.append(tuple(static(k,bands) for k in ((.1-h,.2-h),(.1+h,.2-h),(.1+h,.2+h),(.1-h,.2+h),(.1,.2))))
  sels.append(((0,),)*5 if bands==2 else ((0,1),)*5)
 return tuple(out),tuple(sels)
def test_static_rank_one_and_json():
 l,s=static_levels()
 r=qualify_mpb_plaquette(l,s,(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C,require_live=False)
 assert r.status==PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED and not r.is_live_qualified
 assert "berry" not in json.dumps(r.to_dict()).lower()
def test_static_rank_two():
 l,s=static_levels(3)
 r=qualify_mpb_plaquette(l,s,(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C,require_live=False)
 assert r.status!="PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED"
def test_invalid_geometry_and_live_guard():
 l,s=static_levels()
 with pytest.raises(ValueError): qualify_mpb_plaquette(l,s,(.02,.02,.005),thresholds=E3,refinement_thresholds=E4C,require_live=False)
 with pytest.raises(ValueError,match="live"): qualify_mpb_plaquette(l,s,(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C)
def test_live_three_level_generic_center():
 lat=mp.Lattice(size=mp.Vector3(1,1)); geo=[mp.Cylinder(.2,material=mp.Medium(epsilon=12))]
 p=MPBLiveSpectralProvider(geometry=geo,geometry_lattice=lat,resolution=6,num_bands=2,polarization=mp.TE,default_material=mp.air,eigensolver_tolerance=1e-7,deterministic=True,mesh_size=3,orthogonality_tolerance=1e-8)
 levels=[]; sels=[]
 for h in (.02,.01,.005):
  pts=((.17-h,.23-h),(.17+h,.23-h),(.17+h,.23+h),(.17-h,.23+h),(.17,.23))
  levels.append(tuple(p.solve(x) for x in pts)); sels.append(((0,),)*5)
 r=qualify_mpb_plaquette(tuple(levels),tuple(sels),(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C)
 assert r.status==PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED and r.is_live_qualified


def custom_snapshot(k, frequencies, *, spatial_shape=(1, 1)):
    bands = len(frequencies)
    fields = np.zeros((bands, spatial_shape[0], spatial_shape[1], 3), complex)
    for index in range(min(bands, 3)):
        fields[index, 0, 0, index] = 1
    return adapt_mpb_h_envelopes(k, tuple(frequencies), fields)


def static_levels_with_center_external(center_external, *, bands=2):
    levels = []
    selections = []
    for h in (.02, .01, .005):
        corners = tuple(
            custom_snapshot(k, tuple(0.0 if i == 0 else 1.0 + i for i in range(bands)))
            for i, k in enumerate(((.1-h,.2-h),(.1+h,.2-h),(.1+h,.2+h),(.1-h,.2+h)))
        )
        center = custom_snapshot((.1, .2), tuple(0.0 if i == 0 else (center_external if i == 1 else 1.0 + i) for i in range(bands)))
        levels.append(corners + (center,))
        selections.append(((0,),) * 5 if bands == 2 else ((0, 1),) * 5)
    return tuple(levels), tuple(selections)


def test_rank_two_and_context_evidence_are_exact_and_immutable():
    levels, selections = static_levels(bands=3)
    result = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    assert result.status == PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED
    assert result.boundary_contexts[0] == result.boundary_results[0].external_contexts
    assert result.spoke_contexts[0][0].left_excluded_eigenvalues == (10.0,)
    assert result.spoke_contexts[0][0].right_excluded_eigenvalues == (10.0,)
    assert result.to_dict()["boundary_contexts"][0][0]["left_excluded_eigenvalues"]
    assert result.snapshots[0][0].frequencies.flags.writeable is False
    assert result.snapshots[0][0].h_fields.flags.writeable is False


def test_rank_one_spoke_isolation_loss_requires_subspace():
    levels, selections = static_levels_with_center_external(.01)
    result = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    assert result.status == PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED


def test_cross_snapshot_layout_and_selection_rank_mismatch_fail_closed():
    levels, selections = static_levels()
    mismatched = list(levels)
    mismatched[1] = tuple(
        custom_snapshot(snapshot.k_point, snapshot.frequencies, spatial_shape=(1, 2))
        for snapshot in mismatched[1]
    )
    with pytest.raises(ValueError, match="layout mismatch"):
        qualify_mpb_plaquette(
            tuple(mismatched), selections, (.02, .01, .005),
            thresholds=E3, refinement_thresholds=E4C, require_live=False,
        )
    bad_selections = list(selections)
    bad_selections[0] = ((0,), (0,), (0, 1), (0,), (0,))
    with pytest.raises(ValueError, match="selection rank mismatch"):
        qualify_mpb_plaquette(
            levels, tuple(bad_selections), (.02, .01, .005),
            thresholds=E3, refinement_thresholds=E4C, require_live=False,
        )


def test_representation_mismatch_fail_closed():
    levels, selections = static_levels()
    changed = list(levels)
    snapshot = changed[1][0]
    changed[1] = (
        replace(snapshot, provenance={**dict(snapshot.provenance), "representation": "other"}),
    ) + changed[1][1:]
    with pytest.raises(ValueError, match="layout mismatch"):
        qualify_mpb_plaquette(
            tuple(changed), selections, (.02, .01, .005),
            thresholds=E3, refinement_thresholds=E4C, require_live=False,
        )


def test_solver_order_permutation_preserves_projector_decisions():
    levels, selections = static_levels()
    permuted_levels = tuple(
        tuple(
            adapt_mpb_h_envelopes(
                snapshot.k_point,
                tuple(snapshot.frequencies[::-1]),
                snapshot.h_fields[::-1],
            )
            for snapshot in level
        )
        for level in levels
    )
    permuted_selections = tuple(tuple((1,) for _ in level) for level in permuted_levels)
    base = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    permuted = qualify_mpb_plaquette(
        permuted_levels, permuted_selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    assert base.status == permuted.status
    assert [x.status for x in base.boundary_results] == [x.status for x in permuted.boundary_results]
    assert [x.status for x in base.interior_results] == [x.status for x in permuted.interior_results]
    assert base.refinement_result.to_dict()["metrics"] == permuted.refinement_result.to_dict()["metrics"]


def test_live_phase_callback_preserves_all_e7c_decisions_and_diagnostics():
    def make_levels(phase_callback=None):
        provider = MPBLiveSpectralProvider(
            geometry=[mp.Cylinder(.2, material=mp.Medium(epsilon=12))],
            geometry_lattice=mp.Lattice(size=mp.Vector3(1, 1)),
            resolution=6, num_bands=2, polarization=mp.TE,
            default_material=mp.air, eigensolver_tolerance=1e-7,
            deterministic=True, mesh_size=3, phase_callback=phase_callback,
        )
        out = []
        for h in (.02, .01, .005):
            points = ((.17-h,.23-h),(.17+h,.23-h),(.17+h,.23+h),(.17-h,.23+h),(.17,.23))
            out.append(tuple(provider.solve(point) for point in points))
        return tuple(out), (((0,),) * 5,) * 3
    base_levels, base_selections = make_levels()
    phased_levels, phased_selections = make_levels(mpb.fix_hfield_phase)
    base = qualify_mpb_plaquette(
        base_levels, base_selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C,
    )
    phased = qualify_mpb_plaquette(
        phased_levels, phased_selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C,
    )
    assert base.status == phased.status
    assert [x.status for x in base.boundary_results] == [x.status for x in phased.boundary_results]
    assert [x.status for x in base.interior_results] == [x.status for x in phased.interior_results]
    for left, right in zip(base.refinement_result.metrics, phased.refinement_result.metrics):
        assert np.isclose(left.minimum_singular_value, right.minimum_singular_value, atol=1e-6)
        assert np.isclose(left.maximum_principal_angle, right.maximum_principal_angle, atol=1e-6)
        assert np.isclose(left.maximum_projector_distance, right.maximum_projector_distance, atol=1e-6)


def test_nonhomothetic_geometry_and_nonorthogonal_snapshot_fail_closed():
    levels, selections = static_levels()
    altered = list(levels)
    points = ((.091, .19), (.11, .19), (.109, .21), (.09, .21), (.1, .2))
    altered[1] = tuple(
        custom_snapshot(point, snapshot.frequencies)
        for point, snapshot in zip(points, altered[1])
    )
    with pytest.raises(ValueError, match="homothetic"):
        qualify_mpb_plaquette(
            tuple(altered), selections, (.02, .01, .005),
            thresholds=E3, refinement_thresholds=E4C, require_live=False,
        )
    fields = np.zeros((2, 1, 1, 3), complex)
    fields[:, 0, 0, 0] = 1
    bad = adapt_mpb_h_envelopes((.1, .2), (0.0, 1.0), fields)
    bad_levels = tuple((bad,) * 5 for _ in (.02, .01, .005))
    with pytest.raises(ValueError, match="non-qualified snapshot"):
        qualify_mpb_plaquette(
            bad_levels, selections, (.02, .01, .005),
            thresholds=E3, refinement_thresholds=E4C, require_live=False,
        )


def test_serialization_contains_only_e7c_domain_claims():
    levels, selections = static_levels()
    result = qualify_mpb_plaquette(
        levels, selections, (.02, .01, .005),
        thresholds=E3, refinement_thresholds=E4C, require_live=False,
    )
    serialized = json.dumps(result.to_dict()).lower()
    for forbidden in (
        "berry", "wilson", "chern", "curvature", "matrix-logarithm",
        "observable-convergence", "production-authorization",
        "physical_band_id", "branch_id", "adiabatic_band_id",
    ):
        assert forbidden not in serialized
