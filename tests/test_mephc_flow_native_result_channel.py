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


def streams(tmp_path):
    stdout, stderr = tmp_path / "stdout.log", tmp_path / "stderr.log"
    stdout.write_bytes(b"bounded diagnostic output\n")
    stderr.write_bytes(b"")
    return stdout, stderr


def write_result(path: Path, value) -> None:
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def test_fixed_result_file_is_canonical_bounded_and_schema_bound(tmp_path):
    helper = load()
    stdout, stderr = streams(tmp_path)
    result = tmp_path / "result.json"
    expected = {"schema": "thin-result-v1", "status": "PASS", "record_count": 1}
    write_result(result, expected)
    state = helper.finalize_child_result(
        {"state": "running", "expected_output": {"result_schema": "thin-result-v1"}},
        stdout, stderr, 0, result_path=result,
    )
    assert state["state"] == "succeeded"
    assert state["result_summary"] == expected
    assert state["stdout_sha256"] and state["stderr_sha256"]


def test_missing_malformed_oversized_and_wrong_schema_fail_closed(tmp_path):
    helper = load()
    stdout, stderr = streams(tmp_path)
    cases = [None, b"{not-json}", b"{\"x\":\"" + b"x" * 70000 + b"\"}",
             b'{"schema":"wrong"}']
    for index, content in enumerate(cases):
        result = tmp_path / f"result-{index}.json"
        if content is not None:
            result.write_bytes(content)
        state = helper.finalize_child_result(
            {"state": "running", "expected_output": {"result_schema": "thin-result-v1"}},
            stdout, stderr, 0, result_path=result,
        )
        assert state["state"] == "failed"
        assert state["result_error"]


def test_nonzero_child_preserves_counters_without_accepting_result(tmp_path):
    helper = load()
    stdout, stderr = streams(tmp_path)
    counters = tmp_path / "counters.json"
    counters.write_text(json.dumps({
        "actual_provider_execution_count": 1,
        "actual_solver_execution_count": 1,
        "actual_dataset_record_count": 0,
        "last_counter_update_at": 123.5,
    }), encoding="utf-8")
    state = helper.finalize_child_result(
        {"state": "running"}, stdout, stderr, 7, counters, tmp_path / "missing.json")
    assert state["state"] == "failed"
    assert state["result_error"] == "CHILD_RETURN_CODE_NONZERO"
    assert state["actual_provider_execution_count"] == 1
    assert state["actual_solver_execution_count"] == 1


def test_private_identity_and_raw_arrays_are_rejected(tmp_path):
    helper = load()
    stdout, stderr = streams(tmp_path)
    rejected = [{"schema": "thin-result-v1", "pid": 12},
                {"schema": "thin-result-v1", "path": "/home/icy/private"},
                {"schema": "thin-result-v1", "raw_h": [1]}]
    for index, value in enumerate(rejected):
        result = tmp_path / f"unsafe-{index}.json"
        write_result(result, value)
        state = helper.finalize_child_result(
            {"state": "running", "expected_output": {"result_schema": "thin-result-v1"}},
            stdout, stderr, 0, result_path=result,
        )
        assert state["state"] == "failed"
        assert state["result_error"] == "RESULT_SUMMARY_UNSAFE"
