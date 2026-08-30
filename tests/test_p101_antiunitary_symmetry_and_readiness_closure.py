from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "local_phase_space_symmetry_and_readiness_closure.py"
ARTIFACT = ROOT / "audit" / "local_affine" / "p101_local_phase_space_symmetry_closure.json"


def _module():
    spec = importlib.util.spec_from_file_location("p101_closure", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_geometry_and_deformation_symmetry_are_verified_from_tracked_source():
    module = _module()
    proof = module._geometry_proof()
    assert proof["basis_relation"] == "M_y @ A0 = A0 @ S_swap"
    assert proof["inclusion_centers_individually_invariant"] is True
    assert proof["real_scalar_material_distribution"] is True
    assert all(proof["deformation_commutes_with_mirror"].values())
    assert proof["circular_s0_and_affine_elliptical_symmetry"] is True


def test_combined_antiunitary_action_and_curvature_parity_are_explicit():
    module = _module()
    proof = module._antiunitary_proof()
    assert proof["coordinate_action"]["combined_Theta_M_y_T"] == "(q_x,q_y,s) -> (-q_x,q_y,s)"
    assert proof["q_x_center_is_zero"] is True
    assert proof["qy_s_diamond_center_line_Theta_invariant"] is True
    assert proof["omega_qy_s_symmetry_forced_zero"] is True
    assert proof["omega_qx_s_symmetry_allowed"] is True
    assert proof["isolated_rank_one_conclusion"] == "Omega_qy_s(q_x=0)=0 exactly"


def test_trajectory_readiness_does_not_invent_missing_inputs():
    module = _module()
    readiness = module._trajectory_readiness()
    assert readiness["status"] == "BLOCKED_BY_MISSING_INPUTS"
    assert readiness["missing_input_count"] == len(readiness["missing_inputs"]) == 6
    assert "ordinary_Berry_curvature_Omega_qx_qy" in readiness["missing_inputs"]
    assert "group_velocity_grad_q_frequency" in readiness["missing_inputs"]
    assert readiness["no_defaults_or_zero_substitutions"] is True
    assert readiness["trajectory_executed"] is False


def test_closure_result_exposes_required_top_level_fields():
    module = _module()
    result = module.build_result(module.build_closure())
    required = {
        "mirror_symmetry_certified", "time_reversal_certified", "combined_antiunitary_certified",
        "rank1_isolation_certified", "omega_qy_s_symmetry_forced_zero", "omega_qx_s_symmetry_allowed",
        "qy_numerical_residual_classification", "qx_s_1e9", "domega_ds_1e9",
        "solver_to_geometric_ratio_qx_s", "solver_to_geometric_ratio_domega_ds",
        "trajectory_readiness_status", "trajectory_missing_input_count",
        "trajectory_missing_inputs", "trajectory_available_inputs",
    }
    assert required <= set(result)
    assert result["scientific_acceptance_status"] == "PASS"
    assert result["omega_qy_s_symmetry_forced_zero"] is True
    assert result["trajectory_readiness_status"] == "BLOCKED_BY_MISSING_INPUTS"
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0
    assert result["mpb_execution"] is False
    assert result["field_payload_retained"] is False


def test_committed_ledger_has_machine_readable_premises_and_readiness():
    module = _module()
    ledger = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert ledger["schema"] == "mephc-local-affine-p101-symmetry-closure-ledger-v1"
    assert all(item["status"] == "PASS" for item in ledger["symmetry_premises"])
    assert ledger["antiunitary_proof"]["omega_qy_s_symmetry_forced_zero"] is True
    assert ledger["trajectory_readiness"]["status"] == "BLOCKED_BY_MISSING_INPUTS"
    assert ledger["trajectory_readiness"]["missing_input_count"] == 6
    assert module.ARTIFACT_PATH == ARTIFACT


def test_entrypoint_compiles_and_does_not_execute_trajectory_or_solver():
    module = _module()
    assert module is not None
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in ("import meep", "from meep", "LocalAffineStateProvider", "MPBLiveSpectralProvider", "provider.solve", "trajectory("):
        assert forbidden not in source
    for required in ("M_y", "Omega_qy_s(q_x=0)=0 exactly", "BLOCKED_BY_MISSING_INPUTS", "mephc/phase_space_dynamics.py"):
        assert required in source
