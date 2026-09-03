from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m33", ROOT / "audit/berry_c3_consistency/m33_documented_raw_eigenvector_c3_subspace_validation.py")
assert SPEC and SPEC.loader
m33 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m33)


def test_band_axis_and_rank2_gram_are_measured_without_renormalizing():
    raw = np.zeros((2, 5, 3), dtype=np.complex128)
    raw[0, 0, 0] = 1.0
    raw[1, 1, 1] = 1.0
    semantics = m33.raw_band_axis_semantics(raw)
    assert semantics["axis"] == 0
    result = m33.raw_rank2_gram_residual(raw, semantics)
    assert result["status"] == "MEASURED"
    assert result["normalized_gram_residual"] == 0.0


def test_raw_payload_roundtrip_is_complex_and_content_addressed():
    raw = np.arange(10, dtype=float).reshape(2, 5) + 1j * np.arange(10, dtype=float).reshape(2, 5)
    encoded = m33.encode_raw_array(raw)
    restored = m33.decode_raw_array(encoded)
    assert restored.dtype == np.complex128
    assert np.array_equal(restored, raw)
    assert encoded["sha256"] == m33.hashlib.sha256(raw.astype(np.complex128).tobytes()).hexdigest()


def test_transverse_c3_action_closes_after_three_rotations():
    source, target = m33.synthetic_covariant_rank2()
    third = m33.c3_transverse_action(target)
    closed = m33.c3_transverse_action(third)
    assert np.allclose(closed, source, atol=1e-12)
    overlap = m33.rank2_overlap(m33.c3_transverse_action(source), target)
    assert overlap["minimum_overlap_singular_value"] > 1.0 - 1e-12


def test_corrupted_mode_map_fails_unity_covariance():
    source, target = m33.synthetic_covariant_rank2()
    corrupted = target[::-1]
    assert m33.rank2_overlap(source, corrupted)["minimum_overlap_singular_value"] < 1.0 - 1e-8


def test_counter_reconciliation_is_existing_evidence_only():
    result = m33._m30_reconciliation([])
    assert result["m30_reported_transport_solver_count"] == 3
    assert result["m30_result_solver_count"] == 3
    assert result["m30_durable_or_native_solver_count"] == 0
    assert result["m30_reconciled_solver_count"] == 3
    assert "not rerun" in result["m30_counter_discrepancy_explanation"]


def test_source_has_no_overlap_fitted_mapping():
    source = (ROOT / "audit/berry_c3_consistency/m33_documented_raw_eigenvector_c3_subspace_validation.py").read_text(encoding="utf-8")
    assert "U(2)" not in source
    assert "scipy.optimize" not in source
    assert "run_parity" in source
