from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit/e9f/d10_fr04_residual_composite_method_validation.py"
SPEC = importlib.util.spec_from_file_location("d10_validation", PATH)
assert SPEC is not None and SPEC.loader is not None
D10 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D10)


def test_frozen_convergence_predicates_use_only_declared_resolutions():
    values = {96: 1.0, 128: 0.8, 160: 0.9, 192: 0.84, 224: 0.87, 256: 0.85}
    result = D10.contraction_criteria(values)
    assert result == {"odd_contraction": True, "even_contraction": True, "terminal_parity_consistency": True, "all_resolution_criteria_pass": True}


def test_gap_criterion_is_strictly_terminal_minimum_against_declared_uncertainty():
    assert D10.robust_gap_criterion({96: 0.001, 128: 0.0012, 160: 0.0015, 192: 0.0017, 224: 0.002, 256: 0.0021}) is True
    assert D10.robust_gap_criterion({96: 0.001, 128: 0.001, 160: 0.005, 192: 0.005, 224: 0.002, 256: 0.002}) is False


def test_cross_stencil_predicate_has_no_invented_absolute_tolerance():
    result = D10.cross_stencil_criteria(
        {96: 1.0, 128: 0.8, 160: 0.9, 192: 0.84, 224: 0.87, 256: 0.85},
        {96: 1.0, 128: 0.8, 160: 0.9, 192: 0.84, 224: 0.88, 256: 0.85},
    )
    assert result["terminal_difference_r256"] <= result["terminal_difference_r224"]
    assert result["terminal_nonincrease"] is True


def test_missing_resolution_does_not_silently_pass():
    assert D10.contraction_criteria({96: 1.0})["all_resolution_criteria_pass"] is None
    assert D10.robust_gap_criterion({96: 0.001}) is None
