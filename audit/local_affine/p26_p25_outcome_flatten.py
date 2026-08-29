"""Flatten the verified P25 zero-vs-noop outcome without science execution."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P26-P25-OUTCOME-FLATTEN-20260830-390"
P25_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P25-CORRECTED-ZERO-VS-NOOP-FULL-H-ISOLATION-20260830-389"
P25_JOB_ID = "MEPHC-SCIENCE-1a1bf0f5c9136fc7dd6b0382"
P25_SOURCE_COMMIT = "84ac977a8c6531968d11d2e969e1aedcd391e6a3"
P25_SCHEMA = "mephc-local-affine-p25-corrected-zero-vs-noop-full-h-isolation-v1"


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
    p25_path = result_path.parent / f"{P25_JOB_ID}.json"
    require(p25_path.is_file(), "P25_RESULT_FILE_MISSING")
    p25 = json.loads(p25_path.read_text(encoding="utf-8"))
    require(p25.get("schema") == P25_SCHEMA, "P25_RESULT_SCHEMA_INVALID")
    require(p25.get("work_order_id") == P25_WORK_ORDER_ID, "P25_RESULT_WORK_ORDER_INVALID")
    require(p25.get("source_commit") == P25_SOURCE_COMMIT, "P25_RESULT_SOURCE_INVALID")
    probes = p25.get("probe_outcomes")
    require(isinstance(probes, list) and len(probes) == 2 and all(isinstance(item, dict) for item in probes),
            "P25_PROBE_OUTCOMES_SHAPE_INVALID")
    a, b = probes
    require(a.get("probe") == "probe_a" and b.get("probe") == "probe_b", "P25_PROBE_ORDER_INVALID")
    require(p25.get("probe_a_exact_zero_band_function_call_verified") is True, "P25_ZERO_PROBE_INVALID")
    require(p25.get("probe_b_exact_noop_call_verified") is True, "P25_NOOP_PROBE_INVALID")

    write_result({
        "schema": "mephc-local-affine-p26-p25-outcome-v1",
        "work_order_id": WORK_ORDER_ID,
        "p25_result_job_id": P25_JOB_ID,
        "p25_schema_verified": True,
        "p25_source_verified": True,
        "probe_outcomes_shape_verified": True,
        "probe_a_outcome_flattened": True,
        "probe_b_outcome_flattened": True,
        "zero_vs_noop_classification_status": "PASS",
        "probe_a_return_code": a.get("return_code"),
        "probe_b_return_code": b.get("return_code"),
        "probe_a_last_stage": a.get("last_stage"),
        "probe_b_last_stage": b.get("last_stage"),
        "probe_a_hfield_boundary_count": a.get("hfield_boundary_count"),
        "probe_b_hfield_boundary_count": b.get("hfield_boundary_count"),
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
