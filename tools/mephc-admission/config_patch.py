"""Atomic, target-table-only Codex MCP configuration patcher."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import tomllib

CANONICAL = "mcp_servers.mephc"
LEGACY_TABLES = (
    "mcp_servers.mephc_windows_shadow",
    "mcp_servers.mephc_native",
    "mcp_servers.mephc_admission_probe",
    "mcp_servers.mephc_native_admission_shadow",
    "mcp_servers.mephc_native_admission_probe",
    'plugins."mephc-runner@personal"',
)


def table_span(text: str, table: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"(?m)^\[{re.escape(table)}\]\s*$")
    match = pattern.search(text)
    if not match:
        return None
    following = re.search(r"(?m)^\[", text[match.end():])
    return match.start(), match.end() + (following.start() if following else len(text[match.end():]))


def remove_table(text: str, table: str) -> str:
    headers = list(re.finditer(r"(?m)^\[([^\]]+)\]\s*$", text))
    spans = []
    for index, header in enumerate(headers):
        name = header.group(1)
        if name == table or name.startswith(table + "."):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            spans.append((header.start(), end))
    for start, end in reversed(spans):
        text = text[:start].rstrip() + "\n\n" + text[end:].lstrip()
    return text


def without_owned(value: dict) -> dict:
    result = copy.deepcopy(value)
    servers = result.get("mcp_servers", {})
    for name in ("mephc", "mephc_windows_shadow", "mephc_native", "mephc_admission_probe",
                 "mephc_native_admission_shadow", "mephc_native_admission_probe"):
        servers.pop(name, None)
    if not servers:
        result.pop("mcp_servers", None)
    plugins = result.get("plugins", {})
    plugins.pop("mephc-runner@personal", None)
    if not plugins:
        result.pop("plugins", None)
    return result


def set_enabled(text: str, table: str, enabled: bool) -> str:
    span = table_span(text, table)
    if span is None:
        return text
    start, end = span
    block = text[start:end].rstrip()
    value = "true" if enabled else "false"
    pattern = re.compile(r"(?m)^enabled\s*=.*$")
    block = pattern.sub(f"enabled = {value}", block, count=1) if pattern.search(block) else block + f"\nenabled = {value}"
    return text[:start] + block + "\n\n" + text[end:].lstrip()


def patch(config: Path, python: Path, shim: Path, apply: bool, finalize: bool = False) -> dict:
    before = config.read_text(encoding="utf-8-sig") if config.exists() else ""
    after = remove_table(before, CANONICAL)
    for table_name in LEGACY_TABLES:
        after = remove_table(after, table_name) if finalize else set_enabled(after, table_name, False)
    table = ("[mcp_servers.mephc]\n"
             f"command = {json.dumps(str(python))}\n"
             f"args = [{json.dumps(str(shim))}]\n"
             "enabled = true\n")
    after = after.rstrip() + "\n\n" + table
    before_parsed = tomllib.loads(before) if before.strip() else {}
    after_parsed = tomllib.loads(after)
    if without_owned(before_parsed) != without_owned(after_parsed):
        raise RuntimeError("UNRELATED_CONFIG_DRIFT")
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
    parser.add_argument("--finalize", action="store_true",
                        help="remove disabled legacy MePhC tables after restart acceptance")
    args = parser.parse_args()
    print(patch(args.config, args.python, args.shim, args.apply, args.finalize))
