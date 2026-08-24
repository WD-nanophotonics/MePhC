"""C3.C2 native child with atomic success and failure sidecars."""
from __future__ import annotations
import argparse, contextlib, hashlib, json, os, sys, subprocess, traceback
from pathlib import Path
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as scientific

def canonical(value: object) -> bytes: return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as h: h.write(canonical(value)); h.flush(); os.fsync(h.fileno())
    os.replace(tmp, path)

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", required=True); parser.add_argument("--worker-id", required=True); parser.add_argument("--resolution", required=True, type=int); parser.add_argument("--coordinate-json", required=True); parser.add_argument("--payload-path", required=True); parser.add_argument("--failure-path", required=True); parser.add_argument("--execution-sha", required=True); parser.add_argument("--contract-sha256", required=True); parser.add_argument("--rp1-policy-sha256", required=True); args = parser.parse_args(); root = Path(args.root).resolve(); payload_path = Path(args.payload_path).resolve(); failure_path = Path(args.failure_path).resolve(); row = next((x for x in scientific.build_plan(root) if x["sample_id"] == args.worker_id), None)
    if row is None: raise RuntimeError("C3_C2_UNKNOWN_WORKER")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != args.execution_sha: raise RuntimeError("C3_C2_EXECUTION_SHA_MISMATCH")
    if scientific.sha(root / scientific.CONTRACT_REL) != args.contract_sha256 or scientific.sha(root / scientific.POLICY_REL) != args.rp1_policy_sha256: raise RuntimeError("C3_C2_CONTRACT_POLICY_SHA_MISMATCH")
    scientific.validate_worker_identity(row, args.worker_id, args.resolution, json.loads(args.coordinate_json))
    try:
        with contextlib.redirect_stdout(sys.stderr): payload = scientific.compute_worker(root, row)
        scientific.validate_worker_payload(payload, row); payload = dict(payload); payload["c3_c2_transport_binding"] = {"project_id": "MEPHC", "work_order_id": scientific.WORK_ORDER, "execution_sha": args.execution_sha, "worker_id": args.worker_id, "resolution": 64, "contract_sha256": args.contract_sha256, "rp1_policy_sha256": args.rp1_policy_sha256, "payload_transport": "ATOMIC_FILE"}; payload["payload_sha256"] = hashlib.sha256(canonical(payload)).hexdigest(); atomic(payload_path, payload); return 0
    except Exception as exc:
        sidecar = {"schema": "mephc_e9f_c1_rp2_c3_c2_failure_sidecar_v1", "project_id": "MEPHC", "work_order_id": scientific.WORK_ORDER, "execution_sha": args.execution_sha, "worker_id": args.worker_id, "source_sample_id": row["source_sample_id"], "logical_sample_index": int(row["sample_index"]), "resolution": 64, "stage": "compute_worker", "native_solve_count": None, "exception_type": type(exc).__name__, "exception_message": str(exc), "traceback_tail": traceback.format_exc()[-65536:], "payload_final_exists": payload_path.exists(), "temporary_payload_paths": [str(x) for x in payload_path.parent.glob("*.tmp")], "child_pid": os.getpid()}; atomic(failure_path, sidecar); raise

if __name__ == "__main__": raise SystemExit(main())
