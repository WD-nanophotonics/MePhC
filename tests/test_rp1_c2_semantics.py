import copy
import json
from pathlib import Path

import pytest

from audit.e9f.rp1_policy import (
    POLICY_CANONICAL_SEMANTIC_SHA256,
    POLICY_FILE_SHA256,
    RP1ContractError,
    canonical_semantic_sha256,
    validate_policy_contract,
)

ROOT = Path(__file__).parents[1]
PATH = ROOT / "audit/e9f/rp1_recovery_policy_contract.json"


def base_contract():
    return json.loads(PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutation,code", [
    (lambda c: c["l0_exact_output_contract"].update(qualification_decision_emitted=True), "L0_OUTPUT_CONTRACT_MUTATED"),
    (lambda c: c["l1_exact_shadow_contract"].update(association_quality_required=False), "L1_SHADOW_CONTRACT_MUTATED"),
    (lambda c: c["l2_exact_contract"].update(required_outputs=[]), "L2_CONTRACT_MUTATED"),
    (lambda c: c["l3_consistency_metric"].update(record_metric_only=False), "L3_METRIC_UNDEFINED_OR_MUTATED"),
    (lambda c: c["rp2_diagnostic_matrix"].update(diagnostic_only=False), "RP2_SEMANTIC_TERMINAL_MUTATED"),
    (lambda c: c["rp2_diagnostic_matrix"].update(terminal="SIX_POINTS_RECOVERED"), "RP2_SEMANTIC_TERMINAL_MUTATED"),
    (lambda c: c["source_anchor_firewall"].update(no_anchor_comparison_in_rp2_output=False), "SOURCE_ANCHOR_FIREWALL_INVALID"),
])
def test_supervisor_reproduced_mutations_fail_closed(mutation, code):
    mutated = base_contract()
    mutation(mutated)
    with pytest.raises(RP1ContractError, match=code):
        validate_policy_contract(mutated, ROOT)


def test_canonical_digest_catches_unanticipated_semantic_mutation():
    mutated = base_contract()
    mutated["rp2_semantic_gate"] = "changed_without_field_rule"
    assert canonical_semantic_sha256(mutated) != POLICY_CANONICAL_SEMANTIC_SHA256
    with pytest.raises(RP1ContractError, match="POLICY_CANONICAL_SEMANTIC_DIGEST_MISMATCH"):
        validate_policy_contract(mutated, ROOT)


def test_policy_file_and_canonical_sha_are_immutable():
    assert __import__("hashlib").sha256(PATH.read_bytes()).hexdigest() == POLICY_FILE_SHA256
    assert canonical_semantic_sha256(base_contract()) == POLICY_CANONICAL_SEMANTIC_SHA256


def test_low_gap_semantics_are_bound():
    contract = base_contract()
    assert contract["low_gap_policy"]["must_not_lower_threshold_to_qualify"] is True
    assert set(contract["low_gap_policy"]["required_distinction"]) == {
        "MATHEMATICAL_EXACT_DEGENERACY", "POSITIVE_SMALL_GAP", "NUMERICALLY_UNSTABLE_RANK1_STATE"
    }
