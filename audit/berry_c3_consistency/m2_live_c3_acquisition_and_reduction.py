"""Future M2 C3 acquisition package with a strictly injected live boundary.

M2P itself never invokes a provider or solver.  The future SCIENCE contract
binds ``provider_solve`` to the production adapter after this package has
verified the immutable M1 graph.  Runtime writes are restricted to the result
path supplied by Thin Flow; M1 and frozen evidence are read-only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
M1_DIR = Path(__file__).resolve().parent
GRAPH_PATH = M1_DIR / "m1_native_request_graph.json"
INVENTORY_PATH = M1_DIR / "m1_frozen_record_inventory.json"
BASELINE_PATH = M1_DIR / "m1_c3_orbit_baseline.json"
M1_MANIFEST_PATH = M1_DIR / "m1_manifest.json"
PLAN_PATH = M1_DIR / "PLAN.md"
GOAL_PATH = M1_DIR / "goal_contract_v1.json"
MACHINE_CONTRACT_PATH = M1_DIR / "m2_machine_execution_contract.json"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m2-live-c3-closure-v1"
M1_RESULT_SCHEMA = "mephc-berry-c3-consistency-m1r1-solver-free-preparation-v1"
GRAPH_SCHEMA = "mephc-berry-c3-m1-content-addressed-request-graph-v1"
EXPECTED_GRAPH_SHA256 = "0d461bf439cb5531e134f46a45c52f3b2f2be8d4845db7be32faf5e936b7af0a"
EXPECTED_SOURCE_COMMIT = "56e2bd30fcdd1eccaeb8b9addecb27b7129a9e6c"
M1_CONTRACT_SOURCE_COMMIT = "8c70adabcad979d96e56156634c8348da076d8e8"
REPEAT_COUNT = 3


class M2Error(ValueError):
    """Fail-closed machine-contract or evidence error."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M2Error("M1_ARTIFACT_UNAVAILABLE", str(path)) from exc
    if not isinstance(value, dict):
        raise M2Error("M1_ARTIFACT_NOT_OBJECT", str(path))
    return value


def load_m1_harness():
    spec = importlib.util.spec_from_file_location("berry_c3_m1_harness", M1_DIR / "m1_solver_free_diagnostic_harness.py")
    if spec is None or spec.loader is None:
        raise M2Error("M1_HARNESS_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_graph(graph: Mapping[str, Any]) -> None:
    if graph.get("schema") != GRAPH_SCHEMA or graph.get("graph_sha256") != EXPECTED_GRAPH_SHA256:
        raise M2Error("M1_GRAPH_HASH_MISMATCH")
    harness = load_m1_harness()
    if dict(graph) != harness.build_future_request_graph():
        raise M2Error("M1_GRAPH_SEMANTIC_HASH_MISMATCH")


def verify_m1_bundle() -> dict[str, Any]:
    """Verify the exact published M1 graph and all semantic content hashes."""
    manifest = read_json(M1_MANIFEST_PATH)
    graph = read_json(GRAPH_PATH)
    inventory = read_json(INVENTORY_PATH)
    baseline = read_json(BASELINE_PATH)
    if manifest.get("source_commit") not in (M1_CONTRACT_SOURCE_COMMIT, EXPECTED_SOURCE_COMMIT):
        raise M2Error("M1_SOURCE_COMMIT_MISMATCH")
    verify_graph(graph)
    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        raise M2Error("M1_MANIFEST_HASHES_MISSING")
    for relative, expected in artifact_hashes.items():
        if relative.endswith("m1_manifest.json"):
            continue
        target = ROOT / relative
        if not target.is_file() or digest(target.read_bytes()) != expected:
            raise M2Error("M1_FILE_HASH_MISMATCH", relative)
    evidence_hashes = manifest.get("contract_evidence_hashes", {})
    for relative, expected in evidence_hashes.items():
        target = ROOT / relative
        if not target.is_file() or digest(target.read_bytes()) != expected:
            raise M2Error("M1_AUTHORITY_HASH_MISMATCH", relative)
    if inventory.get("complete_member_evidence") is not False:
        raise M2Error("FROZEN_EVIDENCE_COMPLETENESS_UNEXPECTED")
    if baseline.get("classification") != "INCOMPLETE_EVIDENCE":
        raise M2Error("M1_BASELINE_CLASSIFICATION_UNEXPECTED")
    if len(graph.get("nodes", [])) != 24 or graph.get("expanded_future_request_count") != 72:
        raise M2Error("M1_GRAPH_COUNTS_INVALID")
    return {"manifest": manifest, "graph": graph, "inventory": inventory, "baseline": baseline}


def derive_plan(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Derive exact future demand from verified semantic nodes, not filenames."""
    graph = bundle["graph"]
    inventory = bundle["inventory"]
    nodes = graph["nodes"]
    keys = [node["request_key_sha256"] for node in nodes]
    if len(keys) != len(set(keys)):
        raise M2Error("M1_DUPLICATE_REQUEST_KEY")
    reusable = []
    frozen_semantics = {
        record.get("semantic_identity_sha256")
        for record in inventory.get("records", [])
        if isinstance(record, Mapping) and isinstance(record.get("semantic_identity_sha256"), str)
    }
    for node in nodes:
        if node.get("request_key_sha256") != digest(node.get("semantic_identity")):
            raise M2Error("M1_REQUEST_KEY_HASH_MISMATCH")
        semantic_hash = digest(node["semantic_identity"])
        if semantic_hash in frozen_semantics:
            reusable.append(node)
    live_nodes = [node for node in nodes if node not in reusable]
    live_requests = [
        {"request_key_sha256": node["request_key_sha256"], "semantic_identity": node["semantic_identity"], "repeat_index": repeat}
        for node in live_nodes for repeat in range(REPEAT_COUNT)
    ]
    return {
        "graph_node_count": len(nodes),
        "reused_frozen_record_count": len(reusable),
        "live_semantic_node_count": len(live_nodes),
        "future_live_request_count": len(live_requests),
        "future_provider_budget": len(live_requests),
        "future_solver_budget": len(live_requests),
        "reusable_nodes": reusable,
        "live_requests": live_requests,
    }


def _finite_observable(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise M2Error("LIVE_RESULT_OBSERVABLE_INVALID") from exc
    if not math.isfinite(value):
        raise M2Error("LIVE_RESULT_OBSERVABLE_NONFINITE")
    return value


def execute_injected_plan(
    plan: Mapping[str, Any],
    provider_solve: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    frozen_records: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Execute only exact graph requests; tests inject a transparent fake."""
    if not callable(provider_solve):
        raise M2Error("PROVIDER_CALLBACK_REQUIRED")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in plan["live_requests"]:
        try:
            value = provider_solve(item)
            if not isinstance(value, Mapping):
                raise M2Error("LIVE_RESULT_NOT_OBJECT")
            record = dict(value)
            record["request_key_sha256"] = item["request_key_sha256"]
            record["repeat_index"] = item["repeat_index"]
            semantic = item["semantic_identity"]
            record["_execution_group"] = (semantic["geometry_id"], semantic["solver_configuration"]["deterministic"], semantic["solver_configuration"]["stencil"])
            record["observable"] = _finite_observable(record.get("observable"))
            results.append(record)
        except Exception as exc:  # preserve the exact node and stage without retry
            failures.append({"request_key_sha256": item["request_key_sha256"], "repeat_index": item["repeat_index"], "failed_stage": "provider_or_solver", "failure_code": getattr(exc, "code", type(exc).__name__), "exception_type": type(exc).__name__})
    return {"results": results, "failures": failures, "frozen_records": [dict(item) for item in frozen_records]}


def reduce_evidence(execution: Mapping[str, Any], harness: Any | None = None) -> dict[str, Any]:
    """Reduce each independent repeat without averaging or assigning zeros."""
    harness = harness or load_m1_harness()
    by_repeat: dict[tuple[int, tuple[Any, ...]], list[Mapping[str, Any]]] = {}
    for item in execution.get("results", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("repeat_index"), int):
            raise M2Error("LIVE_RESULT_REPEAT_ID_INVALID")
        record = {key: item[key] for key in harness.RECORD_FIELDS if key in item}
        if len(record) != len(harness.RECORD_FIELDS):
            raise M2Error("LIVE_RESULT_IDENTITY_FIELDS_MISSING")
        group = tuple(item.get("_execution_group", (record["geometry_id"], "unknown", "unknown")))
        by_repeat.setdefault((item["repeat_index"], group), []).append(record)
    repeat_results = []
    for (_repeat, _group), records in sorted(by_repeat.items(), key=lambda item: item[0]):
        repeat_results.append(harness.diagnose_records(records))
    statuses = [item["status"] for result in repeat_results for item in result["orbit_results"]]
    return {
        "repeat_count_observed": len(repeat_results),
        "repeat_results": repeat_results,
        "complete_orbit_count": sum(status == "COMPARABLE_DEFERRED_THRESHOLD" for status in statuses),
        "incomplete_orbit_count": sum(status == "INCOMPLETE_EVIDENCE" for status in statuses),
        "unqualified_orbit_count": sum(status == "UNQUALIFIED" for status in statuses),
        "inconsistent_orbit_count": sum(status == "INCONSISTENT" for status in statuses),
        "failed_request_count": len(execution.get("failures", [])),
    }


def compact_success(plan: Mapping[str, Any], execution: Mapping[str, Any], reduction: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "status": "PASS",
        "scientific_acceptance_status": "PASS" if not execution.get("failures") else "FAIL_CLOSED",
        "m1_request_graph_sha256": EXPECTED_GRAPH_SHA256,
        "graph_node_count": plan["graph_node_count"],
        "reused_frozen_record_count": plan["reused_frozen_record_count"],
        "future_live_request_count": plan["future_live_request_count"],
        "provider_request_count": len(execution.get("results", [])),
        "solver_execution_count": len(execution.get("results", [])),
        "dataset_record_count": len(execution.get("results", [])),
        "c3_complete_orbit_count": reduction["complete_orbit_count"],
        "c3_incomplete_orbit_count": reduction["incomplete_orbit_count"],
        "c3_unqualified_orbit_count": reduction["unqualified_orbit_count"],
        "c3_inconsistent_orbit_count": reduction["inconsistent_orbit_count"],
        "failed_request_count": reduction["failed_request_count"],
        "threshold_status": "THRESHOLD_DEFERRED",
        "actual_counts": {"native": 0, "provider": len(execution.get("results", [])), "solver": len(execution.get("results", [])), "dataset": len(execution.get("results", []))},
    }


def compact_failure(error: M2Error, *, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "status": "FAIL_CLOSED",
        "scientific_acceptance_status": "FAIL_CLOSED",
        "failed_stage": "validation",
        "failure_code": error.code,
        "exception_type": type(error).__name__,
        "m1_request_graph_sha256": EXPECTED_GRAPH_SHA256,
        "graph_node_count": 0 if plan is None else plan["graph_node_count"],
        "reused_frozen_record_count": 0 if plan is None else plan["reused_frozen_record_count"],
        "future_live_request_count": 0 if plan is None else plan["future_live_request_count"],
        "actual_counts": {"native": 0, "provider": 0, "solver": 0, "dataset": 0},
    }


def run(*, provider_solve: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None, frozen_records: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    bundle = verify_m1_bundle()
    plan = derive_plan(bundle)
    if provider_solve is None:
        raise M2Error("PRODUCTION_PROVIDER_BINDING_REQUIRED")
    execution = execute_injected_plan(plan, provider_solve, frozen_records)
    reduction = reduce_evidence(execution)
    return compact_success(plan, execution, reduction)


def write_result(result: Mapping[str, Any]) -> None:
    target = os.environ.get("MEPHC_RESULT_PATH")
    if not target:
        raise M2Error("MEPHC_RESULT_PATH_MISSING")
    Path(target).write_bytes(canonical(dict(result)) + b"\n")


def main() -> int:
    try:
        result = run()
    except M2Error as exc:
        result = compact_failure(exc)
    write_result(result)
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
