"""Always-on Windows STDIO admission shim for the MePhC WSL MCP server."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

ALLOWED_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
WSL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe"
BACKEND = ["-d", "Ubuntu", "--", "/home/icy/miniconda3/envs/mp/bin/python",
           "/opt/mephc-runner/current/mcp_server.py"]
TOOL_NAMES = ("mephc_capabilities", "mephc_doctor", "mephc_resume", "mephc_change",
              "mephc_submit", "mephc_status", "mephc_wait", "mephc_recover",
              "mephc_inspect", "mephc_report", "mephc_publish", "mephc_transport_canary")
AUDIT_LOG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MePhCRunner" / "admission" / "launch-audit.jsonl"


def audit(event: str, **fields: Any) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"event": event, "time": int(time.time()), **fields}, sort_keys=True) + "\n")
    except OSError:
        pass


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
    audit("admission_authorized", cwd=os.getcwd())
    try:
        child = subprocess.Popen([str(WSL), *BACKEND], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
    except OSError as exc:
        audit("backend_start_failed", error=type(exc).__name__)
        return rejected_loop("BACKEND_START_FAILED")
    assert child.stdin is not None and child.stdout is not None
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line.lstrip("\ufeff"))
            audit("client_request", method=request.get("method"))
            child.stdin.write(json.dumps(request, separators=(",", ":"), ensure_ascii=False) + "\n")
            child.stdin.flush()
            response = child.stdout.readline()
            if not response:
                detail = child.stderr.readline().strip()[:500] if child.stderr is not None else ""
                audit("backend_disconnected", return_code=child.poll(), detail=detail)
                if request.get("id") is not None:
                    reply(request.get("id"), error="DURABLE_JOB_RECOVERY_REQUIRED")
                return 3
            audit("backend_response", method=request.get("method"))
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
        audit("admission_rejected", cwd=os.getcwd(), reason=str(exc))
        return rejected_loop(str(exc))
    return proxy()


if __name__ == "__main__":
    raise SystemExit(main())
