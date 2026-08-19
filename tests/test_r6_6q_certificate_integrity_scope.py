import json
from dataclasses import replace

import meep as mp
import pytest

from mephc.convergence import (
    ConvergenceCheck,
    EigenmodeConvergenceCertificate,
    EigenmodeConvergenceProvenance,
    EigenmodeConvergenceThresholds,
    EigenmodePairEvidence,
    check_eigenmode_certificate_integrity,
    certify_eigenmode_convergence,
    revalidate_eigenmode_certificate,
    NumericalConvergenceError,
)
from mephc.convergence_binding import (
    bind_eigenmode_certificate,
    bind_eigenmode_certificate_for_resolution,
)
from mephc.geometry_identity import build_supercell_geometry_identity


def provenance(digest="geometry-sha256"):
    return EigenmodeConvergenceProvenance(
        backend="mpb",
        geometry_digest=digest,
        target_band=0,
        num_bands=2,
        polarization="TE",
        deterministic=True,
        eigensolver_tolerance=1e-11,
        mesh_size=3,
        field_representation="periodic_h_bloch_envelope",
    )


def evidence(*, incomplete=False, failing=False):
    values = [
        EigenmodePairEvidence(80, 96, 1e-8, 0.999999, 1e-4, 0.26),
        EigenmodePairEvidence(96, 128, 1e-8, 0.999999, 1e-4, 0.26),
    ]
    if incomplete:
        return values[:1]
    if failing:
        values[-1] = replace(values[-1], max_abs_frequency_change=1e-4)
    return values


def canonical(*, incomplete=False, failing=False, digest="geometry-sha256"):
    return certify_eigenmode_convergence(
        evidence(incomplete=incomplete, failing=failing),
        provenance=provenance(digest),
    )


def forged(*, incomplete=False, failing=False):
    source = canonical(incomplete=incomplete, failing=failing)
    return EigenmodeConvergenceCertificate(
        status="PASS",
        thresholds=source.thresholds,
        provenance=source.provenance,
        evidence=tuple(source.evidence),
        checks=tuple(),
    )


def scope(certificate, expected_resolution=128, expected_provenance=None):
    return bind_eigenmode_certificate_for_resolution(
        certificate,
        expected_provenance=expected_provenance or certificate.provenance,
        expected_resolution=expected_resolution,
    )


def test_canonical_pass_integrity_and_exact_scope():
    certificate = canonical()
    assert check_eigenmode_certificate_integrity(certificate).status == "PASS"
    assert revalidate_eigenmode_certificate(certificate).to_dict() == certificate.to_dict()
    binding = bind_eigenmode_certificate(certificate, expected_provenance=provenance())
    assert binding.status == "PASS"
    assert scope(certificate).status == "PASS"
    assert scope(certificate).require_passed().status == "PASS"


@pytest.mark.parametrize("resolution", [80, 96, 24, 160, 256])
def test_only_final_certified_resolution_is_authorized(resolution):
    result = scope(canonical(), expected_resolution=resolution)
    assert result.certified_resolution == 128
    assert result.status == ("PASS" if resolution == 128 else "FAIL")


def test_forged_stored_pass_canonical_fail_is_rejected():
    certificate = forged(failing=True)
    assert revalidate_eigenmode_certificate(certificate).status == "FAIL"
    assert check_eigenmode_certificate_integrity(certificate).status == "FAIL"
    binding = bind_eigenmode_certificate(certificate, expected_provenance=provenance())
    assert binding.status == "FAIL"
    assert scope(certificate).status == "FAIL"
    with pytest.raises(NumericalConvergenceError):
        scope(certificate).require_passed()


def test_forged_stored_pass_canonical_incomplete_is_rejected():
    certificate = forged(incomplete=True)
    assert revalidate_eigenmode_certificate(certificate).status == "INCOMPLETE"
    assert check_eigenmode_certificate_integrity(certificate).status == "FAIL"
    assert bind_eigenmode_certificate(certificate, expected_provenance=provenance()).status == "FAIL"
    result = scope(certificate)
    assert result.status == "FAIL"
    assert result.certified_resolution is None


def test_tampered_checks_fail_integrity_but_semantic_clone_passes():
    source = canonical()
    tampered = replace(source, checks=tuple())
    assert check_eigenmode_certificate_integrity(tampered).status == "FAIL"
    assert bind_eigenmode_certificate(tampered, expected_provenance=provenance()).status == "FAIL"
    clone = EigenmodeConvergenceCertificate(
        status=source.status,
        thresholds=source.thresholds,
        provenance=source.provenance,
        evidence=source.evidence,
        checks=source.checks,
    )
    assert check_eigenmode_certificate_integrity(clone).status == "PASS"
    assert scope(clone).status == "PASS"


def test_canonical_incomplete_and_fail_have_no_certified_resolution():
    incomplete = canonical(incomplete=True)
    assert check_eigenmode_certificate_integrity(incomplete).status == "PASS"
    assert bind_eigenmode_certificate(incomplete, expected_provenance=provenance()).status == "INCOMPLETE"
    incomplete_scope = scope(incomplete)
    assert incomplete_scope.status == "INCOMPLETE"
    assert incomplete_scope.certified_resolution is None
    with pytest.raises(NumericalConvergenceError):
        incomplete_scope.require_passed()

    failing = canonical(failing=True)
    assert check_eigenmode_certificate_integrity(failing).status == "PASS"
    assert bind_eigenmode_certificate(failing, expected_provenance=provenance()).status == "FAIL"
    assert scope(failing).certified_resolution is None


def test_geometry_digest_mismatch_dominates_exact_resolution():
    certificate = canonical()
    binding = bind_eigenmode_certificate(
        certificate, expected_provenance=provenance("different-geometry")
    )
    assert check_eigenmode_certificate_integrity(certificate).status == "PASS"
    assert binding.status == "FAIL"
    assert scope(certificate, expected_provenance=provenance("different-geometry")).status == "FAIL"


def test_serialization_is_deterministic_and_json_safe():
    certificate = canonical()
    binding = bind_eigenmode_certificate(certificate, expected_provenance=provenance())
    scoped = scope(certificate)
    for value, schema in ((binding, "mephc-eigenmode-binding/v1"), (scoped, "mephc-eigenmode-scope-binding/v1")):
        first = value.to_dict()
        second = value.to_dict()
        assert first == second
        assert first["schema"] == schema
        assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_type_and_resolution_guards():
    certificate = canonical()
    with pytest.raises(TypeError):
        bind_eigenmode_certificate_for_resolution(object(), expected_provenance=provenance(), expected_resolution=128)
    with pytest.raises(TypeError):
        bind_eigenmode_certificate_for_resolution(certificate, expected_provenance=object(), expected_resolution=128)
    for value in (True, 0, -1, "128"):
        with pytest.raises(ValueError):
            bind_eigenmode_certificate_for_resolution(certificate, expected_provenance=provenance(), expected_resolution=value)


def test_geometry_identity_digest_bridges_to_exact_scope_binding():
    lattice = mp.Lattice(size=mp.Vector3(2, 2, 0))
    geometry = [mp.Cylinder(radius=0.1, height=1, material=mp.air)]
    identity = build_supercell_geometry_identity(
        geometry_lattice=lattice,
        geometry=geometry,
        replication=(2, 2),
    )
    certificate = canonical(digest=identity.digest)
    assert scope(certificate, expected_provenance=provenance(identity.digest)).status == "PASS"
    mutated = build_supercell_geometry_identity(
        geometry_lattice=lattice,
        geometry=[mp.Cylinder(radius=0.11, height=1, material=mp.air)],
        replication=(2, 2),
    )
    assert mutated.digest != identity.digest
    assert scope(certificate, expected_provenance=provenance(mutated.digest)).status == "FAIL"


def test_integrity_check_has_explicit_structured_fields():
    check = check_eigenmode_certificate_integrity(canonical())
    assert isinstance(check, ConvergenceCheck)
    assert check.name == "certificate.integrity"
    assert check.observed["supplied_status"] == "PASS"
    assert check.observed["canonical_status"] == "PASS"
    assert check.observed["serialized_match"] is True
