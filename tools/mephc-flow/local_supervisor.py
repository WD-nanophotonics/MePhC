"""Durable parsing for Chat replies that require local-only diagnosis."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

FILENAME = "local-supervisor-required.json"


def parse(text: str) -> dict[str, str] | None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not re.search(r"^LOCAL_SUPERVISOR_REQUIRED\s*[:=]\s*true\s*$",
                     normalized, re.MULTILINE | re.IGNORECASE):
        return None

    def field(name: str, fallback: str) -> str:
        match = re.search(rf"^{name}\s*[:=]\s*([^\n]+)$", normalized, re.MULTILINE)
        return (match.group(1).strip() if match else fallback)[:1000]

    return {"reason": field("LOCAL_SUPERVISOR_REASON", "UNSPECIFIED_LOCAL_EVIDENCE_GAP"),
            "missing_remote_evidence": field(
                "MISSING_REMOTE_EVIDENCE", "Chat did not identify the missing remote evidence")}


def load(directory: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((directory / FILENAME).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    return value if isinstance(value, dict) else None


def persist(directory: Path, response_path: Path, text: str,
            request: dict[str, Any]) -> dict[str, Any] | None:
    parsed = parse(text)
    if parsed is None:
        return None
    evidence = {"schema": "mephc-local-supervisor-required-v1",
                "error_code": "LOCAL_SUPERVISOR_REQUIRED",
                "work_order_id": request.get("work_order_id"),
                "request_id": request.get("request_id", directory.name),
                "response_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
                **parsed, "captured_at": time.time()}
    path = directory / FILENAME
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return evidence
