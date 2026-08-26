from __future__ import annotations
import json
import math
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"
CONTRACT = AUDIT / "qp_b_c2_control_referenced_curvature_contract.json"
MATRIX = AUDIT / "qp_b_c2_evidence_reuse_matrix.json"
BUDGET = AUDIT / "qp_b_c2_incremental_native_budget.json"
DECISION = AUDIT / "qp_b_c2_science_decision.json"
LADDER = AUDIT / "qp_b_c1_completed_gap_ladder.json"

LOCKED = [
    "fr=0;grid_i=-10;grid_j=-3;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=9;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=-16;estimator=SOURCE_GRID",
    "fr=0;grid_i=-6;grid_j=-1;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID",
    "fr=0;grid_i=-34;grid_j=17;estimator=SOURCE_GRID",
    "fr=0;grid_i=-5;grid_j=0;estimator=SOURCE_GRID",
    "fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID",
]
CONTROLS = {LOCKED[0], LOCKED[1]}
DIAGNOSTIC = LOCKED[3]
AVAILABLE = set(LOCKED[2:3] + LOCKED[4:])


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def srd(a, b):
    if a == 0 and b == 0:
        return 0.0
    return 2 * abs(a - b) / (abs(a) + abs(b))


def test_locked_identities_controls_and_diagnostic_role():
    ladder = load(LADDER)
    assert [row["sample_id"] for row in ladder["locked_samples"]] == LOCKED
    contract = load(CONTRACT)
    assert set(contract["calibration_controls"]) == CONTROLS
    assert len(contract["calibration_controls"]) == 2
    assert contract["stencil_diagnostic_sample"] == DIAGNOSTIC
    assert contract["frozen_inputs"]["threshold"] == 0.02
    assert contract["frozen_inputs"]["locked_sample_count"] == 8


def test_srd_exact_formula_and_contraction_contract():
    contract = load(CONTRACT)
    assert srd(0.0, 0.0) == 0.0
    assert math.isclose(srd(2.0, 1.0), 2.0 / 3.0)
    assert 0 <= srd(-1.0, 1.0) <= 2
    assert srd(-1.0, 1.0) != 0.0
    assert contract["srd_rule"]["range"] == [0, 2]
    assert contract["srd_rule"]["scale_free"] is True
    assert contract["srd_rule"]["sign_agreement_required"] is False
    assert contract["srd_rule"]["sign_reversal_automatic_pass"] is False
    assert contract["srd_rule"]["additive_denominator_floor"] is None
    assert contract["resolution_rule"]["contraction"] == "STEP_128_160[h] < STEP_96_128[h]"
    assert contract["resolution_rule"]["equal_nonzero_steps_pass"] is False
    assert contract["stencil_rule"]["contraction"] == "STENCIL_SRD_R160 < STENCIL_SRD_R128"


def test_reuse_matrix_counts_hash_binding_and_diagnostic_exclusion():
    matrix = load(MATRIX)
    pairs = matrix["sample_resolution_pairs"]
    assert len(pairs) == 24
    assert matrix["reusable_sample_resolution_pairs"] == 15
    assert matrix["context_only_sample_resolution_pairs"] == 0
    assert matrix["missing_sample_resolution_pairs"] == 9
    assert matrix["fresh_sample_resolution_pairs_required"] == 9
    assert {row["sample_id"] for row in pairs if row["classification"] == "REUSABLE_AUTHORITATIVE"} == AVAILABLE
    assert all(row["numeric_curvature_reusable"] for row in pairs if row["classification"] == "REUSABLE_AUTHORITATIVE")
    assert all(row["classification"] == "MISSING" for row in pairs if row["sample_id"] in CONTROLS | {DIAGNOSTIC})
    assert matrix["calibration_envelope_source_ids"] == sorted(CONTROLS)
    assert DIAGNOSTIC not in matrix["calibration_envelope_source_ids"]
    assert len(matrix["source_artifact_sha256"]) >= 5
    assert matrix["reuse_policy"]["old_srd_fields_not_required"] is True


def test_numeric_metrics_are_solver_free_postprocessing():
    matrix = load(MATRIX)
    metrics = matrix["numeric_metrics"]
    assert set(metrics) == AVAILABLE
    assert metrics["fr=0;grid_i=-34;grid_j=17;estimator=SOURCE_GRID"]["1/72"]["resolution_contraction_pass"] is True
    assert metrics["fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID"]["1/72"]["resolution_contraction_pass"] is False
    assert metrics["fr=0;grid_i=-34;grid_j=-16;estimator=SOURCE_GRID"]["stencil_contraction_pass"] is False


def test_identity_invariance_and_budget_fail_closed():
    matrix = load(MATRIX)
    assert matrix["identity_invariance_audit"]["numeric_curvature_reusable"] is True
    assert matrix["identity_invariance_audit"]["identity_evidence_complete"] is False
    assert matrix["identity_invariance_audit"]["invariance_evidence_complete"] is False
    assert all(not item["requires_additional_native_solves"] for item in matrix["invariant_gate_solver_free_audit"].values())
    budget = load(BUDGET)
    assert budget["minimum_fresh_base_native_solve_budget"] == 81
    assert budget["maximum_full_recompute_base_native_solve_budget"] == 216
    assert budget["optional_r192_native_solve_budget"] == 9
    assert budget["total_incremental_max_native_solve_budget"] == 90
    assert budget["additional_native_solves_required_by_invariance_gates"] is False
    assert budget["native_solves_executed"] == 0
    assert budget["mpb_execution"] is False


def test_unique_decision_threshold_and_zero_execution():
    contract = load(CONTRACT)
    assert contract["control_baseline"]["status"] == "INVALID"
    assert contract["control_baseline"]["global_validation_outcome"] == "INSUFFICIENT_EVIDENCE_REQUIRES_TARGETED_ESCALATION"
    assert contract["control_baseline"]["lower_threshold_evidence_claimed"] is False
    assert contract["identity_gate_thresholds"] == {
        "min_overlap_singular_value": 0.9,
        "max_principal_angle": 0.45,
        "max_projector_distance": 0.3,
        "h_orthogonality_tolerance": 1e-10,
        "h_normalization_tolerance": 1e-14,
        "other_tolerances": "preserve existing boolean/exact semantics; invent none",
    }
    decision = load(DECISION)
    assert decision["unique_primary_decision"] is True
    assert decision["primary_decision"] == "CONTROL_REFERENCED_CRITERIA_READY_BUT_EVIDENCE_REUSE_AUDIT_REQUIRES_CORRECTIVE"
    assert decision["current_0p02_threshold_unchanged"] is True
    assert decision["threshold_change"] is False
    assert decision["native_solves"] == 0
    assert decision["mpb_execution"] is False
    assert decision["production_mephc_change"] is False
    assert decision["main_promotion"] is False
