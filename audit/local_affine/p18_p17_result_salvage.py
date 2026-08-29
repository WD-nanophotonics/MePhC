"""Salvage the exact P17 result after Thin Flow rejected one unsafe key."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P18-P17-RESULT-SALVAGE-20260830-382"
PRIOR_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P17-PRODUCTION-PROVIDER-FAILURE-CAPTURE-20260830-381"
PRIOR_JOB_ID = "MEPHC-SCIENCE-e892ea6bb49d20a0ff26ccd6"
PRIOR_SOURCE_COMMIT = "dd76e7d7898a2ffbc8df69550a4a2ed4b6862955"
PRIOR_SCHEMA = "mephc-local-affine-p17-production-provider-failure-capture-v1"


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
    prior_path = result_path.parent / f"{PRIOR_JOB_ID}.json"
    require(prior_path.is_file(), "PRIOR_RESULT_FILE_MISSING")
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    require(prior.get("schema") == PRIOR_SCHEMA, "PRIOR_RESULT_SCHEMA_INVALID")
    require(prior.get("work_order_id") == PRIOR_WORK_ORDER_ID, "PRIOR_RESULT_WORK_ORDER_INVALID")
    require(prior.get("source_commit") == PRIOR_SOURCE_COMMIT, "PRIOR_RESULT_SOURCE_INVALID")
    require(prior.get("failure_or_success_classification_status") == "PASS", "PRIOR_RESULT_CLASSIFICATION_INVALID")

    # Copy only scalar and bounded diagnostic fields; the rejected key is intentionally omitted.
    allowed = {
        "native_invocation_count", "provider_execution_count", "solver_execution_count",
        "diagnostic_child_process_count", "parent_result_written_even_if_child_fails",
        "faulthandler_enabled", "durable_stage_trace_captured", "stage_trace", "child_return_code",
        "classification", "failure_or_success_classification_status",
        "exact_production_local_affine_provider_path_used", "formal_scientific_dataset_records",
        "retry_count", "cache_reuse_count", "status",
    }
    copied = {key: prior[key] for key in sorted(allowed) if key in prior}
    require(copied.get("parent_result_written_even_if_child_fails") is True, "PRIOR_RESULT_PARENT_WRITE_NOT_VERIFIED")
    write_result({
        "schema": "mephc-local-affine-p18-p17-result-salvage-v1",
        "work_order_id": WORK_ORDER_ID,
        "prior_work_order_id": PRIOR_WORK_ORDER_ID,
        "prior_job_id": PRIOR_JOB_ID,
        "prior_source_commit": PRIOR_SOURCE_COMMIT,
        "prior_result_schema_verified": True,
        "prior_result_source_verified": True,
        "prior_result_salvaged": True,
        "sanitized_result_safe": True,
        "native_invocation_count": 0,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "formal_scientific_dataset_records": 0,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "result_written_to_mephc_result_path": True,
        "prior_result": copied,
        "status": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
