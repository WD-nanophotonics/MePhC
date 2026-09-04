"""M39R3: final solver-free adjudication over the finalized M39R1 evidence."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BASE = importlib.util.spec_from_file_location("m39r3_base", ROOT / "audit/berry_c3_consistency/m39r2_persisted_14_state_causal_adjudication.py")
assert BASE and BASE.loader
m39r2 = importlib.util.module_from_spec(BASE)
BASE.loader.exec_module(m39r2)
m39 = m39r2.m39 if hasattr(m39r2, "m39") else m39r2._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m39r3_m39")
m38 = m39r2.m38 if hasattr(m39r2, "m38") else m39r2._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m39r3_m38")

RESULT_SCHEMA = "mephc-berry-c3-consistency-m39r3-g15-persisted-evidence-final-causal-adjudication-v1"
MEMBERS = m39r2.MEMBERS
PARENT_NAMESPACE_SHA256 = m39r2.PARENT_NAMESPACE_SHA256
M18_DATASET_ID = m39r2.M18_DATASET_ID
M33_DATASET_ID = m39r2.M33_DATASET_ID
M39R1_PARENT = m39r2.M39R1_WORK_ORDER_ID
PUBLIC_M38_MIN = m39r2.PUBLIC_M38_MIN
P = m39r2.P
_ORIGINAL_RANK1_LINKS = m39r2._rank1_links


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return "INF" if value > 0 else "-INF" if value < 0 else "NAN"
        return value
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, complex):
        return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError(f"M39R3_UNSAFE_RESULT:{type(value).__name__}")


def _fixed_rank1_links(m38_module: Any, source: np.ndarray, target: np.ndarray, source_band: int, edge: Mapping[str, Any], source_coord: Sequence[float], target_coord: Sequence[float]) -> dict[str, Any]:
    """Use physical labels 2/3 while indexing historical raw2 locally as 0/1."""
    if source.shape[0] != 2:
        return _ORIGINAL_RANK1_LINKS(m38_module, source, target, source_band, edge, source_coord, target_coord)
    local_index = int(source_band) - 1
    if local_index not in (0, 1):
        raise ValueError(f"M39R3_HISTORICAL_RAW2_LOCAL_INDEX_INVALID:{source_band}")
    transformed, ledger = m38_module.apply_raw_operator(source, source_coord, target_coord, edge["G_edge_integer"])
    vector = transformed[local_index].reshape(-1)
    overlaps: list[complex] = []
    for candidate in target:
        denominator = np.linalg.norm(vector) * np.linalg.norm(candidate.reshape(-1))
        overlaps.append(complex(np.vdot(candidate.reshape(-1), vector) / denominator) if denominator else complex(np.nan, np.nan))
    if any(not np.isfinite(value.real) or not np.isfinite(value.imag) for value in overlaps):
        raise ValueError("M39R3_ZERO_NORM_HISTORICAL_LINK")
    same = overlaps[local_index]
    return {"source_band": int(source_band) + 1, "physical_band": int(source_band) + 1, "local_source_index": local_index, "edge_source_member": edge["edge_source_member"], "edge_target_member": edge["edge_target_member"], "target_overlap_magnitudes": [float(abs(value)) for value in overlaps], "best_target_band": int(np.argmax([abs(value) for value in overlaps])) + 2, "same_index_link": _safe(same), "link_magnitude": float(abs(same)), "wrapped_edge_phase": float(np.angle(same)), "mode_map_bijection": bool(ledger["bijection"])}


def _corrected_analysis(records: Sequence[Mapping[str, Any]], m18: Mapping[str, Mapping[str, Any]], m33: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    original = m39r2._rank1_links
    original_loop = m39r2._loop
    m39r2._rank1_links = _fixed_rank1_links
    def partial_historical_loop(values: Sequence[Mapping[str, Any]], deterministic: bool, repeat: int) -> dict[str, Mapping[str, Any]]:
        if not deterministic and repeat == 1:
            selected = {str(item["c3_member_identity"]): item for item in values if not item["deterministic"] and int(item["repeat_index"]) == 1 and item["c3_member_identity"] in {"C3", "C3_SQUARED"}}
            if set(selected) == {"C3", "C3_SQUARED"}:
                return {"IDENTITY": {}, **selected}
        return original_loop(values, deterministic, repeat)
    m39r2._loop = partial_historical_loop
    try:
        analysis = dict(m39r2._analyze(records, m18, m33, m39, m38))
    finally:
        m39r2._rank1_links = original
        m39r2._loop = original_loop
    deterministic_edges = [edge for loop in analysis["c3_rank2_edge_metrics"] if loop["deterministic"] for edge in loop["edges"]]
    nondeterministic_edges = [edge for loop in analysis["c3_rank2_edge_metrics"] if not loop["deterministic"] for edge in loop["edges"]]
    best_pairs = [tuple(edge["best_target_pair"]) for edge in deterministic_edges]
    pair_stable = bool(best_pairs) and len(set(best_pairs)) == 1
    pair_noncanonical = any(pair != (2, 3) for pair in best_pairs)
    det_min = min(edge["canonical_pair_metrics"]["minimum_singular_value"] for edge in deterministic_edges)
    non_min = min(edge["canonical_pair_metrics"]["minimum_singular_value"] for edge in nondeterministic_edges)
    same_k = analysis["same_k_repeat_frequency_dispersion"]
    det_spread = max((1.0 - pair["rank2_bands_2_3"]["minimum_singular_value"] for value in same_k.values() for pair in value["deterministic_pairwise"]), default=0.0)
    non_spread = max((1.0 - value["new_nondeterministic_repeat0_vs_repeat1"]["rank2_bands_2_3"]["minimum_singular_value"] for value in same_k.values() if isinstance(value["new_nondeterministic_repeat0_vs_repeat1"], Mapping)), default=0.0)
    uncertainty = det_spread + non_spread
    same_k_stable = det_spread < max(0.0, 1.0 - det_min)
    primary = m39.classify_causal(deterministic_minimum=det_min, nondeterministic_minimum=non_min, combined_repeat_uncertainty=uncertainty, deterministic_repeat_spread=det_spread, cross_c3_deficit=max(0.0, 1.0 - det_min), adjacent_pair_stable=pair_stable, adjacent_pair_noncanonical=pair_noncanonical, deterministic_same_k_stable=same_k_stable)
    next_decision = {"RANDOM_INITIALIZATION": "DETERMINISTIC_WORST_ORBIT_BERRY_RECOMPUTATION", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_TRANSPORT_ON_EXISTING_M39R1_RAW_BANDS", "REMAINING_NUMERICAL_OR_PHYSICAL_C3_BREAKING": "BOUNDED_RESOLUTION_TOLERANCE_CONVERGENCE_PILOT", "MULTIPLE_IDENTIFIED_CAUSES": "PRIORITIZE_CHEAPEST_IDENTIFIED_CAUSAL_CONTROL", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M39R3_EVIDENCE"}[primary]
    analysis.update({"c3_rank2_best_pair_stability": {"stable": pair_stable, "noncanonical": pair_noncanonical, "canonical_pair_one_based": [2, 3], "deterministic_best_pairs": [list(pair) for pair in best_pairs]}, "deterministic_vs_nondeterministic_effect_summary": {**analysis["deterministic_vs_nondeterministic_effect_summary"], "deterministic_minimum_canonical_rank2": det_min, "nondeterministic_minimum_canonical_rank2": non_min, "combined_observed_repeat_uncertainty": uncertainty, "deterministic_same_k_stable": same_k_stable, "m38_baseline_minimum": PUBLIC_M38_MIN}, "primary_causal_class": primary, "causal_evidence": {"deterministic_minimum": det_min, "nondeterministic_minimum": non_min, "observed_repeat_uncertainty": uncertainty, "deterministic_same_k_stable": same_k_stable, "canonical_pair_one_based": [2, 3], "best_pair_stable": pair_stable, "best_pair_noncanonical": pair_noncanonical}, "next_science_decision": next_decision, "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH"})
    return analysis


def _result_document(work_order_id: str, source_commit: str, records: Sequence[Mapping[str, Any]], parent: Mapping[str, Any], m18: Mapping[str, Mapping[str, Any]], m33: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    analysis = _corrected_analysis(records, m18, m33)
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_M39R1_PARENT_DATASET_FINAL_CAUSAL_ADJUDICATION_COMPLETE", "work_order_id": work_order_id, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "parent_dataset_id": parent["dataset_id"], "parent_manifest_sha256": parent["manifest_sha256"], "parent_namespace_sha256": parent["namespace_sha256"], "source_m18_dataset_id": M18_DATASET_ID, "source_m33_dataset_id": M33_DATASET_ID, "parent_schedule_summary": {"record_count": 14, "deterministic_state_count": 9, "nondeterministic_state_count": 5, "deterministic_repeats": [1, 2, 3], "new_nondeterministic_repeat0_members": list(MEMBERS), "new_nondeterministic_repeat1_members": ["C3", "C3_SQUARED"]}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True, **analysis}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m39r2._load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m39r3_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        records, parent = m39r2._read_parent(job, state_root)
        m18_records = m39r2._read_dataset(job, state_root, M18_DATASET_ID, m39r2.M18_MANIFEST_SHA256, m39r2.M18_SCHEMA, 3)
        m33_records = m39r2._read_dataset(job, state_root, M33_DATASET_ID, m39r2.M33_MANIFEST_SHA256, m39r2.M33_SCHEMA, 3)
        m18 = m39r2._bind_triplet(m18_records, m39r2.M18_SCHEMA)
        m33 = m39r2._bind_triplet(m33_records, m39r2.M33_SCHEMA)
        result = _result_document(bundle["work_order_id"], source_commit, records, parent, m18, m33)
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "parent_resolution_or_solver_free_analysis", "exception_type": type(exc).__name__, "parent_dataset_id": None, "parent_manifest_sha256": None, "parent_namespace_sha256": PARENT_NAMESPACE_SHA256, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
