import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"

def load(name):
    with (AUDIT / name).open(encoding="utf-8") as f:
        return json.load(f)

def test_pair_gate_rows_are_separate():
    data = load("qp_b_c2_c3_r7_c1_pair_gate_matrix_v2.json")
    assert len(data["rows"]) == 15
    for row in data["rows"]:
        required = ("FINITE_DATA_STATUS","NONZERO_NORM_STATUS","H_REPRESENTATION_STATUS","ASSOCIATION_UNAMBIGUOUS_STATUS","OVERLAP_QUALIFIED_STATUS","PRINCIPAL_ANGLE_QUALIFIED_STATUS","PROJECTOR_DISTANCE_QUALIFIED_STATUS","FORWARD_REVERSE_CONSISTENT_STATUS","GAUGE_INVARIANT_STATUS","SOLVER_ORDER_INVARIANT_STATUS")
        assert all(key in row for key in required)
        assert len(row["missing_gate_evidence"]) == 4
        assert all(item["status"] == "MISSING_REQUIRES_NATIVE_RECOMPUTE" for item in row["missing_gate_evidence"])
        assert all(item["retention_id"] and len(item["retention_sha256"]) == 64 and item["pass_fail"] == "PASS" for item in row["direct_evidence"])

def test_dependencies_are_explicitly_unresolved():
    data = load("qp_b_c2_c3_r7_c1_provider_solve_dependencies_v2.json")
    assert len(data["reusable_dependencies"]) == 15
    assert len(data["historically_missing_dependencies"]) == 9
    assert data["mechanical_sum"] is None
    assert all(row["dependency_status"] == "UNRESOLVED_TRUE_INDISPENSABILITY_NOT_PROVEN" for row in data["reusable_dependencies"])
    assert all(len(row["required_new_sample_points"]) == 9 for row in data["reusable_dependencies"])

def test_fail_closed_no_science_execution():
    budget = load("qp_b_c2_c3_r7_c1_true_minimal_native_budget_v2.json")
    decision = load("qp_b_c2_c3_r7_c1_science_decision_v2.json")
    rel = load("qp_b_c2_c3_r7_c1_rel059_closure_or_open_record_v2.json")
    assert budget["minimum_proven_minimal"] is False
    assert budget["native_solves_executed"] == 0
    assert decision["primary_decision"] == "FAIL_CLOSED_TRUE_MINIMUM_NATIVE_BUDGET_REMAINS_UNRESOLVED"
    assert decision["native_validation_authorized"] is False
    assert decision["scientific_work_must_stop"] is True
    assert decision["mpb_execution"] is False
    assert rel["rel_059_status"] == "OPEN_P1"

def test_no_host_paths_or_raw_payloads():
    for name in ("qp_b_c2_c3_r7_c1_pair_gate_matrix_v2.json","qp_b_c2_c3_r7_c1_provider_solve_dependencies_v2.json","qp_b_c2_c3_r7_c1_true_minimal_native_budget_v2.json","qp_b_c2_c3_r7_c1_rel059_closure_or_open_record_v2.json","qp_b_c2_c3_r7_c1_science_decision_v2.json"):
        text = (AUDIT / name).read_text(encoding="utf-8")
        assert "/home/" not in text
        assert "C:\\" not in text
        assert "raw_payload" not in text.lower()
