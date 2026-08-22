import json
import tempfile
import unittest
from pathlib import Path

from c8_perturbed_nodes import normalize_records
from c9_source_bound import (
    EXPECTED_SOURCE_SHA,
    add_result_bindings,
    build_compact_trace,
    direct_flux,
    max_dq_bound,
    validate_logical_association,
    witness_evidence,
)


def result(target=(1.0, 2.0), berry=1.0):
    return {
        "target_q": list(target),
        "valley": "K",
        "radii": [0.15, 0.25],
        "resolution": 64,
        "h": 0.001,
        "representation": "mpb_live_energy_eh_v1",
        "plaquette": "CENTERED_CCW",
        "geometry": "d0500-minus-sealed-honeycomb",
        "selected_bands_one_based": [1, 2],
        "rank": 1,
        "omega_bands_q": [berry, -berry],
        "omega_anti_q": berry,
        "omega_common_q": 0.0,
        "production_decision": "QUALIFIED_VALUE",
    }


def evidence(nominal=(1.0, 2.0), evaluated=None, berry=1.0):
    return {"rules": {"coarse_centroid": [{
        "rule": "coarse_centroid",
        "triangle_index": 0,
        "sample_index": 0,
        "nominal_q": list(nominal),
        "weight": 1.0,
        "result": result(evaluated or nominal, berry),
    }]}}


class C9Tests(unittest.TestCase):
    def test_missing_triangle_index_fails(self):
        value = evidence()
        del value["rules"]["coarse_centroid"][0]["triangle_index"]
        with self.assertRaises(ValueError):
            validate_logical_association(value)

    def test_missing_sample_index_fails(self):
        value = evidence()
        del value["rules"]["coarse_centroid"][0]["sample_index"]
        with self.assertRaises(ValueError):
            validate_logical_association(value)

    def test_wrong_rule_count_fails(self):
        with self.assertRaises(ValueError):
            validate_logical_association(evidence())

    def test_result_digest_changes_when_result_changes(self):
        a = add_result_bindings(evidence(), normalize_records(evidence()))[0]
        b_evidence = evidence(berry=2.0)
        b = add_result_bindings(b_evidence, normalize_records(b_evidence))[0]
        self.assertNotEqual(a["result_digest"], b["result_digest"])

    def test_association_trace_changes_for_nominal_and_evaluated_q(self):
        a_evidence = evidence()
        a = add_result_bindings(a_evidence, normalize_records(a_evidence))
        b_evidence = evidence(nominal=(1.0 + 2**-40, 2.0))
        b = add_result_bindings(b_evidence, normalize_records(b_evidence))
        c_evidence = evidence(evaluated=(1.0 + 2**-40, 2.0))
        c = add_result_bindings(c_evidence, normalize_records(c_evidence))
        self.assertNotEqual(build_compact_trace(a, "a", 1)["chunks"][0]["association_sha256"],
                            build_compact_trace(b, "a", 1)["chunks"][0]["association_sha256"])
        self.assertNotEqual(build_compact_trace(a, "a", 1)["chunks"][0]["association_sha256"],
                            build_compact_trace(c, "a", 1)["chunks"][0]["association_sha256"])

    def test_area_scaled_max_displacement_cross_check(self):
        self.assertAlmostEqual(max_dq_bound(10.0, 2.0), 20.0 / (3.0 ** 0.5))

    def test_direct_flux_uses_evaluated_result(self):
        value = evidence(evaluated=(1.0 + 2**-40, 2.0), berry=3.0)
        records = add_result_bindings(value, normalize_records(value))
        flux = direct_flux(records)
        self.assertEqual(flux["coarse_centroid"]["band1"], 3.0)

    def test_witness_selection_is_deterministic_and_bounded(self):
        value = {"rules": {rule: [{"rule": rule, "triangle_index": i, "sample_index": 0, "nominal_q": [float(i), 0.0], "weight": 1.0, "result": result((float(i), 0.0))}] for i, rule in enumerate(("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid"))}}
        records = add_result_bindings(value, normalize_records(value))
        first = witness_evidence(records, {})
        second = witness_evidence(records, {})
        self.assertEqual(first, second)
        self.assertLessEqual(first["record_count"], 64)
        self.assertTrue(first["records"][0]["physical_identity"])

    def test_source_sha_is_explicit(self):
        self.assertEqual(len(EXPECTED_SOURCE_SHA), 64)
        self.assertNotEqual(EXPECTED_SOURCE_SHA, "0" * 64)

    def test_compact_trace_contains_result_and_physical_binding(self):
        value = evidence()
        records = add_result_bindings(value, normalize_records(value))
        trace = build_compact_trace(records, "a" * 64, 1)
        self.assertEqual(trace["TOTAL_ASSOCIATION_COUNT"], 1)
        self.assertEqual(trace["chunks"][0]["record_count"], 1)
        self.assertEqual(trace["chunks"][0]["association_sha256"].__len__(), 64)

    def test_invalid_source_is_rejected_before_evidence_read(self):
        root = Path(__file__).parents[1]
        with tempfile.NamedTemporaryFile() as handle:
            handle.write(b"not the C7 source")
            handle.flush()
            from c9_source_bound import run
            with self.assertRaises(ValueError):
                run(Path(handle.name), root / "fixtures/c7_coordinate_audit.json",
                    root / "fixtures/c4_reduction_trace.json",
                    Path(handle.name), Path(handle.name), Path(handle.name),
                    Path(handle.name), Path(handle.name))


if __name__ == "__main__":
    unittest.main()
