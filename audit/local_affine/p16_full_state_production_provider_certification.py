"""Certify one production LocalAffineStateProvider solve for receipt-bound P16."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import geometry_anchor_status, make_state
from mephc.local_affine_state_provider import LocalAffineStateProvider, local_affine_reference_cell_contract


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P16-FULL-STATE-PRODUCTION-PROVIDER-CERTIFICATION-20260830-380"
Q0 = (0.0, -37.0 / 60.0)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_p16_scientific_job", path)
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

    from audit.e10f.e8b_local_affine_model import canonical_state_identity, digest_state_identity

    require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_INVALID")
    spec = make_state(Q0, 0.0)
    identity = canonical_state_identity(spec)
    require(identity["public_q"] == [0.0, Q0[1]] and identity["s"] == 0.0, "STATE_01_IDENTITY_INVALID")
    require(identity["polarization"] == "TM", "POLARIZATION_IDENTITY_INVALID")
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
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies)) and np.all(frequencies > 0.0),
            "PERIODIC_H_SNAPSHOT_INVALID")
    raw_norms = np.asarray(snapshot.raw_norms, dtype=float)
    require(raw_norms.shape == (6,) and np.all(np.isfinite(raw_norms)) and np.all(raw_norms > 0.0),
            "RAW_NORMS_INVALID")
    unit_errors = []
    require(len(snapshot.normalized_vectors) == 6, "NORMALIZED_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        require(np.all(np.isfinite(values)), "NORMALIZED_VECTOR_NONFINITE")
        norm = float(np.linalg.norm(values))
        require(np.isfinite(norm) and np.isclose(norm, 1.0, rtol=0.0, atol=1e-10), "NORMALIZED_VECTOR_NONUNIT")
        unit_errors.append(abs(norm - 1.0))

    provenance = snapshot.to_dict()["provenance"]
    reciprocal = provenance.get("mpb_k_point")
    require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3, "CANONICAL_RECIPROCAL_METADATA_MISSING")
    require(np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity["derived_kappa"]), rtol=0.0, atol=1e-9)
            and float(reciprocal[2]) == 0.0, "CANONICAL_RECIPROCAL_METADATA_MISMATCH")
    expected_contract = local_affine_reference_cell_contract(
        spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity,
        lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y)),
    )
    require(provenance.get("local_affine_reference_cell_contract") == expected_contract,
            "REFERENCE_CELL_METADATA_INVALID")
    require(provenance.get("local_affine_solver_polarization_identity") == "TM",
            "EXPLICIT_POLARIZATION_IDENTITY_INVALID")
    require(provenance.get("phase_callback") in (None, "None") or "phase_callback" not in provenance,
            "PHASE_CALLBACK_PRODUCTION_PATH_INVALID")
    write_json(output, {
        "state_id": "STATE_01",
        "exact_state_identity_status": "PASS",
        "identity_sha256": digest_state_identity(identity),
        "frequencies": [float(value) for value in frequencies],
        "raw_norms": [float(value) for value in raw_norms],
        "normalized_vector_unit_errors": [float(value) for value in unit_errors],
        "six_finite_positive_frequencies": True,
        "six_positive_raw_norms": True,
        "six_finite_unit_normalized_vectors": True,
        "periodic_h_snapshot_status": "PASS",
        "canonical_reciprocal_metadata_status": "PASS",
        "reference_cell_metadata_status": "PASS",
        "explicit_polarization_identity_status": "PASS",
        "production_local_affine_provider_used": True,
        "production_mpb_h_provider_used": True,
        "phase_callback_none_production_path_used": True,
    })
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(1, 1)
    with tempfile.TemporaryDirectory(prefix="mephc-p16-") as temporary:
        worker_output = Path(temporary) / "worker.json"
        counter.consume_provider()
        counter.consume_solver()
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(worker_output)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
        )
        require(completed.returncode == 0 and worker_output.is_file(), "PRODUCTION_PROVIDER_WORKER_FAILED")
        worker_result = json.loads(worker_output.read_text(encoding="utf-8"))
        require(isinstance(worker_result, dict), "PRODUCTION_PROVIDER_RESULT_INVALID")

    source_commit = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    write_result({
        "schema": "mephc-local-affine-p16-full-state-production-provider-certification-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        **worker_result,
        "native_invocation_count": 1,
        "provider_execution_count": 1,
        "solver_execution_count": 1,
        "diagnostic_child_process_count": 1,
        "formal_scientific_dataset_records": 0,
        "raw_h_payload_retained": False,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "result_written_to_mephc_result_path": True,
        "status": "PASS",
    })
    return 0


def write_result(value: dict[str, Any]) -> None:
    target = Path(os.environ["MEPHC_RESULT_PATH"])
    write_json(target, value)


if __name__ == "__main__":
    raise SystemExit(main())
