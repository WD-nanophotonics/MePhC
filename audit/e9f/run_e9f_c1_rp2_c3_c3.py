"""C3.C3 parent: complete prelive gates and exactly one new R64 canary."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from audit.e9f import c3_c2_hardening as c2
from audit.e9f import c3_c3_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as c2_science

WORKER = Path("audit/e9f/run_e9f_c1_rp2_c3_c3_worker.py")
CONTRACT = Path("audit/e9f/rp2_c3_c3_execution_contract.json")
FAILURE_RECORD = Path("audit/e9f/rp2_c3_c3_failed_parent_record.json")
POLICY_REL = c2_science.POLICY_REL


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(runtime.canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def tail(data: bytes) -> str:
    return data[-65536:].decode(errors="replace")


def load_contract(root: Path) -> dict[str, Any]:
    contract = json.loads((root / CONTRACT).read_text())
    if contract.get("work_order_id") != runtime.WORK_ORDER or contract.get("parent_failed_execution_sha") != runtime.FAILED_PARENT_EXECUTION_SHA or contract.get("runner_relative_path") != str(runtime.RUNNER_RELATIVE_PATH).replace("\\", "/"):
        raise ValueError("C3_C3_CONTRACT_IDENTITY_INVALID")
    if contract.get("expected_native_solves") != 9 or contract.get("canary_resolution") != 64:
        raise ValueError("C3_C3_CONTRACT_CANARY_INVALID")
    return contract


def run_prelive(root: Path) -> dict[str, Any]:
    tests = ["tests/test_e9f_c1_rp2_c3_c2.py", "tests/test_e9f_c1_rp2_c3_c2_required_nodes.py", "tests/test_e9f_c1_rp2_c3_c3.py", "tests/test_e9f_c1_rp2_c3_c3_required_nodes.py"]
    c2.validate_process_review(json.loads((root / "audit/e9f/c3_c3_process_reliability_review.json").read_text()))
    command = [sys.executable, "-m", "pytest", "-q", *tests, "--disable-warnings"]
    collect = subprocess.run([*command, "--collect-only"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    nodes = [line.strip() for line in (collect.stdout + collect.stderr).splitlines() if "::" in line]
    process = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = process.stdout + process.stderr
    manifest = {"schema": "mephc_e9f_c1_rp2_c3_c3_prelive_manifest_v1", "work_order_id": runtime.WORK_ORDER, "pytest_exit_status": process.returncode, "pytest_node_ids": nodes, "pytest_node_count": len(nodes), "pytest_output_tail": output[-65536:], "placeholder_pass_scan": "PASSED" if "checks[" not in (root / "tests/test_e9f_c1_rp2_c3_c3.py").read_text() else "FAILED", "required_test_file": "tests/test_e9f_c1_rp2_c3_c3.py"}
    atomic(root / "audit/e9f/c3_c3_prelive_manifest.json", manifest)
    if process.returncode != 0 or manifest["placeholder_pass_scan"] != "PASSED":
        raise RuntimeError(f"C3_C3_PRELIVE_FAILED:{manifest}")
    return manifest


def rss() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def run_child(root: Path, row: Mapping[str, Any], runtime_root: Path, execution: str, contract_sha: str, policy_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    slot = runtime_root / "workers" / hashlib.sha256(row["sample_id"].encode()).hexdigest()[:32]
    slot.mkdir(parents=True, exist_ok=False)
    payload_path = slot / "payload.json"
    failure_path = slot / "failure.json"
    binding = {"schema": "mephc_e9f_c1_rp2_c3_c3_binding_v1", "project_id": "MEPHC", "work_order_id": runtime.WORK_ORDER, "phase": runtime.PHASE, "execution_sha": execution, "worker_id": row["sample_id"], "logical_sample_index": row["sample_index"], "resolution": 64, "contract_sha256": contract_sha, "rp1_policy_file_sha256": policy_sha, "payload_path": str(payload_path), "failure_path": str(failure_path), "artifact_schema": runtime.PAYLOAD_SCHEMA, "generation": 1}
    atomic(slot / "binding.json", binding)
    command = [sys.executable, str(root / WORKER), "--root", str(root), "--worker-id", row["sample_id"], "--resolution", "64", "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":")), "--payload-path", str(payload_path), "--failure-path", str(failure_path), "--execution-sha", execution, "--contract-sha256", contract_sha, "--rp1-policy-sha256", policy_sha]
    before = rss()
    started = time.monotonic()
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = child.communicate(timeout=3600)
    orphan_pids = runtime.scan_orphans(worker_marker=WORKER.name, worker_id=row["sample_id"], exclude_pids=(child.pid,))
    measurement = {"pid": int(child.pid), "return_code": int(child.returncode), "direct_pid_gone": not (Path("/proc") / str(child.pid)).exists(), "orphan_pids": orphan_pids, "orphan_count": len(orphan_pids), "stdout_byte_count": len(output), "stderr_byte_count": len(error), "stdout_sha256": hashlib.sha256(output).hexdigest(), "stderr_sha256": hashlib.sha256(error).hexdigest(), "stdout_tail": tail(output), "stderr_tail": tail(error), "parent_rss_before_kib": before, "parent_rss_after_kib": rss(), "elapsed_seconds": time.monotonic() - started, "worker_id": row["sample_id"], "payload_path": str(payload_path), "failure_path": str(failure_path), "failure_sidecar_exists": failure_path.exists()}
    if child.returncode != 0 or measurement["orphan_count"] != 0 or not measurement["direct_pid_gone"]:
        failure = {"schema": "mephc_e9f_c1_rp2_c3_c3_parent_failure_v1", "work_order_id": runtime.WORK_ORDER, "execution_sha": execution, "stage": "child_lifecycle", "process_measurement": measurement, "child_failure_sidecar": json.loads(failure_path.read_text()) if failure_path.exists() else None}
        atomic(runtime_root / "parent_failure.json", failure)
        raise RuntimeError(f"E9F_C1_RP2_C3_C3_CANARY_FAIL_CLOSED_WITH_RETAINED_DIAGNOSTIC_EVIDENCE:{failure}")
    payload = json.loads(payload_path.read_text())
    expected = runtime.expected_binding(row=row, execution_sha=execution, contract_sha256=contract_sha, policy_sha256=policy_sha)
    runtime.validate_payload(payload, row=row, expected=expected)
    measurement.update({"payload_file_sha256": runtime.sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "payload_file_body_hash_distinct": runtime.sha(payload_path) != payload["payload_body_sha256"]})
    return payload, measurement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--runtime-root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    actual_runner = runtime.runner_path(root, Path(__file__))
    load_contract(root)
    c2_science.assert_parent_solver_free()
    rows = [row for row in c2_science.build_plan(root) if row["sample_id"] == "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID::resolution=64"]
    if len(rows) != 1:
        raise RuntimeError("C3_C3_CANARY_PLAN_INVALID")
    prelive = run_prelive(root)
    execution = git(root, "rev-parse", "HEAD")
    contract_sha = runtime.sha(root / CONTRACT)
    policy_sha = runtime.sha(root / POLICY_REL)
    runtime_root = Path(args.runtime_root) if args.runtime_root else root / "audit/e9f/rp2_c3_c3_runtime"
    runtime_root.mkdir(parents=True, exist_ok=False)
    payload, measurement = run_child(root, rows[0], runtime_root, execution, contract_sha, policy_sha)
    expected = runtime.expected_binding(row=rows[0], execution_sha=execution, contract_sha256=contract_sha, policy_sha256=policy_sha)
    try:
        publication = runtime.publish_artifacts(root=root, runtime=runtime_root, payload=payload, measurement=measurement, expected=expected, runner_sha256=runtime.sha(actual_runner))
    except Exception as exc:
        atomic(runtime_root / "parent_failure.json", {"schema": "mephc_e9f_c1_rp2_c3_c3_parent_failure_v1", "work_order_id": runtime.WORK_ORDER, "execution_sha": execution, "stage": "parent_publication", "exception_type": type(exc).__name__, "exception_message": str(exc), "measurement": measurement, "payload_file_sha256": runtime.sha(Path(measurement["payload_path"]))})
        raise RuntimeError(f"E9F_C1_RP2_C3_C3_PUBLICATION_OR_PROVENANCE_FAIL_CLOSED:{exc}")
    result = {"status": "E9F_C1_RP2_C3_C3_SINGLE_CANARY_FULLY_ACCEPTED_READY_FOR_MATRIX_RELEASE_DECISION", "work_order_id": runtime.WORK_ORDER, "execution_sha": execution, "base_sha": runtime.FAILED_PARENT_EXECUTION_SHA, "runner_relative_path": str(runtime.RUNNER_RELATIVE_PATH).replace("\\", "/"), "runner_sha256": runtime.sha(actual_runner), "prelive": prelive, "publication": publication, "measurement": measurement, "summary": {"solve_count": payload["solve_count"], "replay_matched_point_count": payload["replay_matched_point_count"], "replay_unmatched_point_count": payload["replay_unmatched_point_count"]}}
    atomic(runtime_root / "c3_c3_final_report.json", result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
