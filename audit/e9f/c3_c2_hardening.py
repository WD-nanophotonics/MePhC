"""Fail-closed C3.C2 transport and process-review helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

OPEN_STATUSES = {"OPEN", "PARTIALLY_CLOSED", "ROOT_CAUSE_IDENTIFIED", "CORRECTIVE_PENDING", "AWAITING_CORRECTIVE"}
HEALTH_CLASSES = {"PIPELINE_HEALTHY", "PIPELINE_HEALTHY_WITH_TECH_DEBT", "PIPELINE_REQUIRES_CORRECTIVE"}


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_process_review(review: Mapping[str, Any]) -> None:
    required = {"incidents", "pipeline_health", "p0_items", "p1_items", "p2_items"}
    missing = required - set(review)
    if missing or review.get("pipeline_health") not in HEALTH_CLASSES:
        raise ValueError(f"C3_C2_PROCESS_REVIEW_SCHEMA_INVALID:{sorted(missing)}")
    by_id: dict[str, Mapping[str, Any]] = {}
    for incident in review["incidents"]:
        incident_id = str(incident.get("incident_id", ""))
        if not incident_id or incident_id in by_id:
            raise ValueError("C3_C2_PROCESS_REVIEW_DUPLICATE_OR_MISSING_ID")
        if incident.get("priority") not in {"P0", "P1", "P2"}:
            raise ValueError(f"C3_C2_PROCESS_REVIEW_PRIORITY_INVALID:{incident_id}")
        status = incident.get("CORRECTIVE_STATUS", "CLOSED")
        if status not in OPEN_STATUSES | {"CLOSED"}:
            raise ValueError(f"C3_C2_PROCESS_REVIEW_STATUS_INVALID:{incident_id}")
        by_id[incident_id] = incident
    lists = {"P0": list(review["p0_items"]), "P1": list(review["p1_items"]), "P2": list(review["p2_items"])}
    listed = [item for values in lists.values() for item in values]
    if len(listed) != len(set(listed)):
        raise ValueError("C3_C2_PROCESS_REVIEW_OPEN_LIST_DUPLICATE")
    for priority, values in lists.items():
        for incident_id in values:
            incident = by_id.get(incident_id)
            if incident is None or incident.get("priority") != priority or incident.get("CORRECTIVE_STATUS") == "CLOSED":
                raise ValueError(f"C3_C2_PROCESS_REVIEW_OPEN_LIST_MISMATCH:{incident_id}")
    expected = {incident_id for incident_id, incident in by_id.items() if incident.get("CORRECTIVE_STATUS") in OPEN_STATUSES}
    if set(listed) != expected:
        raise ValueError(f"C3_C2_PROCESS_REVIEW_OPEN_SET_MISMATCH:{sorted(expected)}:{sorted(set(listed))}")


def validate_checkpoint(checkpoint: Mapping[str, Any], *, expected: Mapping[str, Any], payload_path: Path) -> None:
    fields = ("schema", "project_id", "work_order_id", "execution_sha", "contract_sha256", "worker_id", "logical_sample_index", "resolution", "payload_sha256", "artifact_schema", "generation")
    for field in fields:
        if checkpoint.get(field) != expected.get(field):
            raise ValueError(f"C3_C2_CHECKPOINT_IDENTITY_MISMATCH:{field}")
    if not payload_path.is_file() or sha(payload_path) != checkpoint.get("payload_sha256"):
        raise ValueError("C3_C2_CHECKPOINT_PAYLOAD_BINDING_MISMATCH")


def validate_payload_hash(payload: Mapping[str, Any]) -> None:
    declared = payload.get("payload_sha256")
    body = dict(payload)
    body.pop("payload_sha256", None)
    if not isinstance(declared, str) or hashlib.sha256(canonical(body)).hexdigest() != declared:
        raise ValueError("C3_C2_PAYLOAD_HASH_MISMATCH")
