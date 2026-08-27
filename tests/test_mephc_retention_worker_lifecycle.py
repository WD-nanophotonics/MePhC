from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mephc_runtime_lifecycle", ROOT / "tools/mephc-admission/runtime_lifecycle.py"
)
assert SPEC and SPEC.loader
lifecycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lifecycle)


def _worker(start_id: str, pid: int, *, source: str = "a" * 40, updated_at: str = "2026-08-28T00:00:00Z"):
    return {
        "platform": "wsl", "worker_role": "shared_durable_worker", "retention_capable": True,
        "service_name": "mephc-runner.service", "worker_start_id": start_id, "pid": pid,
        "worker_started_at": f"2026-08-28T00:00:0{pid % 10}Z", "updated_at": updated_at,
        "worker_build_id": "b" * 16, "loaded_worker_module_hash": "c" * 64,
        "installed_source_head": source, "source_commit": source, "state_epoch": "epoch-1",
    }


def _health(worker):
    return {"ok": True, "errors": [], "worker": worker,
            "broker": {"platform": "windows", "process_role": "transport_broker",
                       "pid": 900, "supervisor_pid": 901, "worker_ok": True}}


def _install_success_fakes(monkeypatch, before, after):
    responses = iter((_health(before), _health(after)))
    monkeypatch.setattr(lifecycle, "_active_jobs", lambda: [])
    monkeypatch.setattr(lifecycle, "_runner_health", lambda: next(responses))
    monkeypatch.setattr(lifecycle, "_current", lambda: {"source_commit": "a" * 40})
    monkeypatch.setattr(lifecycle, "_run", lambda *_, **__: subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(lifecycle, "_receipt", lambda action, value: {"action": action, **value})


def test_fixed_retention_worker_tool_is_advertised_and_argumentless():
    mcp = (ROOT / "tools/mephc-runner/mcp_server.py").read_text(encoding="utf-8")
    admission = (ROOT / "tools/mephc-admission/mephc_admission.py").read_text(encoding="utf-8")
    assert "mephc_retention_worker_reload" in mcp
    assert '"additionalProperties": False' in mcp
    assert '"mephc_retention_worker_reload": "retention-worker-reload"' in admission
    assert "arguments not in ({}, None)" in admission


def test_reload_proves_real_shared_worker_restart(monkeypatch):
    _install_success_fakes(monkeypatch, _worker("old", 10), _worker("new", 11))
    result = lifecycle.retention_worker_reload()
    assert result["state"] == "RETENTION_WORKER_RELOAD_COMPLETED"
    assert result["worker_role"] == "shared_durable_worker"
    assert result["retention_capable"] is True
    assert result["before_worker_start_id"] != result["after_worker_start_id"]
    assert result["before_worker_pid"] != result["after_worker_pid"]
    assert result["transport_process_separation_proved"] is True


def test_timestamp_change_without_start_identity_change_fails(monkeypatch):
    before = _worker("same", 10, updated_at="2026-08-28T00:00:00Z")
    after = _worker("same", 10, updated_at="2026-08-28T00:00:10Z")
    _install_success_fakes(monkeypatch, before, after)
    monkeypatch.setattr(lifecycle.time, "monotonic", iter((0.0, 31.0)).__next__)
    with pytest.raises(lifecycle.LifecycleError, match="SERVICE_RESTART_TIMEOUT"):
        lifecycle.retention_worker_reload()


def test_reload_rejects_active_job_before_service_action(monkeypatch):
    monkeypatch.setattr(lifecycle, "_active_jobs", lambda: [{"job_id": "MEPHC-JOB-X"}])
    with pytest.raises(lifecycle.LifecycleError, match="ACTIVE_JOB"):
        lifecycle.retention_worker_reload()


@pytest.mark.parametrize("mutation", ["source", "build", "module", "epoch"])
def test_reload_fails_closed_on_runtime_identity_change(monkeypatch, mutation):
    before, after = _worker("old", 10), _worker("new", 11)
    if mutation == "source":
        after["source_commit"] = "d" * 40
    elif mutation == "build":
        after["worker_build_id"] = "d" * 16
    elif mutation == "module":
        after["loaded_worker_module_hash"] = "d" * 64
    else:
        after["state_epoch"] = "epoch-2"
    _install_success_fakes(monkeypatch, before, after)
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.retention_worker_reload()


def test_health_is_read_through_fixed_runner_interface(monkeypatch):
    response = _health(_worker("old", 10))
    monkeypatch.setattr(lifecycle, "_run", lambda argv, **kwargs:
                        subprocess.CompletedProcess(argv, 0, json.dumps(response), ""))
    assert lifecycle._runner_health()["worker"]["worker_start_id"] == "old"
