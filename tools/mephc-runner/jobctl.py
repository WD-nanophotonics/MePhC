#!/home/icy/miniconda3/envs/mp/bin/python
"""Typed client for the persistent MePhC WSL worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

INSTALL_ROOT = Path(__file__).resolve().parent
if str(INSTALL_ROOT) not in sys.path: sys.path.insert(0, str(INSTALL_ROOT))
import workflow
import runtime_config as config
import active_index

ROOT = config.CONTROL_ROOT
INSTALL_ROOT = Path(__file__).resolve().parent
RUNTIME = config.RUNTIME
JOBS = config.JOBS
CERTIFICATES = config.CERTIFICATES
NATIVE_RECIPES = INSTALL_ROOT / "native-recipes.json"
TERMINAL = {"succeeded", "failed", "recovery_required"}
OPERATIONS = {"doctor", "worktree", "prelive", "native", "publish", "courier", "change", "retention_search"}
SHA64 = re.compile(r"^[0-9a-f]{64}$")


class ChangeRejected(ValueError):
    def __init__(self, error_code: str, *, noop_files: list[str] | None = None,
                 safe_next_tool: str = "mephc_change") -> None:
        self.error_code = error_code
        self.noop_files = noop_files or []
        self.safe_next_tool = safe_next_tool
        super().__init__(error_code)


class RetentionRejected(ValueError):
    def __init__(self, error_code: str, safe_next_tool: str = "mephc_resume") -> None:
        self.error_code, self.safe_next_tool = error_code, safe_next_tool
        super().__init__(error_code)


def canonical(value: dict[str, Any]) -> bytes:
    payload = {key: item for key, item in value.items() if key != "payload_sha256"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def emit(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True, ensure_ascii=False), flush=True)


def git_head() -> str:
    command = (["git", "-c", f"safe.directory={config.CONTROL_ROOT_WINDOWS}", "-C", config.CONTROL_ROOT_WINDOWS]
               if os.name == "nt" else [str(config.WINDOWS_GIT_WSL), "-c",
                                          f"safe.directory={config.CONTROL_ROOT_WINDOWS}",
                                          "-C", config.CONTROL_ROOT_WINDOWS])
    completed = subprocess.run(
        [*command, "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=15,
    )
    if completed.returncode:
        raise SystemExit(f"cannot resolve MePhC HEAD: {completed.stderr.strip()}")
    return completed.stdout.strip()


def git_origin_main() -> str:
    return git_ref("origin/main")


def job_v2_base(job_id: str, operation: str, arguments: list[str], certificate: str) -> dict[str, Any]:
    head = git_head()
    origin_main = git_origin_main()
    if origin_main != config.EXPECTED_ORIGIN_MAIN:
        raise SystemExit(f"origin/main moved: {origin_main}")
    return {
        "schema": "mephc-runner-job-v2",
        "job_id": job_id,
        "project_id": "MEPHC",
        "operation": operation,
        "arguments": arguments,
        "expected_control_root": config.CONTROL_ROOT_WINDOWS,
        "source_commit": head,
        "expected_origin_main": origin_main,
        "state_epoch": config.state_epoch(),
        "certificate_sha256": certificate,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def latest_certificate_sha256() -> str:
    candidates = sorted(CERTIFICATES.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not candidates:
        raise SystemExit("no relayctl doctor certificate exists")
    return hashlib.sha256(candidates[0].read_bytes()).hexdigest()


def courier_binding(arguments: list[str]) -> dict[str, str] | None:
    if not arguments or arguments[0] != "--request-directory":
        return None
    request_dir = Path(arguments[1]).resolve()
    request_path = request_dir / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("project_id") != "MEPHC" or request.get("attachments") != []:
        raise SystemExit("courier request must be attachment-free MEPHC")
    message_name = request.get("message_file")
    if not isinstance(message_name, str) or Path(message_name).name != message_name:
        raise SystemExit("courier message_file must be a basename")
    message_path = request_dir / message_name
    certificate_value = request.get("relay_certificate")
    if not isinstance(certificate_value, str):
        raise SystemExit("courier request certificate missing")
    certificate_path = Path(certificate_value)
    if not certificate_path.is_file():
        raise SystemExit("courier request certificate unavailable")
    return {
        "request_id": str(request.get("request_id", "")),
        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        "message_sha256": hashlib.sha256(message_path.read_bytes()).hexdigest(),
        "certificate_sha256": hashlib.sha256(certificate_path.read_bytes()).hexdigest(),
    }


def validate_arguments(operation: str, arguments: list[str]) -> None:
    if operation == "doctor" and arguments:
        raise SystemExit("doctor accepts no relayctl arguments")
    if operation == "change":
        raise SystemExit("change requires the typed JSON interface")
    if operation == "retention_search":
        raise SystemExit("retention_search requires the typed JSON interface")
    if operation == "prelive":
        for target in arguments:
            file_part = target.split("::", 1)[0]
            relative = Path(file_part)
            if (target.startswith("-") or relative.is_absolute() or ".." in relative.parts
                    or relative.parts[:1] != ("tests",) or relative.suffix != ".py"
            or not (config.CONTROL_ROOT / relative).is_file()):
                raise SystemExit(f"invalid prelive test target: {target}")
    if operation == "courier":
        if arguments in (["--create-e2e"], ["--create-attachment-e2e"], ["--create-status"]):
            return
        ordinary = len(arguments) == 2 and arguments[0] == "--request-directory"
        recovery = len(arguments) == 3 and arguments[0] == "--request-directory" and arguments[2] == "--recovery-only"
        if not (ordinary or recovery):
            raise SystemExit("courier requires --request-directory <MePhC outbox path> [--recovery-only]")
        request = Path(arguments[1]).resolve(strict=False)
        try:
            outbox = (ROOT / ".relayctl" / "outbox") if os.name == "nt" else config.OUTBOX
            request.relative_to(outbox.resolve())
        except ValueError as exc:
            raise SystemExit("courier request is outside the MePhC outbox") from exc
    if operation == "native":
        if len(arguments) != 2 or arguments[0] != "--recipe":
            raise SystemExit("native requires --recipe <registered-id>")
        registry = json.loads(NATIVE_RECIPES.read_text(encoding="utf-8"))
        if arguments[1] not in registry.get("recipes", {}):
            raise SystemExit(f"native recipe is not registered: {arguments[1]}")



def submit(operation: str, arguments: list[str], certificate_sha256: str | None) -> Path:
    if operation not in OPERATIONS:
        raise SystemExit(f"operation not allowed: {operation}")
    validate_arguments(operation, arguments)
    blocker = unresolved_change()
    if blocker and operation in {"worktree", "native", "publish", "courier"}:
        raise SystemExit(f"CHANGE_RECOVERY_BLOCKS_SIDE_EFFECTS:{blocker}")
    certificate = "" if operation == "doctor" else (certificate_sha256 or latest_certificate_sha256())
    if operation != "doctor" and not SHA64.fullmatch(certificate):
        raise SystemExit("certificate SHA-256 is invalid")
    job_id = f"MEPHC-JOB-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6).upper()}"
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    record: dict[str, Any] = job_v2_base(job_id, operation, arguments, certificate)
    binding = courier_binding(arguments) if operation == "courier" else None
    if binding is not None:
        record["courier_binding"] = binding
    record["payload_sha256"] = hashlib.sha256(canonical(record)).hexdigest()
    atomic_write(job_dir / "job.json", (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    atomic_write(job_dir / "READY", (record["payload_sha256"] + "\n").encode("ascii"))
    active_index.update(JOBS.parent, job_id, "ready", operation)
    emit("runner_job_submitted", job_id=job_id, job_directory=str(job_dir), payload_sha256=record["payload_sha256"])
    return job_dir


def _retention_allowlist(work_order_text: str) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for match in re.finditer(r"RETENTION_ID=([A-Z0-9][A-Z0-9_.-]{2,127})[ \t]*\r?\n[ \t]*EXPECTED_SHA256=([0-9a-f]{64})",
                             work_order_text):
        allowed[match.group(1)] = match.group(2)
    for match in re.finditer(r"(AUTHORITATIVE_[A-Z0-9_]+)_SHA256=([0-9a-f]{64})", work_order_text):
        allowed[match.group(1)] = match.group(2)
    return allowed


def current_runner_build() -> str:
    try:
        heartbeat = json.loads((RUNTIME / "heartbeat.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetentionRejected("RETENTION_RUNNER_HEALTH_REQUIRED") from exc
    build = heartbeat.get("worker_build_id")
    updated_at = heartbeat.get("updated_at")
    if not isinstance(build, str) or not re.fullmatch(r"[0-9a-f]{16}", build) or not isinstance(updated_at, str):
        raise RetentionRejected("RETENTION_RUNNER_HEALTH_REQUIRED")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at.replace("Z", "+00:00"))).total_seconds()
    except ValueError as exc:
        raise RetentionRejected("RETENTION_RUNNER_HEALTH_REQUIRED") from exc
    if age < -5 or age > 15:
        raise RetentionRejected("RETENTION_RUNNER_HEALTH_REQUIRED")
    return build


def submit_retention_search(bindings: object) -> tuple[Path, bool]:
    active = workflow.active()
    if not active or not isinstance(active.get("work_order_text"), str):
        raise RetentionRejected("RETENTION_ACTIVE_WORK_ORDER_REQUIRED")
    work_order_id = active.get("active_work_order_id")
    if not isinstance(work_order_id, str):
        raise RetentionRejected("RETENTION_ACTIVE_WORK_ORDER_REQUIRED")
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 32:
        raise RetentionRejected("RETENTION_BINDINGS_INVALID")
    allowed = _retention_allowlist(active["work_order_text"])
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in bindings:
        if not isinstance(item, dict) or set(item) != {"retention_id", "expected_sha256"}:
            raise RetentionRejected("RETENTION_BINDINGS_INVALID")
        retention_id, digest = item["retention_id"], item["expected_sha256"]
        if (not isinstance(retention_id, str) or not isinstance(digest, str)
                or retention_id in seen or allowed.get(retention_id) != digest):
            raise RetentionRejected("RETENTION_BINDING_NOT_IN_ACTIVE_WORK_ORDER")
        seen.add(retention_id)
        normalized.append({"retention_id": retention_id, "expected_sha256": digest})
    normalized.sort(key=lambda item: item["retention_id"])
    runner_build = current_runner_build()
    query = {"bindings": normalized, "deadline_seconds": config.RETENTION_SEARCH_TIMEOUT_SECONDS,
             "work_order_id": work_order_id, "runner_build": runner_build}
    query_sha = hashlib.sha256(canonical(query)).hexdigest()
    head, epoch = git_head(), config.state_epoch()
    for directory in sorted(JOBS.iterdir(), reverse=True) if JOBS.is_dir() else []:
        try:
            record = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (record.get("operation") == "retention_search" and record.get("query_sha256") == query_sha
                and record.get("source_commit") == head and record.get("state_epoch") == epoch
                and record.get("active_work_order_id") == work_order_id
                and record.get("runner_build") == runner_build):
            state_value = read_basic_state(directory.name).get("state")
            if (state_value in {"ready", "running", "succeeded", "recovery_required"}
                    or state_value == "failed" and (directory / "retention-search-result.json").is_file()):
                return directory, True
    certificate = latest_certificate_sha256()
    job_id = f"MEPHC-JOB-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6).upper()}"
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    record = job_v2_base(job_id, "retention_search", [], certificate)
    record.update({"schema": "mephc-runner-job-v3", "retention_query": query,
                   "active_work_order_id": work_order_id, "query_sha256": query_sha,
                   "runner_build": runner_build})
    record["payload_sha256"] = hashlib.sha256(canonical(record)).hexdigest()
    atomic_write(job_dir / "job.json", (json.dumps(record, sort_keys=True, indent=2) + "\n").encode())
    atomic_write(job_dir / "READY", (record["payload_sha256"] + "\n").encode("ascii"))
    active_index.update(JOBS.parent, job_id, "ready", "retention_search")
    emit("runner_retention_search_submitted", job_id=job_id, query_sha256=query_sha)
    return job_dir, False
def git_ref(ref: str) -> str:
    command = (["git", "-c", f"safe.directory={config.CONTROL_ROOT_WINDOWS}", "-C", config.CONTROL_ROOT_WINDOWS]
               if os.name == "nt" else [str(config.WINDOWS_GIT_WSL), "-c",
                                          f"safe.directory={config.CONTROL_ROOT_WINDOWS}",
                                          "-C", config.CONTROL_ROOT_WINDOWS])
    completed = subprocess.run([*command, "rev-parse", ref], text=True, encoding="utf-8",
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=15)
    if completed.returncode:
        raise SystemExit(f"cannot resolve MePhC {ref}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def change_path(value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise SystemExit("change path is invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] == (".relayctl",):
        raise SystemExit("change path is outside the controlled source root")
    target = config.CONTROL_ROOT / relative
    if target.is_symlink():
        raise SystemExit("change symlink is forbidden")
    return target


def submit_change(change: dict[str, Any]) -> Path:
    blocker = unresolved_change()
    if blocker:
        raise ChangeRejected("CHANGE_RECOVERY_BLOCKS_SIDE_EFFECTS", safe_next_tool="mephc_status")
    if not isinstance(change, dict) or set(change) != {"files", "tests", "commit_message"}:
        raise SystemExit("change payload schema mismatch")
    files = change.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("change files must be non-empty")
    records: list[dict[str, str]] = []
    noop_files: list[str] = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "content_utf8"}:
            raise SystemExit("invalid change file record")
        target = change_path(item["path"])
        content = item["content_utf8"]
        if not isinstance(content, str):
            raise SystemExit("change content must be UTF-8 text")
        try:
            encoded = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise SystemExit("change content is not UTF-8") from exc
        if target.exists() and not target.is_file():
            raise SystemExit("change target must be a regular file")
        preimage = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else "MISSING"
        postimage = hashlib.sha256(encoded).hexdigest()
        if preimage == postimage:
            noop_files.append(item["path"])
        records.append({"path": item["path"], "expected_preimage_sha256": preimage, "expected_postimage_sha256": postimage, "content_utf8": content})
    if noop_files:
        all_noop = len(noop_files) == len(records)
        raise ChangeRejected("CHANGE_NOOP_USE_VALIDATE" if all_noop else "CHANGE_CONTAINS_NOOP_FILES",
                             noop_files=noop_files,
                             safe_next_tool="mephc_validate" if all_noop else "mephc_change")
    tests = change.get("tests")
    if not isinstance(tests, list) or not tests or not all(isinstance(value, str) for value in tests):
        raise SystemExit("change tests must be non-empty")
    if not isinstance(change.get("commit_message"), str) or not change["commit_message"].strip():
        raise SystemExit("change commit message is required")
    materialized = {"expected_main": git_ref("origin/main"), "files": records, "tests": tests, "commit_message": change["commit_message"]}
    job_id = f"MEPHC-JOB-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6).upper()}"
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    record = job_v2_base(job_id, "change", [], latest_certificate_sha256())
    record["change"] = materialized
    record["payload_sha256"] = hashlib.sha256(canonical(record)).hexdigest()
    atomic_write(job_dir / "job.json", (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    atomic_write(job_dir / "READY", (record["payload_sha256"] + "\n").encode("ascii"))
    active_index.update(JOBS.parent, job_id, "ready", "change")
    emit("runner_job_submitted", job_id=job_id, job_directory=str(job_dir), payload_sha256=record["payload_sha256"])
    return job_dir


def _age(path: Path) -> float | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
        unix = record.get("updated_unix") or record.get("phase_heartbeat_unix")
        if unix is not None:
            return max(0.0, time.time() - float(unix))
        value = record.get("updated_at")
        if isinstance(value, str):
            return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds())
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def _health(path: Path, stale_after: int = 20) -> dict[str, Any]:
    age = _age(path)
    return {"available": age is not None, "age_seconds": round(age, 3) if age is not None else None,
            "stale": age is None or age > stale_after}


def read_state(job_id: str) -> dict[str, Any]:
    path = JOBS / job_id / "state.json"
    if not path.is_file():
        value = {"state": "ready" if (JOBS / job_id / "READY").is_file() else "unknown"}
    elif path.stat().st_size > 1024 * 1024:
        value = {"state": "unknown", "error_code": "STATE_FILE_TOO_LARGE",
                 "size_bytes": path.stat().st_size}
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise SystemExit(f"invalid state file: {path}")
    directory = JOBS / job_id
    progress = None
    for name in ("materializer-progress.json", "client-progress.json", "retention-progress.json"):
        candidate = directory / name
        if candidate.is_file():
            try:
                record = json.loads(candidate.read_text(encoding="utf-8"))
                if progress is None or float(record.get("phase_heartbeat_unix", 0)) >= float(progress.get("phase_heartbeat_unix", 0)):
                    progress = record
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
    result = dict(value)
    terminal = value.get("state") in {"succeeded", "failed"}
    phase = "terminal" if terminal else (progress.get("phase") if progress else ("queued" if value.get("state") == "ready" else value.get("state")))
    last = progress.get("phase_heartbeat_unix") if progress else None
    phase_age = max(0.0, time.time() - float(last)) if last is not None else None
    result.update({"phase": phase, "phase_age_seconds": round(phase_age, 3) if phase_age is not None else None,
                   "last_progress_at_unix": last,
                   "deadline_at_unix": progress.get("deadline_unix") if progress else None,
                   "stalled": bool(value.get("state") == "running" and (phase_age is None or phase_age > 20)),
                   "worker_health": _health(RUNTIME / "heartbeat.json"),
                   "broker_health": _health(config.BROKER_HEARTBEAT),
                   "safe_next_tool": "none" if terminal else
                                     ("mephc_recover" if value.get("state") == "recovery_required" else "mephc_status")})
    return result


def read_basic_state(job_id: str) -> dict[str, Any]:
    """Read only the durable state needed for inventory scans.

    In particular this must not touch the Windows broker heartbeat once per
    historical job; health enrichment belongs only to an explicitly selected
    job.
    """
    directory = JOBS / job_id
    path = directory / "state.json"
    if not path.is_file():
        return {"state": "ready" if (directory / "READY").is_file() else "unknown"}
    if path.stat().st_size > 1024 * 1024:
        return {"state": "unknown", "error_code": "STATE_FILE_TOO_LARGE",
                "size_bytes": path.stat().st_size}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"invalid state file: {path}")
    return value


def unresolved_change() -> str | None:
    for job_id, value in sorted(active_index.read(JOBS.parent).items()):
        if value.get("state") == "recovery_required" and value.get("operation") == "change":
            return job_id
    return None


def active_change() -> str | None:
    for job_id, value in sorted(active_index.read(JOBS.parent).items()):
        if value.get("state") in {"ready", "running"} and value.get("operation") == "change":
            return job_id
    return None


def live_runtime_health(stale_after: int = 15) -> dict[str, Any]:
    worker_path, broker_path = RUNTIME / "heartbeat.json", config.BROKER_HEARTBEAT
    worker_health, broker_health = _health(worker_path, stale_after), _health(broker_path, stale_after)
    worker = broker = None
    try:
        if worker_path.stat().st_size <= 1024 * 1024:
            worker = json.loads(worker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    try:
        if broker_path.stat().st_size <= 1024 * 1024:
            broker = json.loads(broker_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    reasons: list[str] = []
    if worker_health["stale"]: reasons.append("WORKER_HEARTBEAT_STALE")
    if broker_health["stale"]: reasons.append("BROKER_HEARTBEAT_STALE")
    if not isinstance(worker, dict) or not isinstance(broker, dict): reasons.append("RUNTIME_HEARTBEAT_INVALID")
    elif broker.get("worker_ok") is not True: reasons.append("BROKER_WORKER_CHECK_FAILED")
    elif broker.get("broker_build_id") != worker.get("worker_build_id"): reasons.append("RUNNER_BUILD_MISMATCH")
    return {"ok": not reasons, "errors": reasons, "worker": worker_health, "broker": broker_health}


def doctor_deduplicated() -> dict[str, Any]:
    blocked = active_change() or unresolved_change()
    if blocked:
        return {"state": "blocked_by_active_change", "blocking_job_id": blocked,
                "blocking_job": read_state(blocked), "job_created": False,
                "safe_next_tool": "mephc_status"}
    health = live_runtime_health()
    if not health["ok"]:
        return {"state": "blocked_by_runtime_health", "error_code": "DOCTOR_LIVE_HEALTH_FAILED",
                "live_health": health, "job_created": False, "retry_allowed": False,
                "safe_next_tool": "mephc_capabilities"}
    head, epoch = git_head(), config.state_epoch()
    for directory in sorted(JOBS.iterdir(), reverse=True) if JOBS.is_dir() else []:
        try:
            job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("operation") == "doctor" and job.get("source_commit") == head and job.get("state_epoch") == epoch:
            value = read_state(directory.name)
            if value.get("state") in {"ready", "running", "succeeded"}:
                return {"job_id": directory.name, "reused": True, "live_health": health, **value}
    directory = submit("doctor", [], None)
    return {"job_id": directory.name, "state": "ready", "reused": False, "job_created": True,
            "safe_next_tool": "mephc_wait"}


def wait(job_id: str, timeout: int) -> int:
    deadline = time.monotonic() + timeout
    next_heartbeat = time.monotonic() + 30
    while True:
        value = read_state(job_id)
        if value.get("state") in TERMINAL:
            emit("runner_job_terminal", job_id=job_id, **value)
            return 0 if value.get("state") == "succeeded" else 1
        if time.monotonic() >= deadline:
            emit("runner_wait_timeout", job_id=job_id, state=value.get("state"), retry_allowed=False, safe_next_action="status")
            return 2
        if time.monotonic() >= next_heartbeat:
            emit("runner_wait_heartbeat", job_id=job_id, state=value.get("state"), retry_allowed=False, safe_next_action="continue_wait")
            next_heartbeat = time.monotonic() + 30
        time.sleep(1.0)


def capabilities() -> dict[str, Any]:
    active=[];orphaned=[]
    for job_id, value in sorted(active_index.read(JOBS.parent).items()):
        name=value.get("state")
        if name == "unknown":
            orphaned.append(job_id)
            continue
        active.append({"job_id":job_id,"state":name,
                       "operation":value.get("operation"),
                       "safe_next_action":"recover" if name=="recovery_required" else "status_or_wait"})
    head = git_head()
    return {"schema":"mephc-runner-capabilities-v3","project_id":"MEPHC",
            "control_root":config.CONTROL_ROOT_WINDOWS,"state_root":str(config.STATE_ROOT),
            "execution_root_policy":str(config.CHECKOUTS / "<commit-sha>"),
            "source_head":head,"execution_head":None,
            "admission_scope":{"kind":"exact_inherited_windows_cwd","root":config.CONTROL_ROOT_WINDOWS},
            "state_epoch":config.state_epoch(),"operations":sorted(OPERATIONS|{"resume","transport_canary","validate"}),
            "inspect_limits":{"default_bytes":16384,"max_bytes":65536},
            "retention_interface":{"search_deadline_seconds":config.RETENTION_SEARCH_TIMEOUT_SECONDS,
                                   "page_limit":200,"page_max_bytes":65536,
                                   "archive_formats":["tar","tar.gz","tgz","git-bundle"]},
            "arbitrary_shell":False,"direct_browser":False,"active_jobs":active,
            "orphaned_job_count":len(orphaned),**workflow.view(),
            "safe_next_tool":"mephc_resume" if not active else "mephc_status_or_wait"}
def resume() -> dict[str, Any]:
    value=workflow.active()
    return value if value else {"workflow_state":"idle_unconfirmed","error_code":"STATUS_REQUEST_REQUIRED","retry_allowed":False,"safe_next_tool":"mephc_report"}


def retention_plan() -> dict[str, Any]:
    entries = []
    for directory in sorted(JOBS.iterdir()) if JOBS.is_dir() else []:
        if directory.is_dir():
            value = read_state(directory.name)
            size = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
            entries.append({"job_id":directory.name, "state":value.get("state"), "bytes":size, "deletable":False, "reason":"remote verification and explicit deletion authorization required"})
    return {"schema":"mephc-runner-retention-plan-v1", "read_only":True, "entries":entries}


def prewrite_recovery_evidence(directory: Path, job: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {"journal_present": (directory / "change-journal.json").exists(),
                                "attestation_present": (directory / "change-attestation.json").exists()}
    try:
        recovery_state=json.loads((directory/"materializer-recovery-state.json").read_text(encoding="utf-8"))
        evidence["recovery_error_code"]=recovery_state.get("error_code")
        files=job.get("change",{}).get("files",[])
        mismatches=[]
        for item in files:
            target=change_path(item["path"])
            actual=hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else "MISSING"
            if actual != item.get("expected_preimage_sha256"):
                mismatches.append({"path":item.get("path"),"expected":item.get("expected_preimage_sha256"),"actual":actual})
        evidence["declared_file_count"]=len(files)
        evidence["preimage_mismatches"]=mismatches
        status_command=(["git","-c",f"safe.directory={config.CONTROL_ROOT_WINDOWS}","-C",config.CONTROL_ROOT_WINDOWS]
                        if os.name=="nt" else [str(config.WINDOWS_GIT_WSL),"-c",f"safe.directory={config.CONTROL_ROOT_WINDOWS}","-C",config.CONTROL_ROOT_WINDOWS])
        status_result=subprocess.run([*status_command,"status","--porcelain","--untracked-files=all"],capture_output=True,text=True,check=False)
        evidence["git_authority"]="windows_git"
        evidence["git_status_return_code"]=status_result.returncode
        evidence["git_status_stderr"]=status_result.stderr.strip()[-1000:]
        evidence["git_dirty_paths"]=status_result.stdout.splitlines()[:50]
        evidence["permitted"]=(not evidence["journal_present"] and not evidence["attestation_present"]
                               and evidence["recovery_error_code"]=="WINDOWS_MATERIALIZATION_FAILED"
                               and bool(files) and not mismatches and status_result.returncode==0
                               and not status_result.stdout.strip())
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
        evidence["permitted"]=False
        evidence["diagnostic_error"]=repr(exc)
    return evidence


def request_recovery(job_id: str) -> None:
    value=read_state(job_id); directory=JOBS/job_id
    permitted=value.get("state")=="recovery_required"
    prewrite_evidence=None
    if value.get("state")=="failed":
        try: job=json.loads((directory/"job.json").read_text(encoding="utf-8"))
        except Exception: job={}
        permitted=(job.get("operation")=="change" and (directory/"change-attestation.json").is_file()
                   and (directory/"change-journal.json").is_file())
        if job.get("operation")=="change" and not permitted and not (directory/"change-journal.json").exists() and not (directory/"change-attestation.json").exists():
            prewrite_evidence=prewrite_recovery_evidence(directory,job)
            permitted=bool(prewrite_evidence.get("permitted"))
    if not permitted: raise SystemExit(f"job is not recoverable: {value.get('state')};evidence={json.dumps(prewrite_evidence,sort_keys=True)}")
    if value.get("state")=="failed" and job.get("operation")=="change":
        attempt=int(value.get("attempt",1))
        for name in ("materializer-recovery-state.json","broker-recovery-dispatch.json","MATERIALIZE_RECOVER_READY"):
            source=directory/name
            if source.exists():
                archived=directory/f"{name}.attempt-{attempt}"
                if archived.exists(): raise SystemExit(f"recovery attempt archive already exists: {archived.name}")
                os.replace(source,archived)
    atomic_write(directory/"RECOVER",(time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())+"\n").encode("ascii"))
    emit("runner_recovery_requested",job_id=job_id)
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mephc-runner")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor"); doctor.add_argument("--wait-seconds", type=int, default=120)
    submit_parser = sub.add_parser("submit"); submit_parser.add_argument("operation", choices=sorted(OPERATIONS)); submit_parser.add_argument("--certificate-sha256"); submit_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    status = sub.add_parser("status"); status.add_argument("job_id")
    wait_parser = sub.add_parser("wait"); wait_parser.add_argument("job_id"); wait_parser.add_argument("--timeout", type=int, default=4860)
    recover = sub.add_parser("recover"); recover.add_argument("job_id")
    sub.add_parser("change"); sub.add_parser("capabilities"); sub.add_parser("retention-plan")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        value = doctor_deduplicated()
        emit("runner_doctor", **value)
        return wait(value["job_id"], args.wait_seconds) if value.get("job_created") else 0
    if args.command == "submit": submit(args.operation, args.arguments, args.certificate_sha256); return 0
    if args.command == "status": emit("runner_job_status", job_id=args.job_id, **read_state(args.job_id)); return 0
    if args.command == "wait": return wait(args.job_id, args.timeout)
    if args.command == "recover":
        request_recovery(args.job_id); return 0
    if args.command == "change": submit_change(json.load(sys.stdin)); return 0
    if args.command == "capabilities": emit("runner_capabilities", **capabilities()); return 0
    if args.command == "retention-plan": emit("runner_retention_plan", **retention_plan()); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

