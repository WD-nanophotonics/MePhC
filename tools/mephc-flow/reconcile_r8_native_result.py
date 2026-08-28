"""Fixed, solver-free reconciliation for the one R8 noncanonical result."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any


CONTROL_ROOT = Path("/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows")
CHECKOUT_ROOT = Path("/home/icy/.cache/mephc-runner/checkouts")
FLOW_STATE = Path("/home/icy/.local/state/mephc-runner/MEPHC/flow")
ORIGINAL_RUN_ID = "MEPHC-NATIVE-c8dd63e77e54e53975468308"
SOURCE_COMMIT = "c8eeaa4e5fa78e25a5b7df07510b446b1f6d6738"
EXPECTED_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
DATASET_ID = "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db"
DATASET_MANIFEST_SHA256 = "55828e4a0eb6e24914807e42d13fa113457ce080ffe37c947b3c0cd7af1281d7"
ENTRYPOINT_SHA256 = "e9d181caf46362a51230e7973a97c569c5921207b396f1a4e1084e6d60b7cee5"
GRAPH_SHA256 = "0b4f1c370a8d4cd9aab26b22220fc2444efe8b5f6439add3d2aad5048d91440b"
EXPECTED_STDOUT_SHA256 = "8bc2019b4965d389d6a6791f816ca8ba07026b62b3c91191d90a729fbe98d6b9"
EXPECTED_STDOUT_SIZE = 553533
EXPECTED_STDERR_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EXPECTED_STDERR_SIZE = 0
MARKER = b"MEPHC_NATIVE_RESULT_JSON="
MAX_RESULT_BYTES = 65536
TAIL_BYTES = MAX_RESULT_BYTES * 2 + len(MARKER) + 4096
SCIENCE_CONTRACT_ID = "E9F_QP_B_C2_C3_R8_LOCKED_SET"
PUBLIC_BINDING = CONTROL_ROOT / "audit" / "e9f" / "qp_b_c2_c3_r8_d3_acquisition_binding.json"


class ReconciliationError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"JSON_READ_FAILED:{path.name}") from exc


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ReconciliationError(f"MODULE_UNAVAILABLE:{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_checkout() -> Path:
    checkout = CHECKOUT_ROOT / SOURCE_COMMIT
    if not checkout.is_dir():
        raise ReconciliationError("EXACT_CHECKOUT_UNAVAILABLE")
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=False, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode or result.stdout.strip() != SOURCE_COMMIT:
        raise ReconciliationError("EXACT_CHECKOUT_MISMATCH")
    return checkout


def historical_marker(stdout_path: Path, native_helper: Any) -> dict[str, Any]:
    with stdout_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - TAIL_BYTES), os.SEEK_SET)
        tail = handle.read(TAIL_BYTES)
    lines = [line.strip() for line in tail.splitlines() if line.strip().startswith(MARKER)]
    if len(lines) != 1:
        raise ReconciliationError("HISTORICAL_MARKER_COUNT_INVALID")
    payload = lines[0][len(MARKER):]
    if len(payload) > MAX_RESULT_BYTES:
        raise ReconciliationError("HISTORICAL_MARKER_OVERSIZED")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError("HISTORICAL_MARKER_MALFORMED") from exc
    if not isinstance(value, dict) or not native_helper._summary_is_safe(value):
        raise ReconciliationError("HISTORICAL_MARKER_UNSAFE")
    return value


def validate_original_run() -> tuple[dict[str, Any], Path, Path]:
    state_path = FLOW_STATE / "native-runs" / f"{ORIGINAL_RUN_ID}.json"
    value = read_json(state_path)
    if not isinstance(value, dict) or value.get("run_id") != ORIGINAL_RUN_ID:
        raise ReconciliationError("ORIGINAL_NATIVE_RUN_ID_MISMATCH")
    expected = {
        "source_commit": SOURCE_COMMIT,
        "state": "failed",
        "return_code": 0,
        "result_error": "RESULT_SUMMARY_NOT_CANONICAL",
        "process_started": True,
        "cost": 1,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ReconciliationError("ORIGINAL_NATIVE_RUN_STATE_MISMATCH")
    stdout_path = state_path.with_suffix(".stdout.log")
    stderr_path = state_path.with_suffix(".stderr.log")
    if (sha256_file(stdout_path), stdout_path.stat().st_size) != (EXPECTED_STDOUT_SHA256, EXPECTED_STDOUT_SIZE):
        raise ReconciliationError("ORIGINAL_STDOUT_PROVENANCE_MISMATCH")
    if (sha256_file(stderr_path), stderr_path.stat().st_size) != (EXPECTED_STDERR_SHA256, EXPECTED_STDERR_SIZE):
        raise ReconciliationError("ORIGINAL_STDERR_PROVENANCE_MISMATCH")
    return value, stdout_path, stderr_path


def validate_summary(marker: dict[str, Any], manifest: dict[str, Any], namespace_id: str) -> dict[str, Any]:
    authoritative = {
        "science_contract_id": manifest["science_contract_id"],
        "source_commit": SOURCE_COMMIT,
        "acquisition_source_commit": SOURCE_COMMIT,
        "entrypoint_sha256": ENTRYPOINT_SHA256,
        "graph_sha256": GRAPH_SHA256,
        "logical_provider_demand_count": 216,
        "unique_provider_request_count": 210,
        "duplicate_logical_demand_count": 6,
        "unique_request_count_by_resolution": {"R96": 70, "R128": 70, "R160": 70},
        "provider_request_count": 210,
        "cache_reuse_count": 0,
        "fresh_provider_execution_count": 210,
        "fresh_native_solver_execution_count": 210,
        "fresh_mpb_execution_observed": True,
        "mpb_execution_observed": True,
        "dataset_is_mpb_backed": True,
        "acquisition_dataset_id": DATASET_ID,
        "acquisition_dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "completed_key_count": 210,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "opaque_retention_namespace_id": namespace_id,
    }
    if set(marker) != set(authoritative):
        raise ReconciliationError("HISTORICAL_MARKER_FIELDS_MISMATCH")
    if any(marker[key] != value for key, value in authoritative.items()):
        raise ReconciliationError("HISTORICAL_MARKER_SEMANTIC_MISMATCH")
    return authoritative


def write_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(value) + b"\n"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        existing = read_json(path)
        if not isinstance(existing, dict) or any(existing.get(key) != value.get(key) for key in (
                "schema", "original_native_run_id", "reconciliation_status",
                "canonical_result_summary_sha256")):
            raise ReconciliationError("RECONCILIATION_RECORD_CONFLICT")
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def reconcile() -> dict[str, Any]:
    checkout = exact_checkout()
    native_helper = load_module("_mephc_reconcile_native_helper", checkout / "tools" / "mephc-flow" / "wsl_native_exec.py")
    science = load_module("_mephc_reconcile_science_runtime", checkout / "tools" / "mephc-flow" / "mephc_science_runtime.py")
    entrypoint = load_module("_mephc_reconcile_entrypoint", checkout / "audit" / "e9f" / "qp_b_c2_c3_r8_locked_set_native.py")
    original, stdout_path, _ = validate_original_run()
    marker = historical_marker(stdout_path, native_helper)
    binding = {
        "acquisition_source_commit": SOURCE_COMMIT,
        "acquisition_dataset_id": DATASET_ID,
        "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "entrypoint_sha256": ENTRYPOINT_SHA256,
        "graph_sha256": GRAPH_SHA256,
    }
    dataset = science.open_r8_dataset(binding)
    manifest = dataset.manifest
    if (manifest.get("logical_provider_demand_count") != 216
            or manifest.get("unique_provider_request_count") != 210
            or manifest.get("completed_key_count") != 210
            or manifest.get("completion_state") != "COMPLETE"
            or len(manifest.get("records", [])) != 210
            or manifest.get("dataset_is_mpb_backed") is not True):
        raise ReconciliationError("IMMUTABLE_DATASET_SCOPE_INVALID")
    graph = entrypoint.load_frozen_graph()
    verified = entrypoint.verify_graph(graph)
    plan = entrypoint.build_provider_plan(graph)
    if verified["logical_provider_demand_count"] != 216 or len(plan) != 210:
        raise ReconciliationError("FROZEN_GRAPH_SCOPE_INVALID")
    plan_keys = {sha256_bytes(entrypoint.canonical_key(item["request_key"])) for item in plan}
    if set(dataset.records) != plan_keys:
        raise ReconciliationError("IMMUTABLE_DATASET_KEY_SET_MISMATCH")
    namespace_id = dataset.retention.namespace_id
    summary = validate_summary(marker, manifest, namespace_id)
    integrity_pass_count = 0
    for item in plan:
        payload = dataset.lookup_exact(entrypoint.canonical_key(item["request_key"]))
        del payload
        integrity_pass_count += 1
    if integrity_pass_count != 210:
        raise ReconciliationError("IMMUTABLE_DATASET_INTEGRITY_INCOMPLETE")
    summary_sha256 = sha256_bytes(canonical_bytes(summary))
    reconciliation_id = "MEPHC-RECON-" + sha256_bytes(canonical_bytes({
        "run_id": ORIGINAL_RUN_ID, "dataset_id": DATASET_ID,
        "manifest_sha256": DATASET_MANIFEST_SHA256,
    }))[:24]
    current_commit = subprocess.run(
        ["git", "-C", str(CONTROL_ROOT), "rev-parse", "HEAD"],
        check=False, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()
    if len(current_commit) != 40 or any(character not in "0123456789abcdef" for character in current_commit):
        raise ReconciliationError("RECONCILIATION_SOURCE_COMMIT_MISMATCH")
    record = {
        "schema": "mephc-flow-native-result-reconciliation-v1",
        "reconciliation_id": reconciliation_id,
        "original_native_run_id": ORIGINAL_RUN_ID,
        "original_native_run_state": original["state"],
        "original_failure_reason": original["result_error"],
        "original_source_commit": SOURCE_COMMIT,
        "original_stdout_sha256": EXPECTED_STDOUT_SHA256,
        "original_stdout_size_bytes": EXPECTED_STDOUT_SIZE,
        "original_stderr_sha256": EXPECTED_STDERR_SHA256,
        "original_stderr_size_bytes": EXPECTED_STDERR_SIZE,
        "reconciliation_source_commit": current_commit,
        "acquisition_binding": binding,
        "immutable_dataset_validation_status": "PASS",
        "full_record_integrity_pass_count": integrity_pass_count,
        "canonical_result_summary": summary,
        "canonical_result_summary_sha256": summary_sha256,
        "reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED",
        "reconciled_at": time.time(),
    }
    record_path = FLOW_STATE / "reconciliations" / f"{ORIGINAL_RUN_ID}.json"
    write_once(record_path, record)
    record_sha256 = sha256_file(record_path)
    public = {
        "schema": "mephc_e9f_c2_c3_r8_d3_acquisition_binding_v1",
        "original_native_run_id": ORIGINAL_RUN_ID,
        "acquisition_source_commit": SOURCE_COMMIT,
        "acquisition_dataset_id": DATASET_ID,
        "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "entrypoint_sha256": ENTRYPOINT_SHA256,
        "graph_sha256": GRAPH_SHA256,
        "logical_provider_demand_count": 216,
        "unique_provider_request_count": 210,
        "duplicate_logical_demand_count": 6,
        "completed_key_count": 210,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "original_stdout_sha256": EXPECTED_STDOUT_SHA256,
        "original_stdout_size_bytes": EXPECTED_STDOUT_SIZE,
        "original_stderr_sha256": EXPECTED_STDERR_SHA256,
        "original_stderr_size_bytes": EXPECTED_STDERR_SIZE,
        "reconciliation_id": reconciliation_id,
        "reconciliation_record_sha256": record_sha256,
        "reconciliation_status": record["reconciliation_status"],
    }
    if PUBLIC_BINDING.is_file():
        if read_json(PUBLIC_BINDING) != public:
            raise ReconciliationError("PUBLIC_BINDING_CONFLICT")
    else:
        PUBLIC_BINDING.parent.mkdir(parents=True, exist_ok=True)
        temporary = PUBLIC_BINDING.with_name(f".{PUBLIC_BINDING.name}.{os.getpid()}.tmp")
        temporary.write_bytes(canonical_bytes(public) + b"\n")
        os.replace(temporary, PUBLIC_BINDING)
    return {
        "schema": "mephc-flow-r8-reconciliation-result-v1",
        "reconciliation_status": record["reconciliation_status"],
        "reconciliation_id": reconciliation_id,
        "reconciliation_record_sha256": record_sha256,
        "original_native_run_id": ORIGINAL_RUN_ID,
        "original_native_run_state": original["state"],
        "original_result_error": original["result_error"],
        "acquisition_dataset_id": DATASET_ID,
        "acquisition_dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
        "immutable_dataset_validation_status": "PASS",
        "full_record_integrity_pass_count": integrity_pass_count,
        "canonical_result_summary_sha256": summary_sha256,
        "public_acquisition_binding_status": "PASS",
        "native_invocation_count": 0,
        "mpb_execution": False,
    }


def main() -> int:
    try:
        print(json.dumps(reconcile(), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except ReconciliationError as exc:
        print(json.dumps({"ok": False, "error_code": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
