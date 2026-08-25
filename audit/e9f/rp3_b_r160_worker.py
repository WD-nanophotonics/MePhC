"""RP3.B R160 worker; actual provider resolution is row-bound."""
from __future__ import annotations
import argparse
import contextlib
import json
import os
import traceback
from pathlib import Path
from audit.e9f import c3_c5_runtime as c35
from audit.e9f import rp3_b_r160_runtime as rp3


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("root", "worker-id", "payload-path", "failure-path", "execution-sha", "contract-sha256", "rp1-policy-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--resolution", type=int, required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    rows = rp3.build_plan(root)
    row = next((item for item in rows if item["sample_id"] == args.worker_id), None)
    if row is None or args.resolution != 160 or row["resolution"] != args.resolution:
        raise RuntimeError("RP3_B_WORKER_IDENTITY_FAIL_CLOSED")
    payload_path = Path(args.payload_path).resolve()
    failure_path = Path(args.failure_path).resolve()
    stage = "preflight_identity"
    try:
        if c35.sha(root / "audit/e9f/rp3_a_c1_process_seal.json") != "252e23d92d8e24ed894c1fbc24def06e7922040d475187918dc254c49e7fab9d":
            raise RuntimeError("RP3_B_PROCESS_SEAL_BINDING_FAIL_CLOSED")
        stage = "science_compute"
        expected = rp3.identity_for(row=row, execution_sha=args.execution_sha, contract_sha256=args.contract_sha256, policy_sha256=args.rp1_policy_sha256)
        with contextlib.redirect_stdout(__import__("sys").stderr):
            raw = c35.compute_worker(root, row)
        stage = "payload_finalize"
        payload = c35.finalize_payload(raw, row=row, expected_identity=expected)
        payload["rp3_replay_policy"] = "NOT_APPLICABLE_R160"
        payload["rp3_replay_reason"] = "ORIGINAL_RP2_HAS_NO_R160_KEY"
        for point in payload.get("all_point_metrics", []):
            replay = point.setdefault("frequency_replay", {})
            replay["matched"] = False
            replay["reason"] = "R160_NOT_APPLICABLE_ORIGINAL_RP2_HAS_NO_R160_KEY"
            replay["prior_frequencies_all6"] = None
            replay["max_abs_difference"] = None
        payload["payload_body_sha256"] = c35.body_hash(payload)
        stage = "payload_validate"
        rp3.validate_payload(payload, row=row, expected=expected)
        stage = "payload_atomic_write"
        c35.atomic_write(payload_path, payload)
        if c35.sha(payload_path) == payload["payload_body_sha256"]:
            raise RuntimeError("RP3_B_HASH_COLLISION")
        return 0
    except Exception as exc:
        c35.atomic_write(failure_path, {"schema":"mephc_e9f_c1_rp3_b_failure_sidecar_v1","project_id":"MEPHC","work_order_id":rp3.WORK_ORDER,"phase":rp3.PHASE,"execution_sha":args.execution_sha,"worker_id":args.worker_id,"resolution":args.resolution,"stage":stage,"exception_type":type(exc).__name__,"exception_message":str(exc),"traceback_tail":traceback.format_exc()[-65536:],"payload_final_exists":payload_path.exists(),"child_pid":os.getpid()})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
