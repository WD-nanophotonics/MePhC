from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "local_dimensionless_trajectory_benchmark.py"
MACHINE = ROOT / "audit" / "local_affine" / "p107_dimensionless_trajectory_machine_execution_contract.json"
BENCHMARK_CONTRACT = ROOT / "audit" / "local_affine" / "p105_dimensionless_trajectory_benchmark_contract.json"


def _module():
    spec = importlib.util.spec_from_file_location("p107_benchmark", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_machine_contract_is_self_sufficient_and_exactly_eight_p64_bindings():
    module = _module()
    contract = json.loads(MACHINE.read_text(encoding="utf-8"))
    assert contract == module.machine_contract()
    assert len(contract["bindings"]) == 8
    assert [item["state_id"] for item in contract["bindings"]] == [
        "STATE_02", "STATE_03", "STATE_04", "STATE_05", "STATE_08", "STATE_09", "STATE_10", "STATE_11"
    ]
    assert contract["budgets"] == {"native_invocations": 1, "provider_requests": 0, "solver_executions": 0, "dataset_writes": 0}
    assert contract["entrypoint"] == "audit/local_affine/local_dimensionless_trajectory_benchmark.py"
    assert contract["result_schema"] == module.RESULT_SCHEMA
    assert contract["no_source_mutation"] is True


def test_benchmark_contract_records_normalization_controls_and_canonical_scenario():
    contract = json.loads(BENCHMARK_CONTRACT.read_text(encoding="utf-8"))
    assert contract["classification"] == "CANONICAL_DIMENSIONLESS_VALIDATION_ONLY_NOT_A_PHYSICAL_DEVICE_PREDICTION"
    assert contract["normalization"]["q"] == "q=a_ref*k_phys/(2*pi)"
    assert contract["normalization"]["omega_phys"] == "omega_phys=2*pi*c_ref*freq_normalized/a_ref"
    assert contract["normalization"]["group_velocity"] == "v_g=c_ref*grad_q(freq_normalized)"
    assert set(contract["controls"]) == {"zero_gradient", "Omega_qx_qy_off", "Omega_qs_off"}
    assert contract["scenario_selection"]["final"]["tau_stop"] == 0.5
    assert contract["future_budget"] == {"native_invocations": 1, "provider_requests": 0, "solver_executions": 0, "dataset_writes": 0}


def test_normalization_has_the_required_two_pi_factors_and_positive_velocity_sign():
    module = _module()
    normalization = module.PhysicalNormalization(2.0, 3.0)
    assert np.allclose(module.q_to_k_phys([1.0, -2.0], normalization), [np.pi, -2.0 * np.pi])
    assert np.allclose(module.k_phys_to_q([np.pi, -2.0 * np.pi], normalization), [1.0, -2.0])
    assert module.normalized_frequency_to_omega(0.25, normalization) == 0.75 * np.pi
    assert np.allclose(module.grad_q_frequency_to_group_velocity([2.0, -1.0], normalization), [6.0, -3.0])


def test_cross_wilson_uses_ccw_cross_order_and_reversal():
    module = _module()
    reference = module.ReferenceCellIdentity(
        "mpb_periodic_h_l2_v1", True, 8, (1, 1), (1.0, 1.0), "supplied final axis order",
        "LAB_CARTESIAN", "MU1_NONMAGNETIC", 1, "same fractional (ix,iy) material coordinates", "test-cell"
    )
    def state(role):
        record = module.ROLE_TO_RECORD[role]
        identity = module.PhaseSpaceStateIdentity(tuple(record[1]), 0.0, tuple(record[1]), ((1.0, 0.0), (0.0, 1.0)), ((1.0, 0.0), (0.0, 1.0)), "test", reference, "test")
        return module.h_state_from_normalized_vectors(identity, np.asarray([1.0 + 0j, 0j]), frequencies=(1.0,), band_indices=(0,))
    states = {role: state(role) for role in module.ROLE_TO_RECORD}
    result = module._cross_wilson(states, "PRIMARY", module.PRIMARY_H_Q)
    assert result["orientation"] == "CCW_CROSS_QX_QY"
    assert result["reversal"] == "PASS"
    assert result["omega_qx_qy"] == 0.0
    assert result["reverse_omega_qx_qy"] == 0.0


def test_production_rhs_trajectory_matches_independent_constant_reference_and_controls():
    module = _module()
    coefficients = module.Coefficients((0.2, -0.3), 0.4, omega_qx_s=0.1, omega_qy_s=-0.2, partial_s_frequency=0.3)
    trajectory = module._trajectory(coefficients, module.SCENARIO)
    analytic = module.analytic_constant_coefficient_reference(coefficients, module.SCENARIO)
    assert np.allclose(trajectory["endpoint"], analytic["rho_endpoint"], rtol=0.0, atol=1e-12)
    zero_gradient = module._trajectory(coefficients, module.SCENARIO, zero_gradient=True)
    assert np.allclose(zero_gradient["endpoint"], [0.1, -0.15], rtol=0.0, atol=1e-12)
    ordinary_off = module._trajectory(coefficients, module.SCENARIO, ordinary=False)
    mixed_off = module._trajectory(coefficients, module.SCENARIO, mixed=False)
    assert not np.array_equal(trajectory["endpoint"], ordinary_off["endpoint"])
    assert not np.array_equal(trajectory["endpoint"], mixed_off["endpoint"])


def test_local_domain_and_result_shape_and_runtime_write_boundary():
    module = _module()
    coefficients = module.Coefficients((0.0, -0.09346940101671863), 0.0)
    trajectory = module._trajectory(coefficients, module.SCENARIO)
    domain = module.local_domain_check(trajectory, module.SCENARIO)
    assert domain["status"] == "PASS"
    assert domain["observed"]["rho_norm"] <= 0.05
    source = TARGET.read_text(encoding="utf-8")
    assert "MEPHC_RESULT_PATH" in source
    assert "write_bytes(canonical(normalize_json(result)))" in source
    assert "import meep" not in source and "LocalAffineStateProvider" not in source and "MPBLiveSpectralProvider" not in source
    py_compile.compile(str(TARGET), doraise=True)


def test_runtime_does_not_write_tracked_contracts():
    module = _module()
    source = TARGET.read_text(encoding="utf-8")
    assert "MACHINE_CONTRACT_PATH.write" not in source
    assert "p105_dimensionless_trajectory_benchmark_contract.json" not in source
    assert module.machine_contract()["future_runtime_mutates_tracked_files"] is False
