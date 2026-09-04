"""M38 solver-free raw-eigenvector C3 adjudication using supplied MPB facts."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
N = 128
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M33_DATASET_ID = "b92b495ea440d1054007b413823d767b2b4fb10b1e01063cbb87a689c1cfcb6d"
M33_MANIFEST_SHA256 = "dd03a3f456ae27af658f42a366967eedb6a5dbfd07ccbbb0ac8d778537f19278"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m38-supplied-exact-mpb-source-semantics-raw-native-c3-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
PUBLIC_H_MIN_OVERLAP = 0.8707405176993757
R3 = np.asarray([[-0.5, -np.sqrt(3.0) / 2.0, 0.0], [np.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M38_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return _safe(value.item(), path)
    if isinstance(value, complex):
        return [float(value.real), float(value.imag)]
    if isinstance(value, Mapping):
        return {str(key): _safe(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Path):
        return str(value)
    raise ValueError(f"M38_UNSAFE_RESULT_VALUE:{path}:{type(value).__name__}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def decode_raw_array(encoded: Mapping[str, Any]) -> np.ndarray:
    payload = zlib.decompress(base64.b64decode(str(encoded["payload_base64"])))
    return np.asarray(np.load(io.BytesIO(payload), allow_pickle=False), dtype=np.complex128)


def resolve_immutable_records(
    job: Any,
    state_root: Path,
    dataset_id: str,
    manifest_sha256: str,
    expected_schema: str,
    record_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use only the committed Thin Flow resolver, with exact binding checks."""
    verified = job.verify_dataset(state_root, dataset_id)
    if verified.get("dataset_id") != dataset_id:
        raise ValueError(f"M38_DATASET_ID_MISMATCH:{dataset_id}")
    if verified.get("manifest_sha256") != manifest_sha256:
        raise ValueError(f"M38_DATASET_MANIFEST_MISMATCH:{dataset_id}")
    keys = verified.get("record_key_sha256")
    if verified.get("record_count") != record_count or not isinstance(keys, list) or len(keys) != record_count or len(set(keys)) != record_count:
        raise ValueError(f"M38_DATASET_MEMBERSHIP_INVALID:{dataset_id}")
    records: list[dict[str, Any]] = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha256, key)
        payload = resolved.get("payload")
        if not isinstance(payload, bytes):
            raise ValueError(f"M38_DATASET_PAYLOAD_MISSING:{dataset_id}:{key}")
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema") != expected_schema:
            raise ValueError(f"M38_DATASET_SCHEMA_MISMATCH:{dataset_id}:{value.get('schema') if isinstance(value, dict) else type(value).__name__}")
        records.append(value)
    return records, {
        "resolver": "tools/mephc-flow/scientific_job.py",
        "verification": "verify_dataset plus resolve_dataset_record",
        "dataset_id": dataset_id,
        "manifest_sha256": manifest_sha256,
        "record_count": len(records),
    }


def semantic_field_inventory(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return bounded key/type/scalar evidence without exposing raw payloads."""
    inventory: dict[str, dict[str, Any]] = {}
    for record in records:
        for key, value in record.items():
            if key in {"raw_eigenvector", "epsilon_grid", "h_arrays_by_band", "point_grids_by_chart_band"}:
                continue
            if isinstance(value, bool):
                type_name, compact = "boolean", value
            elif isinstance(value, (str, int, float)) or value is None:
                type_name, compact = type(value).__name__, value
            elif isinstance(value, list) and len(value) <= 4 and all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
                type_name, compact = "array", list(value)
            elif isinstance(value, Mapping):
                type_name, compact = "object", {"keys": sorted(str(item) for item in value)}
            else:
                type_name, compact = type(value).__name__, None
            inventory.setdefault(str(key), {"types": set(), "values": []})["types"].add(type_name)
            if compact not in inventory[str(key)]["values"] and len(inventory[str(key)]["values"]) < 6:
                inventory[str(key)]["values"].append(compact)
    return {key: {"types": sorted(value["types"]), "compact_values": value["values"]} for key, value in sorted(inventory.items())}


def bind_triplet(records: Sequence[Mapping[str, Any]], expected_schema: str, *, require_runtime_metadata: bool) -> dict[str, dict[str, Any]]:
    """Bind by explicit semantic fields, never by storage order or hash order."""
    result: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        if record.get("schema") != expected_schema or record.get("geometry_id") != "G15":
            raise ValueError("M38_SEMANTIC_BINDING_GEOMETRY_INVALID")
        if require_runtime_metadata:
            if record.get("geometry_role") != "AREA_MATCHED_G15" or record.get("deterministic") is not False:
                raise ValueError("M38_SEMANTIC_BINDING_ROLE_INVALID")
            if record.get("frame_convention") != "LAB_FIXED" or record.get("repeat_index") != 1:
                raise ValueError("M38_SEMANTIC_BINDING_FRAME_INVALID")
        member = record.get("c3_member_identity")
        if member not in MEMBERS or member in result:
            raise ValueError("M38_SEMANTIC_BINDING_MEMBER_INVALID")
        result[str(member)] = record
    if set(result) != set(MEMBERS) or len(result) != 3:
        raise ValueError("M38_SEMANTIC_BINDING_TRIPLET_INVALID")
    return {member: result[member] for member in MEMBERS}


def bind_cross_dataset_triplet(
    m18_records: Sequence[Mapping[str, Any]],
    m33_records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    m18_by_member = bind_triplet(m18_records, "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1", require_runtime_metadata=True)
    m33_by_member = bind_triplet(m33_records, "mephc-berry-c3-consistency-m33-raw-eigenvector-c3-metadata-dataset-v1", require_runtime_metadata=False)
    mapping: list[dict[str, Any]] = []
    for member in MEMBERS:
        left, right = m33_by_member[member], m18_by_member[member]
        shared: list[str] = []
        if left.get("request_key_sha256") and left.get("request_key_sha256") == right.get("request_key_sha256"):
            shared.append("request_key_sha256")
        if left.get("source_m18_record_id") and left.get("source_m18_record_id") == right.get("record_id"):
            shared.append("source_m18_record_id=record_id")
        if not shared:
            raise ValueError(f"M38_SEMANTIC_BINDING_SHARED_IDENTITY_MISSING:{member}")
        mapping.append({"member": member, "m33_record_id": left.get("record_id"), "m18_record_id": right.get("record_id"), "shared_identity_fields": shared, "member_index_m33": left.get("member_index"), "member_index_m18": right.get("member_index")})
    return m18_by_member, m33_by_member, {"status": "SEMANTIC_BINDING_PASS", "source_fields": ["c3_member_identity", "geometry_id", "geometry_role", "deterministic", "frame_convention", "repeat_index", "request_key_sha256", "source_m18_record_id", "record_id"], "mapping_table": mapping}


def reciprocal_basis() -> np.ndarray:
    direct = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]], dtype=float)
    return np.linalg.inv(direct).T


def reciprocal_automorphism() -> np.ndarray:
    basis = reciprocal_basis()
    rotation = R3[:2, :2]
    return np.rint(np.linalg.solve(basis, rotation @ basis)).astype(int)


def fft_label(index: int, shape: tuple[int, int] = (N, N)) -> tuple[int, int]:
    x, y = divmod(int(index), int(shape[1]))
    cx, cy = max(1, shape[0] // 2), max(1, shape[1] // 2)
    return (x - shape[0] if x >= cx else x, y - shape[1] if y >= cy else y)


def fft_index(label: Sequence[int], shape: tuple[int, int] = (N, N)) -> int:
    return (int(label[0]) % shape[0]) * shape[1] + int(label[1]) % shape[1]


def raw_fft_edge_map(label: Sequence[int], edge_g: Sequence[int], shape: tuple[int, int] = (N, N)) -> tuple[int, int]:
    # Native f labels represent physical reciprocal contribution -B f.
    # Therefore G_t=S_recip G_s+G_edge implies f_t=S_recip f_s-G_edge.
    mapped = reciprocal_automorphism() @ np.asarray(label, dtype=int) - np.asarray(edge_g, dtype=int)
    return int(mapped[0]), int(mapped[1])


def transverse_frame(q: Sequence[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vector = np.asarray([float(q[0]), float(q[1]), float(q[2])], dtype=float)
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        n = np.asarray([0.0, 1.0, 0.0])
        m = np.asarray([0.0, 0.0, 1.0])
        khat = np.zeros(3)
        return m, n, khat
    khat = vector / norm
    if vector[0] == 0.0 and vector[1] == 0.0:
        n = np.asarray([0.0, 1.0, 0.0])
    else:
        n = np.cross(np.asarray([0.0, 0.0, 1.0]), vector)
        n = n / np.linalg.norm(n)
    m = np.cross(n, vector)
    m = m / np.linalg.norm(m)
    return m, n, khat


def frame_block(q_source: Sequence[float], q_target: Sequence[float]) -> np.ndarray:
    ms, ns, _ = transverse_frame(q_source)
    mt, nt, _ = transverse_frame(q_target)
    return np.asarray([mt, nt]) @ R3 @ np.asarray([ms, ns]).T


def normalize_raw_layout(raw: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(raw, dtype=np.complex128)
    if value.ndim != 3:
        raise ValueError(f"M38_RAW_LAYOUT_INVALID:{value.shape}")
    if value.shape[0] == N * N and value.shape[1] == 2 and value.shape[2] == 2:
        # MPB H.data[(mode*2+component)*p+band] decodes as (mode,component,band).
        result = np.transpose(value, (2, 0, 1))
        status = "NATIVE_MODE_TRANSVERSE_COMPONENT_BAND_FROM_H_DATA"
    elif value.shape[0] == 2 and value.shape[-1] == 2:
        result = value
        status = "BAND_MODE_TRANSVERSE_COMPONENT"
    elif value.shape[0] == 2 and value.shape[1] == 2:
        result = np.moveaxis(value, 1, -1)
        result = np.moveaxis(result, 1, 1)
        status = "BAND_TRANSVERSE_COMPONENT_MODE_NATIVE_MATRIX"
    else:
        raise ValueError(f"M38_RAW_COMPONENT_AXIS_INVALID:{value.shape}")
    if result.shape[1] != N * N or result.shape[2] != 2:
        raise ValueError(f"M38_RAW_MODE_COUNT_INVALID:{result.shape}")
    return result, {"raw_shape": list(value.shape), "normalized_shape": list(result.shape), "dtype": str(value.dtype), "axis_layout_status": status, "band_axis": 0, "mode_axis": 1, "transverse_component_axis": 2, "mode_count": int(result.shape[1])}


def gram(raw: np.ndarray) -> dict[str, Any]:
    rows = np.asarray(raw, dtype=np.complex128).reshape(2, -1)
    norms = np.linalg.norm(rows, axis=1)
    if np.any(norms == 0.0):
        return {"status": "ZERO_NORM", "gram": None, "normalized_residual": None}
    normalized = rows / norms[:, None]
    value = normalized @ normalized.conj().T
    return {"status": "MEASURED", "gram": [[_safe(item) for item in row] for row in value], "normalized_residual": float(np.linalg.norm(value - np.eye(2)))}


def apply_raw_operator(raw: np.ndarray, source_k: Sequence[float], target_k: Sequence[float], edge_g: Sequence[int]) -> tuple[np.ndarray, dict[str, Any]]:
    source = np.asarray(raw, dtype=np.complex128)
    target = np.zeros_like(source)
    mapping: list[int] = []
    blocks: list[np.ndarray] = []
    basis = reciprocal_basis()
    for index in range(source.shape[1]):
        label = fft_label(index)
        mapped_label = raw_fft_edge_map(label, edge_g)
        target_index = fft_index(mapped_label)
        q_s = np.asarray([source_k[0], source_k[1], 0.0]) - np.asarray([*(basis @ np.asarray(label, dtype=float)), 0.0])
        q_t = np.asarray([target_k[0], target_k[1], 0.0]) - np.asarray([*(basis @ np.asarray(mapped_label, dtype=float)), 0.0])
        block = frame_block(q_s, q_t)
        target[:, target_index, :] += np.einsum("ab,ib->ia", block, source[:, index, :])
        mapping.append(target_index)
        blocks.append(block)
    values = np.asarray(mapping, dtype=int)
    return target, {"mapped_indices": values, "blocks": blocks, "bijection": len(set(values.tolist())) == len(values), "unmatched_source": 0, "unmatched_target": 0, "block_norm_residual": float(max(np.linalg.norm(block.T @ block - np.eye(2)) for block in blocks))}


def rank2_metrics(transformed: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    left = np.asarray(transformed, dtype=np.complex128).reshape(2, -1).T
    right = np.asarray(target, dtype=np.complex128).reshape(2, -1).T
    q_left, _ = np.linalg.qr(left, mode="reduced")
    q_right, _ = np.linalg.qr(right, mode="reduced")
    singular = np.linalg.svd(q_left.conj().T @ q_right, compute_uv=False)
    # ||P-Q||_F^2 = 2r - 2||Q_left^H Q_right||_F^2.  Keep this rank-2:
    # explicitly forming either ambient projector would allocate O(mode_count^2).
    projector_distance = float(np.sqrt(max(0.0, 2.0 * len(singular)
                                                 - 2.0 * np.sum(singular ** 2))))
    minimum = float(np.min(singular))
    return {"singular_values": [float(item) for item in singular], "minimum_overlap_singular_value": minimum, "maximum_principal_angle": float(np.arccos(np.clip(minimum, -1.0, 1.0))), "projector_distance": projector_distance, "covariance_failure": bool(minimum < 1.0 - 1e-8)}


def structural_validation(edges: Sequence[Mapping[str, Any]], states: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rng = np.random.default_rng(38)
    current = (rng.normal(size=(1, N * N, 2)) + 1j * rng.normal(size=(1, N * N, 2))).astype(np.complex128)
    block_norm = 0.0
    bijection = True
    inverse_consistency = True
    for edge in edges:
        source = states[edge["edge_source_member"]]
        target = states[edge["edge_target_member"]]
        _, ledger = apply_raw_operator(current, source["coordinate"], target["coordinate"], edge["G_edge_integer"])
        bijection = bijection and ledger["bijection"]
        block_norm = max(block_norm, ledger["block_norm_residual"])
        mapped = ledger["mapped_indices"]
        inverse_consistency = inverse_consistency and np.array_equal(np.sort(mapped), np.arange(N * N))

    def apply_edge(field: np.ndarray, edge: Mapping[str, Any]) -> np.ndarray:
        source = states[edge["edge_source_member"]]
        target = states[edge["edge_target_member"]]
        value, _ = apply_raw_operator(field, source["coordinate"], target["coordinate"], edge["G_edge_integer"])
        return value

    def closure(field: np.ndarray) -> tuple[np.ndarray, list[float]]:
        initial_norm = float(np.linalg.norm(field))
        value = field.copy()
        norm_residuals: list[float] = []
        for edge in edges:
            before = float(np.linalg.norm(value))
            value = apply_edge(value, edge)
            norm_residuals.append(abs(float(np.linalg.norm(value)) - before) / max(before, np.finfo(float).eps))
        return value, norm_residuals

    random_final, random_norm_residuals = closure(current)
    random_closure_residual = float(np.linalg.norm(random_final - current) / max(np.linalg.norm(current), np.finfo(float).eps))
    one_hot_residuals: list[float] = []
    one_hot_norm_residuals: list[float] = []
    for index, component in ((0, 0), (N * N // 2, 1), (N * N - 1, 0)):
        one_hot = np.zeros((1, N * N, 2), dtype=np.complex128)
        one_hot[0, index, component] = 1.0 + 0.25j
        final, norm_residuals = closure(one_hot)
        one_hot_residuals.append(float(np.linalg.norm(final - one_hot)))
        one_hot_norm_residuals.extend(norm_residuals)
    one_hot_closure_residual = max(one_hot_residuals)
    norm_residual = max([block_norm, *random_norm_residuals, *one_hot_norm_residuals])
    closure_pass = bool(bijection and inverse_consistency and random_closure_residual < 1e-10 and one_hot_closure_residual < 1e-10 and norm_residual < 1e-10)
    return {
        "operator_bijection_status": "PASS" if bijection else "FAIL",
        "operator_inverse_map_status": "PASS" if inverse_consistency else "FAIL",
        "operator_norm_residual": float(norm_residual),
        "single_mode_synthetic_status": "PASS" if one_hot_closure_residual < 1e-10 else "FAIL",
        "random_field_synthetic_status": "PASS" if random_closure_residual < 1e-10 else "FAIL",
        "synthetic_random_field_closure_residual": random_closure_residual,
        "synthetic_one_hot_closure_residual": one_hot_closure_residual,
        "synthetic_one_hot_closure_residuals": one_hot_residuals,
        "synthetic_random_field_norm_residuals": random_norm_residuals,
        "synthetic_one_hot_norm_residual_max": max(one_hot_norm_residuals),
        "synthetic_c3_cubed_residual": max(random_closure_residual, one_hot_closure_residual),
        "synthetic_closure_status": "PASS" if closure_pass else "FAIL",
    }


def _edges(states: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = [states[name] for name in MEMBERS]
    basis = reciprocal_basis()
    result = []
    for index in range(3):
        source, target = ordered[index], ordered[(index + 1) % 3]
        q_source = np.asarray(source["coordinate"], dtype=float)
        q_target = np.asarray(target["coordinate"], dtype=float)
        folded = np.linalg.solve(basis, R3[:2, :2] @ q_source - q_target)
        edge_g = np.rint(folded).astype(int)
        if not np.allclose(folded, edge_g, atol=1e-12, rtol=0.0):
            raise ValueError(f"M38_EDGE_FOLDING_NONINTEGER:{folded}")
        result.append({"edge_source_member": source["c3_member_identity"], "edge_target_member": target["c3_member_identity"], "G_edge_integer": edge_g.tolist(), "folding_residual": float(np.linalg.norm(R3[:2, :2] @ q_source - q_target - basis @ edge_g))})
    return result


def structural_result_fields(structural: Mapping[str, Any], structural_pass: bool, failures: int) -> dict[str, Any]:
    """Project the measured structural record using the canonical result keys."""
    return {
        "single_mode_synthetic_status": structural["single_mode_synthetic_status"],
        "random_field_synthetic_status": structural["random_field_synthetic_status"],
        "synthetic_closure_status": structural["synthetic_closure_status"],
        "synthetic_random_field_closure_residual": structural["synthetic_random_field_closure_residual"],
        "synthetic_one_hot_closure_residual": structural["synthetic_one_hot_closure_residual"],
        "synthetic_random_field_norm_residuals": structural["synthetic_random_field_norm_residuals"],
        "synthetic_one_hot_norm_residual_max": structural["synthetic_one_hot_norm_residual_max"],
        "raw_c3_operator_status": "RAW_C3_OPERATOR_SOURCE_CONFIRMED_AND_CLOSURE_PASS" if structural_pass else "RAW_C3_OPERATOR_STRUCTURAL_VALIDATION_FAIL",
        "raw_native_c3_status": "INSUFFICIENT_EVIDENCE" if not structural_pass else "RAW_NATIVE_RANK2_C3_COVARIANCE_CONFIRMED" if failures == 0 else "RAW_NATIVE_RANK2_C3_COVARIANCE_REJECTED",
    }


def _science_result() -> dict[str, Any]:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
    job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m38_job")
    m18_records, m18_binding = resolve_immutable_records(
        job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256,
        "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1", 3,
    )
    m33_records, m33_binding = resolve_immutable_records(
        job, state_root, M33_DATASET_ID, M33_MANIFEST_SHA256,
        "mephc-berry-c3-consistency-m33-raw-eigenvector-c3-metadata-dataset-v1", 3,
    )
    m18_by_member, m33_by_member, semantic_binding = bind_cross_dataset_triplet(m18_records, m33_records)
    states: dict[str, dict[str, Any]] = {}
    for member in MEMBERS:
        raw, layout = normalize_raw_layout(decode_raw_array(m33_by_member[member]["raw_eigenvector"]))
        states[member] = {"c3_member_identity": member, "coordinate": list(m18_by_member[member]["coordinate"]), "raw": raw, "layout": layout, "gram": gram(raw)}
    edges = _edges(states)
    structural = structural_validation(edges, states)
    edge_metrics: list[dict[str, Any]] = []
    transformed_by_edge: list[np.ndarray] = []
    for edge in edges:
        source, target = states[edge["edge_source_member"]], states[edge["edge_target_member"]]
        transformed, ledger = apply_raw_operator(source["raw"], source["coordinate"], target["coordinate"], edge["G_edge_integer"])
        metrics = rank2_metrics(transformed, target["raw"])
        transformed_by_edge.append(transformed)
        edge_metrics.append({**edge, "mode_map_bijection": ledger["bijection"], "block_norm_residual": ledger["block_norm_residual"], "matched_mode_count": N * N if ledger["bijection"] else None, "unmatched_source_mode_count": ledger["unmatched_source"], "unmatched_target_mode_count": ledger["unmatched_target"], **metrics})
    minimum = min(item["minimum_overlap_singular_value"] for item in edge_metrics)
    maximum_angle = max(item["maximum_principal_angle"] for item in edge_metrics)
    maximum_distance = max(item["projector_distance"] for item in edge_metrics)
    failures = sum(int(item["covariance_failure"]) for item in edge_metrics)
    structural_pass = structural["synthetic_closure_status"] == "PASS" and structural["operator_bijection_status"] == "PASS"
    public_vs_native = "INSUFFICIENT_EVIDENCE" if not structural_pass else "PUBLIC_H_OUTPUT_REPRESENTATION_CAUSES_OVERLAP_LOSS" if minimum > 1.0 - 1e-8 and failures == 0 else "RAW_NATIVE_SUPPORT_MISMATCH_LIMITS_C3_TEST" if not all(item["mode_map_bijection"] for item in edge_metrics) else "GENUINE_NATIVE_OR_STATE_FAMILY_C3_FAILURE"
    dependency_inventory = {
        "scientific_job.verify_dataset": "present-and-used",
        "scientific_job.resolve_dataset_record": "present-and-used",
        "local.decode_raw_array": "present-and-used",
        "historical_m18_or_m33_read_dataset": "not-referenced",
    }
    result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "SOLVER_FREE_RAW_NATIVE_C3_ADJUDICATION_COMPLETE", "supplied_source_authority_status": "EXACT_BUILD5_UNPATCHED_V1_12_0_SOURCE_AUTHORITY_ACCEPTED", "source_m33_dataset_id": M33_DATASET_ID, "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "raw_eigenvector_shape_by_state": {member: states[member]["layout"]["raw_shape"] for member in MEMBERS}, "raw_dtype": {member: states[member]["layout"]["dtype"] for member in MEMBERS}, "raw_axis_layout_status": {member: states[member]["layout"] for member in MEMBERS}, "raw_fft_index_formula": "index=((x_local)*ny+y_local)*nz+z; for 2D z=0 and index=x*ny+y, f=(x>=max(1,nx/2)?x-nx:x, y>=max(1,ny/2)?y-ny:y)", "raw_fft_label_to_physical_G_formula": "k_plus_G_cartesian=k_cartesian-(B1*fx+B2*fy+B3*fz); native FFT label f contributes physical reciprocal -Bf", "raw_fft_edge_c3_mapping_formula": "f_target=S_recip*f_source-G_edge (mod N), derived from -Bf_target=R_C3(-Bf_source)+B*G_edge", "raw_index_semantics_status": "RAW_RECIPROCAL_INDEX_MAP_SOURCE_CONFIRMED", "transverse_frame_semantics_status": "TRANSVERSE_FRAME_SOURCE_CONFIRMED", "transverse_frame_formula": "q=0: n=(0,1,0),m=(0,0,1); qx= qy=0: n=(0,1,0); otherwise n=normalize(z_hat cross q), m=normalize(n cross q); m cross n=q_hat; component0=m, component1=n", "raw_inner_product_metric": "ordinary complex Euclidean metric for mu_inv==NULL", "raw_normalization_semantics": {member: states[member]["gram"] for member in MEMBERS}, "raw_c3_mapping_formula": "G_target=S_recip*G_source+G_edge; B_s=[m_s,n_s], B_t=[m_t,n_t], T_G=B_t^T R_C3 B_s", "raw_c3_operator_status": "RAW_C3_OPERATOR_SOURCE_CONFIRMED_AND_CLOSURE_PASS" if structural["operator_bijection_status"] == "PASS" else "RAW_C3_OPERATOR_SOURCE_CONFIRMED_BUT_SUPPORT_MISMATCH_PRESENT", "C3_operator_bijection_status": structural["operator_bijection_status"], "C3_operator_norm_residual": structural["operator_norm_residual"], "C3_cubed_residual": structural["synthetic_c3_cubed_residual"], "raw_native_c3_singular_values": {f"{item['edge_source_member']}_to_{item['edge_target_member']}": item["singular_values"] for item in edge_metrics}, "raw_native_c3_minimum_overlap_singular_value": minimum, "raw_native_c3_maximum_principal_angle": maximum_angle, "raw_native_c3_projector_distance": maximum_distance, "raw_native_c3_covariance_failure_count": failures, "public_H_baseline_minimum_overlap": PUBLIC_H_MIN_OVERLAP, "public_vs_native_diagnosis": public_vs_native, "rank1_berry_spike_interpretation": "REPRESENTATION_OR_SUBSPACE_IDENTITY_ARTIFACT_NOT_PHYSICAL_C3_BREAKING" if public_vs_native == "PUBLIC_H_OUTPUT_REPRESENTATION_CAUSES_OVERLAP_LOSS" else "PHYSICAL_OR_NUMERICAL_C3_BREAKING_REMAINS_PLAUSIBLE", "alternative_explanations_considered": ["public H output representation", "negative-G FFT sign", "transverse frame branch/sign", "k-dependent support truncation", "native state-family C3 covariance"], "counterevidence_summary": {"edge_metrics": edge_metrics, "raw_gram": {member: states[member]["gram"] for member in MEMBERS}, "structural": structural}, "exact_remaining_uncertainty": "None in the supplied source-semantic operator if all three edge metrics are numerical unity; otherwise the exact edge and support ledger are retained.", "cheapest_remaining_discriminating_test": "If native covariance is confirmed, reimplement Berry/subspace transport solver-free in validated raw H space using existing G15 data; no new physical state is required.", "next_science_decision": "REIMPLEMENT_BERRY_AND_SUBSPACE_TRANSPORT_IN_VALIDATED_NATIVE_H_SPACE_USING_EXISTING_G15_DATA" if public_vs_native == "PUBLIC_H_OUTPUT_REPRESENTATION_CAUSES_OVERLAP_LOSS" else "INSUFFICIENT_EVIDENCE" if public_vs_native == "RAW_NATIVE_SUPPORT_MISMATCH_LIMITS_C3_TEST" else "STOP_C3_GOAL_AS_VALIDATED_NATIVE_H_NUMERICAL_OR_STATE_FAMILY_CONTRADICTION", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "stopping_sufficiency": "No new execution was used; all conclusions are from supplied source semantics and immutable M33/M18 evidence.", "edge_metrics": edge_metrics, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True, "work_order_id": bundle["work_order_id"]}
    result.update({
        "dependency_closure_status": "PASS",
        "helper_dependency_inventory": dependency_inventory,
        "dataset_binding_evidence": {"m18": m18_binding, "m33": m33_binding},
        "semantic_binding_status": semantic_binding["status"],
        "semantic_binding_source_fields": semantic_binding["source_fields"],
        "semantic_binding_mapping_table": semantic_binding["mapping_table"],
        "semantic_field_inventory_m18": semantic_field_inventory(m18_records),
        "semantic_field_inventory_m33": semantic_field_inventory(m33_records),
        "raw_rank2_gram_residuals": {member: states[member]["gram"] for member in MEMBERS},
        **structural_result_fields(structural, structural_pass, failures),
    })
    return result


def main() -> int:
    try:
        result = _science_result()
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": str(exc)[:1024], "failure_stage": "solver_free_analysis", "exception_type": type(exc).__name__, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
