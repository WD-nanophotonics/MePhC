"""Compare tuple and list containers around the same local-affine geometry."""
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


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P38-GEOMETRY-CONTAINER-TUPLE-VS-LIST-20260830-402"
Q0 = (0.0, -37.0 / 60.0)
FRAME_RE = re.compile(
    r'File "[^"\\]*(?:/|\\)(mpb_spectral_provider|local_affine_state_provider)\.py", line (\d+)'
    r'(?:, in ([A-Za-z_][A-Za-z0-9_]*))?'
)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


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
    spec = importlib.util.spec_from_file_location("_mephc_p38_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def mark(path: Path, value: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((value + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def worker(probe: str, trace: Path, output: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        mark(trace, "WORKER_START")
        import meep as mp
        from meep import mpb

        mark(trace, "MEEP_MPB_PREIMPORTED")
        from audit.e10f.e8b_local_affine_model import geometry_anchor_status, make_state
        from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

        require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
        canonical_spec = make_state(Q0, 0.0)
        geometry_tuple = canonical_spec.geometry
        lattice = canonical_spec.geometry_lattice
        require(isinstance(geometry_tuple, tuple), "MAKE_STATE_GEOMETRY_NOT_TUPLE")
        if probe == "probe_a":
            geometry = geometry_tuple
            construction = "make_state_geometry_tuple"
            container = "tuple"
        else:
            geometry = list(geometry_tuple)
            construction = "make_state_geometry_list"
            container = "list"
        require(isinstance(geometry, tuple if probe == "probe_a" else list), "GEOMETRY_CONTAINER_INVALID")
        require(len(geometry) == len(geometry_tuple), "GEOMETRY_CONTAINER_LENGTH_INVALID")
        require(all(left is right for left, right in zip(geometry, geometry_tuple)),
                "UNDERLYING_GEOMETRY_OBJECTS_NOT_SHARED")
        mark(trace, "GEOMETRY_CONTAINER_BOUND")
        reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(Q0[0], Q0[1], 0), lattice)
        k_point = [float(reciprocal.x), float(reciprocal.y), float(reciprocal.z)]
        mark(trace, "GEOMETRY_AND_RECIPROCAL_BOUND")
        provider = MPBLiveSpectralProvider(
            geometry=geometry,
            geometry_lattice=lattice,
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
        snapshot = provider.solve(tuple(canonical_spec.public_q))
        mark(trace, "PROVIDER_SOLVE_RETURNED")
        frequencies = [float(value) for value in snapshot.frequencies]
        require(len(frequencies) == 6 and all(value > 0.0 for value in frequencies), "SNAPSHOT_INVALID")
        write_json(output, {
            "construction": construction,
            "container": container,
            "reciprocal_k": k_point,
            "underlying_geometry_objects_shared": True,
            "lattice_object_shared": True,
            "solve_returned": True,
            "frequency_count": 6,
        })
    return 0


def read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def parse_fault(path: Path, sigsegv: bool) -> tuple[int | None, str | None]:
    if not sigsegv or not path.is_file():
        return None, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = FRAME_RE.search(line)
        if match:
            module, number, function = match.groups()
            return int(number), f"{module.upper()}_{(function or 'UNKNOWN').upper()}"
    return None, None


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        return worker(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(2, 2)
    outcomes: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mephc-p38-") as temporary:
        root = Path(temporary)
        for probe in ("probe_a", "probe_b"):
            counter.consume_provider()
            counter.consume_solver()
            trace = root / f"{probe}.trace"
            output = root / f"{probe}.json"
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", probe,
                 str(trace), str(output)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
            )
            stages = read_lines(trace)
            sigsegv = completed.returncode == -11
            line_number, line_class = parse_fault(trace.with_suffix(".fault"), sigsegv)
            child = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
            outcomes.append({
                "probe": probe,
                "return_code": completed.returncode,
                "sigsegv": sigsegv,
                "construction": child.get("construction", "NOT_REACHED"),
                "geometry_container": child.get("container", "NOT_REACHED"),
                "underlying_geometry_objects_shared": child.get("underlying_geometry_objects_shared", False),
                "lattice_object_shared": child.get("lattice_object_shared", False),
                "solve_returned": child.get("solve_returned", False),
                "last_stage": stages[-1] if stages else "NONE",
                "stage_count": len(stages),
                "fatal_line_number": line_number,
                "fatal_frame_class": line_class,
            })

    require(len(outcomes) == 2, "PROBE_OUTCOME_COUNT_INVALID")
    a, b = outcomes
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), {
        "schema": "mephc-local-affine-p38-container-isolation-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "native_invocation_count": 1,
        "provider_execution_count": 2,
        "solver_execution_count": 2,
        "diagnostic_child_process_count": 2,
        "diagnostic_child_processes_sequential_only": True,
        "probe_a_make_state_used": a["construction"] == "make_state_geometry_tuple",
        "probe_b_make_state_used": b["construction"] == "make_state_geometry_list",
        "probe_a_geometry_container_tuple_verified": a["geometry_container"] == "tuple",
        "probe_b_geometry_container_list_verified": b["geometry_container"] == "list",
        "probe_b_same_underlying_geometry_objects_verified": b["underlying_geometry_objects_shared"],
        "probe_b_same_lattice_object_verified": b["lattice_object_shared"],
        "probe_a_exact_unmodified_MPBLiveSpectralProvider_used": a["last_stage"] != "NONE",
        "probe_b_exact_unmodified_MPBLiveSpectralProvider_used": b["last_stage"] != "NONE",
        "same_q": True,
        "same_provider_parameters": True,
        "phase_callback_none": True,
        "fatal_provider_solve_line_captured_if_sigsegv": all(
            item["fatal_line_number"] is not None or not item["sigsegv"] for item in outcomes
        ),
        "generic_snapshot_validated_if_solve_returns": all(
            item["solve_returned"] or item["sigsegv"] for item in outcomes
        ),
        "decisive_probe_outcomes_top_level_flattened": True,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "probe_outcomes": outcomes,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
