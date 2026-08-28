from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audit" / "e9f"
SCRIPT = AUDIT / "qp_b_c2_c3_r8_c3_r192_acquisition.py"
GRAPH = AUDIT / "qp_b_c2_c3_r8_c3_r192_request_graph.json"


def load():
    spec = importlib.util.spec_from_file_location("r192_acquisition", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph():
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def test_zero_argument_contract_and_graph_generation_are_solver_free():
    entrypoint = load()
    entrypoint.validate_arguments([])
    with pytest.raises(entrypoint.EntrypointError, match="ARGUMENTS_FORBIDDEN"):
        entrypoint.validate_arguments(["extra"])
    assert entrypoint.make_graph() == graph()


def test_exact_r192_graph_counts_and_scope():
    entrypoint = load()
    verified = entrypoint.verify_graph(graph())
    assert verified == {
        "logical_provider_demand_count": 72,
        "unique_provider_request_count": 70,
        "duplicate_logical_demand_count": 2,
        "unique_request_count_by_resolution": {"R192": 70},
        "native_solver_execution": False,
        "mpb_execution": False,
    }
    assert len(graph()["logical_demands"]) == 72
    assert len(graph()["unique_provider_requests"]) == 70
    assert {tuple(item["sample_grid"][key] for key in ("i", "j")) for item in graph()["logical_demands"]} == {
        (-10, -3), (-34, 9), (-6, -1), (-34, -16),
        (-34, -17), (-34, 17), (-5, 0), (-4, 0),
    }


def test_only_two_preregistered_exact_collisions_exist():
    entrypoint = load()
    data = graph()
    collisions = []
    derived = {}
    for demand in data["logical_demands"]:
        key = entrypoint.canonical_key(demand["request_key"])
        derived.setdefault(key, []).append((demand["pair_id"], demand["point"]))
    collisions = [refs for refs in derived.values() if len(refs) > 1]
    assert len(collisions) == 2
    assert {tuple(item for ref in sorted(refs) for item in ref) for refs in collisions} == {
        ("fr=0;grid_i=-34;grid_j=-16;role=POLICY_CHALLENGE;resolution=R192", "H72_MINUS_Y",
         "fr=0;grid_i=-34;grid_j=-17;role=POLICY_CHALLENGE;resolution=R192", "H72_PLUS_Y"),
        ("fr=0;grid_i=-4;grid_j=0;role=POLICY_CHALLENGE;resolution=R192", "H72_MINUS_X",
         "fr=0;grid_i=-5;grid_j=0;role=POLICY_CHALLENGE;resolution=R192", "H72_PLUS_X"),
    }


def test_provider_plan_is_exactly_seventy_unique_keys():
    entrypoint = load()
    plan = entrypoint.build_provider_plan(graph())
    assert len(plan) == 70
    assert len({entrypoint.canonical_key(item["request_key"]) for item in plan}) == 70


def test_argument_rejection_precedes_provider_callback():
    entrypoint = load()
    called = []

    def provider(_request):
        called.append(True)
        return {"ok": True}

    with pytest.raises(entrypoint.EntrypointError, match="ARGUMENTS_FORBIDDEN"):
        entrypoint.run(["--injected"], provider_solve=provider, checkpoint={})
    assert called == []


def test_checkpoint_reuses_only_exact_keys():
    entrypoint = load()
    plan = entrypoint.build_provider_plan(graph())[:2]
    calls = []

    def provider(request):
        calls.append(request)
        return {"ok": True}

    key = entrypoint.canonical_key(plan[0]["request_key"])
    results, reused, fresh = entrypoint.execute_unique_requests(plan, provider, checkpoint={key: {"cached": True}})
    assert len(results) == 2
    assert reused == 1
    assert fresh == 1
    assert len(calls) == 1


def test_caps_and_resolution_variations_fail_closed():
    entrypoint = load()
    plan = entrypoint.build_provider_plan(graph())
    with pytest.raises(entrypoint.EntrypointError, match="CAP_EXCEEDED"):
        entrypoint.execute_unique_requests(plan + [plan[0]], lambda _request: {})
    bad = json.loads(json.dumps(graph()))
    bad["logical_demands"][0]["request_key"]["resolution"] = "R224"
    with pytest.raises(entrypoint.EntrypointError, match="SCOPE_INVALID"):
        entrypoint.verify_graph(bad)


def test_public_graph_has_no_host_paths_or_payloads_and_no_native_execution():
    text = GRAPH.read_text(encoding="utf-8")
    data = graph()
    assert "/home/" not in text
    assert "C:\\" not in text
    assert "raw_payload" not in text.lower()
    assert data["native_execution_started"] is False
    assert data["mpb_execution_started"] is False


def test_future_source_binding_requires_the_certified_execution_checkout(monkeypatch):
    entrypoint = load()
    monkeypatch.delenv("MEPHC_SOURCE_COMMIT", raising=False)
    with pytest.raises(entrypoint.EntrypointError, match="SOURCE_COMMIT_INVALID"):
        entrypoint.certified_execution_source_commit()
    monkeypatch.setenv("MEPHC_SOURCE_COMMIT", "not-a-commit")
    with pytest.raises(entrypoint.EntrypointError, match="SOURCE_COMMIT_INVALID"):
        entrypoint.certified_execution_source_commit()
    monkeypatch.setenv("MEPHC_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setattr(entrypoint.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="b" * 40))
    with pytest.raises(entrypoint.EntrypointError, match="CHECKOUT_MISMATCH"):
        entrypoint.certified_execution_source_commit()


def test_future_source_binding_accepts_only_matching_checkout_head(monkeypatch):
    entrypoint = load()
    commit = "f" * 40
    monkeypatch.setenv("MEPHC_SOURCE_COMMIT", commit)
    monkeypatch.setattr(entrypoint.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=commit))
    assert entrypoint.certified_execution_source_commit() == commit


def test_future_acquisition_does_not_hard_code_execution_provenance():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "MEPHC_SOURCE_COMMIT" in source
    assert "BASE_SOURCE_COMMIT" not in source
