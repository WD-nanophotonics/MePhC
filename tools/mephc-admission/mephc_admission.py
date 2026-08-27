"""Always-on Windows STDIO admission shim for the MePhC WSL MCP server."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ALLOWED_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
WSL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe"
BACKEND = ["-d", "Ubuntu", "--", "/home/icy/miniconda3/envs/mp/bin/python",
           "/opt/mephc-runner/current/mcp_server.py"]
TOOL_NAMES = ("mephc_capabilities", "mephc_doctor", "mephc_resume", "mephc_change",
              "mephc_submit", "mephc_status", "mephc_wait", "mephc_recover",
              "mephc_inspect", "mephc_report", "mephc_publish", "mephc_transport_canary")


def inherited_cwd() -> Path:
    value = os.getcwd()
    if value.startswith("\\\\") or value.startswith("//"):
        raise PermissionError("ADMISSION_SCOPE_MISMATCH:UNC_FORBIDDEN")
    actual = Path(value).resolve(strict=True)
    allowed = ALLOWED_ROOT.resolve(strict=True)
    if os.path.normcase(str(actual)) != os.path.normcase(str(allowed)):
        raise PermissionError(f"ADMISSION_SCOPE_MISMATCH:{actual}")
    return actual


def reply(identifier: Any, result: Any = None, error: str | None = None) -> None:
    value: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier}
    if error is None:
        value["result"] = result
    else:
        value["error"] = {"code": -32001, "message": error}
    sys.stdout.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def rejected_loop(reason: str) -> int:
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line.lstrip("\ufeff"))
            identifier, method = request.get("id"), request.get("method")
            if method == "initialize":
                reply(identifier, {"protocolVersion": request.get("params", {}).get("protocolVersion", "2025-03-26"),
                                   "capabilities": {"tools": {}},
                                   "serverInfo": {"name": "mephc-windows-admission", "version": "1.0.0"}})
            elif method == "ping":
                reply(identifier, {})
            elif method == "tools/list":
                reply(identifier, {"tools": [{"name": name, "description": "MePhC scoped tool",
                                               "inputSchema": {"type": "object"}} for name in TOOL_NAMES]})
            elif method == "tools/call":
                reply(identifier, error=reason)
            elif identifier is not None:
                reply(identifier, error=reason)
        except Exception as exc:
            if request.get("id") is not None:
                reply(request.get("id"), error=f"ADMISSION_PROTOCOL_ERROR:{type(exc).__name__}")
    return 0


def proxy() -> int:
    child = subprocess.Popen([str(WSL), *BACKEND], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
    assert child.stdin is not None and child.stdout is not None
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line.lstrip("\ufeff"))
            child.stdin.write(json.dumps(request, separators=(",", ":"), ensure_ascii=False) + "\n")
            child.stdin.flush()
            response = child.stdout.readline()
            if not response:
                if request.get("id") is not None:
                    reply(request.get("id"), error="DURABLE_JOB_RECOVERY_REQUIRED")
                return 3
            sys.stdout.write(response)
            sys.stdout.flush()
        except (BrokenPipeError, OSError, json.JSONDecodeError):
            if request.get("id") is not None:
                reply(request.get("id"), error="DURABLE_JOB_RECOVERY_REQUIRED")
            return 3
    child.stdin.close()
    child.terminate()
    return 0


def main() -> int:
    try:
        inherited_cwd()
    except (OSError, PermissionError) as exc:
        return rejected_loop(str(exc))
    return proxy()


if __name__ == "__main__":
    raise SystemExit(main())

