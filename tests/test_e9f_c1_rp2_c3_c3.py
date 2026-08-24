from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from audit.e9f import c3_c2_hardening as c2
from audit.e9f import c3_c3_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as science
from audit.e9f import run_e9f_c1_rp2_c3_c3 as runner

ROOT = Path(__file__).resolve().parents[1]
ROW = next(row for row in science.build_plan(ROOT) if row["sample_id"].endswith("::resolution=64"))


def binding():
    return runtime.expected_binding(row=ROW, execution_sha="e" * 40, contract_sha256="c" * 64, policy_sha256="p" * 64)


def fake_payload():
    expected = binding()
    points = [{"EVALUATED_Q": [0.1 + i * 0.001, 0.2], "RAW_FREQUENCIES_ALL6": [1, 2, 3, 3.5, 5, 6], "H_GATE": {"status": "MPB_H_ENVELOPE_QUALIFIED", "max_offdiag": 0.0, "selected_pair_offdiag": 0.0, "max_normalization_error": 0.0, "orthogonality_tolerance": 1e-10}, "L0": {}} for i in range(9)]
    payload = {"schema": runtime.PAYLOAD_SCHEMA, "project_id": "MEPHC", "work_order_id": runtime.WORK_ORDER, "phase": runtime.PHASE, "execution_sha": expected["execution_sha"], "source_sample_id": ROW["source_sample_id"], "source_sample_index": ROW["source_sample_index"], "logical_sample_index": ROW["sample_index"], "worker_id": ROW["sample_id"], "resolution": 64, "contract_sha256": expected["contract_sha256"], "rp1_policy_file_sha256": expected["rp1_policy_file_sha256"], "rp1_policy_canonical_semantic_sha256": expected["rp1_policy_canonical_semantic_sha256"], "payload_transport": "ATOMIC_FILE", "stencils": {"1/72": {"vertices": [{"x": i} for i in range(4)]}, "1/144": {"vertices": [{"x": i} for i in range(4)]}}, "all_point_metrics": points, "solve_count": 9, "replay_matched_point_count": 9, "replay_unmatched_point_count": 0, "diagnostic_only": True, "reducer_admissible": False, "c3_c3_transport_binding": expected}
    payload["payload_body_sha256"] = runtime.body_hash(payload)
    return payload, expected


def test_end_to_end_parent_publication_with_fake_payload(tmp_path):
    payload, expected = fake_payload()
    payload_path = tmp_path / "worker" / "payload.json"
    payload_path.parent.mkdir()
    payload_path.write_bytes(runtime.canonical(payload))
    measurement = {"payload_path": str(payload_path), "pid": 1, "return_code": 0, "direct_pid_gone": True, "orphan_pids": [], "orphan_count": 0}
    published = runtime.publish_artifacts(root=ROOT, runtime=tmp_path / "runtime", payload=payload, measurement=measurement, expected=expected, runner_sha256="r" * 64)
    assert all(Path(published[key]).is_file() for key in ("checkpoint_path", "result_path", "manifest_path"))
    assert published["payload_file_sha256"] != published["payload_body_sha256"]


def test_runner_sha_uses_actual_audit_path():
    actual = runtime.runner_path(ROOT, Path(runner.__file__))
    assert actual == Path(runner.__file__).resolve()
    assert runtime.sha(actual)


def test_runner_root_basename_path_mutation_rejected():
    with pytest.raises(ValueError, match="OUTSIDE_AUDIT"):
        runtime.runner_path(ROOT, ROOT / Path(runner.__file__).name)


def test_checkpoint_live_constructor_and_validator_agree(tmp_path):
    payload, expected = fake_payload()
    payload_path = tmp_path / "payload.json"
    payload_path.write_bytes(runtime.canonical(payload))
    checkpoint = runtime.construct_checkpoint(payload=payload, payload_path=payload_path, expected=expected)
    runtime.validate_checkpoint(checkpoint, payload_path=payload_path, expected=expected)


def test_payload_file_hash_and_body_hash_have_distinct_semantics(tmp_path):
    payload, expected = fake_payload()
    path = tmp_path / "payload.json"
    path.write_bytes(runtime.canonical(payload))
    assert runtime.sha(path) != payload["payload_body_sha256"]


def test_checkpoint_wrong_file_hash_rejected(tmp_path):
    payload, expected = fake_payload()
    path = tmp_path / "payload.json"
    path.write_bytes(runtime.canonical(payload))
    checkpoint = runtime.construct_checkpoint(payload=payload, payload_path=path, expected=expected)
    checkpoint["payload_file_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="FILE_HASH"):
        runtime.validate_checkpoint(checkpoint, payload_path=path, expected=expected)


def test_orphan_process_is_actually_detected():
    marker = "run_e9f_c1_rp2_c3_c3_worker.py"
    worker_id = "fake-worker-id"
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", marker, worker_id])
    try:
        found = []
        for _ in range(20):
            found = runtime.scan_orphans(worker_marker=marker, worker_id=worker_id)
            if process.pid in found:
                break
            time.sleep(0.05)
        assert process.pid in found
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_orphan_process_disappears_after_reap():
    marker = "run_e9f_c1_rp2_c3_c3_worker.py"
    worker_id = "fake-worker-id-after-reap"
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", marker, worker_id])
    process.terminate()
    process.wait(timeout=5)
    assert process.pid not in runtime.scan_orphans(worker_marker=marker, worker_id=worker_id)


def test_parent_rejects_bad_full6_H_gram():
    payload, expected = fake_payload(); payload["all_point_metrics"][0]["H_GATE"]["max_offdiag"] = 1.1e-10
    with pytest.raises(ValueError, match="full6"):
        runtime.validate_h_gates(payload)


def test_parent_rejects_bad_selected_pair_H_gram():
    payload, expected = fake_payload(); payload["all_point_metrics"][0]["H_GATE"]["selected_pair_offdiag"] = 1.1e-10
    with pytest.raises(ValueError, match="selected_pair"):
        runtime.validate_h_gates(payload)


def test_parent_rejects_bad_H_normalization():
    payload, expected = fake_payload(); payload["all_point_metrics"][0]["H_GATE"]["max_normalization_error"] = 1.1e-10
    with pytest.raises(ValueError, match="normalization"):
        runtime.validate_h_gates(payload)


def test_parent_transport_binding_wrong_execution_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["execution_sha"] = "wrong"
    with pytest.raises(ValueError, match="execution_sha"):
        runtime.validate_transport_binding(payload, expected)


def test_parent_transport_binding_wrong_worker_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["worker_id"] = "wrong"
    with pytest.raises(ValueError, match="worker_id"):
        runtime.validate_transport_binding(payload, expected)


def test_parent_transport_binding_wrong_contract_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["contract_sha256"] = "wrong"
    with pytest.raises(ValueError, match="contract_sha256"):
        runtime.validate_transport_binding(payload, expected)


def current_review():
    return json.loads((ROOT / "audit/e9f/c3_c3_process_reliability_review.json").read_text())


def test_closed_incident_retained_in_open_list_rejected():
    value = current_review(); value["incidents"][0]["CORRECTIVE_STATUS"] = "CLOSED"
    with pytest.raises(ValueError, match="OPEN_LIST"):
        c2.validate_process_review(value)


def test_open_incident_missing_from_open_list_rejected():
    value = current_review(); value["p1_items"] = value["p1_items"][1:]
    with pytest.raises(ValueError, match="OPEN_SET"):
        c2.validate_process_review(value)


def test_wrong_priority_incident_rejected():
    value = current_review(); value["p0_items"] = [value["p1_items"][0]]
    with pytest.raises(ValueError, match="OPEN_LIST"):
        c2.validate_process_review(value)


def test_duplicate_open_incident_rejected():
    value = current_review(); value["p1_items"] = value["p1_items"] + [value["p1_items"][0]]
    with pytest.raises(ValueError, match="DUPLICATE"):
        c2.validate_process_review(value)


def test_actual_current_process_review_validates():
    c2.validate_process_review(current_review())


def test_parent_transport_binding_wrong_source_sample_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["source_sample_id"] = "wrong"
    with pytest.raises(ValueError, match="source_sample_id"):
        runtime.validate_transport_binding(payload, expected)


def test_parent_transport_binding_wrong_logical_index_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["logical_sample_index"] = 99
    with pytest.raises(ValueError, match="logical_sample_index"):
        runtime.validate_transport_binding(payload, expected)


def test_parent_transport_binding_wrong_resolution_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["resolution"] = 96
    with pytest.raises(ValueError, match="resolution"):
        runtime.validate_transport_binding(payload, expected)


def test_parent_transport_binding_wrong_policy_rejected():
    payload, expected = fake_payload(); payload["c3_c3_transport_binding"]["rp1_policy_file_sha256"] = "wrong"
    with pytest.raises(ValueError, match="rp1_policy_file_sha256"):
        runtime.validate_transport_binding(payload, expected)
