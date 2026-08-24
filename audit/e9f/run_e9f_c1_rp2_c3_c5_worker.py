"""C3.C5 matrix worker; resolution is always taken from the logical row."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from audit.e9f import c3_c5_runtime as runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("root", "worker-id", "coordinate-json", "payload-path", "failure-path", "execution-sha", "contract-sha256", "rp1-policy-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--resolution", type=int, required=True); args = parser.parse_args()
    root = Path(args.root).resolve(); payload_path = Path(args.payload_path).resolve(); failure_path = Path(args.failure_path).resolve(); rows = runtime.build_plan(root); row = next((item for item in rows if item["sample_id"] == args.worker_id), None)
    if row is None: raise RuntimeError("C3_C5_UNKNOWN_WORKER")
    stage = "preflight_identity"; native_solve_count = 0
    try:
        if row["resolution"] != args.resolution or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != args.execution_sha: raise RuntimeError("C3_C5_EXECUTION_OR_RESOLUTION_IDENTITY")
        contract = root / "audit/e9f/rp2_c3_c5_execution_contract.json"
        if runtime.sha(contract) != args.contract_sha256 or runtime.sha(root / "audit/e9f/rp1_recovery_policy_contract.json") != args.rp1_policy_sha256: raise RuntimeError("C3_C5_CONTRACT_POLICY_SHA")
        expected = runtime.identity_for(row=row, execution_sha=args.execution_sha, contract_sha256=args.contract_sha256, policy_sha256=args.rp1_policy_sha256)
        stage = "science_compute"
        from audit.e9f import c3_c5_runtime as science
        with contextlib.redirect_stdout(sys.stderr): raw = science.compute_worker(root, row)
        native_solve_count = int(raw["solve_count"])
        stage = "payload_finalize"; payload = science.finalize_payload(raw, row=row, expected_identity=expected)
        stage = "payload_validate"; science.validate_payload(payload, row=row, expected_identity=expected)
        stage = "payload_atomic_write"; science.atomic_write(payload_path, payload)
        if runtime.sha(payload_path) == payload["payload_body_sha256"]: raise RuntimeError("C3_C5_HASH_COLLISION")
        return 0
    except Exception as exc:
        runtime.atomic_write(failure_path, {"schema":"mephc_e9f_c1_rp2_c3_c5_failure_sidecar_v1","project_id":"MEPHC","work_order_id":runtime.WORK_ORDER,"execution_sha":args.execution_sha,"worker_id":args.worker_id,"resolution":args.resolution,"stage":stage,"native_solve_count":native_solve_count,"exception_type":type(exc).__name__,"exception_message":str(exc),"traceback_tail":traceback.format_exc()[-65536:],"payload_final_exists":payload_path.exists(),"temporary_payload_paths":[str(item) for item in payload_path.parent.glob("*.tmp")],"child_pid":os.getpid()}); raise


if __name__ == "__main__": raise SystemExit(main())
