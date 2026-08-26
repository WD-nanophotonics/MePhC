import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audit" / "e9f"
CHECKPOINT = ROOT / "audit" / "infrastructure" / "local_replica_archive" / "20260825" / "MePhC-C1-214" / "c1_live_checkpoint.json"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class QPBc1PreregisrationTests(unittest.TestCase):
    def test_qpa_qpb_are_frozen_and_controls_are_hash_bound(self):
        expected = {
  "audit/e9f/qp_a_threshold_provenance.json": "d939afe54db52bbd8b77ad8729af5682c55598bc9c891adb8d29c2ee3b38b039",
  "audit/e9f/qp_a_threshold_validation_contract_draft.json": "d14ffacd9d3028d0191e6bdc44cbf017f6cc48d10231707e1f845801897b7c33",
  "audit/e9f/qp_a_science_decision.json": "567979649bd780f589a02712cabc1e9d53697ed7fea0e3b2180d0407aabbfcf5",
  "audit/e9f/qp_b_source_specific_gap_ladder.json": "df62744cac947d50fae95bfb16217132c39836d3f0c9bb10b3fb108047cb7be7",
  "audit/e9f/qp_b_preregistered_validation_contract.json": "c6b2b8a7d3410bb09e5afd89a74b079c9840e918a740c763793f05af67780715",
  "audit/e9f/qp_b_native_execution_plan.json": "8fc991ffd4b9b6949643249ac6e94fbe54723e1a67805601ca54d80e1b1c61d3",
  "audit/e9f/qp_b_science_decision.json": "688ce07196cd355ab576baf37ad44fa18ae9719460cb585fcc01c711a80adf13"
}
        for rel, digest in expected.items():
            self.assertEqual(sha(ROOT / rel), digest)
        inventory = json.loads((AUDIT / "qp_b_c1_above_policy_candidate_inventory.json").read_text())
        self.assertEqual(sha(CHECKPOINT), "33d6f0a2eeacac23b71b302c0a2ddfbb1ba315d39a3db2cbf8ba72a55121ece2")
        self.assertEqual(inventory["source_checkpoint"]["sha256"], "33d6f0a2eeacac23b71b302c0a2ddfbb1ba315d39a3db2cbf8ba72a55121ece2")
        self.assertEqual(inventory["candidate_count"], 505)
        self.assertEqual(len(inventory["candidates"]), 505)
        defaults = inventory["candidate_field_defaults"]
        self.assertEqual(defaults["zero_based_band"], 2)
        self.assertEqual(defaults["deformation_fraction"], 0)
        self.assertEqual(defaults["source_estimator_identity"], "SOURCE_GRID_MIDPOINT_V1")
        self.assertIn("individual zero-based band 2", defaults["gap_semantics"])
        for row in inventory["candidates"]:
            self.assertGreaterEqual(row["external_gap"], 0.03)
            self.assertTrue(row["sample_id"].endswith("estimator=SOURCE_GRID"))
            self.assertEqual(row["public_q_coordinate"], [row["grid_i"] / 36, row["grid_j"] / 36])

    def test_completed_ladder_contract_budget_and_block_are_consistent(self):
        ladder = json.loads((AUDIT / "qp_b_c1_completed_gap_ladder.json").read_text())
        contract = json.loads((AUDIT / "qp_b_c1_completed_validation_contract.json").read_text())
        budget = json.loads((AUDIT / "qp_b_c1_native_budget.json").read_text())
        decision = json.loads((AUDIT / "qp_b_c1_science_decision.json").read_text())
        self.assertEqual(ladder["completed_locked_sample_count"], 8)
        self.assertEqual(ladder["bin_counts"], {"ABOVE_POLICY": 2, "NEAR_POLICY": 2, "BELOW_POLICY": 4})
        above = [x for x in ladder["locked_samples"] if x["bin"] == "ABOVE_POLICY"]
        self.assertEqual({x["sample_id"] for x in above}, {
            "fr=0;grid_i=-10;grid_j=-3;estimator=SOURCE_GRID",
            "fr=0;grid_i=-34;grid_j=9;estimator=SOURCE_GRID",
        })
        self.assertTrue(all(x["zero_based_band"] == 2 and x["external_gap"] >= 0.03 for x in above))
        self.assertEqual({x["location_class"] for x in above}, {"INTERIOR", "OUTER_OR_BOUNDARY_NEIGHBORHOOD"})
        self.assertEqual(contract["threshold"], 0.02)
        self.assertEqual(contract["curvature_numeric_criteria_status"], "INSUFFICIENT_BASIS")
        self.assertEqual(contract["existing_numeric_gate_thresholds"]["min_overlap_singular_value"], 0.9)
        self.assertEqual(contract["existing_numeric_gate_thresholds"]["max_principal_angle"], 0.45)
        self.assertEqual(contract["existing_numeric_gate_thresholds"]["max_projector_distance"], 0.3)
        self.assertEqual(contract["existing_numeric_gate_thresholds"]["h_orthogonality_tolerance"], 1e-10)
        self.assertEqual(contract["existing_numeric_gate_thresholds"]["h_normalization_tolerance"], 1e-14)
        self.assertEqual(budget["NATIVE_SOLVES_PER_SAMPLE_PER_RESOLUTION"], 9)
        self.assertEqual(budget["BASE_NATIVE_SOLVE_BUDGET"], 8 * 3 * 9)
        self.assertEqual(budget["OPTIONAL_R192_NATIVE_SOLVE_BUDGET"], 9)
        self.assertEqual(budget["TOTAL_MAX_NATIVE_SOLVE_BUDGET"], 225)
        self.assertFalse(budget["PRIOR_QP_B_BUDGET_FORMULA_CORRECT"])
        self.assertFalse(budget["execution_authorized"])
        self.assertEqual(decision["primary_decision"], "PREREGISTRATION_BLOCKED_BY_CURVATURE_CRITERIA_BASIS")
        self.assertEqual(decision["native_solves"], 0)
        self.assertFalse(decision["mpb_execution"])
        self.assertFalse(decision["threshold_change"])

if __name__ == "__main__":
    unittest.main()
