from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m65_gauge_invariant_scalar_observable_ladder.py"
SPEC = importlib.util.spec_from_file_location("m65", SOURCE)
assert SPEC and SPEC.loader
m65 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m65)


def test_strict_m7_orbit_has_three_distinct_c3_points():
    centers = m65.orbit_centers(7)
    assert set(centers) == set(m65.MEMBERS)
    assert len({tuple(value) for value in centers.values()}) == 3
    assert centers["IDENTITY"] == [17.0 / 36.0, 0.0]


def test_scalar_summary_is_gauge_invariant_and_compact():
    import numpy as np
    summary = m65._density_summary(np.asarray([[1.0, 2.0], [3.0, 4.0]]), "ENERGY")
    assert summary["sum"] == 10.0 and summary["inverse_participation"] > 0.0 and len(summary["sha256"]) == 64


def test_fourier_power_retains_four_band_axis_for_both_common_layouts():
    import numpy as np
    rank_mode = np.ones((5, 2, 4), dtype=complex)
    rank_band = np.ones((4, 5, 2), dtype=complex)
    assert m65._fourier_power(rank_mode).shape == (5, 4)
    assert m65._fourier_power(rank_band).shape == (5, 4)


def test_contract_forbids_raw_complex_comparison_and_symmetrization():
    text = SOURCE.read_text(encoding="utf-8")
    assert "raw_complex_field_comparison" in text and "c3_symmetrization" in text
    assert "get_efield" in text and "get_hfield" in text and "pair23_density" in text


def test_exact_solver_budget_is_six_and_each_call_consumes_counter():
    text = SOURCE.read_text(encoding="utf-8")
    assert "BudgetCounter(0, 6)" in text and "counter.consume_solver()" in text
    assert text.count("_solve(mp, mpb") == 1
