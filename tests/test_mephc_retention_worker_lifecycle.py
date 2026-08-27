from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_fixed_retention_worker_tool_is_advertised_and_argumentless():
    mcp = _read("tools/mephc-runner/mcp_server.py")
    admission = _read("tools/mephc-admission/mephc_admission.py")
    assert "mephc_retention_worker_reload" in mcp
    assert '"additionalProperties": False' in mcp
    assert '"mephc_retention_worker_reload": "retention-worker-reload"' in admission
    assert 'arguments not in ({}, None)' in admission


def test_lifecycle_is_fixed_role_and_proves_transport_separation():
    lifecycle = _read("tools/mephc-admission/runtime_lifecycle.py")
    assert 'process_role = "MEPHC_RETENTION_EXECUTION_WORKER"' in lifecycle
    assert "transport_process_separation_proved = True" in lifecycle
    assert '["retention-worker-reload"]' in lifecycle
    assert "systemctl\", \"restart\", \"mephc-runner.service" in lifecycle
    assert "os.kill" not in lifecycle
    assert "taskkill" not in lifecycle
    assert "Popen" not in lifecycle


def test_attestation_uses_v3_source_commit_and_loaded_worker_hash():
    lifecycle = _read("tools/mephc-admission/runtime_lifecycle.py")
    assert '"v3_canonical_head_field": "source_commit"' in lifecycle
    assert '"raw_expected_head_indexing_active": False' in lifecycle
    assert '"source_commit_validation_active": True' in lifecycle
    assert '"worker_module_sha256": module_sha' in lifecycle
    assert "SOURCE_COMMIT_MISSING" in lifecycle
    assert "SOURCE_COMMIT_MISMATCH" in lifecycle


def test_lifecycle_fails_closed_without_raw_keyerror_or_science_execution():
    lifecycle = _read("tools/mephc-admission/runtime_lifecycle.py")
    assert "RETENTION_WORKER_ATTESTATION_FAILED" in lifecycle
    assert "except Exception as exc:" in lifecycle
    assert "expected_head_keyerror" in lifecycle
    assert "mpb" not in lifecycle.lower()
    assert "native" not in lifecycle.lower()
