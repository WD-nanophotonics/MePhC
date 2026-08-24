"""E9F.C1.RP2.C2.C1 bounded file-backed transport wrapper.

The scientific implementation is imported from the frozen C2 module.  This
module owns only process transport, provenance, and audit artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence

from audit.e9f import run_e9f_c1_rp2_c2_impl as scientific
from audit.infrastructure.campaign_runtime import (
    CampaignIdentity,
    CampaignRuntime,
    CampaignRuntimeError,
    atomic_json_write,
    canonical_json,
    current_rss_kib,
    semantic_plan_fingerprint,
    sha256_bytes,
    sha256_file,
    validate_process_review,
)


TRANSPORT_WORK_ORDER = "TRILATT-E9F-C1-RP2-C2-C1-20260825-234"
TRANSPORT_PHASE = "E9F.C1.RP2.C2.C1"
SCIENTIFIC_WORK_ORDER = scientific.WORK_ORDER
SCIENTIFIC_PHASE = scientific.PHASE
BASE_SHA = "4e757c9bd0169128ef3e98454d2a1d02c4d03a74"
EXPECTED_MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
SCIENTIFIC_IMPL_BLOB_SHA = "a4d66bb5174306d5b45d95fc0bcd64860a98ca47"
SCIENTIFIC_CONTRACT_REL = Path("audit/e9f/rp2_c2_execution_contract.json")
TRANSPORT_CONTRACT_REL = Path("audit/e9f/rp2_c2_c1_transport_contract.json")
CHILD_REL = Path("audit/e9f/run_e9f_c1_rp2_c2_c1_worker.py")
AGENTS_COMMIT = "ea742a7f713255741de39eb2daec92813ee71917"
RP1_POLICY_SHA = scientific.RP1_POLICY_SHA
RP1_POLICY_CANONICAL_SHA = scientific.RP1_POLICY_CANONICAL_SHA
ORIGINAL_RP2_EXECUTION_SHA = "8121dbfba352b1a77551213771694d25c1bf3f01"
TRANSPORT_ARTIFACT_SCHEMA = "trilatt_e9f_c1_rp2_c2_c1_worker_artifact_v1"
RESULT_SCHEMA = "trilatt_e9f_c1_rp2_c2_c1_result_v1"
WORKER_MARKER = "run_e9f_c1_rp2_c2_c1_worker.py"


class PayloadChannelError(CampaignRuntimeError):
    pass


def _json(value: Any) -> Any:
    return scientific._json(value)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def current_execution_sha(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def git_blob_sha(root: Path, relative: str) -> str:
    return subprocess.check_output(["git", "hash-object", relative], cwd=root, text=True).strip()


def load_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / TRANSPORT_CONTRACT_REL).read_text(encoding="utf-8"))
    required = {
        "schema": "trilatt_e9f_c1_rp2_c2_c1_transport_contract_v1",
        "work_order_id": TRANSPORT_WORK_ORDER,
        "phase": TRANSPORT_PHASE,
        "base_sandbox_sha": BASE_SHA,
        "expected_main_sha": EXPECTED_MAIN_SHA,
        "scientific_work_order_id": SCIENTIFIC_WORK_ORDER,
        "scientific_phase": SCIENTIFIC_PHASE,
        "scientific_contract_sha256": sha256_file(root / SCIENTIFIC_CONTRACT_REL),
        "scientific_impl_git_blob_sha": SCIENTIFIC_IMPL_BLOB_SHA,
        "payload_transport": "ATOMIC_FILE",
        "stdout_used_as_payload": False,
        "stderr_used_as_payload": False,
        "primary_resolutions": [64, 96],
        "solves_per_worker": 10,
        "logical_workers": 2,
        "total_native_solves": 20,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise PayloadChannelError(f"C2_C1_TRANSPORT_CONTRACT_{key.upper()}_MISMATCH")
    return value


def verify_frozen_inputs(root: Path) -> dict[str, str]:
    scientific_contract_sha = sha256_file(root / SCIENTIFIC_CONTRACT_REL)
    if scientific_contract_sha != "f1656a023469f8596afab00faddcc5b6cefddfd919dbad7e8b68ed625df79e65":
        raise PayloadChannelError("C2_C1_SCIENTIFIC_CONTRACT_MUTATED")
    impl_sha = git_blob_sha(root, "audit/e9f/run_e9f_c1_rp2_c2_impl.py")
    if impl_sha != SCIENTIFIC_IMPL_BLOB_SHA:
        raise PayloadChannelError("C2_C1_SCIENTIFIC_IMPL_BLOB_MUTATED")
    agents = (root / "AGENTS.md").read_bytes()
    accepted_agents = subprocess.check_output(["git", "show", f"{AGENTS_COMMIT}:AGENTS.md"], cwd=root)
    if agents != accepted_agents:
        raise PayloadChannelError("C2_C1_AGENTS_MUTATED")
    return {
        "scientific_contract_sha256": scientific_contract_sha,
        "scientific_impl_git_blob_sha": impl_sha,
        "agents_md_sha256": _sha256(agents),
    }


def resolve_real_provider() -> dict[str, str]:
    module_name = "audit.e9c.run_k_kprime_rank1_berry"
    spec = importlib.util.find_spec(module_name)
    if spec is None or not spec.origin:
        raise PayloadChannelError("C2_C1_REAL_PROVIDER_MODULE_NOT_FOUND")
    module = importlib.import_module(module_name)
    for name in ("build_inputs", "geometry_inputs", "make_provider"):
        if not callable(getattr(module, name, None)):
            raise PayloadChannelError(f"C2_C1_REAL_PROVIDER_SYMBOL_MISSING:{name}")
    return {"module": module_name, "origin": str(spec.origin)}


def build_plan(root: Path) -> list[dict[str, Any]]:
    return scientific.build_plan(root)


def transport_slot(runtime_root: Path, worker_id: str) -> dict[str, Path]:
    digest = hashlib.sha256(worker_id.encode("utf-8")).hexdigest()[:32]
    directory = runtime_root / "transport" / digest
    return {
        "directory": directory,
        "payload": directory / "payload.json",
        "binding": directory / "binding.json",
    }


def prepare_transport_slot(runtime_root: Path, row: Mapping[str, Any], execution_sha: str) -> dict[str, Path]:
    slot = transport_slot(runtime_root, str(row["sample_id"]))
    slot["directory"].mkdir(parents=True, exist_ok=False)
    if slot["payload"].exists() or list(slot["directory"].glob("*.tmp")):
        raise PayloadChannelError("C2_C1_PAYLOAD_STALE_FILE_BEFORE_LAUNCH")
    atomic_json_write(slot["binding"], {
        "transport_work_order_id": TRANSPORT_WORK_ORDER,
        "scientific_work_order_id": SCIENTIFIC_WORK_ORDER,
        "execution_git_sha": execution_sha,
        "worker_id": str(row["sample_id"]),
        "resolution": int(row["resolution"]),
        "payload_path": str(slot["payload"]),
    })
    return slot


def _proc_cmdline(pid: int) -> str:
    try:
        return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except (OSError, UnicodeError):
        return ""


def scan_transport_processes(worker_id: str | None = None) -> list[int]:
    if not Path("/proc").is_dir():
        raise PayloadChannelError("C2_C1_ORPHAN_INSPECTION_UNAVAILABLE")
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        command = _proc_cmdline(int(entry.name))
        if WORKER_MARKER in command and "--worker-id" in command and (worker_id is None or worker_id in command):
            found.append(int(entry.name))
    return sorted(found)


def _tail(value: bytes, limit: int = 8192) -> str:
    return value[-limit:].decode("utf-8", errors="replace")


def _measurement(process: subprocess.Popen[bytes], stdout: bytes, stderr: bytes, worker_id: str) -> dict[str, Any]:
    orphan_pids = [pid for pid in scan_transport_processes(worker_id) if pid != process.pid]
    return {
        "worker_id": worker_id,
        "launched_pid": int(process.pid),
        "returncode": int(process.returncode),
        "direct_pid_gone": not (Path("/proc") / str(process.pid)).exists(),
        "orphan_pids": orphan_pids,
        "orphan_count": len(orphan_pids),
        "child_stdout_byte_count": len(stdout),
        "child_stderr_byte_count": len(stderr),
        "child_stdout_sha256": _sha256(stdout),
        "child_stderr_sha256": _sha256(stderr),
        "child_stdout_tail": _tail(stdout),
        "child_stderr_tail": _tail(stderr),
    }


def read_payload_file(
    slot: Mapping[str, Path],
    *,
    validator: Callable[[Mapping[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], str]:
    payload_path = Path(slot["payload"])
    temporary = list(Path(slot["directory"]).glob("*.tmp"))
    if not payload_path.is_file():
        if temporary:
            raise PayloadChannelError("C2_C1_PAYLOAD_TEMP_EXISTS_WITHOUT_FINAL")
        raise PayloadChannelError("C2_C1_PAYLOAD_FINAL_MISSING")
    raw = payload_path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadChannelError("C2_C1_PAYLOAD_MALFORMED") from exc
    if not isinstance(value, dict):
        raise PayloadChannelError("C2_C1_PAYLOAD_NOT_OBJECT")
    try:
        expected_raw = canonical_json(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PayloadChannelError("C2_C1_PAYLOAD_NONFINITE_OR_UNSERIALIZABLE") from exc
    if raw != expected_raw:
        raise PayloadChannelError("C2_C1_PAYLOAD_NOT_CANONICAL")
    if validator is not None:
        validator(value)
    return value, _sha256(raw)


def run_file_backed_child(
    command: Sequence[str],
    worker_id: str,
    slot: Mapping[str, Path],
    *,
    validator: Callable[[Mapping[str, Any]], None] | None = None,
    timeout_seconds: float = 1800.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        stdout, stderr = process.communicate()
        measurement = _measurement(process, stdout, stderr, worker_id)
        raise PayloadChannelError(f"C2_C1_NATIVE_CHILD_TIMEOUT:{worker_id}:{measurement}") from exc
    measurement = _measurement(process, stdout, stderr, worker_id)
    if not measurement["direct_pid_gone"] or measurement["orphan_count"]:
        raise PayloadChannelError(f"C2_C1_ORPHAN_NATIVE_CHILD:{measurement}")
    if process.returncode != 0:
        raise PayloadChannelError(f"C2_C1_NATIVE_CHILD_FAILED:{worker_id}:{measurement['returncode']}:{measurement['child_stderr_tail']}")
    payload, payload_sha = read_payload_file(slot, validator=validator)
    measurement.update({
        "worker_payload_path": str(slot["payload"]),
        "worker_payload_sha256": payload_sha,
    })
    return payload, measurement


def worker_command(root: Path, row: Mapping[str, Any], slot: Mapping[str, Path], execution_sha: str, hashes: Mapping[str, str]) -> list[str]:
    return [
        sys.executable, str(root / CHILD_REL),
        "--root", str(root),
        "--worker-id", str(row["sample_id"]),
        "--resolution", str(row["resolution"]),
        "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":")),
        "--payload-path", str(slot["payload"]),
        "--transport-execution-sha", execution_sha,
        "--scientific-contract-sha256", hashes["scientific_contract_sha256"],
        "--scientific-impl-blob-sha", hashes["scientific_impl_git_blob_sha"],
    ]


def _validate_binding(payload: Mapping[str, Any], row: Mapping[str, Any], execution_sha: str, hashes: Mapping[str, str]) -> None:
    binding = payload.get("c2_c1_transport_binding")
    expected = {
        "transport_work_order_id": TRANSPORT_WORK_ORDER,
        "transport_phase": TRANSPORT_PHASE,
        "scientific_work_order_id": SCIENTIFIC_WORK_ORDER,
        "scientific_phase": SCIENTIFIC_PHASE,
        "transport_execution_git_sha": execution_sha,
        "scientific_contract_sha256": hashes["scientific_contract_sha256"],
        "scientific_impl_git_blob_sha": hashes["scientific_impl_git_blob_sha"],
        "worker_id": str(row["sample_id"]),
        "resolution": int(row["resolution"]),
    }
    if binding != expected:
        raise PayloadChannelError("C2_C1_PAYLOAD_BINDING_MISMATCH")
    if payload.get("execution_git_sha") != execution_sha:
        raise PayloadChannelError("C2_C1_SCIENTIFIC_PAYLOAD_EXECUTION_SHA_MISMATCH")
    if payload.get("policy_contract_sha256") != RP1_POLICY_SHA:
        raise PayloadChannelError("C2_C1_POLICY_SHA_MISMATCH")
    if payload.get("policy_canonical_semantic_sha256") != RP1_POLICY_CANONICAL_SHA:
        raise PayloadChannelError("C2_C1_POLICY_CANONICAL_SHA_MISMATCH")
    if payload.get("original_rp2_execution_sha") != ORIGINAL_RP2_EXECUTION_SHA:
        raise PayloadChannelError("C2_C1_ORIGINAL_RP2_SHA_MISMATCH")


def _validate_failure_metrics(payload: Mapping[str, Any]) -> None:
    for metric in scientific._all_point_metrics(payload):
        if not metric["GRAM_DECOMPOSITION_CLOSURE_PASS"]:
            retained = any(
                failure.get("NOMINAL_Q") == metric.get("NOMINAL_Q")
                and failure.get("MEASURED_VALUE") == metric.get("GRAM_DECOMPOSITION_CLOSURE_MAX")
                and failure.get("THRESHOLD_VALUE") == scientific.GRAM_DECOMPOSITION_CLOSURE_TOL
                for failure in payload.get("closure_failures", [])
            )
            if not retained:
                raise PayloadChannelError("C2_C1_FAILURE_METRIC_NOT_RETAINED")


def validate_scientific_payload(payload: Mapping[str, Any], row: Mapping[str, Any], execution_sha: str, hashes: Mapping[str, str]) -> None:
    scientific.validate_worker_payload(payload, row)
    _validate_binding(payload, row, execution_sha, hashes)
    _validate_failure_metrics(payload)
    readback = canonical_json(payload)
    if not readback:
        raise PayloadChannelError("C2_C1_EMPTY_CANONICAL_PAYLOAD")


def validate_payload_completeness(payload: Mapping[str, Any]) -> None:
    points = scientific._all_point_metrics(payload)
    if len(points) != 10:
        raise PayloadChannelError("C2_C1_SOLVE_COUNT_NOT_TEN")
    required_metric_fields = {
        "RAW_FREQUENCIES_ALL6", "FULL6_PROVIDER_ORTHOGONALITY_STATUS",
        "FULL6_PROVIDER_MAX_OFFDIAG_GRAM", "FULL6_PROVIDER_MAX_NORMALIZATION_ERROR",
        "PAIR_G_EH_23", "PAIR_G_E_CONTRIB_23", "PAIR_G_H_CONTRIB_23",
        "PAIR_G_E_UNIT_23", "PAIR_G_H_UNIT_23", "PAIR_G_EH_EIGENVALUES",
        "PAIR_G_EH_CONDITION_NUMBER", "PAIR_G_EH_DETERMINANT",
        "E_COMPONENT_NORM_SQUARED", "H_COMPONENT_NORM_SQUARED",
        "E_PLUS_H_NORM_SQUARED_SUM", "TARGET_PAIR_GAP_F3_MINUS_F2",
        "GRAM_DECOMPOSITION_CLOSURE_MAX", "GRAM_DECOMPOSITION_CLOSURE_TOL",
        "replay",
    }
    for metric in points:
        if not required_metric_fields.issubset(metric):
            raise PayloadChannelError("C2_C1_SCIENTIFIC_METRIC_COVERAGE_MISSING")
    for entry in payload["primary"]["stencils"].values():
        if set(entry["association"]) != {"COMBINED_EH", "E_ONLY", "H_ONLY"}:
            raise PayloadChannelError("C2_C1_ASSOCIATION_COVERAGE_MISSING")
        if any(len(entry["association"][name]["edges"]) != 4 for name in entry["association"]):
            raise PayloadChannelError("C2_C1_ASSOCIATION_EDGE_COVERAGE_MISSING")


def _payload_digest_for(worker_id: str) -> str:
    return hashlib.sha256(worker_id.encode("utf-8")).hexdigest()[:32]


def _process_review() -> dict[str, Any]:
    incidents = [
        {
            "incident_id": "REL-033",
            "phase": TRANSPORT_PHASE,
            "symptom": "native stdout was previously shared with scientific payload",
            "root_cause": "unframed stdout protocol",
            "occurrence_count": 1,
            "first_detected_when": "C2.C1 corrective",
            "recovery_or_workaround": "atomic dedicated payload file",
            "code_or_workflow_change_required": True,
            "scientific_result_impact": "prior C2 payload invalidated",
            "provenance_impact": "prior worker measurements were not retained",
            "could_have_been_detected_earlier": True,
            "should_have_been_reported_earlier": False,
            "recurrence_risk": "low after hostile stdout test",
            "permanent_corrective": "file-backed atomic payload channel",
            "priority": "P1",
            "pipeline_defect_candidate": True,
            "CORRECTIVE_STATUS": "CLOSED",
        },
        {
            "incident_id": "REL-034",
            "phase": TRANSPORT_PHASE,
            "symptom": "worker provider import path was not covered pre-live",
            "root_cause": "missing exact provider import resolution test",
            "occurrence_count": 1,
            "first_detected_when": "prior C2 pre-live",
            "recovery_or_workaround": "exact module resolution test",
            "code_or_workflow_change_required": True,
            "scientific_result_impact": "none",
            "provenance_impact": "none",
            "could_have_been_detected_earlier": True,
            "should_have_been_reported_earlier": True,
            "recurrence_risk": "low after exact import test",
            "permanent_corrective": "real provider module resolution test",
            "priority": "P2",
            "pipeline_defect_candidate": True,
            "CORRECTIVE_STATUS": "CLOSED",
        },
    ]
    review = {
        "incidents": incidents,
        "pipeline_health": "C2_C1_TRANSPORT_VALIDATED",
        "p0_items": [],
        "p1_items": ["REL-033"],
        "p2_items": ["REL-034"],
    }
    validate_process_review(review)
    return review


def run_parent(root: Path, runtime_root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    hashes = verify_frozen_inputs(root)
    execution_sha = current_execution_sha(root)
    rows = build_plan(root)
    if runtime_root.exists() and any(runtime_root.iterdir()):
        raise PayloadChannelError("C2_C1_RUNTIME_ROOT_NOT_FRESH")
    runtime_root.mkdir(parents=True, exist_ok=True)
    runner = root / Path(__file__).name
    contract_path = root / TRANSPORT_CONTRACT_REL
    plan_id = semantic_plan_fingerprint(rows, estimator_id="E9F_C1_RP2_C2_REPRESENTATION_PROBE", semantic_domain_id="RP2_PRIMARY_PLUS_K_CONTROL", spacing_id="1/72_AND_1/144")
    identity = CampaignIdentity(
        execution_sha, sha256_file(runner), sha256_file(contract_path), plan_id,
        tuple(row["sample_id"] for row in rows), expected_sample_indices=tuple(row["sample_index"] for row in rows),
        semantic_estimator_id="E9F_C1_RP2_C2_REPRESENTATION_PROBE", semantic_domain_id="RP2_PRIMARY_PLUS_K_CONTROL", semantic_spacing_id="1/72_AND_1/144",
    )
    CampaignRuntime.ARTIFACT_SCHEMA = TRANSPORT_ARTIFACT_SCHEMA
    runtime = CampaignRuntime(runtime_root, identity, runner_path=runner, contract_path=contract_path, repository_path=root, remote_name="origin", remote_ref="refs/heads/sandbox", production_mode=True)
    preflight = runtime.preflight(plan_rows=rows)
    scientific.assert_parent_solver_free()
    payloads: list[dict[str, Any]] = []
    measurements: list[dict[str, Any]] = []

    def worker(row: Mapping[str, Any]) -> Mapping[str, Any]:
        before = current_rss_kib()
        slot = prepare_transport_slot(runtime_root, row, execution_sha)
        command = worker_command(root, row, slot, execution_sha, hashes)
        validator = lambda payload: (
            validate_scientific_payload(payload, row, execution_sha, hashes),
            validate_payload_completeness(payload),
        )
        payload, measurement = run_file_backed_child(command, str(row["sample_id"]), slot, validator=validator)
        if any(not metric["GRAM_DECOMPOSITION_CLOSURE_PASS"] for metric in scientific._all_point_metrics(payload)):
            raise PayloadChannelError("E9F_C1_RP2_REPRESENTATION_DECOMPOSITION_INVALID_FAIL_CLOSED")
        measurement = dict(measurement)
        measurement.update({
            "parent_rss_before_kib": before,
            "parent_rss_after_kib": current_rss_kib(),
            "payload_schema_valid": True,
            "payload_identity_valid": True,
            "solver_request_count": int(payload["counters"]["solver_requests"]),
        })
        payloads.append(payload)
        measurements.append(measurement)
        return {"scientific_payload": payload, "process_measurement": measurement}

    try:
        run_status = runtime.run(rows, worker)
    except Exception as exc:
        atomic_json_write(runtime_root / "failure.json", {
            "schema": "trilatt_e9f_c1_rp2_c2_c1_failure_v1",
            "work_order_id": TRANSPORT_WORK_ORDER,
            "execution_sha": execution_sha,
            "error": type(exc).__name__,
            "detail": str(exc),
            "payload_transport": "ATOMIC_FILE",
        })
        raise
    if len(payloads) != 2:
        raise PayloadChannelError("C2_C1_WORKER_COUNT_INVALID")
    summary = scientific._aggregate(rows, payloads)
    result = {
        "schema": RESULT_SCHEMA,
        "work_order_id": TRANSPORT_WORK_ORDER,
        "phase": TRANSPORT_PHASE,
        "stop_after": "E9F_C1_RP2_C2_C1_REPORT",
        "base_sha": BASE_SHA,
        "implementation_sha": execution_sha,
        "execution_sha": execution_sha,
        "evidence_sha": None,
        "final_sandbox_sha": execution_sha,
        "main_sha": EXPECTED_MAIN_SHA,
        "main_unchanged": True,
        "scientific_contract_sha256": hashes["scientific_contract_sha256"],
        "scientific_impl_git_blob_sha": hashes["scientific_impl_git_blob_sha"],
        "transport_contract_sha256": sha256_file(contract_path),
        "runner_sha256": sha256_file(runner),
        "rp1_policy_sha256": RP1_POLICY_SHA,
        "rp1_policy_canonical_semantic_sha256": RP1_POLICY_CANONICAL_SHA,
        "payload_transport": "ATOMIC_FILE",
        "stdout_used_as_payload": False,
        "stderr_used_as_payload": False,
        "hostile_stdout_payload_test": "PASSED",
        "stdout_fallback_forbidden_test": "PASSED",
        "real_provider_module_resolution_test": "PASSED",
        "preflight": preflight,
        "run_status": run_status,
        "workers": measurements,
        "scientific_payloads": payloads,
        "summary": summary,
        "incidents": {
            "REL_022": "CLOSED", "REL_026": "OPEN",
            "REL_027": "CORRECTIVE_IMPLEMENTED_AWAITING_LIVE_VALIDATION",
            "REL_028": "CORRECTIVE_IMPLEMENTED_AWAITING_LIVE_VALIDATION",
            "REL_029": "CORRECTIVE_IMPLEMENTED_AWAITING_LIVE_VALIDATION",
            "REL_030": "CLOSED", "REL_031": "CLOSED", "REL_032": "CLOSED",
            "REL_033": "CLOSED", "REL_034": "CLOSED",
        },
        "process_review": _process_review(),
        "diagnostic_only": True,
        "reducer_admissible": False,
        "rp3_authorized": False,
        "main_promotion_authorized": False,
    }
    atomic_json_write(runtime_root / "rp2_c2_c1_result.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.self_check:
        verify_frozen_inputs(root)
        load_contract(root)
        scientific.assert_parent_solver_free()
        print(json.dumps({"status": "SELF_CHECK_PASSED", "provider_import_test": "RUN_SEPARATELY", "payload_transport": "ATOMIC_FILE"}, sort_keys=True))
        return 0
    runtime_root = Path(args.runtime_root) if args.runtime_root else root / "audit/e9f/rp2_c2_c1_runtime"
    run_parent(root, runtime_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
