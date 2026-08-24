"""C3.C4 parent runner with shared finalization and exact acceptance gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from audit.e9f import c4_process
from audit.e9f import c3_c2_hardening as c2
from audit.e9f import c3_c4_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as science

WORKER = Path("audit/e9f/run_e9f_c1_rp2_c3_c4_worker.py")
CONTRACT = Path("audit/e9f/rp2_c3_c4_execution_contract.json")


def git(root: Path, *args: str) -> str: return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
def tail(data: bytes) -> str: return data[-65536:].decode(errors="replace")


def load_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT).read_text())
    if value.get("work_order_id") != runtime.WORK_ORDER or value.get("parent_failed_execution_sha") != runtime.FAILED_PARENT_EXECUTION_SHA or value.get("runner_relative_path") != str(runtime.RUNNER_RELATIVE_PATH).replace("\\", "/"): raise ValueError("C3_C4_CONTRACT_IDENTITY")
    if tuple(value.get("required_incident_ids", ())) != runtime.REQUIRED_INCIDENT_IDS: raise ValueError("C3_C4_CONTRACT_PROCESS_REGISTRY")
    gate = value.get("h_gate", {})
    if gate.get("orthogonality_tolerance") != runtime.H_ORTHOGONALITY_TOLERANCE or gate.get("normalization_tolerance") != runtime.H_NORM_TOLERANCE: raise ValueError("C3_C4_CONTRACT_H_TOLERANCE")
    return value


def run_prelive(root: Path) -> dict[str, Any]:
    tests = ["tests/test_e9f_c1_rp2_c3_c2.py", "tests/test_e9f_c1_rp2_c3_c2_required_nodes.py", "tests/test_e9f_c1_rp2_c3_c3.py", "tests/test_e9f_c1_rp2_c3_c3_required_nodes.py", "tests/test_e9f_c1_rp2_c3_c4.py", "tests/test_e9f_c1_rp2_c3_c4_required_nodes.py"]
    runtime.validate_process_review(json.loads((root / "audit/e9f/c3_c4_process_reliability_review.json").read_text()))
    command = [sys.executable, "-m", "pytest", "-q", *tests, "--disable-warnings"]
    collect = subprocess.run([*command, "--collect-only"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); nodes = [line.strip() for line in (collect.stdout + collect.stderr).splitlines() if "::" in line]
    process = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); output = process.stdout + process.stderr
    manifest = {"schema": "mephc_e9f_c1_rp2_c3_c4_prelive_manifest_v1", "work_order_id": runtime.WORK_ORDER, "pytest_exit_status": process.returncode, "pytest_node_ids": nodes, "pytest_node_count": len(nodes), "pytest_output_tail": output[-65536:], "placeholder_pass_scan": "PASSED" if "checks[" not in (root / "tests/test_e9f_c1_rp2_c3_c4.py").read_text() else "FAILED", "shared_finalizer_test": "PASSED" if process.returncode == 0 else "FAILED", "real_worker_finalize_integration": "PASSED" if process.returncode == 0 else "FAILED", "process_registry_completeness": "PASSED" if process.returncode == 0 else "FAILED"}
    runtime.atomic_write(root / "audit/e9f/c3_c4_prelive_manifest.json", manifest)
    if process.returncode != 0 or manifest["placeholder_pass_scan"] != "PASSED": raise RuntimeError(f"C3_C4_PRELIVE_FAILED:{manifest}")
    return manifest


def rss() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"): return int(line.split()[1])
    except OSError: return None
    return None


def run_child(root: Path, row: Mapping[str, Any], runtime_root: Path, execution: str, contract_sha: str, policy_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    slot = runtime_root / "workers" / hashlib.sha256(row["sample_id"].encode()).hexdigest()[:32]; slot.mkdir(parents=True, exist_ok=False); payload_path = slot / "payload.json"; failure_path = slot / "failure.json"
    identity = runtime.identity_for(row=row, execution_sha=execution, contract_sha256=contract_sha, policy_sha256=policy_sha)
    runtime.atomic_write(slot / "binding.json", {"schema": "mephc_e9f_c1_rp2_c3_c4_binding_v1", **identity, "payload_path": str(payload_path), "failure_path": str(failure_path), "artifact_schema": runtime.PAYLOAD_SCHEMA, "generation": 1})
    command = [sys.executable, str(root / WORKER), "--root", str(root), "--worker-id", row["sample_id"], "--resolution", "64", "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":")), "--payload-path", str(payload_path), "--failure-path", str(failure_path), "--execution-sha", execution, "--contract-sha256", contract_sha, "--rp1-policy-sha256", policy_sha]
    before = rss(); started = time.monotonic(); child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE); output, error = child.communicate(timeout=3600); orphan_pids = c4_process.scan_orphans(WORKER.name, row["sample_id"], (child.pid,))
    measurement = {"pid": int(child.pid), "return_code": int(child.returncode), "direct_pid_gone": not (Path("/proc") / str(child.pid)).exists(), "orphan_pids": orphan_pids, "orphan_count": len(orphan_pids), "stdout_byte_count": len(output), "stderr_byte_count": len(error), "stdout_sha256": hashlib.sha256(output).hexdigest(), "stderr_sha256": hashlib.sha256(error).hexdigest(), "stdout_tail": tail(output), "stderr_tail": tail(error), "parent_rss_before_kib": before, "parent_rss_after_kib": rss(), "elapsed_seconds": time.monotonic() - started, "worker_id": row["sample_id"], "payload_path": str(payload_path), "failure_path": str(failure_path), "failure_sidecar_exists": failure_path.exists()}
    if child.returncode != 0 or measurement["orphan_count"] != 0 or not measurement["direct_pid_gone"]:
        failure = {"schema": "mephc_e9f_c1_rp2_c3_c4_parent_failure_v1", "work_order_id": runtime.WORK_ORDER, "execution_sha": execution, "stage": "child_lifecycle", "process_measurement": measurement, "child_failure_sidecar": json.loads(failure_path.read_text()) if failure_path.exists() else None}; runtime.atomic_write(runtime_root / "parent_failure.json", failure); raise RuntimeError(f"E9F_C1_RP2_C3_C4_CANARY_FAIL_CLOSED_WITH_RETAINED_DIAGNOSTIC_EVIDENCE:{failure}")
    payload = json.loads(payload_path.read_text()); runtime.validate_payload(payload, row=row, expected_identity=identity); measurement.update({"payload_file_sha256": runtime.sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "payload_hashes_distinct": runtime.sha(payload_path) != payload["payload_body_sha256"]}); return payload, measurement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2])); parser.add_argument("--runtime-root", default=None); args = parser.parse_args(argv); root = Path(args.root).resolve(); actual_runner = runtime.runner_path(root, Path(__file__)); load_contract(root); science.assert_parent_solver_free(); rows = [row for row in science.build_plan(root) if row["sample_id"] == "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID::resolution=64"]
    if len(rows) != 1: raise RuntimeError("C3_C4_CANARY_PLAN")
    prelive = run_prelive(root); execution = git(root, "rev-parse", "HEAD"); contract_sha = runtime.sha(root / CONTRACT); policy_sha = runtime.sha(root / science.POLICY_REL); runtime_root = Path(args.runtime_root) if args.runtime_root else root / "audit/e9f/rp2_c3_c4_runtime"; runtime_root.mkdir(parents=True, exist_ok=False); payload, measurement = run_child(root, rows[0], runtime_root, execution, contract_sha, policy_sha); expected = runtime.identity_for(row=rows[0], execution_sha=execution, contract_sha256=contract_sha, policy_sha256=policy_sha)
    try: publication = runtime.publish_artifacts(runtime_root=runtime_root, payload=payload, measurement=measurement, expected_identity=expected, runner_sha256=runtime.sha(actual_runner))
    except Exception as exc:
        runtime.atomic_write(runtime_root / "parent_failure.json", {"schema": "mephc_e9f_c1_rp2_c3_c4_parent_failure_v1", "work_order_id": runtime.WORK_ORDER, "execution_sha": execution, "stage": "parent_publication", "exception_type": type(exc).__name__, "exception_message": str(exc), "measurement": measurement}); raise RuntimeError(f"E9F_C1_RP2_C3_C4_PUBLICATION_OR_PROVENANCE_FAIL_CLOSED:{exc}")
    result = {"status": "E9F_C1_RP2_C3_C4_SINGLE_CANARY_FULLY_ACCEPTED_READY_FOR_MATRIX_RELEASE_DECISION", "work_order_id": runtime.WORK_ORDER, "execution_sha": execution, "base_sha": runtime.FAILED_PARENT_EXECUTION_SHA, "runner_relative_path": str(runtime.RUNNER_RELATIVE_PATH).replace("\\", "/"), "runner_sha256": runtime.sha(actual_runner), "prelive": prelive, "publication": publication, "measurement": measurement, "payload": payload}
    runtime.atomic_write(runtime_root / "c3_c4_final_report.json", result); print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
