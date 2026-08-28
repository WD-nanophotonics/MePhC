from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit/e10b/mixed_phase_space_geometry_contract.py"
SPEC = importlib.util.spec_from_file_location("e10b_contract", PATH)
assert SPEC is not None and SPEC.loader is not None
E10B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E10B)


def test_e10a_binding_and_reference_theory_boundary_are_verified():
    hashes = E10B.verify_e10a()
    assert len(hashes) == 3
    reference, _, _, _ = E10B.documents()
    assert reference["references"]["project_implementation_status"].startswith("REFERENCE_BOUND_CONTRACT_ONLY")


def test_fixed_q_chain_rule_and_mixed_pullback_are_explicit():
    _, geometry, _, _ = E10B.documents()
    assert "partial kappa/partial s" in geometry["fixed_q_chain_rule"]["statement"]
    assert geometry["canonical_coordinates"]["local_mpb_fractional_coordinate"] == "kappa(s,q)=A(s)^T q"
    assert geometry["mixed_conversion"]["Omega_qi_rj"] == "Omega_qi_s * partial_rj s"
    assert "antisymmetry" in geometry["rr_vanishing_proof"]


def test_estimator_scope_and_reference_cell_certification_are_fail_closed():
    _, _, estimator, feasibility = E10B.documents()
    assert estimator["rank1_estimator"]["signed_area_qs"] == "2*h_q*h_s"
    assert estimator["rankN_estimator"]["scope"].startswith("RANKN_DETERMINANT_WILSON_ROLE")
    assert estimator["reference_cell_pullback"]["required_status"].endswith("CERTIFICATION")
    assert feasibility["reference_cell_overlap_resolved"] is False
    assert feasibility["no_live_authorization"] is True


def test_e10b_remains_solver_free_and_selects_one_next_step():
    _, geometry, _, feasibility = E10B.documents()
    result = geometry["result_summary"]
    assert result["e10b_next_step"] == "REFERENCE_CELL_OR_INNER_PRODUCT_CONTRACT_UNRESOLVED"
    assert result["native_invocation_count"] == 0
    assert result["provider_request_count"] == 0
    assert result["native_solves"] == 0
    assert result["mpb_execution"] is False
    assert feasibility["minimal_framework_extension_uniquely_defined"] is True
