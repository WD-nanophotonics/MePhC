"""M10 source/data identity and synthetic extraction-fault tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m10_maxwell_state_identity_and_provider_extraction_audit.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m10", ENTRYPOINT)
assert SPEC and SPEC.loader
M10 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M10)


def _frame():
    rng = np.random.default_rng(41)
    frame = rng.normal(size=(2 * 4 * 4 * 3, 2)) + 1j * rng.normal(size=(2 * 4 * 4 * 3, 2))
    return frame / np.linalg.norm(frame, axis=0, keepdims=True)


def test_source_trace_and_band_indexing_are_explicit():
    trace = M10.source_trace()
    assert trace["production_symbol"].endswith("MPBLiveEnergySpectralProvider")
    assert "get_efield" in " ".join(trace["call_sequence"])
    assert "one-based" in trace["band_indexing"]


def test_synthetic_fault_regressions_detect_all_required_faults():
    result = M10.synthetic_fault_regressions()
    assert result["all_fault_regressions_pass"]
    assert result["band_swap_fault_detected"]
    assert result["last_band_overwrite_fault_detected"]
    assert result["e_h_block_swap_fault_detected"]
    assert result["epsilon_grid_misalignment_fault_detected"]


def test_rank2_projector_is_invariant_under_u2_and_serialization_round_trip():
    result = M10.rank2_invariance_check(_frame())
    assert result["passed"]
    assert result["u2_basis_rotation_projector_residual"] <= 1e-12
    assert result["serialization_round_trip_projector_residual"] <= 1e-12


def test_m10_has_no_expensive_execution_path_or_production_write():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "BudgetCounter" not in source
    assert ".solve(" not in source
    assert "ImmutableDatasetStore" not in source
    assert "import meep" not in source
