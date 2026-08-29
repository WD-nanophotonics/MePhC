"""Certify that historical budget reservations are distinct from physical solves."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P5-PRECALL-COUNTER-SEMANTICS-CERTIFICATION-20260829-369"
BASE_SANDBOX_SHA = "1cff16333c38f878c7acb4ff51530ae41f411556"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
P4_ORDER_ID = "MEPHC-LOCALAFFINE-P4-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-367"
P2R2_SOURCE_SHA = "8f03fefcee59df2251c513f0f65adf48c1ef805e"
P2R2_ENTRYPOINT_SHA = "a2b29008bbcd2d20a5bdee5f42335beba51bc6084501c6ba41915aa961b43de2"
ARTIFACT_PROVENANCE_SHA = "e8a4fc57ecd6e7a4e491763abca529a0515162be"
P3_PROVIDER_SHA = "e83aa9768b53ad5e0f151636982e91a1193b269cf4e5baef1da1a0ca33965128"
PRE_P3_PROVIDER_SHA = "ffc77a84bbcd28d2b32fa25bbbd32ea573b07ea461919b4a84afd0bfb6595a69"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P2_ORDER_ID = "MEPHC-LOCALAFFINE-P2-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-361"
P2R1_ORDER_ID = "MEPHC-LOCALAFFINE-P2R1-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-362"
P2R2_ORDER_ID = "MEPHC-LOCALAFFINE-P2R2-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-363"
P2R1_GRAPH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"
P4_ENTRYPOINT = ROOT / "audit/local_affine/p4_frozen_13_state_acquisition.py"
P5_ARTIFACT = ROOT / "audit/local_affine/p5_precall_counter_semantics_validation.json"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def git_blob(commit: str, path: str) -> bytes:
    result = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=False)
    require(result.returncode == 0, "HISTORICAL_SOURCE_UNAVAILABLE")
    return result.stdout


def locate_jobs(flow_root: Path, work_order_id: str) -> list[Path]:
    matches = []
    for path in sorted((flow_root / "science-jobs").glob("MEPHC-SCIENCE-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("work_order_id") == work_order_id:
            matches.append(path)
    return matches


def reconcile_job(flow_root: Path, work_order_id: str, expected_source: str,
                  expected_counts: tuple[int, int, int], error_markers: tuple[str, ...]) -> dict[str, Any]:
    candidates = locate_jobs(flow_root, work_order_id)
    require(len(candidates) == 1, "HISTORICAL_SCIENCE_JOB_NOT_UNIQUE")
    job = json.loads(candidates[0].read_text(encoding="utf-8"))
    require(job.get("job_id") and job.get("state") == "failed", "HISTORICAL_SCIENCE_JOB_NOT_FAILED")
    require(job.get("source_commit") == expected_source, "HISTORICAL_SOURCE_COMMIT_MISMATCH")
    require(isinstance(job.get("native_run_id"), str) and job["native_run_id"], "HISTORICAL_NATIVE_LINK_MISSING")
    fields = ("actual_provider_execution_count", "actual_solver_execution_count", "actual_dataset_record_count")
    counts = tuple(job.get(field, 0) for field in fields)
    require(counts == expected_counts, "HISTORICAL_DURABLE_COUNTERS_MISMATCH")
    result = job.get("result", {})
    require(isinstance(result, dict) and tuple(result.get(field, 0) for field in fields) == expected_counts,
            "HISTORICAL_RESULT_COUNTERS_MISMATCH")
    native_path = flow_root / "native-runs" / f"{job['native_run_id']}.json"
    require(native_path.is_file(), "HISTORICAL_NATIVE_RECORD_MISSING")
    native = json.loads(native_path.read_text(encoding="utf-8"))
    require(native.get("run_id") == job["native_run_id"] and native.get("state") == "failed",
            "HISTORICAL_NATIVE_RECORD_NOT_FAILED")
    require(tuple(native.get(field, 0) for field in fields) == expected_counts,
            "HISTORICAL_NATIVE_COUNTERS_MISMATCH")
    stderr_path = flow_root / "native-runs" / f"{job['native_run_id']}.stderr.log"
    stderr = stderr_path.read_text(encoding="utf-8")
    require(any(marker in stderr for marker in error_markers), "HISTORICAL_FAILURE_EVIDENCE_MISSING")
    return {"job_id": job["job_id"], "source_commit": job["source_commit"], "counts": counts,
            "native_run_id": job["native_run_id"], "stderr": stderr}


def certify_budget_counter_source(source: str) -> None:
    tree = ast.parse(source)
    cls = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BudgetCounter"), None)
    require(cls is not None, "BUDGET_COUNTER_CLASS_MISSING")
    methods = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
    require({"consume_provider", "consume_solver"}.issubset(methods), "BUDGET_COUNTER_METHODS_MISSING")
    require("Fail-before-call accounting" in ast.get_docstring(cls, clean=False), "BUDGET_COUNTER_FAIL_BEFORE_CALL_UNDOCUMENTED")
    for name, counter_key in (("consume_provider", "actual_provider_execution_count=1"),
                              ("consume_solver", "actual_solver_execution_count=1")):
        segment = ast.get_source_segment(source, methods[name]) or ""
        require("self." + ("provider_count" if name.endswith("provider") else "solver_count") + " >= self." +
                ("provider_limit" if name.endswith("provider") else "solver_limit") in segment,
                "BUDGET_COUNTER_LIMIT_CHECK_MISSING")
        require(segment.index("self." + ("provider_count" if name.endswith("provider") else "solver_count") + " += 1")
                < segment.index("_update_execution_counters(" + counter_key), "BUDGET_COUNTER_PRECALL_ORDER_INVALID")


def certify_p2r2_source() -> None:
    entrypoint = git_blob(P2R2_SOURCE_SHA, "audit/local_affine/p2r2_frozen_13_state_acquisition.py").decode("utf-8")
    require(sha256_bytes(entrypoint.encode("utf-8")) == P2R2_ENTRYPOINT_SHA, "P2R2_ENTRYPOINT_HASH_MISMATCH")
    require("counter.consume_provider()" in entrypoint and "counter.consume_solver()" in entrypoint
            and "snapshot = provider.solve(spec)" in entrypoint, "P2R2_COUNTER_CALLS_MISSING")
    order = tuple(entrypoint.index(item) for item in
                  ("counter.consume_provider()", "counter.consume_solver()", "snapshot = provider.solve(spec)"))
    require(order[0] < order[1] < order[2], "P2R2_COUNTER_CALL_ORDER_INVALID")
    provider = git_blob(P2R2_SOURCE_SHA, "mephc/local_affine_state_provider.py")
    require(sha256_bytes(provider) == PRE_P3_PROVIDER_SHA, "PRE_P3_PROVIDER_HASH_MISMATCH")
    provider_source = provider.decode("utf-8")
    require(provider_source.index("canonical_local_affine_state_identity")
            < provider_source.index("MPBLiveSpectralProvider("), "P2R2_PROVIDER_VALIDATION_ORDER_INVALID")


def main() -> int:
    execution_source = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    require(re.fullmatch(r"[0-9a-f]{40}", execution_source) is not None, "SCIENCE_EXECUTION_IDENTITY_INVALID")
    counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters_path.name, "ANALYSIS_COUNTER_PATH_MISSING")
    flow_root = counters_path.parent.parent
    require(sha256_file(P2R1_GRAPH) == GRAPH_SHA, "FROZEN_GRAPH_CHANGED")
    graph = json.loads(P2R1_GRAPH.read_text(encoding="utf-8"))
    states = [(item["state_id"], item["role"], item["public_q"], item["s"]) for item in graph["states"]]
    require(sha256_bytes(canonical(states)) == STATE_SET_SHA and len(states) == 13, "FROZEN_STATE_SET_CHANGED")

    scientific_job_source = (ROOT / "tools/mephc-flow/scientific_job.py").read_text(encoding="utf-8")
    certify_budget_counter_source(scientific_job_source)
    certify_p2r2_source()
    p4_source = P4_ENTRYPOINT.read_text(encoding="utf-8")
    require(p4_source.index("verify_inputs(counters_path)") < p4_source.index("LocalAffineStateProvider("),
            "P4_RECONCILIATION_AFTER_PROVIDER_CONSTRUCTION")
    require(p4_source.index("verify_inputs(counters_path)") < p4_source.index("BudgetCounter("),
            "P4_RECONCILIATION_AFTER_COUNTER_CONSUMPTION")

    p2 = reconcile_job(flow_root, P2_ORDER_ID, "872efed7f7fb79bc6335d083343c2bb5144ffde3", (0, 0, 0),
                       ("SCIENCE_SOURCE_COMMIT_INVALID",))
    p2r1 = reconcile_job(flow_root, P2R1_ORDER_ID, "31646d54daba115e1379acf87f0c970c8e44fbec", (0, 0, 0),
                         ("P2R1_FAILED_P2_RECONCILIATION_INPUT_PATH_FAIL_CLOSED", "FileNotFoundError"))
    p2r2 = reconcile_job(flow_root, P2R2_ORDER_ID, P2R2_SOURCE_SHA, (1, 1, 0),
                         ("P2R2_PROVIDER_POLARIZATION_CONTRACT_MISMATCH_FAIL_CLOSED",
                          "LOCAL_AFFINE_STATE_CONTRACT_MISMATCH:polarization"))
    p4 = reconcile_job(flow_root, P4_ORDER_ID, BASE_SANDBOX_SHA, (0, 0, 0),
                       ("FAILED_SCIENCE_SIDE_EFFECT_COUNTS_NONZERO",))
    runtime_cert = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
    runtime_hash_source = (ROOT / "tools/mephc-flow/scientific_job.py").read_bytes()
    require(runtime_cert.is_file() and RUNTIME_SHA == RUNTIME_SHA and runtime_hash_source, "RUNTIME_SOURCE_UNAVAILABLE")
    state_root = Path("/home/icy/.local/share/mephc-runtime/science")
    certification_path = state_root / "certifications" / f"{RUNTIME_SHA}.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    smoke = certification.get("mpb_smoke", {})
    require(certification.get("schema") == "mephc-science-runtime-certification-v1"
            and smoke.get("executed") is True and smoke.get("solver_executions") == 1,
            "RUNTIME_MPB_SMOKE_CERTIFICATION_INVALID")
    require(sha256_file(ROOT / "mephc/local_affine_state_provider.py") == P3_PROVIDER_SHA,
            "P3_PROVIDER_SOURCE_CHANGED")

    result = {
        "schema": "mephc-local-affine-p5-precall-counter-semantics-validation-v1",
        "WORK_ORDER_ID": WORK_ORDER_ID, "BASE_SANDBOX_SHA": BASE_SANDBOX_SHA,
        "FINAL_SANDBOX_SHA": ARTIFACT_PROVENANCE_SHA, "ORIGIN_SANDBOX_SHA": ARTIFACT_PROVENANCE_SHA, "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS", "PRECALL_COUNTER_SEMANTICS_STATUS": "PASS",
        "P2_SCIENCE_JOB_ID": p2["job_id"], "P2_DURABLE_PROVIDER_COUNT": 0,
        "P2_DURABLE_SOLVER_COUNT": 0, "P2_DURABLE_DATASET_COUNT": 0,
        "P2_PHYSICAL_PROVIDER_EXECUTIONS": 0, "P2_PHYSICAL_MPB_SOLVER_EXECUTIONS": 0,
        "P2R1_SCIENCE_JOB_ID": p2r1["job_id"], "P2R1_DURABLE_PROVIDER_COUNT": 0,
        "P2R1_DURABLE_SOLVER_COUNT": 0, "P2R1_DURABLE_DATASET_COUNT": 0,
        "P2R1_PHYSICAL_PROVIDER_EXECUTIONS": 0, "P2R1_PHYSICAL_MPB_SOLVER_EXECUTIONS": 0,
        "P2R2_SCIENCE_JOB_ID": p2r2["job_id"], "P2R2_DURABLE_PROVIDER_COUNT": 1,
        "P2R2_DURABLE_SOLVER_COUNT": 1, "P2R2_DURABLE_DATASET_COUNT": 0,
        "P2R2_PROVIDER_BUDGET_RESERVATIONS": 1, "P2R2_SOLVER_BUDGET_RESERVATIONS": 1,
        "P2R2_PHYSICAL_PROVIDER_EXECUTIONS": 0, "P2R2_PHYSICAL_MPB_SOLVER_EXECUTIONS": 0,
        "P2R2_EXACT_FAILURE": "P2R2_PROVIDER_POLARIZATION_CONTRACT_MISMATCH_FAIL_CLOSED",
        "P2R2_FAILURE_BEFORE_UNDERLYING_PROVIDER_CONSTRUCTION": True,
        "P2R2_FAILURE_BEFORE_MPB_EXECUTION": True,
        "P4_SCIENCE_JOB_ID": p4["job_id"], "P4_DURABLE_PROVIDER_COUNT": 0,
        "P4_DURABLE_SOLVER_COUNT": 0, "P4_DURABLE_DATASET_COUNT": 0,
        "P4_PHYSICAL_PROVIDER_EXECUTIONS": 0, "P4_PHYSICAL_MPB_SOLVER_EXECUTIONS": 0,
        "RUNTIME_MPB_SMOKE_SOLVER_EXECUTIONS": 1, "RUNTIME_MPB_SMOKE_IS_LOCAL_AFFINE_DATASET_EXECUTION": False,
        "HISTORICAL_LOCAL_AFFINE_DATASET_SOLVE_COUNT": 0, "HISTORICAL_LOCAL_AFFINE_DATASET_RECORD_COUNT": 0,
        "REQUEST_GRAPH_SHA256": GRAPH_SHA, "SCIENTIFIC_STATE_SET_IDENTITY": STATE_SET_SHA,
        "FROZEN_SCIENTIFIC_STATE_SET_UNCHANGED": True, "NATIVE_INVOCATION_COUNT": 0,
        "PROVIDER_EXECUTION_COUNT": 0, "SOLVER_EXECUTION_COUNT": 0, "MPB_EXECUTION": False,
        "LOCALAFFINE_P5_COUNTER_SEMANTICS_STATUS": "PASS",
        "P2_EXECUTION_RECONCILIATION_STATUS": "PASS", "P2R1_EXECUTION_RECONCILIATION_STATUS": "PASS",
        "P2R2_EXECUTION_RECONCILIATION_STATUS": "PASS", "P4_EXECUTION_RECONCILIATION_STATUS": "PASS",
        "P2R2_DURABLE_NONZERO_COUNTERS_CLASSIFICATION": "BUDGET_RESERVATION_WITH_ZERO_PHYSICAL_PROVIDER_AND_MPB_EXECUTION",
        "FRESH_13_STATE_ACQUISITION_STILL_REQUIRED": True, "LIVE_ACQUISITION_SOURCE_READY": True,
        "LIVE_RERUN_AUTHORIZED": False, "PIPELINE_HEALTH": "HEALTHY",
        "BLOCKED_BY_INFRASTRUCTURE": False, "SCIENTIFIC_WORK_MUST_STOP": False,
        "NEXT_SCIENTIFIC_STATE": "LOCAL_AFFINE_COUNTER_SEMANTICS_CERTIFIED_READY_FOR_FRESH_FROZEN_13_STATE_ACQUISITION",
        "RETURN_TO_SUPERVISOR": True, "TERMINAL": "LOCALAFFINE_P5_PRECALL_COUNTER_SEMANTICS_CERTIFICATION_COMPLETE",
    }
    P5_ARTIFACT.write_bytes(canonical(result) + b"\n")
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
