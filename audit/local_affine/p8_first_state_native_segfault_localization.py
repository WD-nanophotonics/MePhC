"""Bound the existing P6 crash with one instrumented STATE_01 worker."""
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
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P8-FIRST-STATE-NATIVE-SEGFAULT-LOCALIZATION-20260829-372"
BASE_INPUT_COMMIT = "b7216710c296e12445491a885456ff414f50ee08"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
P6_NATIVE_RUN_ID = "MEPHC-NATIVE-094734b707e95c354a3294f3"
P7_DIAGNOSIS_SHA = "b4bc434a0300d5c4c9c3f2cf5e9aa20daadf43a138e3824e543875e9d552e2d2"
PROVIDER_SHA = "e83aa9768b53ad5e0f151636982e91a1193b269cf4e5baef1da1a0ca33965128"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P6_ENTRYPOINT_SHA = "2292dbe30c9d3f7e80f036d8548a44f548a783a5815ae081843e51e08a40ebee"
P7_ARTIFACT = ROOT / "audit/local_affine/p7_p6_native_segfault_diagnosis.json"
GRAPH_PATH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"
PROVIDER_PATH = ROOT / "mephc/local_affine_state_provider.py"
P8_BINDING = ROOT / "audit/local_affine/p8_first_state_native_segfault_localization_binding.json"


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


def write_marker(path: Path, stage: str, event: str) -> None:
    line = f"P8_STAGE|{stage}|{event}\n".encode("ascii")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    sys.stdout.write(line.decode("ascii"))
    sys.stdout.flush()


def instrumented_worker(marker_path: Path, fault_path: Path) -> int:
    with fault_path.open("ab", buffering=0) as fault_file:
        faulthandler.enable(file=fault_file, all_threads=True)
        write_marker(marker_path, "A_WORKER_START", "ENTER")
        write_marker(marker_path, "A_WORKER_START", "EXIT")
        write_marker(marker_path, "B_MEEP_IMPORT", "ENTER")
        import meep as mp
        from mephc import local_affine_state_provider as lap
        from mephc import mpb_spectral_provider as msp
        from mephc.mpb_spectral import adapt_mpb_h_envelopes
        import numpy as np
        from audit.e10f.e8b_local_affine_model import canonical_state_identity, make_state
        write_marker(marker_path, "B_MEEP_IMPORT", "EXIT")

        write_marker(marker_path, "C_STATE_CONSTRUCTION", "ENTER")
        spec = make_state((0.0, -37.0 / 60.0), 0.0)
        identity = canonical_state_identity(spec)
        require(identity["polarization"] == "TM" and identity["public_q"] == [0.0, -37.0 / 60.0],
                "P8_STATE_01_IDENTITY_INVALID")
        write_marker(marker_path, "C_STATE_CONSTRUCTION", "EXIT")

        original = lap.MPBLiveSpectralProvider

        class InstrumentedMPBLiveSpectralProvider(original):
            def solve(self, k_point):
                write_marker(marker_path, "F_UNDERLYING_MPB_PROVIDER_SOLVE", "ENTER")
                cartesian = msp._cartesian_point(k_point, name="k_point")
                z = cartesian[2] if len(cartesian) == 3 else 0.0
                public_k_point = tuple(cartesian)
                write_marker(marker_path, "G_CARTESIAN_TO_RECIPROCAL", "ENTER")
                reciprocal = mp.cartesian_to_reciprocal(
                    mp.Vector3(cartesian[0], cartesian[1], z), self.geometry_lattice)
                reciprocal_tuple = msp._vector3_tuple(reciprocal, name="reciprocal k_point")
                write_marker(marker_path, "G_CARTESIAN_TO_RECIPROCAL", "EXIT")
                spatial_shape = msp._spatial_shape(self.geometry_lattice, self.resolution)
                write_marker(marker_path, "H_MPB_MODE_SOLVER_CONSTRUCTION", "ENTER")
                solver = self._build_solver(reciprocal)
                write_marker(marker_path, "H_MPB_MODE_SOLVER_CONSTRUCTION", "EXIT")
                polarization = self.polarization if self.polarization is not None else mp.TE
                write_marker(marker_path, "I_MPB_RUN_PARITY", "ENTER")
                if self.phase_callback is None:
                    solver.run_parity(polarization, False)
                else:
                    solver.run_parity(polarization, False, self.phase_callback)
                write_marker(marker_path, "I_MPB_RUN_PARITY", "EXIT")
                write_marker(marker_path, "J_FREQUENCY_EXTRACTION", "ENTER")
                frequencies = np.asarray(solver.all_freqs)
                if frequencies.ndim != 2 or frequencies.shape[0] < 1 or frequencies.shape[1] != self.num_bands:
                    raise RuntimeError("live MPB all_freqs does not match the requested one-k-point band count")
                frequencies = np.asarray(frequencies[0], dtype=float)
                if not np.all(np.isfinite(frequencies)):
                    raise RuntimeError("live MPB frequencies are not finite")
                write_marker(marker_path, "J_FREQUENCY_EXTRACTION", "EXIT")
                fields = []
                for band in range(1, self.num_bands + 1):
                    stage = f"K_GET_HFIELD_BAND_{band}"
                    write_marker(marker_path, stage, "ENTER")
                    field = solver.get_hfield(band, bloch_phase=False)
                    if getattr(field, "bloch_phase", None) is not False:
                        raise RuntimeError("live MPB H field did not report bloch_phase=False")
                    field_k_point = msp._vector3_tuple(getattr(field, "kpoint", None), name="live H field kpoint")
                    if not np.allclose(field_k_point, reciprocal_tuple, rtol=0.0, atol=self.kpoint_tolerance):
                        raise RuntimeError("live MPB H field kpoint metadata disagrees with the solved reciprocal kpoint")
                    fields.append(msp._canonical_field(field, spatial_shape=spatial_shape, band=band))
                    write_marker(marker_path, stage, "EXIT")
                write_marker(marker_path, "L_H_BATCH_ASSEMBLY", "ENTER")
                h_batch = np.stack(fields, axis=0)
                write_marker(marker_path, "L_H_BATCH_ASSEMBLY", "EXIT")
                provenance = {
                    "live_provider": msp.MPB_LIVE_H_PROVIDER_REPRESENTATION,
                    "solver_settings": self._settings(reciprocal_k_point=reciprocal_tuple),
                    "mpb_reciprocal_k_point": list(reciprocal_tuple),
                    "field_kpoint_metadata_validated": True,
                    "phase_callback_is_gauge_choice": self.phase_callback is not None,
                }
                write_marker(marker_path, "M_H_ENVELOPE_ADAPTER", "ENTER")
                snapshot = adapt_mpb_h_envelopes(
                    public_k_point, frequencies, h_batch, mpb_k_point=reciprocal_tuple,
                    norm_tolerance=self.norm_tolerance, orthogonality_tolerance=self.orthogonality_tolerance,
                    provenance=provenance, _trusted_live_provenance=msp._LIVE_PROVENANCE_TOKEN)
                write_marker(marker_path, "M_H_ENVELOPE_ADAPTER", "EXIT")
                write_marker(marker_path, "F_UNDERLYING_MPB_PROVIDER_SOLVE", "EXIT")
                return snapshot

        lap.MPBLiveSpectralProvider = InstrumentedMPBLiveSpectralProvider
        write_marker(marker_path, "D_LOCAL_AFFINE_PROVIDER_CONSTRUCTION", "ENTER")
        provider = lap.LocalAffineStateProvider(
            polarization=mp.TM, polarization_identity="TM", default_material=mp.air,
            resolution=64, num_bands=6, eigensolver_tolerance=1e-7, mesh_size=3, deterministic=True)
        write_marker(marker_path, "D_LOCAL_AFFINE_PROVIDER_CONSTRUCTION", "EXIT")
        write_marker(marker_path, "E_LOCAL_AFFINE_PROVIDER_SOLVE", "ENTER")
        snapshot = provider.solve(spec)
        write_marker(marker_path, "E_LOCAL_AFFINE_PROVIDER_SOLVE", "EXIT")
        require(snapshot.provenance.get("local_affine_solver_polarization_identity") == "TM",
                "P8_PROVIDER_IDENTITY_INVALID")
        write_marker(marker_path, "N_LOCAL_AFFINE_POST_SOLVE_RETURN", "ENTER")
        print("P8_WORKER_FIRST_STATE_COMPLETED=true", flush=True)
        write_marker(marker_path, "N_LOCAL_AFFINE_POST_SOLVE_RETURN", "EXIT")
    return 0


def stage_classification(markers: list[str], return_code: int) -> tuple[str, str]:
    completed = [line for line in markers if line.endswith("|EXIT")]
    enters = [line for line in markers if line.endswith("|ENTER")]
    last = markers[-1] if markers else "NONE"
    if return_code == 0:
        return "FIRST_STATE_COMPLETED_NO_CRASH", last
    active = enters[-1].split("|")[1] if enters else ""
    mapping = {
        "B_MEEP_IMPORT": "MEEP_IMPORT_OR_INITIALIZATION",
        "G_CARTESIAN_TO_RECIPROCAL": "MEEP_COORDINATE_CONVERSION",
        "H_MPB_MODE_SOLVER_CONSTRUCTION": "MPB_MODE_SOLVER_CONSTRUCTION",
        "I_MPB_RUN_PARITY": "MPB_RUN_PARITY",
        "K_GET_HFIELD_BAND_1": "MPB_HFIELD_EXTRACTION_BAND_1",
        "K_GET_HFIELD_BAND_2": "MPB_HFIELD_EXTRACTION_BAND_2",
        "K_GET_HFIELD_BAND_3": "MPB_HFIELD_EXTRACTION_BAND_3",
        "K_GET_HFIELD_BAND_4": "MPB_HFIELD_EXTRACTION_BAND_4",
        "K_GET_HFIELD_BAND_5": "MPB_HFIELD_EXTRACTION_BAND_5",
        "K_GET_HFIELD_BAND_6": "MPB_HFIELD_EXTRACTION_BAND_6",
        "M_H_ENVELOPE_ADAPTER": "H_ENVELOPE_ADAPTER",
        "N_LOCAL_AFFINE_POST_SOLVE_RETURN": "LOCAL_AFFINE_POST_SOLVE",
    }
    return mapping.get(active, "UNKNOWN_WITH_STAGE_TRACE"), last


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--p8-worker":
        return instrumented_worker(Path(sys.argv[2]), Path(sys.argv[2] + ".faulthandler.log"))

    execution_source = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    require(re.fullmatch(r"[0-9a-f]{40}", execution_source) is not None, "SCIENCE_EXECUTION_IDENTITY_INVALID")
    counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters_path.name, "P8_COUNTER_PATH_MISSING")
    flow_root = counters_path.parent.parent
    require(sha256_file(P7_ARTIFACT) == P7_DIAGNOSIS_SHA, "P7_DIAGNOSIS_HASH_MISMATCH")
    require(sha256_file(PROVIDER_PATH) == PROVIDER_SHA, "P8_PROVIDER_HASH_MISMATCH")
    require(sha256_file(GRAPH_PATH) == GRAPH_SHA, "P8_GRAPH_HASH_MISMATCH")
    runtime = load_module("_mephc_p8_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_p8_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    require(scientific_job.runtime_hash(ROOT) == RUNTIME_SHA, "P8_RUNTIME_HASH_MISMATCH")
    state_root = runtime._trusted_science_state_root()
    trace_namespace = {"project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID,
                       "source_commit": execution_source,
                       "entrypoint_sha256": sha256_file(ROOT / "audit/local_affine/p8_first_state_native_segfault_localization.py"),
                       "trace_type": "p8_native_stage_diagnostic", "diagnostic_state_id": "STATE_01"}
    trace_store = scientific_job.ImmutableDatasetStore(state_root, trace_namespace)
    require(not trace_store.root.exists(), "P8_TRACE_NAMESPACE_ALREADY_EXISTS")
    trace_dir = state_root / "diagnostic-traces" / sha256_bytes(canonical(trace_namespace))
    trace_dir.mkdir(parents=True, exist_ok=False)
    marker_path = trace_dir / "stage-markers.log"
    worker_result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--p8-worker", str(marker_path)],
        cwd=ROOT, capture_output=True, check=False, timeout=3600,
    )
    marker_lines = marker_path.read_text(encoding="utf-8").splitlines() if marker_path.is_file() else []
    fault_path = Path(str(marker_path) + ".faulthandler.log")
    fault = fault_path.read_bytes() if fault_path.is_file() else b""
    stdout = worker_result.stdout or b""
    stderr = worker_result.stderr or b""
    classification, last_marker = stage_classification(marker_lines, worker_result.returncode)
    faulthandler_frame = "UNKNOWN_NO_FAULTHANDLER_FRAME"
    for line in fault.decode("utf-8", errors="replace").splitlines():
        if "File \"" in line or "Fatal Python error" in line:
            faulthandler_frame = line.strip()
            break
    trace_payload = canonical({
        "schema": "mephc-local-affine-p8-native-stage-diagnostic-trace-v1",
        "work_order_id": WORK_ORDER_ID, "diagnostic_state_id": "STATE_01",
        "science_execution_source": execution_source, "worker_return_code": worker_result.returncode,
        "stage_markers": marker_lines, "worker_stdout": stdout.decode("utf-8", errors="replace"),
        "worker_stderr": stderr.decode("utf-8", errors="replace"),
        "faulthandler": fault.decode("utf-8", errors="replace"),
        "crash_stage_classification": classification, "last_stage_marker": last_marker,
        "p6_native_run_id": P6_NATIVE_RUN_ID, "p7_diagnosis_sha256": P7_DIAGNOSIS_SHA,
        "provider_module_sha256": PROVIDER_SHA, "request_graph_sha256": GRAPH_SHA,
        "scientific_state_set_identity": STATE_SET_SHA,
        "formal_scientific_dataset_record_count": 0,
    })
    record = trace_store.put(canonical({"work_order_id": WORK_ORDER_ID, "state_id": "STATE_01"}), trace_payload, {
        "work_order_id": WORK_ORDER_ID, "diagnostic_state_id": "STATE_01",
        "science_execution_source": execution_source, "p6_native_run_id": P6_NATIVE_RUN_ID,
        "p7_diagnosis_sha256": P7_DIAGNOSIS_SHA, "trace_payload_sha256": sha256_bytes(trace_payload),
        "crash_stage_classification": classification, "formal_scientific_dataset_record_count": 0,
    })
    manifest = trace_store.finalize(1, {
        "work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
        "diagnostic_state_id": "STATE_01", "diagnostic_trace": True,
        "formal_scientific_dataset_record_count": 0, "native_invocation_count": 1,
        "provider_execution_count": 1, "solver_execution_count": 1,
    })
    job_id = counters_path.name.split(".", 1)[0]
    result = {
        "schema": "mephc-local-affine-p8-first-state-native-segfault-localization-v1",
        "WORK_ORDER_ID": WORK_ORDER_ID, "BASE_SANDBOX_SHA": BASE_INPUT_COMMIT,
        "IMPLEMENTATION_SOURCE_IDENTITY": execution_source, "SCIENCE_EXECUTION_IDENTITY": execution_source,
        "FINAL_SANDBOX_SHA": execution_source, "ORIGIN_SANDBOX_SHA": execution_source, "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS", "P6_NATIVE_RUN_ID": P6_NATIVE_RUN_ID,
        "P7_DIAGNOSIS_SHA256": P7_DIAGNOSIS_SHA, "PROVIDER_MODULE_SHA256": PROVIDER_SHA,
        "REQUEST_GRAPH_SHA256": GRAPH_SHA, "SCIENTIFIC_STATE_SET_IDENTITY": STATE_SET_SHA,
        "SCIENCE_JOB_ID": job_id, "SCIENCE_SOURCE_SHA": execution_source,
        "NATIVE_INVOCATION_COUNT": 1, "PROVIDER_EXECUTION_COUNT": 1, "SOLVER_EXECUTION_COUNT": 1,
        "DIAGNOSTIC_WORKER_PROCESS_COUNT": 1, "DIAGNOSTIC_WORKER_RETURN_CODE": worker_result.returncode,
        "DIAGNOSTIC_WORKER_SIGSEGV_CONFIRMED": worker_result.returncode == -11,
        "FIRST_STATE_DIAGNOSTIC_COMPLETED": worker_result.returncode == 0,
        "FAULTHANDLER_ENABLED": True, "LAST_STAGE_MARKER": last_marker,
        "CRASH_STAGE_CLASSIFICATION": classification, "TOP_FAULTHANDLER_FRAME": faulthandler_frame,
        "DIAGNOSTIC_TRACE_DATASET_ID": manifest["dataset_id"],
        "DIAGNOSTIC_TRACE_MANIFEST_SHA256": manifest["manifest_sha256"],
        "DIAGNOSTIC_TRACE_RECORD_COUNT": 1, "DIAGNOSTIC_TRACE_PERSISTED": True,
        "DIAGNOSTIC_TRACE_NOT_REUSABLE_FOR_SCIENCE": True,
        "FORMAL_LOCAL_AFFINE_DATASET_RECORD_COUNT": 0, "RETRY_COUNT": 0, "CACHE_REUSE_COUNT": 0,
        "LOCALAFFINE_P8_SEGFAULT_LOCALIZATION_STATUS": "PASS", "P6_DIAGNOSIS_BINDING_STATUS": "VERIFIED",
        "DIAGNOSTIC_STATE_IDENTITY_STATUS": "PASS", "NEXT_LIVE_SOLVER_AUTHORIZATION": False,
        "LIVE_RERUN_AUTHORIZED": False, "PIPELINE_HEALTH": "PIPELINE_REQUIRES_CORRECTIVE",
        "BLOCKED_BY_INFRASTRUCTURE": True, "SCIENTIFIC_WORK_MUST_STOP": True,
        "RETURN_TO_SUPERVISOR": True, "TERMINAL": "LOCALAFFINE_P8_FIRST_STATE_SEGFAULT_LOCALIZATION_COMPLETE",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
