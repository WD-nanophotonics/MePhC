from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from mephc import relayctl


def test_failure_codes_are_fixed():
    assert {"ROOT_MISMATCH", "WORKTREE_NOT_WSL_NATIVE", "INTERPRETER_MISMATCH", "PRELIVE_UNCOMMITTED", "PRELIVE_TEST_FAILED", "SOURCE_BYTE_MISMATCH", "COURIER_TIMEOUT_RECOVERY_REQUIRED", "COURIER_QUEUE_TIMEOUT", "COURIER_QUEUE_RECOVERY_REQUIRED", "COURIER_INTERRUPTED", "COURIER_HARD_STOP"} <= relayctl.FAILURE_CODES


def test_trilatt_root_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(relayctl, "git", lambda *_: str(tmp_path / "TriLatt") if _[1:3] == ("rev-parse", "--show-toplevel") else ".git")
    with pytest.raises(relayctl.RelayFailure, match="ROOT_MISMATCH"):
        relayctl.worktree_root(tmp_path)


def test_wrong_interpreter_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(relayctl.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    with pytest.raises(relayctl.RelayFailure, match="INTERPRETER_MISMATCH"):
        relayctl.require_python(tmp_path)


def test_manifest_hashes_executable_source(monkeypatch, tmp_path):
    (tmp_path / "run.py").write_text("x=1\n")
    monkeypatch.setattr(relayctl, "git", lambda *_: "run.py")
    assert relayctl.source_manifest(tmp_path) == {"run.py": hashlib.sha256((tmp_path / "run.py").read_bytes()).hexdigest()}


def test_source_drift_fails_closed(monkeypatch, tmp_path):
    record = {"kind": "prelive-attestation", "project_id": "MEPHC", "test_returncode": 0, "prelive_sha": "h", "origin_main": "m", "source_sha256": {"x.py": "old"}}
    monkeypatch.setattr(relayctl, "worktree_root", lambda _=None: tmp_path)
    monkeypatch.setattr(relayctl, "require_python", lambda _: None)
    monkeypatch.setattr(relayctl, "clean", lambda _: None)
    monkeypatch.setattr(relayctl, "head", lambda _: "h")
    monkeypatch.setattr(relayctl, "remote_ref", lambda *_: "m")
    monkeypatch.setattr(relayctl, "read_json", lambda _: record)
    monkeypatch.setattr(relayctl, "source_manifest", lambda _: {"x.py": "new"})
    with pytest.raises(relayctl.RelayFailure, match="SOURCE_BYTE_MISMATCH"):
        relayctl.verify_prelive(tmp_path, "p.json")


def test_doctor_certificate_uses_windows_canonical_control_root(monkeypatch, tmp_path):
    monkeypatch.setattr(relayctl, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(relayctl, "worktree_root", lambda _=None: tmp_path)
    monkeypatch.setattr(relayctl, "require_python", lambda _: None)
    monkeypatch.setattr(relayctl, "head", lambda _: "a" * 40)
    monkeypatch.setattr(relayctl, "remote_ref", lambda *_: "b" * 40)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("MEPHC_RUNNER_BUILD", "a" * 16)
    monkeypatch.setenv("MEPHC_STATE_EPOCH", "epoch-1")
    monkeypatch.setenv("MEPHC_INSTALLED_SOURCE_HEAD", "a" * 40)
    for dependency in ("numpy", "scipy", "shapely"):
        monkeypatch.setitem(sys.modules, dependency, SimpleNamespace(__version__="test"))
    path = relayctl.doctor(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["control_root"] == r"C:\Users\icywo\PycharmProjects\MePhC-Windows"
    assert record["control_root_wsl"].replace("\\", "/") == "/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows"
    assert record["version"] == 2 and record["kind"] == "environment-certificate"


def test_publish_uses_windows_canonical_git_when_execution_checkout_has_no_origin(monkeypatch, tmp_path):
    target, main = "a" * 40, relayctl.EXPECTED_ORIGIN_MAIN
    calls = []

    def fake_windows_git(*args, check=True):
        calls.append(args)
        if args[:1] == ("status",):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ("rev-parse", "HEAD"):
            return SimpleNamespace(returncode=0, stdout=target + "\n", stderr="")
        if args[:1] == ("ls-remote",):
            stdout = f"{main}\trefs/heads/main\n{target}\trefs/heads/sandbox\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(relayctl, "verify_prelive", lambda *_: {"prelive_sha": target, "origin_main": main})
    monkeypatch.setattr(relayctl, "windows_git", fake_windows_git)
    monkeypatch.setattr(relayctl, "STATE_ROOT", tmp_path / "state")
    result = relayctl.publish(tmp_path / "originless-execution-checkout", "prelive.json", True)
    record = json.loads(result.read_text(encoding="utf-8"))
    assert record["sandbox_pushed"] is True
    assert record["push_performed"] is False
    assert record["git_authority"] == "windows_canonical"
    assert not any(call[:1] == ("push",) for call in calls)


def test_publish_fails_closed_when_remote_main_moves(monkeypatch, tmp_path):
    target, moved = "a" * 40, "b" * 40

    def fake_windows_git(*args, check=True):
        if args[:1] == ("status",):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ("rev-parse", "HEAD"):
            return SimpleNamespace(returncode=0, stdout=target + "\n", stderr="")
        if args[:1] == ("ls-remote",):
            stdout = f"{moved}\trefs/heads/main\n{target}\trefs/heads/sandbox\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(relayctl, "verify_prelive", lambda *_: {"prelive_sha": target, "origin_main": relayctl.EXPECTED_ORIGIN_MAIN})
    monkeypatch.setattr(relayctl, "windows_git", fake_windows_git)
    with pytest.raises(relayctl.RelayFailure, match="origin/main moved"):
        relayctl.publish(tmp_path, "prelive.json", True)


def test_prelive_failure_is_specific_and_persists_bounded_diagnostic(monkeypatch, tmp_path):
    state_root = tmp_path / "state"
    monkeypatch.setattr(relayctl, "STATE_ROOT", state_root)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_fail.py").write_text("def test_fail(): pass\n")
    certificate = tmp_path / "certificate.json"
    certificate.write_text("{}")
    monkeypatch.setattr(relayctl, "worktree_root", lambda _=None: tmp_path)
    monkeypatch.setattr(relayctl, "require_python", lambda _: None)
    monkeypatch.setattr(relayctl, "clean", lambda _: None)
    monkeypatch.setattr(relayctl, "load_certificate", lambda *_, **__: (certificate, {"version": 2, "head": "old", "origin_main": "m"}))
    monkeypatch.setattr(relayctl, "head", lambda _: "h")
    monkeypatch.setattr(relayctl, "source_manifest", lambda _: {})
    monkeypatch.setattr(relayctl.subprocess, "run", lambda *_, **__: subprocess.CompletedProcess([], 1, "first\n" + "x" * 2500, "stderr"))
    with pytest.raises(relayctl.RelayFailure) as error:
        relayctl.prelive(tmp_path, str(certificate), ["tests/test_fail.py"])
    assert error.value.code == "PRELIVE_TEST_FAILED"
    assert "summary=" in error.value.detail
    attestation = next((relayctl.runtime(tmp_path) / "prelive").glob("*.json"))
    record = relayctl.read_json(attestation)
    assert record["test_returncode"] == 1
    assert len(record["test_stdout_tail"]) == 2000
    assert record["test_stderr_tail"] == "stderr"


def test_v2_environment_certificate_is_reusable_across_source_commits(monkeypatch, tmp_path):
    certificate = tmp_path / "environment-v2.json"
    record = {
        "version": 2, "kind": "environment-certificate", "project_id": "MEPHC",
        "runner_build": "a" * 16, "state_epoch": "epoch-1",
        "control_root": relayctl.CONTROL_ROOT_WINDOWS, "state_root": str(tmp_path / "state"),
        "python": str(relayctl.REQUIRED_PYTHON.resolve()), "origin_main": relayctl.EXPECTED_ORIGIN_MAIN,
        "head": "1" * 40, "worktree": "/old/checkout",
    }
    certificate.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(relayctl, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setenv("MEPHC_RUNNER_BUILD", "a" * 16)
    monkeypatch.setenv("MEPHC_STATE_EPOCH", "epoch-1")
    monkeypatch.setenv("MEPHC_INSTALLED_SOURCE_HEAD", "2" * 40)
    monkeypatch.setattr(relayctl.sys, "executable", str(relayctl.REQUIRED_PYTHON.resolve()))
    monkeypatch.setattr(relayctl, "head", lambda _: "2" * 40)
    path, loaded = relayctl.load_certificate(tmp_path, str(certificate), for_execution=True)
    assert path == certificate and loaded["head"] == "1" * 40


def test_v1_certificate_cannot_cross_execution_head(monkeypatch, tmp_path):
    certificate = tmp_path / "legacy-v1.json"
    certificate.write_text(json.dumps({"version": 1, "kind": "runtime-certificate", "project_id": "MEPHC",
                                       "worktree": str(tmp_path), "head": "1" * 40}), encoding="utf-8")
    monkeypatch.setattr(relayctl, "head", lambda _: "2" * 40)
    with pytest.raises(relayctl.RelayFailure) as error:
        relayctl.load_certificate(tmp_path, str(certificate), for_execution=True)
    assert error.value.code == "CERTIFICATE_EXECUTION_BINDING_MISMATCH"


def test_e2e_request_is_plain_text(monkeypatch, tmp_path):
    cert = tmp_path / "cert.json"
    cert.write_text("{}")
    monkeypatch.setattr(relayctl, "worktree_root", lambda _=None: tmp_path)
    monkeypatch.setattr(relayctl, "load_certificate", lambda *_: (cert, {}))
    request = relayctl.create_e2e(tmp_path, str(cert))
    manifest = relayctl.read_json(request / "request.json")
    assert manifest["project_id"] == "MEPHC" and manifest["attachments"] == [] and manifest["relay_certificate"] == str(cert)


def test_status_request_is_plain_text_and_contains_no_work_order(monkeypatch, tmp_path):
    cert = tmp_path / "cert.json"
    cert.write_text("{}")
    monkeypatch.setattr(relayctl, "worktree_root", lambda _=None: tmp_path)
    monkeypatch.setattr(relayctl, "load_certificate", lambda *_: (cert, {}))
    monkeypatch.setattr(relayctl, "head", lambda _: "a" * 40)
    monkeypatch.setattr(relayctl, "remote_ref", lambda *_: "b" * 40)
    request = relayctl.create_status(tmp_path, str(cert))
    manifest = relayctl.read_json(request / "request.json")
    message = (request / "message.txt").read_text()
    assert manifest["status_request"] and manifest["attachments"] == [] and request.name.startswith("MEPHC-WORKFLOW-STATUS-")
    assert "No scientific or native execution was performed" in message


def test_bridge_has_required_gates():
    text = (Path(__file__).parents[1] / "tools" / "mephc-courier.ps1").read_text(encoding="utf-8-sig")
    for token in ("validate", "run", "queue_joined", "queue_timeout", "queue_recovery_required", "courier_interrupted", "COURIER_INTERRUPTED", "COURIER_TIMEOUT_RECOVERY_REQUIRED", "submission_count", "alternate_browser_used", "certificatePath", "expectedOutbox", "courier_build_id", "courier_source_root", "expectedCourierRoot", "message_sha256", "events_sha256", "bridge-attestation-send.json", "bridge-attestation-recovery.json"):
        assert token in text


def test_bridge_binds_windows_control_durable_state_and_exact_execution_checkout():
    text = (Path(__file__).parents[1] / "tools" / "mephc-courier.ps1").read_text(encoding="utf-8-sig")
    assert "$ControlRoot='C:\\Users\\icywo\\PycharmProjects\\MePhC-Windows'" in text
    assert "$ControlRootWsl='/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows'" in text
    assert "$StateRoot='/home/icy/.local/state/mephc-runner/MEPHC'" in text
    assert "$ExecutionRoot='/home/icy/.cache/mephc-runner/checkouts'" in text
    assert "$certificateRoot=$StateRoot + '/certificates'" in text
    assert "$expectedWorktree=$ExecutionRoot + '/' + $head" in text
    assert "certificate.control_root" in text
    assert "certificate.courier_request_root" in text
    assert "certificate.canonical_root" not in text
    assert "/home/icy/MePhC" not in text
    assert "$windowsControlBinding -or $legacyWslControlBinding" in text
    assert ".Equals($ControlRootWsl,[System.StringComparison]::Ordinal)" in text
    assert "StartsWith($ControlRootWsl" not in text


def test_bridge_rejects_links_and_non_sha_certificate_heads():
    text = (Path(__file__).parents[1] / "tools" / "mephc-courier.ps1").read_text(encoding="utf-8-sig")
    assert text.count("[IO.FileAttributes]::ReparsePoint") >= 3
    assert "^[0-9a-f]{40}$" in text
    assert "-cne $expectedWorktree" in text


def test_bridge_does_not_require_preflight_before_run():
    text = (Path(__file__).parents[1] / "tools" / "mephc-courier.ps1").read_text(encoding="utf-8-sig")
    assert "& $Courier validate $request" in text
    assert "& $Courier run $request" in text
    assert "& $Courier preflight $request" not in text
    assert "COURIER_NOT_CHAT_READY" not in text


def test_windows_powershell_path_is_fixed():
    assert relayctl.WINDOWS_POWERSHELL == Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")


def test_courier_fails_closed_when_windows_powershell_is_missing(monkeypatch, tmp_path):
    request = tmp_path / ".relayctl" / "outbox" / "MEPHC-TEST"
    request.mkdir(parents=True)
    monkeypatch.setattr(relayctl, "worktree_root", lambda _=None: tmp_path)
    monkeypatch.setattr(relayctl, "require_python", lambda _: None)
    monkeypatch.setattr(relayctl, "WINDOWS_POWERSHELL", tmp_path / "missing-powershell.exe")
    with pytest.raises(relayctl.RelayFailure) as excinfo:
        relayctl.courier(tmp_path, str(request), False)
    assert excinfo.value.code == "COURIER_HARD_STOP"


def test_prelive_targets_reject_options_and_escape(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok(): pass\n")
    assert relayctl.prelive_test_targets(tmp_path, ["tests/test_ok.py"]) == ["tests/test_ok.py"]
    for invalid in ("--help", "../test.py", "tests/missing.py"):
        with pytest.raises(relayctl.RelayFailure, match="PRELIVE_UNCOMMITTED"):
            relayctl.prelive_test_targets(tmp_path, [invalid])


def test_default_prelive_targets_include_runner_infrastructure():
    targets = relayctl.prelive_test_targets(Path(__file__).parents[1], [])
    assert "tests/test_relayctl.py" in targets and "tests/test_mephc_runner.py" in targets
