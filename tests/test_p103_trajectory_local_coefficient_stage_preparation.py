from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "local_trajectory_coefficient_solver_free_extraction.py"
CONTRACT = ROOT / "audit" / "local_affine" / "p103_local_trajectory_coefficient_contract.json"


def _module():
    spec = importlib.util.spec_from_file_location("p103_extractor", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_has_exact_eight_p64_bindings_and_future_budget():
    module = _module()
    contract = module.load_contract()
    assert len(contract["bindings"]) == 8
    assert [item["state_id"] for item in contract["bindings"]] == ["STATE_02", "STATE_03", "STATE_04", "STATE_05", "STATE_08", "STATE_09", "STATE_10", "STATE_11"]
    assert contract["future_budget"] == {"native_invocations": 1, "provider_requests": 0, "solver_executions": 0}
    assert contract["request_graph_sha256"] == module.graph_sha256() == module.GRAPH_SHA256


def test_contract_keeps_exact_qspace_diamonds_and_coefficients():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    formulas = contract["formulas"]
    assert formulas["primary_signed_area_qxqy"] == 2 * 0.001 * 0.001
    assert formulas["refined_signed_area_qxqy"] == 2 * 0.0005 * 0.0005
    assert formulas["ordinary_curvature"] == "-arg(det(W_CCW))/signed_area_qxqy"
    assert contract["accepted_mixed_coefficients"] == {"Omega_qx_s": -0.19127165880040325, "Omega_qy_s": 0.0, "partial_s_freq": 0.009029604372262634}
    assert contract["trajectory_inputs"]["scenario_parameter_required"] == [
        "local_deformation_profile_or_gradient", "physical_normalization_reference_length_and_wave_speed",
        "trajectory_initial_conditions", "trajectory_integration_controls",
    ]


def test_centered_gradient_extraction_uses_primary_and_refined_steps(monkeypatch):
    module = _module()
    frequencies = {
        "PRIMARY_PLUS_QX": 3.0, "PRIMARY_MINUS_QX": 1.0,
        "PRIMARY_PLUS_QY": 5.0, "PRIMARY_MINUS_QY": 1.0,
        "REFINED_PLUS_QX": 4.0, "REFINED_MINUS_QX": 2.0,
        "REFINED_PLUS_QY": 7.0, "REFINED_MINUS_QY": 1.0,
    }
    states = {role: SimpleNamespace(frequency_for_band=lambda _band, role=role: frequencies[role]) for role in frequencies}
    curvature = {"phase": 0.1, "reverse_phase": -0.1, "omega": 1.0, "reverse_omega": -1.0, "area": 1.0, "minimum_link_singular_value": 0.9, "maximum_link_principal_angle": 0.4}
    monkeypatch.setattr(module, "_q_wilson", lambda _states, _prefix, _step: curvature)
    result = module.extract_coefficients(states)
    assert result["primary_grad_q_freq_x"] == 1000.0
    assert result["primary_grad_q_freq_y"] == 2000.0
    assert result["refined_grad_q_freq_x"] == 2000.0
    assert result["refined_grad_q_freq_y"] == 6000.0
    assert result["Omega_qy_s"] == 0.0
    assert result["trajectory_science_coefficient_status"] == "SCIENCE_DERIVED_AVAILABLE"
    assert result["trajectory_remaining_scenario_parameter_count"] == 4


def test_symmetric_difference_is_null_only_for_exact_zero_denominator():
    module = _module()
    assert module._symmetric_difference(0.0, 0.0) is None
    assert module._symmetric_difference(1.0, 2.0) == 2.0 / 3.0


def test_extractor_is_solver_free_and_future_execution_writes_only_result_path():
    module = _module()
    assert module is not None
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in ("import meep", "from meep", "LocalAffineStateProvider", "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime", ".solve("):
        assert forbidden not in source
    assert "MEPHC_RESULT_PATH" in source
    assert "write_text" not in source
    assert "write_bytes(canonical(result))" in source
