"""C3.C4 native child using the shared finalizer."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from audit.e9f import c3_c4_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as science


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("root", "worker-id", "coordinate-json", "payload-path", "failure-path", "execution-sha", "contract-sha256", "rp1-policy-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--resolution", type=int, required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve(); payload_path = Path(args.payload_path).resolve(); failure_path = Path(args.failure_path).resolve()
    row = next((item for item in science.build_plan(root) if item["sample_id"] == args.worker_id), None)
    if row is None: raise RuntimeError("C3_C4_UNKNOWN_WORKER")
    stage = "preflight_identity"; native_solve_count = 0
    try:
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != args.execution_sha: raise RuntimeError("C3_C4_EXECUTION_SHA_MISMATCH")
        contract_path = root / "audit/e9f/rp2_c3_c4_execution_contract.json"
        if runtime.sha(contract_path) != args.contract_sha256 or runtime.sha(root / science.POLICY_REL) != args.rp1_policy_sha256: raise RuntimeError("C3_C4_CONTRACT_POLICY_SHA_MISMATCH")
        science.validate_worker_identity(row, args.worker_id, args.resolution, json.loads(args.coordinate_json))
        expected = runtime.identity_for(row=row, execution_sha=args.execution_sha, contract_sha256=args.contract_sha256, policy_sha256=args.rp1_policy_sha256)
        stage = "science_compute"
        with contextlib.redirect_stdout(sys.stderr): raw = science.compute_worker(root, row)
        native_solve_count = int(raw["solve_count"])
        stage = "payload_finalize"
        payload = runtime.finalize_payload(raw, row=row, expected_identity=expected)
        stage = "payload_validate"
        runtime.validate_payload(payload, row=row, expected_identity=expected)
        stage = "payload_atomic_write"
        runtime.atomic_write(payload_path, payload)
        if runtime.sha(payload_path) == payload["payload_body_sha256"]: raise RuntimeError("C3_C4_HASH_SEMANTICS_COLLISION_UNEXPECTED")
        return 0
    except Exception as exc:
        runtime.atomic_write(failure_path, {"schema": "mephc_e9f_c1_rp2_c3_c4_failure_sidecar_v3", "project_id": "MEPHC", "work_order_id": runtime.WORK_ORDER, "execution_sha": args.execution_sha, "worker_id": args.worker_id, "source_sample_id": row["source_sample_id"], "logical_sample_index": int(row["sample_index"]), "resolution": 64, "stage": stage, "native_solve_count": native_solve_count, "exception_type": type(exc).__name__, "exception_message": str(exc), "traceback_tail": traceback.format_exc()[-65536:], "payload_final_exists": payload_path.exists(), "temporary_payload_paths": [str(item) for item in payload_path.parent.glob("*.tmp")], "child_pid": os.getpid()})
        raise


if __name__ == "__main__": raise SystemExit(main())
