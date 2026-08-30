from __future__ import annotations

import copy
import importlib.util
import json
import py_compile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "audit" / "local_affine" / "p86_three_scale_19_state_binding_plan.json"
TARGET = ROOT / "audit" / "local_affine" / "frozen_19_state_three_scale_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p90_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle(plan, *, graph_overrides=None):
    graph_overrides = graph_overrides or {}
    return {
        "datasets": [
            {
                "dataset_id": binding["dataset_id"],
                "manifest_sha256": binding["manifest_sha256"],
                "record_key_sha256": binding["record_key_sha256"],
                "payload_sha256": "a" * 64,
                "payload_size_bytes": 0,
                "identity": {"request_graph_sha256": graph_overrides.get(index, binding["request_graph_sha256"])},
                "payload_file": "payload.bin",
            }
            for index, binding in enumerate(plan["bindings"])
        ]
    }


def test_same_sha256_bytes_canonicalize_only_by_hex_case():
    module = _module()
    uppercase = "ABCD" * 16
    lowercase = uppercase.lower()
    assert module._canonical_sha256_hex(uppercase) == lowercase
    assert module._canonical_sha256_hex(lowercase) == lowercase
    changed = ("0" if lowercase[0] != "0" else "1") + lowercase[1:]
    assert module._canonical_sha256_hex(changed) != lowercase
    for malformed in ("a" * 63, "a" * 65, "g" * 64, None, 123):
        with pytest.raises(ValueError, match="P90_GRAPH_SHA256_HEX_INVALID"):
            module._canonical_sha256_hex(malformed)


def test_all_nineteen_binding_graph_hashes_are_lowercase_tracked_digests():
    module = _module()
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    p64_sha = module._graph_sha(module.P64_GRAPH_PATH)
    p85_sha = module._graph_sha(module.P85_GRAPH_PATH)
    for index, binding in enumerate(plan["bindings"]):
        expected = p64_sha if index < 13 else p85_sha
        assert binding["request_graph_sha256"] == expected
        assert binding["request_graph_sha256"].islower()


def test_p89_state01_case_only_difference_now_passes_descriptor_validation():
    module = _module()
    plan = module.load_binding_plan()
    descriptor_plan = copy.deepcopy(plan)
    descriptor_plan["bindings"][0]["request_graph_sha256"] = plan["bindings"][0]["request_graph_sha256"].upper()
    bundle = _bundle(descriptor_plan)
    assert module.validate_runtime_contract(bundle, descriptor_plan) is None


def test_state01_p85_digest_remains_a_structured_mismatch():
    module = _module()
    plan = module.load_binding_plan()
    with pytest.raises(module.DescriptorGraphMismatchError) as caught:
        module.validate_runtime_contract(_bundle(plan, graph_overrides={0: module._graph_sha(module.P85_GRAPH_PATH)}), plan)
    error = caught.value
    assert error.code == "P86_DESCRIPTOR_GRAPH_MISMATCH"
    assert error.descriptor_index == 0
    assert error.expected_graph_group == "P64_13_STATE"
    assert error.observed_request_graph_source == "descriptor_identity"


def test_state14_p64_digest_remains_a_structured_mismatch():
    module = _module()
    plan = module.load_binding_plan()
    with pytest.raises(module.DescriptorGraphMismatchError) as caught:
        module.validate_runtime_contract(_bundle(plan, graph_overrides={13: module._graph_sha(module.P64_GRAPH_PATH)}), plan)
    error = caught.value
    assert error.code == "P86_DESCRIPTOR_GRAPH_MISMATCH"
    assert error.descriptor_index == 13
    assert error.expected_state_id == "STATE_14"
    assert error.expected_graph_group == "P85_6_STATE"
    assert error.observed_request_graph_source == "descriptor_identity"


def test_reducer_compiles_and_static_guards_remain_solver_free():
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
