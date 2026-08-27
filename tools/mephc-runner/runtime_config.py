"""Single source of truth for the Windows-control/WSL-execution split."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ID = "MEPHC"
CONTROL_ROOT_WINDOWS = os.environ.get(
    "MEPHC_CONTROL_ROOT_WINDOWS", r"C:\Users\icywo\PycharmProjects\MePhC-Windows"
)
CONTROL_ROOT = Path(CONTROL_ROOT_WINDOWS if os.name == "nt" else os.environ.get(
    "MEPHC_CONTROL_ROOT_WSL", "/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows"
))
STATE_ROOT = Path(os.environ.get(
    "MEPHC_STATE_ROOT", "/home/icy/.local/state/mephc-runner/MEPHC"
))
RUNTIME = STATE_ROOT / "runner"
JOBS = RUNTIME / "jobs"
CERTIFICATES = STATE_ROOT / "certificates"
OUTBOX = STATE_ROOT / "outbox"
GIT_CACHE = Path(os.environ.get(
    "MEPHC_GIT_CACHE", "/home/icy/.cache/mephc-runner/MEPHC.git"
))
CHECKOUTS = Path(os.environ.get(
    "MEPHC_EXECUTION_ROOT", "/home/icy/.cache/mephc-runner/checkouts"
))
PYTHON = Path(os.environ.get(
    "MEPHC_PYTHON", "/home/icy/miniconda3/envs/mp/bin/python"
))
WINDOWS_RUNTIME_WSL = Path(os.environ.get(
    "MEPHC_WINDOWS_RUNTIME_WSL", "/mnt/c/Users/icywo/AppData/Local/MePhCRunner"
))
WINDOWS_GIT_WSL = Path(os.environ.get(
    "MEPHC_WINDOWS_GIT_WSL", "/mnt/c/Program Files/Git/cmd/git.exe"
))
BROKER_HEARTBEAT = WINDOWS_RUNTIME_WSL / "broker-heartbeat.json"
MATERIALIZER_TIMEOUT_SECONDS = int(os.environ.get("MEPHC_MATERIALIZER_TIMEOUT_SECONDS", "300"))
RETENTION_SEARCH_TIMEOUT_SECONDS = int(os.environ.get("MEPHC_RETENTION_SEARCH_TIMEOUT_SECONDS", "300"))
EXPECTED_ORIGIN_MAIN = os.environ.get(
    "MEPHC_EXPECTED_ORIGIN_MAIN", "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
)
EPOCH_FILE = RUNTIME / "state-epoch"


def state_epoch() -> str:
    try:
        value = EPOCH_FILE.read_text(encoding="ascii").strip()
    except FileNotFoundError as exc:
        if os.name == "nt":
            return "uninitialized-windows-audit"
        raise RuntimeError("STATE_EPOCH_MISSING") from exc
    if not value or any(character not in "0123456789abcdef-" for character in value.lower()):
        raise RuntimeError("STATE_EPOCH_INVALID")
    return value


def checkout_for(commit: str) -> Path:
    return CHECKOUTS / commit
