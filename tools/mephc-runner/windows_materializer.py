"""Restricted Windows-side source materializer for v2 change jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath

CONTROL_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
EXPECTED_ORIGIN_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_TOP = {"audit", "tests", "tools", "mephc", "scripts", "docs", ".codex", ".agents"}
ADMISSION_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")


class MaterializeError(RuntimeError):
    pass


def git(*args: str, timeout: int = 90) -> str:
    environment = dict(os.environ)
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true",
                        "GIT_MERGE_AUTOEDIT": "no"})
    command = ["git", "-c", f"safe.directory={CONTROL_ROOT.as_posix()}", "-C", str(CONTROL_ROOT)]
    if args[:1] == ("commit",):
        command += ["-c", "commit.gpgSign=false"]
    try:
        result = subprocess.run([*command, *args], text=True, encoding="utf-8",
                                capture_output=True, check=False, timeout=timeout,
                                env=environment)
    except subprocess.TimeoutExpired as exc:
        raise MaterializeError(f"GIT_TIMEOUT:{args[0] if args else 'unknown'}") from exc
    if result.returncode:
        raise MaterializeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def progress(job_dir: Path, phase: str, **fields: object) -> None:
    atomic_json(job_dir / "materializer-progress.json", {
        "schema": "mephc-materializer-progress-v1", "phase": phase,
        "phase_heartbeat_unix": time.time(), **fields,
    })


def is_ancestor(older: str, newer: str) -> bool:
    result = subprocess.run(["git", "-c", f"safe.directory={CONTROL_ROOT.as_posix()}",
                             "-C", str(CONTROL_ROOT), "merge-base", "--is-ancestor", older, newer],
                            capture_output=True, check=False, timeout=30)
    return result.returncode == 0


def declared_hashes_match(job: dict, key: str) -> bool:
    for item in job.get("change", {}).get("files", []):
        target = target_for(item.get("path"))
        digest = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else "MISSING"
        if digest != item.get(key):
            return False
    return bool(job.get("change", {}).get("files"))


def target_for(value: str) -> Path:
    pure = PurePosixPath(value)
    if (not value or pure.is_absolute() or ".." in pure.parts or "\\" in value
            or pure.parts[0] in {".git", ".relayctl"}
            or (value != "AGENTS.md" and pure.parts[0] not in ALLOWED_TOP)):
        raise MaterializeError(f"CHANGE_PATH_INVALID:{value}")
    target = CONTROL_ROOT.joinpath(*pure.parts)
    if target.is_symlink():
        raise MaterializeError(f"CHANGE_SYMLINK_FORBIDDEN:{value}")
    return target


def materialize(job_dir: Path) -> dict:
    progress(job_dir, "validating")
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    schema = job.get("schema")
    admission_binding_valid = (schema == "mephc-runner-job-v2"
                               or (schema == "mephc-runner-job-v4"
                                   and isinstance(job.get("admission_request_id"), str)
                                   and ADMISSION_REQUEST_ID.fullmatch(job["admission_request_id"])))
    if (not admission_binding_valid or job.get("operation") != "change"
            or job.get("expected_control_root", "").casefold() != str(CONTROL_ROOT).casefold()):
        raise MaterializeError("CHANGE_JOB_SCHEMA_REQUIRED")
    base = job.get("source_commit")
    if not isinstance(base, str) or not SHA40.fullmatch(base) or git("rev-parse", "HEAD") != base:
        raise MaterializeError("HEAD_MOVED")
    if git("rev-parse", "origin/main") != job.get("expected_origin_main") or job.get("expected_origin_main") != EXPECTED_ORIGIN_MAIN:
        raise MaterializeError("MAIN_MOVED")
    branch = git("branch", "--show-current")
    if branch in {"", "main"}:
        raise MaterializeError("CONTROL_BRANCH_FORBIDDEN")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise MaterializeError("CONTROL_ROOT_DIRTY")
    files = job.get("change", {}).get("files")
    if not isinstance(files, list) or not files:
        raise MaterializeError("CHANGE_FILES_INVALID")
    backups: list[tuple[Path, bytes | None]] = []
    backup_root = job_dir / "change-backup-windows"
    try:
        records: list[dict[str, object]] = []
        for item in files:
            target = target_for(item.get("path"))
            content = item.get("content_utf8")
            if not isinstance(content, str):
                raise MaterializeError("CHANGE_CONTENT_INVALID")
            before = target.read_bytes() if target.is_file() else None
            expected = item.get("expected_preimage_sha256")
            actual = hashlib.sha256(before).hexdigest() if before is not None else "MISSING"
            if actual != expected:
                raise MaterializeError(f"CHANGE_PREIMAGE_MISMATCH:{item.get('path')}")
            encoded = content.encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != item.get("expected_postimage_sha256"):
                raise MaterializeError(f"CHANGE_POSTIMAGE_MISMATCH:{item.get('path')}")
            if before is not None and hashlib.sha256(before).hexdigest() == hashlib.sha256(encoded).hexdigest():
                raise MaterializeError(f"CHANGE_FILE_NOOP:{item.get('path')}")
            backups.append((target, before))
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_name = f"{len(backups)-1:04d}.bin"
            if before is not None:
                atomic_bytes(backup_root / backup_name, before)
            records.append({"path": item["path"], "existed": before is not None,
                            "backup": backup_name if before is not None else None})
        atomic_json(backup_root / "manifest.json", {"files": records})
        atomic_json(job_dir / "change-journal.json", {"phase": "backed_up", "base_head": base})
        progress(job_dir, "writing")
        for item in files:
            target = target_for(item.get("path"))
            encoded = item["content_utf8"].encode("utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temporary.write_bytes(encoded)
            os.replace(temporary, target)
        atomic_json(job_dir / "change-journal.json", {"phase": "written", "base_head": base})
        progress(job_dir, "committing")
        git("add", "--", *[item["path"] for item in files])
        git("commit", "-m", job["change"]["commit_message"])
        final = git("rev-parse", "HEAD")
        atomic_json(job_dir / "change-journal.json", {"phase": "committed", "base_head": base,
                                                       "final_commit": final})
        progress(job_dir, "attesting", final_commit=final)
        attestation = {"schema": "mephc-windows-materialization-v1", "job_id": job["job_id"],
                       "base_head": base, "final_commit": final, "control_root": str(CONTROL_ROOT),
                       "prelive_required": True,
                       "files": {item["path"]: item["expected_postimage_sha256"] for item in files}}
        atomic_json(job_dir / "change-attestation.json", attestation)
        progress(job_dir, "terminal", final_commit=final)
        return attestation
    except Exception:
        if git("rev-parse", "HEAD") == base:
            for target, before in backups:
                if before is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(before)
            subprocess.run(["git", "-c", f"safe.directory={CONTROL_ROOT.as_posix()}",
                            "-C", str(CONTROL_ROOT), "reset"], capture_output=True, check=False, timeout=30)
        raise


def restore_from_journal(job_dir: Path) -> dict:
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    base = job.get("source_commit")
    journal_path = job_dir / "change-journal.json"
    attestation_path = job_dir / "change-attestation.json"
    actual = git("rev-parse", "HEAD")
    if attestation_path.is_file():
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        final = attestation.get("final_commit")
        if (isinstance(final, str) and is_ancestor(final, actual)
                and declared_hashes_match(job, "expected_postimage_sha256")
                and not git("status", "--porcelain", "--untracked-files=all")):
            return {"state": "succeeded", "recovery": "committed_verified", **attestation}
        return {"state": "recovery_required", "error_code": "CHANGE_RECOVERY_UNRESOLVED",
                "detail": f"attested={final} actual={actual}"}
    if not journal_path.is_file():
        preimages_match = declared_hashes_match(job, "expected_preimage_sha256")
        if preimages_match and not git("status", "--porcelain", "--untracked-files=all"):
            return {"state": "failed", "error_code": "CHANGE_NOT_STARTED_ABORTED",
                    "recovery": "no_effect_verified", "base_head": base, "verified_head": actual}
        return {"state": "recovery_required", "error_code": "CHANGE_RECOVERY_UNRESOLVED",
                "detail": "journal missing and source is not the clean base"}
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    final = journal.get("final_commit")
    if (journal.get("phase") == "committed" and isinstance(final, str)
            and is_ancestor(final, actual)
            and declared_hashes_match(job, "expected_postimage_sha256")
            and not git("status", "--porcelain", "--untracked-files=all")):
        return {"state": "succeeded", "recovery": "committed_journal_verified",
                "base_head": base, "final_commit": final, "verified_head": actual}
    if actual != base:
        return {"state": "recovery_required", "error_code": "CHANGE_RECOVERY_UNRESOLVED",
                "detail": f"expected base={base} actual={actual}"}
    manifest_path = job_dir / "change-backup-windows" / "manifest.json"
    if not manifest_path.is_file():
        return {"state": "recovery_required", "error_code": "CHANGE_BACKUP_MISSING"}
    for item in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]:
        target = target_for(item["path"])
        if item["existed"]:
            atomic_bytes(target, (manifest_path.parent / item["backup"]).read_bytes())
        else:
            target.unlink(missing_ok=True)
    subprocess.run(["git", "-c", f"safe.directory={CONTROL_ROOT.as_posix()}",
                    "-C", str(CONTROL_ROOT), "restore", "--staged", "--",
                    *[item["path"] for item in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]]],
                   capture_output=True, check=False, timeout=30)
    if git("status", "--porcelain", "--untracked-files=all"):
        return {"state": "recovery_required", "error_code": "CHANGE_ROLLBACK_DIRTY"}
    return {"state": "failed", "error_code": "CHANGE_ROLLED_BACK", "recovery": "rollback_complete"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("transact", "recover"))
    parser.add_argument("job_directory", type=Path)
    parser.add_argument("--run-token")
    args = parser.parse_args()
    state_path = args.job_directory / ("materializer-state.json" if args.mode == "transact" else "materializer-recovery-state.json")
    try:
        if args.mode == "recover":
            value = restore_from_journal(args.job_directory)
        else:
            value = materialize(args.job_directory)
        atomic_json(state_path, value if "state" in value else {"state": "succeeded", **value})
        return 0 if value.get("state", "succeeded") == "succeeded" else (3 if value.get("state") == "recovery_required" else 1)
    except Exception as exc:
        atomic_json(state_path, {"state": "failed", "error_code": "WINDOWS_MATERIALIZATION_FAILED", "detail": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
