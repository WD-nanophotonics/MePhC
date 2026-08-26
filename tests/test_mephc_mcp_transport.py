from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_call_never_emits_runner_event_as_a_standalone_stdout_record(monkeypatch):
    mcp = load("runner_mcp_stdout_capture", "mcp_server.py")

    def noisy_invoke(name, args):
        print(json.dumps({"event": "runner_job_submitted", "job_id": "MEPHC-JOB-TEST"}))
        return {"job_id": "MEPHC-JOB-TEST", "state": "ready"}

    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "mephc_submit", "arguments": {"operation": "doctor"}},
    }
    monkeypatch.setattr(mcp, "invoke", noisy_invoke)
    monkeypatch.setattr(mcp.sys, "stdin", io.StringIO(json.dumps(request) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(mcp.sys, "stdout", output)
    mcp.main()
    replies = [json.loads(line) for line in output.getvalue().splitlines() if line]
    assert len(replies) == 1
    result = json.loads(replies[0]["result"]["content"][0]["text"])
    assert result["runner_events"] == [
        {"event": "runner_job_submitted", "job_id": "MEPHC-JOB-TEST"}
    ]
