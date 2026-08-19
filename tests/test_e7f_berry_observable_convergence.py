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
    if all(level.status == "BERRY_ESTIMATE_QUALIFIED" for level in plus.levels):
        plus = _tune(plus, (.1, .10001, .100011))
    if all(level.status == "BERRY_ESTIMATE_QUALIFIED" for level in tr.levels):
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


def _live_e7d(center, phase_callback=None):
    provider = MPBLiveSpectralProvider(
        geometry=[mp.Cylinder(.2, material=mp.Medium(epsilon=12))],
        geometry_lattice=mp.Lattice(size=mp.Vector3(1, 1)), resolution=6,
        num_bands=2, polarization=mp.TE, default_material=mp.air,
        eigensolver_tolerance=1e-7, deterministic=True, mesh_size=3,
        phase_callback=phase_callback,
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

def _transform(result, center, transform):
    center = np.asarray(center, dtype=float)
    old_center = np.mean(
        np.asarray([v.k_point for v in result.levels[0].boundary_vertices]), axis=0
    )
    levels, boundaries, paths = [], [], []
    for level, path, boundary in zip(
        result.levels, result.source_result.path_results,
        result.source_result.source_result.boundary_results,
    ):
        vertices = tuple(
            replace(
                vertex,
                k_point=tuple(center + transform(np.asarray(vertex.k_point) - old_center)),
            )
            for vertex in level.boundary_vertices
        )
        boundaries.append(replace(boundary, vertices=vertices))
        paths.append(replace(path, vertices=vertices))
        levels.append(replace(level, boundary_vertices=vertices,
                              boundary_result=boundaries[-1], path_result=paths[-1]))
    e7c = replace(result.source_result.source_result,
                  boundary_results=tuple(boundaries))
    e7d = replace(result.source_result, source_result=e7c,
                  path_results=tuple(paths))
    return replace(result, source_result=e7d, levels=tuple(levels))


def _live_samples(plus, tr):
    return tuple(
        E7FBerryObservableSample(
            plus_result=plus, tr_result=tr, selected_level=level,
            resolution=6, step=plus.levels[level].step,
            eigenmode_plus=_eigenmode_certificate(6, backend="mpb", digest="live"),
            eigenmode_tr=_eigenmode_certificate(6, backend="mpb", digest="live"),
            provenance={"backend": "mpb", "center": [.17, .23]},
        )
        for level in (0, 1, 2)
    )


def test_e7f_incomplete_e7e_and_nonpass_eigenmode_never_become_fail():
    resolution, step = _static_ladders()
    incomplete_level = replace(
        resolution[0].plus_result.levels[2],
        status="BERRY_INPUT_INCOMPLETE", curvature_estimate=None,
    )
    incomplete_result = replace(
        resolution[0].plus_result,
        levels=resolution[0].plus_result.levels[:2] + (incomplete_level,),
    )
    incomplete = replace(resolution[0], plus_result=incomplete_result)
    assert certify_e7e_berry_observable_convergence(
        (incomplete, *resolution[1:]), step,
        thresholds=_thresholds(), require_live=False,
    ).status == "INCOMPLETE"
    for state in ("FAIL", "INCOMPLETE"):
        nonpass = replace(resolution[0], eigenmode_plus=replace(
            resolution[0].eigenmode_plus, status=state,
        ))
        result = certify_e7e_berry_observable_convergence(
            (nonpass, *resolution[1:]), step,
            thresholds=_thresholds(), require_live=False,
        )
        assert result.status == "INCOMPLETE"


def test_e7f_mixed_incomplete_and_numeric_fail_preserves_both_diagnostics():
    resolution, step = _static_ladders()
    mixed = replace(
        resolution[0],
        plus_result=_tune(resolution[0].plus_result, (.1, .2, .3)),
        eigenmode_plus=None,
    )
    result = certify_e7e_berry_observable_convergence(
        (mixed, *resolution[1:]), step,
        thresholds=_thresholds(), require_live=False,
    )
    assert result.status == "INCOMPLETE"
    assert any(
        check.status == "FAIL" and check.name.startswith("resolution.plus")
        for check in result.checks
    )


def test_e7f_semantic_fail_matrix():
    resolution, step = _static_ladders()
    cases = []
    cases.append(replace(resolution[0], tr_result=_relocate(
        resolution[0].tr_result, (-.2, -.29),
    )))
    cases.append(replace(resolution[0], tr_result=_transform(
        resolution[0].tr_result, (-.2, -.3),
        lambda point: point * np.asarray((1.5, 1.0)),
    )))
    cases.append(replace(resolution[0], tr_result=_transform(
        resolution[0].tr_result, (-.2, -.3),
        lambda point: point[::-1],
    )))
    cases.append(replace(
        resolution[0],
        plus_result=replace(
            resolution[0].plus_result,
            coordinate_convention="wrong",
        ),
    ))
    cases.append(replace(
        resolution[0],
        plus_result=replace(
            resolution[0].plus_result,
            sign_convention="wrong",
        ),
    ))
    rank_two = estimate_mpb_rank1_berry_curvature(
        _E7E.e7d_static(rank=2), require_live=False,
    )
    cases.append(_sample(
        _relocate(rank_two, (.2, .3)),
        _relocate(rank_two, (-.2, -.3)),
        resolution=3, level=2,
    ))
    cases.append(replace(
        resolution[0],
        eigenmode_plus=_eigenmode_certificate(4),
    ))
    cases.append(replace(
        resolution[0],
        eigenmode_plus=_eigenmode_certificate(3, digest="other"),
    ))
    for altered in cases:
        result = certify_e7e_berry_observable_convergence(
            (altered, *resolution[1:]), step,
            thresholds=_thresholds(), require_live=False,
        )
        assert result.status == "FAIL"


def test_e7f_distinct_overlap_identity_and_curvature_guard():
    resolution, step = _static_ladders()
    accepted = certify_e7e_berry_observable_convergence(
        resolution, step, thresholds=_thresholds(), require_live=False,
    )
    assert accepted.status == "PASS"
    altered = replace(
        step[-1],
        plus_result=_tune(step[-1].plus_result, (.1, .2, .3)),
    )
    rejected = certify_e7e_berry_observable_convergence(
        resolution, (step[0], step[1], altered),
        thresholds=_thresholds(), require_live=False,
    )
    assert rejected.status == "FAIL"


def test_e7f_provenance_serialization_is_immutable_and_scoped():
    resolution, step = _static_ladders()
    sample = replace(resolution[0], provenance={"nested": {"values": [1, 2]}})
    with pytest.raises(TypeError):
        sample.provenance["new"] = "blocked"
    with pytest.raises(TypeError):
        sample.provenance["nested"]["values"] = 3
    payload = certify_e7e_berry_observable_convergence(
        (sample, *resolution[1:]), step,
        thresholds=_thresholds(), require_live=False,
    ).to_dict()
    import json
    encoded = json.dumps(payload).lower()
    assert payload["estimator_schema"].startswith("mephc-e7e-native")
    assert "center_tr = -center_plus" in payload["center_pair_semantics"]
    assert payload["authorization_scope"].startswith("e7e_native")
    for forbidden in ("chern", "valley-chern", "bcd", "global-map",
                      "matrix-logarithm", "local non-abelian-curvature",
                      "production-authorization"):
        assert forbidden not in encoded
    assert not sample.plus_result.levels[0].wilson_result.product.flags.writeable


def test_e7f_gauge_and_solver_order_variants_preserve_certificate_status():
    base = estimate_mpb_rank1_berry_curvature(_E7E.dirac_e7d(), require_live=False)
    gauged = estimate_mpb_rank1_berry_curvature(
        _E7E.dirac_e7d(phases=((.2, -.1, .4, -.3, .7),
                                (-.4, .6, -.2, .1, -.5),
                                (.3, .1, -.6, .2, -.8))),
        require_live=False,
    )
    permuted = estimate_mpb_rank1_berry_curvature(
        _E7E.dirac_e7d(order=(1, 0, 2)), require_live=False,
    )
    def certify_variant(result):
        plus = _relocate(result, (.2, .3))
        tr = _relocate(result, (-.2, -.3))
        resolution = tuple(_sample(plus, tr, resolution=x, level=2)
                           for x in (3, 4, 5))
        step = tuple(_sample(plus, tr, resolution=5, level=x)
                     for x in (0, 1, 2))
        return certify_e7e_berry_observable_convergence(
            resolution, step, thresholds=_thresholds(), require_live=False,
        )
    statuses = [certify_variant(item).status
                for item in (base, gauged, permuted)]
    assert statuses == ["PASS", "PASS", "PASS"]


def test_e7f_live_trs_and_phase_callback_invariance():
    plus = estimate_mpb_rank1_berry_curvature(_live_e7d((.17, .23)))
    tr = estimate_mpb_rank1_berry_curvature(_live_e7d((-.17, -.23)))
    plus_phase = estimate_mpb_rank1_berry_curvature(_live_e7d((.17, .23), mpb.fix_hfield_phase))
    tr_phase = estimate_mpb_rank1_berry_curvature(_live_e7d((-.17, -.23), mpb.fix_hfield_phase))
    base_samples = _live_samples(plus, tr)
    phase_samples = _live_samples(plus_phase, tr_phase)
    live_thresholds = BerryObservableThresholds(
        max_resolution_abs_change=.01, max_resolution_relative_change=0.0,
        max_step_abs_change=.01, max_step_relative_change=0.0,
        max_trs_abs_residual=.01, max_trs_relative_residual=0.0,
        required_resolution_tail_pairs=2, required_step_tail_pairs=2,
    )
    base_certificate = certify_e7e_berry_observable_convergence(
        base_samples[:1], base_samples, thresholds=live_thresholds,
    )
    phase_certificate = certify_e7e_berry_observable_convergence(
        phase_samples[:1], phase_samples, thresholds=live_thresholds,
    )
    base_values = [(x.omega_plus, x.omega_tr,
                    abs(x.omega_plus + x.omega_tr))
                   for x in base_samples]
    phase_values = [(x.omega_plus, x.omega_tr,
                     abs(x.omega_plus + x.omega_tr))
                    for x in phase_samples]
    assert base_certificate.status == phase_certificate.status == "INCOMPLETE"
    assert all(np.isfinite(value) for row in base_values + phase_values
               for value in row)
    assert all(row[2] <= .01 for row in base_values + phase_values)
    assert max(abs(a - b) for left, right in zip(base_values, phase_values)
               for a, b in zip(left, right)) < 2e-3


def test_e7f_step_tail_and_provenance_input_guards():
    resolution, step = _static_ladders()
    result = certify_e7e_berry_observable_convergence(resolution, step[:1], thresholds=_thresholds(), require_live=False)
    assert result.status == "INCOMPLETE"
    with pytest.raises(ValueError):
        replace(resolution[0], provenance={"bad": float("nan")})
    with pytest.raises(ValueError):
        replace(resolution[0], provenance={"bad": object()})


def test_e7f_same_numerical_key_semantic_overlap_matrix():
    resolution, step = _static_ladders()
    final = step[-1]
    altered = [
        replace(final, plus_result=_relocate(final.plus_result, (.21, .3))),
        replace(final, plus_result=_transform(final.plus_result, (.2, .3), lambda point: point * np.asarray((1.5, 1.0)))),
        replace(final, plus_result=replace(final.plus_result, coordinate_convention="wrong")),
        replace(final, provenance={"fixture": "altered"}),
        replace(final, eigenmode_plus=_eigenmode_certificate(4)),
    ]
    for candidate in altered:
        result = certify_e7e_berry_observable_convergence(
            resolution, (step[0], step[1], candidate),
            thresholds=_thresholds(), require_live=False,
        )
        assert result.status == "FAIL"
        assert any(check.name == "ladder.overlap.semantic" and check.status == "FAIL" for check in result.checks)
