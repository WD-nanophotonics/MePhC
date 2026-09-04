from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m45_resolution_asymptotic_extrapolation_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m45", SOURCE)
assert SPEC and SPEC.loader
m45 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m45)


def _power_law(resolution: int, y_inf: float = 2.0, amplitude: float = 5.0, p: float = 2.0) -> float:
    return y_inf + amplitude * resolution ** (-p)


def test_positive_p_fit_recovers_declared_model():
    resolutions = (96, 128, 160)
    result = m45._fit_model(resolutions, [_power_law(n) for n in resolutions])
    assert result["status"] == "VALID_POSITIVE_P"
    assert abs(result["p"] - 2.0) < 1e-8
    assert abs(result["y_inf"] - 2.0) < 1e-8


def test_fit_is_withheld_for_sign_oscillation_or_nonshrinking_increment():
    result = m45._fit_model((96, 128, 160), [1.0, 2.0, 1.0])
    assert result["status"] == "NO_ASYMPTOTIC_MODEL"
    result = m45._fit_model((96, 128, 160), [1.0, 1.5, 2.1])
    assert result["status"] == "NO_ASYMPTOTIC_MODEL"


def test_sequence_reports_adjacent_truncation_separately_from_repeat_floor():
    sequence = m45._sequence({resolution: _power_law(resolution) for resolution in m45.RESOLUTIONS})
    assert len(sequence["table"]) == 5
    assert sequence["table"][0]["absolute_difference_to_next"] > 0
    assert sequence["repeat_uncertainty_separate"] is True
    assert set(sequence["fits"]) == {"96-128-160", "128-160-192"}


def test_continuum_envelope_and_c3_are_explicit():
    fit = m45._fit_model((96, 128, 160), [_power_law(n) for n in (96, 128, 160)])
    late = m45._fit_model((128, 160, 192), [_power_law(n) for n in (128, 160, 192)])
    envelope = m45._continuum({"96-128-160": fit, "128-160-192": late}, 0.001)
    assert envelope["status"] == "TWO_TRIPLE_ASYMPTOTIC"
    assert envelope["discretization_envelope"] >= 0
    c3 = m45._pairwise_continuum({member: envelope for member in ("IDENTITY", "C3", "C3_SQUARED")})
    assert c3["status"] == "PASS"


def test_classification_routes_spectral_vs_berry_and_association():
    assert m45.classify(True, False, False, None)[0] == "SPECTRAL_ASYMPTOTIC_BERRY_NONASYMPTOTIC"
    assert m45.classify(False, False, False, None)[0] == "FULL_NONASYMPTOTIC_RESOLUTION_REGIME"
    assert m45.classify(True, True, True, "PASS")[0] == "HIGH_RESOLUTION_ASSOCIATION_INSTABILITY"


def test_contract_is_zero_execution_and_no_unmeasured_extension():
    source = SOURCE.read_text(encoding="utf-8")
    assert '"native_invocation_count": 0' in source
    assert '"provider_execution_count": 0' in source
    assert '"solver_execution_count": 0' in source
    assert "y_inf+a*N^-p" in source
    assert "128, 160, 192" in source
    assert "No additional solver" not in source or "solver-free" in source
