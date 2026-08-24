"""Atomic native C3.C1 child."""
from __future__ import annotations
import argparse, contextlib, hashlib, json, os, subprocess, sys
from pathlib import Path
from audit.e9f import run_e9f_c1_rp2_c3_c1_impl as scientific


def canonical(value: object) -> bytes: return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as handle: handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", required=True); parser.add_argument("--worker-id", required=True); parser.add_argument("--resolution", required=True, type=int); parser.add_argument("--coordinate-json", required=True); parser.add_argument("--payload-path", required=True); parser.add_argument("--execution-sha", required=True); parser.add_argument("--contract-sha256", required=True); parser.add_argument("--rp1-policy-sha256", required=True); args = parser.parse_args()
    root = Path(args.root).resolve(); actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if actual != args.execution_sha: raise RuntimeError("C3_C1_EXECUTION_SHA_MISMATCH")
    if scientific.sha(root / scientific.CONTRACT_REL) != args.contract_sha256 or scientific.sha(root / scientific.POLICY_REL) != args.rp1_policy_sha256: raise RuntimeError("C3_C1_CONTRACT_OR_POLICY_SHA_MISMATCH")
    row = next((x for x in scientific.build_plan(root) if x["sample_id"] == args.worker_id), None)
    if row is None: raise RuntimeError("C3_C1_UNKNOWN_WORKER")
    scientific.validate_worker_identity(row, args.worker_id, args.resolution, json.loads(args.coordinate_json))
    with contextlib.redirect_stdout(sys.stderr): payload = scientific.compute_worker(root, row)
    scientific.validate_worker_payload(payload, row)
    payload = dict(payload); binding = {"project_id": "MEPHC", "work_order_id": scientific.WORK_ORDER, "phase": scientific.PHASE, "execution_sha": args.execution_sha, "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "resolution": int(row["resolution"]), "contract_sha256": args.contract_sha256, "rp1_policy_sha256": args.rp1_policy_sha256, "payload_transport": "ATOMIC_FILE"}; payload["c3_c1_transport_binding"] = binding; payload["payload_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    atomic(Path(args.payload_path).resolve(), payload); return 0


if __name__ == "__main__": raise SystemExit(main())
