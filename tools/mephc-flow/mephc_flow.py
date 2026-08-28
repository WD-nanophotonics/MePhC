#!/usr/bin/env python3
"""Direct MePhC workflow: Git + exact WSL checkout + durable native/Courier state.

This module deliberately has no dependency on the retired Runner, MCP,
certificates, prelive attestations, or installed-runtime activation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
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
FLOW_STATE_UNC = LEGACY_STATE_UNC / "flow"
FLOW_STATE_WSL = LEGACY_STATE_WSL + "/flow"
SCIENCE_STATE_WSL = "/home/icy/.local/share/mephc-runtime/science"
SCIENCE_STATE_UNC = Path(r"\\wsl.localhost\Ubuntu\home\icy\.local\share\mephc-runtime\science")
OUTBOX_UNC = LEGACY_STATE_UNC / "outbox"
OUTBOX_WSL = LEGACY_STATE_WSL + "/outbox"
CHECKOUT_ROOT_WSL = "/home/icy/.cache/mephc-runner/checkouts"
GIT_CACHE_WSL = "/home/icy/.cache/mephc-runner/MEPHC.git"
CONDA_PYTHON_WSL = "/home/icy/miniconda3/envs/mp/bin/python"
COURIER = Path(r"C:\Users\icywo\PycharmProjects\GmailCourier\scripts\chat-courier.cmd")
REPORT_POLICIES = {"adaptive", "per-work-order", "milestone", "final-only"}
REPORT_KINDS = {"milestone", "complete", "blocked"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
WORK_ORDER = re.compile(r"^MEPHC-[A-Z0-9][A-Z0-9._-]{7,159}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FlowError(RuntimeError):
    def __init__(self, code: str, detail: str = "", *, safe_next: str = "status") -> None:
        self.code, self.detail, self.safe_next = code, detail, safe_next
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Paths:
    control: Path = CONTROL_ROOT
    state: Path = FLOW_STATE_UNC
    outbox: Path = OUTBOX_UNC
    courier: Path = COURIER
    legacy_state: Path = LEGACY_STATE_UNC
    outbox_wsl: str = OUTBOX_WSL
    science_state: Path = SCIENCE_STATE_UNC
    science_state_wsl: str = SCIENCE_STATE_WSL


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical_json(value))
    os.replace(temporary, path)


def read_json(path: Path, *, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FlowError("STATE_JSON_INVALID", str(path)) from exc


def command(
    argv: Sequence[str], *, cwd: Path | None = None, timeout: int = 600,
    check: bool = True, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise FlowError("ARGV_INVALID")
    merged = os.environ.copy()
    merged.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "GIT_EDITOR": "true"})
    if env:
        merged.update(env)
    try:
        result = subprocess.run(
            list(argv), cwd=cwd, text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=timeout, check=False, env=merged,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise FlowError("COMMAND_TIMEOUT", " ".join(argv[:3]), safe_next="status") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise FlowError("COMMAND_FAILED", detail[-4000:])
    return result


def git(paths: Paths, *args: str, timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess[str]:
    return command(
        ["git", "-c", f"safe.directory={paths.control}", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=true", "-C", str(paths.control), *args],
        timeout=timeout, check=check,
    )


def wsl(argv: Sequence[str], *, timeout: int = 600, check: bool = True, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    prefix = ["wsl.exe", "-d", "Ubuntu"]
    if cwd is not None:
        prefix.extend(["--cd", cwd])
    prefix.append("--")
    return command([*prefix, *argv], timeout=timeout, check=check)


def source_state(paths: Paths) -> dict[str, Any]:
    branch = git(paths, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    head = git(paths, "rev-parse", "HEAD").stdout.strip()
    main = git(paths, "rev-parse", "refs/remotes/origin/main").stdout.strip()
    sandbox = git(paths, "rev-parse", "refs/remotes/origin/sandbox").stdout.strip()
    dirty = bool(git(paths, "status", "--porcelain", "--untracked-files=all").stdout.strip())
    return {"branch": branch, "head": head, "origin_main": main, "origin_sandbox": sandbox, "dirty": dirty}


def require_source(paths: Paths, *, published: bool = False) -> dict[str, Any]:
    state = source_state(paths)
    if state["branch"] != "sandbox":
        raise FlowError("CONTROL_BRANCH_NOT_SANDBOX")
    if state["dirty"]:
        raise FlowError("CONTROL_ROOT_DIRTY")
    if state["origin_main"] != EXPECTED_MAIN:
        raise FlowError("ORIGIN_MAIN_MOVED")
    if not SHA40.fullmatch(state["head"]):
        raise FlowError("SOURCE_HEAD_INVALID")
    if published and state["head"] != state["origin_sandbox"]:
        raise FlowError("SOURCE_NOT_PUBLISHED", safe_next="publish")
    return state


def remote_refs(paths: Paths) -> tuple[str, str]:
    result = git(paths, "ls-remote", "--heads", "origin", "main", "sandbox", timeout=120)
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            values[fields[1]] = fields[0]
    try:
        return values["refs/heads/main"], values["refs/heads/sandbox"]
    except KeyError as exc:
        raise FlowError("REMOTE_REFS_INCOMPLETE") from exc


def ensure_checkout(paths: Paths, commit: str) -> str:
    if not SHA40.fullmatch(commit):
        raise FlowError("SOURCE_HEAD_INVALID")
    wsl(["/usr/bin/mkdir", "-p", str(PurePosixPath(GIT_CACHE_WSL).parent), CHECKOUT_ROOT_WSL])
    probe = wsl(["/usr/bin/test", "-d", GIT_CACHE_WSL], check=False)
    if probe.returncode:
        wsl(["/usr/bin/git", "init", "--bare", GIT_CACHE_WSL])
    wsl(["/usr/bin/git", "-C", GIT_CACHE_WSL, "fetch", "--force", "--no-tags", f"{CONTROL_ROOT_WSL}/.git", commit])
    resolved = wsl(["/usr/bin/git", "-C", GIT_CACHE_WSL, "rev-parse", "FETCH_HEAD^{commit}"]).stdout.strip()
    if resolved != commit:
        raise FlowError("SOURCE_COMMIT_NOT_EXACT")
    checkout = f"{CHECKOUT_ROOT_WSL}/{commit}"
    exists = wsl(["/usr/bin/test", "-d", checkout], check=False).returncode == 0
    if not exists:
        wsl(["/usr/bin/git", "-C", GIT_CACHE_WSL, "worktree", "add", "--detach", checkout, commit])
    actual = wsl(["/usr/bin/git", "-C", checkout, "rev-parse", "HEAD"]).stdout.strip()
    dirty = wsl(["/usr/bin/git", "-C", checkout, "status", "--porcelain", "--untracked-files=all"]).stdout.strip()
    fstype = wsl(["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "--target", checkout]).stdout.strip().lower()
    if actual != commit or dirty:
        raise FlowError("EXECUTION_CHECKOUT_MISMATCH")
    if fstype in {"9p", "drvfs", "fuseblk"} or not fstype:
        raise FlowError("EXECUTION_CHECKOUT_NOT_LINUX_NATIVE")
    return checkout


def ledger(paths: Paths) -> dict[str, Any]:
    value = read_json(paths.legacy_state / "runner" / "workflow-ledger.json", default={})
    return value if isinstance(value, dict) else {}


def wsl_path_to_unc(value: str, paths: Paths) -> Path:
    if not value.startswith("/home/icy/"):
        raise FlowError("WORKFLOW_RESPONSE_PATH_INVALID")
    relative = PurePosixPath(value).relative_to(PurePosixPath(LEGACY_STATE_WSL))
    return paths.legacy_state.joinpath(*relative.parts)


def active_work_order(paths: Paths) -> dict[str, Any]:
    value = ledger(paths)
    work_order_id = value.get("active_work_order_id")
    response_value = value.get("active_response_path")
    expected_hash = value.get("active_response_sha256")
    if not isinstance(work_order_id, str) or not WORK_ORDER.fullmatch(work_order_id):
        raise FlowError("ACTIVE_WORK_ORDER_UNAVAILABLE", safe_next="courier-reconcile")
    if not isinstance(response_value, str) or not isinstance(expected_hash, str) or not SHA64.fullmatch(expected_hash):
        raise FlowError("ACTIVE_RESPONSE_BINDING_INVALID")
    response = wsl_path_to_unc(response_value, paths)
    if not response.is_file() or sha256_file(response) != expected_hash:
        raise FlowError("ACTIVE_RESPONSE_SHA_MISMATCH")
    request = read_json(response.parent / "request.json", default={})
    receipt = read_json(response.parent / "receipt.json", default={})
    if request.get("project_id") != PROJECT_ID or receipt.get("state") != "response_received":
        raise FlowError("ACTIVE_RESPONSE_NOT_RECEIPT_BOUND")
    text = response.read_text(encoding="utf-8-sig")
    return {"work_order_id": work_order_id, "response_sha256": expected_hash, "response_path": str(response), "text": text}


def response_work_order(text: str) -> str:
    match = re.search(r"^NEXT_WORK_ORDER_ID=([^\r\n]+)$", text.replace("\r\n", "\n"), flags=re.MULTILINE)
    value = match.group(1).strip() if match else ""
    if not WORK_ORDER.fullmatch(value):
        raise FlowError("RESPONSE_WORK_ORDER_ID_INVALID")
    return value


def consume_response(paths: Paths, directory: Path) -> dict[str, Any]:
    request = read_json(directory / "request.json", default={})
    receipt = read_json(directory / "receipt.json", default={})
    response = directory / "response.txt"
    if (request.get("project_id") != PROJECT_ID or request.get("request_id") != directory.name
            or receipt.get("state") != "response_received" or not response.is_file()):
        raise FlowError("RESPONSE_NOT_RECEIPT_BOUND")
    text = response.read_text(encoding="utf-8-sig")
    work_order_id = response_work_order(text)
    digest = sha256_file(response)
    value = {
        "schema": "mephc-workflow-ledger-v2", "workflow_state": "available",
        "active_work_order_id": work_order_id,
        "active_response_path": f"{paths.outbox_wsl.rstrip('/')}/{directory.name}/response.txt",
        "active_response_sha256": digest, "pending_job_id": None, "updated_at": time.time(),
    }
    atomic_json(paths.legacy_state / "runner" / "workflow-ledger.json", value)
    atomic_json(paths.state / "last-consumed-response.json", {
        "schema": "mephc-flow-consumed-response-v1", "request_id": directory.name,
        "work_order_id": work_order_id, "response_sha256": digest, "consumed_at": time.time(),
    })
    return {"work_order_id": work_order_id, "response_sha256": digest, "response_text": text}


def latest_response(paths: Paths) -> Path | None:
    if not paths.outbox.is_dir():
        return None
    candidates: list[Path] = []
    for directory in paths.outbox.iterdir():
        if not directory.is_dir() or directory.is_symlink() or not (directory / "response.txt").is_file():
            continue
        request = read_json(directory / "request.json", default={})
        receipt = read_json(directory / "receipt.json", default={})
        if request.get("project_id") == PROJECT_ID and receipt.get("state") == "response_received":
            candidates.append(directory)
    return max(candidates, key=lambda item: (item.joinpath("response.txt").stat().st_mtime_ns, item.name)) if candidates else None


def key_values(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    normalized = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    for raw in normalized.splitlines():
        line = raw.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", key):
            result.setdefault(key, []).append(value.strip())
    return result


def machine_contract(text: str) -> dict[str, Any]:
    for line in text.replace("\r\n", "\n").splitlines():
        if line.startswith("WORK_ORDER_CONTRACT_JSON="):
            try:
                value = json.loads(line.split("=", 1)[1])
            except json.JSONDecodeError as exc:
                raise FlowError("WORK_ORDER_CONTRACT_JSON_INVALID") from exc
            return value if isinstance(value, dict) else {}
    return {}


def science_module(paths: Paths):
    name = "_mephc_scientific_job_control"
    path = paths.control / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FlowError("SCIENCE_RUNTIME_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def active_machine_contract(paths: Paths) -> tuple[dict[str, Any], dict[str, Any]]:
    order = active_work_order(paths)
    value = machine_contract(order["text"])
    module = science_module(paths)
    try:
        contract = module.validate_contract(value)
    except module.ScientificJobError as exc:
        raise FlowError(str(exc), safe_next="report") from exc
    if contract["work_order_id"] != order["work_order_id"]:
        raise FlowError("WORK_ORDER_CONTRACT_ID_MISMATCH")
    return order, contract


def science_runtime_hash(paths: Paths, commit: str) -> str:
    accumulator = hashlib.sha256()
    for relative in (
        "tools/mephc-flow/scientific_job.py",
        "tools/mephc-flow/mephc_science_runtime.py",
        "tools/mephc-flow/wsl_native_exec.py",
    ):
        blob = git(paths, "show", f"{commit}:{relative}").stdout.encode("utf-8")
        accumulator.update(relative.encode("utf-8"))
        accumulator.update(hashlib.sha256(blob).digest())
    return accumulator.hexdigest()


def science_selftest(paths: Paths, *, mpb_smoke: bool) -> dict[str, Any]:
    source = require_source(paths, published=True)
    checkout = ensure_checkout(paths, source["head"])
    helper = f"{checkout}/tools/mephc-flow/scientific_job.py"
    argv = [CONDA_PYTHON_WSL, helper, "internal-selftest", "--root", checkout,
            "--state-root", paths.science_state_wsl]
    if mpb_smoke:
        argv.append("--mpb-smoke")
    result = wsl(argv, cwd=checkout, timeout=3600, check=False)
    if result.returncode:
        raise FlowError("SCIENCE_RUNTIME_SELFTEST_FAILED", (result.stderr or result.stdout)[-8000:])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        value = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError as exc:
        raise FlowError("SCIENCE_RUNTIME_SELFTEST_OUTPUT_INVALID") from exc
    if not isinstance(value, dict):
        raise FlowError("SCIENCE_RUNTIME_SELFTEST_OUTPUT_INVALID")
    return {
        **value, "source_commit": source["head"], "execution_checkout": checkout,
        "stdout_sha256": sha256_bytes(result.stdout.encode("utf-8")),
        "stdout_size_bytes": len(result.stdout.encode("utf-8")),
        "stderr_sha256": sha256_bytes(result.stderr.encode("utf-8")),
        "stderr_size_bytes": len(result.stderr.encode("utf-8")),
    }


def science_preflight(paths: Paths) -> dict[str, Any]:
    order, contract = active_machine_contract(paths)
    source = require_source(paths, published=True)
    if contract["source_commit"] != source["head"]:
        raise FlowError("WORK_ORDER_SOURCE_COMMIT_MISMATCH", safe_next="report")
    checkout = ensure_checkout(paths, source["head"])
    entrypoint = contract.get("entrypoint")
    if entrypoint is not None:
        tracked = wsl(["/usr/bin/git", "-C", checkout, "ls-files", "--error-unmatch", entrypoint], check=False)
        if tracked.returncode:
            raise FlowError("WORK_ORDER_ENTRYPOINT_NOT_TRACKED")
    runtime_sha = science_runtime_hash(paths, source["head"])
    certification_path = paths.science_state / "certifications" / f"{runtime_sha}.json"
    certification = read_json(certification_path, default={})
    if certification.get("schema") != "mephc-science-runtime-certification-v1":
        raise FlowError("SCIENCE_RUNTIME_SELFTEST_REQUIRED", safe_next="science-selftest")
    if contract["action"] == "acquire" and certification.get("mpb_smoke", {}).get("executed") is not True:
        raise FlowError("SCIENCE_RUNTIME_MPB_SMOKE_REQUIRED", safe_next="science-selftest")
    available = {
        "exact_checkout", "sandbox_publication", "native_execution", "mpb",
        "private_retention", "cross_commit_dataset_read", "result_channel",
        "checkpoint", "payload_codec", "automatic_provenance",
    }
    missing = sorted(set(contract["required_capabilities"]) - available)
    if missing:
        raise FlowError("INFRASTRUCTURE_CAPABILITY_MISSING", ",".join(missing))
    dataset_evidence = None
    if contract["action"] == "analyze":
        dataset_evidence = dataset_verify(paths, contract["inputs"]["dataset_id"])
        expected_manifest = contract["inputs"].get("dataset_manifest_sha256")
        if expected_manifest is not None and dataset_evidence.get("manifest_sha256") != expected_manifest:
            raise FlowError("WORK_ORDER_DATASET_MANIFEST_MISMATCH")
    publish_evidence = read_json(paths.state / "publish" / f"{source['head']}.json", default={})
    changed_files = [line for line in git(paths, "diff", "--name-only", f"{EXPECTED_MAIN}..{source['head']}").stdout.splitlines() if line]
    atomic_json(paths.state / "contracts" / f"{contract['contract_sha256']}.json", {
        **contract, "receipt_response_sha256": order["response_sha256"], "validated_at": time.time(),
    })
    return {
        "schema": "mephc-science-preflight-v1", "ready_to_run": True,
        "work_order_id": order["work_order_id"], "contract_sha256": contract["contract_sha256"],
        "source_commit": source["head"], "execution_checkout": checkout,
        "runtime_sha256": runtime_sha, "required_capabilities": contract["required_capabilities"],
        "missing_capabilities": [], "entrypoint": entrypoint, "budgets": contract["budgets"],
        "certification": certification, "dataset_evidence": dataset_evidence,
        "automatic_provenance": {
            "main_sha": EXPECTED_MAIN, "sandbox_sha": source["head"],
            "changed_files": changed_files,
            "publish_test_count": len(publish_evidence.get("tests", [])),
            "publish_stdout_sha256": publish_evidence.get("stdout_sha256"),
            "publish_stderr_sha256": publish_evidence.get("stderr_sha256"),
        },
    }


def dataset_verify(paths: Paths, dataset_id: str) -> dict[str, Any]:
    if not SHA64.fullmatch(dataset_id):
        raise FlowError("DATASET_ID_INVALID")
    binding = paths.control / "audit" / "e9f" / "qp_b_c2_c3_r8_d3_acquisition_binding.json"
    value = read_json(binding, default={})
    if value.get("acquisition_dataset_id") == dataset_id:
        record_path = paths.state / "reconciliations" / f"{value['original_native_run_id']}.json"
        record = read_json(record_path, default={})
        if (record.get("reconciliation_status") != "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED"
                or record.get("acquisition_binding", {}).get("acquisition_dataset_id") != dataset_id
                or sha256_file(record_path) != value.get("reconciliation_record_sha256")):
            raise FlowError("DATASET_RECONCILIATION_BINDING_INVALID")
        return {
            "state": "verified", "dataset_id": dataset_id,
            "manifest_sha256": value["dataset_manifest_sha256"],
            "record_count": value["completed_key_count"],
            "source_commit": value["acquisition_source_commit"], "compatibility_adapter": "R8",
        }
    source = require_source(paths, published=True)
    checkout = ensure_checkout(paths, source["head"])
    helper = f"{checkout}/tools/mephc-flow/scientific_job.py"
    result = wsl([CONDA_PYTHON_WSL, helper, "internal-dataset-verify",
                  "--state-root", paths.science_state_wsl, "--dataset-id", dataset_id],
                 cwd=checkout, timeout=3600, check=False)
    if result.returncode:
        raise FlowError("DATASET_VERIFICATION_FAILED", (result.stderr or result.stdout)[-4000:])
    return json.loads(result.stdout)


def work_order_policy(text: str) -> dict[str, Any]:
    values = key_values(text)
    contract = machine_contract(text)
    actions = contract.get("authorized_actions", []) if isinstance(contract.get("authorized_actions", []), list) else []
    native_true = any(values.get(key, [""])[-1].lower() in {"1", "true", "yes"} for key in (
        "NATIVE_AUTHORIZED", "NATIVE_SOLVES_AUTHORIZED", "NATIVE_EXECUTION_AUTHORIZED"
    )) or any(str(item).lower() in {"native", "native.execute", "native.solves"} for item in actions)
    budget_values: list[int] = []
    for key, entries in values.items():
        if key.startswith("NATIVE_") and ("BUDGET" in key or "MAX_INVOCATIONS" in key):
            for entry in entries:
                if entry.isdigit() and int(entry) > 0:
                    budget_values.append(int(entry))
    for item in contract.get("native_recipes", []) if isinstance(contract.get("native_recipes", []), list) else []:
        if isinstance(item, dict) and isinstance(item.get("max_invocations"), int) and item["max_invocations"] > 0:
            budget_values.append(item["max_invocations"])
    if contract.get("schema") == "mephc-science-work-order-v1":
        budgets = contract.get("budgets", {})
        if contract.get("action") == "acquire" and isinstance(budgets.get("native_invocations"), int):
            native_true = budgets["native_invocations"] > 0
            if budgets["native_invocations"] > 0:
                budget_values.append(budgets["native_invocations"])
    allowed: set[str] = set()
    for key, entries in values.items():
        if key in {"ALLOWED_PROJECT_PATH", "NATIVE_PROJECT_PATH", "PROJECT_PATH", "DOWNSTREAM_PROJECT_PATH"}:
            allowed.update(value for value in entries if value.startswith("/home/icy/"))
    declared_policy = values.get("REPORT_POLICY", [None])[-1]
    if declared_policy not in REPORT_POLICIES:
        declared_policy = None
    return {
        "native_authorized": native_true,
        "native_budget": min(budget_values) if budget_values else None,
        "allowed_project_paths": sorted(allowed),
        "report_policy": declared_policy,
        "arbitrary_native_command_authorized": values.get("ARBITRARY_NATIVE_COMMAND_AUTHORIZED", ["false"])[-1].lower() in {"1", "true", "yes"},
        "native_entrypoint": contract.get("entrypoint") if contract.get("schema") == "mephc-science-work-order-v1" else values.get("NATIVE_ENTRYPOINT", [None])[-1],
        "native_arguments": [] if contract.get("schema") == "mephc-science-work-order-v1" else values.get("NATIVE_ARGUMENT", []),
    }


def session(paths: Paths) -> dict[str, Any]:
    value = read_json(paths.state / "session.json", default={})
    return value if isinstance(value, dict) else {}


def effective_policy(paths: Paths, order: dict[str, Any] | None = None) -> dict[str, Any]:
    current = session(paths)
    declared: dict[str, Any] = {}
    if order is not None:
        declared = work_order_policy(order["text"])
    policy = current.get("user_report_policy") or declared.get("report_policy") or "adaptive"
    chat_cap = declared.get("native_budget")
    user_cap = current.get("user_native_cap")
    effective_cap = min(chat_cap, user_cap) if isinstance(chat_cap, int) and isinstance(user_cap, int) else chat_cap
    return {"report_policy": policy, "chat_native_budget": chat_cap, "user_native_cap": user_cap, "effective_native_budget": effective_cap}


def start(paths: Paths, report_policy: str | None, native_cap: int | None) -> dict[str, Any]:
    if report_policy is not None and report_policy not in REPORT_POLICIES:
        raise FlowError("REPORT_POLICY_INVALID")
    if native_cap is not None and native_cap < 1:
        raise FlowError("NATIVE_CAP_INVALID")
    value = {
        "schema": "mephc-flow-session-v1", "created_at": time.time(),
        "user_report_policy": report_policy, "user_native_cap": native_cap,
    }
    atomic_json(paths.state / "session.json", value)
    order = active_work_order(paths)
    return {"state": "started", "work_order_id": order["work_order_id"], **effective_policy(paths, order)}


def request_summary(directory: Path) -> dict[str, Any]:
    request = read_json(directory / "request.json", default={})
    receipt = read_json(directory / "receipt.json", default={})
    events = directory / "events.jsonl"
    submissions = 0
    if events.is_file():
        submissions = sum('"event": "request_submitted"' in line or '"event":"request_submitted"' in line
                          for line in events.read_text(encoding="utf-8-sig", errors="replace").splitlines())
    return {
        "request_id": request.get("request_id", directory.name),
        "receipt_state": receipt.get("state"), "submission_count": submissions,
        "response_received": (directory / "response.txt").is_file(),
    }


def status(paths: Paths) -> dict[str, Any]:
    source = source_state(paths)
    try:
        order = active_work_order(paths)
        policy = work_order_policy(order["text"])
        work_order_id = order["work_order_id"]
        effective = effective_policy(paths, order)
    except FlowError:
        work_order_id, policy, effective = None, {}, effective_policy(paths)
    runs = []
    run_root = paths.state / "native-runs"
    if run_root.is_dir():
        for item in sorted(run_root.glob("*.json")):
            value = read_json(item, default={})
            if isinstance(value, dict) and value.get("state") not in {"succeeded", "failed"}:
                runs.append({key: value.get(key) for key in ("run_id", "work_order_id", "state", "pid")})
    requests = []
    if paths.outbox.is_dir():
        for directory in paths.outbox.glob("MEPHC-FLOW-*"):
            if directory.is_dir():
                requests.append(request_summary(directory))
    return {
        "schema": "mephc-flow-status-v1", "source": source,
        "active_work_order_id": work_order_id, "work_order_policy": policy,
        "effective_policy": effective, "pending_native_runs": runs,
        "flow_requests": sorted(requests, key=lambda item: str(item["request_id"])),
    }


def resume(paths: Paths) -> dict[str, Any]:
    newest = latest_response(paths)
    if newest is not None:
        current = ledger(paths)
        newest_wsl = f"{paths.outbox_wsl.rstrip('/')}/{newest.name}/response.txt"
        if current.get("active_response_path") != newest_wsl:
            consume_response(paths, newest)
    order = active_work_order(paths)
    return {
        "schema": "mephc-flow-work-order-v1", "work_order_id": order["work_order_id"],
        "response_sha256": order["response_sha256"], "policy": work_order_policy(order["text"]),
        "effective_policy": effective_policy(paths, order), "work_order_text": order["text"],
    }


def validate_test_path(value: str) -> str:
    path, _, selector = value.partition("::")
    candidate = PurePosixPath(path.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) < 2 or candidate.parts[0] != "tests" or candidate.suffix != ".py":
        raise FlowError("TEST_PATH_INVALID", value)
    return str(candidate) + ("::" + selector if selector else "")


def publish(paths: Paths, tests: list[str]) -> dict[str, Any]:
    if not tests:
        raise FlowError("TESTS_REQUIRED")
    tests = [validate_test_path(value) for value in tests]
    source = require_source(paths)
    remote_main, remote_sandbox = remote_refs(paths)
    if remote_main != EXPECTED_MAIN:
        raise FlowError("ORIGIN_MAIN_MOVED")
    if remote_sandbox != source["origin_sandbox"]:
        raise FlowError("REMOTE_SANDBOX_MOVED", safe_next="git-fetch-review")
    ancestor = git(paths, "merge-base", "--is-ancestor", remote_sandbox, source["head"], check=False)
    if ancestor.returncode:
        raise FlowError("SANDBOX_NOT_FAST_FORWARD")
    checkout = ensure_checkout(paths, source["head"])
    result = wsl([CONDA_PYTHON_WSL, "-m", "pytest", "-q", *tests], cwd=checkout, timeout=3600, check=False)
    evidence = {
        "schema": "mephc-flow-publish-evidence-v1", "created_at": time.time(),
        "source_commit": source["head"], "execution_checkout": checkout,
        "tests": tests, "return_code": result.returncode,
        "stdout_sha256": sha256_bytes(result.stdout.encode("utf-8")),
        "stderr_sha256": sha256_bytes(result.stderr.encode("utf-8")),
        "origin_main": remote_main, "prior_origin_sandbox": remote_sandbox,
    }
    evidence_path = paths.state / "publish" / f"{source['head']}.json"
    atomic_json(evidence_path, evidence)
    if result.returncode:
        raise FlowError("TESTS_FAILED", result.stdout[-2000:] + result.stderr[-2000:])
    before_push = require_source(paths)
    if before_push["head"] != source["head"]:
        raise FlowError("SOURCE_DRIFT_DURING_TESTS")
    current_main, current_sandbox = remote_refs(paths)
    if current_main != EXPECTED_MAIN:
        raise FlowError("ORIGIN_MAIN_MOVED")
    if current_sandbox != remote_sandbox:
        raise FlowError("REMOTE_SANDBOX_MOVED", safe_next="git-fetch-review")
    push = git(paths, "push", "origin", f"{source['head']}:refs/heads/sandbox", timeout=600, check=False)
    if push.returncode:
        raise FlowError("SANDBOX_PUSH_FAILED", (push.stderr or push.stdout)[-4000:])
    verified_main, verified_sandbox = remote_refs(paths)
    if verified_main != EXPECTED_MAIN or verified_sandbox != source["head"]:
        raise FlowError("REMOTE_VERIFICATION_FAILED")
    git(paths, "update-ref", "refs/remotes/origin/sandbox", source["head"])
    evidence.update({"published_at": time.time(), "published_sandbox": verified_sandbox})
    atomic_json(evidence_path, evidence)
    return {"state": "published", "source_commit": source["head"], "origin_main": verified_main,
            "origin_sandbox": verified_sandbox, "execution_checkout": checkout, "tests": tests}


def native_payload(
    work_order_id: str, source: str, cost: int, project: str, argv: list[str],
    scientific_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = {"work_order_id": work_order_id, "source_commit": source, "cost": cost, "project": project, "argv": argv}
    if scientific_contract is not None:
        value.update({
            "science_contract_sha256": scientific_contract["contract_sha256"],
            "provider_request_budget": scientific_contract["budgets"]["provider_requests"],
            "solver_execution_budget": scientific_contract["budgets"]["solver_executions"],
            "expected_output": scientific_contract["expected_output"],
        })
    return value


def native_usage(paths: Paths, work_order_id: str) -> int:
    total = 0
    root = paths.state / "native-runs"
    if not root.is_dir():
        return 0
    for item in root.glob("*.json"):
        value = read_json(item, default={})
        if isinstance(value, dict) and value.get("work_order_id") == work_order_id and value.get("process_started") is True:
            total += int(value.get("cost", 0))
    return total


def normalize_project(project: str, checkout: str, allowed: list[str]) -> str:
    if not project.startswith("/home/icy/") or ".." in PurePosixPath(project).parts:
        raise FlowError("PROJECT_PATH_OUT_OF_SCOPE")
    normalized = str(PurePosixPath(project))
    if normalized != checkout and normalized not in allowed:
        raise FlowError("PROJECT_PATH_NOT_WORK_ORDER_BOUND")
    probe = wsl(["/usr/bin/test", "-d", normalized], check=False)
    real = wsl(["/usr/bin/realpath", "-e", normalized]).stdout.strip() if probe.returncode == 0 else ""
    fstype = wsl(["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "--target", normalized], check=False).stdout.strip().lower()
    if probe.returncode or real != normalized or fstype in {"9p", "drvfs", "fuseblk", ""}:
        raise FlowError("PROJECT_PATH_NOT_LINUX_NATIVE_REAL_DIRECTORY")
    return normalized


def validate_native_argv(policy: dict[str, Any], checkout: str, argv: list[str]) -> None:
    if policy.get("arbitrary_native_command_authorized") is True:
        return
    entrypoint = policy.get("native_entrypoint")
    declared_arguments = policy.get("native_arguments") or []
    if entrypoint is not None:
        expected = [CONDA_PYTHON_WSL, entrypoint, *declared_arguments]
        if argv != expected:
            raise FlowError("NATIVE_COMMAND_NOT_WORK_ORDER_BOUND")
        script = entrypoint
    else:
        if len(argv) != 2 or argv[0] not in {"python", "python3", CONDA_PYTHON_WSL}:
            raise FlowError("NATIVE_COMMAND_NOT_FIXED_TRACKED_PYTHON_ENTRYPOINT")
        script = argv[1]
    relative = PurePosixPath(script.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
        raise FlowError("NATIVE_ENTRYPOINT_OUT_OF_SCOPE")
    tracked = wsl(["/usr/bin/git", "-C", checkout, "ls-files", "--error-unmatch", str(relative)], check=False)
    if tracked.returncode:
        raise FlowError("NATIVE_ENTRYPOINT_NOT_TRACKED_AT_SOURCE_SHA")


def run_native(
    paths: Paths, work_order_id: str, cost: int, project: str, argv: list[str],
    scientific_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if cost < 1 or not argv or any(not item or "\x00" in item for item in argv):
        raise FlowError("NATIVE_ARGUMENTS_INVALID")
    order = active_work_order(paths)
    if order["work_order_id"] != work_order_id:
        raise FlowError("WORK_ORDER_ID_MISMATCH")
    policy = work_order_policy(order["text"])
    effective = effective_policy(paths, order)
    if not policy["native_authorized"]:
        raise FlowError("NATIVE_NOT_AUTHORIZED")
    budget = effective["effective_native_budget"]
    if not isinstance(budget, int):
        raise FlowError("NATIVE_BUDGET_NOT_DECLARED")
    source = require_source(paths, published=True)
    checkout = ensure_checkout(paths, source["head"])
    project = normalize_project(project, checkout, policy["allowed_project_paths"])
    validate_native_argv(policy, checkout, argv)
    used = native_usage(paths, work_order_id)
    if used + cost > budget:
        raise FlowError("NATIVE_BUDGET_EXCEEDED")
    payload = native_payload(work_order_id, source["head"], cost, project, argv, scientific_contract)
    payload_hash = sha256_bytes(canonical_json(payload))
    run_id = "MEPHC-NATIVE-" + payload_hash[:24]
    run_path = paths.state / "native-runs" / f"{run_id}.json"
    existing = read_json(run_path, default=None)
    if isinstance(existing, dict):
        return {**existing, "reused": True, "safe_next": f"native-status {run_id}"}
    run_path.parent.mkdir(parents=True, exist_ok=True)
    claim_path = run_path.with_suffix(".claim")
    try:
        claim = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(claim)
    except FileExistsError:
        existing = read_json(run_path, default=None)
        if isinstance(existing, dict):
            return {**existing, "reused": True, "safe_next": f"native-status {run_id}"}
        raise FlowError("NATIVE_RUN_CREATION_IN_PROGRESS", safe_next=f"native-status {run_id}")
    record = {
        "schema": "mephc-flow-native-run-v1", "run_id": run_id, **payload,
        "payload_sha256": payload_hash, "state": "dispatching", "process_started": False,
        "created_at": time.time(), "used_before": used, "effective_budget": budget,
    }
    atomic_json(run_path, record)
    helper = f"{CONTROL_ROOT_WSL}/tools/mephc-flow/wsl_native_exec.py"
    result = wsl([CONDA_PYTHON_WSL, helper, "--state", f"{FLOW_STATE_WSL}/native-runs/{run_id}.json",
                  "--checkout", checkout, "--project", project, "--", *argv], timeout=7 * 24 * 3600, check=False)
    final = read_json(run_path, default=record)
    if not isinstance(final, dict):
        raise FlowError("NATIVE_STATE_INVALID")
    return {**final, "launcher_return_code": result.returncode, "reused": False}


def native_status(paths: Paths, run_id: str) -> dict[str, Any]:
    if not REQUEST_ID.fullmatch(run_id) or not run_id.startswith("MEPHC-NATIVE-"):
        raise FlowError("NATIVE_RUN_ID_INVALID")
    path = paths.state / "native-runs" / f"{run_id}.json"
    value = read_json(path, default=None)
    if not isinstance(value, dict) or value.get("run_id") != run_id:
        raise FlowError("NATIVE_RUN_NOT_FOUND")
    if value.get("state") in {"succeeded", "failed"}:
        reconciliation_path = paths.state / "reconciliations" / f"{run_id}.json"
        reconciliation = read_json(reconciliation_path, default=None)
        if (isinstance(reconciliation, dict)
                and reconciliation.get("original_native_run_id") == run_id
                and isinstance(reconciliation.get("canonical_result_summary"), dict)):
            return {
                **value,
                "reconciled": True,
                "reconciliation_status": reconciliation.get("reconciliation_status"),
                "reconciled_result_summary": reconciliation["canonical_result_summary"],
            }
        return value
    pid, start_ticks = value.get("pid"), value.get("linux_start_ticks")
    alive = False
    if isinstance(pid, int) and isinstance(start_ticks, str):
        result = wsl(["/usr/bin/cat", f"/proc/{pid}/stat"], check=False)
        fields = result.stdout.split()
        alive = result.returncode == 0 and len(fields) > 21 and fields[21] == start_ticks
    return {**value, "process_identity_alive": alive,
            "safe_next": f"native-status {run_id}" if alive else "human-reconciliation-required"}


def science_job_id(contract: dict[str, Any]) -> str:
    payload = {
        "contract_sha256": contract["contract_sha256"],
        "source_commit": contract["source_commit"],
        "entrypoint": contract["entrypoint"],
        "project": contract["project"],
        "action": contract["action"],
    }
    return "MEPHC-SCIENCE-" + sha256_bytes(canonical_json(payload))[:24]


def science_job_metrics(paths: Paths, contract: dict[str, Any], *, created: bool) -> None:
    path = paths.state / "workflow-metrics.json"
    value = read_json(path, default={})
    if not isinstance(value, dict):
        value = {}
    value.setdefault("schema", "mephc-flow-workflow-metrics-v1")
    value.setdefault("science_work_orders", [])
    value.setdefault("infrastructure_work_orders", [])
    target = value["science_work_orders" if contract["kind"] == "SCIENCE" else "infrastructure_work_orders"]
    if created and contract["work_order_id"] not in target:
        target.append(contract["work_order_id"])
    recent = value["infrastructure_work_orders"][-2:]
    value["workflow_overhead_excessive"] = len(recent) >= 2
    value["updated_at"] = time.time()
    atomic_json(path, value)


def science_acquire(paths: Paths) -> dict[str, Any]:
    preflight = science_preflight(paths)
    _, contract = active_machine_contract(paths)
    if contract["kind"] != "SCIENCE" or contract["action"] != "acquire":
        raise FlowError("SCIENCE_ACQUIRE_ACTION_NOT_AUTHORIZED")
    job_id = science_job_id(contract)
    job_path = paths.state / "science-jobs" / f"{job_id}.json"
    existing = read_json(job_path, default=None)
    if isinstance(existing, dict):
        return {**existing, "reused": True, "safe_next": f"science-status {job_id}"}
    record = {
        "schema": "mephc-scientific-job-v1", "job_id": job_id,
        "work_order_id": contract["work_order_id"], "contract_sha256": contract["contract_sha256"],
        "source_commit": contract["source_commit"], "action": "acquire", "state": "dispatching",
        "created_at": time.time(), "provenance": {
            "main_sha": EXPECTED_MAIN, "sandbox_sha": contract["source_commit"],
            "runtime_sha256": preflight["runtime_sha256"],
        },
    }
    atomic_json(job_path, record)
    science_job_metrics(paths, contract, created=True)
    result = run_native(
        paths, contract["work_order_id"], contract["budgets"]["native_invocations"],
        preflight["execution_checkout"], [CONDA_PYTHON_WSL, contract["entrypoint"]], contract,
    )
    final = {**record, "state": result.get("state"), "native_run_id": result.get("run_id"),
             "result": result, "completed_at": time.time()}
    atomic_json(job_path, final)
    return {**final, "reused": False, "safe_next": f"science-status {job_id}"}


def science_analyze(paths: Paths) -> dict[str, Any]:
    preflight = science_preflight(paths)
    _, contract = active_machine_contract(paths)
    if contract["kind"] != "SCIENCE" or contract["action"] != "analyze":
        raise FlowError("SCIENCE_ANALYZE_ACTION_NOT_AUTHORIZED")
    job_id = science_job_id(contract)
    job_path = paths.state / "science-jobs" / f"{job_id}.json"
    existing = read_json(job_path, default=None)
    if isinstance(existing, dict):
        return {**existing, "reused": True, "safe_next": f"science-status {job_id}"}
    record = {
        "schema": "mephc-scientific-job-v1", "job_id": job_id,
        "work_order_id": contract["work_order_id"], "contract_sha256": contract["contract_sha256"],
        "source_commit": contract["source_commit"], "action": "analyze", "state": "dispatching",
        "process_started": False, "provider_executions": 0, "solver_executions": 0,
        "created_at": time.time(), "provenance": {
            "main_sha": EXPECTED_MAIN, "sandbox_sha": contract["source_commit"],
            "runtime_sha256": preflight["runtime_sha256"],
        },
    }
    atomic_json(job_path, record)
    science_job_metrics(paths, contract, created=True)
    helper = f"{preflight['execution_checkout']}/tools/mephc-flow/wsl_native_exec.py"
    result = wsl([
        CONDA_PYTHON_WSL, helper, "--state", f"{FLOW_STATE_WSL}/science-jobs/{job_id}.json",
        "--checkout", preflight["execution_checkout"], "--project", preflight["execution_checkout"],
        "--", CONDA_PYTHON_WSL, contract["entrypoint"],
    ], timeout=24 * 3600, check=False)
    final = read_json(job_path, default=record)
    final.update({"provider_executions": 0, "solver_executions": 0,
                  "launcher_return_code": result.returncode})
    atomic_json(job_path, final)
    return {**final, "reused": False, "safe_next": f"science-status {job_id}"}


def science_status(paths: Paths, job_id: str) -> dict[str, Any]:
    if not REQUEST_ID.fullmatch(job_id) or not job_id.startswith("MEPHC-SCIENCE-"):
        raise FlowError("SCIENCE_JOB_ID_INVALID")
    path = paths.state / "science-jobs" / f"{job_id}.json"
    value = read_json(path, default=None)
    if not isinstance(value, dict) or value.get("job_id") != job_id:
        raise FlowError("SCIENCE_JOB_NOT_FOUND")
    native_run_id = value.get("native_run_id")
    if isinstance(native_run_id, str):
        return {**value, "native_status": native_status(paths, native_run_id)}
    if value.get("state") in {"succeeded", "failed"}:
        return value
    pid, start_ticks = value.get("pid"), value.get("linux_start_ticks")
    alive = False
    if isinstance(pid, int) and isinstance(start_ticks, str):
        result = wsl(["/usr/bin/cat", f"/proc/{pid}/stat"], check=False)
        fields = result.stdout.split()
        alive = result.returncode == 0 and len(fields) > 21 and fields[21] == start_ticks
    return {**value, "process_identity_alive": alive,
            "safe_next": f"science-status {job_id}" if alive else "human-reconciliation-required"}


def report_allowed(policy: str, kind: str) -> bool:
    if policy == "final-only":
        return kind == "complete"
    if policy == "milestone":
        return kind in {"milestone", "complete", "blocked"}
    return True


def courier_command(paths: Paths, operation: str, directory: Path, *, recovery: bool = False) -> subprocess.CompletedProcess[str]:
    argv = ["cmd.exe", "/d", "/s", "/c", str(paths.courier), operation, str(directory)]
    if recovery:
        argv.append("--recovery-only")
    return command(argv, timeout=4860, check=False)


def report(paths: Paths, work_order_id: str, kind: str, message_file: Path) -> dict[str, Any]:
    if kind not in REPORT_KINDS:
        raise FlowError("REPORT_KIND_INVALID")
    order = active_work_order(paths)
    if order["work_order_id"] != work_order_id:
        raise FlowError("WORK_ORDER_ID_MISMATCH")
    policy = effective_policy(paths, order)["report_policy"]
    if not report_allowed(policy, kind):
        raise FlowError("REPORT_POLICY_SUPPRESSED")
    if not message_file.is_file() or message_file.is_symlink():
        raise FlowError("MESSAGE_FILE_INVALID")
    message = message_file.read_bytes()
    try:
        text = message.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FlowError("MESSAGE_FILE_NOT_UTF8") from exc
    if not text.strip():
        raise FlowError("MESSAGE_FILE_EMPTY")
    message_hash = sha256_bytes(message)
    request_hash = sha256_bytes(canonical_json({"work_order_id": work_order_id, "kind": kind, "message_sha256": message_hash}))
    request_id = "MEPHC-FLOW-" + request_hash[:24]
    directory = paths.outbox / request_id
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir():
            raise FlowError("REQUEST_DIRECTORY_INVALID")
        prior = read_json(directory / "request.json", default={})
        if (prior.get("work_order_id"), prior.get("report_kind"), prior.get("message_sha256")) != (work_order_id, kind, message_hash):
            raise FlowError("REQUEST_IDEMPOTENCY_CONFLICT")
        summary = request_summary(directory)
        return {"state": "existing_request", **summary, "safe_next": f"courier-reconcile {request_id}"}
    paths.outbox.mkdir(parents=True, exist_ok=True)
    staging = paths.outbox / f".{request_id}.{os.getpid()}.tmp"
    staging.mkdir(parents=False, exist_ok=False)
    (staging / "message.txt").write_bytes(message)
    manifest = {
        "version": 1, "project_id": PROJECT_ID, "request_id": request_id,
        "message_file": "message.txt", "attachments": [], "workflow_window_seconds": 600,
        "queue_wait_seconds": 3600, "task_difficulty": "normal", "instruction_level": "normal",
        "flow_schema": "mephc-flow-report-v1", "work_order_id": work_order_id,
        "report_kind": kind, "message_sha256": message_hash, "idempotency_key": request_hash,
    }
    atomic_json(staging / "request.json", manifest)
    os.replace(staging, directory)
    validation = courier_command(paths, "validate", directory)
    if validation.returncode:
        raise FlowError("COURIER_VALIDATION_FAILED", (validation.stderr or validation.stdout)[-4000:])
    result = courier_command(paths, "run", directory)
    summary = request_summary(directory)
    atomic_json(directory / "flow-bridge.json", {
        "schema": "mephc-flow-courier-bridge-v1", "request_id": request_id,
        "message_sha256": message_hash, "return_code": result.returncode,
        "stdout_sha256": sha256_bytes(result.stdout.encode("utf-8")),
        "stderr_sha256": sha256_bytes(result.stderr.encode("utf-8")), "completed_at": time.time(),
    })
    consumed = consume_response(paths, directory) if summary["response_received"] else {}
    return {"state": "response_received" if summary["response_received"] else "courier_stopped",
            **summary, **consumed, "return_code": result.returncode,
            "safe_next": "resume" if summary["response_received"] else f"courier-reconcile {request_id}"}


def courier_reconcile(paths: Paths, request_id: str) -> dict[str, Any]:
    if not REQUEST_ID.fullmatch(request_id):
        raise FlowError("REQUEST_ID_INVALID")
    directory = paths.outbox / request_id
    if not directory.is_dir() or directory.is_symlink():
        raise FlowError("REQUEST_NOT_FOUND")
    manifest = read_json(directory / "request.json", default={})
    if manifest.get("project_id") != PROJECT_ID or manifest.get("request_id") != request_id:
        raise FlowError("REQUEST_BINDING_INVALID")
    summary = request_summary(directory)
    if summary["response_received"]:
        consumed = consume_response(paths, directory)
        return {"state": "response_received", **summary, **consumed, "safe_next": "resume"}
    recoverable = {"request_submitted", "waiting_for_response", "submission_unconfirmed", "chat_submission_unconfirmed",
                   "submission_state_uncertain", "response_timeout", "response_protocol_error"}
    if summary["receipt_state"] not in recoverable:
        return {"state": "not_recoverable_read_only", **summary,
                "safe_next": "report-same-request-only" if summary["submission_count"] == 0 else "human-reconciliation-required"}
    result = courier_command(paths, "run", directory, recovery=True)
    final = request_summary(directory)
    consumed = consume_response(paths, directory) if final["response_received"] else {}
    return {"state": "response_received" if final["response_received"] else "recovery_stopped",
            **final, **consumed, "return_code": result.returncode,
            "safe_next": "resume" if final["response_received"] else f"courier-reconcile {request_id}"}


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="mephc-flow")
    commands = result.add_subparsers(dest="command", required=True)
    start_cmd = commands.add_parser("start")
    start_cmd.add_argument("--report-policy", choices=sorted(REPORT_POLICIES))
    start_cmd.add_argument("--native-cap", type=int)
    commands.add_parser("status")
    commands.add_parser("resume")
    commands.add_parser("science-preflight")
    selftest_cmd = commands.add_parser("science-selftest")
    selftest_cmd.add_argument("--mpb-smoke", action="store_true")
    commands.add_parser("science-acquire")
    science_status_cmd = commands.add_parser("science-status")
    science_status_cmd.add_argument("job_id")
    dataset_cmd = commands.add_parser("dataset-verify")
    dataset_cmd.add_argument("dataset_id")
    commands.add_parser("science-analyze")
    publish_cmd = commands.add_parser("publish")
    publish_cmd.add_argument("--tests", nargs="+", required=True)
    native_cmd = commands.add_parser("run-native")
    native_cmd.add_argument("--work-order", required=True)
    native_cmd.add_argument("--cost", type=int, required=True)
    native_cmd.add_argument("--project", required=True)
    native_cmd.add_argument("argv", nargs=argparse.REMAINDER)
    native_status_cmd = commands.add_parser("native-status")
    native_status_cmd.add_argument("run_id")
    report_cmd = commands.add_parser("report")
    report_cmd.add_argument("--work-order", required=True)
    report_cmd.add_argument("--kind", choices=sorted(REPORT_KINDS), required=True)
    report_cmd.add_argument("--message-file", type=Path, required=True)
    commands.add_parser("reconcile-r8-native-result")
    reconcile_cmd = commands.add_parser("courier-reconcile")
    reconcile_cmd.add_argument("--request-id", required=True)
    return result


def main(argv: list[str] | None = None, *, paths: Paths = Paths()) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "start":
            value = start(paths, args.report_policy, args.native_cap)
        elif args.command == "status":
            value = status(paths)
        elif args.command == "resume":
            value = resume(paths)
        elif args.command == "science-preflight":
            value = science_preflight(paths)
        elif args.command == "science-selftest":
            value = science_selftest(paths, mpb_smoke=args.mpb_smoke)
        elif args.command == "science-acquire":
            value = science_acquire(paths)
        elif args.command == "science-status":
            value = science_status(paths, args.job_id)
        elif args.command == "dataset-verify":
            value = dataset_verify(paths, args.dataset_id)
        elif args.command == "science-analyze":
            value = science_analyze(paths)
        elif args.command == "publish":
            value = publish(paths, args.tests)
        elif args.command == "run-native":
            argv_value = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
            value = run_native(paths, args.work_order, args.cost, args.project, argv_value)
        elif args.command == "native-status":
            value = native_status(paths, args.run_id)
        elif args.command == "report":
            value = report(paths, args.work_order, args.kind, args.message_file.resolve())
        elif args.command == "reconcile-r8-native-result":
            helper = f"{CONTROL_ROOT_WSL}/tools/mephc-flow/reconcile_r8_native_result.py"
            result = wsl([CONDA_PYTHON_WSL, helper], timeout=3600, check=False)
            if result.returncode:
                raise FlowError("R8_RECONCILIATION_FAILED", (result.stderr or result.stdout)[-8000:])
            try:
                value = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise FlowError("R8_RECONCILIATION_OUTPUT_INVALID", result.stdout[-4000:]) from exc
            if not isinstance(value, dict):
                raise FlowError("R8_RECONCILIATION_OUTPUT_INVALID")
        else:
            value = courier_reconcile(paths, args.request_id)
        emit(value)
        return 0
    except FlowError as exc:
        emit({"ok": False, "error_code": exc.code, "detail": exc.detail,
              "retry_allowed": False, "safe_next": exc.safe_next})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
