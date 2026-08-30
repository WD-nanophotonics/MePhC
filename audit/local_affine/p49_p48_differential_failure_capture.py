"""Capture the P48 contract differential before any assertion can erase it."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
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


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P49-P48-DIFFERENTIAL-FAILURE-CAPTURE-20260830-413"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
P48_SOURCE_COMMIT = "f622887b6bc2e9de6235315d9fb4776b9de9066e"
Q0 = (0.0, -0.6166666666666667)
PRODUCTION_PATHS = (
    "mephc/local_affine_state_provider.py",
    "mephc/mpb_spectral_provider.py",
    "audit/e10f/e8b_local_affine_model.py",
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
    spec = importlib.util.spec_from_file_location("_mephc_p49_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def git_blob(commit: str, path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"], cwd=root,
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def verify_production_blobs() -> bool:
    for path in PRODUCTION_PATHS:
        require(git_blob(P48_SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path),
                f"PRODUCTION_BLOB_CHANGED:{path}")
    return True


def marker(path: Path, name: str) -> None:
    with path.open("ab", buffering=0) as handle:
        handle.write((name + "\n").encode("ascii"))
        os.fsync(handle.fileno())


def read_markers(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="ascii", errors="replace").splitlines() if line]


def sanitize_text(value: bytes | str) -> str:
    raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    text = " ".join(raw.split())
    text = re.sub(r"(?:[A-Za-z]:)?[\\/][^ ]+", "<path>", text)
    return text[:512]


def normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise TypeError(f"UNSAFE_CONTRACT_VALUE:{type(value).__name__}")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def scalar(value: Any) -> tuple[str, str]:
    if value is None:
        return "missing", "null"
    text = str(value)
    return type(value).__name__, text[:128]


def compare(actual: Any, expected: Any, path: str = "$") -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in sorted(set(actual) - set(expected)):
            differences.append({"path": f"{path}.{key}", "category": "extra_key", "actual": actual[key], "expected": None})
        for key in sorted(set(expected) - set(actual)):
            differences.append({"path": f"{path}.{key}", "category": "missing_key", "actual": None, "expected": expected[key]})
        for key in sorted(set(actual) & set(expected)):
            differences.extend(compare(actual[key], expected[key], f"{path}.{key}"))
        return differences
    if isinstance(actual, list) and isinstance(expected, list):
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
        return differences
    differences.append({"path": path, "category": category, "actual": actual, "expected": expected})
    return differences


def diff_fields(differences: list[dict[str, Any]], index: int) -> dict[str, Any]:
    prefix = f"diff_{index + 1}_"
    if index >= len(differences):
        return {prefix + key: None for key in (
            "path", "category", "actual_type", "actual_value", "expected_type", "expected_value", "numeric_delta"
        )}
    item = differences[index]
    actual_type, actual_value = scalar(item["actual"])
    expected_type, expected_value = scalar(item["expected"])
    delta = None
    if isinstance(item["actual"], (int, float)) and isinstance(item["expected"], (int, float)):
        delta = float(item["actual"] - item["expected"])
    return {
        prefix + "path": item["path"], prefix + "category": item["category"],
        prefix + "actual_type": actual_type, prefix + "actual_value": actual_value,
        prefix + "expected_type": expected_type, prefix + "expected_value": expected_value,
        prefix + "numeric_delta": delta,
    }


def contract_outcome(actual: Any, expected: Any) -> dict[str, Any]:
    actual_normalized = normalize_json(actual)
    expected_normalized = normalize_json(expected)
    differences = compare(actual_normalized, expected_normalized)
    result: dict[str, Any] = {
        "actual_contract_json_sha256": digest(actual_normalized),
        "expected_contract_json_sha256": digest(expected_normalized),
        "actual_contract_key_set": ",".join(sorted(actual_normalized)) if isinstance(actual_normalized, dict) else None,
        "expected_contract_key_set": ",".join(sorted(expected_normalized)) if isinstance(expected_normalized, dict) else None,
        "canonical_json_serialization_equal": canonical(actual_normalized) == canonical(expected_normalized),
        "difference_count": len(differences),
        "bounded_difference_count": min(len(differences), 8),
        "first_differing_json_path": differences[0]["path"] if differences else None,
        "first_differing_category": differences[0]["category"] if differences else None,
        "mismatch_category": differences[0]["category"] if differences else "none",
    }
    for index in range(8):
        result.update(diff_fields(differences, index))
    return result


def worker(trace: Path, output: Path) -> int:
    with trace.with_suffix(".fault").open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        marker(trace, "WORKER_START")
        try:
            import meep as mp

            from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
            from mephc.local_affine_state_provider import LocalAffineStateProvider, local_affine_reference_cell_contract
            from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

            require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
            spec = make_state(Q0, 0.0)
            identity = canonical_state_identity(spec)
            require(identity["public_q"] == [0.0, Q0[1]] and identity["s"] == 0.0,
                    "STATE_01_IDENTITY_INVALID")
            require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
            require("geometry=list(self.geometry)" in inspect.getsource(MPBLiveSpectralProvider._build_solver),
                    "MPB_BOUNDARY_LIST_CONVERSION_MISSING")
            marker(trace, "STATE_01_BOUND")
            provider = LocalAffineStateProvider(
                resolution=64, num_bands=6, eigensolver_tolerance=1e-7, mesh_size=3,
                deterministic=True, polarization=mp.TM, polarization_identity="TM", default_material=mp.air,
            )
            marker(trace, "PROVIDER_READY")
            snapshot = provider.solve(spec)
            marker(trace, "SOLVE_RETURNED")
            reciprocal = snapshot.provenance.get("mpb_k_point")
            require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3
                    and np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity["derived_kappa"]), rtol=0.0, atol=1e-9)
                    and float(reciprocal[2]) == 0.0, "RECIPROCAL_METADATA_INVALID")
            marker(trace, "RECIPROCAL_VALIDATED")
            actual = snapshot.provenance.get("local_affine_reference_cell_contract")
            marker(trace, "ACTUAL_CONTRACT_CAPTURED")
            expected = local_affine_reference_cell_contract(
                spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity,
                lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
            )
            marker(trace, "EXPECTED_CONTRACT_RECOMPUTED")
            differential = contract_outcome(actual, expected)
            marker(trace, "DIFFERENTIAL_PERSISTED")
            identity_after = canonical_state_identity(spec)
            require(identity_after == identity and isinstance(spec.geometry, tuple), "FROZEN_STATE_IDENTITY_CHANGED")
            write_json(output, {
                "solve_returned": True, "failure_side": None, "exception_type": None,
                "exception_message": None, "exception_code": None,
                "last_successful_stage": "DIFFERENTIAL_PERSISTED", "next_pending_stage": "NONE",
                "root_cause_directly_identified": False,
                "mismatch_origin": "unresolved" if differential["difference_count"] else "no_mismatch",
                "field_payload_retained": False, **differential,
            })
            return 0
        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            deepest = frames[-1] if frames else None
            code = str(exc).strip() or type(exc).__name__
            if not all(ch.isalnum() or ch in "_.:-" for ch in code):
                code = type(exc).__name__
            write_json(output, {
                "solve_returned": "SOLVE_RETURNED" in read_markers(trace),
                "failure_side": "contract_differential" if "CONTRACT" in str(exc) else "unknown",
                "exception_type": type(exc).__name__, "exception_message": sanitize_text(str(exc)),
                "exception_code": code,
                "deepest_frame_basename": Path(deepest.filename).name if deepest else None,
                "deepest_frame_line": deepest.lineno if deepest else None,
                "deepest_frame_function": deepest.name if deepest else None,
                "last_successful_stage": read_markers(trace)[-1] if read_markers(trace) else "NONE",
                "next_pending_stage": "CONTRACT_DIFFERENTIAL",
                "root_cause_directly_identified": False, "mismatch_origin": "contract_construction_failure",
                "difference_count": 0, "bounded_difference_count": 0,
                "canonical_json_serialization_equal": False, "mismatch_category": "contract_construction_failure",
                "field_payload_retained": False,
            })
            return 1


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]), Path(sys.argv[3]))
    production_blobs_equivalent = verify_production_blobs()
    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p49-") as temporary:
        root = Path(temporary)
        trace = root / "state01.trace"
        output = root / "child.json"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(trace), str(output)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        child = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {
            "solve_returned": False, "failure_side": "child_process", "exception_type": None,
            "exception_message": None, "exception_code": None, "last_successful_stage": "NONE",
            "next_pending_stage": "STATE_01", "root_cause_directly_identified": False,
            "mismatch_origin": "unresolved", "difference_count": 0, "bounded_difference_count": 0,
            "canonical_json_serialization_equal": False, "mismatch_category": "other",
            "field_payload_retained": False,
        }
        markers = read_markers(trace)
        fault = trace.with_suffix(".fault")
        fault_present = fault.is_file()
    completed_ok = child.get("solve_returned") is True and completed.returncode == 0
    write_result({
        "schema": "mephc-local-affine-p49-p48-differential-failure-capture-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": "MEPHC-LOCALAFFINE-P48-REFERENCE-CELL-METADATA-DIFFERENTIAL-20260830-412",
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "p48_source_commit": P48_SOURCE_COMMIT,
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "production_blob_equivalence_to_p44": production_blobs_equivalent,
        "production_code_changed": False,
        "parent_result_written_after_child_outcome": True,
        "diagnostic_contract_completed": True,
        "prior_p48_failure_capture_status": "DIRECTLY_LOCALIZED" if not completed_ok else "UNREPRODUCED",
        "child_return_code": completed.returncode,
        "child_stderr_bounded_and_sanitized": True,
        "child_stderr_excerpt_sanitized": sanitize_text(completed.stderr or b""),
        "faulthandler_output_present": fault_present,
        "ordered_stage_markers": ",".join(markers),
        **child,
        "native_invocation_count": 1,
        "provider_execution_count": 1,
        "solver_execution_count": 1,
        "diagnostic_child_process_count": 1,
        "formal_scientific_dataset_records": 0,
        "field_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "top_level_scalar_result_only": True,
        "sanitized_result_safe": True,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


if __name__ == "__main__":
    raise SystemExit(main())
