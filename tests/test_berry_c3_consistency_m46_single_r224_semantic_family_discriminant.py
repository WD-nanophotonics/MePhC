from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m46_single_r224_semantic_family_discriminant.py"
SPEC = importlib.util.spec_from_file_location("m46", SOURCE)
assert SPEC and SPEC.loader
m46 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m46)


def power(n: int, limit: float = 2.0, amplitude: float = 5.0, p: float = 2.0) -> float:
    return limit + amplitude * n ** (-p)


def sequence(identity: str):
    return m46._sequence({n: [power(n), power(n), power(n)] for n in m46.RESOLUTIONS}, identity)


def test_r224_graph_has_exact_unique_36_records_and_dynamic_metadata():
    centers = {member: (float(index), float(index) + 0.1) for index, member in enumerate(m46.MEMBERS)}
    graph = m46.r224_graph(centers, "a" * 40)
    assert len(graph) == 36
    assert len({row["request_key_sha256"] for row in graph}) == 36
    assert {row["mode_count"] for row in graph} == {50176}
    assert {tuple(row["fft_shape"]) for row in graph} == {(224, 224)}


def test_newest_triple_fit_is_160_192_224():
    result = sequence("spectral_frequency:IDENTITY:vertex0:band1")
    assert result["fits"]["160-192-224"]["status"] == "VALID_POSITIVE_P"
    assert "prediction_residual_at_224" in result["fits"]["160-192-224"]


def test_family_counts_are_explicitly_72():
    values = {f"sequence-{i}": sequence(f"sequence-{i}") for i in range(72)}
    support = m46.family_support(values, list(values))
    assert support["sequence_count"] == 72
    assert support["state"] == "ALL_TWO_LATEST"


@pytest.mark.parametrize(
    ("spectral", "berry", "expected"),
    [("ALL_TWO_LATEST", "ALL_TWO_LATEST", "R224_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_CONTROL_QUALIFIED"),
     ("ALL_NEWEST", "NONE_NEWEST", "R224_SPECTRAL_ASYMPTOTIC_BERRY_NONASYMPTOTIC"),
     ("NONE_NEWEST", "NONE_NEWEST", "R224_FULL_FAMILY_NONASYMPTOTIC"),
     ("MIXED_NEWEST", "MIXED_NEWEST", "R224_MIXED_SEMANTIC_FAMILY")])
def test_classifier_has_one_authorized_r224_route(spectral, berry, expected):
    r224 = {"rank1_qualified": True, "rank1_c3": "PASS"}
    continuum = {"status": "PASS"}
    assert m46.classify({"state": spectral}, {"state": berry}, False, continuum, r224)[0] == expected


def test_association_instability_precedes_scalar_routing():
    outcome, decision = m46.classify({"state": "ALL_TWO_LATEST"}, {"state": "ALL_TWO_LATEST"}, True, {"status": "PASS"}, {"rank1_qualified": True, "rank1_c3": "PASS"})
    assert outcome == "R224_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"
    assert decision.startswith("ADAPTIVE_VALIDATED_SUBSPACE")


def test_direct_continuum_sign_and_finite_control_are_separate():
    fit = m46.m45r2.fit_positive_p((128, 160, 192), [power(n) for n in (128, 160, 192)])
    latest = m46.m45r2.fit_positive_p((160, 192, 224), [power(n) for n in (160, 192, 224)])
    rank2 = {f"berry_rank2_primary:{member}": {"fits": {"128-160-192": fit, "160-192-224": latest}, "table": [{"resolution": 224, "repeat_uncertainty": 0.0}]} for member in m46.MEMBERS}
    result = m46.direct_continuum_c3(rank2)
    assert result["eligibility"] is True
    assert result["status"] == "PASS"
    assert result["sign_source"] == "continuum_estimates_direct"


def test_contract_disallows_r256_in_live_entrypoint_and_has_zero_old_counts():
    text = SOURCE.read_text(encoding="utf-8")
    assert "resolution=224" in text
    assert "R256" not in text.split("def main", 1)[1]
    assert "actual_native_invocation_count" not in text or "native_invocation_count" in text
