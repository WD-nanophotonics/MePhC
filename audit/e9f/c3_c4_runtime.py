"""C3.C4 shared identity finalizer and acceptance helpers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from audit.e9f import c3_c2_hardening as c2

WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-C4-20260825-246"
PHASE = "E9F.C1.RP2.C3.C4"
FAILED_PARENT_EXECUTION_SHA = "034339cc7ba04dd7cdf78cf0e37f7d3fc98111e5"
RUNNER_RELATIVE_PATH = Path("audit/e9f/run_e9f_c1_rp2_c3_c4.py")
PAYLOAD_SCHEMA = "mephc_e9f_c1_rp2_c3_c4_worker_v1"
CHECKPOINT_SCHEMA = "mephc_e9f_c1_rp2_c3_c4_checkpoint_v6"
H_ORTHOGONALITY_TOLERANCE = 1e-10
H_NORM_TOLERANCE = 1e-14
CANONICAL_IDENTITY_FIELDS = ("project_id", "work_order_id", "phase", "execution_sha", "source_sample_id", "source_sample_index", "logical_sample_index", "worker_id", "resolution", "contract_sha256", "rp1_policy_file_sha256", "rp1_policy_canonical_semantic_sha256", "payload_transport")
REQUIRED_INCIDENT_IDS = ("REL-021", "REL-026", "REL-035", "REL-036", "REL-037", "REL-038", "REL-039", "REL-040", "REL-041", "REL-042", "REL-043", "REL-044", "REL-045", "REL-046", "REL-047", "REL-048", "REL-049")
HEALTH_CLASSES = {"PIPELINE_HEALTHY", "PIPELINE_HEALTHY_WITH_TECH_DEBT", "PIPELINE_FRAGILE", "PIPELINE_REQUIRES_CORRECTIVE"}
OPEN_STATUSES = {"OPEN", "PARTIALLY_CLOSED", "ROOT_CAUSE_IDENTIFIED", "CORRECTIVE_PENDING", "AWAITING_CORRECTIVE"}


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def runner_path(root: Path, file_path: Path) -> Path:
    actual = file_path.resolve(); expected = (root / "audit/e9f").resolve()
    if expected not in actual.parents or actual.name != RUNNER_RELATIVE_PATH.name:
        raise ValueError("C3_C4_RUNNER_PATH_INVALID")
    return actual


def identity_for(*, row: Mapping[str, Any], execution_sha: str, contract_sha256: str, policy_sha256: str) -> dict[str, Any]:
    return {"project_id": "MEPHC", "work_order_id": WORK_ORDER, "phase": PHASE, "execution_sha": execution_sha, "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "worker_id": row["sample_id"], "resolution": 64, "contract_sha256": contract_sha256, "rp1_policy_file_sha256": policy_sha256, "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a", "payload_transport": "ATOMIC_FILE"}


def body_hash(payload: Mapping[str, Any]) -> str:
    body = dict(payload); body.pop("payload_body_sha256", None); body.pop("payload_file_sha256", None)
    return hashlib.sha256(canonical(body)).hexdigest()


def finalize_payload(raw_science_payload: Mapping[str, Any], *, row: Mapping[str, Any], expected_identity: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(raw_science_payload)
    for legacy in ("execution_git_sha", "payload_sha256", "c3_c2_transport_binding", "c3_c3_transport_binding", "rp1_policy_sha256"):
        payload.pop(legacy, None)
    payload["schema"] = PAYLOAD_SCHEMA
    for key in CANONICAL_IDENTITY_FIELDS:
        payload[key] = expected_identity[key]
    payload["c3_c4_transport_binding"] = dict(expected_identity)
    payload["h_gate_tolerances"] = {"orthogonality_tolerance": H_ORTHOGONALITY_TOLERANCE, "selected_pair_offdiag_tolerance": H_ORTHOGONALITY_TOLERANCE, "normalization_tolerance": H_NORM_TOLERANCE}
    for point in payload.get("all_point_metrics", []):
        gate = point.setdefault("H_GATE", {})
        gate["orthogonality_tolerance"] = H_ORTHOGONALITY_TOLERANCE
        gate["normalization_tolerance"] = H_NORM_TOLERANCE
    payload["payload_body_sha256"] = body_hash(payload)
    validate_payload(payload, row=row, expected_identity=expected_identity)
    return payload


def validate_h_gates(payload: Mapping[str, Any]) -> None:
    points = payload.get("all_point_metrics", [])
    if len(points) != 9:
        raise ValueError("C3_C4_H_POINT_COUNT_INVALID")
    for index, point in enumerate(points):
        gate = point.get("H_GATE", {})
        if gate.get("status") != "MPB_H_ENVELOPE_QUALIFIED": raise ValueError(f"C3_C4_H_GATE_STATUS:{index}")
        if float(gate.get("max_offdiag", float("inf"))) > H_ORTHOGONALITY_TOLERANCE: raise ValueError(f"C3_C4_H_FULL6:{index}")
        if float(gate.get("selected_pair_offdiag", float("inf"))) > H_ORTHOGONALITY_TOLERANCE: raise ValueError(f"C3_C4_H_SELECTED_PAIR:{index}")
        if float(gate.get("max_normalization_error", float("inf"))) > H_NORM_TOLERANCE: raise ValueError(f"C3_C4_H_NORMALIZATION:{index}")
        if float(gate.get("orthogonality_tolerance", float("inf"))) != H_ORTHOGONALITY_TOLERANCE: raise ValueError(f"C3_C4_H_ORTHOGONALITY_METADATA:{index}")
        if float(gate.get("normalization_tolerance", float("inf"))) != H_NORM_TOLERANCE: raise ValueError(f"C3_C4_H_NORMALIZATION_METADATA:{index}")


def validate_identity(payload: Mapping[str, Any], expected_identity: Mapping[str, Any]) -> None:
    binding = payload.get("c3_c4_transport_binding")
    if not isinstance(binding, Mapping): raise ValueError("C3_C4_BINDING_MISSING")
    for key in CANONICAL_IDENTITY_FIELDS:
        if payload.get(key) != expected_identity[key]: raise ValueError(f"C3_C4_TOP_LEVEL_IDENTITY:{key}")
        if binding.get(key) != expected_identity[key]: raise ValueError(f"C3_C4_BINDING_IDENTITY:{key}")
        if payload.get(key) != binding.get(key): raise ValueError(f"C3_C4_TOP_LEVEL_BINDING_DISAGREE:{key}")
    if "execution_git_sha" in payload and payload["execution_git_sha"] != payload["execution_sha"]: raise ValueError("C3_C4_LEGACY_EXECUTION_SHA_CONFLICT")


def validate_payload(payload: Mapping[str, Any], *, row: Mapping[str, Any], expected_identity: Mapping[str, Any]) -> None:
    if payload.get("schema") != PAYLOAD_SCHEMA or payload.get("solve_count") != 9 or payload.get("diagnostic_only") is not True or payload.get("reducer_admissible") is not False: raise ValueError("C3_C4_PAYLOAD_SCHEMA")
    if payload.get("source_sample_id") != row["source_sample_id"] or payload.get("worker_id") != row["sample_id"]: raise ValueError("C3_C4_PAYLOAD_ROW_IDENTITY")
    if len(payload.get("stencils", {})) != 2 or len(payload.get("all_point_metrics", [])) != 9: raise ValueError("C3_C4_PAYLOAD_COVERAGE")
    validate_identity(payload, expected_identity); validate_h_gates(payload)
    if payload.get("payload_body_sha256") != body_hash(payload): raise ValueError("C3_C4_BODY_HASH")


def validate_process_review(review: Mapping[str, Any], required_ids: Sequence[str] = REQUIRED_INCIDENT_IDS) -> None:
    c2.validate_process_review(review)
    actual = [str(item.get("incident_id")) for item in review["incidents"]]
    if set(actual) != set(required_ids) or len(actual) != len(set(actual)): raise ValueError("C3_C4_PROCESS_REGISTRY_MISMATCH")
    if review.get("pipeline_health") not in HEALTH_CLASSES: raise ValueError("C3_C4_PROCESS_HEALTH_INVALID")


def construct_checkpoint(*, payload: Mapping[str, Any], payload_path: Path, expected_identity: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": CHECKPOINT_SCHEMA, **{key: expected_identity[key] for key in CANONICAL_IDENTITY_FIELDS if key != "payload_transport"}, "payload_file_sha256": sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "payload_path": str(payload_path), "artifact_schema": PAYLOAD_SCHEMA, "generation": 1}


def validate_checkpoint(checkpoint: Mapping[str, Any], *, payload_path: Path, expected_identity: Mapping[str, Any]) -> None:
    for key, value in {"schema": CHECKPOINT_SCHEMA, **{key: expected_identity[key] for key in CANONICAL_IDENTITY_FIELDS if key != "payload_transport"}, "artifact_schema": PAYLOAD_SCHEMA, "generation": 1}.items():
        if checkpoint.get(key) != value: raise ValueError(f"C3_C4_CHECKPOINT_IDENTITY:{key}")
    if checkpoint.get("payload_path") != str(payload_path) or not payload_path.is_file() or sha(payload_path) != checkpoint.get("payload_file_sha256"): raise ValueError("C3_C4_CHECKPOINT_FILE_HASH")
    payload = json.loads(payload_path.read_text());
    if payload.get("payload_body_sha256") != checkpoint.get("payload_body_sha256") or body_hash(payload) != checkpoint.get("payload_body_sha256"): raise ValueError("C3_C4_CHECKPOINT_BODY_HASH")


def publish_artifacts(*, runtime_root: Path, payload: Mapping[str, Any], measurement: Mapping[str, Any], expected_identity: Mapping[str, Any], runner_sha256: str) -> dict[str, Any]:
    runtime_root.mkdir(parents=True, exist_ok=True); payload_path = Path(measurement["payload_path"])
    checkpoint = construct_checkpoint(payload=payload, payload_path=payload_path, expected_identity=expected_identity); checkpoint_path = runtime_root / "checkpoint.json"; atomic_write(checkpoint_path, checkpoint); validate_checkpoint(checkpoint, payload_path=payload_path, expected_identity=expected_identity)
    result = {"schema": "mephc_e9f_c1_rp2_c3_c4_result_v1", **expected_identity, "runner_sha256": runner_sha256, "payload_file_sha256": sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "checkpoint_sha256": sha(checkpoint_path), "measurement": dict(measurement), "scientific_payload": dict(payload), "diagnostic_only": True, "reducer_admissible": False, "matrix_release_authorized": False, "pipeline_health": "PIPELINE_REQUIRES_CORRECTIVE"}
    result_path = runtime_root / "rp2_c3_c4_result.json"; atomic_write(result_path, result)
    manifest = {"schema": "mephc_e9f_c1_rp2_c3_c4_evidence_manifest_v1", **expected_identity, "runner_sha256": runner_sha256, "payload_file_sha256": sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"], "checkpoint_sha256": sha(checkpoint_path), "result_sha256": sha(result_path), "canary_solve_count": 9, "diagnostic_only": True, "reducer_admissible": False}
    manifest_path = runtime_root / "rp2_c3_c4_evidence_manifest.json"; atomic_write(manifest_path, manifest)
    return {"checkpoint_path": str(checkpoint_path), "result_path": str(result_path), "manifest_path": str(manifest_path), "checkpoint_sha256": sha(checkpoint_path), "result_sha256": sha(result_path), "manifest_sha256": sha(manifest_path), "payload_file_sha256": sha(payload_path), "payload_body_sha256": payload["payload_body_sha256"]}
