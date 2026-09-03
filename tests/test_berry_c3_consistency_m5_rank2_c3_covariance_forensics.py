"""Focused tests for M5 solver-free C3 covariance forensics."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m5_rank2_c3_covariance_forensics.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m5", ENTRYPOINT)
assert SPEC and SPEC.loader
M5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M5)


def _record(geometry, deterministic, frame, member, frequencies=(1.0, 2.0, 2.5, 4.0)):
    vector = [[1.0, 0.0], [0.0, 0.0]]
    return {
        "geometry_id": geometry, "deterministic": deterministic, "frame_convention": frame,
        "repeat_index": 1, "member_index": member, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[member],
        "first_four_frequencies": list(frequencies), "normalized_vectors_bands_2_3": [vector, vector],
    }


def _records():
    return [_record(geometry, deterministic, frame, member) for geometry in ("G15", "G16") for deterministic in (False, True) for frame in ("LAB_FIXED", "C3_COVARIANT") for member in range(3)]


def test_unordered_pair_metric_is_invariant_to_member_order():
    first = M5.unordered_pair_metrics((2.0, 2.5), (2.0, 2.5))
    second = M5.unordered_pair_metrics((2.0, 2.5), (2.5, 2.0))
    assert first == second == {"pair_center_residual": 0.0, "pair_splitting_residual": 0.0, "unordered_pair_residual": 0.0}


def test_analyze_reconstructs_eight_triplets_and_keeps_representation_fail_safe():
    result = M5.analyze(_records())
    assert result["record_count"] == 24
    assert result["c3_triplet_count"] == 8
    assert result["coordinate_mapping_failure_count"] == 8
    assert result["spectral_c3_unordered_pair_residual_max"] == 0.0
    assert result["representation_test_status"] == "INSUFFICIENT_STORED_METADATA"
    assert result["rank2_covariance_interpretation"] == "PHYSICAL_C3_MAPPING_NOT_ESTABLISHED"
    assert result["next_science_decision"] == "ACQUIRE_MINIMAL_C3_REPRESENTATION_METADATA_ONLY"
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0


def test_missing_or_wrong_record_binding_fails_closed():
    with pytest.raises(M5.M5Error, match="M5_RECORD_COUNT_INVALID"):
        M5.analyze(_records()[:-1])
    with pytest.raises(M5.M5Error, match="M5_TRIPLET_ACCOUNTING_INVALID"):
        M5.analyze(_records()[:-1] + [_record("G15", False, "LAB_FIXED", 0)])


def test_operator_is_not_guessed_from_flat_vectors():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "U(2)" not in source
    assert "phase optimization" not in source
    assert "normalized_vectors_bands_2_3" in source
