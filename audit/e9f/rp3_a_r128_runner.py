"""RP3.A fixed-six R128 diagnostic runner; no reducer or scientific verdict."""
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
from audit.e9f import c3_c5_runtime as c35
from audit.e9f import rp3_a_r128_runtime as rp3

WORKER = Path("audit/e9f/rp3_a_r128_worker.py")
CONTRACT = Path("audit/e9f/rp3_a_r128_execution_contract.json")
CANARY = rp3.CANARY_SOURCE_SAMPLE_ID


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def json_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_provenance(root: Path) -> dict[str, Any]:
    expected = {
        root / "audit/e9f/c3_c5_c1_c1_process_seal.json": "62ff08bc84b662d11e2734059b4b46821b4f058184a0369913c0aed26564b493",
        root / "audit/e9f/c3_c5_c1_c1_process_reliability_registry.json": "048cfafb342049547677397efe4572ccdeacd459a6084ce928619b3d315dd5c3",
        Path("/home/icy/MePhC/.c3-c5-live2/audit/e9f/rp2_c3_c5_runtime_20260825_fix1/matrix_checkpoint.json"): "871b24983800d178f44d09b2220bcc179804e939f1f4c9163d84917ca5a8ca7d",
        Path("/home/icy/MePhC/.c3-c5-live2/audit/e9f/rp2_c3_c5_runtime_20260825_fix1/c3_c5_matrix_result.json"): "068cbb6048d5813cbdd5c38efa323e85af3a340d58d7fa69e0e3b5ff1511785a",
        Path("/home/icy/MePhC/.c3-c5-live2/audit/e9f/rp2_c3_c5_runtime_20260825_fix1/c3_c5_matrix_manifest.json"): "ca9d7fc2184371b1dcf5049a1a8bceaf613372bd69a2cd0449fbf25d4e919d01",
    }
    values = {}
    for path, digest in expected.items():
        if json_sha(path) != digest:
            raise RuntimeError(f"RP3_A_PROVENANCE_FAIL_CLOSED:{path}")
        values[str(path)] = digest
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", rp3.BASE_SANDBOX_SHA, "HEAD"], cwd=root)
    if ancestry.returncode != 0:
        raise RuntimeError("RP3_A_BASE_SANDBOX_ANCESTRY_FAIL_CLOSED")
    main_sha = git(root, "ls-remote", "origin", "refs/heads/main").split()[0]
    if main_sha != "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5":
        raise RuntimeError("RP3_A_MAIN_MOVED_FAIL_CLOSED")
    return {"bindings": values, "base_sandbox_sha": rp3.BASE_SANDBOX_SHA, "main_sha": main_sha}


def load_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT).read_text())
    required = {"work_order_id": rp3.WORK_ORDER, "base_sandbox_sha": rp3.BASE_SANDBOX_SHA, "resolution": 128, "worker_count": 6, "native_solves_per_worker": 9, "runner_relative_path": str(Path("audit/e9f/rp3_a_r128_runner.py"))}
    if any(value.get(key) != expected for key, expected in required.items()):
        raise RuntimeError("RP3_A_CONTRACT_FAIL_CLOSED")
    return value


def run_child(root: Path, row: Mapping[str, Any], runtime_root: Path, execution: str, contract_sha: str, policy_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    slot = runtime_root / "workers" / hashlib.sha256(row["sample_id"].encode()).hexdigest()[:32]
    slot.mkdir(parents=True, exist_ok=False)
    payload_path = slot / "payload.json"
    failure_path = slot / "failure.json"
    expected = rp3.identity_for(row=row, execution_sha=execution, contract_sha256=contract_sha, policy_sha256=policy_sha)
    c35.atomic_write(slot / "binding.json", {"schema": "mephc_e9f_c1_rp3_a_binding_v1", **expected, "payload_path": str(payload_path), "failure_path": str(failure_path)})
    command = [sys.executable, str(root / WORKER), "--root", str(root), "--worker-id", row["sample_id"], "--resolution", "128", "--payload-path", str(payload_path), "--failure-path", str(failure_path), "--execution-sha", execution, "--contract-sha256", contract_sha, "--rp1-policy-sha256", policy_sha]
    started = time.monotonic()
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = child.communicate(timeout=3600)
    orphans = c4_process.scan_orphans(WORKER.name, row["sample_id"], (child.pid,))
    measurement = {"pid": child.pid, "return_code": child.returncode, "direct_pid_gone": not (Path("/proc") / str(child.pid)).exists(), "orphan_pids": orphans, "orphan_count": len(orphans), "stdout_sha256": hashlib.sha256(output).hexdigest(), "stderr_sha256": hashlib.sha256(error).hexdigest(), "stdout_tail": output[-65536:].decode(errors="replace"), "stderr_tail": error[-65536:].decode(errors="replace"), "elapsed_seconds": time.monotonic() - started, "worker_id": row["sample_id"], "resolution": 128, "payload_path": str(payload_path), "failure_path": str(failure_path), "failure_sidecar_exists": failure_path.exists()}
    if child.returncode != 0 or orphans or not measurement["direct_pid_gone"]:
        failure = {"schema": "mephc_e9f_c1_rp3_a_parent_failure_v1", "work_order_id": rp3.WORK_ORDER, "execution_sha": execution, "stage": "child_lifecycle", "process_measurement": measurement, "child_failure_sidecar": json.loads(failure_path.read_text()) if failure_path.exists() else None}
        c35.atomic_write(runtime_root / "parent_failure.json", failure)
        raise RuntimeError("RP3_A_CHILD_FAIL_CLOSED")
    payload = json.loads(payload_path.read_text())
    rp3.validate_payload(payload, row=row, expected=expected)
    measurement["payload_file_sha256"] = c35.sha(payload_path)
    measurement["payload_body_sha256"] = payload["payload_body_sha256"]
    return payload, measurement


def execute(root: Path, runtime_root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    provenance = verify_provenance(root)
    rows = rp3.build_plan(root)
    execution = git(root, "rev-parse", "HEAD")
    contract_sha = c35.sha(root / CONTRACT)
    policy_sha = c35.sha(root / "audit/e9f/rp1_recovery_policy_contract.json")
    runtime_root.mkdir(parents=True, exist_ok=False)
    order = [next(row for row in rows if row["source_sample_id"] == CANARY)] + [row for row in rows if row["source_sample_id"] != CANARY]
    payloads = []
    measurements = []
    completed = []
    for row in order:
        payload, measurement = run_child(root, row, runtime_root, execution, contract_sha, policy_sha)
        payloads.append(payload)
        measurements.append(measurement)
        completed.append({"worker_id": row["sample_id"], "resolution": 128, "payload_path": measurement["payload_path"], "payload_file_sha256": measurement["payload_file_sha256"], "payload_body_sha256": measurement["payload_body_sha256"]})
        checkpoint = rp3.construct_checkpoint(completed=completed, execution_sha=execution, contract_sha256=contract_sha, policy_sha256=policy_sha)
        rp3.validate_checkpoint(checkpoint, root=root, rows=rows)
        c35.atomic_write(runtime_root / "matrix_checkpoint.json", checkpoint)
    convergence, spectral = rp3.convergence_rows(root=root, payloads=payloads)
    result = {"schema": "mephc_e9f_c1_rp3_a_r128_result_v1", "status": "E9F_C1_RP3_A_FIXED_SIX_R128_DIAGNOSTIC_COMPLETE_READY_FOR_SUPERVISOR_CONVERGENCE_DECISION", "project_id": "MEPHC", "work_order_id": rp3.WORK_ORDER, "base_sandbox_sha": rp3.BASE_SANDBOX_SHA, "execution_sha": execution, "contract_sha256": contract_sha, "provenance": provenance, "rows": rows, "payloads": payloads, "measurements": measurements, "checkpoint_generation": len(completed), "authorized_native_solve_count": 54, "actual_native_solve_count": sum(payload["solve_count"] for payload in payloads), "replay_policy": "NOT_APPLICABLE_R128_ORIGINAL_RP2_HAS_NO_R128_KEY", "convergence_rows": convergence, "spectral_rows": spectral, "no_convergence_verdict": True, "diagnostic_only": True, "reducer_admissible": False, "rp3_reducer_started": False, "rp3_chern_started": False}
    c35.atomic_write(runtime_root / "rp3_a_r128_result.json", result)
    manifest = {"schema": "mephc_e9f_c1_rp3_a_r128_manifest_v1", "work_order_id": rp3.WORK_ORDER, "execution_sha": execution, "checkpoint_sha256": c35.sha(runtime_root / "matrix_checkpoint.json"), "result_sha256": c35.sha(runtime_root / "rp3_a_r128_result.json"), "worker_count": 6, "matrix_entry_count": 12, "authorized_native_solves": 54, "actual_native_solves": result["actual_native_solve_count"]}
    c35.atomic_write(runtime_root / "rp3_a_r128_manifest.json", manifest)
    return {"status": result["status"], "execution_sha": execution, "worker_count": 6, "matrix_entry_count": 12, "authorized_native_solves": 54, "actual_native_solves": result["actual_native_solve_count"], "result_sha256": c35.sha(runtime_root / "rp3_a_r128_result.json"), "manifest_sha256": c35.sha(runtime_root / "rp3_a_r128_manifest.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(execute(Path(args.root).resolve(), Path(args.runtime_root).resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
