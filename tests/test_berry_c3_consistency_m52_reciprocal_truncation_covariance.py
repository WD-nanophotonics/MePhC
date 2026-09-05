from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m52_r256_reciprocal_truncation_c3_covariance_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("m52_test_module", SOURCE)
assert SPEC and SPEC.loader
m52 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m52)


def _row(member: str, value: float = 1.0):
    return {"mesh_size": 1, "repeat_index": 0, "vertex_index": 0, "c3_member_identity": member, "frequencies_bands_1_to_4": [value] * 4, "adjacent_gaps": {"a": value}, "raw_eigenvector": None}


def test_group_requires_exact_three_c3_members():
    grouped = m52._group([_row(member) for member in m52.MEMBERS])
    assert set(grouped[(1, 0, 0)]) == set(m52.MEMBERS)


def test_distance_is_gauge_invariant_feature_distance_not_complex_component_distance():
    left = np.asarray([0.5, 0.5])
    right = np.asarray([0.25, 0.75])
    assert m52._distance(left, right) == 0.5


def test_classification_stops_at_frequency_layer_first():
    bad = {"1": {"0": {"all_repeat_pass": False, "per_repeat": []}}, "5": {str(i): {"all_repeat_pass": True, "per_repeat": []} for i in range(4)}}
    classification, decision, earliest = m52._classify(bad)
    assert classification == "C3_FAILURE_EIGENFREQUENCY_OR_GAPS"
    assert earliest == "eigenfrequency_and_gaps"
    assert "RANK1" not in decision


def test_classification_reaches_scalar_then_rank2_in_order():
    item = {"frequencies_bands_1_to_4": {"all_pass": True}, "scalar_power": {"all_pass": True}, "rank2_density": {"all_pass": False}, "projector_trace": {"all_pass": True}, "projector_determinant": {"all_pass": True}, "reciprocal_support": {"all_pass": True}}
    summary = {str(mesh): {str(vertex): {"all_repeat_pass": True, "per_repeat": [item]} for vertex in range(4)} for mesh in (1, 5)}
    classification, _decision, earliest = m52._classify(summary)
    assert classification == "C3_FAILURE_RANK2_PROJECTOR_SUBSPACE"
    assert earliest == "rank2_projector_subspace"


def test_contract_is_zero_side_effect_and_does_not_import_meep():
    text = SOURCE.read_text(encoding="utf-8")
    assert m52.RESULT_SCHEMA in text
    assert '"dataset_write": False' in text
    assert '"native_invocation_count": 0' in text
    assert "import meep" not in text
    assert "M50_DATASET_ID" in text and "M51_DATASET_ID" in text
