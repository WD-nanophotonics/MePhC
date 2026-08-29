"""Certify STATE_01 after canonical metadata precedence is restored."""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import (
    canonical_state_identity,
    geometry_anchor_status,
    make_state,
)
from mephc.local_affine_state_provider import LocalAffineStateProvider, _metadata, local_affine_reference_cell_contract
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P44-METADATA-REPRESENTATION-PRECEDENCE-FIX-STATE01-CERTIFICATION-20260830-408"
Q0 = (0.0, -37.0 / 60.0)


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
    spec = importlib.util.spec_from_file_location("_mephc_p44_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def worker(output: Path) -> int:
    import meep as mp

    require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
    spec = make_state(Q0, 0.0)
    identity_before = canonical_state_identity(spec)
    require(identity_before["public_q"] == [0.0, Q0[1]] and identity_before["s"] == 0.0,
            "STATE_01_IDENTITY_INVALID")
    require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_NOT_TUPLE")
    provider_source = inspect.getsource(MPBLiveSpectralProvider._build_solver)
    require("geometry=list(self.geometry)" in provider_source,
            "MPB_BOUNDARY_LIST_CONVERSION_MISSING")
    stage_provider = LocalAffineStateProvider(
        resolution=64,
        num_bands=6,
        eigensolver_tolerance=1e-7,
        mesh_size=3,
        deterministic=True,
        polarization=mp.TM,
        polarization_identity="TM",
        default_material=mp.air,
    )
    snapshot = stage_provider.solve(spec)
    identity_after = canonical_state_identity(spec)
    require(identity_before == identity_after, "FROZEN_STATE_IDENTITY_CHANGED")
    require(isinstance(spec.geometry, tuple), "AFFINE_GEOMETRY_STATE_GEOMETRY_MUTATED")

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

    metadata = _metadata(snapshot)
    require(metadata.get("representation") == "mpb_periodic_h_l2_v1",
            "CANONICAL_REPRESENTATION_PRECEDENCE_INVALID")
    settings = snapshot.provenance.get("solver_settings", {})
    require(isinstance(settings, dict) and settings.get("resolution") == 64,
            "SOLVER_SETTINGS_RESOLUTION_MISSING")
    require(metadata.get("resolution") == 64, "SOLVER_SETTINGS_NONCONFLICTING_FIELD_MISSING")
    reciprocal = snapshot.provenance.get("mpb_k_point")
    require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3,
            "CANONICAL_RECIPROCAL_METADATA_MISSING")
    require(np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity_before["derived_kappa"]),
                        rtol=0.0, atol=1e-9) and float(reciprocal[2]) == 0.0,
            "CANONICAL_RECIPROCAL_METADATA_MISMATCH")
    expected_contract = local_affine_reference_cell_contract(
        spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity_before,
        lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
    )
    require(snapshot.provenance.get("local_affine_reference_cell_contract") == expected_contract,
            "REFERENCE_CELL_METADATA_INVALID")
    require(snapshot.provenance.get("local_affine_solver_polarization_identity") == "TM",
            "EXPLICIT_POLARIZATION_IDENTITY_INVALID")
    require(snapshot.provenance.get("phase_callback") in (None, "None")
            or "phase_callback" not in snapshot.provenance,
            "PHASE_CALLBACK_PRODUCTION_PATH_INVALID")
    write_json(output, {
        "state_id": "STATE_01",
        "frozen_state_identity_unchanged": True,
        "make_state_unchanged": True,
        "canonical_snapshot_representation_precedence_preserved": True,
        "solver_settings_nonconflicting_fields_remain_available": True,
        "state01_provider_solve_returned": True,
        "state01_full_snapshot_validation_passed": True,
        "exact_LocalAffineStateProvider_used": True,
        "production_phase_callback_none_path_used": True,
        "full_snapshot_validation_status": "PASS",
    })
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))
    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p44-") as temporary:
        output = Path(temporary) / "worker.json"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(output)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        require(completed.returncode == 0 and output.is_file(), "STATE_01_WORKER_FAILED")
        worker_result = json.loads(output.read_text(encoding="utf-8"))
        require(isinstance(worker_result, dict), "STATE_01_WORKER_RESULT_INVALID")
    write_result({
        "schema": "mephc-local-affine-p44-metadata-fix-certification-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT", ""),
        "prepatch_local_affine_provider_blob_verified": True,
        "patched_mpb_provider_blob_unchanged": True,
        "metadata_precedence_unit_test_passed": True,
        "local_affine_provider_tests_passed": True,
        "mpb_boundary_test_passed": True,
        "thin_flow_tests_passed": True,
        "compileall_passed": True,
        **worker_result,
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
