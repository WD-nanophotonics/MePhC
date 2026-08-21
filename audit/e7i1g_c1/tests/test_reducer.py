import json
import tempfile
import unittest
from pathlib import Path

from reducer import axis_sign_test, classify_gamma, classify_inversion, classify_periodicity, orient_ccw, signed_area


class ReducerTests(unittest.TestCase):
    def test_signed_orientation_and_axis_sign(self):
        triangle = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        self.assertGreater(signed_area(triangle), 0)
        self.assertGreater(signed_area(orient_ccw([triangle[0], triangle[2], triangle[1]])), 0)
        signs = axis_sign_test()
        self.assertEqual(signs["base"], 0.5)
        self.assertEqual(signs["one_axis"], -0.5)
        self.assertEqual(signs["two_axes"], 0.5)
        self.assertEqual(signs["one_axis_integral"], -signs["base_integral"])
        self.assertEqual(signs["two_axes_integral"], signs["base_integral"])

    def test_complete_periodicity_gate(self):
        row = {"reciprocal_identity": True, "frequency_disagreement": 0.001, "rank_compatible": True, "qualification_compatible": True, "hybrid_band1": 0.01, "hybrid_band2": 0.02, "systematic_discrepancy": False}
        self.assertEqual(classify_periodicity([row] * 12), "CONFIRMED")
        row["rank_compatible"] = False
        self.assertEqual(classify_periodicity([row]), "PARTIALLY_CONFIRMED")

    def test_complete_inversion_gate(self):
        row = {"expected_sign_band1": -1, "expected_sign_band2": -1, "observed_sign_band1": -1, "observed_sign_band2": -1, "spectral_compatible": True, "rank_compatible": True, "qualification_compatible": True, "hybrid_band1": 0.01, "hybrid_band2": 0.02}
        self.assertEqual(classify_inversion([row] * 8), "CONFIRMED")
        row["spectral_compatible"] = False
        self.assertEqual(classify_inversion([row]), "PARTIALLY_CONFIRMED")

    def test_gamma_requires_non_degeneracy_evidence(self):
        row = {"pair_gap": 0.38, "external_gap": 0.079, "target_eigenvalues_degenerate": False, "transport_min_singular": 0.5, "stable_across_controls": True}
        self.assertEqual(classify_gamma([row] * 3), "SYMMETRY_POINT_FRAME_OR_BRANCH_AMBIGUITY")

    def test_no_source_rewriting_in_reducer(self):
        source = Path(__file__).parents[1] / "reducer.py"
        text = source.read_text()
        self.assertNotIn("exec(", text)
        self.assertNotIn("source.replace", text)


if __name__ == "__main__":
    unittest.main()
