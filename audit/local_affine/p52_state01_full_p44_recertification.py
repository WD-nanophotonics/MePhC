"""Crash-safe, single-attempt recertification of the original P44 STATE_01 matrix."""
from __future__ import annotations

import faulthandler
import hashlib
import importlib.util
import inspect
import json
import math
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
from mephc.local_affine_state_provider import (
    LocalAffineStateProvider,
    _metadata,
    local_affine_reference_cell_contract,
)
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P52-STATE01-FULL-P44-RECERTIFICATION-20260830-416"
ORIGINAL_P44_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P44-METADATA-REPRESENTATION-PRECEDENCE-FIX-STATE01-CERTIFICATION-20260830-408"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
P51_SOURCE_COMMIT = "a5e34d1f34fa31130d32a46f054d0bf02f5b3994"
Q0 = (0.0, -0.6166666666666667)
STAGES = (
    "STATE_CONSTRUCTION",
    "PROVIDER_CONSTRUCTION",
    "MPB_SOLVE_RETURN",
    "FULL_SNAPSHOT_VALIDATION",
    "METADATA_VALIDATION",
    "RECIPROCAL_METADATA_VALIDATION",
    "REFERENCE_CELL_CONTRACT_VALIDATION",
    "FINALIZATION",
)
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
    text = " ".join(raw.split())
    return re.sub(r"(?:[A-Za-z]:)?[\\/][^ ]+", "<path>", text)[:512]


def safe_code(exc: BaseException) -> str:
    candidates = [getattr(exc, "code", None), *(exc.args if exc.args else ()), str(exc)]
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text and SAFE_TOKEN.fullmatch(text):
            return text
    return type(exc).__name__


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p52_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def git_blob(commit: str, path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def verify_production_blobs() -> bool:
    paths = (
        "mephc/local_affine_state_provider.py",
        "mephc/mpb_spectral_provider.py",
        "audit/e10f/e8b_local_affine_model.py",
    )
    for path in paths:
        require(
            git_blob(P51_SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path),
            f"PRODUCTION_BLOB_CHANGED:{path}",
        )
    return True


def mark(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def markers(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise TypeError(f"UNSAFE_RESULT_VALUE:{type(value).__name__}")


def persist_exception(output: Path, trace: Path, exc: BaseException, side: str, pending: str) -> None:
    """Write a bounded scalar failure record even when a child stage raises."""
    try:
        ordered = markers(trace)
        frames = traceback.extract_tb(exc.__traceback__)
        deepest = frames[-1] if frames else None
        write_json(output, {
            "state01_provider_solve_returned": "MPB_SOLVE_RETURN" in ordered,
            "failure_side": side,
            "exact_failing_stage": ordered[-1] if ordered else "DIAGNOSTIC_INITIALIZATION",
            "exception_type": type(exc).__name__,
            "exception_code": safe_code(exc),
            "exception_message": sanitize_text(str(exc)),
            "deepest_relevant_frame_basename": Path(deepest.filename).name if deepest else None,
            "deepest_relevant_frame_line": deepest.lineno if deepest else None,
            "deepest_relevant_frame_function": deepest.name if deepest else None,
            "last_successful_stage": ordered[-1] if ordered else "NONE",
            "next_pending_stage": pending,
            "ordered_stage_markers": ",".join(ordered),
            "field_payload_retained": False,
            "status": "FAIL",
        })
    except Exception:
        try:
            write_json(output, {
                "state01_provider_solve_returned": False,
                "failure_side": side,
                "exact_failing_stage": "DIAGNOSTIC_INITIALIZATION",
                "exception_type": type(exc).__name__,
                "exception_code": type(exc).__name__,
                "exception_message": type(exc).__name__,
                "last_successful_stage": "NONE",
                "next_pending_stage": pending,
                "field_payload_retained": False,
                "status": "FAIL",
            })
        except Exception:
            pass


def validate_snapshot(snapshot: Any, spec: Any, identity: Mapping[str, Any], trace: Path) -> dict[str, Any]:
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies)) and np.all(frequencies > 0.0),
            "FULL_SNAPSHOT_FREQUENCIES_INVALID")
    raw_norms = np.asarray(snapshot.raw_norms, dtype=float)
    require(raw_norms.shape == (6,) and np.all(np.isfinite(raw_norms)) and np.all(raw_norms > 0.0),
            "FULL_SNAPSHOT_RAW_NORMS_INVALID")
    require(len(snapshot.normalized_vectors) == 6, "FULL_SNAPSHOT_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        require(np.all(np.isfinite(values)), "FULL_SNAPSHOT_VECTOR_NONFINITE")
        require(np.isclose(float(np.linalg.norm(values)), 1.0, rtol=0.0, atol=1e-10),
                "FULL_SNAPSHOT_VECTOR_NONUNIT")
    gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
    require(gram.shape == (6, 6) and np.all(np.isfinite(gram)), "FULL_SNAPSHOT_GRAM_INVALID")
    require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3,
            "FULL_SNAPSHOT_SHAPE_INVALID")
    mark(trace, "FULL_SNAPSHOT_VALIDATION")

    metadata = _metadata(snapshot)
    require(metadata.get("representation") == "mpb_periodic_h_l2_v1",
            "CANONICAL_REPRESENTATION_PRECEDENCE_INVALID")
    settings = snapshot.provenance.get("solver_settings", {})
    require(isinstance(settings, Mapping) and settings.get("resolution") == 64,
            "SOLVER_SETTINGS_RESOLUTION_MISSING")
    require(metadata.get("resolution") == 64, "SOLVER_SETTINGS_NONCONFLICTING_FIELD_MISSING")
    mark(trace, "METADATA_VALIDATION")

    reciprocal = snapshot.provenance.get("mpb_k_point")
    require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3,
            "CANONICAL_RECIPROCAL_METADATA_MISSING")
    require(
        np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity["derived_kappa"]), rtol=0.0, atol=1e-9)
        and float(reciprocal[2]) == 0.0,
        "CANONICAL_RECIPROCAL_METADATA_MISMATCH",
    )
    mark(trace, "RECIPROCAL_METADATA_VALIDATION")

    expected_contract = local_affine_reference_cell_contract(
        spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity,
        lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
    )
    actual_contract = snapshot.provenance.get("local_affine_reference_cell_contract")
    actual_json = normalize(actual_contract)
    expected_json = normalize(expected_contract)
    require(canonical(actual_json) == canonical(expected_json), "REFERENCE_CELL_METADATA_INVALID")
    require(hashlib.sha256(canonical(actual_json)).hexdigest() == hashlib.sha256(canonical(expected_json)).hexdigest(),
            "REFERENCE_CELL_METADATA_DIGEST_INVALID")
    mark(trace, "REFERENCE_CELL_CONTRACT_VALIDATION")

    require(snapshot.provenance.get("local_affine_solver_polarization_identity") == "TM",
            "EXPLICIT_POLARIZATION_IDENTITY_INVALID")
    require(snapshot.provenance.get("phase_callback") in (None, "None")
            or "phase_callback" not in snapshot.provenance,
            "PHASE_CALLBACK_PRODUCTION_PATH_INVALID")
    return {
        "frequencies_count": int(frequencies.size),
        "frequencies_all_finite_positive": True,
        "normalized_vectors_count": len(snapshot.normalized_vectors),
        "normalized_vectors_all_finite_unit": True,
        "gram_matrix_shape": "6x6",
        "gram_matrix_all_finite": True,
        "spatial_shape": "64x64",
        "component_count": 3,
        "canonical_snapshot_representation": metadata["representation"],
        "solver_resolution": settings["resolution"],
        "reference_cell_contract_sha256": hashlib.sha256(canonical(actual_json)).hexdigest(),
    }


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
            require(identity_before["public_q"] == [0.0, Q0[1]] and identity_before["s"] == 0.0,
                    "STATE_01_IDENTITY_INVALID")
            require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
            require("geometry=list(self.geometry)" in inspect.getsource(MPBLiveSpectralProvider._build_solver),
                    "MPB_BOUNDARY_LIST_CONVERSION_MISSING")
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
            validation = validate_snapshot(snapshot, spec, identity_before, trace)
            mark(trace, "FINALIZATION")
            write_json(output, {
                "state_id": "STATE_01",
                "frozen_state_identity_unchanged": True,
                "make_state_unchanged": True,
                "geometry_tuple_unchanged": True,
                "mpb_boundary_list_conversion_verified": True,
                "state01_full_snapshot_validation_passed": True,
                "exact_LocalAffineStateProvider_used": True,
                "production_phase_callback_none_path_used": True,
                "reference_cell_contract_exact_and_digest_equal": True,
                "earlier_reference_cell_failure_classification": "UNREPRODUCED_UNDER_UNCHANGED_PRODUCTION",
                "ordered_stage_markers": ",".join(markers(trace)),
                "field_payload_retained": False,
                **validation,
                "status": "PASS",
            })
            return 0
        except Exception as exc:
            persist_exception(output, trace, exc, "state01_acceptance_matrix", "STATE01_ACCEPTANCE_MATRIX")
            return 1
    except Exception as exc:
        persist_exception(output, trace, exc, "diagnostic_initialization", "STATE_CONSTRUCTION")
        return 1
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

    child: dict[str, Any] = {
        "state01_provider_solve_returned": False,
        "failure_side": "child_process",
        "exact_failing_stage": "STATE_CONSTRUCTION",
        "exception_type": None,
        "exception_code": None,
        "exception_message": None,
        "last_successful_stage": "NONE",
        "next_pending_stage": "STATE_CONSTRUCTION",
        "ordered_stage_markers": "",
        "field_payload_retained": False,
        "status": "FAIL",
    }
    completed: subprocess.CompletedProcess[bytes] | None = None
    parent_error: BaseException | None = None
    production_blobs_equivalent = False
    trace_markers = ""
    fault_present = False
    try:
        production_blobs_equivalent = verify_production_blobs()
        BudgetCounter = load_budget_counter()
        counter = BudgetCounter(1, 1)
        with tempfile.TemporaryDirectory(prefix="mephc-p52-") as temporary:
            root = Path(temporary)
            trace = root / "state01.trace"
            output = root / "worker.json"
            counter.consume_provider()
            counter.consume_solver()
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace), str(output)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
            )
            if output.is_file():
                try:
                    loaded = json.loads(output.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        child = loaded
                except Exception as exc:
                    parent_error = exc
            trace_markers = ",".join(markers(trace))
            fault_present = trace.with_suffix(".fault").is_file()
    except Exception as exc:
        parent_error = exc

    scientific_pass = completed is not None and completed.returncode == 0 and child.get("status") == "PASS"
    if parent_error is not None:
        child.update({
            "failure_side": "parent_harness",
            "exception_type": type(parent_error).__name__,
            "exception_code": safe_code(parent_error),
            "exception_message": sanitize_text(str(parent_error)),
            "status": "FAIL",
        })
    result = {
        "schema": "mephc-local-affine-p52-state01-full-p44-recertification-v1",
        "work_order_id": WORK_ORDER_ID,
        "original_p44_work_order_id": ORIGINAL_P44_WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "p51_source_commit": P51_SOURCE_COMMIT,
        "production_blob_equivalence_to_original_p44": production_blobs_equivalent,
        "production_code_changed": False,
        "child_return_code": completed.returncode if completed is not None else None,
        "parent_exception_type": type(parent_error).__name__ if parent_error else None,
        "parent_exception_code": safe_code(parent_error) if parent_error else None,
        "parent_exception_message": sanitize_text(str(parent_error)) if parent_error else None,
        "child_stderr_bounded_and_sanitized": True,
        "child_stderr_excerpt_sanitized": sanitize_text(completed.stderr if completed is not None else b""),
        "faulthandler_output_present": fault_present,
        "ordered_stage_markers": trace_markers,
        "parent_result_written_after_child_outcome": True,
        "diagnostic_child_process_count": 1 if completed is not None else 0,
        "native_invocation_count": 1 if completed is not None else 0,
        "provider_execution_count": 1 if completed is not None else 0,
        "solver_execution_count": 1 if completed is not None else 0,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "sanitized_result_safe": True,
        "result_written_to_mephc_result_path": True,
        **child,
        "status": "PASS" if scientific_pass else "FAIL",
    }
    write_result(result)
    return 0 if scientific_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
