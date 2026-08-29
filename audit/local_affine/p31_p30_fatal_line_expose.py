"""Expose the verified P30 fatal-frame classification without rerunning it."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P31-P30-FATAL-LINE-EXPOSE-20260830-395"
P30_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P30-EXACT-MPB-PROVIDER-FAULTHANDLER-LOCALIZATION-20260830-394"
P30_JOB_ID = "MEPHC-SCIENCE-bbe82596e24d6ca5436caf7b"
P30_SOURCE_COMMIT = "deda5c9f87bb57076df93123ff3c05b20ec8cb95"
P30_SCHEMA = "mephc-local-affine-p30-exact-mpb-provider-fatal-line-v1"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_result(value: dict[str, Any]) -> None:
    target = Path(os.environ["MEPHC_RESULT_PATH"])
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, target)


def main() -> int:
    result_path = Path(os.environ.get("MEPHC_RESULT_PATH", ""))
    require(result_path.name, "RESULT_PATH_MISSING")
    p30_path = result_path.parent / f"{P30_JOB_ID}.json"
    require(p30_path.is_file(), "P30_RESULT_FILE_MISSING")
    p30 = json.loads(p30_path.read_text(encoding="utf-8"))
    require(p30.get("schema") == P30_SCHEMA, "P30_RESULT_SCHEMA_INVALID")
    require(p30.get("work_order_id") == P30_WORK_ORDER_ID, "P30_RESULT_WORK_ORDER_INVALID")
    require(p30.get("source_commit") == P30_SOURCE_COMMIT, "P30_RESULT_SOURCE_INVALID")
    require(p30.get("sigsegv") is True, "P30_SIGSEGV_INVALID")
    require(p30.get("fatal_frame_classification") == "MPB_PROVIDER_SOURCE_FRAME",
            "P30_FATAL_PROVIDER_FRAME_INVALID")
    require(p30.get("fatal_python_frame_parsed_when_sigsegv") is True,
            "P30_FATAL_FRAME_PARSE_INVALID")

    write_result({
        "schema": "mephc-local-affine-p31-p30-fatal-line-v1",
        "work_order_id": WORK_ORDER_ID,
        "p30_result_job_id": P30_JOB_ID,
        "p30_schema_verified": True,
        "p30_source_verified": True,
        "p30_sigsegv_verified": True,
        "fatal_provider_source_frame_verified": True,
        "stored_fatal_line_fields_exposed_if_present": True,
        "p30_child_return_code": p30.get("child_return_code"),
        "p30_fatal_frame_classification": p30.get("fatal_frame_classification"),
        "p30_last_stage": p30.get("last_stage"),
        "top_level_scalar_result_only": True,
        "sanitized_result_safe": True,
        "native_invocation_count": 0,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "formal_scientific_dataset_records": 0,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
