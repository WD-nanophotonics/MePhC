from __future__ import annotations

import importlib.util
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load_retention():
    spec = importlib.util.spec_from_file_location(
        "mephc_windows_copy_retention",
        SOURCE / "windows_copy_retention.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(classification="AMBIGUOUS_FAIL_CLOSED", path="source.py", sha256="abc"):
    return {
        "classification": classification,
        "path": path,
        "sha256": sha256,
        "bytes": 1,
    }


def test_archive_sha_promotes_exact_bytes():
    retention = load_retention()
    bindings = [{"artifact_id": "A", "archive_commit": "c", "archive_member": "m"}]
    result = retention.reclassify(record(), {"abc": bindings}, set(), set(), False)
    assert result["classification"] == "REMOTE_RETAINED_AUDIT"
    assert result["retained_in_archive_artifacts"] == bindings


def test_archive_member_supports_legacy_and_content_addressed_schema():
    retention = load_retention()
    assert retention.archive_member({"archive_member": "legacy/member"}) == "legacy/member"
    assert retention.archive_member({
        "storage": {"format": "tar-gzip", "member": "blobs/abc"}
    }) == "blobs/abc"
    assert retention.archive_member({
        "storage": {"format": "split-gzip", "parts": [{"path": "payload/part-000"}]}
    }) == "parts:payload/part-000"


def test_archive_member_missing_or_unknown_storage_fails_closed():
    retention = load_retention()
    with __import__("pytest").raises(RuntimeError, match="ARCHIVE_MEMBER_BINDING_MISSING"):
        retention.archive_member({})
    with __import__("pytest").raises(RuntimeError, match="ARCHIVE_MEMBER_BINDING_MISSING"):
        retention.archive_member({
            "storage": {"format": "unknown", "member": "blobs/abc"}
        })


def test_remote_head_eol_materialization_is_disposable():
    retention = load_retention()
    result = retention.reclassify(record(), {}, {"source.py"}, set(), True)
    assert result["classification"] == "DISPOSABLE_GENERATED"
    assert result["disposable_reason"] == "REMOTE_HEAD_TRACKED_EOL_MATERIALIZATION"


def test_meaningful_or_untracked_difference_fails_closed():
    retention = load_retention()
    assert retention.reclassify(
        record(), {}, {"source.py"}, {"source.py"}, True
    )["classification"] == "AMBIGUOUS_FAIL_CLOSED"
    assert retention.reclassify(
        record(), {}, set(), set(), True
    )["classification"] == "AMBIGUOUS_FAIL_CLOSED"


def test_explicit_generated_metadata_is_disposable():
    retention = load_retention()
    result = retention.reclassify(record(path="package.egg-info/PKG-INFO"), {}, set(), set(), False)
    assert result["classification"] == "DISPOSABLE_GENERATED"


def test_runtime_package_token_name_is_not_a_credential():
    retention = load_retention()
    item = record(
        "SECRET_OR_CREDENTIAL",
        ".venv/Lib/site-packages/pygments/token.py",
    )
    result = retention.reclassify(item, {}, set(), set(), False)
    assert result["classification"] == "DISPOSABLE_GENERATED"


def test_retention_source_has_no_delete_primitive():
    text = (SOURCE / "windows_copy_retention.py").read_text(encoding="utf-8")
    for token in ("unlink(", "rmtree(", "remove(", "git clean", "git reset"):
        assert token not in text
