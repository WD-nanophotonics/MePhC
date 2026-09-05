from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m61_homogeneous_k_operator_c3_isolation.py"
SPEC = importlib.util.spec_from_file_location("m61_test_module", SOURCE)
assert SPEC and SPEC.loader
m61 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m61)


def _freq(rows):
    return {"failure_set": [{"vertex": v, "band": b, "source_member": s, "target_member": t} for v, b, s, t in rows], "failure_count": len(rows)}


def test_reciprocal_reference_is_window_stable_and_preserves_multiplicity():
    low = m61.reciprocal_spectrum([0.0, 0.0], 4); high = m61.reciprocal_spectrum([0.0, 0.0], 6)
    assert len(low) == len(high) == 4 and np.allclose(low, high, rtol=0, atol=128 * np.finfo(float).eps)


def test_analytic_c3_reference_can_be_passed_without_mp_b_output():
    analytic = {"c3_status": "PASS", "c3_frequency": {"failure_set": []}}
    assert analytic["c3_status"] == "PASS"


def test_material_sanity_is_a_hard_gate_and_route_is_explicit():
    stock = _freq([(0, 1, "IDENTITY", "C3")]); canonical = _freq([(0, 1, "IDENTITY", "C3")])
    analytic = {"c3_status": "PASS"}; material = {"sanity_status": "PASS", "operator_gate": True}
    assert m61.route_after_gates(stock, canonical, analytic, material)["authorize_frequency"]


def test_m60_no_restoration_and_homogeneous_outcomes():
    stock = _freq([(0, 1, "IDENTITY", "C3")]); assert m61.classify(_freq([]))[0] == "R256_HOMOGENEOUS_K_OPERATOR_C3_PASS_PATTERNED_FAILURE_PERSISTS"; assert m61.classify(stock)[0] == "R256_HOMOGENEOUS_K_OPERATOR_C3_BREAKS"


def test_constant_control_has_no_pattern_geometry_or_raw_science():
    text = SOURCE.read_text(encoding="utf-8")
    assert "geometry=[]" in text and "mp.Medium(epsilon=N_EFF ** 2)" in text
    assert "Cylinder" not in text and "MaterialGrid" not in text and "Wilson" not in text and "Berry" not in text
