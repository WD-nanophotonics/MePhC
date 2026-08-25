#!/home/icy/miniconda3/envs/mp/bin/python
"""Generate, but never execute, an exact Windows legacy cleanup plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path("/home/icy/MePhC")
INVENTORY_ROOT = ROOT / ".relayctl" / "inventory"
SAFE_CLASSIFICATIONS = {
    "REMOTE_RETAINED_AUDIT",
    "DISPOSABLE_GENERATED",
}
COPY_ROOTS = {
    "AGENTRELAY": Path("/mnt/c/Users/icywo/PycharmProjects/AgentRelay"),
    "CHATSEQUENCERUNNER": Path("/mnt/c/Users/icywo/PycharmProjects/ChatSequenceRunner"),
    "MEPHC_WINDOWS": Path("/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows"),
    "RETIRED_MEPHC": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC"),
    "RETIRED_SQRLATT": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-SqrLatt"),
    "RETIRED_TRILATT": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-TriLatt"),
    "RETIRED_MEPHC_WINDOWS": Path("/mnt/c/Users/icywo/PycharmProjects/_retired-windows-copies-20260818/MePhC-Windows"),
}


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), *arguments],
        text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deletion_sha256(item: dict[str, Any], root: Path) -> str:
    claimed = item.get("sha256")
    if claimed:
        return claimed
    if item.get("disposable_reason") != "REBUILDABLE_RUNTIME_PACKAGE_CODE":
        raise RuntimeError(f"DELETE_SHA_MISSING:{item['path']}")
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"UNSAFE_DELETE_PATH:{item['path']}")
    source = root.joinpath(relative)
    resolved_root, resolved_source = root.resolve(), source.resolve()
    if resolved_root not in resolved_source.parents or not source.is_file() or source.is_symlink():
        raise RuntimeError(f"UNSAFE_DELETE_PATH:{item['path']}")
    if source.stat().st_size != item["bytes"]:
        raise RuntimeError(f"DELETE_SIZE_MISMATCH:{item['path']}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_index(manifest: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    result = {}
    for item in manifest["files"]:
        key = (item["project_id"], item["original_path"], item["sha256"])
        if key in result:
            continue
        result[key] = item
    return result


def build_plan(
    retention: dict[str, Any],
    manifest: dict[str, Any],
    sandbox_head: str,
) -> dict[str, Any]:
    commit = manifest.get("archive_commit")
    if not commit:
        raise RuntimeError("ARCHIVE_COMMIT_UNBOUND")
    archived = archive_index(manifest)
    delete_files = []
    seen = set()
    for copy in retention["copy_roots"]:
        project_id = copy["project_id"]
        expected_root = COPY_ROOTS.get(project_id)
        if expected_root is None or Path(copy["path"]) != expected_root:
            raise RuntimeError(f"COPY_ROOT_MISMATCH:{project_id}")
        for item in copy["files"]:
            relative = item["path"]
            key = (project_id, relative)
            if key in seen:
                raise RuntimeError(f"DUPLICATE_DELETE_PATH:{project_id}:{relative}")
            seen.add(key)
            classification = item["classification"]
            if classification == "AMBIGUOUS_FAIL_CLOSED":
                archive_key = (project_id, relative, item["sha256"])
                if archive_key not in archived:
                    raise RuntimeError(f"UNRETAINED_AMBIGUOUS_PATH:{project_id}:{relative}")
                retention_basis = {
                    "kind": "ARCHIVE_COMMIT",
                    "artifact_id": manifest["artifact_id"],
                    "archive_commit": commit,
                }
            elif classification in SAFE_CLASSIFICATIONS:
                retention_basis = {
                    "kind": classification,
                    "archive_commit": commit if classification == "REMOTE_RETAINED_AUDIT" else None,
                }
            else:
                raise RuntimeError(f"UNSAFE_CLASSIFICATION:{project_id}:{relative}:{classification}")
            sha256 = deletion_sha256(item, expected_root)
            delete_files.append({
                "project_id": project_id,
                "root": str(expected_root),
                "path": relative,
                "bytes": item["bytes"],
                "sha256": sha256,
                "classification": classification,
                "retention_basis": retention_basis,
            })
    payload_retirement = [{
        "path": f"audit/archive/{manifest['artifact_id']}/{item['path']}",
        "bytes": item["bytes"],
        "sha256": item["sha256"],
        "retained_in_commit": commit,
    } for item in manifest["payloads"]]
    plan = {
        "schema": "mephc-windows-copy-cleanup-plan-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active_project": "MEPHC",
        "archive_artifact_id": manifest["artifact_id"],
        "archive_commit": commit,
        "archive_remote_ref": "origin/sandbox",
        "sandbox_head_at_plan": sandbox_head,
        "copy_root_files": sorted(delete_files, key=lambda item: (item["project_id"], item["path"])),
        "copy_root_file_count": len(delete_files),
        "copy_root_bytes": sum(item["bytes"] for item in delete_files),
        "payload_retirement": sorted(payload_retirement, key=lambda item: item["path"]),
        "payload_retirement_count": len(payload_retirement),
        "payload_retirement_bytes": sum(item["bytes"] for item in payload_retirement),
        "execution_authorized": False,
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-report", type=Path, required=True)
    parser.add_argument("--archive-manifest", type=Path, required=True)
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        raise SystemExit("ROOT_MISMATCH")
    retention = json.loads(args.retention_report.read_text(encoding="utf-8"))
    manifest = json.loads(args.archive_manifest.read_text(encoding="utf-8"))
    commit = manifest.get("archive_commit")
    remote = git("merge-base", "--is-ancestor", commit or "", "origin/sandbox")
    if remote.returncode:
        raise SystemExit("ARCHIVE_COMMIT_NOT_REMOTE_RETAINED")
    head = git("rev-parse", "origin/sandbox")
    if head.returncode:
        raise SystemExit("SANDBOX_HEAD_UNAVAILABLE")
    plan = build_plan(retention, manifest, head.stdout.strip())
    INVENTORY_ROOT.mkdir(parents=True, exist_ok=True)
    output = INVENTORY_ROOT / (
        "windows-copy-cleanup-plan-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".json"
    )
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(output)
    print(plan["plan_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
