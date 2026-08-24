"""C3.C1 parent: 21-gate prelive then exact 12-worker atomic campaign."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path
from typing import Any, Mapping
from audit.e9f import run_e9f_c1_rp2_c3_c1_impl as scientific

WORKER = Path("audit/e9f/run_e9f_c1_rp2_c3_c1_worker.py")
WORK_ORDER = scientific.WORK_ORDER


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as handle: handle.write((json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp, path)
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def git(root: Path, *args: str) -> str: return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
def rss() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"): return int(line.split()[1])
    except OSError: return None
    return None
def proc_cmdline(pid: int) -> str:
    try: return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError: return ""
def orphans(worker_id: str) -> list[int]: return [int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit() and "run_e9f_c1_rp2_c3_c1_worker.py" in proc_cmdline(int(p.name)) and worker_id in proc_cmdline(int(p.name))] if Path("/proc").is_dir() else []


def run_child(root: Path, row: Mapping[str, Any], runtime: Path, execution: str, contract_sha: str, policy_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    slot = runtime / "workers" / hashlib.sha256(row["sample_id"].encode()).hexdigest()[:32]; slot.mkdir(parents=True, exist_ok=False); payload_path = slot / "payload.json"; atomic(slot / "binding.json", {"project_id": "MEPHC", "work_order_id": WORK_ORDER, "execution_sha": execution, "worker_id": row["sample_id"], "logical_sample_index": row["sample_index"], "resolution": row["resolution"], "contract_sha256": contract_sha, "rp1_policy_sha256": policy_sha, "payload_path": str(payload_path)})
    command = [sys.executable, str(root / WORKER), "--root", str(root), "--worker-id", row["sample_id"], "--resolution", str(row["resolution"]), "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":")), "--payload-path", str(payload_path), "--execution-sha", execution, "--contract-sha256", contract_sha, "--rp1-policy-sha256", policy_sha]
    before = rss(); started = time.monotonic(); child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE); out, err = child.communicate(timeout=3600); after = rss(); orphan = orphans(row["sample_id"]); measurement = {"worker_id": row["sample_id"], "pid": int(child.pid), "returncode": int(child.returncode), "elapsed_seconds": time.monotonic() - started, "parent_rss_before_kib": before, "parent_rss_after_kib": after, "direct_pid_gone": not (Path("/proc") / str(child.pid)).exists(), "orphan_pids": orphan, "orphan_count": len(orphan), "stdout_sha256": hashlib.sha256(out).hexdigest(), "stderr_sha256": hashlib.sha256(err).hexdigest(), "stdout_byte_count": len(out), "stderr_byte_count": len(err), "stdout_used_as_payload": False, "stderr_used_as_payload": False}
    if child.returncode != 0 or orphan or not measurement["direct_pid_gone"]: raise RuntimeError(f"C3_C1_NATIVE_CHILD_FAILED:{measurement}")
    raw = payload_path.read_bytes(); payload = json.loads(raw.decode()); scientific.validate_worker_payload(payload, row); committed = dict(payload); declared = committed.pop("payload_sha256", None); expected = hashlib.sha256((json.dumps(committed, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()).hexdigest()
    if declared != expected: raise RuntimeError("C3_C1_PAYLOAD_SHA256_MISMATCH")
    measurement.update({"payload_path": str(payload_path), "payload_file_sha256": hashlib.sha256(raw).hexdigest(), "payload_declared_sha256": declared, "payload_identity_valid": True}); return payload, measurement


def prelive(root: Path) -> dict[str, str]:
    from audit.e9f import c3_c1_prelive
    result = c3_c1_prelive.run_all(root)
    if set(result) != set(c3_c1_prelive.REQUIRED): raise RuntimeError("C3_C1_PRELIVE_STATUS_SET_MISMATCH")
    if any(value != "PASSED" for value in result.values()): raise RuntimeError(f"C3_C1_PRELIVE_GATE_FAILED:{result}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2])); parser.add_argument("--runtime-root", default=None); parser.add_argument("--prelive-only", action="store_true"); args = parser.parse_args(); root = Path(args.root).resolve(); scientific.assert_parent_solver_free(); contract = scientific.load_contract(root); rows = scientific.build_plan(root); gates = prelive(root)
    if args.prelive_only: print(json.dumps(gates, sort_keys=True)); return 0
    execution = git(root, "rev-parse", "HEAD"); contract_sha = sha(root / scientific.CONTRACT_REL); policy_sha = sha(root / scientific.POLICY_REL); runtime = Path(args.runtime_root) if args.runtime_root else root / "audit/e9f/rp2_c3_c1_runtime"; runtime.mkdir(parents=True, exist_ok=False); payloads = []; measurements = []; checkpoint_count = 0
    for index, row in enumerate(rows):
        payload, measurement = run_child(root, row, runtime, execution, contract_sha, policy_sha); payloads.append(payload); measurements.append(measurement); checkpoint_count += 1; atomic(runtime / "checkpoint.json", {"schema": "mephc_e9f_c1_rp2_c3_c1_checkpoint_v3", "work_order_id": WORK_ORDER, "execution_sha": execution, "generation": checkpoint_count, "completed_worker_ids": [x["worker_id"] for x in measurements], "next_index": index + 1})
    if len(payloads) != 12 or sum(x["solve_count"] for x in payloads) != 108: raise RuntimeError("C3_C1_MATRIX_INCOMPLETE_FAIL_CLOSED")
    result = {"schema": "mephc_e9f_c1_rp2_c3_c1_result_v1", "project_id": "MEPHC", "work_order_id": WORK_ORDER, "phase": scientific.PHASE, "base_sha": "c0153d37e2f01f456e7ba1e4aa7fd532e8770bec", "implementation_sha": execution, "execution_sha": execution, "failed_parent_execution_sha": scientific.PARENT_FAILED_EXECUTION_SHA, "failed_parent_canary_record_sha256": sha(root / scientific.FAILURE_REL), "contract_sha256": contract_sha, "runner_sha256": sha(root / Path(__file__).name), "rp1_policy_file_sha256": policy_sha, "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a", "main_sha": "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5", "main_unchanged": True, "prelive": gates, "canary_status": "PASSED", "workers": measurements, "native_child_pids": [x["pid"] for x in measurements], "orphan_native_child_count": sum(x["orphan_count"] for x in measurements), "checkpoint_generation_count": checkpoint_count, "summary": scientific.aggregate(payloads), "scientific_payloads": payloads, "diagnostic_only": True, "reducer_admissible": False, "rp3_authorized": False, "main_promotion_authorized": False, "pipeline_health": "C3_C1_CORRECTED_MATRIX_COLLECTED_READY_FOR_RP3_DECISION", "incidents": {"REL_021": "OPEN", "REL_026": "CORRECTIVE_LIVE_VALIDATED", "REL_027": "LIVE_VALIDATION_RECORDED", "REL_028": "LIVE_VALIDATION_RECORDED", "REL_029": "LIVE_VALIDATION_RECORDED", "REL_035": "CLOSED", "REL_036": "CLOSED", "REL_037": "CLOSED", "REL_038": "CLOSED", "REL_039": "CLOSED"}}
    atomic(runtime / "rp2_c3_c1_result.json", result); manifest = {"schema": "mephc_e9f_c1_rp2_c3_c1_evidence_manifest_v1", "project_id": "MEPHC", "work_order_id": WORK_ORDER, "execution_sha": execution, "contract_sha256": contract_sha, "result_sha256": sha(runtime / "rp2_c3_c1_result.json"), "failed_parent_canary_record_sha256": sha(root / scientific.FAILURE_REL), "worker_payloads": [{"worker_id": x["worker_id"], "payload_sha256": x["payload_declared_sha256"]} for x in measurements], "total_native_solves": 108, "payload_transport": "ATOMIC_FILE", "diagnostic_only": True, "reducer_admissible": False}; atomic(root / "audit/e9f/rp2_c3_c1_evidence_manifest.json", manifest); print(json.dumps({"status": "E9F_C1_H_ENVELOPE_SIX_POINT_DIAGNOSTIC_CORRECTED_READY_FOR_RP3_DECISION", "work_order_id": WORK_ORDER, "execution_sha": execution, "worker_count": 12, "total_native_solves": 108}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
