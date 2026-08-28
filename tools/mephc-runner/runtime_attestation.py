#!/home/icy/miniconda3/envs/mp/bin/python
"""Cross-layer runtime attestation using import-time module digests."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import runtime_config as config

MCP_BUNDLE_FILES = ("mcp_server.py", "jobctl.py", "workflow.py", "work_order_contract.py", "runtime_attestation.py", "job_semantics.py", "runner_errors.py", "admission_requests.py")
CURRENT_MCP_BUNDLE_HASH: str | None = None


def bundle_hash(root: Path, names: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256((root / name).read_bytes()).digest())
    return digest.hexdigest()


def set_loaded_mcp_hash(value: str) -> None:
    global CURRENT_MCP_BUNDLE_HASH
    CURRENT_MCP_BUNDLE_HASH = value


def _json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _fresh(record: dict[str, Any] | None, seconds: int = 20) -> bool:
    if not record or not isinstance(record.get("updated_at"), str): return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return False
    return -5 <= age <= seconds


def _source_head() -> str | None:
    command = (["git", "-c", f"safe.directory={config.CONTROL_ROOT_WINDOWS}", "-C", config.CONTROL_ROOT_WINDOWS]
               if os.name == "nt" else [str(config.WINDOWS_GIT_WSL), "-c", f"safe.directory={config.CONTROL_ROOT_WINDOWS}", "-C", config.CONTROL_ROOT_WINDOWS])
    try:
        result = subprocess.run([*command, "rev-parse", "HEAD"], text=True, capture_output=True, timeout=15, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def attest() -> dict[str, Any]:
    current = _json(config.WINDOWS_RUNTIME_WSL / "current.json") or {}
    manifest_value: Any = None
    try: manifest_value = json.loads((config.WINDOWS_RUNTIME_WSL / "install-manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError): pass
    manifest = ({item.get("name"): item.get("sha256") for item in manifest_value if isinstance(item, dict)}
                if isinstance(manifest_value, list) else {})
    worker = _json(config.RUNTIME / "heartbeat.json")
    broker = _json(config.BROKER_HEARTBEAT)
    build = current.get("build_id")
    mcp_hash = CURRENT_MCP_BUNDLE_HASH or os.environ.get("MEPHC_LOADED_MCP_MODULE_HASH")
    admission_hash = os.environ.get("MEPHC_ADMISSION_MODULE_HASH")
    admission_build = os.environ.get("MEPHC_ADMISSION_BUILD") or (admission_hash[:16] if admission_hash else None)
    admission_current = _json(config.WINDOWS_RUNTIME_WSL / "admission/current.json") or {}
    mismatches: list[str] = []
    if CURRENT_MCP_BUNDLE_HASH and not admission_hash:
        mismatches.append("ADMISSION_ATTESTATION_MISSING")
    if not _fresh(worker): mismatches.append("WORKER_HEARTBEAT_STALE")
    if not _fresh(broker): mismatches.append("BROKER_HEARTBEAT_STALE")
    if not worker or worker.get("worker_build_id") != build: mismatches.append("WORKER_BUILD_MISMATCH")
    if not broker or broker.get("broker_build_id") != build: mismatches.append("BROKER_BUILD_MISMATCH")
    if worker and broker and broker.get("worker_ok") is not True: mismatches.append("BROKER_WORKER_CHECK_FAILED")
    if worker and mcp_hash and worker.get("expected_mcp_bundle_hash") != mcp_hash:
        mismatches.append("MCP_LOADED_MODULE_MISMATCH")
    expected_worker_hash = manifest.get("worker.py")
    if not isinstance(expected_worker_hash, str) or not worker or worker.get("loaded_worker_module_hash") != expected_worker_hash:
        mismatches.append("WORKER_LOADED_MODULE_MISMATCH")
    if admission_hash:
        if admission_current.get("admission_sha256") != admission_hash:
            mismatches.append("ADMISSION_LOADED_MODULE_MISMATCH")
        admission_source = config.CONTROL_ROOT / "tools/mephc-admission/mephc_admission.py"
        try:
            if admission_current.get("admission_sha256") != hashlib.sha256(admission_source.read_bytes()).hexdigest():
                mismatches.append("ADMISSION_SOURCE_MISMATCH")
        except OSError:
            mismatches.append("ADMISSION_SOURCE_UNAVAILABLE")
        if admission_current.get("source_commit") != current.get("source_commit"):
            mismatches.append("ADMISSION_SOURCE_COMMIT_MISMATCH")
    source = _source_head()
    installed_source = current.get("source_commit")
    runtime_source_matches = worker.get("runtime_source_matches") if worker else None
    if runtime_source_matches is False: mismatches.append("SOURCE_RUNTIME_FILES_MISMATCH")
    value = {
        "schema": "mephc-runtime-attestation-v1",
        "admission_build": admission_build,
        "broker_build": broker.get("broker_build_id") if broker else None,
        "worker_build": worker.get("worker_build_id") if worker else None,
        "mcp_server_build": build if mcp_hash and not "MCP_LOADED_MODULE_MISMATCH" in mismatches else None,
        "source_head": source,
        "installed_source_head": installed_source,
        "loaded_admission_module_hash": admission_hash,
        "loaded_mcp_module_hash": mcp_hash,
        "loaded_worker_module_hash": worker.get("loaded_worker_module_hash") if worker else None,
        "state_epoch": config.state_epoch(),
        "health_fresh": _fresh(worker) and _fresh(broker),
        "coherent": not mismatches,
        "mismatches": sorted(set(mismatches)),
    }
    value["safe_next_tool"] = "mephc_doctor" if value["coherent"] else (
        "mephc_runtime_activate" if ({"SOURCE_RUNTIME_FILES_MISMATCH"}
                                     & set(value["mismatches"])) else "mephc_runtime_reload")
    return value
