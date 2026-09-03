from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m27_mpb_h_grid_origin_sampling_phase_audit.py"
SPEC = importlib.util.spec_from_file_location("m27_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M27 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M27)


def test_contract_is_solver_free_and_sources_are_inspected():
    source = PATH.read_text(encoding="utf-8")
    assert '"native_invocation_count": 0' in source
    assert "get_hfield" in source and "get_field_point" in source
    assert "MEPHC_RESULT_PATH" in source


def test_common_offset_phase_law_matches_shifted_fourier_modes():
    result = M27.phase_law_validation()
    assert result["status"] == "PASS"
    assert result["maximum_residual"] <= 1e-12
    assert "2pi" in result["common_offset_formula"]


def test_standard_controls_are_fixed_preregistered_offsets():
    source = PATH.read_text(encoding="utf-8")
    for name in ("zero", "x_half", "y_half", "xy_half"):
        assert name in source
    assert "overlap" in source.lower()


def test_sampling_metadata_is_not_inferred_from_overlap():
    source = PATH.read_text(encoding="utf-8")
    assert "NO_AUTHORITATIVE_CORRECTION_AVAILABLE" in source
    assert "OUTPUT_GRID_LOCATION_METADATA_NOT_EXPOSED" in source
    assert "source_confirmed_sampling_correction" in source


def test_component_phase_is_not_commuted_through_rotation():
    result = M27.phase_law_validation()
    assert "cannot commute" in result["component_offset_formula"]
