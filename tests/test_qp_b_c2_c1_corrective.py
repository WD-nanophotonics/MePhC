from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"
PROVENANCE = AUDIT / "qp_b_c2_c1_interleaved_provenance.json"
MATRIX = AUDIT / "qp_b_c2_c1_gate_recoverability_matrix.json"
BUDGET = AUDIT / "qp_b_c2_c1_incremental_budget_corrected.json"
DECISION = AUDIT / "qp_b_c2_c1_preregistration_finalization.json"

LOCKED = ["fr=0;grid_i=-10;grid_j=-3;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=9;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=-16;estimator=SOURCE_GRID","fr=0;grid_i=-6;grid_j=-1;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=17;estimator=SOURCE_GRID","fr=0;grid_i=-5;grid_j=0;estimator=SOURCE_GRID","fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID"]

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def test_provenance_fails_closed_without_invented_git_history():
    value = load(PROVENANCE)
    assert value["science_commit_sha_or_shas"] == []
    assert value["science_commit_parent_sha"] is None
    assert value["exact_history_recovery_status"] == "UNRESOLVED_FROM_TYPED_READ_ONLY_CONNECTOR"
    assert value["safety_classification"] == "PROVENANCE_UNRESOLVED_FAIL_CLOSED"

def test_all_locked_pairs_and_frozen_roles_unchanged():
    matrix = load(MATRIX)
    assert matrix["total_locked_sample_resolution_pairs"] == 24
    assert matrix["calibration_controls"] == LOCKED[:2]
    assert matrix["stencil_diagnostic_sample"] == LOCKED[3]
    assert matrix["policy_challenge_samples"] == LOCKED[2:3] + LOCKED[4:]
    assert len(matrix["sample_resolution_pairs"]) == 24
    assert matrix["frozen_threshold"] == 0.02
    assert matrix["frozen_locked_sample_count"] == 8

def test_every_pair_has_explicit_gate_recoverability_and_h_vector_audit():
    matrix = load(MATRIX)
    for pair in matrix["sample_resolution_pairs"]:
        assert pair["GATE_RECOVERABILITY_STATUS"] in {
            "ALREADY_AUTHORITATIVE",
            "DERIVABLE_SOLVER_FREE_FROM_HASH_BOUND_RETAINED_DATA",
            "NOT_DERIVABLE_REQUIRES_NATIVE_RECOMPUTE",
            "MISSING_PAIR_REQUIRES_NATIVE_EXECUTION",
        }
        assert pair["H_VECTORS_RETAINED"] is False
        assert pair["SUFFICIENT_FOR_OVERLAP_RECONSTRUCTION"] is False
        assert pair["SUFFICIENT_FOR_FORWARD_REVERSE_RECONSTRUCTION"] is False
        assert pair["SUFFICIENT_FOR_SOLVER_ORDER_CHECK"] is False
        assert pair["SUFFICIENT_FOR_GAUGE_PHASE_CHECK"] is False

def test_gate_audit_is_conservative_and_hash_bound():
    matrix = load(MATRIX)
    assert matrix["H_vector_audit"]["H_vectors_retained"] is False
    assert matrix["H_vector_audit"]["sufficient_for_overlap_reconstruction"] is False
    for gate in matrix["gate_decisions"].values():
        assert gate["retained_inputs"]
        assert all(item["path"] and item["sha256"] for item in gate["retained_inputs"])
    assert all(
        not item["requires_additional_native_solves"]
        for name, item in matrix["gate_decisions"].items()
        if name == "FINITE_DATA"
    )
    assert all(
        item["requires_additional_native_solves"]
        for name, item in matrix["gate_decisions"].items()
        if name != "FINITE_DATA"
    )

def test_budget_corrects_undercount_without_authorizing_execution():
    budget = load(BUDGET)
    assert budget["numerically_reusable_pairs"] == 15
    assert budget["fully_gate_complete_pairs"] == 0
    assert budget["solver_free_gate_recoverable_pairs"] == 0
    assert budget["native_recompute_required_pairs"] == 15
    assert budget["missing_pair_requires_native_execution_pairs"] == 9
    assert budget["fresh_sample_resolution_pairs_required"] == 24
    assert budget["minimum_fresh_base_native_solve_budget"] == 216
    assert budget["maximum_full_recompute_base_native_solve_budget"] == 216
    assert budget["optional_r192_native_solve_budget"] == 9
    assert budget["total_incremental_max_native_solve_budget"] == 225
    assert budget["additional_native_solves_required_by_invariance_gates"] is True
    assert budget["native_solves_executed"] == 0
    assert budget["mpb_execution"] is False

def test_decision_fails_closed_and_preserves_scope():
    decision = load(DECISION)
    assert decision["prospective_control_baseline_status"] == "NOT_YET_EVALUABLE_MISSING_NATIVE_EVIDENCE"
    assert decision["historical_status_correction"] == "PREMATURE_PRE_EXECUTION_CLASSIFICATION_SUPERSEDED"
    assert decision["primary_decision"] == "FAIL_CLOSED_PROVENANCE_OR_GATE_EVIDENCE_INSUFFICIENT"
    assert decision["unique_primary_decision"] is True
    assert decision["current_0p02_threshold_unchanged"] is True
    assert decision["threshold_change"] is False
    assert decision["native_solves"] == 0
    assert decision["mpb_execution"] is False
    assert decision["main_unchanged"] is True
    assert decision["rel_059_registered"] is True
