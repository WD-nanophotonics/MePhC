import unittest

from reducer_c4_scaled import classify_periodicity


def raw(omega):
    return {"frequencies": [[0.1, 0.2, 0.4]], "pair_gap": 0.1, "external_gap": 0.2, "rank": 1, "production_decision": "QUALIFIED_VALUE", "omega_bands_q": omega}


class ScaledC4Tests(unittest.TestCase):
    def test_near_zero_seam_uses_fixed_scale_floor(self):
        row = {"a": raw([1e-6, 2e-6]), "b": raw([2e-6, 3e-6]), "reciprocal_identity": True, "scale_band1": 15.0, "scale_band2": 9.0}
        self.assertEqual(classify_periodicity([row] * 12), "CONFIRMED")

    def test_large_raw_frequency_mismatch_still_fails(self):
        left, right = raw([1.0, 2.0]), raw([1.0, 2.0])
        right["frequencies"] = [[0.101, 0.2, 0.4]]
        row = {"a": left, "b": right, "reciprocal_identity": True, "scale_band1": 15.0, "scale_band2": 9.0}
        self.assertEqual(classify_periodicity([row]), "PARTIALLY_CONFIRMED")
