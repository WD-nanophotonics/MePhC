from dataclasses import replace
import json

import pytest

from mephc.berry_convergence import (
    BerryObservableConvergenceCertificate,
    BerryObservableProvenance,
    BerryObservableThresholds,
    QualifiedBerrySample,
    certify_berry_observable_convergence,
)
from mephc.convergence import (
    EigenmodeConvergenceProvenance,
    EigenmodeConvergenceThresholds,
    EigenmodePairEvidence,
    NumericalConvergenceError,
    certify_eigenmode_convergence,
)


def provenance(*, geometry_digest="a" * 64):
    return BerryObservableProvenance(
        backend="mpb",
        geometry_digest=geometry_digest,
        target_band=0,
        num_bands=2,
        polarization="TE",
        deterministic=True,
        eigensolver_tolerance=1e-7,
        mesh_size=3,
        field_representation="periodic_h_bloch_envelope",
        overlap_formulation="mpb_h",
        k_plus=(0.1, 0.2),
        coordinate_system="cartesian_reciprocal",
        plaquette_semantics="counterclockwise_square_lower_left",
        trs_partner_semantics="k_tr_lower_left=-k_plus-(step,step)",
        estimator_schema="mephc-abelian-square-wilson-mpb-h/v1",
    )


def eigenmode_certificate(p, resolution, *, status="PASS", bad=False, incomplete=False):
    ep = p.eigenmode_provenance()
    if incomplete:
        evidence = [EigenmodePairEvidence(2, 3, 1e-8, 0.999999, 1e-4, 0.26)]
    else:
        evidence = [
            EigenmodePairEvidence(2, 3, 1e-8, 0.999999, 1e-4, 0.26),
            EigenmodePairEvidence(3, resolution, 0.2 if bad else 1e-8, 0.999999, 1e-4, 0.26),
        ]
    cert = certify_eigenmode_convergence(evidence, provenance=ep)
    return cert


def sample(p, resolution, step, omega_plus, omega_tr, **kwargs):
    return QualifiedBerrySample(
        resolution=resolution,
        step=step,
        omega_plus=omega_plus,
        omega_tr=omega_tr,
        eigenmode_certificate=eigenmode_certificate(p, kwargs.pop("certificate_resolution", resolution), **kwargs),
    )


def stable_fixture(p=None):
    p = p or provenance()
    resolutions = [
        sample(p, 4, 0.001, 0.1000, -0.1000),
        sample(p, 8, 0.001, 0.1005, -0.1005),
        sample(p, 12, 0.001, 0.1008, -0.1008),
    ]
    steps = [
        sample(p, 12, 0.003, 0.1002, -0.1002),
        sample(p, 12, 0.002, 0.1005, -0.1005),
        sample(p, 12, 0.001, 0.1008, -0.1008),
    ]
    return p, resolutions, steps


def test_stable_fixture_passes_and_serializes_deterministically():
    p, resolutions, steps = stable_fixture()
    result = certify_berry_observable_convergence(resolutions, steps, provenance=p)
    assert result.status == "PASS"
    assert result.qualified_resolution == 12
    assert result.qualified_step == 0.001
    assert result.require_passed() is result
    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert json.loads(encoded)["schema"] == "mephc-berry-observable-convergence/v1"
    assert json.dumps(result.to_dict(), sort_keys=True) == encoded


def test_near_zero_signal_passes_without_minimum_signal_requirement():
    p = provenance()
    resolutions = [
        sample(p, 4, 0.001, 0.0, 0.0),
        sample(p, 8, 0.001, 1e-7, -1e-7),
        sample(p, 12, 0.001, 2e-7, -2e-7),
    ]
    steps = [
        sample(p, 12, 0.003, 0.0, 0.0),
        sample(p, 12, 0.002, 1e-7, -1e-7),
        sample(p, 12, 0.001, 2e-7, -2e-7),
    ]
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p).status == "PASS"


def test_unstable_resolution_fails_with_stable_step_ladder():
    p = provenance()
    resolutions = [
        sample(p, 16, 0.001, 9.620075263489499e-4, -8.821482843389922e-4),
        sample(p, 20, 0.001, 3.964634242854383e-3, -4.066853835986755e-3),
        sample(p, 24, 0.001, 2.6145780600112526e-4, -2.5395763939721965e-4),
    ]
    steps = [
        sample(p, 24, 0.003, 2.70e-4, -2.70e-4),
        sample(p, 24, 0.002, 2.65e-4, -2.65e-4),
        sample(p, 24, 0.001, 2.6145780600112526e-4, -2.5395763939721965e-4),
    ]
    result = certify_berry_observable_convergence(resolutions, steps, provenance=p)
    assert result.status == "FAIL"
    assert any(check.name.startswith("resolution.") and check.status == "FAIL" for check in result.checks)


def test_stable_resolution_unstable_step_fails():
    p = provenance()
    resolutions = [sample(p, 4, 0.001, 0.1, -0.1), sample(p, 8, 0.001, 0.1001, -0.1001), sample(p, 12, 0.001, 0.2, -0.2)]
    steps = [sample(p, 12, 0.003, 0.1, -0.1), sample(p, 12, 0.002, 0.1001, -0.1001), sample(p, 12, 0.001, 0.2, -0.2)]
    thresholds = BerryObservableThresholds(max_resolution_abs_change=0.2, max_resolution_relative_change=0.0, max_step_abs_change=0.01, max_step_relative_change=0.0)
    result = certify_berry_observable_convergence(resolutions, steps, provenance=p, thresholds=thresholds)
    assert result.status == "FAIL"
    assert any(check.name.startswith("step.") and check.status == "FAIL" for check in result.checks)


def test_bad_trs_fails_even_when_ladders_converge():
    p = provenance()
    resolutions = [sample(p, 4, 0.001, 0.1, -0.08), sample(p, 8, 0.001, 0.1, -0.08), sample(p, 12, 0.001, 0.1, -0.08)]
    steps = [sample(p, 12, 0.003, 0.1, -0.08), sample(p, 12, 0.002, 0.1, -0.08), sample(p, 12, 0.001, 0.1, -0.08)]
    result = certify_berry_observable_convergence(resolutions, steps, provenance=p)
    assert result.status == "FAIL"
    assert any(check.name.startswith("trs.") and check.status == "FAIL" for check in result.checks)


def test_missing_ladder_evidence_is_incomplete():
    p = provenance()
    resolutions = [sample(p, 4, 0.001, 0.1, -0.1), sample(p, 8, 0.001, 0.1, -0.1)]
    steps = [sample(p, 8, 0.003, 0.1, -0.1), sample(p, 8, 0.002, 0.1, -0.1), sample(p, 8, 0.001, 0.1, -0.1)]
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p).status == "INCOMPLETE"
    resolutions, steps = stable_fixture(p)[1], [sample(p, 12, 0.002, 0.1007, -0.1007), sample(p, 12, 0.001, 0.1008, -0.1008)]
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p).status == "INCOMPLETE"


@pytest.mark.parametrize("kind", ["FAIL", "INCOMPLETE"])
def test_eigenmode_gating_status_is_recomputed(kind):
    p = provenance()
    resolutions = [sample(p, 4, 0.001, 0.1, -0.1), sample(p, 8, 0.001, 0.1, -0.1), sample(p, 12, 0.001, 0.1, -0.1)]
    steps = [sample(p, 12, 0.003, 0.1, -0.1), sample(p, 12, 0.002, 0.1, -0.1), sample(p, 12, 0.001, 0.1, -0.1)]
    if kind == "FAIL":
        resolutions[-1] = sample(p, 12, 0.001, 0.1, -0.1, bad=True)
    else:
        resolutions[-1] = sample(p, 12, 0.001, 0.1, -0.1, incomplete=True)
    steps[-1] = resolutions[-1]
    result = certify_berry_observable_convergence(resolutions, steps, provenance=p)
    assert result.status == kind


def test_forged_stored_pass_is_revalidated_and_fails():
    p = provenance()
    bad = eigenmode_certificate(p, 12, bad=True)
    forged = replace(bad, status="PASS")
    resolutions, steps = stable_fixture(p)[1], stable_fixture(p)[2]
    resolutions[-1] = replace(resolutions[-1], eigenmode_certificate=forged)
    steps[-1] = replace(steps[-1], eigenmode_certificate=forged)
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p).status == "FAIL"


def test_geometry_mismatch_and_resolution_scope_replay_fail():
    p = provenance()
    resolutions, steps = stable_fixture(p)[1:]
    other = provenance(geometry_digest="b" * 64)
    resolutions[-1] = replace(resolutions[-1], eigenmode_certificate=eigenmode_certificate(other, 12))
    steps[-1] = resolutions[-1]
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p).status == "FAIL"
    resolutions, steps = stable_fixture(p)[1:]
    replay = eigenmode_certificate(p, 128)
    resolutions[-1] = replace(resolutions[-1], eigenmode_certificate=replay)
    steps[-1] = resolutions[-1]
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p).status == "FAIL"


def test_exact_threshold_boundary_passes_and_outside_fails():
    p = provenance()
    thresholds = BerryObservableThresholds(
        max_resolution_abs_change=0.1, max_resolution_relative_change=0.0,
        max_step_abs_change=0.1, max_step_relative_change=0.0,
        max_trs_abs_residual=0.0, max_trs_relative_residual=0.0,
    )
    resolutions = [sample(p, 4, 0.001, 0.0, 0.0), sample(p, 8, 0.001, 0.1, -0.1), sample(p, 12, 0.001, 0.2, -0.2)]
    steps = [sample(p, 12, 0.003, 0.0, 0.0), sample(p, 12, 0.002, 0.1, -0.1), sample(p, 12, 0.001, 0.2, -0.2)]
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p, thresholds=thresholds).status == "PASS"
    resolutions[-1] = replace(resolutions[-1], omega_plus=0.2000001, omega_tr=-0.2000001)
    steps[-1] = resolutions[-1]
    assert certify_berry_observable_convergence(resolutions, steps, provenance=p, thresholds=thresholds).status == "FAIL"


def test_malformed_overlap_and_wrong_semantics_are_rejected():
    p, resolutions, steps = stable_fixture()
    steps[-1] = replace(steps[-1], omega_plus=0.2)
    with pytest.raises(ValueError):
        certify_berry_observable_convergence(resolutions, steps, provenance=p)
    for field in ("overlap_formulation", "field_representation", "coordinate_system", "plaquette_semantics", "trs_partner_semantics", "estimator_schema"):
        with pytest.raises(ValueError):
            replace(p, **{field: "wrong"})


def test_require_passed_identifies_blockers():
    p, resolutions, steps = stable_fixture()
    resolutions = resolutions[:2]
    steps = [sample(p, 8, 0.003, 0.1001, -0.1001), sample(p, 8, 0.002, 0.1003, -0.1003), sample(p, 8, 0.001, 0.1005, -0.1005)]
    result = certify_berry_observable_convergence(resolutions, steps, provenance=p)
    with pytest.raises(NumericalConvergenceError, match="resolution.completeness"):
        result.require_passed()


def test_threshold_validation_rejects_bool_and_invalid_relative_values():
    with pytest.raises(ValueError):
        BerryObservableThresholds(required_resolution_tail_pairs=True)
    with pytest.raises(ValueError):
        BerryObservableThresholds(max_step_relative_change=1.1)
    with pytest.raises(ValueError):
        BerryObservableThresholds(max_trs_abs_residual=float("inf"))


def test_provenance_exposes_exact_eigenmode_scope():
    p = provenance()
    eigenmode = p.eigenmode_provenance()
    assert eigenmode.backend == "mpb"
    assert eigenmode.geometry_digest == p.geometry_digest
    assert eigenmode.field_representation == p.field_representation
