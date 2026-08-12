"""R6.1 corrected benchmark and band-local eligibility regression tests."""
from __future__ import annotations

import unittest
import numpy as np

from mephc.bravais import BravaisLattice2D
from mephc.response import (
    R6_AMPLITUDES,
    band_local_delta_max,
    benchmark_field,
    eligibility,
    sign_reversal,
)


class R61ResponseTests(unittest.TestCase):
    def test_corrected_field_site_pattern_sign_and_half_amplitude(self):
        lattice = BravaisLattice2D.square()
        plus = benchmark_field(lattice, 0.005)
        minus = benchmark_field(lattice, -0.005)
        half = benchmark_field(lattice, 0.0025)
        probes = np.asarray([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
        expected = np.asarray([[0.005, 0.0], [-0.005, 0.0], [-0.005, 0.0], [0.005, 0.0]])
        np.testing.assert_allclose(plus.displacement(probes), expected, atol=1e-12)
        np.testing.assert_allclose(minus.displacement(probes), -expected, atol=1e-12)
        np.testing.assert_allclose(half.displacement(probes), expected / 2.0, atol=1e-12)
        self.assertTrue(plus.verified)
        self.assertEqual(set(R6_AMPLITUDES), {0.0, 0.005, -0.005, 0.0025, -0.0025})

    def test_band_local_delta_captures_larger_negative_shift(self):
        baseline = np.asarray([1.0, 2.0, 4.0])
        perturbed = np.asarray([
            [1.01, 2.01, 4.02],
            [0.96, 2.02, 4.03],
            [1.00, 2.00, 4.01],
            [1.005, 2.005, 4.02],
        ])
        self.assertAlmostEqual(band_local_delta_max(baseline, perturbed, 0), 0.04)
        self.assertAlmostEqual(band_local_delta_max(baseline, perturbed, 1), 0.02)
        self.assertAlmostEqual(band_local_delta_max(baseline, perturbed, 2), 0.03)

    def test_neighbor_band_does_not_contaminate_local_eligibility(self):
        baseline = np.asarray([1.0, 2.0, 4.0])
        perturbed = np.asarray([
            [1.01, 2.01, 8.0],
            [1.00, 2.02, 4.0],
            [0.99, 1.98, 4.0],
            [1.005, 2.005, 7.0],
        ])
        result = eligibility(baseline, perturbed, band_ordinal=1, convergence_error_bound=0.0)
        self.assertTrue(result.eligible)
        self.assertAlmostEqual(result.maximum_perturbation, 0.02)
        self.assertAlmostEqual(result.metadata()["delta_max"], 0.02)

    def test_zero_delta_and_strict_threshold(self):
        baseline = np.asarray([1.0, 2.0, 3.0])
        zero = np.repeat(baseline[None, :], 4, axis=0)
        self.assertEqual(band_local_delta_max(baseline, zero, 1), 0.0)
        equality = zero.copy()
        equality[:, 1] = 2.25
        result = eligibility(baseline, equality, band_ordinal=1, convergence_error_bound=0.0)
        self.assertFalse(result.eligible)
        self.assertIn("perturbation_fraction_of_gap", result.reason)

    def test_sign_reversal_uses_complete_spectra_band_locally(self):
        raw = {
            0.0: np.asarray([1.0, 2.0, 4.0]),
            0.005: np.asarray([1.01, 2.01, 8.0]),
            -0.005: np.asarray([0.96, 1.99, 4.0]),
            0.0025: np.asarray([1.005, 2.005, 7.0]),
            -0.0025: np.asarray([0.98, 1.995, 4.0]),
        }
        result = sign_reversal(
            "q1",
            1,
            raw,
            0.0,
            baseline_spectrum=raw[0.0],
            perturbed_spectra=np.vstack([raw[0.005], raw[-0.005], raw[0.0025], raw[-0.0025]]),
        )
        self.assertTrue(result.eligibility.eligible)
        self.assertAlmostEqual(result.eligibility.maximum_perturbation, 0.01)


if __name__ == "__main__":
    unittest.main()

