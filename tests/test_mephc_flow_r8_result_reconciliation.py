from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]


def load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_entrypoint_emits_the_exact_native_helper_canonical_bytes(tmp_path):
    entrypoint = load("r8_reconcile_entrypoint", "audit/e9f/qp_b_c2_c3_r8_locked_set_native.py")
    helper = load("r8_reconcile_helper", "tools/mephc-flow/wsl_native_exec.py")
    value = {field: None for field in entrypoint.OUTPUT_FIELDS}
    payload = entrypoint.canonical_result_bytes(value)
    assert b", " not in payload and b": " not in payload
    stream = b"MEPHC_NATIVE_RESULT_JSON=" + payload + b"\n"
    stdout = tmp_path / "stdout.log"
    stdout.write_bytes(stream)
    assert helper.extract_result_summary(stdout) == value


def test_reconciliation_parser_accepts_only_the_known_historical_whitespace_class(tmp_path):
    reconciliation = load("r8_reconciliation", "tools/mephc-flow/reconcile_r8_native_result.py")
    helper = load("r8_reconcile_helper_2", "tools/mephc-flow/wsl_native_exec.py")
    value = {
        "science_contract_id": "E9F_C2_QP_B_C2_C3_R8_LOCKED_SET",
        "opaque_retention_namespace_id": "f" * 24,
    }
    stdout = tmp_path / "stdout.log"
    stdout.write_bytes(b"MEPHC_NATIVE_RESULT_JSON=" + json.dumps(value, sort_keys=True).encode() + b"\n")
    assert reconciliation.historical_marker(stdout, helper) == value

    stdout.write_bytes(b"MEPHC_NATIVE_RESULT_JSON={\"private\":\"/home/icy/forbidden\"}\n")
    with pytest.raises(reconciliation.ReconciliationError, match="HISTORICAL_MARKER_UNSAFE|HISTORICAL_MARKER"):
        reconciliation.historical_marker(stdout, helper)


def test_summary_semantics_are_bound_to_the_immutable_dataset():
    reconciliation = load("r8_reconciliation_summary", "tools/mephc-flow/reconcile_r8_native_result.py")
    manifest = {"science_contract_id": reconciliation.SCIENCE_CONTRACT_ID}
    marker = {
        "science_contract_id": reconciliation.SCIENCE_CONTRACT_ID,
        "source_commit": reconciliation.SOURCE_COMMIT,
        "acquisition_source_commit": reconciliation.SOURCE_COMMIT,
        "entrypoint_sha256": reconciliation.ENTRYPOINT_SHA256,
        "graph_sha256": reconciliation.GRAPH_SHA256,
        "logical_provider_demand_count": 216,
        "unique_provider_request_count": 210,
        "duplicate_logical_demand_count": 6,
        "unique_request_count_by_resolution": {"R96": 70, "R128": 70, "R160": 70},
        "provider_request_count": 210,
        "cache_reuse_count": 0,
        "fresh_provider_execution_count": 210,
        "fresh_native_solver_execution_count": 210,
        "fresh_mpb_execution_observed": True,
        "mpb_execution_observed": True,
        "dataset_is_mpb_backed": True,
        "acquisition_dataset_id": reconciliation.DATASET_ID,
        "acquisition_dataset_manifest_sha256": reconciliation.DATASET_MANIFEST_SHA256,
        "completed_key_count": 210,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "opaque_retention_namespace_id": "f" * 24,
    }
    assert reconciliation.validate_summary(marker, manifest, "f" * 24) == marker
    marker["completed_key_count"] = 209
    with pytest.raises(reconciliation.ReconciliationError, match="SEMANTIC_MISMATCH"):
        reconciliation.validate_summary(marker, manifest, "f" * 24)


def test_native_status_preserves_failed_history_and_surfaces_reconciliation(tmp_path):
    flow = load("r8_flow_status", "tools/mephc-flow/mephc_flow.py")
    run_id = "MEPHC-NATIVE-abcdef0123456789abcdef01"
    run_root = tmp_path / "native-runs"
    recon_root = tmp_path / "reconciliations"
    run_root.mkdir()
    recon_root.mkdir()
    (run_root / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "state": "failed", "result_error": "RESULT_SUMMARY_NOT_CANONICAL",
    }), encoding="utf-8")
    summary = {"completed_key_count": 210, "failed_key_count": 0}
    (recon_root / f"{run_id}.json").write_text(json.dumps({
        "original_native_run_id": run_id,
        "reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED",
        "canonical_result_summary": summary,
    }), encoding="utf-8")
    value = flow.native_status(flow.Paths(state=tmp_path), run_id)
    assert value["state"] == "failed"
    assert value["result_error"] == "RESULT_SUMMARY_NOT_CANONICAL"
    assert value["reconciled"] is True
    assert value["reconciliation_status"] == "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED"
    assert value["reconciled_result_summary"] == summary
