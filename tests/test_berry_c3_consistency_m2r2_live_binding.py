"""Focused M2R2 production-boundary tests; all calls are strict fakes."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m2r2", ENTRYPOINT)
assert SPEC and SPEC.loader
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)


def fake_record(item):
    semantic = item["semantic_identity"]
    return {
        "record_id": f"boundary-{item['request_key_sha256']}-{item['repeat_index']}",
        "orbit_id": semantic["orbit_id"],
        "member_index": semantic["member_index"],
        "coordinate": semantic["public_coordinate"],
        "geometry_id": semantic["geometry_id"],
        "domain_id": semantic["domain_id"],
        "band_identity": "band-1-of-4",
        "subspace_identity": "rank1-withheld",
        "qualification_status": "QUALIFIED",
        "observable": 1.0,
    }


class StrictProductionBoundary:
    def __init__(self):
        self.calls = []
        self.records = 0

    @property
    def provider_count(self):
        return len(self.calls)

    @property
    def solver_count(self):
        return len(self.calls)

    @property
    def dataset_count(self):
        return self.records

    def __call__(self, item):
        constituent_requests = M2.expand_constituent_requests(item)
        assert len(constituent_requests) == 4
        for constituent in constituent_requests:
            production_request = M2.build_production_request(item, constituent)
            key = production_request["constituent_request_key_sha256"]
            assert key not in self.calls
            self.calls.append(key)
        self.records += 1
        return fake_record(item)


def test_existing_production_symbol_is_explicitly_bound():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert M2.PRODUCTION_PROVIDER_SYMBOL == "mephc.mpb_energy_spectral_provider.MPBLiveEnergySpectralProvider"
    assert "MPBLiveEnergySpectralProvider" in source
    assert "PRODUCTION_PROVIDER_BINDING_REQUIRED" in source  # retained only as bounded historical metadata


def test_one_record_and_full_pilot_reach_strict_boundary():
    plan = M2.derive_plan(M2.verify_m1_bundle())
    one = plan["live_requests"][0]
    assert len(M2.expand_constituent_requests(one)) == 4
    fake = StrictProductionBoundary()
    execution = M2.execute_injected_plan(plan, fake)
    assert len(execution["results"]) == 72
    assert execution["failures"] == []
    assert execution["provider_count"] == 288
    assert execution["solver_count"] == 288
    assert execution["dataset_count"] == 72
    assert len(fake.calls) == len(set(fake.calls)) == 288
    reduction = M2.reduce_evidence(execution)
    result = M2.compact_success(plan, execution, reduction)
    assert result["production_provider_symbol"] == M2.PRODUCTION_PROVIDER_SYMBOL
    assert result["provider_request_count"] == 288
    assert result["solver_execution_count"] == 288
    assert result["dataset_record_count"] == 72
    assert result["failure_code"] is None


def test_geometry_mode_frame_repeat_member_and_coordinate_stay_distinct():
    plan = M2.derive_plan(M2.verify_m1_bundle())
    requests = [M2.expand_constituent_requests(item) for item in plan["live_requests"]]
    keys = [request["constituent_request_key_sha256"] for group in requests for request in group]
    assert len(keys) == len(set(keys)) == 288
    candidate = copy.deepcopy(plan["live_requests"][0])
    candidate["repeat_index"] = 9
    with pytest.raises(M2.M2Error, match="GRAPH_REPEAT_IDENTITY_INVALID"):
        M2.expand_constituent_requests(candidate)
    candidate = copy.deepcopy(plan["live_requests"][0])
    candidate["semantic_identity"]["solver_configuration"]["stencil"] = "C3_COVARIANT"
    with pytest.raises(M2.M2Error, match="GRAPH_SOLVER_SETTINGS_INVALID"):
        M2.expand_constituent_requests(candidate)


def test_valid_graph_records_never_return_binding_placeholder():
    plan = M2.derive_plan(M2.verify_m1_bundle())
    fake = StrictProductionBoundary()
    execution = M2.execute_injected_plan(plan, fake)
    assert all(failure["failure_code"] != M2.PREVIOUS_FAILURE_CODE for failure in execution["failures"])
    assert len(execution["results"]) == 72
    assert fake.provider_count == 288
