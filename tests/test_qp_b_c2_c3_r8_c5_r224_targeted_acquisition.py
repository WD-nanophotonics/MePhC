from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audit" / "e9f"
SCRIPT = AUDIT / "qp_b_c2_c3_r8_c5_r224_targeted_acquisition.py"
GRAPH = AUDIT / "qp_b_c2_c3_r8_c5_r224_request_graph.json"


def load():
    spec = importlib.util.spec_from_file_location("r224_targeted_acquisition", SCRIPT)
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
        "unique_request_count_by_resolution": {"R224": 35},
        "native_solver_execution": False,
        "mpb_execution": False,
    }
    assert {tuple(item["sample_grid"][key] for key in ("i", "j")) for item in graph["logical_demands"]} == {
        (-10, -3), (-6, -1), (-5, 0), (-4, 0)
    }
    assert len(graph["logical_demands"]) == 36
    assert len(graph["unique_provider_requests"]) == 35
    assert graph["duplicate_relations"] == [{
        "resolution": "R224",
        "left_pair": "fr=0;grid_i=-5;grid_j=0;role=POLICY_CHALLENGE;resolution=R224",
        "left_point": "H72_PLUS_X",
        "right_pair": "fr=0;grid_i=-4;grid_j=0;role=POLICY_CHALLENGE;resolution=R224",
        "right_point": "H72_MINUS_X",
    }]


def test_graph_hash_and_source_binding_targets_are_stable():
    module = load()
    assert hashlib.sha256(GRAPH.read_bytes().rstrip()).hexdigest() == hashlib.sha256(module.canonical(module.make_graph())).hexdigest()
    assert module.WORK_ORDER_ID == "MEPHC-E9F-C2-QP-B-C2-C3-R8-C5-A1-20260828-312"
    assert module.DECLARED_WORK_ORDER_BASE_COMMIT == "16cb4668833dd612d688aecb9509206e93ddf1b3"
    assert module.PARENT_DATASET_ID == "446ad69a302c9eb3524b67fe2127701030f62986dd1ccc570e3b0830a3dc488c"
    assert module.PARENT_RECONCILIATION_SHA256 == "bc49f09faaaa2eeb27d47e41f846361218d40d32f8cebf3078dfe3db1261ba10"
    assert module.FIXED_H_RESULT_SHA256 == "d07e2d2962ce7283098a70ee70444c406309b6581f1be4fd4407d01de55443df"


def test_arguments_and_injected_execution_requirements_fail_closed():
    module = load()
    with pytest.raises(module.EntrypointError, match="ENTRYPOINT_ARGUMENTS_FORBIDDEN"):
        module.validate_arguments(("unexpected",))
    with pytest.raises(module.EntrypointError, match="CALLER_RUNTIME_INJECTION_INCOMPLETE"):
        module.run((), provider_solve=lambda _: None)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "certified_execution_source_commit" in source
    assert "EXISTING_R224_STATE_RECONCILIATION_REQUIRED" in source
    assert "NATIVE_RETRY" not in source
