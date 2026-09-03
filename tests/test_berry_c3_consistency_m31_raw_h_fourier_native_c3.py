from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m31", ROOT / "audit/berry_c3_consistency/m31_raw_h_fourier_output_grid_native_c3_closure.py")
assert SPEC and SPEC.loader
m31 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m31)


class FakeSolver:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []

    def get_hfield(self, band: int, bloch_phase: bool = False):
        self.calls.append((band, bloch_phase))
        return np.ones(m31.SHAPE, dtype=np.complex128) * (band + 1j * band)


def test_candidate_inventory_is_frozen_without_raw_attributes():
    inventory = m31.raw_access_candidate_inventory(FakeSolver())
    assert len(inventory) == len(m31._candidate_names())
    assert all(item["evidence_level"] == "not_exposed" for item in inventory)


def test_public_h_capture_preserves_complex_shape_and_hash():
    array = m31._get_hfield(FakeSolver(), 2)
    assert array.shape == m31.SHAPE
    assert array.dtype == np.complex128
    assert m31._encode_shape(array)["sha256"] == m31._complex_hash(array)


def test_unavailable_raw_path_is_fail_closed():
    solver = FakeSolver()
    inventory = m31.raw_access_candidate_inventory(solver)
    probe = m31.probe_raw_h(solver, 2, inventory)
    assert probe["status"] == "RAW_RECIPROCAL_H_NOT_EXPOSED_IN_INSTALLED_RUNTIME"
    metrics = m31._native_metrics({member: {"captured": False} for member in m31.MEMBERS})
    assert metrics["status"] == "NATIVE_C3_NOT_EVALUABLE_RAW_H_UNAVAILABLE"


def test_no_fit_or_public_array_correction_is_claimed():
    source = (ROOT / "audit/berry_c3_consistency/m31_raw_h_fourier_output_grid_native_c3_closure.py").read_text(encoding="utf-8")
    assert "np.real" not in source
    assert "fit(" not in source
    assert "authoritative_public_H_result_unchanged" in source
