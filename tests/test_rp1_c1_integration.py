import json
import subprocess
from pathlib import Path

import pytest

from audit.infrastructure.campaign_runtime import validate_process_review
from audit.e9f.rp1_policy import validate_manifest_path_set, validate_policy_contract, validate_process_review_index


ROOT = Path(__file__).parents[1]


def _require_final_artifacts():
    paths = [ROOT / "audit/e9f/rp1_c1_result.json", ROOT / "audit/e9f/rp1_c1_process_reliability_review.json", ROOT / "audit/e9f/rp1_c1_provenance_manifest.json"]
    if not all(path.is_file() for path in paths):
        pytest.skip("RP1.C1 evidence descendant is created after implementation commit")
    return paths


def test_real_rp1_contract_and_process_review_artifacts_bind():
    _require_final_artifacts()
    contract = json.loads((ROOT / "audit/e9f/rp1_recovery_policy_contract.json").read_text(encoding="utf-8"))
    validate_policy_contract(contract, ROOT)
    review = json.loads((ROOT / "audit/e9f/rp1_c1_process_reliability_review.json").read_text(encoding="utf-8"))
    validate_process_review(review)
    validate_process_review_index(review)


def test_real_manifest_matches_actual_base_to_head_git_diff():
    _require_final_artifacts()
    path = ROOT / "audit/e9f/rp1_c1_provenance_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    actual = subprocess.check_output([
        "git", "diff", "--name-only", f"{manifest['base_sandbox_sha']}...HEAD"
    ], cwd=ROOT, text=True).splitlines()
    validate_manifest_path_set(manifest, actual)
    assert "audit/e9f/rp1_c1_provenance_manifest.json" in manifest["changed_files"]
