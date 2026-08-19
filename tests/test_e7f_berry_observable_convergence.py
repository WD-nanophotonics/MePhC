"""Controlled E7F convergence-certificate tests."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path

import meep as mp
import meep.mpb as mpb
import numpy as np
import pytest

from mephc.berry_convergence import BerryObservableThresholds
from mephc.convergence import (
    EigenmodeConvergenceProvenance,
    EigenmodeConvergenceThresholds,
    EigenmodePairEvidence,
    certify_eigenmode_convergence,
)
from mephc.mpb_berry_estimator import estimate_mpb_rank1_berry_curvature
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_spectral import adapt_mpb_h_envelopes
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.plaquette_domain import PlaquetteRefinementThresholds
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.berry_observable_e7f import (
    E7FBerryObservableSample,
    certify_e7e_berry_observable_convergence,
)


_E7E_PATH = Path(__file__).with_name("test_e7e_mpb_berry_estimator.py")
_SPEC = importlib.util.spec_from_file_location("e7e_fixture_module", _E7E_PATH)
_E7E = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_E7E)

E3 = SubspaceQualificationThresholds(.9, .45, .3, .05)
E4C = PlaquetteRefinementThresholds(.9, .45, .3, .1)


def _relocate(result, center):
    center = np.asarray(center, dtype=float)
    levels = []
    boundaries = []
    paths = []
    old_center = np.mean(
        np.asarray([v.k_point for v in result.levels[0].boundary_vertices]), axis=0
    )
    for level, path, boundary in zip(
        result.levels, result.source_result.path_results,
        result.source_result.source_result.boundary_results,
    ):
        vertices = tuple(
            replace(vertex, k_point=tuple(center + (np.asarray(vertex.k_point) - old_center)))
            for vertex in level.boundary_vertices
        )
        boundaries.append(replace(boundary, vertices=vertices))
        paths.append(replace(path, vertices=vertices))
        levels.append(replace(
            level, boundary_vertices=vertices,
            boundary_result=boundaries[-1], path_result=paths[-1],
        ))
    e7c = replace(result.source_result.source_result, boundary_results=tuple(boundaries))
    e7d = replace(result.source_result, source_result=e7c, path_results=tuple(paths))
    return replace(result, source_result=e7d, levels=tuple(levels))


def _tune(result, values):
    levels = tuple(
        replace(level, curvature_estimate=float(value))
        for level, value in zip(result.levels, values)
    )
    return replace(result, levels=levels)


def _eigenmode_certificate(resolution, *, backend="fixture", digest="e7f"):
    provenance = EigenmodeConvergenceProvenance(
        backend=backend, geometry_digest=digest, target_band=0, num_bands=2,
        polarization="TE", deterministic=True, eigensolver_tolerance=1e-7,
        mesh_size=3, field_representation="periodic_h_bloch_envelope",
    )
    evidence = tuple(
        EigenmodePairEvidence(
            lower_resolution=resolution - 2 + index,
            upper_resolution=resolution - 1 + index,
            max_abs_frequency_change=1e-7,
            min_h_fidelity=.999999,
            max_h_relative_l2_residual=1e-4,
            min_isolation_gap=.1,
        )
        for index in (0, 1)
    )
    return certify_eigenmode_convergence(
        evidence, provenance=provenance,
        thresholds=EigenmodeConvergenceThresholds(
            max_abs_frequency_change=1e-5, min_h_fidelity=.99,
            max_h_relative_l2_residual=.01, min_isolation_gap=1e-8,
            required_tail_pairs=2,
        ),
    )


def _sample(plus, tr, *, resolution, level, cert=True, provenance=None):
    plus = _tune(plus, (.1, .10001, .100011))
    tr = _tune(tr, (-.1, -.10001, -.100011))
    return E7FBerryObservableSample(
        plus_result=plus, tr_result=tr, selected_level=level,
        resolution=resolution, step=plus.levels[level].step,
        eigenmode_plus=None if not cert else _eigenmode_certificate(resolution),
        eigenmode_tr=None if not cert else _eigenmode_certificate(resolution),
        provenance={} if provenance is None else provenance,
    )


def _thresholds():
    return BerryObservableThresholds(
        max_resolution_abs_change=.01, max_resolution_relative_change=0.0,
        max_step_abs_change=.01, max_step_relative_change=0.0,
        max_trs_abs_residual=1e-8, max_trs_relative_residual=0.0,
        required_resolution_tail_pairs=2, required_step_tail_pairs=2,
    )


def _static_ladders():
    base = estimate_mpb_rank1_berry_curvature(_E7E.e7d_static(), require_live=False)
    plus = _relocate(base, (.2, .3))
    tr = _relocate(base, (-.2, -.3))
    resolution = tuple(_sample(plus, tr, resolution=res, level=2, provenance={"fixture": "e7f"}) for res in (3, 4, 5))
    step = tuple(_sample(plus, tr, resolution=5, level=level, provenance={"fixture": "e7f"}) for level in (0, 1, 2))
    return resolution, step


def test_e7f_static_certificate_passes_but_is_not_live_qualified():
    resolution, step = _static_ladders()
    certificate = certify_e7e_berry_observable_convergence(
        resolution, step, thresholds=_thresholds(), require_live=False,
    )
    assert certificate.status == "PASS"
    assert certificate.is_live_qualified is False
    assert certificate.qualified_resolution == 5
    assert certificate.qualified_step == .005
    assert certificate.to_dict()["e7e_scope"]


@pytest.mark.parametrize("kind", ["resolution", "step", "trs"])
def test_e7f_numeric_gates_fail_closed(kind):
    resolution, step = _static_ladders()
    if kind == "resolution":
        resolution = tuple(replace(x, plus_result=_tune(x.plus_result, (.1, .2, .3))) for x in resolution)
    elif kind == "step":
        step = tuple(replace(x, plus_result=_tune(x.plus_result, (.1, .2, .3))) for x in step)
    else:
        step = tuple(replace(x, tr_result=_tune(x.tr_result, (-.1, -.1, -.1))) for x in step)
    certificate = certify_e7e_berry_observable_convergence(
        resolution, step, thresholds=_thresholds(), require_live=False,
    )
    assert certificate.status == "FAIL"


def test_e7f_missing_tail_or_solver_evidence_is_incomplete():
    resolution, step = _static_ladders()
    short = certify_e7e_berry_observable_convergence(
        resolution[:1], step[:1], thresholds=_thresholds(), require_live=False,
    )
    assert short.status == "INCOMPLETE"
    missing = tuple(replace(x, eigenmode_plus=None) for x in resolution)
    incomplete = certify_e7e_berry_observable_convergence(
        missing, step, thresholds=_thresholds(), require_live=False,
    )
    assert incomplete.status == "INCOMPLETE"


def test_e7f_center_orientation_and_provenance_are_fail_closed():
    resolution, step = _static_ladders()
    wrong_tr = _relocate(resolution[0].tr_result, (-.2, -.29))
    altered = replace(resolution[0], tr_result=wrong_tr)
    failed = certify_e7e_berry_observable_convergence(
        (altered,) + resolution[1:], step, thresholds=_thresholds(), require_live=False,
    )
    assert failed.status == "FAIL"
    mixed = replace(resolution[1], provenance={"fixture": "other"})
    failed = certify_e7e_berry_observable_convergence(
        (resolution[0], mixed, resolution[2]), step, thresholds=_thresholds(), require_live=False,
    )
    assert failed.status == "FAIL"


def _live_e7d(center):
    provider = MPBLiveSpectralProvider(
        geometry=[mp.Cylinder(.2, material=mp.Medium(epsilon=12))],
        geometry_lattice=mp.Lattice(size=mp.Vector3(1, 1)), resolution=6,
        num_bands=2, polarization=mp.TE, default_material=mp.air,
        eigensolver_tolerance=1e-7, deterministic=True, mesh_size=3,
    )
    levels = []
    for h in (.02, .01, .005):
        points = ((center[0]-h, center[1]-h), (center[0]+h, center[1]-h),
                  (center[0]+h, center[1]+h), (center[0]-h, center[1]+h), center)
        levels.append(tuple(provider.solve(point) for point in points))
    selections = (((0,),) * 5,) * 3
    source = qualify_mpb_plaquette(
        tuple(levels), selections, (.02, .01, .005), thresholds=E3,
        refinement_thresholds=E4C,
    )
    return compose_mpb_plaquette_holonomy(source)


def test_e7f_live_tr_smoke_remains_incomplete_until_resolution_tail_exists():
    plus = estimate_mpb_rank1_berry_curvature(_live_e7d((.17, .23)))
    tr = estimate_mpb_rank1_berry_curvature(_live_e7d((-.17, -.23)))
    samples = tuple(
        E7FBerryObservableSample(
            plus_result=plus, tr_result=tr, selected_level=level,
            resolution=6, step=plus.levels[level].step,
            eigenmode_plus=_eigenmode_certificate(6, backend="mpb", digest="live"),
            eigenmode_tr=_eigenmode_certificate(6, backend="mpb", digest="live"),
            provenance={"backend": "mpb", "center": [.17, .23]},
        )
        for level in (0, 1, 2)
    )
    certificate = certify_e7e_berry_observable_convergence(
        samples[:1], samples, thresholds=BerryObservableThresholds(
            max_resolution_abs_change=.01, max_resolution_relative_change=0.0,
            max_step_abs_change=.01, max_step_relative_change=0.0,
            max_trs_abs_residual=.01, max_trs_relative_residual=0.0,
            required_resolution_tail_pairs=2, required_step_tail_pairs=2,
        ),
    )
    assert plus.is_live_qualified and tr.is_live_qualified
    assert np.isfinite(samples[-1].omega_plus)
    assert np.isfinite(samples[-1].omega_tr)
    assert certificate.status == "INCOMPLETE"
