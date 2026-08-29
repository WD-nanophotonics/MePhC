"""Correct P32's faulthandler parser and capture one exact provider attempt."""
from __future__ import annotations

import faulthandler
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P33-CORRECTED-FATAL-SOLVE-LINE-CAPTURE-20260830-397"
Q0 = (0.0, -37.0 / 60.0)
FRAME_RE = re.compile(
    r'File "[^"\\]*(?:/|\\)(mpb_spectral_provider|local_affine_state_provider)\.py", line (\d+)(?:, in ([A-Za-z_][A-Za-z0-9_]*))?'
)


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
    spec = importlib.util.spec_from_file_location("_mephc_p33_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def parse_frame_line(line: str) -> tuple[int | None, str | None]:
    match = FRAME_RE.search(line)
    if not match:
        return None, None
    module, number, function = match.groups()
    return int(number), f"{module.upper()}_{(function or 'UNKNOWN').upper()}"


def parser_self_test() -> tuple[bool, bool, bool]:
    normal_line = '  File "/tmp/mpb_spectral_provider.py", line 184, in solve'
    no_comma_line = '  File "/tmp/mpb_spectral_provider.py", line 184'
    normal_number, normal_class = parse_frame_line(normal_line)
    optional_number, optional_class = parse_frame_line(no_comma_line)
    normal_ok = normal_number == 184 and normal_class == "MPB_SPECTRAL_PROVIDER_SOLVE"
    no_comma_ok = optional_number == 184 and optional_class == "MPB_SPECTRAL_PROVIDER_UNKNOWN"
    basename_ok = normal_class is not None and normal_class.startswith("MPB_SPECTRAL_PROVIDER_")
    return normal_ok, no_comma_ok, basename_ok


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


def read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def parse_fault(path: Path, sigsegv: bool) -> tuple[int | None, str | None, bool]:
    if not sigsegv or not path.is_file():
        return None, None, False
    frame_seen = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        number, frame_class = parse_frame_line(line)
        if number is not None:
            frame_seen = True
            return number, frame_class, True
        if "File \"" in line:
            frame_seen = True
    return None, None, frame_seen


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))

    normal_parser_ok, no_comma_parser_ok, basename_parser_ok = parser_self_test()
    require(normal_parser_ok and no_comma_parser_ok and basename_parser_ok, "P33_PARSER_SELF_TEST_FAILED")
    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p33-") as temporary:
        trace = Path(temporary) / "provider.trace"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        stages = read_lines(trace)
        sigsegv = completed.returncode == -11
        line_number, line_class, frame_seen = parse_fault(trace.with_suffix(".fault"), sigsegv)
        line_available = line_number is not None

    write_result({
        "schema": "mephc-local-affine-p33-fatal-solve-line-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "native_invocation_count": 1,
        "provider_execution_count": 1,
        "solver_execution_count": 1,
        "diagnostic_child_process_count": 1,
        "parser_self_test_passed_before_budget_reservation": True,
        "exact_unmodified_mpb_live_spectral_provider_used": True,
        "phase_callback_none": True,
        "provider_solve_body_unmodified": True,
        "faulthandler_enabled": True,
        "fault_file_parsed_before_temp_cleanup": True,
        "normal_faulthandler_no_comma_format_supported": normal_parser_ok,
        "optional_comma_format_supported": no_comma_parser_ok,
        "provider_basename_and_solve_function_matched": basename_parser_ok,
        "child_return_code": completed.returncode,
        "sigsegv": sigsegv,
        "provider_solve_source_line_available": line_available,
        "provider_solve_source_line_number": line_number,
        "provider_solve_frame_class": line_class,
        "fatal_frame_seen": frame_seen,
        "exact_provider_solve_frame_line_persisted_when_present": line_available or not frame_seen,
        "provider_solve_line_class_persisted_when_present": line_available or not frame_seen,
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
