from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_response(root: Path, name: str, order: str, stamp: int) -> Path:
    directory = root / ".relayctl" / "outbox" / name
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({"project_id": "MEPHC", "attachments": []}))
    (directory / "receipt.json").write_text(json.dumps({"state": "response_received"}))
    response = directory / "response.txt"
    response.write_text(f"NEXT_WORK_ORDER_ID={order}\n")
    response.touch()
    return response


def test_workflow_discovers_latest_hash_bound_response_not_hardcoded_rp4b(tmp_path, monkeypatch):
    workflow = load("runner_workflow_discovery", "workflow.py")
    monkeypatch.setattr(workflow, "ROOT", tmp_path)
    monkeypatch.setattr(workflow, "RUNTIME", tmp_path / ".relayctl" / "runner")
    monkeypatch.setattr(workflow, "LEDGER", tmp_path / ".relayctl" / "runner" / "workflow-ledger.json")
    monkeypatch.setattr(workflow, "OUTBOX", tmp_path / ".relayctl" / "outbox")
    old = write_response(tmp_path, "MEPHC-WORKFLOW-STATUS-OLD", "MEPHC-E9F-C1-RP4-B-20260826-274", 1)
    new = write_response(tmp_path, "MEPHC-WORKFLOW-STATUS-NEW", "MEPHC-E9F-C2-QP-B-C2-20260826-279", 2)
    old.touch()
    import os
    os.utime(old, ns=(1, 1))
    os.utime(new, ns=(2, 2))
    active = workflow.active()
    assert active["active_work_order_id"] == "MEPHC-E9F-C2-QP-B-C2-20260826-279"
    assert "QP-B-C2" in active["work_order_text"]


def test_workflow_ignores_unreceived_or_wrong_project_response(tmp_path, monkeypatch):
    workflow = load("runner_workflow_reject", "workflow.py")
    monkeypatch.setattr(workflow, "ROOT", tmp_path)
    monkeypatch.setattr(workflow, "RUNTIME", tmp_path / ".relayctl" / "runner")
    monkeypatch.setattr(workflow, "LEDGER", tmp_path / ".relayctl" / "runner" / "workflow-ledger.json")
    monkeypatch.setattr(workflow, "OUTBOX", tmp_path / ".relayctl" / "outbox")
    directory = tmp_path / ".relayctl" / "outbox" / "MEPHC-UNCONFIRMED"
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({"project_id": "MEPHC"}))
    (directory / "receipt.json").write_text(json.dumps({"state": "response_timeout"}))
    (directory / "response.txt").write_text("NEXT_WORK_ORDER_ID=MEPHC-E9F-C2-QP-B-C2-20260826-279\n")
    assert workflow.active() is None


def _load_resume(jobctl, workflow):
    previous_jobctl = sys.modules.get("jobctl")
    previous_workflow = sys.modules.get("workflow")
    sys.modules["jobctl"] = jobctl
    sys.modules["workflow"] = workflow
    try:
        return load("runner_workflow_resume_isolated", "workflow_resume.py")
    finally:
        if previous_jobctl is None:
            sys.modules.pop("jobctl", None)
        else:
            sys.modules["jobctl"] = previous_jobctl
        if previous_workflow is None:
            sys.modules.pop("workflow", None)
        else:
            sys.modules["workflow"] = previous_workflow


def _write_job(jobs: Path, job_id: str) -> None:
    directory = jobs / job_id
    directory.mkdir(parents=True)
    (directory / "job.json").write_text(json.dumps({"operation": "courier"}))


def test_resume_creates_one_status_request_then_reuses_its_running_dispatch(tmp_path):
    outbox = tmp_path / "outbox"
    jobs = tmp_path / "jobs"
    calls: list[list[str]] = []
    states: dict[str, str] = {}

    def submit(operation, arguments, certificate):
        assert operation == "courier" and certificate is None
        calls.append(arguments)
        if arguments == ["--create-status"]:
            directory = outbox / "MEPHC-STATUS-ONLY"
            directory.mkdir(parents=True)
            (directory / "request.json").write_text(json.dumps({
                "project_id": "MEPHC",
                "status_request": True,
                "attachments": [],
            }))
            _write_job(jobs, "creation")
            states["creation"] = "succeeded"
            return types.SimpleNamespace(name="creation")
        _write_job(jobs, "dispatch")
        states["dispatch"] = "running"
        return types.SimpleNamespace(name="dispatch")

    jobctl = types.SimpleNamespace(
        JOBS=jobs,
        submit=submit,
        read_state=lambda job_id: {"state": states[job_id]},
    )
    workflow = types.SimpleNamespace(OUTBOX=outbox, active=lambda: None)
    resume = _load_resume(jobctl, workflow)

    first = resume.resume()
    second = resume.resume()

    assert first["workflow_state"] == "awaiting_supervisor"
    assert first["pending_job_id"] == "dispatch"
    assert second["workflow_state"] == "awaiting_supervisor"
    assert second["pending_job_id"] == "dispatch"
    assert calls == [
        ["--create-status"],
        ["--request-directory", str(outbox / "MEPHC-STATUS-ONLY")],
    ]


def test_resume_uses_recovery_only_for_submitted_status_request(tmp_path):
    outbox = tmp_path / "outbox"
    directory = outbox / "MEPHC-STATUS-TIMEOUT"
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps({
        "project_id": "MEPHC",
        "status_request": True,
        "attachments": [],
    }))
    (directory / "receipt.json").write_text(json.dumps({"state": "response_timeout"}))
    calls: list[list[str]] = []

    def submit(operation, arguments, certificate):
        calls.append(arguments)
        return types.SimpleNamespace(name="dispatch")

    jobctl = types.SimpleNamespace(JOBS=tmp_path / "jobs", submit=submit, read_state=lambda job_id: {})
    workflow = types.SimpleNamespace(OUTBOX=outbox, active=lambda: None)
    resume = _load_resume(jobctl, workflow)

    value = resume.resume()

    assert value["pending_job_id"] == "dispatch"
    assert calls == [[
        "--request-directory",
        str(directory),
        "--recovery-only",
    ]]


def test_resume_is_zero_idle_and_never_returns_status_request_required():
    text = (SOURCE / "workflow_resume.py").read_text(encoding="utf-8")
    server = (SOURCE / "mcp_server.py").read_text(encoding="utf-8")
    assert "STATUS_REQUEST_REQUIRED" not in text
    assert 'jobctl.submit("courier", ["--create-status"], None)' in text
    assert '"safe_next_tool": "mephc_wait"' in text
    assert "workflow_resume.resume()" in server


def test_resume_reuses_pending_status_before_creating_another():
    text = (SOURCE / "workflow_resume.py").read_text(encoding="utf-8")
    assert "request = _pending_status()" in text
    assert "if request is None:" in text
    assert 'dispatch = jobctl.submit("courier", _request_arguments(request), None)' in text


def test_mcp_tool_set_stays_typed_and_describes_zero_idle_resume():
    mcp = load("runner_mcp_zero_idle", "mcp_server.py")
    tools = {item["name"]: item for item in mcp.TOOLS}
    assert set(tools) == {"mephc_capabilities", "mephc_doctor", "mephc_resume", "mephc_change", "mephc_submit", "mephc_status", "mephc_wait", "mephc_recover"}
    assert "Never returns an idle" in tools["mephc_resume"]["description"]
