from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit" / "berry_c3_consistency" / "m23_hfield_c3_and_tensor_coordinate_semantics.py"
SPEC = importlib.util.spec_from_file_location("m23_test_module", PATH)
assert SPEC is not None and SPEC.loader is not None
M23 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M23)


def test_contract_is_solver_free_and_result_channel_bound():
    source = PATH.read_text(encoding="utf-8")
    assert "MEPHC_INPUT_BUNDLE" in source
    assert "MEPHC_RESULT_PATH" in source
    assert "native_invocation_count\": 0" in source
    assert "get_epsilon_inverse_tensor_point" in source
    assert "get_hfield" in source
    assert "get_bloch_field" in source
    assert "fft_transform" in source
    assert "49152x49152" not in source


def test_explicit_representation_round_trips_preserve_axes():
    rng = np.random.default_rng(23)
    grid = rng.normal(size=(128, 128, 3, 2)) + 1j * rng.normal(size=(128, 128, 3, 2))
    metric = M23.grid_rank2_to_metric(grid)
    assert metric.shape == (16384, 3, 2)
    assert np.array_equal(M23.metric_rank2_to_grid(metric), grid)
    flat = M23.grid_rank2_to_h_flat(grid)
    assert flat.shape == (49152, 2)
    assert np.array_equal(M23.h_flat_to_grid_rank2(flat), grid)


def test_periodic_and_physical_operators_agree_on_direction_sensitive_mode():
    result = M23.synthetic_operator_validation()
    assert result["direction_sensitive"] is True
    assert result["status"] == "PASS"
    assert result["periodic_vs_physical_difference_max"] <= 1e-10


def test_physical_operator_preserves_component_and_band_axes():
    m15, m9 = M23._m15(), M23._m9()
    lattice = m15.lattice_automorphisms()
    rng = np.random.default_rng(24)
    frame = rng.normal(size=(128, 128, 3, 2)) + 1j * rng.normal(size=(128, 128, 3, 2))
    qs = np.asarray([0.11, -0.19])
    folding = np.asarray([1, -2])
    qt = lattice["c3_reciprocal_integer_automorphism"] @ qs - folding
    transformed = M23.physical_bloch_c3(frame, qs, qt, lattice["c3_direct_integer_automorphism"], m9)
    assert transformed.shape == frame.shape
    assert np.all(np.isfinite(transformed))


def test_source_semantics_are_reported_without_solver_construction():
    evidence = M23.api_semantics_evidence()
    assert "get_hfield_semantics" in evidence
    assert "get_bloch_field_semantics" in evidence
    assert "get_epsilon_inverse_tensor_point_semantics" in evidence
    assert evidence["cell_origin_convention"]


def test_tensor_audit_does_not_authorize_unproven_reindexing():
    record = {"inverse_epsilon_tensor_grid": [[[[[1.0, 0.0] if i == j else [0.1, 0.0] for j in range(3)] for i in range(3)] for _ in range(128)] for _ in range(128)]}
    record["member_index"] = 0
    record["c3_member_identity"] = "IDENTITY"
    result = M23._tensor_audit([record, {**record, "member_index": 1, "c3_member_identity": "C3"}, {**record, "member_index": 2, "c3_member_identity": "C3_SQUARED"}])
    assert result["exact_reindexing_status"].startswith("NONE_PROVEN")
    assert result["corrected_full_tensor_E_vs_etaD_relative_residual_max"] is None
