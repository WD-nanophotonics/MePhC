import json
import unittest
from dataclasses import replace

from mephc.convergence import (
    EigenmodeConvergenceProvenance,
    EigenmodePairEvidence,
    certify_eigenmode_convergence,
    NumericalConvergenceError,
)
from mephc.convergence_binding import (
    EigenmodeCertificateBinding,
    bind_eigenmode_certificate,
)


def provenance(**changes):
    value = EigenmodeConvergenceProvenance(
        backend="mpb",
        geometry_digest="geometry-sha256",
        target_band=0,
        num_bands=2,
        polarization="TE",
        deterministic=True,
        eigensolver_tolerance=1e-11,
        mesh_size=3,
        field_representation="periodic_h_bloch_envelope",
    )
    return replace(value, **changes)


def certificate(*, status="PASS", observed_provenance=None):
    observed_provenance = observed_provenance or provenance()
    evidence = [
        EigenmodePairEvidence(64, 80, 1e-8, 0.999999, 1e-4, 0.26),
        EigenmodePairEvidence(80, 96, 1e-8, 0.999999, 1e-4, 0.26),
    ]
    if status == "INCOMPLETE":
        evidence = evidence[:1]
    if status == "FAIL":
        evidence[1] = replace(evidence[1], max_abs_frequency_change=1e-4)
    result = certify_eigenmode_convergence(evidence, provenance=observed_provenance)
    assert result.status == status
    return result


class CertificateProvenanceBindingR66OTests(unittest.TestCase):
    def test_exact_pass_binding(self):
        binding = bind_eigenmode_certificate(
            certificate(), expected_provenance=provenance()
        )
        self.assertIsInstance(binding, EigenmodeCertificateBinding)
        self.assertEqual(binding.status, "PASS")
        self.assertIs(binding.require_passed(), binding)
        self.assertTrue(all(check.status == "PASS" for check in binding.checks))

    def test_geometry_replay_protection(self):
        binding = bind_eigenmode_certificate(
            certificate(), expected_provenance=provenance(geometry_digest="other-geometry")
        )
        self.assertEqual(binding.status, "FAIL")
        self.assertEqual(binding.checks[2].name, "provenance.geometry_digest")
        self.assertEqual(binding.checks[2].status, "FAIL")
        with self.assertRaises(NumericalConvergenceError):
            binding.require_passed()

    def test_one_field_mismatch_matrix(self):
        mismatches = {
            "backend": "other-backend",
            "target_band": 1,
            "num_bands": 3,
            "polarization": "TM",
            "deterministic": False,
            "eigensolver_tolerance": 1e-7,
            "mesh_size": 5,
            "field_representation": "other-field-representation",
        }
        for field, value in mismatches.items():
            with self.subTest(field=field):
                binding = bind_eigenmode_certificate(
                    certificate(), expected_provenance=provenance(**{field: value})
                )
                self.assertEqual(binding.status, "FAIL")
                failed = [check.name for check in binding.checks if check.status == "FAIL"]
                self.assertEqual(failed, [f"provenance.{field}"])

    def test_changed_solver_settings_cannot_bless_pass_certificate(self):
        for field, value in (("eigensolver_tolerance", 1e-7), ("mesh_size", 5), ("deterministic", False)):
            with self.subTest(field=field):
                binding = bind_eigenmode_certificate(
                    certificate(), expected_provenance=provenance(**{field: value})
                )
                self.assertEqual(binding.status, "FAIL")

    def test_fail_certificate_exact_provenance(self):
        binding = bind_eigenmode_certificate(
            certificate(status="FAIL"), expected_provenance=provenance()
        )
        self.assertEqual(binding.status, "FAIL")
        self.assertEqual(binding.checks[0].name, "certificate.status")
        self.assertEqual(binding.checks[0].status, "FAIL")
        self.assertTrue(all(check.status == "PASS" for check in binding.checks[1:]))

    def test_incomplete_certificate_exact_provenance(self):
        binding = bind_eigenmode_certificate(
            certificate(status="INCOMPLETE"), expected_provenance=provenance()
        )
        self.assertEqual(binding.status, "INCOMPLETE")
        self.assertEqual(binding.checks[0].status, "INCOMPLETE")
        self.assertTrue(all(check.status == "PASS" for check in binding.checks[1:]))
        with self.assertRaises(NumericalConvergenceError):
            binding.require_passed()

    def test_incomplete_certificate_plus_mismatch_is_fail(self):
        binding = bind_eigenmode_certificate(
            certificate(status="INCOMPLETE"),
            expected_provenance=provenance(geometry_digest="other-geometry"),
        )
        self.assertEqual(binding.status, "FAIL")

    def test_serialization_is_deterministic_and_json_safe(self):
        first = bind_eigenmode_certificate(
            certificate(), expected_provenance=provenance()
        ).to_dict()
        second = bind_eigenmode_certificate(
            certificate(), expected_provenance=provenance()
        ).to_dict()
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], "mephc-eigenmode-binding/v1")
        self.assertEqual(json.loads(json.dumps(first, sort_keys=True)), first)

    def test_type_guards(self):
        with self.assertRaises(TypeError):
            bind_eigenmode_certificate(object(), expected_provenance=provenance())
        with self.assertRaises(TypeError):
            bind_eigenmode_certificate(certificate(), expected_provenance=object())


if __name__ == "__main__":
    unittest.main()
