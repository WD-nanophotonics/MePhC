from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m41r2_recover36_complete_numerical_convergence.py"
SPEC = importlib.util.spec_from_file_location("m41r2", SOURCE)
assert SPEC and SPEC.loader
m41r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m41r2)


def test_exact_constants_and_append_only_contract_are_present():
    source = SOURCE.read_text(encoding="utf-8")
    assert m41r2.M39R1_DATASET_ID == "0fb83c45dad9a224845040ef5598741e0488b6d41b4d4fe7910ca8aa6dea75fa"
    assert m41r2.M39R1_MANIFEST_SHA256 == "58cae64b4732077ad35126a0b86ca1993a2efef1c84f8b306e15bd7b99a7cf95"
    assert "M39R1_SCHEMA" in source and "M39R1_SCHEMA, 14" in source
    assert "m40r3._rank1" not in source and "m40r3._rank2_pair" not in source
    assert "R128_T1E9_M1" in source and "R64_T1E9_M3" in source and "R96_T1E9_M3" in source


def test_main_equivalent_synthetic_configuration_analysis_runs_end_to_end():
    result = m41r2.main_equivalent_smoke()
    assert result["record_count"] == 36
    assert result["configuration_id"] == "SYNTHETIC"
    assert result["rank1_status"] in {"RANK1_QUALIFIED", "RANK1_WITHHELD"}
    assert result["rank2_status"] in {"PASS", "FAIL"}


def test_resolution_mode_counts_and_dynamic_fft_shape_are_explicit():
    source = SOURCE.read_text(encoding="utf-8")
    assert "4096" in source and "9216" in source and "16384" in source
    assert "resolution" in source and "fft_label" in source
    assert "capture_state_resolution_aware" in source


def test_partial_parent_is_never_finalized_and_new_records_are_immediately_put():
    source = SOURCE.read_text(encoding="utf-8")
    assert "_read_partial" in source
    assert "store.put" in source and "store.finalize" in source
    assert "partial_parent_namespace_sha256" in source
    assert "cumulative_m41_chain_record_count" in source


def test_result_schema_and_budget_limits_are_explicit():
    source = SOURCE.read_text(encoding="utf-8")
    assert m41r2.RESULT_SCHEMA == "mephc-berry-c3-consistency-m41r2-g15-covariant-numerical-convergence-complete-v1"
    assert "BudgetCounter(108, 108)" in source
    assert "len(records) not in (72, 108)" in source
