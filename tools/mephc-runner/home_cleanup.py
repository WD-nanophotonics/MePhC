#!/usr/bin/env python3
"""Inventory, archive, verify, then remove only the retired WSL MePhC copy.

The command is intentionally phased. ``inventory`` is read-only, ``archive``
creates a recoverable hidden archive, and ``apply`` accepts only an already
verified archive generated for the exact legacy repository. Unknown Home items
are reported and retained.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

LEGACY = Path("/home/icy/MePhC")
EXPECTED_LEGACY_HEAD = "bc3d83937c6b90a224b83b2d80576f9fb0ad0b09"
ARCHIVE_ROOT = Path("/home/icy/.local/share/mephc-archive")
STATE_ROOT = Path("/home/icy/.local/state/mephc-runner/MEPHC")
GIT_CACHE = Path("/home/icy/.cache/mephc-runner/MEPHC.git")
CHECKOUTS = Path("/home/icy/.cache/mephc-runner/checkouts")
CONTROL_ROOT = Path("/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows")
TRILATT = Path("/home/icy/TriLatt")
EMPTY_DIRS = (Path("/home/icy/MePhC-recovery"), Path("/home/icy/MePhC_R3_1_smoke_output"))
LOOSE_NAMES = (
    "MePhC_Affine_Architecture_R3_1_Closure_Submission_Receipt.json",
    "MePhC_Affine_Architecture_R3_1_Validator_Receipt_Submission.json",
    "MePhC_Affine_Architecture_R4_1_Submission_Receipt.json",
    "MePhC_Affine_Architecture_R4_Submission_Receipt.json",
    "MePhC_R3_1_bundle_validator_v2.log",
    "MePhC_R3_1_compileall_external.log",
    "MePhC_R3_1_final_validator.log",
    "MePhC_R3_1_final_validator_v2.log",
    "MePhC_R3_1_negative_fixtures_external.log",
    "MePhC_R3_1_worktree_validator_v2.log",
    "MePhC_R4_1_final_validator.log",
    "MePhC_R4_final_validator.log",
)
LEGACY_EXTRAS = (".relayctl", ".rp2_staging", "origin")
TRILATT_GUARDS = ("band_structure.py", "config.py")
TERMINAL_STATES = {"succeeded", "failed", "rejected", "cancelled"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class CleanupFailure(RuntimeError):
    pass


def command(argv: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(argv, cwd=cwd, text=True, encoding="utf-8", capture_output=True, check=False)
    if result.returncode:
        raise CleanupFailure(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def git(*args: str, cwd: Path = LEGACY) -> str:
    return command(["/usr/bin/git", "-C", str(cwd), *args])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def trilatt_guard() -> dict[str, str | None]:
    return {name: sha256(TRILATT / name) if (TRILATT / name).is_file() else None for name in TRILATT_GUARDS}


def legacy_facts() -> dict:
    if not (LEGACY / ".git").is_dir():
        raise CleanupFailure("LEGACY_REPOSITORY_MISSING")
    head = git("rev-parse", "HEAD")
    if head != EXPECTED_LEGACY_HEAD:
        raise CleanupFailure(f"LEGACY_HEAD_MISMATCH:{head}")
    tracked = git("status", "--porcelain", "--untracked-files=no")
    if tracked:
        raise CleanupFailure("LEGACY_TRACKED_STATE_DIRTY")
    untracked = git("status", "--porcelain", "--untracked-files=all").splitlines()
    unexpected = [line for line in untracked if not any(line[3:] == item or line[3:].startswith(item + "/") for item in LEGACY_EXTRAS)]
    if unexpected:
        raise CleanupFailure("LEGACY_UNKNOWN_UNTRACKED:" + json.dumps(unexpected))
    return {
        "head": head,
        "branch": git("branch", "--show-current"),
        "origin": git("remote", "get-url", "origin"),
        "status_porcelain": untracked,
        "refs": git("show-ref").splitlines(),
    }


def hardcoded_references() -> dict:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL_ROOT), "grep", "-l", "-F", "/home/icy/MePhC"],
        text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if result.returncode not in (0, 1):
        raise CleanupFailure("REFERENCE_SCAN_FAILED:" + result.stderr.strip())
    paths = sorted(result.stdout.splitlines())
    retired_names = {
        "archive_residue.py", "archive_windows_copies.py", "cleanup_residue.py",
        "execute_windows_copy_cleanup.py", "inventory.py", "materializer.py",
        "plan_windows_copy_cleanup.py", "retention.py", "windows_copy_inventory.py",
        "windows_copy_retention.py",
    }
    runtime_compatibility, retired_tools, historical = [], [], []
    for path in paths:
        name = Path(path).name
        if path in {"tools/mephc-runner/home_cleanup.py", "tools/mephc-runner/migrate_state.py",
                    "tools/mephc-runner/worker.py", "tools/mephc-runner/README.md", "AGENTS.md"}:
            runtime_compatibility.append(path)
        elif name in retired_names and path.startswith("tools/mephc-runner/"):
            retired_tools.append(path)
        else:
            historical.append(path)
    digest = hashlib.sha256("\n".join(paths).encode("utf-8")).hexdigest()
    return {"all_paths": paths, "path_count": len(paths), "paths_sha256": digest,
            "runtime_compatibility": runtime_compatibility, "retired_tools": retired_tools,
            "historical_evidence_or_science_fixtures": historical}


def checkout_plan(keep_commit: str | None) -> dict:
    preserve = {keep_commit} if keep_commit else set()
    jobs = STATE_ROOT / "runner" / "jobs"
    nonterminal = []
    if jobs.is_dir():
        for directory in sorted(jobs.glob("MEPHC-JOB-*")):
            job_file, state_file = directory / "job.json", directory / "state.json"
            if not job_file.is_file():
                continue
            job = json.loads(job_file.read_text(encoding="utf-8"))
            state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {}
            if state.get("state") not in TERMINAL_STATES:
                nonterminal.append(directory.name)
                commit = job.get("source_commit")
                if isinstance(commit, str) and SHA40.fullmatch(commit):
                    preserve.add(commit)
    existing = sorted(path.name for path in CHECKOUTS.iterdir() if path.is_dir() and SHA40.fullmatch(path.name)) if CHECKOUTS.is_dir() else []
    return {"preserve": sorted(filter(None, preserve)), "remove": sorted(set(existing) - preserve),
            "nonterminal_jobs": nonterminal}


def inventory(keep_commit: str | None = None) -> dict:
    home = Path("/home/icy")
    known = set(LOOSE_NAMES) | {path.name for path in EMPTY_DIRS} | {LEGACY.name}
    unknown = sorted(path.name for path in home.iterdir()
                     if "mephc" in path.name.lower() and path.name not in known)
    return {
        "schema": "mephc-home-cleanup-inventory-v1",
        "legacy": legacy_facts(),
        "loose_existing": [str(home / name) for name in LOOSE_NAMES if (home / name).is_file()],
        "empty_directories": [{"path": str(path), "empty": path.is_dir() and not any(path.iterdir())} for path in EMPTY_DIRS],
        "unknown_mephc_home_items_retained": unknown,
        "hardcoded_legacy_references": hardcoded_references(),
        "checkout_plan": checkout_plan(keep_commit),
        "trilatt_guard": trilatt_guard(),
    }


def archive(keep_commit: str | None = None) -> Path:
    facts = inventory(keep_commit)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = ARCHIVE_ROOT / stamp
    destination.mkdir(parents=True, exist_ok=False)
    bundle = destination / "MePhC-all-refs.bundle"
    git("bundle", "create", str(bundle), "--all")
    git("bundle", "verify", str(bundle))
    (destination / "refs.txt").write_text("\n".join(facts["legacy"]["refs"]) + "\n", encoding="utf-8")
    (destination / "legacy-facts.json").write_text(json.dumps(facts["legacy"], indent=2) + "\n", encoding="utf-8")
    extras = destination / "legacy-state-and-extras.tar.gz"
    with tarfile.open(extras, "w:gz") as output:
        for name in LEGACY_EXTRAS:
            source = LEGACY / name
            if source.exists():
                output.add(source, arcname=f"MePhC/{name}", recursive=True)
    loose_root = destination / "home-loose-files"
    loose_root.mkdir()
    for value in facts["loose_existing"]:
        shutil.copy2(value, loose_root / Path(value).name)
    with tempfile.TemporaryDirectory(prefix="mephc-bundle-drill-") as temporary:
        restored = Path(temporary) / "repo"
        command(["/usr/bin/git", "clone", "--quiet", str(bundle), str(restored)])
        if git("rev-parse", "HEAD", cwd=restored) != EXPECTED_LEGACY_HEAD:
            raise CleanupFailure("BUNDLE_RESTORE_HEAD_MISMATCH")
    restore = (
        "# Restore the retired WSL MePhC source\n\n"
        "Clone `MePhC-all-refs.bundle` to a new ext4 directory. Extract\n"
        "`legacy-state-and-extras.tar.gz` only if the historical `.relayctl`\n"
        "or other recorded extras are needed. The active durable state remains\n"
        "at `/home/icy/.local/state/mephc-runner/MEPHC` and is not replaced.\n"
    )
    (destination / "RESTORE.md").write_text(restore, encoding="utf-8")
    artifact_hashes = {str(path.relative_to(destination)): sha256(path) for path in sorted(destination.rglob("*")) if path.is_file()}
    manifest = {**facts, "schema": "mephc-home-archive-v1", "archive": str(destination),
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "artifact_sha256": artifact_hashes,
                "bundle_restore_verified": True, "legacy_relayctl_archived": (LEGACY / ".relayctl").exists()}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "VERIFIED").write_text(sha256(destination / "manifest.json") + "\n", encoding="ascii")
    return destination


def verify_archive(destination: Path) -> dict:
    destination = destination.resolve(strict=True)
    if destination.parent != ARCHIVE_ROOT.resolve(strict=True):
        raise CleanupFailure("ARCHIVE_PATH_FORBIDDEN")
    manifest_file, verified_file = destination / "manifest.json", destination / "VERIFIED"
    if not manifest_file.is_file() or not verified_file.is_file() or sha256(manifest_file) != verified_file.read_text(encoding="ascii").strip():
        raise CleanupFailure("ARCHIVE_MANIFEST_NOT_VERIFIED")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    for relative, expected in manifest["artifact_sha256"].items():
        if sha256(destination / relative) != expected:
            raise CleanupFailure("ARCHIVE_ARTIFACT_DRIFT:" + relative)
    git("bundle", "verify", str(destination / "MePhC-all-refs.bundle"))
    if manifest["legacy"]["head"] != EXPECTED_LEGACY_HEAD or not manifest.get("bundle_restore_verified"):
        raise CleanupFailure("ARCHIVE_IDENTITY_INVALID")
    return manifest


def apply(destination: Path, keep_commit: str, prune_checkouts: bool) -> dict:
    if not SHA40.fullmatch(keep_commit):
        raise CleanupFailure("KEEP_COMMIT_INVALID")
    manifest = verify_archive(destination)
    if trilatt_guard() != manifest["trilatt_guard"]:
        raise CleanupFailure("TRILATT_GUARD_CHANGED")
    if legacy_facts()["head"] != manifest["legacy"]["head"]:
        raise CleanupFailure("LEGACY_CHANGED_AFTER_ARCHIVE")
    removed = []
    shutil.rmtree(LEGACY)
    removed.append(str(LEGACY))
    home = Path("/home/icy")
    for name in LOOSE_NAMES:
        target = home / name
        if target.is_file():
            target.unlink()
            removed.append(str(target))
    for target in EMPTY_DIRS:
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()
            removed.append(str(target))
    pruned = []
    if prune_checkouts:
        plan = checkout_plan(keep_commit)
        for commit in plan["remove"]:
            target = CHECKOUTS / commit
            git("worktree", "remove", "--force", str(target), cwd=GIT_CACHE)
            pruned.append(str(target))
    if trilatt_guard() != manifest["trilatt_guard"]:
        raise CleanupFailure("TRILATT_GUARD_CHANGED_AFTER_APPLY")
    result = {"schema": "mephc-home-cleanup-result-v1", "archive": str(destination),
              "removed": removed, "pruned_checkouts": pruned, "trilatt_guard": trilatt_guard()}
    (destination / "cleanup-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="mephc-home-cleanup")
    parser.add_argument("mode", choices=("inventory", "archive", "verify", "apply"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--keep-commit")
    parser.add_argument("--prune-checkouts", action="store_true")
    args = parser.parse_args()
    if args.mode == "inventory":
        value = inventory(args.keep_commit)
    elif args.mode == "archive":
        value = {"archive": str(archive(args.keep_commit))}
    elif args.mode == "verify":
        if not args.archive:
            parser.error("verify requires --archive")
        value = verify_archive(args.archive)
    else:
        if not args.archive or not args.keep_commit:
            parser.error("apply requires --archive and --keep-commit")
        value = apply(args.archive, args.keep_commit, args.prune_checkouts)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
