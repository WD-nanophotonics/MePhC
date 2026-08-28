import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"
DOMAIN = AUDIT / "d1_fr04_source_grid_domain.json"
GRAPH = AUDIT / "d1_fr04_r64_request_graph.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def implementation():
    path = AUDIT / "d1_fr04_source_grid_preflight.py"
    spec = importlib.util.spec_from_file_location("d1_fr04_source_grid_preflight_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_domain_is_geometry_bound_and_uses_exact_source_weights():
    if not DOMAIN.exists():
        module = implementation()
        geometry = module.load_geometry()
        cells = module.retained_cells(geometry)
        assert cells
        assert all(cell["weight_q2_exact"] == "1/1296" for cell in cells)
        return
    data = load(DOMAIN)
    assert data["schema"] == "mephc-e9f-d1-fr04-source-grid-domain-v1"
    assert data["work_order_id"] == "MEPHC-E9F-D1-FR04-SOURCE-GRID-PREFLIGHT-20260828-321"
    assert data["fr"] == 0.4
    assert data["resolution"] == "R64"
    assert data["estimator"] == "SOURCE_GRID_MIDPOINT_V1"
    assert data["weight_q2_exact"] == "1/1296"
    assert data["total_weight_q2"] == data["retained_cell_count"] / 1296.0
    assert data["domain_list_sha256"] == hashlib.sha256(canonical(data["retained_cells"])).hexdigest()
    assert data["source_anchors_used_for_selection"] is False
    assert data["source_anchors_used_for_fitting"] is False
    assert data["source_anchors_used_for_qualification"] is False
    assert all(cell["weight_q2_exact"] == "1/1296" for cell in data["retained_cells"])


def test_graph_is_complete_fine_bundle_and_mechanically_deduplicated():
    if not GRAPH.exists() or not DOMAIN.exists():
        module = implementation()
        geometry = module.load_geometry()
        graph = module.build_graph(module.retained_cells(geometry))
        assert graph["logical_provider_demand_count"] == 5 * len(module.retained_cells(geometry))
        assert graph["stage_a_status"] == "PASS"
        return
    data = load(GRAPH)
    domain = load(DOMAIN)
    assert data["schema"] == "mephc-e9f-d1-fr04-r64-request-graph-v1"
    assert data["h_representation"] == "mpb_periodic_h_l2_v1"
    assert data["source_model_identity"] == "FROZEN_E9_SOURCE_MODEL"
    assert data["provider_configuration_identity"] == "FROZEN_QP_B_PROVIDER_CONFIGURATION"
    assert data["band_request_configuration"] == "FROZEN_QP_B_LOCKED_BAND_REQUEST"
    assert data["logical_provider_demand_count"] == 5 * domain["retained_cell_count"]
    assert data["prospective_r64_provider_request_budget"] == data["unique_provider_request_count"]
    assert data["prospective_r64_solver_execution_budget"] == data["unique_provider_request_count"]
    assert data["prospective_native_invocation_budget"] == 1
    assert len(data["logical_demands"]) == data["logical_provider_demand_count"]
    assert len(data["unique_provider_requests"]) == data["unique_provider_request_count"]
    assert data["duplicate_logical_demand_count"] == data["logical_provider_demand_count"] - data["unique_provider_request_count"]
    assert data["collision_group_count"] == sum(len(item["logical_demand_refs"]) > 1 for item in data["unique_provider_requests"])
    for demand in data["logical_demands"]:
        key = demand["request_key"]
        assert set(key) == {"fr", "resolution", "canonical_k_coordinate_units_1_over_144", "source_model_identity", "provider_configuration_identity", "band_request_configuration"}
        assert key["fr"] == 0.4
        assert key["resolution"] == "R64"
        assert demand["canonical_q_rational"]["denominator"] == 144
    assert data["native_execution_started"] is False
    assert data["provider_construction_started"] is False
    assert data["solver_execution_started"] is False
    assert data["mpb_execution_started"] is False


def test_graph_contains_no_payloads_or_private_paths():
    text = GRAPH.read_text(encoding="utf-8") if GRAPH.exists() else (AUDIT / "d1_fr04_source_grid_preflight.py").read_text(encoding="utf-8")
    assert "/home/" not in text
    assert "C:\\" not in text
    if GRAPH.exists():
        assert "payload" not in text.lower()
        assert "frequency" not in text.lower()
        assert "berry" not in text.lower()
