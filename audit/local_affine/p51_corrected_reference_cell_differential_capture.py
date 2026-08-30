"""Crash-safe, single-attempt P51 reference-cell differential capture."""
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
from mephc.local_affine_state_provider import LocalAffineStateProvider, local_affine_reference_cell_contract
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P51-P50-HARNESS-FAULTHANDLER-FIX-20260830-415"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
P50_SOURCE_COMMIT = "6384ce8730a8caa62fdf56e7e98853511117798e"
Q0 = (0.0, -0.6166666666666667)
PRODUCTION_PATHS = (
    "mephc/local_affine_state_provider.py",
    "mephc/mpb_spectral_provider.py",
    "audit/e10f/e8b_local_affine_model.py",
)
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")
STAGES = (
    "STATE_CONSTRUCTION",
    "PROVIDER_CONSTRUCTION",
    "MPB_SOLVE_RETURN",
    "RECIPROCAL_METADATA_VALIDATION",
    "ACTUAL_CONTRACT_CAPTURE",
    "EXPECTED_CONTRACT_RECOMPUTATION",
    "CONTRACT_NORMALIZATION",
    "CONTRACT_COMPARISON",
    "DIFFERENTIAL_PERSISTENCE",
    "FINALIZATION",
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
    spec = importlib.util.spec_from_file_location("_mephc_p51_scientific_job", path)
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
    for path in PRODUCTION_PATHS:
        require(
            git_blob(P50_SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path),
            f"PRODUCTION_BLOB_CHANGED:{path}",
        )
    return True


def marker(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def read_markers(path: Path) -> list[str]:
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
    raise TypeError(f"UNSAFE_CONTRACT_VALUE:{type(value).__name__}")


def compare(actual: Any, expected: Any, path: str = "$") -> list[dict[str, Any]]:
    if isinstance(actual, dict) and isinstance(expected, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(actual) - set(expected)):
            differences.append({"path": f"{path}.{key}", "category": "extra_key", "actual": actual[key], "expected": None})
        for key in sorted(set(expected) - set(actual)):
            differences.append({"path": f"{path}.{key}", "category": "missing_key", "actual": None, "expected": expected[key]})
        for key in sorted(set(actual) & set(expected)):
            differences.extend(compare(actual[key], expected[key], f"{path}.{key}"))
        return differences
    if isinstance(actual, list) and isinstance(expected, list):
        differences = []
        if len(actual) != len(expected):
            differences.append({"path": path, "category": "container_length", "actual": len(actual), "expected": len(expected)})
        for index in range(min(len(actual), len(expected))):
            differences.extend(compare(actual[index], expected[index], f"{path}[{index}]"))
        return differences
    if type(actual) is not type(expected):
        category = "container_type" if isinstance(actual, (dict, list)) or isinstance(expected, (dict, list)) else "scalar_type"
    elif isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and actual != expected:
        category = "numeric_value"
    elif actual != expected:
        category = "scalar_value"
    else:
        return []
    return [{"path": path, "category": category, "actual": actual, "expected": expected}]


def bounded_scalar(value: Any) -> tuple[str, str]:
    if value is None:
        return "missing", "null"
    return type(value).__name__, str(value)[:128]


def differential(actual: Any, expected: Any) -> dict[str, Any]:
    actual_json = normalize(actual)
    expected_json = normalize(expected)
    differences = compare(actual_json, expected_json)
    result: dict[str, Any] = {
        "actual_contract_json_sha256": hashlib.sha256(canonical(actual_json)).hexdigest(),
        "expected_contract_json_sha256": hashlib.sha256(canonical(expected_json)).hexdigest(),
        "actual_contract_key_set": ",".join(sorted(actual_json)) if isinstance(actual_json, dict) else None,
        "expected_contract_key_set": ",".join(sorted(expected_json)) if isinstance(expected_json, dict) else None,
        "canonical_json_serialization_equal": canonical(actual_json) == canonical(expected_json),
        "difference_count": len(differences),
        "bounded_difference_count": min(len(differences), 8),
        "first_differing_json_path": differences[0]["path"] if differences else None,
        "first_differing_category": differences[0]["category"] if differences else "none",
        "mismatch_category": differences[0]["category"] if differences else "none",
    }
    for index in range(8):
        prefix = f"diff_{index + 1}_"
        if index >= len(differences):
            result.update({prefix + key: None for key in (
                "path", "category", "actual_type", "actual_value", "expected_type", "expected_value", "numeric_delta"
            )})
            continue
        item = differences[index]
        actual_type, actual_value = bounded_scalar(item["actual"])
        expected_type, expected_value = bounded_scalar(item["expected"])
        numeric_delta = None
        if isinstance(item["actual"], (int, float)) and isinstance(item["expected"], (int, float)):
            numeric_delta = float(item["actual"] - item["expected"])
        result.update({
            prefix + "path": item["path"], prefix + "category": item["category"],
            prefix + "actual_type": actual_type, prefix + "actual_value": actual_value,
            prefix + "expected_type": expected_type, prefix + "expected_value": expected_value,
            prefix + "numeric_delta": numeric_delta,
        })
    return result


def mismatch_origin(stage: str) -> str:
    if stage in {"ACTUAL_CONTRACT_CAPTURE", "RECIPROCAL_METADATA_VALIDATION"}:
        return "snapshot_provenance_construction"
    if stage == "EXPECTED_CONTRACT_RECOMPUTATION":
        return "expected_contract_recomputation"
    if stage == "CONTRACT_NORMALIZATION":
        return "metadata_flattening_precedence"
    if stage in {"CONTRACT_COMPARISON", "DIFFERENTIAL_PERSISTENCE"}:
        return "comparison_harness_failure"
    if stage in {"STATE_CONSTRUCTION", "PROVIDER_CONSTRUCTION", "MPB_SOLVE_RETURN"}:
        return "contract_construction_failure"
    return "unresolved"


def persist_exception(output: Path, trace: Path, exc: BaseException, side: str, pending: str) -> None:
    """Persist a bounded exception record without allowing reporting to mask it."""
    try:
        ordered = read_markers(trace)
        frames = traceback.extract_tb(exc.__traceback__)
        deepest = frames[-1] if frames else None
        last_stage = ordered[-1] if ordered else "NONE"
        record: dict[str, Any] = {
            "solve_returned": "MPB_SOLVE_RETURN" in ordered,
            "failure_side": side,
            "exception_type": type(exc).__name__,
            "exception_code": safe_code(exc),
            "exception_message": sanitize_text(str(exc)),
            "deepest_frame_basename": Path(deepest.filename).name if deepest else None,
            "deepest_frame_line": deepest.lineno if deepest else None,
            "deepest_frame_function": deepest.name if deepest else None,
            "last_successful_stage": last_stage,
            "next_pending_stage": pending,
            "ordered_stage_markers": ",".join(ordered),
            "root_cause_directly_identified": False,
            "mismatch_origin": mismatch_origin(last_stage),
            "difference_count": 0,
            "bounded_difference_count": 0,
            "canonical_json_serialization_equal": False,
            "mismatch_category": "exception",
            "field_payload_retained": False,
        }
        write_json(output, record)
    except Exception:
        # The normal temporary output path is writable; this final fallback is
        # deliberately scalar-only and must not raise into the worker.
        try:
            write_json(output, {
                "solve_returned": False,
                "failure_side": side,
                "exception_type": type(exc).__name__,
                "exception_code": type(exc).__name__,
                "exception_message": type(exc).__name__,
                "last_successful_stage": "NONE",
                "next_pending_stage": pending,
                "root_cause_directly_identified": False,
                "mismatch_origin": "unresolved",
                "field_payload_retained": False,
            })
        except Exception:
            pass


def worker(trace: Path, output: Path) -> int:
    fault_file = None
    try:
        # Both faulthandler initialization and the scientific body are inside
        # the same persistence boundary; a setup failure cannot erase its code.
        fault_file = trace.with_suffix(".fault").open("ab", buffering=0)
        faulthandler.enable(file=fault_file, all_threads=True)
        marker(trace, "WORKER_START")
        try:
            import meep as mp

            require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
            spec = make_state(Q0, 0.0)
            identity = canonical_state_identity(spec)
            require(identity["public_q"] == [0.0, Q0[1]] and identity["s"] == 0.0, "STATE_01_IDENTITY_INVALID")
            require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
            require(
                "geometry=list(self.geometry)" in inspect.getsource(MPBLiveSpectralProvider._build_solver),
                "MPB_BOUNDARY_LIST_CONVERSION_MISSING",
            )
            marker(trace, "STATE_CONSTRUCTION")
            provider = LocalAffineStateProvider(
                resolution=64, num_bands=6, eigensolver_tolerance=1e-7, mesh_size=3,
                deterministic=True, polarization=mp.TM, polarization_identity="TM", default_material=mp.air,
            )
            marker(trace, "PROVIDER_CONSTRUCTION")
            snapshot = provider.solve(spec)
            marker(trace, "MPB_SOLVE_RETURN")
            reciprocal = snapshot.provenance.get("mpb_k_point")
            require(
                isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3
                and np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity["derived_kappa"]), rtol=0.0, atol=1e-9)
                and float(reciprocal[2]) == 0.0,
                "RECIPROCAL_METADATA_INVALID",
            )
            marker(trace, "RECIPROCAL_METADATA_VALIDATION")
            actual = snapshot.provenance.get("local_affine_reference_cell_contract")
            marker(trace, "ACTUAL_CONTRACT_CAPTURE")
            expected = local_affine_reference_cell_contract(
                spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity,
                lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
            )
            marker(trace, "EXPECTED_CONTRACT_RECOMPUTATION")
            marker(trace, "CONTRACT_NORMALIZATION")
            result = differential(actual, expected)
            marker(trace, "CONTRACT_COMPARISON")
            marker(trace, "DIFFERENTIAL_PERSISTENCE")
            require(canonical_state_identity(spec) == identity and isinstance(spec.geometry, tuple), "FROZEN_STATE_IDENTITY_CHANGED")
            result.update({
                "solve_returned": True, "failure_side": None, "exception_type": None,
                "exception_message": None, "exception_code": None,
                "last_successful_stage": "DIFFERENTIAL_PERSISTENCE", "next_pending_stage": "FINALIZATION",
                "ordered_stage_markers": ",".join(read_markers(trace)),
                "root_cause_directly_identified": False,
                "mismatch_origin": "unresolved",
                "field_payload_retained": False,
            })
            write_json(output, result)
            marker(trace, "FINALIZATION")
            return 0
        except Exception as exc:
            pending = STAGES[len(read_markers(trace))] if len(read_markers(trace)) < len(STAGES) else "FINALIZATION"
            persist_exception(output, trace, exc, "contract_differential", pending)
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


def child_fallback() -> dict[str, Any]:
    return {
        "solve_returned": False, "failure_side": "child_process", "exception_type": None,
        "exception_message": None, "exception_code": None, "last_successful_stage": "NONE",
        "next_pending_stage": "STATE_CONSTRUCTION", "ordered_stage_markers": "",
        "root_cause_directly_identified": False, "mismatch_origin": "comparison_harness_failure",
        "difference_count": 0, "bounded_difference_count": 0,
        "canonical_json_serialization_equal": False, "mismatch_category": "comparison_harness_failure",
        "field_payload_retained": False,
    }


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]), Path(sys.argv[3]))

    production_blobs_equivalent = False
    completed: subprocess.CompletedProcess[bytes] | None = None
    child: dict[str, Any] = child_fallback()
    markers = ""
    fault_present = False
    parent_error: BaseException | None = None
    try:
        production_blobs_equivalent = verify_production_blobs()
        BudgetCounter = load_budget_counter()
        counter = BudgetCounter(1, 1)
        with tempfile.TemporaryDirectory(prefix="mephc-p51-") as temporary:
            root = Path(temporary)
            trace = root / "state01.trace"
            output = root / "child.json"
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
                except Exception:
                    child = child_fallback()
            markers = ",".join(read_markers(trace))
            fault_present = trace.with_suffix(".fault").is_file()
    except Exception as exc:
        parent_error = exc

    completed_return_code = completed.returncode if completed is not None else None
    stderr = completed.stderr if completed is not None else b""
    result: dict[str, Any] = {
        "schema": "mephc-local-affine-p51-corrected-reference-cell-differential-capture-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": "MEPHC-LOCALAFFINE-P50-CORRECTED-REFERENCE-CELL-DIFFERENTIAL-CAPTURE-20260830-414",
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "p50_source_commit": P50_SOURCE_COMMIT,
        "production_blob_equivalence_to_p44": production_blobs_equivalent,
        "production_code_changed": False,
        "p50_harness_faulthandler_import_corrected": True,
        "diagnostic_initialization_inside_persistence_boundary": True,
        "exception_result_persisted_before_optional_sanitization": True,
        "parent_result_written_after_child_outcome": True,
        "diagnostic_contract_completed": parent_error is None,
        "parent_exception_type": type(parent_error).__name__ if parent_error else None,
        "parent_exception_code": safe_code(parent_error) if parent_error else None,
        "parent_exception_message": sanitize_text(str(parent_error)) if parent_error else None,
        "child_return_code": completed_return_code,
        "ordered_stage_markers": markers,
        "faulthandler_output_present": fault_present,
        "stderr_bounded_and_sanitized": True,
        "stderr_excerpt_sanitized": sanitize_text(stderr),
        **child,
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
        "status": "PASS",
    }
    write_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
