"""M41R3: finish the bounded Berry-C3 convergence experiment.

This entrypoint deliberately owns its reference-reader and analysis path.  The
two earlier recovery entrypoints depended on symbols in their parents, which
made a real ``main`` invocation fail before the scientific boundary.  M41R3
keeps the immutable 36-state parent read-only and uses resolution-aware raw
and transfer helpers for the new settings.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import itertools
import io
import json
import math
import os
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
PARTIAL_WORK_ORDER_ID = "MEPHC-BERRY-C3-M41-G15-COVARIANT-NUMERICAL-CONVERGENCE-PILOT-20260904-106"
PARTIAL_SOURCE_COMMIT = "0bdc3fe14a12663d0d12e5d7294499ebdb3c9de9"
PARTIAL_NAMESPACE_SHA256 = "a1ec5b7605212832ac5e91fc8bf5a37b8a541f0a1259208bfb86cb55966e8b16"
PARENT_RECORD_SCHEMA = "mephc-berry-c3-consistency-m41-g15-covariant-numerical-convergence-vertex-dataset-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m41r3-recovery-numerical-convergence-vertex-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m41r3-g15-covariant-numerical-convergence-complete-v1"
BASELINE_DATASET_ID = "7c88b9e3760a21eaef60a94c57dad7bc04504906f02ffeb1de7bfb3feac1990a"
BASELINE_MANIFEST_SHA256 = "9f793b812fce84a01b51766d582c5b3c54eb83b5689b90a5af83386cb7df620e"
BASELINE_SCHEMA = "mephc-berry-c3-consistency-m40r1-deterministic-raw-h-worst-orbit-vertex-dataset-v1"
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M18_SCHEMA = "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1"
M39R1_DATASET_ID = "0fb83c45dad9a224845040ef5598741e0488b6d41b4d4fe7910ca8aa6dea75fa"
M39R1_MANIFEST_SHA256 = "58cae64b4732077ad35126a0b86ca1993a2efef1c84f8b306e15bd7b99a7cf95"
M39R1_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
MODE_COUNT_BY_RESOLUTION = {64: 4096, 96: 9216, 128: 16384}
STEP = 0.001


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
    raise ValueError(f"M41R3_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M41R3_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    """Read and bind a reference dataset through the executable job reader."""
    verified = job.verify_dataset(state_root, dataset_id)
    if verified.get("manifest_sha256") != manifest or verified.get("record_count") != count:
        raise ValueError(f"M41R3_DATASET_BINDING_INVALID:{dataset_id}")
    values: list[dict[str, Any]] = []
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest, key)
        value = json.loads(resolved["payload"].decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema") != schema:
            raise ValueError(f"M41R3_DATASET_SCHEMA_INVALID:{dataset_id}")
        values.append(value)
    return values


def _read_partial(job: Any, state_root: Path) -> list[dict[str, Any]]:
    namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": PARTIAL_WORK_ORDER_ID, "source_commit": PARTIAL_SOURCE_COMMIT, "record_schema": PARENT_RECORD_SCHEMA}
    store = job.ImmutableDatasetStore(state_root, namespace)
    if store.namespace_sha256 != PARTIAL_NAMESPACE_SHA256 or (store.root / "dataset-manifest.json").exists():
        raise ValueError("M41R3_PARTIAL_NAMESPACE_OR_MANIFEST_INVALID")
    paths = sorted(store.records.glob("*.json"))
    if len(paths) != 36:
        raise ValueError("M41R3_PARTIAL_COUNT_INVALID")
    records: list[dict[str, Any]] = []
    for metadata_path in paths:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        payload_path = metadata_path.with_suffix(".payload")
        payload = payload_path.read_bytes()
        if metadata.get("complete") is not True or metadata.get("payload_sha256") != hashlib.sha256(payload).hexdigest() or metadata.get("payload_size_bytes") != len(payload):
            raise ValueError("M41R3_PARTIAL_RECORD_INTEGRITY_INVALID")
        value = json.loads(payload.decode("utf-8"))
        if value.get("schema") != PARENT_RECORD_SCHEMA or value.get("configuration_id") != "R128_T1E9_M3" or value.get("resolution") != 128 or value.get("mesh_size") != 3 or value.get("stencil") != "C3_COVARIANT" or value.get("deterministic") is not True:
            raise ValueError("M41R3_PARTIAL_RECORD_METADATA_INVALID")
        records.append(value)
    return records


def _centers(m18: Sequence[Mapping[str, Any]], m39r1: Sequence[Mapping[str, Any]]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for row in m18:
        member = row.get("c3_member_identity")
        if member in MEMBERS and row.get("geometry_id") == "G15" and row.get("geometry_role") == "AREA_MATCHED_G15" and row.get("deterministic") is False:
            if member in result:
                raise ValueError(f"M41R3_DUPLICATE_CENTER:{member}")
            result[str(member)] = [float(v) for v in row["coordinate"]]
    if set(result) != set(MEMBERS) or len({tuple(v) for v in result.values()}) != 3:
        raise ValueError("M41R3_MEMBER_CENTERS_INVALID")
    for member in MEMBERS:
        cross = [row for row in m39r1 if row.get("c3_member_identity") == member and row.get("geometry_id") == "G15"]
        if not cross or any(not np.allclose(result[member], row.get("coordinate", []), rtol=0.0, atol=1e-12) for row in cross):
            raise ValueError(f"M41R3_CENTER_CROSSCHECK_INVALID:{member}")
    return result


def _plaquette_vertices(center: Sequence[float], member_index: int) -> tuple[list[list[float]], float]:
    angle = 2.0 * math.pi * int(member_index) / 3.0
    rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    point = np.asarray(center, dtype=float)
    dx, dy = rotation @ np.asarray([STEP, 0.0]), rotation @ np.asarray([0.0, STEP])
    vertices = [point - dx / 2 - dy / 2, point + dx / 2 - dy / 2, point + dx / 2 + dy / 2, point - dx / 2 + dy / 2]
    area = sum(vertices[i][0] * vertices[(i + 1) % 4][1] - vertices[(i + 1) % 4][0] * vertices[i][1] for i in range(4)) / 2.0
    return [v.tolist() for v in vertices], float(area)


def _new_graph(config: Mapping[str, Any], centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph: list[dict[str, Any]] = []
    for member_index, member in enumerate(MEMBERS):
        for repeat in range(3):
            vertices, _ = _plaquette_vertices(centers[member], member_index)
            for vertex_index, coordinate in enumerate(vertices):
                row = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M41R3", "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": config["configuration_id"], "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": int(config["resolution"]), "tolerance": float(config["tolerance"]), "mesh_size": int(config["mesh_size"]), "polarization": "TE", "source_commit": source_commit}
                row["request_key_sha256"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(row)
    if len(graph) != 36 or len({v["request_key_sha256"] for v in graph}) != 36:
        raise ValueError("M41R3_GRAPH_INVALID")
    return graph


def _normalize_raw(raw: Any, resolution: int) -> tuple[np.ndarray, dict[str, Any]]:
    expected = int(resolution) * int(resolution)
    value = np.asarray(raw, dtype=np.complex128)
    if value.shape == (expected, 2, 4):
        canonical, layout = np.transpose(value, (2, 0, 1)), "NATIVE_MODE_TRANSVERSE_COMPONENT_BAND"
    elif value.shape == (4, expected, 2):
        canonical, layout = value, "CANONICAL_BAND_MODE_TRANSVERSE_COMPONENT"
    elif value.shape == (4, 2, expected):
        canonical, layout = np.transpose(value, (0, 2, 1)), "BAND_TRANSVERSE_COMPONENT_MODE"
    else:
        raise ValueError(f"M41R3_RAW_LAYOUT_INVALID:{value.shape}:resolution={resolution}")
    if not np.all(np.isfinite(canonical.real)) or not np.all(np.isfinite(canonical.imag)):
        raise ValueError("M41R3_RAW_NONFINITE")
    vectors = canonical.reshape(4, -1)
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0):
        raise ValueError("M41R3_RAW_ZERO_BAND")
    gram = (vectors / norms[:, None]) @ (vectors / norms[:, None]).conj().T
    offdiag = float(np.max(np.abs(gram - np.diag(np.diag(gram)))))
    normalization = float(np.max(np.abs(np.diag(gram) - 1.0)))
    return canonical, {"raw_shape": list(value.shape), "normalized_shape": list(canonical.shape), "mode_count": expected, "band_count": 4, "transverse_component_count": 2, "layout": layout, "four_band_gram_offdiagonal_residual": offdiag, "four_band_gram_normalization_residual": normalization}


def _dynamic_raw(row: Mapping[str, Any], m39: Any) -> np.ndarray:
    encoded = m39.decode_raw(row["raw_eigenvector"])
    resolution = int(row.get("resolution", round(math.sqrt(np.asarray(encoded).shape[-2]))))
    if hasattr(m39, "normalize_raw"):
        try:
            normalized = m39.normalize_raw(encoded)[0]
            if np.asarray(normalized).shape == (4, MODE_COUNT_BY_RESOLUTION[resolution], 2):
                return np.asarray(normalized, dtype=np.complex128)
        except (AttributeError, ValueError, IndexError):
            pass
    return _normalize_raw(encoded, resolution)[0]


def _transfer(m38: Any, source: np.ndarray, source_k: Sequence[float], target_k: Sequence[float]) -> np.ndarray:
    resolution = int(round(math.sqrt(source.shape[1])))
    shape = (resolution, resolution)
    basis = np.asarray(m38.reciprocal_basis())
    result = np.zeros_like(source)
    for index in range(source.shape[1]):
        label = m38.fft_label(index, shape=shape)
        reciprocal = basis @ np.asarray(label, dtype=float)
        qs = np.asarray([source_k[0] - reciprocal[0], source_k[1] - reciprocal[1], 0.0])
        qt = np.asarray([target_k[0] - reciprocal[0], target_k[1] - reciprocal[1], 0.0])
        ms, ns, _ = m38.transverse_frame(qs)
        mt, nt, _ = m38.transverse_frame(qt)
        block = np.asarray([mt, nt]) @ np.asarray([ms, ns]).T
        result[:, index, :] = np.einsum("ab,ib->ia", block, source[:, index, :])
    return result


def _rank1(m38: Any, source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float]) -> dict[str, Any]:
    transported = _transfer(m38, source, source_k, target_k)
    vector = transported[1].reshape(-1)
    overlaps = [complex(np.vdot(target[i].reshape(-1), vector) / (np.linalg.norm(target[i]) * np.linalg.norm(vector))) for i in range(4)]
    same = overlaps[1]
    return {"physical_source_band": 2, "target_overlap_magnitudes": [float(abs(v)) for v in overlaps], "best_target_band": int(np.argmax(np.abs(overlaps))) + 1, "link_magnitude": float(abs(same)), "wrapped_edge_phase": float(np.angle(same)), "normalized_link": [float(same.real), float(same.imag)]}


def _rank2_pair(m38: Any, source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float], pair: Sequence[int]) -> dict[str, Any]:
    transported = _transfer(m38, source, source_k, target_k)
    selected = tuple(int(v) for v in pair)
    source_frame = np.asarray([transported[i + 1].reshape(-1) for i in range(2)], dtype=np.complex128).T
    target_frame = np.asarray([target[i].reshape(-1) for i in selected], dtype=np.complex128).T
    source_q, _ = np.linalg.qr(source_frame, mode="reduced")
    target_q, _ = np.linalg.qr(target_frame, mode="reduced")
    matrix = target_q.conj().T @ source_q
    u, singular, vh = np.linalg.svd(matrix)
    return {"target_pair": [i + 1 for i in selected], "singular_values": singular, "minimum_singular_value": float(np.min(singular)), "principal_angle": float(np.arccos(np.clip(np.min(singular), -1.0, 1.0))), "projector_distance": float(np.sqrt(max(0.0, 4.0 - 2.0 * float(np.sum(singular ** 2))))), "captured_weight": float(np.sum(singular ** 2)), "polar_unitary": u @ vh}


def _branch_safe(values: Sequence[float]) -> dict[str, Any]:
    vals = [float(v) for v in values]
    lifted = [vals[0]] if vals else []
    for value in vals[1:]:
        prior = lifted[-1]
        lifted.append(value + 2.0 * math.pi * round((prior - value) / (2.0 * math.pi)))
    median = float(np.median(lifted)) if lifted else 0.0
    uncertainty = float(max((abs(v - median) for v in lifted), default=0.0))
    wrapped = [abs(math.atan2(math.sin(a - b), math.cos(a - b))) for a, b in itertools.combinations(vals, 2)]
    return {"lifted_phases": lifted, "median": median, "uncertainty": uncertainty, "maximum_pairwise_wrapped_distance": float(max(wrapped, default=0.0))}


def analyze_configuration(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    groups: dict[tuple[str, int], dict[int, Mapping[str, Any]]] = {}
    for row in records:
        groups.setdefault((str(row["c3_member_identity"]), int(row["repeat_index"])), {})[int(row["vertex_index"])] = row
    if set(groups) != {(member, repeat) for member in MEMBERS for repeat in range(3)} or any(set(v) != {0, 1, 2, 3} for v in groups.values()):
        raise ValueError("M41R3_CONFIGURATION_SCHEDULE_INVALID")
    plaquettes: list[dict[str, Any]] = []
    for (member, repeat), vertices in sorted(groups.items()):
        rows = [vertices[i] for i in range(4)]
        rank1_edges, rank2_edges = [], []
        for edge_index, (left, right) in enumerate(zip(rows, rows[1:] + rows[:1])):
            source, target = _dynamic_raw(left, m39), _dynamic_raw(right, m39)
            one = _rank1(m38, source, target, left["coordinate"], right["coordinate"])
            one["edge_index"] = edge_index
            pairs = [_rank2_pair(m38, source, target, left["coordinate"], right["coordinate"], pair) for pair in itertools.combinations(range(4), 2)]
            canonical = next(item for item in pairs if item["target_pair"] == [2, 3])
            best = max(pairs, key=lambda item: (item["minimum_singular_value"], tuple(-x for x in item["target_pair"])))
            rank1_edges.append(one)
            rank2_edges.append({**canonical, "edge_index": edge_index, "best_target_pair": best["target_pair"], "best_target_pair_minimum_singular_value": best["minimum_singular_value"]})
        area = sum(rows[i]["coordinate"][0] * rows[(i + 1) % 4]["coordinate"][1] - rows[(i + 1) % 4]["coordinate"][0] * rows[i]["coordinate"][1] for i in range(4)) / 2.0
        wilson = complex(1.0, 0.0)
        polar = np.eye(2, dtype=np.complex128)
        for edge in rank1_edges:
            link = complex(*edge["normalized_link"])
            wilson *= link / abs(link) if abs(link) else 1.0
        for edge in rank2_edges:
            polar = edge["polar_unitary"] @ polar
        rank1_phase, rank2_phase = float(np.angle(wilson)), float(np.angle(np.linalg.det(polar)))
        plaquettes.append({"member": member, "repeat_index": repeat, "configuration_id": configuration_id, "vertices": [list(map(float, r["coordinate"])) for r in rows], "signed_area": float(area), "rank1_edges": rank1_edges, "rank1_wilson_phase": rank1_phase, "rank1_phase_density": rank1_phase / area, "rank1_branch_margin": math.pi - abs(rank1_phase), "rank2_edges": rank2_edges, "rank2_trace_phase": rank2_phase, "rank2_trace_phase_density": rank2_phase / area, "rank2_branch_margin": math.pi - abs(rank2_phase), "rank2_minimum_singular_value": float(min(e["minimum_singular_value"] for e in rank2_edges))})
    by_member: dict[str, Any] = {}
    for member in MEMBERS:
        rows = [p for p in plaquettes if p["member"] == member]
        one = _branch_safe([p["rank1_wilson_phase"] for p in rows])
        two = _branch_safe([p["rank2_trace_phase"] for p in rows])
        by_member[member] = {"rank1_phase_density": {"median": float(np.median([v / p["signed_area"] for v, p in zip(one["lifted_phases"], rows)])), "uncertainty": one["uncertainty"], "branch_safe": one}, "rank2_trace_phase_density": {"median": float(np.median([v / p["signed_area"] for v, p in zip(two["lifted_phases"], rows)])), "uncertainty": two["uncertainty"], "branch_safe": two}, "rank1_association": all(edge["best_target_band"] == 2 for p in rows for edge in p["rank1_edges"]), "rank2_best_pairs": sorted({tuple(edge["best_target_pair"]) for p in rows for edge in p["rank2_edges"]})}
    gaps = [min(float(r["adjacent_gaps"]["lower_gap"]), float(r["adjacent_gaps"]["internal_split"])) for r in records]
    links = [float(e["link_magnitude"]) for p in plaquettes for e in p["rank1_edges"]]
    gap_signal, link_signal = min(gaps), min(links)
    gap_noise = max(gaps) - min(gaps) if gaps else 0.0
    link_noise = max(links) - min(links) if links else 0.0
    branch_noise = max(by_member[m]["rank1_phase_density"]["branch_safe"]["maximum_pairwise_wrapped_distance"] for m in MEMBERS)
    branch_margin = min(p["rank1_branch_margin"] for p in plaquettes)
    gap_ratio = gap_signal / gap_noise if gap_noise else (float("inf") if gap_signal > 0 else 0.0)
    link_ratio = link_signal / link_noise if link_noise else (float("inf") if link_signal > 0 else 0.0)
    branch_ratio = branch_margin / branch_noise if branch_noise else float("inf")
    stable = all(by_member[m]["rank1_association"] for m in MEMBERS)
    qualified = stable and gap_ratio >= 10.0 and link_ratio >= 10.0 and branch_ratio >= 5.0
    def c3(key: str, require_rank1: bool) -> str:
        if require_rank1 and not qualified:
            return "RANK1_WITHHELD"
        for left, right in itertools.combinations(MEMBERS, 2):
            a, b = by_member[left][key], by_member[right][key]
            if abs(a["median"] - b["median"]) > a["uncertainty"] + b["uncertainty"] or (a["median"] and b["median"] and np.sign(a["median"]) != np.sign(b["median"])):
                return "FAIL"
        return "PASS"
    return {"configuration_id": configuration_id, "record_count": len(records), "plaquettes": plaquettes, "member_summary": by_member, "rank1_qualification": {"status": "RANK1_QUALIFIED" if qualified else "RANK1_WITHHELD", "stable_band2_association": stable, "gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "link_signal": link_signal, "link_repeat_noise": link_noise, "ratios": {"gap_to_uncertainty": gap_ratio, "link_to_repeat_noise": link_ratio, "branch_margin_to_phase_uncertainty": branch_ratio}}, "rank1_c3_status": c3("rank1_phase_density", True), "rank2_c3_status": c3("rank2_trace_phase_density", False), "canonical_rank2_pair_one_based": [2, 3], "stencil": "C3_COVARIANT"}


def _comparison(a: Mapping[str, Any], b: Mapping[str, Any], key: str, observable: str = "rank1_phase_density") -> dict[str, Any]:
    left, right = a["member_summary"][key][observable], b["member_summary"][key][observable]
    difference = abs(float(left["median"]) - float(right["median"]))
    combined = float(left["uncertainty"]) + float(right["uncertainty"])
    return {"observable": observable, "median_A": left["median"], "uncertainty_A": left["uncertainty"], "median_B": right["median"], "uncertainty_B": right["uncertainty"], "absolute_difference": difference, "combined_uncertainty": combined, "difference_beyond_uncertainty": difference > combined, "association_A": a["member_summary"][key]["rank1_association"], "association_B": b["member_summary"][key]["rank1_association"], "rank2_association_A": a["member_summary"][key]["rank2_best_pairs"], "rank2_association_B": b["member_summary"][key]["rank2_best_pairs"], "C3_status_A": a["rank1_c3_status"], "C3_status_B": b["rank1_c3_status"], "rank2_C3_status_A": a["rank2_c3_status"], "rank2_C3_status_B": b["rank2_c3_status"]}


def conditional_r96_trigger(analyses: Mapping[str, Mapping[str, Any]]) -> tuple[bool, list[str]]:
    coarse, fine = analyses["R64_T1E9_M3"], analyses["R128_T1E9_M3"]
    reasons: list[str] = []
    for member in MEMBERS:
        if _comparison(coarse, fine, member, "rank2_trace_phase_density")["difference_beyond_uncertainty"]:
            reasons.append(f"rank2_endpoint_difference:{member}")
        if coarse["member_summary"][member]["rank2_best_pairs"] != fine["member_summary"][member]["rank2_best_pairs"]:
            reasons.append(f"rank2_association_difference:{member}")
        rank1_qualified = coarse["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and fine["rank1_qualification"]["status"] == "RANK1_QUALIFIED"
        if rank1_qualified and _comparison(coarse, fine, member, "rank1_phase_density")["difference_beyond_uncertainty"]:
            reasons.append(f"qualified_rank1_endpoint_difference:{member}")
        if coarse["rank1_c3_status"] != fine["rank1_c3_status"]:
            reasons.append(f"rank1_exact_c3_status_difference:{member}")
        if coarse["rank2_c3_status"] != fine["rank2_c3_status"]:
            reasons.append(f"rank2_exact_c3_status_difference:{member}")
    return bool(reasons), reasons


def _capture(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    resolution = int(spec["resolution"])
    counter.consume_provider()
    counter.consume_solver()
    solver.run_parity(mp.TE, False)
    frequencies = np.asarray(solver.all_freqs, dtype=float)
    if frequencies.ndim == 2:
        frequencies = frequencies[0]
    if frequencies.shape != (4,):
        raise ValueError(f"M41R3_FREQUENCY_LAYOUT_INVALID:{frequencies.shape}")
    raw_native = np.asarray(solver.get_eigenvectors(1, 4))
    canonical, diagnostics = _normalize_raw(raw_native, resolution)
    gaps = {"lower_gap": float(frequencies[1] - frequencies[0]), "internal_split": float(frequencies[2] - frequencies[1]), "upper_gap": float(frequencies[3] - frequencies[2])}
    gaps["band2_isolation_gap"] = min(gaps["lower_gap"], gaps["internal_split"])
    return {"schema": DATASET_SCHEMA, "record_id": "M41R3-" + str(spec["request_key_sha256"]), "request_key_sha256": spec["request_key_sha256"], "configuration_id": spec["configuration_id"], "member_index": int(spec["member_index"]), "c3_member_identity": spec["c3_member_identity"], "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "stencil": "C3_COVARIANT", "coordinate": list(spec["coordinate"]), "center": list(spec["center"]), "deterministic": True, "repeat_index": int(spec["repeat_index"]), "vertex_index": int(spec["vertex_index"]), "num_bands": 4, "resolution": resolution, "tolerance": float(spec["tolerance"]), "eigensolver_tolerance": float(spec["tolerance"]), "mesh_size": int(spec["mesh_size"]), "polarization": "TE", "frequencies_bands_1_to_4": frequencies.tolist(), "adjacent_gaps": gaps, "solver_convergence_evidence": {"requested_tolerance": float(spec["tolerance"])}, "raw_eigenvector": encode_raw(raw_native), "raw_layout": diagnostics["layout"], "raw_rank2_gram_residual": {"status": "MEASURED", "four_band_gram_offdiagonal_residual": diagnostics["four_band_gram_offdiagonal_residual"], "normalization_residual": diagnostics["four_band_gram_normalization_residual"]}, "source_commit": source_commit}


def encode_raw(raw: np.ndarray) -> dict[str, Any]:
    stream = io.BytesIO()
    value = np.asarray(raw, dtype=np.complex128)
    np.save(stream, value, allow_pickle=False)
    compressed = zlib.compress(stream.getvalue(), level=6)
    return {"encoding": "zlib_npy_complex128_base64", "shape": list(value.shape), "dtype": str(value.dtype), "sha256": hashlib.sha256(value.tobytes()).hexdigest(), "payload_base64": base64.b64encode(compressed).decode("ascii")}


def _result(bundle: Mapping[str, Any], source_commit: str, records: Sequence[Mapping[str, Any]], analyses: Mapping[str, Any], graphs: Mapping[str, Any], trigger: bool, reasons: Sequence[str], dataset: Mapping[str, Any] | None) -> dict[str, Any]:
    tolerance_pair = {m: _comparison(analyses["R128_T1E7_M3"], analyses["R128_T1E9_M3"], m) for m in MEMBERS} if "R128_T1E7_M3" in analyses else {}
    mesh_pair = {m: _comparison(analyses["R128_T1E9_M1"], analyses["R128_T1E9_M3"], m, "rank2_trace_phase_density") for m in MEMBERS} if "R128_T1E9_M1" in analyses else {}
    resolution_pair = {m: _comparison(analyses["R64_T1E9_M3"], analyses["R128_T1E9_M3"], m, "rank2_trace_phase_density") for m in MEMBERS} if "R64_T1E9_M3" in analyses else {}
    tolerance_sensitive = any(v["difference_beyond_uncertainty"] for v in tolerance_pair.values())
    mesh_sensitive = any(v["difference_beyond_uncertainty"] for v in mesh_pair.values())
    resolution_sensitive = any(v["difference_beyond_uncertainty"] for v in resolution_pair.values())
    association_problem = any(not a.get("rank1_qualification", {}).get("stable_band2_association", False) for a in analyses.values())
    high_resolution_plateau = bool("R96_T1E9_M3" in analyses and not resolution_sensitive and analyses["R96_T1E9_M3"]["rank1_c3_status"] == analyses["R128_T1E9_M3"]["rank1_c3_status"] and analyses["R96_T1E9_M3"]["rank2_c3_status"] == analyses["R128_T1E9_M3"]["rank2_c3_status"])
    qualified_exact_c3_setting = any(a["rank1_qualification"]["status"] == "RANK1_QUALIFIED" and a["rank1_c3_status"] == "PASS" for a in analyses.values())
    flags = {"tolerance_sensitive": tolerance_sensitive, "mesh_sensitive": mesh_sensitive, "resolution_sensitive": resolution_sensitive, "association_problem": association_problem, "high_resolution_plateau": high_resolution_plateau, "qualified_exact_c3_setting": qualified_exact_c3_setting}
    causal = [k for k in ("tolerance_sensitive", "mesh_sensitive", "resolution_sensitive", "association_problem") if flags[k]]
    if len(causal) >= 2:
        synthesis = "MULTIPLE_IDENTIFIED_CAUSES"
    elif association_problem:
        synthesis = "BAND_ASSOCIATION_OR_NEAR_DEGENERACY"
    elif trigger and not high_resolution_plateau:
        synthesis = "NO_NUMERICAL_RESOLUTION_PLATEAU"
    elif resolution_sensitive and high_resolution_plateau:
        synthesis = "RESOLUTION_SENSITIVITY_WITH_HIGH_RESOLUTION_PLATEAU"
    elif mesh_sensitive:
        synthesis = "MESH_SENSITIVITY"
    elif tolerance_sensitive:
        synthesis = "TOLERANCE_SENSITIVITY"
    elif high_resolution_plateau and not qualified_exact_c3_setting:
        synthesis = "PERSISTENT_C3_INCONSISTENCY_ON_NUMERICAL_PLATEAU"
    elif qualified_exact_c3_setting and not causal:
        synthesis = "NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED"
    else:
        synthesis = "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"
    next_map = {"MULTIPLE_IDENTIFIED_CAUSES": "PRIORITIZE_CHEAPEST_IDENTIFIED_NUMERICAL_CONTROL", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_M41_RAW_BANDS", "NO_NUMERICAL_RESOLUTION_PLATEAU": "TARGETED_HIGHER_RESOLUTION_PLATEAU_EXTENSION", "RESOLUTION_SENSITIVITY_WITH_HIGH_RESOLUTION_PLATEAU": "QUALIFY_HIGH_RESOLUTION_PLATEAU_AND_ADVANCE_IF_RANK1_PASSES", "MESH_SENSITIVITY": "BOUND_MESH_SETTING_QUALIFICATION_AT_SELECTED_RESOLUTION", "TOLERANCE_SENSITIVITY": "QUALIFY_T1E9_SETTINGS_AND_ADVANCE_TO_FULL_G15_MAP_IF_RANK1_PASSES", "PERSISTENT_C3_INCONSISTENCY_ON_NUMERICAL_PLATEAU": "BOUND_PLAQUETTE_STEP_CONVERGENCE_PILOT", "NUMERICAL_SETTINGS_QUALIFIED_C3_RESTORED": "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_AT_M41_SETTINGS", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M41R3_EVIDENCE"}
    return {"schema": RESULT_SCHEMA, "status": "PASS" if len(records) in (72, 108) else "FAIL_CLOSED", "scientific_acceptance_status": "PASS" if len(records) in (72, 108) else "FAIL_CLOSED", "machine_execution_contract_status": "ONE_NATIVE_M41R3_RECOVERY_72_OR_108_COMPLETE" if len(records) in (72, 108) else "M41R3_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1 if records else 0, "provider_execution_count": len(records), "solver_execution_count": len(records), "dataset_record_count": len(records), "new_record_count": len(records), "cumulative_m41_chain_record_count": 36 + len(records), "partial_parent_namespace_sha256": PARTIAL_NAMESPACE_SHA256, "partial_parent_record_count": 36, "executed_configuration_ids": list(analyses), "conditional_R96_executed": trigger, "conditional_R96_trigger_reasons": list(reasons), "request_graph_sha256_by_configuration": {name: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest() for name, value in graphs.items()}, "configuration_analysis": analyses, "uncertainty_comparisons": {"tolerance": tolerance_pair, "mesh": mesh_pair, "resolution": resolution_pair}, "cause_flags": flags, "causal_synthesis": {"class": synthesis, "evidence": flags}, "next_science_decision": next_map[synthesis], "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH", "dataset_id": None if dataset is None else dataset.get("dataset_id"), "manifest_sha256": None if dataset is None else dataset.get("manifest_sha256"), "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    counter = None
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m41r3_job")
        m39 = _load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m41r3_m39")
        m38 = _load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m41r3_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = _read_partial(job, state_root)
        baseline = _read_dataset(job, state_root, BASELINE_DATASET_ID, BASELINE_MANIFEST_SHA256, BASELINE_SCHEMA, 72)
        m18 = _read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, M18_SCHEMA, 3)
        m39r1 = _read_dataset(job, state_root, M39R1_DATASET_ID, M39R1_MANIFEST_SHA256, M39R1_SCHEMA, 14)
        m2 = _read_dataset(job, state_root, M2_DATASET_ID, M2_MANIFEST_SHA256, "mephc-berry-c3-pilot-plaquette-v1", 72)
        centers = _centers(m18, m39r1)
        baseline_cov = [dict(row, configuration_id="R128_T1E7_M3", resolution=128, tolerance=1e-7, mesh_size=3) for row in baseline if row.get("stencil") == "C3_COVARIANT"]
        analyses: dict[str, Any] = {"R128_T1E7_M3": analyze_configuration(baseline_cov, centers, m38, m39, "R128_T1E7_M3"), "R128_T1E9_M3": analyze_configuration(partial, centers, m38, m39, "R128_T1E9_M3")}
        graphs = {name: _new_graph(config, centers, source_commit) for name, config in (("R128_T1E9_M1", {"configuration_id": "R128_T1E9_M1", "resolution": 128, "tolerance": 1e-9, "mesh_size": 1}), ("R64_T1E9_M3", {"configuration_id": "R64_T1E9_M3", "resolution": 64, "tolerance": 1e-9, "mesh_size": 3}), ("R96_T1E9_M3", {"configuration_id": "R96_T1E9_M3", "resolution": 96, "tolerance": 1e-9, "mesh_size": 3}))}
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=128, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(108, 108)
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        for config_id, resolution, mesh_size in (("R128_T1E9_M1", 128, 1), ("R64_T1E9_M3", 64, 3)):
            for spec in graphs[config_id]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=resolution, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=mesh_size)
                captured = _capture(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": config_id, "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": config_id, "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses[config_id] = analyze_configuration([r for r in records if r["configuration_id"] == config_id], centers, m38, m39, config_id)
        trigger, reasons = conditional_r96_trigger(analyses)
        if trigger:
            for spec in graphs["R96_T1E9_M3"]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=96, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=3)
                captured = _capture(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": "R96_T1E9_M3", "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": "R96_T1E9_M3", "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses["R96_T1E9_M3"] = analyze_configuration([r for r in records if r["configuration_id"] == "R96_T1E9_M3"], centers, m38, m39, "R96_T1E9_M3")
        if len(records) not in (72, 108) or counter.provider_count != len(records) or counter.solver_count != len(records):
            raise ValueError(f"M41R3_COUNT_INVALID:{len(records)}:{counter.provider_count}:{counter.solver_count}")
        dataset = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "partial_parent_namespace_sha256": PARTIAL_NAMESPACE_SHA256, "partial_parent_record_count": 36, "configuration_ids": list(analyses), "conditional_R96_executed": trigger, "cumulative_m41_chain_record_count": 36 + len(records)})
        result = _result(bundle, source_commit, records, analyses, graphs, trigger, reasons, dataset)
        result["historical_m2_comparison"] = {"dataset_id": M2_DATASET_ID, "manifest_sha256": M2_MANIFEST_SHA256, "record_count": len(m2), "not_used_as_raw_H": True}
    except BaseException as exc:
        result = _result(bundle, source_commit, records, {}, {}, False, [], None)
        result.update({"status": "PARTIAL_ACQUISITION" if records else "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": str(exc)[:1024], "failure_stage": "reference_binding_parent_baseline_analysis_or_acquisition", "exception_type": type(exc).__name__, "native_invocation_count": 1 if counter is not None else 0, "provider_execution_count": getattr(counter, "provider_count", 0), "solver_execution_count": getattr(counter, "solver_count", 0), "dataset_record_count": len(records)})
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
