from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "local_phase_space_symmetry_and_readiness_closure.py"
ARTIFACT = ROOT / "audit" / "local_affine" / "p101_local_phase_space_symmetry_closure.json"
P101_TEST = ROOT / "tests" / "test_p101_antiunitary_symmetry_and_readiness_closure.py"


def _module():
    spec = importlib.util.spec_from_file_location("p102_closure", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_committed_artifact_has_contract_sha_and_semantic_content():
    module = _module()
    assert _digest(ARTIFACT) == module.EXPECTED_ARTIFACT_SHA256
    ledger = module.load_committed_closure()
    assert ledger["antiunitary_proof"]["omega_qy_s_symmetry_forced_zero"] is True
    assert ledger["trajectory_readiness"]["missing_input_count"] == 6


def test_entrypoint_reads_tracked_artifact_and_only_writes_result(monkeypatch, tmp_path):
    module = _module()
    tracked = (TARGET, ARTIFACT, P101_TEST)
    before = {path: _digest(path) for path in tracked}
    result_path = tmp_path / "p101-result.json"
    monkeypatch.setenv("MEPHC_RESULT_PATH", str(result_path))
    assert module.main() == 0
    after = {path: _digest(path) for path in tracked}
    assert after == before
    result = module.json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema"] == module.RESULT_SCHEMA
    assert result["scientific_acceptance_status"] == "PASS"
    assert result["trajectory_readiness_status"] == "BLOCKED_BY_MISSING_INPUTS"


def test_no_tracked_artifact_write_remains_in_future_execution_path():
    source = TARGET.read_text(encoding="utf-8")
    assert "write_json(ARTIFACT_PATH" not in source
    assert "load_committed_closure()" in source
    assert "MEPHC_RESULT_PATH" in source
