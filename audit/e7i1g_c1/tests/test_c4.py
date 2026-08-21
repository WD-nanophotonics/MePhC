import copy
import math
import unittest

from geometry_generator import EXPECTED_AREA, LEVELS, mesh
from reducer_c4 import classify_inversion, classify_periodicity, validate_trace


def raw(value, rank=1):
    return {"frequencies": [[0.1, 0.2, 0.4], [0.1 + value, 0.2 + value, 0.4 + value]], "pair_gap": 0.1, "external_gap": 0.2, "rank": rank, "production_decision": "QUALIFIED_VALUE", "omega_bands_q": [1.0, -2.0], "omega_anti_q": 1.5, "omega_common_q": -0.5}


class C4Tests(unittest.TestCase):
    def test_all_levels_are_same_exact_domain(self):
        for name in LEVELS:
            generated = mesh(name)
            self.assertEqual(generated["triangle_count"], {"coarse": 1536, "fine": 6144, "refined": 24576}[name])
            self.assertTrue(all(area > 0 for area in (0.5 * ((t[1][0] - t[0][0]) * (t[2][1] - t[0][1]) - (t[1][1] - t[0][1]) * (t[2][0] - t[0][0])) for t in generated["triangles"])))
            self.assertTrue(math.isclose(generated["signed_area"], EXPECTED_AREA, abs_tol=1e-12))

    def test_periodicity_recomputes_raw_frequency_and_rejects_point_one_percent(self):
        row = {"a": raw(0.0), "b": raw(0.001), "reciprocal_identity": True}
        self.assertEqual(classify_periodicity([row]), "PARTIALLY_CONFIRMED")
        row = {"a": raw(0.0), "b": raw(1e-8), "reciprocal_identity": True}
        self.assertEqual(classify_periodicity([row] * 12), "CONFIRMED")

    def test_inversion_near_zero_sign_is_indeterminate_but_antisymmetry_is_required(self):
        base = raw(0.0)
        plus = copy.deepcopy(base)
        base["omega_bands_q"] = [1e-6, -2.0]
        plus["omega_bands_q"] = [2e-6, 2.0]
        row = {"base": base, "plus": plus, "scale_band1": 1.0, "scale_band2": 1.0}
        self.assertEqual(classify_inversion([row] * 8), "CONFIRMED")
        plus["omega_bands_q"][1] = 3.0
        self.assertEqual(classify_inversion([row] * 8), "PARTIALLY_CONFIRMED")

    def test_trace_closure_rejects_reordered_chunks_and_incomplete_domain(self):
        trace = {"trace_version": "c4-structured-v1", "source_raw_manifest_sha256": "a" * 64, "rules": {"r": {"exact_domain": True, "total_record_count": 1, "qualified_count": 1, "sum_signed_weights": EXPECTED_AREA, "resulting_flux": {"band1": 1.0, "band2": 2.0, "anti": 3.0, "common": 4.0}, "chunks": [{"chunk_index": 0, "input_record_count": 1, "qualified_count": 1, "signed_weight_sum": EXPECTED_AREA, "weighted_curvature_sum": {"band1": 1.0, "band2": 2.0, "anti": 3.0, "common": 4.0}}]}}}
        validate_trace(trace)
        broken = copy.deepcopy(trace)
        broken["rules"]["r"]["chunks"][0]["chunk_index"] = 1
        with self.assertRaises(ValueError):
            validate_trace(broken)
        broken = copy.deepcopy(trace)
        broken["rules"]["r"]["sum_signed_weights"] = EXPECTED_AREA - 0.01
        with self.assertRaises(ValueError):
            validate_trace(broken)


if __name__ == "__main__":
    unittest.main()
