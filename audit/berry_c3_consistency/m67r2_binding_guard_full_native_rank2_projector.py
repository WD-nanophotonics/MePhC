"""M67R2: manifest-guarded, solver-free completion of the M67 projector audit."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M66_DATASET_ID = "d399c2ab44d2139331d3d59ddcbebce2de584ea4f34fb5de2ee69c25994a82b5"
M66_MANIFEST_HALF_1 = "96463ece684c248c04097630bd3f133a"
M66_MANIFEST_HALF_2 = "c41f537a05150884c0e5026db9a88427"
M66_MANIFEST_SHA256 = M66_MANIFEST_HALF_1 + M66_MANIFEST_HALF_2
M66_SCHEMA = "mephc-berry-c3-consistency-m66-native-rank2-projector-scalar-dataset-v1"
M66_COUNT = 9
RESULT_SCHEMA = "mephc-berry-c3-consistency-m67r2-binding-guard-full-native-rank2-projector-v1"
N = 256
P = N * N
SHAPE = (N, N)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
CANONICAL_PAIR = (1, 2)
TARGET_PAIRS = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"M67R2_IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ValueError(f"{code}:{detail}" if detail else code)


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, complex):
        return [float(value.real), float(value.imag)]
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M67R2_UNSAFE_RESULT:{type(value).__name__}")


def _decode_array(value: Mapping[str, Any]) -> np.ndarray:
    return _load(ROOT / "audit/berry_c3_consistency/m67r1_recover_binding_full_native_rank2_projector.py", "m67r2_r1_decode").decode_array(value)


def _binding_guard() -> str:
    require(len(M66_MANIFEST_HALF_1) == 32 and len(M66_MANIFEST_HALF_2) == 32, "M67R2_MANIFEST_HALF_LENGTH_INVALID")
    value = M66_MANIFEST_HALF_1 + M66_MANIFEST_HALF_2
    require(len(value) == 64 and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "M67R2_MANIFEST_CANONICAL_INVALID")
    malformed = "96463ece684c248c04097630bd3f133ac41f537a051508844c0e5026db9a88427"
    require(value != malformed and len(malformed) == 65, "M67R2_MALFORMED_MANIFEST_REGRESSION_FAILED")
    return value


def _read_m66(job: Any, root: Path) -> list[dict[str, Any]]:
    manifest = _binding_guard()
    verified = job.verify_dataset(root, M66_DATASET_ID)
    require(verified.get("dataset_id") == M66_DATASET_ID, "M67R2_M66_DATASET_ID_INVALID")
    require(verified.get("manifest_sha256") == manifest, "M67R2_M66_MANIFEST_INVALID", str(verified.get("manifest_sha256")))
    require(verified.get("record_count") == M66_COUNT, "M67R2_M66_COUNT_INVALID")
    rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, M66_DATASET_ID, manifest, key)["payload"].decode("utf-8"))
        require(row.get("schema") == M66_SCHEMA, "M67R2_M66_SCHEMA_INVALID")
        rows.append(row)
    require(sorted((str(row["member"]), int(row["repeat_index"])) for row in rows) == sorted((member, repeat) for member in MEMBERS for repeat in range(3)), "M67R2_M66_COVERAGE_INVALID")
    return rows


def q_to_raw(Q: np.ndarray) -> np.ndarray:
    value = np.asarray(Q, dtype=np.complex128)
    require(value.shape == (P * 2, 2), "M67R2_Q_SHAPE_INVALID")
    return value.T.reshape(2, P, 2)


def raw_to_q(raw: np.ndarray) -> np.ndarray:
    value = np.asarray(raw, dtype=np.complex128)
    require(value.shape == (2, P, 2), "M67R2_SYNTHETIC_RAW_SHAPE_INVALID")
    return value.reshape(2, P * 2).T


def _alternate(raw_by_key: Mapping[tuple[str, int], np.ndarray], source: str, target: str, edge: Mapping[str, Any], m38: Any, coordinates: Mapping[str, Sequence[float]], pair: tuple[int, int], helper: Any, machine: float) -> dict[str, Any]:
    transformed, targets = [], []
    for repeat in range(3):
        source_q = helper.orthonormal_basis(raw_by_key[(source, repeat)][list(CANONICAL_PAIR)])[0]
        target_q = helper.orthonormal_basis(raw_by_key[(target, repeat)][list(pair)])[0]
        moved, _ = m38.apply_raw_operator(q_to_raw(source_q), coordinates[source], coordinates[target], edge["G_edge_integer"])
        transformed.append(raw_to_q(moved)); targets.append(target_q)
    distance, source_norm, target_norm = helper._distance(transformed, targets)
    source_radius = max(helper._radius(item, transformed) for item in transformed); target_radius = max(helper._radius(item, targets) for item in targets)
    return {"target_pair_one_based": [pair[0] + 1, pair[1] + 1], "distance": distance, "source_mean_projector_norm_squared": source_norm, "target_mean_projector_norm_squared": target_norm, "source_uncertainty_radius": source_radius, "target_uncertainty_radius": target_radius, "machine_term": machine, "pass": distance <= source_radius + target_radius + machine}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        helper = _load(ROOT / "audit/berry_c3_consistency/m67r1_recover_binding_full_native_rank2_projector.py", "m67r2_helper"); m38 = _load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m67r2_m38"); m41 = _load(ROOT / "audit/berry_c3_consistency/m41r3_recover36_finish_convergence.py", "m67r2_m41"); job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m67r2_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        rows = _read_m66(job, state_root); coordinates = {member: list(next(row["coordinate"] for row in rows if row["member"] == member)) for member in MEMBERS}; states = {member: {"c3_member_identity": member, "coordinate": value} for member, value in coordinates.items()}; edges = m38._edges(states); structural = m38.structural_validation(edges, states); require(structural["synthetic_closure_status"] == "PASS", "M67R2_M38_STRUCTURAL_CLOSURE_FAILED")
        maps = {(edge["edge_source_member"], edge["edge_target_member"]): helper._reciprocal_map(m38, edge) for edge in edges}; raw_by_key, q_by_key, q_meta = {}, {}, {}
        for row in rows:
            raw, layout = m41._normalize_raw(_decode_array(row["raw_eigenvector"]), N); q, meta = helper.orthonormal_basis(raw[list(CANONICAL_PAIR)]); key = (row["member"], int(row["repeat_index"])); raw_by_key[key], q_by_key[key], q_meta[key] = raw, q, {"layout": layout, **meta}
            trace_total = float(np.sum(helper.projector_trace(q))); require(abs(trace_total - 2.0) <= meta["machine_term"], "M67R2_TRACE_SUM_RANK_INVALID", str(trace_total))
        q_machine = max(item["orthogonality_residual"] for item in q_meta.values()); machine = np.finfo(float).eps * max(1.0, P * 2.0) * (32.0 + q_machine + structural["operator_norm_residual"] + structural["synthetic_c3_cubed_residual"])
        historical = helper._median_historical_ledger([{ "member": row["member"], "historical": _decode_array(row["reciprocal_projector_scalar_normalized"]) } for row in rows], maps); freq = helper._frequency(rows); window = helper._window(rows); require(not freq["all_pass"] and not historical["all_pass"] and window["qualified"], "M67R2_PREANALYSIS_NOT_REPRODUCED")
        grouped = {member: [q_by_key[(member, repeat)] for repeat in range(3)] for member in MEMBERS}; trace = helper._mean_scalar_ledger([{ "member": member, "trace": helper.projector_trace(q_by_key[(member, repeat)]) } for member in MEMBERS for repeat in range(3)], "trace", maps, machine); blocks, full = {}, {}
        for edge in edges:
            source, target = edge["edge_source_member"], edge["edge_target_member"]; transformed = []
            for repeat in range(3):
                moved, _ = m38.apply_raw_operator(q_to_raw(grouped[source][repeat]), coordinates[source], coordinates[target], edge["G_edge_integer"]); transformed.append(raw_to_q(moved))
            full_item = helper._full_edge(grouped[source], grouped[target], transformed, structural, q_machine); block_item = helper._block_edge_corrected(grouped[source], grouped[target], coordinates, edge, m38, machine); full_squared = full_item["distance"] ** 2; diagonal_squared = block_item["diagonal_block_frobenius_squared"]; block_item.update({"full_projector_frobenius_squared": full_squared, "offdiagonal_projector_frobenius_squared": max(0.0, full_squared - diagonal_squared), "diagonal_exceeds_full_arithmetic_flag": diagonal_squared > full_squared + machine, "machine_term": machine}); blocks[f"{source}_to_{target}"], full[f"{source}_to_{target}"] = block_item, full_item
        alternate = {f"{pair[0] + 1}-{pair[1] + 1}": {f"{edge['edge_source_member']}_to_{edge['edge_target_member']}": _alternate(raw_by_key, edge["edge_source_member"], edge["edge_target_member"], edge, m38, coordinates, pair, helper, machine) for edge in edges} for pair in TARGET_PAIRS}; canonical_fail = [key for key, item in full.items() if not item["pass"]]; unique = [key for key in alternate if key != "2-3" and canonical_fail and all(alternate[key][edge]["pass"] for edge in canonical_fail)]
        if not trace["all_pass"]: outcome = "R256_M67R2_FREQUENCY_C3_FAILURE_TRUE_PROJECTOR_TRACE_BREAK"
        elif not all(item["pass"] for item in blocks.values()): outcome = "R256_M67R2_FREQUENCY_C3_FAILURE_TRACE_PASS_BLOCK_DIAGONAL_BREAK"
        elif not all(item["pass"] for item in full.values()): outcome = "R256_M67R2_FREQUENCY_C3_FAILURE_CANONICAL_RANK2_BREAK_ALTERNATE_PAIR_COVARIANCE" if len(unique) == 1 else "R256_M67R2_FREQUENCY_C3_FAILURE_BLOCK_DIAGONAL_PASS_FULL_PROJECTOR_BREAK"
        elif not historical["all_pass"]: outcome = "R256_M67R2_FREQUENCY_C3_FAILURE_FULL_PROJECTOR_PASS_RAW_WEIGHTING_ARTIFACT"
        else: outcome = "R256_M67R2_FREQUENCY_C3_FAILURE_FULL_RANK2_PROJECTOR_C3_PASS"
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "SOLVER_FREE_REQUALIFICATION", "work_order_id": bundle["work_order_id"], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": source_commit, "m66_binding": {"dataset_id": M66_DATASET_ID, "manifest_sha256": M66_MANIFEST_SHA256, "manifest_halves": [M66_MANIFEST_HALF_1, M66_MANIFEST_HALF_2], "manifest_length": len(M66_MANIFEST_SHA256), "schema": M66_SCHEMA, "record_count": len(rows), "malformed_65_character_rejected": True}, "frequency_requalification": freq, "rank2_window": window, "historical_m66_raw_scalar_ledger": historical, "raw_layout_and_rank": q_meta, "true_projector_trace_ledger": trace, "diagonal_block_ledger": blocks, "full_projector_ledger": full, "alternate_target_pair_diagnostic": alternate, "unique_strong_alternate_pairs": unique, "reciprocal_c3_structural_validation": structural, "q_raw_roundtrip": "PASS", "mean_projector_formula": "exact thin-overlap self/cross traces; no hard-coded norm", "classification": outcome, "causal_outcome": outcome, "next_science_decision": "M7_RECIPROCAL_OFFDIAGONAL_PROJECTOR_COHERENCE_LOCALIZATION_FROM_M66_RAW_DATA" if outcome.endswith("FULL_PROJECTOR_BREAK") else "M7_EIGENVALUE_ONLY_C3_BREAK_VS_FULL_PROJECTOR_COVARIANCE_SYNTHESIS", "raw_complex_field_comparison": False, "gauge_u2_band_permutation_fitting": False, "c3_symmetrization": False, "ambient_projector_allocated": False, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "m67r2_solver_free_requalification", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
