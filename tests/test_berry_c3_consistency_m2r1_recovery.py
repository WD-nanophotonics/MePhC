"""Recovery tests for the pre-provider M2 failure, using a strict fake boundary."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m2r1", ENTRYPOINT)
assert SPEC and SPEC.loader
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)


def fake_record(item):
    semantic = item["semantic_identity"]
    return {
        "record_id": f"m2r1-{item['request_key_sha256']}-{item['repeat_index']}",
        "orbit_id": semantic["orbit_id"],
        "member_index": semantic["member_index"],
        "coordinate": semantic["public_coordinate"],
        "geometry_id": semantic["geometry_id"],
        "domain_id": semantic["domain_id"],
        "band_identity": "band-1-of-4",
        "subspace_identity": "rank1-withheld",
        "qualification_status": "QUALIFIED",
        "observable": 1.0 + semantic["member_index"] * 0.01,
    }


class StrictFakeProduction:
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
        requests = M2.expand_constituent_requests(item)
        assert len(requests) == 4
        for request in requests:
            key = request["constituent_request_key_sha256"]
            assert key not in self.calls
            self.calls.append(key)
        self.records += 1
        return fake_record(item)

    def finalize(self, expected_count):
        assert expected_count == 72
        return {"dataset_id": "a" * 64, "manifest_sha256": "b" * 64}


def test_previous_failure_is_bound_to_explicit_preprovider_metadata():
    assert M2.PREVIOUS_FAILURE_STAGE == "pre_provider_binding"
    assert M2.PREVIOUS_FAILURE_CODE == "PRODUCTION_PROVIDER_BINDING_REQUIRED"


def test_all_72_records_validate_and_expand_to_288_unique_calls():
    bundle = M2.verify_m1_bundle()
    plan = M2.derive_plan(bundle)
    fake = StrictFakeProduction()
    execution = M2.execute_injected_plan(plan, fake)
    assert len(execution["results"]) == 72
    assert execution["provider_count"] == 288
    assert execution["solver_count"] == 288
    assert execution["dataset_count"] == 72
    assert len(fake.calls) == len(set(fake.calls)) == 288
    reduction = M2.reduce_evidence(execution)
    assert reduction["complete_orbit_count"] == 24
    assert reduction["failed_request_count"] == 0


def test_semantic_dimensions_cannot_alias_or_bypass_preprovider_validation():
    item = M2.derive_plan(M2.verify_m1_bundle())["live_requests"][0]
    for mutation, code in (
        (lambda value: value["semantic_identity"].update({"geometry_id": "G99"}), "GRAPH_GEOMETRY_DOMAIN_INVALID"),
        (lambda value: value["semantic_identity"]["solver_configuration"].update({"stencil": "wrong"}), "GRAPH_SOLVER_SETTINGS_INVALID"),
        (lambda value: value.update({"repeat_index": 7}), "GRAPH_REPEAT_IDENTITY_INVALID"),
        (lambda value: value["semantic_identity"].update({"public_coordinate": [0.0, 0.0]}), "GRAPH_REQUEST_KEY_IDENTITY_INVALID"),
    ):
        candidate = copy.deepcopy(item)
        mutation(candidate)
        with pytest.raises(M2.M2Error, match=code):
            M2.expand_constituent_requests(candidate)


def test_cli_main_uses_bound_fake_production_adapter_and_writes_only_result(tmp_path, monkeypatch):
    fake = StrictFakeProduction()

    class BoundFake:
        def __init__(self, _plan):
            self._fake = fake

        @property
        def provider_count(self):
            return self._fake.provider_count

        @property
        def solver_count(self):
            return self._fake.solver_count

        @property
        def dataset_count(self):
            return self._fake.dataset_count

        def __call__(self, item):
            return self._fake(item)

        def finalize(self, expected_count):
            return self._fake.finalize(expected_count)

    monkeypatch.setattr(M2, "ProductionPilot", BoundFake)
    result_path = tmp_path / "m2r1-result.json"
    monkeypatch.setenv("MEPHC_RESULT_PATH", str(result_path))
    assert M2.main() == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["provider_request_count"] == 288
    assert result["solver_execution_count"] == 288
    assert result["dataset_record_count"] == 72
    assert result["native_invocation_count"] == 1
    assert result["previous_failure_code"] == "PRODUCTION_PROVIDER_BINDING_REQUIRED"
    assert len(fake.calls) == 288
