from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m30_full_grid_h_point_array_spectral_collocation.py"
SPEC = importlib.util.spec_from_file_location("m30_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M30 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M30)


def test_full_grid_capture_freezes_two_charts_and_stateful_band_order():
    class Vector3Type:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    class FakeMP:
        Vector3 = Vector3Type

    class Solver:
        def __init__(self):
            self.band = None
            self.h_calls = []
            self.point_calls = 0

        def get_hfield(self, band, bloch_phase=True):
            self.band = band
            self.h_calls.append((band, bloch_phase))
            return np.full(M30.SHAPE, band + 0.25j, dtype=np.complex128)

        def get_field_point(self, point):
            self.point_calls += 1
            return np.asarray([self.band + point.x * 1j, point.y + 2j, point.x + point.y * 1j], dtype=np.complex128)

    solver = Solver()
    arrays, points, hashes = M30.capture_full_grid(solver, FakeMP)
    assert solver.point_calls == 2 * 2 * M30.N * M30.N
    assert solver.h_calls == [(2, False), (2, False), (3, False), (3, False)]
    assert set(arrays) == set(M30.CHARTS) == {"node", "half"}
    assert all(points[chart][str(band)].shape == M30.SHAPE for chart in M30.CHARTS for band in (2, 3))
    assert all(len(value) == 64 for value in hashes["point"]["node"].values())


def test_complex_real_space_and_spectral_comparison_are_lossless():
    array = np.zeros(M30.SHAPE, dtype=np.complex128)
    for i in range(M30.N):
        for j in range(M30.N):
            phase = np.exp(2j * np.pi * (3 * i / M30.N + 5 * j / M30.N))
            array[i, j] = phase * np.asarray([1 + 2j, -2 + 0.5j, 0.25 - 3j])
    assert M30.compare_grid(array, array)["max"] == 0.0
    point = np.roll(array, (1, 0), axis=(0, 1))
    transfer = M30.spectral_transfer(array, point, (0.0, 0.0))
    assert transfer["identity_transfer_relative_residual"] > 0.0
    assert transfer["nonzero_mode_count"] > 0


def test_m30_contract_has_no_fit_or_real_only_shortcuts():
    source = PATH.read_text(encoding="utf-8")
    assert "get_field_point(_point" in source
    assert ".solve(" not in source and "np.real" not in source
    assert "np.linalg.lstsq" not in source
    assert "component permutation" in source or "permutation" not in source
