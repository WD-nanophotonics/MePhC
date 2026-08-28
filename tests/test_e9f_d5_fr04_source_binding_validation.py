import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit" / "e9f" / "d5_fr04_source_binding_validation.py"
INCIDENT = ROOT / "audit" / "e9f" / "d5_fr04_source_binding_incident.json"
GRAPH = ROOT / "audit" / "e9f" / "d5_fr04_corrected_r64_request_graph.json"


def load_module():
    try:
        spec = importlib.util.spec_from_file_location("d5_validation_test_module", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except ModuleNotFoundError as exc:
        if exc.name in {"meep", "meep.mpb"}:
            pytest.skip("MPB runtime unavailable in the Windows test environment")
        raise


def test_incident_records_mechanical_misbind_and_preservation():
    value = json.loads(INCIDENT.read_text(encoding="utf-8"))
    assert value["incident_id"] == "SCI-FR04-SOURCE-BIND-001"
    assert value["old_d3_dataset_reuse_authorized"] is False
    assert value["d4_artifacts_immutable_preservation_required"] is True
    assert all(value["mechanical_old_provider_checks"].values())


def test_corrected_graph_is_full_and_coordinate_preserving():
    value = json.loads(GRAPH.read_text(encoding="utf-8"))
    assert value["schema"] == "mephc-e9f-d5-fr04-corrected-r64-request-graph-v1"
    assert value["logical_provider_demand_count"] == 3205
    assert value["unique_provider_request_count"] == 3205
    assert value["duplicate_logical_demand_count"] == 0
    assert value["collision_group_count"] == 0
    assert value["coordinate_set_equal_to_d1"] is True
    keys = [json.dumps(item["request_key"], sort_keys=True, separators=(",", ":")) for item in value["unique_provider_requests"]]
    assert len(set(keys)) == 3205
    assert all(item["request_key"]["analytic_geometry_boundary_digest"] == "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71" for item in value["unique_provider_requests"])


def test_prepare_artifacts_is_idempotent():
    module = load_module()
    incident_before = INCIDENT.read_bytes()
    graph_before = GRAPH.read_bytes()
    module.prepare_artifacts()
    assert INCIDENT.read_bytes() == incident_before
    assert GRAPH.read_bytes() == graph_before
