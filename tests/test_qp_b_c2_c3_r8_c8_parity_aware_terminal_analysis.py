from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e9f/qp_b_c2_c3_r8_c8_parity_aware_terminal_analysis.py"


def load():
    spec = importlib.util.spec_from_file_location("r8_c8_analysis", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(module, i: int, j: int, role: str, resolution: str) -> dict:
    return {
        "sample_id": module.sample_id(i, j), "role": role,
        "grid_i": i, "grid_j": j, "terminal_fixed_h_pass": True,
        "terminal_fixed_h_resolution": resolution,
        "terminal_fixed_h_resolution_metric": 0.01,
    }


def test_exact_parity_relation_and_srd() -> None:
    module = load()
    assert module.srd(0.0, 0.0) == 0.0
    assert module.srd(1.0, -1.0) == 2.0
    assert module.relation(2.0, 1.0) == "FINAL_INCREMENT_CONTRACTS"
    assert module.relation(1.0, 2.0) == "FINAL_INCREMENT_EXPANDS"
    assert module.relation(1.0, 1.0) == "FINAL_INCREMENT_EQUAL_NONZERO"
    assert module.relation(0.0, 0.0) == "ALL_ZERO_STABLE"


def test_third_stencil_uses_validated_terminal_resolution_and_exact_counts() -> None:
    module = load()
    samples = [
        sample(module, -10, -3, "CALIBRATION_CONTROL", "R256"),
        sample(module, -34, 9, "CALIBRATION_CONTROL", "R192"),
        sample(module, -6, -1, "STENCIL_DIAGNOSTIC", "R256"),
        sample(module, -34, -16, "POLICY_CHALLENGE", "R192"),
        sample(module, -34, -17, "POLICY_CHALLENGE", "R192"),
        sample(module, -34, 17, "POLICY_CHALLENGE", "R192"),
        sample(module, -5, 0, "POLICY_CHALLENGE", "R256"),
        sample(module, -4, 0, "POLICY_CHALLENGE", "R256"),
    ]
    graph = module.prospective_graph(
        samples, "PROCEED_TO_TERMINAL_RESOLUTION_H_1_288_THIRD_STENCIL_DESIGN"
    )
    assert graph["status"] == "DESIGNED_NOT_EXECUTED"
    assert graph["axis"] == "H_1_288"
    assert graph["logical_demand_count"] == 32
    assert graph["unique_provider_request_count"] == 32
    assert graph["duplicate_count"] == 0
    assert graph["counts_by_resolution"] == {"R192": 16, "R256": 16}
    assert all(item["coordinate"]["denominator"] == 288 for item in graph["logical_demands"])


def test_fail_branch_does_not_design_r288() -> None:
    module = load()
    graph = module.prospective_graph(
        [sample(module, -5, 0, "POLICY_CHALLENGE", "R256")],
        "STOP_FIXED_H_REFINEMENT_METHOD_LIMIT_REACHED",
    )
    assert graph["status"] == "NOT_APPLICABLE"
    assert graph["logical_demand_count"] == 0
    assert graph["axis"] is None


def test_source_has_no_live_execution_or_provider_construction_path() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "build_r8_provider_factory" not in source
    assert "provider_solve" not in source
    assert "run-native" not in source
    assert "subprocess" not in source
