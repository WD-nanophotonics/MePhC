from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m52r1_exact_reciprocal_label_scalar_ladder.py"
SPEC = importlib.util.spec_from_file_location("m52r1_test_module", SOURCE)
assert SPEC and SPEC.loader
m52r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m52r1)


def _item(pass_value=True):
    return {"pass": pass_value, "residual": 0.0, "combined_repeat_uncertainty": 1.0}


def _summary(*, frequency=True, gaps=True, fields=True, boundaries=True):
    frequency_edge = {f"band{i}": _item(frequency) for i in range(4)}
    gaps_edge = {name: _item(gaps) for name in ("lower_gap", "internal_split", "upper_gap", "band2_isolation_gap")}
    fields_edge = {"band_power": {f"band{i}": _item(fields) for i in range(4)}, "rank2_power": _item(fields), "rank2_trace": _item(fields), "rank2_determinant": _item(fields)}
    boundary_edge = {"band_power": {f"band{i}": _item(boundaries) for i in range(4)}, "rank2_power": _item(boundaries), "rank2_trace": _item(boundaries), "rank2_determinant": _item(boundaries)}
    return {str(vertex): {"frequency": {"IDENTITY_to_C3": frequency_edge}, "gaps": {"IDENTITY_to_C3": gaps_edge}, "fields": {"IDENTITY_to_C3": fields_edge}, "boundary_power": {"IDENTITY_to_C3": boundary_edge}} for vertex in range(4)}


def test_scalar_features_have_real_raw_h_shape_and_rank2_determinant_is_one_dimensional():
    rng = np.random.default_rng(7)
    raw = rng.normal(size=(4, 65536, 2)) + 1j * rng.normal(size=(4, 65536, 2))
    features = m52r1.scalar_features(raw)
    assert features["band_power"].shape == (4, 65536)
    assert features["rank2_determinant"].shape == (65536,)


def test_rank2_invariants_survive_unitary_band_and_component_rotations():
    rng = np.random.default_rng(8)
    raw = rng.normal(size=(4, 65536, 2)) + 1j * rng.normal(size=(4, 65536, 2))
    first = m52r1.scalar_features(raw)
    q1, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
    q2, _ = np.linalg.qr(rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2)))
    rotated = raw.copy()
    rotated[1:3] = np.einsum("ab,bpc->apc", q1, raw[1:3])
    rotated[1:3] = np.einsum("apc,cd->apd", rotated[1:3], q2)
    second = m52r1.scalar_features(rotated)
    for name in ("rank2_power", "rank2_trace", "rank2_determinant"):
        assert np.allclose(first[name], second[name], rtol=1e-12, atol=1e-12)


def test_frequency_failure_is_classified_before_later_layers():
    classification, decision, earliest = m52r1.classify(_summary(frequency=False, fields=False), True)
    assert classification == "R256_M5_FREQUENCY_C3_FAILURE_WITH_NONCOVARIANT_RECIPROCAL_WINDOW"
    assert earliest == "L1_frequency"
    assert "MPB_DISCRETE_OPERATOR" in decision


def test_gap_failure_after_frequency_pass():
    assert m52r1.classify(_summary(gaps=False), False)[0] == "R256_M5_FREQUENCY_PASS_GAP_C3_FAILURE"


def test_scalar_field_failure_after_frequency_and_gap_pass():
    assert m52r1.classify(_summary(fields=False), False)[0] == "R256_M5_SPECTRAL_PASS_SCALAR_FIELD_C3_FAILURE"


def test_rank2_failure_and_all_through_rank2_routes():
    assert m52r1.classify(_summary(), False)[0] == "R256_M5_C3_PASS_THROUGH_RANK2"
    assert m52r1.classify(_summary(boundaries=False), False)[0] == "R256_M5_SPECTRAL_PASS_SCALAR_FIELD_C3_FAILURE"


def test_exact_label_path_has_no_histogram_or_complex_component_comparison():
    text = SOURCE.read_text(encoding="utf-8")
    assert "np.bincount" not in text
    assert "np.angle" not in text
    assert "import meep" not in text
    assert '"dataset_write": False' in text
