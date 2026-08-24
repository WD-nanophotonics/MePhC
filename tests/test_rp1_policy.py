import json
from pathlib import Path

import pytest

from audit.e9f.rp1_policy import RP1ContractError, validate_manifest_path_set, validate_policy_contract, validate_process_review_index

ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "audit/e9f/rp1_recovery_policy_contract.json"

def test_rp1_contract_binds_immutable_d1_input_and_decision_tree():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    validate_policy_contract(contract, ROOT)

def test_rp1_contract_rejects_threshold_or_sample_mutation(tmp_path):
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["threshold_governance"]["current_min_external_gap"] = 0.01
    with pytest.raises(RP1ContractError):
        validate_policy_contract(contract, ROOT)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["immutable_inputs"]["failed_sample_records"] = []
    with pytest.raises(RP1ContractError):
        validate_policy_contract(contract, ROOT)

def test_manifest_path_set_comparison_requires_c2_manifest_path():
    manifest = {"changed_files": ["audit/e9f/rp1_policy.py", "audit/e9f/rp1_c2_provenance_manifest.json"]}
    validate_manifest_path_set(manifest, manifest["changed_files"])

def test_process_review_index_must_cover_every_incident():
    review = {"incidents": [{"incident_id": "REL-023"}], "repository_or_workflow_defects": ["REL-023"]}
    validate_process_review_index(review)
