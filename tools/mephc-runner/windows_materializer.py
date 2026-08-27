"""Restricted Windows-side source materializer for v2 change jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

CONTROL_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
EXPECTED_ORIGIN_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_TOP = {"audit", "tests", "tools", "mephc", "scripts", "docs", ".codex", ".agents"}


class MaterializeError(RuntimeError):
    pass


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(CONTROL_ROOT), *args], text=True,
                            encoding="utf-8", capture_output=True, check=False)
    if result.returncode:
        raise MaterializeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


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
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    if (job.get("schema") != "mephc-runner-job-v2" or job.get("operation") != "change"
            or job.get("expected_control_root", "").casefold() != str(CONTROL_ROOT).casefold()):
        raise MaterializeError("CHANGE_JOB_V2_REQUIRED")
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
    try:
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
            backups.append((target, before))
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temporary.write_bytes(encoded)
            os.replace(temporary, target)
        git("add", "--", *[item["path"] for item in files])
        git("commit", "-m", job["change"]["commit_message"])
        final = git("rev-parse", "HEAD")
        attestation = {"schema": "mephc-windows-materialization-v1", "job_id": job["job_id"],
                       "base_head": base, "final_commit": final, "control_root": str(CONTROL_ROOT),
                       "prelive_required": True,
                       "files": {item["path"]: item["expected_postimage_sha256"] for item in files}}
        atomic_json(job_dir / "change-attestation.json", attestation)
        return attestation
    except Exception:
        if git("rev-parse", "HEAD") == base:
            for target, before in backups:
                if before is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(before)
            subprocess.run(["git", "-C", str(CONTROL_ROOT), "reset"], capture_output=True, check=False)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("transact", "recover"))
    parser.add_argument("job_directory", type=Path)
    args = parser.parse_args()
    state_path = args.job_directory / ("materializer-state.json" if args.mode == "transact" else "materializer-recovery-state.json")
    try:
        if args.mode == "recover" and (args.job_directory / "change-attestation.json").is_file():
            value = json.loads((args.job_directory / "change-attestation.json").read_text(encoding="utf-8"))
        else:
            value = materialize(args.job_directory)
        atomic_json(state_path, {"state": "succeeded", **value})
        return 0
    except Exception as exc:
        atomic_json(state_path, {"state": "failed", "error_code": "WINDOWS_MATERIALIZATION_FAILED", "detail": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
