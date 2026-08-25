#!/home/icy/miniconda3/envs/mp/bin/python
"""Read-only, fixed-scope residue inventory for the MePhC workflow."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any


ROOT = Path("/home/icy/MePhC")
OUTPUT_ROOT = ROOT / ".relayctl" / "inventory"
REPOSITORIES = {
    "MEPHC": Path("/home/icy/MePhC"),
    "TRILATT": Path("/home/icy/TriLatt"),
    "SQRLATT": Path("/home/icy/SqrLatt"),
    "GMAILCOURIER": Path("/mnt/c/Users/icywo/PycharmProjects/GmailCourier"),
}
SECRET_NAME = re.compile(r"(^|[._-])(token|secret|credential|password|passwd|cookie|oauth|key)([._-]|$)", re.I)
DISPOSABLE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", "build", "dist"}
DISPOSABLE_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log"}


def run(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def classify(relative_path: str, tracked: bool, project_id: str | None = None) -> str:
    if tracked:
        return "CANONICAL_SOURCE"
    path = Path(relative_path)
    if project_id == "MEPHC" and path.parts and path.parts[0] == ".relayctl":
        return "INSTALLED_REBUILDABLE_RUNTIME"
    if any(SECRET_NAME.search(part) for part in path.parts):
        return "SECRET_OR_CREDENTIAL"
    if any(part in DISPOSABLE_PARTS for part in path.parts) or path.suffix.lower() in DISPOSABLE_SUFFIXES:
        return "DISPOSABLE_GENERATED"
    return "AMBIGUOUS_FAIL_CLOSED"


def file_record(project_id: str, repo: Path, status: str, relative_path: str) -> dict[str, Any]:
    tracked = status not in {"??", "!!"}
    path = repo / relative_path
    record: dict[str, Any] = {
        "path": relative_path,
        "status": status,
        "classification": classify(relative_path, tracked, project_id),
    }
    try:
        stat = path.lstat()
        record["bytes"] = stat.st_size
        record["kind"] = "symlink" if path.is_symlink() else "file" if path.is_file() else "directory"
        if path.is_file() and record["classification"] != "SECRET_OR_CREDENTIAL":
            record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        record["kind"] = "unreadable"
        record["error"] = type(exc).__name__
    return record


def status_records(project_id: str, repo: Path) -> list[dict[str, Any]]:
    completed = run(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if completed.returncode:
        return [{"classification": "AMBIGUOUS_FAIL_CLOSED", "error": completed.stderr.strip(), "path": "", "status": "GIT_ERROR"}]
    records: list[dict[str, Any]] = []
    fields = completed.stdout.split("\0")
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        status = field[:2]
        relative_path = field[3:]
        if status[0] in {"R", "C"} and index < len(fields):
            index += 1
        records.append(file_record(project_id, repo, status, relative_path))
    known = {record["path"] for record in records}
    ignored = run(repo, "ls-files", "-z", "--others", "-i", "--exclude-standard")
    if ignored.returncode:
        records.append({"classification": "AMBIGUOUS_FAIL_CLOSED",
                        "error": ignored.stderr.strip(), "path": "", "status": "GIT_IGNORED_ERROR"})
    else:
        for relative_path in ignored.stdout.split("\0"):
            if relative_path and relative_path not in known:
                records.append(file_record(project_id, repo, "!!", relative_path))
    return records


def repository_record(project_id: str, repo: Path) -> dict[str, Any]:
    head = run(repo, "rev-parse", "HEAD")
    branch = run(repo, "branch", "--show-current")
    remotes = run(repo, "remote", "-v")
    worktrees = run(repo, "worktree", "list", "--porcelain")
    residues = status_records(project_id, repo)
    counts: dict[str, int] = {}
    for residue in residues:
        key = residue["classification"]
        counts[key] = counts.get(key, 0) + 1
    return {
        "project_id": project_id,
        "path": str(repo),
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "remotes": [line for line in remotes.stdout.splitlines() if line],
        "worktree_porcelain": worktrees.stdout.splitlines(),
        "residue_counts": counts,
        "residues": residues,
    }


def create_inventory() -> Path:
    if Path.cwd().resolve() != ROOT:
        raise SystemExit("ROOT_MISMATCH")
    record = {
        "schema": "mephc-residue-inventory-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "active_project": "MEPHC",
        "classification_policy": [
            "CANONICAL_SOURCE", "INSTALLED_REBUILDABLE_RUNTIME", "REMOTE_RETAINED_AUDIT",
            "DISPOSABLE_GENERATED", "AMBIGUOUS_FAIL_CLOSED", "SECRET_OR_CREDENTIAL",
        ],
        "repositories": [repository_record(project_id, repo) for project_id, repo in REPOSITORIES.items()],
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / f"inventory-{time.strftime('%Y%m%d-%H%M%S')}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return output


if __name__ == "__main__":
    print(create_inventory())
