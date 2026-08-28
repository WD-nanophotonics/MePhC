"""Always-on Windows STDIO admission shim for the MePhC WSL MCP server."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import secrets
from typing import Any

ALLOWED_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
CONNECTOR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MePhCRunner" / "mephc-connector.ps1"
BACKEND = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(CONNECTOR)]
TOOL_NAMES = ("mephc_capabilities", "mephc_doctor", "mephc_resume", "mephc_change",
              "mephc_validate", "mephc_submit", "mephc_native", "mephc_request_status",
              "mephc_status", "mephc_wait", "mephc_recover",
              "mephc_inspect", "mephc_retention_search", "mephc_retention_inspect",
              "mephc_runtime_attest", "mephc_runtime_reload", "mephc_runtime_activate",
              "mephc_work_order_preflight", "mephc_retention_worker_reload",
              "mephc_report", "mephc_publish", "mephc_transport_canary")
AUDIT_LOG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MePhCRunner" / "admission" / "launch-audit.jsonl"
READ_ONLY_TOOLS = {"mephc_capabilities", "mephc_inspect", "mephc_retention_inspect",
                   "mephc_runtime_attest", "mephc_work_order_preflight",
                   "mephc_request_status", "mephc_status", "mephc_wait"}
LOCAL_LIFECYCLE_TOOLS = {"mephc_runtime_reload": "reload", "mephc_runtime_activate": "activate",
                         "mephc_retention_worker_reload": "retention-worker-reload"}
LIFECYCLE = Path(__file__).resolve().parent / "runtime_lifecycle.py"
LOADED_ADMISSION_MODULE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def reply(identifier: Any, result: Any = None, error: str | None = None,
          error_data: dict[str, Any] | None = None) -> None:
    value: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier}
    if error is None:
        value["result"] = result
    else:
        value["error"] = {"code": -32001, "message": error}
        if error_data is not None:
            value["error"]["data"] = error_data
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


def start_backend() -> subprocess.Popen[str]:
    environment = dict(os.environ)
    environment["MEPHC_ADMISSION_MODULE_HASH"] = LOADED_ADMISSION_MODULE_HASH
    environment["MEPHC_ADMISSION_BUILD"] = LOADED_ADMISSION_MODULE_HASH[:16]
    inherited = [item for item in environment.get("WSLENV", "").split(":") if item]
    for name in ("MEPHC_ADMISSION_MODULE_HASH", "MEPHC_ADMISSION_BUILD"):
        if name not in inherited: inherited.append(name)
    environment["WSLENV"] = ":".join(inherited)
    return subprocess.Popen([str(POWERSHELL), *BACKEND], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1, env=environment,
                            creationflags=NO_WINDOW)


def installed_build() -> str | None:
    try:
        value = json.loads((CONNECTOR.parent / "current.json").read_text(encoding="utf-8-sig"))
        return value.get("build_id") if isinstance(value.get("build_id"), str) else None
    except (OSError, json.JSONDecodeError):
        return None


def local_lifecycle(name: str) -> dict[str, Any]:
    result = subprocess.run([sys.executable, str(LIFECYCLE), LOCAL_LIFECYCLE_TOOLS[name]],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", timeout=1800, check=False,
                            creationflags=NO_WINDOW)
    try:
        value = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        value = {"state":"rejected","error_code":"RUNTIME_LIFECYCLE_PROTOCOL_ERROR",
                 "detail":result.stderr[-1000:],"retry_allowed":False,"safe_next_tool":"mephc_runtime_attest"}
    return value


def tool_name(request: dict[str, Any]) -> str | None:
    if request.get("method") != "tools/call":
        return None
    value = request.get("params", {}).get("name")
    return value if isinstance(value, str) else None


def replay_safe(request: dict[str, Any]) -> bool:
    return request.get("method") in {"initialize", "ping", "tools/list"} or tool_name(request) in READ_ONLY_TOOLS


def disconnect_data(request: dict[str, Any], request_identity: str) -> dict[str, Any]:
    arguments = request.get("params", {}).get("arguments") or {}
    job_id = arguments.get("job_id") if isinstance(arguments, dict) else None
    name = tool_name(request)
    return {"error_code": "BACKEND_DISCONNECTED", "tool": name,
            "job_id": job_id if isinstance(job_id, str) else None,
            "admission_request_id": request_identity, "retry_allowed": False,
            "safe_next_tool": "mephc_status" if isinstance(job_id, str) else "mephc_request_status"}


def stop_backend(child: subprocess.Popen[str]) -> None:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()


def proxy() -> int:
    audit("admission_authorized", cwd=os.getcwd())
    try:
        child = start_backend()
    except OSError as exc:
        audit("backend_start_failed", error=type(exc).__name__)
        return rejected_loop("BACKEND_START_FAILED")
    assert child.stdin is not None and child.stdout is not None
    child_build = installed_build()
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line.lstrip("\ufeff"))
            audit("client_request", method=request.get("method"))
            if request.get("id") is None:
                payload = json.dumps(request, separators=(",", ":"), ensure_ascii=False) + "\n"
                child.stdin.write(payload)
                child.stdin.flush()
                audit("notification_forwarded", method=request.get("method"))
                continue
            request_identity = secrets.token_hex(16)
            params = request.get("params")
            if isinstance(params, dict):
                meta = params.setdefault("_meta", {})
                if isinstance(meta, dict): meta["mephc_admission_request_id"] = request_identity
            name = tool_name(request)
            if name in LOCAL_LIFECYCLE_TOOLS:
                arguments = params.get("arguments") if isinstance(params, dict) else None
                value = ({"state":"rejected","error_code":"RUNTIME_LIFECYCLE_ARGUMENTS_FORBIDDEN",
                          "retry_allowed":False,"safe_next_tool":"mephc_runtime_attest"}
                         if arguments not in ({}, None) else local_lifecycle(name))
                reply(request.get("id"), {"content":[{"type":"text","text":json.dumps(value, sort_keys=True)}],
                                          "isError":False})
                stop_backend(child)
                child = start_backend(); child_build = installed_build()
                assert child.stdin is not None and child.stdout is not None
                continue
            current_build = installed_build()
            if name not in READ_ONLY_TOOLS and current_build != child_build:
                stop_backend(child)
                child = start_backend(); child_build = current_build
                assert child.stdin is not None and child.stdout is not None
                audit("backend_rotated_for_build", build_id=current_build, tool=name)
            payload = json.dumps(request, separators=(",", ":"), ensure_ascii=False) + "\n"
            response = ""
            attempts = 2 if replay_safe(request) else 1
            for attempt in range(attempts):
                try:
                    child.stdin.write(payload)
                    child.stdin.flush()
                    response = child.stdout.readline()
                except (BrokenPipeError, OSError):
                    response = ""
                if response:
                    break
                audit("backend_disconnected", return_code=child.poll(), tool=tool_name(request),
                      request_identity=request_identity, attempt=attempt + 1)
                if attempt + 1 < attempts:
                    stop_backend(child)
                    child = start_backend()
                    child_build = installed_build()
                    audit("backend_restarted_for_read_only", tool=tool_name(request),
                          request_identity=request_identity)
            if not response:
                reply(request.get("id"), error="DURABLE_JOB_RECOVERY_REQUIRED",
                      error_data=disconnect_data(request, request_identity))
                return 3
            audit("backend_response", method=request.get("method"))
            sys.stdout.write(response)
            sys.stdout.flush()
        except (BrokenPipeError, OSError, json.JSONDecodeError):
            if request.get("id") is not None:
                identity = secrets.token_hex(16)
                reply(request.get("id"), error="DURABLE_JOB_RECOVERY_REQUIRED",
                      error_data=disconnect_data(request, identity))
            return 3
    child.stdin.close()
    stop_backend(child)
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
