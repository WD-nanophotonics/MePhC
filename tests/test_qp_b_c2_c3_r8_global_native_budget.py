import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"

def load():
    with (AUDIT / "qp_b_c2_c3_r8_global_provider_request_graph.json").open(encoding="utf-8") as f:
        return json.load(f)

def test_graph_counts_and_rational_keys():
    data = load()
    assert data["work_order_id"] == "MEPHC-E9F-C2-QP-B-C2-C3-R8-D1-20260828-293"
    assert data["base_sandbox_sha"] == "0e5c71f8f07571a5870e151bcffc7bcc6e74588d"
    assert data["expected_main_sha"] == "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
    assert data["stage_a_status"] == "PASS"
    assert data["global_unique_provider_request_count"] == 210
    assert data["duplicate_logical_demand_count"] == 6
    assert data["unique_request_count_by_resolution"] == {"R96": 70, "R128": 70, "R160": 70}
    assert len(data["logical_demands"]) == 216
    assert len(data["unique_provider_requests"]) == 210
    assert {tuple(item["sample_grid"][key] for key in ("i", "j"))
            for item in data["logical_demands"]} == {
        (-10, -3), (-34, 9), (-6, -1), (-34, -16),
        (-34, -17), (-34, 17), (-5, 0), (-4, 0),
    }
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
    assert data["mechanically_verified"]["expected_collision_relations_match"] is True
    assert data["mechanically_verified"]["each_unique_request_is_endpoint_or_center_of_locked_gate"] is True

def test_every_locked_sample_resolution_has_the_complete_two_stencil_bundle():
    data = load()
    groups = {}
    for demand in data["logical_demands"]:
        sample = tuple(demand["sample_grid"][key] for key in ("i", "j"))
        groups.setdefault((sample, demand["resolution"]), set()).add(demand["point"])
    expected_points = {
        "CENTER", "H72_PLUS_X", "H72_MINUS_X", "H72_PLUS_Y", "H72_MINUS_Y",
        "H144_PLUS_X", "H144_MINUS_X", "H144_PLUS_Y", "H144_MINUS_Y",
    }
    assert len(groups) == 24
    assert all(points == expected_points for points in groups.values())

def test_only_the_two_declared_within_resolution_collisions_repeat():
    data = load()
    relations = data["duplicate_relations"]
    assert len(relations) == 6
    for resolution in ("R96", "R128", "R160"):
        same = [item for item in relations if item["resolution"] == resolution]
        assert {(item["left_pair"].split(";role=")[0], item["left_point"],
                 item["right_pair"].split(";role=")[0], item["right_point"])
                for item in same} == {
            ("fr=0;grid_i=-34;grid_j=-17", "H72_PLUS_Y",
             "fr=0;grid_i=-34;grid_j=-16", "H72_MINUS_Y"),
            ("fr=0;grid_i=-5;grid_j=0", "H72_PLUS_X",
             "fr=0;grid_i=-4;grid_j=0", "H72_MINUS_X"),
        }

def test_graph_is_not_native_or_mpb_execution():
    data = load()
    assert data["native_execution_started"] is False
    assert data["mpb_execution_started"] is False

def test_no_host_paths_or_large_payloads():
    text = (AUDIT / "qp_b_c2_c3_r8_global_provider_request_graph.json").read_text(encoding="utf-8")
    assert "/home/" not in text
    assert "C:\\" not in text
    assert "raw_payload" not in text.lower()
