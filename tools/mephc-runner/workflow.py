from __future__ import annotations
import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path

ROOT = Path("/home/icy/MePhC")
RUNTIME = ROOT / ".relayctl" / "runner"
LEDGER = RUNTIME / "workflow-ledger.json"
OUTBOX = ROOT / ".relayctl" / "outbox"
WORK_ORDER = re.compile(r"^MEPHC-[A-Z0-9][A-Z0-9._-]{7,119}$")


def _atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _response_candidate(path: Path) -> dict | None:
    directory = path.parent
    request_path = directory / "request.json"
    receipt_path = directory / "receipt.json"
    if not request_path.is_file() or not receipt_path.is_file():
        return None
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if request.get("project_id") != "MEPHC" or receipt.get("state") != "response_received":
        return None
    match = re.search(r"^NEXT_WORK_ORDER_ID=([^\r\n]+)$", text, flags=re.MULTILINE)
    if not match or not WORK_ORDER.fullmatch(match.group(1).strip()):
        return None
    return {
        "workflow_state": "available",
        "active_work_order_id": match.group(1).strip(),
        "active_response_path": str(path),
        "active_response_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pending_job_id": None,
        "updated_at": time.time(),
    }


def discover() -> dict | None:
    if not OUTBOX.is_dir():
        return None
    candidates = [candidate for path in OUTBOX.rglob("response.txt") if (candidate := _response_candidate(path))]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (Path(item["active_response_path"]).stat().st_mtime_ns, item["active_response_path"]))


def ensure() -> dict:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "workflow.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        discovered = discover()
        value = discovered or {
            "workflow_state": "idle_unconfirmed",
            "active_work_order_id": None,
            "active_response_path": None,
            "active_response_sha256": None,
            "pending_job_id": None,
            "updated_at": time.time(),
        }
        value["schema"] = "mephc-workflow-ledger-v2"
        _atomic(LEDGER, value)
        return value


def view() -> dict:
    value = ensure()
    return {key: value.get(key) for key in ("workflow_state", "active_work_order_id", "pending_job_id")}


def active() -> dict | None:
    value = ensure()
    source = value.get("active_response_path")
    if not source:
        return None
    path = Path(source)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != value["active_response_sha256"]:
        raise RuntimeError("WORKFLOW_RESPONSE_SHA_MISMATCH")
    return {
        "workflow_state": value["workflow_state"],
        "active_work_order_id": value["active_work_order_id"],
        "source_response_sha256": value["active_response_sha256"],
        "work_order_text": path.read_text(encoding="utf-8-sig"),
        "safe_next_tool": "execute_work_order",
    }
