#!/usr/bin/env python3
"""Operator-only, hash-bound quarantine for oversized Runner state evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

import active_index
import runtime_config as config

JOB_ID = re.compile(r"^MEPHC-JOB-[A-Z0-9][A-Z0-9._-]{7,119}$")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def quarantine(jobs: Path, job_id: str, state_sha256: str, events_sha256: str) -> dict:
    if not JOB_ID.fullmatch(job_id):
        raise RuntimeError("JOB_ID_INVALID")
    directory = jobs / job_id
    state_path, events_path = directory / "state.json", directory / "events.jsonl"
    if not state_path.is_file() or not events_path.is_file():
        raise RuntimeError("EVIDENCE_MISSING")
    actual_state, actual_events = digest(state_path), digest(events_path)
    if actual_state != state_sha256 or actual_events != events_sha256:
        raise RuntimeError("EVIDENCE_HASH_MISMATCH")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archived_state = directory / f"state.oversized-{stamp}.json"
    archived_events = directory / f"events.oversized-{stamp}.jsonl"
    os.replace(state_path, archived_state)
    os.replace(events_path, archived_events)
    (directory / "RECOVER").unlink(missing_ok=True)
    manifest = {
        "schema": "mephc-runner-oversized-state-quarantine-v1",
        "job_id": job_id,
        "quarantined_at": stamp,
        "files": [
            {"name": archived_state.name, "size_bytes": archived_state.stat().st_size, "sha256": actual_state},
            {"name": archived_events.name, "size_bytes": archived_events.stat().st_size, "sha256": actual_events},
        ],
    }
    atomic_json(directory / "oversized-state-quarantine.json", manifest)
    terminal = {"state": "failed", "updated_at": stamp, "operation": "change",
                "error_code": "OVERSIZED_STATE_QUARANTINED",
                "detail": "Recursive recovery diagnostics were quarantined; no replay performed."}
    atomic_json(state_path, terminal)
    atomic_json(directory / "events.jsonl", {"event": "oversized_state_quarantined", **terminal})
    active_index.update(jobs.parent, job_id, "failed", "change")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--state-sha256", required=True)
    parser.add_argument("--events-sha256", required=True)
    args = parser.parse_args()
    value = quarantine(config.JOBS, args.job_id, args.state_sha256, args.events_sha256)
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
