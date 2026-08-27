#!/home/icy/miniconda3/envs/mp/bin/python
"""Safely normalize a never-submitted infrastructure canary manifest."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows unit-test fallback
    class fcntl:  # type: ignore[no-redef]
        LOCK_EX = LOCK_NB = 0

        @staticmethod
        def flock(*_args) -> None:
            return None

INSTALL_ROOT = Path(__file__).resolve().parent
if str(INSTALL_ROOT) not in sys.path:
    sys.path.insert(0, str(INSTALL_ROOT))
import runtime_config as config


REQUEST_ID = re.compile(r"^MEPHC-INFRA-CANARY-[0-9A-F]{24}$")
SUBMISSION_EVENTS = {
    "request_submitted", "waiting_for_response", "submission_unconfirmed",
    "chat_submission_unconfirmed", "submission_state_uncertain", "response_received",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def submitted_events(path: Path) -> list[str]:
    found: list[str] = []
    if not path.is_file():
        return found
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"CANARY_EVENTS_INVALID:line={number}") from exc
        event = value.get("event") if isinstance(value, dict) else None
        if event in SUBMISSION_EVENTS:
            found.append(str(event))
    return found


def migrate(request_id: str, apply: bool) -> dict:
    if not REQUEST_ID.fullmatch(request_id):
        raise RuntimeError("CANARY_REQUEST_ID_INVALID")
    request_dir = config.OUTBOX / request_id
    if not request_dir.is_dir() or request_dir.is_symlink():
        raise RuntimeError("CANARY_REQUEST_DIRECTORY_INVALID")
    manifest_path = request_dir / "request.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise RuntimeError("CANARY_MANIFEST_INVALID")
    if (request_dir / "receipt.json").exists() or (request_dir / "response.txt").exists():
        raise RuntimeError("CANARY_ALREADY_ENTERED_TRANSPORT")
    observed_submission_events = submitted_events(request_dir / "events.jsonl")
    if observed_submission_events:
        raise RuntimeError(f"CANARY_ALREADY_SUBMITTED:{observed_submission_events}")

    before_bytes = manifest_path.read_bytes()
    before = json.loads(before_bytes.decode("utf-8"))
    required = {
        "project_id": "MEPHC", "request_id": request_id, "transport_canary": True,
        "attachments": [], "task_difficulty": "low",
    }
    if any(before.get(key) != value for key, value in required.items()):
        raise RuntimeError("CANARY_MANIFEST_NOT_MIGRATABLE")
    after = copy.deepcopy(before)
    after["task_difficulty"] = "normal"
    after_bytes = (json.dumps(after, sort_keys=True) + "\n").encode("utf-8")
    result = {
        "schema": "mephc-canary-metadata-migration-v1",
        "request_id": request_id,
        "field": "task_difficulty",
        "before": "low",
        "after": "normal",
        "request_sha256_before": sha256(before_bytes),
        "request_sha256_after": sha256(after_bytes),
        "receipt_present": False,
        "response_present": False,
        "submission_events": [],
        "applied": apply,
    }
    if apply:
        atomic_json(manifest_path, after)
        result["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        receipt = config.RUNTIME / "migrations" / "canary-metadata" / f"{request_id}.json"
        result["migration_receipt"] = str(receipt)
        atomic_json(receipt, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config.RUNTIME.mkdir(parents=True, exist_ok=True)
    with (config.RUNTIME / "worker.lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(migrate(args.request_id, args.apply), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
