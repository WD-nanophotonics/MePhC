from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "tools" / "mephc-flow" / "mephc_flow.py"
JOB_PATH = ROOT / "tools" / "mephc-flow" / "scientific_job.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


flow = load("mephc_flow_c9_i1", FLOW_PATH)
scientific_job = load("scientific_job_c9_i1", JOB_PATH)


def contract(*, dataset: bool = False, manifest: bool = False, native: int = 0) -> dict:
    inputs = {"result_sha256": "c" * 64}
    if dataset:
        inputs["dataset_id"] = "a" * 64
        if manifest:
            inputs["dataset_manifest_sha256"] = "b" * 64
    return {
        "schema": scientific_job.CONTRACT_SCHEMA,
        "kind": "SCIENCE", "work_order_id": "MEPHC-TEST-WORK-ORDER-0001",
        "source_commit": "d" * 40, "action": "analyze", "project": ".",
        "entrypoint": "audit/e9f/c9.py", "inputs": inputs,
        "budgets": {"native_invocations": native, "provider_requests": 0, "solver_executions": 0},
        "required_capabilities": ["exact_checkout", "sandbox_publication", "automatic_provenance"],
        "allowed_writes": ["audit/e9f/c9.py"],
        "expected_output": {"dataset_schema": None, "result_schema": "mephc-r8-c9-terminal-policy-synthesis-v1"},
        "acceptance_criteria": ["provider_executions=0"], "forbidden": ["native_execution"],
    }


def test_artifact_only_contract_validates_without_dummy_dataset() -> None:
    value = scientific_job.validate_contract(contract())
    assert value["contract_sha256"]


def test_dataset_bound_contract_and_manifest_validate() -> None:
    value = scientific_job.validate_contract(contract(dataset=True, manifest=True))
    assert value["inputs"]["dataset_id"] == "a" * 64


def test_malformed_supplied_dataset_id_fails() -> None:
    value = contract(dataset=True)
    value["inputs"]["dataset_id"] = "not-a-dataset"
    with pytest.raises(scientific_job.ScientificJobError, match="ANALYSIS_DATASET_INPUT_INVALID"):
        scientific_job.validate_contract(value)


def test_malformed_supplied_manifest_fails() -> None:
    value = contract(dataset=True, manifest=True)
    value["inputs"]["dataset_manifest_sha256"] = "wrong"
    with pytest.raises(scientific_job.ScientificJobError, match="ANALYSIS_DATASET_MANIFEST_INVALID"):
        scientific_job.validate_contract(value)


def test_artifact_only_analysis_requires_null_dataset_schema() -> None:
    value = contract()
    value["expected_output"]["dataset_schema"] = "mephc-dataset"
    with pytest.raises(scientific_job.ScientificJobError, match="ARTIFACT_ONLY_ANALYSIS_DATASET_SCHEMA_REQUIRED_NULL"):
        scientific_job.validate_contract(value)


def test_artifact_only_analysis_remains_solver_free() -> None:
    for field in ("native_invocations", "provider_requests", "solver_executions"):
        value = contract()
        value["budgets"][field] = 1
        with pytest.raises(scientific_job.ScientificJobError, match="SOLVER_FREE_ANALYSIS_BUDGET_NONZERO"):
            scientific_job.validate_contract(value)


def test_acquire_contract_behavior_is_unchanged() -> None:
    value = contract()
    value.update({
        "action": "acquire", "entrypoint": "audit/e9f/c9_acquire.py",
        "budgets": {"native_invocations": 1, "provider_requests": 1, "solver_executions": 1},
        "expected_output": {"dataset_schema": "dataset", "result_schema": "result"},
    })
    assert scientific_job.validate_contract(value)["action"] == "acquire"


def _preflight_scope(tmp_path: Path) -> flow.Paths:
    return flow.Paths(
        control=tmp_path / "control", state=tmp_path / "state",
        outbox=tmp_path / "outbox", courier=tmp_path / "courier.cmd",
        legacy_state=tmp_path / "legacy", outbox_wsl=flow.OUTBOX_WSL,
        science_state=tmp_path / "science", science_state_wsl=flow.SCIENCE_STATE_WSL,
    )


def test_science_preflight_conditionally_verifies_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _preflight_scope(tmp_path)
    source = {"head": "d" * 40, "origin_sandbox": "d" * 40, "origin_main": flow.EXPECTED_MAIN,
              "branch": "sandbox", "dirty": False}
    calls: list[str] = []

    def prepare(value: dict):
        validated = scientific_job.validate_contract(value)
        monkeypatch.setattr(flow, "active_machine_contract", lambda _paths: ({
            "work_order_id": validated["work_order_id"], "response_sha256": "f" * 64,
        }, validated))
        monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: source)
        monkeypatch.setattr(flow, "ensure_checkout", lambda *_args: "/home/icy/checkout")
        monkeypatch.setattr(flow, "wsl", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""))
        monkeypatch.setattr(flow, "science_runtime_hash", lambda *_args: "e" * 64)
        (scope.science_state / "certifications").mkdir(parents=True)
        (scope.science_state / "certifications" / ("e" * 64 + ".json")).write_text(
            json.dumps({"schema": "mephc-science-runtime-certification-v1"}), encoding="utf-8"
        )
        monkeypatch.setattr(flow, "git", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""))
        monkeypatch.setattr(flow, "dataset_verify", lambda *_args: calls.append("dataset") or {"manifest_sha256": "b" * 64})

    prepare(contract())
    result = flow.science_preflight(scope)
    assert result["dataset_evidence"] is None
    assert calls == []

    prepare(contract(dataset=True, manifest=True))
    result = flow.science_preflight(scope)
    assert result["dataset_evidence"]["manifest_sha256"] == "b" * 64
    assert calls == ["dataset"]


def test_dataset_manifest_mismatch_still_fails_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _preflight_scope(tmp_path)
    value = scientific_job.validate_contract(contract(dataset=True, manifest=True))
    monkeypatch.setattr(flow, "active_machine_contract", lambda _paths: ({
        "work_order_id": value["work_order_id"], "response_sha256": "f" * 64,
    }, value))
    monkeypatch.setattr(flow, "require_source", lambda *_args, **_kwargs: {
        "head": "d" * 40, "origin_sandbox": "d" * 40, "origin_main": flow.EXPECTED_MAIN,
        "branch": "sandbox", "dirty": False,
    })
    monkeypatch.setattr(flow, "ensure_checkout", lambda *_args: "/home/icy/checkout")
    monkeypatch.setattr(flow, "wsl", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(flow, "science_runtime_hash", lambda *_args: "e" * 64)
    (scope.science_state / "certifications").mkdir(parents=True)
    (scope.science_state / "certifications" / ("e" * 64 + ".json")).write_text(
        json.dumps({"schema": "mephc-science-runtime-certification-v1"}), encoding="utf-8"
    )
    monkeypatch.setattr(flow, "git", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(flow, "dataset_verify", lambda *_args: {"manifest_sha256": "f" * 64})
    with pytest.raises(flow.FlowError, match="WORK_ORDER_DATASET_MANIFEST_MISMATCH"):
        flow.science_preflight(scope)


def test_framework_sources_do_not_execute_native_or_mpb_for_these_checks() -> None:
    value = scientific_job.validate_contract(contract())
    assert value["budgets"] == {"native_invocations": 0, "provider_requests": 0, "solver_executions": 0}
