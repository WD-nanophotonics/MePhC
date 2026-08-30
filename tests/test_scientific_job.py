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


def test_contract_is_strict_and_content_addressed():
    module = load_module()
    first = module.validate_contract(contract())
    assert first["contract_sha256"] == module.validate_contract(contract())["contract_sha256"]
    with pytest.raises(module.ScientificJobError, match="FIELDS_INVALID"):
        module.validate_contract({**contract(), "surprise": True})
    with pytest.raises(module.ScientificJobError, match="ENTRYPOINT_INVALID"):
        module.validate_contract(contract(entrypoint="../escape.py"))
    with pytest.raises(module.ScientificJobError, match="BUDGET_INVALID"):
        module.validate_contract(contract(budgets={"native_invocations": 1, "provider_requests": 3, "solver_executions": -1}))


def test_science_contract_cannot_write_framework_and_analysis_is_zero_budget():
    module = load_module("scientific_job_contract_separation")
    with pytest.raises(module.ScientificJobError, match="INFRASTRUCTURE_WRITE_FORBIDDEN"):
        module.validate_contract(contract(allowed_writes=["tools/mephc-flow/new_layer.py"]))
    with pytest.raises(module.ScientificJobError, match="ANALYSIS_BUDGET_NONZERO"):
        module.validate_contract(contract(action="analyze"))
    analysis = contract(action="analyze", inputs={"dataset_id": "d" * 64},
                        budgets={"native_invocations": 0, "provider_requests": 0, "solver_executions": 0})
    assert module.validate_contract(analysis)["action"] == "analyze"


def test_acquisition_may_be_result_only_but_always_requires_result_schema():
    module = load_module("scientific_job_result_only_acquisition")
    result_only = contract(
        expected_output={"dataset_schema": None, "result_schema": "certification-v1"},
    )
    validated = module.validate_contract(result_only)
    assert validated["action"] == "acquire"
    assert validated["expected_output"]["dataset_schema"] is None
    with pytest.raises(module.ScientificJobError, match="ACQUISITION_RESULT_SCHEMA_REQUIRED"):
        module.validate_contract(
            contract(expected_output={"dataset_schema": None, "result_schema": None})
        )


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
    assert validated["expected_output"]["result_schema"].startswith("mephc-diagnostic-result-")
    assert set(validated["required_capabilities"]) <= module.CAPABILITIES


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


def test_solver_free_selftest_covers_codec_checkpoint_result_and_dataset(tmp_path):
    module = load_module("scientific_job_selftest")
    result = module.selftest(ROOT, tmp_path, mpb_smoke=False)
    assert result["payload_codec_tested"] is True
    assert result["checkpoint_tested"] is True
    assert result["result_channel_tested"] is True
    assert result["dataset_consumer_tested"] is True
    assert result["solver_free_import_isolation"] is True
    assert "meep" not in sys.modules
    assert result["mpb_smoke"] == {"executed": False, "reused": False}
    assert (tmp_path / "certifications" / f"{result['runtime_sha256']}.json").is_file()


def test_selftest_rejects_nonmatching_mephc_module_root(tmp_path, monkeypatch):
    module = load_module("scientific_job_wrong_root")
    wrong_root = tmp_path / "wrong"
    package = wrong_root / "mephc"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    original = sys.modules.pop("mephc", None)
    spec = importlib.util.spec_from_file_location("mephc", package / "__init__.py")
    assert spec and spec.loader
    wrong_module = importlib.util.module_from_spec(spec)
    sys.modules["mephc"] = wrong_module
    spec.loader.exec_module(wrong_module)
    try:
        with pytest.raises(module.ScientificJobError, match="SOURCE_MODULE_ROOT_MISMATCH"):
            module.selftest(ROOT, tmp_path / "state", mpb_smoke=False)
    finally:
        sys.modules.pop("mephc", None)
        if original is not None:
            sys.modules["mephc"] = original
