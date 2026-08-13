"""R7 equivalence-aware differential Maxwell response tests."""
from __future__ import annotations

import unittest

import numpy as np

from mephc.response import RawSpectrum, SolverSettings, SupercellQPoint
from mephc.r7_response import match_equivalent_spectrum, qualify_differential_maxwell_response


class R7ResponseTests(unittest.TestCase):
    def test_permutation_is_equivalent_and_returns_assignment(self):
        result = match_equivalent_spectrum([1.0, 2.0, 4.0], [4.0, 1.0, 2.0])
        self.assertTrue(result.equivalent)
        self.assertEqual(result.assignment, (1, 2, 0))
        self.assertEqual(result.maximum_difference, 0.0)

    def test_raw_spectrum_identity_mismatch_is_blocked(self):
        settings = SolverSettings(0.0, 8, num_bands=3)
        left = RawSpectrum(SupercellQPoint("q1", (0.12, 0.07)), settings, (1.0, 2.0, 4.0))
        right = RawSpectrum(SupercellQPoint("q2", (-0.09, 0.14)), settings, (4.0, 1.0, 2.0))
        result = match_equivalent_spectrum(left, right)
        self.assertFalse(result.equivalent)
        self.assertEqual(result.reason, "semantic_identity_mismatch")

    def test_permuted_null_ladder_cannot_create_response(self):
        baseline = np.asarray([1.0, 2.0, 4.0])
        raw = {
            0.0: baseline,
            0.005: baseline[[2, 0, 1]],
            -0.005: baseline[[1, 2, 0]],
            0.0025: baseline[[0, 2, 1]],
            -0.0025: baseline[[2, 1, 0]],
        }
        result = qualify_differential_maxwell_response("q1", 1, raw, 0.0)
        self.assertEqual(result.status, "EQUIVALENT_NULL")
        self.assertFalse(result.qualified)
        self.assertEqual(result.odd_a, 0.0)
        self.assertEqual(result.mapped_spectra[0], tuple(baseline))

    def test_physical_shift_is_permutation_invariant(self):
        baseline = np.asarray([1.0, 2.0, 4.0])
        ordered = {
            0.0: baseline,
            0.005: np.asarray([1.01, 2.01, 4.02]),
            -0.005: np.asarray([0.99, 1.99, 3.98]),
            0.0025: np.asarray([1.005, 2.005, 4.01]),
            -0.0025: np.asarray([0.995, 1.995, 3.99]),
        }
        permuted = {0.0: baseline}
        for amplitude, values in ordered.items():
            if amplitude != 0.0:
                permuted[amplitude] = values[[2, 0, 1]]
        left = qualify_differential_maxwell_response("q1", 1, ordered, 0.0)
        right = qualify_differential_maxwell_response("q1", 1, permuted, 0.0)
        self.assertEqual(left.status, "PASS_DIFFERENTIAL")
        self.assertTrue(left.qualified)
        self.assertAlmostEqual(left.odd_a, right.odd_a)
        self.assertAlmostEqual(left.even_a, right.even_a)
        self.assertAlmostEqual(left.eligibility.maximum_perturbation, right.eligibility.maximum_perturbation)

    def test_nonfinite_or_missing_ladder_is_rejected(self):
        with self.assertRaises(ValueError):
            qualify_differential_maxwell_response("q1", 0, {0.0: [1.0]}, 0.0)
        with self.assertRaises(ValueError):
            match_equivalent_spectrum([1.0, np.nan], [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
