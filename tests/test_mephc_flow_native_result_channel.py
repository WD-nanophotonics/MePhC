from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
HELPER = ROOT / "tools" / "mephc-flow" / "wsl_native_exec.py"


def load():
    spec = importlib.util.spec_from_file_location("native_result_channel", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_streams(tmp_path, stdout: bytes, stderr: bytes):
    out = tmp_path / "run.stdout.log"
    err = tmp_path / "run.stderr.log"
    out.write_bytes(stdout)
    err.write_bytes(stderr)
    return out, err


def summary():
    return {
        "science_contract_id": "E9F_C2_QP_B_C2_C3_R8_LOCKED_SET",
        "acquisition_source_commit": "a" * 40,
        "entrypoint_sha256": "b" * 64,
        "graph_sha256": "c" * 64,
        "logical_provider_demand_count": 216,
        "provider_request_count": 210,
        "cache_reuse_count": 0,
        "fresh_provider_execution_count": 210,
        "fresh_native_solver_execution_count": 210,
        "fresh_mpb_execution_observed": True,
        "mpb_execution_observed": True,
        "dataset_is_mpb_backed": True,
        "acquisition_dataset_id": "d" * 64,
        "acquisition_dataset_manifest_sha256": "e" * 64,
        "completed_key_count": 210,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "opaque_retention_namespace_id": "f" * 24,
    }


def line(value):
    return b"MEPHC_NATIVE_RESULT_JSON=" + json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_success_summary_is_durable_and_stream_metadata_is_bounded(tmp_path):
    helper = load()
    result = summary()
    stdout, stderr = write_streams(tmp_path, b"large-log\n" * 10000 + line(result) + b"\n", b"warning\n" * 100)
    state = helper.finalize_child_result({"state": "running", "process_started": True}, stdout, stderr, 0)
    assert state["state"] == "succeeded"
    assert state["result_summary"] == result
    assert state["stdout_size_bytes"] == stdout.stat().st_size
    assert state["stderr_size_bytes"] == stderr.stat().st_size
    assert state["stdout_sha256"]
    assert "large-log" not in json.dumps(state)


def test_missing_duplicate_malformed_and_oversized_summaries_fail_closed(tmp_path):
    helper = load()
    cases = [
        b"ordinary output\n",
        line(summary()) + b"\n" + line(summary()) + b"\n",
        b"MEPHC_NATIVE_RESULT_JSON={not-json}\n",
        b"MEPHC_NATIVE_RESULT_JSON=" + b"{\"x\":\"" + b"x" * 70000 + b"\"}\n",
    ]
    for index, content in enumerate(cases):
        directory = tmp_path / str(index)
        directory.mkdir()
        stdout, stderr = write_streams(directory, content, b"")
        state = helper.finalize_child_result({"state": "running"}, stdout, stderr, 0)
        assert state["state"] == "failed"
        assert "result_summary" not in state
        assert state["result_error"]


def test_nonzero_child_preserves_stream_hashes_without_success_summary(tmp_path):
    helper = load()
    stdout, stderr = write_streams(tmp_path, b"failure output", b"traceback")
    state = helper.finalize_child_result({"state": "running"}, stdout, stderr, 7)
    assert state["state"] == "failed"
    assert state["result_error"] == "CHILD_RETURN_CODE_NONZERO"
    assert "result_summary" not in state
    assert state["return_code"] == 7


def test_nonzero_child_preserves_actual_execution_counters(tmp_path):
    helper = load()
    stdout, stderr = write_streams(tmp_path, b"failed after solve", b"traceback")
    counters = tmp_path / "run.counters.json"
    counters.write_text(json.dumps({
        "actual_provider_execution_count": 1,
        "actual_solver_execution_count": 1,
        "actual_dataset_record_count": 0,
        "last_counter_update_at": 123.5,
    }), encoding="utf-8")
    state = helper.finalize_child_result({"state": "running"}, stdout, stderr, 7, counters)
    assert state["state"] == "failed"
    assert state["actual_provider_execution_count"] == 1
    assert state["actual_solver_execution_count"] == 1
    assert state["actual_dataset_record_count"] == 0
    assert state["last_counter_update_at"] == 123.5


def test_machine_contract_status_is_safe_but_identity_and_raw_state_are_not(tmp_path):
    helper = load()
    accepted = summary() | {"machine_contract_status": "PASS", "result_id": "r192-result"}
    stdout, _ = write_streams(tmp_path, line(accepted) + b"\n", b"")
    assert helper.extract_result_summary(stdout) == accepted

    rejected = [
        {"pid": 12}, {"process_id": 12}, {"username": "icy"}, {"user_name": "icy"},
        {"machine": "host"}, {"machine_name": "host"}, {"hostname": "host"},
        {"host_name": "host"}, {"path": "/home/icy/private"},
        {"path": "C:\\Users\\icywo\\private"}, {"normalized_vectors": [1]},
        {"raw_h": [1]}, {"payload_codec": "pickle"},
    ]
    for index, value in enumerate(rejected):
        path = tmp_path / f"unsafe-{index}.log"
        path.write_bytes(line(value) + b"\n")
        try:
            helper.extract_result_summary(path)
        except ValueError as exc:
            assert str(exc) == "RESULT_SUMMARY_UNSAFE"
        else:
            raise AssertionError(value)
