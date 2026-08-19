import json
import unittest

from mephc.convergence import (
    EigenmodeConvergenceProvenance,
    EigenmodeConvergenceThresholds,
    EigenmodePairEvidence,
    NumericalConvergenceError,
    certify_eigenmode_convergence,
)


def provenance(*, deterministic=True):
    return EigenmodeConvergenceProvenance(
        backend="mpb",
        geometry_digest="geometry-sha256",
        target_band=1,
        num_bands=2,
        polarization="TE",
        deterministic=deterministic,
        eigensolver_tolerance=1e-11,
        mesh_size=3,
        field_representation="periodic_h_bloch_envelope",
    )


def pair(lower, upper, frequency, fidelity, residual, gap=0.26):
    return EigenmodePairEvidence(
        lower_resolution=lower,
        upper_resolution=upper,
        max_abs_frequency_change=frequency,
        min_h_fidelity=fidelity,
        max_h_relative_l2_residual=residual,
        min_isolation_gap=gap,
    )


class EigenmodeConvergenceR66NTests(unittest.TestCase):
    def test_homogeneous_control_passes(self):
        certificate = certify_eigenmode_convergence([
            pair(48, 64, 1e-13, 0.999999999998, 2e-6),
            pair(64, 80, 3.95516952522712e-15, 0.999999999999994, 1.0893702261916245e-7),
            pair(80, 96, 4.118927421359331e-14, 0.999999999998978, 1.42964109559628e-6),
        ], provenance=provenance())
        self.assertEqual(certificate.status, "PASS")
        self.assertIs(certificate.require_passed(), certificate)

    def test_active_sharp_control_fails_frequency_gate(self):
        certificate = certify_eigenmode_convergence([
            pair(64, 80, 5.46e-5, 0.999930804533445, 0.01176),
            pair(80, 96, 1.1814566604656518e-4, 0.9999990623940567, 0.0013693837616515058),
            pair(96, 128, 5.576987011549073e-5, 0.9999922899613093, 0.0039268406361111915),
        ], provenance=provenance())
        self.assertEqual(certificate.status, "FAIL")
        self.assertTrue(any(
            check.name.endswith("frequency_change") and check.status == "FAIL"
            for check in certificate.checks
        ))

    def test_smooth_control_fails_only_frequency_gate_in_tail(self):
        certificate = certify_eigenmode_convergence([
            pair(64, 80, 4.918669223805128e-5, 0.9999998171986828, 0.0006046508365446112),
            pair(80, 96, 3.459461256613561e-5, 0.9999999439308488, 0.0003348705757659016),
            pair(96, 128, 3.650686985601226e-5, 0.999999931736325, 0.00036949607639257204),
        ], provenance=provenance())
        self.assertEqual(certificate.status, "FAIL")
        tail_checks = certificate.checks[1:]
        self.assertTrue(all(
            check.status == "PASS"
            for check in tail_checks
            if check.name.endswith(("h_fidelity", "h_relative_l2_residual", "isolation_gap"))
        ))
        self.assertTrue(any(
            check.name.endswith("frequency_change") and check.status == "FAIL"
            for check in tail_checks
        ))

    def test_missing_tail_pair_is_incomplete(self):
        certificate = certify_eigenmode_convergence(
            [pair(80, 96, 1e-8, 0.999999, 1e-4)],
            provenance=provenance(),
        )
        self.assertEqual(certificate.status, "INCOMPLETE")
        with self.assertRaises(NumericalConvergenceError):
            certificate.require_passed()

    def test_nondeterministic_provenance_fails(self):
        certificate = certify_eigenmode_convergence([
            pair(64, 80, 1e-8, 0.999999, 1e-4),
            pair(80, 96, 1e-8, 0.999999, 1e-4),
        ], provenance=provenance(deterministic=False))
        self.assertEqual(certificate.status, "FAIL")
        self.assertEqual(certificate.checks[-1].name, "provenance.deterministic")
        self.assertEqual(certificate.checks[-1].status, "FAIL")

    def test_threshold_boundaries_are_inclusive(self):
        thresholds = EigenmodeConvergenceThresholds()
        certificate = certify_eigenmode_convergence([
            pair(64, 80, 1e-5, 0.99999, 5e-3, 1e-8),
            pair(80, 96, 1e-5, 0.99999, 5e-3, 1e-8),
        ], provenance=provenance(), thresholds=thresholds)
        self.assertEqual(certificate.status, "PASS")
        outside = certify_eigenmode_convergence([
            pair(64, 80, 1e-5 + 1e-12, 0.99999, 5e-3, 1e-8),
            pair(80, 96, 1e-5, 0.99999, 5e-3, 1e-8),
        ], provenance=provenance())
        self.assertEqual(outside.status, "FAIL")

    def test_serialization_is_json_safe_and_deterministic(self):
        evidence = [
            pair(64, 80, 1e-8, 0.999999, 1e-4),
            pair(80, 96, 1e-8, 0.999999, 1e-4),
        ]
        first = certify_eigenmode_convergence(evidence, provenance=provenance()).to_dict()
        second = certify_eigenmode_convergence(evidence, provenance=provenance()).to_dict()
        self.assertEqual(first, second)
        self.assertEqual(json.loads(json.dumps(first, sort_keys=True)), first)
        self.assertEqual(first["schema"], "mephc-eigenmode-convergence/v1")

    def test_malformed_chain_is_rejected(self):
        with self.assertRaises(ValueError):
            certify_eigenmode_convergence([
                pair(64, 80, 1e-8, 0.999999, 1e-4),
                pair(81, 96, 1e-8, 0.999999, 1e-4),
            ], provenance=provenance())


if __name__ == "__main__":
    unittest.main()
