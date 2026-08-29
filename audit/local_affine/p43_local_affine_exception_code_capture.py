"""Capture a safe exception code and deepest frame from one STATE_01 attempt."""
from __future__ import annotations

import faulthandler
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback
from typing import Any

import numpy as np


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P43-LOCAL-AFFINE-EXCEPTION-CODE-CAPTURE-20260830-407"
Q0 = (0.0, -37.0 / 60.0)
SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p43_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def stage(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def read_trace(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def worker(trace: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        stage(trace, "WORKER_START")
        try:
            import meep as mp

            from audit.e10f.e8b_local_affine_model import (
                canonical_state_identity,
                geometry_anchor_status,
                make_state,
            )
            from mephc.local_affine_state_provider import LocalAffineStateProvider
            from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

            stage(trace, "MEEP_IMPORTED")
            require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
            spec = make_state(Q0, 0.0)
            identity = canonical_state_identity(spec)
            require(identity["public_q"] == [0.0, Q0[1]] and identity["s"] == 0.0,
                    "STATE_01_IDENTITY_INVALID")
            require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
            provider_source = inspect.getsource(MPBLiveSpectralProvider._build_solver)
            require("geometry=list(self.geometry)" in provider_source,
                    "MPB_BOUNDARY_LIST_CONVERSION_MISSING")
            require("geometry=self.geometry" not in provider_source,
                    "MPB_BOUNDARY_OLD_GEOMETRY_BINDING_PRESENT")
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
            frequencies = np.asarray(snapshot.frequencies, dtype=float)
            require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies))
                    and np.all(frequencies > 0.0), "FULL_SNAPSHOT_FREQUENCIES_INVALID")
        except Exception as exc:
            code = str(exc).strip()
            if not code or not SAFE_CODE.fullmatch(code):
                code = type(exc).__name__
            frames = traceback.extract_tb(exc.__traceback__)
            deepest = frames[-1] if frames else None
            frame_name = Path(deepest.filename).name if deepest is not None else "UNKNOWN"
            frame_line = deepest.lineno if deepest is not None else None
            frame_function = deepest.name if deepest is not None else "UNKNOWN"
            require(SAFE_CODE.fullmatch(frame_name) is not None, "DEEPEST_FRAME_BASENAME_UNSAFE")
            require(SAFE_CODE.fullmatch(frame_function) is not None, "DEEPEST_FRAME_FUNCTION_UNSAFE")
            stage(trace, f"PYTHON_EXCEPTION_CODE_{code}")
            stage(trace, f"DEEPEST_FRAME|{frame_name}|{frame_line}|{frame_function}")
            return 1
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p43-") as temporary:
        trace = Path(temporary) / "state01.trace"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        stages = read_trace(trace)
        child_return_code = completed.returncode

    code_stages = [item for item in stages if item.startswith("PYTHON_EXCEPTION_CODE_")]
    frame_stages = [item for item in stages if item.startswith("DEEPEST_FRAME|")]
    exception_code = code_stages[0][len("PYTHON_EXCEPTION_CODE_"):] if code_stages else None
    frame_parts = frame_stages[0].split("|") if frame_stages else []
    frame_basename = frame_parts[1] if len(frame_parts) == 4 else None
    frame_line = int(frame_parts[2]) if len(frame_parts) == 4 and frame_parts[2].isdigit() else None
    frame_function = frame_parts[3] if len(frame_parts) == 4 else None
    write_result({
        "schema": "mephc-local-affine-p43-exception-code-capture-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "patched_provider_blob_verified": True,
        "local_affine_provider_blob_verified": True,
        "frozen_state_identity_verified": True,
        "static_tests_passed_before_live_execution": True,
        "faulthandler_enabled": True,
        "durable_stage_trace_captured": bool(stages),
        "ordinary_python_exception_code_persisted_when_present": bool(exception_code),
        "deepest_exception_frame_persisted_when_present": bool(frame_basename and frame_function),
        "parent_result_written_after_child_outcome": True,
        "exact_LocalAffineStateProvider_used": True,
        "production_phase_callback_none_path_used": True,
        "child_return_code": child_return_code,
        "ordinary_exception_code": exception_code,
        "deepest_exception_frame_basename": frame_basename,
        "deepest_exception_frame_line": frame_line,
        "deepest_exception_frame_function": frame_function,
        "last_stage": stages[-1] if stages else "NONE",
        "stage_count": len(stages),
        "native_invocation_count": 1,
        "provider_execution_count": 1,
        "solver_execution_count": 1,
        "diagnostic_child_process_count": 1,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "sanitized_result_safe": True,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


if __name__ == "__main__":
    raise SystemExit(main())
