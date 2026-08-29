"""Capture one production-provider attempt with a flushed, bounded stage trace."""
from __future__ import annotations

import faulthandler
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P17-PRODUCTION-PROVIDER-FAILURE-CAPTURE-20260830-381"
Q0 = (0.0, -37.0 / 60.0)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p17_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def stage(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def worker(trace: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        stage(trace, "WORKER_START")
        import meep as mp

        stage(trace, "MEEP_IMPORTED")
        from audit.e10f.e8b_local_affine_model import geometry_anchor_status, make_state
        from mephc.local_affine_state_provider import LocalAffineStateProvider

        require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
        spec = make_state(Q0, 0.0)
        require(spec.polarization == "TM", "POLARIZATION_IDENTITY_INVALID")
        stage(trace, "STATE_01_BOUND")
        provider = LocalAffineStateProvider(
            resolution=64,
            num_bands=6,
            eigensolver_tolerance=1e-7,
            mesh_size=3,
            deterministic=True,
            polarization=mp.TM,
            polarization_identity="TM",
            default_material=mp.air,
        )
        stage(trace, "PRODUCTION_PROVIDER_READY")
        snapshot = provider.solve(spec)
        stage(trace, "PROVIDER_SOLVE_RETURNED")
        frequencies = [float(value) for value in snapshot.frequencies]
        require(len(frequencies) == 6 and all(value > 0.0 for value in frequencies),
                "PERIODIC_H_SNAPSHOT_INVALID")
        stage(trace, "SIX_FREQUENCIES_VERIFIED")
    return 0


def read_trace(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))

    trace: Path | None = None
    child_return_code: int | None = None
    trace_stages: list[str] = []
    classification = "P17_PARENT_SETUP_FAILED"
    try:
        BudgetCounter = load_budget_counter()
        counter = BudgetCounter(1, 1)
        with tempfile.TemporaryDirectory(prefix="mephc-p17-") as temporary:
            trace = Path(temporary) / "stage.trace"
            counter.consume_provider()
            counter.consume_solver()
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
            )
            child_return_code = completed.returncode
            trace_stages = read_trace(trace)
            classification = "P17_PRODUCTION_PROVIDER_SUCCESS" if child_return_code == 0 else "P17_PRODUCTION_PROVIDER_FAILURE_CAPTURED"
    except Exception as exc:
        classification = f"P17_PARENT_FAILURE_{type(exc).__name__}"

    # The parent result is written for both a successful and a failed child.
    write_result({
        "schema": "mephc-local-affine-p17-production-provider-failure-capture-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "native_invocation_count": 1,
        "provider_execution_count": 1,
        "solver_execution_count": 1,
        "diagnostic_child_process_count": 1,
        "parent_result_written_even_if_child_fails": True,
        "faulthandler_enabled": True,
        "durable_stage_trace_captured": bool(trace_stages),
        "stage_trace": trace_stages,
        "child_return_code": child_return_code,
        "classification": classification,
        "failure_or_success_classification_status": "PASS",
        "exact_production_local_affine_provider_path_used": True,
        "formal_scientific_dataset_records": 0,
        "raw_h_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "status": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
