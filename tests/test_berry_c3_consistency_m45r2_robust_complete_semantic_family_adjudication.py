from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m45r2_robust_complete_semantic_family_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m45r2", SOURCE)
assert SPEC and SPEC.loader
m45r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m45r2)


def power(n: int, y_inf: float = 2.0, a: float = 5.0, p: float = 2.0) -> float:
    return y_inf + a * n ** (-p)


def sequence(identity: str, good: bool = True):
    values = {n: [power(n), power(n), power(n)] if good else [1.0, 2.0, 1.0] for n in m45r2.RESOLUTIONS}
    return m45r2._sequence(values, identity)


def test_robust_fit_recovers_power_law_without_inherited_solver():
    result = m45r2.fit_positive_p((96, 128, 160), [power(n) for n in (96, 128, 160)])
    assert result["status"] == "VALID_POSITIVE_P"
    assert abs(result["p"] - 2.0) < 1e-8
    assert abs(result["y_inf"] - 2.0) < 1e-8


def test_ratio_at_or_below_p0_limit_is_withheld_without_overflow():
    result = m45r2.fit_positive_p((96, 128, 160), [1.0, 1.5, 2.0])
    assert result["status"] == "NO_ASYMPTOTIC_MODEL"
    assert result["reason"] in {"zero_sign_change_or_nonshrinking_increment", "ratio_at_or_below_p0_limit"}


def test_large_ratio_is_structured_not_zero_division_or_overflow():
    result = m45r2.fit_positive_p((96, 128, 160), [1.0, 1.0 - 1e-200, 1.0 - 1.1e-200])
    assert result["status"] == "NO_ASYMPTOTIC_MODEL"
    assert "reason" in result


def test_every_fit_has_prediction_diagnostic_and_repeat_floor():
    result = sequence("spectral_frequency:IDENTITY:vertex0:band1")
    assert result["repeat_uncertainty_separate"] is True
    assert "prediction_residual_at_192" in result["fits"]["96-128-160"]


def test_family_support_uses_explicit_keys_not_prefix_omission():
    values = {f"item-{i}": sequence(f"item-{i}") for i in range(72)}
    support = m45r2.family_support(values, list(values))
    assert support["sequence_count"] == 72
    assert support["state"] == "ALL_TWO_TRIPLE"


@pytest.mark.parametrize(
    ("spectral", "berry", "expected"),
    [("ALL_TWO_TRIPLE", "ALL_TWO_TRIPLE", "COMPLETE_FAMILY_ASYMPTOTIC_CONTINUUM_C3_PASS"),
     ("ALL_LATE", "MIXED_LATE", "SPECTRAL_FAMILY_ASYMPTOTIC_BERRY_NONASYMPTOTIC"),
     ("NONE_LATE", "NONE_LATE", "FULL_FAMILY_NONASYMPTOTIC_RESOLUTION_REGIME"),
     ("MIXED_LATE", "MIXED_LATE", "MIXED_SEMANTIC_FAMILY_CONVERGENCE")])
def test_classification_matches_contract(spectral, berry, expected):
    result = m45r2.classify_family({"state": spectral}, {"state": berry}, False, "PASS")
    assert result[0] == expected


def test_direct_continuum_sign_is_not_finite_resolution_status():
    fit = m45r2.fit_positive_p((96, 128, 160), [power(n) for n in (96, 128, 160)])
    late = m45r2.fit_positive_p((128, 160, 192), [power(n) for n in (128, 160, 192)])
    rank2 = {f"berry_rank2_primary:{member}": {"fits": {"96-128-160": fit, "128-160-192": late}, "table": [{"resolution": 192, "repeat_uncertainty": 0.0}]} for member in m45r2.MEMBERS}
    result = m45r2.direct_continuum_c3(rank2, {})
    assert result["eligibility"] is True
    assert result["status"] == "PASS"
    assert result["sign_source"] == "continuum_estimates_direct"


def test_source_has_local_detail_path_and_zero_science_budget():
    text = SOURCE.read_text(encoding="utf-8")
    assert "def configuration_detail" in text
    assert "def fit_positive_p" in text
    assert "spectral_subspace_total" in text
    assert "72" in text
    assert "m45._fit_model" not in text
    assert "native_invocation_count\": 0" in text
