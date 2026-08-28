from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e9f/qp_b_c2_c3_r8_c6_adaptive_terminal_fixed_h_analysis.py"


def load():
    spec = importlib.util.spec_from_file_location("r8_c6_analysis", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(module, i: int, j: int, role: str, passed: bool = False, resolution: str = "R224") -> dict:
    return {
        "sample_id": module.sample_id(i, j), "role": role, "grid_i": i, "grid_j": j,
        "terminal_fixed_h_contraction_pass": passed,
        "terminal_fixed_h_resolution": resolution if passed else None,
        "terminal_fixed_h_resolution_metric": 0.1 if passed else None,
    }


def test_exact_relation_and_srd() -> None:
    module = load()
    assert module.srd(0.0, 0.0) == 0.0
    assert module.srd(1.0, -1.0) == 2.0
    assert module.relation(2.0, 1.0) == "R224_FINAL_INCREMENT_CONTRACTS"
    assert module.relation(1.0, 2.0) == "R224_FINAL_INCREMENT_EXPANDS"
    assert module.relation(1.0, 1.0) == "R224_FINAL_INCREMENT_EQUAL_NONZERO"
    assert module.relation(0.0, 0.0) == "ALL_ZERO_STABLE"


def test_r256_graph_is_mechanical_and_not_executed() -> None:
    module = load()
    samples = [
        sample(module, -5, 0, "POLICY_CHALLENGE"),
        sample(module, -4, 0, "POLICY_CHALLENGE"),
    ]
    graph = module.prospective_graph(samples, "TARGETED_R256_REQUIRED_BEFORE_THIRD_STENCIL")
    assert graph["status"] == "DESIGNED_NOT_EXECUTED"
    assert graph["axis"] == "R256"
    assert graph["logical_demand_count"] == 18
    assert graph["unique_provider_request_count"] == 17
    assert graph["duplicate_count"] == 1
    assert len(graph["collisions"]) == 1
    assert all(item["resolution"] == "R256" for item in graph["logical_demands"])


def test_h288_graph_uses_each_validated_terminal_resolution() -> None:
    module = load()
    samples = [sample(module, -10, -3, "CALIBRATION_CONTROL", True, "R224")]
    graph = module.prospective_graph(samples, "PROCEED_TO_ADAPTIVE_TERMINAL_H_1_288_THIRD_STENCIL_DESIGN")
    assert graph["axis"] == "H_1_288"
    assert graph["logical_demand_count"] == 4
    assert graph["unique_provider_request_count"] == 4
    assert graph["duplicate_count"] == 0
    assert all(item["coordinate"]["denominator"] == 288 for item in graph["logical_demands"])
    assert all(item["resolution"] == "R224" for item in graph["logical_demands"])


def test_source_has_no_live_execution_or_provider_construction_path() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "build_r8_provider_factory" not in source
    assert "provider_solve" not in source
    assert "run-native" not in source
    assert "subprocess" not in source
