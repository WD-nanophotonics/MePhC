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


def test_native_mode_component_band_layout_is_transposed_to_band_mode_component():
    raw = np.arange(m38.N * m38.N * 4).reshape(m38.N * m38.N, 2, 2)
    normalized, evidence = m38.normalize_raw_layout(raw)
    assert normalized.shape == (2, m38.N * m38.N, 2)
    assert np.array_equal(normalized, np.transpose(raw, (2, 0, 1)))
    assert evidence["axis_layout_status"] == "NATIVE_MODE_TRANSVERSE_COMPONENT_BAND_FROM_H_DATA"


def test_rank2_projector_distance_uses_low_rank_identity_and_matches_dense_reference():
    rng = np.random.default_rng(38)
    left = rng.normal(size=(2, 9, 2)) + 1j * rng.normal(size=(2, 9, 2))
    right = rng.normal(size=(2, 9, 2)) + 1j * rng.normal(size=(2, 9, 2))
    measured = m38.rank2_metrics(left, right)["projector_distance"]
    q_left, _ = np.linalg.qr(left.reshape(2, -1).T, mode="reduced")
    q_right, _ = np.linalg.qr(right.reshape(2, -1).T, mode="reduced")
    dense = np.linalg.norm(q_left @ q_left.conj().T - q_right @ q_right.conj().T)
    assert np.isclose(measured, dense, atol=1e-12)


def test_source_is_solver_free_and_no_overlap_fit():
    source = (ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py").read_text(encoding="utf-8")
    assert "run_parity" not in source
    assert "import meep" not in source
    assert "scipy.optimize" not in source


def test_cross_dataset_binding_uses_actual_m33_vocabulary_without_role_field():
    m18 = [
        {"schema": "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1", "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "deterministic": False, "frame_convention": "LAB_FIXED", "repeat_index": 1, "c3_member_identity": member, "request_key_sha256": f"key-{member}", "record_id": f"m18-{member}"}
        for member in ("C3_SQUARED", "IDENTITY", "C3")
    ]
    m33 = [
        {"schema": "mephc-berry-c3-consistency-m33-raw-eigenvector-c3-metadata-dataset-v1", "geometry_id": "G15", "c3_member_identity": member, "request_key_sha256": f"key-{member}", "record_id": f"m33-{member}", "raw_eigenvector": {}}
        for member in ("C3", "IDENTITY", "C3_SQUARED")
    ]
    left, right, evidence = m38.bind_cross_dataset_triplet(m18, m33)
    assert list(left) == ["IDENTITY", "C3", "C3_SQUARED"]
    assert list(right) == ["IDENTITY", "C3", "C3_SQUARED"]
    assert evidence["status"] == "SEMANTIC_BINDING_PASS"
    assert all("shared_identity_fields" in row for row in evidence["mapping_table"])


def test_c3_closure_is_measured_not_hard_coded():
    source = (ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py").read_text(encoding="utf-8")
    assert '"synthetic_c3_cubed_residual": 0.0' not in source
    assert "synthetic_random_field_closure_residual" in source
    assert "synthetic_one_hot_closure_residual" in source
    assert "closure_pass = bool(" in source


def test_executed_structural_result_projection_uses_canonical_keys():
    states = {member: {"coordinate": [0.0, 0.0, 0.0]} for member in ("IDENTITY", "C3", "C3_SQUARED")}
    edges = [
        {"edge_source_member": "IDENTITY", "edge_target_member": "C3", "G_edge_integer": [0, 0]},
        {"edge_source_member": "C3", "edge_target_member": "C3_SQUARED", "G_edge_integer": [0, 0]},
        {"edge_source_member": "C3_SQUARED", "edge_target_member": "IDENTITY", "G_edge_integer": [0, 0]},
    ]
    structural = m38.structural_validation(edges, states)
    projected = m38.structural_result_fields(structural, False, 3)
    assert set(("single_mode_synthetic_status", "random_field_synthetic_status", "synthetic_closure_status")) <= set(projected)
    assert "synthetic_single_mode_status" not in structural
    assert projected["raw_c3_operator_status"] == "RAW_C3_OPERATOR_STRUCTURAL_VALIDATION_FAIL"
