"""Expose the actual bounded P17 fields carried by the exact P18 result."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P22-P17-OUTCOME-EXPOSE-ACTUAL-SCHEMA-20260830-386"
P18_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P18-P17-RESULT-SALVAGE-20260830-382"
P18_JOB_ID = "MEPHC-SCIENCE-c4be5a365f9086b503caaf11"
P18_SOURCE_COMMIT = "8a746f0443ec74b892301675519a67023553f4af"
P18_SCHEMA = "mephc-local-affine-p18-p17-result-salvage-v1"
P17_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P17-PRODUCTION-PROVIDER-FAILURE-CAPTURE-20260830-381"
P17_SOURCE_COMMIT = "dd76e7d7898a2ffbc8df69550a4a2ed4b6862955"


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
    p18_path = result_path.parent / f"{P18_JOB_ID}.json"
    require(p18_path.is_file(), "P18_RESULT_FILE_MISSING")
    p18 = json.loads(p18_path.read_text(encoding="utf-8"))
    require(p18.get("schema") == P18_SCHEMA, "P18_RESULT_SCHEMA_INVALID")
    require(p18.get("work_order_id") == P18_WORK_ORDER_ID, "P18_RESULT_WORK_ORDER_INVALID")
    require(p18.get("source_commit") == P18_SOURCE_COMMIT, "P18_RESULT_SOURCE_INVALID")
    require(p18.get("prior_work_order_id") == P17_WORK_ORDER_ID, "P17_BINDING_WORK_ORDER_INVALID")
    require(p18.get("prior_source_commit") == P17_SOURCE_COMMIT, "P17_BINDING_SOURCE_INVALID")
    require(p18.get("prior_result_schema_verified") is True and p18.get("prior_result_source_verified") is True,
            "P18_ACTUAL_SCHEMA_FIELDS_INVALID")
    nested = p18.get("prior_result")
    require(isinstance(nested, dict), "P17_BOUNDED_RESULT_MISSING")
    classification = nested.get("classification")
    require(classification in {"P17_PRODUCTION_PROVIDER_SUCCESS", "P17_PRODUCTION_PROVIDER_FAILURE_CAPTURED"},
            "P17_OUTCOME_CLASSIFICATION_INVALID")
    child_return_code = nested.get("child_return_code")
    require(isinstance(child_return_code, int), "P17_CHILD_RETURN_CODE_INVALID")
    stages = nested.get("stage_trace")
    require(isinstance(stages, list) and all(isinstance(item, str) for item in stages),
            "P17_STAGE_TRACE_INVALID")

    write_result({
        "schema": "mephc-local-affine-p22-p17-outcome-expose-v1",
        "work_order_id": WORK_ORDER_ID,
        "p18_result_job_id": P18_JOB_ID,
        "p18_result_schema_verified": True,
        "p18_result_source_verified": True,
        "p18_actual_schema_fields_verified": True,
        "nested_p17_bounded_result_verified": True,
        "p17_child_outcome_classified": True,
        "p17_work_order_id": P17_WORK_ORDER_ID,
        "p17_source_commit": P17_SOURCE_COMMIT,
        "p17_classification": classification,
        "p17_child_return_code": child_return_code,
        "p17_stage_count": len(stages),
        "p17_faulthandler_enabled": nested.get("faulthandler_enabled") is True,
        "p17_parent_result_written": nested.get("parent_result_written_even_if_child_fails") is True,
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
