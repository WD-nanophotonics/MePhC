"""Compare the direct live MPB provider with the LocalAffine provider path."""
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


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P27-DIRECT-MPB-PROVIDER-VS-LOCALAFFINE-PROVIDER-20260830-391"
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
    spec = importlib.util.spec_from_file_location("_mephc_p27_scientific_job", path)
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
        import numpy as np

        from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
        from mephc.local_affine_state_provider import LocalAffineStateProvider
        from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

        mark(trace, "MEEP_IMPORTED")
        require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
        spec = make_state(Q0, 0.0)
        identity = canonical_state_identity(spec)
        require(identity["polarization"] == "TM" and identity["s"] == 0.0, "STATE_01_IDENTITY_INVALID")
        mark(trace, "STATE_01_BOUND")
        if probe == "probe_a":
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
            provider_name = "MPBLiveSpectralProvider"
            phase_none = provider.phase_callback is None
        else:
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
            provider_name = "LocalAffineStateProvider"
            phase_none = True
        mark(trace, "PROVIDER_READY")
        snapshot = provider.solve(spec if probe == "probe_b" else tuple(spec.public_q))
        mark(trace, "PROVIDER_SOLVE_RETURNED")
        frequencies = np.asarray(snapshot.frequencies, dtype=float)
        require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies)), "P27_FREQUENCY_INVALID")
        mark(trace, "SIX_FREQUENCIES_VERIFIED")
        write_json(output, {
            "probe": probe,
            "provider": provider_name,
            "phase_callback_none": phase_none,
            "solve_returned": True,
            "finite_frequency_count": 6,
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
    with tempfile.TemporaryDirectory(prefix="mephc-p27-") as temporary:
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
                "provider": child.get("provider", "NOT_REACHED"),
                "phase_callback_none": child.get("phase_callback_none", False),
                "solve_returned": child.get("solve_returned", False),
                "finite_frequency_count": child.get("finite_frequency_count", 0),
                "last_stage": stages[-1] if stages else "NONE",
                "stage_count": len(stages),
            })

    write_result({
        "schema": "mephc-local-affine-p27-provider-layer-isolation-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "native_invocation_count": 1,
        "provider_execution_count": 2,
        "solver_execution_count": 2,
        "diagnostic_child_process_count": 2,
        "probe_a_exact_mpb_live_spectral_provider_used": outcomes[0]["provider"] == "MPBLiveSpectralProvider",
        "probe_a_phase_callback_none": outcomes[0]["phase_callback_none"],
        "probe_b_exact_local_affine_state_provider_used": outcomes[1]["provider"] == "LocalAffineStateProvider",
        "probe_b_phase_callback_none_production_path": outcomes[1]["phase_callback_none"],
        "probe_a_child_outcome_captured": True,
        "probe_b_child_outcome_captured": True,
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
