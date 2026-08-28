#!/home/icy/miniconda3/envs/mp/bin/python
"""Fail-closed persistent WSL worker for MePhC relayctl jobs."""

from __future__ import annotations

try:
    import fcntl
except ModuleNotFoundError:  # Import-only support for Windows infrastructure tests.
    class _Fcntl:
        LOCK_EX = LOCK_NB = 0
        @staticmethod
        def flock(*_args): return None
    fcntl = _Fcntl()
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

INSTALL_ROOT = Path(__file__).resolve().parent
if str(INSTALL_ROOT) not in sys.path: sys.path.insert(0, str(INSTALL_ROOT))
import checkout_manager
import runtime_config as config
import active_index
import workflow
import job_semantics
import runtime_attestation
import work_order_contract
import admission_requests

ROOT = config.CONTROL_ROOT
PYTHON = config.PYTHON
RELAYCTL = ROOT / "scripts" / "relayctl"
RUNTIME = config.RUNTIME
JOBS = RUNTIME / "jobs"
CERTIFICATES = config.CERTIFICATES
NATIVE_RECIPES = INSTALL_ROOT / "native-recipes.json"
MATERIALIZE_CLIENT = INSTALL_ROOT / "materialize_client.py"
MATERIALIZER = INSTALL_ROOT / "materializer.py"
RETENTION_INSPECTOR = INSTALL_ROOT / "retention_inspector.py"
OPERATIONS = {"doctor", "worktree", "prelive", "native", "publish", "courier", "change", "retention_search"}
JOB_ID = re.compile(r"^MEPHC-JOB-[A-Z0-9][A-Z0-9._-]{7,119}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
RECOVERABLE = {"response_timeout", "courier_interrupted", "chat_submission_unconfirmed", "submission_state_uncertain"}
FORBIDDEN_FLAGS = {"--root", "--python", "--pythonpath", "--project-id", "--courier-root", "--profile", "--chat-url", "--certificate"}
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_DETAIL_CHARS = 2000
LOADED_WORKER_MODULE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
WORKER_START_ID = uuid.uuid4().hex
WORKER_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
_SOURCE_RUNTIME_MATCH_CACHE: tuple[str, bool] | None = None
_SOURCE_RUNTIME_MISMATCH: dict[str, Any] | None = None


class Rejected(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical(value: dict[str, Any]) -> bytes:
    payload = {key: item for key, item in value.items() if key != "payload_sha256"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def event(job_dir: Path, name: str, **fields: Any) -> None:
    record = {"event": name, "timestamp": now(), **fields}
    with (job_dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def state(job_dir: Path, name: str, **fields: Any) -> None:
    operation = fields.get("operation")
    if not isinstance(operation, str):
        try:
            operation = json.loads((job_dir / "job.json").read_text(encoding="utf-8")).get("operation")
        except (OSError, json.JSONDecodeError):
            operation = None
    semantics = job_semantics.enrich(name, operation, fields.get("error_code"), fields.get("phase"))
    atomic_json(job_dir / "state.json", {"state": name, "updated_at": now(), **semantics, **fields})
    active_index.update(RUNTIME, job_dir.name, name, operation)


def read_object(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        if size > MAX_JSON_BYTES:
            raise Rejected("JOB_JSON_TOO_LARGE", f"{path}: size={size} max={MAX_JSON_BYTES}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except Rejected:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejected("JOB_JSON_INVALID", f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Rejected("JOB_JSON_INVALID", f"{path}: object required")
    return value


def bounded_detail(value: object) -> str:
    text = str(value)
    if len(text) <= MAX_DETAIL_CHARS:
        return text
    return f"{text[:MAX_DETAIL_CHARS]}...[truncated; original_chars={len(text)}]"


def git(*arguments: str, root: Path | None = None) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(root or ROOT), *arguments],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise Rejected("GIT_CHECK_FAILED", completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def certificate_path(digest: str) -> Path:
    matches: list[Path] = []
    if not CERTIFICATES.is_dir():
        raise Rejected("CERTIFICATE_INVALID", "certificate directory missing")
    for path in sorted(CERTIFICATES.glob("*.json")):
        try:
            if (
                path.is_file() and not path.is_symlink()
                and hashlib.sha256(path.read_bytes()).hexdigest() == digest
            ):
                matches.append(path.resolve())
        except OSError:
            continue
    if len(matches) != 1:
        raise Rejected("CERTIFICATE_INVALID", f"certificate SHA matches={len(matches)}")
    return matches[0]
def verify_courier_binding(job: dict[str, Any]) -> None:
    binding = job.get("courier_binding"); request_dir = Path(job["arguments"][1]); request_path = request_dir / "request.json"; request = read_object(request_path)
    message = request_dir / request.get("message_file", ""); certificate = Path(request.get("relay_certificate", ""))
    actual = {"request_id":str(request.get("request_id", "")), "request_sha256":hashlib.sha256(request_path.read_bytes()).hexdigest(), "message_sha256":hashlib.sha256(message.read_bytes()).hexdigest(), "certificate_sha256":hashlib.sha256(certificate.read_bytes()).hexdigest()}
    if binding != actual or request.get("attachments") != []:
        raise Rejected("COURIER_REQUEST_MUTATED", f"expected={binding} actual={actual}")


def recovery_arguments(job: dict[str, Any], attempt: int) -> list[str]:
    arguments = list(job["arguments"]); receipt = read_object(Path(arguments[1]) / "receipt.json"); value = receipt.get("state")
    if value == "courier_interrupted" and receipt.get("interruption_stage") == "pre_browser":
        if attempt > 2:
            raise Rejected("COURIER_PRE_BROWSER_RETRY_EXHAUSTED", job["job_id"])
        return arguments
    submitted = {"request_submitted", "waiting_for_response", "submission_unconfirmed", "chat_submission_unconfirmed", "submission_state_uncertain", "response_timeout", "response_protocol_error", "response_received"}
    if value in submitted:
        return arguments if arguments[-1:] == ["--recovery-only"] else [*arguments, "--recovery-only"]
    raise Rejected("COURIER_RECOVERY_NOT_ALLOWED", repr(value))




def command_for(job: dict[str, Any], execution_root: Path | None = None, recovery: bool = False, attempt: int = 1) -> list[str]:
    execution_root = execution_root or ROOT
    relayctl = execution_root / "scripts" / "relayctl"
    if job["operation"] == "prelive":
        return [str(relayctl), "prelive", "--certificate",
                str(certificate_path(job["certificate_sha256"])), *job["arguments"]]
    if job["operation"] == "courier":
        if recovery:
            return [str(relayctl), "courier", *recovery_arguments(job, attempt)]
        if job["arguments"] in (["--create-e2e"], ["--create-attachment-e2e"], ["--create-status"]):
            return [str(relayctl), "courier", job["arguments"][0], "--certificate",
                    str(certificate_path(job["certificate_sha256"]))]
    if job["operation"] == "change":
        mode = "recover" if recovery else "transact"
        return [str(PYTHON), str(MATERIALIZE_CLIENT), mode, str(JOBS / job["job_id"])]
    if job["operation"] == "retention_search":
        return [str(PYTHON), str(RETENTION_INSPECTOR), "search", str(JOBS / job["job_id"]),
                str(execution_root)]
    if job["operation"] == "native":
        recipe_id = job["native_binding"]["recipe_id"]
        recipe = read_object(NATIVE_RECIPES).get("recipes", {}).get(recipe_id)
        if not isinstance(recipe, dict) or set(recipe) != {"argv"} or not isinstance(recipe.get("argv"), list):
            raise Rejected("NATIVE_RECIPE_INVALID", recipe_id)
        argv = recipe["argv"]
        if not argv or not all(isinstance(value, str) and value and "\x00" not in value for value in argv):
            raise Rejected("NATIVE_RECIPE_INVALID", recipe_id)
        prelive = config.STATE_ROOT / "prelive" / job["native_binding"]["prelive_id"]
        return [str(relayctl), "native", "--prelive", str(prelive), "--", *argv]
    return [str(relayctl), job["operation"], *job["arguments"]]
def inside(path: Path, parent: Path, code: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(parent.resolve())
    except ValueError as exc:
        raise Rejected(code, f"{resolved} is outside {parent}") from exc
    return resolved


def expected_head_for_job(job: dict[str, Any], modern: bool) -> str:
    key = "source_commit" if modern else "expected_head"
    if key not in job:
        raise Rejected("RUNNER_CONTRACT_EXPECTED_HEAD_MISSING", key)
    value = job.get(key)
    if not isinstance(value, str) or not SHA40.fullmatch(value):
        raise Rejected("RUNNER_CONTRACT_EXPECTED_HEAD_INVALID", key)
    return value


def verify_expected_head(job: dict[str, Any], actual_head: str, modern: bool) -> str:
    expected_head = expected_head_for_job(job, modern)
    if actual_head != expected_head:
        raise Rejected("HEAD_MOVED", f"expected={expected_head} actual={actual_head}")
    return expected_head


def validate(job_dir: Path, recovery: bool = False) -> tuple[dict[str, Any], str, Path]:
    if not (job_dir / "READY").is_file():
        raise Rejected("JOB_NOT_READY", str(job_dir))
    raw = (job_dir / "job.json").read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    job = read_object(job_dir / "job.json")
    v2 = job.get("schema") == "mephc-runner-job-v2"
    v3 = job.get("schema") == "mephc-runner-job-v3"
    v4 = job.get("schema") == "mephc-runner-job-v4"
    modern = v2 or v3 or v4
    expected_head_for_job(job, modern)
    required = ({"schema", "job_id", "project_id", "operation", "arguments",
                 "expected_control_root", "source_commit", "expected_origin_main", "state_epoch",
                 "certificate_sha256", "created_at", "payload_sha256"} if modern else {
                 "schema", "job_id", "project_id", "operation", "arguments", "expected_root",
                 "expected_head", "certificate_sha256", "created_at", "payload_sha256"})
    if job.get("operation") == "change":
        required.add("change")
    if job.get("operation") == "courier" and job.get("arguments", [])[:1] == ["--request-directory"]:
        required.add("courier_binding")
    if v3:
        required.update({"retention_query", "active_work_order_id", "query_sha256", "runner_build"})
    if v4:
        required.add("admission_request_id")
        if job.get("operation") == "retention_search":
            required.update({"retention_query", "active_work_order_id", "query_sha256", "runner_build"})
        if job.get("operation") == "native":
            required.update({"active_work_order_id", "work_order_contract_sha256", "native_binding"})
    if set(job) != required or job.get("schema") not in {"mephc-runner-job-v1", "mephc-runner-job-v2", "mephc-runner-job-v3", "mephc-runner-job-v4"}:
        raise Rejected("JOB_SCHEMA_MISMATCH", f"keys={sorted(job)}")
    if not isinstance(job.get("job_id"), str) or not JOB_ID.fullmatch(job["job_id"]):
        raise Rejected("JOB_ID_INVALID", repr(job.get("job_id")))
    if job_dir.name != job["job_id"]:
        raise Rejected("JOB_DIRECTORY_MISMATCH", f"{job_dir.name} != {job['job_id']}")
    if job.get("project_id") != "MEPHC":
        raise Rejected("PROJECT_MISMATCH", repr(job.get("project_id")))
    if job.get("operation") not in OPERATIONS:
        raise Rejected("OPERATION_NOT_ALLOWED", repr(job.get("operation")))
    expected = hashlib.sha256(canonical(job)).hexdigest()
    if job.get("payload_sha256") != expected:
        raise Rejected("PAYLOAD_SHA256_MISMATCH", f"expected={expected}")
    if modern:
        if job.get("expected_control_root") != config.CONTROL_ROOT_WINDOWS:
            raise Rejected("CONTROL_ROOT_MISMATCH", repr(job.get("expected_control_root")))
        if job.get("expected_origin_main") != config.EXPECTED_ORIGIN_MAIN:
            raise Rejected("MAIN_MOVED", repr(job.get("expected_origin_main")))
        if job.get("state_epoch") != config.state_epoch():
            raise Rejected("STATE_EPOCH_MISMATCH", repr(job.get("state_epoch")))
        if not isinstance(job.get("source_commit"), str) or not SHA40.fullmatch(job["source_commit"]):
            raise Rejected("SOURCE_COMMIT_INVALID", repr(job.get("source_commit")))
        try:
            execution_root = checkout_manager.ensure(job["source_commit"])
        except checkout_manager.CheckoutError as exc:
            raise Rejected("EXECUTION_CHECKOUT_INVALID", str(exc)) from exc
    else:
        legacy_root = Path("/home/icy/MePhC")
        if not (legacy_root / ".git").is_dir():
            raise Rejected("LEGACY_ARCHIVED_RECOVERY_UNAVAILABLE", job.get("job_id", ""))
        if job.get("expected_root") != str(legacy_root):
            raise Rejected("ROOT_MISMATCH", repr(job.get("expected_root")))
        if not isinstance(job.get("expected_head"), str) or not SHA40.fullmatch(job["expected_head"]):
            raise Rejected("EXPECTED_HEAD_INVALID", repr(job.get("expected_head")))
        execution_root = legacy_root
    arguments = job.get("arguments")
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise Rejected("ARGUMENTS_INVALID", "array of strings required")
    if any(any(marker in value for marker in ("\x00", "\r", "\n")) for value in arguments):
        raise Rejected("ARGUMENTS_INVALID", "control characters forbidden")
    if any(value.lower() in FORBIDDEN_FLAGS for value in arguments):
        raise Rejected("ARGUMENT_OVERRIDE_FORBIDDEN", repr(arguments))
    if job["operation"] == "prelive":
        for target in arguments:
            file_part = target.split("::", 1)[0]
            relative = Path(file_part)
            if (target.startswith("-") or relative.is_absolute() or ".." in relative.parts
                    or relative.parts[:1] != ("tests",) or relative.suffix != ".py"
                    or not (execution_root / relative).is_file()):
                raise Rejected("PRELIVE_ARGUMENTS_INVALID", target)
    if not modern and not recovery:
        raise Rejected("LEGACY_JOB_RECOVERY_ONLY", job.get("job_id", ""))

    certificate = job.get("certificate_sha256")
    if job["operation"] == "doctor":
        if arguments or certificate != "":
            raise Rejected("DOCTOR_JOB_INVALID", "doctor accepts no arguments or certificate")
    elif not isinstance(certificate, str) or not SHA64.fullmatch(certificate):
        raise Rejected("CERTIFICATE_INVALID", repr(certificate))
    else:
        certificate_path(certificate)

    if job["operation"] == "change" and (arguments or not isinstance(job.get("change"), dict)):
        raise Rejected("CHANGE_JOB_INVALID", "typed change payload required")
    if job["operation"] == "retention_search":
        query = job.get("retention_query")
        active = workflow.active()
        try:
            active_contract_sha = work_order_contract.parse(
                active.get("work_order_text", "") if active else "", job.get("active_work_order_id")
            )["contract_sha256"]
        except (work_order_contract.ContractError, TypeError) as exc:
            raise Rejected("RUNNER_CONTRACT_WORK_ORDER_INVALID", str(exc)) from exc
        if (not (v3 or v4) or arguments or not isinstance(query, dict)
                or set(query) != {"bindings", "deadline_seconds", "work_order_id", "work_order_contract_sha256", "runner_build"}
                or query.get("work_order_id") != job.get("active_work_order_id")
                or query.get("runner_build") != job.get("runner_build")
                or job.get("runner_build") != runner_build_id()
                or not active or active.get("active_work_order_id") != job.get("active_work_order_id")
                or active_contract_sha != query.get("work_order_contract_sha256")
                or hashlib.sha256(json.dumps(query, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=False).encode("utf-8")).hexdigest() != job.get("query_sha256")):
            raise Rejected("RETENTION_QUERY_INVALID", "query/work-order binding mismatch")
    if job["operation"] == "native":
        if len(arguments) != 2 or arguments[0] != "--recipe":
            raise Rejected("NATIVE_RECIPE_INVALID", repr(arguments))
        registry_recipe = read_object(NATIVE_RECIPES).get("recipes", {}).get(arguments[1])
        if registry_recipe is None:
            raise Rejected("NATIVE_RECIPE_INVALID", arguments[1])
        binding = job.get("native_binding")
        active = workflow.active()
        if (not v4 or not isinstance(binding, dict)
                or binding.get("recipe_id") != arguments[1]
                or not active or active.get("active_work_order_id") != job.get("active_work_order_id")):
            raise Rejected("NATIVE_WORK_ORDER_BINDING_INVALID", arguments[1])
        try:
            contract = work_order_contract.parse(active["work_order_text"], active["active_work_order_id"])
        except (work_order_contract.ContractError, KeyError, TypeError) as exc:
            raise Rejected("NATIVE_WORK_ORDER_BINDING_INVALID", str(exc)) from exc
        declared = next((item for item in contract.get("native_recipes", [])
                         if item.get("recipe_id") == arguments[1]), None)
        registry_digest = hashlib.sha256(json.dumps(registry_recipe, sort_keys=True, separators=(",", ":"),
                                                       ensure_ascii=False).encode("utf-8")).hexdigest()
        if (contract.get("contract_sha256") != job.get("work_order_contract_sha256")
                or not declared or binding.get("recipe_sha256") != declared.get("recipe_sha256")
                or binding.get("max_invocations") != declared.get("max_invocations")
                or binding.get("registered_recipe_sha256") != registry_digest
                or registry_digest != declared.get("recipe_sha256")
                or binding.get("prelive_source_commit") != job.get("source_commit")):
            raise Rejected("NATIVE_WORK_ORDER_BINDING_INVALID", arguments[1])

    if job["operation"] == "courier":
        if arguments in (["--create-e2e"], ["--create-attachment-e2e"], ["--create-status"]):
            pass
        elif not ((len(arguments) == 2 and arguments[0] == "--request-directory")
                  or (len(arguments) == 3 and arguments[0] == "--request-directory"
                      and arguments[2] == "--recovery-only")):
            raise Rejected("COURIER_ARGUMENTS_INVALID", repr(arguments))
        else:
            outbox = config.OUTBOX if modern else Path("/home/icy/MePhC/.relayctl/outbox")
            request_dir = inside(Path(arguments[1]), outbox, "COURIER_REQUEST_OUTSIDE_OUTBOX")
            request = read_object(request_dir / "request.json")
            if request.get("project_id") != "MEPHC":
                raise Rejected("PROJECT_MISMATCH", f"request={request_dir}")
            verify_courier_binding(job)

    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise Rejected("INTERPRETER_MISMATCH", sys.executable)
    actual_head = git("rev-parse", "HEAD", root=execution_root)
    expected_head = expected_head_for_job(job, modern)
    if actual_head != expected_head and not (recovery and job["operation"] == "change"):
        raise Rejected("HEAD_MOVED", f"expected={expected_head} actual={actual_head}")
    return job, raw_sha, execution_root


def receipt_state(job: dict[str, Any]) -> str | None:
    if job["operation"] != "courier":
        return None
    if job["arguments"] in (["--create-e2e"], ["--create-status"]):
        return None
    path = Path(job["arguments"][1]) / "receipt.json"
    if not path.is_file():
        return None
    try:
        record = read_object(path)
    except Rejected:
        return None
    value = record.get("state")
    return value if isinstance(value, str) else None


def failure_detail(job_dir: Path) -> str:
    """Return a bounded, structured-safe diagnostic for a failed child process."""
    materializer_state = next((path for path in (job_dir / "materializer-recovery-state.json",
                                                  job_dir / "materializer-state.json") if path.is_file()), None)
    if materializer_state is not None:
        try:
            record = read_object(materializer_state)
            code = record.get("error_code")
            detail = record.get("detail")
            if isinstance(code, str):
                return f"{code}: {detail}"[-2000:] if isinstance(detail, str) else code
        except Rejected:
            return "MATERIALIZER_STATE_INVALID"
    log = job_dir / "process.log"
    if not log.is_file():
        return "PROCESS_LOG_UNAVAILABLE"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "PROCESS_LOG_UNREADABLE"
    tail = "\n".join(lines[-24:]).strip()
    return tail[-2000:] if tail else "PROCESS_LOG_EMPTY"


def relay_failure_code(job_dir: Path) -> str | None:
    allowed = {"CERTIFICATE_ENVIRONMENT_MISMATCH", "CERTIFICATE_EXECUTION_BINDING_MISMATCH"}
    try:
        for line in reversed((job_dir / "process.log").read_text(encoding="utf-8", errors="replace").splitlines()[-24:]):
            value = json.loads(line)
            if isinstance(value, dict) and value.get("event") in allowed:
                return value["event"]
    except (OSError, json.JSONDecodeError):
        return None
    return None


def execute(job_dir: Path, recovery: bool = False) -> None:
    # A recovery marker authorizes one reconciliation attempt, never a replay
    # loop. Consume it before any parsing/validation that can fail.
    if recovery:
        (job_dir / "RECOVER").unlink(missing_ok=True)
    prior_state = read_object(job_dir / "state.json") if recovery else None
    try:
        state(job_dir, "running", recovery=recovery, phase="worker_started",
              phase_started_at=now(), last_progress_at=now())
        event(job_dir, "worker_started", recovery=recovery)
        job, immutable_sha, execution_root = validate(job_dir, recovery=recovery)
        if isinstance(job.get("admission_request_id"), str):
            admission_requests.update(job["admission_request_id"], phase="worker_started",
                                      dispatch_reached=True, job_id=job["job_id"], job_created=True)
        event(job_dir, "contract_validated", operation=job["operation"], job_sha256=immutable_sha)
        state(job_dir, "running", operation=job["operation"], recovery=recovery,
              phase="contract_validated", phase_started_at=now(), last_progress_at=now())
        claim = job_dir / "CLAIMED"
        previous_attempt = 0
        if recovery:
            old_state = prior_state or {}
            change_attested = (job["operation"] == "change" and old_state.get("state") == "failed"
                               and (job_dir / "change-attestation.json").is_file()
                               and (job_dir / "change-journal.json").is_file())
            prewrite_failed = False
            if job["operation"] == "change" and old_state.get("state") == "failed" and not (job_dir / "change-journal.json").exists():
                try:
                    recovery_candidates = sorted(job_dir.glob("materializer-recovery-state.json*"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
                    if not recovery_candidates:
                        raise Rejected("CHANGE_RECOVERY_STATE_MISSING", str(job_dir))
                    recovery_state = read_object(recovery_candidates[0])
                    prewrite_failed = recovery_state.get("error_code") == "WINDOWS_MATERIALIZATION_FAILED"
                except Rejected:
                    prewrite_failed = False
            if not (old_state.get("state") == "recovery_required"
                    and job["operation"] in {"courier", "change", "retention_search"}) and not change_attested and not prewrite_failed:
                raise Rejected("RECOVERY_NOT_ALLOWED", repr(old_state))
            previous_attempt = int(old_state.get("attempt", 1))
        else:
            try:
                descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as exc:
                raise Rejected("JOB_ALREADY_CLAIMED", str(job_dir)) from exc
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(f"pid={os.getpid()} claimed_at={now()} job_sha256={immutable_sha}\n")
                handle.flush()
                os.fsync(handle.fileno())
        attempt = previous_attempt + 1
        state(job_dir, "running", attempt=attempt, operation=job["operation"], recovery=recovery,
              phase="contract_validated", phase_started_at=now(), last_progress_at=now())
        event(job_dir, "runner_job_started", attempt=attempt, operation=job["operation"], recovery=recovery, job_sha256=immutable_sha)
        command = command_for(job, execution_root, recovery=recovery, attempt=attempt)
        environment = {
            "HOME": "/home/icy",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/home/icy/miniconda3/envs/mp/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PYTHONPATH": str(execution_root),
            "MEPHC_CONTROL_ROOT_WINDOWS": config.CONTROL_ROOT_WINDOWS,
            "MEPHC_CONTROL_ROOT_WSL": str(config.CONTROL_ROOT),
            "MEPHC_STATE_ROOT": str(config.STATE_ROOT),
            "MEPHC_EXECUTION_ROOT": str(config.CHECKOUTS),
            "MEPHC_GIT_CACHE": str(config.GIT_CACHE),
            "MEPHC_RUNNER_JOB_ID": job["job_id"],
            "MEPHC_RUNNER_JOB_DIRECTORY": str(job_dir),
            "MEPHC_RUNNER_BUILD": runner_build_id(),
            "MEPHC_STATE_EPOCH": config.state_epoch(),
            "MEPHC_INSTALLED_SOURCE_HEAD": current_installed_source(),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
        }
        event(job_dir, "broker_dispatched" if job["operation"] == "change" else "broker_not_applicable",
              operation=job["operation"])
        if job["operation"] == "retention_search":
            event(job_dir, "retention_operation_entered")
            state(job_dir, "running", attempt=attempt, operation=job["operation"], recovery=recovery,
                  phase="retention_operation_entered", phase_started_at=now(), last_progress_at=now())
        if job["operation"] == "native":
            event(job_dir, "native_recipe_validated", recipe_id=job["native_binding"]["recipe_id"])
            state(job_dir, "running", attempt=attempt, operation="native", recovery=False,
                  phase="native_process_starting", phase_started_at=now(), last_progress_at=now())
        with (job_dir / "process.log").open("a", encoding="utf-8", newline="\n") as log:
            process = subprocess.Popen(
                command,
                cwd=execution_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = (time.monotonic() + config.MATERIALIZER_TIMEOUT_SECONDS + 60
                        if job["operation"] == "change" else
                        time.monotonic() + config.RETENTION_SEARCH_TIMEOUT_SECONDS + 30
                        if job["operation"] == "retention_search" else None)
            next_progress = 0.0
            timed_out = False
            while process.poll() is None:
                current = time.monotonic()
                if deadline is not None and current >= deadline:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=10)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    break
                if current >= next_progress:
                    state(job_dir, "running", attempt=attempt, operation=job["operation"], recovery=recovery,
                          child_pid=process.pid,
                          phase="awaiting_materializer" if job["operation"] == "change" else
                                "retention_search" if job["operation"] == "retention_search" else "executing",
                          deadline_unix=(time.time() + max(0, deadline - current)) if deadline is not None else None)
                    next_progress = current + 5
                time.sleep(0.5)
            return_code = process.returncode if process.returncode is not None else 124
        if hashlib.sha256((job_dir / "job.json").read_bytes()).hexdigest() != immutable_sha:
            raise Rejected("JOB_MUTATED_AFTER_CLAIM", str(job_dir / "job.json"))
        if job["operation"] == "courier" and job["arguments"][:1] == ["--request-directory"]:
            verify_courier_binding(job)
        courier_state = receipt_state(job)
        if job["operation"] == "native":
            event(job_dir, "native_process_exited", return_code=return_code)
        if return_code == 0:
            if job["operation"] == "retention_search":
                event(job_dir, "retention_search_completed")
            completion: dict[str, Any] = {}
            if job["operation"] == "change":
                attestation = read_object(job_dir / "change-attestation.json")
                completion = {"prelive_required": True, "source_commit": attestation.get("final_commit"),
                              "safe_next_tool": "mephc_validate"}
            state(job_dir, "succeeded", attempt=attempt, operation=job["operation"], return_code=0,
                  receipt_state=courier_state, **completion)
            event(job_dir, "runner_job_succeeded", return_code=0, receipt_state=courier_state)
        elif job["operation"] == "change" and (timed_out or return_code == 3):
            code = "CHANGE_CLIENT_TIMEOUT" if timed_out else "CHANGE_TRANSACTION_RECOVERY_REQUIRED"
            state(job_dir, "recovery_required", attempt=attempt, operation="change", return_code=return_code,
                  error_code=code, detail=failure_detail(job_dir))
            event(job_dir, "runner_recovery_required", return_code=return_code, error_code=code)
        elif job["operation"] == "courier" and courier_state in RECOVERABLE:
            state(job_dir, "recovery_required", attempt=attempt, operation="courier", return_code=return_code, receipt_state=courier_state)
            event(job_dir, "runner_recovery_required", return_code=return_code, receipt_state=courier_state)
        elif job["operation"] == "retention_search":
            code = "SEARCH_INCOMPLETE" if timed_out or return_code == 4 else "CHILD_PROCESS_FAILED"
            state(job_dir, "failed", attempt=attempt, operation="retention_search", return_code=return_code,
                  error_code=code, detail=failure_detail(job_dir), retry_allowed=False,
                  safe_next_tool="mephc_retention_inspect" if (job_dir / "retention-search-result.json").is_file()
                                 else "mephc_status")
            event(job_dir, "runner_job_failed", return_code=return_code, error_code=code)
        elif job["operation"] == "change":
            detail = failure_detail(job_dir)
            state_record = None
            for candidate in (job_dir / "materializer-recovery-state.json", job_dir / "materializer-state.json"):
                if candidate.is_file():
                    try: state_record = read_object(candidate)
                    except Rejected: state_record = None
                    if state_record is not None: break
            code = state_record.get("error_code", "CHILD_PROCESS_FAILED") if state_record else "CHILD_PROCESS_FAILED"
            state(job_dir, "failed", attempt=attempt, operation="change", return_code=return_code,
                  detail=detail, error_code=code)
            event(job_dir, "runner_job_failed", return_code=return_code, error_code=code)
        else:
            detail = failure_detail(job_dir)
            code = relay_failure_code(job_dir) or "CHILD_PROCESS_FAILED"
            state(job_dir, "failed", attempt=attempt, operation=job["operation"], return_code=return_code,
                  receipt_state=courier_state, detail=detail, error_code=code)
            event(job_dir, "runner_job_failed", return_code=return_code, receipt_state=courier_state, error_code=code)
    except Rejected as exc:
        detail = bounded_detail(exc.detail)
        state(job_dir, "failed", error_code=exc.code, detail=detail)
        event(job_dir, "runner_job_rejected", error_code=exc.code, detail=detail)
    except Exception as exc:
        detail = bounded_detail(repr(exc))
        state(job_dir, "failed", error_code="RUNNER_INTERNAL_ERROR", detail=detail)
        event(job_dir, "runner_internal_error", detail=detail)
    finally:
        try:
            final_job = read_object(job_dir / "job.json")
            request_id = final_job.get("admission_request_id")
            final_state = read_object(job_dir / "state.json")
            if isinstance(request_id, str):
                admission_requests.update(request_id, phase="terminal" if final_state.get("state") in job_semantics.TERMINAL else final_state.get("phase"),
                                          dispatch_reached=True, error_code=final_state.get("error_code"),
                                          failure_layer=job_semantics.failure_layer(final_state.get("error_code")))
        except (OSError, Rejected, ValueError, json.JSONDecodeError):
            pass


def repair_interrupted() -> None:
    for job_dir in JOBS.iterdir() if JOBS.is_dir() else []:
        state_path = job_dir / "state.json"
        if not job_dir.is_dir() or not state_path.is_file():
            continue
        try:
            old_state = read_object(state_path)
            if old_state.get("state") != "running":
                continue
            job = read_object(job_dir / "job.json")
            if job.get("operation") == "change":
                state(job_dir, "recovery_required", attempt=old_state.get("attempt", 1), operation="change", error_code="CHANGE_TRANSACTION_RECOVERY_REQUIRED")
                event(job_dir, "runner_interrupted_state_repaired", next_state="recovery_required", error_code="CHANGE_TRANSACTION_RECOVERY_REQUIRED")
                continue
            if job.get("operation") == "retention_search":
                state(job_dir, "recovery_required", attempt=old_state.get("attempt", 1),
                      operation="retention_search", error_code="SEARCH_INTERRUPTED_RECOVERY_REQUIRED",
                      retry_allowed=False, safe_next_tool="mephc_recover")
                event(job_dir, "runner_interrupted_state_repaired", next_state="recovery_required",
                      error_code="SEARCH_INTERRUPTED_RECOVERY_REQUIRED")
                continue
            next_state = "recovery_required" if job.get("operation") == "courier" else "failed"
            code = "WORKER_RESTART_RECOVERY_REQUIRED" if next_state == "recovery_required" else "WORKER_RESTARTED"
            state(job_dir, next_state, attempt=old_state.get("attempt", 1), error_code=code)
            event(job_dir, "runner_interrupted_state_repaired", next_state=next_state, error_code=code)
        except Rejected:
            continue


def runner_build_id() -> str:
    names = ("worker.py","jobctl.py","workflow.py","workflow_resume.py","work_order_contract.py",
             "runtime_attestation.py","job_semantics.py","runner_errors.py","admission_requests.py","runtime_config.py","active_index.py",
             "reconcile_stale_ready.py",
             "quarantine_oversized_state.py","checkout_manager.py","retention_inspector.py",
             "user_runtime.py","home_cleanup.py","migrate_state.py","migrate_canary_metadata.py",
             "windows_materializer.py","windows_broker.py",
             "materialize_client.py","mcp_server.py","native-recipes.json","mephc-runner.ps1",
             "mephc-runner.cmd","mephc-connector.cmd","mephc-connector.ps1",
             "mephc-runner.service","README.md")
    source_hashes = "".join(hashlib.sha256((INSTALL_ROOT / name).read_bytes()).hexdigest() for name in names)
    return hashlib.sha256(source_hashes.encode("ascii")).hexdigest()[:16]


def runtime_source_matches() -> bool:
    global _SOURCE_RUNTIME_MATCH_CACHE, _SOURCE_RUNTIME_MISMATCH
    try:
        manifest = json.loads((config.WINDOWS_RUNTIME_WSL / "install-manifest.json").read_text(encoding="utf-8-sig"))
        current = json.loads((config.WINDOWS_RUNTIME_WSL / "current.json").read_text(encoding="utf-8-sig"))
        expected = {item["name"]: item["sha256"] for item in manifest if isinstance(item, dict)}
        source_head = checkout_manager.source_head()
        # A negative result can be observed during the small bootstrap window
        # between the WSL version switch and the Windows manifest pointer
        # switch.  Never pin that transient mismatch for the lifetime of the
        # worker; only a positive proof is safe to cache by source SHA.
        if (_SOURCE_RUNTIME_MATCH_CACHE is not None
                and _SOURCE_RUNTIME_MATCH_CACHE[0] == source_head
                and _SOURCE_RUNTIME_MATCH_CACHE[1] is True):
            return _SOURCE_RUNTIME_MATCH_CACHE[1]
        if not expected or not isinstance(current.get("source_commit"), str):
            _SOURCE_RUNTIME_MISMATCH = {"reason": "manifest_or_current_invalid"}
            return False
        for name, digest in expected.items():
            installed = INSTALL_ROOT / name
            source = subprocess.run(
                [str(config.WINDOWS_GIT_WSL), "-c", f"safe.directory={config.CONTROL_ROOT_WINDOWS}",
                 "-C", config.CONTROL_ROOT_WINDOWS, "-c", "core.autocrlf=false", "cat-file", "blob",
                 f"{source_head}:tools/mephc-runner/{name}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=15,
            )
            installed_matches = (installed.is_file()
                                 and hashlib.sha256(installed.read_bytes()).hexdigest() == digest)
            source_matches = source.returncode == 0 and hashlib.sha256(source.stdout).hexdigest() == digest
            if not installed_matches or not source_matches:
                _SOURCE_RUNTIME_MISMATCH = {"reason": "managed_file_mismatch", "name": name,
                                            "git_return_code": source.returncode,
                                            "installed_matches_manifest": installed_matches,
                                            "source_blob_matches_manifest": source_matches}
                _SOURCE_RUNTIME_MATCH_CACHE = (source_head, False)
                return False
        _SOURCE_RUNTIME_MISMATCH = None
        _SOURCE_RUNTIME_MATCH_CACHE = (source_head, True)
        return True
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        _SOURCE_RUNTIME_MISMATCH = {"reason": "runtime_source_check_failed"}
        return False


def current_installed_source() -> str:
    try:
        value = json.loads((config.WINDOWS_RUNTIME_WSL / "current.json").read_text(encoding="utf-8-sig"))
        source = value.get("source_commit")
        return source if isinstance(source, str) else ""
    except (OSError, json.JSONDecodeError):
        return ""


def heartbeat() -> None:
    build_id = runner_build_id()
    expected_mcp = runtime_attestation.bundle_hash(INSTALL_ROOT, runtime_attestation.MCP_BUNDLE_FILES)
    current = None
    try: current = json.loads((config.WINDOWS_RUNTIME_WSL / "current.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError): current = {}
    atomic_json(RUNTIME / "heartbeat.json", {
        "schema": "mephc-runner-heartbeat-v1",
        "pid": os.getpid(),
        "platform": "wsl",
        "worker_role": "shared_durable_worker",
        "retention_capable": True,
        "service_name": "mephc-runner.service",
        "worker_start_id": WORKER_START_ID,
        "worker_started_at": WORKER_STARTED_AT,
        "control_root": config.CONTROL_ROOT_WINDOWS,
        "state_root": str(config.STATE_ROOT),
        "execution_root_policy": str(config.CHECKOUTS / "<commit-sha>"),
        "python": sys.executable,
        "source_head": checkout_manager.source_head(),
        "source_commit": checkout_manager.source_head(),
        "origin_main": checkout_manager.source_origin_main(),
        "state_epoch": config.state_epoch(),
        "worker_build_id": build_id,
        "installed_source_head": current.get("source_commit"),
        "loaded_worker_module_hash": LOADED_WORKER_MODULE_HASH,
        "expected_mcp_bundle_hash": expected_mcp,
        "runtime_source_matches": runtime_source_matches(),
        "runtime_source_mismatch": _SOURCE_RUNTIME_MISMATCH,
        "updated_at": now(),
    })


def heartbeat_loop() -> None:
    while True:
        heartbeat()
        time.sleep(2.0)


def main() -> int:
    if Path.cwd().resolve() != RUNTIME:
        print(json.dumps({"event": "runner_start_failed", "error_code": "ROOT_MISMATCH"}))
        return 2
    if Path(sys.executable).resolve() != PYTHON.resolve():
        print(json.dumps({"event": "runner_start_failed", "error_code": "INTERPRETER_MISMATCH"}))
        return 2
    RUNTIME.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    lock_handle = (RUNTIME / "worker.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"event": "runner_start_failed", "error_code": "WORKER_ALREADY_RUNNING"}))
        return 3
    repair_interrupted()
    active_index.rebuild(JOBS)
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    while True:
        for job_dir in sorted(path for path in JOBS.iterdir() if path.is_dir()):
            if (job_dir / "RECOVER").is_file():
                execute(job_dir, recovery=True)
            elif (job_dir / "READY").is_file() and not (job_dir / "CLAIMED").exists():
                try:
                    existing = read_object(job_dir / "state.json").get("state")
                except Rejected:
                    existing = "unknown"
                if existing not in {"succeeded", "failed", "recovery_required"}:
                    execute(job_dir)
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
