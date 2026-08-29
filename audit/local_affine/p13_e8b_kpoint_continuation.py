"""Probe the exact E8B geometry along a fixed, predeclared k-point continuation."""
from __future__ import annotations

import faulthandler
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P13-E8B-KPOINT-CONTINUATION-20260829-377"
BASE_SANDBOX_SHA = "2bf12b383e54c3d478d00575cbd4f37de8dcf78a"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P12_TRACE_DATASET_ID = "3cb72daa2a2c2f72948982449712bc8ae5569374dbaf4161c9f81b7d3dc911bd"
P12_TRACE_MANIFEST_SHA = "f7db9e9a2bccb66c42f4e97ffaa89548c7563990ad36aeb40cb2533906dfe947"
P12_ENTRYPOINT_SHA = "5de4b5b725e99997af6d124592abfdce91d68b77d01b1dc490638538aca8635f"
P11_TRACE_DATASET_ID = "a2e44227c43e3dabe425daae4350e9fe8f6987504069ffc14f86e276ea552663"
P11_TRACE_MANIFEST_SHA = "e1ae5ea5d3d6070a9912bf69acb2857857ead68241e032c01a6addde60f58726"
P11_ENTRYPOINT_SHA = "85eac31d77dbb540798ad8bd33ab2b547f49121007a90601c282f4a02974e0a7"
PROVIDER_SHA = "e83aa9768b53ad5e0f151636982e91a1193b269cf4e5baef1da1a0ca33965128"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
ENTRYPOINT = ROOT / "audit/local_affine/p13_e8b_kpoint_continuation.py"
PROVIDER_PATH = ROOT / "mephc/local_affine_state_provider.py"
GRAPH_PATH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"

PROBES = (
    ("E8B_FULL_T_1_64", 1.0 / 64.0),
    ("E8B_FULL_T_1_16", 1.0 / 16.0),
    ("E8B_FULL_T_1_4", 1.0 / 4.0),
    ("E8B_FULL_T_1_2", 1.0 / 2.0),
    ("E8B_FULL_T_3_4", 3.0 / 4.0),
    ("E8B_FULL_T_1", 1.0),
)
QCENTER = (0.0, -37.0 / 60.0)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_marker(path: Path, probe: str, stage: str, event: str) -> None:
    line = f"P13_STAGE|{probe}|{stage}|{event}\n".encode("ascii")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    sys.stdout.write(line.decode("ascii"))
    sys.stdout.flush()


def write_json(path: Path, value: Any) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def module_identity(module: Any) -> dict[str, Any]:
    value = getattr(module, "__file__", None)
    path = Path(value).resolve() if value else None
    return {"path": str(path) if path else None, "sha256": sha256_file(path) if path and path.is_file() else None}


def runtime_identities(mp: Any, np: Any) -> dict[str, Any]:
    native = {}
    for name, module in sorted(sys.modules.items()):
        value = getattr(module, "__file__", None)
        if not value or not str(value).lower().endswith((".so", ".pyd", ".dll")):
            continue
        path = Path(value).resolve()
        if path.is_file():
            native[name] = {"path": str(path), "sha256": sha256_file(path)}
    return {"python": sys.version, "meep": module_identity(mp),
            "numpy": {"version": str(np.__version__), **module_identity(np)},
            "loaded_native_extensions": native}


def worker(probe: str, t: float, marker_path: Path, fault_path: Path) -> int:
    with fault_path.open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        write_marker(marker_path, probe, "MEEP_IMPORT", "ENTER")
        import meep as mp
        from meep import mpb
        import numpy as np

        write_json(marker_path.with_suffix(".runtime.json"), runtime_identities(mp, np))
        write_marker(marker_path, probe, "MEEP_IMPORT", "EXIT")
        q = (QCENTER[0] * t, QCENTER[1] * t)
        write_marker(marker_path, probe, "GEOMETRY_AND_LATTICE_CONSTRUCTION", "ENTER")
        from audit.e8b.e8b_geometry import all_states, solver_geometry

        geometry, lattice = solver_geometry(all_states()["0.0"])
        write_marker(marker_path, probe, "GEOMETRY_AND_LATTICE_CONSTRUCTION", "EXIT")
        write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "ENTER")
        reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(q[0], q[1], 0), lattice)
        reciprocal_tuple = [float(reciprocal.x), float(reciprocal.y), float(reciprocal.z)]
        write_json(marker_path.with_suffix(".probe.json"), {"t": t, "public_q": list(q), "reciprocal_k": reciprocal_tuple})
        write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "EXIT")
        write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "ENTER")
        solver = mpb.ModeSolver(
            geometry=geometry, geometry_lattice=lattice, k_points=[reciprocal],
            resolution=64, num_bands=6, default_material=mp.air,
            tolerance=1e-7, deterministic=True, mesh_size=3,
        )
        write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "EXIT")
        write_marker(marker_path, probe, "RUN_PARITY", "ENTER")
        solver.run_parity(mp.TM, False, mpb.fix_efield_phase)
        write_marker(marker_path, probe, "RUN_PARITY", "EXIT")
        write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "ENTER")
        frequencies = np.asarray(solver.all_freqs)
        require(frequencies.ndim == 2 and frequencies.shape[0] >= 1 and frequencies.shape[1] == 6,
                "P13_FREQUENCY_SHAPE_INVALID")
        values = np.asarray(frequencies[0], dtype=float)
        require(values.shape == (6,) and np.all(np.isfinite(values)), "P13_FREQUENCY_FINITE_SIX_INVALID")
        write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "EXIT")
        write_marker(marker_path, probe, "COMPLETE", "ENTER")
        write_marker(marker_path, probe, "COMPLETE", "EXIT")
    return 0


def fault_frame(path: Path) -> str:
    if not path.is_file():
        return "UNKNOWN_NO_FAULTHANDLER_FRAME"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Fatal Python error" in line or "File \"" in line:
            return line.strip()
    return "UNKNOWN_NO_FAULTHANDLER_FRAME"


def probe_result(probe: str, t: float, completed: subprocess.CompletedProcess[bytes], marker_path: Path) -> dict[str, Any]:
    markers = marker_path.read_text(encoding="utf-8").splitlines() if marker_path.is_file() else []
    metadata_path = marker_path.with_suffix(".probe.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {
        "t": t, "public_q": [QCENTER[0] * t, QCENTER[1] * t], "reciprocal_k": None,
    }
    run_ok = any("|RUN_PARITY|EXIT" in line for line in markers)
    freq_ok = any("|FREQUENCY_EXTRACTION|EXIT" in line for line in markers)
    return {
        "probe_id": probe, "t": t, "public_q": metadata["public_q"], "reciprocal_k": metadata["reciprocal_k"],
        "return_code": completed.returncode, "sigsegv": completed.returncode == -11,
        "success": completed.returncode == 0 and run_ok and freq_ok,
        "frequency_extraction_success": freq_ok, "finite_six_frequencies": freq_ok,
        "last_stage_marker": markers[-1] if markers else "NONE",
        "top_faulthandler_frame": fault_frame(Path(str(marker_path) + ".faulthandler.log")),
        "markers": markers, "stdout_sha256": sha256_bytes(completed.stdout or b""),
        "stderr_sha256": sha256_bytes(completed.stderr or b""),
        "runtime_identities": json.loads(marker_path.with_suffix(".runtime.json").read_text(encoding="utf-8"))
        if marker_path.with_suffix(".runtime.json").is_file() else {},
    }


def classify(outcomes: list[dict[str, Any]]) -> tuple[str, str | float | None, str | float | None, str]:
    success = [bool(item["success"]) for item in outcomes]
    if not success[0] and not any(success[1:]):
        return ("NONZERO_Q_IMMEDIATE_OR_THRESHOLD_BELOW_T_1_64", 0, 1.0 / 64.0,
                "SUBDIVIDE_T_IN_0_TO_1_64_WITH_LOG_SPACED_PREDECLARED_POINTS_AND_COMPARE_RECIPROCAL_K_LIMIT")
    if all(success[:5]) and not success[5]:
        return ("QCENTER_ENDPOINT_OR_NEAR_ENDPOINT_SPECIFIC_FAILURE", 3.0 / 4.0, 1.0,
                "PREDECLARED_NEAR_ENDPOINT_CONTINUATION_T_7_8_15_16_31_32_AND_1")
    if success[5]:
        return ("NONDETERMINISTIC_OR_ENVIRONMENT_SENSITIVE_FULL_STATE_FAILURE", None, None,
                "RECONCILE_P11_AND_P13_RUNTIME_AND_LOADED_NATIVE_LIBRARY_IDENTITIES_BEFORE_MORE_MPB_SOLVES")
    for index in range(len(success)):
        if all(success[:index]) and not any(success[index:]):
            return ("MONOTONE_K_MAGNITUDE_FAILURE_THRESHOLD_BRACKETED", 0 if index == 0 else outcomes[index - 1]["t"],
                    outcomes[index]["t"], "BISECT_ONLY_THE_BRACKET_BETWEEN_LAST_CONFIRMED_SUCCESS_T_AND_FIRST_CONFIRMED_FAILURE_T")
    return ("NONMONOTONIC_K_DEPENDENT_NATIVE_FAILURE", None, None,
            "REPRODUCE_ONLY_THE_PREDECLARED_BOUNDARY_SUCCESS_AND_FAILURE_POINTS_IN_SEPARATE_FRESH_PROCESSES_AFTER_RUNTIME_IDENTITY_RECONCILIATION")


def verify_trace(scientific_job: Any, state_root: Path, dataset_id: str, manifest_sha: str,
                 namespace: dict[str, Any], key: bytes) -> dict[str, Any]:
    verified = scientific_job.verify_dataset(state_root, dataset_id)
    require(verified["manifest_sha256"] == manifest_sha and verified["record_count"] == 1,
            "HISTORICAL_TRACE_MANIFEST_MISMATCH")
    store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    payload, _ = store.get(key)
    return json.loads(payload.decode("utf-8"))


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--p13-worker":
        return worker(sys.argv[2], float(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[4] + ".faulthandler.log"))

    execution_source = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    require(len(execution_source) == 40 and all(c in "0123456789abcdef" for c in execution_source),
            "SCIENCE_EXECUTION_IDENTITY_INVALID")
    require(git_head() == execution_source, "P13_SOURCE_IDENTITY_MISMATCH")
    counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters_path.name, "P13_COUNTER_PATH_MISSING")
    require(sha256_file(PROVIDER_PATH) == PROVIDER_SHA, "P13_PROVIDER_HASH_MISMATCH")
    require(sha256_file(GRAPH_PATH) == GRAPH_SHA, "P13_GRAPH_HASH_MISMATCH")
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    states = [(item["state_id"], item["role"], item["public_q"], item["s"]) for item in graph["states"]]
    require(len(states) == 13 and sha256_bytes(canonical(states)) == STATE_SET_SHA, "P13_STATE_SET_IDENTITY_MISMATCH")

    runtime = load_module("_mephc_p13_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_p13_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    require(scientific_job.runtime_hash(ROOT) == RUNTIME_SHA, "P13_RUNTIME_HASH_MISMATCH")
    state_root = runtime._trusted_science_state_root()

    p12_namespace = {"project_id": "MEPHC", "science_contract_id": "MEPHC-LOCALAFFINE-P12-MPB-E8B-FACTOR-DECOMPOSITION-20260829-376",
                     "source_commit": "2bf12b383e54c3d478d00575cbd4f37de8dcf78a", "entrypoint_sha256": P12_ENTRYPOINT_SHA,
                     "trace_type": "p12_mpb_e8b_factor_decomposition", "p11_trace_dataset_id": P11_TRACE_DATASET_ID}
    p12_payload = verify_trace(scientific_job, state_root, P12_TRACE_DATASET_ID, P12_TRACE_MANIFEST_SHA,
                               p12_namespace, canonical({"work_order_id": p12_namespace["science_contract_id"],
                                                         "role": "five_predeclared_factor_probes"}))
    p12_probe = next((item for item in p12_payload["probe_results"] if item["probe_id"] == "E8B_FULL_TM_R64_Q0"), None)
    require(isinstance(p12_probe, dict) and p12_probe.get("success") is True, "P12_Q0_ENDPOINT_EVIDENCE_INVALID")

    p11_namespace = {"project_id": "MEPHC", "science_contract_id": "MEPHC-LOCALAFFINE-P11-RUN-PARITY-BAND-FUNCTION-ISOLATION-20260829-375",
                     "source_commit": "7f03e92bacac95dcb869811fdc5a4c0f028c2a5c", "entrypoint_sha256": P11_ENTRYPOINT_SHA,
                     "trace_type": "p11_run_parity_band_function_isolation", "p9_trace_dataset_id": "386987b790d65f2b5b82a41c4903607ca1addfb137af27e6b379bf3d26f10e4f"}
    p11_payload = verify_trace(scientific_job, state_root, P11_TRACE_DATASET_ID, P11_TRACE_MANIFEST_SHA,
                               p11_namespace, canonical({"work_order_id": p11_namespace["science_contract_id"],
                                                         "role": "two_predeclared_probes"}))
    require(p11_payload.get("band_function_failure_class") == "HISTORICAL_E8B_RUN_PATH_NO_LONGER_REPRODUCES",
            "P11_ENDPOINT_FAILURE_CLASS_INVALID")
    require(all(item.get("success") is False and item.get("return_code") == -11
                for item in (p11_payload.get("probe_a", {}), p11_payload.get("probe_b", {}))),
            "P11_ENDPOINT_FAILURE_EVIDENCE_INVALID")

    namespace = {"project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID, "source_commit": execution_source,
                 "entrypoint_sha256": sha256_file(ENTRYPOINT), "trace_type": "p13_e8b_kpoint_continuation",
                 "p12_trace_dataset_id": P12_TRACE_DATASET_ID}
    trace_store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    require(not trace_store.root.exists(), "P13_TRACE_NAMESPACE_ALREADY_EXISTS")
    trace_dir = state_root / "diagnostic-traces" / sha256_bytes(canonical(namespace))
    trace_dir.mkdir(parents=True, exist_ok=False)
    counter = scientific_job.BudgetCounter(6, 6)
    outcomes = []
    for probe, t in PROBES:
        counter.consume_provider()
        counter.consume_solver()
        marker_path = trace_dir / f"{probe}.markers.log"
        completed = subprocess.run([sys.executable, str(ENTRYPOINT), "--p13-worker", probe, str(t), str(marker_path)],
                                   cwd=ROOT, capture_output=True, check=False, timeout=3600)
        outcomes.append(probe_result(probe, t, completed, marker_path))
    failure_class, last_success, first_failure, next_diagnosis = classify(outcomes)
    payload = canonical({"schema": "mephc-local-affine-p13-e8b-kpoint-continuation-diagnostic-trace-v1",
                         "work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
                         "p12_trace_dataset_id": P12_TRACE_DATASET_ID, "p12_trace_manifest_sha256": P12_TRACE_MANIFEST_SHA,
                         "p11_endpoint_verified": True, "p12_endpoint_verified": True, "probe_results": outcomes,
                         "kpoint_continuation_failure_class": failure_class, "root_cause_status": "LOCALIZED_NOT_ESTABLISHED",
                         "next_required_diagnosis": next_diagnosis, "diagnostic_trace_not_reusable_for_science": True,
                         "formal_local_affine_dataset_record_count": 0})
    trace_store.put(canonical({"work_order_id": WORK_ORDER_ID, "role": "six_predeclared_kpoint_probes"}), payload,
                    {"work_order_id": WORK_ORDER_ID, "p12_trace_dataset_id": P12_TRACE_DATASET_ID,
                     "p12_trace_manifest_sha256": P12_TRACE_MANIFEST_SHA, "probe_count": 6,
                     "kpoint_continuation_failure_class": failure_class, "formal_local_affine_dataset_record_count": 0})
    manifest = trace_store.finalize(1, {"work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
                                       "native_invocation_count": 1, "provider_execution_count": 6,
                                       "solver_execution_count": 6, "formal_local_affine_dataset_record_count": 0})

    result = {"schema": "mephc-local-affine-p13-e8b-kpoint-continuation-v1", "WORK_ORDER_ID": WORK_ORDER_ID,
              "BASE_SANDBOX_SHA": BASE_SANDBOX_SHA, "FINAL_SANDBOX_SHA": execution_source,
              "ORIGIN_SANDBOX_SHA": execution_source, "MAIN_SHA": MAIN_SHA, "MACHINE_CONTRACT_STATUS": "PASS",
              "P12_TRACE_DATASET_ID": P12_TRACE_DATASET_ID, "P12_TRACE_MANIFEST_SHA256": P12_TRACE_MANIFEST_SHA,
              "PROVIDER_MODULE_SHA256": PROVIDER_SHA, "REQUEST_GRAPH_SHA256": GRAPH_SHA,
              "SCIENTIFIC_STATE_SET_IDENTITY": STATE_SET_SHA, "SCIENCE_JOB_ID": counters_path.name.split(".", 1)[0],
              "SCIENCE_SOURCE_SHA": execution_source, "NATIVE_INVOCATION_COUNT": 1,
              "PROVIDER_EXECUTION_COUNT": 6, "SOLVER_EXECUTION_COUNT": 6, "DIAGNOSTIC_WORKER_PROCESS_COUNT": 6,
              "KPOINT_CONTINUATION_FAILURE_CLASS": failure_class, "ROOT_CAUSE_STATUS": "LOCALIZED_NOT_ESTABLISHED",
              "LAST_CONFIRMED_SUCCESS_T": last_success, "FIRST_CONFIRMED_FAILURE_T": first_failure,
              "NEXT_REQUIRED_DIAGNOSIS": next_diagnosis, "DIAGNOSTIC_TRACE_DATASET_ID": manifest["dataset_id"],
              "DIAGNOSTIC_TRACE_MANIFEST_SHA256": manifest["manifest_sha256"], "DIAGNOSTIC_TRACE_RECORD_COUNT": 1,
              "DIAGNOSTIC_TRACE_PERSISTED": True, "DIAGNOSTIC_TRACE_NOT_REUSABLE_FOR_SCIENCE": True,
              "FORMAL_LOCAL_AFFINE_DATASET_RECORD_COUNT": 0, "RETRY_COUNT": 0, "CACHE_REUSE_COUNT": 0,
              "LOCALAFFINE_P13_KPOINT_CONTINUATION_STATUS": "PASS", "P12_DIAGNOSIS_STATUS": "VERIFIED",
              "KPOINT_CONTINUATION_CLASSIFICATION_STATUS": "PASS", "NEXT_LIVE_SOLVER_AUTHORIZATION": False,
              "LIVE_RERUN_AUTHORIZED": False, "PIPELINE_HEALTH": "PIPELINE_REQUIRES_CORRECTIVE",
              "BLOCKED_BY_INFRASTRUCTURE": True, "SCIENTIFIC_WORK_MUST_STOP": True, "RETURN_TO_SUPERVISOR": True,
              "TERMINAL": "LOCALAFFINE_P13_E8B_KPOINT_CONTINUATION_COMPLETE"}
    for index, item in enumerate(outcomes, 1):
        result.update({f"PROBE_{index}_T": item["t"], f"PROBE_{index}_PUBLIC_Q": item["public_q"],
                       f"PROBE_{index}_RECIPROCAL_K": item["reciprocal_k"], f"PROBE_{index}_RETURN_CODE": item["return_code"],
                       f"PROBE_{index}_SIGSEGV": item["sigsegv"], f"PROBE_{index}_SUCCESS": item["success"],
                       f"PROBE_{index}_LAST_STAGE_MARKER": item["last_stage_marker"],
                       f"PROBE_{index}_FREQUENCY_EXTRACTION_SUCCESS": item["frequency_extraction_success"],
                       f"PROBE_{index}_FINITE_SIX_FREQUENCIES": item["finite_six_frequencies"],
                       f"PROBE_{index}_TOP_FAULTHANDLER_FRAME": item["top_faulthandler_frame"]})
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
