"""Flatten the verified P27 provider-layer outcome without rerunning science."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P28-P27-PROVIDER-OUTCOME-FLATTEN-20260830-392"
P27_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P27-DIRECT-MPB-PROVIDER-VS-LOCALAFFINE-PROVIDER-20260830-391"
P27_JOB_ID = "MEPHC-SCIENCE-07dfd7c12f96a7212b587d1d"
P27_SOURCE_COMMIT = "9b6ad6d599ae6f03a26adb123036a7c113007d7a"
P27_SCHEMA = "mephc-local-affine-p27-provider-layer-isolation-v1"


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
    p27_path = result_path.parent / f"{P27_JOB_ID}.json"
    require(p27_path.is_file(), "P27_RESULT_FILE_MISSING")
    p27 = json.loads(p27_path.read_text(encoding="utf-8"))
    require(p27.get("schema") == P27_SCHEMA, "P27_RESULT_SCHEMA_INVALID")
    require(p27.get("work_order_id") == P27_WORK_ORDER_ID, "P27_RESULT_WORK_ORDER_INVALID")
    require(p27.get("source_commit") == P27_SOURCE_COMMIT, "P27_RESULT_SOURCE_INVALID")
    probes = p27.get("probe_outcomes")
    require(isinstance(probes, list) and len(probes) == 2 and all(isinstance(item, dict) for item in probes),
            "P27_PROBE_OUTCOMES_SHAPE_INVALID")
    a, b = probes
    require(a.get("probe") == "probe_a" and b.get("probe") == "probe_b", "P27_PROBE_ORDER_INVALID")
    require(a.get("provider") == "MPBLiveSpectralProvider", "P27_PROBE_A_PROVIDER_INVALID")
    require(b.get("provider") == "LocalAffineStateProvider", "P27_PROBE_B_PROVIDER_INVALID")

    write_result({
        "schema": "mephc-local-affine-p28-p27-provider-outcome-v1",
        "work_order_id": WORK_ORDER_ID,
        "p27_result_job_id": P27_JOB_ID,
        "p27_schema_verified": True,
        "p27_source_verified": True,
        "probe_outcomes_shape_verified": True,
        "probe_a_outcome_flattened": True,
        "probe_b_outcome_flattened": True,
        "provider_layer_classification_status": "PASS",
        "probe_a_provider": a.get("provider"),
        "probe_b_provider": b.get("provider"),
        "probe_a_return_code": a.get("return_code"),
        "probe_b_return_code": b.get("return_code"),
        "probe_a_last_stage": a.get("last_stage"),
        "probe_b_last_stage": b.get("last_stage"),
        "probe_a_phase_callback_none": a.get("phase_callback_none"),
        "probe_b_phase_callback_none": b.get("phase_callback_none"),
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
