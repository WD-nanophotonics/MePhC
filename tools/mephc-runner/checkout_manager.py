"""Create immutable, detached ext4 execution checkouts from the Windows Git store."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import runtime_config as config

SHA40 = re.compile(r"^[0-9a-f]{40}$")


class CheckoutError(RuntimeError):
    pass


def _git(*args: str, cwd: Path | None = None) -> str:
    command = ["/usr/bin/git"]
    if cwd is not None:
        command.extend(["-C", str(cwd)])
    command.extend(args)
    result = subprocess.run(command, text=True, encoding="utf-8", capture_output=True, check=False)
    if result.returncode:
        raise CheckoutError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def source_head() -> str:
    value = _git("-c", "core.autocrlf=true", "rev-parse", "HEAD", cwd=config.CONTROL_ROOT)
    if not SHA40.fullmatch(value):
        raise CheckoutError("SOURCE_HEAD_INVALID")
    return value


def source_origin_main() -> str:
    return _git("-c", "core.autocrlf=true", "rev-parse", "origin/main", cwd=config.CONTROL_ROOT)


def require_clean_source() -> None:
    if _git("-c", "core.autocrlf=true", "status", "--porcelain", "--untracked-files=no", cwd=config.CONTROL_ROOT):
        raise CheckoutError("CONTROL_ROOT_DIRTY")


def ensure(commit: str) -> Path:
    if not SHA40.fullmatch(commit):
        raise CheckoutError("SOURCE_COMMIT_INVALID")
    require_clean_source()
    if source_origin_main() != config.EXPECTED_ORIGIN_MAIN:
        raise CheckoutError("ORIGIN_MAIN_MOVED")
    config.GIT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    config.CHECKOUTS.mkdir(parents=True, exist_ok=True)
    if not config.GIT_CACHE.is_dir():
        _git("init", "--bare", str(config.GIT_CACHE))
    _git("fetch", "--force", "--no-tags", str(config.CONTROL_ROOT / ".git"), commit, cwd=config.GIT_CACHE)
    resolved = _git("rev-parse", "FETCH_HEAD^{commit}", cwd=config.GIT_CACHE)
    if resolved != commit:
        raise CheckoutError("SOURCE_COMMIT_NOT_EXACT")
    checkout = config.checkout_for(commit)
    if not checkout.exists():
        _git("worktree", "add", "--detach", str(checkout), commit, cwd=config.GIT_CACHE)
    if _git("rev-parse", "HEAD", cwd=checkout) != commit:
        raise CheckoutError("EXECUTION_HEAD_MISMATCH")
    if _git("status", "--porcelain", "--untracked-files=all", cwd=checkout):
        raise CheckoutError("EXECUTION_CHECKOUT_DIRTY")
    mount = subprocess.run(
        ["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "--target", str(checkout)],
        text=True, encoding="utf-8", capture_output=True, check=False,
    )
    if mount.returncode or mount.stdout.strip().lower() in {"9p", "drvfs", "fuseblk"}:
        raise CheckoutError("EXECUTION_CHECKOUT_NOT_EXT4")
    return checkout
