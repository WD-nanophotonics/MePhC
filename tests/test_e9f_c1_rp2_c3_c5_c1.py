from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from audit.e9f import c3_c5_c1_postprocess as pp

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUNTIME = Path(os.environ.get("MEPHC_C3_C5_SOURCE_RUNTIME", "/home/icy/MePhC/.c3-c5-live2/audit/e9f/rp2_c3_c5_runtime_20260825_fix1"))
FAILURE_RUNTIME = Path(os.environ.get("MEPHC_C3_C5_FAILURE_RUNTIME", "/home/icy/MePhC/.c3-c5-live/audit/e9f/rp2_c3_c5_runtime_20260825"))


@pytest.fixture(scope="module")
def source():
    if not SOURCE_RUNTIME.exists():
        pytest.skip("immutable C3.C5 source runtime is not mounted")
    return pp.verify_source_matrix(root=ROOT, source_runtime=SOURCE_RUNTIME)


def test_source_matrix_binding_is_fail_closed(source):
    assert len(source["payloads"]) == 12
    assert sum(payload["resolution"] == 64 for payload in source["payloads"]) == 6
    assert sum(payload["resolution"] == 96 for payload in source["payloads"]) == 6
    assert sum(payload["replay_matched_point_count"] for payload in source["payloads"]) == 108


def test_checkpoint_is_generation_12_ordered_and_complete(source):
    checkpoint = source["checkpoint"]
    assert checkpoint["generation"] == 12
    assert [item["worker_id"] for item in checkpoint["completed_workers"]] == [payload["worker_id"] for payload in source["payloads"]]


def test_complete_entry_schema_has_all_24_entries_and_nested_evidence(source):
    entries = pp.complete_entries(source["payloads"], source["rows"])
    assert len(entries) == 24
    for entry in entries:
        assert len(entry["VERTEX_L0"]) == 4
        assert len(entry["association"]["edges"]) == 4
        assert len(entry["BAND2"]["edges"]) == 4
        assert len(entry["BAND3"]["edges"]) == 4
        assert len(entry["L2"]["edges"]) == 4
        assert entry["CENTER_L0"] and entry["VERTEX_L0"]


def test_complete_delta_tables_have_24_plus_24_and_reproduce_old_subset(source):
    stencil, resolution, old_ok = pp.delta_tables(source["payloads"], source["rows"], source["result"]["deltas"])
    assert len(stencil) == 24
    assert len(resolution) == 24
    assert old_ok
    assert all(item["delta_abs"] == abs(item["delta_signed"]) for item in [*stencil, *resolution])


def test_safe_projector_dense_equivalence_and_no_dense_path():
    result = pp.safe_projector_regression(ROOT)
    assert result["dense_equivalence"] is True
    assert result["max_abs_error"] <= 1e-12
    assert result["no_dense_nxn"] is True
    assert result["rank2_production_qualification_path_unchanged"] is True


def test_replay_index_has_exact_108_keys_and_mutations_fail(source):
    evidence = ROOT / "audit/e9f/rp2_evidence/workers"
    if not evidence.exists():
        pytest.skip("immutable RP2 evidence is not mounted")
    result = pp.replay_coverage(source["payloads"], evidence)
    assert result == {"expected_key_count": 108, "index_key_count": result["index_key_count"], "coverage_valid": True, "mutation_tests": True}


def _checkpoint_prefix(source, count):
    cp = copy.deepcopy(source["checkpoint"])
    cp["completed_workers"] = cp["completed_workers"][:count]
    cp["generation"] = count
    return cp


def test_resume_planner_returns_expected_suffixes(source):
    rows = source["rows"]
    assert len(pp.resume_suffix(checkpoint=_checkpoint_prefix(source, 0), rows=rows)) == 12
    assert [row["sample_index"] for row in pp.resume_suffix(checkpoint=_checkpoint_prefix(source, 3), rows=rows)] == list(range(3, 12))
    assert pp.resume_suffix(checkpoint=_checkpoint_prefix(source, 12), rows=rows) == []


@pytest.mark.parametrize("mutation", ["duplicate", "out_of_order", "generation", "execution", "contract", "policy", "missing_payload", "file_hash", "body_hash"])
def test_resume_planner_rejects_adversarial_checkpoint(mutation, source, tmp_path):
    cp = _checkpoint_prefix(source, 3)
    if mutation == "duplicate": cp["completed_workers"][1] = copy.deepcopy(cp["completed_workers"][0])
    elif mutation == "out_of_order": cp["completed_workers"][0], cp["completed_workers"][1] = cp["completed_workers"][1], cp["completed_workers"][0]
    elif mutation == "generation": cp["generation"] = 2
    elif mutation == "execution": cp["execution_sha"] = "0" * 40
    elif mutation == "contract": cp["contract_sha256"] = "0" * 64
    elif mutation == "policy": cp["rp1_policy_file_sha256"] = "0" * 64
    elif mutation == "missing_payload": cp["completed_workers"][0]["payload_path"] = str(tmp_path / "missing")
    elif mutation == "file_hash": cp["completed_workers"][0]["payload_file_sha256"] = "0" * 64
    elif mutation == "body_hash": cp["completed_workers"][0]["payload_body_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        pp.resume_suffix(checkpoint=cp, rows=source["rows"])


def test_resume_planner_rejects_orphans(source):
    with pytest.raises(ValueError, match="RESUME_BINDING"):
        pp.resume_suffix(checkpoint=_checkpoint_prefix(source, 0), rows=source["rows"], orphan_pids=[1234])


@pytest.mark.parametrize("incident_id", ["REL-022", "REL-025", "REL-034", "REL-035"])
def test_process_registry_historical_p2_priority_mutation_rejected(incident_id):
    registry = pp.process_registry()
    registry["incidents"] = [dict(item, priority=("P1" if item["incident_id"] == incident_id else item["priority"])) for item in registry["incidents"]]
    with pytest.raises(ValueError, match="PROCESS_REGISTRY"):
        pp.validate_process_registry(registry)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "status", "open_list"])
def test_process_registry_closed_world_mutations_rejected(mutation):
    registry = pp.process_registry()
    if mutation == "missing": registry["incidents"] = registry["incidents"][1:]
    elif mutation == "extra": registry["incidents"].append({"incident_id":"REL-999","priority":"P1","status":"CLOSED"})
    elif mutation == "duplicate": registry["incidents"].append(copy.deepcopy(registry["incidents"][0]))
    elif mutation == "status": registry["incidents"][0]["status"] = "UNKNOWN"
    elif mutation == "open_list": registry["p1_items"].append("REL-022")
    with pytest.raises(ValueError, match="PROCESS_REGISTRY"):
        pp.validate_process_registry(registry)


def test_process_registry_is_33_ids_and_expected_open_set():
    registry = pp.process_registry()
    pp.validate_process_registry(registry)
    assert len(registry["incidents"]) == 33
    assert set(registry["p1_items"]) == set(pp.OPEN_P1)


def test_failed_initial_attempt_record_is_immutable_and_payload_not_reused():
    if not FAILURE_RUNTIME.exists():
        pytest.skip("retained 87eb failure runtime is not mounted")
    record = pp.create_failed_attempt_record(root=ROOT, failure_runtime=FAILURE_RUNTIME)
    assert record["failed_execution_sha"] == pp.FAILED_EXECUTION
    assert record["exception_type"] == "MemoryError"
    assert record["payload_reused_by_final"] is False
    assert record["scientific_payload_reuse_conclusion"].endswith("false")
