from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m47_corrected_single_r256_semantic_family_discriminant.py"
SPEC = importlib.util.spec_from_file_location("m47", SOURCE)
assert SPEC and SPEC.loader
m47 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m47)


def power(n: int, limit: float = 2.0, amplitude: float = 5.0, p: float = 2.0) -> float:
    return limit + amplitude * n ** (-p)


def sequence(identity: str):
    return m47._sequence({n: [power(n), power(n), power(n)] for n in m47.RESOLUTIONS}, identity)


def test_r256_graph_exactly_36_dynamic_states():
    centers = {member: (float(i), float(i) + 0.1) for i, member in enumerate(m47.MEMBERS)}
    graph = m47.r256_graph(centers, "a" * 40)
    assert len(graph) == 36
    assert len({row["request_key_sha256"] for row in graph}) == 36
    assert {row["mode_count"] for row in graph} == {65536}
    assert {tuple(row["fft_shape"]) for row in graph} == {(256, 256)}


def test_newest_and_previous_fit_triples_are_recorded():
    result = sequence("spectral_frequency:IDENTITY:vertex0:band1")
    assert set(result["fits"]) == {"128-160-192", "160-192-224", "192-224-256"}
    assert result["fits"]["192-224-256"]["status"] == "VALID_POSITIVE_P"


def test_family_support_is_exact_and_not_majority_based():
    values = {f"seq-{i}": sequence(f"seq-{i}") for i in range(72)}
    support = m47._family(values, list(values), (192, 224, 256), (160, 192, 224))
    assert support["sequence_count"] == 72
    assert support["state"] == "ALL_TWO_LATEST"


@pytest.mark.parametrize(
    ("spectral", "berry", "expected"),
    [("NONE_NEWEST", "NONE_NEWEST", "R256_FULL_FAMILY_NONASYMPTOTIC"),
     ("MIXED_NEWEST", "MIXED_NEWEST", "R256_MIXED_SEMANTIC_FAMILY"),
     ("ALL_NEWEST", "NONE_NEWEST", "R256_SPECTRAL_ASYMPTOTIC_BERRY_NONASYMPTOTIC")])
def test_authorized_r256_classification_branches(spectral, berry, expected):
    result = m47._classification({"state": spectral}, {"state": berry}, {"unstable": False}, {"status": "WITHHELD"}, {"rank1_qualified": False, "rank1_c3": "RANK1_WITHHELD"})
    assert result[0] == expected


def test_association_instability_has_priority():
    result = m47._classification({"state": "ALL_TWO_LATEST"}, {"state": "ALL_TWO_LATEST"}, {"unstable": True}, {"status": "PASS"}, {"rank1_qualified": True, "rank1_c3": "PASS"})
    assert result[0] == "R256_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"


def test_continuum_sign_is_direct_and_finite_control_separate():
    fit = m47.m45r2.fit_positive_p((128, 160, 192), [power(n) for n in (128, 160, 192)])
    latest = m47.m45r2.fit_positive_p((192, 224, 256), [power(n) for n in (192, 224, 256)])
    rank2 = {f"berry_rank2_primary:{member}": {"fits": {"128-160-192": fit, "192-224-256": latest}, "table": [{"resolution": 256, "repeat_uncertainty": 0.0}]} for member in m47.MEMBERS}
    result = m47._continuum(rank2, (128, 160, 192), (192, 224, 256))
    assert result["eligibility"] is True
    assert result["status"] == "PASS"


def test_source_has_conditional_gate_and_no_r288_execution():
    text = SOURCE.read_text(encoding="utf-8")
    assert "pre_native_corrected_m46_classification" in text
    assert "pre_native_r256_authorized" in text
    assert "resolution=256" in text
    assert "R288" not in text.split("def main", 1)[1]
