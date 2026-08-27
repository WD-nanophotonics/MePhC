from pathlib import Path

SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def test_bootstrap_installs_resume_coordinator_and_has_initialized_windows_rollback_state():
    text = (SOURCE / "bootstrap.ps1").read_text(encoding="utf-8-sig")
    assert "'workflow_resume.py'" in text
    assert "$previousCurrent=Join-Path $Runtime 'current.json'" in text
    assert "$previousWindowsVersion=''" in text
    assert "if($previousWindowsVersion -and" in text
    assert "for($healthIndex=0;$healthIndex -lt 20;$healthIndex++)" in text
    assert "-not $InventoryStaleReady -and -not $ReconcileStaleReady" in text
