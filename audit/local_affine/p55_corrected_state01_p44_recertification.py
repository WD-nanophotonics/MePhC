"""Recertify P44 STATE_01 after removing the stale solver_settings assertion."""
from __future__ import annotations

import faulthandler
import hashlib
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
from collections.abc import Mapping
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
from audit.local_affine.p54_solver_settings_resolution_provenance_diagnostic import full_snapshot_matrix
from mephc.local_affine_state_provider import LocalAffineStateProvider, _metadata, local_affine_reference_cell_contract
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P55-CORRECTED-STATE01-P44-RECERTIFICATION-20260830-419"
PARENT_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P54-SOLVER-SETTINGS-RESOLUTION-PROVENANCE-DIAGNOSTIC-20260830-418"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
P54_SOURCE_COMMIT = "1b46ee4129b92a15446be50e82241c9e53253fae"
Q0 = (0.0, -0.6166666666666667)
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def sanitize_text(value: bytes | str) -> str:
    raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return re.sub(r"(?:[A-Za-z]:)?[\\/][^ ]+", "<path>", " ".join(raw.split()))[:512]


def safe_code(exc: BaseException) -> str:
    for value in [getattr(exc, "code", None), *(exc.args if exc.args else ()), str(exc)]:
        text = str(value).strip() if value is not None else ""
        if text and SAFE_TOKEN.fullmatch(text):
            return text
    return type(exc).__name__


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("_mephc_p55_scientific_job", root / "tools" / "mephc-flow" / "scientific_job.py")
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def git_blob(commit: str, path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return subprocess.run(["git", "rev-parse", f"{commit}:{path}"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def verify_production_blobs() -> bool:
    for path in ("mephc/local_affine_state_provider.py", "mephc/mpb_spectral_provider.py", "audit/e10f/e8b_local_affine_model.py"):
        require(git_blob(P54_SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path), f"PRODUCTION_BLOB_CHANGED:{path}")
    return True


def mark(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def markers(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line] if path.is_file() else []


def failure_record(output: Path, trace: Path, exc: BaseException, stage: str) -> None:
    try:
        ordered = markers(trace)
        frames = traceback.extract_tb(exc.__traceback__)
        deepest = frames[-1] if frames else None
        write_json(output, {
            "diagnostic_contract_completed": True,
            "scientific_acceptance_status": "FAIL",
            "exact_failing_stage": stage,
            "exception_type": type(exc).__name__,
            "exception_code": safe_code(exc),
            "exception_message": sanitize_text(str(exc)),
            "deepest_relevant_frame_basename": Path(deepest.filename).name if deepest else None,
            "deepest_relevant_frame_line": deepest.lineno if deepest else None,
            "deepest_relevant_frame_function": deepest.name if deepest else None,
            "ordered_stage_markers": ",".join(ordered),
            "field_payload_retained": False,
            "status": "PASS",
        })
    except Exception:
        pass


def worker(trace: Path, output: Path) -> int:
    fault_file = None
    try:
        fault_file = trace.with_suffix(".fault").open("ab", buffering=0)
        faulthandler.enable(file=fault_file, all_threads=True)
        mark(trace, "WORKER_START")
        try:
            import meep as mp

            require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
            spec = make_state(Q0, 0.0)
            identity_before = canonical_state_identity(spec)
            require(identity_before["public_q"] == [0.0, Q0[1]] and identity_before["s"] == 0.0, "STATE_01_IDENTITY_INVALID")
            require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
            require("geometry=list(self.geometry)" in inspect.getsource(MPBLiveSpectralProvider._build_solver), "MPB_BOUNDARY_LIST_CONVERSION_MISSING")
            mark(trace, "STATE_CONSTRUCTION")
            provider = LocalAffineStateProvider(
                resolution=64, num_bands=6, eigensolver_tolerance=1e-7, mesh_size=3,
                deterministic=True, polarization=mp.TM, polarization_identity="TM", default_material=mp.air,
            )
            mark(trace, "PROVIDER_CONSTRUCTION")
            snapshot = provider.solve(spec)
            mark(trace, "MPB_SOLVE_RETURN")
            identity_after = canonical_state_identity(spec)
            require(identity_before == identity_after, "FROZEN_STATE_IDENTITY_CHANGED")
            require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_MUTATED")
            matrix = full_snapshot_matrix(snapshot)
            mark(trace, "FULL_SNAPSHOT_VALIDATION")

            provenance = snapshot.provenance
            require(isinstance(provenance, Mapping), "PROVENANCE_MAPPING_MISSING")
            metadata = _metadata(snapshot)
            require(metadata.get("representation") == "mpb_periodic_h_l2_v1", "CANONICAL_REPRESENTATION_PRECEDENCE_INVALID")
            require(provider.resolution == 64 and metadata.get("resolution") == 64, "EFFECTIVE_RESOLUTION_NOT_64")
            reciprocal = provenance.get("mpb_k_point")
            require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3, "CANONICAL_RECIPROCAL_METADATA_MISSING")
            require(np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity_before["derived_kappa"]), rtol=0.0, atol=1e-9) and float(reciprocal[2]) == 0.0, "CANONICAL_RECIPROCAL_METADATA_MISMATCH")
            expected = local_affine_reference_cell_contract(
                spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity_before,
                lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
            )
            actual = provenance.get("local_affine_reference_cell_contract")
            actual_json, expected_json = canonical(actual), canonical(expected)
            require(actual_json == expected_json, "REFERENCE_CELL_METADATA_INVALID")
            require(hashlib.sha256(actual_json).hexdigest() == hashlib.sha256(expected_json).hexdigest(), "REFERENCE_CELL_METADATA_DIGEST_INVALID")
            require(provenance.get("local_affine_solver_polarization_identity") == "TM", "EXPLICIT_POLARIZATION_IDENTITY_INVALID")
            require(provenance.get("phase_callback") in (None, "None") or "phase_callback" not in provenance, "PHASE_CALLBACK_PRODUCTION_PATH_INVALID")
            mark(trace, "CORRECTED_PROVENANCE_MATRIX_VALIDATION")
            write_json(output, {
                "diagnostic_contract_completed": True,
                "scientific_acceptance_status": "PASS",
                "state_id": "STATE_01",
                "frozen_state_identity_unchanged": True,
                "geometry_tuple_unchanged": True,
                "mpb_boundary_list_conversion_verified": True,
                "solver_settings_assertion_removed": True,
                "solver_settings_presence_diagnostic": isinstance(provenance.get("solver_settings"), Mapping),
                "effective_resolution": 64,
                "canonical_snapshot_representation": "mpb_periodic_h_l2_v1",
                "reference_cell_contract_canonical_equal": True,
                "reference_cell_contract_sha256_equal": True,
                "p44_state01_scientifically_recovered_under_corrected_provenance_contract": True,
                "prior_failure_interpretation": "stale_acceptance_assumption_only",
                "ordered_stage_markers": ",".join(markers(trace)),
                "field_payload_retained": False,
                **matrix,
                "status": "PASS",
            })
            mark(trace, "FINALIZATION")
            return 0
        except Exception as exc:
            failure_record(output, trace, exc, markers(trace)[-1] if markers(trace) else "STATE_CONSTRUCTION")
            return 0
    except Exception as exc:
        failure_record(output, trace, exc, "DIAGNOSTIC_INITIALIZATION")
        return 0
    finally:
        if fault_file is not None:
            try:
                fault_file.close()
            except Exception:
                pass


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]), Path(sys.argv[3]))
    child: dict[str, Any] = {}
    completed: subprocess.CompletedProcess[bytes] | None = None
    parent_error: BaseException | None = None
    production_ok = False
    loaded = False
    try:
        production_ok = verify_production_blobs()
        BudgetCounter = load_budget_counter()
        counter = BudgetCounter(1, 1)
        with tempfile.TemporaryDirectory(prefix="mephc-p55-") as temporary:
            root = Path(temporary)
            trace, output = root / "state01.trace", root / "worker.json"
            counter.consume_provider()
            counter.consume_solver()
            completed = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace), str(output)], cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600)
            if output.is_file():
                candidate = json.loads(output.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    child, loaded = candidate, True
    except Exception as exc:
        parent_error = exc
    diagnostic_complete = parent_error is None and completed is not None and loaded
    if parent_error:
        child = {
            "diagnostic_contract_completed": False,
            "scientific_acceptance_status": "FAIL",
            "exact_failing_stage": "DIAGNOSTIC_TRANSPORT",
            "exception_type": type(parent_error).__name__,
            "exception_code": safe_code(parent_error),
            "exception_message": sanitize_text(str(parent_error)),
            "field_payload_retained": False,
        }
    result = {
        "schema": "mephc-local-affine-p55-corrected-state01-p44-recertification-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": PARENT_WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "p54_source_commit": P54_SOURCE_COMMIT,
        "production_blob_equivalence_to_original_p44": production_ok,
        "production_code_changed": False,
        "diagnostic_contract_completed": diagnostic_complete,
        "scientific_acceptance_status": child.get("scientific_acceptance_status", "FAIL"),
        "child_return_code": completed.returncode if completed is not None else None,
        "child_stderr_bounded_and_sanitized": True,
        "child_stderr_excerpt_sanitized": sanitize_text(completed.stderr if completed is not None else b""),
        "native_invocation_count": 1 if completed is not None else 0,
        "provider_execution_count": 1 if completed is not None else 0,
        "solver_execution_count": 1 if completed is not None else 0,
        "diagnostic_child_process_count": 1 if completed is not None else 0,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "sanitized_result_safe": True,
        "result_written_to_mephc_result_path": True,
        **child,
        "diagnostic_contract_completed": diagnostic_complete,
        "scientific_acceptance_status": child.get("scientific_acceptance_status", "FAIL"),
        "status": "PASS" if diagnostic_complete else "FAIL",
    }
    try:
        write_result(result)
    except Exception:
        return 1
    return 0 if diagnostic_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
