import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e9f/qp_b_c2_c3_r8_c1_solver_free_calibration.py"
EVIDENCE = ROOT / "audit/e9f/qp_b_c2_c3_r8_c1_locked_set_evidence.json"
CALIBRATION = ROOT / "audit/e9f/qp_b_c2_c3_r8_c1_calibration.json"


def load_script():
    spec = importlib.util.spec_from_file_location("_r8_c1_calibration_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analysis():
    module = load_script()
    return module, module.analyze()


def test_srd_preregistered_arithmetic_and_zero_case():
    module = load_script()
    assert module.srd(0.0, 0.0) == 0.0
    assert module.srd(1.0, -1.0) == 2.0
    assert module.srd(1.0, 3.0) == pytest.approx(1.0)


def test_exact_immutable_dataset_and_all_twenty_four_bundles(analysis):
    _, result = analysis
    assert result["dataset"] == {
        "dataset_id": "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db",
        "manifest_sha256": "55828e4a0eb6e24914807e42d13fa113457ce080ffe37c947b3c0cd7af1281d7",
        "record_count": 210,
        "acquisition_source_commit": "c8eeaa4e5fa78e25a5b7df07510b446b1f6d6738",
    }
    assert result["sample_resolution_pair_count"] == 24
    assert result["stencil_curvature_value_count"] == 48
    assert len(result["pair_evidence"]) == 24
    assert all(pair["status"] == "COMPLETE_VALID" for pair in result["pair_evidence"])
    assert all(len(pair["curvature"]) == 2 for pair in result["pair_evidence"])
    assert len(result["historical_anchor_comparisons"]) == 30
    assert {item["decision_role"] for item in result["historical_anchor_comparisons"]} == {
        "CONSISTENCY_EVIDENCE_ONLY"
    }


def test_gap_policy_is_separate_and_verdict_mapping_is_fail_closed(analysis):
    _, result = analysis
    below = [pair for pair in result["pair_evidence"] if pair["current_policy_gap_status"] == "BELOW_0P02"]
    assert below and all(pair["status"] == "COMPLETE_VALID" for pair in below)
    assert result["controls"]["valid"] is False
    assert result["controls"]["envelopes"] is None
    assert result["stencil_diagnostic"]["pass"] is False
    assert set(result["policy_challenges"].values()) == {"INCOMPLETE_OR_AMBIGUOUS"}
    assert result["current_0p02_policy_calibration"] == "INCONCLUSIVE"
    assert result["threshold_change_authorized"] is False


def test_tracked_artifacts_equal_bounded_projection(analysis):
    module, result = analysis
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    assert evidence == module.evidence_artifact(result)
    assert calibration == module.calibration_artifact(result)
    serialized = EVIDENCE.read_text(encoding="utf-8") + CALIBRATION.read_text(encoding="utf-8")
    assert "h_fields" not in serialized
    assert "normalized_vectors" not in serialized
    assert "/home/" not in serialized


def test_execution_is_solver_free_and_does_not_construct_provider(analysis):
    _, result = analysis
    assert result["execution"] == {
        "native_invocations": 0,
        "provider_requests": 0,
        "solver_executions": 0,
        "mpb_execution": False,
    }
    source = SCRIPT.read_text(encoding="utf-8")
    assert "build_r8_provider_factory(" not in source
    assert "_build_live_provider(" not in source
    assert "run-native" not in source
    assert result["band2_chern_execution"] is False
    assert result["full_source_grid_validation_still_required"] is True
