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


def test_windows_cmd_is_fixed_execution_policy_boundary():
    text = (SOURCE / "mephc-runner.cmd").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "%systemroot%\\system32\\windowspowershell\\v1.0\\powershell.exe" in lowered
    assert "-executionpolicy bypass" in lowered
    assert "%mephc_runner_runtime%\\mephc-runner.ps1" in lowered
    assert "wsl.exe" not in lowered
    assert "courier" not in lowered
    assert "browser" not in lowered
    assert "endlocal & exit /b %mephc_runner_exit%" in lowered


def test_bootstrap_installs_and_exercises_public_cmd():
    text = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8")
    assert "'mephc-runner.cmd'" in text
    assert "$publicLauncher=Join-Path $Runtime 'mephc-runner.cmd'" in text
    assert "& $publicLauncher Doctor" in text


def test_prelive_command_resolves_unique_certificate_sha(tmp_path, monkeypatch):
    worker = load("runner_worker_certificate", "worker.py")
    data = b'{"project_id":"MEPHC"}\n'
    certificate = tmp_path / "doctor.json"
    certificate.write_bytes(data)
    monkeypatch.setattr(worker, "CERTIFICATES", tmp_path)
    digest = hashlib.sha256(data).hexdigest()
    command = worker.command_for({
        "operation": "prelive",
        "certificate_sha256": digest,
        "arguments": ["tests/test_relayctl.py"],
    })
    assert command == [
        str(worker.RELAYCTL), "prelive", "--certificate", str(certificate.resolve()),
        "tests/test_relayctl.py",
    ]


def test_duplicate_certificate_sha_fails_closed(tmp_path, monkeypatch):
    worker = load("runner_worker_duplicate_certificate", "worker.py")
    data = b"same"
    (tmp_path / "a.json").write_bytes(data)
    (tmp_path / "b.json").write_bytes(data)
    monkeypatch.setattr(worker, "CERTIFICATES", tmp_path)
    with pytest.raises(worker.Rejected, match="matches=2") as error:
        worker.certificate_path(hashlib.sha256(data).hexdigest())
    assert error.value.code == "CERTIFICATE_INVALID"


def test_certificate_override_is_forbidden():
    worker = load("runner_worker_certificate_override", "worker.py")
    assert "--certificate" in worker.FORBIDDEN_FLAGS


def test_courier_e2e_creation_is_typed_and_certificate_bound(tmp_path, monkeypatch):
    worker = load("runner_worker_e2e", "worker.py")
    data = b"certificate"
    certificate = tmp_path / "doctor.json"
    certificate.write_bytes(data)
    monkeypatch.setattr(worker, "CERTIFICATES", tmp_path)
    job = {"operation": "courier", "arguments": ["--create-e2e"],
           "certificate_sha256": hashlib.sha256(data).hexdigest()}
    assert worker.command_for(job) == [
        str(worker.RELAYCTL), "courier", "--create-e2e", "--certificate",
        str(certificate.resolve()),
    ]
    assert worker.receipt_state(job) is None


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


def test_courier_e2e_creation_argument_is_exact():
    jobctl = load("runner_jobctl_e2e", "jobctl.py")
    jobctl.validate_arguments("courier", ["--create-e2e"])
    with pytest.raises(SystemExit):
        jobctl.validate_arguments("courier", ["--create-e2e", "--certificate", "x"])

def test_prelive_rejects_pytest_options():
    jobctl = load("runner_jobctl_prelive_options", "jobctl.py")
    with pytest.raises(SystemExit, match="invalid prelive test target"):
        jobctl.validate_arguments("prelive", ["--help"])

def test_courier_explicit_read_only_recovery_is_typed(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_read_only_recovery", "jobctl.py")
    monkeypatch.setattr(jobctl, "ROOT", tmp_path)
    request = tmp_path / ".relayctl" / "outbox" / "MEPHC-E2E"
    jobctl.validate_arguments("courier", ["--request-directory", str(request), "--recovery-only"])
    with pytest.raises(SystemExit):
        jobctl.validate_arguments("courier", ["--recovery-only", str(request)])

def test_worker_duplicates_prelive_and_recovery_argument_gates():
    text = (SOURCE / "worker.py").read_text(encoding="utf-8")
    assert "PRELIVE_ARGUMENTS_INVALID" in text
    assert 'arguments[2] == "--recovery-only"' in text


def test_worker_service_protects_home_and_only_opens_runtime():
    text = (SOURCE / "mephc-runner.service").read_text(encoding="utf-8")
    assert "ProtectHome=read-only" in text
    assert "ReadWritePaths=/home/icy/MePhC/.relayctl" in text
