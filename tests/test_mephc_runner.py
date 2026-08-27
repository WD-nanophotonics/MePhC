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
    assert worker.OPERATIONS == {"doctor", "worktree", "prelive", "native", "publish", "courier", "change"}
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

def test_courier_status_creation_argument_is_exact(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_status", "jobctl.py")
    worker = load("runner_worker_status", "worker.py")
    jobctl.validate_arguments("courier", ["--create-status"])
    with pytest.raises(SystemExit):
        jobctl.validate_arguments("courier", ["--create-status", "extra"])
    assert worker.receipt_state({"operation":"courier","arguments":["--create-status"]}) is None

def test_prelive_rejects_pytest_options():
    jobctl = load("runner_jobctl_prelive_options", "jobctl.py")
    with pytest.raises(SystemExit, match="invalid prelive test target"):
        jobctl.validate_arguments("prelive", ["--help"])

def test_courier_explicit_read_only_recovery_is_typed(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_read_only_recovery", "jobctl.py")
    monkeypatch.setattr(jobctl, "ROOT", tmp_path)
    request = tmp_path / ".relayctl" / "outbox" / "MEPHC-E2E"
    monkeypatch.setattr(jobctl.config, "OUTBOX", request.parent)
    jobctl.validate_arguments("courier", ["--request-directory", str(request), "--recovery-only"])
    with pytest.raises(SystemExit):
        jobctl.validate_arguments("courier", ["--recovery-only", str(request)])

def test_worker_duplicates_prelive_and_recovery_argument_gates():
    text = (SOURCE / "worker.py").read_text(encoding="utf-8")
    assert "PRELIVE_ARGUMENTS_INVALID" in text
    assert 'arguments[2] == "--recovery-only"' in text

def test_project_registry_points_to_public_cmd_launcher():
    registry = json.loads((SOURCE / "project-registry.json").read_text(encoding="utf-8"))
    assert registry["active_project"] == "MEPHC"
    assert registry["runtime"]["windows_launcher"].endswith("\\mephc-runner.cmd")
    assert registry["repositories"][0]["role"] == "WINDOWS_CANONICAL_SOURCE"
    assert registry["repositories"][1]["role"] == "USER_EDITABLE_WSL_DOWNSTREAM"
    assert registry["runtime"]["job_root"].startswith("/home/icy/.local/state/")


def test_worker_service_protects_home_and_only_opens_runtime():
    text = (SOURCE / "mephc-runner.service").read_text(encoding="utf-8")
    assert "ProtectHome=read-only" in text
    assert "ReadWritePaths=/home/icy/.local/state/mephc-runner/MEPHC /home/icy/.cache/mephc-runner" in text


def test_materializer_writes_exact_root_agents_policy_without_sibling_temp(tmp_path, monkeypatch):
    materializer = load("runner_materializer_agents_write", "materializer.py")
    monkeypatch.setattr(materializer, "ROOT", tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_bytes(b"before")
    materializer.atomic(agents, b"after")
    assert agents.read_bytes() == b"after"
    assert list(tmp_path.iterdir()) == [agents]


def test_broker_allows_only_the_exact_root_agents_policy_file():
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    materializer = (SOURCE / "windows_materializer.py").read_text(encoding="utf-8")
    assert 'value != "AGENTS.md"' in materializer
    assert 'pure.parts[0] in {".git", ".relayctl"}' in materializer
    assert "$ControlRoot='C:\\Users\\icywo\\PycharmProjects\\MePhC-Windows'" in broker


def test_change_is_typed_and_native_arbitrary_argv_is_rejected():
    jobctl = load("runner_jobctl_change_gate", "jobctl.py")
    with pytest.raises(SystemExit, match="typed JSON"):
        jobctl.validate_arguments("change", [])
    with pytest.raises(SystemExit, match="--recipe"):
        jobctl.validate_arguments("native", ["python", "script.py"])
    with pytest.raises(SystemExit, match="not registered"):
        jobctl.validate_arguments("native", ["--recipe", "unknown"])


def test_materializer_rejects_traversal_and_symlink(tmp_path, monkeypatch):
    materializer = load("runner_materializer_paths", "materializer.py")
    monkeypatch.setattr(materializer, "ROOT", tmp_path)
    with pytest.raises(materializer.Failure) as error:
        materializer.safe_path("../outside")
    assert error.value.code == "CHANGE_PATH_INVALID"
    (tmp_path / "tests").mkdir()
    try:
        (tmp_path / "tests" / "link").symlink_to(tmp_path / "elsewhere")
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(materializer.Failure) as error:
        materializer.safe_path("tests/link/file.py")
    assert error.value.code == "CHANGE_SYMLINK_FORBIDDEN"


def test_courier_binding_detects_message_mutation(tmp_path):
    worker = load("runner_worker_courier_binding", "worker.py")
    certificate = tmp_path / "certificate.json"; certificate.write_text("{}\n")
    message = tmp_path / "message.txt"; message.write_text("original\n")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"project_id":"MEPHC","request_id":"MEPHC-TEST","message_file":"message.txt","relay_certificate":str(certificate),"attachments":[]}) + "\n")
    binding = {"request_id":"MEPHC-TEST","request_sha256":hashlib.sha256(request.read_bytes()).hexdigest(),"message_sha256":hashlib.sha256(message.read_bytes()).hexdigest(),"certificate_sha256":hashlib.sha256(certificate.read_bytes()).hexdigest()}
    job = {"arguments":["--request-directory",str(tmp_path)],"courier_binding":binding}
    worker.verify_courier_binding(job)
    message.write_text("mutated\n")
    with pytest.raises(worker.Rejected) as error:
        worker.verify_courier_binding(job)
    assert error.value.code == "COURIER_REQUEST_MUTATED"


def test_courier_recovery_forces_read_only_and_limits_prebrowser(tmp_path):
    worker = load("runner_worker_recovery_mode", "worker.py")
    job = {"job_id":"MEPHC-JOB-ABCDEFGH","arguments":["--request-directory",str(tmp_path)]}
    (tmp_path / "receipt.json").write_text(json.dumps({"state":"response_timeout"}))
    assert worker.recovery_arguments(job, 2)[-1] == "--recovery-only"
    (tmp_path / "receipt.json").write_text(json.dumps({"state":"courier_interrupted","interruption_stage":"pre_browser"}))
    assert worker.recovery_arguments(job, 2) == job["arguments"]
    with pytest.raises(worker.Rejected) as error:
        worker.recovery_arguments(job, 3)
    assert error.value.code == "COURIER_PRE_BROWSER_RETRY_EXHAUSTED"


def test_connector_and_install_are_typed_and_versioned():
    mcp = load("runner_mcp_server", "mcp_server.py")
    names = {item["name"] for item in mcp.TOOLS}
    assert names == {"mephc_capabilities","mephc_doctor","mephc_resume","mephc_change","mephc_validate","mephc_submit","mephc_status","mephc_wait","mephc_recover"}
    bootstrap = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "/opt/mephc-runner/versions/$BuildId" in bootstrap
    assert "/opt/mephc-runner/current/jobctl.py" in broker
    assert "$previousOutput.Count -gt 0" in bootstrap
    assert "windows_broker.py" in broker and "windows_broker.py" in bootstrap
    assert "ReadWritePaths=/home/icy/MePhC" not in (SOURCE / "mephc-runner.service").read_text().splitlines()


def test_legacy_v1_recovery_fails_closed_after_archive():
    text = (SOURCE / "worker.py").read_text(encoding="utf-8")
    assert "LEGACY_ARCHIVED_RECOVERY_UNAVAILABLE" in text


def test_health_is_fail_closed_and_capabilities_are_context_complete(tmp_path, monkeypatch):
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "BROKER_HEARTBEAT_STALE" in broker
    assert "WORKER_HEARTBEAT_STALE" in broker
    assert "if($ok){exit 0}else{exit 2}" in broker
    jobctl = load("runner_jobctl_capabilities", "jobctl.py")
    monkeypatch.setattr(jobctl, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(jobctl.workflow, "RUNTIME", tmp_path / "runner")
    monkeypatch.setattr(jobctl.workflow, "LEDGER", tmp_path / "runner" / "ledger.json")
    monkeypatch.setattr(jobctl.workflow, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(jobctl, "git_head", lambda: "a" * 40)
    value = jobctl.capabilities()
    assert value["control_root"] == r"C:\Users\icywo\PycharmProjects\MePhC-Windows"
    assert value["execution_root_policy"].endswith("<commit-sha>")
    assert value["arbitrary_shell"] is False and value["direct_browser"] is False


def test_materializer_main_dispatches_transact_before_apply():
    text = (SOURCE / "materializer.py").read_text(encoding="utf-8")
    assert text.index('if args.mode=="transact"') < text.index('value=apply(Path(args.job_directory))')

def test_mcp_server_initializes_request_and_tolerates_utf8_bom():
    text = (SOURCE / "mcp_server.py").read_text(encoding="utf-8")
    assert "request={}" in text
    assert 'line.lstrip("\\ufeff")' in text


def test_change_transient_unit_has_canonical_working_directory():
    text = (SOURCE / "windows_broker.py").read_text(encoding="utf-8")
    assert "cwd=CONTROL_ROOT" in text


def test_change_and_courier_recovery_are_reachable_and_typed():
    worker = (SOURCE / "worker.py").read_text(encoding="utf-8")
    client = (SOURCE / "materialize_client.py").read_text(encoding="utf-8")
    broker = (SOURCE / "windows_broker.py").read_text(encoding="utf-8")
    assert 'if job["operation"] == "courier":' in worker
    assert 'mode = "recover" if recovery else "transact"' in worker
    assert 'job["operation"] in {"courier", "change"}' in worker
    assert '"MATERIALIZE_RECOVER"' in client
    assert "MATERIALIZE_RECOVER_READY" in broker

def test_change_recovery_accepts_committed_ancestor():
    text = (SOURCE / "materializer.py").read_text(encoding="utf-8")
    assert '"merge-base","--is-ancestor"' in text
    assert "CHANGE_ROLLED_BACK" in text


def test_broker_recovery_dispatch_and_health_fail_closed():
    broker = (SOURCE / "windows_broker.py").read_text(encoding="utf-8")
    health = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert '("recover", "MATERIALIZE_RECOVER_READY")' in broker
    assert "materializer-recovery-state.json" in broker
    assert "BROKER_WORKER_CHECK_FAILED" in health

def test_bootstrap_restarts_broker_and_fixes_parent_cwd():
    text = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    assert 'taskkill.exe" /PID' in text and "windows_broker.py" in text
    assert "Push-Location $Runtime" in text
    assert "-WorkingDirectory $Runtime" in text
    assert "Register-ScheduledTask" in text and "RestartCount 999" in text
    assert "New-ScheduledTaskAction -Execute $windowsPython" in text
    assert "$brokerScript=Join-Path $Runtime 'windows_broker.py'" in text
    assert "-ExecutionPolicy Bypass -File" not in text
    assert "-AllowStartIfOnBatteries" in text and "-DontStopIfGoingOnBatteries" in text
    assert "-DontStopOnIdleEnd" in text and "-StartWhenAvailable" in text
    assert "return (($_.CommandLine" in text
    assert "Stop-ScheduledTask" in text and "Start-ScheduledTask" in text
    assert "Disable-ScheduledTask" in text and "Enable-ScheduledTask" in text
    assert "-notin @('Running','Queued')" in text
    assert "[switch]$Install,[switch]$Verify" in text
    assert "$index -lt 180" in text and "scheduled broker failed to produce current heartbeat" in text
    assert "scheduled broker did not stop cleanly" in text and "pending.broker_start_utc" in text
    assert "pending-install.json" in text and "MEPHC_RUNNER_INSTALL_PENDING_VERIFY" in text
    assert "Get-Content -LiteralPath $previousCurrent -Raw|ConvertFrom-Json" in text
    assert "([json](Get-Content" not in text
    assert "& $publicLauncher Health" in text and "cross-layer health failed" in text
    wrapper = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "Security.Cryptography.SHA256" in wrapper and "Get-FileHash" not in wrapper


def test_attested_failed_change_has_narrow_recovery_path():
    jobctl = (SOURCE / "jobctl.py").read_text(encoding="utf-8")
    worker = (SOURCE / "worker.py").read_text(encoding="utf-8")
    assert "change-attestation.json" in jobctl
    assert "change_attested" in worker


def test_health_binds_build_main_and_unresolved_jobs():
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    worker = (SOURCE / "worker.py").read_text(encoding="utf-8")
    bootstrap = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    assert "RUNNER_BUILD_MISMATCH" in broker
    assert "UNRESOLVED_RUNNER_JOB" in broker
    assert "MAIN_MOVED" in broker
    assert '"origin_main"' in worker
    assert "foreach($name in $Files)" in bootstrap


def test_courier_binding_is_required_before_schema_comparison():
    text = (SOURCE / "worker.py").read_text(encoding="utf-8")
    binding = text.index('required.add("courier_binding")')
    comparison = text.index("if set(job) != required")
    assert binding < comparison


def test_bootstrap_final_doctor_is_inside_rollback_scope():
    text = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    doctor = text.index("cross-layer doctor failed")
    restore = text.index("restored_at", doctor)
    assert restore > doctor

def test_health_detects_windows_install_drift():
    text = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "WINDOWS_INSTALL_MANIFEST_MISSING" in text
    assert "WINDOWS_INSTALL_DRIFT" in text


def test_bootstrap_has_no_collapsed_generated_line():
    lines = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig").splitlines()
    assert max(map(len, lines)) < 500
    assert any(line.strip().startswith("$launcher=Join-Path") for line in lines)


def test_workflow_migrates_rp4b(tmp_path,monkeypatch):
 workflow=load("runner_workflow","workflow.py");runtime=tmp_path/"runner";request=tmp_path/"request";request.mkdir();(request/"response.txt").write_text("NEXT_WORK_ORDER_ID=MEPHC-E9F-C1-RP4-B-20260826-274\\n");monkeypatch.setattr(workflow,"RUNTIME",runtime);monkeypatch.setattr(workflow,"LEDGER",runtime/"ledger.json");monkeypatch.setattr(workflow,"KNOWN",request);assert workflow.active()["active_work_order_id"]=="MEPHC-E9F-C1-RP4-B-20260826-274"


def test_bootstrap_installs_workflow_module():
    assert "'workflow.py'" in (SOURCE/"bootstrap.ps1").read_text(encoding="utf-8-sig")
    assert (SOURCE/"workflow.py").is_file()


def test_materializer_permits_a_new_declared_test_path(tmp_path, monkeypatch):
    materializer = load("runner_materializer_new_test", "materializer.py")
    monkeypatch.setattr(materializer, "ROOT", tmp_path)
    assert materializer.tests(["tests/test_new_contract.py"], {"tests/test_new_contract.py"}) == ["tests/test_new_contract.py"]
    with pytest.raises(materializer.Failure) as error:
        materializer.tests(["audit/test_new_contract.py"], {"audit/test_new_contract.py"})
    assert error.value.code == "CHANGE_TESTS_INVALID"


def test_bridge_requires_bound_attachment_attestation():
    bridge = (SOURCE.parents[1] / "tools" / "mephc-courier.ps1").read_text(encoding="utf-8-sig")
    assert "chat-courier-attachments-v1" in bridge
    assert "attachment attestation is required" in bridge
    assert "10485760" in bridge and "20971520" in bridge


def test_broker_uses_existing_parent_for_new_declared_directories():
    broker = (SOURCE / "windows_broker.py").read_text(encoding="utf-8")
    materializer = (SOURCE / "windows_materializer.py").read_text(encoding="utf-8")
    assert "target.parent.mkdir(parents=True, exist_ok=True)" in materializer
    assert "ALLOWED_TOP" in materializer


def test_change_noop_is_rejected_before_job_creation(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_noop", "jobctl.py")
    target = tmp_path / "tests" / "test_same.py"
    target.parent.mkdir()
    target.write_bytes(b"same\n")
    monkeypatch.setattr(jobctl, "unresolved_change", lambda: None)
    monkeypatch.setattr(jobctl.config, "CONTROL_ROOT", tmp_path)
    with pytest.raises(jobctl.ChangeRejected) as error:
        jobctl.submit_change({"files": [{"path": "tests/test_same.py", "content_utf8": "same\n"}],
                              "tests": ["tests/test_same.py"], "commit_message": "noop"})
    assert error.value.error_code == "CHANGE_NOOP_USE_VALIDATE"
    assert error.value.safe_next_tool == "mephc_validate"
    assert not list(tmp_path.glob("MEPHC-JOB-*"))


def test_change_mixed_noop_names_exact_files(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_mixed_noop", "jobctl.py")
    tests = tmp_path / "tests"; tests.mkdir()
    (tests / "same.py").write_bytes(b"same\n")
    (tests / "changed.py").write_bytes(b"before\n")
    monkeypatch.setattr(jobctl, "unresolved_change", lambda: None)
    monkeypatch.setattr(jobctl.config, "CONTROL_ROOT", tmp_path)
    with pytest.raises(jobctl.ChangeRejected) as error:
        jobctl.submit_change({"files": [
            {"path": "tests/same.py", "content_utf8": "same\n"},
            {"path": "tests/changed.py", "content_utf8": "after\n"}],
            "tests": ["tests/changed.py"], "commit_message": "mixed"})
    assert error.value.error_code == "CHANGE_CONTAINS_NOOP_FILES"
    assert error.value.noop_files == ["tests/same.py"]


def test_doctor_does_not_queue_behind_active_change(monkeypatch):
    jobctl = load("runner_jobctl_doctor_dedupe", "jobctl.py")
    monkeypatch.setattr(jobctl, "active_change", lambda: "MEPHC-JOB-BLOCKED")
    monkeypatch.setattr(jobctl, "unresolved_change", lambda: None)
    monkeypatch.setattr(jobctl, "read_state", lambda _job: {"state": "running", "phase": "committing"})
    value = jobctl.doctor_deduplicated()
    assert value["state"] == "blocked_by_active_change"
    assert value["job_created"] is False


def test_doctor_never_reuses_certificate_when_live_health_is_stale(monkeypatch):
    jobctl = load("runner_jobctl_doctor_live_health", "jobctl.py")
    monkeypatch.setattr(jobctl, "active_change", lambda: None)
    monkeypatch.setattr(jobctl, "unresolved_change", lambda: None)
    monkeypatch.setattr(jobctl, "live_runtime_health", lambda: {
        "ok": False, "errors": ["BROKER_HEARTBEAT_STALE"], "worker": {}, "broker": {}})
    monkeypatch.setattr(jobctl, "submit", lambda *_args: (_ for _ in ()).throw(
        AssertionError("stale health must not create or reuse doctor")))
    value = jobctl.doctor_deduplicated()
    assert value["state"] == "blocked_by_runtime_health"
    assert value["error_code"] == "DOCTOR_LIVE_HEALTH_FAILED"
    assert value["job_created"] is False and value["safe_next_tool"] == "mephc_capabilities"


def test_connector_self_heals_stopped_broker_after_admission():
    connector = (SOURCE / "mephc-connector.ps1").read_text(encoding="utf-8-sig")
    assert "function Ensure-Broker" in connector and "Start-ScheduledTask" in connector
    assert "BROKER_HEARTBEAT_UNAVAILABLE" in connector and "broker_build_id" in connector
    assert "$heartbeatUtc -lt $MinimumUtc.Value" in connector
    assert "if($task.State -notin @('Running','Queued'))" in connector
    assert connector.index("Ensure-Broker") < connector.index("$child=Start-McpChild")


def test_status_exposes_phase_stall_and_health(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_phase", "jobctl.py")
    jobs = tmp_path / "jobs"; runtime = tmp_path / "runner"; job = jobs / "MEPHC-JOB-PHASE"
    job.mkdir(parents=True); runtime.mkdir(exist_ok=True)
    (job / "state.json").write_text(json.dumps({"state": "running"}), encoding="utf-8")
    (job / "client-progress.json").write_text(json.dumps({"phase": "awaiting_materializer",
                                                           "phase_heartbeat_unix": 1.0,
                                                           "deadline_unix": 2.0}), encoding="utf-8")
    broker = tmp_path / "broker.json"; broker.write_text(json.dumps({"updated_unix": 1.0}), encoding="utf-8")
    monkeypatch.setattr(jobctl, "JOBS", jobs); monkeypatch.setattr(jobctl, "RUNTIME", runtime)
    monkeypatch.setattr(jobctl.config, "BROKER_HEARTBEAT", broker)
    value = jobctl.read_state(job.name)
    assert value["phase"] == "awaiting_materializer" and value["stalled"] is True
    assert value["safe_next_tool"] == "mephc_status"
    (job / "state.json").write_text(json.dumps({"state": "failed", "error_code": "CHANGE_NOT_STARTED_ABORTED"}), encoding="utf-8")
    terminal = jobctl.read_state(job.name)
    assert terminal["phase"] == "terminal" and terminal["safe_next_tool"] == "none"


def test_capabilities_inventory_does_not_enrich_every_historical_job(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_capabilities_inventory", "jobctl.py")
    jobs = tmp_path / "jobs"; jobs.mkdir()
    for index, state in enumerate(("succeeded", "failed", "ready")):
        directory = jobs / f"MEPHC-JOB-{index}"; directory.mkdir()
        (directory / "state.json").write_text(json.dumps({"state": state}), encoding="utf-8")
    monkeypatch.setattr(jobctl, "JOBS", jobs)
    jobctl.active_index.rebuild(jobs)
    monkeypatch.setattr(jobctl, "git_head", lambda: "a" * 40)
    monkeypatch.setattr(jobctl.workflow, "view", lambda: {"workflow_state": "available",
                                                           "active_work_order_id": "MEPHC-WORK",
                                                           "pending_job_id": None})
    monkeypatch.setattr(jobctl, "read_state", lambda _job_id: (_ for _ in ()).throw(
        AssertionError("capabilities must not perform per-job health enrichment")))
    value = jobctl.capabilities()
    assert value["active_jobs"] == [{"job_id": "MEPHC-JOB-2", "state": "ready",
                                      "operation": None, "safe_next_action": "status_or_wait"}]


def test_active_index_rebuild_never_reads_oversized_state(tmp_path):
    active_index = load("runner_active_index_bounded", "active_index.py")
    jobs = tmp_path / "jobs"; directory = jobs / "MEPHC-JOB-CORRUPT"; directory.mkdir(parents=True)
    (directory / "state.json").write_bytes(b"{" + b"x" * (active_index.MAX_STATE_BYTES + 1))
    (directory / "job.json").write_text(json.dumps({"operation": "change"}), encoding="utf-8")
    value = active_index.rebuild(jobs)
    assert value[directory.name] == {"state": "unknown", "operation": "change"}


def test_worker_consumes_recovery_marker_before_validation_and_bounds_errors():
    worker = (SOURCE / "worker.py").read_text(encoding="utf-8")
    execute = worker.split("def execute", 1)[1].split("def repair_interrupted", 1)[0]
    assert execute.index('(job_dir / "RECOVER").unlink') < execute.index("validate(job_dir")
    assert "bounded_detail(exc.detail)" in execute
    assert "JOB_JSON_TOO_LARGE" in worker


def test_windows_health_uses_bounded_active_index_not_historical_scan():
    wrapper = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    health = wrapper.split("if($Command -eq 'Health')", 1)[1].split("Ensure-Worker", 1)[0]
    assert "active-jobs.json" in health and "ACTIVE_JOB_INDEX_TOO_LARGE" in health
    assert "Get-ChildItem" not in health and "state.json" not in health


def test_status_fails_bounded_on_oversized_state(tmp_path, monkeypatch):
    jobctl = load("runner_jobctl_bounded_state", "jobctl.py")
    jobs = tmp_path / "jobs"; job = jobs / "MEPHC-JOB-CORRUPT"; job.mkdir(parents=True)
    state = job / "state.json"; state.write_bytes(b"x" * (1024 * 1024 + 1))
    runtime = tmp_path / "runner"; runtime.mkdir()
    monkeypatch.setattr(jobctl, "JOBS", jobs); monkeypatch.setattr(jobctl, "RUNTIME", runtime)
    monkeypatch.setattr(jobctl.config, "BROKER_HEARTBEAT", tmp_path / "broker.json")
    value = jobctl.read_state(job.name)
    assert value["state"] == "unknown" and value["error_code"] == "STATE_FILE_TOO_LARGE"


def test_hash_bound_oversized_state_quarantine_preserves_evidence(tmp_path, monkeypatch):
    repair = load("runner_quarantine_oversized", "quarantine_oversized_state.py")
    jobs = tmp_path / "runner" / "jobs"; job = jobs / "MEPHC-JOB-CORRUPT1"; job.mkdir(parents=True)
    state_bytes, event_bytes = b'{"detail":"recursive"}', b'{"event":"old"}\n'
    (job / "state.json").write_bytes(state_bytes); (job / "events.jsonl").write_bytes(event_bytes)
    (job / "RECOVER").write_text("retry", encoding="ascii")
    monkeypatch.setattr(repair.active_index, "update", lambda *_args: None)
    value = repair.quarantine(jobs, job.name, hashlib.sha256(state_bytes).hexdigest(),
                              hashlib.sha256(event_bytes).hexdigest())
    assert len(value["files"]) == 2 and not (job / "RECOVER").exists()
    assert json.loads((job / "state.json").read_text())["error_code"] == "OVERSIZED_STATE_QUARANTINED"
    for record in value["files"]:
        assert (job / record["name"]).is_file()


def test_broker_is_nonblocking_and_has_exact_tree_watchdog():
    broker = (SOURCE / "windows_broker.py").read_text(encoding="utf-8")
    wrapper = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "CHANGE_MATERIALIZER_TIMEOUT" in broker
    assert '"/PID", str(process.pid), "/T", "/F"' in broker
    assert "process.poll()" in broker and "updated_unix" in broker
    broker_block = wrapper.split("if($Command -eq 'Broker')", 1)[1].split("if($Command -eq 'Health')", 1)[0]
    assert "WaitForExit" not in broker_block
    assert "Ensure-Worker" not in broker_block
    assert '"--heartbeat", str(os.getpid())' in broker
    assert "def heartbeat_process(parent_pid: int)" in broker
    heartbeat_body = broker.split("def heartbeat_process", 1)[1].split("def start_worker_probe", 1)[0]
    assert "atomic_json(HEARTBEAT" in heartbeat_body and "STATE_ROOT" not in heartbeat_body
    assert 'time.time() - float(worker["checked_unix"]) <= 30' in heartbeat_body
    assert "OpenProcess.restype = wintypes.HANDLE" in broker
    assert "WaitForSingleObject.argtypes" in broker and "CloseHandle.argtypes" in broker
    assert "except OSError:" in heartbeat_body
    assert "subprocess.run([str(wsl)" not in broker
    assert "probe.poll()" in broker and "probe.kill()" in broker
    assert "Get-FileHash" not in wrapper and "Security.Cryptography.SHA256" in wrapper


def test_broker_timeout_fault_injection_marks_recovery_without_replay(tmp_path, monkeypatch):
    broker = load("runner_windows_broker_timeout", "windows_broker.py")
    class Hung:
        pid = 4242
        returncode = None
        def poll(self): return None
    calls = []
    monkeypatch.setattr(broker, "terminate_tree", lambda process: calls.append(("terminate", process.pid)))
    monkeypatch.setattr(broker, "fail", lambda job, mode, code, detail: calls.append((mode, code, detail)))
    active = {"job": {"process": Hung(), "job_dir": tmp_path, "mode": "transact", "deadline": 5.0}}
    broker.poll_active(active, current=6.0)
    assert active == {}
    assert calls[0] == ("terminate", 4242)
    assert calls[1][0:2] == ("transact", "CHANGE_MATERIALIZER_TIMEOUT")


def test_recovery_without_journal_never_replays_materialize(tmp_path, monkeypatch):
    materializer = load("runner_windows_materializer_recovery", "windows_materializer.py")
    job = tmp_path / "job"; job.mkdir()
    source = tmp_path / "tests" / "same.py"; source.parent.mkdir(); source.write_bytes(b"same\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (job / "job.json").write_text(json.dumps({"source_commit": "a" * 40,
                                               "change": {"files": [{"path": "tests/same.py",
                                                                        "expected_preimage_sha256": digest}]}}), encoding="utf-8")
    monkeypatch.setattr(materializer, "CONTROL_ROOT", tmp_path)
    monkeypatch.setattr(materializer, "git", lambda *args, **_kwargs: "a" * 40 if args[:2] == ("rev-parse", "HEAD") else "")
    value = materializer.restore_from_journal(job)
    assert value["error_code"] == "CHANGE_NOT_STARTED_ABORTED"
    assert value["recovery"] == "no_effect_verified"


def test_windows_materializer_scopes_git_safe_directory_without_global_config():
    materializer = (SOURCE / "windows_materializer.py").read_text(encoding="utf-8")
    assert 'f"safe.directory={CONTROL_ROOT.as_posix()}"' in materializer
    assert "config --global" not in materializer
    jobctl = (SOURCE / "jobctl.py").read_text(encoding="utf-8")
    worker = (SOURCE / "worker.py").read_text(encoding="utf-8")
    assert 'evidence["recovery_error_code"]=="WINDOWS_MATERIALIZATION_FAILED"' in jobctl
    assert 'prewrite_failed = recovery_state.get("error_code") == "WINDOWS_MATERIALIZATION_FAILED"' in worker
    assert "WINDOWS_GIT_WSL" in jobctl and 'evidence["git_authority"]="windows_git"' in jobctl
    assert 'materializer-recovery-state.json*' in worker
    assert 'archived=directory/f"{name}.attempt-{attempt}"' in jobctl
    assert "prewrite_recovery_evidence" in jobctl and "preimage_mismatches" in jobctl


def test_broker_restart_never_redispatches_abandoned_child():
    broker = (SOURCE / "windows_broker.py").read_text(encoding="utf-8")
    assert "reconcile_abandoned_dispatch(job_dir, mode)" in broker
    assert "BROKER_RESTART_DURING_MATERIALIZATION" in broker
    assert "run_token" in broker and "command_line_for(pid)" in broker


def test_broker_ignores_stale_marker_after_job_enters_recovery(tmp_path):
    broker = load("runner_windows_broker_stale_marker", "windows_broker.py")
    job = tmp_path / "MEPHC-JOB-STALE"; job.mkdir()
    (job / "MATERIALIZE_READY").write_text("{}", encoding="utf-8")
    (job / "state.json").write_text(json.dumps({"state": "recovery_required", "operation": "change"}), encoding="utf-8")
    assert broker.request_for(job) is None
    (job / "state.json").write_text(json.dumps({"state": "running", "operation": "change", "recovery": True}), encoding="utf-8")
    assert broker.request_for(job) is None
    (job / "MATERIALIZE_RECOVER_READY").write_text("{}", encoding="utf-8")
    assert broker.request_for(job)[0] == "recover"


def test_inspect_invalid_offset_advertises_valid_bounds(tmp_path, monkeypatch):
    mcp = load("runner_mcp_inspect_bounds", "mcp_server.py")
    source = tmp_path / "tests" / "small.py"; source.parent.mkdir(); source.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(mcp, "ROOT", tmp_path)
    monkeypatch.setattr(mcp, "_git_files", lambda _relative: ["tests/small.py"])
    with pytest.raises(ValueError) as error:
        mcp.inspect({"operation": "read", "path": "tests/small.py", "offset": 999})
    detail = json.loads(str(error.value))
    assert detail["error_code"] == "INSPECT_SIZE_OR_OFFSET_INVALID"
    assert detail["max_bytes"] == 65536 and detail["size_bytes"] == len(source.read_bytes())


def test_validate_submits_only_prelive_without_change(tmp_path, monkeypatch):
    mcp = load("runner_mcp_validate", "mcp_server.py")
    job_dir = tmp_path / "MEPHC-JOB-VALIDATE"; job_dir.mkdir()
    calls = []
    monkeypatch.setattr(mcp.jobctl, "submit", lambda operation, arguments, certificate: calls.append(
        (operation, arguments, certificate)) or job_dir)
    value = mcp.invoke("mephc_validate", {"tests": ["tests/test_mephc_runner.py"]})
    assert calls == [("prelive", ["tests/test_mephc_runner.py"], None)]
    assert value["job_id"] == job_dir.name and value["job_created"] is True


def test_attachment_e2e_factory_is_typed_and_artifact_bound():
    relayctl = (SOURCE.parents[1] / "mephc" / "relayctl.py").read_text(encoding="utf-8")
    jobctl = (SOURCE / "jobctl.py").read_text(encoding="utf-8")
    worker = (SOURCE / "worker.py").read_text(encoding="utf-8")
    assert "create_attachment_e2e" in relayctl
    assert "MEPHC-ATTACHMENT-E2E-fixture.txt" in relayctl
    assert "--create-attachment-e2e" in jobctl and "--create-attachment-e2e" in worker
