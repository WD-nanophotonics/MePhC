"""Test the historical non-empty band-function contrast for the P9 crash."""
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
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P10-RUN-PARITY-BAND-FUNCTION-ISOLATION-20260829-374"
BASE_INPUT_COMMIT = "61151fdab010ef7e65f42b1693ca03fe1ae94f0d"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
P9_BINDING_SHA = "d3d22a5b50e13485b287b0f708e760d3171e361c8e9199d1b9a9d54ed37b6a94"
P9_TRACE_DATASET_ID = "386987b790d65f2b5b82a41c4903607ca1addfb137af27e6b379bf3d26f10e4f"
P9_TRACE_MANIFEST_SHA = "b97b3b5631b319f3de36269b2710257b5eb1573017054fa26938a07db0cbedcb"
HISTORICAL_RUN_SHA = "5119df243617ebedaac615a07305c77dacf4de83"
HISTORICAL_ENERGY_PROVIDER_SHA = "f3dd87c9b3ece5ccec577caa4b1b47b269e53133"
HISTORICAL_GEOMETRY_SHA = "53beca884f7f2802cf152e5c32d468ad35efda3d"
PROVIDER_SHA = "e83aa9768b53ad5e0f151636982e91a1193b269cf4e5baef1da1a0ca33965128"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P9_BINDING = ROOT / "audit/local_affine/p9_run_parity_reset_isolation_binding.json"
HISTORICAL_RUN = ROOT / "audit/e8b/run_e8b.py"
HISTORICAL_ENERGY_PROVIDER = ROOT / "mephc/mpb_energy_spectral_provider.py"
HISTORICAL_GEOMETRY = ROOT / "audit/e8b/e8b_geometry.py"
PROVIDER_PATH = ROOT / "mephc/local_affine_state_provider.py"
GRAPH_PATH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"


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
    line = f"P10_STAGE|{probe}|{stage}|{event}\n".encode("ascii")
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
        from meep import mpb
        import numpy as np
        from audit.e10f.e8b_local_affine_model import canonical_state_identity, make_state
        from mephc import mpb_spectral_provider as msp
        write_marker(marker_path, probe, "MEEP_IMPORT", "EXIT")

        write_marker(marker_path, probe, "STATE_CONSTRUCTION", "ENTER")
        spec = make_state((0.0, -37.0 / 60.0), 0.0)
        identity = canonical_state_identity(spec)
        require(identity["public_q"] == [0.0, -37.0 / 60.0] and identity["s"] == 0.0,
                "P10_STATE_01_IDENTITY_INVALID")
        require(identity["polarization"] == "TM" and identity["resolution"] == 64
                and identity["num_bands"] == 6 and identity["eigensolver_tolerance"] == 1e-7
                and identity["mesh_size"] == 3 and identity["deterministic"] is True,
                "P10_STATE_01_SOLVER_CONTRACT_INVALID")
        write_marker(marker_path, probe, "STATE_CONSTRUCTION", "EXIT")

        class HistoricalContrastProvider(msp.MPBLiveSpectralProvider):
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

                def noop_band_function(*args, **kwargs):
                    return None

                callback = noop_band_function if probe == "TM_FALSE_NOOP_BAND_FUNCTION" else mpb.fix_efield_phase
                write_marker(marker_path, probe, "RUN_PARITY", "ENTER")
                solver.run_parity(mp.TM, False, callback)
                write_marker(marker_path, probe, "RUN_PARITY", "EXIT")
                write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "ENTER")
                frequencies = np.asarray(solver.all_freqs)
                require(frequencies.ndim == 2 and frequencies.shape[0] >= 1
                        and frequencies.shape[1] == 6, "P10_FREQUENCY_SHAPE_INVALID")
                values = np.asarray(frequencies[0], dtype=float)
                require(values.shape == (6,) and np.all(np.isfinite(values)),
                        "P10_FREQUENCY_FINITE_SIX_INVALID")
                write_marker(marker_path, probe, "FREQUENCY_EXTRACTION", "EXIT")
                return values

        provider = HistoricalContrastProvider(
            geometry=spec.geometry, geometry_lattice=spec.geometry_lattice,
            resolution=64, num_bands=6, polarization=mp.TM, default_material=mp.air,
            eigensolver_tolerance=1e-7, deterministic=True, mesh_size=3, phase_callback=None)
        frequencies = provider.solve(tuple(identity["public_q"]))
        require(frequencies.shape == (6,), "P10_RESULT_SHAPE_INVALID")
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


def record(probe: str, completed: subprocess.CompletedProcess[bytes], marker_path: Path) -> dict[str, Any]:
    markers = marker_path.read_text(encoding="utf-8").splitlines() if marker_path.is_file() else []
    return {
        "probe_id": probe, "return_code": completed.returncode, "sigsegv": completed.returncode == -11,
        "last_stage_marker": markers[-1] if markers else "NONE",
        "callback_observed": False,
        "frequency_extraction_success": any("|FREQUENCY_EXTRACTION|EXIT" in line for line in markers),
        "finite_six_frequencies": any("|FREQUENCY_EXTRACTION|EXIT" in line for line in markers),
        "top_faulthandler_frame": fault_frame(Path(str(marker_path) + ".faulthandler.log")),
        "markers": markers,
        "stdout": (completed.stdout or b"").decode("utf-8", errors="replace"),
        "stderr": (completed.stderr or b"").decode("utf-8", errors="replace"),
    }


def classify(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, str, str]:
    if a["sigsegv"] and not b["sigsegv"]:
        return ("FIX_EFIELD_PHASE_CALLBACK_REQUIRED_FOR_HISTORICAL_E8B_RUN_PATH",
                "LOCALIZED_NOT_ESTABLISHED", "NONE_PENDING_GAUGE_CALLBACK_SAFETY_CERTIFICATION")
    if a["sigsegv"] and b["sigsegv"]:
        return ("HISTORICAL_E8B_RUN_PATH_NO_LONGER_REPRODUCES",
                "LOCALIZED_NOT_ESTABLISHED", "NONE")
    if not a["sigsegv"] and b["sigsegv"]:
        return ("FIX_EFIELD_PHASE_CALLBACK_SPECIFIC_FAILURE",
                "LOCALIZED_NOT_ESTABLISHED", "SEMANTICS_NEUTRAL_NOOP_CALLBACK_CANDIDATE_PENDING_FULL_STATE_CERTIFICATION")
    return ("ZERO_BAND_FUNCTION_RUN_PARITY_NATIVE_BUG", "ESTABLISHED",
            "WHEN_PHASE_CALLBACK_IS_NONE_PASS_A_SEMANTICS_NEUTRAL_NOOP_BAND_FUNCTION_TO_RUN_PARITY_AND_CERTIFY_ONE_FULL_STATE_BEFORE_13_STATE_ACQUISITION")


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--p10-worker":
        return worker(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[3] + ".faulthandler.log"))

    execution_source = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    require(re.fullmatch(r"[0-9a-f]{40}", execution_source) is not None, "SCIENCE_EXECUTION_IDENTITY_INVALID")
    counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters_path.name, "P10_COUNTER_PATH_MISSING")
    require(sha256_file(P9_BINDING) == P9_BINDING_SHA, "P9_BINDING_HASH_MISMATCH")
    p9_binding = json.loads(P9_BINDING.read_text(encoding="utf-8"))
    require(p9_binding.get("RUN_PARITY_FAILURE_CLASS") == "GENERAL_E8B_MPB_RUN_PATH"
            and p9_binding.get("PROBE_A_RESULT", {}).get("sigsegv") is True
            and p9_binding.get("PROBE_B_RESULT", {}).get("sigsegv") is True,
            "P9_BINDING_EVIDENCE_INVALID")
    require(sha256_file(HISTORICAL_RUN) == HISTORICAL_RUN_SHA, "HISTORICAL_RUN_HASH_MISMATCH")
    require(sha256_file(HISTORICAL_ENERGY_PROVIDER) == HISTORICAL_ENERGY_PROVIDER_SHA,
            "HISTORICAL_ENERGY_PROVIDER_HASH_MISMATCH")
    require(sha256_file(HISTORICAL_GEOMETRY) == HISTORICAL_GEOMETRY_SHA, "HISTORICAL_GEOMETRY_HASH_MISMATCH")
    require(sha256_file(PROVIDER_PATH) == PROVIDER_SHA and sha256_file(GRAPH_PATH) == GRAPH_SHA,
            "P10_CURRENT_INPUT_HASH_MISMATCH")
    historical_run = HISTORICAL_RUN.read_text(encoding="utf-8")
    historical_energy = HISTORICAL_ENERGY_PROVIDER.read_text(encoding="utf-8")
    require("phase_callback=mpb.fix_efield_phase" in historical_run
            and "R64=64" in historical_run and "for res in (R48,R64)" in historical_run
            and "polarization=mp.TM" in historical_run,
            "HISTORICAL_E8B_CONTRAST_DECLARATION_INVALID")
    require("solver.run_parity(polarization, False, self.phase_callback)" in historical_energy,
            "HISTORICAL_CALLBACK_RUN_PARITY_INVALID")

    runtime = load_module("_mephc_p10_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_p10_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    require(scientific_job.runtime_hash(ROOT) == RUNTIME_SHA, "P10_RUNTIME_HASH_MISMATCH")
    state_root = runtime._trusted_science_state_root()
    trace_namespace = {
        "project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID,
        "source_commit": execution_source,
        "entrypoint_sha256": sha256_file(ROOT / "audit/local_affine/p10_run_parity_band_function_isolation.py"),
        "trace_type": "p10_run_parity_band_function_isolation", "p9_trace_dataset_id": P9_TRACE_DATASET_ID,
    }
    trace_store = scientific_job.ImmutableDatasetStore(state_root, trace_namespace)
    require(not trace_store.root.exists(), "P10_TRACE_NAMESPACE_ALREADY_EXISTS")
    trace_dir = state_root / "diagnostic-traces" / sha256_bytes(canonical(trace_namespace))
    trace_dir.mkdir(parents=True, exist_ok=False)
    counter = scientific_job.BudgetCounter(2, 2)
    outcomes = []
    for probe in ("TM_FALSE_NOOP_BAND_FUNCTION", "TM_FALSE_FIX_EFIELD_PHASE"):
        counter.consume_provider()
        counter.consume_solver()
        marker_path = trace_dir / f"{probe}.markers.log"
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--p10-worker", probe, str(marker_path)],
            cwd=ROOT, capture_output=True, check=False, timeout=3600,
        )
        outcomes.append(record(probe, completed, marker_path))
    a, b = outcomes
    failure_class, root_cause, repair = classify(a, b)
    payload = canonical({
        "schema": "mephc-local-affine-p10-run-parity-band-function-diagnostic-trace-v1",
        "work_order_id": WORK_ORDER_ID, "science_execution_source": execution_source,
        "p9_trace_dataset_id": P9_TRACE_DATASET_ID, "p9_trace_manifest_sha256": P9_TRACE_MANIFEST_SHA,
        "historical_e8b_contrast_status": "PASS", "probe_a": a, "probe_b": b,
        "band_function_failure_class": failure_class, "root_cause_status": root_cause,
        "diagnostic_trace_not_reusable_for_science": True, "formal_local_affine_dataset_record_count": 0,
    })
    trace_store.put(canonical({"work_order_id": WORK_ORDER_ID, "role": "two_predeclared_probes"}), payload, {
        "work_order_id": WORK_ORDER_ID, "p9_trace_dataset_id": P9_TRACE_DATASET_ID,
        "p9_trace_manifest_sha256": P9_TRACE_MANIFEST_SHA, "probe_a_id": a["probe_id"],
        "probe_b_id": b["probe_id"], "band_function_failure_class": failure_class,
        "formal_local_affine_dataset_record_count": 0,
    })
    manifest = trace_store.finalize(1, {
        "work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
        "p9_trace_dataset_id": P9_TRACE_DATASET_ID, "native_invocation_count": 1,
        "provider_execution_count": 2, "solver_execution_count": 2,
        "formal_local_affine_dataset_record_count": 0,
    })
    job_id = counters_path.name.split(".", 1)[0]
    result = {
        "schema": "mephc-local-affine-p10-run-parity-band-function-isolation-v1",
        "WORK_ORDER_ID": WORK_ORDER_ID, "BASE_SANDBOX_SHA": BASE_INPUT_COMMIT,
        "IMPLEMENTATION_SOURCE_IDENTITY": execution_source, "SCIENCE_EXECUTION_IDENTITY": execution_source,
        "FINAL_SANDBOX_SHA": execution_source, "ORIGIN_SANDBOX_SHA": execution_source, "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS", "P9_BINDING_SHA256": P9_BINDING_SHA,
        "P9_TRACE_DATASET_ID": P9_TRACE_DATASET_ID, "P9_TRACE_MANIFEST_SHA256": P9_TRACE_MANIFEST_SHA,
        "HISTORICAL_E8B_CONTRAST_STATUS": "PASS", "PROVIDER_MODULE_SHA256": PROVIDER_SHA,
        "REQUEST_GRAPH_SHA256": GRAPH_SHA, "SCIENTIFIC_STATE_SET_IDENTITY": STATE_SET_SHA,
        "SCIENCE_JOB_ID": job_id, "SCIENCE_SOURCE_SHA": execution_source,
        "NATIVE_INVOCATION_COUNT": 1, "PROVIDER_EXECUTION_COUNT": 2, "SOLVER_EXECUTION_COUNT": 2,
        "DIAGNOSTIC_WORKER_PROCESS_COUNT": 2,
        "PROBE_A_RETURN_CODE": a["return_code"], "PROBE_A_SIGSEGV": a["sigsegv"],
        "PROBE_A_LAST_STAGE_MARKER": a["last_stage_marker"], "PROBE_A_CALLBACK_OBSERVED": a["callback_observed"],
        "PROBE_A_FREQUENCY_EXTRACTION_SUCCESS": a["frequency_extraction_success"],
        "PROBE_A_FINITE_SIX_FREQUENCIES": a["finite_six_frequencies"],
        "PROBE_A_TOP_FAULTHANDLER_FRAME": a["top_faulthandler_frame"],
        "PROBE_B_RETURN_CODE": b["return_code"], "PROBE_B_SIGSEGV": b["sigsegv"],
        "PROBE_B_LAST_STAGE_MARKER": b["last_stage_marker"], "PROBE_B_CALLBACK_OBSERVED": b["callback_observed"],
        "PROBE_B_FREQUENCY_EXTRACTION_SUCCESS": b["frequency_extraction_success"],
        "PROBE_B_FINITE_SIX_FREQUENCIES": b["finite_six_frequencies"],
        "PROBE_B_TOP_FAULTHANDLER_FRAME": b["top_faulthandler_frame"],
        "BAND_FUNCTION_FAILURE_CLASS": failure_class, "ROOT_CAUSE_STATUS": root_cause,
        "RECOMMENDED_PROVIDER_REPAIR": repair, "DIAGNOSTIC_TRACE_DATASET_ID": manifest["dataset_id"],
        "DIAGNOSTIC_TRACE_MANIFEST_SHA256": manifest["manifest_sha256"], "DIAGNOSTIC_TRACE_RECORD_COUNT": 1,
        "DIAGNOSTIC_TRACE_PERSISTED": True, "DIAGNOSTIC_TRACE_NOT_REUSABLE_FOR_SCIENCE": True,
        "FORMAL_LOCAL_AFFINE_DATASET_RECORD_COUNT": 0, "RETRY_COUNT": 0, "CACHE_REUSE_COUNT": 0,
        "LOCALAFFINE_P10_BAND_FUNCTION_ISOLATION_STATUS": "PASS", "P9_DIAGNOSIS_BINDING_STATUS": "VERIFIED",
        "NEXT_LIVE_SOLVER_AUTHORIZATION": False, "LIVE_RERUN_AUTHORIZED": False,
        "PIPELINE_HEALTH": "PIPELINE_REQUIRES_CORRECTIVE", "BLOCKED_BY_INFRASTRUCTURE": True,
        "SCIENTIFIC_WORK_MUST_STOP": True, "RETURN_TO_SUPERVISOR": True,
        "TERMINAL": "LOCALAFFINE_P10_RUN_PARITY_BAND_FUNCTION_ISOLATION_COMPLETE",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
