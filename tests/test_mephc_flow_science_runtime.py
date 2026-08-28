from __future__ import annotations

import importlib.util
import inspect
import json
import pickle
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"
RUNTIME_PATH = ROOT / "tools" / "mephc-flow" / "mephc_science_runtime.py"


def load_entrypoint():
    path = AUDIT / "qp_b_c2_c3_r8_locked_set_native.py"
    spec = importlib.util.spec_from_file_location("r8_entrypoint_runtime_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runtime():
    entrypoint = load_entrypoint()
    return entrypoint.load_science_runtime()


def plan():
    entrypoint = load_entrypoint()
    return entrypoint, entrypoint.build_provider_plan(entrypoint.load_frozen_graph())


class FakeRetention:
    def __init__(self):
        self.namespace = {
            "project_id": "MEPHC",
            "science_contract_id": "E9F_C2_QP_B_C2_C3_R8_LOCKED_SET",
            "source_commit": "a" * 40,
            "entrypoint_sha256": "b" * 64,
            "graph_sha256": "c" * 64,
        }
        self.values = {}
        self.stored = []
        self.completed = []

    def expected_identity(self, key):
        return {"key": key.hex()}

    def lookup_exact(self, key):
        return self.values.get(key)

    def store_exact(self, key, payload, identity):
        assert identity == self.expected_identity(key)
        self.values[key] = payload
        self.stored.append(key)

    def mark_complete(self, key):
        self.completed.append(key)

    def finalize_run_manifest(self, summary=None):
        return {"completed_count": len(self.completed), **(summary or {})}

    def finalize_dataset_manifest(self, plan, *, fresh_provider_execution_count, cache_reuse_count, fresh_mpb_execution_observed):
        return {
            "acquisition_source_commit": self.namespace["source_commit"],
            "dataset_id": "d" * 64,
            "manifest_sha256": "e" * 64,
            "dataset_is_mpb_backed": True,
        }


def test_zero_argument_runtime_factory_constructs_official_context(monkeypatch):
    runtime = load_runtime()
    provider_calls = []
    retention = FakeRetention()

    def provider(request):
        provider_calls.append(request)
        return {"frequencies": [1.0], "normalized_vectors": [[1.0]]}

    monkeypatch.setattr(runtime, "_official_r8_provider_factory", lambda: provider)
    monkeypatch.setattr(runtime, "_official_private_retention", lambda: retention)
    context = runtime.create_r8_runtime()
    assert context.provider_solve is provider
    assert context.retention is retention
    assert not [parameter for parameter in inspect.signature(runtime.create_r8_runtime).parameters]


def test_production_entrypoint_uses_official_provider_and_retention_without_injection(monkeypatch):
    entrypoint = load_entrypoint()
    runtime = entrypoint.load_science_runtime()
    retention = FakeRetention()
    calls = []

    def provider(request):
        calls.append(request)
        return {"frequencies": [1.0], "normalized_vectors": [[1.0]]}

    monkeypatch.setattr(runtime, "_official_r8_provider_factory", lambda: provider)
    monkeypatch.setattr(runtime, "_official_private_retention", lambda: retention)
    result = entrypoint.run(())
    assert result["provider_request_count"] == 210
    assert result["fresh_native_solver_execution_count"] == 210
    assert result["cache_reuse_count"] == 0
    assert len(calls) == 210
    assert len(retention.completed) == 210


def test_provider_factory_rejects_outside_frozen_key_before_provider_initialization(monkeypatch):
    entrypoint, requests = plan()
    runtime = load_runtime()
    initialized = []

    def fake_build(_resolution):
        initialized.append(True)
        return object()

    monkeypatch.setattr(runtime, "_build_live_provider", fake_build)
    provider = runtime.build_r8_provider_factory()
    outside = dict(requests[0]["request_key"])
    outside["canonical_k_coordinate_units_1_over_144"] = {"i": 9999, "j": 0}
    with pytest.raises(runtime.ScienceRuntimeError, match="OUTSIDE_FROZEN_GRAPH"):
        provider(outside)
    assert initialized == []


def test_exact_key_retention_requires_full_identity_and_complete_state(monkeypatch, tmp_path):
    runtime = load_runtime()
    entrypoint, requests = plan()
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": "E9F_QP_B_C2_C3_R8_LOCKED_SET",
        "source_commit": "a" * 40,
        "entrypoint_sha256": "b" * 64,
        "graph_sha256": "c" * 64,
    }
    monkeypatch.setattr(runtime, "_trusted_science_state_root", lambda: tmp_path)
    retention = runtime.ExactKeyRetention(namespace)
    key = entrypoint.canonical_key(requests[0]["request_key"])
    payload = {"frequencies": [1.0], "normalized_vectors": [[1.0]]}
    with pytest.raises(runtime.ScienceRuntimeError, match="STATE_INCOMPLETE"):
        retention.store_exact(key, {"metadata": True}, retention.expected_identity(key))
    retention.store_exact(key, payload, retention.expected_identity(key))
    assert retention.lookup_exact(key) is None
    retention.mark_complete(key)
    assert retention.lookup_exact(key) == payload
    wrong = dict(retention.expected_identity(key))
    wrong["source_commit"] = "d" * 40
    with pytest.raises(runtime.ScienceRuntimeError, match="IDENTITY_MISMATCH"):
        retention.store_exact(key, payload, wrong)


def test_incomplete_record_is_not_complete_after_reload(monkeypatch, tmp_path):
    runtime = load_runtime()
    entrypoint, requests = plan()
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": "E9F_QP_B_C2_C3_R8_LOCKED_SET",
        "source_commit": "e" * 40,
        "entrypoint_sha256": "f" * 64,
        "graph_sha256": "1" * 64,
    }
    monkeypatch.setattr(runtime, "_trusted_science_state_root", lambda: tmp_path)
    first = runtime.ExactKeyRetention(namespace)
    key = entrypoint.canonical_key(requests[1]["request_key"])
    first.store_exact(key, {"frequencies": [2.0], "normalized_vectors": [[1.0]]}, first.expected_identity(key))
    second = runtime.ExactKeyRetention(namespace)
    assert second.lookup_exact(key) is None


def test_payload_byte_integrity_and_size_are_verified_before_reuse(monkeypatch, tmp_path):
    runtime = load_runtime()
    entrypoint, requests = plan()
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": "E9F_C2_QP_B_C2_C3_R8_LOCKED_SET",
        "source_commit": "2" * 40,
        "entrypoint_sha256": "3" * 64,
        "graph_sha256": "4" * 64,
    }
    monkeypatch.setattr(runtime, "_trusted_science_state_root", lambda: tmp_path)
    retention = runtime.ExactKeyRetention(namespace)
    key = entrypoint.canonical_key(requests[2]["request_key"])
    payload = {"frequencies": [3.0], "normalized_vectors": [[1.0]]}
    retention.store_exact(key, payload, retention.expected_identity(key))
    retention.mark_complete(key)
    payload_path, metadata_path = retention._paths(key)
    payload_path.write_bytes(payload_path.read_bytes() + b"tamper")
    with pytest.raises(runtime.ScienceRuntimeError, match="INTEGRITY_MISMATCH"):
        retention.lookup_exact(key)
    payload_path.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["payload_size_bytes"] += 1
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(runtime.ScienceRuntimeError, match="INTEGRITY_MISMATCH"):
        retention.lookup_exact(key)


def test_production_summary_does_not_aggregate_payloads_or_exceed_stdout_limit(monkeypatch, capsys):
    entrypoint = load_entrypoint()
    runtime = entrypoint.load_science_runtime()
    retention = FakeRetention()

    def provider(_request):
        return {
            "frequencies": [1.0],
            "normalized_vectors": ["raw-state-" + ("x" * 5000)],
        }

    monkeypatch.setattr(runtime, "_official_r8_provider_factory", lambda: provider)
    monkeypatch.setattr(runtime, "_official_private_retention", lambda: retention)
    monkeypatch.setattr(sys, "argv", ["qp_b_c2_c3_r8_locked_set_native.py"])
    assert entrypoint.main() == 0
    stdout = capsys.readouterr().out
    assert len(stdout.encode("utf-8")) <= entrypoint.MAX_SUCCESS_STDOUT_BYTES
    assert "normalized_vectors" not in stdout
    assert "raw-state-" not in stdout
    assert "opaque_retention_namespace_id" in stdout


def test_complete_dataset_is_immutable_and_cross_commit_consumer_is_read_only(monkeypatch, tmp_path):
    runtime = load_runtime()
    entrypoint, requests = plan()
    namespace = runtime._identity()
    monkeypatch.setattr(runtime, "_trusted_science_state_root", lambda: tmp_path)
    retention = runtime.ExactKeyRetention(namespace)
    calls = []

    def provider(request):
        calls.append(request)
        return {"frequencies": [1.0], "normalized_vectors": [[1.0]]}

    first = runtime.R8ScienceRuntime(provider, retention)
    summary = first.execute(requests)
    assert len(calls) == 210
    assert summary["fresh_provider_execution_count"] == 210
    assert summary["fresh_mpb_execution_observed"] is True
    assert summary["dataset_is_mpb_backed"] is True
    assert len(summary["acquisition_dataset_id"]) == 64
    binding = {
        "acquisition_source_commit": namespace["source_commit"],
        "acquisition_dataset_id": summary["acquisition_dataset_id"],
        "dataset_manifest_sha256": summary["acquisition_dataset_manifest_sha256"],
        "entrypoint_sha256": namespace["entrypoint_sha256"],
        "graph_sha256": namespace["graph_sha256"],
    }
    consumer = runtime.open_r8_dataset(binding)
    assert consumer.lookup_exact(entrypoint.canonical_key(requests[0]["request_key"]))["frequencies"] == [1.0]
    with pytest.raises(runtime.ScienceRuntimeError, match="KEY_NOT_IN_IMMUTABLE_DATASET"):
        consumer.lookup_exact(b"outside")

    calls.clear()
    resumed = runtime.R8ScienceRuntime(lambda _request: pytest.fail("all keys should be reused"), runtime.ExactKeyRetention(namespace))
    resumed_summary = resumed.execute(requests)
    assert resumed_summary["fresh_provider_execution_count"] == 0
    assert resumed_summary["fresh_mpb_execution_observed"] is False
    assert resumed_summary["dataset_is_mpb_backed"] is True
    assert resumed_summary["acquisition_dataset_id"] == summary["acquisition_dataset_id"]


def test_directory_fsync_is_required_for_durable_replacement(monkeypatch, tmp_path):
    runtime = load_runtime()
    entrypoint, requests = plan()
    namespace = runtime._identity()
    monkeypatch.setattr(runtime, "_trusted_science_state_root", lambda: tmp_path)
    fsync_calls = []
    monkeypatch.setattr(runtime, "_fsync_directory", lambda directory: fsync_calls.append(directory))
    retention = runtime.ExactKeyRetention(namespace)
    key = entrypoint.canonical_key(requests[0]["request_key"])
    payload = {"frequencies": [1.0], "normalized_vectors": [[1.0]]}
    retention.store_exact(key, payload, retention.expected_identity(key))
    retention.mark_complete(key)
    assert len(fsync_calls) == 3

    failing = runtime.ExactKeyRetention({**namespace, "source_commit": "9" * 40})
    monkeypatch.setattr(runtime, "_fsync_directory", lambda _directory: (_ for _ in ()).throw(runtime.ScienceRuntimeError("fsync")))
    with pytest.raises(runtime.ScienceRuntimeError, match="fsync"):
        failing.store_exact(key, payload, failing.expected_identity(key))


def test_manifest_summary_is_bounded_and_root_is_canonical_runtime_derived(monkeypatch, tmp_path):
    runtime = load_runtime()
    retention = FakeRetention()
    monkeypatch.setattr(runtime, "_trusted_science_state_root", lambda: tmp_path)
    assert runtime._trusted_science_state_root() == tmp_path
    context = runtime.R8ScienceRuntime(lambda _request: {"frequencies": [1.0], "normalized_vectors": [[1.0]]}, retention)
    _, requests = plan()
    summary = context.execute(requests[:1])
    assert summary["completed_key_count"] == 1
    assert "raw-state-" not in json.dumps(summary)


def test_contract_declares_official_runtime_and_no_caller_surfaces():
    contract = json.loads((AUDIT / "qp_b_c2_c3_r8_native_entrypoint_contract.json").read_text(encoding="utf-8"))
    assert contract["runtime_provider_binding"] == "OFFICIAL_DIRECT_FLOW_FIXED_R8_MPB_PROVIDER"
    assert contract["runtime_retention_binding"] == "OFFICIAL_DIRECT_FLOW_PRIVATE_EXACT_KEY_RETENTION_WITH_PAYLOAD_SHA256"
    assert contract["caller_callback_injection_required"] is False
    assert contract["caller_checkpoint_argument_required"] is False
    assert contract["cli_zero_argument_executable"] is True
    assert contract["private_retention_identity_schema"] == "mephc_direct_flow_exact_key_record_v1"
    assert contract["native_solver_execution_in_tests"] == 0
    assert contract["mpb_execution_in_tests"] is False
