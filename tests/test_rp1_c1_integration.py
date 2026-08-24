import json
import subprocess
from pathlib import Path

import pytest

from audit.infrastructure.campaign_runtime import validate_process_review
from audit.e9f.rp1_policy import validate_manifest_path_set, validate_policy_contract, validate_process_review_index

ROOT = Path(__file__).parents[1]

def _final_artifacts():
    paths = [ROOT / "audit/e9f/rp1_c2_result.json", ROOT / "audit/e9f/rp1_c2_process_reliability_review.json", ROOT / "audit/e9f/rp1_c2_provenance_manifest.json"]
    if not all(path.is_file() for path in paths):
        pytest.skip("RP1.C2 evidence descendant is created after implementation commit")
    return paths

def test_real_contract_and_c2_review_bind():
    _final_artifacts()
    contract = json.loads((ROOT / "audit/e9f/rp1_recovery_policy_contract.json").read_text(encoding="utf-8"))
    validate_policy_contract(contract, ROOT)
    review = json.loads((ROOT / "audit/e9f/rp1_c2_process_reliability_review.json").read_text(encoding="utf-8"))
    validate_process_review(review)
    validate_process_review_index(review)

def test_real_c2_manifest_matches_actual_git_diff():
    _final_artifacts()
    manifest = json.loads((ROOT / "audit/e9f/rp1_c2_provenance_manifest.json").read_text(encoding="utf-8"))
    actual = subprocess.check_output(["git", "diff", "--name-only", manifest["base_sandbox_sha"] + "...HEAD"], cwd=ROOT, text=True).splitlines()
    validate_manifest_path_set(manifest, actual)
    assert "audit/e9f/rp1_c2_provenance_manifest.json" in manifest["changed_files"]
