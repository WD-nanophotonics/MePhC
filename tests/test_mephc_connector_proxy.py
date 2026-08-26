from pathlib import Path

ROOT = Path(__file__).parents[1] / "tools" / "mephc-runner"


def test_connector_uses_persistent_windows_stdio_proxy():
    proxy = (ROOT / "mephc-connector.ps1").read_text(encoding="utf-8-sig")
    command = (ROOT / "mephc-connector.cmd").read_text(encoding="utf-8-sig")
    bootstrap = (ROOT / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    for token in ("$info.Arguments=", "RedirectStandardInput=$true", "RedirectStandardOutput=$true", "RedirectStandardError=$true", "if($child.HasExited)", "Start-McpChild", "WriteLine($line)"):
        assert token in proxy
    assert "ArgumentList" not in proxy
    assert "mephc-connector.ps1" in command
    assert "'mephc-connector.ps1'" in bootstrap
    assert "mcp_server.py" not in command
