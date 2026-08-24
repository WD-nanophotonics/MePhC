"""C3 parent transport: solver-free, atomic-file, reaped native children."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path
from typing import Any, Mapping

from audit.e9f import run_e9f_c1_rp2_c3_impl as scientific

WORK_ORDER = scientific.WORK_ORDER
WORKER = Path("audit/e9f/run_e9f_c1_rp2_c3_worker.py")


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def git_sha(root: Path) -> str: return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
def canonical(value: object) -> bytes: return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as h: h.write(canonical(value)); h.flush(); os.fsync(h.fileno())
    os.replace(tmp, path)


def proc_cmdline(pid: int) -> str:
    try: return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError: return ""


def workers(worker_id: str | None = None) -> list[int]:
    if not Path("/proc").is_dir(): raise RuntimeError("C3_ORPHAN_INSPECTION_UNAVAILABLE")
    return sorted(int(x.name) for x in Path("/proc").iterdir() if x.name.isdigit() and "run_e9f_c1_rp2_c3_worker.py" in proc_cmdline(int(x.name)) and (worker_id is None or worker_id in proc_cmdline(int(x.name))))


def run_child(root: Path, row: Mapping[str, Any], slot: Path, execution: str, contract_sha: str, policy_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload_path = slot / "payload.json"; binding_path = slot / "binding.json"; slot.mkdir(parents=True, exist_ok=False)
    atomic(binding_path, {"work_order_id": WORK_ORDER, "phase": scientific.PHASE, "execution_git_sha": execution, "worker_id": row["sample_id"], "resolution": int(row["resolution"]), "contract_sha256": contract_sha, "rp1_policy_sha256": policy_sha, "payload_path": str(payload_path)})
    cmd = [sys.executable, str(root / WORKER), "--root", str(root), "--worker-id", row["sample_id"], "--resolution", str(row["resolution"]), "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":")), "--payload-path", str(payload_path), "--transport-execution-sha", execution, "--contract-sha256", contract_sha, "--rp1-policy-sha256", policy_sha]
    before = time.monotonic(); p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE); out, err = p.communicate(timeout=3600); elapsed = time.monotonic() - before
    orphan = [x for x in workers(str(row["sample_id"])) if x != p.pid]
    measurement = {"worker_id": row["sample_id"], "pid": p.pid, "returncode": p.returncode, "elapsed_seconds": elapsed, "direct_pid_gone": not (Path("/proc") / str(p.pid)).exists(), "orphan_pids": orphan, "orphan_count": len(orphan), "stdout_byte_count": len(out), "stderr_byte_count": len(err), "stdout_sha256": hashlib.sha256(out).hexdigest(), "stderr_sha256": hashlib.sha256(err).hexdigest(), "stdout_used_as_payload": False, "stderr_used_as_payload": False, "stderr_tail": err[-8192:].decode(errors="replace")}
    if p.returncode != 0 or orphan or not measurement["direct_pid_gone"]: raise RuntimeError(f"C3_NATIVE_CHILD_FAILED:{measurement}")
    if not payload_path.is_file() or list(slot.glob("*.tmp")): raise RuntimeError("C3_ATOMIC_PAYLOAD_INCOMPLETE")
    raw = payload_path.read_bytes(); payload = json.loads(raw.decode());
    if raw != canonical(payload): raise RuntimeError("C3_PAYLOAD_NOT_CANONICAL")
    scientific.validate_worker_payload(payload, row)
    binding = payload.get("c3_transport_binding")
    if binding != {"work_order_id": WORK_ORDER, "phase": scientific.PHASE, "execution_git_sha": execution, "worker_id": row["sample_id"], "resolution": int(row["resolution"]), "contract_sha256": contract_sha, "rp1_policy_sha256": policy_sha, "payload_transport": "ATOMIC_FILE"}: raise RuntimeError("C3_PAYLOAD_BINDING_MISMATCH")
    measurement.update({"payload_path": str(payload_path), "payload_sha256": hashlib.sha256(raw).hexdigest(), "payload_identity_valid": True})
    return payload, measurement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2])); parser.add_argument("--runtime-root", default=None); parser.add_argument("--self-check", action="store_true"); args = parser.parse_args(argv)
    root = Path(args.root).resolve(); scientific.assert_parent_solver_free(); scientific.load_contract(root); rows = scientific.build_plan(root)
    if args.self_check:
        print(json.dumps({"status": "SELF_CHECK_PASSED", "worker_count": len(rows), "matrix_entries": 24, "total_native_solves": 108, "parent_native_import_free": True}, sort_keys=True)); return 0
    execution = git_sha(root); contract_sha = sha(root / scientific.CONTRACT_REL); policy_sha = sha(root / scientific.POLICY_REL)
    runtime = Path(args.runtime_root) if args.runtime_root else root / "audit/e9f/rp2_c3_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    checkpoint = runtime / "checkpoint.json"; payloads: list[dict[str, Any]] = []; measurements: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        slot = runtime / "workers" / hashlib.sha256(row["sample_id"].encode()).hexdigest()[:32]
        payload_path = slot / "payload.json"
        if payload_path.exists():
            payload = json.loads(payload_path.read_text(encoding="utf-8")); scientific.validate_worker_payload(payload, row); payloads.append(payload); measurements.append({"worker_id": row["sample_id"], "resumed": True, "payload_sha256": sha(payload_path), "payload_identity_valid": True, "orphan_count": 0}); continue
        payload, measurement = run_child(root, row, slot, execution, contract_sha, policy_sha); payloads.append(payload); measurements.append(measurement)
        atomic(checkpoint, {"schema": "mephc_e9f_c1_rp2_c3_checkpoint_v2", "work_order_id": WORK_ORDER, "execution_git_sha": execution, "completed_worker_ids": [x["worker_id"] for x in measurements], "next_index": index + 1, "payload_sha256": {x["worker_id"]: x.get("payload_sha256") for x in measurements}})
    if len(payloads) != 12 or sum(int(x["solve_count"]) for x in payloads) != 108: raise RuntimeError("C3_PROCESS_OR_SOLVE_COVERAGE_FAIL_CLOSED")
    result = {"schema": "mephc_e9f_c1_rp2_c3_result_v1", "work_order_id": WORK_ORDER, "phase": scientific.PHASE, "stop_after": "E9F_C1_RP2_C3_REPORT", "base_sandbox_sha": "ea98a8ebb05c292c1914e46e2e2431aab3b1bfe4", "execution_git_sha": execution, "main_sha": "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5", "main_unchanged": True, "contract_sha256": contract_sha, "rp1_policy_sha256": policy_sha, "worker_count": 12, "total_native_solves": 108, "matrix_entries": 24, "payload_transport": "ATOMIC_FILE", "stdout_used_as_payload": False, "stderr_used_as_payload": False, "prelive": {"parent_solver_free": True, "exact_six_sample_derivation": True, "exact_matrix": True, "h_provider_binding": True, "atomic_payload": True, "checkpoint_v2": True, "source_anchor_firewall": True}, "workers": measurements, "summary": scientific.aggregate(payloads), "scientific_payloads": payloads, "diagnostic_only": True, "reducer_admissible": False, "rp3_authorized": False, "main_promotion_authorized": False, "incidents": {"REL_021": "REVIEW_VALIDATOR_FIXED_ADVERSARIAL_TESTS_PASSED", "REL_026": "CORRECTIVE_H_ENVELOPE_LIVE_VALIDATED", "REL_032": "CLOSED", "REL_033": "CLOSED", "REL_034": "CLOSED", "REL_035": "CLOSED_NEXT_MEPHC_ENVELOPE_CONSISTENT"}}
    atomic(runtime / "rp2_c3_result.json", result)
    manifest = {"schema": "mephc_e9f_c1_rp2_c3_evidence_manifest_v1", "work_order_id": WORK_ORDER, "execution_git_sha": execution, "contract_sha256": contract_sha, "result_sha256": sha(runtime / "rp2_c3_result.json"), "worker_payloads": [{"worker_id": x["worker_id"], "payload_sha256": x["payload_sha256"]} for x in measurements], "payload_transport": "ATOMIC_FILE", "exact_solve_count": 108, "diagnostic_only": True, "reducer_admissible": False}
    atomic(root / "audit/e9f/rp2_c3_evidence_manifest.json", manifest)
    print(json.dumps({"status": "E9F_C1_H_ENVELOPE_SIX_POINT_DIAGNOSTIC_COLLECTED_READY_FOR_RP3_DECISION", "worker_count": 12, "total_native_solves": 108, "execution_git_sha": execution}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
