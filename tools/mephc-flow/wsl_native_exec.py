#!/home/icy/miniconda3/envs/mp/bin/python
"""Fixed WSL-side foreground process recorder used by mephc-flow."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

MAX_INLINE_RESULT_BYTES = 65536
MAX_RESULT_ARTIFACT_BYTES = 64 * 1024 * 1024
def atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def stream_stats(path: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def load_result(path: Path, expected_schema: str | None = None) -> tuple[dict, dict, list[str]]:
    """Load a fixed result artifact and derive a bounded Chat-facing summary."""
    if not path.is_file():
        raise ValueError("RESULT_FILE_MISSING")
    stats = stream_stats(path)
    if stats["size_bytes"] > MAX_RESULT_ARTIFACT_BYTES:
        raise ValueError("RESULT_ARTIFACT_TOO_LARGE")
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("RESULT_SUMMARY_INVALID")
    warnings = []
    if expected_schema and value.get("schema") != expected_schema:
        warnings.append("result_schema_mismatch")
    artifact = {"sha256": stats["sha256"], "size_bytes": stats["size_bytes"],
                "json_type": "object", "schema": value.get("schema")}
    if stats["size_bytes"] <= MAX_INLINE_RESULT_BYTES:
        return value, artifact, warnings
    summary = {}
    for name in sorted(value):
        item = value[name]
        if isinstance(item, (str, int, float, bool)) or item is None:
            encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(summary) < 32 and len(encoded) <= 2048:
                summary[name] = item
    summary.update({"result_externalized": True, "result_artifact_sha256": stats["sha256"],
                    "result_artifact_size_bytes": stats["size_bytes"],
                    "result_top_level_key_count": len(value)})
    warnings.append("result_summary_externalized")
    return summary, artifact, warnings


def finalize_child_result(
    record: dict, stdout_path: Path, stderr_path: Path, return_code: int,
    counters_path: Path | None = None, result_path: Path | None = None,
) -> dict:
    stdout = stream_stats(stdout_path)
    stderr = stream_stats(stderr_path)
    result = dict(record)
    result.update({
        "stdout_sha256": stdout["sha256"],
        "stdout_size_bytes": stdout["size_bytes"],
        "stderr_sha256": stderr["sha256"],
        "stderr_size_bytes": stderr["size_bytes"],
        "return_code": return_code,
        "completed_at": time.time(),
    })
    counters = {}
    if counters_path is not None and counters_path.is_file():
        try:
            candidate = json.loads(counters_path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                counters = candidate
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            counters = {"counter_error": "EXECUTION_COUNTER_STATE_INVALID"}
    for key in ("actual_provider_execution_count", "actual_solver_execution_count",
                "actual_dataset_record_count", "last_counter_update_at"):
        result[key] = counters.get(key, 0 if key != "last_counter_update_at" else None)
    if return_code != 0:
        result.update({"state": "failed", "result_error": "CHILD_RETURN_CODE_NONZERO"})
        return result
    try:
        if result_path is None or not result_path.is_file():
            raise ValueError("RESULT_FILE_MISSING")
        expected = record.get("expected_output", {}).get("result_schema")
        summary, artifact, warnings = load_result(result_path, expected)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result.update({"state": "failed", "result_error": str(exc)})
        result.pop("result_summary", None)
        return result
    result.update({"state": "succeeded", "result_summary": summary,
                   "result_artifact": artifact,
                   "result_warnings": warnings})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--input-bundle")
    parser.add_argument("--result-path")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
    state_path = Path(args.state)
    counters_path = state_path.with_suffix(".counters.json")
    value = json.loads(state_path.read_text(encoding="utf-8"))
    stdout_path = state_path.with_suffix(".stdout.log")
    stderr_path = state_path.with_suffix(".stderr.log")
    environment = os.environ.copy()
    environment["PATH"] = "/home/icy/miniconda3/envs/mp/bin:" + environment.get("PATH", "")
    environment["PYTHONPATH"] = args.checkout
    environment["MEPHC_SOURCE_COMMIT"] = Path(args.checkout).name
    if isinstance(value.get("provider_request_budget"), int):
        environment["MEPHC_PROVIDER_REQUEST_BUDGET"] = str(value["provider_request_budget"])
    if isinstance(value.get("solver_execution_budget"), int):
        environment["MEPHC_SOLVER_EXECUTION_BUDGET"] = str(value["solver_execution_budget"])
    if isinstance(value.get("science_contract_sha256"), str):
        environment["MEPHC_SCIENCE_CONTRACT_SHA256"] = value["science_contract_sha256"]
    if args.input_bundle:
        environment["MEPHC_INPUT_BUNDLE"] = args.input_bundle
    if args.result_path:
        result_path = Path(args.result_path)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        environment["MEPHC_RESULT_PATH"] = args.result_path
    initial_counters = {
        "schema": "mephc-native-execution-counters-v1",
        "actual_provider_execution_count": 0,
        "actual_solver_execution_count": 0,
        "actual_dataset_record_count": 0,
        "last_counter_update_at": time.time(),
    }
    atomic(counters_path, initial_counters)
    environment["MEPHC_EXECUTION_COUNTERS_PATH"] = str(counters_path)
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(argv, cwd=args.project, env=environment, shell=False,
                                       stdout=stdout, stderr=stderr)
            stat = Path(f"/proc/{process.pid}/stat").read_text(encoding="ascii").split()
            native_count = 1 if int(value.get("native_invocation_budget", 0)) > 0 else 0
            value.update({"state": "running", "process_started": True, "pid": process.pid,
                          "linux_start_ticks": stat[21], "started_at": time.time(),
                          "actual_native_invocation_count": native_count})
            atomic(state_path, value)
            return_code = process.wait()
    except OSError as exc:
        value.update({"state": "failed", "process_started": False,
                      "actual_native_invocation_count": 0,
                      "result_error": f"PROCESS_START_FAILED:{type(exc).__name__}",
                      "completed_at": time.time()})
        atomic(state_path, value)
        return 2
    final = finalize_child_result(
        value, stdout_path, stderr_path, return_code, counters_path,
        Path(args.result_path) if args.result_path else None,
    )
    final.pop("pid", None)
    final.pop("linux_start_ticks", None)
    atomic(state_path, final)
    return 0 if final["state"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
