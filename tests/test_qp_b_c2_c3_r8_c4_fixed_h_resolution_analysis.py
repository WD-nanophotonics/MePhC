from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e9f/qp_b_c2_c3_r8_c4_fixed_h_resolution_analysis.py"


def load():
    spec = importlib.util.spec_from_file_location("r8_c4_analysis", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analysis():
    module = load()
    return module, module.analyze()


def test_srd_and_final_increment_classification_are_exact():
    module = load()
    assert module.srd(0.0, 0.0) == 0.0
    assert module.srd(1.0, -1.0) == 2.0
    assert module.relation(2.0, 1.0) == "FINAL_INCREMENT_CONTRACTS"
    assert module.relation(1.0, 2.0) == "FINAL_INCREMENT_EXPANDS"
    assert module.relation(1.0, 1.0) == "FINAL_INCREMENT_EQUAL_NONZERO"
    assert module.relation(0.0, 0.0) == "ALL_ZERO_STABLE"
    assert module.signed_behavior(1.0, 2.0) == "MONOTONIC_LAST_TWO_STEPS"
    assert module.signed_behavior(1.0, -2.0) == "OSCILLATORY_OR_OVERSHOOT_LAST_TWO_STEPS"


def test_prospective_graph_is_mechanical_and_nonexecuting():
    module = load()
    samples = [(i, j, role, {"final_fixed_h_contraction_pass": True}) for i, j, role in module.SAMPLES]
    graph = module.prospective_graph(samples, "PROCEED_TO_R192_H_1_288_THIRD_STENCIL_DESIGN")
    assert graph["status"] == "DESIGNED_NOT_EXECUTED"
    assert graph["logical_demand_count"] == 32
    assert graph["unique_provider_request_count"] == 32
    assert graph["duplicate_count"] == 0
    assert all(item["coordinate"]["denominator"] == 288 for item in graph["logical_demands"])
    assert graph["selected_sample_ids"] == [module.sample_id(i, j) for i, j, _ in module.SAMPLES]


def test_real_analysis_binds_both_immutable_datasets_and_preserves_policy(analysis):
    _, result = analysis
    assert result["parent_dataset_binding"] == {
        "status": "VERIFIED",
        "dataset_id": "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db",
        "manifest_sha256": "55828e4a0eb6e24914807e42d13fa113457ce080ffe37c947b3c0cd7af1281d7",
        "record_count": 210,
        "source_commit": "c8eeaa4e5fa78e25a5b7df07510b446b1f6d6738",
    }
    assert result["r192_dataset_binding"]["status"] == "VERIFIED"
    assert result["r192_dataset_binding"]["dataset_id"] == "446ad69a302c9eb3524b67fe2127701030f62986dd1ccc570e3b0830a3dc488c"
    assert result["r192_dataset_binding"]["record_count"] == 70
    assert result["r192_provenance_status"] == "VERIFIED_EXECUTION_SOURCE_REBOUND_WITHOUT_DATASET_MUTATION"
    assert result["sample_count"] == 8
    assert result["execution"] == {
        "native_invocation_count": 0, "provider_request_count": 0,
        "solver_executions": 0, "native_solves": 0, "mpb_execution": False,
    }
    assert result["current_0p02_policy_calibration"] == "INCONCLUSIVE"
    assert result["c1_rescoring"] is False
    assert result["threshold_change_authorized"] is False
    assert result["holdout_used"] is False
    assert result["band2_chern_execution"] is False
    assert result["q2_finite_stencil_convergence_status"] == "NOT_ESTABLISHED_WITH_TWO_STENCILS"


def test_real_analysis_has_four_resolution_values_and_exact_report_projection(analysis):
    module, result = analysis
    assert all(set(item["stencils"]) == {"1/72", "1/144"} for item in result["samples"].values())
    assert all(set(item["stencils"][stencil]["omega"]) == set(module.RESOLUTIONS)
               for item in result["samples"].values() for stencil in module.STENCILS)
    assert result["all_eight_fixed_h_contraction_pass_count"] <= 8
    assert result["next_axis_decision"] in {
        "PROCEED_TO_R192_H_1_288_THIRD_STENCIL_DESIGN",
        "TARGETED_HIGHER_RESOLUTION_REQUIRED_BEFORE_THIRD_STENCIL",
        "INCONCLUSIVE_DATA_OR_PROVENANCE",
    }
    evidence = module.evidence_artifact(result)
    contract = module.next_axis_artifact(result)
    serialized = json.dumps({"evidence": evidence, "contract": contract}, ensure_ascii=False)
    assert "h_fields" not in serialized
    assert "normalized_vectors" not in serialized
    assert "/home/" not in serialized
    assert contract["designed_not_executed"] is True
    assert contract["h_1_288_execution"] is False
    assert contract["r224_execution"] is False


def test_analysis_source_has_no_live_execution_path():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "from mephc.mpb_spectral_provider" not in source
    assert "build_r8_provider_factory" not in source
    assert "run-native" not in source
    assert "provider_solve" not in source
