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
    assert registry["repositories"][1]["role"] == "LEGACY_AUXILIARY_READ_ONLY"


def test_worker_service_protects_home_and_only_opens_runtime():
    text = (SOURCE / "mephc-runner.service").read_text(encoding="utf-8")
    assert "ProtectHome=read-only" in text
    assert "ReadWritePaths=/home/icy/MePhC/.relayctl" in text


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
    assert "if($relative -eq 'AGENTS.md')" in broker
    assert "/home/icy/MePhC/AGENTS.md" in broker
    assert "'AGENTS.md'" not in broker.split("$allowed=@(", 1)[1].split(")", 1)[0]


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
    (tmp_path / "tests" / "link").symlink_to(tmp_path / "elsewhere")
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
    assert names == {"mephc_capabilities","mephc_doctor","mephc_resume","mephc_change","mephc_submit","mephc_status","mephc_wait","mephc_recover"}
    bootstrap = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "/opt/mephc-runner/versions/$BuildId" in bootstrap
    assert "/opt/mephc-runner/current/jobctl.py" in broker
    assert "$previousOutput.Count -gt 0" in bootstrap
    assert "systemd-run" in broker and "--no-block" in broker
    assert "ReadWritePaths=/home/icy/MePhC" not in (SOURCE / "mephc-runner.service").read_text().splitlines()


def test_health_is_fail_closed_and_capabilities_are_context_complete():
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "BROKER_HEARTBEAT_STALE" in broker
    assert "WORKER_HEARTBEAT_STALE" in broker
    assert "if($ok){exit 0}else{exit 2}" in broker
    jobctl = load("runner_jobctl_capabilities", "jobctl.py")
    value = jobctl.capabilities()
    assert value["canonical_root"] == "/home/icy/MePhC"
    assert value["arbitrary_shell"] is False and value["direct_browser"] is False


def test_materializer_main_dispatches_transact_before_apply():
    text = (SOURCE / "materializer.py").read_text(encoding="utf-8")
    assert text.index('if args.mode=="transact"') < text.index('value=apply(Path(args.job_directory))')

def test_mcp_server_initializes_request_and_tolerates_utf8_bom():
    text = (SOURCE / "mcp_server.py").read_text(encoding="utf-8")
    assert "request={}" in text
    assert 'line.lstrip("\\ufeff")' in text


def test_change_transient_unit_has_canonical_working_directory():
    text = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "'--working-directory=/home/icy/MePhC'" in text


def test_change_and_courier_recovery_are_reachable_and_typed():
    worker = (SOURCE / "worker.py").read_text(encoding="utf-8")
    client = (SOURCE / "materialize_client.py").read_text(encoding="utf-8")
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
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
    broker = (SOURCE / "mephc-runner.ps1").read_text(encoding="utf-8-sig")
    assert "$dispatchName=if(" in broker
    assert "materializer-recovery-state.json" in broker
    assert "BROKER_WORKER_CHECK_FAILED" in broker

def test_bootstrap_restarts_broker_and_fixes_parent_cwd():
    text = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    assert "foreach($process in @($existing)){Stop-Process" in text
    assert "Push-Location $Runtime" in text
    assert "-WorkingDirectory $Runtime" in text


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
