from pathlib import Path

ROOT = Path(__file__).parents[1] / "tools" / "mephc-runner"


def test_connector_uses_persistent_windows_stdio_proxy():
    proxy = (ROOT / "mephc-connector.ps1").read_text(encoding="utf-8-sig")
    command = (ROOT / "mephc-connector.cmd").read_text(encoding="utf-8-sig")
    bootstrap = (ROOT / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    for token in ("$info.Arguments=", "RedirectStandardInput=$true", "RedirectStandardOutput=$true", "RedirectStandardError=$false", "if($child.HasExited)", "Start-McpChild", "StandardOutput.ReadLine()", "MCP_CHILD_EXITED_AFTER_REQUEST", "$child.Kill()"):
        assert token in proxy
    for token in ("Get-AdmissionRequestId", "Reconcile-AdmissionRequest", "mephc_internal_request_disconnect",
                  "safe_next_tool='mephc_request_status'", "admission_request_id=$requestId"):
        assert token in proxy
    assert "ArgumentList" not in proxy
    assert "Kill($true)" not in proxy
    assert "mephc-connector.ps1" in command
    assert "'mephc-connector.ps1'" in bootstrap
    assert "mcp_server.py" not in command


def test_connector_does_not_wait_for_notification_response():
    source = (ROOT / "mephc-connector.ps1").read_text(encoding="utf-8-sig")
    forward = source.index("$child.StandardInput.WriteLine($line)")
    notification_guard = source.index("if(-not $expectsResponse){continue}")
    response_read = source.index("$response=$child.StandardOutput.ReadLine()")

    assert forward < notification_guard < response_read
    assert "$request.PSObject.Properties.Name -contains 'id'" in source
