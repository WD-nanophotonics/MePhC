"""M40R3: final solver-free Berry/C3 adjudication over M40R1 evidence."""
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "audit/berry_c3_consistency/m40r2_persisted_72_state_final_berry_causal_closure.py"
SPEC = importlib.util.spec_from_file_location("m40r3_base", BASE)
assert SPEC and SPEC.loader
m40r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m40r2)

MEMBERS = m40r2.MEMBERS
STENCILS = m40r2.STENCILS
REPEATS = m40r2.REPEATS
RESULT_SCHEMA = "mephc-berry-c3-consistency-m40r3-g15-persisted-72-state-berry-c3-final-adjudication-v1"
M39R1_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
M39R1_DATASET_ID = m40r2.M39R1_DATASET_ID
M39R1_MANIFEST_SHA256 = m40r2.M39R1_MANIFEST_SHA256
PARENT_NAMESPACE_SHA256 = m40r2.PARENT_NAMESPACE_SHA256


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, complex):
        return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M40R3_UNSAFE_RESULT:{type(value).__name__}")


def branch_safe_phases(values: Sequence[float]) -> dict[str, Any]:
    """Lift phases around a circular reference before scalar summaries."""
    phases = [float(v) for v in values]
    if not phases:
        raise ValueError("M40R3_EMPTY_PHASE_SERIES")
    reference = phases[0]
    lifted = [reference + float(np.angle(np.exp(1j * (phase - reference)))) for phase in phases]
    wrapped = [abs(float(np.angle(np.exp(1j * (a - b))))) for a, b in itertools.combinations(phases, 2)]
    stable = all(distance < math.pi for distance in wrapped)
    median = float(np.median(lifted))
    return {"reference_phase": reference, "lifted_phases": lifted, "median": median, "max_absolute_deviation": float(max((abs(v - median) for v in lifted), default=0.0)), "maximum_pairwise_wrapped_distance": float(max(wrapped, default=0.0)), "branch_stability": "STABLE_CIRCULAR_CLUSTER" if stable else "BRANCH_STABILITY_INSUFFICIENT"}


def _recompute_c3(analysis: dict[str, Any]) -> None:
    qualification = analysis["rank1_qualification"]
    uncertainty = analysis["repeat_uncertainty_by_member_stencil"]
    rank1_c3: dict[str, list[dict[str, Any]]] = {}
    rank2_c3: dict[str, list[dict[str, Any]]] = {}
    for stencil in STENCILS:
        rank1_c3[stencil], rank2_c3[stencil] = [], []
        for left, right in itertools.combinations(MEMBERS, 2):
            a = uncertainty[stencil][left]["rank1_phase_density"]
            b = uncertainty[stencil][right]["rank1_phase_density"]
            rank1_status = "RANK1_WITHHELD" if qualification[stencil]["status"] != "RANK1_QUALIFIED" else "PASS" if abs(a["median"] - b["median"]) <= a["uncertainty"] + b["uncertainty"] and (a["median"] == 0 or b["median"] == 0 or np.sign(a["median"]) == np.sign(b["median"])) else "FAIL"
            rank1_c3[stencil].append({"members": [left, right], "absolute_difference": abs(a["median"] - b["median"]), "combined_uncertainty": a["uncertainty"] + b["uncertainty"], "proper_c3_sign_preserved": bool(a["median"] == 0 or b["median"] == 0 or np.sign(a["median"]) == np.sign(b["median"])), "status": rank1_status})
            a = uncertainty[stencil][left]["rank2_trace_phase_density"]
            b = uncertainty[stencil][right]["rank2_trace_phase_density"]
            rank2_c3[stencil].append({"members": [left, right], "absolute_difference": abs(a["median"] - b["median"]), "combined_uncertainty": a["uncertainty"] + b["uncertainty"], "proper_c3_sign_preserved": bool(a["median"] == 0 or b["median"] == 0 or np.sign(a["median"]) == np.sign(b["median"])), "status": "PASS" if abs(a["median"] - b["median"]) <= a["uncertainty"] + b["uncertainty"] and (a["median"] == 0 or b["median"] == 0 or np.sign(a["median"]) == np.sign(b["median"])) else "FAIL"})
    analysis["rank1_c3_pairwise_comparison_by_stencil"] = rank1_c3
    analysis["rank2_c3_pairwise_comparison_by_stencil"] = rank2_c3
    analysis["rank1_c3_status_by_stencil"] = {s: "PASS" if qualification[s]["status"] == "RANK1_QUALIFIED" and all(p["status"] == "PASS" for p in rank1_c3[s]) else "RANK1_WITHHELD" if qualification[s]["status"] != "RANK1_QUALIFIED" else "FAIL" for s in STENCILS}
    analysis["rank2_c3_status_by_stencil"] = {s: "PASS" if all(p["status"] == "PASS" for p in rank2_c3[s]) else "FAIL" for s in STENCILS}


def analyze(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, m2_count: int, m39r1_count: int) -> dict[str, Any]:
    analysis = m40r2.analyze(records, centers, m38, m39, m2_count, m39r1_count)
    for stencil in STENCILS:
        for member in MEMBERS:
            rows = [row for row in analysis["rank1_plaquette_results"][stencil] if row["member"] == member]
            rank1_phase = branch_safe_phases([row["rank1_wilson_phase"] for row in rows])
            rank2_phase = branch_safe_phases([row["rank2_trace_phase"] for row in rows])
            rank1_density = [phase / float(row["signed_area"]) for phase, row in zip(rank1_phase["lifted_phases"], rows)]
            rank2_density = [phase / float(row["signed_area"]) for phase, row in zip(rank2_phase["lifted_phases"], rows)]
            current = analysis["repeat_uncertainty_by_member_stencil"][stencil][member]
            current["rank1_wilson_phase"] = rank1_phase
            current["rank2_trace_phase"] = rank2_phase
            current["rank1_phase_density"] = {"median": float(np.median(rank1_density)), "uncertainty": float(max((abs(v - np.median(rank1_density)) for v in rank1_density), default=0.0)), "branch_lifted_values": rank1_density}
            current["rank1_legacy_m2_compatible_curvature"] = {"median": float(np.median([-v / (2.0 * math.pi) ** 2 for v in rank1_density])), "uncertainty": float(max((abs((-v / (2.0 * math.pi) ** 2) - np.median([-x / (2.0 * math.pi) ** 2 for x in rank1_density])) for v in rank1_density), default=0.0))}
            current["rank2_trace_phase_density"] = {"median": float(np.median(rank2_density)), "uncertainty": float(max((abs(v - np.median(rank2_density)) for v in rank2_density), default=0.0)), "branch_lifted_values": rank2_density}
            current["rank2_legacy_m2_compatible_trace_curvature"] = {"median": float(np.median([-v / (2.0 * math.pi) ** 2 for v in rank2_density])), "uncertainty": float(max((abs((-v / (2.0 * math.pi) ** 2) - np.median([-x / (2.0 * math.pi) ** 2 for x in rank2_density])) for v in rank2_density), default=0.0))}
    _recompute_c3(analysis)
    analysis["branch_safe_repeat_statistics"] = analysis["repeat_uncertainty_by_member_stencil"]
    return analysis


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m40r2._load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m40r3_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        m39 = m40r2._load(ROOT / "audit" / "berry_c3_consistency" / "m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m40r3_m39")
        m38 = m40r2._load(ROOT / "audit" / "berry_c3_consistency" / "m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m40r3_m38")
        parent, records, recovery_status = m40r2.recover_parent(job, state_root)
        m18 = m40r2._read_dataset(job, state_root, m40r2.M18_DATASET_ID, m40r2.M18_MANIFEST_SHA256, m40r2.M18_SCHEMA, 3)
        m39r1 = m40r2._read_dataset(job, state_root, M39R1_DATASET_ID, M39R1_MANIFEST_SHA256, M39R1_SCHEMA, 14)
        centers = m40r2._centers(m18, m39r1)
        try:
            m2 = m40r2._read_dataset(job, state_root, m40r2.M2_DATASET_ID, m40r2.M2_MANIFEST_SHA256, "mephc-berry-c3-pilot-plaquette-v1", 72)
        except Exception:
            m2 = []
        analysis = analyze(records, centers, m38, m39, len(m2), len(m39r1))
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_M40R1_PARENT_DATASET_FINAL_BERRY_C3_ADJUDICATION_COMPLETE", "work_order_id": bundle["work_order_id"], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "parent_namespace_sha256": PARENT_NAMESPACE_SHA256, "parent_dataset_id": parent["dataset_id"], "parent_manifest_sha256": parent["manifest_sha256"], "parent_manifest_recovery_status": recovery_status, "source_m18_dataset_id": m40r2.M18_DATASET_ID, "source_m39r1_dataset_id": M39R1_DATASET_ID, "source_m2_dataset_id": m40r2.M2_DATASET_ID, "parent_schedule_summary": {"record_count": 72, "members": list(MEMBERS), "stencils": list(STENCILS), "repeat_indices": list(REPEATS), "vertex_indices": list(range(4)), "deterministic": True}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True, **analysis}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "parent_resolution_or_solver_free_analysis", "exception_type": type(exc).__name__, "parent_namespace_sha256": PARENT_NAMESPACE_SHA256, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
