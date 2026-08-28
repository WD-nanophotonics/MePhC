from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit/e9f/d11_fr04_source_reproduction_terminal_synthesis.py"
SPEC = importlib.util.spec_from_file_location("d11_synthesis", PATH)
assert SPEC is not None and SPEC.loader is not None
D11 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D11)


def test_bound_artifact_manifest_is_exact_and_solver_free():
    assert len(D11.ARTIFACTS) == 10
    assert D11.RUNTIME_SHA256 == "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"


def test_primary_failure_cells_are_replayed_from_d10_evidence():
    files = D11.verify_bound_artifacts()
    assert D11.exact_failure_cells(files["audit/e9f/d10_fr04_primary_stencil_convergence.json"], "rank2") == [[-5, -1], [-5, 1]]
    assert D11.exact_failure_cells(files["audit/e9f/d10_fr04_primary_stencil_convergence.json"], "rank3") == [[-5, -1], [-5, 1]]


def test_refined_failure_criteria_are_not_collapsed():
    files = D11.verify_bound_artifacts()
    expected = [{"grid_index": [-35, -15], "failed_criteria": ["terminal_nonincrease"]}, {"grid_index": [-5, -1], "failed_criteria": ["even_contraction"]}]
    assert D11.refined_failures(files["audit/e9f/d10_fr04_refined_stencil_convergence.json"], "rank2") == expected
    assert D11.refined_failures(files["audit/e9f/d10_fr04_refined_stencil_convergence.json"], "rank3") == expected


def test_synthesis_preserves_no_new_scientific_execution():
    files = D11.verify_bound_artifacts()
    d10 = files["audit/e9f/d10_fr04_composite_method_validation_result.json"]
    assert d10["native_invocation_count"] == 0
    assert d10["provider_request_count"] == 0
    assert d10["native_solves"] == 0
    assert d10["mpb_execution"] is False
