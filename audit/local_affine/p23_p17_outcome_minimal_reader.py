"""Read the exact P18 result and expose only scalar P17 outcome facts."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P23-P17-OUTCOME-MINIMAL-READER-20260830-387"
P18_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P18-P17-RESULT-SALVAGE-20260830-382"
P18_JOB_ID = "MEPHC-SCIENCE-c4be5a365f9086b503caaf11"
P18_SCHEMA = "mephc-local-affine-p18-p17-result-salvage-v1"
P17_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P17-PRODUCTION-PROVIDER-FAILURE-CAPTURE-20260830-381"


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
    require(p18.get("prior_work_order_id") == P17_WORK_ORDER_ID, "P17_BINDING_WORK_ORDER_INVALID")
    require(p18.get("prior_job_id") == "MEPHC-SCIENCE-e892ea6bb49d20a0ff26ccd6", "P17_BINDING_JOB_INVALID")
    nested = p18.get("prior_result")
    require(isinstance(nested, dict), "P17_BOUNDED_RESULT_MISSING")
    classification = nested.get("classification")
    child_return_code = nested.get("child_return_code")
    stages = nested.get("stage_trace")
    require(isinstance(classification, str), "P17_OUTCOME_CLASSIFICATION_INVALID")
    require(isinstance(child_return_code, int), "P17_CHILD_RETURN_CODE_INVALID")
    require(isinstance(stages, list) and all(isinstance(item, str) for item in stages),
            "P17_STAGE_TRACE_INVALID")

    write_result({
        "schema": "mephc-local-affine-p23-p17-outcome-v1",
        "work_order_id": WORK_ORDER_ID,
        "p18_result_job_id": P18_JOB_ID,
        "p18_schema_verified": True,
        "p17_binding_verified_from_p18_top_level": True,
        "nested_p17_result_verified": True,
        "p17_child_return_code_classified": True,
        "p17_classification": classification,
        "p17_child_return_code": child_return_code,
        "p17_stage_count": len(stages),
        "p17_faulthandler_enabled": nested.get("faulthandler_enabled") is True,
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
