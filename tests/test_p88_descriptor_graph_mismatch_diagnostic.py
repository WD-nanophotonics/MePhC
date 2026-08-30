from __future__ import annotations

import copy
import importlib.util
import py_compile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_19_state_three_scale_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p88_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle(module, plan, *, override_graphs=None):
    override_graphs = override_graphs or {}
    descriptors = []
    for index, binding in enumerate(plan["bindings"]):
        descriptors.append({
            "dataset_id": binding["dataset_id"],
            "manifest_sha256": binding["manifest_sha256"],
            "record_key_sha256": binding["record_key_sha256"],
            "payload_sha256": "a" * 64,
            "payload_size_bytes": 0,
            "identity": {"request_graph_sha256": override_graphs.get(index, binding["request_graph_sha256"])},
            "payload_file": "payload.bin",
        })
    return {"datasets": descriptors}


def test_p64_descriptor_carrying_p85_graph_hash_is_structured():
    module = _module()
    plan = module.load_binding_plan()
    p85_sha = module._graph_sha(module.P85_GRAPH_PATH)
    with pytest.raises(module.DescriptorGraphMismatchError) as caught:
        module.validate_runtime_contract(_bundle(module, plan, override_graphs={0: p85_sha}), plan)
    error = caught.value
    assert error.code == "P86_DESCRIPTOR_GRAPH_MISMATCH"
    assert error.descriptor_index == 0
    assert error.binding_index == 0
    assert error.expected_state_id == "STATE_01"
    assert error.expected_role == plan["bindings"][0]["role"]
    assert error.expected_graph_group == "P64_13_STATE"
    assert error.expected_request_graph_sha256 == module._graph_sha(module.P64_GRAPH_PATH)
    assert error.observed_request_graph_sha256 == p85_sha
    assert error.observed_request_graph_source == "descriptor_identity"


def test_p85_descriptor_carrying_p64_graph_hash_is_structured():
    module = _module()
    plan = module.load_binding_plan()
    p64_sha = module._graph_sha(module.P64_GRAPH_PATH)
    with pytest.raises(module.DescriptorGraphMismatchError) as caught:
        module.validate_runtime_contract(_bundle(module, plan, override_graphs={13: p64_sha}), plan)
    error = caught.value
    assert error.descriptor_index == 13
    assert error.binding_index == 13
    assert error.expected_state_id == "STATE_14"
    assert error.expected_role == plan["bindings"][13]["role"]
    assert error.expected_graph_group == "P85_6_STATE"
    assert error.expected_request_graph_sha256 == module._graph_sha(module.P85_GRAPH_PATH)
    assert error.observed_request_graph_sha256 == p64_sha
    assert error.observed_request_graph_source == "descriptor_identity"


def test_binding_plan_graph_mismatch_is_distinguished_from_descriptor_identity():
    module = _module()
    plan = module.load_binding_plan()
    bad_plan = copy.deepcopy(plan)
    bad_plan["bindings"][0]["request_graph_sha256"] = module._graph_sha(module.P85_GRAPH_PATH)
    with pytest.raises(module.DescriptorGraphMismatchError) as caught:
        module.validate_runtime_contract(_bundle(module, plan), bad_plan)
    error = caught.value
    assert error.descriptor_index is None
    assert error.binding_index == 0
    assert error.expected_state_id == "STATE_01"
    assert error.expected_graph_group == "P64_13_STATE"
    assert error.expected_request_graph_sha256 == module._graph_sha(module.P64_GRAPH_PATH)
    assert error.observed_request_graph_source == "binding_plan"


def test_correct_two_graph_nineteen_binding_set_passes_graph_validation():
    module = _module()
    plan = module.load_binding_plan()
    assert module.validate_runtime_contract(_bundle(module, plan), plan) is None


def test_state_ranges_map_only_to_their_named_graphs():
    module = _module()
    plan = module.load_binding_plan()
    p64_sha = module._graph_sha(module.P64_GRAPH_PATH)
    p85_sha = module._graph_sha(module.P85_GRAPH_PATH)
    for index, binding in enumerate(plan["bindings"]):
        expected = module._expected_graph_metadata(binding, index)
        assert expected["group"] == ("P64_13_STATE" if index < 13 else "P85_6_STATE")
        assert expected["sha"] == (p64_sha if index < 13 else p85_sha)


def test_future_result_preserves_bounded_graph_diagnostic_fields():
    module = _module()
    error = module.DescriptorGraphMismatchError(
        descriptor_index=None,
        binding_index=13,
        record_key_sha256=None,
        dataset_id=None,
        expected_state_id=None,
        expected_role=None,
        expected_graph_group="P85_6_STATE",
        expected_request_graph_sha256=module._graph_sha(module.P85_GRAPH_PATH),
        observed_request_graph_sha256=module._graph_sha(module.P64_GRAPH_PATH),
        observed_request_graph_source="binding_plan",
    )
    result = module._future_result("FAIL", failed_stage="bundle-or-reduction", diagnostic=error)
    assert result["schema"] == module.RESULT_SCHEMA
    assert result["scientific_acceptance_status"] == "FAIL"
    assert result["failure_code"] == "P86_DESCRIPTOR_GRAPH_MISMATCH"
    assert result["exception_type"] == "DescriptorGraphMismatchError"
    assert result["descriptor_index"] is None
    assert result["binding_index"] == 13
    assert result["expected_graph_group"] == "P85_6_STATE"
    assert result["observed_request_graph_source"] == "binding_plan"
    assert result["native_invocation_count"] == 1
    assert result["provider_execution_count"] == 0
    assert result["solver_execution_count"] == 0
    assert result["dataset_record_count"] == 0
    assert result["mpb_execution"] is False
    assert result["field_payload_retained"] is False


def test_reducer_and_p88_test_compile_and_static_guards_remain_solver_free():
    module = _module()
    assert module is not None
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
