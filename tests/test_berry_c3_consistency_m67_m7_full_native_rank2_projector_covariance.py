from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m67_m7_full_native_rank2_projector_covariance.py"
SPEC = importlib.util.spec_from_file_location("m67", SOURCE)
assert SPEC and SPEC.loader
m67 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m67)


def test_orthogonal_projector_is_invariant_under_arbitrary_nonsingular_basis_change():
    rng = np.random.default_rng(67)
    pair = rng.normal(size=(2, m67.P, 2)) + 1j * rng.normal(size=(2, m67.P, 2))
    left, _ = m67.orthonormal_basis(pair)
    transform = np.asarray([[2.0 + 0.2j, 0.3 - 0.1j], [-0.4 + 0.5j, 0.7 + 0.1j]])
    changed = np.einsum("apc,ab->bpc", pair, transform)
    right, _ = m67.orthonormal_basis(changed)
    assert np.allclose(m67.projector_trace(left), m67.projector_trace(right), rtol=1e-12, atol=1e-12)
    assert np.allclose(m67.projector_blocks(left), m67.projector_blocks(right), rtol=1e-12, atol=1e-12)


def test_true_projector_uses_thin_algebra_and_has_no_ambient_matrix_or_fit():
    text = SOURCE.read_text(encoding="utf-8")
    assert "np.linalg.qr" in text and "np.linalg.svd" in text
    assert "ambient_projector_allocated" in text
    assert "131072,131072" not in text and "argmin" not in text and "np.roll" not in text
    assert "c3_symmetrization" in text and "gauge_u2_band_permutation_fitting" in text


def test_solver_provider_native_budgets_are_zero_and_rank2_pair_is_canonical():
    text = SOURCE.read_text(encoding="utf-8")
    assert "native_invocation_count\": 0" in text and "solver_execution_count\": 0" in text
    assert "RANK2 = (1, 2)" in text and "m38.raw_fft_edge_map" in text


def test_median_frequency_and_mean_projector_rules_remain_distinct():
    text = SOURCE.read_text(encoding="utf-8")
    assert "np.median" in text and "np.mean(np.stack" in text
    assert "offdiagonal_projector_frobenius_squared" in text
    assert "alternate_target_pair_diagnostic" in text
