"""Focused M7 zero-solve cross-dataset reconstruction tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m7_cross_dataset_spatial_mapping_and_rank2_closure.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m7", ENTRYPOINT)
assert SPEC and SPEC.loader
M7 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M7)


def _record(geometry, deterministic, frame, member, key):
    vector = [[1.0, 0.0]] * (2 * 128 * 128 * 3)
    return {"request_key_sha256": key, "geometry_id": geometry, "deterministic": deterministic, "frame_convention": frame, "repeat_index": 1, "member_index": member, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[member], "coordinate": M7.rotate_about_center([0.4722222222222222, 0.0], member), "first_four_frequencies": [1.0, 2.0, 2.5, 4.0], "normalized_vectors_bands_2_3": [vector, vector]}


def _datasets():
    m4, m2 = [], []
    index = 0
    for geometry in ("G15", "G16"):
        for deterministic in (False, True):
            for frame in ("LAB_FIXED", "C3_COVARIANT"):
                for member in range(3):
                    key = f"key-{index}"; index += 1
                    m4.append(_record(geometry, deterministic, frame, member, key))
                    for repeat in (0, 1, 2):
                        m2.append({"request_key_sha256": key, "geometry_id": geometry, "member_index": member, "repeat_index": repeat, "coordinate": m4[-1]["coordinate"], "solver_configuration": {"deterministic": deterministic, "stencil": "lab_fixed" if frame == "LAB_FIXED" else "c3_covariant", "resolution": 128}})
    return m4, m2


def test_exact_cross_dataset_binding_and_grid_shape():
    m4, m2 = _datasets()
    result = M7.analyze(m4, m2)
    assert result["m4_record_count"] == 24
    assert result["m2_record_count"] == 72
    assert result["source_binding_failure_count"] == 0
    assert result["source_equivalent_candidate_multiplicity_max"] == 3
    assert result["reconstructed_spatial_shape_status"].startswith("RECONSTRUCTED_128x128")
    assert result["coordinate_mapping_failure_count"] == 0
    assert result["next_science_decision"] == "ACQUIRE_MINIMAL_C3_REPRESENTATION_METADATA_ONLY"
    assert result["minimal_next_live_state_count"] == 3


def test_wrong_source_identity_fails_closed():
    m4, m2 = _datasets()
    for candidate in m2[:3]:
        candidate["geometry_id"] = "G16"
    with pytest.raises(M7.M7Error, match="M7_SOURCE_IDENTITY_CONFLICT"):
        M7.analyze(m4, m2)


def test_triangular_c3_operator_is_unitary_and_cubed_identity():
    matrix = np.asarray(M7.ROTATION)
    assert np.allclose(matrix.T @ matrix, np.eye(2))
    assert np.allclose(matrix @ matrix @ matrix, np.eye(2))


def test_m7_has_no_expensive_execution_path():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert ".solve(" not in source
    assert '"provider_execution_count": 0' in source
