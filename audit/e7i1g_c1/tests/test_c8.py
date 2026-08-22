import json
import unittest
from pathlib import Path

from c8_perturbed_nodes import (
    moments,

    alias_report,
    audit_committed_evidence,
    classify_bound,
    normalize_records,
    provenance_trace,
)


def result(target=(1.0, 2.0), **overrides):
    value = {
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
        "omega_bands_q": [1.0, -1.0],
        "omega_anti_q": 0.5,
        "omega_common_q": 0.0,
        "production_decision": "QUALIFIED_VALUE",
    }
    value.update(overrides)
    return value


def row(rule, nominal, evaluated=None, weight_value=1.0, **overrides):
    value = {"nominal_q": list(nominal), "weight": weight_value,
             "result": result(evaluated or nominal)}
    value.update(overrides)
    return (rule, [value])


class C8Tests(unittest.TestCase):
    def test_exact_nodes_have_zero_weighted_perturbation(self):
        evidence = {"rules": dict(row(rule, (float(i), 0.0)) for i, rule in enumerate(
            ("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid")))}
        records = normalize_records(evidence)
        self.assertEqual(moments(records)["coarse_centroid"]["sum_abs_weight_dq"], 0.0)

    def test_nonzero_evaluated_q_is_preserved(self):
        evidence = {"rules": dict([row("coarse_centroid", (1.0, 2.0), (1.0 + 2**-40, 2.0))])}
        record = normalize_records(evidence)[0]
        self.assertEqual(record["evaluated_q"], (1.0 + 2**-40, 2.0))
        self.assertGreater(record["dq_norm"], 0.0)

    def test_weighted_moment_uses_absolute_weight(self):
        evidence = {"rules": {
            "coarse_centroid": [
                {"nominal_q": [0.0, 0.0], "weight": 2.0, "result": result((1e-3, 0.0))},
                {"nominal_q": [0.0, 0.0], "weight": -1.0, "result": result((2e-3, 0.0))},
            ]
        }}
        moment = moments(normalize_records(evidence))["coarse_centroid"]
        self.assertAlmostEqual(moment["sum_abs_weight_dq"], 0.004)
        self.assertAlmostEqual(moment["weighted_mean_dq"], 0.004 / 3.0)

    def test_alias_reuse_counts_each_nominal_weight(self):
        records = normalize_records({"rules": {
            "coarse_centroid": [
                {"nominal_q": [0.0, 0.0], "weight": 2.0, "result": result((1.0, 1.0))},
                {"nominal_q": [0.1, 0.0], "weight": 3.0, "result": result((1.0, 1.0))},
            ]
        }})
        report = alias_report(records)
        self.assertEqual(report["group_count"], 1)
        self.assertEqual(report["aliased_record_count"], 2)
        self.assertEqual(report["groups"][0]["weight"], 5.0)

    def test_classification_detects_larger_displacement(self):
        self.assertEqual(classify_bound(5e-5, 1.0, 1e-3), "SMALL")
        self.assertEqual(classify_bound(1e-2, 1.0, 1e-3), "TENSION")
        self.assertEqual(classify_bound(1e-8, 1.0, 0.0), "NOT_COMPARABLE")

    def test_provenance_digest_changes_for_coordinates(self):
        base = normalize_records({"rules": {
            "coarse_centroid": [{"nominal_q": [0.0, 0.0], "weight": 1.0, "result": result((0.0, 0.0))}]
        }})
        changed_nominal = normalize_records({"rules": {
            "coarse_centroid": [{"nominal_q": [2**-40, 0.0], "weight": 1.0, "result": result((0.0, 0.0))}]
        }})
        changed_evaluated = normalize_records({"rules": {
            "coarse_centroid": [{"nominal_q": [0.0, 0.0], "weight": 1.0, "result": result((2**-40, 0.0))}]
        }})
        self.assertNotEqual(provenance_trace(base)["source_digest"], provenance_trace(changed_nominal)["source_digest"])
        self.assertNotEqual(provenance_trace(base)["source_digest"], provenance_trace(changed_evaluated)["source_digest"])

    def test_compact_committed_trace_fails_closed(self):
        root = Path(__file__).parents[1]
        c7 = json.loads((root / "fixtures/c7_coordinate_audit.json").read_text())
        trace = json.loads((root / "fixtures/c4_reduction_trace.json").read_text())
        report = audit_committed_evidence(c7, trace)
        self.assertEqual(report["PERTURBED_NODE_ASSOCIATION"], "INCOMPLETE")
        self.assertEqual(report["BROAD_MPB_RECOMPUTATION_REQUIRED"], "UNRESOLVED")
        self.assertEqual(report["VALLEY_ASSIGNED_BERRY_FLUX_SEAL"], "FAIL_CLOSED")


if __name__ == "__main__":
    unittest.main()
