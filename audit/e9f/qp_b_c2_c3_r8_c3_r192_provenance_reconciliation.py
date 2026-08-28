"""Solver-free reconciliation of the existing R192 acquisition."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ACQUISITION = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_acquisition.py"
GRAPH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_request_graph.json"
ARTIFACT = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_provenance_reconciliation.json"
BINDING = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_acquisition_binding.json"
RUNTIME = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
SCIENTIFIC_JOB = ROOT / "tools/mephc-flow/scientific_job.py"
NATIVE_HELPER = ROOT / "tools/mephc-flow/wsl_native_exec.py"

WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C3-R1-20260828-310"
ORIGINAL_WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C3-A1-20260828-307"
TARGET_SOURCE_COMMIT = "f468e6016fed3019fcdf5937722abf47d20995e6"
TARGET_DECLARED_SOURCE_COMMIT = "56f7e51a2cb910a7187d982366a492c9cb17bd09"
TARGET_ENTRYPOINT_SHA256 = "2e690c68a1a270189d15cbaf1a9c173f684c64acf6309c8635d72cc395c18b2f"
TARGET_GRAPH_SHA256 = "c0dc7ba7600e2bd18a7c57cb91683ece237f432cb68e70f325725535a0091008"
TARGET_RUNTIME_SHA256 = "d292915b021769ae3c5ee2be3181b6aef4acf021bb178ec2af5ea6ac9905f022"
PARENT_DATASET_ID = "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db"
PARENT_MANIFEST_SHA256 = "55828e4a0eb6e24914807e42d13fa113457ce080ffe37c947b3c0cd7af1281d7"
RAW_DATASET_ID = "446ad69a302c9eb3524b67fe2127701030f62986dd1ccc570e3b0830a3dc488c"
RAW_MANIFEST_SHA256 = "4db0377cf2126fcc1ed8fb4b74a0ed6a2bd0ccf2e58e4a22e922262bc427d7d5"
RESOLUTION = "R192"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"


class ReconciliationError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ReconciliationError("FILE_UNAVAILABLE", str(path.name)) from exc


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError("JSON_UNAVAILABLE", str(path.name)) from exc
    if not isinstance(value, dict):
        raise ReconciliationError("JSON_OBJECT_REQUIRED", str(path.name))
    return value


def load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ReconciliationError("FRAMEWORK_MODULE_UNAVAILABLE", str(path.name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime():
    return load_module("_mephc_r192_reconciliation_runtime", RUNTIME)


def load_job_framework():
    return load_module("_mephc_r192_reconciliation_job", SCIENTIFIC_JOB)


def load_native_helper():
    return load_module("_mephc_r192_reconciliation_native_helper", NATIVE_HELPER)


def load_acquisition():
    return load_module("_mephc_r192_reconciliation_acquisition", ACQUISITION)


def git_value(checkout: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ReconciliationError("EXECUTION_CHECKOUT_GIT_UNAVAILABLE")
    return result.stdout.strip()


def find_original_lineage(flow_root: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    jobs = []
    for path in sorted(flow_root.joinpath("science-jobs").glob("MEPHC-SCIENCE-*.json")):
        value = read_json(path)
        if value.get("work_order_id") == ORIGINAL_WORK_ORDER_ID:
            jobs.append((value, path))
    if len(jobs) != 1:
        raise ReconciliationError("ORIGINAL_LINEAGE_COUNT_INVALID", str(len(jobs)))
    job, _ = jobs[0]
    if job.get("source_commit") != TARGET_SOURCE_COMMIT or not isinstance(job.get("native_run_id"), str):
        raise ReconciliationError("ORIGINAL_LINEAGE_SOURCE_INVALID")
    native_path = flow_root / "native-runs" / f"{job['native_run_id']}.json"
    native = read_json(native_path)
    if native.get("work_order_id") != ORIGINAL_WORK_ORDER_ID or native.get("source_commit") != TARGET_SOURCE_COMMIT:
        raise ReconciliationError("ORIGINAL_NATIVE_LINEAGE_INVALID")
    stdout_path = native_path.with_suffix(".stdout.log")
    stderr_path = native_path.with_suffix(".stderr.log")
    if not stdout_path.is_file() or not stderr_path.is_file():
        raise ReconciliationError("ORIGINAL_NATIVE_LOGS_UNAVAILABLE")
    return job, native, stdout_path, stderr_path


def verify_target_checkout() -> None:
    checkout = Path("/home/icy/.cache/mephc-runner/checkouts") / TARGET_SOURCE_COMMIT
    if not checkout.is_dir():
        raise ReconciliationError("EXECUTION_CHECKOUT_UNAVAILABLE")
    if git_value(checkout, "rev-parse", "HEAD") != TARGET_SOURCE_COMMIT:
        raise ReconciliationError("EXECUTION_CHECKOUT_HEAD_MISMATCH")
    fstype = subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "--target", str(checkout)], capture_output=True, text=True, check=False).stdout.strip().lower()
    if not fstype or fstype in {"9p", "drvfs", "fuseblk"}:
        raise ReconciliationError("EXECUTION_CHECKOUT_NOT_LINUX_NATIVE")
    entrypoint = checkout / "audit/e9f/qp_b_c2_c3_r8_c3_r192_acquisition.py"
    graph = checkout / "audit/e9f/qp_b_c2_c3_r8_c3_r192_request_graph.json"
    if sha256_file(entrypoint) != TARGET_ENTRYPOINT_SHA256 or sha256_file(graph) != TARGET_GRAPH_SHA256:
        raise ReconciliationError("EXECUTION_CODE_IDENTITY_MISMATCH")
    if load_job_framework().runtime_hash(checkout) != TARGET_RUNTIME_SHA256:
        raise ReconciliationError("EXECUTION_RUNTIME_IDENTITY_MISMATCH")


def parse_original_result(stdout_path: Path, native: dict[str, Any]) -> dict[str, Any]:
    try:
        summary = load_native_helper().extract_result_summary(stdout_path)
    except (ValueError, OSError) as exc:
        raise ReconciliationError("ORIGINAL_RESULT_MARKER_INVALID", str(exc)) from exc
    if summary.get("R192_dataset_id") != RAW_DATASET_ID or summary.get("R192_dataset_manifest_sha256") != RAW_MANIFEST_SHA256:
        raise ReconciliationError("ORIGINAL_RESULT_DATASET_ID_MISMATCH")
    if summary.get("R192_entrypoint_sha256") != TARGET_ENTRYPOINT_SHA256 or summary.get("R192_request_graph_sha256") != TARGET_GRAPH_SHA256:
        raise ReconciliationError("ORIGINAL_RESULT_CODE_IDENTITY_MISMATCH")
    if summary.get("R192_acquisition_source_commit") != TARGET_DECLARED_SOURCE_COMMIT:
        raise ReconciliationError("ORIGINAL_RESULT_DECLARED_SOURCE_MISMATCH")
    if summary.get("logical_provider_demand_count") != 72 or summary.get("provider_request_count") != 70:
        raise ReconciliationError("ORIGINAL_RESULT_ACCOUNTING_MISMATCH")
    if summary.get("native_solves") != 70 or summary.get("mpb_execution") is not True:
        raise ReconciliationError("ORIGINAL_RESULT_EXECUTION_MISMATCH")
    if native.get("result_error") != "RESULT_SUMMARY_UNSAFE":
        raise ReconciliationError("HISTORICAL_RESULT_ERROR_MISMATCH")
    return summary


def candidate_matches(manifest: dict[str, Any], generic: dict[str, Any], summary: dict[str, Any]) -> bool:
    return (
        manifest.get("schema") == "mephc_direct_flow_r8_acquisition_dataset_v1"
        and manifest.get("dataset_id") == RAW_DATASET_ID
        and manifest.get("manifest_sha256") == RAW_MANIFEST_SHA256
        and manifest.get("resolution") == RESOLUTION
        and manifest.get("acquisition_source_commit") == TARGET_DECLARED_SOURCE_COMMIT
        and manifest.get("entrypoint_sha256") == TARGET_ENTRYPOINT_SHA256
        and manifest.get("graph_sha256") == TARGET_GRAPH_SHA256
        and manifest.get("parent_dataset_id") == PARENT_DATASET_ID
        and manifest.get("source_model_identity") == "FROZEN_QP_B_SOURCE_MODEL"
        and manifest.get("provider_configuration_identity") == "FROZEN_QP_B_PROVIDER_CONFIGURATION"
        and manifest.get("band_request_configuration") == "FROZEN_QP_B_LOCKED_BAND_REQUEST"
        and manifest.get("completed_key_count") == 70
        and len(manifest.get("records", [])) == 70
        and manifest.get("completion_state") == "COMPLETE"
        and manifest.get("dataset_is_mpb_backed") is True
        and manifest.get("fresh_provider_execution_count") == 70
        and manifest.get("cache_reuse_count") == 0
        and generic.get("namespace", {}).get("source_commit") == TARGET_DECLARED_SOURCE_COMMIT
        and summary.get("R192_dataset_id") == manifest.get("dataset_id")
    )


def locate_dataset(state_root: Path, summary: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidates = []
    for path in state_root.joinpath("datasets").glob("*/acquisition-dataset-manifest.json"):
        manifest = read_json(path)
        generic = read_json(path.parent / "dataset-manifest.json")
        if candidate_matches(manifest, generic, summary):
            candidates.append((path, manifest, generic, generic.get("namespace", {})))
    if len(candidates) != 1:
        raise ReconciliationError("R192_DATASET_CANDIDATE_COUNT_INVALID", str(len(candidates)))
    return candidates[0]


def verify_manifest(manifest: dict[str, Any], generic: dict[str, Any], namespace: dict[str, Any]) -> None:
    unsigned_id = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    if sha256_bytes(canonical(unsigned_id)) != manifest.get("dataset_id"):
        raise ReconciliationError("R192_DATASET_ID_INTEGRITY_INVALID")
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if sha256_bytes(canonical(unsigned_manifest)) != manifest.get("manifest_sha256"):
        raise ReconciliationError("R192_MANIFEST_SHA_INTEGRITY_INVALID")
    if generic.get("completion_state") != "COMPLETE" or generic.get("record_count") != 70:
        raise ReconciliationError("GENERIC_DATASET_MANIFEST_INVALID")
    if namespace.get("source_commit") != TARGET_DECLARED_SOURCE_COMMIT or namespace.get("resolution") != RESOLUTION:
        raise ReconciliationError("R192_NAMESPACE_IDENTITY_INVALID")


def verify_records(state_root: Path, manifest: dict[str, Any]) -> int:
    acquisition = load_acquisition()
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    if sha256_file(GRAPH) != TARGET_GRAPH_SHA256:
        raise ReconciliationError("CURRENT_GRAPH_SHA_MISMATCH")
    expected_plan = acquisition.build_provider_plan(graph)
    expected = {hashlib.sha256(acquisition.canonical_key(item["request_key"])).hexdigest(): item["request_key"] for item in expected_plan}
    records = manifest.get("records")
    if not isinstance(records, list) or {item.get("key_sha256") for item in records} != set(expected):
        raise ReconciliationError("R192_RECORD_KEY_SET_INVALID")
    generic = load_job_framework().ImmutableDatasetStore(state_root, {
        "project_id": "MEPHC", "science_contract_id": "E9F_QP_B_C2_C3_R8_LOCKED_SET_R192",
        "source_commit": TARGET_DECLARED_SOURCE_COMMIT, "work_order_id": ORIGINAL_WORK_ORDER_ID,
        "resolution": RESOLUTION, "entrypoint_sha256": TARGET_ENTRYPOINT_SHA256,
        "graph_sha256": TARGET_GRAPH_SHA256, "science_runtime_sha256": TARGET_RUNTIME_SHA256,
    })
    runtime = load_runtime()
    metadata_by_key = {item["key_sha256"]: item for item in records}
    passed = 0
    for key_sha, request_key in expected.items():
        key = acquisition.canonical_key(request_key)
        try:
            payload, metadata = generic.get(key)
        except Exception as exc:
            raise ReconciliationError("R192_RECORD_INTEGRITY_FAILED", key_sha) from exc
        record = metadata_by_key[key_sha]
        if (metadata.get("key_sha256") != key_sha
                or metadata.get("payload_sha256") != record.get("payload_sha256")
                or metadata.get("payload_size_bytes") != record.get("payload_size_bytes")):
            raise ReconciliationError("R192_RECORD_METADATA_MISMATCH", key_sha)
        identity = metadata.get("identity", {})
        if (identity.get("resolution") != RESOLUTION
                or identity.get("source_model_identity") != "FROZEN_QP_B_SOURCE_MODEL"
                or identity.get("provider_configuration_identity") != "FROZEN_QP_B_PROVIDER_CONFIGURATION"
                or identity.get("band_request_configuration") != "FROZEN_QP_B_LOCKED_BAND_REQUEST"):
            raise ReconciliationError("R192_RECORD_SCIENTIFIC_IDENTITY_MISMATCH", key_sha)
        try:
            decoded = runtime.decode_snapshot(payload)
            coordinate = request_key["canonical_k_coordinate_units_1_over_144"]
            expected_point = (coordinate["i"] / 144.0, coordinate["j"] / 144.0)
            if (decoded.provenance.get("representation") != H_REPRESENTATION
                    or tuple(decoded.k_point) != expected_point):
                raise ReconciliationError("R192_DECODED_SCIENTIFIC_IDENTITY_MISMATCH", key_sha)
        except ReconciliationError:
            raise
        except Exception as exc:
            raise ReconciliationError("R192_PAYLOAD_DECODE_FAILED", key_sha) from exc
        del decoded, payload, metadata
        passed += 1
    if passed != 70:
        raise ReconciliationError("R192_RECORD_PASS_COUNT_INVALID", str(passed))
    return passed


def reconciliation_content(job: dict[str, Any], native: dict[str, Any], stdout: Path, stderr: Path,
                           manifest: dict[str, Any], record_count: int) -> dict[str, Any]:
    return {
        "schema": "mephc-r8-c3-r192-provenance-reconciliation-v1",
        "work_order_id": WORK_ORDER_ID, "original_work_order_id": ORIGINAL_WORK_ORDER_ID,
        "original_science_job_id": job["job_id"], "original_native_run_id": native["run_id"],
        "raw_immutable_dataset_id": manifest["dataset_id"],
        "raw_immutable_dataset_manifest_sha256": manifest["manifest_sha256"],
        "raw_dataset_declared_source_commit": manifest["acquisition_source_commit"],
        "verified_execution_source_commit": TARGET_SOURCE_COMMIT,
        "entrypoint_sha256": TARGET_ENTRYPOINT_SHA256, "graph_sha256": TARGET_GRAPH_SHA256,
        "execution_runtime_sha256": TARGET_RUNTIME_SHA256, "parent_dataset_id": PARENT_DATASET_ID,
        "original_native_process_started": native.get("process_started") is True,
        "original_child_return_code": native.get("return_code"), "original_native_run_state": native.get("state"),
        "original_result_error": native.get("result_error"), "original_stdout_sha256": sha256_file(stdout),
        "original_stdout_size_bytes": stdout.stat().st_size, "original_stderr_sha256": sha256_file(stderr),
        "original_stderr_size_bytes": stderr.stat().st_size, "full_r192_record_integrity_pass_count": record_count,
        "acquisition_accounting": {"logical_provider_demand_count": 72, "unique_provider_request_count": 70,
                                    "fresh_provider_execution_count": 70, "cache_reuse_count": 0,
                                    "solver_execution_count": 70, "completed_key_count": 70,
                                    "failed_key_count": 0, "provider_failure_count": 0, "mpb_execution": True},
        "historical_result_summary_rejection": "RESULT_SUMMARY_UNSAFE",
        "provenance_defect_class": "HARDCODED_WORK_ORDER_BASE_USED_AS_ACQUISITION_SOURCE",
        "dataset_mutation": False,
        "reconciliation_status": "VERIFIED_EXECUTION_SOURCE_REBOUND_WITHOUT_DATASET_MUTATION",
        "canonical_reconciliation_sha256": None,
    }


def write_reconciliation(content: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in content.items() if key != "canonical_reconciliation_sha256"}
    digest = sha256_bytes(canonical(unsigned))
    content["canonical_reconciliation_sha256"] = digest
    load_job_framework().atomic_json(ARTIFACT, content)
    return digest


def write_public_binding(manifest: dict[str, Any], reconciliation_sha: str) -> None:
    value = {
        "schema": "mephc_e9f_qp_b_c2_c3_r8_c3_r192_acquisition_binding_v2",
        "work_order_id": WORK_ORDER_ID, "raw_immutable_dataset_id": manifest["dataset_id"],
        "raw_immutable_dataset_manifest_sha256": manifest["manifest_sha256"],
        "raw_dataset_declared_source_commit": manifest["acquisition_source_commit"],
        "verified_execution_source_commit": TARGET_SOURCE_COMMIT,
        "provenance_reconciliation_sha256": reconciliation_sha, "provenance_status": "RECONCILED",
        "R192_dataset_record_count": 70, "parent_dataset_id": PARENT_DATASET_ID,
        "entrypoint_sha256": TARGET_ENTRYPOINT_SHA256, "graph_sha256": TARGET_GRAPH_SHA256,
        "runtime_sha256": TARGET_RUNTIME_SHA256,
        "future_consumer_requires_reconciliation": True,
    }
    load_job_framework().atomic_json(BINDING, value)


def reconcile() -> dict[str, Any]:
    verify_target_checkout()
    flow_root = Path.home() / ".local/state/mephc-runner/MEPHC/flow"
    job, native, stdout, stderr = find_original_lineage(flow_root)
    summary = parse_original_result(stdout, native)
    state_root = load_runtime()._trusted_science_state_root()
    manifest_path, manifest, generic, namespace = locate_dataset(state_root, summary)
    before_manifest = manifest_path.read_bytes()
    before_generic = (manifest_path.parent / "dataset-manifest.json").read_bytes()
    verify_manifest(manifest, generic, namespace)
    record_count = verify_records(state_root, manifest)
    if manifest_path.read_bytes() != before_manifest or (manifest_path.parent / "dataset-manifest.json").read_bytes() != before_generic:
        raise ReconciliationError("R192_DATASET_MUTATED_DURING_RECONCILIATION")
    content = reconciliation_content(job, native, stdout, stderr, manifest, record_count)
    reconciliation_sha = write_reconciliation(content)
    write_public_binding(manifest, reconciliation_sha)
    return {
        "schema": "mephc-r8-c3-r192-provenance-reconciliation-v1", "result_schema": "mephc-r8-c3-r192-provenance-reconciliation-v1",
        "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": "5cde7414587adb95a25cec4fe542992db5395625",
        "final_sandbox_sha": "5cde7414587adb95a25cec4fe542992db5395625", "origin_sandbox_sha": "5cde7414587adb95a25cec4fe542992db5395625",
        "main_sha": "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5", "machine_contract_status": "PASS",
        "original_science_job_id": job["job_id"], "original_native_run_id": native["run_id"],
        "original_native_process_started": native.get("process_started") is True,
        "original_child_return_code": native.get("return_code"), "original_native_run_state": native.get("state"),
        "original_result_error": native.get("result_error"), "original_stdout_sha256": sha256_file(stdout),
        "original_stdout_size_bytes": stdout.stat().st_size, "original_stderr_sha256": sha256_file(stderr),
        "original_stderr_size_bytes": stderr.stat().st_size, "existing_r192_dataset_discovery_status": "EXACTLY_ONE_CANDIDATE",
        "existing_r192_dataset_id": manifest["dataset_id"], "existing_r192_dataset_manifest_sha256": manifest["manifest_sha256"],
        "existing_r192_dataset_record_count": 70, "existing_r192_manifest_declared_source_commit": manifest["acquisition_source_commit"],
        "verified_execution_source_commit": TARGET_SOURCE_COMMIT, "full_r192_record_integrity_pass_count": record_count,
        "acquisition_accounting_status": "VERIFIED_70_FRESH_PROVIDER_EXECUTIONS_NO_REUSE",
        "R192_provenance_reconciliation_status": "VERIFIED_EXECUTION_SOURCE_REBOUND_WITHOUT_DATASET_MUTATION",
        "R192_provenance_reconciliation_sha256": reconciliation_sha, "public_r192_acquisition_binding_status": "RECONCILED",
        "future_source_binding_fix_status": "CERTIFIED_EXECUTION_CHECKOUT_SOURCE_BOUND",
        "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False,
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "next_scientific_state": "R192_EXISTING_DATASET_PROVENANCE_RECONCILED_READY_FOR_SOLVER_FREE_FIXED_H_RESOLUTION_ANALYSIS",
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C3_R1_EXISTING_R192_DATASET_PROVENANCE_RECONCILED_READY_FOR_SOLVER_FREE_ANALYSIS",
    }


def main() -> int:
    try:
        result = reconcile()
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(result).decode("utf-8"))
        return 0
    except ReconciliationError as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-r8-c3-r192-provenance-reconciliation-v1", "state": "failed",
            "error_code": exc.code, "terminal": "E9F_C2_C3_R1_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
