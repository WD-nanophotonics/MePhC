"""C3.C5 matrix checkpoint validation with no phantom completion."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from audit.e9f import c3_c5_runtime as runtime


def validate(checkpoint: Mapping[str, Any], *, root: Path, rows: Mapping[str, Mapping[str, Any]]) -> None:
    if checkpoint.get("schema") != runtime.CHECKPOINT_SCHEMA or checkpoint.get("work_order_id") != runtime.WORK_ORDER or checkpoint.get("phase") != runtime.PHASE:
        raise ValueError("C3_C5_CHECKPOINT_IDENTITY")
    execution_sha = checkpoint.get("execution_sha")
    contract_sha256 = checkpoint.get("contract_sha256")
    policy_sha256 = checkpoint.get("rp1_policy_file_sha256")
    if not isinstance(execution_sha, str) or not isinstance(contract_sha256, str) or not isinstance(policy_sha256, str):
        raise ValueError("C3_C5_CHECKPOINT_IDENTITY")
    for item in checkpoint.get("completed_workers", []):
        worker_id = item.get("worker_id")
        row = rows.get(worker_id)
        if row is None or item.get("resolution") != row["resolution"]:
            raise ValueError("C3_C5_CHECKPOINT_WORKER_IDENTITY")
        path = Path(item.get("payload_path", ""))
        if not path.is_file() or runtime.sha(path) != item.get("payload_file_sha256"):
            raise ValueError("C3_C5_CHECKPOINT_FILE_HASH")
        payload = json.loads(path.read_text())
        expected_identity = runtime.identity_for(row=row, execution_sha=execution_sha, contract_sha256=contract_sha256, policy_sha256=policy_sha256)
        try:
            runtime.validate_payload(payload, row=row, expected_identity=expected_identity)
        except ValueError as exc:
            raise ValueError(f"C3_C5_CHECKPOINT_IDENTITY:{exc}") from exc
        if payload.get("payload_body_sha256") != item.get("payload_body_sha256") or runtime.body_hash(payload) != item.get("payload_body_sha256"):
            raise ValueError("C3_C5_CHECKPOINT_BODY_HASH")
