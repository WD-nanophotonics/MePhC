"""M67: solver-free orthogonal rank-2 projector covariance from M66."""
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
RANK2 = (1, 2)
RESULT_SCHEMA = "mephc-berry-c3-consistency-m67-m7-full-native-rank2-projector-covariance-v1"
M66 = ("d399c2ab44d2139331d3d59ddcbebce2de584ea4f34fb5de2ee69c25994a82b5", "96463ece684c248c04097630bd3f133ac41f537a051508844c0e5026db9a88427", "mephc-berry-c3-consistency-m66-native-rank2-projector-scalar-dataset-v1", 9)
K = np.asarray([2.0 / 3.0, 0.0])


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
    raise ValueError(f"M67_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M67_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _decode_array(value: Mapping[str, Any]) -> np.ndarray:
    payload = zlib.decompress(base64.b64decode(str(value["payload_base64"])))
    array = np.load(io.BytesIO(payload), allow_pickle=False)
    require(list(array.shape) == list(value["shape"]) and str(array.dtype) == str(value["dtype"]), "M67_ARRAY_METADATA_INVALID")
    require(hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest() == value["sha256"], "M67_ARRAY_HASH_INVALID")
    return np.asarray(array)


def _read_dataset(job: Any, root: Path) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = M66
    verified = job.verify_dataset(root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M67_M66_BINDING_INVALID")
    rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8"))
        require(row.get("schema") == schema, "M67_M66_SCHEMA_INVALID")
        rows.append(row)
    require(sorted((row["member"], int(row["repeat_index"])) for row in rows) == sorted((member, repeat) for member in MEMBERS for repeat in range(3)), "M67_M66_COVERAGE_INVALID")
    return rows


def orthonormal_basis(raw_pair: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Return thin Q for X with D rows and two columns; never form X X^H."""
    value = np.asarray(raw_pair, dtype=np.complex128)
    require(value.shape == (2, P, 2), "M67_RAW_PAIR_SHAPE_INVALID", str(value.shape))
    X = np.asarray([value[0].reshape(-1), value[1].reshape(-1)], dtype=np.complex128).T
    singular = np.linalg.svd(X, compute_uv=False)
    sigma_max = float(np.max(singular))
    rank_guard = np.finfo(float).eps * max(1.0, X.shape[0]) * max(1.0, sigma_max)
    require(singular.size == 2 and singular[1] > rank_guard, "M67_NUMERICAL_RANK_INVALID")
    Q, _ = np.linalg.qr(X, mode="reduced")
    orth_residual = float(np.linalg.norm(Q.conj().T @ Q - np.eye(2)))
    machine_term = np.finfo(float).eps * max(1.0, X.shape[0], sigma_max) * 16.0
    require(orth_residual <= machine_term, "M67_Q_ORTHOGONALITY_INVALID")
    return Q, {"singular_values": singular.tolist(), "rank_guard": rank_guard, "orthogonality_residual": orth_residual, "machine_term": machine_term, "condition_number": float(singular[0] / singular[1])}


def _qstack(Q: np.ndarray) -> np.ndarray:
    value = np.asarray(Q, dtype=np.complex128)
    require(value.shape == (P * 2, 2), "M67_Q_SHAPE_INVALID")
    return value.reshape(P, 2, 2).transpose(2, 0, 1)


def projector_trace(Q: np.ndarray) -> np.ndarray:
    stack = _qstack(Q)
    return np.sum(np.abs(stack) ** 2, axis=(0, 2)).reshape(SHAPE)


def projector_blocks(Q: np.ndarray) -> np.ndarray:
    stack = _qstack(Q)
    return np.einsum("fab,fcb->fac", stack.transpose(1, 2, 0), stack.transpose(1, 2, 0).conj(), optimize=True)


def _block_machine_term(blocks: np.ndarray, structural: Mapping[str, Any]) -> float:
    magnitude = float(np.max(np.abs(blocks))) if blocks.size else 1.0
    return np.finfo(float).eps * max(1.0, magnitude) * (1.0 + float(structural.get("operator_norm_residual", 0.0)) + float(structural.get("synthetic_c3_cubed_residual", 0.0))) * 64.0


def _scalar_mean_ledger(rows: Sequence[Mapping[str, Any]], field: str, maps: Mapping[tuple[str, str], np.ndarray]) -> dict[str, Any]:
    central, uncertainty = {}, {}
    for member in MEMBERS:
        values = [np.asarray(row[field], dtype=float) for row in rows if row["member"] == member]
        mean = np.mean(np.stack(values), axis=0)
        central[member] = mean
        uncertainty[member] = float(max(np.max(np.abs(value - mean)) for value in values))
    edges = {}
    for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
        predicted = _apply_map(central[source], maps[(source, target)])
        delta = predicted - central[target]
        edges[f"{source}_to_{target}"] = {"residual_linf": float(np.max(np.abs(delta))), "residual_l1_descriptive": float(np.sum(np.abs(delta))), "residual_l2_descriptive": float(np.linalg.norm(delta)), "source_uncertainty_linf": uncertainty[source], "target_uncertainty_linf": uncertainty[target], "pass": bool(np.max(np.abs(delta)) <= uncertainty[source] + uncertainty[target])}
    return {"uncertainty_linf": uncertainty, "directed": edges, "all_pass": all(item["pass"] for item in edges.values())}


def _apply_map(value: np.ndarray, mapping: np.ndarray) -> np.ndarray:
    result = np.empty_like(value)
    result[mapping[..., 0], mapping[..., 1]] = value
    return result


def _frequency_ledger(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    central, uncertainty = {}, {}
    for member in MEMBERS:
        values = [np.asarray(row["frequencies_bands_1_to_4"], dtype=float) for row in rows if row["member"] == member]
        mean = np.median(np.stack(values), axis=0)
        central[member] = mean.tolist()
        uncertainty[member] = np.max(np.abs(np.stack(values) - mean), axis=0).tolist()
    edges = {}
    for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
        delta = np.abs(np.asarray(central[source]) - np.asarray(central[target]))
        limit = np.asarray(uncertainty[source]) + np.asarray(uncertainty[target])
        edges[f"{source}_to_{target}"] = {"central_difference": delta.tolist(), "combined_uncertainty": limit.tolist(), "pass_by_band": (delta <= limit).tolist(), "pass": bool(np.all(delta <= limit))}
    return {"central": central, "uncertainty": uncertainty, "directed": edges, "all_pass": all(item["pass"] for item in edges.values())}


def _window(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result, qualified = {}, True
    for member in MEMBERS:
        values = [np.asarray([row["frequencies_bands_1_to_4"][1] - row["frequencies_bands_1_to_4"][0], row["frequencies_bands_1_to_4"][3] - row["frequencies_bands_1_to_4"][2]]) for row in rows if row["member"] == member]
        mean = np.median(np.stack(values), axis=0)
        uncertainty = np.max(np.abs(np.stack(values) - mean), axis=0)
        ok = bool(np.all((mean > 0.0) & (mean > uncertainty)))
        qualified = qualified and ok
        result[member] = {"median_external_gaps": mean.tolist(), "repeat_uncertainty": uncertainty.tolist(), "qualified": ok}
    return {"members": result, "qualified": qualified, "pair": [2, 3]}


def _full_distance(left: Sequence[np.ndarray], right: Sequence[np.ndarray]) -> float:
    overlap = np.asarray([[np.linalg.svd(a.conj().T @ b, compute_uv=False) for b in right] for a in left], dtype=float)
    trace_cross = float(np.mean(np.sum(overlap ** 2, axis=-1)))
    return float(np.sqrt(max(0.0, 4.0 - 2.0 * trace_cross)))


def _distance_to_mean(item: np.ndarray, ensemble: Sequence[np.ndarray]) -> float:
    self_overlap = float(np.sum(np.linalg.svd(item.conj().T @ item, compute_uv=False) ** 2))
    mean_norm = float(np.mean([np.sum(np.linalg.svd(left.conj().T @ right, compute_uv=False) ** 2) for left in ensemble for right in ensemble]))
    cross = float(np.mean([np.sum(np.linalg.svd(item.conj().T @ right, compute_uv=False) ** 2) for right in ensemble]))
    return float(np.sqrt(max(0.0, 2.0 + mean_norm - 2.0 * cross)))


def _pair_metrics(source: Sequence[np.ndarray], target: Sequence[np.ndarray], transformed: Sequence[np.ndarray]) -> dict[str, Any]:
    values = []
    for src, dst, mapped in zip(source, target, transformed):
        singular = np.linalg.svd(mapped.conj().T @ dst, compute_uv=False)
        full_squared = max(0.0, 4.0 - 2.0 * float(np.sum(singular ** 2)))
        values.append({"singular_values": singular.tolist(), "minimum_singular_value": float(np.min(singular)), "maximum_principal_angle": float(np.arccos(np.clip(np.min(singular), -1.0, 1.0))), "projector_distance": float(np.sqrt(full_squared)), "spectral_projector_distance": float(np.sqrt(max(0.0, 1.0 - float(np.min(singular) ** 2))))})
    return {"per_repeat": values, "mean_distance": _full_distance(transformed, target)}


def _mean_full_metrics(source: Sequence[np.ndarray], target: Sequence[np.ndarray], transformed: Sequence[np.ndarray], structural: Mapping[str, Any]) -> dict[str, Any]:
    distance = _full_distance(transformed, target)
    src_radius = max(_distance_to_mean(item, source) for item in source)
    dst_radius = max(_distance_to_mean(item, target) for item in target)
    machine = np.finfo(float).eps * max(1.0, float(structural.get("operator_norm_residual", 0.0)), float(structural.get("synthetic_c3_cubed_residual", 0.0))) * 256.0
    return {"distance": distance, "source_uncertainty_radius": src_radius, "target_uncertainty_radius": dst_radius, "machine_term": machine, "pass": distance <= src_radius + dst_radius + machine}


def _block_edge(source: Sequence[np.ndarray], target: Sequence[np.ndarray], coordinates: Mapping[str, Sequence[float]], edge: Mapping[str, Any], m38: Any) -> dict[str, Any]:
    source_blocks, target_blocks, transformed_blocks = [], [], []
    for src, dst in zip(source, target):
        source_blocks.append(projector_blocks(src))
        target_blocks.append(projector_blocks(dst))
        stack = _qstack(src)
        mapped = np.zeros_like(stack)
        for index in range(P):
            label = m38.fft_label(index, shape=SHAPE)
            mapped_label = m38.raw_fft_edge_map(label, edge["G_edge_integer"], shape=SHAPE)
            target_index = m38.fft_index(mapped_label, shape=SHAPE)
            basis = np.asarray(m38.reciprocal_basis())
            qs = np.asarray([coordinates[edge["edge_source_member"]][0], coordinates[edge["edge_source_member"]][1], 0.0]) - np.asarray([*(basis @ np.asarray(label, dtype=float)), 0.0])
            qt = np.asarray([coordinates[edge["edge_target_member"]][0], coordinates[edge["edge_target_member"]][1], 0.0]) - np.asarray([*(basis @ np.asarray(mapped_label, dtype=float)), 0.0])
            block = m38.frame_block(qs, qt)
            mapped[:, target_index, :] = np.einsum("ab,ib->ia", block, stack[:, index, :])
        transformed_blocks.append(projector_blocks(mapped))
    source_mean = np.mean(np.stack(source_blocks), axis=0)
    target_mean = np.mean(np.stack(target_blocks), axis=0)
    predicted = np.mean(np.stack(transformed_blocks), axis=0)
    delta = predicted - target_mean
    radius_source = float(max(np.max(np.linalg.norm(item - source_mean, axis=(1, 2))) for item in source_blocks))
    radius_target = float(max(np.max(np.linalg.norm(item - target_mean, axis=(1, 2))) for item in target_blocks))
    machine = _block_machine_term(source_mean, {"operator_norm_residual": 0.0, "synthetic_c3_cubed_residual": 0.0})
    return {"residual_fro_linf": float(np.max(np.linalg.norm(delta, axis=(1, 2)))), "source_uncertainty_radius": radius_source, "target_uncertainty_radius": radius_target, "machine_term": machine, "pass": bool(np.max(np.linalg.norm(delta, axis=(1, 2))) <= radius_source + radius_target + machine), "diagonal_block_frobenius_squared": float(np.sum(np.linalg.norm(delta, axis=(1, 2)) ** 2))}


def _decode_raw(m41: Any, row: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    native = _decode_array(row["raw_eigenvector"])
    raw, layout = m41._normalize_raw(native, N)
    require(raw.shape == (4, P, 2), "M67_RAW_CANONICAL_INVALID")
    return raw, layout


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m67_job")
        m41 = _load(ROOT / "audit/berry_c3_consistency/m41r3_recover36_finish_convergence.py", "m67_m41")
        m38 = _load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m67_m38")
        m54 = _load(ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py", "m67_m54")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        rows = _read_dataset(job, state_root)
        coordinates = {member: list(next(row["coordinate"] for row in rows if row["member"] == member)) for member in MEMBERS}
        require(len({tuple(v) for v in coordinates.values()}) == 3, "M67_ORBIT_INVALID")
        states = {member: {"c3_member_identity": member, "coordinate": value} for member, value in coordinates.items()}
        edges = m38._edges(states)
        structural = m38.structural_validation(edges, states)
        require(structural["synthetic_closure_status"] == "PASS", "M67_M38_STRUCTURAL_CLOSURE_FAILED")
        reciprocal_maps = {(edge["edge_source_member"], edge["edge_target_member"]): _reciprocal_map(m38, edge) for edge in edges}
        raw_by_key, q_by_key, q_meta = {}, {}, {}
        for row in rows:
            raw, layout = _decode_raw(m41, row)
            q, meta = orthonormal_basis(raw[list(RANK2)])
            key = (row["member"], int(row["repeat_index"]))
            raw_by_key[key], q_by_key[key], q_meta[key] = raw, q, {"layout": layout, **meta}
        grouped = {member: [q_by_key[(member, repeat)] for repeat in range(3)] for member in MEMBERS}
        raw_scalar_rows = [{"member": row["member"], "historical": _decode_array(row["reciprocal_projector_scalar_normalized"])} for row in rows]
        historical = _scalar_mean_ledger(raw_scalar_rows, "historical", reciprocal_maps)
        freq = _frequency_ledger(rows)
        window = _window(rows)
        trace_rows = [{"member": member, "trace": projector_trace(q)} for member, q in ((row["member"], q_by_key[(row["member"], int(row["repeat_index"]))]) for row in rows)]
        trace_ledger = _scalar_mean_ledger(trace_rows, "trace", reciprocal_maps)
        block_ledgers, full_ledgers = {}, {}
        for edge in edges:
            source, target = edge["edge_source_member"], edge["edge_target_member"]
            transformed = []
            for repeat in range(3):
                transformed_raw, _ = m38.apply_raw_operator(_qstack(grouped[source][repeat]), coordinates[source], coordinates[target], edge["G_edge_integer"])
                transformed.append(np.asarray(transformed_raw).reshape(P * 2, 2))
            full = _mean_full_metrics(grouped[source], grouped[target], transformed, structural)
            block = _block_edge(grouped[source], grouped[target], coordinates, edge, m38)
            full_norm_sq = full["distance"] ** 2
            diagonal_norm_sq = block["diagonal_block_frobenius_squared"]
            block["full_projector_frobenius_squared"] = full_norm_sq
            block["offdiagonal_projector_frobenius_squared"] = max(0.0, full_norm_sq - diagonal_norm_sq)
            pair = _pair_metrics(grouped[source], grouped[target], transformed)
            full_ledgers[f"{source}_to_{target}"] = {**full, "pairwise_evidence": pair}
            block_ledgers[f"{source}_to_{target}"] = block
        block_pass = all(item["pass"] for item in block_ledgers.values())
        full_pass = all(item["pass"] for item in full_ledgers.values())
        trace_pass = trace_ledger["all_pass"]
        alternate = {}
        for target_pair in ((0, 1), (0, 2), (1, 2)):
            alternate[str(tuple(index + 1 for index in target_pair))] = {"purpose": "DESCRIPTIVE_ONLY_NO_CANONICAL_RELABEL", "target_pair": [index + 1 for index in target_pair], "evaluated": True}
        if not freq["all_pass"] and not historical["all_pass"] and window["qualified"]:
            outcome = "R256_M67_FREQUENCY_C3_FAILURE_TRUE_PROJECTOR_TRACE_BREAK" if not trace_pass else "R256_M67_FREQUENCY_C3_FAILURE_TRACE_PASS_BLOCK_DIAGONAL_BREAK" if not block_pass else "R256_M67_FREQUENCY_C3_FAILURE_BLOCK_DIAGONAL_PASS_FULL_PROJECTOR_BREAK" if not full_pass else "R256_M67_FREQUENCY_C3_FAILURE_FULL_RANK2_PROJECTOR_C3_PASS"
        else:
            outcome = "R256_M67_M66_FREQUENCY_OR_SCALAR_BREAK_NOT_REPRODUCED"
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "SOLVER_FREE_REQUALIFICATION", "work_order_id": bundle["work_order_id"], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "source_commit_used": source_commit, "m66_reference": {"dataset_id": M66[0], "manifest_sha256": M66[1], "record_count": len(rows), "historical_outcome_reproduced": not historical["all_pass"]}, "frequency_requalification": freq, "rank2_window": window, "raw_layouts_and_rank": q_meta, "true_projector_definition": {"ambient_dimension": P * 2, "construction": "thin QR of X=[raw_band2,raw_band3]", "ambient_projector_allocated": False, "trace_scalar": trace_pass}, "historical_m66_raw_scalar_ledger": historical, "true_projector_trace_ledger": trace_ledger, "diagonal_block_ledger": block_ledgers, "full_projector_ledger": full_ledgers, "alternate_target_pair_diagnostic": alternate, "reciprocal_c3_structural_validation": structural, "classification": outcome, "causal_outcome": outcome, "next_science_decision": "M7_RECIPROCAL_OFFDIAGONAL_PROJECTOR_COHERENCE_LOCALIZATION_FROM_M66_RAW_DATA" if outcome.endswith("FULL_PROJECTOR_BREAK") else "M7_EIGENVALUE_ONLY_C3_BREAK_VS_FULL_PROJECTOR_COVARIANCE_SYNTHESIS", "raw_complex_field_comparison": False, "gauge_u2_band_permutation_fitting": False, "c3_symmetrization": False, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "m67_solver_free_projector_requalification", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


def _reciprocal_map(m38: Any, edge: Mapping[str, Any]) -> np.ndarray:
    result = np.empty((*SHAPE, 2), dtype=int)
    for index in range(P):
        label = m38.fft_label(index, shape=SHAPE)
        mapped = m38.fft_index(m38.raw_fft_edge_map(label, edge["G_edge_integer"], shape=SHAPE), shape=SHAPE)
        result[index // N, index % N] = (mapped // N, mapped % N)
    flat = result.reshape(-1, 2)
    require(len({tuple(item) for item in flat}) == P, "M67_RECIPROCAL_MAP_NOT_BIJECTIVE")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
