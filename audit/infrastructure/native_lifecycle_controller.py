"""MPB-free outer controller for the NC1.C1 process-boundary corrective."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

from audit.infrastructure.campaign_runtime import (
    CampaignIdentity,
    CampaignRuntime,
    CampaignRuntimeError,
    current_rss_kib,
    sha256_file,
    semantic_plan_fingerprint,
)
from audit.infrastructure.native_canary import (
    build_plan,
    child_command,
    load_contract,
    validate_child,
)


MODULE = "audit.infrastructure.native_lifecycle_controller"
STAGE_STOP = "PARENT_STAGE_STOP"
NATIVE_MARKER = "native_canary.py"


def _native_modules_loaded() -> list[str]:
    return sorted(
        name for name in sys.modules
        if name.lower() == "meep" or name.lower().startswith("meep.")
        or name.lower() == "mpb" or name.lower().startswith("mpb.")
    )


def assert_parent_solver_free() -> None:
    loaded = _native_modules_loaded()
    if loaded:
        raise CampaignRuntimeError(f"PARENT_NATIVE_IMPORT_DETECTED:{loaded}")


def _proc_cmdline(pid: int) -> str:
    path = Path("/proc") / str(pid) / "cmdline"
    try:
        return path.read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except (OSError, UnicodeError):
        return ""


def scan_native_child_processes(sample_id: str | None = None) -> list[int]:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        raise CampaignRuntimeError("ORPHAN_PROCESS_INSPECTION_UNAVAILABLE")
    found: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        command = _proc_cmdline(pid)
        if NATIVE_MARKER not in command or "--child" not in command:
            continue
        if sample_id is not None and f"--sample-id {sample_id}" not in command:
            continue
        found.append(pid)
    return sorted(found)


def measure_native_child_exit(pid: int, sample_id: str) -> dict[str, Any]:
    if not Path("/proc").is_dir():
        raise CampaignRuntimeError("ORPHAN_PROCESS_INSPECTION_UNAVAILABLE")
    direct_alive = Path("/proc") .joinpath(str(pid)).exists()
    descendants = scan_native_child_processes(sample_id)
    if pid in descendants:
        descendants.remove(pid)
    return {
        "sample_id": sample_id,
        "launched_pid": pid,
        "direct_pid_gone": not direct_alive,
        "orphan_pids": descendants,
        "orphan_count": len(descendants),
    }


def run_native_child(
    row: Mapping[str, Any],
    *,
    inject_fault: bool = False,
    timeout_seconds: float = 120.0,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    process = subprocess.Popen(
        child_command(row, inject_fault),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise CampaignRuntimeError(f"NATIVE_CHILD_TIMEOUT:{row['sample_id']}") from exc
    measurement = measure_native_child_exit(process.pid, str(row["sample_id"]))
    if not measurement["direct_pid_gone"] or measurement["orphan_count"]:
        raise CampaignRuntimeError(
            f"NATIVE_ORPHAN_PROCESS_DETECTED:{row['sample_id']}:{measurement}"
        )
    if inject_fault:
        if process.returncode == 0:
            raise CampaignRuntimeError("INJECTED_FAULT_DID_NOT_FAIL")
        return {
            "returncode": process.returncode,
            "stderr_tail": stderr[-400:],
        }, measurement
    if process.returncode != 0:
        raise CampaignRuntimeError(
            f"NATIVE_CHILD_FAILED:{row['sample_id']}:{process.returncode}:{stderr[-240:]}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CampaignRuntimeError(f"NATIVE_CHILD_JSON_INVALID:{row['sample_id']}") from exc
    if not isinstance(payload, dict):
        raise CampaignRuntimeError("NATIVE_CHILD_RESULT_NOT_OBJECT")
    validate_child(row, payload)
    return payload, measurement


def _identity(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], CampaignIdentity, Path, Path]:
    contract = load_contract(root)
    rows = build_plan(contract)
    execution_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    runner = root / "audit/infrastructure/native_canary.py"
    contract_path = root / "audit/e9f/c1_nc1_contract.json"
    plan_id = semantic_plan_fingerprint(
        rows,
        estimator_id=contract["identity"]["estimator_id"],
        semantic_domain_id=contract["identity"]["semantic_domain_id"],
        spacing_id=contract["identity"]["spacing_id"],
    )
    identity = CampaignIdentity(
        execution_sha,
        sha256_file(runner),
        sha256_file(contract_path),
        plan_id,
        tuple(row["sample_id"] for row in rows),
        expected_sample_indices=tuple(row["sample_index"] for row in rows),
        semantic_estimator_id=contract["identity"]["estimator_id"],
        semantic_domain_id=contract["identity"]["semantic_domain_id"],
        semantic_spacing_id=contract["identity"]["spacing_id"],
    )
    return contract, rows, identity, runner, contract_path


def _runtime(root: Path, runtime_root: Path) -> tuple[CampaignRuntime, list[dict[str, Any]], CampaignIdentity]:
    _, rows, identity, runner, contract_path = _identity(root)
    runtime = CampaignRuntime(
        runtime_root,
        identity,
        runner_path=runner,
        contract_path=contract_path,
        repository_path=root,
        remote_name="origin",
        remote_ref="refs/heads/sandbox",
        production_mode=True,
    )
    return runtime, rows, identity


def _artifact_hash(runtime: CampaignRuntime, sample_id: str) -> str:
    return sha256_file(runtime._artifact_path(sample_id))


def run_parent_stage(root: Path, runtime_root: Path, stage: str) -> dict[str, Any]:
    assert_parent_solver_free()
    runtime, rows, identity = _runtime(root, runtime_root)
    preflight = runtime.preflight(plan_rows=rows)
    assert_parent_solver_free()
    orphan_measurements: list[dict[str, Any]] = []
    worker_pids: list[int] = []
    records: list[dict[str, Any]] = []
    faults: list[dict[str, Any]] = []
    injected = False

    def publish_result(row: Mapping[str, Any], *, inject: bool = False) -> dict[str, Any]:
        nonlocal orphan_measurements
        payload, measurement = run_native_child(row, inject_fault=inject)
        orphan_measurements.append(measurement)
        if payload is None:
            raise CampaignRuntimeError("NATIVE_CHILD_PAYLOAD_MISSING")
        if inject:
            faults.append(payload)
            raise CampaignRuntimeError("INJECTED_NATIVE_CHILD_FAILURE")
        worker_pids.append(int(payload["pid"]))
        records.append(dict(payload))
        payload = dict(payload)
        payload["child_schema"] = payload.pop("schema")
        return payload

    if stage == "A":
        def worker_a(row: Mapping[str, Any]) -> Mapping[str, Any]:
            if row["sample_id"] != "native_canary_0":
                raise RuntimeError(STAGE_STOP)
            return publish_result(row)

        try:
            runtime.run(rows, worker_a)
        except RuntimeError as exc:
            if str(exc) != STAGE_STOP:
                raise
        checkpoint = runtime.load_checkpoint()
        if checkpoint != {"native_canary_0"}:
            raise CampaignRuntimeError(f"PARENT_A_CHECKPOINT_INVALID:{sorted(checkpoint)}")
        result = {
            "stage": "A",
            "parent_pid": os.getpid(),
            "parent_exit_code": 0,
            "parent_native_import_free": not _native_modules_loaded(),
            "preflight": preflight,
            "worker_pids": worker_pids,
            "records": records,
            "orphan_measurements": orphan_measurements,
            "faults": faults,
            "rss_series_kib": [current_rss_kib()],
            "sample0_artifact_sha": _artifact_hash(runtime, "native_canary_0"),
            "checkpoint_generation": json.loads(runtime.checkpoint_path.read_text())["generation"],
        }
        print(json.dumps(result, sort_keys=True), flush=True)
        return result

    if stage != "B":
        raise CampaignRuntimeError(f"UNKNOWN_PARENT_STAGE:{stage}")

    before = runtime.load_checkpoint()
    if before != {"native_canary_0"}:
        raise CampaignRuntimeError(f"PARENT_B_INITIAL_CHECKPOINT_INVALID:{sorted(before)}")
    sample0_before = _artifact_hash(runtime, "native_canary_0")

    def worker_b(row: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal injected
        if row["sample_id"] == "native_canary_1" and not injected:
            injected = True
            return publish_result(row, inject=True)
        return publish_result(row)

    try:
        runtime.run(rows, worker_b)
    except RuntimeError as exc:
        if str(exc) != "INJECTED_NATIVE_CHILD_FAILURE":
            raise
    resumed = runtime.run(rows, worker_b)
    after = runtime.load_checkpoint()
    sample0_after = _artifact_hash(runtime, "native_canary_0")
    if sample0_before != sample0_after:
        raise CampaignRuntimeError("SAMPLE0_ARTIFACT_CHANGED_AFTER_PARENT_RESTART")
    if after != {"native_canary_0", "native_canary_1", "native_canary_2"}:
        raise CampaignRuntimeError(f"PARENT_B_FINAL_CHECKPOINT_INVALID:{sorted(after)}")
    result = {
        "stage": "B",
        "parent_pid": os.getpid(),
        "parent_exit_code": 0,
        "parent_native_import_free": not _native_modules_loaded(),
        "preflight": preflight,
        "worker_pids": worker_pids,
        "records": records,
        "orphan_measurements": orphan_measurements,
        "faults": faults,
        "rss_series_kib": [current_rss_kib()],
        "sample0_artifact_sha_before_restart": sample0_before,
        "sample0_artifact_sha_after_restart": sample0_after,
        "sample0_recomputed": False,
        "sample0_worker_pid_count": sum(1 for record in records if record["sample_id"] == "native_canary_0"),
        "checkpoint_generation": json.loads(runtime.checkpoint_path.read_text())["generation"],
        "checkpoint_completed_sample_count": json.loads(runtime.checkpoint_path.read_text())["telemetry"]["completed_sample_count"],
        "resumed_status": resumed["status"],
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def launch_parent_process(root: Path, runtime_root: Path, stage: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [sys.executable, "-m", MODULE, "--parent-stage", stage,
         "--root", str(root), "--runtime-root", str(runtime_root)],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(timeout=600)
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise CampaignRuntimeError(f"PARENT_STAGE_NO_RESULT:{stage}:{stderr[-400:]}")
    try:
        summary = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise CampaignRuntimeError(f"PARENT_STAGE_RESULT_INVALID:{stage}:{stdout[-400:]}") from exc
    if process.returncode != 0:
        raise CampaignRuntimeError(f"PARENT_STAGE_FAILED:{stage}:{process.returncode}:{stderr[-400:]}")
    return {
        "pid": process.pid,
        "exit_code": process.returncode,
        "summary": summary,
        "stderr_tail": stderr[-400:],
    }


def _merge_orphan_measurements(a: Mapping[str, Any], b: Mapping[str, Any], after_a: list[int], after_b: list[int]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for label, stage in (("parent_a", a), ("parent_b", b)):
        for measurement in stage["summary"]["orphan_measurements"]:
            values[f"{label}_{measurement['sample_id']}"] = measurement
    values["parent_a_exit"] = {"orphan_pids": after_a, "orphan_count": len(after_a)}
    values["parent_b_exit"] = {"orphan_pids": after_b, "orphan_count": len(after_b)}
    return values


def run_controller(root: Path, runtime_root: Path) -> dict[str, Any]:
    assert_parent_solver_free()
    runtime_root = Path(runtime_root)
    if runtime_root.exists() and any(runtime_root.iterdir()):
        raise CampaignRuntimeError("RUNTIME_ROOT_MUST_BE_FRESH")
    runtime_root.mkdir(parents=True, exist_ok=True)
    parent_a = launch_parent_process(root, runtime_root, "A")
    after_a = scan_native_child_processes()
    parent_b = launch_parent_process(root, runtime_root, "B")
    after_b = scan_native_child_processes()
    if parent_a["pid"] == parent_b["pid"]:
        raise CampaignRuntimeError("PARENT_PROCESS_PID_NOT_RESTARTED")
    _, rows, identity, _, _ = _identity(root)
    checkpoint = json.loads((runtime_root / "checkpoint.json").read_text(encoding="utf-8"))
    orphan_by_stage = _merge_orphan_measurements(parent_a, parent_b, after_a, after_b)
    final_orphan_count = len(after_b)
    if not all(item["direct_pid_gone"] and item["orphan_count"] == 0 for item in (
        *parent_a["summary"]["orphan_measurements"],
        *parent_b["summary"]["orphan_measurements"],
    )) or final_orphan_count:
        raise CampaignRuntimeError("NATIVE_ORPHAN_PROCESS_DETECTED")
    records = parent_a["summary"]["records"] + parent_b["summary"]["records"]
    vectors = [record["frequency_vector"] for record in records]
    maxdiff = max(abs(float(vectors[i][j]) - float(vectors[0][j])) for i in range(len(vectors)) for j in range(2))
    result = {
        "schema": "trilatt_e9f_c1_nc1_c1_result_v1",
        "phase": "E9F.C1.NC1.C1",
        "status": "E9F_C1_NATIVE_PROCESS_BOUNDARY_VALIDATED_READY_FOR_RECOVERY_POLICY_DESIGN",
        "execution_git_sha": identity.execution_git_sha,
        "runner_sha256": identity.runner_sha256,
        "canary_contract_sha256": identity.scientific_contract_sha256,
        "plan_semantic_id": identity.plan_semantic_id,
        "parent_a_pid": parent_a["summary"]["parent_pid"],
        "parent_b_pid": parent_b["summary"]["parent_pid"],
        "parent_controller_pid_a": parent_a["pid"],
        "parent_controller_pid_b": parent_b["pid"],
        "parent_process_restart_confirmed": True,
        "parent_a_exit_code": parent_a["exit_code"],
        "parent_b_exit_code": parent_b["exit_code"],
        "parent_a_rss_series_kib": parent_a["summary"]["rss_series_kib"],
        "parent_b_rss_series_kib": parent_b["summary"]["rss_series_kib"],
        "sample0_artifact_sha_before_restart": parent_b["summary"]["sample0_artifact_sha_before_restart"],
        "sample0_artifact_sha_after_restart": parent_b["summary"]["sample0_artifact_sha_after_restart"],
        "sample0_recomputed": parent_b["summary"]["sample0_recomputed"],
        "sample0_worker_pid_count": parent_b["summary"]["sample0_worker_pid_count"],
        "orphan_native_child_counts_by_stage": orphan_by_stage,
        "orphan_native_child_count": final_orphan_count,
        "final_checkpoint_generation": checkpoint["generation"],
        "final_checkpoint_completed_sample_count": checkpoint["telemetry"]["completed_sample_count"],
        "final_checkpoint_completed_artifact_count": len(checkpoint["completed_artifacts"]),
        "native_successful_worker_count": len(records),
        "native_injected_failure_count": len(parent_b["summary"]["faults"]),
        "native_reproducibility_max_abs_diff": maxdiff,
        "native_reproducibility_tolerance": 1e-8,
        "records": records,
        "parent_a_summary": parent_a["summary"],
        "parent_b_summary": parent_b["summary"],
        "main_unchanged": True,
        "no_berry_calculation": True,
        "no_chern_calculation": True,
        "no_band2_recovery": True,
        "no_three_band_sum": True,
        "no_threshold_change": True,
    }
    if result["sample0_worker_pid_count"] != 0 or result["sample0_recomputed"]:
        raise CampaignRuntimeError("SAMPLE0_RECOMPUTED_AFTER_PARENT_RESTART")
    if result["final_checkpoint_completed_sample_count"] != result["final_checkpoint_completed_artifact_count"]:
        raise CampaignRuntimeError("CHECKPOINT_COMPLETED_COUNT_INCONSISTENT")
    (runtime_root / "c1_c1_result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller", action="store_true")
    parser.add_argument("--parent-stage", choices=("A", "B"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    if args.controller:
        result = run_controller(args.root, args.runtime_root)
    elif args.parent_stage:
        result = run_parent_stage(args.root, args.runtime_root, args.parent_stage)
    else:
        parser.error("choose --controller or --parent-stage")
    if args.controller:
        print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
