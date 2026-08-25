import hashlib
from pathlib import Path
import pytest
from tools.mephc_runner_loader import load_runner_module

executor = load_runner_module("execute_windows_copy_cleanup")

def digest(data):
    return hashlib.sha256(data).hexdigest()

def make_plan(copy_root, payload_path):
    source = copy_root / "nested" / "evidence.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"copy")
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"payload")
    plan = {
        "schema": "mephc-windows-copy-cleanup-plan-v1",
        "active_project": "MEPHC",
        "archive_commit": "a" * 40,
        "sandbox_head_at_plan": "b" * 40,
        "copy_root_files": [{
            "root": str(copy_root), "path": "nested/evidence.txt",
            "bytes": 4, "sha256": digest(b"copy"),
        }],
        "copy_root_file_count": 1,
        "copy_root_bytes": 4,
        "payload_retirement": [{
            "path": payload_path.relative_to(payload_path.parents[4]).as_posix(),
            "bytes": 7, "sha256": digest(b"payload"),
        }],
        "payload_retirement_count": 1,
        "payload_retirement_bytes": 7,
    }
    plan["plan_sha256"] = executor.canonical_sha(plan)
    return plan, source

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path / "MePhC"
    root.mkdir()
    copy_root = tmp_path / "legacy"
    payload = root / "audit" / "archive" / "A" / "payload" / "one.bin"
    monkeypatch.setattr(executor, "ROOT", root)
    monkeypatch.setattr(executor, "INVENTORY", root / ".relayctl" / "inventory")
    monkeypatch.setattr(executor, "COPY_ROOTS", {str(copy_root)})
    monkeypatch.setattr(executor, "git", lambda *args: type("R", (), {
        "returncode": 0, "stdout": "tracked\n", "stderr": ""})())
    return make_plan(copy_root, payload), copy_root, payload

def test_plan_hash_mismatch_is_rejected(isolated):
    (plan, _), _, _ = isolated
    with pytest.raises(RuntimeError, match="PLAN_SHA256_MISMATCH"):
        executor.verify_plan(plan, "0" * 64)

def test_extra_file_fails_before_delete(isolated):
    (plan, source), copy_root, _ = isolated
    (copy_root / "extra").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="COPY_FILE_SET_MISMATCH"):
        executor.verify_all(plan)
    assert source.exists()

def test_byte_drift_fails_before_delete(isolated):
    (plan, source), _, _ = isolated
    source.write_bytes(b"drift")
    with pytest.raises(RuntimeError, match="FILE_SIZE_MISMATCH"):
        executor.verify_all(plan)
    assert source.exists()

def test_exact_verified_files_are_deleted(isolated):
    (plan, source), copy_root, payload = isolated
    executor.verify_plan(plan, plan["plan_sha256"])
    executor.verify_all(plan)
    receipt = executor.execute(plan, plan["plan_sha256"], "c" * 40)
    assert not source.exists()
    assert not payload.exists()
    assert not copy_root.exists()
    assert receipt.is_file()

def test_executor_uses_no_recursive_or_git_cleanup():
    text = Path(executor.__file__).read_text(encoding="utf-8")
    for forbidden in ("rmtree(", "git clean", "git reset", "rm -", "shutil"):
        assert forbidden not in text
    assert ".unlink()" in text
    assert ".rmdir()" in text
