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

INSTALL_ROOT = Path(__file__).resolve().parent
if str(INSTALL_ROOT) not in sys.path: sys.path.insert(0, str(INSTALL_ROOT))
import workflow

ROOT = Path("/home/icy/MePhC")
INSTALL_ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".relayctl" / "runner"
JOBS = RUNTIME / "jobs"
CERTIFICATES = ROOT / ".relayctl" / "certificates"
NATIVE_RECIPES = INSTALL_ROOT / "native-recipes.json"
TERMINAL = {"succeeded", "failed", "recovery_required"}
OPERATIONS = {"doctor", "worktree", "prelive", "native", "publish", "courier", "change"}
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
    if operation == "prelive":
        for target in arguments:
            file_part = target.split("::", 1)[0]
            relative = Path(file_part)
            if (target.startswith("-") or relative.is_absolute() or ".." in relative.parts
                    or relative.parts[:1] != ("tests",) or relative.suffix != ".py"
                    or not (ROOT / relative).is_file()):
                raise SystemExit(f"invalid prelive test target: {target}")
    if operation == "courier":
        if arguments in (["--create-e2e"], ["--create-status"]):
            return
        ordinary = len(arguments) == 2 and arguments[0] == "--request-directory"
        recovery = len(arguments) == 3 and arguments[0] == "--request-directory" and arguments[2] == "--recovery-only"
        if not (ordinary or recovery):
            raise SystemExit("courier requires --request-directory <MePhC outbox path> [--recovery-only]")
        request = Path(arguments[1]).resolve(strict=False)
        try:
            request.relative_to((ROOT / ".relayctl" / "outbox").resolve())
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
    binding = courier_binding(arguments) if operation == "courier" else None
    if binding is not None:
        record["courier_binding"] = binding
    record["payload_sha256"] = hashlib.sha256(canonical(record)).hexdigest()
    atomic_write(job_dir / "job.json", (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    atomic_write(job_dir / "READY", (record["payload_sha256"] + "\n").encode("ascii"))
    emit("runner_job_submitted", job_id=job_id, job_directory=str(job_dir), payload_sha256=record["payload_sha256"])
    return job_dir
def submit_change(change: dict[str, Any]) -> Path:
    required = {"expected_main", "files", "tests", "commit_message"}
    if not isinstance(change, dict) or set(change) != required:
        raise SystemExit("change payload schema mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(change.get("expected_main", ""))):
        raise SystemExit("expected_main must be a Git SHA")
    files = change.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("change files must be non-empty")
    keys = {"path", "expected_preimage_sha256", "expected_postimage_sha256", "content_utf8"}
    for item in files:
        if not isinstance(item, dict) or set(item) != keys:
            raise SystemExit("invalid change file record")
        if item["expected_preimage_sha256"] != "MISSING" and not SHA64.fullmatch(str(item["expected_preimage_sha256"])):
            raise SystemExit("invalid preimage SHA")
        if not SHA64.fullmatch(str(item["expected_postimage_sha256"])):
            raise SystemExit("invalid postimage SHA")
    job_id = f"MEPHC-JOB-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(6).upper()}"
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    record = {"schema":"mephc-runner-job-v1", "job_id":job_id, "project_id":"MEPHC",
              "operation":"change", "arguments":[], "expected_root":str(ROOT),
              "expected_head":git_head(), "certificate_sha256":latest_certificate_sha256(),
              "created_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "change":change}
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
    for directory in sorted(JOBS.iterdir()) if JOBS.is_dir() else []:
        if not directory.is_dir():continue
        value=read_state(directory.name);name=value.get("state")
        if name=="unknown":orphaned.append(directory.name)
        elif name not in TERMINAL:active.append({"job_id":directory.name,"state":name,"safe_next_action":"status_or_wait"})
    return {"schema":"mephc-runner-capabilities-v2","project_id":"MEPHC","canonical_root":str(ROOT),"operations":sorted(OPERATIONS|{"resume"}),"arbitrary_shell":False,"direct_browser":False,"active_jobs":active,"orphaned_job_count":len(orphaned),"head":git_head(),**workflow.view(),"safe_next_tool":"mephc_resume" if not active else "mephc_status_or_wait"}
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


def request_recovery(job_id: str) -> None:
    value=read_state(job_id); directory=JOBS/job_id
    permitted=value.get("state")=="recovery_required"
    if value.get("state")=="failed":
        try: job=json.loads((directory/"job.json").read_text(encoding="utf-8"))
        except Exception: job={}
        permitted=(job.get("operation")=="change" and (directory/"change-attestation.json").is_file()
                   and (directory/"change-journal.json").is_file())
    if not permitted: raise SystemExit(f"job is not recoverable: {value.get('state')}")
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
        job_dir = submit("doctor", [], None); return wait(job_dir.name, args.wait_seconds)
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

