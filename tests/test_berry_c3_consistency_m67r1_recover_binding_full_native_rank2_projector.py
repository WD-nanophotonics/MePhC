from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m67r1_recover_binding_full_native_rank2_projector.py"
SPEC = importlib.util.spec_from_file_location("m67r1", SOURCE)
assert SPEC and SPEC.loader
m67r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m67r1)


def test_exact_corrected_m66_manifest_and_zero_budget_contract():
    text = SOURCE.read_text(encoding="utf-8")
    assert m67r1.M66_MANIFEST_SHA256 == "96463ece684c248c04097630bd3f133ac41f537a051508844c0e5026db9a88427"
    assert '"native_invocation_count": 0' in text
    assert '"provider_execution_count": 0' in text
    assert '"solver_execution_count": 0' in text
    assert "M67R1_M66_MANIFEST_INVALID" in text


def test_q_raw_roundtrip_uses_explicit_transpose_order():
    rng = np.random.default_rng(671)
    q = rng.normal(size=(m67r1.P * 2, 2)) + 1j * rng.normal(size=(m67r1.P * 2, 2))
    assert np.array_equal(m67r1.raw_to_q(m67r1.q_to_raw(q)), q)
    text = SOURCE.read_text(encoding="utf-8")
    assert "value.T.reshape(2, P, 2)" in text and "value.reshape(2, P * 2).T" in text


def test_true_projector_invariant_under_nonsingular_change_and_no_ambient_matrix():
    rng = np.random.default_rng(672)
    pair = rng.normal(size=(2, m67r1.P, 2)) + 1j * rng.normal(size=(2, m67r1.P, 2))
    left, _ = m67r1.orthonormal_basis(pair)
    transform = np.asarray([[2.0 + 0.4j, 0.3 - 0.2j], [-0.5 + 0.1j, 0.8 + 0.2j]])
    changed = np.einsum("apc,ab->bpc", pair, transform)
    right, _ = m67r1.orthonormal_basis(changed)
    assert np.allclose(m67r1.projector_trace(left), m67r1.projector_trace(right), rtol=1e-12, atol=1e-12)
    assert np.allclose(m67r1.projector_blocks(left), m67r1.projector_blocks(right), rtol=1e-12, atol=1e-12)
    text = SOURCE.read_text(encoding="utf-8")
    assert "ambient_projector_allocated" in text
    assert "131072,131072" not in text and "argmin" not in text and "np.roll" not in text


def test_historical_median_and_exact_mean_overlap_rules_are_distinct():
    text = SOURCE.read_text(encoding="utf-8")
    assert "np.median" in text and "np.mean(np.stack" in text
    assert "source_mean_projector_norm_squared" in text and "pairwise_3x3" in text
    assert "alternate_target_pair_diagnostic" in text and "c3_symmetrization" in text
