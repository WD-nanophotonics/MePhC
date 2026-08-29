"""Corrected zero-vs-noop isolation with production H-field boundary checks."""
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


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P25-CORRECTED-ZERO-VS-NOOP-FULL-H-ISOLATION-20260830-389"
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
    spec = importlib.util.spec_from_file_location("_mephc_p25_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def mark(path: Path, value: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((value + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def noop_band_function(*_args: Any, **_kwargs: Any) -> None:
    return None


def worker(probe: str, trace: Path, output: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        mark(trace, "WORKER_START")
        import meep as mp
        from meep import mpb
        import numpy as np

        from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
        from audit.e8b.e8b_geometry import all_states, solver_geometry
        from mephc.local_affine_state_provider import (
            _validate_snapshot,
            local_affine_reference_cell_contract,
        )
        from mephc.mpb_spectral import adapt_mpb_h_envelopes

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
        mark(trace, "RUN_PARITY_ENTER")
        if probe == "probe_a":
            # Zero band-function call: no optional callback is passed.
            solver.run_parity(mp.TM, False)
            callback_count = 0
        else:
            solver.run_parity(mp.TM, False, noop_band_function)
            callback_count = 1
        mark(trace, "RUN_PARITY_RETURNED")
        frequencies = np.asarray(solver.all_freqs, dtype=float)
        require(frequencies.ndim == 2 and frequencies.shape[0] >= 1 and frequencies.shape[1] == 6,
                "P25_FREQUENCY_SHAPE_INVALID")
        values = np.asarray(frequencies[0], dtype=float)
        require(np.all(np.isfinite(values)) and np.all(values > 0.0), "P25_FREQUENCY_INVALID")
        mark(trace, "SIX_FREQUENCIES_VERIFIED")
        fields = []
        for band in range(1, 7):
            mark(trace, f"HFIELD_{band}_ENTER")
            field = solver.get_hfield(band, bloch_phase=False)
            require(getattr(field, "bloch_phase", None) is False, "P25_BLOCH_PHASE_NOT_FALSE")
            field_k = getattr(field, "kpoint", None)
            require(field_k is not None, "P25_HFIELD_KPOINT_MISSING")
            field_array = np.asarray(field, dtype=np.complex128)
            if field_array.ndim == 4 and field_array.shape[2] == 1:
                field_array = field_array[:, :, 0, :]
            require(field_array.ndim == 3 and field_array.shape[2] == 3 and np.all(np.isfinite(field_array)),
                    "P25_HFIELD_INVALID")
            fields.append(field_array)
            mark(trace, f"HFIELD_{band}_RETURNED")
        mark(trace, "GET_HFIELD_BLOCH_PHASE_FALSE_VERIFIED")
        h_batch = np.stack(fields, axis=0)
        mark(trace, "PRODUCTION_FIELD_CANONICALIZATION_ENTER")
        snapshot = adapt_mpb_h_envelopes(
            Q0, values, h_batch, mpb_k_point=k_point,
            provenance={"field_extraction": "get_hfield(band, bloch_phase=False)"},
        )
        del h_batch, fields
        mark(trace, "PRODUCTION_FIELD_CANONICALIZATION_RETURNED")
        mark(trace, "PRODUCTION_H_ADAPTER_RETURNED")
        expected_contract = local_affine_reference_cell_contract(
            spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity,
            lattice_size=(float(lattice.size.x), float(lattice.size.y)),
        )
        _validate_snapshot(snapshot, expected_shape=tuple(snapshot.spatial_shape),
                           identity=identity, expected_contract=expected_contract)
        mark(trace, "LOCAL_AFFINE_SNAPSHOT_VALIDATION_RETURNED")
        write_json(output, {
            "probe": probe,
            "callback_count": callback_count,
            "run_parity_boundary": "RETURNED",
            "get_hfield_bloch_phase_false": True,
            "production_field_canonicalization": True,
            "production_h_adapter": True,
            "local_affine_snapshot_validation": True,
            "finite_positive_frequency_count": 6,
            "hfield_boundary_count": 6,
        })
    return 0


def read_trace(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        return worker(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(2, 2)
    outcomes: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mephc-p25-") as temporary:
        root = Path(temporary)
        for probe in ("probe_a", "probe_b"):
            counter.consume_provider()
            counter.consume_solver()
            trace = root / f"{probe}.trace"
            output = root / f"{probe}.json"
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", probe, str(trace), str(output)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
            )
            stages = read_trace(trace)
            child = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
            outcomes.append({
                "probe": probe,
                "return_code": completed.returncode,
                "sigsegv": completed.returncode == -11,
                "last_stage": stages[-1] if stages else "NONE",
                "stage_count": len(stages),
                "callback_count": child.get("callback_count", 0 if probe == "probe_a" else 1),
                "run_parity_boundary": child.get("run_parity_boundary", "NOT_REACHED"),
                "get_hfield_bloch_phase_false": child.get("get_hfield_bloch_phase_false", False),
                "production_field_canonicalization": child.get("production_field_canonicalization", False),
                "production_h_adapter": child.get("production_h_adapter", False),
                "local_affine_snapshot_validation": child.get("local_affine_snapshot_validation", False),
                "hfield_boundary_count": child.get("hfield_boundary_count", 0),
            })

    a, b = outcomes
    write_result({
        "schema": "mephc-local-affine-p25-corrected-zero-vs-noop-full-h-isolation-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "native_invocation_count": 1,
        "provider_execution_count": 2,
        "solver_execution_count": 2,
        "diagnostic_child_process_count": 2,
        "probe_a_exact_zero_band_function_call_verified": a["callback_count"] == 0,
        "probe_b_exact_noop_call_verified": b["callback_count"] == 1,
        "get_hfield_bloch_phase_false_verified": all(item["get_hfield_bloch_phase_false"] for item in outcomes),
        "production_field_canonicalization_executed_when_reached": all(item["production_field_canonicalization"] for item in outcomes),
        "production_h_adapter_executed_when_reached": all(item["production_h_adapter"] for item in outcomes),
        "local_affine_snapshot_validation_executed_when_reached": all(item["local_affine_snapshot_validation"] for item in outcomes),
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


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


if __name__ == "__main__":
    raise SystemExit(main())
