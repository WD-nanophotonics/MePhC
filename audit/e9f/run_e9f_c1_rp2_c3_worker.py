"""Native C3 child: compute exactly one sample/resolution payload atomically."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

from audit.e9f import run_e9f_c1_rp2_c3_impl as scientific

WORK_ORDER = scientific.WORK_ORDER


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): raise RuntimeError("C3_PAYLOAD_PREEXISTING")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if tmp.exists(): raise RuntimeError("C3_PAYLOAD_TEMP_PREEXISTING")
    try:
        with tmp.open("wb") as handle:
            handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True); parser.add_argument("--worker-id", required=True)
    parser.add_argument("--resolution", required=True, type=int); parser.add_argument("--coordinate-json", required=True)
    parser.add_argument("--payload-path", required=True); parser.add_argument("--transport-execution-sha", required=True)
    parser.add_argument("--contract-sha256", required=True); parser.add_argument("--rp1-policy-sha256", required=True)
    args = parser.parse_args(); root = Path(args.root).resolve()
    if __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != args.transport_execution_sha: raise RuntimeError("C3_EXECUTION_SHA_MISMATCH")
    contract = root / scientific.CONTRACT_REL
    if __import__("hashlib").sha256(contract.read_bytes()).hexdigest() != args.contract_sha256: raise RuntimeError("C3_CONTRACT_SHA_MISMATCH")
    rows = scientific.build_plan(root); row = next((x for x in rows if x["sample_id"] == args.worker_id), None)
    if row is None: raise RuntimeError("C3_UNKNOWN_WORKER")
    scientific.validate_worker_identity(row, args.worker_id, args.resolution, json.loads(args.coordinate_json))
    with __import__("contextlib").redirect_stdout(sys.stderr): payload = scientific.compute_worker(root, row)
    scientific.validate_worker_payload(payload, row)
    payload = dict(payload); payload["c3_transport_binding"] = {"work_order_id": WORK_ORDER, "phase": scientific.PHASE, "execution_git_sha": args.transport_execution_sha, "worker_id": args.worker_id, "resolution": args.resolution, "contract_sha256": args.contract_sha256, "rp1_policy_sha256": args.rp1_policy_sha256, "payload_transport": "ATOMIC_FILE"}
    write_atomic(Path(args.payload_path).resolve(), payload)
    return 0


if __name__ == "__main__": raise SystemExit(main())
