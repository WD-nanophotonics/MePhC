from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).parents[1]
AUDIT=ROOT/"audit"/"e9f"
PROVENANCE=AUDIT/"qp_b_c2_c2_supervisor_resolved_provenance.json"
INVENTORY=AUDIT/"qp_b_c2_c2_authoritative_raw_artifact_inventory.json"
MATRIX=AUDIT/"qp_b_c2_c2_gate_scope_and_evidence_matrix.json"
BUDGET=AUDIT/"qp_b_c2_c2_incremental_budget_final.json"
DECISION=AUDIT/"qp_b_c2_c2_science_decision.json"
FROZEN_CONTRACT=AUDIT/"qp_b_c2_control_referenced_curvature_contract.json"
LOCKED_IDS=["fr=0;grid_i=-10;grid_j=-3;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=9;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=-16;estimator=SOURCE_GRID","fr=0;grid_i=-6;grid_j=-1;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID","fr=0;grid_i=-34;grid_j=17;estimator=SOURCE_GRID","fr=0;grid_i=-5;grid_j=0;estimator=SOURCE_GRID","fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID"]

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def test_supervisor_provenance_is_materialized_exactly():
    value=load(PROVENANCE)
    assert value["science_commit_sha_or_shas"] == ["aede3467cc0fbfa4f1bdad115566569dbd30b47a","cb8e4216404fc7da1ceff5ad97c2e923874f7c78"]
    assert value["historical_range"]["total_commits"] == 53
    assert value["excluded_interleaved_infrastructure_commit_count"] == 51
    assert value["science_commit_descends_from_9ee6"] is True
    assert value["historical_qp_b_c2_artifacts_unchanged"] is True
    contract=load(FROZEN_CONTRACT)
    assert contract["frozen_inputs"]["locked_sample_identity_unchanged"] is True
    actual=(contract["calibration_controls"]+contract["policy_challenge_samples"]+[contract["stencil_diagnostic_sample"]])
    assert set(actual) == set(LOCKED_IDS)
    assert len(actual) == 8

def test_raw_artifact_inventory_is_hash_bound_and_fail_closed():
    value=load(INVENTORY)
    assert len(value["artifacts"]) == 9
    assert value["search_exhausted_for_committed_and_retention_records"] is True
    assert value["exact_raw_content_accessible_via_typed_surface"] is False
    assert any(item["matches_expected"] is False for item in value["artifacts"] if item["resolution"]=="R96")
    assert all(item["immutable_or_hash_bound"] is True for item in value["artifacts"])

def test_all_locked_pairs_preserve_numeric_reuse_without_gate_inference():
    value=load(MATRIX)
    counts=value["counts"]
    assert counts["total_locked_sample_resolution_pairs"] == 24
    assert counts["numerically_reusable_pairs"] == 15
    assert counts["sample_local_gate_complete_pairs"] == 0
    assert len(value["sample_resolution_pairs"]) == 15
    assert all(item["NUMERIC_CURVATURE_REUSABLE"] is True for item in value["sample_resolution_pairs"])
    assert all(item["NATIVE_RECOMPUTE_REQUIRED"] is True for item in value["sample_resolution_pairs"])
    assert value["no_inference_from_compact_traces"] is True
    contract=load(FROZEN_CONTRACT)
    assert {item["sample_id"] for item in value["sample_resolution_pairs"]} == set(contract["policy_challenge_samples"])
    assert {item["resolution"] for item in value["sample_resolution_pairs"]} == {"R96","R128","R160"}
    assert all(item["RAW_H_VECTOR_REQUIRED_GATES"] for item in value["sample_resolution_pairs"])
    assert all("<" not in item["NUMERIC_SOURCE_PATH_OR_RETENTION_ID"] for item in value["sample_resolution_pairs"])

def test_gate_scope_is_contractual_not_outcome_dependent():
    value=load(MATRIX)
    assert value["gate_scope_decisions"]["GAUGE_INVARIANT"]["FROZEN_SCOPE"] == "IMPLEMENTATION_LEVEL"
    assert value["gate_scope_decisions"]["SOLVER_ORDER_INVARIANT"]["FROZEN_SCOPE"] == "IMPLEMENTATION_LEVEL"
    assert value["implementation_level_scope"]["GAUGE_INVARIANT"]["ADDITIONAL_NATIVE_SOLVES_REQUIRED"] is False
    assert value["implementation_level_scope"]["SOLVER_ORDER_INVARIANT"]["ADDITIONAL_NATIVE_SOLVES_REQUIRED"] is False

def test_budget_is_conservative_and_zero_execution():
    value=load(BUDGET)
    assert value["minimum_fresh_native_budget_under_actual_gate_deficits"] == 216
    assert value["conservative_full_24_pair_recompute_budget"] == 216
    assert value["optional_r192_native_solve_budget"] == 9
    assert value["total_incremental_max_native_solve_budget"] == 225
    assert value["additional_native_solves_required_by_invariance_gates"] is False
    assert value["native_solves_executed"] == 0 and value["mpb_execution"] is False

def test_decision_fail_closed_and_scope_preserved():
    value=load(DECISION)
    assert value["QP_B_C2_C2_PRIMARY_DECISION"] == "FAIL_CLOSED_RAW_EVIDENCE_OR_GATE_SCOPE_REMAINS_UNRESOLVED"
    assert value["supervisor_provenance_materialized"] is True
    assert value["rel_059_status"] == "OPEN_P1"
    assert value["current_threshold"] == 0.02
    assert value["threshold_change"] is False
    assert value["native_solves"] == 0 and value["mpb_execution"] is False
    assert value["main_unchanged"] is True
