#!/home/icy/miniconda3/envs/mp/bin/python
"""Read-only inventory for fixed Windows legacy-copy roots.

This scanner deliberately has no deletion capability. It classifies bytes only
after comparing their Git blob identity with objects reachable from approved
remote-tracking refs in the canonical local repositories.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable


ROOT = Path("/home/icy/MePhC")
OUTPUT_ROOT = ROOT / ".relayctl" / "inventory"
WINDOWS_ROOT = Path("/mnt/c/Users/icywo/PycharmProjects")
COPY_ROOTS = {
    "AGENTRELAY": WINDOWS_ROOT / "AgentRelay",
    "CHATSEQUENCERUNNER": WINDOWS_ROOT / "ChatSequenceRunner",
    "MEPHC_WINDOWS": WINDOWS_ROOT / "MePhC-Windows",
    "RETIRED_MEPHC": WINDOWS_ROOT / "_retired-windows-copies-20260818" / "MePhC",
    "RETIRED_SQRLATT": WINDOWS_ROOT / "_retired-windows-copies-20260818" / "MePhC-SqrLatt",
    "RETIRED_TRILATT": WINDOWS_ROOT / "_retired-windows-copies-20260818" / "MePhC-TriLatt",
    "RETIRED_MEPHC_WINDOWS": WINDOWS_ROOT / "_retired-windows-copies-20260818" / "MePhC-Windows",
}
REMOTE_SOURCES = {
    "MEPHC": Path("/home/icy/MePhC"),
    "TRILATT": Path("/home/icy/TriLatt"),
    "SQRLATT": Path("/home/icy/SqrLatt"),
    "GMAILCOURIER": WINDOWS_ROOT / "GmailCourier",
    "AGENTRELAY": WINDOWS_ROOT / "AgentRelay",
}
SECRET_NAME = re.compile(
    r"(^|[._-])(token|secret|credential|password|passwd|cookie|oauth|private[-_]?key)([._-]|$)",
    re.I,
)
DISPOSABLE_PARTS = {
    ".git", ".idea", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".run", ".tox", ".venv", "__pycache__", "build", "dist", "node_modules", "venv",
}
DISPOSABLE_SUFFIXES = {".log", ".pyc", ".pyo", ".tmp"}


def git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def reachable_objects(repo: Path) -> set[str]:
    result = git(repo, "rev-list", "--objects", "--remotes=origin")
    if result.returncode:
        raise SystemExit(f"REMOTE_OBJECT_ENUMERATION_FAILED:{repo}:{result.stderr.strip()}")
    return {line.split(" ", 1)[0] for line in result.stdout.splitlines() if line}


def sha256_and_blob_oid(path: Path) -> tuple[str, str]:
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1(usedforsecurity=False)
    size = path.stat().st_size
    sha1.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha256.update(chunk)
            sha1.update(chunk)
    return sha256.hexdigest(), sha1.hexdigest()


def base_classification(relative: str) -> str | None:
    path = Path(relative)
    parts = {part.lower() for part in path.parts}
    if "site-packages" in parts and bool(parts & {".venv", "venv"}) and (
        path.suffix.lower() in {".py", ".pyc", ".pyo", ".pyi"}
    ):
        return "DISPOSABLE_GENERATED"
    if any(part.lower().endswith(".egg-info") for part in path.parts):
        return "DISPOSABLE_GENERATED"
    if any(SECRET_NAME.search(part) for part in path.parts):
        return "SECRET_OR_CREDENTIAL"
    if any(part.lower() in DISPOSABLE_PARTS for part in path.parts):
        return "DISPOSABLE_GENERATED"
    if path.suffix.lower() in DISPOSABLE_SUFFIXES:
        return "DISPOSABLE_GENERATED"
    return None


def iter_files(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root, followlinks=False):
        names.sort()
        files.sort()
        base = Path(directory)
        for name in files:
            yield base / name


def repository_metadata(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        return {"is_git_repository": False}
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "branch", "--show-current")
    remotes = git(root, "remote", "-v")
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    return {
        "is_git_repository": True,
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "remotes": [line for line in remotes.stdout.splitlines() if line],
        "status": status.stdout.splitlines() if status.returncode == 0 else None,
        "status_error": status.stderr.strip() if status.returncode else None,
    }


def scan_root(project_id: str, root: Path, reachable: dict[str, set[str]]) -> dict[str, Any]:
    metadata = repository_metadata(root)
    records: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    bytes_by_classification: dict[str, int] = {}
    if not root.is_dir():
        return {
            "project_id": project_id,
            "path": str(root),
            "error": "ROOT_MISSING",
            "repository": metadata,
            "counts": {"AMBIGUOUS_FAIL_CLOSED": 1},
            "bytes_by_classification": {},
            "files": [],
        }
    for path in iter_files(root):
        relative = path.relative_to(root).as_posix()
        record: dict[str, Any] = {"path": relative}
        try:
            stat = path.lstat()
            record["bytes"] = stat.st_size
            if path.is_symlink():
                record["kind"] = "symlink"
                record["classification"] = "AMBIGUOUS_FAIL_CLOSED"
            else:
                record["kind"] = "file"
                classification = base_classification(relative)
                if classification == "SECRET_OR_CREDENTIAL":
                    record["classification"] = classification
                else:
                    sha256, oid = sha256_and_blob_oid(path)
                    retained_in = sorted(name for name, objects in reachable.items() if oid in objects)
                    record.update({
                        "sha256": sha256,
                        "git_blob_oid": oid,
                        "retained_in_remote_projects": retained_in,
                    })
                    record["classification"] = (
                        "REMOTE_RETAINED_AUDIT"
                        if retained_in
                        else classification or "AMBIGUOUS_FAIL_CLOSED"
                    )
        except OSError as exc:
            record.update({
                "kind": "unreadable",
                "classification": "AMBIGUOUS_FAIL_CLOSED",
                "error": type(exc).__name__,
            })
        classification = record["classification"]
        counts[classification] = counts.get(classification, 0) + 1
        bytes_by_classification[classification] = (
            bytes_by_classification.get(classification, 0) + record.get("bytes", 0)
        )
        records.append(record)
    return {
        "project_id": project_id,
        "path": str(root),
        "repository": metadata,
        "counts": counts,
        "bytes_by_classification": bytes_by_classification,
        "files": records,
    }


def create_inventory() -> Path:
    if Path.cwd().resolve() != ROOT:
        raise SystemExit("ROOT_MISMATCH")
    reachable = {
        project_id: reachable_objects(repo)
        for project_id, repo in REMOTE_SOURCES.items()
    }
    copies = [
        scan_root(project_id, path, reachable)
        for project_id, path in COPY_ROOTS.items()
    ]
    record = {
        "schema": "mephc-windows-copy-inventory-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "active_project": "MEPHC",
        "copy_roots": copies,
        "remote_source_paths": {
            key: str(value) for key, value in REMOTE_SOURCES.items()
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / (
        f"windows-copy-inventory-{time.strftime('%Y%m%d-%H%M%S')}.json"
    )
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return output


if __name__ == "__main__":
    print(create_inventory())
