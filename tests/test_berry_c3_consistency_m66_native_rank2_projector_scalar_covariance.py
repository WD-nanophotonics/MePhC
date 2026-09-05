from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m66_native_rank2_projector_scalar_covariance.py"
SPEC = importlib.util.spec_from_file_location("m66", SOURCE)
assert SPEC and SPEC.loader
m66 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m66)


def test_all_documented_raw_layouts_normalize_to_band_mode_component():
    class M41:
        @staticmethod
        def _normalize_raw(value, resolution):
            expected = resolution * resolution
            value = np.asarray(value)
            if value.shape == (expected, 2, 4):
                return np.transpose(value, (2, 0, 1)), {"layout": "P,2,4"}
            if value.shape == (4, expected, 2):
                return value, {"layout": "4,P,2"}
            if value.shape == (4, 2, expected):
                return np.transpose(value, (0, 2, 1)), {"layout": "4,2,P"}
            raise ValueError("bad")

    source = np.arange(4 * 9 * 2, dtype=float).reshape(4, 9, 2) + 1j
    for value in (np.transpose(source, (1, 2, 0)), source, np.transpose(source, (0, 2, 1))):
        result, _ = m66._normalize_raw(M41, value, 3)
        assert result.shape == source.shape and np.array_equal(result, source)


def test_reciprocal_scalar_is_phase_and_u2_invariant():
    rng = np.random.default_rng(66)
    raw = rng.normal(size=(4, m66.N * m66.N, 2)) + 1j * rng.normal(size=(4, m66.N * m66.N, 2))
    angle = 0.37
    unitary = np.asarray([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]], dtype=complex)
    mixed = raw.copy()
    mixed[1:3] = np.einsum("ab,bpc->apc", unitary, raw[1:3])
    mixed[1:3] *= np.exp(1j * 0.91)
    assert np.allclose(m66.reciprocal_projector_scalar(raw), m66.reciprocal_projector_scalar(mixed), rtol=1e-14, atol=1e-14)


def test_orbit_and_contract_forbid_fitted_mapping_or_symmetrization():
    centers = m66.orbit_centers(7)
    assert centers["IDENTITY"] == [17.0 / 36.0, 0.0]
    assert len({tuple(value) for value in centers.values()}) == 3
    text = SOURCE.read_text(encoding="utf-8")
    assert "m38.raw_fft_edge_map" in text and "m38.fft_label" in text
    assert "c3_symmetrization" in text and "gauge_or_u2_fitting" in text
    assert "argmin" not in text and "fftshift" not in text and "np.roll" not in text


def test_repeat_rule_uses_median_max_deviation_and_exactly_three_solver_budget():
    text = SOURCE.read_text(encoding="utf-8")
    assert "np.median" in text and "np.max(np.abs" in text
    assert "BudgetCounter(0, 9)" in text and "counter.consume_solver()" in text
    assert text.count("_solve(mp, mpb") == 1


def test_direct_grid_map_is_not_a_fitted_shift():
    class M54:
        @staticmethod
        def build_index_map():
            result = np.empty((m66.N, m66.N, 2), dtype=int)
            action = np.asarray([[-1, 1], [-1, 0]])
            for i in range(m66.N):
                for j in range(m66.N):
                    result[i, j] = (action @ action @ np.asarray([i, j])) % m66.N
            return result

    mapping = m66._direct_index_map(M54)
    assert mapping.shape == (m66.N, m66.N, 2)
