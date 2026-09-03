"""Regression checks that the accepted M2 live entrypoint remains M2-only."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"


def _load_m2():
    spec = importlib.util.spec_from_file_location("berry_c3_m2_accepted", ENTRYPOINT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m2_entrypoint_has_no_m3_analysis_branch():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "M3_RESULT_SCHEMA" not in source
    assert "analyze_m3_records" not in source
    assert "M3_DATASET_ID" not in source


def test_m2_entrypoint_keeps_accepted_live_contract_symbols():
    m2 = _load_m2()
    assert m2.RESULT_SCHEMA == "mephc-berry-c3-consistency-m2-live-c3-closure-v1"
    assert callable(m2.run)
    assert callable(m2.reduce_evidence)
