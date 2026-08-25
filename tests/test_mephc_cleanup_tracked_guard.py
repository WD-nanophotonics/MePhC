import hashlib
import subprocess

import pytest

from tools.mephc_runner_loader import load_runner_module


cleanup = load_runner_module("cleanup_residue")


def test_execution_rejects_target_that_became_tracked(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "later_tracked.txt"
    data = b"same bytes"
    source.write_bytes(data)
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", source.name], check=True)
    plan = {
        "entries": [{
            "project_id": "TRILATT",
            "path": source.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }]
    }
    with pytest.raises(RuntimeError, match="CLEANUP_TARGET_BECAME_TRACKED"):
        cleanup.verify_entries(plan, {"TRILATT": tmp_path}, reject_tracked=True)
    assert source.exists()
