"""Bounded E9F.C.C1 fr=0 source-grid live Berry campaign."""
from __future__ import annotations

import gc
import hashlib
import json
import math
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit.e9c.run_k_kprime_rank1_berry import (
    KPRIME_PUBLIC,
    BANDS,
    build_inputs,
    geometry_inputs,
    make_provider,
    stencil_evidence,
)
from mephc.valley_integration import (
    MEPHC_CLIPPED_RETAINED_DOMAIN_V1,
    SOURCE_GRID_MIDPOINT_V1,
    build_berry_row,
    build_integration_plan,
    build_source_bound_domain,
    reduce_supplied_berry_rows,
    semantic_domain_id,
    validate_integration_plan,
)

WORK_ORDER = "TRILATT-E9F-C-C1-20260824-214"
RESOLUTION = 64
SIDE = 1.0 / 36.0
NUM_BANDS = 6
SOLVER_TOLERANCE = 1e-7
MESH_SIZE = 3
FIXED_SAMPLE_COUNT = 551
KPRIME = (-2.0 / 3.0, 0.0)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def execution_base_is_ancestor(contract: dict) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", contract["execution_code_base_sha"], git_head()], cwd=ROOT).returncode == 0


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_contract() -> dict:
    return json.loads((ROOT / "audit/e9f/c1_live_contract.json").read_text(encoding="utf-8"))


def make_plan(contract: dict) -> dict:
    domain = build_source_bound_domain(0.0)
    if domain.case != "fr=0" or domain.semantic_domain_id != semantic_domain_id("fr=0"):
        raise RuntimeError("fr=0 semantic domain preflight failed")
    plan = build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)
    validate_integration_plan(plan)
    if plan["SAMPLE_COUNT"] != FIXED_SAMPLE_COUNT or plan["ESTIMATOR_ID"] != contract["scope"]["estimator"]:
        raise RuntimeError("sealed source plan count or estimator mismatch")
    if plan["SOURCE_GRID_SPACING_ID"] != contract["domain"]["grid_spacing"]:
        raise RuntimeError("sealed source grid spacing mismatch")
    return plan


def self_checks(contract: dict, plan: dict, preflight, geometry: dict) -> dict:
    checks = {
        "WORK_ORDER": contract["work_order_id"] == WORK_ORDER,
        "EXECUTION_CODE_SHA": execution_base_is_ancestor(contract),
        "MAIN_EXPECTATION": contract["expected_main_head"] == "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5",
        "FR0_ONLY": contract["scope"]["fr"] == 0.0 and not contract["authorization"].get("fr04", False),
        "SOURCE_ESTIMATOR_ONLY": contract["scope"]["estimator"] == SOURCE_GRID_MIDPOINT_V1 and MEPHC_CLIPPED_RETAINED_DOMAIN_V1 not in (contract["scope"]["estimator"],),
        "BANDS": tuple(contract["scope"]["zero_based_bands"]) == tuple(BANDS),
        "MODEL": contract["scope"]["resolution"] == RESOLUTION and contract["scope"]["num_bands"] == NUM_BANDS and contract["scope"]["solver_tolerance"] == SOLVER_TOLERANCE and contract["scope"]["mesh_size"] == MESH_SIZE,
        "GEOMETRY": geometry["max_roundtrip_error"] <= 1e-12 and abs(geometry["physical_fill_fraction"] - 0.24) <= 1e-12 and geometry["orientation"] == "COUNTERCLOCKWISE",
        "MAPPING": bool(preflight.ready) and preflight.round_trip_residual <= 1e-12,
        "KPRIME": tuple(round(float(x), 12) for x in preflight.public_q_to_mpb(KPRIME)) == (-0.333333333333, -0.333333333333),
        "PLAN_VALID": validate_integration_plan(plan) is True,
        "PLAN_COUNT": plan["SAMPLE_COUNT"] == FIXED_SAMPLE_COUNT,
        "PLAN_SEMANTIC": plan["SEMANTIC_DOMAIN_ID"] == semantic_domain_id("fr=0"),
        "NO_ZERO_FILL": contract["status_policy"]["zero_fill"] is False,
        "NO_RENORMALIZATION": contract["status_policy"]["posthoc_renormalization"] is False,
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9F.C1 self-check failed: {checks}")
    return checks


def solve_sample(plan_row: dict, plan: dict, band: int, provider, preflight, cache: dict, counters: dict) -> tuple[dict, dict]:
    center = tuple(float(x) for x in plan_row["PUBLIC_Q"])
    counters["sample_evaluations"] += 1
    evidence = stencil_evidence(center, SIDE, band, RESOLUTION, provider, preflight, cache, counters)
    phase = evidence["wilson"]["determinant_phase"]
    qualified = bool(evidence["qualified_before_refinement"] and phase is not None and math.isfinite(float(phase)))
    diagnostics = {
        "center_public_q": list(center),
        "band": band,
        "qualification_status": "QUALIFIED_REPORTED" if qualified else "NOT_REPORTED_WITH_REASON",
        "minimum_external_gap": evidence["minimum_external_gap"],
        "profile_passed": evidence["profile_passed"],
        "path_status": evidence["path"]["status"],
        "wilson_status": evidence["wilson"]["status"],
        "boundary_status": evidence["boundary"]["status"],
        "interior_status": evidence["interior"]["status"],
        "signed_area": SIDE * SIDE,
        "omega_formula": "-WILSON_PHASE/SIGNED_AREA",
    }
    if qualified:
        omega_q = float(-float(phase) / (SIDE * SIDE))
        if not math.isfinite(omega_q):
            raise RuntimeError(f"non-finite qualified Omega at {plan_row['SAMPLE_ID']}, band {band}")
        row = build_berry_row(plan, plan_row, band, "QUALIFIED_REPORTED", omega_q=omega_q)
        diagnostics["omega_q"] = omega_q
    else:
        reasons = []
        if not evidence["profile_passed"]: reasons.append("external_gap")
        if not evidence["path"]["is_qualified"]: reasons.append("ordered_path")
        if evidence["wilson"]["status"] != "WILSON_LOOP_QUALIFIED": reasons.append("wilson")
        if not evidence["boundary"]["is_qualified"]: reasons.append("boundary")
        if not evidence["interior"]["is_qualified"]: reasons.append("interior")
        if phase is None or not math.isfinite(float(phase)): reasons.append("finite_estimator")
        reason = "qualification_failed:" + ",".join(reasons or ["unspecified"])
        row = build_berry_row(plan, plan_row, band, "NOT_REPORTED_WITH_REASON", reason=reason)
        diagnostics["reason"] = reason
    return row, diagnostics


def checkpoint_payload(contract: dict, plan: dict, completed: dict, counters: dict) -> dict:
    return {
        "schema": "trilatt_e9f_c1_live_checkpoint_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "plan_digest": plan["PLAN_DIGEST"],
        "domain_digest": plan["DOMAIN_DIGEST"],
        "semantic_domain_id": plan["SEMANTIC_DOMAIN_ID"],
        "portable_plan_fingerprint": plan["PORTABLE_PLAN_FINGERPRINT"],
        "completed": completed,
        "counters": counters,
    }


def run_isolated_sample(contract: dict, plan: dict, sample_index: int, output: Path) -> None:
    """Evaluate one source sample in a fresh process."""
    if sample_index < 0 or sample_index >= len(plan["ROWS"]):
        raise ValueError("sample_index is outside the immutable source plan")
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    self_checks(contract, plan, preflight, geometry)
    provider = make_provider(RESOLUTION, lattice, solver_geometry, background)
    cache: dict = {}
    counters = {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0, "sample_evaluations": 0}
    plan_row = plan["ROWS"][sample_index]
    bands = {}
    for band in BANDS:
        row, diagnostics = solve_sample(plan_row, plan, band, provider, preflight, cache, counters)
        bands[str(band)] = {"row": row, "diagnostics": diagnostics}
    atomic_json(output, {
        "schema": "trilatt_e9f_c1_isolated_sample_v1",
        "sample_index": sample_index,
        "sample_id": plan_row["SAMPLE_ID"],
        "bands": bands,
        "counters": counters,
    })

def reduction_summary(plan: dict, rows: list[dict], band: int) -> dict:
    result = reduce_supplied_berry_rows(plan, rows, band)
    qualified = [row for row in rows if row["STATUS"] == "QUALIFIED_REPORTED"]
    failed = [row for row in rows if row["STATUS"] == "NOT_REPORTED_WITH_REASON"]
    return {
        "paper_band": band + 1,
        "zero_based_band": band,
        "result": result,
        "total_sample_count": len(rows),
        "qualified_sample_count": len(qualified),
        "not_reported_sample_count": len(failed),
        "qualified_weight_q2": float(sum(float(row["WEIGHT_Q2"]) for row in qualified)),
        "failed_weight_q2": float(sum(float(row["WEIGHT_Q2"]) for row in failed)),
        "sign_counts_qualified": {"positive": sum(float(row.get("OMEGA_Q", 0.0)) > 0 for row in qualified), "negative": sum(float(row.get("OMEGA_Q", 0.0)) < 0 for row in qualified), "zero": sum(float(row.get("OMEGA_Q", 0.0)) == 0 for row in qualified)},
        "failed_samples": [{"sample_id": row["SAMPLE_ID"], "reason": row["REASON"]} for row in failed],
    }


def run(output: Path, checkpoint: Path) -> dict:
    started = time.monotonic()
    contract = load_contract()
    if not execution_base_is_ancestor(contract):
        raise RuntimeError("live execution must start from committed contract SHA")
    plan = make_plan(contract)
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    checks = self_checks(contract, plan, preflight, geometry)
    completed = {}
    counters = {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0, "sample_evaluations": 0}
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        expected = {"work_order_id": WORK_ORDER, "base_sandbox_sha": contract["base_sandbox_sha"], "plan_digest": plan["PLAN_DIGEST"], "domain_digest": plan["DOMAIN_DIGEST"], "semantic_domain_id": plan["SEMANTIC_DOMAIN_ID"], "portable_plan_fingerprint": plan["PORTABLE_PLAN_FINGERPRINT"]}
        if any(saved.get(key) != value for key, value in expected.items()):
            raise RuntimeError("checkpoint does not match immutable live contract")
        completed = saved.get("completed", {})
        counters.update(saved.get("counters", {}))
    rows_by_id = {row["SAMPLE_ID"]: row for row in plan["ROWS"]}
    for index, plan_row in enumerate(plan["ROWS"], start=1):
        sample_id = plan_row["SAMPLE_ID"]
        if sample_id in completed and all(str(band) in completed[sample_id]["bands"] for band in BANDS):
            continue
        worker_output = checkpoint.with_name(f"{checkpoint.stem}.sample_{index - 1:04d}.json")
        if worker_output.exists():
            worker_output.unlink()
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(index - 1), "--worker-output", str(worker_output)],
            cwd=ROOT,
            check=True,
        )
        worker = json.loads(worker_output.read_text(encoding="utf-8"))
        worker_output.unlink()
        if worker.get("sample_index") != index - 1 or worker.get("sample_id") != sample_id:
            raise RuntimeError("isolated sample returned a mismatched immutable plan identity")
        bands = worker["bands"]
        for key in counters:
            counters[key] += int(worker["counters"].get(key, 0))
        completed[sample_id] = {"sample_id": sample_id, "public_q": list(plan_row["PUBLIC_Q"]), "bands": bands}
        atomic_json(checkpoint, checkpoint_payload(contract, plan, completed, counters))
        if index % 25 == 0 or index == len(plan["ROWS"]):
            print(json.dumps({"event": "sample_checkpoint", "completed": index, "total": len(plan["ROWS"]), "solver_requests": counters["solver_requests"], "cache_hits": counters["cache_hits"]}), flush=True)
    if set(completed) != set(rows_by_id):
        raise RuntimeError("checkpoint does not contain every source-grid sample")
    summaries = []
    for band in BANDS:
        rows = [completed[row["SAMPLE_ID"]]["bands"][str(band)]["row"] for row in plan["ROWS"]]
        summaries.append(reduction_summary(plan, rows, band))
    complete = all(item["result"]["COMPLETE_STATUS"] == "COMPLETE" for item in summaries)
    anchors = {0: -0.1, 1: 0.54, 2: -0.43}
    for item in summaries:
        value = item["result"].get("VALLEY_CHERN")
        item["source_anchor"] = anchors[item["zero_based_band"]] if value not in (None, "NOT_EMITTED") else None
        item["signed_difference_from_source_anchor"] = None if item["source_anchor"] is None else float(value - item["source_anchor"])
        item["absolute_difference_from_source_anchor"] = None if item["source_anchor"] is None else abs(item["signed_difference_from_source_anchor"])
    first_three_sum = None if not complete else float(sum(item["result"]["VALLEY_CHERN"] for item in summaries))
    payload = {
        "schema": "trilatt_e9f_c1_fr0_source_grid_live_result_v1",
        "work_order_id": WORK_ORDER,
        "upstream_seal": "E9F_B_PORTABLE_RETAINED_DOMAIN_INTEGRATION_CORE_VALIDATED",
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "calculation_code_git_sha": git_head(),
        "main_sha": contract["expected_main_head"],
        "main_unchanged": True,
        "contract_sha256": file_sha(ROOT / "audit/e9f/c1_live_contract.json"),
        "plan": {"estimator_id": plan["ESTIMATOR_ID"], "sample_count": plan["SAMPLE_COUNT"], "domain_digest": plan["DOMAIN_DIGEST"], "plan_digest": plan["PLAN_DIGEST"], "semantic_domain_id": plan["SEMANTIC_DOMAIN_ID"], "portable_plan_fingerprint": plan["PORTABLE_PLAN_FINGERPRINT"], "source_grid_spacing_id": plan["SOURCE_GRID_SPACING_ID"], "total_weight_q2": plan["TOTAL_WEIGHT_Q2"]},
        "model": contract["scope"],
        "qualification": contract["qualification"],
        "self_checks": checks,
        "band_summaries": summaries,
        "first_three_band_sum": first_three_sum,
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), **counters},
        "no_zero_fill": True,
        "no_failed_weight_removal": all(item["failed_weight_q2"] == 0.0 for item in summaries) if complete else True,
        "no_posthoc_renormalization": True,
        "new_scientific_campaign_scope": "fr=0 SOURCE_GRID bands 1-3 only",
        "status": "E9F_C1_FR0_SOURCE_GRID_VALLEY_CHERN_COMPLETE_READY_FOR_SUPERVISOR_REVIEW" if complete else "E9F_C1_FR0_SOURCE_GRID_INCOMPLETE_FAIL_CLOSED_READY_FOR_BLOCKER_DIAGNOSIS",
    }
    atomic_json(output, payload)
    return payload


if __name__ == "__main__":
    contract = load_contract()
    if "--worker" in sys.argv:
        plan = make_plan(contract)
        sample_index = int(sys.argv[sys.argv.index("--worker") + 1])
        output = Path(sys.argv[sys.argv.index("--worker-output") + 1])
        run_isolated_sample(contract, plan, sample_index, output)
    elif "--self-check" in sys.argv:
        if not execution_base_is_ancestor(contract):
            raise SystemExit("self-check requires contract SHA")
        plan = make_plan(contract)
        geometry = geometry_inputs()
        preflight, _, _, _ = build_inputs(geometry)
        print(json.dumps(self_checks(contract, plan, preflight, geometry), sort_keys=True))
    else:
        output = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else ROOT / "audit/e9f/c1_live_result.json"
        checkpoint = Path(sys.argv[sys.argv.index("--checkpoint") + 1]) if "--checkpoint" in sys.argv else ROOT / "audit/e9f/c1_live_checkpoint.json"
        result = run(output, checkpoint)
        print(json.dumps({"status": result["status"], "telemetry": result["telemetry"], "band_summaries": [{"band": row["paper_band"], "status": row["result"]["COMPLETE_STATUS"], "qualified": row["qualified_sample_count"], "not_reported": row["not_reported_sample_count"]} for row in result["band_summaries"]]}, sort_keys=True))
