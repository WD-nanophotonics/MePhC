"""Decompose the current Native MPB failure into five predeclared factors."""
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
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P12-MPB-E8B-FACTOR-DECOMPOSITION-20260829-376"
BASE_SANDBOX_SHA = "7f03e92bacac95dcb869811fdc5a4c0f028c2a5c"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P11_TRACE_DATASET_ID = "a2e44227c43e3dabe425daae4350e9fe8f6987504069ffc14f86e276ea552663"
P11_TRACE_MANIFEST_SHA = "e1ae5ea5d3d6070a9912bf69acb2857857ead68241e032c01a6addde60f58726"
P11_FAILURE_CLASS = "HISTORICAL_E8B_RUN_PATH_NO_LONGER_REPRODUCES"
PROVIDER_SHA = "e83aa9768b53ad5e0f151636982e91a1193b269cf4e5baef1da1a0ca33965128"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
ENTRYPOINT = ROOT / "audit/local_affine/p12_mpb_e8b_factor_decomposition.py"
PROVIDER_PATH = ROOT / "mephc/local_affine_state_provider.py"
GRAPH_PATH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"
P11_SCRIPT = ROOT / "audit/local_affine/p11_run_parity_band_function_isolation.py"


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
    line = f"P12_STAGE|{probe}|{stage}|{event}\n".encode("ascii")
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
    path_value = getattr(module, "__file__", None)
    path = Path(path_value).resolve() if path_value else None
    return {
        "path": str(path) if path else None,
        "sha256": sha256_file(path) if path and path.is_file() else None,
    }


def runtime_identities(mp: Any, np: Any) -> dict[str, Any]:
    native = {}
    for name, module in sorted(sys.modules.items()):
        path_value = getattr(module, "__file__", None)
        if not path_value or not str(path_value).lower().endswith((".so", ".pyd", ".dll")):
            continue
        path = Path(path_value).resolve()
        if path.is_file():
            native[name] = {"path": str(path), "sha256": sha256_file(path)}
    return {
        "python": sys.version,
        "meep": module_identity(mp),
        "numpy": {"version": str(np.__version__), **module_identity(np)},
        "loaded_native_extensions": native,
    }


def finite_six(values: Any, np: Any) -> bool:
    array = np.asarray(values, dtype=float)
    return bool(array.shape == (6,) and np.all(np.isfinite(array)))


def square_lattice(mp: Any) -> Any:
    return mp.Lattice(size=mp.Vector3(1, 1))


def e8b_lattice(mp: Any) -> Any:
    from audit.e8b.e8b_geometry import all_states, solver_geometry

    state = all_states()["0.0"]
    _, lattice = solver_geometry(state)
    return lattice


def worker(probe: str, marker_path: Path, fault_path: Path) -> int:
    with fault_path.open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        write_marker(marker_path, probe, "MEEP_IMPORT", "ENTER")
        import meep as mp
        from meep import mpb
        import numpy as np

        write_json(marker_path.with_suffix(".runtime.json"), runtime_identities(mp, np))
        write_marker(marker_path, probe, "MEEP_IMPORT", "EXIT")

        q = (0.0, -37.0 / 60.0) if probe != "E8B_FULL_TM_R64_Q0" else (0.0, 0.0)
        write_marker(marker_path, probe, "GEOMETRY_AND_LATTICE_CONSTRUCTION", "ENTER")
        if probe == "E9_RUNTIME_CONTROL_TE_R96_K0":
            geometry = None
            lattice = None
        elif probe in {"SQUARE_VACUUM_TE_R64_QCENTER", "SQUARE_VACUUM_TM_R64_QCENTER"}:
            geometry = []
            lattice = square_lattice(mp)
        else:
            from audit.e8b.e8b_geometry import all_states, solver_geometry

            geometry, lattice = solver_geometry(all_states()["0.0"])
            if probe == "E8B_LATTICE_VACUUM_TM_R64_QCENTER":
                geometry = []
        write_marker(marker_path, probe, "GEOMETRY_AND_LATTICE_CONSTRUCTION", "EXIT")

        if probe == "E9_RUNTIME_CONTROL_TE_R96_K0":
            runtime = load_module("_mephc_p12_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
            write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "ENTER")
            write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "ENTER")
            provider = runtime._build_live_provider("R96")
            write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "EXIT")
            write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "EXIT")
            write_marker(marker_path, probe, "RUN_PARITY_OR_PROVIDER_SOLVE", "ENTER")
            snapshot = provider.solve((0.0, 0.0))
            write_marker(marker_path, probe, "RUN_PARITY_OR_PROVIDER_SOLVE", "EXIT")
            write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "ENTER")
            require(finite_six(snapshot.frequencies, np), "P12_RUNTIME_CONTROL_FREQUENCIES_INVALID")
            write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "EXIT")
        else:
            polarization = mp.TE if probe == "SQUARE_VACUUM_TE_R64_QCENTER" else mp.TM
            write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "ENTER")
            reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(q[0], q[1], 0), lattice)
            write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "EXIT")
            write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "ENTER")
            solver = mpb.ModeSolver(
                geometry=geometry, geometry_lattice=lattice, k_points=[reciprocal],
                resolution=64, num_bands=6, default_material=mp.air,
                tolerance=1e-7, deterministic=True, mesh_size=3,
            )
            write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "EXIT")
            write_marker(marker_path, probe, "RUN_PARITY_OR_PROVIDER_SOLVE", "ENTER")
            solver.run_parity(polarization, False, mpb.fix_efield_phase)
            write_marker(marker_path, probe, "RUN_PARITY_OR_PROVIDER_SOLVE", "EXIT")
            write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "ENTER")
            frequencies = np.asarray(solver.all_freqs)
            require(frequencies.ndim == 2 and frequencies.shape[0] >= 1 and finite_six(frequencies[0], np),
                    "P12_FREQUENCIES_INVALID")
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


def probe_result(probe: str, completed: subprocess.CompletedProcess[bytes], marker_path: Path) -> dict[str, Any]:
    markers = marker_path.read_text(encoding="utf-8").splitlines() if marker_path.is_file() else []
    run_ok = any("|RUN_PARITY_OR_PROVIDER_SOLVE|EXIT" in line for line in markers)
    freq_ok = any("|FREQUENCY_EXTRACTION|EXIT" in line for line in markers)
    complete_ok = any("|COMPLETE|EXIT" in line for line in markers)
    return {
        "probe_id": probe,
        "return_code": completed.returncode,
        "sigsegv": completed.returncode == -11,
        "last_stage_marker": markers[-1] if markers else "NONE",
        "run_parity_or_provider_solve_success": run_ok,
        "frequency_extraction_success": freq_ok,
        "finite_six_frequencies": freq_ok,
        "success": completed.returncode == 0 and run_ok and freq_ok and complete_ok,
        "top_faulthandler_frame": fault_frame(Path(str(marker_path) + ".faulthandler.log")),
        "markers": markers,
        "stdout_sha256": sha256_bytes(completed.stdout or b""),
        "stderr_sha256": sha256_bytes(completed.stderr or b""),
        "runtime_identities": json.loads(marker_path.with_suffix(".runtime.json").read_text(encoding="utf-8"))
        if marker_path.with_suffix(".runtime.json").is_file() else {},
    }


def classify(outcomes: list[dict[str, Any]]) -> tuple[str, str, str]:
    a, b, c, d, e = (item["success"] for item in outcomes)
    if not a:
        return ("CURRENT_NATIVE_E9_RUNTIME_CONTROL_FAILURE", "LOCALIZED_NOT_ESTABLISHED",
                "RECONCILE_CURRENT_MEEP_MPB_NATIVE_ENVIRONMENT_AGAINST_THE_CERTIFIED_RUNTIME_SMOKE_ENVIRONMENT")
    if not b:
        return ("R64_OR_NONZERO_Q_OR_MINIMAL_RUN_CONTEXT_FAILURE", "LOCALIZED_NOT_ESTABLISHED",
                "SQUARE_VACUUM_R64_K0_VS_QCENTER_AND_R96_VS_R64_SPLIT")
    if not c:
        return ("TM_POLARIZATION_SPECIFIC_CURRENT_NATIVE_FAILURE", "LOCALIZED_NOT_ESTABLISHED",
                "TM_NATIVE_PARITY_RUNTIME_DIAGNOSIS_IN_ORTHOGONAL_VACUUM_CONTROL")
    if not d:
        return ("NONORTHOGONAL_E8B_LATTICE_SPECIFIC_FAILURE", "LOCALIZED_NOT_ESTABLISHED",
                "E8B_LATTICE_BASIS_REPRESENTATION_AND_MPB_GRID_INITIALIZATION")
    if not e:
        return ("E8B_DIELECTRIC_GEOMETRY_SPECIFIC_FAILURE", "LOCALIZED_NOT_ESTABLISHED",
                "ONE_CYLINDER_VS_TWO_CYLINDER_E8B_GEOMETRY_DECOMPOSITION")
    return ("E8B_GEOMETRY_BY_NONZERO_Q_INTERACTION_FAILURE", "LOCALIZED_NOT_ESTABLISHED",
            "FULL_E8B_GEOMETRY_K0_TO_QCENTER_KPOINT_CONTINUATION_WITH_PREDECLARED_BOUNDED_POINTS")


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--p12-worker":
        return worker(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[3] + ".faulthandler.log"))

    execution_source = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    require(len(execution_source) == 40 and all(c in "0123456789abcdef" for c in execution_source),
            "SCIENCE_EXECUTION_IDENTITY_INVALID")
    require(execution_source == BASE_SANDBOX_SHA and git_head() == BASE_SANDBOX_SHA,
            "P12_SOURCE_IDENTITY_MISMATCH")
    counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters_path.name, "P12_COUNTER_PATH_MISSING")
    require(sha256_file(PROVIDER_PATH) == PROVIDER_SHA, "P12_PROVIDER_HASH_MISMATCH")
    require(sha256_file(GRAPH_PATH) == GRAPH_SHA, "P12_GRAPH_HASH_MISMATCH")
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    states = [(item["state_id"], item["role"], item["public_q"], item["s"]) for item in graph["states"]]
    require(len(states) == 13 and sha256_bytes(canonical(states)) == STATE_SET_SHA, "P12_STATE_SET_IDENTITY_MISMATCH")

    runtime = load_module("_mephc_p12_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_p12_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    require(scientific_job.runtime_hash(ROOT) == RUNTIME_SHA, "P12_RUNTIME_HASH_MISMATCH")
    state_root = runtime._trusted_science_state_root()
    verified = scientific_job.verify_dataset(state_root, P11_TRACE_DATASET_ID)
    require(verified["manifest_sha256"] == P11_TRACE_MANIFEST_SHA and verified["record_count"] == 1,
            "P11_TRACE_INPUT_INTEGRITY_MISMATCH")

    namespace = {
        "project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID,
        "source_commit": execution_source, "entrypoint_sha256": sha256_file(ENTRYPOINT),
        "trace_type": "p12_mpb_e8b_factor_decomposition", "p11_trace_dataset_id": P11_TRACE_DATASET_ID,
    }
    trace_store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    require(not trace_store.root.exists(), "P12_TRACE_NAMESPACE_ALREADY_EXISTS")
    trace_dir = state_root / "diagnostic-traces" / sha256_bytes(canonical(namespace))
    trace_dir.mkdir(parents=True, exist_ok=False)

    counter = scientific_job.BudgetCounter(5, 5)
    probes = (
        "E9_RUNTIME_CONTROL_TE_R96_K0", "SQUARE_VACUUM_TE_R64_QCENTER",
        "SQUARE_VACUUM_TM_R64_QCENTER", "E8B_LATTICE_VACUUM_TM_R64_QCENTER", "E8B_FULL_TM_R64_Q0",
    )
    outcomes = []
    for probe in probes:
        counter.consume_provider()
        counter.consume_solver()
        marker_path = trace_dir / f"{probe}.markers.log"
        completed = subprocess.run(
            [sys.executable, str(ENTRYPOINT), "--p12-worker", probe, str(marker_path)],
            cwd=ROOT, capture_output=True, check=False, timeout=3600,
        )
        outcomes.append(probe_result(probe, completed, marker_path))

    failure_class, root_cause, next_diagnosis = classify(outcomes)
    payload = canonical({
        "schema": "mephc-local-affine-p12-mpb-factor-diagnostic-trace-v1",
        "work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
        "p11_trace_dataset_id": P11_TRACE_DATASET_ID, "p11_trace_manifest_sha256": P11_TRACE_MANIFEST_SHA,
        "p11_failure_class": P11_FAILURE_CLASS, "probe_results": outcomes,
        "mpb_factor_failure_class": failure_class, "root_cause_status": root_cause,
        "next_required_diagnosis": next_diagnosis, "diagnostic_trace_not_reusable_for_science": True,
        "formal_local_affine_dataset_record_count": 0,
    })
    trace_store.put(canonical({"work_order_id": WORK_ORDER_ID, "role": "five_predeclared_factor_probes"}), payload, {
        "work_order_id": WORK_ORDER_ID, "p11_trace_dataset_id": P11_TRACE_DATASET_ID,
        "p11_trace_manifest_sha256": P11_TRACE_MANIFEST_SHA, "probe_count": 5,
        "mpb_factor_failure_class": failure_class, "formal_local_affine_dataset_record_count": 0,
    })
    manifest = trace_store.finalize(1, {
        "work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
        "native_invocation_count": 1, "provider_execution_count": 5,
        "solver_execution_count": 5, "formal_local_affine_dataset_record_count": 0,
    })

    def field(prefix: str, key: str) -> Any:
        item = outcomes[probes.index(prefix)]
        return item[key]

    result = {
        "schema": "mephc-local-affine-p12-mpb-e8b-factor-decomposition-v1",
        "WORK_ORDER_ID": WORK_ORDER_ID, "BASE_SANDBOX_SHA": BASE_SANDBOX_SHA,
        "FINAL_SANDBOX_SHA": execution_source, "ORIGIN_SANDBOX_SHA": execution_source, "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS", "P11_TRACE_DATASET_ID": P11_TRACE_DATASET_ID,
        "P11_TRACE_MANIFEST_SHA256": P11_TRACE_MANIFEST_SHA, "P11_DIAGNOSIS_STATUS": "VERIFIED",
        "PROVIDER_MODULE_SHA256": PROVIDER_SHA, "REQUEST_GRAPH_SHA256": GRAPH_SHA,
        "SCIENTIFIC_STATE_SET_IDENTITY": STATE_SET_SHA, "SCIENCE_JOB_ID": counters_path.name.split(".", 1)[0],
        "SCIENCE_SOURCE_SHA": execution_source, "NATIVE_INVOCATION_COUNT": 1,
        "PROVIDER_EXECUTION_COUNT": 5, "SOLVER_EXECUTION_COUNT": 5, "DIAGNOSTIC_WORKER_PROCESS_COUNT": 5,
        "CURRENT_RUNTIME_CONTROL_EXECUTED": True,
        "DIAGNOSTIC_TRACE_DATASET_ID": manifest["dataset_id"],
        "DIAGNOSTIC_TRACE_MANIFEST_SHA256": manifest["manifest_sha256"],
        "DIAGNOSTIC_TRACE_RECORD_COUNT": 1, "DIAGNOSTIC_TRACE_PERSISTED": True,
        "DIAGNOSTIC_TRACE_NOT_REUSABLE_FOR_SCIENCE": True, "FORMAL_LOCAL_AFFINE_DATASET_RECORD_COUNT": 0,
        "MPB_FACTOR_FAILURE_CLASS": failure_class, "ROOT_CAUSE_STATUS": root_cause,
        "NEXT_REQUIRED_DIAGNOSIS": next_diagnosis,
        "RETRY_COUNT": 0, "CACHE_REUSE_COUNT": 0,
        "LOCALAFFINE_P12_MPB_FACTOR_DECOMPOSITION_STATUS": "PASS",
        "NEXT_LIVE_SOLVER_AUTHORIZATION": False, "LIVE_RERUN_AUTHORIZED": False,
        "PIPELINE_HEALTH": "PIPELINE_REQUIRES_CORRECTIVE", "BLOCKED_BY_INFRASTRUCTURE": True,
        "SCIENTIFIC_WORK_MUST_STOP": True, "RETURN_TO_SUPERVISOR": True,
        "TERMINAL": "LOCALAFFINE_P12_MPB_E8B_FACTOR_DECOMPOSITION_COMPLETE",
    }
    for probe in probes:
        label = {"E9_RUNTIME_CONTROL_TE_R96_K0": "A", "SQUARE_VACUUM_TE_R64_QCENTER": "B",
                 "SQUARE_VACUUM_TM_R64_QCENTER": "C", "E8B_LATTICE_VACUUM_TM_R64_QCENTER": "D",
                 "E8B_FULL_TM_R64_Q0": "E"}[probe]
        result[f"PROBE_{label}_RETURN_CODE"] = field(probe, "return_code")
        result[f"PROBE_{label}_SIGSEGV"] = field(probe, "sigsegv")
        result[f"PROBE_{label}_SUCCESS"] = field(probe, "success")
        result[f"PROBE_{label}_LAST_STAGE_MARKER"] = field(probe, "last_stage_marker")
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
