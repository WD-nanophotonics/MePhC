#!/usr/bin/env python3
"""MePhC Thin Flow: one small, durable Git/WSL/Courier state machine.

Normal agents use exactly four commands: status, resume, execute, closeout.
The retired feature-rich coordinator is preserved under archive/ and is never
imported here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


PROJECT_ID = "MEPHC"
EXPECTED_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
CONTROL_ROOT = Path(r"C:\Users\icywo\PycharmProjects\MePhC-Windows")
CONTROL_ROOT_WSL = "/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows"
LEGACY_STATE_WSL = "/home/icy/.local/state/mephc-runner/MEPHC"
LEGACY_STATE_UNC = Path(r"\\wsl.localhost\Ubuntu\home\icy\.local\state\mephc-runner\MEPHC")
FLOW_STATE_WSL = LEGACY_STATE_WSL + "/flow"
FLOW_STATE_UNC = LEGACY_STATE_UNC / "flow"
SCIENCE_STATE_WSL = "/home/icy/.local/share/mephc-runtime/science"
SCIENCE_STATE_UNC = Path(r"\\wsl.localhost\Ubuntu\home\icy\.local\share\mephc-runtime\science")
OUTBOX_WSL = LEGACY_STATE_WSL + "/outbox"
OUTBOX_UNC = LEGACY_STATE_UNC / "outbox"
CHECKOUT_ROOT_WSL = "/home/icy/.cache/mephc-runner/checkouts"
GIT_CACHE_WSL = "/home/icy/.cache/mephc-runner/MEPHC.git"
CONDA_PYTHON_WSL = "/home/icy/miniconda3/envs/mp/bin/python"
COURIER = Path(r"C:\Users\icywo\PycharmProjects\GmailCourier\scripts\chat-courier.cmd")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
WORK_ORDER = re.compile(r"^MEPHC-[A-Z0-9][A-Z0-9._-]{7,159}$")
HARD_RECEIPTS = {"login_error", "target_error", "hard_error", "validation_failed", "request_rejected"}
TERMINAL_JOBS = {"succeeded", "failed", "blocked"}
TASK_DIFFICULTIES = {"normal", "hard", "challenge", "adaptive"}
INSTRUCTION_LEVELS = {"normal", "detailed", "manual_book", "adaptive"}
REPORT_POLICIES = {"adaptive", "per-work-order", "milestone", "final-only"}
HARD_INVARIANT_ERRORS = {
    "ACTIVE_RESPONSE_BINDING_INVALID", "ACTIVE_RESPONSE_SHA_MISMATCH",
    "ACTIVE_WORK_ORDER_UNAVAILABLE", "CONTROL_BRANCH_NOT_SANDBOX",
    "ORIGIN_MAIN_MOVED", "REMOTE_SANDBOX_MOVED", "SANDBOX_NOT_FAST_FORWARD",
    "SOURCE_COMMIT_INVALID", "WORK_ORDER_CONTRACT_ID_MISMATCH",
}


class FlowError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Paths:
    control: Path = CONTROL_ROOT
    state: Path = FLOW_STATE_UNC
    science_state: Path = SCIENCE_STATE_UNC
    outbox: Path = OUTBOX_UNC
    legacy_state: Path = LEGACY_STATE_UNC
    courier: Path = COURIER


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FlowError("STATE_JSON_INVALID", path.name) from exc


def run(argv: Sequence[str], *, cwd: Path | None = None, timeout: int = 600,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        raise FlowError("ARGV_INVALID")
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "GIT_EDITOR": "true"})
    try:
        result = subprocess.run(list(argv), cwd=cwd, env=env, text=True, encoding="utf-8",
                                errors="replace", capture_output=True, timeout=timeout,
                                creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise FlowError("COMMAND_TIMEOUT", " ".join(argv[:3])) from exc
    if check and result.returncode:
        raise FlowError("COMMAND_FAILED", (result.stderr or result.stdout)[-3000:])
    return result


def git(paths: Paths, *args: str, check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return run(["git", "-c", f"safe.directory={paths.control}", "-c", "commit.gpgsign=false",
                "-c", "core.autocrlf=true", "-C", str(paths.control), *args],
               check=check, timeout=timeout)


def wsl(argv: Sequence[str], *, cwd: str | None = None, check: bool = True,
        timeout: int = 600) -> subprocess.CompletedProcess[str]:
    prefix = ["wsl.exe", "-d", "Ubuntu"]
    if cwd:
        prefix += ["--cd", cwd]
    return run([*prefix, "--", *argv], check=check, timeout=timeout)


def source(paths: Paths) -> dict[str, Any]:
    return {
        "branch": git(paths, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip(),
        "head": git(paths, "rev-parse", "HEAD").stdout.strip(),
        "origin_main": git(paths, "rev-parse", "refs/remotes/origin/main").stdout.strip(),
        "origin_sandbox": git(paths, "rev-parse", "refs/remotes/origin/sandbox").stdout.strip(),
        "dirty": bool(git(paths, "status", "--porcelain", "--untracked-files=all").stdout.strip()),
    }


def require_source(paths: Paths, *, published: bool = False) -> dict[str, Any]:
    value = source(paths)
    if value["branch"] != "sandbox":
        raise FlowError("CONTROL_BRANCH_NOT_SANDBOX")
    if value["origin_main"] != EXPECTED_MAIN:
        raise FlowError("ORIGIN_MAIN_MOVED")
    if published and value["head"] != value["origin_sandbox"]:
        raise FlowError("SOURCE_NOT_PUBLISHED")
    return value


def remote_refs(paths: Paths) -> tuple[str, str]:
    result = git(paths, "ls-remote", "--heads", "origin", "main", "sandbox", timeout=120)
    refs = {line.split()[1]: line.split()[0] for line in result.stdout.splitlines() if len(line.split()) == 2}
    try:
        return refs["refs/heads/main"], refs["refs/heads/sandbox"]
    except KeyError as exc:
        raise FlowError("REMOTE_REFS_INCOMPLETE") from exc


def ensure_checkout(paths: Paths, commit: str) -> str:
    if not SHA40.fullmatch(commit):
        raise FlowError("SOURCE_COMMIT_INVALID")
    wsl(["/usr/bin/mkdir", "-p", CHECKOUT_ROOT_WSL, str(PurePosixPath(GIT_CACHE_WSL).parent)])
    if wsl(["/usr/bin/test", "-d", GIT_CACHE_WSL], check=False).returncode:
        wsl(["/usr/bin/git", "init", "--bare", GIT_CACHE_WSL])
    wsl(["/usr/bin/git", "-C", GIT_CACHE_WSL, "fetch", "--force", "--no-tags",
         f"{CONTROL_ROOT_WSL}/.git", commit])
    checkout = f"{CHECKOUT_ROOT_WSL}/{commit}"
    if wsl(["/usr/bin/test", "-d", checkout], check=False).returncode:
        wsl(["/usr/bin/git", "-C", GIT_CACHE_WSL, "worktree", "add", "--detach", checkout, commit])
    actual = wsl(["/usr/bin/git", "-C", checkout, "rev-parse", "HEAD"]).stdout.strip()
    dirty = wsl(["/usr/bin/git", "-C", checkout, "status", "--porcelain", "--untracked-files=all"]).stdout.strip()
    fstype = wsl(["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "--target", checkout]).stdout.strip().lower()
    if actual != commit or dirty:
        raise FlowError("EXECUTION_CHECKOUT_MISMATCH")
    if fstype in {"9p", "drvfs", "fuseblk", ""}:
        raise FlowError("EXECUTION_CHECKOUT_NOT_LINUX_NATIVE")
    return checkout


def ledger(paths: Paths) -> dict[str, Any]:
    value = read_json(paths.legacy_state / "runner" / "workflow-ledger.json", {})
    return value if isinstance(value, dict) else {}


def active_order(paths: Paths) -> dict[str, Any]:
    value = ledger(paths)
    if value.get("workflow_state") == "terminated":
        raise FlowError("WORKFLOW_TERMINATED")
    work_order_id = value.get("active_work_order_id")
    response_path = value.get("active_response_path")
    response_sha = value.get("active_response_sha256")
    if not isinstance(work_order_id, str) or not WORK_ORDER.fullmatch(work_order_id):
        raise FlowError("ACTIVE_WORK_ORDER_UNAVAILABLE")
    if not isinstance(response_path, str) or not response_path.startswith(OUTBOX_WSL + "/"):
        raise FlowError("ACTIVE_RESPONSE_BINDING_INVALID")
    relative = PurePosixPath(response_path).relative_to(PurePosixPath(LEGACY_STATE_WSL))
    local = paths.legacy_state.joinpath(*relative.parts)
    if not local.is_file() or not SHA64.fullmatch(str(response_sha)) or digest(local.read_bytes()) != response_sha:
        raise FlowError("ACTIVE_RESPONSE_SHA_MISMATCH")
    text = local.read_text(encoding="utf-8-sig")
    return {"work_order_id": work_order_id, "response_sha256": response_sha, "text": text}


def contract_from_text(text: str) -> dict[str, Any]:
    normalized = text.replace("\r\n", "\n")
    for line in normalized.splitlines():
        match = re.match(r"^WORK_ORDER_CONTRACT_JSON\s*[:=]\s*(\{.*\})\s*$", line)
        if match:
            try:
                value = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    for block in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", normalized, re.DOTALL | re.IGNORECASE):
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and ("work_order_id" in value or "WORK_ORDER_ID" in value):
            return value
    raise FlowError("WORK_ORDER_MACHINE_CONTRACT_REQUIRED")


def science_module(paths: Paths):
    path = paths.control / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_thin_science", path)
    if spec is None or spec.loader is None:
        raise FlowError("SCIENCE_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def native_helper_module(paths: Paths):
    module_path = paths.control / "tools" / "mephc-flow" / "wsl_native_exec.py"
    spec = importlib.util.spec_from_file_location("mephc_thin_native_helper", module_path)
    if spec is None or spec.loader is None: raise FlowError("NATIVE_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def active_contract(paths: Paths) -> tuple[dict[str, Any], dict[str, Any]]:
    order = active_order(paths)
    module = science_module(paths)
    try:
        contract = module.validate_contract(contract_from_text(order["text"]))
    except module.ScientificJobError as exc:
        raise FlowError(str(exc)) from exc
    if contract["work_order_id"] != order["work_order_id"]:
        raise FlowError("WORK_ORDER_CONTRACT_ID_MISMATCH")
    return order, contract


def request_summary(directory: Path) -> dict[str, Any]:
    request = read_json(directory / "request.json", {})
    receipt = read_json(directory / "receipt.json", {})
    events = directory / "events.jsonl"
    submissions = 0; captures = 0; total_submissions = 0
    if events.is_file():
        lines = events.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("event") == "target_rollover_authorized":
                submissions = 0
                captures = 0
            elif item.get("event") == "request_submitted":
                submissions += 1
                total_submissions += 1
            elif item.get("event") == "latest_response_captured":
                captures += 1
    capture = read_json(directory / "latest-response-capture.json", {})
    found_user = capture.get("latest_user_turn_found") if isinstance(capture, dict) else None
    found_reply = capture.get("post_submission_reply_found") if isinstance(capture, dict) else None
    response_path = directory / "response.txt"
    invalid_response_capture = False
    if response_path.is_file():
        try:
            response_text = response_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
            terminated = bool(re.search(r"^WORKFLOW_TERMINATED=true$", response_text, re.MULTILINE))
            successor_match = re.search(
                r"^NEXT_WORK_ORDER_ID=([^\n]+)$", response_text, re.MULTILINE
            )
            successor_valid = bool(
                successor_match
                and WORK_ORDER.fullmatch(successor_match.group(1).strip())
            )
            invalid_response_capture = not terminated and not successor_valid
        except OSError:
            invalid_response_capture = True
    response_received = response_path.is_file() and not invalid_response_capture
    if response_received:
        recovery_action = "none"
    elif submissions < 1 or captures < 1:
        recovery_action = "read"
    elif submissions == 1:
        recovery_action = "resend_once"
    else:
        recovery_action = "none"
    return {"request_id": request.get("request_id", directory.name),
            "receipt_state": receipt.get("state"), "submission_count": submissions,
            "total_submission_count": total_submissions,
            "response_received": response_received, "capture_attempt_count": captures,
            "latest_user_turn_found": found_user,
            "post_submission_reply_found": found_reply,
            "invalid_response_capture": invalid_response_capture,
            "recovery_action": recovery_action}


def request_for_work_order(paths: Paths, work_order_id: str) -> Path | None:
    request_id, _ = fixed_request_id(work_order_id)
    directory = paths.outbox / request_id
    if not directory.is_dir() or directory.is_symlink():
        return None
    request = read_json(directory / "request.json", {})
    if request.get("project_id") != PROJECT_ID or request.get("work_order_id") != work_order_id:
        raise FlowError("CLOSEOUT_REQUEST_BINDING_MISMATCH")
    return directory


def current_job(paths: Paths, work_order_id: str) -> dict[str, Any] | None:
    root = paths.state / "science-jobs"
    matches = []
    if root.is_dir():
        for path in root.glob("*.json"):
            value = read_json(path, {})
            if isinstance(value, dict) and value.get("work_order_id") == work_order_id:
                matches.append((path.stat().st_mtime_ns, value))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def actual_counts(job: dict[str, Any]) -> dict[str, int]:
    legacy = job.get("result") if isinstance(job.get("result"), dict) else {}
    native = job.get("actual_native_invocation_count")
    if native is None:
        native = 1 if legacy.get("process_started") is True else 0
    return {
        "native_invocation": int(native),
        "provider": int(job.get("actual_provider_execution_count",
                                legacy.get("actual_provider_execution_count", 0))),
        "solver": int(job.get("actual_solver_execution_count",
                              legacy.get("actual_solver_execution_count", 0))),
        "dataset": int(job.get("actual_dataset_record_count",
                               legacy.get("actual_dataset_record_count", 0))),
    }


def job_summary(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    counts = actual_counts(job)
    return {
        "job_id": job.get("job_id"), "work_order_id": job.get("work_order_id"),
        "action": job.get("action"), "terminal_state": job.get("state"),
        "source_commit": job.get("source_commit"), "native_run_id": job.get("native_run_id"),
        "failure_code": job.get("failure_code"),
        "contract_warnings": job.get("contract_warnings", []),
        "scope_warnings": job.get("scope_warnings", []),
        "result_warnings": job.get("result_warnings", []),
        "actual_native_invocation_count": counts["native_invocation"],
        "actual_provider_execution_count": counts["provider"],
        "actual_solver_execution_count": counts["solver"],
        "actual_dataset_record_count": counts["dataset"],
    }


def side_effect_evidence(paths: Paths, job: dict[str, Any] | None) -> dict[str, Any]:
    """Return the one authoritative answer to whether execute may be re-entered."""
    if not job:
        return {"side_effect_state": "NOT_STARTED", "execute_reentry_safe": True,
                "dispatch_reached": False, "process_started": False}
    if job.get("state") in TERMINAL_JOBS:
        return {"side_effect_state": "TERMINAL", "execute_reentry_safe": False,
                "dispatch_reached": bool(job.get("native_run_id")),
                "process_started": actual_counts(job)["native_invocation"] > 0}
    run_id = job.get("native_run_id")
    if not isinstance(run_id, str):
        return {"side_effect_state": "UNKNOWN", "execute_reentry_safe": False,
                "dispatch_reached": False, "process_started": False}
    run_record = read_json(paths.state / "native-runs" / f"{run_id}.json", None)
    if run_record is None:
        # execute writes the job before the run record and launches only after both.
        return {"side_effect_state": "DISPATCHING", "execute_reentry_safe": True,
                "dispatch_reached": False, "process_started": False}
    if not isinstance(run_record, dict) or run_record.get("run_id") != run_id:
        return {"side_effect_state": "UNKNOWN", "execute_reentry_safe": False,
                "dispatch_reached": True, "process_started": None}
    if run_record.get("state") in {"succeeded", "failed"}:
        phase = "TERMINAL"
    elif run_record.get("process_started") is True:
        phase = "STARTED"
    else:
        phase = "DISPATCHING"
    return {"side_effect_state": phase, "execute_reentry_safe": phase != "UNKNOWN",
            "dispatch_reached": True,
            "process_started": run_record.get("process_started") is True}


def state_view(paths: Paths) -> dict[str, Any]:
    source_value = source(paths)
    try:
        order = active_order(paths)
    except FlowError as exc:
        terminated = exc.code == "WORKFLOW_TERMINATED"
        return {"schema": "mephc-thin-flow-status-v1",
                "state": "TERMINATED" if terminated else "AWAITING_WORK_ORDER",
                "error_code": exc.code, "safe_next": None if terminated else "resume",
                "source": source_value}
    request = request_for_work_order(paths, order["work_order_id"])
    if request:
        summary = request_summary(request)
        if summary["receipt_state"] in HARD_RECEIPTS:
            state, safe_next = "HARD_BLOCKED", None
        elif summary["response_received"]:
            state, safe_next = "AWAITING_REPLY", "closeout"
        else:
            state, safe_next = "AWAITING_REPLY", "closeout"
        job = current_job(paths, order["work_order_id"])
        return {"schema": "mephc-thin-flow-status-v1", "state": state, "safe_next": safe_next,
                "work_order_id": order["work_order_id"], "source": source_value,
                "request": summary, "job": job_summary(job), **side_effect_evidence(paths, job)}
    job = current_job(paths, order["work_order_id"])
    if job and job.get("state") in TERMINAL_JOBS:
        state, safe_next = "READY_TO_CLOSE", "closeout"
    elif job:
        state, safe_next = "RUNNING", "execute"
    else:
        state, safe_next = "READY", "execute"
    return {"schema": "mephc-thin-flow-status-v1", "state": state, "safe_next": safe_next,
            "work_order_id": order["work_order_id"], "source": source_value, "job": job_summary(job),
            "request": None, **side_effect_evidence(paths, job)}


def successor_from_text(text: str, prior_work_order_id: str | None) -> str | None:
    normalized = text.replace("\r\n", "\n")
    match = re.search(r"^NEXT_WORK_ORDER_ID\s*[:=]\s*([^\n]+)$", normalized, re.MULTILINE)
    candidate = match.group(1).strip() if match else None
    if not candidate or not WORK_ORDER.fullmatch(candidate):
        try:
            contract = contract_from_text(normalized)
        except FlowError:
            contract = {}
        candidate = contract.get("work_order_id", contract.get("WORK_ORDER_ID"))
    if not isinstance(candidate, str) or not WORK_ORDER.fullmatch(candidate):
        return None
    return candidate if candidate != prior_work_order_id else None


def consume_response(paths: Paths, directory: Path) -> dict[str, Any]:
    response = directory / "response.txt"
    receipt = read_json(directory / "receipt.json", {})
    if receipt.get("state") != "response_received" or not response.is_file():
        raise FlowError("RESPONSE_NOT_RECEIPT_BOUND")
    text = response.read_text(encoding="utf-8-sig")
    if re.search(r"^WORKFLOW_TERMINATED=true$", text.replace("\r\n", "\n"), re.MULTILINE):
        atomic_json(paths.legacy_state / "runner" / "workflow-ledger.json", {
            "schema": "mephc-workflow-ledger-v2", "workflow_state": "terminated",
            "pending_job_id": None, "updated_at": time.time()})
        return {"state": "TERMINATED", "safe_next": None}
    request = read_json(directory / "request.json", {})
    successor = successor_from_text(text, request.get("work_order_id"))
    if successor is None:
        raise FlowError("RESPONSE_WORK_ORDER_ID_INVALID")
    response_sha = digest(response.read_bytes())
    atomic_json(paths.legacy_state / "runner" / "workflow-ledger.json", {
        "schema": "mephc-workflow-ledger-v2", "workflow_state": "available",
        "active_work_order_id": successor,
        "active_response_path": f"{OUTBOX_WSL}/{directory.name}/response.txt",
        "active_response_sha256": response_sha, "pending_job_id": None, "updated_at": time.time()})
    return {"state": "READY", "work_order_id": successor, "response_sha256": response_sha,
            "safe_next": "resume"}


def _captured_body(text: str) -> str:
    """Extract an optional Courier envelope without using it as authorization."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    begin, end = "BEGIN_RESPONSE", "END_RESPONSE"
    lines = normalized.split("\n")
    if begin in lines:
        start = lines.index(begin) + 1
        try:
            stop = lines.index(end, start)
        except ValueError:
            raise FlowError("CAPTURED_RESPONSE_INCOMPLETE")
        body = "\n".join(lines[start:stop]).strip()
        if not body:
            raise FlowError("CAPTURED_RESPONSE_EMPTY")
        return body
    if not normalized:
        raise FlowError("CAPTURED_RESPONSE_EMPTY")
    return normalized


def captured_response(paths: Paths, directory: Path) -> tuple[Path, str] | None:
    manifest = read_json(directory / "latest-response-capture.json", {})
    if not isinstance(manifest, dict) or manifest.get("post_submission_reply_found") is not True:
        return None
    name = manifest.get("raw_path")
    if not isinstance(name, str) or Path(name).name != name:
        raise FlowError("CAPTURED_RESPONSE_PATH_INVALID")
    path = directory / name
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FlowError("CAPTURED_RESPONSE_UNAVAILABLE") from exc
    if digest(raw) != manifest.get("raw_sha256"):
        raise FlowError("CAPTURED_RESPONSE_SHA_MISMATCH")
    return path, _captured_body(raw.decode("utf-8-sig"))


def consume_captured_response(paths: Paths, directory: Path) -> dict[str, Any] | None:
    captured = captured_response(paths, directory)
    if captured is None:
        return None
    raw_path, body = captured
    if re.search(r"^WORKFLOW_TERMINATED=true$", body, re.MULTILINE):
        atomic_json(paths.legacy_state / "runner" / "workflow-ledger.json", {
            "schema": "mephc-workflow-ledger-v2", "workflow_state": "terminated",
            "pending_job_id": None, "updated_at": time.time()})
        atomic_json(directory / "thin-captured-reply.json", {
            "schema": "mephc-thin-captured-reply-v1", "terminal": True,
            "raw_sha256": digest(raw_path.read_bytes()), "consumed_at": time.time()})
        return {"state": "TERMINATED", "safe_next": None}
    request = read_json(directory / "request.json", {})
    successor = successor_from_text(body, request.get("work_order_id"))
    if successor is None:
        return None
    response_sha = digest(raw_path.read_bytes())
    atomic_json(paths.legacy_state / "runner" / "workflow-ledger.json", {
        "schema": "mephc-workflow-ledger-v2", "workflow_state": "available",
        "active_work_order_id": successor,
        "active_response_path": f"{OUTBOX_WSL}/{directory.name}/{raw_path.name}",
        "active_response_sha256": response_sha, "pending_job_id": None,
        "updated_at": time.time()})
    atomic_json(directory / "thin-captured-reply.json", {
        "schema": "mephc-thin-captured-reply-v1", "terminal": False,
        "successor_work_order_id": successor, "raw_sha256": response_sha,
        "envelope_mismatch_tolerated": True,
        "capture_binding_warning": True, "consumed_at": time.time()})
    return {"state": "READY", "work_order_id": successor,
            "response_sha256": response_sha, "safe_next": "resume"}


def resume(paths: Paths) -> dict[str, Any]:
    view = state_view(paths)
    if view["state"] == "AWAITING_REPLY":
        directory = request_for_work_order(paths, view["work_order_id"])
        if directory and request_summary(directory)["response_received"]:
            return consume_response(paths, directory)
        return view
    if view["state"] == "HARD_BLOCKED":
        return view
    if view["state"] in {"AWAITING_WORK_ORDER", "TERMINATED"}:
        return view
    try:
        order, contract = active_contract(paths)
    except FlowError as exc:
        if exc.code.startswith("WORK_ORDER_"):
            order = active_order(paths)
            return pre_contract_block(paths, order, exc.code)
        raise
    try:
        validate_input_bindings(paths, contract)
    except FlowError as exc:
        return pre_execution_block(paths, contract, exc.code)
    return {"schema": "mephc-thin-flow-resume-v1", "state": "READY",
            "work_order_id": order["work_order_id"], "contract": contract,
            "safe_next": "execute"}


def dirty_paths(paths: Paths) -> list[str]:
    result = git(paths, "status", "--porcelain=v1", "--untracked-files=all")
    changed = []
    for line in result.stdout.splitlines():
        if len(line) < 4 or " -> " in line[3:]:
            raise FlowError("SCOPED_CHANGE_INVALID")
        changed.append(line[3:].replace("\\", "/"))
    return changed


def scoped_commit(paths: Paths, contract: dict[str, Any]) -> dict[str, Any] | None:
    changed = dirty_paths(paths)
    if not changed:
        return None
    allowed = set(contract["allowed_writes"])
    outside = sorted(set(changed) - allowed)
    git(paths, "add", "--", *sorted(changed))
    staged = git(paths, "diff", "--cached", "--name-only").stdout.splitlines()
    if set(staged) != set(changed):
        raise FlowError("SCOPED_STAGING_MISMATCH")
    git(paths, "commit", "-m", f"work-order({contract['work_order_id']}): scoped update")
    if dirty_paths(paths):
        raise FlowError("SCOPED_COMMIT_DIRTY")
    return {"changed_files": sorted(changed), "source_commit": git(paths, "rev-parse", "HEAD").stdout.strip(),
            "scope_warnings": [f"outside_declared_scope:{path}" for path in outside]}


def test_paths(contract: dict[str, Any]) -> list[str]:
    declared = contract["inputs"].get("tests")
    if declared is None: declared = [path for path in contract["allowed_writes"] if path.startswith("tests/") and path.endswith(".py")] or ["tests/test_mephc_thin_flow.py"]
    if not isinstance(declared, list) or not declared:
        raise FlowError("TESTS_REQUIRED")
    result = []
    for value in declared:
        candidate = PurePosixPath(str(value).replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts or candidate.parts[0] != "tests" or candidate.suffix != ".py":
            raise FlowError("TEST_PATH_INVALID", str(value))
        result.append(str(candidate))
    return result

def require_local_implementation(paths: Paths, contract: dict[str, Any]) -> None:
    """Keep missing implementation inputs in READY, before commit or durable jobs."""
    for relative in test_paths(contract):
        if not (paths.control / Path(relative)).is_file(): raise FlowError("TEST_IMPLEMENTATION_REQUIRED", relative)
    entrypoint = contract.get("entrypoint")
    if (contract.get("action") not in {"corrective", "infrastructure"}
            and (not isinstance(entrypoint, str) or not (paths.control / Path(entrypoint)).is_file())):
        raise FlowError("ENTRYPOINT_IMPLEMENTATION_REQUIRED", str(entrypoint))
    if contract.get("action") == "infrastructure":
        missing = next((path for path in contract["allowed_writes"] if not (paths.control / Path(path)).is_file()), None)
        if missing: raise FlowError("ARTIFACT_IMPLEMENTATION_REQUIRED", missing)


def publish(paths: Paths, contract: dict[str, Any]) -> dict[str, Any]:
    commit = scoped_commit(paths, contract)
    value = require_source(paths)
    if not git(paths, "merge-base", "--is-ancestor", contract["source_commit"], value["head"], check=False).returncode == 0:
        raise FlowError("WORK_ORDER_SOURCE_NOT_ANCESTOR")
    remote_main, remote_sandbox = remote_refs(paths)
    if remote_main != EXPECTED_MAIN:
        raise FlowError("ORIGIN_MAIN_MOVED")
    if remote_sandbox != value["origin_sandbox"]:
        raise FlowError("REMOTE_SANDBOX_MOVED")
    if git(paths, "merge-base", "--is-ancestor", remote_sandbox, value["head"], check=False).returncode:
        raise FlowError("SANDBOX_NOT_FAST_FORWARD")
    checkout = ensure_checkout(paths, value["head"])
    tests = test_paths(contract)
    tested = wsl([CONDA_PYTHON_WSL, "-m", "pytest", "-q", *tests], cwd=checkout,
                 timeout=3600, check=False)
    evidence = {"schema": "mephc-thin-publish-v1", "source_commit": value["head"],
                "tests": tests, "test_return_code": tested.returncode,
                "stdout_sha256": digest(tested.stdout.encode()), "stderr_sha256": digest(tested.stderr.encode()),
                "origin_main": remote_main, "prior_origin_sandbox": remote_sandbox,
                "created_at": time.time()}
    atomic_json(paths.state / "publish" / f"{value['head']}.json", evidence)
    if tested.returncode:
        raise FlowError("TESTS_FAILED", (tested.stdout + tested.stderr)[-3000:])
    if value["head"] != remote_sandbox:
        pushed = git(paths, "push", "origin", f"{value['head']}:refs/heads/sandbox", timeout=600, check=False)
        if pushed.returncode:
            raise FlowError("SANDBOX_PUSH_FAILED", (pushed.stderr or pushed.stdout)[-3000:])
        git(paths, "update-ref", "refs/remotes/origin/sandbox", value["head"])
    final_main, final_sandbox = remote_refs(paths)
    if final_main != EXPECTED_MAIN or final_sandbox != value["head"]:
        raise FlowError("REMOTE_VERIFICATION_FAILED")
    evidence.update({"published_at": time.time(), "published_sandbox": final_sandbox})
    atomic_json(paths.state / "publish" / f"{value['head']}.json", evidence)
    return {"source_commit": value["head"], "checkout": checkout, "tests": tests, "commit": commit}


def dataset_bindings(contract: dict[str, Any]) -> list[dict[str, str]]:
    values = contract["inputs"].get("datasets", [])
    if not isinstance(values, list):
        raise FlowError("DATASET_BINDINGS_INVALID")
    result = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {"dataset_id", "manifest_sha256", "record_key_sha256"}:
            raise FlowError("DATASET_BINDING_INVALID")
        if not all(SHA64.fullmatch(str(item[key])) for key in item):
            raise FlowError("DATASET_BINDING_INVALID")
        result.append({key: str(item[key]) for key in item})
    legacy_ids = [key for key in contract["inputs"] if key.endswith("dataset_id")]
    if legacy_ids and not result:
        raise FlowError("DATASET_BINDINGS_V2_REQUIRED")
    return result


def validate_input_bindings(paths: Paths, contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve every historical input before editing, publication or Native."""
    bindings = dataset_bindings(contract)
    if not bindings:
        return []
    module = science_module(paths)
    resolved = []
    for binding in bindings:
        try:
            record = module.resolve_dataset_record(paths.science_state, **binding)
        except module.ScientificJobError as exc:
            raise FlowError(str(exc)) from exc
        resolved.append({key: value for key, value in record.items() if key != "payload"})
    return resolved


def prepare_inputs(paths: Paths, contract: dict[str, Any], job_id: str) -> tuple[Path, str]:
    module = science_module(paths)
    resolved = []
    bundle = paths.science_state / "input-bundles" / job_id
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    for index, binding in enumerate(dataset_bindings(contract)):
        try:
            record = module.resolve_dataset_record(paths.science_state, **binding)
        except module.ScientificJobError as exc:
            raise FlowError(str(exc)) from exc
        payload = bundle / f"{index}.payload"
        atomic_bytes(payload, record.pop("payload"))
        resolved.append({**binding, **record, "payload_file": payload.name})
    value = {"schema": "mephc-thin-input-bundle-v1", "work_order_id": contract["work_order_id"],
             "contract_sha256": contract["contract_sha256"], "inputs": contract["inputs"],
             "datasets": resolved}
    atomic_json(bundle / "bundle.json", value)
    relative = bundle.relative_to(paths.science_state).as_posix()
    return bundle, f"{SCIENCE_STATE_WSL}/{relative}/bundle.json"


def job_id(contract: dict[str, Any], commit: str) -> str:
    return "MEPHC-SCIENCE-" + digest({"work_order_id": contract["work_order_id"],
                                      "contract_sha256": contract["contract_sha256"],
                                      "source_commit": commit, "action": contract["action"]})[:24]


def pre_execution_block(paths: Paths, contract: dict[str, Any], failure_code: str) -> dict[str, Any]:
    """Persist a zero-execution terminal result against the published source."""
    value = require_source(paths, published=True)
    identifier = job_id(contract, value["head"])
    final = {
        "schema": "mephc-thin-job-v1", "job_id": identifier,
        "work_order_id": contract["work_order_id"],
        "contract_sha256": contract["contract_sha256"],
        "source_commit": value["head"], "action": contract["action"],
        "state": "blocked", "failure_code": failure_code,
        "actual_native_invocation_count": 0,
        "actual_provider_execution_count": 0,
        "actual_solver_execution_count": 0,
        "actual_dataset_record_count": 0,
        "created_at": time.time(), "completed_at": time.time(),
    }
    atomic_json(paths.state / "science-jobs" / f"{identifier}.json", final)
    return execution_view(final)


def pre_contract_block(paths: Paths, order: dict[str, Any], failure_code: str) -> dict[str, Any]:
    """Turn a malformed Chat contract into a zero-execution clarification result."""
    value = require_source(paths, published=True)
    contract_hash = digest({"work_order_id": order["work_order_id"],
                            "response_sha256": order.get("response_sha256")})
    identifier = "MEPHC-SCIENCE-" + digest({"work_order_id": order["work_order_id"],
                                             "contract_sha256": contract_hash,
                                             "source_commit": value["head"],
                                             "action": "clarification"})[:24]
    final = {
        "schema": "mephc-thin-job-v1", "job_id": identifier,
        "work_order_id": order["work_order_id"], "contract_sha256": contract_hash,
        "source_commit": value["head"], "action": "clarification",
        "state": "blocked", "failure_code": failure_code,
        "contract_warnings": ["chat_contract_clarification_required"],
        "actual_native_invocation_count": 0, "actual_provider_execution_count": 0,
        "actual_solver_execution_count": 0, "actual_dataset_record_count": 0,
        "created_at": time.time(), "completed_at": time.time(),
    }
    atomic_json(paths.state / "science-jobs" / f"{identifier}.json", final)
    return execution_view(final)


def execution_view(job: dict[str, Any]) -> dict[str, Any]:
    terminal = job.get("state") in TERMINAL_JOBS
    return {"schema": "mephc-thin-flow-execute-v1",
            "state": "READY_TO_CLOSE" if terminal else "RUNNING",
            "safe_next": "closeout" if terminal else "execute",
            "execution": job_summary(job)}


def finish_native(paths: Paths, job: dict[str, Any], run_record: dict[str, Any]) -> dict[str, Any]:
    if run_record.get("state") not in {"succeeded", "failed"}:
        return execution_view(job)
    checkout = f"{CHECKOUT_ROOT_WSL}/{job['source_commit']}"
    dirty = wsl(["/usr/bin/git", "-C", checkout, "status", "--porcelain",
                 "--untracked-files=all"]).stdout.strip()
    state, failure = run_record.get("state", "failed"), run_record.get("result_error")
    summary = run_record.get("result_summary")
    if state == "succeeded" and isinstance(summary, dict):
        scientific_status = str(summary.get("scientific_acceptance_status", summary.get("status", ""))).upper()
        if scientific_status in {"BLOCKED", "HARD_BLOCKED"} or (scientific_status in {"FAIL", "FAILED", "FAIL_CLOSED"} and summary.get("failure_code")):
            state, failure = "failed", str(summary.get("failure_code") or f"SCIENTIFIC_RESULT_{scientific_status}")
    if dirty:
        state, failure = "failed", "EXECUTION_CHECKOUT_MUTATED"
    final = {
        **job, "state": state, "failure_code": failure,
        "actual_native_invocation_count": int(run_record.get("actual_native_invocation_count", 0)),
        "actual_provider_execution_count": int(run_record.get("actual_provider_execution_count", 0)),
        "actual_solver_execution_count": int(run_record.get("actual_solver_execution_count", 0)),
        "actual_dataset_record_count": int(run_record.get("actual_dataset_record_count", 0)),
        "result_summary": summary,
        "result_artifact": run_record.get("result_artifact"),
        "result_warnings": run_record.get("result_warnings", []),
        "completed_at": time.time(),
    }
    atomic_json(paths.state / "science-jobs" / f"{job['job_id']}.json", final)
    return execution_view(final)
def reconcile_oversized_result(paths: Paths, job: dict[str, Any]) -> dict[str, Any]:
    """Upgrade an old oversized-result failure without rerunning its child process."""
    if job.get("state") != "failed" or job.get("failure_code") != "RESULT_SUMMARY_OVERSIZED":
        return job
    run_id = job.get("native_run_id")
    if not isinstance(run_id, str):
        return job
    run_path = paths.state / "native-runs" / f"{run_id}.json"
    run_record = read_json(run_path, None)
    result_path = paths.science_state / "results" / f"{job['job_id']}.json"
    if not isinstance(run_record, dict) or run_record.get("result_error") != "RESULT_SUMMARY_OVERSIZED":
        return job
    try:
        expected = run_record.get("expected_output", {}).get("result_schema")
        summary, artifact, warnings = native_helper_module(paths).load_result(result_path, expected)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return job
    repaired_run = {**run_record, "state": "succeeded", "result_summary": summary,
                    "result_artifact": artifact, "result_warnings": warnings, "reconciled_without_execution": True}
    repaired_run.pop("result_error", None)
    repaired_job = {**job, "state": "succeeded", "failure_code": None, "result_summary": summary,
                    "result_artifact": artifact, "result_warnings": warnings, "reconciled_without_execution": True}
    for target, value in ((run_path, repaired_run),
                          (paths.state / "science-jobs" / f"{job['job_id']}.json", repaired_job)): atomic_json(target, value)
    return repaired_job
def native_record(job: dict[str, Any], contract: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {**job, "schema": "mephc-thin-native-run-v1", "run_id": run_id,
            "state": "dispatching", "process_started": False,
            "native_invocation_budget": contract["budgets"]["native_invocations"],
            "provider_request_budget": contract["budgets"]["provider_requests"],
            "solver_execution_budget": contract["budgets"]["solver_executions"],
            "science_contract_sha256": contract["contract_sha256"],
            "expected_output": contract["expected_output"]}


def launch_native(paths: Paths, contract: dict[str, Any], job: dict[str, Any],
                  checkout: str, bundle_wsl: str) -> dict[str, Any]:
    """Launch only after the deterministic job and run records both exist."""
    run_id = job["native_run_id"]
    run_path = paths.state / "native-runs" / f"{run_id}.json"
    helper = f"{checkout}/tools/mephc-flow/wsl_native_exec.py"
    result_wsl = f"{SCIENCE_STATE_WSL}/results/{job['job_id']}.json"
    launched = wsl([CONDA_PYTHON_WSL, helper, "--state", f"{FLOW_STATE_WSL}/native-runs/{run_id}.json",
                    "--checkout", checkout, "--project", checkout,
                    "--input-bundle", bundle_wsl, "--result-path", result_wsl,
                    "--", CONDA_PYTHON_WSL, "-B", contract["entrypoint"]],
                   timeout=7 * 24 * 3600, check=False)
    run_record = read_json(run_path, native_record(job, contract, run_id))
    run_record.setdefault("launcher_return_code", launched.returncode)
    return finish_native(paths, job, run_record)
def reconcile_running(paths: Paths, job: dict[str, Any]) -> dict[str, Any]:
    run_id = job.get("native_run_id")
    if not isinstance(run_id, str):
        raise FlowError("EXECUTION_STATE_INCOMPLETE")
    run_path = paths.state / "native-runs" / f"{run_id}.json"
    run_record = read_json(run_path, None)
    if run_record is None:
        # A missing run record proves launch was not reached: it is written before launch.
        _, contract = active_contract(paths)
        value = require_source(paths, published=True)
        if (job.get("work_order_id") != contract["work_order_id"]
                or job.get("job_id") != job_id(contract, job["source_commit"])
                or value["head"] != job.get("source_commit")):
            raise FlowError("EXECUTION_STATE_INCOMPLETE")
        checkout = ensure_checkout(paths, job["source_commit"])
        _, bundle_wsl = prepare_inputs(paths, contract, job["job_id"])
        atomic_json(run_path, native_record(job, contract, run_id))
        return launch_native(paths, contract, job, checkout, bundle_wsl)
    if not isinstance(run_record, dict) or run_record.get("run_id") != run_id:
        raise FlowError("NATIVE_RUN_STATE_UNAVAILABLE")
    return finish_native(paths, job, run_record)


def execute(paths: Paths) -> dict[str, Any]:
    view = state_view(paths)
    if view["state"] == "RUNNING":
        job = current_job(paths, view["work_order_id"])
        if not job:
            raise FlowError("EXECUTION_STATE_UNAVAILABLE")
        return reconcile_running(paths, job)
    if view["state"] != "READY":
        return view
    _, contract = active_contract(paths)
    require_local_implementation(paths, contract)
    try:
        validate_input_bindings(paths, contract)
    except FlowError as exc:
        return pre_execution_block(paths, contract, exc.code)
    publication = publish(paths, contract)
    identifier = job_id(contract, publication["source_commit"])
    job_path = paths.state / "science-jobs" / f"{identifier}.json"
    existing = read_json(job_path)
    if isinstance(existing, dict):
        return execution_view(existing)
    commit_evidence = publication.get("commit") or {}
    base = {"schema": "mephc-thin-job-v1", "job_id": identifier,
            "work_order_id": contract["work_order_id"], "contract_sha256": contract["contract_sha256"],
            "source_commit": publication["source_commit"], "action": contract["action"],
            "contract_warnings": contract.get("contract_warnings", []),
            "scope_warnings": commit_evidence.get("scope_warnings", []),
            "changed_files": commit_evidence.get("changed_files", []),
            "tests": publication.get("tests", []),
            "actual_native_invocation_count": 0, "actual_provider_execution_count": 0,
            "actual_solver_execution_count": 0, "actual_dataset_record_count": 0,
            "created_at": time.time()}
    try:
        _, bundle_wsl = prepare_inputs(paths, contract, identifier)
    except FlowError as exc:
        final = {**base, "state": "blocked", "failure_code": exc.code, "completed_at": time.time()}
        atomic_json(job_path, final)
        return execution_view(final)
    if contract["action"] in {"corrective", "infrastructure"}:
        final = {**base, "state": "succeeded", "completed_at": time.time(),
                 "result_summary": {"schema": contract["expected_output"]["result_schema"],
                                    "terminal": "COMPLETE"}}
        atomic_json(job_path, final)
        return execution_view(final)
    entrypoint = contract["entrypoint"]
    tracked = wsl(["/usr/bin/git", "-C", publication["checkout"], "ls-files",
                   "--error-unmatch", entrypoint], check=False)
    if tracked.returncode:
        final = {**base, "state": "blocked", "failure_code": "ENTRYPOINT_NOT_TRACKED",
                 "completed_at": time.time()}
        atomic_json(job_path, final)
        return execution_view(final)
    run_id = "MEPHC-NATIVE-" + digest({"job_id": identifier})[:24]
    run_path = paths.state / "native-runs" / f"{run_id}.json"
    job = {**base, "state": "running", "native_run_id": run_id}
    native = native_record(job, contract, run_id)
    atomic_json(job_path, job)
    atomic_json(run_path, native)
    return launch_native(paths, contract, job, publication["checkout"], bundle_wsl)


def fixed_request_id(work_order_id: str) -> tuple[str, str]:
    key = digest({"project_id": PROJECT_ID, "work_order_id": work_order_id,
                  "flow_schema": "mephc-fixed-closeout-v2"})
    return "MEPHC-FLOW-" + key[:24], key


def adaptive_query_preferences(contract: dict[str, Any] | None, job: dict[str, Any],
                               requested: dict[str, str | None]) -> dict[str, str]:
    declared = contract.get("query_preferences", {}) if isinstance(contract, dict) else {}
    work_order = str(job.get("work_order_id", "")).upper()
    action = str(job.get("action", "")).casefold()
    corrective = (action in {"corrective", "infrastructure"}
                  or any(word in work_order for word in ("CORRECTIVE", "DIAGNOSTIC", "RECERTIFICATION")))
    ambiguity = (job.get("state") == "blocked" and actual_counts(job)["native_invocation"] == 0)
    defaults = {
        "task_difficulty": "challenge" if corrective else "hard",
        "instruction_level": "manual_book" if corrective or ambiguity else "detailed",
        "report_policy": "milestone",
    }
    choices = {
        "task_difficulty": TASK_DIFFICULTIES,
        "instruction_level": INSTRUCTION_LEVELS,
        "report_policy": REPORT_POLICIES,
    }
    result = {}
    for name in choices:
        selected = requested.get(name)
        if selected in {None, "adaptive"}:
            selected = declared.get(name)
        if selected in {None, "adaptive"} or selected not in choices[name]:
            selected = defaults[name]
        result[name] = selected
    return result


def tracked_artifact_sha256(paths: Paths, source_commit: str, relative: str) -> str | None:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    argv = ["git", "-c", f"safe.directory={paths.control}", "-C", str(paths.control),
            "cat-file", "blob", f"{source_commit}:{relative}"]
    try:
        completed = subprocess.run(argv, capture_output=True, timeout=30,
                                   creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return hashlib.sha256(completed.stdout).hexdigest() if completed.returncode == 0 else None


def canonical_report(paths: Paths, order: dict[str, Any], job: dict[str, Any],
                     preferences: dict[str, str]) -> dict[str, Any]:
    request_id, key = fixed_request_id(order["work_order_id"])
    counts = actual_counts(job)
    kind = "complete" if job.get("state") == "succeeded" else "blocked"
    lines = ["MEPHC_THIN_FLOW_REPORT=true", f"WORK_ORDER_ID={order['work_order_id']}",
             f"REPORT_KIND={kind}", f"TERMINAL_STATE={job.get('state')}",
             f"SOURCE_COMMIT={job.get('source_commit')}", f"JOB_ID={job.get('job_id')}",
             f"NATIVE_INVOCATIONS={counts['native_invocation']}",
             f"PROVIDER_EXECUTIONS={counts['provider']}", f"SOLVER_EXECUTIONS={counts['solver']}",
             f"DATASET_RECORDS={counts['dataset']}"]
    if job.get("failure_code"):
        lines.append(f"BLOCKED_CODE={job['failure_code']}")
    if job.get("contract_warnings"):
        lines.append("CONTRACT_WARNINGS=" + ",".join(job["contract_warnings"]))
    if job.get("scope_warnings"):
        lines.append("SCOPE_WARNINGS=" + ",".join(job["scope_warnings"]))
    if job.get("result_warnings"):
        lines.append("RESULT_WARNINGS=" + ",".join(job["result_warnings"]))
    changed = [path for path in job.get("changed_files", []) if isinstance(path, str)][:16]
    tests = [path for path in job.get("tests", []) if isinstance(path, str)][:16]
    if changed:
        lines.append("CHANGED_FILES=" + ",".join(changed))
        artifacts = []
        for path in changed:
            value = tracked_artifact_sha256(paths, str(job.get("source_commit", "")), path)
            if value:
                artifacts.append(f"{path}:{value}")
        if artifacts:
            lines.append("ARTIFACT_SHA256=" + ",".join(artifacts))
    if tests:
        lines.extend(["TESTS=" + ",".join(tests), "TEST_RETURN_CODE=0"])
    summary = job.get("result_summary")
    if isinstance(summary, dict):
        for name, value in sorted(summary.items()):
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) and isinstance(value, (str, int, float, bool)):
                lines.append(f"RESULT_{name.upper()}={value}")
    message = ("\n".join(lines) + "\n").encode()
    retry_lines = [line for line in lines if not line.startswith("RESULT_")]
    retry_lines.extend(["REPORT_RETRY_COMPACT=true", f"FULL_REPORT_SHA256={digest(message)}"])
    retry_message = ("\n".join(retry_lines) + "\n").encode()
    return {"request_id": request_id, "request_hash": key, "work_order_id": order["work_order_id"],
            "kind": kind, "message": message, "message_sha256": digest(message),
            "retry_message": retry_message, "retry_message_sha256": digest(retry_message),
            **preferences}


def courier(paths: Paths, operation: str, directory: Path) -> subprocess.CompletedProcess[str]:
    if operation not in {"validate", "courier_dispatch", "courier_recover",
                          "courier_capture_latest", "courier_resend_once"}:
        raise FlowError("COURIER_OPERATION_INVALID")
    argv = ["cmd.exe", "/d", "/s", "/c", str(paths.courier), operation, str(directory)]
    return run(argv, timeout=4860, check=False)


def create_request(paths: Paths, report: dict[str, Any]) -> Path:
    directory = paths.outbox / report["request_id"]
    if directory.exists():
        return directory
    staging = paths.outbox / f".{report['request_id']}.{os.getpid()}.tmp"
    staging.mkdir(parents=True)
    atomic_bytes(staging / "message.txt", report["message"])
    atomic_bytes(staging / "retry-message.txt", report["retry_message"])
    atomic_json(staging / "request.json", {
        "version": 1, "project_id": PROJECT_ID, "request_id": report["request_id"],
        "message_file": "message.txt", "retry_message_file": "retry-message.txt",
        "attachments": [], "workflow_window_seconds": 600,
        "queue_wait_seconds": 3600, "task_difficulty": report["task_difficulty"],
        "instruction_level": report["instruction_level"], "report_policy": report["report_policy"],
        "flow_schema": "mephc-fixed-closeout-v2", "work_order_id": report["work_order_id"],
        "report_kind": report["kind"], "message_sha256": report["message_sha256"],
        "retry_message_sha256": report["retry_message_sha256"],
        "idempotency_key": report["request_hash"]})
    checked = courier(paths, "validate", staging)
    if checked.returncode:
        shutil.rmtree(staging, ignore_errors=True)
        raise FlowError("COURIER_VALIDATION_FAILED", (checked.stderr or checked.stdout)[-2000:])
    paths.outbox.mkdir(parents=True, exist_ok=True)
    os.replace(staging, directory)
    return directory


def closeout_once(paths: Paths, requested: dict[str, str | None] | None = None) -> dict[str, Any]:
    order = active_order(paths)
    directory = request_for_work_order(paths, order["work_order_id"])
    if directory is None:
        job = current_job(paths, order["work_order_id"])
        if not job or job.get("state") not in TERMINAL_JOBS:
            raise FlowError("TERMINAL_JOB_REQUIRED")
        job = reconcile_oversized_result(paths, job)
        try:
            _, contract = active_contract(paths)
        except FlowError:
            contract = None
        preferences = adaptive_query_preferences(contract, job, requested or {})
        directory = create_request(paths, canonical_report(paths, order, job, preferences))
    summary = request_summary(directory)
    if summary["receipt_state"] in HARD_RECEIPTS:
        return {"state": "HARD_BLOCKED", **summary, "safe_next": None}
    if summary["response_received"]:
        return consume_response(paths, directory)
    retry_path = directory / "thin-closeout.json"
    retry = read_json(retry_path, {})
    now = time.time()
    if isinstance(retry, dict) and now < float(retry.get("next_retry_at", 0)):
        return {"state": "AWAITING_REPLY", **summary, "next_retry_at": retry["next_retry_at"],
                "safe_next": "closeout"}
    operation = ("courier_recover" if summary["submission_count"] > 0
                 or summary["receipt_state"] is not None else "courier_dispatch")
    result = courier(paths, operation, directory)
    final = request_summary(directory)
    if final["response_received"]:
        return consume_response(paths, directory)
    # The regular recovery is the first read-only confirmation.  Re-open once
    # with the exact outbound user-turn marker and capture whatever Chat has
    # already completed, independent of its optional reply envelope.
    courier(paths, "courier_capture_latest", directory)
    final = request_summary(directory)
    consumed = consume_captured_response(paths, directory)
    if consumed is not None:
        return consumed
    # A duplicate Chat report is cheap and explicitly bounded.  Keep the same
    # request identity and permit exactly one second user turn.
    if final["submission_count"] == 1:
        courier(paths, "courier_resend_once", directory)
        final = request_summary(directory)
        if final["response_received"]:
            return consume_response(paths, directory)
        courier(paths, "courier_capture_latest", directory)
        final = request_summary(directory)
        consumed = consume_captured_response(paths, directory)
        if consumed is not None:
            return consumed
    if final["submission_count"] >= 2:
        return {"state": "HARD_BLOCKED", **final,
                "error_code": "COURIER_BOUNDED_RECOVERY_EXHAUSTED", "safe_next": None}
    attempt = int(retry.get("attempt", 0)) + 1 if isinstance(retry, dict) else 1
    delay = min(900, 30 * (2 ** min(attempt - 1, 5)))
    atomic_json(retry_path, {"schema": "mephc-thin-closeout-wait-v1", "attempt": attempt,
                             "last_attempt_at": now, "next_retry_at": now + delay,
                             "return_code": result.returncode})
    return {"state": "AWAITING_REPLY", **final, "next_retry_at": now + delay,
            "safe_next": "closeout"}


def closeout(paths: Paths, requested: dict[str, str | None] | None = None) -> dict[str, Any]:
    """Run one bounded recovery ladder for the fixed request."""
    return closeout_once(paths, requested)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="mephc-flow")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("status", "resume", "execute"):
        commands.add_parser(name)
    closeout_command = commands.add_parser("closeout")
    closeout_command.add_argument("--task-difficulty", choices=sorted(TASK_DIFFICULTIES))
    closeout_command.add_argument("--instruction-level", choices=sorted(INSTRUCTION_LEVELS))
    closeout_command.add_argument("--report-policy", choices=sorted(REPORT_POLICIES))
    return result
def command_error_view(paths: Paths, command: str, exc: FlowError) -> dict[str, Any]:
    """Classify errors by durable evidence instead of by an agent's guess."""
    hard = {"state": "HARD_BLOCKED", "error_code": exc.code,
            "detail": exc.detail, "safe_next": None,
            "side_effect_state": "UNKNOWN", "execute_reentry_safe": False}
    if command != "execute" or exc.code in HARD_INVARIANT_ERRORS:
        return hard
    try:
        view = state_view(paths)
    except FlowError:
        return hard
    state = view.get("state")
    phase = view.get("side_effect_state")
    if state == "READY" and phase == "NOT_STARTED":
        return {**view, "error_code": exc.code, "detail": exc.detail,
                "failure_class": "LOCAL_IMPLEMENTATION_OR_TRANSIENT",
                "native_started": False, "safe_next": "execute"}
    if state == "RUNNING" and phase in {"DISPATCHING", "STARTED"}:
        return {**view, "error_code": exc.code, "detail": exc.detail,
                "failure_class": "DURABLE_RECONCILIATION", "safe_next": "execute"}
    if state == "READY_TO_CLOSE" and phase == "TERMINAL":
        return {**view, "error_code": exc.code, "detail": exc.detail}
    return hard
def main(argv: list[str] | None = None, paths: Paths | None = None) -> int:
    args = parser().parse_args(argv)
    scope = paths or Paths()
    try:
        if args.command == "closeout":
            value = closeout(scope, {"task_difficulty": args.task_difficulty,
                                     "instruction_level": args.instruction_level,
                                     "report_policy": args.report_policy})
        else:
            value = {"status": state_view, "resume": resume,
                     "execute": execute}[args.command](scope)
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if value.get("state") not in {"HARD_BLOCKED"} else 2
    except FlowError as exc:
        value = command_error_view(scope, args.command, exc)
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return 2 if value.get("state") == "HARD_BLOCKED" else 0
if __name__ == "__main__":
    raise SystemExit(main())
