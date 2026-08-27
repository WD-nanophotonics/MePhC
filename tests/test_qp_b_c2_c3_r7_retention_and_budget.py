import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"

def load(name):
    with (AUDIT / name).open(encoding="utf-8") as f:
        return json.load(f)

def test_worker_reload_and_probe_are_infrastructure_only():
    data = load("qp_b_c2_c3_r7_worker_runtime_attestation.json")
    reload_data = data["retention_worker_reload"]
    assert reload_data["state"] == "RETENTION_WORKER_RELOAD_COMPLETED"
    assert reload_data["worker_restart_observed"] is True
    assert reload_data["source_commit_validation_active"] is True
    assert reload_data["raw_expected_head_indexing_active"] is False
    assert data["runtime_attestation_after_reload"]["coherent"] is True
    assert data["validation_only_probe"]["return_code"] == 0
    assert data["validation_only_probe"]["native_solve_count"] == 0
    assert data["validation_only_probe"]["mpb_executed"] is False

def test_inventory_has_exactly_nine_hash_bound_objects():
    data = load("qp_b_c2_c3_r7_exact_retention_inventory.json")
    assert data["terminal_state"] == "SUCCEEDED"
    assert data["search_incomplete"] is False
    assert data["duplicate_search_jobs"] == 0
    objects = data["exact_bindings"]
    assert len(objects) == 9
    assert all(o["match"] == "EXACT_SHA256" for o in objects)
    assert all(len(o["expected_sha256"]) == 64 for o in objects)
    assert all(o["actual_sha256"] == o["expected_sha256"] for o in objects)

def test_r96_mirror_is_not_used_as_authoritative_evidence():
    data = load("qp_b_c2_c3_r7_r96_recovery_classification.json")
    assert data["classification"] == "UNRESOLVED"
    assert data["rel_060"] == "NOT_REGISTERED"
    assert data["authoritative_retained_artifact"]["content_match"] == "EXACT_SHA256"

def test_evidence_preserves_pair_scope_and_fail_closed_rule():
    data = load("qp_b_c2_c3_r7_extracted_gate_evidence.json")
    assert len(data["policy_challenge_pairs"]) == 15
    assert len(data["historically_missing_pairs"]) == 9
    assert data["gate_classifications"]["CALIBRATION_CONTROLS"] == "MISSING_REQUIRES_NATIVE_RECOMPUTE"
    assert "No pair is promoted" in data["conservative_rule"]

def test_budget_accounting_is_explicit():
    data = load("qp_b_c2_c3_r7_minimal_native_budget.json")
    counts = data["counts"]
    assert counts["numerically_reusable_pairs"] == 15
    assert counts["gate_incomplete_reusable_pairs"] == 15
    assert counts["historically_missing_pairs"] == 9
    assert counts["fresh_native_required_pairs"] == 24
    assert counts["minimum_fresh_base_native_solve_budget"] == 216
    assert len(data["fresh_native_required_pairs"]) == counts["fresh_native_required_pairs"]
    assert len(set(data["fresh_native_required_pairs"])) == 24
    assert data["native_solve_count_executed"] == 0
    assert data["mpb_executed"] is False

def test_decision_is_bounded_and_no_science_escalation_occurred():
    data = load("qp_b_c2_c3_r7_science_decision.json")
    assert data["primary_decision"] == "READY_FOR_BOUNDED_NATIVE_VALIDATION_WITH_CORRECTED_BUDGET"
    assert data["global_validation_state"] == "NOT_YET_EXECUTED_INSUFFICIENT_CALIBRATION_DATA"
    assert data["threshold_decision_made"] is False
    assert data["reducer_started"] is False
    assert data["chern_started"] is False
    assert data["main_promotion"] is False

def test_artifacts_contain_no_host_paths_or_process_ids():
    files = [
        "qp_b_c2_c3_r7_worker_runtime_attestation.json",
        "qp_b_c2_c3_r7_exact_retention_inventory.json",
        "qp_b_c2_c3_r7_extracted_gate_evidence.json",
        "qp_b_c2_c3_r7_r96_recovery_classification.json",
        "qp_b_c2_c3_r7_minimal_native_budget.json",
        "qp_b_c2_c3_r7_incident_registry.json",
        "qp_b_c2_c3_r7_science_decision.json",
    ]
    for name in files:
        text = (AUDIT / name).read_text(encoding="utf-8")
        assert "/home/" not in text
        assert "C:\\" not in text
        assert '"pid"' not in text.lower()
