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
SHA64 = re.compile(r"^[0-9a-f]{64}$")
SUBMISSION_EVENTS = {
    "submission_intent_writing", "submission_intent_written", "browser_launch_requested",
    "browser_started", "request_submitted", "waiting_for_response", "response_waiting", "submission_unconfirmed",
    "chat_submission_unconfirmed", "submission_state_uncertain", "response_received",
}
NORMALIZATIONS = {
    "task_difficulty": {"low": "normal"},
    "instruction_level": {"low": "normal"},
}
ALLOWED_DIFFICULTIES = {"normal", "hard", "challenge"}
ALLOWED_INSTRUCTION_LEVELS = {"normal", "detailed", "manual_book"}


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
    required = {"version": 1, "project_id": "MEPHC", "request_id": request_id,
                "transport_canary": True, "attachments": []}
    if any(before.get(key) != value for key, value in required.items()):
        raise RuntimeError("CANARY_MANIFEST_NOT_MIGRATABLE")
    message_file = before.get("message_file")
    if not isinstance(message_file, str) or Path(message_file).name != message_file:
        raise RuntimeError("CANARY_MESSAGE_FILE_INVALID")
    message_path = request_dir / message_file
    if not message_path.is_file() or message_path.is_symlink():
        raise RuntimeError("CANARY_MESSAGE_FILE_INVALID")
    try:
        message = message_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError("CANARY_MESSAGE_FILE_INVALID") from exc
    window = before.get("workflow_window_seconds", 600)
    queue_wait = before.get("queue_wait_seconds", 3600)
    if not isinstance(window, int) or not 1 <= window <= 3600:
        raise RuntimeError("CANARY_WORKFLOW_WINDOW_INVALID")
    if not isinstance(queue_wait, int) or not 1 <= queue_wait <= 7200:
        raise RuntimeError("CANARY_QUEUE_WAIT_INVALID")
    if before.get("chat_url") is not None:
        raise RuntimeError("CANARY_EXPLICIT_CHAT_URL_FORBIDDEN")
    key = before.get("transport_canary_idempotency_key")
    expected_message = ("MEPHC infrastructure transport canary. No scientific task or content. "
                        f"CANARY_BINDING={key}\nReply exactly: MEPHC_TRANSPORT_CANARY_OK={key}\n")
    if not isinstance(key, str) or not SHA64.fullmatch(key) or request_id.rsplit("-", 1)[-1] != key[:24].upper():
        raise RuntimeError("CANARY_IDEMPOTENCY_BINDING_INVALID")
    if message != expected_message:
        raise RuntimeError("CANARY_MESSAGE_BINDING_INVALID")

    after = copy.deepcopy(before)
    changes: dict[str, dict[str, str]] = {}
    for field, replacements in NORMALIZATIONS.items():
        value = after.get(field, "normal")
        if value in replacements:
            replacement = replacements[value]
            changes[field] = {"before": value, "after": replacement}
            after[field] = replacement
    if after.get("task_difficulty", "normal") not in ALLOWED_DIFFICULTIES:
        raise RuntimeError("CANARY_TASK_DIFFICULTY_INVALID")
    if after.get("instruction_level", "normal") not in ALLOWED_INSTRUCTION_LEVELS:
        raise RuntimeError("CANARY_INSTRUCTION_LEVEL_INVALID")
    if not changes:
        raise RuntimeError("CANARY_MANIFEST_ALREADY_COMPATIBLE")
    after_bytes = (json.dumps(after, sort_keys=True) + "\n").encode("utf-8")
    result = {
        "schema": "mephc-canary-metadata-migration-v2",
        "request_id": request_id,
        "changes": changes,
        "courier_manifest_contract": {
            "version": 1,
            "workflow_window_seconds": [1, 3600],
            "queue_wait_seconds": [1, 7200],
            "task_difficulty": sorted(ALLOWED_DIFFICULTIES),
            "instruction_level": sorted(ALLOWED_INSTRUCTION_LEVELS),
        },
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
        receipt = config.RUNTIME / "migrations" / "canary-metadata" / f"{request_id}-{sha256(before_bytes)[:16]}.json"
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
