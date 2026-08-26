import json
from pathlib import Path
ROOT=Path(__file__).parents[1]
def test_qp_b_c2_materialized_smoke():
    a=ROOT/"audit"/"e9f"
    assert json.loads((a/"qp_b_c2_control_referenced_curvature_contract.json").read_text())["work_order_id"]=="MEPHC-E9F-C2-QP-B-C2-20260826-279"
    assert len(json.loads((a/"qp_b_c2_evidence_reuse_matrix.json").read_text())["sample_resolution_pairs"])==24
    assert json.loads((a/"qp_b_c2_incremental_native_budget.json").read_text())["native_solves_executed"]==0
    assert json.loads((a/"qp_b_c2_science_decision.json").read_text())["unique_primary_decision"] is True
