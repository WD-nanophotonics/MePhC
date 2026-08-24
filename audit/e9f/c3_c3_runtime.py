"""C3.C3 parent-side identity, publication, H-gate and process helpers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from audit.e9f import c3_c2_hardening as c2

WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-C3-20260825-244"
PHASE = "E9F.C1.RP2.C3.C3"
FAILED_PARENT_EXECUTION_SHA = "1cbf56826456aaca2cabaf5244dc72a92f250040"
RUNNER_RELATIVE_PATH = Path("audit/e9f/run_e9f_c1_rp2_c3_c3.py")
PAYLOAD_SCHEMA = "mephc_e9f_c1_rp2_c3_c3_worker_v1"
CHECKPOINT_SCHEMA = "mephc_e9f_c1_rp2_c3_c3_checkpoint_v5"
H_TOL = 1e-10
NORM_TOL = 1e-10


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def runner_path(root: Path, file_path: Path) -> Path:
    actual = file_path.resolve()
    expected_root = (root / "audit/e9f").resolve()
    if expected_root not in actual.parents:
        raise ValueError("C3_C3_RUNNER_PATH_OUTSIDE_AUDIT_E9F")
    if actual.name != RUNNER_RELATIVE_PATH.name:
        raise ValueError("C3_C3_RUNNER_BASENAME_MISMATCH")
    return actual


def body_hash(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("payload_body_sha256", None)
    if "payload_file_sha256" in body:
        body.pop("payload_file_sha256")
    return hashlib.sha256(canonical(body)).hexdigest()


def validate_h_gates(payload: Mapping[str, Any]) -> None:
    points = payload.get("all_point_metrics")
    if not isinstance(points, list) or len(points) != 9:
        raise ValueError("C3_C3_H_GATE_POINT_COUNT_INVALID")
    for index, point in enumerate(points):
        gate = point.get("H_GATE", {})
        if gate.get("status") != "MPB_H_ENVELOPE_QUALIFIED":
            raise ValueError(f"C3_C3_H_REPRESENTATION_PRECONDITION_FAIL_CLOSED:{index}:status")
        if float(gate.get("max_offdiag", float("inf"))) > H_TOL:
            raise ValueError(f"C3_C3_H_REPRESENTATION_PRECONDITION_FAIL_CLOSED:{index}:full6")
        if float(gate.get("selected_pair_offdiag", float("inf"))) > H_TOL:
            raise ValueError(f"C3_C3_H_REPRESENTATION_PRECONDITION_FAIL_CLOSED:{index}:selected_pair")
        if float(gate.get("max_normalization_error", float("inf"))) > NORM_TOL:
            raise ValueError(f"C3_C3_H_REPRESENTATION_PRECONDITION_FAIL_CLOSED:{index}:normalization")
        if float(gate.get("orthogonality_tolerance", H_TOL)) > H_TOL:
            raise ValueError(f"C3_C3_H_REPRESENTATION_PRECONDITION_FAIL_CLOSED:{index}:tolerance")


def expected_binding(*, row: Mapping[str, Any], execution_sha: str, contract_sha256: str, policy_sha256: str) -> dict[str, Any]:
    return {
        "project_id": "MEPHC", "work_order_id": WORK_ORDER, "phase": PHASE,
        "execution_sha": execution_sha, "source_sample_id": row["source_sample_id"],
        "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]),
        "worker_id": row["sample_id"], "resolution": 64, "contract_sha256": contract_sha256,
        "rp1_policy_file_sha256": policy_sha256,
        "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a",
        "payload_transport": "ATOMIC_FILE",
    }


def validate_transport_binding(payload: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    binding = payload.get("c3_c3_transport_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("C3_C3_TRANSPORT_BINDING_MISSING")
    for key, value in expected.items():
        if binding.get(key) != value:
            raise ValueError(f"C3_C3_TRANSPORT_BINDING_MISMATCH:{key}")
    for key, value in expected.items():
        if payload.get(key) != value and key not in {"payload_transport"}:
            raise ValueError(f"C3_C3_PAYLOAD_IDENTITY_MISMATCH:{key}")


def validate_payload(payload: Mapping[str, Any], *, row: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    required = {
        "schema": PAYLOAD_SCHEMA, "project_id": "MEPHC", "work_order_id": WORK_ORDER,
        "phase": PHASE, "resolution": 64, "solve_count": 9,
        "diagnostic_only": True, "reducer_admissible": False,
    }
    for key, value in required.items():
        if payload.get(key) != value:
            raise ValueError(f"C3_C3_PAYLOAD_FIELD_MISMATCH:{key}")
    if payload.get("worker_id") != row["sample_id"] or payload.get("source_sample_id") != row["source_sample_id"]:
        raise ValueError("C3_C3_PAYLOAD_WORKER_SOURCE_MISMATCH")
    if len(payload.get("stencils", {})) != 2 or len(payload.get("all_point_metrics", [])) != 9:
        raise ValueError("C3_C3_PAYLOAD_COVERAGE_MISMATCH")
    validate_transport_binding(payload, expected)
    validate_h_gates(payload)
    declared = payload.get("payload_body_sha256")
    if not isinstance(declared, str) or declared != body_hash(payload):
        raise ValueError("C3_C3_PAYLOAD_BODY_HASH_MISMATCH")


def construct_checkpoint(*, payload: Mapping[str, Any], payload_path: Path, expected: Mapping[str, Any], generation: int = 1) -> dict[str, Any]:
    file_sha = sha(payload_path)
    return {"schema": CHECKPOINT_SCHEMA, **{key: expected[key] for key in ("project_id", "work_order_id", "phase", "execution_sha", "contract_sha256", "worker_id", "logical_sample_index", "resolution", "rp1_policy_file_sha256", "rp1_policy_canonical_semantic_sha256")}, "payload_file_sha256": file_sha, "payload_body_sha256": payload["payload_body_sha256"], "payload_path": str(payload_path), "artifact_schema": PAYLOAD_SCHEMA, "generation": generation}


def validate_checkpoint(checkpoint: Mapping[str, Any], *, payload_path: Path, expected: Mapping[str, Any]) -> None:
    for key, value in {"schema": CHECKPOINT_SCHEMA, **{key: expected[key] for key in ("project_id", "work_order_id", "phase", "execution_sha", "contract_sha256", "worker_id", "logical_sample_index", "resolution", "rp1_policy_file_sha256", "rp1_policy_canonical_semantic_sha256")}, "artifact_schema": PAYLOAD_SCHEMA, "generation": 1}.items():
        if checkpoint.get(key) != value:
            raise ValueError(f"C3_C3_CHECKPOINT_IDENTITY_MISMATCH:{key}")
    if checkpoint.get("payload_path") != str(payload_path):
        raise ValueError("C3_C3_CHECKPOINT_PAYLOAD_PATH_MISMATCH")
    if not payload_path.is_file() or sha(payload_path) != checkpoint.get("payload_file_sha256"):
        raise ValueError("C3_C3_CHECKPOINT_FILE_HASH_MISMATCH")
    payload = json.loads(payload_path.read_text())
    if payload.get("payload_body_sha256") != checkpoint.get("payload_body_sha256") or body_hash(payload) != checkpoint.get("payload_body_sha256"):
        raise ValueError("C3_C3_CHECKPOINT_BODY_HASH_MISMATCH")


def scan_orphans(*, worker_marker: str, worker_id: str, exclude_pids: Sequence[int] = ()) -> list[int]:
    result: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        raise RuntimeError("C3_C3_PROC_SCAN_UNAVAILABLE")
    for candidate in proc.iterdir():
        if not candidate.name.isdigit() or int(candidate.name) in set(exclude_pids):
            continue
        try:
            command = (candidate / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if worker_marker in command and worker_id in command:
            result.append(int(candidate.name))
    return sorted(result)


def publish_artifacts(*, root: Path, runtime: Path, payload: Mapping[str, Any], measurement: Mapping[str, Any], expected: Mapping[str, Any], runner_sha256: str) -> dict[str, Any]:
    runtime.mkdir(parents=True, exist_ok=True)
    payload_path = Path(measurement["payload_path"])
    checkpoint = construct_checkpoint(payload=payload, payload_path=payload_path, expected=expected)
    checkpoint_path = runtime / "checkpoint.json"
    atomic_write(checkpoint_path, checkpoint)
    validate_checkpoint(checkpoint, payload_path=payload_path, expected=expected)
    result = {"schema": "mephc_e9f_c1_rp2_c3_c3_result_v1", **expected, "runner_sha256": runner_sha256, "checkpoint_sha256": sha(checkpoint_path), "payload_file_sha256": sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "canary_measurement": dict(measurement), "summary": {"total_native_solves": payload["solve_count"], "REPLAY_MATCHED_POINT_COUNT": payload["replay_matched_point_count"], "REPLAY_UNMATCHED_POINT_COUNT": payload["replay_unmatched_point_count"]}, "scientific_payload": dict(payload), "diagnostic_only": True, "reducer_admissible": False, "matrix_release_authorized": False, "pipeline_health": "PIPELINE_REQUIRES_CORRECTIVE"}
    result_path = runtime / "rp2_c3_c3_result.json"
    atomic_write(result_path, result)
    manifest = {"schema": "mephc_e9f_c1_rp2_c3_c3_evidence_manifest_v1", **expected, "runner_sha256": runner_sha256, "checkpoint_sha256": sha(checkpoint_path), "result_sha256": sha(result_path), "payload_file_sha256": sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "canary_solve_count": 9, "diagnostic_only": True, "reducer_admissible": False}
    manifest_path = runtime / "rp2_c3_c3_evidence_manifest.json"
    atomic_write(manifest_path, manifest)
    return {"checkpoint_path": str(checkpoint_path), "result_path": str(result_path), "manifest_path": str(manifest_path), "checkpoint_sha256": sha(checkpoint_path), "result_sha256": sha(result_path), "manifest_sha256": sha(manifest_path), "payload_file_sha256": sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"]}
