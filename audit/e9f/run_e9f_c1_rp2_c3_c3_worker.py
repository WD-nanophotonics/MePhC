"""C3.C3 native child with separate body/file hashes and failure sidecar."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from audit.e9f import c3_c3_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c1_impl as base
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as c2


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(runtime.canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--resolution", required=True, type=int)
    parser.add_argument("--coordinate-json", required=True)
    parser.add_argument("--payload-path", required=True)
    parser.add_argument("--failure-path", required=True)
    parser.add_argument("--execution-sha", required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--rp1-policy-sha256", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    payload_path = Path(args.payload_path).resolve()
    failure_path = Path(args.failure_path).resolve()
    row = next((item for item in c2.build_plan(root) if item["sample_id"] == args.worker_id), None)
    if row is None:
        raise RuntimeError("C3_C3_UNKNOWN_WORKER")
    native_solve_count = 0
    try:
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != args.execution_sha:
            raise RuntimeError("C3_C3_EXECUTION_SHA_MISMATCH")
        contract_path = root / "audit/e9f/rp2_c3_c3_execution_contract.json"
        if runtime.sha(contract_path) != args.contract_sha256 or runtime.sha(root / base.POLICY_REL) != args.rp1_policy_sha256:
            raise RuntimeError("C3_C3_CONTRACT_POLICY_SHA_MISMATCH")
        c2.validate_worker_identity(row, args.worker_id, args.resolution, json.loads(args.coordinate_json))
        with contextlib.redirect_stdout(sys.stderr):
            payload = c2.compute_worker(root, row)
        native_solve_count = int(payload["solve_count"])
        payload = dict(payload)
        payload.update({"schema": runtime.PAYLOAD_SCHEMA, "work_order_id": runtime.WORK_ORDER, "phase": runtime.PHASE, "project_id": "MEPHC", "rp1_policy_file_sha256": args.rp1_policy_sha256, "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a"})
        for point in payload["all_point_metrics"]:
            point.setdefault("H_GATE", {})["orthogonality_tolerance"] = runtime.H_TOL
        binding = runtime.expected_binding(row=row, execution_sha=args.execution_sha, contract_sha256=args.contract_sha256, policy_sha256=args.rp1_policy_sha256)
        payload["c3_c3_transport_binding"] = binding
        payload["payload_body_sha256"] = runtime.body_hash(payload)
        runtime.validate_payload(payload, row=row, expected=binding)
        atomic(payload_path, payload)
        if runtime.sha(payload_path) == payload["payload_body_sha256"]:
            raise RuntimeError("C3_C3_HASH_SEMANTICS_COLLISION_UNEXPECTED")
        return 0
    except Exception as exc:
        sidecar = {"schema": "mephc_e9f_c1_rp2_c3_c3_failure_sidecar_v2", "project_id": "MEPHC", "work_order_id": runtime.WORK_ORDER, "execution_sha": args.execution_sha, "worker_id": args.worker_id, "source_sample_id": row["source_sample_id"], "logical_sample_index": int(row["sample_index"]), "resolution": 64, "stage": "compute_or_publish_payload", "native_solve_count": native_solve_count, "exception_type": type(exc).__name__, "exception_message": str(exc), "traceback_tail": traceback.format_exc()[-65536:], "payload_final_exists": payload_path.exists(), "temporary_payload_paths": [str(item) for item in payload_path.parent.glob("*.tmp")], "child_pid": os.getpid()}
        atomic(failure_path, sidecar)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
