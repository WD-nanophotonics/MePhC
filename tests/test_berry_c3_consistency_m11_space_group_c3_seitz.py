"""M11 exact geometry-Seitz and isolated-family tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m11_space_group_c3_seitz_and_band_family_audit.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m11", ENTRYPOINT)
assert SPEC and SPEC.loader
M11 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M11)


def test_geometry_side_count_derives_exact_c3_status_without_vectors():
    goal = {"geometries": {"G16": {"n1": 16, "n2": 16}, "G15": {"n1": 15, "n2": 15}}}
    assert M11.geometry_space_group(goal, "G16")["status"] == "NO_EXACT_C3_OPERATOR_EQUIVALENCE"
    assert M11.geometry_space_group(goal, "G15")["status"] == "ORIGIN_CENTERED_C3"


def test_seitz_formula_includes_translation_phase_and_zero_gauge():
    formula = M11.seitz_formula()
    assert "R^-1" in formula["periodic_field_formula"]
    assert "exp(-i q_target dot tau)" in formula["periodic_envelope_formula"]
    assert "[0,0]" in formula["reciprocal_translation_gauge"]


def test_shifted_center_fixture_distinguishes_origin_centered_rotation():
    point = (0.71, -0.23)
    origin = M11.seitz_coordinate(point, (0.0, 0.0))
    shifted = M11.seitz_coordinate(point, (0.19, -0.11))
    assert not np.allclose(origin, shifted, rtol=0.0, atol=1e-12)


def test_m11_is_solver_free_and_does_not_write_datasets():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert ".solve(" not in source
    assert "ImmutableDatasetStore" not in source
    assert "TARGET_COUNT" not in source
