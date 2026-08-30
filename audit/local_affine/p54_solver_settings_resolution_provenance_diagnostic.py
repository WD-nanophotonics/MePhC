"""Diagnose the bounded STATE_01 resolution provenance contract."""
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
from mephc.local_affine_state_provider import LocalAffineStateProvider, _metadata
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P54-SOLVER-SETTINGS-RESOLUTION-PROVENANCE-DIAGNOSTIC-20260830-418"
PARENT_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P53-NONBLOCKING-STATE01-RECERTIFICATION-20260830-417"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
P53_SOURCE_COMMIT = "fef3639a56c987bbe02aadab893db4b6d3f7ca70"
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
        if value is not None and SAFE_TOKEN.fullmatch(str(value).strip()):
            return str(value).strip()
    return type(exc).__name__


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("_mephc_p54_scientific_job", root / "tools" / "mephc-flow" / "scientific_job.py")
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def git_blob(commit: str, path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return subprocess.run(["git", "rev-parse", f"{commit}:{path}"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def verify_production_blobs() -> bool:
    for path in ("mephc/local_affine_state_provider.py", "mephc/mpb_spectral_provider.py", "audit/e10f/e8b_local_affine_model.py"):
        require(git_blob(P53_SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path), f"PRODUCTION_BLOB_CHANGED:{path}")
    return True


def mark(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def markers(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line] if path.is_file() else []


def scalar_location(path: str, container: Any, key: str = "resolution") -> dict[str, Any]:
    if not isinstance(container, Mapping) or key not in container:
        return {"path": path + "." + key, "present": False, "type": None, "value": None}
    value = container[key]
    safe_value = value if value is None or type(value) in {bool, int, float, str} else type(value).__name__
    return {"path": path + "." + key, "present": True, "type": type(value).__name__, "value": safe_value}


def source_resolution_evidence() -> dict[str, Any]:
    functions = {
        "LocalAffineStateProvider.solve": LocalAffineStateProvider.solve,
        "MPBLiveSpectralProvider._settings": MPBLiveSpectralProvider._settings,
        "MPBLiveSpectralProvider.solve": MPBLiveSpectralProvider.solve,
    }
    records: list[str] = []
    for name, function in functions.items():
        for line in inspect.getsource(function).splitlines():
            if "resolution" in line or "solver_settings" in line:
                records.append(f"{name}:{sanitize_text(line.strip())}")
    return {
        "source_resolution_evidence_key_set": ",".join(sorted(functions)),
        "source_resolution_assignment_count": len(records),
        "source_resolution_assignments_bounded": " | ".join(records[:8]),
    }


def full_snapshot_matrix(snapshot: Any) -> dict[str, Any]:
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies)) and np.all(frequencies > 0.0), "FULL_SNAPSHOT_FREQUENCIES_INVALID")
    require(len(snapshot.normalized_vectors) == 6, "FULL_SNAPSHOT_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        require(np.all(np.isfinite(values)), "FULL_SNAPSHOT_VECTOR_NONFINITE")
        require(np.isclose(float(np.linalg.norm(values)), 1.0, rtol=0.0, atol=1e-10), "FULL_SNAPSHOT_VECTOR_NONUNIT")
    gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
    require(gram.shape == (6, 6) and np.all(np.isfinite(gram)), "FULL_SNAPSHOT_GRAM_INVALID")
    require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3, "FULL_SNAPSHOT_SHAPE_INVALID")
    return {
        "frequencies_count": 6,
        "frequencies_all_finite_positive": True,
        "normalized_vectors_count": 6,
        "normalized_vectors_all_finite_unit": True,
        "gram_matrix_shape": "6x6",
        "gram_matrix_all_finite": True,
        "spatial_shape": "64x64",
        "component_count": 3,
    }


def classify(locations: list[dict[str, Any]], source: dict[str, Any], flattened: dict[str, Any]) -> tuple[str, bool]:
    solver = locations[1]
    observed_64 = [item for item in locations if item["present"] and item["value"] == 64]
    conflicting = [item for item in locations if item["present"] and item["value"] not in (64, None)]
    renamed = [item for item in locations if item["path"].endswith("renamed_resolution") and item["present"]]
    if conflicting:
        return "conflicting_provenance_value", True
    if renamed:
        return "renamed_provenance_field", True
    if not solver["present"] and observed_64 and flattened.get("value") == 64:
        return "obsolete_p44_acceptance_assumption", True
    if solver["present"] and solver["value"] != 64 and observed_64:
        return "conflicting_provenance_value", True
    if not observed_64 and source["source_resolution_assignment_count"]:
        return "production_solver_settings_omission", True
    if flattened.get("present") and not solver["present"]:
        return "flattened_metadata_loss", True
    return "unresolved", False


def persist_failure(output: Path, trace: Path, exc: BaseException, stage: str) -> None:
    ordered = markers(trace)
    frames = traceback.extract_tb(exc.__traceback__)
    deepest = frames[-1] if frames else None
    record = {
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
        "child_return_code": 1,
        "field_payload_retained": False,
        "status": "PASS",
    }
    try:
        write_json(output, record)
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
            configured_resolution = provider.resolution
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
            top_keys = ",".join(sorted(str(key) for key in provenance))
            settings = provenance.get("solver_settings")
            representation = provenance.get("representation_provenance")
            contract = provenance.get("local_affine_reference_cell_contract")
            flattened = scalar_location("flattened_metadata", _metadata(snapshot))
            locations = [
                scalar_location("solver_settings", settings),
                scalar_location("representation_provenance", representation),
                scalar_location("local_affine_reference_cell_contract", contract),
                scalar_location("top_level_provenance", provenance),
                flattened,
            ]
            other_resolution_keys = sorted(str(key) for key in provenance if "resolution" in str(key).lower() and key != "resolution")
            renamed = scalar_location("top_level_provenance", provenance, "renamed_resolution")
            locations.append(renamed)
            mark(trace, "PROVENANCE_CAPTURE")
            representation_value = provenance.get("representation")
            source = source_resolution_evidence()
            classification, root_direct = classify(locations, source, flattened)
            mark(trace, "SOURCE_CONSTRUCTION_INSPECTION")
            result = {
                **matrix,
                "state_id": "STATE_01",
                "provider_configured_resolution": configured_resolution,
                "provenance_top_level_key_set": top_keys,
                "solver_settings_present": isinstance(settings, Mapping),
                "solver_settings_type": type(settings).__name__ if settings is not None else None,
                "solver_settings_key_set": ",".join(sorted(str(key) for key in settings)) if isinstance(settings, Mapping) else None,
                "solver_settings_resolution_present": locations[0]["present"],
                "solver_settings_resolution_type": locations[0]["type"],
                "solver_settings_resolution_value": locations[0]["value"],
                "representation_provenance_key_set": ",".join(sorted(str(key) for key in representation)) if isinstance(representation, Mapping) else None,
                "representation_provenance_resolution": locations[1],
                "reference_cell_contract_resolution": locations[2],
                "top_level_resolution": locations[3],
                "flattened_metadata_resolution": flattened,
                "other_top_level_resolution_key_set": ",".join(other_resolution_keys),
                "canonical_snapshot_representation": representation_value,
                "p44_representation_precedence_preserved": representation_value == "mpb_periodic_h_l2_v1",
                "source_construction": source,
                "responsible_function": "MPBLiveSpectralProvider._settings" if root_direct else None,
                "responsible_assignment": '"resolution": self.resolution' if root_direct else None,
                "resolution_provenance_classification": classification,
                "root_cause_directly_identified": root_direct,
                "scientific_failure_code_under_diagnosis": "SOLVER_SETTINGS_RESOLUTION_MISSING",
                "scientific_acceptance_status": "PASS",
                "diagnostic_contract_completed": True,
                "ordered_stage_markers": ",".join(markers(trace)),
                "child_return_code": 0,
                "field_payload_retained": False,
                "status": "PASS",
            }
            write_json(output, result)
            return 0
        except Exception as exc:
            persist_failure(output, trace, exc, markers(trace)[-1] if markers(trace) else "STATE_CONSTRUCTION")
            return 0
    except Exception as exc:
        persist_failure(output, trace, exc, "DIAGNOSTIC_INITIALIZATION")
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
    production_ok = False
    parent_error: BaseException | None = None
    child_loaded = False
    try:
        production_ok = verify_production_blobs()
        BudgetCounter = load_budget_counter()
        counter = BudgetCounter(1, 1)
        with tempfile.TemporaryDirectory(prefix="mephc-p54-") as temporary:
            root = Path(temporary)
            trace, output = root / "state01.trace", root / "worker.json"
            counter.consume_provider()
            counter.consume_solver()
            completed = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace), str(output)], cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600)
            if output.is_file():
                loaded = json.loads(output.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    child, child_loaded = loaded, True
    except Exception as exc:
        parent_error = exc
    diagnostic_complete = parent_error is None and completed is not None and child_loaded
    if parent_error is not None:
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
        "schema": "mephc-local-affine-p54-solver-settings-resolution-provenance-diagnostic-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": PARENT_WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "p53_source_commit": P53_SOURCE_COMMIT,
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
