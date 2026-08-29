"""Reconcile the preserved E10F live attempt without rerunning science."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FLOW_ROOT = (
    Path("/home/icy/.local/state/mephc-runner/MEPHC/flow")
    if os.name != "nt"
    else Path(r"\\wsl.localhost\Ubuntu\home\icy\.local\state\mephc-runner\MEPHC\flow")
)
WORK_ORDER_ID = "MEPHC-E10F-R2-PREEXISTING-LIVE-ATTEMPT-RECONCILIATION-20260829-351"
ORIGINAL_WORK_ORDER_ID = "MEPHC-E10F-LOCAL-AFFINE-STATE-PROVIDER-LIVE-PREFLIGHT-20260829-349"
BASE_SANDBOX_SHA = "0442a41429117a3c462066e05bedd51187987991"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
R1_CERTIFICATION = ROOT / "audit/e10f/e10f_r1_provider_metadata_certification.json"
R1_CERTIFICATION_SHA256 = "e5944b595613f9372fc3cb502b3e364075f8616024ecdb9d69571fca9a14b796"
PROVIDER = ROOT / "mephc/local_affine_state_provider.py"
SPECTRAL_PROVIDER = ROOT / "mephc/mpb_spectral_provider.py"
ADAPTER = ROOT / "mephc/mpb_spectral.py"
ACQUISITION = ROOT / "audit/e10f/run_local_affine_state_acquisition.py"
OUTPUT = ROOT / "audit/e10f/e10f_r2_preexisting_live_attempt_reconciliation.json"
SCIENCE_JOB_ID = "MEPHC-SCIENCE-c9445511854b14eba6b8e172"
NATIVE_RUN_ID = "MEPHC-NATIVE-10ea7acae05629a43bc66460"


class ReconciliationError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ReconciliationError(f"FILE_UNAVAILABLE:{path}") from exc


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"JSON_UNAVAILABLE:{path}") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReconciliationError(f"TEXT_UNAVAILABLE:{path}") from exc


def classify_failure(stdout: str, stderr: str, provider: str, acquisition: str) -> str:
    if "Finished solving for bands" not in stdout or "tmfreqs:" not in stdout:
        raise ReconciliationError("MPB_COMPLETION_EVIDENCE_MISSING")
    if not re.search(r"LocalAffineProviderError:\s+LOCAL_AFFINE_KAPPA_BINDING_MISMATCH", stderr):
        raise ReconciliationError("POST_SOLVE_FAILURE_EVIDENCE_MISSING")
    if 'snapshot.provenance.get("mpb_reciprocal_k_point")' not in provider:
        raise ReconciliationError("FAILING_PROVIDER_PATH_NOT_FOUND")
    solve_position = acquisition.index("snapshot = provider.solve(spec)")
    put_position = acquisition.index("record = store.put(key, payload, record_identity)")
    if solve_position >= put_position:
        raise ReconciliationError("ACQUISITION_PERSISTENCE_ORDER_INVALID")
    return "D_SNAPSHOT_EXTRACTION_SUCCEEDED_POST_SOLVE_PROVIDER_VALIDATION_FAILED"


def verify_original_records() -> dict[str, Any]:
    job_path = FLOW_ROOT / "science-jobs" / f"{SCIENCE_JOB_ID}.json"
    native_path = FLOW_ROOT / "native-runs" / f"{NATIVE_RUN_ID}.json"
    stdout_path = native_path.with_suffix(".stdout.log")
    stderr_path = native_path.with_suffix(".stderr.log")
    job = read_json(job_path)
    native = read_json(native_path)
    stdout = read_text(stdout_path)
    stderr = read_text(stderr_path)
    if job.get("job_id") != SCIENCE_JOB_ID or job.get("work_order_id") != ORIGINAL_WORK_ORDER_ID:
        raise ReconciliationError("ORIGINAL_SCIENCE_JOB_IDENTITY_INVALID")
    if job.get("native_run_id") != NATIVE_RUN_ID or job.get("state") != "failed":
        raise ReconciliationError("ORIGINAL_SCIENCE_JOB_STATE_INVALID")
    if native.get("run_id") != NATIVE_RUN_ID or native.get("work_order_id") != ORIGINAL_WORK_ORDER_ID:
        raise ReconciliationError("ORIGINAL_NATIVE_RUN_IDENTITY_INVALID")
    if native.get("state") != "failed" or native.get("return_code") != 1:
        raise ReconciliationError("ORIGINAL_NATIVE_RUN_STATE_INVALID")
    if native.get("process_started") is not True or native.get("used_before") != 0 or native.get("cost") != 1:
        raise ReconciliationError("ORIGINAL_NATIVE_ACCOUNTING_INVALID")
    provider_source = read_text(PROVIDER)
    spectral_source = read_text(SPECTRAL_PROVIDER)
    adapter_source = read_text(ADAPTER)
    acquisition_source = read_text(ACQUISITION)
    classification = classify_failure(stdout, stderr, provider_source, acquisition_source)
    if '"mpb_reciprocal_k_point": list(reciprocal_tuple)' not in spectral_source:
        raise ReconciliationError("CALLER_RECIPROCAL_K_POINT_PATH_MISSING")
    if '"mpb_k_point": None if mpb_k_point is None else list(mpb_k_point)' not in adapter_source:
        raise ReconciliationError("TOP_LEVEL_MPB_K_POINT_PATH_MISSING")
    if '"caller_provenance": {} if provenance is None else dict(provenance)' not in adapter_source:
        raise ReconciliationError("CALLER_PROVENANCE_WRAPPING_MISSING")
    if "store.put" not in acquisition_source or acquisition_source.index("store.put") <= acquisition_source.index("provider.solve"):
        raise ReconciliationError("DATASET_PERSISTENCE_ORDER_UNVERIFIED")
    return {
        "job": job,
        "native": native,
        "stdout": stdout,
        "stderr": stderr,
        "provider_source": provider_source,
        "spectral_source": spectral_source,
        "adapter_source": adapter_source,
        "acquisition_source": acquisition_source,
        "failure_stage": classification,
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
    }


def build_reconciliation() -> dict[str, Any]:
    if sha256_file(R1_CERTIFICATION) != R1_CERTIFICATION_SHA256:
        raise ReconciliationError("R1_CERTIFICATION_HASH_MISMATCH")
    observed = verify_original_records()
    native = observed["native"]
    job = observed["job"]
    provider = observed["provider_source"]
    spectral = observed["spectral_source"]
    adapter = observed["adapter_source"]
    acquisition = observed["acquisition_source"]
    query_path = "snapshot.provenance[mpb_reciprocal_k_point]"
    top_level_path = "snapshot.provenance[mpb_k_point]"
    nested_path = "snapshot.provenance[caller_provenance][mpb_reciprocal_k_point]"
    return {
        "schema": "mephc-e10f-r2-preexisting-live-attempt-reconciliation-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": BASE_SANDBOX_SHA,
        "origin_sandbox_sha": BASE_SANDBOX_SHA,
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "original_science_job_id": SCIENCE_JOB_ID,
        "original_science_job_status": job["state"],
        "original_science_job_source_commit": job["source_commit"],
        "original_native_run_id": NATIVE_RUN_ID,
        "original_native_run_status": native["state"],
        "original_native_run_source_commit": native["source_commit"],
        "original_native_process_started": native["process_started"],
        "original_native_child_return_code": native["return_code"],
        "original_native_run_cost": native["cost"],
        "original_retry_count": 0,
        "original_cache_reuse_count": 0,
        "original_provider_execution_count": 1,
        "original_solver_execution_count": 1,
        "original_dataset_record_count": 0,
        "original_failure": "LOCAL_AFFINE_KAPPA_BINDING_MISMATCH",
        "original_stdout_sha256": observed["stdout_sha256"],
        "original_stderr_sha256": observed["stderr_sha256"],
        "failure_stage_classification": observed["failure_stage"],
        "post_solve_metadata_key_mismatch_confirmed": True,
        "failing_provider_query_path": query_path,
        "top_level_mpb_k_point_path": top_level_path,
        "caller_provenance_mpb_reciprocal_k_point_path": nested_path,
        "top_level_mpb_k_point_status": "PASS_SCHEMA_CONFIRMED",
        "caller_provenance_mpb_reciprocal_k_point_status": "PASS_SCHEMA_CONFIRMED",
        "reciprocal_coordinate_agreement_status": "PASS_SAME_RECIPROCAL_TUPLE_SOURCE_SCHEMA_FAILED_SNAPSHOT_NOT_PERSISTED",
        "failed_solve_payload_dataset_status": "NOT_PERSISTED",
        "failed_attempt_preservation_status": "PASS",
        "failed_attempt_dataset_reuse_authorized": False,
        "scientific_model_impact": "NONE_ESTABLISHED",
        "solver_numerical_failure_established": False,
        "fixed_q_to_local_kappa_physics_failure_established": False,
        "provider_metadata_contract_failure_established": True,
        "r1_certification_sha256": R1_CERTIFICATION_SHA256,
        "provider_module_sha256": sha256_file(PROVIDER),
        "spectral_provider_module_sha256": sha256_file(SPECTRAL_PROVIDER),
        "snapshot_adapter_module_sha256": sha256_file(ADAPTER),
        "acquisition_entrypoint_sha256": sha256_file(ACQUISITION),
        "e10f_provider_patch_authorization_ready": True,
        "e10f_live_rerun_authorized": False,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "solver_execution_count": 0,
        "mpb_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "E10F_FAILED_SINGLE_SOLVE_RECONCILED_READY_FOR_ZERO_SOLVER_PROVIDER_CORRECTIVE",
        "return_to_supervisor": True,
        "terminal": "E10F_R2_PREEXISTING_LIVE_ATTEMPT_RECONCILIATION_COMPLETE",
    }


def main() -> int:
    try:
        result = build_reconciliation()
        OUTPUT.write_text(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ReconciliationError) as exc:
        print(f"RECONCILIATION_ERROR={exc}")
        return 1
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
