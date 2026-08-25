import hashlib
from pathlib import Path
import pytest
from tools.mephc_runner_loader import load_runner_module

cleanup = load_runner_module("cleanup_residue")

def report(path, data, classification="AMBIGUOUS_FAIL_CLOSED"):
    return {"repositories": [{"project_id": "TRILATT", "residues": [{
        "classification": classification, "path": path.name, "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest()}]}]}

def manifest(path, data):
    return {"files": [{"project_id": "TRILATT", "original_path": path.name,
                       "sha256": hashlib.sha256(data).hexdigest()}]}

def test_plan_requires_archive_match(tmp_path):
    source = tmp_path / "evidence.txt"
    source.write_bytes(b"data")
    with pytest.raises(RuntimeError, match="UNARCHIVED_RESIDUE"):
        cleanup.build_plan(report(source, b"data"), {"files": []}, {"TRILATT": tmp_path})

def test_verify_fails_before_delete_on_any_drift(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"a"); b.write_bytes(b"b")
    combined = {"repositories": [{"project_id": "TRILATT", "residues": [
        {"classification": "REMOTE_RETAINED_AUDIT", "path": "a.txt", "bytes": 1,
         "sha256": hashlib.sha256(b"a").hexdigest()},
        {"classification": "REMOTE_RETAINED_AUDIT", "path": "b.txt", "bytes": 1,
         "sha256": hashlib.sha256(b"b").hexdigest()}]}]}
    plan = cleanup.build_plan(combined, {"files": []}, {"TRILATT": tmp_path})
    b.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="SOURCE_BYTE_MISMATCH"):
        cleanup.remove_entries(plan, {"TRILATT": tmp_path})
    assert a.exists() and b.exists()

def test_exact_cleanup_and_empty_directory_receipt(tmp_path):
    directory = tmp_path / "old"
    directory.mkdir()
    source = directory / "evidence.txt"
    data = b"data"
    source.write_bytes(data)
    r = {"repositories": [{"project_id": "TRILATT", "residues": [{
        "classification": "AMBIGUOUS_FAIL_CLOSED", "path": "old/evidence.txt",
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}]}
    m = {"files": [{"project_id": "TRILATT", "original_path": "old/evidence.txt",
                    "sha256": hashlib.sha256(data).hexdigest()}]}
    plan = cleanup.build_plan(r, m, {"TRILATT": tmp_path})
    receipt = cleanup.remove_entries(plan, {"TRILATT": tmp_path})
    assert receipt["deleted_count"] == 1
    assert not source.exists() and not directory.exists()
