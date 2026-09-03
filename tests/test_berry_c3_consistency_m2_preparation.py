"""M2P tests: fake acquisition only, with no MPB/Meep/provider side effects."""
from __future__ import annotations

import copy
import ast
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m2", ENTRYPOINT)
assert SPEC and SPEC.loader
M2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M2)


def bundle():
    return M2.verify_m1_bundle()


def fake_record(item, *, qualification="QUALIFIED", coordinate=None, observable=1.0):
    semantic = item["semantic_identity"]
    return {
        "record_id": f"live-{item['request_key_sha256']}-{item['repeat_index']}",
        "orbit_id": semantic["orbit_id"],
        "member_index": semantic["member_index"],
        "coordinate": semantic["public_coordinate"] if coordinate is None else coordinate,
        "geometry_id": semantic["geometry_id"],
        "domain_id": semantic["domain_id"],
        "band_identity": "band-1-of-4",
        "subspace_identity": "rank1-withheld",
        "qualification_status": qualification,
        "observable": observable,
    }


def fake_provider(calls, **options):
    def provider(item):
        calls.append((item["request_key_sha256"], item["repeat_index"]))
        if options.get("fail_first") and len(calls) == 1:
            raise RuntimeError("FAKE_PROVIDER_FAILURE")
        return fake_record(item, **options.get("record_options", {}))
    return provider


def test_exact_graph_execution_and_reduction_are_bounded():
    calls = []
    result = M2.run(provider_solve=fake_provider(calls))
    assert len(calls) == 72
    assert len(set(calls)) == 72
    assert result["m1_request_graph_sha256"] == M2.EXPECTED_GRAPH_SHA256
    assert result["graph_node_count"] == 24
    assert result["reused_frozen_record_count"] == 0
    assert result["future_live_request_count"] == 72
    assert result["provider_request_count"] == 72
    assert result["solver_execution_count"] == 72
    assert result["dataset_record_count"] == 72
    assert result["c3_complete_orbit_count"] == 24
    assert result["actual_counts"]["native"] == 0
    plan = M2.derive_plan(bundle())
    assert plan["future_provider_budget"] == 288
    assert plan["future_solver_budget"] == 288


def test_exact_frozen_reuse_removes_only_exact_semantic_node():
    verified = bundle()
    node = verified["graph"]["nodes"][0]
    altered = copy.deepcopy(verified)
    altered["inventory"]["records"].append({"semantic_identity_sha256": M2.digest(node["semantic_identity"])})
    plan = M2.derive_plan(altered)
    assert plan["graph_node_count"] == 24
    assert plan["reused_frozen_record_count"] == 1
    assert plan["future_live_request_count"] == 69


def test_duplicate_and_wrong_graph_keys_fail_closed():
    verified = bundle()
    duplicate = copy.deepcopy(verified["graph"])
    duplicate["nodes"][1]["request_key_sha256"] = duplicate["nodes"][0]["request_key_sha256"]
    with pytest.raises(M2.M2Error, match="M1_DUPLICATE_REQUEST_KEY"):
        M2.derive_plan({**verified, "graph": duplicate})
    wrong_key = copy.deepcopy(verified["graph"])
    wrong_key["nodes"][1]["request_key_sha256"] = "f" * 64
    with pytest.raises(M2.M2Error, match="M1_REQUEST_KEY_HASH_MISMATCH"):
        M2.derive_plan({**verified, "graph": wrong_key})
    wrong = copy.deepcopy(verified["graph"])
    wrong["graph_sha256"] = "0" * 64
    with pytest.raises(M2.M2Error, match="M1_GRAPH_HASH_MISMATCH"):
        M2.verify_graph(wrong)


def test_identity_mismatch_is_reported_without_parameter_retry():
    calls = []
    def provider(item):
        calls.append(item["request_key_sha256"])
        coordinate = [0.0, 0.0] if len(calls) == 1 else None
        return fake_record(item, coordinate=coordinate)
    result = M2.run(provider_solve=provider)
    assert len(calls) == 72
    assert result["c3_inconsistent_orbit_count"] >= 1
    assert result["provider_request_count"] == 72


def test_failed_node_is_preserved_and_not_retried():
    calls = []
    result = M2.run(provider_solve=fake_provider(calls, fail_first=True))
    assert len(calls) == 72
    assert result["failed_request_count"] == 1
    assert result["c3_incomplete_orbit_count"] >= 1


def test_production_failure_stops_after_first_record_and_preserves_message():
    plan = M2.derive_plan(M2.verify_m1_bundle())

    class BrokenProduction:
        fail_fast = True
        provider_count = 0
        solver_count = 0
        dataset_count = 0

        def __call__(self, _item):
            raise TypeError("pattern is not a numeric array")

    execution = M2.execute_injected_plan(plan, BrokenProduction())
    assert len(execution["failures"]) == 1
    assert execution["failures"][0]["exception_message"] == "pattern is not a numeric array"


def test_unqualified_evidence_propagates_fail_closed():
    calls = []
    result = M2.run(provider_solve=fake_provider(calls, record_options={"qualification": "UNQUALIFIED"}))
    assert result["c3_unqualified_orbit_count"] == 24
    assert result["scientific_acceptance_status"] == "FAIL_CLOSED"


def test_compact_success_and_failure_pass_actual_summary_loader(tmp_path):
    calls = []
    success = M2.run(provider_solve=fake_provider(calls))
    result_path = tmp_path / "success.json"
    result_path.write_bytes(M2.canonical(success))
    native_spec = importlib.util.spec_from_file_location("native_result_loader", ROOT / "tools" / "mephc-flow" / "wsl_native_exec.py")
    assert native_spec and native_spec.loader
    native = importlib.util.module_from_spec(native_spec)
    native_spec.loader.exec_module(native)
    summary, artifact, warnings = native.load_result(result_path, M2.RESULT_SCHEMA)
    assert summary["status"] == "PASS"
    assert artifact["json_type"] == "object"
    assert warnings == []
    failure = M2.compact_failure(M2.M2Error("GRAPH_HASH_FAIL"), plan={"graph_node_count": 24, "reused_frozen_record_count": 0, "future_live_request_count": 72})
    failure_path = tmp_path / "failure.json"
    failure_path.write_bytes(M2.canonical(failure))
    failure_summary, _, failure_warnings = native.load_result(failure_path, M2.RESULT_SCHEMA)
    assert failure_summary["status"] == "FAIL_CLOSED"
    assert failure_warnings == []


def test_static_contracts_encode_exact_counts_and_no_source_mutation():
    machine = json.loads((ROOT / "audit" / "berry_c3_consistency" / "m2_machine_execution_contract.json").read_text(encoding="utf-8"))
    projection = json.loads((ROOT / "audit" / "berry_c3_consistency" / "m2_compact_result_projection_contract.json").read_text(encoding="utf-8"))
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert machine["source_entrypoint"] == "audit/berry_c3_consistency/m2_live_c3_acquisition_and_reduction.py"
    assert machine["m1_graph_node_count"] == 24
    assert machine["future_live_request_count"] == 72
    assert machine["future_provider_budget"] == machine["future_solver_budget"] == 288
    assert machine["native_invocation_budget"] == 1
    assert machine["runtime_no_source_mutation"] is True
    assert projection["result_schema"] == M2.RESULT_SCHEMA
    assert "write_text(" not in source and "write_bytes(" in source
    tree = ast.parse(source)
    top_level_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(node.module != "meep" for node in top_level_imports if isinstance(node, ast.ImportFrom))
    assert all(all(alias.name != "meep" for alias in node.names) for node in top_level_imports if isinstance(node, ast.Import))


def test_lab_and_covariant_stencils_have_equal_area_and_rotate():
    semantic = copy.deepcopy(bundle()["graph"]["nodes"][0]["semantic_identity"])
    semantic["solver_configuration"]["stencil"] = "lab_fixed"
    lab, lab_area = M2.ProductionPilot._vertices(semantic)
    semantic["solver_configuration"]["stencil"] = "c3_covariant"
    semantic["member_index"] = 1
    rotated, rotated_area = M2.ProductionPilot._vertices(semantic)
    assert lab_area == pytest.approx(1e-6)
    assert rotated_area == pytest.approx(lab_area)
    assert rotated != lab


def test_command_line_run_constructs_production_adapter(monkeypatch):
    calls = []

    class FakeProduction:
        provider_count = 0
        solver_count = 0
        dataset_count = 0

        def __init__(self, plan):
            self.plan = plan
            calls.append(plan["future_live_request_count"])

        def __call__(self, item):
            self.provider_count += 4
            self.solver_count += 4
            self.dataset_count += 1
            return fake_record(item)

        def finalize(self, expected_count):
            assert expected_count == 72
            return {"dataset_id": "d" * 64, "manifest_sha256": "e" * 64}

    monkeypatch.setattr(M2, "ProductionPilot", FakeProduction)
    result = M2.run()
    assert calls == [72]
    assert result["actual_counts"] == {"native": 1, "provider": 288, "solver": 288, "dataset": 72}
    assert result["dataset_id"] == "d" * 64
