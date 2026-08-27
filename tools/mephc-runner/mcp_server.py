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
import workflow
import workflow_resume
import runtime_config as config
import retention_inspector
import runtime_attestation

ROOT = config.CONTROL_ROOT
READ_ROOTS = {"audit", "mephc", "scripts", "tests", "tools"}
READ_ROOT_FILES = {"AGENTS.md", "pyproject.toml"}
INSPECT_DEFAULT_BYTES = 16384
INSPECT_MAX_BYTES = 65536
LOADED_MCP_MODULE_HASH = runtime_attestation.bundle_hash(Path(__file__).resolve().parent,
                                                         runtime_attestation.MCP_BUNDLE_FILES)
runtime_attestation.set_loaded_mcp_hash(LOADED_MCP_MODULE_HASH)
CURRENT_ADMISSION_REQUEST_ID: str | None = None


def bind_admission(directory: Path) -> None:
    if not CURRENT_ADMISSION_REQUEST_ID:
        return
    record = {"event":"admission_accepted","admission_request_id":CURRENT_ADMISSION_REQUEST_ID,
              "timestamp":__import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())}
    with (directory / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _inspect_error(code: str, **fields: object) -> ValueError:
    return ValueError(json.dumps({"error_code": code, "default_bytes": INSPECT_DEFAULT_BYTES,
                                  "max_bytes": INSPECT_MAX_BYTES, **fields}, sort_keys=True))


def advertised_tools():
    return [*TOOLS, *READONLY_TOOLS, *LIFECYCLE_TOOLS, *REPORT_TOOLS, *RELEASE_TOOLS, *CANARY_TOOLS]


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
            raise _inspect_error("INSPECT_LIMIT_INVALID", minimum=1)
        return {"operation": "list", "path": relative.as_posix(), "entries": entries[:limit], "total_entries": len(entries), "truncated": len(entries) > limit}
    if operation != "read":
        raise ValueError("INSPECT_OPERATION_INVALID")
    if not target.is_file() or target.is_symlink() or relative.as_posix() not in tracked:
        raise ValueError("INSPECT_TRACKED_FILE_REQUIRED")
    offset = args.get("offset", 0)
    limit = args.get("max_bytes", INSPECT_DEFAULT_BYTES)
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 65536:
        raise _inspect_error("INSPECT_LIMIT_INVALID", minimum=1)
    raw = target.read_bytes()
    if len(raw) > 8 * 1024 * 1024 or offset > len(raw):
        raise _inspect_error("INSPECT_SIZE_OR_OFFSET_INVALID", size_bytes=len(raw), requested_offset=offset,
                             next_offset=len(raw) if offset > len(raw) else offset)
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
    {"name": "mephc_validate", "description": "Run declared solver-free prelive tests against the current committed SHA without changing or committing source.", "inputSchema": {"type": "object", "required": ["tests"], "properties": {"tests": {"type": "array", "minItems": 1, "items": {"type": "string"}}}, "additionalProperties": False}},
    {"name": "mephc_submit", "description": "Submit a typed non-change MePhC operation.", "inputSchema": {"type": "object", "required": ["operation"], "properties": {"operation": {"type": "string", "enum": ["doctor", "worktree", "prelive", "native", "publish", "courier"]}, "arguments": {"type": "array", "items": {"type": "string"}}, "certificate_sha256": {"type": ["string", "null"]}}, "additionalProperties": False}},
    {"name": "mephc_status", "description": "Read one persisted job state.", "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}}, "additionalProperties": False}},
    {"name": "mephc_wait", "description": "Wait without killing the persistent job.", "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 4860}}, "additionalProperties": False}},
    {"name": "mephc_recover", "description": "Request the only state-approved recovery for an existing job.", "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}}, "additionalProperties": False}},
    {"name": "mephc_retention_search", "description": "Create or reuse a durable read-only exact-SHA search over fixed execution-host retention roots. Every binding must occur in the active work order.", "inputSchema": {"type": "object", "required": ["bindings"], "properties": {"bindings": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "object", "required": ["retention_id", "expected_sha256"], "properties": {"retention_id": {"type": "string"}, "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, "additionalProperties": False}}}, "additionalProperties": False}},
]

LIFECYCLE_TOOLS = [
    {"name": "mephc_runtime_attest", "description": "Return import-time cross-layer build and module attestation without creating a job.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mephc_runtime_reload", "description": "Reload only the installed fixed MePhC broker/worker runtime. Admission handles this tool; it accepts no arguments.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mephc_runtime_activate", "description": "Strictly gate, test, install and activate the exact published infrastructure build. Admission handles this tool; it accepts no arguments.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mephc_work_order_preflight", "description": "Compare the active machine work-order contract with typed capabilities, policy and live runtime attestation.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]

REPORT_TOOLS = [
    {"name": "mephc_report", "description": "Create or safely reuse one plain-text report request bound to the active work order, then return its Courier job. Agents cannot create outbox files, choose destinations, or attach local files.", "inputSchema": {"type": "object", "required": ["work_order_id", "message_utf8"], "properties": {"work_order_id": {"type": "string"}, "message_utf8": {"type": "string"}}, "additionalProperties": False}},
]

READONLY_TOOLS = [
    {"name": "mephc_inspect", "description": "Read only tracked UTF-8 MePhC source or audit evidence, or list a controlled tracked directory. Rejects runtime, Git internals, symlinks, credentials, path traversal, and untracked files.", "inputSchema": {"type": "object", "required": ["operation", "path"], "properties": {"operation": {"type": "string", "enum": ["list", "read"]}, "path": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "max_bytes": {"type": "integer", "minimum": 1, "maximum": 65536}}, "additionalProperties": False}},
    {"name": "mephc_retention_inspect", "description": "Inspect an exact hash-matched retention JSON through an opaque locator. Rehashes bytes on every call and redacts host identity.", "inputSchema": {"type": "object", "required": ["job_id", "retention_id", "operation"], "properties": {"job_id": {"type": "string"}, "retention_id": {"type": "string"}, "operation": {"type": "string", "enum": ["metadata", "outline", "json_page", "numeric_summary"]}, "json_pointer": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "additionalProperties": False}},
]

RELEASE_TOOLS = [
    {"name": "mephc_publish", "description": "Publish the current clean HEAD to origin/sandbox using only the newest passing prelive attestation bound to that exact HEAD. No path or attestation name is accepted from the agent.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]

CANARY_TOOLS = [
    {"name": "mephc_transport_canary", "description": "Create or reuse the single build-bound, attachment-free infrastructure transport canary. It does not alter the active scientific work order.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def _report_certificate() -> tuple[Path, str]:
    candidates = sorted(jobctl.CERTIFICATES.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not candidates:
        raise ValueError("REPORT_CERTIFICATE_MISSING")
    path = candidates[0]
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def report(args: dict) -> dict:
    if not isinstance(args, dict) or set(args) != {"work_order_id", "message_utf8"}:
        raise ValueError("REPORT_SCHEMA_INVALID")
    work_order_id, message = args["work_order_id"], args["message_utf8"]
    active = workflow.active()
    if not isinstance(work_order_id, str) or not active or active.get("active_work_order_id") != work_order_id:
        raise ValueError("REPORT_WORK_ORDER_INVALID")
    if not isinstance(message, str) or not message.strip() or "\x00" in message or len(message.encode("utf-8")) > 16384:
        raise ValueError("REPORT_MESSAGE_INVALID")
    content = message.encode("utf-8")
    key = hashlib.sha256((work_order_id + "\x00").encode("utf-8") + content).hexdigest()
    request_dir = workflow.OUTBOX / f"MEPHC-REPORT-{key[:24]}"
    certificate, certificate_sha256 = _report_certificate()
    if not request_dir.is_dir():
        request_dir.mkdir(parents=True, mode=0o700)
        (request_dir / "message.txt").write_bytes(content)
        request = {
            "version": 1, "project_id": "MEPHC", "request_id": request_dir.name, "message_file": "message.txt",
            "attachments": [], "workflow_window_seconds": 600, "task_difficulty": "normal",
            "instruction_level": "normal", "relay_certificate": str(certificate), "report_request": True,
            "work_order_id": work_order_id, "report_idempotency_key": key,
        }
        temporary = request_dir / ".request.json.tmp"
        temporary.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(request_dir / "request.json")
    else:
        try:
            request = json.loads((request_dir / "request.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("REPORT_REQUEST_STATE_INVALID") from exc
        if request.get("report_idempotency_key") != key or request.get("attachments") != []:
            raise ValueError("REPORT_REQUEST_STATE_INVALID")
    receipt = request_dir / "receipt.json"
    recovery = False
    if receipt.is_file():
        try:
            state = json.loads(receipt.read_text(encoding="utf-8")).get("state")
        except (OSError, json.JSONDecodeError):
            state = None
        recovery = state in {"request_submitted", "waiting_for_response", "submission_unconfirmed", "chat_submission_unconfirmed", "submission_state_uncertain", "response_timeout", "response_protocol_error"}
    arguments = ["--request-directory", str(request_dir)]
    if recovery:
        arguments.append("--recovery-only")
    directory = jobctl.submit("courier", arguments, certificate_sha256)
    return {"job_id": directory.name, "state": "ready", "request_id": request_dir.name, "safe_next_tool": "mephc_wait"}


def transport_canary(args: dict) -> dict:
    if args:
        raise ValueError("TRANSPORT_CANARY_ACCEPTS_NO_ARGUMENTS")
    certificate, certificate_sha256 = _report_certificate()
    build_binding = hashlib.sha256((config.state_epoch() + "\x00" + jobctl.git_head()).encode("ascii")).hexdigest()
    request_dir = workflow.OUTBOX / f"MEPHC-INFRA-CANARY-{build_binding[:24].upper()}"
    message = ("MEPHC infrastructure transport canary. No scientific task or content. "
               f"CANARY_BINDING={build_binding}\nReply exactly: MEPHC_TRANSPORT_CANARY_OK={build_binding}\n")
    if not request_dir.exists():
        request_dir.mkdir(parents=True, mode=0o700)
        (request_dir / "message.txt").write_text(message, encoding="utf-8", newline="\n")
        request = {"version": 1, "project_id": "MEPHC", "request_id": request_dir.name,
                   "message_file": "message.txt", "attachments": [], "workflow_window_seconds": 600,
                   "task_difficulty": "normal", "instruction_level": "normal",
                   "relay_certificate": str(certificate), "transport_canary": True,
                   "transport_canary_idempotency_key": build_binding}
        temporary = request_dir / ".request.json.tmp"
        temporary.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(request_dir / "request.json")
    else:
        request = json.loads((request_dir / "request.json").read_text(encoding="utf-8"))
        if (request.get("transport_canary_idempotency_key") != build_binding
                or request.get("attachments") != []
                or (request_dir / "message.txt").read_text(encoding="utf-8") != message):
            raise ValueError("TRANSPORT_CANARY_STATE_INVALID")
    receipt = request_dir / "receipt.json"
    arguments = ["--request-directory", str(request_dir)]
    if receipt.is_file():
        receipt_state = json.loads(receipt.read_text(encoding="utf-8")).get("state")
        if receipt_state == "response_received":
            return {"request_id": request_dir.name, "state": "response_received", "reused": True}
        if receipt_state in {"request_submitted", "waiting_for_response", "submission_unconfirmed",
                             "chat_submission_unconfirmed", "submission_state_uncertain", "response_timeout",
                             "response_protocol_error"}:
            arguments.append("--recovery-only")
        else:
            raise ValueError("TRANSPORT_CANARY_HARD_STOP")
    directory = jobctl.submit("courier", arguments, certificate_sha256)
    return {"job_id": directory.name, "request_id": request_dir.name, "state": "ready",
            "safe_next_tool": "mephc_wait", "idempotency_key": build_binding}


def publish_latest_prelive():
    candidates = []
    for path in (config.STATE_ROOT / "prelive").glob("prelive-*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (record.get("kind") == "prelive-attestation"
                and record.get("test_returncode") == 0
                and record.get("prelive_sha") == jobctl.git_head()):
            candidates.append(path)
    if not candidates:
        raise RuntimeError("PUBLISH_PRELIVE_NOT_FOUND_FOR_CURRENT_HEAD")
    path = max(candidates, key=lambda value: value.stat().st_mtime_ns)
    directory = jobctl.submit("publish", ["--prelive", path.name, "--push"], None)
    return {"job_id": directory.name, "state": "ready", "prelive_id": path.name, "safe_next_tool": "mephc_wait"}


def captured(call):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        result = call()
    return {"return_code": result if isinstance(result, int) else 0, "events": [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]}


def invoke_captured(name, args):
    """Keep internal runner events out of the JSON-RPC transport stream."""
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        value = invoke(name, args)
    events = []
    other_output = []
    for line in stream.getvalue().splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            other_output.append(line)
    if not events and not other_output:
        return value
    result = dict(value) if isinstance(value, dict) else {"value": value}
    if events:
        result["runner_events"] = events
    if other_output:
        result["runner_stdout"] = other_output
    return result


def invoke(name, args):
    if name == "mephc_runtime_attest":
        return runtime_attestation.attest()
    if name == "mephc_work_order_preflight":
        return jobctl.work_order_preflight()
    if name in {"mephc_runtime_reload", "mephc_runtime_activate"}:
        return {"state":"rejected","error_code":"ADMISSION_LIFECYCLE_REQUIRED",
                "retry_allowed":False,"safe_next_tool":"mephc_runtime_attest"}
    if name == "mephc_capabilities":
        value = jobctl.capabilities()
        value["read_only_evidence"] = {"tool": "mephc_inspect", "operations": ["list", "read"], "tracked_only": True}
        value["release_protocol"] = {"publish_tool": "mephc_publish", "agent_supplies_prelive_path": False}
        return value
    if name == "mephc_inspect":
        return inspect(args)
    if name == "mephc_retention_inspect":
        try:
            return retention_inspector.inspect(args.get("job_id"), args.get("retention_id"),
                                               args.get("operation"), args.get("json_pointer", ""),
                                               args.get("offset", 0), args.get("limit", 200))
        except retention_inspector.RetentionError as exc:
            next_tool = ("mephc_retention_search" if exc.code in {
                         "RETENTION_SEARCH_JOB_NOT_FOUND", "RETENTION_SEARCH_JOB_INVALID"} else
                         "mephc_status" if exc.code in {"RETENTION_SEARCH_NOT_READY", "RETENTION_BYTE_DRIFT"} else
                         "mephc_retention_inspect")
            return {"state": "rejected", "error_code": exc.code, "detail": exc.detail,
                    "retry_allowed": False, "safe_next_tool": next_tool}
    if name == "mephc_report":
        return report(args)
    if name == "mephc_transport_canary":
        return transport_canary(args)
    if name == "mephc_publish":
        return publish_latest_prelive()
    if name == "mephc_resume":
        return workflow_resume.resume()
    if name == "mephc_doctor":
        value = jobctl.doctor_deduplicated()
        if value.get("job_created"):
            bind_admission(jobctl.JOBS / value["job_id"])
            return {**value, **captured(lambda: jobctl.wait(value["job_id"], 120))}
        return value
    if name == "mephc_change":
        try:
            directory = jobctl.submit_change(args)
        except jobctl.ChangeRejected as exc:
            return {"state": "rejected", "error_code": exc.error_code,
                    "noop_files": exc.noop_files, "job_created": False,
                    "retry_allowed": False, "safe_next_tool": exc.safe_next_tool}
        bind_admission(directory)
        return {"job_id": directory.name, "state": "ready", "job_created": True,
                "safe_next_tool": "mephc_wait"}
    if name == "mephc_validate":
        tests = args.get("tests") if isinstance(args, dict) else None
        if not isinstance(tests, list) or not tests:
            raise ValueError("VALIDATE_TESTS_REQUIRED")
        directory = jobctl.submit("prelive", tests, None)
        bind_admission(directory)
        return {"job_id": directory.name, "state": "ready", "job_created": True,
                "safe_next_tool": "mephc_wait"}
    if name == "mephc_retention_search":
        try:
            directory, reused = jobctl.submit_retention_search(args.get("bindings") if isinstance(args, dict) else None)
        except jobctl.RetentionRejected as exc:
            return {"state": "rejected", "error_code": exc.error_code, "job_created": False,
                    "retry_allowed": False, "safe_next_tool": exc.safe_next_tool}
        state = jobctl.read_basic_state(directory.name).get("state")
        if not reused: bind_admission(directory)
        has_result = (directory / "retention-search-result.json").is_file()
        return {"job_id": directory.name, "state": state, "job_created": not reused, "reused": reused,
                "safe_next_tool": "mephc_retention_inspect" if has_result else
                                  "mephc_recover" if state == "recovery_required" else
                                  "mephc_status" if state == "running" else "mephc_wait"}
    if name == "mephc_submit":
        directory = jobctl.submit(args["operation"], args.get("arguments", []), args.get("certificate_sha256"))
        bind_admission(directory)
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
                reply(identifier, {"protocolVersion": request.get("params", {}).get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}}, "serverInfo": {"name": "mephc-runner", "version": "4.0.0"}})
            elif method == "ping":
                reply(identifier, {})
            elif method == "tools/list":
                reply(identifier, {"tools": advertised_tools()})
            elif method == "tools/call":
                params = request.get("params", {})
                global CURRENT_ADMISSION_REQUEST_ID
                meta = params.get("_meta") if isinstance(params, dict) else None
                CURRENT_ADMISSION_REQUEST_ID = meta.get("mephc_admission_request_id") if isinstance(meta, dict) else None
                value = invoke_captured(params.get("name"), params.get("arguments") or {})
                reply(identifier, {"content": [{"type": "text", "text": json.dumps(value, sort_keys=True, ensure_ascii=False)}], "isError": False})
            elif identifier is not None:
                reply(identifier, error=f"unsupported method: {method}")
        except Exception as exc:
            if request.get("id") is not None:
                reply(request.get("id"), error=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
