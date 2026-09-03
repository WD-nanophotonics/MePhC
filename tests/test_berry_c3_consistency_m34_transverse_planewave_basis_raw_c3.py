from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m34", ROOT / "audit/berry_c3_consistency/m34_documented_transverse_planewave_basis_raw_c3_closure.py")
assert SPEC and SPEC.loader
m34 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m34)


def test_raw_layout_is_explicit_for_unambiguous_band_axis():
    raw = np.zeros((2, 7, 3), dtype=np.complex128)
    layout = m34.raw_layout(raw)
    assert layout["band_axis"] == 0
    assert layout["axis_layout_status"] == "FIRST_AXIS_BAND_MAJOR"


def test_gram_measurement_does_not_hide_nonorthogonality():
    raw = np.zeros((2, 4, 2), dtype=np.complex128)
    raw[0, 0, 0] = 1
    raw[1, 0, 0] = 0.25
    raw[1, 1, 1] = 1
    result = m34.gram_measure(raw, 0)
    assert result["status"] == "MEASURED"
    assert result["normalized_residual"] > 0


def test_synthetic_operator_has_cubed_closure():
    result = m34.derive_operator_properties()
    assert result["synthetic_closure_status"] == "PASS"
    assert result["cubed_residual"] < 1e-12
    assert result["bijection_status"] == "SYNTHETIC_BIJECTION_PASS"


def test_mapping_formula_is_not_overlap_fitted():
    assert "S_recip" in m34.raw_c3_mapping_formula()
    source = (ROOT / "audit/berry_c3_consistency/m34_documented_transverse_planewave_basis_raw_c3_closure.py").read_text(encoding="utf-8")
    assert "scipy.optimize" not in source
    assert "import meep" not in source
    assert "run_parity" not in source


def test_no_solver_side_effects_are_declared():
    assert m34.RESULT_SCHEMA.endswith("raw-c3-closure-v1")
