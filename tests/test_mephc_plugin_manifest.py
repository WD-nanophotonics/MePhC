from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "tools" / "mephc-runner" / "plugin" / "mephc-runner"


def test_plugin_starts_connector_without_cmd_unc_current_directory_warning():
    mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["mephc"]

    assert server["command"].lower().endswith("powershell.exe")
    assert server["args"] == [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        r"C:\Users\icywo\AppData\Local\MePhCRunner\mephc-connector.ps1",
    ]
    assert all(not argument.lower().endswith(".cmd") for argument in server["args"])
