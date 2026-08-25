import hashlib, json, tarfile
from pathlib import Path
from tools.mephc_runner_loader import load_runner_module

archive_residue = load_runner_module("archive_residue")

def report(path, data):
    return {"repositories": [{"project_id": "TRILATT", "residues": [{
        "classification": "AMBIGUOUS_FAIL_CLOSED", "path": path.name,
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}]}

def test_scan_accepts_plain_file(tmp_path):
    data, source = b"plain audit evidence\n", tmp_path / "evidence.txt"
    source.write_bytes(data)
    result = archive_residue.scan(report(source, data), {"TRILATT": tmp_path})
    assert (result["accepted_count"], result["rejected_count"]) == (1, 0)

def test_scan_rejects_secret_without_exposing_value(tmp_path):
    data, source = b"access_token = do-not-print-this", tmp_path / "evidence.txt"
    source.write_bytes(data)
    result = archive_residue.scan(report(source, data), {"TRILATT": tmp_path})
    encoded = json.dumps(result)
    assert "SECRET_OR_CREDENTIAL_CONTENT" in encoded
    assert "do-not-print-this" not in encoded

def test_scan_rejects_source_drift(tmp_path):
    source = tmp_path / "evidence.txt"
    source.write_bytes(b"changed")
    result = archive_residue.scan(report(source, b"original"), {"TRILATT": tmp_path})
    assert result["rejected"][0]["reason"] == "SOURCE_BYTE_MISMATCH"

def test_deterministic_archive(tmp_path):
    data, source = b"payload", tmp_path / "evidence.txt"
    source.write_bytes(data)
    entries = archive_residue.scan(report(source, data), {"TRILATT": tmp_path})["accepted"]
    first = archive_residue.deterministic_tar_gz(entries, {"TRILATT": tmp_path})
    assert first == archive_residue.deterministic_tar_gz(entries, {"TRILATT": tmp_path})
    archive_path = tmp_path / "payload.tar.gz"
    archive_path.write_bytes(first)
    with tarfile.open(archive_path, "r:gz") as output:
        info = output.getmember("TRILATT/evidence.txt")
        assert info.mtime == 0 and output.extractfile(info).read() == data

def test_tool_has_no_deletion_primitives():
    text = Path(archive_residue.__file__).read_text(encoding="utf-8")
    for forbidden in (".unlink(", "rmtree(", "os.remove(", "Remove-Item", "rm -"):
        assert forbidden not in text
