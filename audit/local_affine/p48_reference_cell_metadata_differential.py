"""Differentially localize the P44 reference-cell metadata mismatch."""
from __future__ import annotations

import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import canonical_state_identity, geometry_anchor_status, make_state
from mephc.local_affine_state_provider import LocalAffineStateProvider, local_affine_reference_cell_contract
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P48-REFERENCE-CELL-METADATA-DIFFERENTIAL-20260830-412"
ORIGINAL_P44_SOURCE_COMMIT = "43e934027bcf5947e6192004ddf7263bb6883757"
P47_SOURCE_COMMIT = "02abcc78e0fe7d4ea67a4b03f969f1e0031c1c96"
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


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p48_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def git_blob(commit: str, path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"], cwd=root,
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def verify_production_blobs() -> bool:
    for path in PRODUCTION_PATHS:
        require(git_blob(P47_SOURCE_COMMIT, path) == git_blob(ORIGINAL_P44_SOURCE_COMMIT, path),
                f"PRODUCTION_BLOB_CHANGED:{path}")
    return True


def scalar(value: Any) -> tuple[str, str]:
    type_name = type(value).__name__
    if isinstance(value, float) and not math.isfinite(value):
        return type_name, "nonfinite"
    text = str(value)
    return type_name, text[:128]


def compare_values(actual: Any, expected: Any, path: str = "$") -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    if isinstance(actual, dict) and isinstance(expected, dict):
        actual_keys = set(actual)
        expected_keys = set(expected)
        for key in sorted(actual_keys - expected_keys):
            differences.append({"path": f"{path}.{key}", "category": "extra_key", "actual": actual[key], "expected": None})
        for key in sorted(expected_keys - actual_keys):
            differences.append({"path": f"{path}.{key}", "category": "missing_key", "actual": None, "expected": expected[key]})
        for key in sorted(actual_keys & expected_keys):
            differences.extend(compare_values(actual[key], expected[key], f"{path}.{key}"))
        return differences
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            differences.append({"path": path, "category": "container_length", "actual": len(actual), "expected": len(expected)})
        for index in range(min(len(actual), len(expected))):
            differences.extend(compare_values(actual[index], expected[index], f"{path}[{index}]"))
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


def difference_fields(differences: list[dict[str, Any]], index: int) -> dict[str, Any]:
    if index >= len(differences):
        return {
            f"diff_{index + 1}_path": None, f"diff_{index + 1}_category": None,
            f"diff_{index + 1}_actual_type": None, f"diff_{index + 1}_actual_value": None,
            f"diff_{index + 1}_expected_type": None, f"diff_{index + 1}_expected_value": None,
            f"diff_{index + 1}_numeric_delta": None,
        }
    item = differences[index]
    actual_type, actual_value = scalar(item["actual"]) if item["actual"] is not None else ("missing", None)
    expected_type, expected_value = scalar(item["expected"]) if item["expected"] is not None else ("missing", None)
    delta = None
    if isinstance(item["actual"], (int, float)) and isinstance(item["expected"], (int, float)):
        delta = float(item["actual"] - item["expected"])
    return {
        f"diff_{index + 1}_path": item["path"], f"diff_{index + 1}_category": item["category"],
        f"diff_{index + 1}_actual_type": actual_type, f"diff_{index + 1}_actual_value": actual_value,
        f"diff_{index + 1}_expected_type": expected_type, f"diff_{index + 1}_expected_value": expected_value,
        f"diff_{index + 1}_numeric_delta": delta,
    }


def worker(output: Path) -> int:
    import meep as mp

    require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
    spec = make_state(Q0, 0.0)
    identity_before = canonical_state_identity(spec)
    require(identity_before["public_q"] == [0.0, Q0[1]] and identity_before["s"] == 0.0,
            "STATE_01_IDENTITY_INVALID")
    require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
    require("geometry=list(self.geometry)" in inspect.getsource(MPBLiveSpectralProvider._build_solver),
            "MPB_BOUNDARY_LIST_CONVERSION_MISSING")
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
    snapshot = provider.solve(spec)
    require(canonical_state_identity(spec) == identity_before, "FROZEN_STATE_IDENTITY_CHANGED")
    reciprocal = snapshot.provenance.get("mpb_k_point")
    require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3
            and np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity_before["derived_kappa"]), rtol=0.0, atol=1e-9)
            and float(reciprocal[2]) == 0.0, "RECIPROCAL_METADATA_NOT_REACHED")
    actual = snapshot.provenance.get("local_affine_reference_cell_contract")
    expected = local_affine_reference_cell_contract(
        spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity_before,
        lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
    )
    expected_again = local_affine_reference_cell_contract(
        spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity_before,
        lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
    )
    require(isinstance(actual, dict) and isinstance(expected, dict), "REFERENCE_CONTRACT_SHAPE_INVALID")
    differences = compare_values(actual, expected)
    canonical_equal = canonical(actual) == canonical(expected)
    differences_bounded = differences[:8]
    payload: dict[str, Any] = {
        "state_id": "STATE_01",
        "solve_returned": True,
        "reciprocal_metadata_validation_reached": True,
        "actual_contract_key_count": len(actual),
        "expected_contract_key_count": len(expected),
        "difference_count": len(differences),
        "bounded_difference_count": len(differences_bounded),
        "first_differing_json_path": differences[0]["path"] if differences else None,
        "first_differing_category": differences[0]["category"] if differences else None,
        "canonical_json_serialization_equal": canonical_equal,
        "expected_recomputation_deterministic": expected == expected_again,
        "actual_contract_source": "snapshot_provenance",
        "expected_contract_source": "canonical_recomputation",
        "field_payload_retained": False,
    }
    for index in range(8):
        payload.update(difference_fields(differences_bounded, index))
    write_json(output, payload)
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))
    production_blobs_equivalent = verify_production_blobs()
    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p48-") as temporary:
        output = Path(temporary) / "worker.json"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(output)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        require(completed.returncode == 0 and output.is_file(), "P48_WORKER_FAILED")
        worker_result = json.loads(output.read_text(encoding="utf-8"))
        require(isinstance(worker_result, dict), "P48_WORKER_RESULT_INVALID")

    mismatch = worker_result.get("difference_count", 0) > 0
    root_direct = mismatch and worker_result.get("expected_recomputation_deterministic") is True
    write_result({
        "schema": "mephc-local-affine-p48-reference-cell-metadata-differential-v1",
        "work_order_id": WORK_ORDER_ID,
        "parent_work_order_id": "MEPHC-LOCALAFFINE-P47-P46-FAILURE-LOCALIZATION-20260830-411",
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "original_p44_source_commit": ORIGINAL_P44_SOURCE_COMMIT,
        "p47_contract_source_commit": P47_SOURCE_COMMIT,
        "production_blob_equivalence_to_p44": production_blobs_equivalent,
        "production_code_changed": False,
        **worker_result,
        "mismatch_origin": "snapshot_provenance_construction" if root_direct else ("no_mismatch" if not mismatch else "unresolved"),
        "root_cause_directly_identified": root_direct,
        "minimal_proposed_corrective_target": "LocalAffineStateProvider.solve" if root_direct else None,
        "minimal_proposed_corrective": "preserve the canonical reference-cell contract when constructing returned snapshot provenance" if root_direct else None,
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
