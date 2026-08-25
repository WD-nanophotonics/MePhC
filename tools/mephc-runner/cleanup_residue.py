#!/usr/bin/env python3
"""Two-phase exact-path cleanup for remotely retained or archived residue."""
from __future__ import annotations
import argparse, hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MEPHC_ROOT = Path("/home/icy/MePhC")
ROOTS = {
    "MEPHC": MEPHC_ROOT,
    "TRILATT": Path("/home/icy/TriLatt"),
    "SQRLATT": Path("/home/icy/SqrLatt"),
    "GMAILCOURIER": Path("/mnt/c/Users/icywo/PycharmProjects/GmailCourier"),
}

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"UNSAFE_CLEANUP_PATH:{relative}")
    path = root.joinpath(*pure.parts)
    resolved_root, resolved = root.resolve(), path.resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise RuntimeError(f"UNSAFE_CLEANUP_PATH:{relative}")
    return path

def verify_archive_commit(commit: str, manifest_path: Path, manifest: dict) -> None:
    subprocess.run(
        ["git", "-C", str(MEPHC_ROOT), "merge-base", "--is-ancestor", commit, "origin/sandbox"],
        check=True, stdout=subprocess.DEVNULL)
    relative = manifest_path.resolve().relative_to(MEPHC_ROOT.resolve()).as_posix()
    payload_relative = str(PurePosixPath(relative).parent / manifest["payload"])
    payload = subprocess.check_output(
        ["git", "-C", str(MEPHC_ROOT), "show", f"{commit}:{payload_relative}"])
    if hashlib.sha256(payload).hexdigest() != manifest["payload_sha256"]:
        raise RuntimeError("REMOTE_ARCHIVE_HASH_MISMATCH")

def build_plan(report: dict, manifest: dict, roots: dict[str, Path]) -> dict:
    archived = {
        (item["project_id"], item["original_path"]): item
        for item in manifest.get("files", [])
    }
    entries = []
    unresolved = []
    for repository in report.get("repositories", []):
        project = repository.get("project_id")
        if project not in roots:
            continue
        for residue in repository.get("residues", []):
            classification = residue.get("classification")
            key = (project, residue.get("path"))
            reason = None
            if classification == "REMOTE_RETAINED_AUDIT":
                reason = "REMOTE_RETAINED_AUDIT"
            elif classification == "AMBIGUOUS_FAIL_CLOSED":
                archived_item = archived.get(key)
                if archived_item and archived_item["sha256"] == residue["sha256"]:
                    reason = "ARCHIVED_IN_AUDIT_ARTIFACT"
                else:
                    unresolved.append({"project_id": project, "path": residue.get("path")})
            if reason:
                source = safe_path(roots[project], residue["path"])
                entries.append({
                    "project_id": project, "path": residue["path"],
                    "bytes": int(residue["bytes"]), "sha256": residue["sha256"],
                    "retention_reason": reason, "source": str(source),
                })
    if unresolved:
        raise RuntimeError("AMBIGUOUS_FAIL_CLOSED:UNARCHIVED_RESIDUE")
    return {
        "schema": "mephc-exact-cleanup-plan-v1",
        "entries": sorted(entries, key=lambda x: (x["project_id"], x["path"])),
        "entry_count": len(entries),
        "bytes": sum(item["bytes"] for item in entries),
    }

def verify_entries(plan: dict, roots: dict[str, Path]) -> None:
    for entry in plan["entries"]:
        path = safe_path(roots[entry["project_id"]], entry["path"])
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"CLEANUP_TARGET_NOT_REGULAR:{entry['project_id']}:{entry['path']}")
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"SOURCE_BYTE_MISMATCH:{entry['project_id']}:{entry['path']}")

def remove_entries(plan: dict, roots: dict[str, Path]) -> dict:
    verify_entries(plan, roots)
    parents = set()
    for entry in plan["entries"]:
        root = roots[entry["project_id"]].resolve()
        path = safe_path(root, entry["path"])
        path.unlink()
        parent = path.parent
        while parent != root and root in parent.parents:
            parents.add(parent)
            parent = parent.parent
    removed_dirs = []
    for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        try:
            parent.rmdir()
            removed_dirs.append(str(parent))
        except OSError:
            pass
    return {
        "schema": "mephc-exact-cleanup-receipt-v1",
        "deleted_count": plan["entry_count"], "deleted_bytes": plan["bytes"],
        "removed_empty_directories": removed_dirs,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

def write_json(prefix: str, value: dict) -> Path:
    root = MEPHC_ROOT / ".relayctl" / "inventory"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = root / f"{prefix}-{stamp}.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path

def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--retention-report", type=Path, required=True)
    plan_cmd.add_argument("--archive-manifest", type=Path, required=True)
    plan_cmd.add_argument("--archive-commit", required=True)
    execute_cmd = sub.add_parser("execute")
    execute_cmd.add_argument("--plan", type=Path, required=True)
    execute_cmd.add_argument("--authorization-sha256", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        report = json.loads(args.retention_report.read_text(encoding="utf-8"))
        manifest = json.loads(args.archive_manifest.read_text(encoding="utf-8"))
        verify_archive_commit(args.archive_commit, args.archive_manifest, manifest)
        plan = build_plan(report, manifest, ROOTS)
        plan.update({"archive_artifact_id": manifest["artifact_id"],
                     "archive_commit": args.archive_commit,
                     "archive_payload_sha256": manifest["payload_sha256"]})
        verify_entries(plan, ROOTS)
        path = write_json("cleanup-plan", plan)
        print(path)
        print(sha256_file(path))
    else:
        if sha256_file(args.plan) != args.authorization_sha256:
            raise RuntimeError("CLEANUP_PLAN_AUTHORIZATION_MISMATCH")
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        receipt = remove_entries(plan, ROOTS)
        receipt.update({"plan": str(args.plan), "plan_sha256": args.authorization_sha256,
                        "archive_commit": plan["archive_commit"]})
        print(write_json("cleanup-receipt", receipt))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
