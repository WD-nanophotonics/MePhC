from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

import jobctl
import workflow

OUTBOX = workflow.OUTBOX
TERMINAL = {"succeeded", "failed", "recovery_required"}
RECOVERY_ONLY = {
    "request_submitted", "waiting_for_response", "submission_unconfirmed",
    "chat_submission_unconfirmed", "submission_state_uncertain",
    "response_timeout", "response_protocol_error",
}


def _job(job_id: str) -> dict[str, Any]:
    path = jobctl.JOBS / job_id / "job.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _active_courier() -> dict[str, Any] | None:
    if not jobctl.JOBS.is_dir():
        return None
    found = []
    for directory in jobctl.JOBS.iterdir():
        if not directory.is_dir():
            continue
        state = jobctl.read_state(directory.name)
        if state.get("state") in TERMINAL:
            continue
        value = _job(directory.name)
        if value.get("operation") == "courier":
            found.append((directory.name, state))
    if not found:
        return None
    job_id, state = sorted(found)[0]
    return {
        "workflow_state": "awaiting_supervisor",
        "pending_job_id": job_id,
        "job_state": state.get("state"),
        "safe_next_tool": "mephc_wait",
        "retry_allowed": False,
    }


def _pending_status() -> Path | None:
    if not OUTBOX.is_dir():
        return None
    found = []
    for directory in OUTBOX.iterdir():
        request_path = directory / "request.json"
        if not directory.is_dir() or not request_path.is_file() or (directory / "response.txt").is_file():
            continue
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if request.get("project_id") == "MEPHC" and request.get("status_request") is True and request.get("attachments") == []:
            found.append(directory)
    return max(found, key=lambda path: path.stat().st_mtime_ns) if found else None


def _request_arguments(directory: Path) -> list[str]:
    receipt = directory / "receipt.json"
    if receipt.is_file():
        try:
            state = json.loads(receipt.read_text(encoding="utf-8")).get("state")
        except (OSError, json.JSONDecodeError):
            state = None
        if state in RECOVERY_ONLY:
            return ["--request-directory", str(directory), "--recovery-only"]
    return ["--request-directory", str(directory)]


def _wait_silently(job_id: str, seconds: int = 30) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        state = jobctl.read_state(job_id)
        if state.get("state") in TERMINAL or time.monotonic() >= deadline:
            return state
        time.sleep(0.1)


def resume() -> dict[str, Any]:
    active = workflow.active()
    if active:
        return active
    pending = _active_courier()
    if pending:
        return pending
    request = _pending_status()
    if request is None:
        creation = jobctl.submit("courier", ["--create-status"], None)
        state = _wait_silently(creation.name)
        if state.get("state") != "succeeded":
            return {
                "workflow_state": "awaiting_status_request_creation",
                "pending_job_id": creation.name,
                "job_state": state.get("state"),
                "safe_next_tool": "mephc_wait",
                "retry_allowed": False,
            }
        request = _pending_status()
        if request is None:
            return {
                "workflow_state": "recovery_required",
                "error_code": "STATUS_REQUEST_CREATION_MISSING",
                "safe_next_tool": "mephc_status",
                "retry_allowed": False,
            }
    dispatch = jobctl.submit("courier", _request_arguments(request), None)
    return {
        "workflow_state": "awaiting_supervisor",
        "pending_job_id": dispatch.name,
        "request_directory": str(request),
        "safe_next_tool": "mephc_wait",
        "retry_allowed": False,
    }
