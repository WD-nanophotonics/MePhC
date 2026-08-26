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
