"""Durable parsing for Chat replies that require local-only diagnosis."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

FILENAME = "local-supervisor-required.json"
RESOLUTION_FILENAME = "local-supervisor-resolution.json"
SUCCESSOR_RESPONSE_FILENAME = "local-supervisor-successor.txt"


def parse(text: str) -> dict[str, str] | None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    requested = re.search(r"^LOCAL_SUPERVISOR_REQUIRED\s*[:=]\s*true\s*$",
                          normalized, re.MULTILINE | re.IGNORECASE)
    legacy_termination = re.search(r"^WORKFLOW_TERMINATED\s*[:=]\s*true\s*$",
                                   normalized, re.MULTILINE | re.IGNORECASE)
    if not requested and not legacy_termination:
        return None

    def field(name: str, fallback: str) -> str:
        match = re.search(rf"^{name}\s*[:=]\s*([^\n]+)$", normalized, re.MULTILINE)
        return (match.group(1).strip() if match else fallback)[:1000]

    reason = field("LOCAL_SUPERVISOR_REASON", "PROJECT_TERMINATION_REVIEW" if legacy_termination else "UNSPECIFIED_LOCAL_EVIDENCE_GAP")
    termination = legacy_termination is not None or reason.upper() == "PROJECT_TERMINATION_REVIEW"
    return {"error_code": "TERMINATION_REVIEW_REQUIRED" if termination else "LOCAL_SUPERVISOR_REQUIRED",
            "reason": reason,
            "missing_remote_evidence": field(
                "MISSING_REMOTE_EVIDENCE", "Legacy Chat termination requires supervisor review"),
            "goal_outcome": field("GOAL_OUTCOME", "UNSPECIFIED"),
            "completion_evidence": field("COMPLETION_EVIDENCE", "UNSPECIFIED"),
            "unresolved_questions": field("UNRESOLVED_QUESTIONS", "UNSPECIFIED"),
            "cheapest_next_test": field("CHEAPEST_NEXT_TEST", "UNSPECIFIED"),
            "why_no_successor": field("WHY_STOP_IS_SUFFICIENT", "UNSPECIFIED")}


def load(directory: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((directory / FILENAME).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    return value if isinstance(value, dict) else None


def persist(directory: Path, response_path: Path, text: str,
            request: dict[str, Any]) -> dict[str, Any] | None:
    parsed = parse(text)
    if parsed is None:
        return None
    evidence = {"schema": "mephc-local-supervisor-required-v1",
                "work_order_id": request.get("work_order_id"),
                "request_id": request.get("request_id", directory.name),
                "response_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
                **parsed, "captured_at": time.time()}
    path = directory / FILENAME
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return evidence


def load_resolution(directory: Path, requirement: dict[str, Any],
                    expected_reviewer_task_id: str) -> dict[str, Any] | None:
    try:
        value = json.loads((directory / RESOLUTION_FILENAME).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ValueError("SUPERVISOR_RESOLUTION_INVALID")
    bindings = (
        value.get("schema") == "mephc-local-supervisor-resolution-v1",
        value.get("reviewer_task_id") == expected_reviewer_task_id,
        value.get("prior_work_order_id") == requirement.get("work_order_id"),
        value.get("request_id") == requirement.get("request_id"),
        value.get("response_sha256") == requirement.get("response_sha256"),
        isinstance(value.get("successor_contract"), dict),
    )
    if not all(bindings):
        raise ValueError("SUPERVISOR_RESOLUTION_BINDING_INVALID")
    successor = value["successor_contract"].get(
        "work_order_id", value["successor_contract"].get("WORK_ORDER_ID"))
    if not isinstance(successor, str) or successor == requirement.get("work_order_id"):
        raise ValueError("SUPERVISOR_RESOLUTION_SUCCESSOR_INVALID")
    return value


def resolve(directory: Path, reviewer_task_id: str, expected_reviewer_task_id: str,
            successor_contract: dict[str, Any], rationale: str) -> dict[str, Any]:
    requirement = load(directory)
    if not requirement or requirement.get("error_code") != "LOCAL_SUPERVISOR_REQUIRED":
        raise ValueError("LOCAL_SUPERVISOR_REQUIREMENT_REQUIRED")
    if reviewer_task_id != expected_reviewer_task_id:
        raise ValueError("SUPERVISOR_ID_INVALID")
    successor = successor_contract.get("work_order_id", successor_contract.get("WORK_ORDER_ID"))
    if not isinstance(successor, str) or successor == requirement.get("work_order_id"):
        raise ValueError("SUPERVISOR_RESOLUTION_SUCCESSOR_INVALID")
    decision = {
        "schema": "mephc-local-supervisor-resolution-v1",
        "reviewer_task_id": reviewer_task_id,
        "prior_work_order_id": requirement.get("work_order_id"),
        "request_id": requirement.get("request_id"),
        "response_sha256": requirement.get("response_sha256"),
        "successor_contract": successor_contract,
        "rationale": str(rationale)[:4000],
        "resolved_at": time.time(),
    }
    path = directory / RESOLUTION_FILENAME
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(decision, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return decision


def approve_termination(directory: Path, ledger_path: Path, reviewer_task_id: str,
                        expected_reviewer_task_id: str, review: dict[str, Any]) -> dict[str, Any]:
    evidence = load(directory)
    required = {"completion_evidence", "attempts_completed", "unresolved_questions",
                "alternative_explanations", "cheapest_next_test", "counterevidence_search",
                "why_stop_is_sufficient"}
    if not evidence or evidence.get("error_code") != "TERMINATION_REVIEW_REQUIRED":
        raise ValueError("TERMINATION_PROPOSAL_REQUIRED")
    if reviewer_task_id != expected_reviewer_task_id or not required.issubset(review):
        raise ValueError("TERMINATION_REVIEW_INCOMPLETE")
    decision = {"schema": "mephc-supervisor-termination-approval-v1",
                "reviewer_task_id": reviewer_task_id, "proposal": evidence,
                "review": review, "approved_at": time.time()}
    decision_path = directory / "supervisor-termination-approval.json"
    temporary = decision_path.with_name(f".{decision_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(decision, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, decision_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_name(f".{ledger_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"schema": "mephc-workflow-ledger-v2",
                                     "workflow_state": "terminated", "pending_job_id": None,
                                     "termination_approval_path": str(decision_path),
                                     "updated_at": time.time()}, sort_keys=True,
                                    separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, ledger_path)
    return decision
