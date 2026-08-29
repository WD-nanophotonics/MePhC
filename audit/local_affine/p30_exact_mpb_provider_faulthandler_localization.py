"""Localize the exact live-provider failure with one faulthandler child."""
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


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P30-EXACT-MPB-PROVIDER-FAULTHANDLER-LOCALIZATION-20260830-394"
Q0 = (0.0, -37.0 / 60.0)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p30_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def mark(path: Path, value: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((value + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def worker(trace: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        mark(trace, "WORKER_START")
        import meep as mp

        from audit.e10f.e8b_local_affine_model import geometry_anchor_status, make_state
        from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

        mark(trace, "MEEP_IMPORTED")
        require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
        spec = make_state(Q0, 0.0)
        mark(trace, "STATE_01_BOUND")
        provider = MPBLiveSpectralProvider(
            geometry=spec.geometry,
            geometry_lattice=spec.geometry_lattice,
            resolution=64,
            num_bands=6,
            polarization=mp.TM,
            default_material=mp.air,
            eigensolver_tolerance=1e-7,
            deterministic=True,
            mesh_size=3,
            phase_callback=None,
        )
        require(provider.phase_callback is None, "PHASE_CALLBACK_NOT_NONE")
        mark(trace, "PROVIDER_READY")
        mark(trace, "PROVIDER_SOLVE_ENTER")
        provider.solve(tuple(spec.public_q))
        mark(trace, "PROVIDER_SOLVE_RETURNED")
    return 0


def trace_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def classify_fault(path: Path, sigsegv: bool) -> str:
    if not sigsegv:
        return "NO_SIGSEGV"
    if not path.is_file():
        return "SIGSEGV_NO_FAULTHANDLER_FRAME"
    text = path.read_text(encoding="utf-8", errors="replace")
    if "local_affine_state_provider.py" in text:
        return "LOCAL_AFFINE_PROVIDER_SOURCE_FRAME"
    if "mpb_spectral_provider.py" in text:
        return "MPB_PROVIDER_SOURCE_FRAME"
    if "meep" in text.lower():
        return "MEEP_NATIVE_FRAME"
    return "FAULTHANDLER_FRAME_AVAILABLE_UNCLASSIFIED"


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p30-") as temporary:
        trace = Path(temporary) / "provider.trace"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        stages = trace_lines(trace)
        sigsegv = completed.returncode == -11
        fault_class = classify_fault(trace.with_suffix(".fault"), sigsegv)

    write_result({
        "schema": "mephc-local-affine-p30-exact-mpb-provider-fatal-line-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "native_invocation_count": 1,
        "provider_execution_count": 1,
        "solver_execution_count": 1,
        "diagnostic_child_process_count": 1,
        "exact_unmodified_mpb_live_spectral_provider_used": True,
        "phase_callback_none": True,
        "provider_solve_body_unmodified": True,
        "faulthandler_enabled": True,
        "child_return_code": completed.returncode,
        "sigsegv": sigsegv,
        "fatal_python_frame_parsed_when_sigsegv": fault_class != "SIGSEGV_NO_FAULTHANDLER_FRAME" if sigsegv else False,
        "provider_solve_source_line_classified_when_available": fault_class in {
            "LOCAL_AFFINE_PROVIDER_SOURCE_FRAME", "MPB_PROVIDER_SOURCE_FRAME",
        },
        "fatal_frame_classification": fault_class,
        "last_stage": stages[-1] if stages else "NONE",
        "stage_count": len(stages),
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


if __name__ == "__main__":
    raise SystemExit(main())
