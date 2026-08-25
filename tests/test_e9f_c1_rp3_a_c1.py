from pathlib import Path
import copy
import json

import pytest

from audit.e9f import c3_c5_runtime as c35
from audit.e9f import rp3_a_r128_runtime as rp3

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("/home/icy/MePhC/.rp3-a-r128-runtime-20260825-run2")
RESULT = json.loads((RUNTIME / "rp3_a_r128_result.json").read_text())
CONTRACT_SHA = c35.sha(ROOT / "audit/e9f/rp3_a_r128_execution_contract.json")
POLICY_SHA = c35.sha(ROOT / "audit/e9f/rp1_recovery_policy_contract.json")
EXECUTION = "39b63b80bf42d48e5b256dd1a211f6bec2585cd4"


def make_checkpoint(count):
    rows = rp3.build_plan(ROOT)
    by_worker = {row["sample_id"]: row for row in rows}
    payloads = {payload["worker_id"]: payload for payload in RESULT["payloads"]}
    measurements = {measurement["worker_id"]: measurement for measurement in RESULT["measurements"]}
    completed = []
    for generation, worker_id in enumerate(rp3.execution_order(rows)[:count], 1):
        row = by_worker[worker_id]
        payload = payloads[worker_id]
        measurement = measurements[worker_id]
        completed.append({"worker_id": worker_id, "source_sample_id": row["source_sample_id"], "logical_sample_index": row["sample_index"], "resolution": 128, "payload_path": measurement["payload_path"], "payload_file_sha256": measurement["payload_file_sha256"], "payload_body_sha256": measurement["payload_body_sha256"], "execution_sha": EXECUTION, "contract_sha256": CONTRACT_SHA, "policy_sha256": POLICY_SHA, "item_generation": generation, "terminal_payload_status": "COMPLETE"})
    return rp3.construct_checkpoint(completed=completed, rows=rows, execution_sha=EXECUTION, contract_sha256=CONTRACT_SHA, policy_sha256=POLICY_SHA), rows


@pytest.mark.parametrize("count,expected", [(0, 6), (1, 5), (3, 3), (6, 0)])
def test_resume_returns_exact_suffix_lengths(count, expected):
    checkpoint, rows = make_checkpoint(count)
    suffix = rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: [])
    assert len(suffix) == expected


def test_resume_default_performs_real_orphan_scan():
    checkpoint, rows = make_checkpoint(0)
    assert rp3.scan_rp3_orphans(rp3.execution_order(rows)) == []
    assert len(rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows)) == 6


@pytest.mark.parametrize("mutation", ["duplicate", "out_of_order", "skipped_prefix", "wrong_logical", "wrong_resolution", "wrong_execution", "wrong_contract", "wrong_policy", "wrong_generation", "missing_payload", "file_hash", "body_hash", "payload_identity", "orphan"])
def test_resume_mutations_fail_closed(tmp_path, mutation):
    checkpoint, rows = make_checkpoint(3)
    if mutation == "duplicate":
        checkpoint["completed_workers"][1] = copy.deepcopy(checkpoint["completed_workers"][0])
    elif mutation == "out_of_order":
        checkpoint["completed_workers"][0], checkpoint["completed_workers"][1] = checkpoint["completed_workers"][1], checkpoint["completed_workers"][0]
    elif mutation == "skipped_prefix":
        checkpoint["completed_workers"][0] = copy.deepcopy(make_checkpoint(1)[0]["completed_workers"][0])
        checkpoint["completed_workers"][0]["worker_id"] = rp3.execution_order(rows)[2]
    elif mutation == "wrong_logical":
        checkpoint["completed_workers"][0]["logical_sample_index"] = 99
    elif mutation == "wrong_resolution":
        checkpoint["completed_workers"][0]["resolution"] = 96
    elif mutation == "wrong_execution":
        checkpoint["completed_workers"][0]["execution_sha"] = "0" * 40
    elif mutation == "wrong_contract":
        checkpoint["completed_workers"][0]["contract_sha256"] = "0" * 64
    elif mutation == "wrong_policy":
        checkpoint["completed_workers"][0]["policy_sha256"] = "0" * 64
    elif mutation == "wrong_generation":
        checkpoint["generation"] = 2
    elif mutation == "missing_payload":
        checkpoint["completed_workers"][0]["payload_path"] = str(tmp_path / "missing")
    elif mutation == "file_hash":
        checkpoint["completed_workers"][0]["payload_file_sha256"] = "0" * 64
    elif mutation == "body_hash":
        checkpoint["completed_workers"][0]["payload_body_sha256"] = "0" * 64
    elif mutation == "payload_identity":
        item = checkpoint["completed_workers"][0]
        payload = json.loads(Path(item["payload_path"]).read_text())
        payload["resolution"] = 96
        payload["payload_body_sha256"] = c35.body_hash(payload)
        path = tmp_path / "mutated_payload.json"
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + chr(10))
        item["payload_path"] = str(path)
        item["payload_file_sha256"] = c35.sha(path)
        item["payload_body_sha256"] = payload["payload_body_sha256"]
    with pytest.raises(ValueError):
        if mutation == "orphan":
            rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: [12345])
        else:
            rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: [])


def test_rp3_c1_process_registry_reopens_and_closes_canonically():
    opened = rp3.canonical_rp3_a_c1_process_registry(closed=False)
    rp3.validate_rp3_a_c1_process_registry(opened, closed=False)
    assert len(opened["incidents"]) == 34
    assert opened["p1_items"] == ["REL-052", "REL-054"]
    closed = rp3.canonical_rp3_a_c1_process_registry(closed=True)
    rp3.validate_rp3_a_c1_process_registry(closed, closed=True)
    assert all(item["status"] == "CLOSED" for item in closed["incidents"])


def test_final_rp3_a_c1_process_seal_is_closed_and_bound():
    seal = json.loads((ROOT / "audit/e9f/rp3_a_c1_process_seal.json").read_text())
    registry = json.loads((ROOT / "audit/e9f/rp3_a_c1_process_reliability_registry.json").read_text())
    rp3.validate_rp3_a_c1_process_registry(registry, closed=True)
    assert seal["source_r128_execution_sha"] == EXECUTION
    assert seal["item_generation_exact_prefix_binding"] is True
    assert seal["process_registry_count"] == 34
    assert seal["process_registry_all_closed"] is True
    assert seal["rel_052_status"] == "CLOSED"
    assert seal["rel_054_status"] == "CLOSED"
    assert seal["native_solves_performed_by_c1"] == 0
    assert seal["pytest_node_count"] == 82
    assert seal["pytest_failed_count"] == 0


def test_item_generation_is_exact_prefix_position():
    checkpoint, rows = make_checkpoint(3)
    checkpoint["completed_workers"][0]["item_generation"] = 99
    with pytest.raises(ValueError):
        rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: [])
    checkpoint, rows = make_checkpoint(3)
    checkpoint["completed_workers"][0]["item_generation"], checkpoint["completed_workers"][1]["item_generation"] = 2, 1
    with pytest.raises(ValueError):
        rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: [])
    checkpoint, rows = make_checkpoint(3)
    checkpoint["completed_workers"][1]["item_generation"] = 1
    with pytest.raises(ValueError):
        rp3.resume_suffix(checkpoint=checkpoint, root=ROOT, rows=rows, orphan_scan=lambda ids: [])
