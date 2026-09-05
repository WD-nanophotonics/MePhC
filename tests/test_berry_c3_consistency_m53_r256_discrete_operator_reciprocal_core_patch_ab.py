from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m53_r256_discrete_operator_reciprocal_core_patch_ab.py"
SPEC = importlib.util.spec_from_file_location("m53_test_module", SOURCE)
assert SPEC and SPEC.loader
m53 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m53)


def _operator(*, nonzero: int):
    return {"IDENTITY_to_C3": {"stock_nonzero_delta_q_count": nonzero}, "C3_to_C3_SQUARED": {"stock_nonzero_delta_q_count": nonzero}, "C3_SQUARED_to_IDENTITY": {"stock_nonzero_delta_q_count": nonzero}}


def _failure(*, supported: bool):
    return {"complete_causal_signature": supported}


def test_contract_constants_are_zero_execution_and_two_file_scoped():
    assert m53.RESULT_SCHEMA.endswith("m53-r256-discrete-operator-reciprocal-core-patch-ab-v1")
    assert len(m53.MESH_DATASETS) == 3
    assert m53.MODE_COUNT == 65536


def test_synthetic_regressions_cover_operator_and_causal_branches():
    assert all(value == "PASS" for value in m53.synthetic_operator_regression().values())
    assert all(value == "PASS" for value in m53.synthetic_causal_regression().values())


def test_classification_requires_every_failing_pair_for_full_causal_claim():
    failures = [{"id": 1}, {"id": 2}]
    assert m53.classify(failures, [_failure(supported=True), _failure(supported=True)], _operator(nonzero=1))[0] == "R256_M5_RECIPROCAL_WINDOW_CAUSAL_SIGNATURE_SUPPORTED"
    assert m53.classify(failures, [_failure(supported=True), _failure(supported=False)], _operator(nonzero=1))[0] == "R256_M5_RECIPROCAL_WINDOW_MIXED_CONTRIBUTOR"
    assert m53.classify(failures, [_failure(supported=False), _failure(supported=False)], _operator(nonzero=1))[0] == "R256_M5_RECIPROCAL_WINDOW_STRUCTURAL_ONLY_NOT_CAUSAL"


def test_classification_separates_physical_covariance_from_window_difference():
    failures = [{"id": 1}]
    assert m53.classify(failures, [_failure(supported=True)], _operator(nonzero=0))[0] == "R256_M5_STOCK_OPERATOR_PHYSICALLY_C3_COVARIANT_DESPITE_UNWRAPPED_WINDOW"
    assert m53.classify([], [], _operator(nonzero=1))[0] == "R256_M5_FREQUENCY_C3_FAILURE_NOT_REPRODUCED"


def test_exact_core_pullback_does_not_renormalize_and_uses_measured_repeat_uncertainty():
    edge = {"exact_labels": [(0, 0), (0, 1)], "wrapped_labels": [(0, 0), (0, 0)]}
    source = [np.pad(np.array([[1.0, 2.0]]), ((0, 0), (0, 65534))) for _ in range(3)]
    target = [np.pad(np.array([[1.0, 2.0]]), ((0, 0), (0, 65534))) for _ in range(3)]
    exact = m53._pullback(source, target, edge, 0, np.array([0, 1]), exact=True)
    stock = m53._pullback(source, target, edge, 0, np.array([0, 1]), exact=False)
    assert exact["sample_count"] == 2
    assert exact["pass"]
    assert stock["residual_l1"] == 1.0


def test_source_has_no_science_engine_or_raw_component_comparison():
    text = SOURCE.read_text(encoding="utf-8")
    assert "import meep" not in text
    assert "np.angle" not in text
    assert "np.bincount" not in text
    assert '"dataset_write": False' in text
