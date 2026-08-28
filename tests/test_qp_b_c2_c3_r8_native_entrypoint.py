from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"


def load():
    path = AUDIT / "qp_b_c2_c3_r8_locked_set_native.py"
    spec = importlib.util.spec_from_file_location("r8_fixed_entrypoint", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph():
    with (AUDIT / "qp_b_c2_c3_r8_global_provider_request_graph.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def test_zero_arguments_are_the_only_entrypoint_contract():
    entrypoint = load()
    entrypoint.validate_arguments([])
    with pytest.raises(entrypoint.EntrypointError, match="ARGUMENTS_FORBIDDEN"):
        entrypoint.validate_arguments(["extra"])


def test_argument_rejection_happens_before_provider_initialization():
    entrypoint = load()
    called = []

    def provider(_request):
        called.append(True)
        return {}

    with pytest.raises(entrypoint.EntrypointError, match="ARGUMENTS_FORBIDDEN"):
        entrypoint.run(["--injected"], provider_solve=provider, checkpoint={})
    assert called == []


def test_frozen_graph_is_verified_independently():
    entrypoint = load()
    verified = entrypoint.verify_graph(graph())
    assert verified["logical_provider_demand_count"] == 216
    assert verified["unique_provider_request_count"] == 210
    assert verified["duplicate_logical_demand_count"] == 6
    assert verified["unique_request_count_by_resolution"] == {"R96": 70, "R128": 70, "R160": 70}


def test_graph_count_and_sample_mutations_fail_closed():
    entrypoint = load()
    bad_count = graph()
    bad_count["logical_demands"] = bad_count["logical_demands"][:-1]
    with pytest.raises(entrypoint.EntrypointError, match="LOGICAL_DEMAND_COUNT_INVALID"):
        entrypoint.verify_graph(bad_count)
    bad_sample = graph()
    bad_sample["logical_demands"][0]["sample_grid"] = {"i": 999, "j": 999}
    with pytest.raises(entrypoint.EntrypointError, match="LOCKED_SAMPLE_SET_INVALID"):
        entrypoint.verify_graph(bad_sample)


def test_request_key_mutation_fails_closed():
    entrypoint = load()
    bad = graph()
    bad["logical_demands"][0]["request_key"]["source_model_identity"] = "MUTATED"
    with pytest.raises(entrypoint.EntrypointError, match="LISTED_UNIQUE_KEYS_INVALID"):
        entrypoint.verify_graph(bad)


def test_provider_plan_is_exactly_the_global_unique_set():
    entrypoint = load()
    plan = entrypoint.build_provider_plan(graph())
    assert len(plan) == 210
    assert len({entrypoint.canonical_key(item["request_key"]) for item in plan}) == 210


def test_duplicate_requests_are_executed_once_and_checkpoint_reuses_exact_keys():
    entrypoint = load()
    plan = entrypoint.build_provider_plan(graph())[:2]
    calls = []

    def provider(request):
        calls.append(request)
        return {"ok": True}

    key = entrypoint.canonical_key(plan[0]["request_key"])
    results, reused, fresh = entrypoint.execute_unique_requests(
        plan, provider, checkpoint={key: {"cached": True}}
    )
    assert len(results) == 2
    assert reused == 1
    assert fresh == 1
    assert len(calls) == 1


def test_caps_and_no_adaptive_expansion_are_hard_fail_closed():
    entrypoint = load()
    plan = entrypoint.build_provider_plan(graph())
    extra = {
        "request_key": {
            "fr": 0,
            "grid_i": 9999,
            "grid_j": 0,
            "role": "CAP_PROBE",
        },
        "logical_demand_refs": [],
    }
    with pytest.raises(entrypoint.EntrypointError, match="CAP_EXCEEDED"):
        entrypoint.execute_unique_requests(plan + [extra], lambda _request: {})
    assert len(plan) == 210
    assert entrypoint.MAX_UNIQUE_REQUESTS == 210
    assert entrypoint.MAX_FRESH_SOLVER_EXECUTIONS == 210


def test_future_output_contract_and_zero_execution_test_contract():
    entrypoint = load()
    contract = json.loads((AUDIT / "qp_b_c2_c3_r8_native_entrypoint_contract.json").read_text(encoding="utf-8"))
    output = {field: None for field in contract["output_contract_fields"]}
    entrypoint.validate_output_contract(output)
    assert contract["future_native_invocation_budget"] == 1
    assert contract["future_provider_request_budget"] == 210
    assert contract["future_solver_execution_budget"] == 210
    assert contract["future_retry_budget"] == 0
    assert contract["native_solver_execution_in_tests"] == 0
    assert contract["mpb_execution_in_tests"] is False
