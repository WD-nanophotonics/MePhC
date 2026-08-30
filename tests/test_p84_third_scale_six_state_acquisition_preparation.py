from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import py_compile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "audit" / "local_affine" / "p84_third_scale_6_state_request_graph.json"
ENTRYPOINT = ROOT / "audit" / "local_affine" / "third_scale_6_state_live_acquisition.py"


def _module():
    spec = importlib.util.spec_from_file_location("p84_acquisition", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_graph_has_exact_six_unique_third_scale_states_and_coordinates():
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    assert graph["schema"] == "mephc-local-affine-p84-third-scale-6-state-request-graph-v1"
    assert graph["state_count"] == graph["logical_state_count"] == graph["unique_state_count"] == 6
    assert [item["state_id"] for item in graph["states"]] == [f"STATE_{index:02d}" for index in range(14, 20)]
    assert len({item["state_id"] for item in graph["states"]}) == 6
    assert [(item["role"], item["public_q"], item["s"]) for item in graph["states"]] == [
        ("THIRD_PLUS_QX", [0.00025, -0.6166666666666667], 0.0),
        ("THIRD_MINUS_QX", [-0.00025, -0.6166666666666667], 0.0),
        ("THIRD_PLUS_QY", [0.0, -0.6164166666666667], 0.0),
        ("THIRD_MINUS_QY", [0.0, -0.6169166666666667], 0.0),
        ("THIRD_PLUS_S", [0.0, -0.6166666666666667], 0.005),
        ("THIRD_MINUS_S", [0.0, -0.6166666666666667], -0.005),
    ]


def test_future_budget_contract_is_exactly_one_six_six_and_framework_bound():
    module = _module()
    assert module.validate_acquisition_budgets({"native_invocations": 1, "provider_requests": 6, "solver_executions": 6})
    assert module.validate_framework_budgets({"MEPHC_PROVIDER_REQUEST_BUDGET": "6", "MEPHC_SOLVER_EXECUTION_BUDGET": "6"}) == {"provider_requests": 6, "solver_executions": 6}
    with pytest.raises(RuntimeError, match="ACQUISITION_BUDGET_NOT_1_6_6"):
        module.validate_acquisition_budgets({"native_invocations": 1, "provider_requests": 13, "solver_executions": 13})


def test_record_key_derivation_is_deterministic_and_canonical():
    module = _module()
    key = module.derive_record_key_sha256("MEPHC-FUTURE", "STATE_14", "THIRD_PLUS_QX", (0.00025, -0.6166666666666667), 0.0)
    expected = hashlib.sha256(module.canonical({"work_order_id": "MEPHC-FUTURE", "state_id": "STATE_14", "role": "THIRD_PLUS_QX", "public_q": [0.00025, -0.6166666666666667], "s": 0.0})).hexdigest()
    assert key == expected
    assert key == module.derive_record_key_sha256("MEPHC-FUTURE", "STATE_14", "THIRD_PLUS_QX", [0.00025, -0.6166666666666667], 0.0)


def test_dataset_completeness_is_independent_from_rank1_qualification():
    module = _module()
    assert module.rank1_preflight(0.05) is True
    assert module.rank1_preflight(0.049999) is False
    assert module.solver_free_reduction_ready(6, False) is False
    assert module.solver_free_reduction_ready(6, True) is True
    assert module.solver_free_reduction_ready(5, True) is False


def test_normalization_is_json_safe_and_fail_closed_for_unsupported_values():
    module = _module()
    value = {"tuple": (64, 64), "nested": {"flag": True, "none": None}, "float": 0.5}
    normalized = module.normalize_json(value)
    assert normalized == {"tuple": [64, 64], "nested": {"flag": True, "none": None}, "float": 0.5}
    assert value["tuple"] == (64, 64)
    with pytest.raises(TypeError, match="UNSAFE_JSON_VALUE"):
        module.normalize_json(float("nan"))
    with pytest.raises(TypeError, match="UNSAFE_JSON_VALUE"):
        module.normalize_json(object())


def test_entrypoint_compiles_and_uses_active_codec_current_runtime_and_future_only_graph():
    py_compile.compile(str(ENTRYPOINT), doraise=True)
    source = ENTRYPOINT.read_text(encoding="utf-8")
    for required in (
        "LocalAffineStateProvider", "local_affine_reference_cell_contract", "encode_snapshot",
        "MEPHC_INPUT_BUNDLE", "MEPHC_RESULT_PATH", "MEPHC_SOURCE_COMMIT",
        "p84_third_scale_6_state_request_graph.json",
    ):
        assert required in source
    for forbidden in (
        "p2_frozen_13_state_request_graph", "p66_p64_v2_binding_plan", "archive",
        "legacy",
    ):
        assert forbidden not in source.lower()


def test_static_source_preserves_future_six_record_and_no_side_effect_contract():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "records: list[dict[str, Any]] = []" in source
    assert "store.finalize(6" in source
    assert "counter.consume_provider()" in source and "counter.consume_solver()" in source
    assert '"native_invocation_count": 1' in source
