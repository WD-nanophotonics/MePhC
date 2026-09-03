"""Focused zero-solve tests for M6 representation reconstruction."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m6_c3_representation_reconstruction_and_rank2_reanalysis.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m6", ENTRYPOINT)
assert SPEC and SPEC.loader
M6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M6)


def _record(geometry, deterministic, frame, member, frequencies=(1.0, 2.0, 2.5, 4.0)):
    vector = [[1.0, 0.0], [0.0, 0.0]]
    return {"geometry_id": geometry, "deterministic": deterministic, "frame_convention": frame, "repeat_index": 1, "member_index": member, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[member], "first_four_frequencies": list(frequencies), "normalized_vectors_bands_2_3": [vector, vector]}


def _records():
    return [_record(geometry, deterministic, frame, member) for geometry in ("G15", "G16") for deterministic in (False, True) for frame in ("LAB_FIXED", "C3_COVARIANT") for member in range(3)]


def test_m6_reconstructs_source_conventions_and_keeps_missing_metadata_explicit():
    result = M6.analyze(_records())
    assert result["record_count"] == 24
    assert result["c3_triplet_count"] == 8
    assert result["stored_q_coordinate_convention"].startswith("Cartesian")
    assert result["stored_vector_representation"].startswith("mpb_energy_eh_v1")
    assert result["reconstructed_metadata_completeness_status"] == "INCOMPLETE_M4_SERIALIZATION_FOR_FULL_SPATIAL_C3_OPERATOR"
    assert result["coordinate_mapping_failure_count"] == 8
    assert result["transformed_c3_subspace_closure_failure_count"] == 8
    assert result["next_science_decision"] == "ACQUIRE_MINIMAL_C3_REPRESENTATION_METADATA_ONLY"
    assert result["minimal_next_live_state_count"] == 0


def test_m6_rejects_incomplete_triplet_accounting():
    with pytest.raises(M6.M6Error, match="M6_RECORD_COUNT_INVALID"):
        M6.analyze(_records()[:-1])


def test_prescribed_component_c3_is_unitary_and_cubed_identity():
    matrix = np.asarray(M6.reconstruct_metadata()["proper_c3_direct_matrix"], dtype=float)
    assert np.allclose(matrix.T @ matrix, np.eye(2))
    assert np.allclose(matrix @ matrix @ matrix, np.eye(2))


def test_m6_has_no_expensive_execution_path():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert ".solve(" not in source
    assert '"provider_execution_count": 0' in source
    assert '"solver_execution_count": 0' in source
