import json
from pathlib import Path

import pytest

from audit.e9f.rp1_policy import (
    RP1ContractError,
    validate_manifest_path_set,
    validate_policy_contract,
    validate_process_review_index,
)


ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "audit/e9f/rp1_recovery_policy_contract.json"


def test_rp1_contract_binds_immutable_d1_input_and_decision_tree():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    validate_policy_contract(contract, ROOT)
    assert contract["threshold_governance"]["current_min_external_gap"] == 0.02
    assert contract["reducer_firewall"]["band2_result_status_until_complete"] == "INCOMPLETE_NOT_REPORTED"


def test_rp1_contract_rejects_threshold_or_sample_mutation():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["threshold_governance"]["current_min_external_gap"] = 0.01
    with pytest.raises(RP1ContractError, match="THRESHOLD_GOVERNANCE_INVALID"):
        validate_policy_contract(contract, ROOT)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["immutable_inputs"]["failed_sample_records"] = []
    with pytest.raises(RP1ContractError, match="IMMUTABLE_FAILED_SAMPLE_RECORDS_MISMATCH"):
        validate_policy_contract(contract, ROOT)


def test_manifest_path_set_comparison_requires_manifest_path():
    manifest = {"changed_files": ["audit/e9f/rp1_policy.py", "audit/e9f/rp1_provenance_manifest.json"]}
    validate_manifest_path_set(manifest, manifest["changed_files"])
    with pytest.raises(RP1ContractError, match="MANIFEST_CHANGED_PATH_SET_MISMATCH"):
        validate_manifest_path_set(manifest, ["audit/e9f/rp1_policy.py"])


def test_process_review_index_must_cover_every_incident():
    review = {"incidents": [{"incident_id": "REL-020"}], "repository_or_workflow_defects": ["REL-020"]}
    validate_process_review_index(review)
    review["repository_or_workflow_defects"] = []
    with pytest.raises(RP1ContractError, match="PROCESS_REVIEW_DEFECT_INDEX_INCOMPLETE"):
        validate_process_review_index(review)
