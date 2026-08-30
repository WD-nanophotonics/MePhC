from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools" / "mephc-flow" / "scientific_job.py"


def load_module(name: str = "scientific_job_test"):
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def contract(**overrides):
    value = {
        "schema": "mephc-science-work-order-v1", "kind": "SCIENCE",
        "work_order_id": "MEPHC-TEST-SCIENCE-0001", "source_commit": "a" * 40,
        "action": "acquire", "project": ".", "entrypoint": "audit/e9f/fixed_entrypoint.py",
        "inputs": {},
        "budgets": {"native_invocations": 1, "provider_requests": 3, "solver_executions": 3},
        "required_capabilities": ["exact_checkout", "private_retention", "result_channel"],
        "allowed_writes": ["audit/e9f/result.json"],
        "expected_output": {"dataset_schema": "test-dataset-v1", "result_schema": "test-result-v1"},
        "acceptance_criteria": ["record_count=3"], "forbidden": ["main_promotion"],
    }
    value.update(overrides)
    return value


def test_contract_is_tolerant_and_execution_intent_is_content_addressed():
    module = load_module()
    first = module.validate_contract(contract())
    assert first["contract_sha256"] == module.validate_contract(contract())["contract_sha256"]
    extra = module.validate_contract({**contract(), "surprise": True})
    assert extra["contract_sha256"] == first["contract_sha256"]
    assert extra["raw_contract_sha256"] != first["raw_contract_sha256"]
    unsafe = module.validate_contract(contract(entrypoint="../escape.py"))
    assert unsafe["budgets"] == {"native_invocations": 0, "provider_requests": 0, "solver_executions": 0}
    assert "native_disabled_without_safe_entrypoint" in unsafe["contract_warnings"]
    negative = module.validate_contract(contract(
        budgets={"native_invocations": 1, "provider_requests": 3, "solver_executions": -1}))
    assert negative["budgets"]["solver_executions"] == 0
    assert "invalid_budget_reduced_to_zero" in negative["contract_warnings"]


def test_query_preferences_are_soft_normalized_and_do_not_change_execution_identity():
    module = load_module("scientific_job_query_preferences")
    base = module.validate_contract(contract())
    preferred = module.validate_contract(contract(query_preferences={
        "task_difficulty": "challenge", "instruction_level": "manual_book",
        "report_policy": "milestone",
    }))
    assert preferred["query_preferences"] == {
        "task_difficulty": "challenge", "instruction_level": "manual_book",
        "report_policy": "milestone",
    }
    assert preferred["contract_sha256"] == base["contract_sha256"]
    invalid = module.validate_contract(contract(query_preferences={
        "task_difficulty": "impossible", "report_policy": 7,
    }))
    assert invalid["query_preferences"] == {}
    assert "invalid_query_preference_ignored:task_difficulty" in invalid["contract_warnings"]
    assert "invalid_query_preference_ignored:report_policy" in invalid["contract_warnings"]


def test_minimal_identity_contract_becomes_zero_execution_clarification():
    module = load_module("scientific_job_minimal_contract")
    normalized = module.validate_contract({
        "work_order_id": "MEPHC-MINIMAL-00000001", "source_commit": "c" * 40,
        "scientific_request": "run something expensive but no budget was declared",
    })
    assert normalized["action"] == "infrastructure"
    assert normalized["entrypoint"] is None
    assert normalized["budgets"] == {
        "native_invocations": 0, "provider_requests": 0, "solver_executions": 0}


def test_science_contract_cannot_write_framework_and_analysis_is_zero_budget():
    module = load_module("scientific_job_contract_separation")
    repaired = module.validate_contract(contract(allowed_writes=["tools/mephc-flow/new_layer.py"]))
    assert "framework_write_outside_advisory_scope" in repaired["contract_warnings"]
    analysis_with_orphan_budget = module.validate_contract(contract(
        action="analyze",
        budgets={"native_invocations": 0, "provider_requests": 1, "solver_executions": 0},
    ))
    assert analysis_with_orphan_budget["budgets"] == {
        "native_invocations": 0, "provider_requests": 0, "solver_executions": 0}
    analysis = contract(action="analyze", inputs={"dataset_id": "d" * 64},
                        budgets={"native_invocations": 0, "provider_requests": 0, "solver_executions": 0})
    assert module.validate_contract(analysis)["action"] == "analyze"


def test_live_recertification_named_analyze_follows_its_explicit_native_budget():
    module = load_module("scientific_job_live_recertification_alias")
    value = contract(
        action="analyze",
        expected_output={"dataset_schema": None, "result_schema": "recertification-v1"},
        budgets={"native_invocations": 1, "provider_requests": 1, "solver_executions": 1},
    )
    assert module.validate_contract(value)["action"] == "acquire"


def test_fresh_chat_capability_aliases_reduce_to_action_budget_minimum():
    module = load_module("scientific_job_capability_aliases")
    value = contract(
        action="analyze",
        expected_output={"dataset_schema": None, "result_schema": "recertification-v1"},
        budgets={"native_invocations": 1, "provider_requests": 1, "solver_executions": 1},
        required_capabilities=["python", "meep", "mpb", "faulthandler"],
    )
    validated = module.validate_contract(value)
    assert validated["action"] == "acquire"
    assert validated["required_capabilities"] == [
        "exact_checkout", "sandbox_publication", "result_channel",
        "automatic_provenance", "native_execution", "mpb",
    ]


def test_infrastructure_primary_artifact_is_not_executed_as_native_entrypoint():
    module = load_module("scientific_job_infrastructure_artifact")
    value = contract(
        kind="INFRASTRUCTURE", action="infrastructure",
        entrypoint="tools/harness_fix.py", allowed_writes=["tools/harness_fix.py"],
        budgets={"native_invocations": 0, "provider_requests": 0, "solver_executions": 0},
        expected_output={"dataset_schema": None, "result_schema": "infra-result-v1"},
    )
    validated = module.validate_contract(value)
    assert validated["entrypoint"] is None
    assert module.validate_contract({**value, "allowed_writes": ["tools/other.py"]})["entrypoint"] is None
    executable = module.validate_contract({
        **value,
        "budgets": {"native_invocations": 1, "provider_requests": 1, "solver_executions": 1},
    })
    assert executable["kind"] == "SCIENCE"
    assert executable["action"] == "acquire"
    assert executable["entrypoint"] == "tools/harness_fix.py"
    assert executable["budgets"] == {
        "native_invocations": 1,
        "provider_requests": 1,
        "solver_executions": 1,
    }


def test_zero_budget_infrastructure_named_analyze_is_solver_free_infrastructure():
    module = load_module("scientific_job_infrastructure_analyze_alias")
    value = contract(
        kind="INFRASTRUCTURE", action="analyze",
        entrypoint="audit/local_affine/stale_science_entrypoint.py",
        allowed_writes=[],
        budgets={"native_invocations": 0, "provider_requests": 0, "solver_executions": 0},
        expected_output={"dataset_schema": None, "result_schema": None},
    )
    validated = module.validate_contract(value)
    assert validated["action"] == "infrastructure"
    assert validated["entrypoint"] is None


def test_tagged_null_entrypoint_is_literal_null_for_infrastructure():
    module = load_module("scientific_job_tagged_null_entrypoint")
    value = contract(
        kind="INFRASTRUCTURE",
        action="analyze",
        entrypoint={"type": "null", "value": None},
        allowed_writes=[],
        budgets={"native_invocations": 0, "provider_requests": 0, "solver_executions": 0},
        expected_output={"dataset_schema": None, "result_schema": None},
    )
    validated = module.validate_contract(value)
    assert validated["action"] == "infrastructure"
    assert validated["entrypoint"] is None


def test_acquisition_may_be_result_only_but_always_requires_result_schema():
    module = load_module("scientific_job_result_only_acquisition")
    result_only = contract(
        expected_output={"dataset_schema": None, "result_schema": "certification-v1"},
    )
    validated = module.validate_contract(result_only)
    assert validated["action"] == "acquire"
    assert validated["expected_output"]["dataset_schema"] is None
    derived = module.validate_contract(
        contract(expected_output={"dataset_schema": None, "result_schema": None})
    )
    assert derived["expected_output"]["result_schema"].startswith("mephc-result-")
    assert "result_schema_derived" in derived["contract_warnings"]


def test_fresh_chat_diagnostic_dialect_normalizes_without_new_action_or_state():
    module = load_module("scientific_job_diagnostic_normalization")
    value = contract(
        kind="diagnostic",
        action="Reproduce one exact worker path and localize its failure.",
        project="MEPHC",
        budgets={
            "native_invocations": 1, "provider_executions": 1,
            "solver_executions": 1, "dataset_records": 0, "retries": 0,
        },
        required_capabilities=["python", "meep", "mpb"],
        expected_output={"transport": "MEPHC_RESULT_PATH", "format": "json",
                         "required_fields": ["schema", "status"]},
    )
    validated = module.validate_contract(value)
    assert validated["kind"] == "SCIENCE"
    assert validated["action"] == "acquire"
    assert validated["project"] == "."
    assert validated["budgets"] == {
        "native_invocations": 1, "provider_requests": 1, "solver_executions": 1,
    }
    assert validated["expected_output"]["dataset_schema"] is None
    assert validated["expected_output"]["result_schema"].startswith("mephc-result-")
    assert set(validated["required_capabilities"]) <= module.CAPABILITIES


def test_one_hundred_chat_dialect_variants_preserve_minimum_risk_intent():
    module = load_module("scientific_job_dialect_soak")
    for index in range(100):
        value = contract(
            kind=("diagnostic" if index % 2 else "SCIENCE"),
            action=("analyze" if index % 3 else "perform bounded recertification"),
            budgets={
                "native_invocations": "1" if index % 2 else 1,
                ("provider_executions" if index % 3 else "provider_requests"): 1,
                "solver_executions": 1,
                "ignored_budget_field": index,
            },
            required_capabilities=["python", "mpb", f"unknown-{index}"],
            unknown_chat_metadata={"index": index},
        )
        normalized = module.validate_contract(value)
        assert normalized["action"] == "acquire"
        assert normalized["entrypoint"] == "audit/e9f/fixed_entrypoint.py"
        assert normalized["budgets"] == {
            "native_invocations": 1, "provider_requests": 1, "solver_executions": 1}


def test_budget_counter_fails_before_extra_provider_or_solver():
    module = load_module("scientific_job_budget")
    counter = module.BudgetCounter(1, 1)
    counter.consume_provider()
    counter.consume_solver()
    with pytest.raises(module.ScientificJobError, match="PROVIDER_REQUEST_BUDGET_EXCEEDED"):
        counter.consume_provider()
    with pytest.raises(module.ScientificJobError, match="SOLVER_EXECUTION_BUDGET_EXCEEDED"):
        counter.consume_solver()


def test_durable_actual_counters_survive_failure_boundaries(tmp_path, monkeypatch):
    module = load_module("scientific_job_durable_counters")
    counters = tmp_path / "counters.json"
    monkeypatch.setenv("MEPHC_EXECUTION_COUNTERS_PATH", str(counters))
    counter = module.BudgetCounter(1, 1)
    counter.consume_provider()
    counter.consume_solver()
    store = module.ImmutableDatasetStore(tmp_path / "state", {"science_contract_id": "COUNTERS"})
    store.put(b"key", b"payload", {"identity": "fixed"})
    value = json.loads(counters.read_text())
    assert value["actual_provider_execution_count"] == 1
    assert value["actual_solver_execution_count"] == 1
    assert value["actual_dataset_record_count"] == 1
    assert isinstance(value["last_counter_update_at"], float)


def test_corrective_contract_is_science_zero_budget():
    module = load_module("scientific_job_corrective")
    value = contract(
        action="corrective", entrypoint=None, mode="CORRECTIVE",
        original_work_order_class="SCIENCE_CORRECTIVE",
        budgets={"native_invocations": 0, "provider_requests": 0, "solver_executions": 0},
        expected_output={"dataset_schema": None, "result_schema": "corrective-v1"},
    )
    validated = module.validate_contract(value)
    assert validated["kind"] == "SCIENCE"
    assert validated["mode"] == "CORRECTIVE"


def test_dataset_is_exact_key_immutable_and_integrity_checked(tmp_path):
    module = load_module("scientific_job_dataset")
    store = module.ImmutableDatasetStore(tmp_path, {"science_contract_id": "TEST", "source_commit": "a" * 40})
    key, payload = b"key-1", b"payload-1"
    record = store.put(key, payload, {"request": 1})
    assert store.get(key) == (payload, record)
    assert store.put(key, payload, {"request": 1}) == record
    with pytest.raises(module.ScientificJobError, match="IMMUTABILITY"):
        store.put(key, b"different", {"request": 1})
    manifest = store.finalize(1, {"source_sha": "a" * 40})
    assert module.verify_dataset(tmp_path, manifest["dataset_id"])["record_count"] == 1
    payload_path, _ = store._paths(key)
    payload_path.write_bytes(b"tamper")
    with pytest.raises(module.ScientificJobError, match="INTEGRITY"):
        module.verify_dataset(tmp_path, manifest["dataset_id"])


def test_partial_record_is_not_finalizable(tmp_path):
    module = load_module("scientific_job_partial")
    store = module.ImmutableDatasetStore(tmp_path, {"science_contract_id": "TEST"})
    key = b"key"
    payload_path, metadata_path = store._paths(key)
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"payload")
    metadata_path.write_text(json.dumps({
        "schema": module.RECORD_SCHEMA, "key_sha256": module.hashlib.sha256(key).hexdigest(),
        "payload_sha256": module.hashlib.sha256(b"payload").hexdigest(),
        "payload_size_bytes": 7, "identity": {}, "complete": False,
    }), encoding="utf-8")
    with pytest.raises(module.ScientificJobError, match="INTEGRITY"):
        store.finalize(1, {})
