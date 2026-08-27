"""Small durable index for nonterminal and recovery-required Runner jobs."""
from __future__ import annotations

try:
    import fcntl
except ModuleNotFoundError:  # Import-only support for Windows infrastructure tests.
    class _Fcntl:
        LOCK_EX = 0
        @staticmethod
        def flock(*_args): return None
    fcntl = _Fcntl()
import json
import os
from pathlib import Path
from typing import Any

import runtime_config as config

VISIBLE = {"ready", "running", "recovery_required", "recovery_requested", "unknown"}


def _paths(runtime: Path) -> tuple[Path, Path]:
    return runtime / "active-jobs.json", runtime / "active-jobs.lock"


def _atomic(index: Path, value: dict[str, Any]) -> None:
    index.parent.mkdir(parents=True, exist_ok=True)
    temporary = index.with_name(f".{index.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, index)


def read(runtime: Path = config.RUNTIME) -> dict[str, dict[str, Any]]:
    index, _ = _paths(runtime)
    try:
        value = json.loads(index.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if value.get("schema") != "mephc-active-jobs-v1" or not isinstance(value.get("jobs"), dict):
        raise RuntimeError("ACTIVE_JOB_INDEX_INVALID")
    return value["jobs"]


def update(runtime: Path, job_id: str, state: str, operation: str | None = None) -> None:
    index, lock_path = _paths(runtime)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        jobs = read(runtime)
        if state in VISIBLE:
            jobs[job_id] = {"state": state, "operation": operation}
        else:
            jobs.pop(job_id, None)
        _atomic(index, {"schema": "mephc-active-jobs-v1", "jobs": jobs})


def rebuild(jobs_root: Path) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for directory in sorted(jobs_root.iterdir()) if jobs_root.is_dir() else []:
        if not directory.is_dir():
            continue
        try:
            state = json.loads((directory / "state.json").read_text(encoding="utf-8")).get("state")
        except (OSError, json.JSONDecodeError):
            state = "unknown"
        try:
            job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            job = {}
        if state in VISIBLE:
            jobs[directory.name] = {"state": state, "operation": job.get("operation")}
    _atomic(jobs_root.parent / "active-jobs.json", {"schema": "mephc-active-jobs-v1", "jobs": jobs})
    return jobs
