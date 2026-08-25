import hashlib
import json
from pathlib import Path
import tarfile

import pytest

from tools.mephc_runner_loader import load_runner_module

archive = load_runner_module("archive_windows_copies")


def report(root, records):
    return {
        "copy_roots": [{
            "project_id": "TEST",
            "path": str(root),
            "files": records,
        }]
    }


def item(path, data):
    return {
        "classification": "AMBIGUOUS_FAIL_CLOSED",
        "path": path,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_scan_deduplicates_without_losing_references(tmp_path):
    data = b"same evidence\n"
    (tmp_path / "a").write_bytes(data)
    (tmp_path / "b").write_bytes(data)
    result = archive.scan(report(tmp_path, [item("a", data), item("b", data)]), {"TEST": tmp_path})
    assert result["accepted_count"] == 2
    assert result["unique_blob_count"] == 1
    assert result["rejected_count"] == 0


def test_inspect_file_combines_hash_and_sensitive_scan(tmp_path):
    path = tmp_path / "evidence"
    path.write_bytes(b"access_token = hidden")
    assert archive.inspect_file(path) == (hashlib.sha256(path.read_bytes()).hexdigest(), True)


def test_scan_rejects_source_drift_and_secret(tmp_path):
    (tmp_path / "changed").write_bytes(b"changed")
    secret = b"access_token = hidden"
    (tmp_path / "secret.txt").write_bytes(secret)
    records = [item("changed", b"original"), item("secret.txt", secret)]
    result = archive.scan(report(tmp_path, records), {"TEST": tmp_path})
    reasons = {entry["reason"] for entry in result["rejected"]}
    assert reasons == {"SOURCE_BYTE_MISMATCH", "SECRET_OR_CREDENTIAL_CONTENT"}


def test_split_writer_enforces_part_limit(tmp_path):
    writer = archive.SplitWriter(tmp_path, "blob", limit=4)
    writer.write(b"abcdefghij")
    writer.close()
    assert [path.read_bytes() for path in writer.parts] == [b"abcd", b"efgh", b"ij"]


def test_archive_is_content_addressed_and_restorable(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    data = b"payload\n"
    (root / "a").write_bytes(data)
    (root / "b").write_bytes(data)
    retention = tmp_path / "retention.json"
    payload = report(root, [item("a", data), item("b", data)])
    retention.write_text(json.dumps(payload), encoding="utf-8")
    result = archive.scan(payload, {"TEST": root})
    output = archive.create_archive(
        retention, "TEST-ARCHIVE-001", result,
        roots={"TEST": root}, archive_root=tmp_path / "archives",
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["reference_count"] == 2
    assert manifest["unique_blob_count"] == 1
    storage = manifest["files"][0]["storage"]
    assert storage["format"] == "tar-gzip"
    with tarfile.open(output / storage["payload"]["path"], "r:gz") as handle:
        assert handle.extractfile(storage["member"]).read() == data


def test_archive_rejects_source_drift_after_scan(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    original = b"original"
    path = root / "evidence"
    path.write_bytes(original)
    retention = tmp_path / "retention.json"
    payload = report(root, [item("evidence", original)])
    retention.write_text(json.dumps(payload), encoding="utf-8")
    result = archive.scan(payload, {"TEST": root})
    path.write_bytes(b"modified")
    with pytest.raises(RuntimeError, match="SOURCE_BYTE_MISMATCH"):
        archive.create_archive(
            retention, "TEST-ARCHIVE-DRIFT", result,
            roots={"TEST": root}, archive_root=tmp_path / "archives",
        )


def test_tool_has_no_deletion_primitives():
    text = Path(archive.__file__).read_text(encoding="utf-8")
    for forbidden in (".unlink(", "rmtree(", "os.remove(", "Remove-Item", "rm -"):
        assert forbidden not in text
