from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
PROVENANCE = ROOT / "audit/e9f/qp_a_threshold_provenance.json"
CONTRACT = ROOT / "audit/e9f/qp_a_threshold_validation_contract_draft.json"
DECISION = ROOT / "audit/e9f/qp_a_science_decision.json"


def test_qp_a_threshold_audit_is_solver_free_and_contract_complete() -> None:
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    decision = json.loads(DECISION.read_text(encoding="utf-8"))
    assert provenance["threshold"] == 0.02
    assert provenance["earliest_numeric_origin"]["commit"] == "f4929282b6efd300517010398054ad90fae16ca5"
    assert provenance["earliest_numeric_origin"]["path"] == "audit/e9c/human_reference_berry_contract.json"
    for path in provenance["evidence_paths"]:
        assert (ROOT / path).is_file(), path
    for item in [provenance["earliest_gate_concept"], provenance["earliest_numeric_origin"], provenance["e9f_contract_origin"]]:
        assert subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--verify", item["commit"]], text=True).strip() == item["commit"]
    assert provenance["classification"] == {
        "SOURCE_MANDATED_PROVEN": False,
        "PROJECT_SOURCE_REPRODUCTION_POLICY": True,
        "MATHEMATICALLY_REQUIRED_EXACT_0P02": False,
        "EMPIRICALLY_VALIDATED_SAFETY_MARGIN": False,
        "HISTORICAL_ENGINEERING_POLICY": True,
    }
    assert provenance["existing_diagnostics"]["persistent_low_gap_centers"] == [[-34,-17],[-34,-16],[-34,16],[-34,17],[-5,0],[-4,0]]
    required = {"exact-degeneracy fail-closed","avoided-crossing","solver-resolution convergence","local-stencil convergence","rank1 overlap singular values","principal angles and projector distances","association ambiguity","gauge-phase invariance","solver band-order permutation invariance","Berry-curvature convergence","integration-weight preservation","no missing-cell renormalization"}
    assert required <= set(contract["controlled_gap_ladder"]["controls"])
    assert contract["selects_new_threshold"] is False and contract["execution"] == {"native_solves": 0, "mpb_execution": False, "threshold_change": False}
    assert decision["primary_next_step_classification"] == "THRESHOLD_VALIDATION_CONTRACT_SHOULD_BE_EXECUTED"
    assert decision["more_native_solves_useful_before_policy_contract"] is False
    assert decision["full_six_point_r192_justified_before_policy_contract"] is False
    assert decision["targeted_minus4_0_r192_justified_before_policy_contract"] is False
    assert decision["targeted_minus5_0_r192_justified_before_policy_contract"] is False
    assert decision["frozen_endpoint"]["band2"].startswith("INCOMPLETE_NOT_REPORTED")
    assert decision["execution"] == {"native_solves": 0, "mpb_execution": False, "reducer_execution": False, "chern_execution": False, "threshold_change": False}
