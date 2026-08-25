#!/home/icy/miniconda3/envs/mp/bin/python
"""Bind residue bytes to blobs reachable from approved remote refs."""

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
REPOSITORIES = {
    "MEPHC": Path("/home/icy/MePhC"),
    "TRILATT": Path("/home/icy/TriLatt"),
    "SQRLATT": Path("/home/icy/SqrLatt"),
    "GMAILCOURIER": Path("/mnt/c/Users/icywo/PycharmProjects/GmailCourier"),
}
CANDIDATE_REMOTES = {
    "MEPHC": ("MEPHC",),
    "TRILATT": ("TRILATT", "MEPHC"),
    "SQRLATT": ("SQRLATT", "MEPHC"),
    "GMAILCOURIER": ("GMAILCOURIER", "MEPHC", "TRILATT", "SQRLATT"),
}


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
    object_format = git(repo, "rev-parse", "--show-object-format")
    if object_format.returncode or object_format.stdout.strip() != "sha1":
        raise SystemExit(f"unsupported Git object format: {repo}")
    completed = git(repo, "rev-list", "--objects", "--remotes=origin")
    if completed.returncode:
        raise SystemExit(f"cannot enumerate remote objects: {repo}: {completed.stderr.strip()}")
    return {line.split(" ", 1)[0] for line in completed.stdout.splitlines() if line}


def blob_oid(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data, usedforsecurity=False).hexdigest()


def latest_inventory() -> Path:
    candidates = list(INVENTORY_ROOT.glob("inventory-*.json"))
    if not candidates:
        raise SystemExit("no residue inventory exists")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def analyze() -> Path:
    if Path.cwd().resolve() != ROOT:
        raise SystemExit("ROOT_MISMATCH")
    source = latest_inventory()
    inventory = json.loads(source.read_text(encoding="utf-8"))
    reachable = {project_id: reachable_objects(repo) for project_id, repo in REPOSITORIES.items()}
    summary: dict[str, dict[str, int]] = {}
    for repository in inventory["repositories"]:
        project_id = repository["project_id"]
        repo_root = Path(repository["path"])
        counts: dict[str, int] = {}
        for residue in repository["residues"]:
            if residue.get("classification") != "AMBIGUOUS_FAIL_CLOSED" or residue.get("kind") != "file":
                classification = residue.get("classification", "AMBIGUOUS_FAIL_CLOSED")
                counts[classification] = counts.get(classification, 0) + 1
                continue
            path = repo_root / residue["path"]
            try:
                oid = blob_oid(path)
            except OSError as exc:
                residue["retention_error"] = type(exc).__name__
                counts["AMBIGUOUS_FAIL_CLOSED"] = counts.get("AMBIGUOUS_FAIL_CLOSED", 0) + 1
                continue
            retained_in = [candidate for candidate in CANDIDATE_REMOTES[project_id] if oid in reachable[candidate]]
            residue["git_blob_oid"] = oid
            residue["retained_in_remote_projects"] = retained_in
            if retained_in:
                residue["classification"] = "REMOTE_RETAINED_AUDIT"
            counts[residue["classification"]] = counts.get(residue["classification"], 0) + 1
        summary[project_id] = counts
    record = {
        "schema": "mephc-residue-retention-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_inventory": str(source),
        "remote_refs_refreshed_required": True,
        "summary": summary,
        "repositories": inventory["repositories"],
    }
    output = INVENTORY_ROOT / f"retention-{time.strftime('%Y%m%d-%H%M%S')}.json"
    atomic_json(output, record)
    return output


if __name__ == "__main__":
    print(analyze())
