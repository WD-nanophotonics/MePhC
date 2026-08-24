"""Native child for C2.C1: atomically publish the frozen C2 payload to a file."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import sys

from audit.e9f import run_e9f_c1_rp2_c2_impl as scientific


TRANSPORT_WORK_ORDER = "TRILATT-E9F-C1-RP2-C2-C1-20260825-234"
TRANSPORT_PHASE = "E9F.C1.RP2.C2.C1"
TRANSPORT_CONTRACT_REL = Path("audit/e9f/rp2_c2_c1_transport_contract.json")


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _git_sha(root: Path) -> str:
    import subprocess
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _write_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if path.exists() or temporary.exists():
        raise RuntimeError("C2_C1_PAYLOAD_PATH_PREEXISTING")
    encoded = _canonical_json(payload)
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def run_worker(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    payload_path = Path(args.payload_path).resolve()
    expected_sha = _git_sha(root)
    if expected_sha != args.transport_execution_sha:
        raise RuntimeError("C2_C1_TRANSPORT_EXECUTION_SHA_MISMATCH")
    contract = json.loads((root / TRANSPORT_CONTRACT_REL).read_text(encoding="utf-8"))
    if contract["scientific_contract_sha256"] != args.scientific_contract_sha256:
        raise RuntimeError("C2_C1_SCIENTIFIC_CONTRACT_SHA_MISMATCH")
    if contract["scientific_impl_git_blob_sha"] != args.scientific_impl_blob_sha:
        raise RuntimeError("C2_C1_SCIENTIFIC_IMPL_BLOB_SHA_MISMATCH")
    rows = scientific.build_plan(root)
    row = next((item for item in rows if item["sample_id"] == args.worker_id), None)
    if row is None:
        raise RuntimeError("C2_C1_UNKNOWN_WORKER_ID")
    if int(row["resolution"]) != int(args.resolution):
        raise RuntimeError("C2_C1_WORKER_RESOLUTION_MISMATCH")
    coordinate = json.loads(args.coordinate_json)
    scientific.validate_worker_identity(row, worker_id=args.worker_id, resolution=args.resolution, coordinate=coordinate)
    if payload_path.exists():
        raise RuntimeError("C2_C1_PAYLOAD_FINAL_PREEXISTING")
    temporary = payload_path.with_name(f".{payload_path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise RuntimeError("C2_C1_PAYLOAD_TEMP_PREEXISTING")
    with contextlib.redirect_stdout(sys.stderr):
        payload = scientific.compute_worker(root, row)
    scientific.validate_worker_payload(payload, row)
    payload = dict(payload)
    payload["c2_c1_transport_binding"] = {
        "transport_work_order_id": TRANSPORT_WORK_ORDER,
        "transport_phase": TRANSPORT_PHASE,
        "scientific_work_order_id": scientific.WORK_ORDER,
        "scientific_phase": scientific.PHASE,
        "transport_execution_git_sha": expected_sha,
        "scientific_contract_sha256": args.scientific_contract_sha256,
        "scientific_impl_git_blob_sha": args.scientific_impl_blob_sha,
        "worker_id": args.worker_id,
        "resolution": int(args.resolution),
    }
    _write_atomic(payload_path, payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--resolution", required=True, type=int)
    parser.add_argument("--coordinate-json", required=True)
    parser.add_argument("--payload-path", required=True)
    parser.add_argument("--transport-execution-sha", required=True)
    parser.add_argument("--scientific-contract-sha256", required=True)
    parser.add_argument("--scientific-impl-blob-sha", required=True)
    args = parser.parse_args(argv)
    return run_worker(args)


if __name__ == "__main__":
    raise SystemExit(main())
