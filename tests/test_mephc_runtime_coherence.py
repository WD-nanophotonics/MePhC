from __future__ import annotations

from datetime import datetime, timezone
import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "tools" / "mephc-runner"
ADMISSION = ROOT / "tools" / "mephc-admission"
sys.path.insert(0, str(RUNNER))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def machine_line(contract: dict) -> str:
    return "WORK_ORDER_CONTRACT_JSON=" + json.dumps(contract, separators=(",", ":"))


def test_machine_and_legacy_retention_contracts_normalize_identically():
    module = load("coherence_contract", RUNNER / "work_order_contract.py")
    work_order_id, digest = "WO-RETENTION", "a" * 64
    machine = {"schema":module.SCHEMA, "work_order_id":work_order_id,
               "required_capabilities":["retention.search", "retention.inspect"],
               "authorized_actions":[],
               "retention_bindings":[{"retention_id":"RP3_R96", "expected_sha256":digest}]}
    forms = [
        f"RETENTION_ID=RP3_R96\nEXPECTED_SHA256={digest}\n",
        f"AUTHORITATIVE_R96_RESULT_RETENTION_ID=RP3_R96\r\nAUTHORITATIVE_R96_RESULT_SHA256={digest}\r\n",
        f"AUTHORITATIVE_R96_RESULT_RETENTION_ID=RP3_R96\\nAUTHORITATIVE_R96_RESULT_SHA256={digest}\\n",
    ]
    canonical = module.parse(machine_line(machine), work_order_id)
    for text in forms:
        adapted = module.parse(text, work_order_id)
        assert adapted["retention_bindings"] == canonical["retention_bindings"]
        assert adapted["required_capabilities"] == canonical["required_capabilities"]
        assert adapted["contract_sha256"] == canonical["contract_sha256"]


def test_contract_rejects_forged_binding_and_identifies_policy_conflict():
    module = load("coherence_contract_policy", RUNNER / "work_order_contract.py")
    base = {"schema":module.SCHEMA, "work_order_id":"WO-POLICY",
            "required_capabilities":["runtime.reload"], "authorized_actions":["shell"],
            "retention_bindings":[]}
    assert module.authority_conflicts(module.validate(base, "WO-POLICY")) == ["shell"]
    base["retention_bindings"] = [{"retention_id":"R", "expected_sha256":"z" * 64}]
    with pytest.raises(module.ContractError) as caught:
        module.validate(base, "WO-POLICY")
    assert caught.value.code == "WORK_ORDER_CONTRACT_SCHEMA_INVALID"


@pytest.mark.parametrize(
    ("required", "authorized", "coherent", "status"),
    [
        (["capability.not_installed"], [], True, "WORK_ORDER_BLOCKED_MISSING_TYPED_CAPABILITY"),
        ([], ["shell"], True, "AUTHORITY_CONFLICT_USER_CONSTRAINT_VS_WORK_ORDER"),
        (["runtime.reload"], [], False, "RUNTIME_ATTESTATION_INCOHERENT"),
        (["runtime.reload"], [], True, "READY"),
    ],
)
def test_work_order_preflight_blocks_before_execution(required, authorized, coherent, status, monkeypatch):
    module = load(f"coherence_preflight_{status}", RUNNER / "jobctl.py")
    contract = {"schema":"mephc-work-order-contract-v1", "work_order_id":"WO-PREFLIGHT",
                "required_capabilities":required, "authorized_actions":authorized,
                "retention_bindings":[]}
    active = {"active_work_order_id":"WO-PREFLIGHT", "work_order_text":machine_line(contract)}
    monkeypatch.setattr(module.workflow, "active", lambda: active)
    monkeypatch.setattr(module.runtime_attestation, "attest", lambda: {
        "coherent":coherent, "safe_next_tool":"mephc_runtime_reload"})
    value = module.work_order_preflight()
    assert value["status"] == status
    assert value["retry_allowed"] is False
    assert len(value["contract_sha256"]) == 64


def test_attestation_detects_loaded_worker_and_source_staleness(tmp_path, monkeypatch):
    module = load("coherence_attestation", RUNNER / "runtime_attestation.py")
    windows, state = tmp_path / "windows", tmp_path / "state"
    windows.mkdir(); state.mkdir()
    now = datetime.now(timezone.utc).isoformat()
    build, source, worker_hash, mcp_hash = "build-1", "1" * 40, "a" * 64, "b" * 64
    (windows / "current.json").write_text(json.dumps({"build_id":build, "source_commit":source}))
    (windows / "install-manifest.json").write_text(json.dumps([{"name":"worker.py", "sha256":worker_hash}]))
    (state / "heartbeat.json").write_text(json.dumps({"updated_at":now, "worker_build_id":build,
        "loaded_worker_module_hash":worker_hash, "expected_mcp_bundle_hash":mcp_hash,
        "runtime_source_matches":True}))
    broker = tmp_path / "broker.json"
    broker.write_text(json.dumps({"updated_at":now, "broker_build_id":build, "worker_ok":True}))
    monkeypatch.setattr(module.config, "WINDOWS_RUNTIME_WSL", windows)
    monkeypatch.setattr(module.config, "RUNTIME", state)
    monkeypatch.setattr(module.config, "BROKER_HEARTBEAT", broker)
    monkeypatch.setattr(module.config, "state_epoch", lambda: "epoch-1")
    monkeypatch.setattr(module, "_source_head", lambda: source)
    module.set_loaded_mcp_hash(mcp_hash)
    assert module.attest()["coherent"] is True
    heartbeat = json.loads((state / "heartbeat.json").read_text())
    heartbeat["loaded_worker_module_hash"] = "c" * 64
    (state / "heartbeat.json").write_text(json.dumps(heartbeat))
    stale = module.attest()
    assert stale["coherent"] is False
    assert "WORKER_LOADED_MODULE_MISMATCH" in stale["mismatches"]
    heartbeat["loaded_worker_module_hash"] = worker_hash
    heartbeat["expected_mcp_bundle_hash"] = "d" * 64
    (state / "heartbeat.json").write_text(json.dumps(heartbeat))
    assert "MCP_LOADED_MODULE_MISMATCH" in module.attest()["mismatches"]
    monkeypatch.setattr(module, "_source_head", lambda: "2" * 40)
    stale_source = module.attest()
    assert "SOURCE_HEAD_NOT_INSTALLED" in stale_source["mismatches"]
    assert stale_source["safe_next_tool"] == "mephc_runtime_activate"


def test_central_job_semantics_are_non_retrying_and_layered():
    module = load("coherence_semantics", RUNNER / "job_semantics.py")
    contract = module.enrich("failed", "retention_search", "RETENTION_QUERY_CONTRACT_MISMATCH")
    assert contract == {"terminal_state":"failed", "retry_allowed":False,
                        "same_job_recovery_allowed":False, "new_job_allowed":False,
                        "failure_layer":"worker_contract", "failure_code":"RETENTION_QUERY_CONTRACT_MISMATCH",
                        "phase":"terminal"}
    recovery = module.enrich("recovery_required", "change", "CHANGE_TRANSACTION_RECOVERY_REQUIRED")
    assert recovery["same_job_recovery_allowed"] is True
    assert recovery["new_job_allowed"] is False


def test_recovery_required_status_has_one_safe_recovery_tool(tmp_path, monkeypatch):
    module = load("coherence_jobctl_status", RUNNER / "jobctl.py")
    jobs = tmp_path / "jobs"
    job = jobs / "MEPHC-JOB-RECOVERY"
    job.mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"operation":"change"}), encoding="utf-8")
    (job / "state.json").write_text(json.dumps({"state":"recovery_required",
        "error_code":"CHANGE_TRANSACTION_RECOVERY_REQUIRED"}), encoding="utf-8")
    monkeypatch.setattr(module, "JOBS", jobs)
    monkeypatch.setattr(module, "_health", lambda *_args, **_kwargs: {"stale":False})
    value = module.read_state(job.name)
    assert value["terminal_state"] == "recovery_required"
    assert value["same_job_recovery_allowed"] is True
    assert value["new_job_allowed"] is False
    assert value["safe_next_tool"] == "mephc_recover"


def test_lifecycle_gate_accepts_only_published_clean_infrastructure(monkeypatch):
    module = load("coherence_lifecycle", ADMISSION / "runtime_lifecycle.py")
    head, installed = "2" * 40, "1" * 40
    answers = {
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("branch", "--show-current"): "sandbox",
        ("rev-parse", "HEAD"): head,
        ("rev-parse", "origin/main"): module.EXPECTED_MAIN,
        ("ls-remote", "origin", "refs/heads/main", "refs/heads/sandbox"):
            f"{module.EXPECTED_MAIN}\trefs/heads/main\n{head}\trefs/heads/sandbox",
        ("diff", "--name-only", f"{installed}..{head}"): "tools/mephc-runner/jobctl.py\nAGENTS.md",
    }
    monkeypatch.setattr(module, "_git", lambda *args, **kwargs: answers[args])
    monkeypatch.setattr(module, "_current", lambda: {"source_commit":installed})
    monkeypatch.setattr(module, "_active_jobs", lambda: [])
    assert module._gate() == {"source_head":head, "installed_source_head":installed}
    answers[("diff", "--name-only", f"{installed}..{head}")] = "mephc/science.py"
    with pytest.raises(module.LifecycleError) as caught:
        module._gate()
    assert caught.value.code == "RUNTIME_ACTIVATION_NON_INFRASTRUCTURE_DIFF"


def test_activation_install_failure_restores_snapshot(monkeypatch, tmp_path):
    module = load("coherence_lifecycle_rollback", ADMISSION / "runtime_lifecycle.py")
    stage = tmp_path / "stage"
    (stage / "tools/mephc-runner").mkdir(parents=True)
    (stage / "tools/mephc-admission").mkdir(parents=True)
    monkeypatch.setattr(module, "_gate", lambda: {"source_head":"2" * 40,
                                                  "installed_source_head":"1" * 40})
    monkeypatch.setattr(module, "_tests", lambda: None)
    monkeypatch.setattr(module, "_stage", lambda _head: stage)
    snapshot = {"current":{"build_id":"old"}, "root":tmp_path / "backup"}
    monkeypatch.setattr(module, "_snapshot", lambda: snapshot)
    monkeypatch.setattr(module, "_run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=2, stdout="", stderr="install failed"))
    restored = []
    monkeypatch.setattr(module, "_restore", lambda value: restored.append(value))
    monkeypatch.setattr(module, "_receipt", lambda *args, **kwargs: {})
    with pytest.raises(module.LifecycleError) as caught:
        module.activate()
    assert caught.value.code == "RUNTIME_ACTIVATION_ROLLED_BACK"
    assert restored == [snapshot]


def test_lifecycle_schema_and_admission_replay_boundary_are_fixed():
    admission = (ADMISSION / "mephc_admission.py").read_text(encoding="utf-8")
    server = (RUNNER / "mcp_server.py").read_text(encoding="utf-8")
    admission_module = load("coherence_admission", ADMISSION / "mephc_admission.py")
    assert '"additionalProperties": False' in server
    assert 'LOCAL_LIFECYCLE_TOOLS = {"mephc_runtime_reload": "reload", "mephc_runtime_activate": "activate"}' in admission
    assert "mephc_runtime_attest" in admission_module.READ_ONLY_TOOLS
    assert "mephc_runtime_reload" not in admission_module.READ_ONLY_TOOLS
    assert "mephc_runtime_activate" not in admission_module.READ_ONLY_TOOLS


def test_bootstrap_and_worker_share_one_ordered_build_manifest():
    bootstrap = (RUNNER / "bootstrap.ps1").read_text(encoding="utf-8")
    worker = (RUNNER / "worker.py").read_text(encoding="utf-8")
    powershell_block = bootstrap.split("$Files=@(", 1)[1].split("\n)", 1)[0]
    powershell_names = __import__("re").findall(r"'([^']+)'", powershell_block)
    function = worker.split("def runner_build_id()", 1)[1].split("def runtime_source_matches", 1)[0]
    tuple_source = function.split("names =", 1)[1].split("\n    source_hashes", 1)[0].strip()
    assert powershell_names == list(ast.literal_eval(tuple_source))
