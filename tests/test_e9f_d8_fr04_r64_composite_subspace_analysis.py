from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit/e9f/d8_fr04_r64_composite_subspace_analysis.py"


def test_d8_replays_accepted_nonabelian_stack_and_fixed_composite_ranks():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert '"status": "PASS_EXACT_ACCEPTED_IMPLEMENTATION_REPLAY"' in source
    assert 'RANK2 = (1, 2)' in source
    assert 'RANK3 = (0, 1, 2)' in source
    assert 'SIGNED_AREA_Q2 = 1.0 / 10368.0' in source
    assert 'SOURCE_WEIGHT_Q2 = 1.0 / 1296.0' in source
    assert 'QUALIFICATION_THRESHOLD = 0.02' in source


def test_d8_preserves_external_gap_and_fail_closed_semantics():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'values[1] - values[0], values[3] - values[2]' in source
    assert 'values[3] - values[2]' in source
    assert 'reduce_supplied_berry_rows' in source
    assert 'NOT_REPORTED_WITH_REASON' in source
    assert 'internal band1-band2 separation excluded' in source


def test_d8_has_no_native_provider_or_solver_execution_path():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "make_provider" not in source
    assert '"native_invocation_count": 0' in source
    assert '"provider_request_count": 0' in source
    assert '"mpb_execution": False' in source
