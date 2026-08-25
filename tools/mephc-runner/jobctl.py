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
from typing import Any

ROOT = Path("/home/icy/MePhC")
RUNTIME = ROOT / ".relayctl" / "runner"
JOBS = RUNTIME / "jobs"
CERTIFICATES = ROOT / ".relayctl" / "certificates"
TERMINAL = {"succeeded", "failed", "recovery_required"}
OPERATIONS = {"doctor", "worktree", "prelive", "native", "publish", "courier"}
SHA64 = re.compile(r"^[0-9a-f]{64}$")


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
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise SystemExit(f"cannot resolve MePhC HEAD: {completed.stderr.strip()}")
    return completed.stdout.strip()


def latest_certificate_sha256() -> str:
    candidates = sorted(CERTIFICATES.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not candidates:
        raise SystemExit("no relayctl doctor certificate exists")
    return hashlib.sha256(candidates[0].read_bytes()).hexdigest()


def validate_arguments(operation: str, arguments: list[str]) -> None:
    if operation == "doctor" and arguments:
        raise SystemExit("doctor accepts no relayctl arguments")
    if operation == "courier":
        if len(arguments) != 2 or arguments[0] != "--request-directory":
            raise SystemExit("courier requires exactly --request-directory <MePhC outbox path>")
        request = Path(arguments[1]).resolve(strict=False)
        try:
            request.relative_to((ROOT / ".relayctl" / "outbox").resolve())
        except ValueError as exc:
            raise SystemExit("courier request is outside the MePhC outbox") from exc


def submit(operation: str, arguments: list[str], certificate_sha256: str | None) -> Path:
    if operation not in OPERATIONS:
        raise SystemExit(f"operation not allowed: {operation}")
    validate_arguments(operation, arguments)
    certificate = "" if operation == "doctor" else (certificate_sha256 or latest_certificate_sha256())
    if operation != "doctor" and not SHA64.fullmatch(certificate):
        raise SystemExit("certificate SHA-256 is invalid")
    job_id = f"MEPHC-JOB-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6).upper()}"
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    record: dict[str, Any] = {
        "schema": "mephc-runner-job-v1",
        "job_id": job_id,
        "project_id": "MEPHC",
        "operation": operation,
        "arguments": arguments,
        "expected_root": str(ROOT),
        "expected_head": git_head(),
        "certificate_sha256": certificate,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    record["payload_sha256"] = hashlib.sha256(canonical(record)).hexdigest()
    atomic_write(job_dir / "job.json", (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    atomic_write(job_dir / "READY", (record["payload_sha256"] + "\n").encode("ascii"))
    emit("runner_job_submitted", job_id=job_id, job_directory=str(job_dir), payload_sha256=record["payload_sha256"])
    return job_dir


def read_state(job_id: str) -> dict[str, Any]:
    path = JOBS / job_id / "state.json"
    if not path.is_file():
        return {"state": "ready" if (JOBS / job_id / "READY").is_file() else "unknown"}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"invalid state file: {path}")
    return value


def wait(job_id: str, timeout: int) -> int:
    deadline = time.monotonic() + timeout
    while True:
        value = read_state(job_id)
        if value.get("state") in TERMINAL:
            emit("runner_job_terminal", job_id=job_id, **value)
            return 0 if value.get("state") == "succeeded" else 1
        if time.monotonic() >= deadline:
            emit("runner_wait_timeout", job_id=job_id, state=value.get("state"))
            return 2
        time.sleep(1.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mephc-runner")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--wait-seconds", type=int, default=120)
    submit_parser = sub.add_parser("submit")
    submit_parser.add_argument("operation", choices=sorted(OPERATIONS))
    submit_parser.add_argument("--certificate-sha256")
    submit_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    status = sub.add_parser("status")
    status.add_argument("job_id")
    wait_parser = sub.add_parser("wait")
    wait_parser.add_argument("job_id")
    wait_parser.add_argument("--timeout", type=int, default=4860)
    recover = sub.add_parser("recover")
    recover.add_argument("job_id")
    args = parser.parse_args(argv)

    if args.command == "doctor":
        job_dir = submit("doctor", [], None)
        return wait(job_dir.name, args.wait_seconds)
    if args.command == "submit":
        submit(args.operation, args.arguments, args.certificate_sha256)
        return 0
    if args.command == "status":
        emit("runner_job_status", job_id=args.job_id, **read_state(args.job_id))
        return 0
    if args.command == "wait":
        return wait(args.job_id, args.timeout)
    if args.command == "recover":
        value = read_state(args.job_id)
        if value.get("state") != "recovery_required":
            raise SystemExit(f"job is not recovery_required: {value.get('state')}")
        marker = JOBS / args.job_id / "RECOVER"
        atomic_write(marker, (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n").encode("ascii"))
        emit("runner_recovery_requested", job_id=args.job_id)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
