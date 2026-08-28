#!/home/icy/miniconda3/envs/mp/bin/python
"""WSL helper for exact committed MePhC sandbox checkouts."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


CONTROL = Path("/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows")
CACHE = Path("/home/icy/.cache/mephc-runner/MEPHC.git")
CHECKOUTS = Path("/home/icy/.cache/mephc-runner/checkouts")
CURRENT = Path("/home/icy/.local/share/mephc-runtime/current")
SCIENCE_STATE = CURRENT.parent / "science"
PYTHON = Path("/home/icy/miniconda3/envs/mp/bin/python")
EXPECTED_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class RuntimeError_(RuntimeError):
    pass


def run(argv: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, text=True, encoding="utf-8", capture_output=True, check=False,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""})
    if check and result.returncode:
        raise RuntimeError_((result.stderr or result.stdout).strip())
    return result


def git(*args: str, cwd: Path = CONTROL) -> str:
    return run(["/usr/bin/git", "-c", "core.autocrlf=true", "-C", str(cwd), *args]).stdout.strip()


def source() -> str:
    if git("symbolic-ref", "--quiet", "--short", "HEAD") != "sandbox":
        raise RuntimeError_("CONTROL_BRANCH_NOT_SANDBOX")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError_("CONTROL_ROOT_DIRTY")
    if git("rev-parse", "origin/main") != EXPECTED_MAIN:
        raise RuntimeError_("ORIGIN_MAIN_MOVED")
    head = git("rev-parse", "HEAD")
    if not SHA40.fullmatch(head):
        raise RuntimeError_("SOURCE_HEAD_INVALID")
    return head


def ensure(commit: str) -> Path:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHECKOUTS.mkdir(parents=True, exist_ok=True)
    if not CACHE.is_dir():
        run(["/usr/bin/git", "init", "--bare", str(CACHE)])
    run(["/usr/bin/git", "-C", str(CACHE), "fetch", "--force", "--no-tags", str(CONTROL / ".git"), commit])
    if run(["/usr/bin/git", "-C", str(CACHE), "rev-parse", "FETCH_HEAD^{commit}"]).stdout.strip() != commit:
        raise RuntimeError_("SOURCE_COMMIT_NOT_EXACT")
    checkout = CHECKOUTS / commit
    if not checkout.exists():
        run(["/usr/bin/git", "-C", str(CACHE), "worktree", "add", "--detach", str(checkout), commit])
    if git("rev-parse", "HEAD", cwd=checkout) != commit or git("status", "--porcelain", "--untracked-files=all", cwd=checkout):
        raise RuntimeError_("EXECUTION_CHECKOUT_MISMATCH")
    fstype = run(["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "--target", str(checkout)]).stdout.strip().lower()
    if fstype in {"9p", "drvfs", "fuseblk", ""}:
        raise RuntimeError_("EXECUTION_CHECKOUT_NOT_LINUX_NATIVE")
    return checkout


def sync() -> Path:
    checkout = ensure(source()).resolve(strict=True)
    CURRENT.parent.mkdir(parents=True, exist_ok=True)
    temporary = CURRENT.with_name(f".{CURRENT.name}.{os.getpid()}.new")
    try:
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(checkout, target_is_directory=True)
        os.replace(temporary, CURRENT)
    finally:
        temporary.unlink(missing_ok=True)
    return checkout


def current() -> Path:
    if not CURRENT.is_symlink():
        raise RuntimeError_("RUNTIME_NOT_SYNCED")
    checkout = CURRENT.resolve(strict=True)
    try:
        checkout.relative_to(CHECKOUTS.resolve(strict=True))
    except ValueError as exc:
        raise RuntimeError_("RUNTIME_LINK_OUTSIDE_CHECKOUTS") from exc
    if not SHA40.fullmatch(checkout.name) or git("rev-parse", "HEAD", cwd=checkout) != checkout.name:
        raise RuntimeError_("RUNTIME_HEAD_MISMATCH")
    if git("status", "--porcelain", "--untracked-files=all", cwd=checkout):
        raise RuntimeError_("RUNTIME_CHECKOUT_DIRTY")
    return checkout


def project(value: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute() or raw.is_symlink():
        raise RuntimeError_("PROJECT_PATH_MUST_BE_ABSOLUTE_REAL_DIRECTORY")
    resolved = raw.resolve(strict=True)
    if not resolved.is_dir() or resolved == CHECKOUTS or CHECKOUTS in resolved.parents:
        raise RuntimeError_("PROJECT_PATH_FORBIDDEN")
    fstype = run(["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "--target", str(resolved)]).stdout.strip().lower()
    if fstype in {"9p", "drvfs", "fuseblk", ""}:
        raise RuntimeError_("PROJECT_PATH_NOT_WSL_NATIVE")
    return resolved


def execute(project_value: str, argv: list[str]) -> None:
    if not argv or any(not item or "\x00" in item for item in argv):
        raise RuntimeError_("ARGV_REQUIRED")
    checkout = sync()
    destination = project(project_value)
    environment = os.environ.copy()
    environment["PATH"] = str(PYTHON.parent) + os.pathsep + environment.get("PATH", "")
    environment["PYTHONPATH"] = str(checkout)
    environment["MEPHC_SOURCE_COMMIT"] = checkout.name
    os.chdir(destination)
    os.execvpe(argv[0], argv, environment)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mephc-runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync")
    commands.add_parser("path")
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--project", required=True)
    run_parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            print(sync())
        elif args.command == "path":
            print(current())
        else:
            values = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
            execute(args.project, values)
    except (RuntimeError_, OSError) as exc:
        print(f"MEPHC_RUNTIME_ERROR:{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
