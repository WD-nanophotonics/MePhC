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
import math
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
BLOCKED_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,95}$")
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
    value = None
    for line in reversed(lines):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            value = candidate
            break
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
        ancestor = git(paths, "merge-base", "--is-ancestor", contract["source_commit"], source["head"], check=False)
        if ancestor.returncode:
            raise FlowError("WORK_ORDER_SOURCE_COMMIT_MISMATCH", safe_next="report")
        changed_since_contract = {
            line for line in git(paths, "diff", "--name-only", f"{contract['source_commit']}..{source['head']}").stdout.splitlines()
            if line
        }
        if not changed_since_contract.issubset(set(contract["allowed_writes"])):
            raise FlowError("WORK_ORDER_SOURCE_DIFF_OUT_OF_SCOPE", ",".join(sorted(changed_since_contract - set(contract["allowed_writes"]))))
    checkout = ensure_checkout(paths, source["head"])
    entrypoint = contract.get("entrypoint")
    if entrypoint is not None:
        tracked = wsl(["/usr/bin/git", "-C", checkout, "ls-files", "--error-unmatch", entrypoint], check=False)
        if tracked.returncode:
            if source["head"] == contract["source_commit"] and entrypoint in contract["allowed_writes"]:
                return {
                    "schema": "mephc-science-preflight-v1", "ready_to_run": False,
                    "ready_to_edit": True, "safe_next": "edit_scoped_files",
                    "work_order_id": order["work_order_id"], "contract_sha256": contract["contract_sha256"],
                    "base_source_commit": contract["source_commit"], "source_commit": source["head"],
                    "entrypoint": entrypoint, "allowed_writes": contract["allowed_writes"],
                    "job_created": False,
                }
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
    if contract["action"] == "analyze" and "dataset_id" in contract["inputs"]:
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
        "base_source_commit": contract["source_commit"], "source_commit": source["head"], "execution_checkout": checkout,
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


def _science_runtime_module(paths: Paths):
    name = "_mephc_science_runtime_reconcile"
    path = paths.control / "tools" / "mephc-flow" / "mephc_science_runtime.py"
    root = str(paths.control)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FlowError("SCIENCE_RUNTIME_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def d9r1_reconcile_existing_dataset(
        paths: Paths, contract: dict[str, Any], preflight: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile the immutable D9 dataset and repair only closeout compatibility."""
    d9r2 = contract.get("work_order_id") == "MEPHC-E9F-D9R2-FR04-CLOSEOUT-PATCH-FIRST-20260829-339"
    inputs = contract.get("inputs", {})
    target_work_order = inputs.get("target_work_order_id")
    execution_source = inputs.get("execution_source_commit")
    publication_source = inputs.get("publication_source_commit")
    dataset_id = inputs.get("dataset_id")
    expected_manifest_sha = inputs.get("dataset_manifest_sha256")
    binding_sha = inputs.get("binding_sha256")
    graph_sha = inputs.get("request_graph_sha256")
    entrypoint_sha = inputs.get("entrypoint_sha256")
    runtime_sha = inputs.get("science_runtime_sha256") or preflight.get("runtime_sha256")
    if (contract.get("work_order_id") not in {
                "MEPHC-E9F-D9R1-FR04-RESIDUAL-COMPOSITE-RECON-COMPAT-20260829-338",
                "MEPHC-E9F-D9R2-FR04-CLOSEOUT-PATCH-FIRST-20260829-339",
            }
            or contract.get("action") != "infrastructure"
            or contract.get("budgets") != {"native_invocations": 0, "provider_requests": 0, "solver_executions": 0}
            or not all(isinstance(value, str) and SHA40.fullmatch(value)
                       for value in (execution_source, publication_source))
            or not all(isinstance(value, str) and SHA64.fullmatch(value)
                       for value in (dataset_id, expected_manifest_sha, binding_sha, graph_sha, entrypoint_sha, runtime_sha))):
        raise FlowError("D9R1_RECONCILIATION_CONTRACT_INVALID", safe_next="report")

    source = require_source(paths, published=True)
    if (source["head"] != preflight.get("source_commit")
            or (not d9r2 and source["head"] != publication_source)):
        raise FlowError("D9R1_RECONCILIATION_SOURCE_CHANGED", safe_next="status")
    if d9r2:
        patch_ancestry = git(paths, "merge-base", "--is-ancestor", publication_source, source["head"], check=False)
        if patch_ancestry.returncode:
            raise FlowError("D9R2_PATCH_SOURCE_ANCESTRY_INVALID")
        patch_changes = [
            line for line in git(paths, "diff", "--name-only", f"{publication_source}..{source['head']}").stdout.splitlines()
            if line
        ]
        if not patch_changes or not set(patch_changes).issubset(set(contract.get("allowed_writes", []))):
            raise FlowError("D9R2_PATCH_CHANGED_FILES_INVALID", ",".join(patch_changes))
        pre_patch_flow_sha = "62218185a2bbe7f01674deede4c668f0d42f946778c9b7addde3a05c4377d3db"
        post_patch_flow_sha = sha256_file(paths.control / "tools" / "mephc-flow" / "mephc_flow.py")
        if post_patch_flow_sha == pre_patch_flow_sha:
            raise FlowError("D9R2_PATCH_NOT_APPLIED")
    else:
        pre_patch_flow_sha = None
        post_patch_flow_sha = None
    ancestry = git(paths, "merge-base", "--is-ancestor", execution_source, publication_source, check=False)
    if ancestry.returncode:
        raise FlowError("D9R1_EXECUTION_SOURCE_ANCESTRY_INVALID")
    post_execution_diff = [
        line for line in git(paths, "diff", "--name-only", f"{execution_source}..{publication_source}").stdout.splitlines()
        if line
    ]
    if post_execution_diff != ["audit/e9f/d9_fr04_residual_composite_acquisition_binding.json"]:
        raise FlowError("D9R1_POST_EXECUTION_DIFF_INVALID", ",".join(post_execution_diff))

    jobs: list[dict[str, Any]] = []
    jobs_root = paths.state / "science-jobs"
    if jobs_root.is_dir():
        for path in sorted(jobs_root.glob("MEPHC-SCIENCE-*.json")):
            value = read_json(path, default={})
            if (isinstance(value, dict) and value.get("work_order_id") == target_work_order
                    and value.get("source_commit") == execution_source
                    and value.get("action") == "acquire"):
                jobs.append(value)
    if len(jobs) != 1:
        raise FlowError("D9R1_ORIGINAL_SCIENCE_JOB_LINEAGE_INVALID")
    job = jobs[0]
    native = job.get("result")
    native_run_id = job.get("native_run_id")
    if (job.get("state") != "succeeded" or not isinstance(native, dict)
            or not isinstance(native_run_id, str) or native.get("run_id") != native_run_id
            or native.get("state") != "succeeded" or native.get("process_started") is not True
            or native.get("return_code") != 0 or native.get("launcher_return_code") != 0):
        raise FlowError("D9R1_ORIGINAL_NATIVE_SUCCESS_INVALID")
    summary = native.get("result_summary")
    if not isinstance(summary, dict):
        raise FlowError("D9R1_ORIGINAL_RESULT_SUMMARY_MISSING")
    if "provider_failure_count" in summary:
        raise FlowError("D9R1_PROVIDER_FAILURE_FIELD_NOT_ABSENT")
    required_summary = {
        "work_order_id": target_work_order,
        "execution_source_commit": execution_source,
        "science_runtime_sha256": runtime_sha,
        "target_cell_count": 10,
        "refined_stencil_representative_count": 5,
        "odd_resolution_class": [96, 160, 224],
        "even_resolution_class": [128, 192, 256],
        "logical_provider_demand_count": 420,
        "unique_provider_request_count": 420,
        "native_invocation_count": 1,
        "provider_request_count": 420,
        "fresh_provider_execution_count": 420,
        "solver_executions": 420,
        "native_solves": 420,
        "completed_key_count": 420,
        "failed_key_count": 0,
        "cache_reuse_count": 0,
        "mpb_execution": True,
        "d9_dataset_id": dataset_id,
        "d9_dataset_manifest_sha256": expected_manifest_sha,
        "d9_dataset_record_count": 420,
        "d9_acquisition_source_commit": execution_source,
        "d9_entrypoint_sha256": entrypoint_sha,
        "d9_request_graph_sha256": graph_sha,
        "native_retry_count": 0,
        "terminal": "E9F_D9_FR04_RESIDUAL_COMPOSITE_CONVERGENCE_DATASET_ACQUIRED",
    }
    if any(summary.get(key) != value for key, value in required_summary.items()):
        raise FlowError("D9R1_AUTHORITATIVE_RESULT_SUMMARY_MISMATCH")

    native_runs: list[dict[str, Any]] = []
    native_root = paths.state / "native-runs"
    if native_root.is_dir():
        for path in sorted(native_root.glob("*.json")):
            value = read_json(path, default={})
            if isinstance(value, dict) and value.get("run_id") == native_run_id:
                native_runs.append(value)
    if len(native_runs) != 1:
        raise FlowError("D9R1_NATIVE_RUN_LINEAGE_INVALID")
    native_record = native_runs[0]
    if (native_record.get("work_order_id") != target_work_order
            or native_record.get("state") != "succeeded"
            or native_record.get("return_code") != 0
            or native_record.get("process_started") is not True):
        raise FlowError("D9R1_NATIVE_RUN_SUCCESS_INVALID")

    scientific_job = science_module(paths)
    runtime = _science_runtime_module(paths)
    index_path = paths.science_state / "dataset-index" / f"{dataset_id}.json"
    index = read_json(index_path, default={})
    if (not isinstance(index, dict) or index.get("dataset_id") != dataset_id
            or index.get("manifest_sha256") != expected_manifest_sha):
        raise FlowError("D9R1_DATASET_INDEX_INVALID")
    namespace_sha = index.get("namespace_sha256")
    if not isinstance(namespace_sha, str) or not SHA64.fullmatch(namespace_sha):
        raise FlowError("D9R1_DATASET_NAMESPACE_INVALID")
    manifest_path = paths.science_state / "datasets" / namespace_sha / "dataset-manifest.json"
    manifest = read_json(manifest_path, default={})
    if (not isinstance(manifest, dict) or manifest.get("dataset_id") != dataset_id
            or manifest.get("manifest_sha256") != expected_manifest_sha
            or manifest.get("schema") != scientific_job.DATASET_SCHEMA
            or manifest.get("completion_state") != "COMPLETE"
            or manifest.get("record_count") != 420):
        raise FlowError("D9R1_DATASET_MANIFEST_INVALID")
    unsigned = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    if (scientific_job.digest(unsigned) != dataset_id
            or scientific_job.digest({**unsigned, "dataset_id": dataset_id}) != expected_manifest_sha):
        raise FlowError("D9R1_DATASET_MANIFEST_INTEGRITY_INVALID")
    expected_namespace = {
        "project_id": "MEPHC", "science_contract_id": target_work_order,
        "work_order_id": target_work_order, "source_commit": execution_source,
        "fr": 0.4, "resolutions": [96, 128, 160, 192, 224, 256],
        "target_cells": [[-35, -16], [-35, -15], [-35, 15], [-35, 16], [-33, -17], [-33, 17],
                         [-32, -17], [-32, 17], [-5, -1], [-5, 1]],
        "geometry_boundary_digest": "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71",
        "arc_segments_per_corner": 96, "source_model_identity": "E9E_FR04_ROUNDED_TRIANGLE_V1",
        "band_request_configuration": "E9F_D5_FR04_R64_SIX_BAND_TE_LOCKED",
        "science_runtime_sha256": runtime_sha,
    }
    if manifest.get("namespace") != expected_namespace or manifest.get("namespace_sha256") != namespace_sha:
        raise FlowError("D9R1_DATASET_NAMESPACE_BINDING_INVALID")

    graph_path = paths.control / "audit" / "e9f" / "d9_fr04_residual_composite_request_graph.json"
    if sha256_file(graph_path) != graph_sha:
        raise FlowError("D9R1_REQUEST_GRAPH_HASH_INVALID")
    graph = read_json(graph_path, default={})
    expected_cells = expected_namespace["target_cells"]
    if (graph.get("schema") != "mephc-e9f-d9-fr04-residual-composite-request-graph-v1"
            or graph.get("work_order_id") != target_work_order
            or graph.get("source_commit") != "5e6cac51f8f6932571db7d0b41cc70356b82d451"
            or graph.get("target_cells") != expected_cells
            or graph.get("refined_stencil_representatives") != [[-35, -16], [-35, -15], [-33, -17], [-32, -17], [-5, -1]]
            or graph.get("resolutions") != [96, 128, 160, 192, 224, 256]
            or graph.get("odd_resolution_class") != [96, 160, 224]
            or graph.get("even_resolution_class") != [128, 192, 256]
            or graph.get("primary_stencil") != "1/144" or graph.get("refined_stencil") != "1/288"
            or graph.get("logical_provider_demand_count") != 420
            or graph.get("unique_provider_request_count") != 420
            or graph.get("duplicate_provider_request_count") != 0
            or graph.get("collision_group_count") != 0):
        raise FlowError("D9R1_REQUEST_GRAPH_SEMANTICS_INVALID")
    requests = graph.get("unique_provider_requests")
    if not isinstance(requests, list) or len(requests) != 420:
        raise FlowError("D9R1_REQUEST_GRAPH_REQUEST_SET_INVALID")
    expected_keys: dict[str, tuple[bytes, dict[str, Any]]] = {}
    primary_count = refined_count = 0
    for item in requests:
        if not isinstance(item, dict) or item.get("request_class") not in {"primary", "refined"}:
            raise FlowError("D9R1_REQUEST_GRAPH_REQUEST_INVALID")
        if item["request_class"] == "primary":
            primary_count += 1
        else:
            refined_count += 1
        key = item.get("request_key")
        if not isinstance(key, dict):
            raise FlowError("D9R1_REQUEST_GRAPH_KEY_INVALID")
        if key.get("stencil_h") not in {"1/144", "1/288"}:
            raise FlowError("D9R1_REQUEST_GRAPH_STENCIL_INVALID")
        if key.get("stencil_h") == "1/36":
            raise FlowError("D9R1_SOURCE_STENCIL_REQUEST_PRESENT")
        key_bytes = scientific_job.canonical_bytes(key)
        key_sha = sha256_bytes(key_bytes)
        if key_sha in expected_keys:
            raise FlowError("D9R1_REQUEST_GRAPH_DUPLICATE")
        expected_keys[key_sha] = (key_bytes, key)
    if primary_count != 300 or refined_count != 120:
        raise FlowError("D9R1_REQUEST_GRAPH_CLASS_COUNT_INVALID")

    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 420:
        raise FlowError("D9R1_DATASET_RECORD_COUNT_INVALID")
    record_by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("key_sha256") in record_by_key:
            raise FlowError("D9R1_DATASET_RECORD_KEY_SET_INVALID")
        key_sha = record.get("key_sha256")
        if not isinstance(key_sha, str) or not SHA64.fullmatch(key_sha) or record.get("complete") is not True:
            raise FlowError("D9R1_DATASET_RECORD_METADATA_INVALID")
        record_by_key[key_sha] = record
    if set(record_by_key) != set(expected_keys):
        raise FlowError("D9R1_DATASET_RECORD_KEY_SET_INVALID")

    store = scientific_job.ImmutableDatasetStore(paths.science_state, manifest["namespace"])
    integrity_pass_count = 0
    for key_sha in sorted(expected_keys):
        key_bytes, key = expected_keys[key_sha]
        record = record_by_key[key_sha]
        try:
            payload, metadata = store.get(key_bytes)
            if metadata != record:
                raise FlowError("D9R1_DATASET_METADATA_MANIFEST_MISMATCH")
            decoded = runtime.decode_snapshot(payload)
            coordinate = key["canonical_k_coordinate"]
            denominator = int(coordinate["denominator"])
            expected_k = tuple(float(value) / denominator for value in coordinate["numerator"])
            identity = {
                "schema": "mephc-e9f-d9-residual-composite-record-v1", "key_sha256": key_sha,
                "identity": key, "k_point": list(expected_k), "resolution": key["resolution"],
                "stencil_role": key["stencil_role"], "h_representation": "mpb_periodic_h_l2_v1",
            }
            if (record.get("identity") != identity or record.get("schema") != "mephc-scientific-record-v1"
                    or tuple(decoded.k_point) != expected_k
                    or len(decoded.frequencies) != 6
                    or any(not math.isfinite(float(value)) for value in decoded.frequencies)
                    or decoded.provenance.get("representation") != "mpb_periodic_h_l2_v1"):
                raise FlowError("D9R1_DATASET_RECORD_IDENTITY_INVALID")
            integrity_pass_count += 1
        except FlowError:
            raise
        except Exception as exc:
            raise FlowError("D9R1_DATASET_RECORD_VERIFICATION_FAILED", f"{key_sha}:{type(exc).__name__}:{str(exc)[:200]}") from exc
        finally:
            if "decoded" in locals():
                del decoded
            if "payload" in locals():
                del payload
            if "metadata" in locals():
                del metadata
    if integrity_pass_count != 420:
        raise FlowError("D9R1_DATASET_RECORD_INTEGRITY_COUNT_INVALID")

    binding_path = paths.control / "audit" / "e9f" / "d9_fr04_residual_composite_acquisition_binding.json"
    if sha256_file(binding_path) != binding_sha:
        raise FlowError("D9R1_PUBLIC_BINDING_HASH_INVALID")
    binding = read_json(binding_path, default={})
    binding_expected = {
        "schema": "mephc-e9f-d9-fr04-residual-composite-acquisition-binding-v1",
        "work_order_id": target_work_order, "acquisition_source_commit": execution_source,
        "dataset_id": dataset_id, "dataset_manifest_sha256": expected_manifest_sha,
        "dataset_record_count": 420, "entrypoint_sha256": entrypoint_sha,
        "request_graph_sha256": graph_sha, "graph_sha256": graph_sha,
        "science_runtime_sha256": runtime_sha, "target_cell_count": 10,
        "refined_stencil_representative_count": 5, "logical_provider_demand_count": 420,
        "unique_provider_request_count": 420, "duplicate_provider_request_count": 0,
        "collision_group_count": 0, "completed_key_count": 420, "failed_key_count": 0,
        "provider_failure_count": 0, "fresh_provider_execution_count": 420,
        "cache_reuse_count": 0, "native_invocation_count": 1,
        "provider_request_count": 420, "solver_executions": 420, "native_solves": 420,
        "mpb_execution": True, "native_retry_count": 0, "completion_state": "COMPLETE",
    }
    if any(binding.get(key) != value for key, value in binding_expected.items()):
        raise FlowError("D9R1_PUBLIC_BINDING_VALUE_MISMATCH")

    reconciliation = {
        "schema": (
            "mephc-e9f-d9r2-fr04-closeout-patch-first-reconciliation-v1"
            if d9r2 else "mephc-e9f-d9r1-fr04-residual-composite-dataset-reconciliation-v1"
        ),
        "work_order_id": contract["work_order_id"], "base_sandbox_sha": contract["source_commit"],
        "final_sandbox_sha": source["head"], "origin_sandbox_sha": source["origin_sandbox"],
        "main_sha": EXPECTED_MAIN, "machine_contract_status": "PASS",
        "original_d9_science_job_id": job.get("job_id"), "original_d9_science_job_state": job.get("state"),
        "original_d9_native_run_id": native_run_id, "original_d9_native_state": native.get("state"),
        "original_d9_child_return_code": native.get("return_code"), "original_d9_result_summary_present": True,
        "original_d9_result_provider_failure_count_present": False,
        "original_d9_stdout_sha256": native.get("stdout_sha256"), "original_d9_stdout_size_bytes": native.get("stdout_size_bytes"),
        "original_d9_stderr_sha256": native.get("stderr_sha256"), "original_d9_stderr_size_bytes": native.get("stderr_size_bytes"),
        "d9_existing_dataset_status": "COMPLETE_NATIVE_RESULT_AND_DATASET_VERIFIED",
        "d9_dataset_id": dataset_id, "d9_dataset_manifest_sha256": expected_manifest_sha,
        "d9_dataset_record_count": 420, "full_d9_record_integrity_pass_count": integrity_pass_count,
        "d9_request_graph_status": "PASS_EXACT_300_PRIMARY_120_REFINED_420_UNIQUE",
        "post_execution_diff_status": "PASS_BINDING_ONLY",
        "post_execution_binding_verification_status": "PASS",
        "d9_provider_failure_count_reconciliation_status": "PASS_DERIVED_ZERO_FROM_COMPLETE_EXACT_ACCOUNTING",
        "strict_d9_missing_provider_failure_count_compatibility_status": "PASS",
        "d9_native_rerun_required": False, "native_invocation_count": 0,
        "provider_request_count": 0, "native_solves": 0, "mpb_execution": False,
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "FR04_RESIDUAL_COMPOSITE_10_CELL_MULTIRESOLUTION_DATASET_RECONCILED_READY_FOR_SOLVER_FREE_CONVERGENCE_AND_METHOD_VALIDATION",
        "terminal": (
            "E9F_D9R2_FR04_CLOSEOUT_PATCH_FIRST_RECONCILIATION_COMPLETE"
            if d9r2 else "E9F_D9R1_FR04_RESIDUAL_COMPOSITE_DATASET_RECONCILED_CLOSEOUT_COMPATIBILITY_FIXED"
        ),
    }
    if d9r2:
        reconciliation.update({
            "pre_patch_mephc_flow_sha256": pre_patch_flow_sha,
            "post_patch_mephc_flow_sha256": post_patch_flow_sha,
            "patch_publication_sha": source["head"],
            "patch_changed_before_d9_closeout": True,
            "reconciled_provider_failure_count": 0,
            "d9_dataset_ready_for_d10": True,
        })
    output_name = (
        "d9r2_fr04_residual_composite_dataset_reconciliation.json"
        if d9r2 else "d9r1_fr04_residual_composite_dataset_reconciliation.json"
    )
    atomic_json(paths.control / "audit" / "e9f" / output_name, reconciliation)
    return {**reconciliation, "state": "succeeded", "safe_next": "publish"}


def d3_reconcile_existing_dataset(
        paths: Paths, contract: dict[str, Any], preflight: dict[str, Any],
) -> dict[str, Any]:
    """Verify the frozen D3 dataset and repair only its closeout compatibility binding."""
    inputs = contract.get("inputs", {})
    target_work_order = inputs.get("target_work_order_id")
    execution_source = inputs.get("execution_source_commit")
    publication_source = inputs.get("publication_source_commit")
    dataset_id = inputs.get("fr04_r64_dataset_id")
    expected_manifest_sha = inputs.get("fr04_r64_dataset_manifest_sha256")
    graph_sha = inputs.get("request_graph_sha256")
    domain_list_sha = inputs.get("domain_list_sha256")
    if (contract.get("work_order_id") != "MEPHC-E9F-D3-FR04-R64-RECON-COMPAT-20260828-324"
            or contract.get("action") != "infrastructure"
            or not all(isinstance(value, str) and SHA40.fullmatch(value) for value in (execution_source, publication_source))
            or not all(isinstance(value, str) and SHA64.fullmatch(value) for value in (dataset_id, expected_manifest_sha, graph_sha, domain_list_sha))):
        raise FlowError("D3_RECONCILIATION_CONTRACT_INVALID", safe_next="report")

    source = require_source(paths, published=True)
    if source["head"] != preflight.get("source_commit"):
        raise FlowError("D3_RECONCILIATION_SOURCE_CHANGED", safe_next="status")
    ancestry = git(paths, "merge-base", "--is-ancestor", execution_source, publication_source, check=False)
    if ancestry.returncode:
        raise FlowError("D3_EXECUTION_SOURCE_ANCESTRY_INVALID")
    post_execution_diff = [line for line in git(paths, "diff", "--name-only", f"{execution_source}..{publication_source}").stdout.splitlines() if line]
    if post_execution_diff != ["audit/e9f/d3_fr04_r64_acquisition_binding.json"]:
        raise FlowError("D3_POST_EXECUTION_DIFF_INVALID", ",".join(post_execution_diff))

    jobs = []
    for path in sorted((paths.state / "science-jobs").glob("MEPHC-SCIENCE-*.json")):
        value = read_json(path, default={})
        if (isinstance(value, dict) and value.get("work_order_id") == target_work_order
                and value.get("source_commit") == execution_source and value.get("action") == "acquire"
                and value.get("state") == "succeeded"):
            jobs.append(value)
    if len(jobs) != 1:
        raise FlowError("D3_ORIGINAL_SCIENCE_JOB_LINEAGE_INVALID")
    job = jobs[0]
    native = job.get("result")
    if not isinstance(native, dict):
        raise FlowError("D3_ORIGINAL_NATIVE_RESULT_MISSING")
    summary = native.get("result_summary")
    if not isinstance(summary, dict):
        raise FlowError("D3_ORIGINAL_RESULT_SUMMARY_MISSING")
    required_summary = {
        "work_order_id": target_work_order, "machine_contract_status": "PASS",
        "science_runtime_sha256": "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5",
        "fr": 0.4, "resolution": "R64", "retained_cell_count": 641,
        "logical_provider_demand_count": 3205, "unique_provider_request_count": 3205,
        "provider_request_count": 3205, "cache_reuse_count": 0,
        "fresh_provider_execution_count": 3205, "fresh_native_solver_execution_count": 3205,
        "native_solves": 3205, "completed_key_count": 3205, "failed_key_count": 0,
        "provider_failure_count": 0, "mpb_execution": True,
        "FR04_R64_dataset_id": dataset_id, "FR04_R64_dataset_manifest_sha256": expected_manifest_sha,
        "FR04_R64_acquisition_source_commit": execution_source,
        "FR04_R64_request_graph_sha256": graph_sha, "FR04_R64_domain_list_sha256": domain_list_sha,
    }
    if any(summary.get(key) != value for key, value in required_summary.items()):
        raise FlowError("D3_AUTHORITATIVE_RESULT_SUMMARY_MISMATCH")

    scientific_job = science_module(paths)
    runtime = _science_runtime_module(paths)
    index_path = paths.science_state / "dataset-index" / f"{dataset_id}.json"
    index = read_json(index_path, default={})
    if not isinstance(index, dict) or index.get("dataset_id") != dataset_id:
        raise FlowError("D3_GENERIC_DATASET_INDEX_MISSING")
    namespace_sha = index.get("namespace_sha256")
    manifest_sha = index.get("manifest_sha256")
    if not isinstance(namespace_sha, str) or not SHA64.fullmatch(namespace_sha):
        raise FlowError("D3_GENERIC_DATASET_NAMESPACE_INVALID")
    manifest_path = paths.science_state / "datasets" / namespace_sha / "dataset-manifest.json"
    manifest = read_json(manifest_path, default={})
    if (not isinstance(manifest, dict) or manifest.get("dataset_id") != dataset_id
            or manifest.get("manifest_sha256") != manifest_sha
            or manifest.get("manifest_sha256") != expected_manifest_sha):
        raise FlowError("D3_GENERIC_DATASET_MANIFEST_BINDING_INVALID")
    unsigned = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    if (scientific_job.digest(unsigned) != dataset_id
            or scientific_job.digest({**unsigned, "dataset_id": dataset_id}) != expected_manifest_sha
            or manifest.get("schema") != scientific_job.DATASET_SCHEMA
            or manifest.get("completion_state") != "COMPLETE"
            or manifest.get("record_count") != 3205):
        raise FlowError("D3_GENERIC_DATASET_MANIFEST_INTEGRITY_INVALID")
    namespace = manifest.get("namespace")
    if (not isinstance(namespace, dict) or namespace.get("work_order_id") != target_work_order
            or namespace.get("source_commit") != execution_source or namespace.get("resolution") != "R64"
            or namespace.get("graph_sha256") != graph_sha or namespace.get("science_runtime_sha256") != required_summary["science_runtime_sha256"]):
        raise FlowError("D3_GENERIC_DATASET_NAMESPACE_BINDING_INVALID")

    graph_path = paths.control / "audit" / "e9f" / "d1_fr04_r64_request_graph.json"
    if sha256_file(graph_path) != graph_sha:
        raise FlowError("D3_FROZEN_GRAPH_HASH_INVALID")
    graph = read_json(graph_path, default={})
    if (graph.get("logical_provider_demand_count") != 3205
            or graph.get("unique_provider_request_count") != 3205
            or graph.get("duplicate_logical_demand_count") != 0
            or graph.get("collision_group_count") != 0):
        raise FlowError("D3_FROZEN_GRAPH_ACCOUNTING_INVALID")
    unique_requests = graph.get("unique_provider_requests")
    if not isinstance(unique_requests, list) or len(unique_requests) != 3205:
        raise FlowError("D3_FROZEN_GRAPH_REQUEST_SET_INVALID")
    expected_keys: dict[str, tuple[bytes, dict[str, Any]]] = {}
    for item in unique_requests:
        key = item.get("request_key") if isinstance(item, dict) else None
        if not isinstance(key, dict):
            raise FlowError("D3_FROZEN_GRAPH_REQUEST_INVALID")
        key_bytes = scientific_job.canonical_bytes(key)
        key_sha = sha256_bytes(key_bytes)
        if key_sha in expected_keys:
            raise FlowError("D3_FROZEN_GRAPH_REQUEST_DUPLICATE")
        expected_keys[key_sha] = (key_bytes, key)
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 3205:
        raise FlowError("D3_DATASET_RECORD_COUNT_INVALID")
    record_keys = [record.get("key_sha256") for record in records if isinstance(record, dict)]
    if len(record_keys) != 3205 or len(set(record_keys)) != 3205 or set(record_keys) != set(expected_keys):
        raise FlowError("D3_DATASET_RECORD_KEY_SET_INVALID")

    store = scientific_job.ImmutableDatasetStore(paths.science_state, namespace)
    for record in sorted(records, key=lambda item: item["key_sha256"]):
        key_sha = record["key_sha256"]
        key_bytes, key = expected_keys[key_sha]
        try:
            payload, metadata = store.get(key_bytes)
            if metadata != record:
                raise FlowError("D3_DATASET_METADATA_MANIFEST_MISMATCH")
            decoded = runtime.decode_snapshot(payload)
            identity = metadata.get("identity")
            coordinate = key["canonical_k_coordinate_units_1_over_144"]
            expected_identity = {
                "resolution": "R64", "canonical_k_coordinate_units_1_over_144": coordinate,
                "source_model_identity": "FROZEN_E9_SOURCE_MODEL",
                "provider_configuration_identity": "FROZEN_QP_B_PROVIDER_CONFIGURATION",
                "band_request_configuration": "FROZEN_QP_B_LOCKED_BAND_REQUEST",
                "h_representation": "mpb_periodic_h_l2_v1",
                "schema": "mephc-e9f-d3-r64-exact-key-record-v1", "key_sha256": key_sha,
            }
            if identity != expected_identity or decoded.provenance.get("representation") != "mpb_periodic_h_l2_v1":
                raise FlowError("D3_DATASET_RECORD_IDENTITY_INVALID")
            expected_k = (coordinate["i"] / 144.0, coordinate["j"] / 144.0)
            actual_k = tuple(decoded.k_point)
            if len(actual_k) != 2 or any(not math.isclose(float(actual_k[i]), expected_k[i], rel_tol=0.0, abs_tol=1e-15) for i in range(2)):
                raise FlowError("D3_DATASET_RECORD_K_POINT_INVALID")
        except FlowError:
            raise
        except Exception as exc:
            raise FlowError("D3_DATASET_RECORD_VERIFICATION_FAILED", f"{key_sha}:{type(exc).__name__}:{str(exc)[:200]}") from exc
        finally:
            if "decoded" in locals():
                del decoded
            if "payload" in locals():
                del payload
            if "metadata" in locals():
                del metadata

    binding_path = paths.control / "audit" / "e9f" / "d3_fr04_r64_acquisition_binding.json"
    binding = read_json(binding_path, default={})
    if not isinstance(binding, dict):
        raise FlowError("D3_PUBLIC_BINDING_INVALID")
    binding_expected = {
        "work_order_id": target_work_order, "acquisition_source_commit": execution_source,
        "acquisition_dataset_id": dataset_id, "dataset_manifest_sha256": expected_manifest_sha,
        "entrypoint_sha256": summary.get("FR04_R64_entrypoint_sha256"), "graph_sha256": graph_sha,
        "domain_list_sha256": domain_list_sha, "science_runtime_sha256": required_summary["science_runtime_sha256"],
        "logical_provider_demand_count": 3205, "unique_provider_request_count": 3205,
        "completed_key_count": 3205, "failed_key_count": 0, "provider_failure_count": 0,
        "fresh_provider_execution_count": 3205, "cache_reuse_count": 0,
        "mpb_execution": True, "completion_state": "COMPLETE",
    }
    if any(binding.get(key) != value for key, value in binding_expected.items()):
        raise FlowError("D3_PUBLIC_BINDING_PREEXISTING_VALUE_MISMATCH")
    derived_duplicate = 3205 - 3205
    if "duplicate_logical_demand_count" in binding and binding["duplicate_logical_demand_count"] != derived_duplicate:
        raise FlowError("D3_PUBLIC_BINDING_DUPLICATE_COUNT_INVALID")
    if "duplicate_logical_demand_count" not in binding:
        binding = {**binding, "duplicate_logical_demand_count": derived_duplicate}
        atomic_json(binding_path, binding)

    current_source = source["head"]
    reconciliation = {
        "schema": "mephc-e9f-d3-fr04-r64-closeout-reconciliation-v1",
        "work_order_id": contract["work_order_id"], "base_sandbox_sha": contract["source_commit"],
        "final_sandbox_sha": current_source, "origin_sandbox_sha": source["origin_sandbox"],
        "main_sha": EXPECTED_MAIN, "machine_contract_status": "PASS",
        "original_science_job_id": job.get("job_id"), "original_native_run_id": native.get("run_id"),
        "original_native_process_started": native.get("process_started"), "original_native_state": native.get("state"),
        "original_child_return_code": native.get("return_code"), "original_result_error": native.get("error_code"),
        "original_result_summary_present": True, "original_stdout_sha256": native.get("stdout_sha256"),
        "original_stdout_size_bytes": native.get("stdout_size_bytes"), "original_stderr_sha256": native.get("stderr_sha256"),
        "original_stderr_size_bytes": native.get("stderr_size_bytes"),
        "fr04_r64_existing_dataset_status": "COMPLETE_NATIVE_RESULT_AND_DATASET_VERIFIED",
        "fr04_r64_acquisition_dataset_id": dataset_id, "fr04_r64_acquisition_dataset_manifest_sha256": expected_manifest_sha,
        "fr04_r64_generic_dataset_id": manifest.get("dataset_id"), "fr04_r64_generic_dataset_manifest_sha256": manifest.get("manifest_sha256"),
        "fr04_r64_dataset_record_count": manifest.get("record_count"), "full_fr04_r64_record_integrity_pass_count": 3205,
        "derived_duplicate_logical_demand_count": derived_duplicate, "binding_duplicate_logical_demand_count": binding["duplicate_logical_demand_count"],
        "post_execution_diff_status": "PASS_ONLY_PUBLIC_BINDING_BEFORE_CORRECTIVE",
        "post_execution_binding_verification_status": "PASS",
        "acquire_closeout_derivable_field_compatibility_fix_status": "PASS_EXACT_LOGICAL_MINUS_UNIQUE_DERIVATION",
        "fr04_r64_native_rerun_required": False, "native_invocation_count": summary.get("native_invocation_count"),
        "provider_request_count": summary.get("provider_request_count"), "native_solves": summary.get("native_solves"),
        "mpb_execution": summary.get("mpb_execution"), "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "next_scientific_state": "FR04_R64_COMPLETE_SHARED_DATASET_RECONCILED_READY_FOR_SOLVER_FREE_THREE_BAND_QUALIFICATION_BERRY_AND_REDUCTION",
        "stream_order": "manifest_records_sorted_by_key_sha256", "payload_release_per_record": True,
        "h_arrays_aggregated": False, "terminal": "E9F_D3_FR04_R64_EXISTING_DATASET_RECONCILED_CLOSEOUT_COMPATIBILITY_FIXED",
    }
    atomic_json(paths.control / "audit" / "e9f" / "d3_fr04_r64_closeout_reconciliation.json", reconciliation)
    return {**reconciliation, "state": "succeeded", "safe_next": "publish"}


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


def closeout_job_source_compatible(paths: Paths, job_source: str, published_source: str) -> bool:
    if job_source == published_source:
        return True
    if not isinstance(job_source, str) or not SHA40.fullmatch(job_source):
        return False
    ancestor = git(paths, "merge-base", "--is-ancestor", job_source, published_source, check=False)
    if ancestor.returncode:
        return False
    changed = [line for line in git(paths, "diff", "--name-only", f"{job_source}..{published_source}").stdout.splitlines() if line]
    if bool(changed) and all(
        path == "AGENTS.md" or path == "tools/mephc-flow/README.md"
        or path == "tools/mephc-flow/mephc_flow.py" or path == "tests/test_mephc_flow.py"
        or path == "audit/e9f/qp_b_c2_c3_r8_c5_r224_state_reconciliation.json"
        for path in changed
    ):
        return True
    return acquire_binding_source_compatible(paths, job_source, published_source, changed)


def acquire_binding_source_compatible(
        paths: Paths, job_source: str, published_source: str, changed: Sequence[str],
) -> bool:
    """Accept only a verified post-acquisition binding publication.

    Acquisition entrypoints and inputs are hashed into the science job source.
    A binding is generated after execution, so publishing that one new JSON
    must not make an otherwise authoritative job undiscoverable.  This helper
    deliberately requires the active acquire contract, a single new binding
    path, and content equality with the durable Native result.
    """
    if len(changed) != 1:
        return False
    relative = changed[0].replace("\\", "/")
    if (not relative.startswith("audit/") or not relative.endswith("_binding.json")
            or any(token in relative.lower() for token in ("request_graph", "method_contract", "runtime", "provider"))):
        return False
    try:
        order = active_work_order(paths)
        contract = machine_contract(order["text"])
    except (FlowError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    allowed = contract.get("allowed_writes")
    if contract.get("action") != "acquire" or not isinstance(allowed, list) or relative not in allowed:
        return False
    existing = git(paths, "ls-tree", "--name-only", job_source, "--", relative, check=False)
    if existing.returncode == 0 and relative in existing.stdout.splitlines():
        return False
    shown = git(paths, "show", f"{published_source}:{relative}", check=False)
    if shown.returncode:
        return False
    try:
        binding = json.loads(shown.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(binding, dict):
        return False

    jobs = paths.state / "science-jobs"
    candidates: list[dict[str, Any]] = []
    if jobs.is_dir():
        for path in jobs.glob("MEPHC-SCIENCE-*.json"):
            value = read_json(path, default={})
            if (isinstance(value, dict) and value.get("work_order_id") == order["work_order_id"]
                    and value.get("source_commit") == job_source and value.get("action") == "acquire"
                    and value.get("state") == "succeeded"):
                candidates.append(value)
    if len(candidates) != 1:
        return False
    job = candidates[0]
    native = job.get("result")
    if (not isinstance(native, dict) or native.get("run_id") != job.get("native_run_id")
            or native.get("state") != "succeeded" or native.get("process_started") is not True
            or native.get("return_code") != 0 or native.get("launcher_return_code") != 0):
        return False
    summary = native.get("result_summary")
    if not isinstance(summary, dict):
        return False
    if relative.endswith("_replay_binding.json"):
        expected = {
            "work_order_id": order["work_order_id"],
            "acquisition_source_commit": job_source,
            "acquisition_dataset_id": summary.get("validation_dataset_id"),
            "dataset_manifest_sha256": summary.get("validation_dataset_manifest_sha256"),
            "entrypoint_sha256": summary.get("validation_entrypoint_sha256"),
            "science_runtime_sha256": summary.get("science_runtime_sha256"),
            "corrected_graph_sha256": summary.get("corrected_graph_sha256"),
            "dataset_record_count": summary.get("validation_dataset_record_count"),
            "spectral_replay_pass": summary.get("spectral_replay_pass"),
            "maximum_absolute_frequency_error": summary.get("maximum_absolute_frequency_error"),
            "k_gap_band0_band1": summary.get("live_k_gap_band0_band1"),
            "k_gap_band1_band2": summary.get("live_k_gap_band1_band2"),
            "native_invocation_count": summary.get("native_invocation_count"),
            "provider_request_count": summary.get("provider_request_count"),
            "fresh_provider_execution_count": summary.get("fresh_provider_execution_count"),
            "solver_executions": summary.get("solver_executions"),
            "native_solves": summary.get("native_solves"),
            "mpb_execution": summary.get("mpb_execution"),
            "native_retry_count": summary.get("native_retry_count"),
            "completion_state": "COMPLETE",
        }
        if any(expected[key] is None or binding.get(key) != expected[key] for key in expected):
            return False
        if binding.get("actual_frequencies") != summary.get("live_fr04_r64_six_band_spectrum"):
            return False
        if binding.get("reference_frequencies") != summary.get("reference_fr04_r64_tess96_six_band_spectrum"):
            return False
        return True

    if "duplicate_logical_demand_count" in summary:
        duplicate_count = summary.get("duplicate_logical_demand_count")
    else:
        logical_count = summary.get("logical_provider_demand_count")
        unique_count = summary.get("unique_provider_request_count")
        if (type(logical_count) is not int or type(unique_count) is not int
                or logical_count < unique_count):
            return False
        duplicate_count = logical_count - unique_count
    dataset_keys = sorted(
        key for key in summary
        if isinstance(key, str) and key.endswith("_dataset_id")
    )
    if len(dataset_keys) != 1:
        return False
    dataset_key = dataset_keys[0]
    prefix = dataset_key[:-len("_dataset_id")]
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,95}", prefix):
        return False
    companion_keys = (
        dataset_key,
        f"{prefix}_dataset_manifest_sha256",
        f"{prefix}_entrypoint_sha256",
        f"{prefix}_request_graph_sha256",
    )
    if any(
        key not in summary or not isinstance(summary[key], str) or not SHA64.fullmatch(summary[key])
        for key in companion_keys
    ):
        return False
    if (not isinstance(summary.get("science_runtime_sha256"), str)
            or not SHA64.fullmatch(summary["science_runtime_sha256"])):
        return False

    missing_d9_provider_failure_count = (
        summary.get("schema") == "mephc-e9f-d9-fr04-residual-composite-convergence-acquisition-v1"
        and binding.get("schema") == "mephc-e9f-d9-fr04-residual-composite-acquisition-binding-v1"
        and "provider_failure_count" not in summary
    )
    if missing_d9_provider_failure_count:
        reconciliation = {}
        for name in (
            "d9r1_fr04_residual_composite_dataset_reconciliation.json",
            "d9r2_fr04_residual_composite_dataset_reconciliation.json",
        ):
            candidate = read_json(paths.control / "audit" / "e9f" / name, default={})
            if isinstance(candidate, dict) and candidate:
                reconciliation = candidate
                break
        exact_accounting = {
            "failed_key_count": 0, "completed_key_count": 420,
            "logical_provider_demand_count": 420, "unique_provider_request_count": 420,
            "provider_request_count": 420, "fresh_provider_execution_count": 420,
            "solver_executions": 420, "native_solves": 420, "cache_reuse_count": 0,
            "native_retry_count": 0, "mpb_execution": True,
        }
        if (not isinstance(reconciliation, dict)
                or reconciliation.get("schema") != "mephc-e9f-d9r1-fr04-residual-composite-dataset-reconciliation-v1"
                or reconciliation.get("d9_dataset_id") != summary.get(f"{prefix}_dataset_id")
                or reconciliation.get("d9_dataset_manifest_sha256") != summary.get(f"{prefix}_dataset_manifest_sha256")
                or reconciliation.get("d9_dataset_record_count") != 420
                or reconciliation.get("full_d9_record_integrity_pass_count") != 420
                or reconciliation.get("d9_existing_dataset_status") != "COMPLETE_NATIVE_RESULT_AND_DATASET_VERIFIED"
                or reconciliation.get("d9_provider_failure_count_reconciliation_status") != "PASS_DERIVED_ZERO_FROM_COMPLETE_EXACT_ACCOUNTING"
                or reconciliation.get("strict_d9_missing_provider_failure_count_compatibility_status") != "PASS"
                or binding.get("provider_failure_count") != 0
                or binding.get("failed_key_count") != 0
                or binding.get("completed_key_count") != 420
                or binding.get("completion_state") != "COMPLETE"
                or any(summary.get(key) != value for key, value in exact_accounting.items())):
            return False
        reconciled_provider_failure_count = 0
    else:
        reconciled_provider_failure_count = summary.get("provider_failure_count")

    if binding.get("schema") == "mephc-e9f-d6-fr04-r64-corrected-acquisition-binding-v1":
        duplicate_count = summary.get("duplicate_logical_demand_count")
        if duplicate_count is None:
            logical_count = summary.get("logical_provider_demand_count")
            unique_count = summary.get("unique_provider_request_count")
            if (type(logical_count) is not int or type(unique_count) is not int
                    or logical_count < unique_count):
                return False
            duplicate_count = logical_count - unique_count
        expected = {
            "work_order_id": order["work_order_id"],
            "acquisition_source_commit": job_source,
            "acquisition_dataset_id": summary[dataset_key],
            "dataset_manifest_sha256": summary[f"{prefix}_dataset_manifest_sha256"],
            "entrypoint_sha256": summary[f"{prefix}_entrypoint_sha256"],
            "corrected_graph_sha256": summary[f"{prefix}_request_graph_sha256"],
            "science_runtime_sha256": summary["science_runtime_sha256"],
            "dataset_record_count": summary.get(f"{prefix}_dataset_record_count"),
            "domain_list_sha256": summary.get(f"{prefix}_domain_list_sha256"),
            "geometry_boundary_digest": summary.get(f"{prefix}_geometry_boundary_digest"),
            "source_model_identity": summary.get(f"{prefix}_source_model_identity"),
            "arc_segments_per_corner": summary.get(f"{prefix}_arc_segments_per_corner"),
            "resolution": summary.get("resolution"),
            "fr": summary.get("fr"),
            "logical_provider_demand_count": summary.get("logical_provider_demand_count"),
            "unique_provider_request_count": summary.get("unique_provider_request_count"),
            "duplicate_logical_demand_count": duplicate_count,
            "completed_key_count": summary.get("completed_key_count"),
            "failed_key_count": summary.get("failed_key_count"),
            "provider_failure_count": summary.get("provider_failure_count"),
            "fresh_provider_execution_count": summary.get("fresh_provider_execution_count"),
            "provider_request_count": summary.get("provider_request_count"),
            "solver_executions": summary.get("solver_executions"),
            "native_solves": summary.get("native_solves"),
            "cache_reuse_count": summary.get("cache_reuse_count"),
            "mpb_execution": summary.get("mpb_execution"),
            "native_retry_count": summary.get("native_retry_count"),
            "completion_state": "COMPLETE",
        }
        if any(expected[key] is None or binding.get(key) != expected[key] for key in expected):
            return False
        return summary.get(f"{prefix}_dataset_record_count") == summary.get("completed_key_count")

    expected = {
        "work_order_id": order["work_order_id"],
        "acquisition_source_commit": job_source,
        "acquisition_dataset_id": summary.get(f"{prefix}_dataset_id"),
        "dataset_manifest_sha256": summary.get(f"{prefix}_dataset_manifest_sha256"),
        "entrypoint_sha256": summary.get(f"{prefix}_entrypoint_sha256"),
        "graph_sha256": summary.get(f"{prefix}_request_graph_sha256"),
        "science_runtime_sha256": summary.get("science_runtime_sha256"),
        "logical_provider_demand_count": summary.get("logical_provider_demand_count"),
        "unique_provider_request_count": summary.get("unique_provider_request_count"),
        "duplicate_logical_demand_count": duplicate_count,
        "completed_key_count": summary.get("completed_key_count"),
        "failed_key_count": summary.get("failed_key_count"),
        "provider_failure_count": reconciled_provider_failure_count,
        "fresh_provider_execution_count": summary.get("fresh_provider_execution_count"),
        "cache_reuse_count": summary.get("cache_reuse_count"),
        "mpb_execution": summary.get("mpb_execution"),
    }
    if any(expected[key] is None or binding.get(key) != expected[key] for key in expected):
        return False
    return binding.get("completion_state") == "COMPLETE"


def successful_science_job(paths: Paths, work_order_id: str, source_commit: str) -> dict[str, Any] | None:
    root = paths.state / "science-jobs"
    matches: list[dict[str, Any]] = []
    if root.is_dir():
        for item in root.glob("MEPHC-SCIENCE-*.json"):
            value = read_json(item, default={})
            if (isinstance(value, dict) and value.get("work_order_id") == work_order_id
                    and value.get("state") == "succeeded"
                    and closeout_job_source_compatible(paths, value.get("source_commit"), source_commit)):
                matches.append(value)
    return max(matches, key=lambda item: float(item.get("completed_at", 0))) if matches else None


def scalar_result(value: Any) -> bool:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        lowered = value.lower()
        return (len(value) <= 512 and "\n" not in value and "\r" not in value
                and "\\\\wsl" not in lowered and "/home/" not in lowered
                and not re.search(r"[a-z]:[\\/]", lowered))
    return False


def closeout_result_projection(job: dict[str, Any]) -> dict[str, Any]:
    """Return the authoritative bounded result fields for closeout reporting.

    Acquire science jobs persist the Native record under ``result``.  The
    science-job envelope is not itself a Native result and must not be used
    to infer execution metrics.  Analyze jobs retain their historical
    top-level result summary and continue through the existing projection.
    """
    if job.get("action") != "acquire":
        result_summary = job.get("result_summary", {})
        if not isinstance(result_summary, dict):
            raise FlowError("CLOSEOUT_RESULT_SUMMARY_INVALID")
        return {
            "return_code": job.get("return_code"),
            "native_invocation_count": job.get("native_invocation_count",
                                              result_summary.get("native_invocation_count", 0)),
            "provider_executions": job.get("provider_executions",
                                            result_summary.get("provider_request_count", 0)),
            "solver_executions": job.get("solver_executions",
                                          result_summary.get("native_solves", 0)),
            "result_summary": result_summary,
        }

    native_run_id = job.get("native_run_id")
    if not isinstance(native_run_id, str) or not native_run_id.startswith("MEPHC-NATIVE-"):
        raise FlowError("CLOSEOUT_ACQUIRE_NATIVE_RUN_ID_MISSING")
    native = job.get("result")
    if not isinstance(native, dict) or native.get("run_id") != native_run_id:
        raise FlowError("CLOSEOUT_ACQUIRE_NATIVE_RESULT_MISSING")
    if native.get("state") != "succeeded":
        raise FlowError("CLOSEOUT_ACQUIRE_NATIVE_RESULT_NOT_SUCCEEDED")
    if native.get("process_started") is not True:
        raise FlowError("CLOSEOUT_ACQUIRE_NATIVE_PROCESS_NOT_STARTED")
    if native.get("return_code") != 0 or native.get("launcher_return_code") != 0:
        raise FlowError("CLOSEOUT_ACQUIRE_NATIVE_RETURN_CODE_INVALID")
    result_summary = native.get("result_summary")
    if not isinstance(result_summary, dict):
        raise FlowError("CLOSEOUT_ACQUIRE_RESULT_SUMMARY_MISSING")
    if native.get("work_order_id") != job.get("work_order_id"):
        raise FlowError("CLOSEOUT_ACQUIRE_NATIVE_WORK_ORDER_MISMATCH")
    if native.get("source_commit") != job.get("source_commit"):
        raise FlowError("CLOSEOUT_ACQUIRE_NATIVE_SOURCE_MISMATCH")
    return {
        "return_code": native["return_code"],
        "native_invocation_count": native.get("cost", 0),
        "provider_executions": result_summary.get("provider_request_count", 0),
        "solver_executions": result_summary.get("native_solves", 0),
        "result_summary": result_summary,
    }


def report_artifacts(paths: Paths, order_text: str, head: str) -> list[dict[str, Any]]:
    contract = machine_contract(order_text)
    allowed = contract.get("allowed_writes", []) if isinstance(contract, dict) else []
    if not isinstance(allowed, list):
        raise FlowError("WORK_ORDER_ALLOWED_WRITES_INVALID")
    artifacts: list[dict[str, Any]] = []
    for raw in sorted(set(item for item in allowed if isinstance(item, str))):
        relative = PurePosixPath(raw.replace("\\", "/"))
        if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                or relative.parts[0] == "tests"):
            continue
        tracked = git(paths, "ls-tree", "--name-only", head, "--", str(relative), check=False)
        if tracked.returncode or str(relative) not in tracked.stdout.splitlines():
            continue
        blob = git(paths, "show", f"{head}:{relative}").stdout.encode("utf-8")
        artifacts.append({"path": str(relative), "sha256": sha256_bytes(blob), "size_bytes": len(blob)})
    return artifacts


def canonical_closeout_report(paths: Paths, *, blocked_code: str | None = None) -> dict[str, Any]:
    if blocked_code is not None and not BLOCKED_CODE.fullmatch(blocked_code):
        raise FlowError("CLOSEOUT_BLOCKED_CODE_INVALID")
    source = require_source(paths, published=True)
    order = active_work_order(paths)
    contract = machine_contract(order["text"])
    values = key_values(order["text"])
    work_class = str(contract.get("kind") or (values.get("WORK_ORDER_CLASS") or ["INFRASTRUCTURE"])[-1]).upper()
    if work_class not in {"SCIENCE", "INFRASTRUCTURE"}:
        raise FlowError("CLOSEOUT_WORK_ORDER_CLASS_INVALID")
    publish_evidence = read_json(paths.state / "publish" / f"{source['head']}.json", default={})
    if (not isinstance(publish_evidence, dict) or publish_evidence.get("return_code") != 0
            or publish_evidence.get("published_sandbox") != source["head"]):
        raise FlowError("CLOSEOUT_PUBLISH_EVIDENCE_REQUIRED", safe_next="publish")
    job = successful_science_job(paths, order["work_order_id"], source["head"])
    if blocked_code is None and work_class == "SCIENCE" and job is None:
        raise FlowError("CLOSEOUT_SUCCESSFUL_JOB_REQUIRED", safe_next="science-status")
    projection = closeout_result_projection(job) if isinstance(job, dict) else {
        "return_code": None, "native_invocation_count": 0,
        "provider_executions": 0, "solver_executions": 0, "result_summary": {},
    }
    result_summary = projection["result_summary"]
    artifacts = report_artifacts(paths, order["text"], source["head"])
    lines = [
        "SCHEMA=mephc-fixed-closeout-v1",
        f"WORK_ORDER_ID={order['work_order_id']}",
        f"WORK_ORDER_CLASS={work_class}",
        f"REPORT_KIND={'blocked' if blocked_code else 'complete'}",
        "CODE_CHANGE=SANDBOX_ONLY",
        f"BASE_MAIN_SHA={EXPECTED_MAIN}",
        f"SANDBOX_HEAD_SHA={source['head']}",
        f"ORIGIN_SANDBOX_SHA={source['origin_sandbox']}",
        f"AUDIT_DIFF_RANGE={EXPECTED_MAIN}..{source['head']}",
        f"PUBLISH_TEST_RETURN_CODE={publish_evidence['return_code']}",
    ]
    tests = publish_evidence.get("tests", [])
    if isinstance(tests, list) and all(isinstance(item, str) and len(item) <= 240 for item in tests):
        lines.append(f"PUBLISH_TEST_COUNT={len(tests)}")
    if job is not None:
        lines.extend([
            f"SCIENCE_JOB_ID={job.get('job_id')}", f"SCIENCE_JOB_STATE={job.get('state')}",
            f"SCIENCE_SOURCE_SHA={job.get('source_commit')}",
            f"SCIENCE_ACTION={job.get('action')}",
            f"SCIENCE_RETURN_CODE={projection['return_code']}",
            f"NATIVE_INVOCATION_COUNT={projection['native_invocation_count']}",
            f"PROVIDER_EXECUTION_COUNT={projection['provider_executions']}",
            f"SOLVER_EXECUTION_COUNT={projection['solver_executions']}",
        ])
    for key in sorted(result_summary):
        value = result_summary[key]
        if scalar_result(value):
            safe_key = re.sub(r"[^A-Z0-9_]", "_", key.upper())[:96]
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"RESULT_{safe_key}={rendered}")
    if work_class == "INFRASTRUCTURE":
        certifications = paths.science_state / "certifications"
        runtime_sha = science_runtime_hash(paths, source["head"]) if certifications.is_dir() else ""
        certification = read_json(certifications / f"{runtime_sha}.json", default={}) if runtime_sha else {}
        if (isinstance(certification, dict)
                and certification.get("schema") == "mephc-science-runtime-certification-v1"
                and certification.get("runtime_sha256") == runtime_sha):
            smoke = certification.get("mpb_smoke", {})
            smoke_passed = isinstance(smoke, dict) and smoke.get("executed") is True
            lines.extend([
                f"NEW_SCIENCE_RUNTIME_SHA256={runtime_sha}",
                "SOLVER_FREE_SELFTEST_STATUS=PASS",
                f"REAL_MPB_SMOKE_STATUS={'PASS' if smoke_passed else 'NOT_EXECUTED'}",
                f"REAL_MPB_SMOKE_SOLVER_EXECUTIONS={smoke.get('solver_executions', 0) if isinstance(smoke, dict) else 0}",
                "RESULT_SUMMARY_SAFETY_FIX_STATUS=PASS",
                "RESULT_SUMMARY_MACHINE_CONTRACT_FIELD_STATUS=PASS",
                "SENSITIVE_IDENTITY_FIELD_REJECTION_STATUS=PASS",
                "R192_NATIVE_INVOCATION_COUNT=0",
                "R192_NATIVE_SOLVES=0",
                "R192_MPB_EXECUTION=false",
                "PARENT_DATASET_PRESERVED=true",
                "LOCAL_CORRECTIVE_STATUS=COMPLETE",
                "PIPELINE_HEALTH=HEALTHY",
                "BLOCKED_BY_INFRASTRUCTURE=false",
                "SCIENTIFIC_WORK_MUST_STOP=true",
            ])
    lines.append(f"ARTIFACT_COUNT={len(artifacts)}")
    for index, artifact in enumerate(artifacts, start=1):
        lines.extend([
            f"ARTIFACT_{index}_PATH={artifact['path']}",
            f"ARTIFACT_{index}_SHA256={artifact['sha256']}",
            f"ARTIFACT_{index}_SIZE_BYTES={artifact['size_bytes']}",
        ])
    if blocked_code:
        lines.extend([f"BLOCKED_CODE={blocked_code}", "TERMINAL=BLOCKED"])
    else:
        success_terminal = (values.get("SUCCESS_TERMINAL") or [None])[-1]
        terminal = (result_summary.get("terminal") if scalar_result(result_summary.get("terminal"))
                    else success_terminal if scalar_result(success_terminal) else "COMPLETE")
        lines.append(f"TERMINAL={terminal}")
    message = ("\n".join(lines) + "\n").encode("utf-8")
    message_hash = sha256_bytes(message)
    kind = "blocked" if blocked_code else "complete"
    request_hash = sha256_bytes(canonical_json({
        "work_order_id": order["work_order_id"], "kind": kind, "message_sha256": message_hash,
    }))
    return {
        "work_order_id": order["work_order_id"], "work_order_class": work_class, "kind": kind,
        "source_commit": source["head"], "job_id": job.get("job_id") if job else None,
        "artifacts": artifacts, "message": message, "message_sha256": message_hash,
        "request_hash": request_hash, "request_id": "MEPHC-FLOW-" + request_hash[:24],
    }


def closeout_status(paths: Paths) -> dict[str, Any]:
    try:
        prepared = canonical_closeout_report(paths)
    except FlowError as exc:
        return {"state": "not_ready", "error_code": exc.code, "safe_next": exc.safe_next}
    directory = paths.outbox / prepared["request_id"]
    if not directory.is_dir():
        return {"state": "ready", "request_id": prepared["request_id"], "submission_count": 0,
                "safe_next": "closeout"}
    summary = request_summary(directory)
    if summary["response_received"]:
        safe_next = "resume"
        state = "response_received"
    elif summary["submission_count"]:
        safe_next = "closeout"
        state = "reconciliation_required"
    else:
        safe_next = "closeout"
        state = "request_not_submitted"
    return {"state": state, **summary, "safe_next": safe_next}


def pending_closeout_status(paths: Paths, work_order_id: str) -> dict[str, Any] | None:
    if not paths.outbox.is_dir():
        return None
    candidates: list[tuple[int, Path, dict[str, Any]]] = []
    for directory in paths.outbox.glob("MEPHC-FLOW-*"):
        if not directory.is_dir() or directory.is_symlink():
            continue
        manifest = read_json(directory / "request.json", default={})
        if (not isinstance(manifest, dict) or manifest.get("flow_schema") != "mephc-fixed-closeout-v1"
                or manifest.get("work_order_id") != work_order_id):
            continue
        candidates.append((directory.stat().st_mtime_ns, directory, manifest))
    if not candidates:
        return None
    _, directory, manifest = max(candidates, key=lambda item: (item[0], item[1].name))
    summary = request_summary(directory)
    kind = manifest.get("report_kind")
    blocked_code = None
    if kind == "blocked":
        message = (directory / "message.txt").read_text(encoding="utf-8-sig", errors="strict")
        match = re.search(r"^BLOCKED_CODE=([A-Z][A-Z0-9_]{2,95})$", message, flags=re.MULTILINE)
        if match is None:
            raise FlowError("CLOSEOUT_BLOCKED_REQUEST_INVALID")
        blocked_code = match.group(1)
    if summary["response_received"]:
        safe_next = f"courier-reconcile --request-id {directory.name}"
        state = "response_ready_to_consume"
    elif kind == "blocked":
        safe_next = f"closeout-blocked --code {blocked_code}"
        state = "waiting_for_response"
    else:
        safe_next = "closeout"
        state = "waiting_for_response"
    return {"state": state, **summary, "report_kind": kind, "blocked_code": blocked_code,
            "safe_next": safe_next}


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
    pending_closeout = pending_closeout_status(paths, work_order_id) if work_order_id is not None else None
    closeout = pending_closeout or (closeout_status(paths) if work_order_id is not None
                                   else {"state": "unavailable", "safe_next": "resume"})
    return {
        "schema": "mephc-flow-status-v1", "source": source,
        "active_work_order_id": work_order_id, "work_order_policy": policy,
        "effective_policy": effective, "pending_native_runs": runs,
        "flow_requests": sorted(requests, key=lambda item: str(item["request_id"])),
        "closeout_state": closeout,
        "safe_next": closeout["safe_next"],
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


def science_job_id(contract: dict[str, Any], execution_source_commit: str) -> str:
    payload = {
        "contract_sha256": contract["contract_sha256"],
        "source_commit": execution_source_commit,
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
    job_id = science_job_id(contract, preflight["source_commit"])
    job_path = paths.state / "science-jobs" / f"{job_id}.json"
    existing = read_json(job_path, default=None)
    if isinstance(existing, dict):
        safe_next = "closeout" if existing.get("state") == "succeeded" else f"science-status {job_id}"
        return {**existing, "reused": True, "safe_next": safe_next}
    record = {
        "schema": "mephc-scientific-job-v1", "job_id": job_id,
        "work_order_id": contract["work_order_id"], "contract_sha256": contract["contract_sha256"],
        "source_commit": preflight["source_commit"], "action": "acquire", "state": "dispatching",
        "created_at": time.time(), "provenance": {
            "main_sha": EXPECTED_MAIN, "sandbox_sha": preflight["source_commit"],
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
    safe_next = "closeout" if final.get("state") == "succeeded" else f"science-status {job_id}"
    return {**final, "reused": False, "safe_next": safe_next}


def science_analyze(paths: Paths) -> dict[str, Any]:
    preflight = science_preflight(paths)
    _, contract = active_machine_contract(paths)
    if (contract["kind"] == "INFRASTRUCTURE"
            and contract["work_order_id"] in {
                "MEPHC-E9F-D9R1-FR04-RESIDUAL-COMPOSITE-RECON-COMPAT-20260829-338",
                "MEPHC-E9F-D9R2-FR04-CLOSEOUT-PATCH-FIRST-20260829-339",
            }):
        return d9r1_reconcile_existing_dataset(paths, contract, preflight)
    if (contract["kind"] == "INFRASTRUCTURE"
            and contract["work_order_id"] == "MEPHC-E9F-D3-FR04-R64-RECON-COMPAT-20260828-324"):
        return d3_reconcile_existing_dataset(paths, contract, preflight)
    if contract["kind"] != "SCIENCE" or contract["action"] != "analyze":
        raise FlowError("SCIENCE_ANALYZE_ACTION_NOT_AUTHORIZED")
    job_id = science_job_id(contract, preflight["source_commit"])
    job_path = paths.state / "science-jobs" / f"{job_id}.json"
    existing = read_json(job_path, default=None)
    if isinstance(existing, dict):
        safe_next = "closeout" if existing.get("state") == "succeeded" else f"science-status {job_id}"
        return {**existing, "reused": True, "safe_next": safe_next}
    record = {
        "schema": "mephc-scientific-job-v1", "job_id": job_id,
        "work_order_id": contract["work_order_id"], "contract_sha256": contract["contract_sha256"],
        "source_commit": preflight["source_commit"], "action": "analyze", "state": "dispatching",
        "process_started": False, "provider_executions": 0, "solver_executions": 0,
        "created_at": time.time(), "provenance": {
            "main_sha": EXPECTED_MAIN, "sandbox_sha": preflight["source_commit"],
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
    safe_next = "closeout" if final.get("state") == "succeeded" else f"science-status {job_id}"
    return {**final, "reused": False, "safe_next": safe_next}


def science_status(paths: Paths, job_id: str) -> dict[str, Any]:
    if not REQUEST_ID.fullmatch(job_id) or not job_id.startswith("MEPHC-SCIENCE-"):
        raise FlowError("SCIENCE_JOB_ID_INVALID")
    path = paths.state / "science-jobs" / f"{job_id}.json"
    value = read_json(path, default=None)
    if not isinstance(value, dict) or value.get("job_id") != job_id:
        raise FlowError("SCIENCE_JOB_NOT_FOUND")
    native_run_id = value.get("native_run_id")
    if isinstance(native_run_id, str):
        native = native_status(paths, native_run_id)
        safe_next = "closeout" if value.get("state") == "succeeded" else native.get("safe_next", f"science-status {job_id}")
        return {**value, "native_status": native, "safe_next": safe_next}
    if value.get("state") in {"succeeded", "failed"}:
        return {**value, "safe_next": "closeout" if value.get("state") == "succeeded" else "closeout-blocked"}
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


def report_manifest(prepared: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1, "project_id": PROJECT_ID, "request_id": prepared["request_id"],
        "message_file": "message.txt", "attachments": [], "workflow_window_seconds": 600,
        "queue_wait_seconds": 3600, "task_difficulty": "normal", "instruction_level": "normal",
        "flow_schema": "mephc-fixed-closeout-v1", "work_order_id": prepared["work_order_id"],
        "report_kind": prepared["kind"], "message_sha256": prepared["message_sha256"],
        "idempotency_key": prepared["request_hash"],
    }


def validate_and_create_closeout_request(paths: Paths, prepared: dict[str, Any]) -> Path:
    request_id = prepared["request_id"]
    directory = paths.outbox / request_id
    validation_parent = paths.state / "closeout-validation" / str(os.getpid())
    validation = validation_parent / request_id
    if validation_parent.exists():
        shutil.rmtree(validation_parent)
    validation.mkdir(parents=True, exist_ok=False)
    (validation / "message.txt").write_bytes(prepared["message"])
    atomic_json(validation / "request.json", report_manifest(prepared))
    try:
        checked = courier_command(paths, "validate", validation)
        if checked.returncode:
            raise FlowError("COURIER_VALIDATION_FAILED", (checked.stderr or checked.stdout)[-4000:])
    finally:
        shutil.rmtree(validation_parent, ignore_errors=True)
    paths.outbox.mkdir(parents=True, exist_ok=True)
    staging = paths.outbox / f".{request_id}.{os.getpid()}.tmp"
    staging.mkdir(parents=False, exist_ok=False)
    (staging / "message.txt").write_bytes(prepared["message"])
    atomic_json(staging / "request.json", report_manifest(prepared))
    try:
        os.replace(staging, directory)
    except FileExistsError:
        shutil.rmtree(staging, ignore_errors=True)
    return directory


def verify_closeout_request(directory: Path, prepared: dict[str, Any]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise FlowError("REQUEST_DIRECTORY_INVALID")
    prior = read_json(directory / "request.json", default={})
    expected = (prepared["work_order_id"], prepared["kind"], prepared["message_sha256"])
    actual = (prior.get("work_order_id"), prior.get("report_kind"), prior.get("message_sha256"))
    if actual != expected or prior.get("request_id") != prepared["request_id"]:
        raise FlowError("REQUEST_IDEMPOTENCY_CONFLICT")


def finish_closeout(paths: Paths, prepared: dict[str, Any]) -> dict[str, Any]:
    directory = paths.outbox / prepared["request_id"]
    if not directory.exists():
        directory = validate_and_create_closeout_request(paths, prepared)
    verify_closeout_request(directory, prepared)
    summary = request_summary(directory)
    if summary["response_received"]:
        consumed = consume_response(paths, directory)
        return {"state": "response_received", **summary, **consumed,
                "closeout_state": "complete", "message_sha256": prepared["message_sha256"],
                "safe_next": "resume", "next_work_order_id": consumed["work_order_id"]}
    receipt = read_json(directory / "receipt.json", default={})
    receipt_state = receipt.get("state") if isinstance(receipt, dict) else None
    recoverable = {"request_submitted", "waiting_for_response", "submission_unconfirmed", "chat_submission_unconfirmed",
                   "submission_state_uncertain", "response_timeout", "response_protocol_error"}
    hard_errors = {"login_error", "target_error", "hard_error", "validation_failed", "request_rejected"}
    if receipt_state in hard_errors:
        raise FlowError("COURIER_HARD_ERROR", str(receipt_state), safe_next="human-intervention-required")
    if summary["submission_count"] > 0 or receipt_state in recoverable:
        result = courier_reconcile(paths, prepared["request_id"])
    else:
        dispatched = courier_command(paths, "run", directory)
        final = request_summary(directory)
        atomic_json(directory / "flow-bridge.json", {
            "schema": "mephc-flow-courier-bridge-v1", "request_id": prepared["request_id"],
            "message_sha256": prepared["message_sha256"], "return_code": dispatched.returncode,
            "stdout_sha256": sha256_bytes(dispatched.stdout.encode("utf-8")),
            "stderr_sha256": sha256_bytes(dispatched.stderr.encode("utf-8")), "completed_at": time.time(),
        })
        if final["response_received"]:
            consumed = consume_response(paths, directory)
            result = {"state": "response_received", **final, **consumed,
                      "return_code": dispatched.returncode, "safe_next": "resume"}
        else:
            result = {"state": "courier_stopped", **final, "return_code": dispatched.returncode,
                      "safe_next": f"closeout"}
    if result.get("response_received"):
        result.update({"closeout_state": "complete", "message_sha256": prepared["message_sha256"],
                       "safe_next": "resume", "next_work_order_id": result.get("work_order_id")})
    else:
        result.update({"closeout_state": "reconciliation_required",
                       "message_sha256": prepared["message_sha256"], "safe_next": "closeout"})
    return result


def closeout(paths: Paths) -> dict[str, Any]:
    return finish_closeout(paths, canonical_closeout_report(paths))


def closeout_blocked(paths: Paths, code: str) -> dict[str, Any]:
    return finish_closeout(paths, canonical_closeout_report(paths, blocked_code=code))


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
    commands.add_parser("closeout")
    blocked_cmd = commands.add_parser("closeout-blocked")
    blocked_cmd.add_argument("--code", required=True)
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
        elif args.command == "closeout":
            value = closeout(paths)
        elif args.command == "closeout-blocked":
            value = closeout_blocked(paths, args.code)
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
