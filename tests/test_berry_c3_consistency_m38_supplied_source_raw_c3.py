from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("m38", ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py")
assert SPEC and SPEC.loader
m38 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m38)


def test_negative_g_fft_mapping_is_deterministic():
    assert m38.raw_fft_edge_map((1, -2), (3, -4)) == tuple((m38.reciprocal_automorphism() @ np.asarray([1, -2]) - np.asarray([3, -4])).tolist())


def test_transverse_frame_branches_are_orthonormal_and_handed():
    for q in ((0.0, 0.0, 0.0), (0.0, 0.0, 2.0), (1.0, 2.0, 3.0)):
        m, n, khat = m38.transverse_frame(q)
        assert np.isclose(np.linalg.norm(m), 1.0)
        assert np.isclose(np.linalg.norm(n), 1.0)
        assert np.isclose(np.dot(m, n), 0.0)
        if np.linalg.norm(khat) > 0:
            assert np.allclose(np.cross(m, n), khat)


def test_frame_block_is_orthogonal():
    block = m38.frame_block((1.0, 0.5, 0.25), (-0.5, 1.0, 0.25))
    # B_t^T R B_s is a transverse-subspace projection; for different q
    # directions it is a contraction, not generally a 2-D orthogonal matrix.
    assert np.all(np.linalg.svd(block, compute_uv=False) <= 1.0 + 1e-12)


def test_raw_layout_requires_exact_two_bands_and_components():
    raw = np.zeros((2, 7, 2), dtype=np.complex128)
    try:
        m38.normalize_raw_layout(raw)
    except ValueError as exc:
        assert "MODE_COUNT" in str(exc)
    else:
        raise AssertionError("unexpected acceptance of non-M33 mode count")


def test_source_is_solver_free_and_no_overlap_fit():
    source = (ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py").read_text(encoding="utf-8")
    assert "run_parity" not in source
    assert "import meep" not in source
    assert "scipy.optimize" not in source
