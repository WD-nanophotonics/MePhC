import hashlib
from tools.mephc_runner_loader import load_runner_module

cleanup = load_runner_module("cleanup_residue")


def test_disposable_cleanup_requires_explicit_opt_in(tmp_path):
    source = tmp_path / "cache.pyc"
    data = b"cache"
    source.write_bytes(data)
    report = {"repositories": [{"project_id": "TRILATT", "residues": [{
        "classification": "DISPOSABLE_GENERATED", "path": source.name,
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()
    }]}]}
    without = cleanup.build_plan(report, {"files": []}, {"TRILATT": tmp_path})
    with_opt_in = cleanup.build_plan(
        report, {"files": []}, {"TRILATT": tmp_path}, include_disposable=True
    )
    assert without["entry_count"] == 0
    assert with_opt_in["entry_count"] == 1
    assert with_opt_in["entries"][0]["retention_reason"] == "DISPOSABLE_GENERATED"
