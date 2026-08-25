#!/home/icy/miniconda3/envs/mp/bin/python
"""Second-stage retention analysis for the fixed Windows copy inventory."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

ROOT = Path("/home/icy/MePhC")
INVENTORY_ROOT = ROOT / ".relayctl" / "inventory"
ARCHIVE_ROOT = ROOT / "audit" / "archive"


def git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *arguments],
        text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def archive_member(item: dict[str, Any]) -> str:
    legacy = item.get("archive_member")
    if isinstance(legacy, str) and legacy:
        return legacy
    storage = item.get("storage")
    if not isinstance(storage, dict):
        raise RuntimeError("ARCHIVE_MEMBER_BINDING_MISSING")
    if (
        storage.get("format") == "tar-gzip"
        and isinstance(storage.get("member"), str) and storage["member"]
    ):
        return storage["member"]
    if storage.get("format") == "split-gzip":
        parts = storage.get("parts")
        if isinstance(parts, list) and parts and all(
            isinstance(part, dict)
            and isinstance(part.get("path"), str) and part["path"]
            for part in parts
        ):
            return "parts:" + ",".join(part["path"] for part in parts)
    raise RuntimeError("ARCHIVE_MEMBER_BINDING_MISSING")


def latest_inventory() -> Path:
    candidates = list(INVENTORY_ROOT.glob("windows-copy-inventory-*.json"))
    if not candidates:
        raise SystemExit("WINDOWS_COPY_INVENTORY_MISSING")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def archive_sha_index() -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = {}
    for path in sorted(ARCHIVE_ROOT.glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        commit = manifest.get("archive_commit")
        remote_ref = manifest.get("archive_remote_ref")
        if not commit or remote_ref != "origin/sandbox":
            raise SystemExit(f"ARCHIVE_AUTHORITY_INVALID:{path}")
        retained = git(ROOT, "merge-base", "--is-ancestor", commit, remote_ref)
        if retained.returncode:
            raise SystemExit(f"ARCHIVE_COMMIT_NOT_REMOTE_RETAINED:{path}:{commit}")
        for item in manifest.get("files", []):
            sha256 = item.get("sha256")
            if not sha256:
                raise SystemExit(f"ARCHIVE_ENTRY_SHA_MISSING:{path}")
            index.setdefault(sha256, []).append({
                "artifact_id": manifest["artifact_id"],
                "archive_commit": commit,
                "archive_member": archive_member(item),
            })
    return index


def tracked_paths(repo: Path) -> set[str]:
    result = git(repo, "ls-files", "-z")
    if result.returncode:
        raise SystemExit(f"TRACKED_PATH_ENUMERATION_FAILED:{repo}")
    return {path for path in result.stdout.split("\0") if path}


def meaningful_diff(repo: Path) -> set[str]:
    result = git(
        repo, "diff", "HEAD", "--ignore-space-at-eol", "--name-only", "-z",
    )
    if result.returncode:
        raise SystemExit(f"NON_EOL_DIFF_FAILED:{repo}:{result.stderr.strip()}")
    return {path for path in result.stdout.split("\0") if path}


def head_remote_reachable(repo: Path) -> bool:
    head = git(repo, "rev-parse", "HEAD")
    if head.returncode:
        return False
    refs = git(
        repo, "for-each-ref", f"--contains={head.stdout.strip()}",
        "--format=%(refname)", "refs/remotes/origin",
    )
    return refs.returncode == 0 and any(
        line.startswith("refs/remotes/origin/") for line in refs.stdout.splitlines()
    )


def is_runtime_package_code(relative: str) -> bool:
    path = Path(relative)
    parts = {part.lower() for part in path.parts}
    return (
        "site-packages" in parts
        and bool(parts & {".venv", "venv"})
        and path.suffix.lower() in {".py", ".pyc", ".pyo", ".pyi"}
    )


def is_explicit_generated(relative: str) -> bool:
    path = Path(relative)
    return ".run" in path.parts or any(part.lower().endswith(".egg-info") for part in path.parts)


def reclassify(
    record: dict[str, Any],
    archives: dict[str, list[dict[str, str]]],
    tracked: set[str],
    meaningful: set[str],
    remote_head: bool,
) -> dict[str, Any]:
    updated = dict(record)
    if (
        updated.get("classification") == "SECRET_OR_CREDENTIAL"
        and is_runtime_package_code(updated["path"])
    ):
        updated["classification"] = "DISPOSABLE_GENERATED"
        updated["disposable_reason"] = "REBUILDABLE_RUNTIME_PACKAGE_CODE"
        return updated
    if updated.get("classification") != "AMBIGUOUS_FAIL_CLOSED":
        return updated
    if is_explicit_generated(updated["path"]):
        updated["classification"] = "DISPOSABLE_GENERATED"
        updated["disposable_reason"] = "EXPLICIT_REBUILDABLE_PROJECT_METADATA"
        return updated
    bindings = archives.get(updated.get("sha256", ""))
    if bindings:
        updated["classification"] = "REMOTE_RETAINED_AUDIT"
        updated["retained_in_archive_artifacts"] = bindings
        return updated
    if remote_head and updated["path"] in tracked and updated["path"] not in meaningful:
        updated["classification"] = "DISPOSABLE_GENERATED"
        updated["disposable_reason"] = "REMOTE_HEAD_TRACKED_EOL_MATERIALIZATION"
    return updated


def analyze() -> Path:
    if Path.cwd().resolve() != ROOT:
        raise SystemExit("ROOT_MISMATCH")
    source = latest_inventory()
    source_bytes = source.read_bytes()
    inventory = json.loads(source_bytes)
    archives = archive_sha_index()
    summary: dict[str, dict[str, int]] = {}
    for copy in inventory["copy_roots"]:
        repo = Path(copy["path"])
        repository = copy["repository"]
        remote_head = (
            bool(repository.get("is_git_repository"))
            and bool(repository.get("head"))
            and head_remote_reachable(repo)
        )
        tracked = tracked_paths(repo) if remote_head else set()
        meaningful = meaningful_diff(repo) if remote_head else set()
        files = [
            reclassify(item, archives, tracked, meaningful, remote_head)
            for item in copy["files"]
        ]
        counts: dict[str, int] = {}
        bytes_by_classification: dict[str, int] = {}
        for item in files:
            classification = item["classification"]
            counts[classification] = counts.get(classification, 0) + 1
            bytes_by_classification[classification] = (
                bytes_by_classification.get(classification, 0) + item.get("bytes", 0)
            )
        copy["files"] = files
        copy["counts"] = counts
        copy["bytes_by_classification"] = bytes_by_classification
        copy["remote_head_reachable"] = remote_head
        copy["meaningful_diff_paths"] = sorted(meaningful)
        summary[copy["project_id"]] = counts
    result = {
        "schema": "mephc-windows-copy-retention-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_inventory": str(source),
        "source_inventory_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "summary": summary,
        "copy_roots": inventory["copy_roots"],
    }
    output = INVENTORY_ROOT / (
        f"windows-copy-retention-{time.strftime('%Y%m%d-%H%M%S')}.json"
    )
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return output


if __name__ == "__main__":
    print(analyze())
