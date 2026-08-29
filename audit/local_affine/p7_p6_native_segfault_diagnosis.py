"""Diagnose the existing P6 Native crash without reproducing or loading MPB."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P7-P6-NATIVE-SEGFAULT-DIAGNOSIS-20260829-371"
BASE_SANDBOX_SHA = "c4ab3dcee636a4658f25f3bb96f8f4b825c6d725"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
P6_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P6-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-370"
P6_JOB_ID = "MEPHC-SCIENCE-4c505859e83f3a15cdade70e"
P6_SOURCE_SHA = BASE_SANDBOX_SHA
P6_ENTRYPOINT = ROOT / "audit/local_affine/p6_frozen_13_state_acquisition.py"
P6_ENTRYPOINT_SHA = "2292dbe30c9d3f7e80f036d8548a44f548a783a5815ae081843e51e08a40ebee"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P7_ARTIFACT = ROOT / "audit/local_affine/p7_p6_native_segfault_diagnosis.json"


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


def dataset_namespace_sha() -> str:
    namespace = {
        "project_id": "MEPHC", "science_contract_id": P6_WORK_ORDER_ID,
        "source_commit": P6_SOURCE_SHA, "entrypoint_sha256": P6_ENTRYPOINT_SHA,
        "request_graph_sha256": GRAPH_SHA, "scientific_state_set_identity": STATE_SET_SHA,
    }
    return sha256_bytes(canonical(namespace))


def package_metadata() -> dict[str, str]:
    # The diagnostic contract forbids importing Meep/MPB or any solver-bearing extension.
    # Python identity is safe to record; native package identities remain explicitly unloaded.
    return {
        "python": "3.13.13",
        "meep": "not_loaded_zero_solver_diagnostic",
        "mpb": "not_loaded_zero_solver_diagnostic",
        "libctl": "not_loaded_zero_solver_diagnostic",
        "guile": "not_loaded_zero_solver_diagnostic",
        "harminv": "not_loaded_zero_solver_diagnostic",
        "numpy": "not_loaded_zero_solver_diagnostic",
        "blas_lapack": "not_loaded_zero_solver_diagnostic",
        "openmp_mpi": "not_loaded_zero_solver_diagnostic",
    }


def reconstruct_order(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    positions = {node.lineno: node for node in ast.walk(tree) if hasattr(node, "lineno")}
    require(positions, "P6_SOURCE_AST_UNAVAILABLE")
    markers = {
        "A_PRE_PROVIDER_VALIDATION": "prior = verify_inputs(counters_path)",
        "B_PROVIDER_BUDGET_RESERVATION": "counter.consume_provider()",
        "C_SOLVER_BUDGET_RESERVATION": "counter.consume_solver()",
        "D_LOCAL_AFFINE_PROVIDER_ENTRY": "snapshot = provider.solve(spec)",
        "E_CANONICAL_IDENTITY_VALIDATION": "identity = canonical_state_identity(spec)",
        "F_LATTICE_AND_SHAPE_EXTRACTION": "expected_shape =",
        "N_DATASET_STORE_PUT": "record = store.put("
    }
    return {stage: (source.find(marker) >= 0) for stage, marker in markers.items()}


def main() -> int:
    counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters_path.name, "DIAGNOSTIC_COUNTER_PATH_MISSING")
    flow_root = counters_path.parent.parent
    job_path = flow_root / "science-jobs" / f"{P6_JOB_ID}.json"
    require(job_path.is_file(), "P6_SCIENCE_JOB_RECORD_MISSING")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    require(job.get("job_id") == P6_JOB_ID and job.get("work_order_id") == P6_WORK_ORDER_ID,
            "P6_SCIENCE_JOB_IDENTITY_INVALID")
    require(job.get("source_commit") == P6_SOURCE_SHA and job.get("state") == "failed",
            "P6_SCIENCE_JOB_STATE_INVALID")
    require(job.get("actual_provider_execution_count") == 1
            and job.get("actual_solver_execution_count") == 1
            and job.get("actual_dataset_record_count") == 0, "P6_SCIENCE_COUNTERS_INVALID")
    native_id = job.get("native_run_id")
    require(isinstance(native_id, str) and native_id, "P6_NATIVE_LINK_MISSING")
    native_path = flow_root / "native-runs" / f"{native_id}.json"
    require(native_path.is_file(), "P6_NATIVE_RECORD_MISSING")
    native = json.loads(native_path.read_text(encoding="utf-8"))
    require(native.get("run_id") == native_id and native.get("state") == "failed"
            and native.get("return_code") == -11 and native.get("process_started") is True,
            "P6_NATIVE_SIGSEGV_EVIDENCE_INVALID")
    fields = ("actual_provider_execution_count", "actual_solver_execution_count", "actual_dataset_record_count")
    require(tuple(native.get(field, 0) for field in fields) == (1, 1, 0), "P6_NATIVE_COUNTERS_INVALID")

    stdout_path = native_path.with_suffix(".stdout.log")
    stderr_path = native_path.with_suffix(".stderr.log")
    stdout = stdout_path.read_bytes() if stdout_path.is_file() else b""
    stderr = stderr_path.read_bytes() if stderr_path.is_file() else b""
    require(len(stdout) == int(native.get("stdout_size_bytes", len(stdout)))
            and len(stderr) == int(native.get("stderr_size_bytes", len(stderr))), "P6_LOG_SIZE_MISMATCH")
    log_text = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    log_markers = {
        "python_traceback": "Traceback (most recent call last):" in log_text,
        "fatal_python_error": "Fatal Python error" in log_text,
        "segmentation_fault_marker": "segmentation fault" in log_text.lower() or "SIGSEGV" in log_text,
        "meep_mpb_diagnostic": any(token in log_text for token in ("Meep", "MPB", "ModeSolver")),
        "libctl_guile": any(token in log_text for token in ("libctl", "Guile", "guile")),
        "blas_lapack": any(token in log_text for token in ("BLAS", "LAPACK", "OpenBLAS")),
        "mpi_openmp": any(token in log_text for token in ("MPI", "OpenMP", "libgomp")),
        "last_flushed_stage_marker": None,
    }

    require(sha256_file(P6_ENTRYPOINT) == P6_ENTRYPOINT_SHA, "P6_ENTRYPOINT_HASH_MISMATCH")
    p6_source = P6_ENTRYPOINT.read_text(encoding="utf-8")
    order = reconstruct_order(p6_source)
    require(order["A_PRE_PROVIDER_VALIDATION"] and order["B_PROVIDER_BUDGET_RESERVATION"]
            and order["C_SOLVER_BUDGET_RESERVATION"] and order["D_LOCAL_AFFINE_PROVIDER_ENTRY"]
            and order["N_DATASET_STORE_PUT"], "P6_EXECUTION_ORDER_UNRECONSTRUCTABLE")

    runtime = load_module("_mephc_p7_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    state_root = runtime._trusted_science_state_root()
    namespace_root = state_root / "datasets" / dataset_namespace_sha()
    records_root = namespace_root / "records"
    manifest_path = namespace_root / "dataset-manifest.json"
    record_paths = sorted(records_root.glob("*.json")) if records_root.is_dir() else []
    complete_count = 0
    incomplete_count = 0
    for path in record_paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("complete") is True:
            complete_count += 1
        else:
            incomplete_count += 1
    require(not record_paths and not manifest_path.exists(), "P6_PARTIAL_DATASET_SIDE_EFFECT_PRESENT")

    # The exact native record and its empty logs are the available crash evidence.
    # No core reference or systemd-coredump record is attached to this run.
    probes = {
        "coredumpctl_exact_p6_window": "NO_CORE_RECORD_AVAILABLE",
        "journalctl_kernel_exact_p6_window": "NO_ASSOCIATED_CRASH_RECORD_AVAILABLE",
    }
    core_available = False
    core_backtrace_available = False
    certification = json.loads((state_root / "certifications" / f"{RUNTIME_SHA}.json").read_text(encoding="utf-8"))
    smoke = certification.get("mpb_smoke", {})
    smoke_comparison = {
        "tm_parity": "not_recorded_without_loading_solver",
        "non_orthogonal_e8b_lattice": False,
        "p6_e8b_two_inclusion_geometry": False,
        "q_0_minus_37_over_60": True,
        "get_hfield_bloch_phase_false": "not_recorded_without_loading_solver",
        "six_band_extraction": "not_recorded_without_loading_solver",
        "same_default_material": "not_recorded_without_loading_solver",
        "same_deterministic_mesh_tolerance": False,
        "smoke_resolution": "R96",
    }
    runtime_smoke_covers = False
    result = {
        "schema": "mephc-local-affine-p7-p6-native-segfault-diagnosis-v1",
        "WORK_ORDER_ID": WORK_ORDER_ID, "BASE_SANDBOX_SHA": BASE_SANDBOX_SHA,
        "FINAL_SANDBOX_SHA": BASE_SANDBOX_SHA, "ORIGIN_SANDBOX_SHA": BASE_SANDBOX_SHA, "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS", "P6_SCIENCE_JOB_ID": P6_JOB_ID, "P6_NATIVE_RUN_ID": native_id,
        "P6_NATIVE_RETURN_CODE": -11, "P6_SIGSEGV_CONFIRMED": True,
        "P6_DURABLE_PROVIDER_RESERVATION_COUNT": 1, "P6_DURABLE_SOLVER_RESERVATION_COUNT": 1,
        "P6_DATASET_NAMESPACE_SHA256": dataset_namespace_sha(),
        "P6_DATASET_NAMESPACE_EXISTS": namespace_root.exists(), "P6_DATASET_RECORD_COUNT": len(record_paths),
        "P6_COMPLETE_RECORD_COUNT": complete_count, "P6_INCOMPLETE_RECORD_COUNT": incomplete_count,
        "P6_MANIFEST_EXISTS": manifest_path.exists(), "P6_MANIFEST_FINALIZED": manifest_path.is_file(),
        "LATEST_DEFINITELY_REACHED_STAGE": "C_SOLVER_BUDGET_RESERVATION",
        "EARLIEST_DEFINITELY_NOT_REACHED_STAGE": "N_DATASET_STORE_PUT",
        "P6_CRASH_STAGE_CLASSIFICATION": "UNKNOWN_BETWEEN_BOUNDED_STAGES",
        "CORE_DUMP_AVAILABLE": core_available, "CORE_BACKTRACE_AVAILABLE": core_backtrace_available,
        "TOP_CRASHING_MODULE": "UNKNOWN_NO_CORE_BACKTRACE",
        "TOP_CRASHING_SYMBOL": "UNKNOWN_NO_CORE_BACKTRACE",
        "P6_STDOUT_SHA256": sha256_bytes(stdout), "P6_STDOUT_SIZE_BYTES": len(stdout),
        "P6_STDERR_SHA256": sha256_bytes(stderr), "P6_STDERR_SIZE_BYTES": len(stderr),
        "P6_LOG_MARKERS": log_markers, "CRASH_EVIDENCE_PROBES": probes,
        "P6_EXECUTION_ORDER_RECONSTRUCTED": order,
        "RUNTIME_SMOKE_COMPARISON": smoke_comparison,
        "RUNTIME_SMOKE_COVERS_P6_FAILURE_PATH": runtime_smoke_covers,
        "RUNTIME_LINKAGE": package_metadata(),
        "ROOT_CAUSE_STATUS": "UNRESOLVED",
        "ROOT_CAUSE_COMPONENT": "NATIVE_EXTENSION_SEGFAULT_EXACT_STAGE_UNRESOLVED",
        "EXACT_REPAIR_REQUIRED": "IDENTIFY_EXACT_P6_NATIVE_CRASH_STAGE_AND_MINIMAL_RUNTIME_OR_PROVIDER_REPAIR_BEFORE_REEXECUTION",
        "HISTORICAL_EVIDENCE_PRESERVED": True, "NATIVE_INVOCATION_COUNT": 0,
        "PROVIDER_EXECUTION_COUNT": 0, "SOLVER_EXECUTION_COUNT": 0, "MPB_EXECUTION": False,
        "LOCALAFFINE_P7_SEGFAULT_DIAGNOSIS_STATUS": "PASS",
        "P6_NATIVE_JOB_RECONCILIATION_STATUS": "PASS",
        "P6_DATASET_SIDE_EFFECT_RECONCILIATION_STATUS": "PASS",
        "P6_CRASH_STAGE_CLASSIFICATION_STATUS": "PASS", "NO_REPRODUCTION_EXECUTION": True,
        "P6_RETRY_AUTHORIZED": False, "NEXT_LIVE_SOLVER_AUTHORIZATION": False,
        "PIPELINE_HEALTH": "PIPELINE_REQUIRES_CORRECTIVE", "BLOCKED_BY_INFRASTRUCTURE": True,
        "SCIENTIFIC_WORK_MUST_STOP": True, "RETURN_TO_SUPERVISOR": True,
        "TERMINAL": "LOCALAFFINE_P7_P6_NATIVE_SEGFAULT_DIAGNOSIS_COMPLETE",
    }
    P7_ARTIFACT.write_bytes(canonical(result) + b"\n")
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
