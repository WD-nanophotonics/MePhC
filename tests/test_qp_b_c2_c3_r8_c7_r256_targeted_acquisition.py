from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audit" / "e9f"
SCRIPT = AUDIT / "qp_b_c2_c3_r8_c7_r256_targeted_acquisition.py"
GRAPH = AUDIT / "qp_b_c2_c3_r8_c7_r256_request_graph.json"


def load():
    spec = importlib.util.spec_from_file_location("r256_targeted_acquisition", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_graph_is_exactly_targeted_and_mechanically_verified():
    module = load()
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    assert graph == module.make_graph()
    assert module.verify_graph(graph) == {
        "logical_provider_demand_count": 36,
        "unique_provider_request_count": 35,
        "duplicate_logical_demand_count": 1,
        "unique_request_count_by_resolution": {"R256": 35},
        "native_solver_execution": False,
        "mpb_execution": False,
    }
    assert {tuple(item["sample_grid"][key] for key in ("i", "j")) for item in graph["logical_demands"]} == {
        (-10, -3), (-6, -1), (-5, 0), (-4, 0)
    }
    assert len(graph["logical_demands"]) == 36
    assert len(graph["unique_provider_requests"]) == 35
    assert graph["duplicate_relations"] == [{
        "resolution": "R256",
        "left_pair": "fr=0;grid_i=-5;grid_j=0;role=POLICY_CHALLENGE;resolution=R256",
        "left_point": "H72_PLUS_X",
        "right_pair": "fr=0;grid_i=-4;grid_j=0;role=POLICY_CHALLENGE;resolution=R256",
        "right_point": "H72_MINUS_X",
    }]


def test_graph_hash_and_source_binding_targets_are_stable():
    module = load()
    assert hashlib.sha256(GRAPH.read_bytes().rstrip()).hexdigest() == hashlib.sha256(module.canonical(module.make_graph())).hexdigest()
    assert module.WORK_ORDER_ID == "MEPHC-E9F-C2-QP-B-C2-C3-R8-C7-A1-20260828-315"
    assert module.DECLARED_WORK_ORDER_BASE_COMMIT == "6b65347445f9a6203d3f50148129bf467bec40eb"
    assert module.PARENT_DATASET_ID == "574097e09e10a4dcd951b068eeef89dc208899600656a525bed265e790c168cd"
    assert module.PARENT_RECONCILIATION_SHA256 == "ed26664f48ff001ffc8c4e679c19635922df8c14878aeaae11d75fbbaa5cf2af"
    assert module.FIXED_H_RESULT_SHA256 == "d0d35093560ec9b5acf5b5853d46acbcf46f7ad5219ea11a1b42177f7ad07e85"


def test_arguments_and_injected_execution_requirements_fail_closed():
    module = load()
    with pytest.raises(module.EntrypointError, match="ENTRYPOINT_ARGUMENTS_FORBIDDEN"):
        module.validate_arguments(("unexpected",))
    with pytest.raises(module.EntrypointError, match="CALLER_RUNTIME_INJECTION_INCOMPLETE"):
        module.run((), provider_solve=lambda _: None)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "certified_execution_source_commit" in source
    assert "EXISTING_R256_STATE_RECONCILIATION_REQUIRED" in source
    assert "NATIVE_RETRY" not in source
    assert "verify_parity_precheck" in source
    assert "provider = _provider()" in source
