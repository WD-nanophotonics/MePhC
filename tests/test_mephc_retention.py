from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load_retention():
    spec = importlib.util.spec_from_file_location("mephc_retention", SOURCE / "retention.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blob_oid_is_exact_git_blob_identity(tmp_path):
    retention = load_retention()
    path = tmp_path / "evidence.bin"
    path.write_bytes(b"evidence\n")
    expected = hashlib.sha1(b"blob 9\0evidence\n", usedforsecurity=False).hexdigest()
    assert retention.blob_oid(path) == expected


def test_candidate_remote_scope_is_fixed():
    retention = load_retention()
    assert set(retention.REPOSITORIES) == {"MEPHC", "TRILATT", "SQRLATT", "GMAILCOURIER"}
    assert retention.CANDIDATE_REMOTES["GMAILCOURIER"] == ("GMAILCOURIER", "MEPHC", "TRILATT", "SQRLATT")


def test_retention_source_has_no_delete_primitive():
    text = (SOURCE / "retention.py").read_text(encoding="utf-8")
    for token in ("unlink(", "rmtree(", "remove(", "git clean", "git reset"):
        assert token not in text
