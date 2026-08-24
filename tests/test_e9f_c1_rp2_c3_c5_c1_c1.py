from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from audit.e9f import c3_c5_c1_postprocess as pp

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUNTIME = Path(os.environ.get("MEPHC_C3_C5_SOURCE_RUNTIME", "/home/icy/MePhC/.c3-c5-live2/audit/e9f/rp2_c3_c5_runtime_20260825_fix1"))
FAILURE_RUNTIME = Path(os.environ.get("MEPHC_C3_C5_FAILURE_RUNTIME", "/home/icy/MePhC/.c3-c5-live/audit/e9f/rp2_c3_c5_runtime_20260825"))
EVIDENCE = SOURCE_RUNTIME.parent / "rp2_evidence/workers"


@pytest.fixture(scope="module")
def source():
    return pp.verify_source_matrix(root=ROOT, source_runtime=SOURCE_RUNTIME)


def _prefix(source, count):
    checkpoint = copy.deepcopy(source["checkpoint"])
    checkpoint["completed_workers"] = checkpoint["completed_workers"][:count]
    checkpoint["generation"] = count
    return checkpoint


def test_failed_count_semantics_are_sealed():
    record = pp.create_failed_attempt_record(root=ROOT, failure_runtime=FAILURE_RUNTIME)
    assert record["sidecar_native_solve_count_raw"] == 0
    assert record["sidecar_native_solve_count_semantics"] == "INITIAL_VALUE_NOT_UPDATED_ON_IN_FUNCTION_EXCEPTION"
    assert record["measured_native_solve_count"] == "UNKNOWN"
    assert record["control_flow_inferred_completed_solves"] == 5
    assert record["traceback_confirms_dense_gauge_path"] is True
    assert record["payload_reused_by_final"] is False


def test_assignment_cardinality_and_mutations(source):
    entries = pp.complete_entries(source["payloads"], source["rows"])
    edges = [edge for entry in entries for edge in entry["association"]["edges"]]
    assert len(entries) == 24
    assert len(edges) == 96
    assert all(len(edge["assignment"]) == 2 for edge in edges)
    edge = copy.deepcopy(edges[0])
    window = [2, 3]
    for mutation in ("missing", "duplicate_left", "duplicate_right", "range", "inconsistent"):
        mutated = copy.deepcopy(edge)
        if mutation == "missing":
            mutated.pop("assignment")
        elif mutation == "duplicate_left":
            mutated["assignment"] = [[0, 0], [0, 1]]
        elif mutation == "duplicate_right":
            mutated["assignment"] = [[0, 0], [1, 0]]
        elif mutation == "range":
            mutated["assignment"] = [[0, 0], [2, 1]]
        else:
            mutated["assignment"] = [[1, 1], [0, 0]]
        with pytest.raises(ValueError):
            pp.validate_positional_assignment(mutated, window)


def test_replay_raw_multiplicity_and_real_mutations(source):
    summary = pp.replay_multiplicity(source["payloads"], EVIDENCE)
    assert summary["raw_record_count"] == 120
    assert summary["index_key_count"] == 108
    assert summary["expected_key_count"] == 108
    assert summary["duplicate_key_count"] == 12
    assert summary["duplicate_record_excess_count"] == 12
    assert summary["conflicting_duplicate_key_count"] == 0
    assert summary["coverage_valid"] is True
    index = pp.build_replay_index(EVIDENCE)
    expected = pp._expected_replay_keys(source["payloads"])
    mutations = []
    for mutation in ("missing", "resolution", "sample", "q", "execution"):
        changed = {key: [dict(item) for item in value] for key, value in index.items()}
        old = expected[0]
        if mutation == "missing":
            changed.pop(old)
        elif mutation == "resolution":
            changed[(old[0], 96 if old[1] == 64 else 64, old[2], old[3])] = changed.pop(old)
        elif mutation == "sample":
            changed[("WRONG_SOURCE", old[1], old[2], old[3])] = changed.pop(old)
        elif mutation == "q":
            changed[(old[0], old[1], (old[2][0] + 0.001, old[2][1]), old[3])] = changed.pop(old)
        else:
            changed[(old[0], old[1], old[2], "0" * 40)] = changed.pop(old)
        assert pp.validate_replay_index(source["payloads"], changed)["coverage_valid"] is False
        mutations.append(True)
    conflicting = {key: [dict(item) for item in value] for key, value in index.items()}
    conflicting[old][0]["frequencies"] = list(conflicting[old][0]["frequencies"])
    conflicting[old][0]["frequencies"][0] += 1e-6
    assert pp.validate_replay_index(source["payloads"], conflicting)["conflicting_duplicate_key_count"] > 0
    assert len(mutations) == 5


def test_resume_performs_real_proc_orphan_scan(source):
    row = source["rows"][0]
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "run_e9f_c1_rp2_c3_c5_worker.py", "--worker-id", row["sample_id"]])
    try:
        deadline = time.time() + 5
        while proc.poll() is None and not pp.scan_c3_c5_orphans(worker_ids=[row["sample_id"]]) and time.time() < deadline:
            time.sleep(0.05)
        assert proc.poll() is None
        assert pp.scan_c3_c5_orphans(worker_ids=[row["sample_id"]])
        with pytest.raises(ValueError, match="RESUME_BINDING_ORPHAN"):
            pp.resume_suffix(checkpoint=_prefix(source, 0), rows=source["rows"])
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    assert pp.scan_c3_c5_orphans(worker_ids=[row["sample_id"]]) == []
    assert len(pp.resume_suffix(checkpoint=_prefix(source, 0), rows=source["rows"])) == 12


@pytest.mark.parametrize("field", [
    "project_id", "work_order_id", "phase", "execution_sha", "source_sample_id",
    "source_sample_index", "logical_sample_index", "worker_id", "resolution",
    "contract_sha256", "rp1_policy_file_sha256", "rp1_policy_canonical_semantic_sha256",
    "payload_transport",
])
def test_resume_rejects_full_identity_mutations(source, tmp_path, field):
    checkpoint = _prefix(source, 3)
    item = checkpoint["completed_workers"][0]
    payload = json.loads(Path(item["payload_path"]).read_text())
    if field == "provider_resolution":
        payload["provider"]["resolution"] = 96 if payload["resolution"] == 64 else 64
    elif field == "transport_binding":
        payload["c3_c5_transport_binding"]["worker_id"] = "WRONG"
    else:
        payload[field] = 96 if field == "resolution" and payload["resolution"] == 64 else ("WRONG" if field not in {"source_sample_index", "logical_sample_index"} else 999)
    if field == "provider_resolution":
        pass
    elif field == "transport_binding":
        pass
    digest = pp.body_hash(payload)
    payload["payload_body_sha256"] = digest
    path = tmp_path / f"{field}.json"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    item["payload_path"] = str(path)
    item["payload_file_sha256"] = pp.sha(path)
    item["payload_body_sha256"] = digest
    with pytest.raises(ValueError):
        pp.resume_suffix(checkpoint=checkpoint, rows=source["rows"], orphan_scan=lambda ids: [])


def test_resume_provider_and_transport_mutations(source, tmp_path):
    for field in ("provider_resolution", "transport_binding"):
        checkpoint = _prefix(source, 3)
        item = checkpoint["completed_workers"][0]
        payload = json.loads(Path(item["payload_path"]).read_text())
        if field == "provider_resolution":
            payload["provider"]["resolution"] = 96 if payload["resolution"] == 64 else 64
        else:
            payload["c3_c5_transport_binding"]["worker_id"] = "WRONG"
        digest = pp.body_hash(payload)
        payload["payload_body_sha256"] = digest
        path = tmp_path / f"{field}.json"
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        item.update({"payload_path": str(path), "payload_file_sha256": pp.sha(path), "payload_body_sha256": digest})
        with pytest.raises(ValueError):
            pp.resume_suffix(checkpoint=checkpoint, rows=source["rows"], orphan_scan=lambda ids: [])


def test_canonical_process_registry_and_coordinated_mutations():
    registry = pp.canonical_c1_c1_process_registry()
    pp.validate_c1_c1_process_registry(registry)
    assert registry["p1_items"] == ["REL-021", "REL-042", "REL-050", "REL-051", "REL-052"]
    for incident in ("REL-021", "REL-042", "REL-050", "REL-051", "REL-052"):
        mutated = copy.deepcopy(registry)
        next(item for item in mutated["incidents"] if item["incident_id"] == incident)["status"] = "CLOSED"
        mutated["p1_items"].remove(incident)
        with pytest.raises(ValueError):
            pp.validate_c1_c1_process_registry(mutated)
    mutated = copy.deepcopy(registry)
    next(item for item in mutated["incidents"] if item["incident_id"] == "REL-022")["status"] = "OPEN"
    mutated["p2_items"] = ["REL-022"]
    with pytest.raises(ValueError):
        pp.validate_c1_c1_process_registry(mutated)
    closed = pp.canonical_c1_c1_process_registry(closed=True)
    pp.validate_c1_c1_process_registry(closed=closed, registry=closed)
