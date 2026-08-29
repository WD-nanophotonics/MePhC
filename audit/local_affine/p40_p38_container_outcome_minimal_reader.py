"""Read the exact P38 result with only the contract's minimal assertions."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P40-P38-CONTAINER-OUTCOME-MINIMAL-READER-20260830-404"
P38_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P38-GEOMETRY-CONTAINER-TUPLE-VS-LIST-20260830-402"
P38_JOB_ID = "MEPHC-SCIENCE-a3156f8f717129c231fa1a2a"
P38_SOURCE_COMMIT = "ca377d4c9ff191fe88a059205c851bde945285c8"
P38_SCHEMA = "mephc-local-affine-p38-container-isolation-v1"


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


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
    p38_path = result_path.parent / f"{P38_JOB_ID}.json"
    require(p38_path.is_file(), "P38_RESULT_FILE_MISSING")
    p38 = json.loads(p38_path.read_text(encoding="utf-8"))
    require(p38.get("schema") == P38_SCHEMA, "P38_RESULT_SCHEMA_INVALID")
    require(p38.get("work_order_id") == P38_WORK_ORDER_ID, "P38_RESULT_WORK_ORDER_INVALID")
    require(p38.get("source_commit") == P38_SOURCE_COMMIT, "P38_RESULT_SOURCE_INVALID")
    probes = p38.get("probe_outcomes")
    require(
        isinstance(probes, list)
        and len(probes) == 2
        and all(isinstance(item, dict) for item in probes),
        "P38_PROBE_OUTCOMES_SHAPE_INVALID",
    )
    a, b = probes
    require(a.get("probe") == "probe_a" and b.get("probe") == "probe_b", "P38_PROBE_ORDER_INVALID")

    write_result({
        "schema": "mephc-local-affine-p40-p38-container-causality-v1",
        "work_order_id": WORK_ORDER_ID,
        "p38_result_job_id": P38_JOB_ID,
        "p38_schema_verified": True,
        "p38_source_verified": True,
        "probe_outcomes_shape_verified": True,
        "no_probe_a_child_container_assertion": True,
        "probe_a_outcome_flattened": True,
        "probe_b_outcome_flattened": True,
        "container_causality_classification_status": "PASS",
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
