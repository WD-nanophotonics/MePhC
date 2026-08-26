from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
LADDER = ROOT / "audit/e9f/qp_b_source_specific_gap_ladder.json"
CONTRACT = ROOT / "audit/e9f/qp_b_preregistered_validation_contract.json"
PLAN = ROOT / "audit/e9f/qp_b_native_execution_plan.json"
DECISION = ROOT / "audit/e9f/qp_b_science_decision.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_qp_b_preregistration_is_exact_solver_free_and_fail_closed_for_empty_above_bin() -> None:
    ladder = json.loads(LADDER.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    decision = json.loads(DECISION.read_text(encoding="utf-8"))
    assert ladder["threshold"] == 0.02
    assert ladder["bins"]["ABOVE_POLICY"]["status"] == "EMPTY_BIN"
    assert ladder["bins"]["NEAR_POLICY"]["count"] == 2 and ladder["bins"]["BELOW_POLICY"]["count"] == 4
    exact = {f"{item['grid_i']},{item['grid_j']}": item["gap"] for item in ladder["persistent_low_gap_population"]}
    assert exact == {"-34,-17":0.013482483999199102,"-34,-16":0.018428896349577062,"-34,16":0.01838056395569737,"-34,17":0.013443428678322489,"-5,0":0.016715192085324126,"-4,0":0.010594785956050956}
    recovered = ladder["finite_stencil_recoverable_identities"]
    assert recovered["status"] == "RECONSTRUCTED_FROM_RETAINED_D1_C1_EVIDENCE" and recovered["count"] == 11
    assert digest(ROOT / recovered["source_artifact"]) == recovered["source_sha256"]
    assert contract["resolution_ladder"] == ["R96","R128","R160"]
    assert "R192 may be proposed only for one preregistered sample" in contract["r192_escalation_rule"]
    assert "GAUGE_INVARIANT" in contract["identity_gates"] and "SOLVER_ORDER_INVARIANT" in contract["identity_gates"]
    assert plan["base_native_solve_budget"]["count"] == 36 and plan["optional_r192_escalation_budget"]["count"] == 2
    assert plan["execution"] == {"native_solves": 0, "mpb_execution": False}
    assert decision["primary_decision"] == "PREREGISTRATION_INCOMPLETE_MORE_EXISTING_EVIDENCE_RECOVERY_REQUIRED"
    assert decision["execution"] == {"native_solves": 0, "mpb_execution": False, "threshold_change": False}
