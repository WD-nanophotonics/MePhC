from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

RUNNER = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RUNNER / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_v3_uses_explicit_source_commit_as_expected_head():
    worker = load("worker_expected_head_valid", "worker.py")
    expected = "a" * 40
    assert worker.expected_head_for_job({"source_commit": expected}, True) == expected


def test_missing_expected_head_is_explicit_contract_failure():
    worker = load("worker_expected_head_missing", "worker.py")
    with pytest.raises(worker.Rejected) as missing:
        worker.expected_head_for_job({}, True)
    assert missing.value.code == "RUNNER_CONTRACT_EXPECTED_HEAD_MISSING"
    with pytest.raises(worker.Rejected) as invalid:
        worker.expected_head_for_job({"source_commit": "not-a-sha"}, True)
    assert invalid.value.code == "RUNNER_CONTRACT_EXPECTED_HEAD_INVALID"


def test_mismatched_expected_head_fails_before_payload_execution():
    worker = load("worker_expected_head_mismatch", "worker.py")
    with pytest.raises(worker.Rejected) as mismatch:
        worker.verify_expected_head({"source_commit": "a" * 40}, "b" * 40, True)
    assert mismatch.value.code == "HEAD_MOVED"


def test_failed_retention_job_is_not_completed_and_retry_gets_new_identity(tmp_path, monkeypatch):
    jobctl = load("jobctl_expected_head_retry", "jobctl.py")
    jobs, certs = tmp_path / "jobs", tmp_path / "certificates"
    jobs.mkdir()
    certs.mkdir()
    (certs / "doctor.json").write_text("{}", encoding="utf-8")
    digest = "c" * 64
    active = {
        "active_work_order_id": "WO-RETENTION",
        "work_order_text": f"RETENTION_ID=BOUND_RESULT\nEXPECTED_SHA256={digest}\n",
    }
    monkeypatch.setattr(jobctl, "JOBS", jobs)
    monkeypatch.setattr(jobctl, "CERTIFICATES", certs)
    monkeypatch.setattr(jobctl.workflow, "active", lambda: active)
    monkeypatch.setattr(jobctl, "git_head", lambda: "b" * 40)
    monkeypatch.setattr(jobctl, "git_origin_main", lambda: jobctl.config.EXPECTED_ORIGIN_MAIN)
    monkeypatch.setattr(jobctl.config, "state_epoch", lambda: "test-epoch")
    monkeypatch.setattr(jobctl, "current_runner_build", lambda: "2" * 16)
    monkeypatch.setattr(jobctl, "select_environment_certificate", lambda *_args, **_kwargs: "d" * 64)
    monkeypatch.setattr(jobctl.active_index, "update", lambda *_: None)

    first, reused = jobctl.submit_retention_search(
        [{"retention_id": "BOUND_RESULT", "expected_sha256": digest}]
    )
    assert reused is False
    (first / "state.json").write_text(json.dumps({"state": "failed"}), encoding="utf-8")

    second, reused = jobctl.submit_retention_search(
        [{"retention_id": "BOUND_RESULT", "expected_sha256": digest}]
    )
    assert reused is False
    assert second != first
    assert json.loads((first / "state.json").read_text(encoding="utf-8"))["state"] == "failed"
    assert json.loads((second / "job.json").read_text(encoding="utf-8"))["operation"] == "retention_search"


def test_contract_regression_is_non_scientific():
    source = (RUNNER / "worker.py").read_text(encoding="utf-8")
    assert "provider.solve" not in source
    assert "mpb" not in source.lower()


def test_prefixed_retention_id_binds_to_matching_sha256():
    jobctl = load("jobctl_prefixed_allowlist", "jobctl.py")
    digest = "d" * 64
    text = (
        "AUTHORITATIVE_R96_RESULT_RETENTION_ID=RP3_C3C5_R96_AUTHORITATIVE_RESULT\n"
        "\n"
        f"AUTHORITATIVE_R96_RESULT_SHA256={digest}\n"
    )
    allowed = jobctl._retention_allowlist(text)
    assert allowed["RP3_C3C5_R96_AUTHORITATIVE_RESULT"] == digest
    escaped_text = (
        "AUTHORITATIVE_R96_RESULT_RETENTION_ID=RP3_C3C5_R96_AUTHORITATIVE_RESULT\\n"
        "AUTHORITATIVE_R96_RESULT_SHA256=" + digest + "\\n"
    )
    escaped_allowed = jobctl._retention_allowlist(escaped_text)
    assert escaped_allowed["RP3_C3C5_R96_AUTHORITATIVE_RESULT"] == digest
