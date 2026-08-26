#!/home/icy/miniconda3/envs/mp/bin/python
"""Typed stdio MCP server for the MePhC persistent runner."""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jobctl
import workflow_resume

ROOT = Path("/home/icy/MePhC")
READ_ROOTS = {"audit", "mephc", "scripts", "tests", "tools"}
READ_ROOT_FILES = {"AGENTS.md", "pyproject.toml"}


def advertised_tools():
    return [*TOOLS, *READONLY_TOOLS]


def _relative(value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("INSPECT_PATH_INVALID")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] in {(".relayctl",), (".git",)}:
        raise ValueError("INSPECT_PATH_FORBIDDEN")
    if len(relative.parts) == 1 and relative.name in READ_ROOT_FILES:
        return relative
    if not relative.parts or relative.parts[0] not in READ_ROOTS:
        raise ValueError("INSPECT_PATH_FORBIDDEN")
    return relative


def _target(relative: Path) -> Path:
    target = ROOT / relative
    try:
        target.resolve(strict=False).relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError("INSPECT_PATH_FORBIDDEN") from exc
    for part in (target, *target.parents):
        if part.is_symlink():
            raise ValueError("INSPECT_SYMLINK_FORBIDDEN")
        if part == ROOT:
            break
    return target


def _git_files(relative: Path) -> list[str]:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "ls-files", "-z", "--", relative.as_posix()],
        text=False, capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("INSPECT_GIT_CHECK_FAILED")
    return [value.decode("utf-8") for value in result.stdout.split(b"\0") if value]


def inspect(args: dict) -> dict:
    if not isinstance(args, dict) or set(args) - {"operation", "path", "offset", "max_bytes"}:
        raise ValueError("INSPECT_SCHEMA_INVALID")
    operation = args.get("operation")
    relative = _relative(args.get("path"))
    target = _target(relative)
    tracked = _git_files(relative)
    if operation == "list":
        if not target.is_dir():
            raise ValueError("INSPECT_NOT_DIRECTORY")
        prefix = relative.as_posix().rstrip("/") + "/"
        entries = sorted({value[len(prefix):].split("/", 1)[0] for value in tracked if value.startswith(prefix)})
        limit = args.get("max_bytes", 200)
        if not isinstance(limit, int) or not 1 <= limit <= 65536:
            raise ValueError("INSPECT_LIMIT_INVALID")
        return {"operation": "list", "path": relative.as_posix(), "entries": entries[:limit], "total_entries": len(entries), "truncated": len(entries) > limit}
    if operation != "read":
        raise ValueError("INSPECT_OPERATION_INVALID")
    if not target.is_file() or target.is_symlink() or relative.as_posix() not in tracked:
        raise ValueError("INSPECT_TRACKED_FILE_REQUIRED")
    offset = args.get("offset", 0)
    limit = args.get("max_bytes", 16384)
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 65536:
        raise ValueError("INSPECT_LIMIT_INVALID")
    raw = target.read_bytes()
    if len(raw) > 8 * 1024 * 1024 or offset > len(raw):
        raise ValueError("INSPECT_SIZE_OR_OFFSET_INVALID")
    end = min(len(raw), offset + limit)
    while True:
        try:
            content = raw[offset:end].decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            if exc.start == 0:
                raise ValueError("INSPECT_OFFSET_NOT_UTF8_BOUNDARY") from exc
            end = offset + exc.start
    return {"operation": "read", "path": relative.as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw), "offset": offset, "next_offset": end if end < len(raw) else None, "content_utf8": content}

TOOLS = [
    {"name": "mephc_capabilities", "description": "Return canonical MePhC runner capabilities, the discovered current workflow state, and active durable jobs.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mephc_doctor", "description": "Submit and wait for a canonical MePhC doctor job.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mephc_resume", "description": "Return the latest hash-bound supervisor work order, or create and dispatch exactly one durable status request and return its wait job. Never returns an idle work-order request to the agent.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mephc_change", "description": "Atomically materialize, test, and commit declared UTF-8 MePhC files. The Runner binds Git and image hashes itself.", "inputSchema": {"type": "object", "required": ["files", "tests", "commit_message"], "properties": {"files": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["path", "content_utf8"], "properties": {"path": {"type": "string"}, "content_utf8": {"type": "string"}}, "additionalProperties": False}}, "tests": {"type": "array", "minItems": 1, "items": {"type": "string"}}, "commit_message": {"type": "string"}}, "additionalProperties": False}},
    {"name": "mephc_submit", "description": "Submit a typed non-change MePhC operation.", "inputSchema": {"type": "object", "required": ["operation"], "properties": {"operation": {"type": "string", "enum": ["doctor", "worktree", "prelive", "native", "publish", "courier"]}, "arguments": {"type": "array", "items": {"type": "string"}}, "certificate_sha256": {"type": ["string", "null"]}}, "additionalProperties": False}},
    {"name": "mephc_status", "description": "Read one persisted job state.", "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}}, "additionalProperties": False}},
    {"name": "mephc_wait", "description": "Wait without killing the persistent job.", "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 4860}}, "additionalProperties": False}},
    {"name": "mephc_recover", "description": "Request the only state-approved recovery for an existing job.", "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}}, "additionalProperties": False}},
]

READONLY_TOOLS = [
    {"name": "mephc_inspect", "description": "Read only tracked UTF-8 MePhC source or audit evidence, or list a controlled tracked directory. Rejects runtime, Git internals, symlinks, credentials, path traversal, and untracked files.", "inputSchema": {"type": "object", "required": ["operation", "path"], "properties": {"operation": {"type": "string", "enum": ["list", "read"]}, "path": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536}}, "additionalProperties": False}},
]


def captured(call):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        result = call()
    return {"return_code": result if isinstance(result, int) else 0, "events": [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]}


def invoke(name, args):
    if name == "mephc_capabilities":
        value = jobctl.capabilities()
        value["read_only_evidence"] = {"tool": "mephc_inspect", "operations": ["list", "read"], "tracked_only": True}
        return value
    if name == "mephc_inspect":
        return inspect(args)
    if name == "mephc_resume":
        return workflow_resume.resume()
    if name == "mephc_doctor":
        directory = jobctl.submit("doctor", [], None)
        return captured(lambda: jobctl.wait(directory.name, 120))
    if name == "mephc_change":
        directory = jobctl.submit_change(args)
        return {"job_id": directory.name, "state": "ready"}
    if name == "mephc_submit":
        directory = jobctl.submit(args["operation"], args.get("arguments", []), args.get("certificate_sha256"))
        return {"job_id": directory.name, "state": "ready"}
    if name == "mephc_status":
        return jobctl.read_state(args["job_id"])
    if name == "mephc_wait":
        return captured(lambda: jobctl.wait(args["job_id"], args.get("timeout", 4860)))
    if name == "mephc_recover":
        jobctl.request_recovery(args["job_id"])
        return {"job_id": args["job_id"], "state": "recovery_requested"}
    raise ValueError(f"unknown tool: {name}")


def reply(identifier, result=None, error=None):
    value = {"jsonrpc": "2.0", "id": identifier}
    if error is not None:
        value["error"] = {"code": -32000, "message": error}
    else:
        value["result"] = result
    print(json.dumps(value, separators=(",", ":"), ensure_ascii=False), flush=True)


def main():
    for line in sys.stdin:
        request={}
        try:
            request = json.loads(line.lstrip("\ufeff"))
            method = request.get("method")
            identifier = request.get("id")
            if method == "initialize":
                reply(identifier, {"protocolVersion": request.get("params", {}).get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}}, "serverInfo": {"name": "mephc-runner", "version": "2.2.0"}})
            elif method == "ping":
                reply(identifier, {})
            elif method == "tools/list":
                reply(identifier, {"tools": advertised_tools()})
            elif method == "tools/call":
                params = request.get("params", {})
                value = invoke(params.get("name"), params.get("arguments") or {})
                reply(identifier, {"content": [{"type": "text", "text": json.dumps(value, sort_keys=True, ensure_ascii=False)}], "isError": False})
            elif identifier is not None:
                reply(identifier, error=f"unsupported method: {method}")
        except Exception as exc:
            if request.get("id") is not None:
                reply(request.get("id"), error=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
