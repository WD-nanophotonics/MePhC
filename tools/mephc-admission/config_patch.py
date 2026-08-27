"""Atomic, target-table-only Codex MCP configuration patcher."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

TARGETS = ("mephc_windows_shadow", "mephc_native_admission_shadow", "mephc_native_admission_probe")


def table_span(text: str, name: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"(?m)^\[mcp_servers\.{re.escape(name)}\]\s*$")
    match = pattern.search(text)
    if not match:
        return None
    following = re.search(r"(?m)^\[", text[match.end():])
    return match.start(), match.end() + (following.start() if following else len(text[match.end():]))


def remove_table(text: str, name: str) -> str:
    span = table_span(text, name)
    return text if span is None else text[:span[0]].rstrip() + "\n\n" + text[span[1]:].lstrip()


def patch(config: Path, python: Path, shim: Path, apply: bool) -> dict:
    before = config.read_text(encoding="utf-8-sig") if config.exists() else ""
    after = before
    for name in TARGETS:
        after = remove_table(after, name)
    table = ("[mcp_servers.mephc_windows_shadow]\n"
             f"command = {json.dumps(str(python))}\n"
             f"args = [{json.dumps(str(shim))}]\n"
             "enabled = true\n")
    after = after.rstrip() + "\n\n" + table
    result = {"changed": before != after, "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
              "after_sha256": hashlib.sha256(after.encode()).hexdigest(), "target": str(config)}
    if not apply or before == after:
        return result
    backup = config.with_name(config.name + ".mephc-backup-" + time.strftime("%Y%m%d-%H%M%S"))
    if config.exists():
        shutil.copy2(config, backup)
    temporary = config.with_name(f".{config.name}.{os.getpid()}.tmp")
    temporary.write_text(after, encoding="utf-8", newline="\n")
    os.replace(temporary, config)
    result["backup"] = str(backup)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(patch(args.config, args.python, args.shim, args.apply))
