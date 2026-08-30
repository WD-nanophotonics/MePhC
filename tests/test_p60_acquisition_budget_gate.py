"""No-MPB tests for the corrected 1/13/13 acquisition budget gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_live_acquisition_v2.py"


def load_target():
    spec = importlib.util.spec_from_file_location("p60_budget_target", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_one_thirteen_thirteen_budget_is_accepted_without_mpb():
    target = load_target()
    assert target.validate_acquisition_budgets({"native_invocations": 1, "provider_requests": 13, "solver_executions": 13}) is True


def test_thirteen_thirteen_thirteen_budget_is_rejected_without_mpb():
    target = load_target()
    with pytest.raises(RuntimeError, match="ACQUISITION_BUDGET_NOT_1_13_13"):
        target.validate_acquisition_budgets({"native_invocations": 13, "provider_requests": 13, "solver_executions": 13})
