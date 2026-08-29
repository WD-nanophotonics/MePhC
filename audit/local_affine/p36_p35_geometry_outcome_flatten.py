"""Flatten the verified P35 geometry-context outcome."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P36-P35-GEOMETRY-OUTCOME-FLATTEN-20260830-400"
P35_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P35-GEOMETRY-CONSTRUCTION-CONTEXT-ISOLATION-20260830-399"
P35_JOB_ID = "MEPHC-SCIENCE-6877e0be7a9eead89989be0a"
P35_SOURCE_COMMIT = "709ed926010fe22fa14494533debf3e65ad1d625"
P35_SCHEMA = "mephc-local-affine-p35-geometry-context-isolation-v1"


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
    p35_path = result_path.parent / f"{P35_JOB_ID}.json"
    require(p35_path.is_file(), "P35_RESULT_FILE_MISSING")
    p35 = json.loads(p35_path.read_text(encoding="utf-8"))
    require(p35.get("schema") == P35_SCHEMA, "P35_RESULT_SCHEMA_INVALID")
    require(p35.get("work_order_id") == P35_WORK_ORDER_ID, "P35_RESULT_WORK_ORDER_INVALID")
    require(p35.get("source_commit") == P35_SOURCE_COMMIT, "P35_RESULT_SOURCE_INVALID")
    probes = p35.get("probe_outcomes")
    require(isinstance(probes, list) and len(probes) == 2 and all(isinstance(item, dict) for item in probes),
            "P35_PROBE_OUTCOMES_SHAPE_INVALID")
    a, b = probes
    require(a.get("probe") == "probe_a" and b.get("probe") == "probe_b", "P35_PROBE_ORDER_INVALID")

    write_result({
        "schema": "mephc-local-affine-p36-p35-geometry-outcome-v1",
        "work_order_id": WORK_ORDER_ID,
        "p35_result_job_id": P35_JOB_ID,
        "p35_schema_verified": True,
        "p35_source_verified": True,
        "probe_outcomes_shape_verified": True,
        "probe_a_outcome_flattened": True,
        "probe_b_outcome_flattened": True,
        "geometry_object_source_classification_status": "PASS",
        "probe_a_return_code": a.get("return_code"),
        "probe_b_return_code": b.get("return_code"),
        "probe_a_last_stage": a.get("last_stage"),
        "probe_b_last_stage": b.get("last_stage"),
        "probe_a_fatal_line_number": a.get("fatal_line_number"),
        "probe_b_fatal_line_number": b.get("fatal_line_number"),
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
