"""Structured request rejection shared by importable Runner modules."""
from __future__ import annotations

from typing import Any
import re


class RunnerRequestRejected(ValueError):
    """A normal, pre-job request rejection; never a process-termination signal."""

    def __init__(self, error_code: str, detail: str = "", *,
                 safe_next_tool: str = "mephc_work_order_preflight",
                 retry_allowed: bool = False, new_job_allowed: bool = False,
                 failure_layer: str = "request_validation") -> None:
        self.error_code = error_code
        self.detail = detail
        self.safe_next_tool = safe_next_tool
        self.retry_allowed = retry_allowed
        self.new_job_allowed = new_job_allowed
        self.failure_layer = failure_layer
        super().__init__(f"{error_code}:{detail}" if detail else error_code)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": "rejected",
            "error_code": self.error_code,
            "detail": self.detail,
            "job_created": False,
            "retry_allowed": self.retry_allowed,
            "new_job_allowed": self.new_job_allowed,
            "failure_layer": self.failure_layer,
            "safe_next_tool": self.safe_next_tool,
        }


def legacy_system_exit(exc: SystemExit) -> RunnerRequestRejected:
    """Map a remaining legacy validation exit into a stable request rejection."""
    detail = str(exc.code or "LEGACY_REQUEST_REJECTED")
    normalized = detail.upper().replace(" ", "_").replace(":", "_")
    code = "RUNNER_REQUEST_REJECTED_" + "".join(
        character for character in normalized if character.isalnum() or character == "_"
    )[:96]
    return RunnerRequestRejected(code, detail, safe_next_tool="mephc_work_order_preflight")


def validation_error(exc: ValueError) -> RunnerRequestRejected:
    detail = str(exc)
    candidate = detail.split(":", 1)[0]
    code = candidate if re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", candidate) else "RUNNER_REQUEST_VALIDATION_FAILED"
    return RunnerRequestRejected(code, detail if code != detail else "",
                                 safe_next_tool="mephc_work_order_preflight")
