from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m25_bloch_q_coordinate_nyquist_alias_fourier_closure.py"
SPEC = importlib.util.spec_from_file_location("m25_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M25 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M25)


def test_contract_is_zero_execution_and_source_derived():
    source = PATH.read_text(encoding="utf-8")
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
    assert '"native_invocation_count": 0' in source
    assert "cartesian_to_reciprocal" in source
    assert "2pi" in source


def test_provider_cartesian_to_fractional_conversion_is_exact_linear_algebra():
    basis = np.asarray([[2.0, 0.5], [0.25, 1.5]])
    fractional = np.asarray([0.2, -0.4])
    public = basis @ fractional
    assert np.allclose(M25.provider_q_to_mpb_k(public, basis), fractional)


def test_all_mode_classes_partition_16384_modes_and_are_bijective():
    m15 = M25._m15(); lattice = m15.lattice_automorphisms()
    ledger = M25.mode_ledger(lattice["c3_reciprocal_integer_automorphism"], (2, -1))
    assert ledger["mode_count"] == 128 * 128
    assert sum(ledger["class_counts"].values()) == 128 * 128
    assert ledger["bijection"] is True
    assert ledger["duplicate_target_mode_count"] == 0


def test_mode_classification_marks_nyquist_and_wrap_without_filtering():
    assert M25.classify_mode((-64, 0), (64, 0), (-64, 0)) == "NYQUIST_X_ONLY"
    assert M25.classify_mode((1, 2), (130, 2), (2, 2)) == "WRAP_CROSSING_NON_NYQUIST"
    assert M25.classify_mode((0, 0), (0, 0), (0, 0)) == "SELF_INVERSE_MOD_128"


def test_required_result_fields_and_no_masked_authoritative_result():
    source = PATH.read_text(encoding="utf-8")
    for name in ("actual_periodic_vs_physical_C3_operator_difference_max_after_q_fix", "class_counts_by_edge", "inverse_mapping_residual_max", "special_mode_union_residual_fraction", "ordinary_no_wrap_residual_fraction", "counterfactual_special_modes_removed_H_minimum_overlap"):
        assert name in source
