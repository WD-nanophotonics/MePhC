#!/home/icy/miniconda3/envs/mp/bin/python
"""Quarantine never-started jobs bound to an older source before runtime activation."""
from __future__ import annotations

import argparse
try:
    import fcntl
except ModuleNotFoundError:  # Import-only support for Windows infrastructure tests.
    class _Fcntl:
        LOCK_EX = 0
        LOCK_NB = 0
        @staticmethod
        def flock(*_args: Any) -> None: return None
    fcntl = _Fcntl()
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

import active_index
import runtime_config as config

JOBS = config.JOBS
RUNTIME = config.RUNTIME
FINAL = {"succeeded", "failed"}
MAX_BYTES = 4 * 1024 * 1024


def _read(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_BYTES: raise ValueError("oversized")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError("object required")
    return value


def inventory(target_source_commit: str) -> dict[str, Any]:
    stale, blockers = [], []
    for directory in sorted(JOBS.iterdir()) if JOBS.is_dir() else []:
        if not directory.is_dir() or not (directory / "READY").is_file() or (directory / "CLAIMED").exists():
            continue
        try:
            job = _read(directory / "job.json")
            state_path = directory / "state.json"
            state = _read(state_path).get("state") if state_path.is_file() else "ready"
            if state in FINAL: continue
            if state in {"recovery_required", "recovery_requested"}:
                blockers.append({"job_id":directory.name, "state":state, "operation":job.get("operation")})
                continue
            item = {"job_id":directory.name, "operation":job.get("operation"),
                    "source_commit":job.get("source_commit"), "state":state,
                    "job_sha256":hashlib.sha256((directory / "job.json").read_bytes()).hexdigest(),
                    "ready_sha256":hashlib.sha256((directory / "READY").read_bytes()).hexdigest()}
            (blockers if job.get("source_commit") == target_source_commit else stale).append(item)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            blockers.append({"job_id":directory.name, "state":"unknown", "error":type(exc).__name__})
    return {"schema":"mephc-stale-ready-reconciliation-v1", "target_source_commit":target_source_commit,
            "stale_candidates":stale, "current_or_unknown_blockers":blockers,
            "stale_count":len(stale), "blocker_count":len(blockers)}


def _atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def apply(target_source_commit: str) -> dict[str, Any]:
    lock_path = RUNTIME / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError("STALE_READY_WORKER_MUST_BE_STOPPED") from exc
        plan = inventory(target_source_commit)
        if plan["current_or_unknown_blockers"]:
            raise RuntimeError("STALE_READY_RECONCILIATION_BLOCKED")
        reconciled = []
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for item in plan["stale_candidates"]:
            directory = JOBS / item["job_id"]
            ready = directory / "READY"
            if (directory / "CLAIMED").exists() or hashlib.sha256(ready.read_bytes()).hexdigest() != item["ready_sha256"]:
                raise RuntimeError("STALE_READY_BYTE_DRIFT")
            archived = directory / "READY.quarantined-runtime-activation"
            if archived.exists(): raise RuntimeError("STALE_READY_ARCHIVE_EXISTS")
            os.replace(ready, archived)
            state = {"state":"failed", "terminal_state":"failed", "updated_at":timestamp,
                     "phase":"terminal", "retry_allowed":False, "same_job_recovery_allowed":False,
                     "new_job_allowed":False, "failure_layer":"worker_contract",
                     "failure_code":"RUNTIME_ACTIVATION_STALE_QUEUED_JOB",
                     "error_code":"RUNTIME_ACTIVATION_STALE_QUEUED_JOB",
                     "safe_next_tool":"mephc_runtime_attest", "reconciliation":item}
            _atomic(directory / "state.json", state)
            with (directory / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"event":"stale_ready_quarantined", "timestamp":timestamp,
                                         "target_source_commit":target_source_commit}, sort_keys=True) + "\n")
            active_index.update(RUNTIME, directory.name, "failed", item.get("operation"))
            reconciled.append(directory.name)
        receipt = {**plan, "applied":True, "reconciled_job_ids":reconciled, "applied_at":timestamp}
        receipt_dir = RUNTIME / "migrations" / "stale-ready"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _atomic(receipt_dir / f"{digest}.json", receipt)
        return {**receipt, "receipt_sha256":digest}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "apply"))
    parser.add_argument("--target-source-commit", required=True)
    args = parser.parse_args()
    if not __import__("re").fullmatch(r"[0-9a-f]{40}", args.target_source_commit): return 2
    value = inventory(args.target_source_commit) if args.mode == "inventory" else apply(args.target_source_commit)
    print(json.dumps(value, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
