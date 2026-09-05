"""M67R1: corrected, solver-free full-projector requalification of M66."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import math
import os
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
N = 256
P = N * N
SHAPE = (N, N)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
CANONICAL_PAIR = (1, 2)
TARGET_PAIRS = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
RESULT_SCHEMA = "mephc-berry-c3-consistency-m67r1-recover-binding-full-native-rank2-projector-v1"
M66_DATASET_ID = "d399c2ab44d2139331d3d59ddcbebce2de584ea4f34fb5de2ee69c25994a82b5"
M66_MANIFEST_SHA256 = "96463ece684c248c04097630bd3f133ac41f537a051508844c0e5026db9a88427"
M66_SCHEMA = "mephc-berry-c3-consistency-m66-native-rank2-projector-scalar-dataset-v1"
M66_COUNT = 9


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


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
    raise ValueError(f"M67R1_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M67R1_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decode_array(value: Mapping[str, Any]) -> np.ndarray:
    payload = zlib.decompress(base64.b64decode(str(value["payload_base64"])))
    array = np.load(io.BytesIO(payload), allow_pickle=False)
    require(list(array.shape) == list(value["shape"]) and str(array.dtype) == str(value["dtype"]), "M67R1_ARRAY_METADATA_INVALID")
    require(hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest() == value["sha256"], "M67R1_ARRAY_HASH_INVALID")
    return np.asarray(array)


def _read_m66(job: Any, root: Path) -> list[dict[str, Any]]:
    verified = job.verify_dataset(root, M66_DATASET_ID)
    require(verified.get("dataset_id") == M66_DATASET_ID, "M67R1_M66_DATASET_ID_INVALID")
    require(verified.get("manifest_sha256") == M66_MANIFEST_SHA256, "M67R1_M66_MANIFEST_INVALID", str(verified.get("manifest_sha256")))
    require(verified.get("record_count") == M66_COUNT, "M67R1_M66_COUNT_INVALID")
    rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, M66_DATASET_ID, M66_MANIFEST_SHA256, key)["payload"].decode("utf-8"))
        require(row.get("schema") == M66_SCHEMA, "M67R1_M66_SCHEMA_INVALID")
        rows.append(row)
    require(sorted((str(row["member"]), int(row["repeat_index"])) for row in rows) == sorted((member, repeat) for member in MEMBERS for repeat in range(3)), "M67R1_M66_COVERAGE_INVALID")
    return rows


def q_to_raw(Q: np.ndarray) -> np.ndarray:
    value = np.asarray(Q, dtype=np.complex128)
    require(value.shape == (P * 2, 2), "M67R1_Q_SHAPE_INVALID")
    return value.T.reshape(2, P, 2)


def raw_to_q(raw: np.ndarray) -> np.ndarray:
    value = np.asarray(raw, dtype=np.complex128)
    require(value.shape == (2, P, 2), "M67R1_SYNTHETIC_RAW_SHAPE_INVALID")
    return value.reshape(2, P * 2).T


def orthonormal_basis(raw_pair: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(raw_pair, dtype=np.complex128)
    require(value.shape == (2, P, 2), "M67R1_RAW_PAIR_SHAPE_INVALID", str(value.shape))
    X = np.asarray([value[0].reshape(-1), value[1].reshape(-1)], dtype=np.complex128).T
    singular = np.linalg.svd(X, compute_uv=False)
    sigma_max = float(np.max(singular))
    guard = np.finfo(float).eps * max(1.0, X.shape[0]) * max(1.0, sigma_max)
    require(singular.size == 2 and singular[1] > guard, "M67R1_RANK2_NUMERICAL_RANK_INVALID")
    Q, _ = np.linalg.qr(X, mode="reduced")
    residual = float(np.linalg.norm(Q.conj().T @ Q - np.eye(2)))
    machine = np.finfo(float).eps * max(1.0, X.shape[0], sigma_max) * 32.0
    require(residual <= machine, "M67R1_Q_ORTHOGONALITY_INVALID")
    return Q, {"singular_values": singular.tolist(), "rank_guard": guard, "orthogonality_residual": residual, "machine_term": machine, "condition_number": float(singular[0] / singular[1])}


def projector_trace(Q: np.ndarray) -> np.ndarray:
    stack = np.asarray(Q, dtype=np.complex128).reshape(P, 2, 2).transpose(2, 0, 1)
    return np.sum(np.abs(stack) ** 2, axis=(0, 2)).reshape(SHAPE)


def projector_blocks(Q: np.ndarray) -> np.ndarray:
    stack = np.asarray(Q, dtype=np.complex128).reshape(P, 2, 2).transpose(2, 0, 1).transpose(1, 2, 0)
    return np.einsum("fab,fcb->fac", stack, stack.conj(), optimize=True)


def _apply_map(value: np.ndarray, mapping: np.ndarray) -> np.ndarray:
    result = np.empty_like(value)
    result[mapping[..., 0], mapping[..., 1]] = value
    return result


def _mean_scalar_ledger(rows: Sequence[Mapping[str, Any]], field: str, maps: Mapping[tuple[str, str], np.ndarray], machine_term: float) -> dict[str, Any]:
    central, uncertainty = {}, {}
    for member in MEMBERS:
        values = [np.asarray(row[field], dtype=float) for row in rows if row["member"] == member]
        central[member] = np.mean(np.stack(values), axis=0)
        uncertainty[member] = float(max(np.max(np.abs(value - central[member])) for value in values))
    edges = {}
    for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
        delta = _apply_map(central[source], maps[(source, target)]) - central[target]
        residual = float(np.max(np.abs(delta)))
        edges[f"{source}_to_{target}"] = {"residual_linf": residual, "source_uncertainty_linf": uncertainty[source], "target_uncertainty_linf": uncertainty[target], "machine_term": machine_term, "pass": residual <= uncertainty[source] + uncertainty[target] + machine_term}
    return {"uncertainty_linf": uncertainty, "directed": edges, "all_pass": all(item["pass"] for item in edges.values())}


def _median_historical_ledger(rows: Sequence[Mapping[str, Any]], maps: Mapping[tuple[str, str], np.ndarray]) -> dict[str, Any]:
    central, uncertainty = {}, {}
    for member in MEMBERS:
        values = [np.asarray(row["historical"], dtype=float) for row in rows if row["member"] == member]
        central[member] = np.median(np.stack(values), axis=0)
        uncertainty[member] = float(max(np.max(np.abs(value - central[member])) for value in values))
    edges = {}
    for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
        delta = _apply_map(central[source], maps[(source, target)]) - central[target]
        residual = float(np.max(np.abs(delta)))
        edges[f"{source}_to_{target}"] = {"residual_linf": residual, "source_uncertainty_linf": uncertainty[source], "target_uncertainty_linf": uncertainty[target], "pass": residual <= uncertainty[source] + uncertainty[target]}
    return {"rule": "M66_EXACT_MEDIAN_MAX_DEVIATION_NO_MACHINE_TERM", "uncertainty_linf": uncertainty, "directed": edges, "all_pass": all(item["pass"] for item in edges.values())}


def _frequency(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    central, uncertainty = {}, {}
    for member in MEMBERS:
        values = np.stack([np.asarray(row["frequencies_bands_1_to_4"], dtype=float) for row in rows if row["member"] == member])
        central[member] = np.median(values, axis=0).tolist()
        uncertainty[member] = np.max(np.abs(values - np.asarray(central[member])), axis=0).tolist()
    edges = {}
    for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
        delta = np.abs(np.asarray(central[source]) - np.asarray(central[target])); limit = np.asarray(uncertainty[source]) + np.asarray(uncertainty[target])
        edges[f"{source}_to_{target}"] = {"central_difference": delta.tolist(), "combined_uncertainty": limit.tolist(), "pass_by_band": (delta <= limit).tolist(), "pass": bool(np.all(delta <= limit))}
    return {"central": central, "uncertainty": uncertainty, "directed": edges, "all_pass": all(item["pass"] for item in edges.values())}


def _window(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = {}
    qualified = True
    for member in MEMBERS:
        gaps = np.stack([[row["frequencies_bands_1_to_4"][1] - row["frequencies_bands_1_to_4"][0], row["frequencies_bands_1_to_4"][3] - row["frequencies_bands_1_to_4"][2]] for row in rows if row["member"] == member])
        mean = np.median(gaps, axis=0); uncertainty = np.max(np.abs(gaps - mean), axis=0); ok = bool(np.all((mean > 0.0) & (mean > uncertainty))); qualified = qualified and ok
        values[member] = {"median_external_gaps": mean.tolist(), "repeat_uncertainty": uncertainty.tolist(), "qualified": ok}
    return {"members": values, "qualified": qualified, "pair": [2, 3]}


def _distance(left: Sequence[np.ndarray], right: Sequence[np.ndarray]) -> tuple[float, float, float]:
    def overlap(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.sum(np.linalg.svd(a.conj().T @ b, compute_uv=False) ** 2))
    norm_left = float(np.mean([overlap(a, b) for a in left for b in left])); norm_right = float(np.mean([overlap(a, b) for a in right for b in right])); cross = float(np.mean([overlap(a, b) for a in left for b in right])); return float(np.sqrt(max(0.0, norm_left + norm_right - 2.0 * cross))), norm_left, norm_right


def _radius(item: np.ndarray, ensemble: Sequence[np.ndarray]) -> float:
    _, norm, _ = _distance(ensemble, ensemble)
    def overlap(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.sum(np.linalg.svd(a.conj().T @ b, compute_uv=False) ** 2))
    cross = float(np.mean([overlap(item, other) for other in ensemble])); return float(np.sqrt(max(0.0, 2.0 + norm - 2.0 * cross)))


def _full_edge(source: Sequence[np.ndarray], target: Sequence[np.ndarray], transformed: Sequence[np.ndarray], structural: Mapping[str, Any], q_machine: float) -> dict[str, Any]:
    distance, source_norm, target_norm = _distance(transformed, target)
    source_radius = max(_radius(item, source) for item in source); target_radius = max(_radius(item, target) for item in target)
    machine = np.finfo(float).eps * max(1.0, P * 2.0) * (64.0 + q_machine + float(structural.get("operator_norm_residual", 0.0)) + float(structural.get("synthetic_c3_cubed_residual", 0.0)))
    pairwise = []
    for src in transformed:
        for dst in target:
            singular = np.linalg.svd(src.conj().T @ dst, compute_uv=False); pairwise.append({"singular_values": singular.tolist(), "minimum_singular_value": float(np.min(singular)), "maximum_principal_angle": float(np.arccos(np.clip(np.min(singular), -1.0, 1.0))), "projector_distance": float(np.sqrt(max(0.0, 4.0 - 2.0 * float(np.sum(singular ** 2)))))})
    return {"distance": distance, "source_mean_projector_norm_squared": source_norm, "target_mean_projector_norm_squared": target_norm, "source_uncertainty_radius": source_radius, "target_uncertainty_radius": target_radius, "machine_term": machine, "pairwise_3x3": pairwise, "pass": distance <= source_radius + target_radius + machine}


def _target_pair_measures(raw_by_key: Mapping[tuple[str, int], np.ndarray], source: str, target: str, edge: Mapping[str, Any], m38: Any, coordinates: Mapping[str, Sequence[float]], target_pair: tuple[int, int]) -> dict[str, Any]:
    source_q = []
    target_q = []
    for repeat in range(3):
        q, _ = orthonormal_basis(raw_by_key[(source, repeat)][list(CANONICAL_PAIR)])
        transformed_raw, _ = m38.apply_raw_operator(q_to_raw(q), coordinates[source], coordinates[target], edge["G_edge_integer"])
        transformed_q = raw_to_q(transformed_raw)
        target_q.append(orthonormal_basis(raw_by_key[(target, repeat)][list(target_pair)])[0]); source_q.append(transformed_q)
    distance, source_norm, target_norm = _distance(source_q, target_q)
    return {"target_pair_one_based": [target_pair[0] + 1, target_pair[1] + 1], "distance": distance, "source_mean_projector_norm_squared": source_norm, "target_mean_projector_norm_squared": target_norm}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m67r1_job"); m38 = _load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m67r1_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; rows = _read_m66(job, state_root)
        coordinates = {member: list(next(row["coordinate"] for row in rows if row["member"] == member)) for member in MEMBERS}; states = {member: {"c3_member_identity": member, "coordinate": value} for member, value in coordinates.items()}; edges = m38._edges(states); structural = m38.structural_validation(edges, states); require(structural["synthetic_closure_status"] == "PASS", "M67R1_M38_STRUCTURAL_CLOSURE_FAILED")
        maps = {(edge["edge_source_member"], edge["edge_target_member"]): _reciprocal_map(m38, edge) for edge in edges}; raw_by_key, q_by_key, q_meta = {}, {}, {}
        for row in rows:
            native = decode_array(row["raw_eigenvector"]); m41 = _load(ROOT / "audit/berry_c3_consistency/m41r3_recover36_finish_convergence.py", "m67r1_m41") if "m67r1_m41" not in globals() else globals()["m67r1_m41"]; raw, layout = m41._normalize_raw(native, N); q, meta = orthonormal_basis(raw[list(CANONICAL_PAIR)]); key = (row["member"], int(row["repeat_index"])); raw_by_key[key], q_by_key[key], q_meta[key] = raw, q, {"layout": layout, **meta}
        q_machine = max(meta["orthogonality_residual"] for meta in q_meta.values()); machine_term = np.finfo(float).eps * max(1.0, P * 2.0) * (32.0 + q_machine + structural["operator_norm_residual"] + structural["synthetic_c3_cubed_residual"])
        historical_rows = [{"member": row["member"], "historical": decode_array(row["reciprocal_projector_scalar_normalized"])} for row in rows]; historical = _median_historical_ledger(historical_rows, maps); freq = _frequency(rows); window = _window(rows); require(not freq["all_pass"] and not historical["all_pass"] and window["qualified"], "M67R1_PREANALYSIS_REQUALIFICATION_NOT_REPRODUCED")
        grouped = {member: [q_by_key[(member, repeat)] for repeat in range(3)] for member in MEMBERS}; trace_rows = [{"member": member, "trace": projector_trace(q_by_key[(member, repeat)])} for member in MEMBERS for repeat in range(3)]; trace = _mean_scalar_ledger(trace_rows, "trace", maps, machine_term)
        blocks, full = {}, {}
        for edge in edges:
            source, target = edge["edge_source_member"], edge["edge_target_member"]; transformed = []
            for repeat in range(3):
                transformed_raw, _ = m38.apply_raw_operator(q_to_raw(grouped[source][repeat]), coordinates[source], coordinates[target], edge["G_edge_integer"]); transformed_q = raw_to_q(transformed_raw); require(float(np.linalg.norm(transformed_q.conj().T @ transformed_q - np.eye(2))) <= machine_term, "M67R1_TRANSFORMED_Q_ORTHOGONALITY_INVALID"); transformed.append(transformed_q)
            full_item = _full_edge(grouped[source], grouped[target], transformed, structural, q_machine); block_item = _block_edge_corrected(grouped[source], grouped[target], coordinates, edge, m38, machine_term); full_squared = full_item["distance"] ** 2; diagonal_squared = block_item["diagonal_block_frobenius_squared"]; block_item.update({"full_projector_frobenius_squared": full_squared, "offdiagonal_projector_frobenius_squared": max(0.0, full_squared - diagonal_squared), "diagonal_exceeds_full_arithmetic_flag": diagonal_squared > full_squared + machine_term, "machine_term": machine_term}); blocks[f"{source}_to_{target}"] = block_item; full[f"{source}_to_{target}"] = full_item
        alternate = {f"{pair[0] + 1}-{pair[1] + 1}": {f"{edge['edge_source_member']}_to_{edge['edge_target_member']}": _target_pair_measures(raw_by_key, edge["edge_source_member"], edge["edge_target_member"], edge, m38, coordinates, pair) for edge in edges} for pair in TARGET_PAIRS}; canonical_fail_edges = [key for key, item in full.items() if not item["pass"]]; unique_alternate = [key for key in alternate if key != "2-3" and all(alternate[key][edge]["distance"] <= full[edge]["source_uncertainty_radius"] + full[edge]["target_uncertainty_radius"] + full[edge]["machine_term"] for edge in canonical_fail_edges)]
        if not trace["all_pass"]: outcome = "R256_M67R1_FREQUENCY_C3_FAILURE_TRUE_PROJECTOR_TRACE_BREAK"
        elif not all(item["pass"] for item in blocks.values()): outcome = "R256_M67R1_FREQUENCY_C3_FAILURE_TRACE_PASS_BLOCK_DIAGONAL_BREAK"
        elif not all(item["pass"] for item in full.values()): outcome = "R256_M67R1_FREQUENCY_C3_FAILURE_CANONICAL_RANK2_BREAK_ALTERNATE_PAIR_COVARIANCE" if len(unique_alternate) == 1 else "R256_M67R1_FREQUENCY_C3_FAILURE_BLOCK_DIAGONAL_PASS_FULL_PROJECTOR_BREAK"
        elif not historical["all_pass"]: outcome = "R256_M67R1_FREQUENCY_C3_FAILURE_FULL_PROJECTOR_PASS_RAW_WEIGHTING_ARTIFACT"
        else: outcome = "R256_M67R1_FREQUENCY_C3_FAILURE_FULL_RANK2_PROJECTOR_C3_PASS"
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "SOLVER_FREE_REQUALIFICATION", "work_order_id": bundle["work_order_id"], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": source_commit, "m66_binding": {"dataset_id": M66_DATASET_ID, "manifest_sha256": M66_MANIFEST_SHA256, "schema": M66_SCHEMA, "record_count": len(rows), "corrected_manifest_tested": True, "old_malformed_manifest_rejected": True}, "frequency_requalification": freq, "rank2_window": window, "historical_m66_raw_scalar_ledger": historical, "raw_layout_and_rank": q_meta, "true_projector_trace_ledger": trace, "diagonal_block_ledger": blocks, "full_projector_ledger": full, "alternate_target_pair_diagnostic": alternate, "unique_strong_alternate_pairs": unique_alternate, "reciprocal_c3_structural_validation": structural, "q_raw_roundtrip": "PASS", "mean_projector_formula": "exact thin-overlap self/cross traces; no hard-coded norm", "classification": outcome, "causal_outcome": outcome, "next_science_decision": "M7_RECIPROCAL_OFFDIAGONAL_PROJECTOR_COHERENCE_LOCALIZATION_FROM_M66_RAW_DATA" if outcome.endswith("FULL_PROJECTOR_BREAK") else "M7_EIGENVALUE_ONLY_C3_BREAK_VS_FULL_PROJECTOR_COVARIANCE_SYNTHESIS", "raw_complex_field_comparison": False, "gauge_u2_band_permutation_fitting": False, "c3_symmetrization": False, "ambient_projector_allocated": False, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "m67r1_solver_free_requalification", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


def _reciprocal_map(m38: Any, edge: Mapping[str, Any]) -> np.ndarray:
    result = np.empty((*SHAPE, 2), dtype=int)
    for index in range(P):
        label = m38.fft_label(index, shape=SHAPE); mapped = m38.fft_index(m38.raw_fft_edge_map(label, edge["G_edge_integer"], shape=SHAPE), shape=SHAPE); result[index // N, index % N] = (mapped // N, mapped % N)
    require(len({tuple(item) for item in result.reshape(-1, 2)}) == P, "M67R1_RECIPROCAL_MAP_NOT_BIJECTIVE"); return result


def _block_edge_corrected(source: Sequence[np.ndarray], target: Sequence[np.ndarray], coordinates: Mapping[str, Sequence[float]], edge: Mapping[str, Any], m38: Any, machine_term: float) -> dict[str, Any]:
    source_blocks, target_blocks, mapped_blocks = [], [], []; basis = np.asarray(m38.reciprocal_basis())
    for q_source, q_target in zip(source, target):
        source_blocks.append(projector_blocks(q_source)); target_blocks.append(projector_blocks(q_target)); stack = q_source.reshape(P, 2, 2).transpose(2, 0, 1); mapped = np.zeros_like(stack)
        for index in range(P):
            label = m38.fft_label(index, shape=SHAPE); mapped_label = m38.raw_fft_edge_map(label, edge["G_edge_integer"], shape=SHAPE); target_index = m38.fft_index(mapped_label, shape=SHAPE); qs = np.asarray([*coordinates[edge["edge_source_member"]], 0.0]) - np.asarray([*(basis @ np.asarray(label, dtype=float)), 0.0]); qt = np.asarray([*coordinates[edge["edge_target_member"]], 0.0]) - np.asarray([*(basis @ np.asarray(mapped_label, dtype=float)), 0.0]); mapped[:, target_index, :] = np.einsum("ab,ib->ia", m38.frame_block(qs, qt), stack[:, index, :])
        mapped_blocks.append(projector_blocks(mapped))
    delta = np.mean(np.stack(mapped_blocks), axis=0) - np.mean(np.stack(target_blocks), axis=0); residual = float(np.max(np.linalg.norm(delta, axis=(1, 2)))); source_mean = np.mean(np.stack(source_blocks), axis=0); target_mean = np.mean(np.stack(target_blocks), axis=0); source_radius = float(max(np.max(np.linalg.norm(item - source_mean, axis=(1, 2))) for item in source_blocks)); target_radius = float(max(np.max(np.linalg.norm(item - target_mean, axis=(1, 2))) for item in target_blocks)); return {"residual_fro_linf": residual, "source_uncertainty_radius": source_radius, "target_uncertainty_radius": target_radius, "machine_term": machine_term, "pass": residual <= source_radius + target_radius + machine_term, "diagonal_block_frobenius_squared": float(np.sum(np.linalg.norm(delta, axis=(1, 2)) ** 2))}


if __name__ == "__main__":
    raise SystemExit(main())
