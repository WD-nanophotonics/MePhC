from pathlib import Path

import pytest

from audit.e9f import c3_c3_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c3 as runner
from tests.test_e9f_c1_rp2_c3_c3 import ROOT, binding, fake_payload


def test_checkpoint_payload_path_mutation_rejected(tmp_path):
    payload, expected = fake_payload()
    payload_path = tmp_path / "payload.json"
    payload_path.write_bytes(runtime.canonical(payload))
    checkpoint = runtime.construct_checkpoint(payload=payload, payload_path=payload_path, expected=expected)
    checkpoint["payload_path"] = str(tmp_path / "other.json")
    with pytest.raises(ValueError, match="PATH"):
        runtime.validate_checkpoint(checkpoint, payload_path=payload_path, expected=expected)


def test_checkpoint_malformed_payload_rejected(tmp_path):
    payload, expected = fake_payload()
    payload_path = tmp_path / "payload.json"
    payload_path.write_bytes(b"not-json\n")
    checkpoint = {"schema": runtime.CHECKPOINT_SCHEMA, **{key: expected[key] for key in ("project_id", "work_order_id", "phase", "execution_sha", "contract_sha256", "worker_id", "logical_sample_index", "resolution", "rp1_policy_file_sha256", "rp1_policy_canonical_semantic_sha256")}, "payload_file_sha256": runtime.sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "payload_path": str(payload_path), "artifact_schema": runtime.PAYLOAD_SCHEMA, "generation": 1}
    with pytest.raises(Exception):
        runtime.validate_checkpoint(checkpoint, payload_path=payload_path, expected=expected)


def test_parent_rejects_bad_H_status():
    payload, expected = fake_payload(); payload["all_point_metrics"][0]["H_GATE"]["status"] = "BAD"
    with pytest.raises(ValueError, match="status"):
        runtime.validate_h_gates(payload)


def test_parent_transport_binding_wrong_work_order_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["work_order_id"] = "wrong"
    with pytest.raises(ValueError, match="work_order_id"):
        runtime.validate_transport_binding(payload, expected)


def test_parent_transport_binding_wrong_phase_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["phase"] = "wrong"
    with pytest.raises(ValueError, match="phase"):
        runtime.validate_transport_binding(payload, expected)


def test_runner_relative_path_is_registered():
    assert str(runtime.RUNNER_RELATIVE_PATH).replace("\\", "/") == "audit/e9f/run_e9f_c1_rp2_c3_c3.py"
