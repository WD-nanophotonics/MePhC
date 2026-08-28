from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit/e9f/d9_fr04_residual_composite_convergence_acquisition.py"


def test_d9_is_bounded_to_the_contract_target_and_resolution_classes():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'EXPECTED_REQUEST_COUNT = 420' in source
    assert 'RESOLUTIONS = (96, 128, 160, 192, 224, 256)' in source
    assert 'ODD_RESOLUTIONS = (96, 160, 224)' in source
    assert 'EVEN_RESOLUTIONS = (128, 192, 256)' in source
    assert 'PRIMARY_H_DENOMINATOR = 144' in source
    assert 'REFINED_H_DENOMINATOR = 288' in source


def test_d9_preserves_single_native_and_fresh_provider_accounting():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'counter.consume_provider(); counter.consume_solver()' in source
    assert 'native_invocation_count": 1' in source
    assert 'fresh_provider_execution_count": EXPECTED_REQUEST_COUNT' in source
    assert 'cache_reuse_count": 0' in source
    assert 'EXISTING_D9_RESIDUAL_CONVERGENCE_STATE_RECONCILIATION_REQUIRED' in source


def test_d9_forbids_production_composite_analysis_and_retry():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert '"native_retry_count": 0' in source
    assert "composite Chern" not in source
    assert "import meep as mp" in source
