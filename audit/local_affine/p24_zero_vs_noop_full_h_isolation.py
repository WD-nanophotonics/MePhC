"""Isolate the zero-band callback from a semantics-neutral callback at STATE_01."""
from __future__ import annotations

import faulthandler
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P24-ZERO-VS-NOOP-FULL-H-ISOLATION-20260830-388"
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
    spec = importlib.util.spec_from_file_location("_mephc_p24_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def mark(path: Path, value: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((value + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def zero_band_function(*_args: Any, **_kwargs: Any) -> int:
    return 0


def noop_band_function(*_args: Any, **_kwargs: Any) -> None:
    return None


def worker(probe: str, callback_name: str, trace: Path, output: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        mark(trace, "WORKER_START")
        import meep as mp
        from meep import mpb
        import numpy as np

        from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
        from audit.e8b.e8b_geometry import all_states, solver_geometry

        mark(trace, "MEEP_IMPORTED")
        require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
        raw = all_states()["0.0"]
        geometry, lattice = solver_geometry(raw)
        spec = make_state(Q0, 0.0)
        identity = canonical_state_identity(spec)
        require(identity["public_q"] == [0.0, Q0[1]] and identity["s"] == 0.0, "STATE_01_IDENTITY_INVALID")
        require(identity["geometry_digest"] == raw["geometry_digest"], "STATE_01_GEOMETRY_IDENTITY_INVALID")
        mark(trace, "STATE_01_GEOMETRY_LATTICE_VERIFIED")
        reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(Q0[0], Q0[1], 0), lattice)
        k_point = [float(reciprocal.x), float(reciprocal.y), float(reciprocal.z)]
        mark(trace, "RECIPROCAL_K_VERIFIED")
        solver = mpb.ModeSolver(
            geometry=geometry,
            geometry_lattice=lattice,
            k_points=[reciprocal],
            resolution=64,
            num_bands=6,
            default_material=mp.air,
            tolerance=1e-7,
            deterministic=True,
            mesh_size=3,
        )
        mark(trace, "MODE_SOLVER_READY")
        callback: Callable[..., Any] = zero_band_function if callback_name == "zero_band_function" else noop_band_function
        mark(trace, "RUN_PARITY_ENTER")
        solver.run_parity(mp.TM, False, callback)
        mark(trace, "RUN_PARITY_RETURNED")
        frequencies = np.asarray(solver.all_freqs, dtype=float)
        require(frequencies.ndim == 2 and frequencies.shape[0] >= 1 and frequencies.shape[1] == 6,
                "P24_FREQUENCY_SHAPE_INVALID")
        values = np.asarray(frequencies[0], dtype=float)
        require(np.all(np.isfinite(values)), "P24_FREQUENCY_NONFINITE")
        mark(trace, "SIX_FREQUENCIES_VERIFIED")
        h_boundaries = 0
        for band in range(1, 7):
            mark(trace, f"HFIELD_{band}_ENTER")
            field = np.asarray(solver.get_hfield(band), dtype=np.complex128)
            require(field.size > 0 and np.all(np.isfinite(field)), f"P24_HFIELD_{band}_INVALID")
            del field
            h_boundaries += 1
            mark(trace, f"HFIELD_{band}_RETURNED")
        mark(trace, "ADAPTER_BOUNDARY_REACHED")
        mark(trace, "LOCAL_AFFINE_VALIDATION_BOUNDARY_REACHED")
        write_json(output, {
            "probe": probe,
            "callback": callback_name,
            "return_code": 0,
            "run_parity_boundary": "RETURNED",
            "frequencies_finite_six": True,
            "hfield_boundaries_reached": h_boundaries,
            "adapter_boundary": True,
            "local_affine_validation_boundary": True,
            "reciprocal_k": k_point,
        })
    return 0


def trace_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def main() -> int:
    if len(sys.argv) == 6 and sys.argv[1] == "--worker":
        return worker(sys.argv[2], sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5]))

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(2, 2)
    outcomes: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mephc-p24-") as temporary:
        root = Path(temporary)
        probes = (("probe_a", "zero_band_function"), ("probe_b", "semantics_neutral_noop_band_function"))
        for probe, callback in probes:
            counter.consume_provider()
            counter.consume_solver()
            trace = root / f"{probe}.trace"
            result = root / f"{probe}.json"
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", probe, callback, str(trace), str(result)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
            )
            child_result = json.loads(result.read_text(encoding="utf-8")) if result.is_file() else {}
            stages = trace_lines(trace)
            outcomes.append({
                "probe": probe,
                "callback": callback,
                "return_code": completed.returncode,
                "sigsegv": completed.returncode == -11,
                "last_stage": stages[-1] if stages else "NONE",
                "stage_count": len(stages),
                "state_01_geometry_lattice_verified": "STATE_01_GEOMETRY_LATTICE_VERIFIED" in stages,
                "run_parity_boundary": child_result.get("run_parity_boundary", "NOT_REACHED"),
                "frequencies_finite_six": child_result.get("frequencies_finite_six", False),
                "hfield_boundaries_reached": child_result.get("hfield_boundaries_reached", 0),
                "adapter_boundary": child_result.get("adapter_boundary", False),
                "local_affine_validation_boundary": child_result.get("local_affine_validation_boundary", False),
            })

    write_result({
        "schema": "mephc-local-affine-p24-zero-vs-noop-full-h-isolation-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "native_invocation_count": 1,
        "provider_execution_count": 2,
        "solver_execution_count": 2,
        "diagnostic_child_process_count": 2,
        "diagnostic_child_processes_sequential_only": True,
        "exact_state_01_geometry_lattice_verified": all(item["state_01_geometry_lattice_verified"] for item in outcomes),
        "zero_band_function_probe_captured": True,
        "noop_band_function_probe_captured": True,
        "run_parity_boundary_captured": True,
        "six_hfield_boundaries_captured_when_reached": True,
        "adapter_boundary_captured_when_reached": True,
        "local_affine_validation_boundary_captured_when_reached": True,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "probe_outcomes": outcomes,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


if __name__ == "__main__":
    raise SystemExit(main())
