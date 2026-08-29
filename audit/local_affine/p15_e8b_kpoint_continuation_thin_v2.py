"""Run the receipt-bound P15 E8B k-point continuation diagnostic."""
from __future__ import annotations

import faulthandler
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P15-E8B-KPOINT-CONTINUATION-THIN-V2-20260830-379"
P12_DATASET_ID = "3cb72daa2a2c2f72948982449712bc8ae5569374dbaf4161c9f81b7d3dc911bd"
P12_MANIFEST = "f7db9e9a2bccb66c42f4e97ffaa89548c7563990ad36aeb40cb2533906dfe947"
P12_KEY = "2557ce66360177b087cfac20946f120701cb8f3777f03092ce5e5a8aad4cc7f0"
P11_DATASET_ID = "a2e44227c43e3dabe425daae4350e9fe8f6987504069ffc14f86e276ea552663"
P11_MANIFEST = "e1ae5ea5d3d6070a9912bf69acb2857857ead68241e032c01a6addde60f58726"
P11_KEY = "8d88431b8f65602eefbf169e7881f7fe715102cf0d5dd0b78a197c88e16a0710"
Q_CENTER = (0.0, -37.0 / 60.0)
PROBES = (
    ("E8B_FULL_T_1_64", 1.0 / 64.0),
    ("E8B_FULL_T_1_16", 1.0 / 16.0),
    ("E8B_FULL_T_1_4", 1.0 / 4.0),
    ("E8B_FULL_T_1_2", 1.0 / 2.0),
    ("E8B_FULL_T_3_4", 3.0 / 4.0),
    ("E8B_FULL_T_1", 1.0),
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_result(value: dict[str, Any]) -> None:
    target = Path(os.environ["MEPHC_RESULT_PATH"])
    data = canonical(value)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)


def load_budget_counter() -> Any:
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_thin_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def load_bound_payload(bundle: dict[str, Any], dataset_id: str, manifest: str, key: str) -> dict[str, Any]:
    matches = [item for item in bundle.get("datasets", [])
               if isinstance(item, dict) and item.get("dataset_id") == dataset_id
               and item.get("manifest_sha256") == manifest and item.get("record_key_sha256") == key]
    require(len(matches) == 1, "INPUT_RECORD_BINDING_INVALID")
    record = matches[0]
    payload_name = record.get("payload_file")
    require(isinstance(payload_name, str) and Path(payload_name).name == payload_name, "INPUT_PAYLOAD_REFERENCE_INVALID")
    payload_path = Path(os.environ["MEPHC_INPUT_BUNDLE"]).parent / payload_name
    payload = payload_path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == record.get("payload_sha256"), "INPUT_PAYLOAD_HASH_INVALID")
    require(len(payload) == record.get("payload_size_bytes"), "INPUT_PAYLOAD_SIZE_INVALID")
    value = json.loads(payload.decode("utf-8"))
    require(isinstance(value, dict), "INPUT_PAYLOAD_SCHEMA_INVALID")
    return value


def worker(probe: str, t: float, marker: Path, fault_log: Path) -> int:
    with fault_log.open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        import meep as mp
        from meep import mpb
        import numpy as np

        from audit.e8b.e8b_geometry import all_states, solver_geometry

        geometry, lattice = solver_geometry(all_states()["0.0"])
        q = (Q_CENTER[0] * t, Q_CENTER[1] * t)
        reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(q[0], q[1], 0), lattice)
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
        solver.run_parity(mp.TM, False, mpb.fix_efield_phase)
        frequencies = np.asarray(solver.all_freqs)
        require(frequencies.ndim == 2 and frequencies.shape[0] >= 1 and frequencies.shape[1] == 6,
                "P15_FREQUENCY_SHAPE_INVALID")
        values = np.asarray(frequencies[0], dtype=float)
        require(values.shape == (6,) and np.all(np.isfinite(values)), "P15_FREQUENCY_FINITE_SIX_INVALID")
        marker.write_text(json.dumps({"probe_id": probe, "t": t, "success": True}, sort_keys=True), encoding="utf-8")
    return 0


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        return worker(sys.argv[2], float(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[4] + ".fault"))

    bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", ""))
    require(bundle_path.is_file(), "INPUT_BUNDLE_MISSING")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    require(bundle.get("schema") == "mephc-thin-input-bundle-v1", "INPUT_BUNDLE_SCHEMA_INVALID")
    require(bundle.get("work_order_id") == WORK_ORDER_ID, "INPUT_WORK_ORDER_MISMATCH")
    contract_sha = os.environ.get("MEPHC_SCIENCE_CONTRACT_SHA256")
    if contract_sha:
        require(bundle.get("contract_sha256") == contract_sha, "INPUT_CONTRACT_MISMATCH")
    p12 = load_bound_payload(bundle, P12_DATASET_ID, P12_MANIFEST, P12_KEY)
    p11 = load_bound_payload(bundle, P11_DATASET_ID, P11_MANIFEST, P11_KEY)
    p12_probe = next((item for item in p12.get("probe_results", [])
                      if isinstance(item, dict) and item.get("probe_id") == "E8B_FULL_TM_R64_Q0"), None)
    require(isinstance(p12_probe, dict) and p12_probe.get("success") is True, "P12_INPUT_RECORD_NOT_VERIFIED")
    require(p11.get("band_function_failure_class") == "HISTORICAL_E8B_RUN_PATH_NO_LONGER_REPRODUCES",
            "P11_INPUT_RECORD_NOT_VERIFIED")
    p11_probes = (p11.get("probe_a"), p11.get("probe_b"))
    require(all(isinstance(item, dict) and item.get("success") is False and item.get("return_code") == -11
                for item in p11_probes), "P11_INPUT_FAILURE_EVIDENCE_INVALID")

    BudgetCounter = load_budget_counter()
    counter = BudgetCounter(6, 6)
    outcomes: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mephc-p15-") as temporary:
        root = Path(temporary)
        for probe, t in PROBES:
            counter.consume_provider()
            counter.consume_solver()
            marker = root / f"{probe}.json"
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", probe, str(t), str(marker)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, check=False, timeout=3600,
            )
            outcome = {
                "probe_id": probe,
                "t": t,
                "public_q": [Q_CENTER[0] * t, Q_CENTER[1] * t],
                "return_code": completed.returncode,
                "sigsegv": completed.returncode == -11,
                "success": completed.returncode == 0 and marker.is_file(),
            }
            outcomes.append(outcome)

    successes = [item["success"] for item in outcomes]
    if all(successes):
        classification = "FULL_E8B_KPOINT_CONTINUATION_COMPLETED"
    elif not any(successes):
        classification = "E8B_KPOINT_CONTINUATION_FAILED_AT_ALL_PREDECLARED_POINTS"
    else:
        classification = "E8B_KPOINT_CONTINUATION_BOUNDARY_LOCALIZED"
    source_commit = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    write_result({
        "schema": "mephc-local-affine-p15-e8b-kpoint-continuation-v1",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        "p12_input_record_status": "VERIFIED",
        "p11_input_record_status": "VERIFIED",
        "p14_zero_execution_status": "VERIFIED_FROM_CONTRACT_INPUT",
        "native_invocation_count": 1,
        "provider_execution_count": 6,
        "solver_execution_count": 6,
        "diagnostic_worker_process_count": 6,
        "formal_dataset_record_count": 0,
        "retry_count": 0,
        "cache_reuse_count": 0,
        "classification": classification,
        "probe_results": outcomes,
        "status": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
