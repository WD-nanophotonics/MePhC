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
    monkeypatch.setattr(admission, "inherited_cwd", lambda: (_ for _ in ()).throw(PermissionError("ADMISSION_SCOPE_MISMATCH")))
    monkeypatch.setattr(admission.sys, "stdin", iter(()))
    assert admission.main() == 0
    assert called is False


def test_config_patch_changes_only_owned_tables(tmp_path):
    module = load("windows_config_patch", ADMISSION / "config_patch.py")
    config = tmp_path / "config.toml"
    config.write_text("model = 'gpt-5.6'\n\n[mcp_servers.keep_me]\ncommand = 'keep'\n\n[mcp_servers.mephc_native_admission_probe]\ncommand = 'old'\n", encoding="utf-8")
    result = module.patch(config, Path("C:/Python/python.exe"), Path("C:/runtime/shim.py"), True)
    after = config.read_text(encoding="utf-8")
    assert result["changed"] is True
    assert "[mcp_servers.keep_me]" in after and "command = 'keep'" in after
    assert "mephc_native_admission_probe" not in after
    assert after.count("[mcp_servers.mephc_windows_shadow]") == 1
    assert Path(result["backup"]).is_file()
    parsed = tomllib.loads(after)
    assert parsed["mcp_servers"]["mephc_windows_shadow"]["enabled"] is True


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
