from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tomllib

import pytest

ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "tools" / "mephc-runner"
ADMISSION = ROOT / "tools" / "mephc-admission"


def load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_runtime_roots_are_separated_and_outside_checkout():
    config = load("windows_config", RUNNER / "runtime_config.py")
    assert config.CONTROL_ROOT_WINDOWS == r"C:\Users\icywo\PycharmProjects\MePhC-Windows"
    assert config.STATE_ROOT.as_posix() == "/home/icy/.local/state/mephc-runner/MEPHC"
    assert config.CHECKOUTS.as_posix() == "/home/icy/.cache/mephc-runner/checkouts"
    assert config.STATE_ROOT not in config.CHECKOUTS.parents


def test_admission_accepts_only_exact_resolved_windows_root(tmp_path, monkeypatch):
    admission = load("windows_admission", ADMISSION / "mephc_admission.py")
    root = tmp_path / "MePhC-Windows"
    root.mkdir()
    monkeypatch.setattr(admission, "ALLOWED_ROOT", root)
    monkeypatch.setattr(admission.os, "getcwd", lambda: str(root))
    assert admission.inherited_cwd() == root.resolve()
    child = root / "tests"
    child.mkdir()
    monkeypatch.setattr(admission.os, "getcwd", lambda: str(child))
    with pytest.raises(PermissionError, match="ADMISSION_SCOPE_MISMATCH"):
        admission.inherited_cwd()


@pytest.mark.parametrize("value", [r"\\wsl.localhost\Ubuntu\home\icy\MePhC", "///home/icy/MePhC"])
def test_admission_rejects_unc_before_resolution(monkeypatch, value):
    admission = load("windows_admission_unc_" + hashlib.sha1(value.encode()).hexdigest(), ADMISSION / "mephc_admission.py")
    monkeypatch.setattr(admission.os, "getcwd", lambda: value)
    with pytest.raises(PermissionError, match="UNC_FORBIDDEN"):
        admission.inherited_cwd()


def test_scope_rejection_does_not_start_wsl(monkeypatch):
    admission = load("windows_admission_no_child", ADMISSION / "mephc_admission.py")
    called = False
    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("child started")
    monkeypatch.setattr(admission.subprocess, "Popen", forbidden)
    monkeypatch.setattr(admission, "audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(admission, "inherited_cwd", lambda: (_ for _ in ()).throw(PermissionError("ADMISSION_SCOPE_MISMATCH")))
    monkeypatch.setattr(admission.sys, "stdin", iter(()))
    assert admission.main() == 0
    assert called is False


def test_stdio_notifications_are_forwarded_without_waiting_for_response():
    text = (ADMISSION / "mephc_admission.py").read_text(encoding="utf-8")
    forward = text.index('if request.get("id") is None:')
    read = text.index("response = child.stdout.readline()")
    assert forward < read
    assert 'audit("notification_forwarded"' in text


def test_config_patch_changes_only_owned_tables(tmp_path):
    module = load("windows_config_patch", ADMISSION / "config_patch.py")
    config = tmp_path / "config.toml"
    config.write_text(
        "model = 'gpt-5.6'\n\n"
        "[mcp_servers.keep_me]\ncommand = 'keep'\n\n"
        "[mcp_servers.mephc_native]\nurl = 'http://127.0.0.1:8765/mcp'\n\n"
        "[mcp_servers.mephc_admission_probe]\ncommand = 'probe'\nenabled = true\n\n"
        "[mcp_servers.mephc_native_admission_probe]\ncommand = 'old'\n\n"
        "[plugins.\"mephc-runner@personal\"]\nenabled = true\n",
        encoding="utf-8",
    )
    result = module.patch(config, Path("C:/Python/python.exe"), Path("C:/runtime/shim.py"), True)
    after = config.read_text(encoding="utf-8")
    assert result["changed"] is True
    assert "[mcp_servers.keep_me]" in after and "command = 'keep'" in after
    assert "mephc_native_admission_probe" in after
    assert after.count("[mcp_servers.mephc]") == 1
    assert Path(result["backup"]).is_file()
    parsed = tomllib.loads(after)
    assert parsed["mcp_servers"]["mephc"]["enabled"] is True
    assert parsed["mcp_servers"]["mephc"]["command"] == r"C:\Python\python.exe"
    assert parsed["mcp_servers"]["mephc"]["args"] == [r"C:\runtime\shim.py"]
    assert parsed["mcp_servers"]["mephc_native"]["enabled"] is False
    assert parsed["mcp_servers"]["mephc_admission_probe"]["enabled"] is False
    assert parsed["mcp_servers"]["mephc_native_admission_probe"]["enabled"] is False
    assert parsed["plugins"]["mephc-runner@personal"]["enabled"] is False


def test_config_finalize_removes_only_retired_owned_tables(tmp_path):
    module = load("windows_config_finalize", ADMISSION / "config_patch.py")
    config = tmp_path / "config.toml"
    config.write_text(
        "[mcp_servers.keep_me]\ncommand = 'keep'\n\n"
        "[mcp_servers.mephc_windows_shadow]\ncommand = 'shadow'\nenabled = false\n\n"
        "[mcp_servers.mephc_windows_shadow.env]\nTOKEN = 'retired'\n\n"
        "[plugins.\"mephc-runner@personal\"]\nenabled = false\n",
        encoding="utf-8",
    )
    module.patch(config, Path("C:/Python/python.exe"), Path("C:/runtime/shim.py"), True, True)
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["mcp_servers"]["keep_me"]["command"] == "keep"
    assert "mephc_windows_shadow" not in parsed["mcp_servers"]
    assert parsed["mcp_servers"]["mephc"]["enabled"] is True
    assert "plugins" not in parsed


def test_human_runtime_is_strict_and_preserves_project_cwd(monkeypatch, tmp_path):
    module = load("windows_user_runtime", RUNNER / "user_runtime.py")
    root = tmp_path / "control"
    checkout = tmp_path / "checkouts" / ("a" * 40)
    project = tmp_path / "TriLatt"
    for path in (root, checkout, project):
        path.mkdir(parents=True)
    monkeypatch.setattr(module.config, "CONTROL_ROOT", root)
    monkeypatch.setattr(module.config, "CHECKOUTS", checkout.parent)
    monkeypatch.setattr(module.config, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module.config, "EXPECTED_ORIGIN_MAIN", "b" * 40)
    replies = {("symbolic-ref", "--quiet", "--short", "HEAD"): "sandbox",
               ("status", "--porcelain", "--untracked-files=all"): "",
               ("rev-parse", "origin/main"): "b" * 40,
               ("rev-parse", "HEAD"): "a" * 40}
    monkeypatch.setattr(module, "git", lambda *args: replies[args])
    monkeypatch.setattr(module.checkout_manager, "ensure", lambda _commit: checkout)
    monkeypatch.setattr(module, "CURRENT_LINK", tmp_path / "share" / "current")
    assert module.source_commit() == "a" * 40
    linked = True
    try:
        assert module.sync() == checkout.resolve()
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        linked = False
    if linked:
        assert module.CURRENT_LINK.resolve() == checkout.resolve()
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_kw: type("R", (), {"returncode": 0, "stdout": "ext4\n"})())
    assert module.project_path(str(project)) == project.resolve()
    monkeypatch.setenv("MEPHC_RUNNER_JOB_ID", "job")
    with pytest.raises(module.RuntimeFailure, match="BYPASS"):
        module.sync()


def test_state_migration_is_byte_exact_and_keeps_orphan(tmp_path, monkeypatch):
    module = load("windows_state_migration", RUNNER / "migrate_state.py")
    legacy, destination = tmp_path / "legacy", tmp_path / "state"
    orphan = legacy / "runner" / "jobs" / "MEPHC-JOB-ORPHANED"
    orphan.mkdir(parents=True)
    (orphan / "job.json").write_bytes(b'{"legacy":true}\n')
    (legacy / "outbox" / "request").mkdir(parents=True)
    (legacy / "outbox" / "request" / "receipt.json").write_bytes(b"receipt\x00bytes")
    monkeypatch.setattr(module, "LEGACY", legacy)
    monkeypatch.setattr(module.config, "STATE_ROOT", destination)
    result = module.migrate(True)
    assert result["state_epoch"]
    assert (destination / "runner" / "jobs" / "MEPHC-JOB-ORPHANED" / "job.json").read_bytes() == b'{"legacy":true}\n'
    assert (destination / "outbox" / "request" / "receipt.json").read_bytes() == b"receipt\x00bytes"
    assert module.unresolved_jobs(destination) == []
    (destination / "runner" / "jobs" / "MEPHC-JOB-NEW").mkdir()
    assert module.migrate(True)["reused"] is True


def test_state_migration_remains_reusable_after_legacy_archive(tmp_path, monkeypatch):
    module = load("windows_state_migration_archived", RUNNER / "migrate_state.py")
    legacy, destination = tmp_path / "legacy", tmp_path / "state"
    legacy.mkdir()
    monkeypatch.setattr(module, "LEGACY", legacy)
    monkeypatch.setattr(module.config, "STATE_ROOT", destination)
    first = module.migrate(True)
    legacy.rmdir()
    reused = module.migrate(True)
    assert reused["reused"] is True
    assert reused["legacy_present"] is False
    assert reused["state_epoch"] == first["state_epoch"]


def test_new_jobs_bind_control_commit_main_and_epoch(tmp_path, monkeypatch):
    jobctl = load("windows_jobctl_v2", RUNNER / "jobctl.py")
    monkeypatch.setattr(jobctl, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(jobctl, "git_head", lambda: "a" * 40)
    monkeypatch.setattr(jobctl, "git_origin_main", lambda: jobctl.config.EXPECTED_ORIGIN_MAIN)
    monkeypatch.setattr(jobctl.config, "state_epoch", lambda: "epoch-1")
    directory = jobctl.submit("doctor", [], None)
    record = json.loads((directory / "job.json").read_text(encoding="utf-8"))
    assert record["schema"] == "mephc-runner-job-v2"
    assert record["expected_control_root"] == jobctl.config.CONTROL_ROOT_WINDOWS
    assert record["source_commit"] == "a" * 40
    assert record["expected_origin_main"] == jobctl.config.EXPECTED_ORIGIN_MAIN
    assert record["state_epoch"] == "epoch-1"


def test_worker_service_writes_only_state_and_cache():
    text = (RUNNER / "mephc-runner.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/home/icy/.local/state/mephc-runner/MEPHC/runner" in text
    assert "ReadWritePaths=/home/icy/.local/state/mephc-runner/MEPHC /home/icy/.cache/mephc-runner" in text
    assert "ReadWritePaths=/home/icy/MePhC" not in text


def test_bootstraps_do_not_use_codex_mcp_cli_and_do_support_launcher_discovery():
    admission = (ADMISSION / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    assert "Get-Command codex" in admission
    assert "codex mcp add" not in admission.lower()
    assert "codex mcp remove" not in admission.lower()
    assert "CODEX_HOME" in admission


def test_transport_canary_is_argument_free_and_attachment_free():
    text = (RUNNER / "mcp_server.py").read_text(encoding="utf-8")
    assert '"name": "mephc_transport_canary"' in text
    assert "TRANSPORT_CANARY_ACCEPTS_NO_ARGUMENTS" in text
    assert '"attachments": []' in text
    assert '"transport_canary": True' in text


def test_no_infrastructure_default_points_execution_to_mnt_c():
    text = "\n".join(path.read_text(encoding="utf-8-sig") for path in RUNNER.glob("*.*") if path.suffix in {".py", ".ps1", ".service"})
    assert 'MEPHC_EXECUTION_ROOT", "/mnt/c/' not in text
    assert "ReadWritePaths=/mnt/c/" not in text


def test_wsl_control_git_uses_windows_line_ending_semantics():
    text = (RUNNER / "checkout_manager.py").read_text(encoding="utf-8")
    assert text.count('"-c", "core.autocrlf=true"') == 3


def test_execution_cache_carries_audited_remote_tracking_refs():
    text = (RUNNER / "checkout_manager.py").read_text(encoding="utf-8")
    assert "refs/remotes/origin/main:refs/remotes/origin/main" in text
    assert "refs/remotes/origin/sandbox:refs/remotes/origin/sandbox" in text


def test_worker_and_bootstrap_bind_the_same_build_files():
    worker = (RUNNER / "worker.py").read_text(encoding="utf-8")
    bootstrap = (RUNNER / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    for name in ("workflow_resume.py", "runtime_config.py", "checkout_manager.py", "migrate_state.py",
                 "windows_materializer.py", "mephc-connector.ps1"):
        assert f'"{name}"' in worker
        assert f"'{name}'" in bootstrap
    assert "'user_runtime.py'" in bootstrap
    assert "'home_cleanup.py'" in bootstrap
