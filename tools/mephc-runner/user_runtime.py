#!/usr/bin/env python3
"""Human-facing launcher for using committed MePhC sandbox code from WSL projects.

This is deliberately not an Agent entry point. Agent work must use the typed MCP
connector, while this helper gives a human an exact, read-only MePhC import tree
without turning a downstream project's working directory into a runner checkout.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import checkout_manager
import runtime_config as config

CURRENT_LINK = Path("/home/icy/.local/share/mephc-runtime/current")
CONDA_BIN = config.PYTHON.parent
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class RuntimeFailure(RuntimeError):
    pass


def git(*args: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-c", "core.autocrlf=true", "-C", str(config.CONTROL_ROOT), *args],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeFailure(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def require_human_context() -> None:
    if os.environ.get("MEPHC_RUNNER_JOB_ID"):
        raise RuntimeFailure("AGENT_RUNTIME_BYPASS_FORBIDDEN")


def source_commit() -> str:
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "sandbox":
        raise RuntimeFailure("CONTROL_BRANCH_NOT_SANDBOX")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeFailure("CONTROL_ROOT_DIRTY")
    if git("rev-parse", "origin/main") != config.EXPECTED_ORIGIN_MAIN:
        raise RuntimeFailure("ORIGIN_MAIN_MOVED")
    commit = git("rev-parse", "HEAD")
    if not SHA40.fullmatch(commit):
        raise RuntimeFailure("SOURCE_HEAD_INVALID")
    return commit


def sync() -> Path:
    require_human_context()
    checkout = checkout_manager.ensure(source_commit()).resolve(strict=True)
    CURRENT_LINK.parent.mkdir(parents=True, exist_ok=True)
    temporary = CURRENT_LINK.with_name(f".{CURRENT_LINK.name}.{os.getpid()}.new")
    try:
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(checkout, target_is_directory=True)
        os.replace(temporary, CURRENT_LINK)
    finally:
        temporary.unlink(missing_ok=True)
    return checkout


def current_path() -> Path:
    require_human_context()
    if not CURRENT_LINK.is_symlink():
        raise RuntimeFailure("RUNTIME_NOT_SYNCED")
    checkout = CURRENT_LINK.resolve(strict=True)
    try:
        checkout.relative_to(config.CHECKOUTS.resolve(strict=True))
    except ValueError as exc:
        raise RuntimeFailure("RUNTIME_LINK_OUTSIDE_CHECKOUTS") from exc
    commit = checkout.name
    if not SHA40.fullmatch(commit) or checkout_manager._git("rev-parse", "HEAD", cwd=checkout) != commit:
        raise RuntimeFailure("RUNTIME_HEAD_MISMATCH")
    if checkout_manager._git("status", "--porcelain", "--untracked-files=all", cwd=checkout):
        raise RuntimeFailure("RUNTIME_CHECKOUT_DIRTY")
    return checkout


def project_path(value: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute() or raw.is_symlink():
        raise RuntimeFailure("PROJECT_PATH_MUST_BE_ABSOLUTE_REAL_DIRECTORY")
    project = raw.resolve(strict=True)
    if not project.is_dir():
        raise RuntimeFailure("PROJECT_PATH_NOT_DIRECTORY")
    forbidden = (config.CONTROL_ROOT.resolve(), config.STATE_ROOT.resolve(), config.CHECKOUTS.resolve())
    if any(project == root or root in project.parents for root in forbidden):
        raise RuntimeFailure("PROJECT_PATH_FORBIDDEN")
    mount = subprocess.run(
        ["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "--target", str(project)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if mount.returncode or mount.stdout.strip().lower() in {"9p", "drvfs", "fuseblk"}:
        raise RuntimeFailure("PROJECT_PATH_NOT_WSL_NATIVE")
    return project


def run(project_value: str, argv: list[str]) -> None:
    if not argv or argv[0] == "--" or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise RuntimeFailure("ARGV_REQUIRED")
    checkout = sync()
    project = project_path(project_value)
    environment = os.environ.copy()
    environment["PATH"] = str(CONDA_BIN) + os.pathsep + environment.get("PATH", "")
    environment["PYTHONPATH"] = str(checkout)
    environment["MEPHC_SOURCE_COMMIT"] = checkout.name
    os.chdir(project)
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
            print(current_path())
        else:
            command = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
            run(args.project, command)
    except (RuntimeFailure, checkout_manager.CheckoutError, FileNotFoundError) as exc:
        print(f"MEPHC_RUNTIME_ERROR:{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
