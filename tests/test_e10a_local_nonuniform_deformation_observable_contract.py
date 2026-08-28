from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit/e10a/local_nonuniform_deformation_observable_contract.py"
SPEC = importlib.util.spec_from_file_location("e10a_contract", PATH)
assert SPEC is not None and SPEC.loader is not None
E10A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E10A)


def test_bound_inputs_and_e8_statuses_are_verified():
    hashes, d11, e8a, e8b_contract, e8b_closure = E10A.verify_inputs()
    assert len(hashes) == 7
    assert d11["terminal"].endswith("SYNTHESIS_COMPLETE")
    assert e8a["classification"]["physical_response_status"].endswith("NOT_YET_DERIVED")
    assert e8b_contract["authorization"]["local_nonuniform_deformation"] is False
    assert e8b_closure["main_unchanged"] is True


def test_coordinate_chain_keeps_physical_and_normalized_k_distinct():
    contract, _ = E10A.build_documents()
    equations = contract["coordinate_contract"]
    assert "k_phys" in equations["reciprocal_basis"]
    assert "q=" in equations["normalized_coordinate"]
    assert "kappa=A(r)^T" in equations["normalized_coordinate"]
    assert "grad_r s" in equations["strain_gradient"]


def test_missing_phase_space_objects_block_live_pilot():
    contract, feasibility = E10A.build_documents()
    result = contract["result_summary"]
    assert result["current_framework_sufficient_for_observable"] is False
    assert result["e10a_next_step"] == "THEORY_OR_FRAMEWORK_EXTENSION_REQUIRED_BEFORE_LIVE_PILOT"
    assert result["weighted_berry_gradient_observable_role"] == "DESCRIPTOR_ONLY_NO_OBSERVABLE_MAPPING_ESTABLISHED"
    assert feasibility["no_live_authorization"] is True
    assert feasibility["mixed_phase_space_object_required"] is True


def test_contract_is_solver_free_and_preserves_prior_policy():
    contract, _ = E10A.build_documents()
    result = contract["result_summary"]
    assert result["native_invocation_count"] == 0
    assert result["provider_request_count"] == 0
    assert result["native_solves"] == 0
    assert result["mpb_execution"] is False
    assert contract["policy"]["production_threshold_action"] == "RETAIN_UNCHANGED"
