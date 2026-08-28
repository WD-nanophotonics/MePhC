import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "audit" / "e9f"
DOMAIN = AUDIT / "d1_fr04_source_grid_domain.json"
GRAPH = AUDIT / "d1_fr04_r64_request_graph.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_inputs_match_d3_contract():
    domain = load(DOMAIN)
    graph = load(GRAPH)
    assert domain["retained_cell_count"] == 641
    assert domain["domain_list_sha256"] == "df1e87976df1f435c075485dca2cebd9cf350b32376f8a6d5c61188df447d631"
    assert graph["logical_provider_demand_count"] == 3205
    assert graph["unique_provider_request_count"] == 3205
    assert graph["duplicate_logical_demand_count"] == 0
    assert graph["collision_group_count"] == 0
    assert graph["h_representation"] == "mpb_periodic_h_l2_v1"


def test_graph_requests_are_shared_six_band_identities_without_payloads():
    graph = load(GRAPH)
    expected = {"fr", "resolution", "canonical_k_coordinate_units_1_over_144", "source_model_identity", "provider_configuration_identity", "band_request_configuration"}
    keys = set()
    for demand in graph["logical_demands"]:
        key = demand["request_key"]
        assert set(key) == expected
        assert key["fr"] == 0.4
        assert key["resolution"] == "R64"
        assert demand["canonical_q_rational"]["denominator"] == 144
        keys.add(json.dumps(key, sort_keys=True, separators=(",", ":")))
    assert len(keys) == 3205
    text = GRAPH.read_text(encoding="utf-8").lower()
    assert "/home/" not in text
    assert "c:\\" not in text
    assert "payload" not in text
    assert "frequencies" not in text
    assert "berry" not in text


def test_binding_schema_is_bounded_when_present():
    binding = AUDIT / "d3_fr04_r64_acquisition_binding.json"
    if not binding.exists():
        return
    data = load(binding)
    assert data["schema"] == "mephc-e9f-d3-fr04-r64-acquisition-binding-v1"
    assert data["completion_state"] == "COMPLETE"
    assert data["dataset_record_count"] == 3205
    assert data["native_invocation_count"] == 1
    assert data["fresh_provider_execution_count"] == 3205
    assert data["cache_reuse_count"] == 0
