"""No-MPB tests for P59 reusable acquisition-harness semantics."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_live_acquisition_v2.py"


def load_target():
    spec = importlib.util.spec_from_file_location("p59_target_semantics", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_future_science_budget_is_one_native_thirteen_provider_thirteen_solver():
    source = TARGET.read_text(encoding="utf-8")
    assert "BudgetCounter(13, 13)" in source
    assert '"native_invocation_count": 1' in source
    assert '"provider_execution_count": 13' in source
    assert '"solver_execution_count": 13' in source


def test_rank1_failure_does_not_make_a_complete_dataset_incomplete():
    target = load_target()
    assert target.rank1_preflight(0.049999) is False
    assert target.solver_free_reduction_ready(13, False) is False
    assert target.solver_free_reduction_ready(13, True) is True
    assert target.solver_free_reduction_ready(12, True) is False


def test_structured_scientific_failure_transport_is_nonblocking_and_no_direct_validator_solve():
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert any(isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and node.value.value == 0 for node in ast.walk(tree))
    assert "scientific_acceptance_status" in source
    validator = ROOT / "audit" / "local_affine" / "p58_tracked_13_state_acquisition_entrypoint_preparation.py"
    validator_tree = ast.parse(validator.read_text(encoding="utf-8"))
    direct_solves = [node for node in ast.walk(validator_tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "solve"]
    assert not direct_solves
