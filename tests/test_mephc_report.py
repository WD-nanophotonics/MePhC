from __future__ import annotations

from pathlib import Path


def test_typed_report_api_is_bound_and_hides_outbox_construction():
    source = (Path(__file__).parents[1] / "tools" / "mephc-runner" / "mcp_server.py").read_text(encoding="utf-8")
    assert '"name": "mephc_report"' in source
    assert 'set(args) != {"work_order_id", "message_utf8"}' in source
    assert 'active.get("active_work_order_id") != work_order_id' in source
    assert '"attachments": []' in source
    assert '"report_idempotency_key": key' in source
    assert 'jobctl.submit("courier", arguments, certificate_sha256)' in source
    assert '"--recovery-only"' in source


def test_report_creates_one_request_and_reuses_it_for_timeout_recovery(tmp_path, monkeypatch):
    import importlib.util
    import types

    source_dir = Path(__file__).parents[1] / "tools" / "mephc-runner"
    spec = importlib.util.spec_from_file_location("report_mcp", source_dir / "mcp_server.py")
    assert spec and spec.loader
    mcp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp)

    outbox = tmp_path / "outbox"
    certificates = tmp_path / "certificates"
    certificates.mkdir()
    certificate = certificates / "doctor.json"
    certificate.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(mcp.workflow, "OUTBOX", outbox)
    monkeypatch.setattr(mcp.workflow, "active", lambda: {"active_work_order_id": "MEPHC-E9F-C2-QP-B-C2-20260826-279"})
    monkeypatch.setattr(mcp.jobctl, "CERTIFICATES", certificates)
    calls = []
    monkeypatch.setattr(mcp.jobctl, "submit", lambda operation, arguments, certificate_sha256: (calls.append((operation, arguments, certificate_sha256)) or types.SimpleNamespace(name=f"MEPHC-JOB-{len(calls)}")))

    args = {"work_order_id": "MEPHC-E9F-C2-QP-B-C2-20260826-279", "message_utf8": "Plain-text report.\n"}
    first = mcp.report(args)
    second = mcp.report(args)
    assert first["request_id"] == second["request_id"]
    request_dir = outbox / first["request_id"]
    request = __import__("json").loads((request_dir / "request.json").read_text(encoding="utf-8"))
    assert request["attachments"] == []
    assert request["report_request"] is True
    assert len(list(outbox.iterdir())) == 1
    assert all(call[1][-1] != "--recovery-only" for call in calls)

    (request_dir / "receipt.json").write_text('{"state":"response_timeout"}\n', encoding="utf-8")
    mcp.report(args)
    assert calls[-1][1][-1] == "--recovery-only"
