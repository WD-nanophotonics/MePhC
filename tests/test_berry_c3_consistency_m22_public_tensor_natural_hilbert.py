"""Focused M22 tests: public tensor parsing and natural-space algebra."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m22_public_tensor_constitutive_natural_hilbert_audit.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m22", ENTRYPOINT)
assert SPEC and SPEC.loader
M22 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M22)


def test_contract_entrypoint_uses_only_public_tensor_and_result_channel():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "get_epsilon_inverse_tensor_point" in source
    assert "MEPHC_INPUT_BUNDLE" in source and "MEPHC_RESULT_PATH" in source
    assert "MPBLiveSpectralProvider" not in source


def test_tensor_parser_accepts_real_flat_public_result():
    value = np.arange(9, dtype=float)
    parsed = M22._tensor(value)
    assert parsed.shape == (3, 3)
    assert np.array_equal(parsed.real, value.reshape(3, 3))


def test_tensor_parser_accepts_matrix_like_attributes():
    class Matrix:
        rows = cols = 3
        def __getitem__(self, index):
            return index[0] * 3 + index[1]
    assert np.array_equal(M22._tensor(Matrix()).real, np.arange(9).reshape(3, 3))


def test_material_metric_is_hermitian_and_positive():
    rng = np.random.default_rng(22)
    v = rng.normal(size=(32, 3, 2)) + 1j * rng.normal(size=(32, 3, 2))
    eta = np.broadcast_to(np.diag([1.0, 2.0, 3.0]), (32, 3, 3)).astype(complex)
    gram = M22._gram(v, eta)
    assert np.allclose(gram, gram.conj().T)
    assert np.all(np.linalg.eigvalsh(gram) > 0.0)


def test_metric_whitening_is_identity():
    rng = np.random.default_rng(23)
    v = rng.normal(size=(40, 3, 2)) + 1j * rng.normal(size=(40, 3, 2))
    eta = np.broadcast_to(np.diag([1.0, 1.5, 2.0]), (40, 3, 3)).astype(complex)
    q = M22._metric_q(v, eta)
    assert np.allclose(M22._gram(q, eta), np.eye(2), atol=1e-12)


def test_projector_is_invariant_under_fixed_u2_basis_change():
    rng = np.random.default_rng(24)
    v = rng.normal(size=(24, 3, 2)) + 1j * rng.normal(size=(24, 3, 2))
    eta = np.broadcast_to(np.eye(3), (24, 3, 3)).astype(complex)
    u = np.asarray([[0, 1], [-1, 0]], dtype=complex)
    probe = v[:, :, :1]
    assert np.allclose(M22._projector_action(v, probe, eta), M22._projector_action(v @ u, probe, eta), atol=1e-12)


def test_interface_mask_is_deterministic_without_threshold():
    epsilon = np.ones((4, 4)); epsilon[1:3, 1:3] = 2.0
    mask = M22._interface_mask(epsilon)
    assert mask.dtype == bool and mask.any() and (~mask).any()


def test_tensor_encoding_is_complex_pair_and_explicit_axes():
    encoded = M22._complex_encode(np.eye(3, dtype=complex)[None, None])
    assert encoded[0][0][0][1] == [0.0, 0.0]
    assert encoded[0][0][1][1] == [1.0, 0.0]


def test_fallback_is_bounded_to_three_members_by_source():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "for member in ordered_triplet(members)" in source
    assert "counter.consume_solver()" in source
    assert "run_parity" in source


def test_rank2_transform_separates_bands_before_fft():
    calls = []
    class FFT:
        def fft_transform(self, field, shape, reciprocal, folding, rotation):
            calls.append((field.shape, tuple(folding)))
            return field
    frame = np.zeros((128, 128, 3, 2), dtype=complex)
    result = M22.transform_rank2_vector_frame(frame, np.eye(2, dtype=int), (3, -2), FFT())
    assert result.shape == (49152, 2)
    assert calls == [((128, 128, 3), (3, -2)), ((128, 128, 3), (3, -2))]


def test_rank2_transform_rejects_flattened_frame():
    class FFT:
        def fft_transform(self, *args):
            raise AssertionError("malformed frame must be rejected first")
    with pytest.raises(M22.M22Error, match="M22_RANK2_GRID_SHAPE_INVALID"):
        M22.transform_rank2_vector_frame(np.zeros((49152, 2), dtype=complex), np.eye(2, dtype=int), (0, 0), FFT())


def test_edge_derivation_keeps_nonzero_reciprocal_translation():
    class Lattice:
        R2 = np.eye(2)
        @staticmethod
        def lattice_automorphisms():
            return {"reciprocal_basis": np.eye(2), "c3_reciprocal_integer_automorphism": np.eye(2, dtype=int)}
    records = [{"member_index": i, "c3_member_identity": name, "coordinate": ([1.0, 0.0] if i == 0 else [0.0, 0.0])} for i, name in enumerate(("IDENTITY", "C3", "C3_SQUARED"))]
    edges, residual, cycle = M22.derive_edges(records, Lattice())
    assert edges[0]["G_edge_integer"] == [1, 0]
    assert residual == 0.0 and cycle == 0.0
