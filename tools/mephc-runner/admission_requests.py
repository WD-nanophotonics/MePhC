"""Durable admission-request envelope and reconciliation index."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import active_index
import job_semantics
import runtime_config as config

REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
ROOT = config.RUNTIME / "admission-requests"


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _path(request_id: str) -> Path:
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise ValueError("ADMISSION_REQUEST_ID_INVALID")
    return ROOT / f"{request_id}.json"


def _read(request_id: str) -> dict[str, Any] | None:
    path = _path(request_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except FileNotFoundError:
        return None


def begin(request_id: str, tool: str, arguments: object, *, source_commit: str | None,
          runner_build: str | None, state_epoch: str) -> dict[str, Any]:
    path = _path(request_id)
    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    existing = _read(request_id)
    if existing:
        if existing.get("tool") != tool or existing.get("payload_sha256") != hashlib.sha256(payload).hexdigest():
            raise ValueError("ADMISSION_REQUEST_ID_COLLISION")
        return existing
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    value = {
        "schema": "mephc-admission-request-v1",
        "admission_request_id": request_id,
        "tool": tool,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "source_commit": source_commit,
        "runner_build": runner_build,
        "state_epoch": state_epoch,
        "phase": "admission_accepted",
        "created_at": now,
        "updated_at": now,
        "job_id": None,
        "dispatch_reached": False,
        "native_process_started": False,
    }
    _atomic(path, value)
    return value


def update(request_id: str, **fields: Any) -> dict[str, Any]:
    value = _read(request_id)
    if value is None:
        raise ValueError("ADMISSION_REQUEST_NOT_FOUND")
    value.update(fields)
    value["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic(_path(request_id), value)
    return value


def bind_job(request_id: str | None, job_id: str) -> None:
    if request_id:
        update(request_id, job_id=job_id, job_created=True, phase="job_bound")


def response_ready(request_id: str | None, result: dict[str, Any]) -> None:
    if not request_id:
        return
    fields: dict[str, Any] = {"phase": "response_ready", "response_ready": True}
    for key in ("job_id", "job_created", "error_code", "safe_next_tool", "retry_allowed", "new_job_allowed"):
        if key in result:
            fields[key] = result[key]
    update(request_id, **fields)


def disconnected(request_id: str) -> dict[str, Any]:
    value = _read(request_id)
    if value is None:
        return {"state": "not_found", "error_code": "ADMISSION_REQUEST_NOT_FOUND",
                "admission_request_id": request_id, "retry_allowed": False,
                "safe_next_tool": "mephc_capabilities"}
    phase = "disconnected_after_job" if value.get("job_id") else "disconnected_before_job"
    update(request_id, phase=phase, disconnect_observed=True)
    return status(request_id)


def status(request_id: str) -> dict[str, Any]:
    value = _read(request_id)
    if value is None:
        return {"state": "not_found", "error_code": "ADMISSION_REQUEST_NOT_FOUND",
                "admission_request_id": request_id, "job_created": False,
                "retry_allowed": False, "new_job_allowed": False,
                "safe_next_tool": "mephc_capabilities"}
    job_id = value.get("job_id")
    job_state: dict[str, Any] = {}
    if isinstance(job_id, str):
        state_path = config.JOBS / job_id / "state.json"
        try:
            job_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            job_state = {"state": "ready" if (config.JOBS / job_id / "READY").is_file() else "unknown"}
        lifecycle = config.JOBS / job_id / "native-lifecycle.json"
        try:
            native = json.loads(lifecycle.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            native = {}
    else:
        native = {}
    state_name = job_state.get("state") if job_state else "request_recorded"
    semantics = job_semantics.enrich(state_name, job_state.get("operation"), job_state.get("error_code"),
                                     job_state.get("phase"))
    safe = ("mephc_status" if isinstance(job_id, str) else
            value.get("safe_next_tool") or "mephc_work_order_preflight")
    return {
        "schema": "mephc-admission-request-status-v1",
        "admission_request_id": request_id,
        "tool": value.get("tool"),
        "payload_sha256": value.get("payload_sha256"),
        "phase": value.get("phase"),
        "job_created": isinstance(job_id, str),
        "job_id": job_id,
        "job_state": state_name,
        "terminal_state": semantics["terminal_state"],
        "dispatch_reached": bool(value.get("dispatch_reached") or job_state.get("phase") not in {None, "queued"}),
        "native_process_started": bool(native.get("native_process_started")),
        "retry_allowed": False,
        "same_job_recovery_allowed": semantics["same_job_recovery_allowed"],
        "new_job_allowed": semantics["new_job_allowed"] if job_id else bool(value.get("new_job_allowed", False)),
        "failure_layer": job_state.get("failure_layer") or value.get("failure_layer"),
        "failure_code": job_state.get("error_code") or value.get("error_code"),
        "safe_next_tool": safe,
    }


def unresolved() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(ROOT.glob("*.json")) if ROOT.is_dir() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("phase") not in {"response_ready"}:
            item = status(value.get("admission_request_id"))
            if item.get("terminal_state") is None:
                result.append(item)
    return result
