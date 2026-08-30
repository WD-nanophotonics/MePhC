from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "third_scale_solver_precision_solver_free_comparison.py"


def _module():
    spec = importlib.util.spec_from_file_location("p100_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(module):
    baseline = {
        "omega_qx_s": 1.0, "omega_qy_s": 2.0, "domega_ds": 3.0,
        "forward_wilson_phase_baseline_qx": 0.1, "forward_wilson_phase_baseline_qy": 0.2,
        "minimum_link_singular_value_baseline_qx": 0.9, "minimum_link_singular_value_baseline_qy": 0.8,
        "maximum_link_principal_angle_baseline_qx": 0.3, "maximum_link_principal_angle_baseline_qy": 0.4,
    }
    tight = {
        "omega_qx_s": 1.5, "omega_qy_s": 2.0, "domega_ds": 4.0,
        "forward_wilson_phase_tight_qx": 0.15, "forward_wilson_phase_tight_qy": 0.25,
        "minimum_link_singular_value_tight_qx": 0.7, "minimum_link_singular_value_tight_qy": 0.6,
        "maximum_link_principal_angle_tight_qx": 0.5, "maximum_link_principal_angle_tight_qy": 0.6,
    }
    return {
        "schema": module.RESULT_SCHEMA, "baseline": baseline, "tight": tight,
        "solver_precision_absolute_difference": {"qx_s": 0.5, "qy_s": 0.0, "domega_ds": 1.0},
        "solver_precision_symmetric_relative_difference": {"qx_s": 2 / 2.5, "qy_s": 0.0, "domega_ds": 2 / 7},
        "solver_sensitivity_to_geometric_refinement_ratio": {"qx_s": 10.0, "qy_s": 0.0, "domega_ds": 20.0},
        "statewise_infidelity": {"STATE_14": 0.01, "STATE_15": 0.03},
        "frequency_difference_absolute": {"STATE_14": 0.2, "STATE_15": 0.4},
    }


def test_direct_comparison_has_only_three_exact_orderings():
    module = _module()
    assert module._direct_comparison(1.0, 2.0) == "SMALLER"
    assert module._direct_comparison(2.0, 2.0) == "EQUAL"
    assert module._direct_comparison(3.0, 2.0) == "LARGER"


def test_projection_flattens_decisive_scalars_and_phase_ratios():
    module = _module()
    result = module.project_result_scalars(_result(module))
    assert result["baseline_omega_qx_s"] == 1.0
    assert result["tight_omega_qx_s"] == 1.5
    assert result["solver_abs_delta_qx_s"] == 0.5
    assert abs(result["solver_abs_delta_forward_phase_qx"] - 0.05) < 1e-15
    assert result["solver_relative_delta_qy_s"] == 0.0
    assert result["solver_vs_geometric_qx_s"] == "LARGER"
    assert abs(result["solver_phase_delta_to_baseline_abs_qx"] - 0.5) < 1e-15
    assert abs(result["solver_phase_delta_to_baseline_abs_qy"] - 0.25) < 1e-15


def test_projection_identifies_maximum_infidelity_and_frequency_states():
    module = _module()
    result = module.project_result_scalars(_result(module))
    assert result["maximum_infidelity_state_id"] == "STATE_15"
    assert result["maximum_infidelity_role"] == "STATE_15"
    assert result["maximum_absolute_frequency_difference_state_id"] == "STATE_15"
    assert result["maximum_absolute_frequency_difference_role"] == "STATE_15"


def test_existing_p99_comparison_math_remains_present_and_solver_free():
    module = _module()
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    for required in ("rank1_mixed_curvature", "reverse_mixed_curvature", "fixed_q_frequency_derivative", "1e-12 / abs", "np.vdot"):
        assert required in source
    for forbidden in ("import meep", "from meep", "LocalAffineStateProvider", "MPBLiveSpectralProvider", ".solve("):
        assert forbidden not in source
