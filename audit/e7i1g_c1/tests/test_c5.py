import copy
import math
import unittest

from identity_cache import CacheCollisionError, build_cache, lookup
from reducer_c5 import validate_trace
from sample_identity import expected_identity


def result(q=(0.1, 0.2), valley="K", radii=(0.15, 0.25), resolution=64, h=0.001):
    return {"target_q": list(q), "valley": valley, "radii": list(radii), "resolution": resolution, "h": h, "representation": "mpb_live_energy_eh_v1", "plaquette": "CENTERED_CCW", "geometry": "d0500-minus-sealed-honeycomb", "selected_bands_one_based": [1, 2], "rank": 1, "omega_bands_q": [1.0, -1.0], "production_decision": "QUALIFIED_VALUE"}


class C5Tests(unittest.TestCase):
    def test_complete_identity_rejects_same_q_physical_collisions(self):
        minus = result()
        plus = result(radii=(0.25, 0.15))
        kp = result(valley="Kp")
        cache = build_cache([("minus", [0.1, 0.2], minus), ("plus", [0.1, 0.2], plus), ("kp", [0.1, 0.2], kp)])
        self.assertEqual(lookup(cache, [0.1, 0.2])["source"], "minus")

    def test_disagreeing_exact_identity_fails_closed(self):
        left, right = result(), result()
        right["omega_bands_q"] = [2.0, -1.0]
        with self.assertRaises(CacheCollisionError):
            build_cache([("a", [0.1, 0.2], left), ("b", [0.1, 0.2], right)])

    def test_strict_exact_domain_qualification_fails_closed(self):
        trace = {"trace_version": "c4-structured-v1", "source_raw_manifest_sha256": "a" * 64, "rules": {"r": {"exact_domain": True, "total_record_count": 1, "qualified_count": 0, "sum_signed_weights": 1 / math.sqrt(3), "resulting_flux": {"band1": 0.0, "band2": 0.0, "anti": 0.0, "common": 0.0}, "chunks": [{"chunk_index": 0, "input_record_count": 1, "qualified_count": 0, "signed_weight_sum": 1 / math.sqrt(3), "weighted_curvature_sum": {"band1": 0.0, "band2": 0.0, "anti": 0.0, "common": 0.0}}]}}}
        with self.assertRaises(ValueError):
            validate_trace(trace)


if __name__ == "__main__":
    unittest.main()
