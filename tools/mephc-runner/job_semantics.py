"""Central durable-job outcome and recovery semantics."""
from __future__ import annotations

from typing import Any

TERMINAL = {"succeeded", "failed", "recovery_required"}


def failure_layer(code: str | None) -> str | None:
    if not code:
        return None
    if code.startswith(("ADMISSION_", "BACKEND_")): return "admission"
    if code.startswith(("BROKER_", "WINDOWS_MATERIAL")): return "broker"
    if code.startswith(("RUNNER_CONTRACT_", "JOB_SCHEMA", "RETENTION_QUERY", "CONTROL_ROOT",
                        "SOURCE_COMMIT", "STATE_EPOCH", "MAIN_MOVED")): return "worker_contract"
    if code.startswith(("CHAT_", "COURIER_", "RESPONSE_", "SUBMISSION_")): return "transport"
    return "operation"


def enrich(state: str, operation: str | None = None, error_code: str | None = None,
           phase: str | None = None, **overrides: Any) -> dict[str, Any]:
    terminal_state = state if state in TERMINAL else None
    same_recovery = state == "recovery_required"
    retry = False
    new_job = state in {"succeeded"}
    if state == "failed" and operation not in {"change", "courier", "retention_search", "native"}:
        new_job = True
    value = {
        "terminal_state": terminal_state,
        "retry_allowed": retry,
        "same_job_recovery_allowed": same_recovery,
        "new_job_allowed": new_job,
        "failure_layer": failure_layer(error_code),
        "failure_code": error_code,
        "phase": phase or ("terminal" if terminal_state else "queued" if state == "ready" else state),
    }
    value.update(overrides)
    return value
