"""No-MPB tests for framework-owned P62 budget authorization."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_live_acquisition_v2.py"


def load_target():
    spec = importlib.util.spec_from_file_location("p62_budget_target", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_representative_thin_bundle_needs_no_budget_fields():
    source = TARGET.read_text(encoding="utf-8")
    load_bundle_source = source[source.index("def load_bundle"):source.index("def supplied_namespace")]
    assert "budgets" not in load_bundle_source
    target = load_target()
    assert target.validate_framework_budgets({"MEPHC_PROVIDER_REQUEST_BUDGET": "13", "MEPHC_SOLVER_EXECUTION_BUDGET": "13"}) == {"provider_requests": 13, "solver_executions": 13}


@pytest.mark.parametrize("environment", [
    {},
    {"MEPHC_PROVIDER_REQUEST_BUDGET": "13"},
    {"MEPHC_PROVIDER_REQUEST_BUDGET": "x", "MEPHC_SOLVER_EXECUTION_BUDGET": "13"},
    {"MEPHC_PROVIDER_REQUEST_BUDGET": "12", "MEPHC_SOLVER_EXECUTION_BUDGET": "13"},
    {"MEPHC_PROVIDER_REQUEST_BUDGET": "13", "MEPHC_SOLVER_EXECUTION_BUDGET": "14"},
])
def test_missing_malformed_or_non_thirteen_framework_budget_fails_closed(environment):
    target = load_target()
    with pytest.raises(RuntimeError):
        target.validate_framework_budgets(environment)


def test_native_budget_environment_is_not_a_child_authorization_input():
    source = TARGET.read_text(encoding="utf-8")
    assert "MEPHC_NATIVE_INVOCATION_BUDGET" not in source
    assert "MEPHC_PROVIDER_REQUEST_BUDGET" in source
    assert "MEPHC_SOLVER_EXECUTION_BUDGET" in source
    assert "bundle.get(\"budgets\")" not in source
    assert "bundle.get(\"contract\")" not in source
