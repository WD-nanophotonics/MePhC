import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"

def load():
    with (AUDIT / "qp_b_c2_c3_r8_global_provider_request_graph.json").open(encoding="utf-8") as f:
        return json.load(f)

def test_graph_counts_and_rational_keys():
    data = load()
    assert data["stage_a_status"] == "PASS"
    assert data["global_unique_provider_request_count"] == 210
    assert data["duplicate_logical_demand_count"] == 6
    assert data["unique_request_count_by_resolution"] == {"R96": 70, "R128": 70, "R160": 70}
    assert len(data["logical_demands"]) == 216
    assert len(data["unique_provider_requests"]) == 210
    for demand in data["logical_demands"]:
        key = demand["request_key"]
        assert set(key) == {"fr","resolution","canonical_k_coordinate_units_1_over_144","source_model_identity","provider_configuration_identity","band_request_configuration"}
        assert demand["canonical_q_rational"]["denominator"] == 144
    assert data["cross_resolution_deduplication_allowed"] is False

def test_only_expected_within_resolution_collisions_exist():
    data = load()
    collisions = [item for item in data["unique_provider_requests"] if len(item["logical_demand_refs"]) > 1]
    assert len(collisions) == 6
    assert all(len(item["logical_demand_refs"]) == 2 for item in collisions)
    assert data["mechanically_verified"]["additional_exact_collisions"] == 0
    assert data["mechanically_verified"]["all_solver_relevant_keys_equal_for_collisions"] is True

def test_graph_is_not_native_or_mpb_execution():
    data = load()
    assert data["native_execution_started"] is False
    assert data["mpb_execution_started"] is False

def test_no_host_paths_or_large_payloads():
    text = (AUDIT / "qp_b_c2_c3_r8_global_provider_request_graph.json").read_text(encoding="utf-8")
    assert "/home/" not in text
    assert "C:\\" not in text
    assert "raw_payload" not in text.lower()
