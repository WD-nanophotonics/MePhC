from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).parents[1]
MATRIX=json.loads((ROOT/"audit/e9f/rp4_a_existing_evidence_matrix.json").read_text())
DECISION=json.loads((ROOT/"audit/e9f/rp4_a_science_decision.json").read_text())

def test_rp4_a_frozen_hashes_and_fail_closed_endpoint():
    assert MATRIX["authoritative_inputs"]["r160_execution_sha"]=="6fe10738d639f0f72987d0612442010339f719d9"
    assert MATRIX["authoritative_inputs"]["r160_result_sha256"]=="5456250e9da1555c603e96a593734d4938b9de4cc4791a3244ed64f3fe27c9da"
    assert MATRIX["original_17_band2_failures"]["persistent_true_low_gap_centers"]==[[-34,-17],[-34,-16],[-34,16],[-34,17],[-5,0],[-4,0]]
    assert MATRIX["source_bound_individual_band_outcomes"][2]["numeric_chern_forbidden"]

def test_rp4_a_unique_decision_and_no_execution():
    assert DECISION["primary_decision"]=="SOURCE_BOUND_BAND2_CLOSE_INCOMPLETE_UNDER_CURRENT_CONTRACT"
    assert DECISION["native_solve_count"]==0 and DECISION["mpb_execution"] is False
    assert DECISION["R192_CAN_CHANGE_CURRENT_REDUCER_ADMISSIBILITY"] is False
    assert "rank2_replacement" in DECISION["forbidden_for_incomplete_band2"]
