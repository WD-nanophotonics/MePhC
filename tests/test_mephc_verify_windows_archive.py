import json

import pytest

from tools.mephc_runner_loader import load_runner_module

archive = load_runner_module("archive_windows_copies")
verify = load_runner_module("verify_windows_archive")


def test_verifier_restores_and_detects_payload_corruption(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    data = b"evidence\n"
    (source / "item").write_bytes(data)
    report = {
        "copy_roots": [{
            "project_id": "TEST",
            "path": str(source),
            "files": [{
                "classification": "AMBIGUOUS_FAIL_CLOSED",
                "path": "item",
                "bytes": len(data),
                "sha256": archive.hashlib.sha256(data).hexdigest(),
            }],
        }]
    }
    retention = tmp_path / "retention.json"
    retention.write_text(json.dumps(report), encoding="utf-8")
    scan = archive.scan(report, {"TEST": source})
    output = archive.create_archive(
        retention, "TEST-VERIFY-ARCHIVE", scan,
        roots={"TEST": source}, archive_root=tmp_path / "archives",
    )
    receipt = verify.verify_archive(output)
    assert receipt["status"] == "VERIFIED"
    assert receipt["unique_blob_count"] == 1
    manifest = json.loads((output / "manifest.json").read_text())
    payload = output / manifest["payloads"][0]["path"]
    payload.write_bytes(payload.read_bytes() + b"corrupt")
    with pytest.raises(RuntimeError, match="ARCHIVE_PAYLOAD_BYTE_MISMATCH"):
        verify.verify_archive(output)


def test_verifier_has_no_deletion_primitives():
    text = open(verify.__file__, encoding="utf-8").read()
    for forbidden in (".unlink(", "rmtree(", "remove(", "git clean", "git reset"):
        assert forbidden not in text
