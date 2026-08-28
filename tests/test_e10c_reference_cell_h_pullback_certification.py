from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "audit/e10c/reference_cell_h_pullback_certification.py"
SPEC = importlib.util.spec_from_file_location("e10c_contract", PATH)
assert SPEC is not None and SPEC.loader is not None
E10C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E10C)


def test_e10b_binding_and_provider_audit_pass():
    bound = E10C.verify_e10b()
    assert bound["hashes"] == E10C.E10B_HASHES
    audit = E10C.audit_provider()
    assert audit["code_audit_status"] == "PASS"
    assert audit["supervisor_bound_facts"]["field_representation"] == "mpb_periodic_h_l2_v1"


def test_solver_free_synthetic_certification_passes():
    result = E10C.synthetic_certification()
    assert result["overall_status"] == "PASS"
    assert result["solver_free"] is True
    assert result["mpb_imported"] is False
    assert all(check["status"] == "PASS" for check in result["checks"].values())


def test_reference_cell_contract_selects_exactly_one_next_step():
    semantics, hilbert, synthetic, feasibility = E10C.documents()
    result = hilbert["result_summary"]
    assert semantics["bloch_phase_included"] is False
    assert hilbert["deformation"]["det_F"] == 1.0
    assert synthetic["overall_status"] == "PASS"
    assert feasibility["status"] == "READY_FOR_SOLVER_FREE_PHASE_SPACE_GEOMETRY_KERNEL_IMPLEMENTATION"
    assert result["current_h_vector_representation_reusable_for_cross_s_overlap"] is True
    assert result["next_live_solver_authorization"] is False
    assert result["terminal"] == "E10C_REFERENCE_CELL_H_PULLBACK_CERTIFICATION_COMPLETE"
