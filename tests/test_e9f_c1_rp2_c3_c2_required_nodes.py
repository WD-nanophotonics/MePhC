from pathlib import Path

import pytest

from audit.e9f import c3_c2_hardening as hardening


def _identity(tmp_path):
    payload = tmp_path / "payload.json"
    payload.write_bytes(b"{}\n")
    digest = hardening.sha(payload)
    return payload, {"schema": "s", "project_id": "MEPHC", "work_order_id": "w", "execution_sha": "e", "contract_sha256": "c", "worker_id": "i", "logical_sample_index": 0, "resolution": 64, "payload_sha256": digest, "artifact_schema": "a", "generation": 1}


def test_checkpoint_rejects_wrong_execution_sha(tmp_path):
    payload, expected = _identity(tmp_path)
    actual = dict(expected, execution_sha="wrong")
    with pytest.raises(ValueError, match="IDENTITY"):
        hardening.validate_checkpoint(actual, expected=expected, payload_path=payload)


def test_checkpoint_rejects_wrong_worker_id(tmp_path):
    payload, expected = _identity(tmp_path)
    actual = dict(expected, worker_id="wrong")
    with pytest.raises(ValueError, match="IDENTITY"):
        hardening.validate_checkpoint(actual, expected=expected, payload_path=payload)


def test_current_process_review_artifact_is_fail_closed():
    import json
    path = Path(__file__).resolve().parents[1] / "audit/e9f/c3_c2_process_reliability_review.json"
    value = json.loads(path.read_text())
    hardening.validate_process_review(value)
