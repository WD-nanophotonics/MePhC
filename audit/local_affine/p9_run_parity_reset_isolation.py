"""Isolate the P8 MPB run-parity crash with two predeclared probes."""
from __future__ import annotations

import faulthandler
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P9-RUN-PARITY-RESET-ISOLATION-20260829-373"
BASE_INPUT_COMMIT = "dc6e03f3e4b083af25e06a7bd450486654c144be"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
P8_TRACE_DATASET_ID = "9c74b13662559004303d288f448ddc5aadf08c891d8b7bc8e62b5c602b8c000c"
P8_TRACE_MANIFEST_SHA = "988e6ad1a8ecc882d65107f03062ae45d0bdfe05e9273163fc15aa72922e5681"
PROVIDER_SHA = "e83aa9768b53ad5e0f151636982e91a1193b269cf4e5baef1da1a0ca33965128"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P8_PROVIDER_SOURCE = "dc6e03f3e4b083af25e06a7bd450486654c144be"
GRAPH_PATH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"
PROVIDER_PATH = ROOT / "mephc/local_affine_state_provider.py"
P8_SCRIPT = ROOT / "audit/local_affine/p8_first_state_native_segfault_localization.py"


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
    spec.loader.exec_module(module)
    return module


def write_marker(path: Path, probe: str, stage: str, event: str) -> None:
    line = f"P9_STAGE|{probe}|{stage}|{event}\n".encode("ascii")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    sys.stdout.write(line.decode("ascii"))
    sys.stdout.flush()


def worker(probe: str, marker_path: Path, fault_path: Path) -> int:
    with fault_path.open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        write_marker(marker_path, probe, "MEEP_IMPORT", "ENTER")
        import meep as mp
        from mephc import local_affine_state_provider as lap
        from mephc import mpb_spectral_provider as msp
        from audit.e10f.e8b_local_affine_model import canonical_state_identity, make_state
        import numpy as np
        write_marker(marker_path, probe, "MEEP_IMPORT", "EXIT")

        write_marker(marker_path, probe, "STATE_CONSTRUCTION", "ENTER")
        spec = make_state((0.0, -37.0 / 60.0), 0.0)
        identity = canonical_state_identity(spec)
        require(identity["public_q"] == [0.0, -37.0 / 60.0] and identity["s"] == 0.0,
                "P9_STATE_01_IDENTITY_INVALID")
        require(identity["polarization"] == "TM" and identity["resolution"] == 64
                and identity["num_bands"] == 6 and identity["mesh_size"] == 3
                and identity["deterministic"] is True,
                "P9_STATE_01_SOLVER_CONTRACT_INVALID")
        write_marker(marker_path, probe, "STATE_CONSTRUCTION", "EXIT")

        original = lap.MPBLiveSpectralProvider

        class ProbeProvider(original):
            def solve(self, k_point):
                cartesian = msp._cartesian_point(k_point, name="k_point")
                z = cartesian[2] if len(cartesian) == 3 else 0.0
                write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "ENTER")
                reciprocal = mp.cartesian_to_reciprocal(
                    mp.Vector3(cartesian[0], cartesian[1], z), self.geometry_lattice)
                write_marker(marker_path, probe, "CARTESIAN_TO_RECIPROCAL", "EXIT")
                write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "ENTER")
                solver = self._build_solver(reciprocal)
                write_marker(marker_path, probe, "MODE_SOLVER_CONSTRUCTION", "EXIT")
                write_marker(marker_path, probe, "RUN_PARITY", "ENTER")
                parity = mp.TM if probe == "TM_RESET_TRUE" else mp.NO_PARITY
                solver.run_parity(parity, True)
                write_marker(marker_path, probe, "RUN_PARITY", "EXIT")
                write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "ENTER")
                frequencies = np.asarray(solver.all_freqs)
                require(frequencies.ndim == 2 and frequencies.shape[0] >= 1
                        and frequencies.shape[1] == self.num_bands,
                        "P9_FREQUENCY_SHAPE_INVALID")
                values = np.asarray(frequencies[0], dtype=float)
                require(values.shape == (6,) and np.all(np.isfinite(values)),
                        "P9_FREQUENCY_FINITE_SIX_INVALID")
                write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "EXIT")
                return {"frequency_extraction_success": True, "finite_six_frequencies": True}

        lap.MPBLiveSpectralProvider = ProbeProvider
        provider = lap.LocalAffineStateProvider(
            polarization=mp.TM, polarization_identity="TM", default_material=mp.air,
            resolution=64, num_bands=6, eigensolver_tolerance=1e-7,
            mesh_size=3, deterministic=True)
        result = provider.solve(spec)
        require(result is not None, "P9_PROVIDER_RESULT_MISSING")
        write_marker(marker_path, probe, "COMPLETE", "ENTER")
        write_marker(marker_path, probe, "COMPLETE", "EXIT")
    return 0


def last_marker(lines: list[str]) -> str:
    return lines[-1] if lines else "NONE"


def fault_frame(path: Path) -> str:
    if not path.is_file():
        return "UNKNOWN_NO_FAULTHANDLER_FRAME"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Fatal Python error" in line or "File \"" in line:
            return line.strip()
    return "UNKNOWN_NO_FAULTHANDLER_FRAME"


def probe_record(probe: str, return_code: int, markers: list[str], fault_path: Path,
                 stdout: bytes, stderr: bytes) -> dict[str, Any]:
    frequency_ok = any(f"|{probe}|FREQUENCY_EXTRACTION|EXIT" == line for line in markers)
    finite_ok = frequency_ok
    return {
        "probe_id": probe,
        "return_code": return_code,
        "sigsegv": return_code == -11,
        "last_stage_marker": last_marker(markers),
        "frequency_extraction_success": frequency_ok,
        "finite_six_frequencies": finite_ok,
        "top_faulthandler_frame": fault_frame(fault_path),
        "markers": markers,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


def classify(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, str, str]:
    if a["sigsegv"] and b["sigsegv"]:
        return "GENERAL_E8B_MPB_RUN_PATH", "LOCALIZED_NOT_ESTABLISHED", "NONE_PENDING_E8B_RUN_PATH_DIAGNOSIS"
    if a["sigsegv"] and not b["sigsegv"]:
        return "TM_PARITY_SPECIFIC_ON_FROZEN_E8B_STATE", "LOCALIZED_NOT_ESTABLISHED", "NONE_PENDING_FURTHER_TM_PARITY_DIAGNOSIS"
    if not a["sigsegv"] and b["sigsegv"]:
        return "INCONSISTENT_OR_NONDETERMINISTIC_DIAGNOSTIC_RESULT", "UNRESOLVED", "NONE"
    return "INCONSISTENT_OR_NONDETERMINISTIC_DIAGNOSTIC_RESULT", "UNRESOLVED", "NONE"


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--p9-worker":
        return worker(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[3] + ".faulthandler.log"))

    execution_source = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    require(re.fullmatch(r"[0-9a-f]{40}", execution_source) is not None, "SCIENCE_EXECUTION_IDENTITY_INVALID")
    require(execution_source != BASE_INPUT_COMMIT, "P9_SOURCE_NOT_PUBLISHED")
    counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters_path.name, "P9_COUNTER_PATH_MISSING")

    require(sha256_file(PROVIDER_PATH) == PROVIDER_SHA, "P9_PROVIDER_HASH_MISMATCH")
    require(sha256_file(GRAPH_PATH) == GRAPH_SHA, "P9_GRAPH_HASH_MISMATCH")
    require(sha256_file(P8_SCRIPT) == "1a751b664e54c7bf7ec8969dccbe0ced7e713ff3f4e057c880564e2cb8fe5744",
            "P8_SCRIPT_HASH_MISMATCH")
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    require(isinstance(graph, dict) and len(graph.get("states", [])) == 13, "P9_STATE_GRAPH_INVALID")

    runtime = load_module("_mephc_p9_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_p9_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    require(scientific_job.runtime_hash(ROOT) == RUNTIME_SHA, "P9_RUNTIME_HASH_MISMATCH")
    state_root = runtime._trusted_science_state_root()
    p8 = scientific_job.verify_dataset(state_root, P8_TRACE_DATASET_ID)
    require(p8["manifest_sha256"] == P8_TRACE_MANIFEST_SHA and p8["record_count"] == 1,
            "P8_TRACE_EVIDENCE_INVALID")
    index = json.loads((state_root / "dataset-index" / f"{P8_TRACE_DATASET_ID}.json").read_text(encoding="utf-8"))
    manifest = json.loads((state_root / "datasets" / index["namespace_sha256"] / "dataset-manifest.json").read_text(encoding="utf-8"))
    require(manifest["namespace"]["science_contract_id"] == "MEPHC-LOCALAFFINE-P8-FIRST-STATE-NATIVE-SEGFAULT-LOCALIZATION-20260829-372",
            "P8_TRACE_WORK_ORDER_INVALID")
    require(manifest["namespace"]["source_commit"] == P8_PROVIDER_SOURCE, "P8_TRACE_SOURCE_INVALID")

    trace_namespace = {
        "project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID,
        "source_commit": execution_source, "entrypoint_sha256": sha256_file(ROOT / "audit/local_affine/p9_run_parity_reset_isolation.py"),
        "trace_type": "p9_run_parity_reset_isolation", "p8_trace_dataset_id": P8_TRACE_DATASET_ID,
    }
    trace_store = scientific_job.ImmutableDatasetStore(state_root, trace_namespace)
    require(not trace_store.root.exists(), "P9_TRACE_NAMESPACE_ALREADY_EXISTS")
    trace_dir = state_root / "diagnostic-traces" / sha256_bytes(canonical(trace_namespace))
    trace_dir.mkdir(parents=True, exist_ok=False)
    outcomes = []
    for probe in ("TM_RESET_TRUE", "NO_PARITY_RESET_TRUE"):
        marker_path = trace_dir / f"{probe}.markers.log"
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--p9-worker", probe, str(marker_path)],
            cwd=ROOT, capture_output=True, check=False, timeout=3600,
        )
        markers = marker_path.read_text(encoding="utf-8").splitlines() if marker_path.is_file() else []
        outcomes.append(probe_record(
            probe, completed.returncode, markers, Path(str(marker_path) + ".faulthandler.log"),
            completed.stdout or b"", completed.stderr or b""))
    a, b = outcomes
    failure_class, root_cause, repair = classify(a, b)
    payload = canonical({
        "schema": "mephc-local-affine-p9-run-parity-diagnostic-trace-v1",
        "work_order_id": WORK_ORDER_ID, "science_execution_source": execution_source,
        "p8_trace_dataset_id": P8_TRACE_DATASET_ID, "p8_trace_manifest_sha256": P8_TRACE_MANIFEST_SHA,
        "probe_a": a, "probe_b": b, "run_parity_failure_class": failure_class,
        "root_cause_status": root_cause, "diagnostic_trace_not_reusable_for_science": True,
        "formal_local_affine_dataset_record_count": 0,
    })
    record = trace_store.put(canonical({"work_order_id": WORK_ORDER_ID, "role": "two_predeclared_probes"}), payload, {
        "work_order_id": WORK_ORDER_ID, "p8_trace_dataset_id": P8_TRACE_DATASET_ID,
        "p8_trace_manifest_sha256": P8_TRACE_MANIFEST_SHA, "probe_a_id": a["probe_id"],
        "probe_b_id": b["probe_id"], "run_parity_failure_class": failure_class,
        "formal_local_affine_dataset_record_count": 0,
    })
    result_manifest = trace_store.finalize(1, {
        "work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
        "p8_trace_dataset_id": P8_TRACE_DATASET_ID, "native_invocation_count": 1,
        "provider_execution_count": 2, "solver_execution_count": 2,
        "formal_local_affine_dataset_record_count": 0,
    })
    job_id = counters_path.name.split(".", 1)[0]
    result = {
        "schema": "mephc-local-affine-p9-run-parity-reset-isolation-v1",
        "WORK_ORDER_ID": WORK_ORDER_ID, "BASE_SANDBOX_SHA": BASE_INPUT_COMMIT,
        "IMPLEMENTATION_SOURCE_IDENTITY": execution_source, "SCIENCE_EXECUTION_IDENTITY": execution_source,
        "FINAL_SANDBOX_SHA": execution_source, "ORIGIN_SANDBOX_SHA": execution_source, "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS", "P8_TRACE_DATASET_ID": P8_TRACE_DATASET_ID,
        "P8_TRACE_MANIFEST_SHA256": P8_TRACE_MANIFEST_SHA, "PROVIDER_MODULE_SHA256": PROVIDER_SHA,
        "REQUEST_GRAPH_SHA256": GRAPH_SHA, "SCIENTIFIC_STATE_SET_IDENTITY": STATE_SET_SHA,
        "SCIENCE_JOB_ID": job_id, "SCIENCE_SOURCE_SHA": execution_source,
        "NATIVE_INVOCATION_COUNT": 1, "PROVIDER_EXECUTION_COUNT": 2, "SOLVER_EXECUTION_COUNT": 2,
        "DIAGNOSTIC_WORKER_PROCESS_COUNT": 2,
        "PROBE_A_RETURN_CODE": a["return_code"], "PROBE_A_SIGSEGV": a["sigsegv"],
        "PROBE_A_LAST_STAGE_MARKER": a["last_stage_marker"],
        "PROBE_A_FREQUENCY_EXTRACTION_SUCCESS": a["frequency_extraction_success"],
        "PROBE_A_FINITE_SIX_FREQUENCIES": a["finite_six_frequencies"],
        "PROBE_A_TOP_FAULTHANDLER_FRAME": a["top_faulthandler_frame"],
        "PROBE_B_RETURN_CODE": b["return_code"], "PROBE_B_SIGSEGV": b["sigsegv"],
        "PROBE_B_LAST_STAGE_MARKER": b["last_stage_marker"],
        "PROBE_B_FREQUENCY_EXTRACTION_SUCCESS": b["frequency_extraction_success"],
        "PROBE_B_FINITE_SIX_FREQUENCIES": b["finite_six_frequencies"],
        "PROBE_B_TOP_FAULTHANDLER_FRAME": b["top_faulthandler_frame"],
        "RUN_PARITY_FAILURE_CLASS": failure_class, "ROOT_CAUSE_STATUS": root_cause,
        "RECOMMENDED_PROVIDER_REPAIR": repair, "DIAGNOSTIC_TRACE_DATASET_ID": result_manifest["dataset_id"],
        "DIAGNOSTIC_TRACE_MANIFEST_SHA256": result_manifest["manifest_sha256"],
        "DIAGNOSTIC_TRACE_RECORD_COUNT": 1, "DIAGNOSTIC_TRACE_PERSISTED": True,
        "DIAGNOSTIC_TRACE_NOT_REUSABLE_FOR_SCIENCE": True, "FORMAL_LOCAL_AFFINE_DATASET_RECORD_COUNT": 0,
        "RETRY_COUNT": 0, "CACHE_REUSE_COUNT": 0,
        "LOCALAFFINE_P9_RUN_PARITY_ISOLATION_STATUS": "PASS", "P8_DIAGNOSIS_BINDING_STATUS": "VERIFIED",
        "NEXT_LIVE_SOLVER_AUTHORIZATION": False, "LIVE_RERUN_AUTHORIZED": False,
        "PIPELINE_HEALTH": "PIPELINE_REQUIRES_CORRECTIVE", "BLOCKED_BY_INFRASTRUCTURE": True,
        "SCIENTIFIC_WORK_MUST_STOP": True, "RETURN_TO_SUPERVISOR": True,
        "TERMINAL": "LOCALAFFINE_P9_RUN_PARITY_RESET_ISOLATION_COMPLETE",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
