#!/home/icy/miniconda3/envs/mp/bin/python
"""Fail-closed persistent WSL worker for MePhC relayctl jobs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any

ROOT = Path("/home/icy/MePhC")
PYTHON = Path("/home/icy/miniconda3/envs/mp/bin/python")
RELAYCTL = ROOT / "scripts" / "relayctl"
RUNTIME = ROOT / ".relayctl" / "runner"
JOBS = RUNTIME / "jobs"
CERTIFICATES = ROOT / ".relayctl" / "certificates"
OPERATIONS = {"doctor", "worktree", "prelive", "native", "publish", "courier"}
JOB_ID = re.compile(r"^MEPHC-JOB-[A-Z0-9][A-Z0-9._-]{7,119}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
RECOVERABLE = {"response_timeout", "courier_interrupted", "chat_submission_unconfirmed", "submission_state_uncertain"}
FORBIDDEN_FLAGS = {"--root", "--python", "--pythonpath", "--project-id", "--courier-root", "--profile", "--chat-url"}


class Rejected(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical(value: dict[str, Any]) -> bytes:
    payload = {key: item for key, item in value.items() if key != "payload_sha256"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def event(job_dir: Path, name: str, **fields: Any) -> None:
    record = {"event": name, "timestamp": now(), **fields}
    with (job_dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def state(job_dir: Path, name: str, **fields: Any) -> None:
    atomic_json(job_dir / "state.json", {"state": name, "updated_at": now(), **fields})


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejected("JOB_JSON_INVALID", f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Rejected("JOB_JSON_INVALID", f"{path}: object required")
    return value


def git(*arguments: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), *arguments],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise Rejected("GIT_CHECK_FAILED", completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def certificate_present(digest: str) -> bool:
    if not CERTIFICATES.is_dir():
        return False
    for path in CERTIFICATES.glob("*.json"):
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                return True
        except OSError:
            continue
    return False


def inside(path: Path, parent: Path, code: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(parent.resolve())
    except ValueError as exc:
        raise Rejected(code, f"{resolved} is outside {parent}") from exc
    return resolved


def validate(job_dir: Path) -> tuple[dict[str, Any], str]:
    if not (job_dir / "READY").is_file():
        raise Rejected("JOB_NOT_READY", str(job_dir))
    raw = (job_dir / "job.json").read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    job = read_object(job_dir / "job.json")
    required = {
        "schema", "job_id", "project_id", "operation", "arguments", "expected_root",
        "expected_head", "certificate_sha256", "created_at", "payload_sha256",
    }
    if set(job) != required or job.get("schema") != "mephc-runner-job-v1":
        raise Rejected("JOB_SCHEMA_MISMATCH", f"keys={sorted(job)}")
    if not isinstance(job.get("job_id"), str) or not JOB_ID.fullmatch(job["job_id"]):
        raise Rejected("JOB_ID_INVALID", repr(job.get("job_id")))
    if job_dir.name != job["job_id"]:
        raise Rejected("JOB_DIRECTORY_MISMATCH", f"{job_dir.name} != {job['job_id']}")
    if job.get("project_id") != "MEPHC":
        raise Rejected("PROJECT_MISMATCH", repr(job.get("project_id")))
    if job.get("operation") not in OPERATIONS:
        raise Rejected("OPERATION_NOT_ALLOWED", repr(job.get("operation")))
    if job.get("expected_root") != str(ROOT):
        raise Rejected("ROOT_MISMATCH", repr(job.get("expected_root")))
    if not isinstance(job.get("expected_head"), str) or not SHA40.fullmatch(job["expected_head"]):
        raise Rejected("EXPECTED_HEAD_INVALID", repr(job.get("expected_head")))
    arguments = job.get("arguments")
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise Rejected("ARGUMENTS_INVALID", "array of strings required")
    if any(any(marker in value for marker in ("\x00", "\r", "\n")) for value in arguments):
        raise Rejected("ARGUMENTS_INVALID", "control characters forbidden")
    if any(value.lower() in FORBIDDEN_FLAGS for value in arguments):
        raise Rejected("ARGUMENT_OVERRIDE_FORBIDDEN", repr(arguments))
    expected = hashlib.sha256(canonical(job)).hexdigest()
    if job.get("payload_sha256") != expected:
        raise Rejected("PAYLOAD_SHA256_MISMATCH", f"expected={expected}")

    certificate = job.get("certificate_sha256")
    if job["operation"] == "doctor":
        if arguments or certificate != "":
            raise Rejected("DOCTOR_JOB_INVALID", "doctor accepts no arguments or certificate")
    elif not isinstance(certificate, str) or not SHA64.fullmatch(certificate) or not certificate_present(certificate):
        raise Rejected("CERTIFICATE_INVALID", repr(certificate))

    if job["operation"] == "courier":
        if len(arguments) != 2 or arguments[0] != "--request-directory":
            raise Rejected("COURIER_ARGUMENTS_INVALID", repr(arguments))
        request_dir = inside(Path(arguments[1]), ROOT / ".relayctl" / "outbox", "COURIER_REQUEST_OUTSIDE_OUTBOX")
        request = read_object(request_dir / "request.json")
        if request.get("project_id") != "MEPHC":
            raise Rejected("PROJECT_MISMATCH", f"request={request_dir}")

    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise Rejected("INTERPRETER_MISMATCH", sys.executable)
    if git("rev-parse", "--show-toplevel") != str(ROOT):
        raise Rejected("ROOT_MISMATCH", git("rev-parse", "--show-toplevel"))
    actual_head = git("rev-parse", "HEAD")
    if actual_head != job["expected_head"]:
        raise Rejected("HEAD_MOVED", f"expected={job['expected_head']} actual={actual_head}")
    return job, raw_sha


def receipt_state(job: dict[str, Any]) -> str | None:
    if job["operation"] != "courier":
        return None
    path = Path(job["arguments"][1]) / "receipt.json"
    if not path.is_file():
        return None
    try:
        record = read_object(path)
    except Rejected:
        return None
    value = record.get("state")
    return value if isinstance(value, str) else None


def execute(job_dir: Path, recovery: bool = False) -> None:
    try:
        job, immutable_sha = validate(job_dir)
        claim = job_dir / "CLAIMED"
        previous_attempt = 0
        if recovery:
            old_state = read_object(job_dir / "state.json")
            if job["operation"] != "courier" or old_state.get("state") != "recovery_required":
                raise Rejected("RECOVERY_NOT_ALLOWED", repr(old_state))
            previous_attempt = int(old_state.get("attempt", 1))
            (job_dir / "RECOVER").unlink(missing_ok=True)
        else:
            try:
                descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as exc:
                raise Rejected("JOB_ALREADY_CLAIMED", str(job_dir)) from exc
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(f"pid={os.getpid()} claimed_at={now()} job_sha256={immutable_sha}\n")
                handle.flush()
                os.fsync(handle.fileno())
        attempt = previous_attempt + 1
        state(job_dir, "running", attempt=attempt, operation=job["operation"], recovery=recovery)
        event(job_dir, "runner_job_started", attempt=attempt, operation=job["operation"], recovery=recovery, job_sha256=immutable_sha)
        command = [str(RELAYCTL), job["operation"], *job["arguments"]]
        environment = {
            "HOME": "/home/icy",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/home/icy/miniconda3/envs/mp/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PYTHONPATH": str(ROOT),
            "MEPHC_RUNNER_JOB_ID": job["job_id"],
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
        }
        with (job_dir / "process.log").open("a", encoding="utf-8", newline="\n") as log:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if hashlib.sha256((job_dir / "job.json").read_bytes()).hexdigest() != immutable_sha:
            raise Rejected("JOB_MUTATED_AFTER_CLAIM", str(job_dir / "job.json"))
        courier_state = receipt_state(job)
        if completed.returncode == 0:
            state(job_dir, "succeeded", attempt=attempt, operation=job["operation"], return_code=0, receipt_state=courier_state)
            event(job_dir, "runner_job_succeeded", return_code=0, receipt_state=courier_state)
        elif job["operation"] == "courier" and courier_state in RECOVERABLE:
            state(job_dir, "recovery_required", attempt=attempt, operation="courier", return_code=completed.returncode, receipt_state=courier_state)
            event(job_dir, "runner_recovery_required", return_code=completed.returncode, receipt_state=courier_state)
        else:
            state(job_dir, "failed", attempt=attempt, operation=job["operation"], return_code=completed.returncode, receipt_state=courier_state)
            event(job_dir, "runner_job_failed", return_code=completed.returncode, receipt_state=courier_state)
    except Rejected as exc:
        state(job_dir, "failed", error_code=exc.code, detail=exc.detail)
        event(job_dir, "runner_job_rejected", error_code=exc.code, detail=exc.detail)
    except Exception as exc:
        state(job_dir, "failed", error_code="RUNNER_INTERNAL_ERROR", detail=repr(exc))
        event(job_dir, "runner_internal_error", detail=repr(exc))


def repair_interrupted() -> None:
    for job_dir in JOBS.iterdir() if JOBS.is_dir() else []:
        state_path = job_dir / "state.json"
        if not job_dir.is_dir() or not state_path.is_file():
            continue
        try:
            old_state = read_object(state_path)
            if old_state.get("state") != "running":
                continue
            job = read_object(job_dir / "job.json")
            next_state = "recovery_required" if job.get("operation") == "courier" else "failed"
            code = "WORKER_RESTART_RECOVERY_REQUIRED" if next_state == "recovery_required" else "WORKER_RESTARTED"
            state(job_dir, next_state, attempt=old_state.get("attempt", 1), error_code=code)
            event(job_dir, "runner_interrupted_state_repaired", next_state=next_state, error_code=code)
        except Rejected:
            continue


def heartbeat() -> None:
    atomic_json(RUNTIME / "heartbeat.json", {
        "schema": "mephc-runner-heartbeat-v1",
        "pid": os.getpid(),
        "root": str(ROOT),
        "python": sys.executable,
        "updated_at": now(),
    })


def heartbeat_loop() -> None:
    while True:
        heartbeat()
        time.sleep(2.0)


def main() -> int:
    if Path.cwd().resolve() != ROOT:
        print(json.dumps({"event": "runner_start_failed", "error_code": "ROOT_MISMATCH"}))
        return 2
    if Path(sys.executable).resolve() != PYTHON.resolve():
        print(json.dumps({"event": "runner_start_failed", "error_code": "INTERPRETER_MISMATCH"}))
        return 2
    RUNTIME.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    lock_handle = (RUNTIME / "worker.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"event": "runner_start_failed", "error_code": "WORKER_ALREADY_RUNNING"}))
        return 3
    repair_interrupted()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    while True:
        for job_dir in sorted(path for path in JOBS.iterdir() if path.is_dir()):
            if (job_dir / "RECOVER").is_file():
                execute(job_dir, recovery=True)
            elif (job_dir / "READY").is_file() and not (job_dir / "CLAIMED").exists():
                execute(job_dir)
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
