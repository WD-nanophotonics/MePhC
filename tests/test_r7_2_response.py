"""R7.2 sign-equivalence and differential-resolution tests."""
from __future__ import annotations

import unittest

import numpy as np

from mephc.r7_2_response import (
    compare_differential_resolution_ladder,
    verify_periodic_sign_geometry,
    verify_sign_spectrum,
)
from mephc.r7_response import DifferentialMaxwellResponse
from mephc.response import RawSpectrum, SolverSettings, SupercellQPoint


class R72ResponseTests(unittest.TestCase):
    def test_periodic_translation_verifies_sign_equivalence(self):
        motif = np.asarray([[-0.2, -0.2], [0.2, -0.2], [0.2, 0.2], [-0.2, 0.2]])
        plus = [motif + [0.01, 0.0], motif + [0.99, 0.0], motif + [-0.01, 1.0], motif + [1.01, 1.0]]
        minus = [motif + [-0.01, 0.0], motif + [1.01, 0.0], motif + [0.01, 1.0], motif + [0.99, 1.0]]
        result = verify_periodic_sign_geometry(plus, minus, np.diag([2.0, 2.0]), ([1.0, 0.0], [0.0, 1.0]))
        self.assertTrue(result.equivalent)
        self.assertEqual(result.reason, "EQUIVALENT_PERIODIC_TRANSLATION")

    def test_sign_spectrum_requires_semantic_identity(self):
        settings = SolverSettings(0.005, 12, num_bands=2)
        plus = RawSpectrum(SupercellQPoint("q1", (0.12, 0.07)), settings, (1.0, 2.0))
        minus = RawSpectrum(SupercellQPoint("q1", (0.12, 0.07)), SolverSettings(-0.005, 12, num_bands=2), (2.0, 1.0))
        result = verify_sign_spectrum(plus, minus)
        self.assertTrue(result.equivalent)
        self.assertEqual(result.spectrum.assignment, (1, 0))

    def test_differential_resolution_ladder_accepts_stable_response(self):
        def response(value):
            return DifferentialMaxwellResponse("q1", 1, "PASS_DIFFERENTIAL", True, 2.0, value, value / 10, value / 2, value / 20, 2.0, 2.0, ((1.0,),), tuple(), None, "PASS")
        data = {
            8: {("q1", 1): response(0.1000)},
            12: {("q1", 1): response(0.1005)},
            16: {("q1", 1): response(0.1004)},
        }
        result = compare_differential_resolution_ladder(data, absolute_tolerance=0.002, relative_tolerance=0.02)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.accepted_resolution, 12)

    def test_differential_resolution_ladder_blocks_drift(self):
        def response(value):
            return DifferentialMaxwellResponse("q1", 1, "PASS_DIFFERENTIAL", True, 2.0, value, 0.0, 0.0, 0.0, None, None, ((1.0,),), tuple(), None, "PASS")
        data = {8: {("q1", 1): response(0.1)}, 12: {("q1", 1): response(0.2)}, 16: {("q1", 1): response(0.3)}}
        result = compare_differential_resolution_ladder(data, absolute_tolerance=0.002, relative_tolerance=0.02)
        self.assertEqual(result.status, "BLOCKED_DIFFERENTIAL_NONCONVERGED")
        self.assertIsNone(result.accepted_resolution)


if __name__ == "__main__":
    unittest.main()
