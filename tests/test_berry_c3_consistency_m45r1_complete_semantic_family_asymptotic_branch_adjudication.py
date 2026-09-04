from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m45r1_complete_semantic_family_asymptotic_branch_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m45r1", SOURCE)
assert SPEC and SPEC.loader
m45r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m45r1)


def power(n: int, limit: float = 2.0, amplitude: float = 7.0, p: float = 2.0) -> float:
    return limit + amplitude * n ** (-p)


def sequence(prefix: str, good: bool = True):
    values = {n: [power(n), power(n)] for n in m45r1.RESOLUTIONS} if good else {n: [1.0, 2.0, 1.0] for n in m45r1.RESOLUTIONS}
    return m45r1._scalar_sequence(values, identity=prefix)


def test_semantic_sequence_keeps_repeat_identity_and_fits_both_triples():
    result = sequence("spectral_frequency:IDENTITY:vertex0:band1")
    assert result["repeat_uncertainty_separate"] is True
    assert len(result["table"]) == 5
    assert set(result["fits"]) == {"96-128-160", "128-160-192"}
    assert result["fits"]["128-160-192"]["status"] == "VALID_POSITIVE_P"


def test_unsupported_fit_arithmetic_is_withheld_not_family_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise ZeroDivisionError("zero denominator")
    monkeypatch.setattr(m45r1.m45, "_fit_model", fail)
    result = m45r1._fit({n: float(n) for n in m45r1.RESOLUTIONS})
    assert all(item["status"] == "NO_ASYMPTOTIC_MODEL" for item in result.values())


@pytest.mark.parametrize(
    ("spectral", "berry", "expected"),
    [("ALL_TWO_TRIPLE", "ALL_TWO_TRIPLE", "COMPLETE_FAMILY_ASYMPTOTIC_CONTINUUM_C3_PASS"),
     ("ALL_LATE", "NONE_LATE", "SPECTRAL_FAMILY_ASYMPTOTIC_BERRY_NONASYMPTOTIC"),
     ("NONE_LATE", "NONE_LATE", "FULL_FAMILY_NONASYMPTOTIC_RESOLUTION_REGIME"),
     ("ALL_LATE", "ALL_LATE", "COMPLETE_FAMILY_LATE_ASYMPTOTIC_PROVISIONAL"),
     ("MIXED_LATE", "MIXED_LATE", "MIXED_SEMANTIC_FAMILY_CONVERGENCE")])
def test_contract_classification_routes_only_authorized_outcomes(spectral, berry, expected):
    s = {"state": spectral}
    b = {"state": berry}
    continuum = "PASS" if expected.endswith("PASS") else None
    assert m45r1.classify_family(s, b, False, continuum)[0] == expected


def test_association_instability_overrides_all_scalar_support():
    outcome, decision = m45r1.classify_family({"state": "ALL_LATE"}, {"state": "ALL_TWO_TRIPLE"}, True, "PASS")
    assert outcome == "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"
    assert decision.startswith("ADAPTIVE_VALIDATED_SUBSPACE")


def test_continuum_c3_requires_all_three_members_and_sign():
    fit = m45r1.m45._fit_model((96, 128, 160), [power(n) for n in (96, 128, 160)])
    late = m45r1.m45._fit_model((128, 160, 192), [power(n) for n in (128, 160, 192)])
    rank2 = {f"berry_rank2_canonical_phase_density:{member}": {"fits": {"96-128-160": fit, "128-160-192": late}, "table": [{"resolution": 192, "repeat_uncertainty": 0.0}]} for member in m45r1.MEMBERS}
    analyses = {n: {"rank2_c3_status": "PASS"} for n in m45r1.HIGH_RESOLUTIONS}
    result = m45r1._continuum_c3(rank2, analyses)
    assert result["eligibility"] is True
    assert result["status"] == "PASS"


def test_forbidden_reacquisition_and_zero_execution_are_explicit():
    text = SOURCE.read_text(encoding="utf-8")
    assert "ZERO_SCIENTIFIC_EXECUTION" in text
    assert "_read_dataset" in text
    assert "R224_PLUS_CONDITIONAL_R256_RESOLUTION_EXTENSION" in text
    assert "R224" not in text.split("def main", 1)[1]
