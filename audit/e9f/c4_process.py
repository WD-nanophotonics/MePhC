"""Measured C4 worker-process scanner; unavailable /proc is fail-closed."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence


def scan_orphans(worker_marker: str, worker_id: str, exclude_pids: Sequence[int] = ()) -> list[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        raise RuntimeError("C3_C4_PROC_SCAN_UNAVAILABLE")
    excluded = set(exclude_pids)
    found: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) in excluded:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if worker_marker in command and worker_id in command:
            found.append(int(entry.name))
    return sorted(found)
