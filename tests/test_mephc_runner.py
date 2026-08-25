from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_job_payload_hash_excludes_only_hash_field():
    worker = load("runner_worker", "worker.py")
    job = {"schema": "mephc-runner-job-v1", "job_id": "MEPHC-JOB-ABCDEFGH", "payload_sha256": "ignored"}
    expected = json.dumps({"job_id": job["job_id"], "schema": job["schema"]}, sort_keys=True, separators=(",", ":")).encode()
    assert worker.canonical(job) == expected
    assert hashlib.sha256(worker.canonical(job)).hexdigest()


def test_operation_allowlist_is_exact():
    worker = load("runner_worker_allowlist", "worker.py")
    assert worker.OPERATIONS == {"doctor", "worktree", "prelive", "native", "publish", "courier"}
    assert "shell" not in worker.OPERATIONS


def test_courier_recovery_states_do_not_include_success():
    worker = load("runner_worker_recovery", "worker.py")
    assert "response_received" not in worker.RECOVERABLE
    assert "courier_interrupted" in worker.RECOVERABLE


def test_windows_client_has_no_direct_courier_or_browser_invocation():
    text = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "chat-courier" not in text
    assert "chrome" not in text.lower()
    assert "browser" not in text.lower()
    assert "jobctl.py" in text


def test_project_mismatch_fails_closed(tmp_path):
    worker = load("runner_worker_project", "worker.py")
    job_id = "MEPHC-JOB-ABCDEFGH"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    record = {
        "schema": "mephc-runner-job-v1",
        "job_id": job_id,
        "project_id": "TRILATT",
        "operation": "doctor",
        "arguments": [],
        "expected_root": str(worker.ROOT),
        "expected_head": "0" * 40,
        "certificate_sha256": "",
        "created_at": "2026-08-25T00:00:00Z",
    }
    record["payload_sha256"] = hashlib.sha256(worker.canonical(record)).hexdigest()
    (job_dir / "job.json").write_text(json.dumps(record), encoding="utf-8")
    (job_dir / "READY").write_text("ready\n", encoding="ascii")
    with pytest.raises(worker.Rejected, match="TRILATT") as error:
        worker.validate(job_dir)
    assert error.value.code == "PROJECT_MISMATCH"


def test_payload_tamper_fails_before_execution(tmp_path):
    worker = load("runner_worker_tamper", "worker.py")
    job_id = "MEPHC-JOB-ABCDEFGH"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    record = {
        "schema": "mephc-runner-job-v1",
        "job_id": job_id,
        "project_id": "MEPHC",
        "operation": "doctor",
        "arguments": [],
        "expected_root": str(worker.ROOT),
        "expected_head": "0" * 40,
        "certificate_sha256": "",
        "created_at": "2026-08-25T00:00:00Z",
        "payload_sha256": "f" * 64,
    }
    (job_dir / "job.json").write_text(json.dumps(record), encoding="utf-8")
    (job_dir / "READY").write_text("ready\n", encoding="ascii")
    with pytest.raises(worker.Rejected) as error:
        worker.validate(job_dir)
    assert error.value.code == "PAYLOAD_SHA256_MISMATCH"


def test_courier_path_must_be_mephc_outbox():
    jobctl = load("runner_jobctl_courier", "jobctl.py")
    with pytest.raises(SystemExit, match="outside"):
        jobctl.validate_arguments("courier", ["--request-directory", "/home/icy/TriLatt/outbox/request"])


def test_worker_service_protects_home_and_only_opens_runtime():
    text = (SOURCE / "mephc-runner.service").read_text(encoding="utf-8")
    assert "ProtectHome=read-only" in text
    assert "ReadWritePaths=/home/icy/MePhC/.relayctl" in text
