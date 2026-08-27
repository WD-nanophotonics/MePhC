"""Audit and atomically copy legacy .relayctl into the durable state root."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import runtime_config as config

LEGACY = Path("/home/icy/MePhC/.relayctl")


def manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
        and path.relative_to(root).as_posix() not in {"runner/state-epoch", "runner/migration-receipt.json"}
    }


def unresolved_jobs(root: Path) -> list[str]:
    result = []
    for directory in sorted((root / "runner" / "jobs").glob("MEPHC-JOB-*")):
        state_path = directory / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8")).get("state")
        except (OSError, json.JSONDecodeError):
            state = "orphaned"
        if state in {"ready", "running", "recovery_requested"}:
            result.append(directory.name)
    return result


def migrate(apply: bool) -> dict:
    before = manifest(LEGACY)
    active = unresolved_jobs(LEGACY)
    result = {"schema": "mephc-state-migration-v1", "legacy": str(LEGACY),
              "state_root": str(config.STATE_ROOT), "file_count": len(before),
              "active_jobs": active, "apply": apply}
    if not apply:
        return result
    if active:
        raise RuntimeError("ACTIVE_JOBS_PRESENT")
    if config.STATE_ROOT.exists():
        epoch_file = config.STATE_ROOT / "runner" / "state-epoch"
        receipt_file = config.STATE_ROOT / "runner" / "migration-receipt.json"
        if not epoch_file.is_file() or not receipt_file.is_file():
            raise RuntimeError("STATE_ROOT_EXISTS_WITHOUT_MIGRATION_RECEIPT")
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        if receipt.get("legacy") != str(LEGACY) or receipt.get("file_count") != len(before):
            raise RuntimeError("STATE_MIGRATION_RECEIPT_MISMATCH")
        result["reused"] = True
        result["state_epoch"] = epoch_file.read_text(encoding="ascii").strip()
        return result
    staging = config.STATE_ROOT.with_name(config.STATE_ROOT.name + ".staging-" + uuid.uuid4().hex)
    staging.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(LEGACY, staging, symlinks=False)
    if manifest(staging) != before:
        shutil.rmtree(staging)
        raise RuntimeError("STATE_COPY_HASH_MISMATCH")
    (staging / "runner").mkdir(parents=True, exist_ok=True)
    epoch = uuid.uuid4().hex
    (staging / "runner" / "state-epoch").write_text(epoch + "\n", encoding="ascii")
    (staging / "runner" / "migration-receipt.json").write_text(
        json.dumps({**result, "state_epoch": epoch}, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staging, config.STATE_ROOT)
    result.update({"migrated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "state_epoch": epoch})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(json.dumps(migrate(parser.parse_args().apply), sort_keys=True))
