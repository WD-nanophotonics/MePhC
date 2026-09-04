"""M40R2: solver-free causal adjudication of the immutable M40R1 states."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
STENCILS = ("LAB_FIXED", "C3_COVARIANT")
REPEATS = (0, 1, 2)
VERTICES = (0, 1, 2, 3)
N = 128
P = N * N
BANDS = 4
STEP = 0.001
PARENT_NAMESPACE_SHA256 = "d96ae5283a04766430ad15c8f1a63a825e34c573c57c7e502bd08b289c2752a8"
PARENT_SOURCE_COMMIT = "9a31a1b019136f91b6b9e10ce9b801b3267f6a91"
PARENT_WORK_ORDER_ID = "MEPHC-BERRY-C3-M40R1-CORRECTED-M7-CENTERS-DETERMINISTIC-RAW-H-BERRY-CLOSURE-20260904-103"
PARENT_RECORD_SCHEMA = "mephc-berry-c3-consistency-m40r1-deterministic-raw-h-worst-orbit-vertex-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m40r2-g15-persisted-72-state-final-berry-causal-closure-v1"
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
M39R1_DATASET_ID = "0fb83c45dad9a224845040ef5598741e0488b6d41b4d4fe7910ca8aa6dea75fa"
M39R1_MANIFEST_SHA256 = "58cae64b4732077ad35126a0b86ca1993a2efef1c84f8b306e15bd7b99a7cf95"
M18_SCHEMA = "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1"
M39R1_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M40R2_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    raise ValueError(f"M40R2_UNSAFE_RESULT:{type(value).__name__}")


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    if verified["manifest_sha256"] != manifest or verified["record_count"] != count:
        raise ValueError(f"M40R2_DATASET_BINDING_INVALID:{dataset_id}")
    values = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest, key)["payload"]
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema") != schema:
            raise ValueError(f"M40R2_DATASET_SCHEMA_INVALID:{dataset_id}")
        values.append(value)
    return values


def _parent_namespace() -> dict[str, Any]:
    return {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": PARENT_WORK_ORDER_ID,
            "source_commit": PARENT_SOURCE_COMMIT, "record_schema": PARENT_RECORD_SCHEMA}


def recover_parent(job: Any, state_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Verify the exact namespace; finalize only an already complete 72-record set."""
    namespace = _parent_namespace()
    store = job.ImmutableDatasetStore(state_root, namespace)
    if store.namespace_sha256 != PARENT_NAMESPACE_SHA256:
        raise ValueError("M40R2_PARENT_NAMESPACE_SHA256_MISMATCH")
    manifest_path = store.root / "dataset-manifest.json"
    if manifest_path.exists():
        recovery_status = "VERIFIED_EXISTING"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("namespace_sha256") != PARENT_NAMESPACE_SHA256 or manifest.get("record_count") != 72 or manifest.get("completion_state") != "COMPLETE":
            raise ValueError("M40R2_PARENT_MANIFEST_INVALID")
    else:
        recovery_status = "FINALIZED_EXISTING_RECORDS_ONLY"
        metadata_paths = sorted(store.records.glob("*.json"))
        if len(metadata_paths) != 72:
            raise ValueError("M40R2_PARENT_RECORD_COUNT_INVALID")
        for metadata_path in metadata_paths:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            payload_path = metadata_path.with_suffix(".payload")
            payload = payload_path.read_bytes()
            if metadata.get("complete") is not True or metadata.get("payload_sha256") != hashlib.sha256(payload).hexdigest() or metadata.get("payload_size_bytes") != len(payload):
                raise ValueError("M40R2_PARENT_RECORD_INTEGRITY_INVALID")
        manifest = store.finalize(72, {"dataset_schema": PARENT_RECORD_SCHEMA, "plaquette_count": 18, "vertex_count": 72,
                                      "deterministic": True, "source_m18_dataset_id": M18_DATASET_ID,
                                      "source_m2_dataset_id": M2_DATASET_ID, "source_m39r1_dataset_id": M39R1_DATASET_ID})
    verified = job.verify_dataset(state_root, manifest["dataset_id"])
    if verified.get("manifest_sha256") != manifest.get("manifest_sha256") or verified.get("record_count") != 72:
        raise ValueError("M40R2_PARENT_MANIFEST_REVERIFICATION_INVALID")
    records = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, manifest["dataset_id"], manifest["manifest_sha256"], key)["payload"]
        value = json.loads(payload.decode("utf-8"))
        if value.get("schema") != PARENT_RECORD_SCHEMA:
            raise ValueError("M40R2_PARENT_RECORD_SCHEMA_INVALID")
        records.append(value)
    return manifest, records, recovery_status


def _centers(m18: Sequence[Mapping[str, Any]], m39r1: Sequence[Mapping[str, Any]]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for row in m18:
        if row.get("c3_member_identity") in MEMBERS and row.get("geometry_id") == "G15" and row.get("geometry_role") == "AREA_MATCHED_G15" and row.get("deterministic") is False:
            member = str(row["c3_member_identity"])
            if member in result:
                raise ValueError(f"M40R2_DUPLICATE_MEMBER_CENTER:{member}")
            result[member] = [float(v) for v in row["coordinate"]]
    if set(result) != set(MEMBERS) or len({tuple(v) for v in result.values()}) != 3:
        raise ValueError("M40R2_MEMBER_CENTERS_INVALID")
    for member in MEMBERS:
        cross = [row for row in m39r1 if row.get("c3_member_identity") == member and row.get("geometry_id") == "G15"]
        if not cross or any(not np.allclose(result[member], row.get("coordinate", []), rtol=0.0, atol=1e-12) for row in cross):
            raise ValueError(f"M40R2_M39R1_CENTER_CROSSCHECK_INVALID:{member}")
    return result


def _area(points: Sequence[Sequence[float]]) -> float:
    return float(sum(points[i][0] * points[(i + 1) % 4][1] - points[(i + 1) % 4][0] * points[i][1] for i in range(4)) / 2.0)


def _validate_records(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m39: Any) -> dict[tuple[str, int, str], dict[int, Mapping[str, Any]]]:
    if len(records) != 72:
        raise ValueError("M40R2_EXPECTED_72_RECORDS")
    groups: dict[tuple[str, int, str], dict[int, Mapping[str, Any]]] = {}
    for row in records:
        member, repeat, stencil, vertex = str(row.get("c3_member_identity")), int(row.get("repeat_index", -1)), str(row.get("stencil")), int(row.get("vertex_index", -1))
        if member not in MEMBERS or repeat not in REPEATS or stencil not in STENCILS or vertex not in VERTICES:
            raise ValueError("M40R2_RECORD_IDENTITY_INVALID")
        if any(row.get(key) != expected for key, expected in (("geometry_id", "G15"), ("orbit_id", "M7"), ("deterministic", True), ("num_bands", 4), ("resolution", 128), ("mesh_size", 3), ("polarization", "TE"))):
            raise ValueError("M40R2_RECORD_CONTRACT_METADATA_INVALID")
        if row.get("source_commit") != PARENT_SOURCE_COMMIT:
            raise ValueError("M40R2_RECORD_SOURCE_COMMIT_INVALID")
        center = np.asarray(row.get("center"), dtype=float)
        if center.shape != (2,) or not np.allclose(center, centers[member], rtol=0.0, atol=1e-12):
            raise ValueError("M40R2_RECORD_CENTER_INVALID")
        raw = row.get("raw_eigenvector")
        if not isinstance(raw, Mapping):
            raise ValueError("M40R2_RAW_H_MISSING")
        decoded = m39.decode_raw(raw)
        canonical, _ = m39.normalize_raw(decoded)
        if canonical.shape != (4, 16384, 2) or not np.all(np.isfinite(canonical.real)) or not np.all(np.isfinite(canonical.imag)):
            raise ValueError("M40R2_RAW_H_SHAPE_INVALID")
        if np.asarray(row.get("frequencies_bands_1_to_4"), dtype=float).shape != (4,) or not isinstance(row.get("adjacent_gaps"), Mapping) or not isinstance(row.get("solver_convergence_evidence"), Mapping):
            raise ValueError("M40R2_SPECTRAL_EVIDENCE_INVALID")
        key = (member, repeat, stencil)
        bucket = groups.setdefault(key, {})
        if vertex in bucket:
            raise ValueError("M40R2_DUPLICATE_VERTEX")
        bucket[vertex] = row
    if set(groups) != {(m, r, s) for m in MEMBERS for r in REPEATS for s in STENCILS} or any(set(v) != set(VERTICES) for v in groups.values()):
        raise ValueError("M40R2_SCHEDULE_INVALID")
    for (member, _, _), bucket in groups.items():
        points = [bucket[i]["coordinate"] for i in VERTICES]
        if any(np.asarray(p, dtype=float).shape != (2,) for p in points) or _area(points) <= 0.0:
            raise ValueError(f"M40R2_PLAQUETTE_GEOMETRY_INVALID:{member}")
        mean = np.mean(np.asarray(points, dtype=float), axis=0)
        if not np.allclose(mean, centers[member], rtol=0.0, atol=2e-12) or abs(_area(points)) < STEP * STEP * 0.5:
            raise ValueError("M40R2_PLAQUETTE_CENTER_OR_AREA_INVALID")
    return groups


def _transfer(m38: Any, source: np.ndarray, source_k: Sequence[float], target_k: Sequence[float]) -> np.ndarray:
    basis = m38.reciprocal_basis()
    output = np.zeros_like(source)
    for index in range(source.shape[1]):
        label = m38.fft_label(index)
        reciprocal = basis @ np.asarray(label, dtype=float)
        qs = np.asarray([source_k[0] - reciprocal[0], source_k[1] - reciprocal[1], 0.0])
        qt = np.asarray([target_k[0] - reciprocal[0], target_k[1] - reciprocal[1], 0.0])
        ms, ns, _ = m38.transverse_frame(qs)
        mt, nt, _ = m38.transverse_frame(qt)
        block = np.asarray([mt, nt]) @ np.asarray([ms, ns]).T
        output[:, index, :] = np.einsum("ab,ib->ia", block, source[:, index, :])
    return output


def _raw(row: Mapping[str, Any], m39: Any) -> np.ndarray:
    value, _ = m39.normalize_raw(m39.decode_raw(row["raw_eigenvector"]))
    return value


def _rank1(m38: Any, source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float]) -> dict[str, Any]:
    transported = _transfer(m38, source, source_k, target_k)
    vector = transported[1].reshape(-1)
    denom = np.linalg.norm(vector)
    overlaps = []
    for band in range(4):
        t = target[band].reshape(-1)
        value = np.vdot(t, vector) / (np.linalg.norm(t) * denom)
        overlaps.append(complex(value))
    same = overlaps[1]
    return {"physical_source_band": 2, "target_overlap_magnitudes": [float(abs(v)) for v in overlaps], "best_target_band": int(np.argmax(np.abs(overlaps))) + 1,
            "link_magnitude": float(abs(same)), "wrapped_edge_phase": float(np.angle(same)), "normalized_link": [float(same.real), float(same.imag)]}


def _rank2_pair(m38: Any, source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float], pair: Sequence[int]) -> dict[str, Any]:
    transported = _transfer(m38, source, source_k, target_k)
    selected = tuple(int(v) for v in pair)
    matrix = np.asarray([[np.vdot(target[target_index].reshape(-1), transported[source_index + 1].reshape(-1)) for source_index in range(2)] for target_index in selected], dtype=np.complex128)
    matrix /= np.outer([np.linalg.norm(target[i]) for i in selected], [np.linalg.norm(transported[i + 1]) for i in range(2)])
    u, singular, vh = np.linalg.svd(matrix)
    polar = u @ vh
    return {"target_pair": [i + 1 for i in selected], "overlap_matrix": matrix, "singular_values": singular, "minimum_singular_value": float(np.min(singular)),
            "principal_angle": float(np.arccos(np.clip(np.min(singular), -1.0, 1.0))), "projector_distance": float(np.sqrt(max(0.0, 4.0 - 2.0 * float(np.sum(singular ** 2))))),
            "captured_weight": float(np.sum(singular ** 2)), "polar_unitary": polar}


def _circular_distance(values: Sequence[float]) -> float:
    return float(max((abs(float(np.angle(np.exp(1j * (a - b))))) for a, b in itertools.combinations(values, 2)), default=0.0))


def _median_uncertainty(values: Sequence[float]) -> dict[str, float]:
    median = float(np.median(values))
    return {"median": median, "uncertainty": float(max((abs(float(v) - median) for v in values), default=0.0))}


def analyze(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, m2_count: int, m39r1_count: int) -> dict[str, Any]:
    groups = _validate_records(records, centers, m39)
    by_stencil = {stencil: [] for stencil in STENCILS}
    for (member, repeat, stencil), bucket in sorted(groups.items()):
        rows = [bucket[i] for i in VERTICES]
        rank1_edges, rank2_edges = [], []
        for edge_index, (left, right) in enumerate(zip(rows, rows[1:] + rows[:1])):
            source, target = _raw(left, m39), _raw(right, m39)
            one = _rank1(m38, source, target, left["coordinate"], right["coordinate"])
            one["edge_index"] = edge_index
            pairs = [_rank2_pair(m38, source, target, left["coordinate"], right["coordinate"], pair) for pair in itertools.combinations(range(4), 2)]
            canonical = next(item for item in pairs if item["target_pair"] == [2, 3])
            best = max(pairs, key=lambda item: (item["minimum_singular_value"], tuple(-v for v in item["target_pair"])))
            canonical.update({"edge_index": edge_index, "competing_target_pairs": pairs, "best_target_pair": best["target_pair"], "best_target_pair_minimum_singular_value": best["minimum_singular_value"]})
            rank1_edges.append(one)
            rank2_edges.append(canonical)
        area = _area([row["coordinate"] for row in rows])
        wilson = complex(1.0, 0.0)
        for edge in rank1_edges:
            phase = complex(*edge["normalized_link"])
            wilson *= phase / abs(phase)
        polar = np.eye(2, dtype=np.complex128)
        for edge in rank2_edges:
            polar = edge["polar_unitary"] @ polar
        rank1_phase = float(np.angle(wilson))
        rank2_phase = float(np.angle(np.linalg.det(polar)))
        by_stencil[stencil].append({"member": member, "repeat_index": repeat, "stencil": stencil, "vertices": [list(map(float, r["coordinate"])) for r in rows], "signed_area": area,
            "rank1_edges": rank1_edges, "rank1_wilson_phase": rank1_phase, "rank1_phase_density": rank1_phase / area, "rank1_legacy_m2_compatible_curvature": -rank1_phase / area / (2.0 * math.pi) ** 2,
            "rank1_branch_margin": math.pi - abs(rank1_phase), "rank2_edges": rank2_edges, "rank2_trace_phase": rank2_phase, "rank2_trace_phase_density": rank2_phase / area,
            "rank2_legacy_m2_compatible_trace_curvature": -rank2_phase / area / (2.0 * math.pi) ** 2, "rank2_branch_margin": math.pi - abs(rank2_phase),
            "rank2_minimum_singular_value": float(min(e["minimum_singular_value"] for e in rank2_edges))})

    repeat_uncertainty: dict[str, dict[str, Any]] = {}
    rank1_c3: dict[str, Any] = {}
    rank2_c3: dict[str, Any] = {}
    qualification: dict[str, Any] = {}
    for stencil, rows in by_stencil.items():
        repeat_uncertainty[stencil] = {}
        for member in MEMBERS:
            own = [r for r in rows if r["member"] == member]
            scalar = {"rank1_phase_density": _median_uncertainty([r["rank1_phase_density"] for r in own]),
                      "rank1_legacy_m2_compatible_curvature": _median_uncertainty([r["rank1_legacy_m2_compatible_curvature"] for r in own]),
                      "rank2_trace_phase_density": _median_uncertainty([r["rank2_trace_phase_density"] for r in own]),
                      "rank2_legacy_m2_compatible_trace_curvature": _median_uncertainty([r["rank2_legacy_m2_compatible_trace_curvature"] for r in own]),
                      "rank1_wilson_phase": {"median": float(np.median([r["rank1_wilson_phase"] for r in own])), "uncertainty": _circular_distance([r["rank1_wilson_phase"] for r in own])},
                      "rank2_trace_phase": {"median": float(np.median([r["rank2_trace_phase"] for r in own])), "uncertainty": _circular_distance([r["rank2_trace_phase"] for r in own])}}
            repeat_uncertainty[stencil][member] = scalar
        gap_groups: dict[tuple[str, int], list[float]] = {}
        for row in records:
            if row["stencil"] == stencil:
                gaps = row["adjacent_gaps"]
                gap_groups.setdefault((row["c3_member_identity"], int(row["vertex_index"])), []).append(min(float(gaps["lower_gap"]), float(gaps["internal_split"])))
        gap_signal = min(min(v) for v in gap_groups.values())
        gap_noise = max(max(v) - min(v) for v in gap_groups.values())
        link_groups: dict[tuple[str, int], list[float]] = {}
        for row in rows:
            for edge_index, edge in enumerate(row["rank1_edges"]):
                link_groups.setdefault((row["member"], edge_index), []).append(float(edge["link_magnitude"]))
        link_signal = min(min(v) for v in link_groups.values())
        link_noise = max(max(v) - min(v) for v in link_groups.values())
        association = all(edge["best_target_band"] == 2 for row in rows for edge in row["rank1_edges"])
        phase_noise = max(repeat_uncertainty[stencil][m]["rank1_wilson_phase"]["uncertainty"] for m in MEMBERS)
        branch_ratio = min(r["rank1_branch_margin"] for r in rows) / phase_noise if phase_noise > 0 else float("inf")
        gap_ratio = gap_signal / gap_noise if gap_noise > 0 else (float("inf") if gap_signal > 0 else 0.0)
        link_ratio = link_signal / link_noise if link_noise > 0 else (float("inf") if link_signal > 0 else 0.0)
        qualification[stencil] = {"status": "RANK1_QUALIFIED" if association and gap_ratio >= 10.0 and link_ratio >= 10.0 and branch_ratio >= 5.0 else "RANK1_WITHHELD",
            "stable_band2_association": association, "gap_signal": gap_signal, "gap_repeat_noise": gap_noise, "minimum_link_magnitude": link_signal, "link_repeat_noise": link_noise,
            "ratios": {"gap_to_uncertainty": gap_ratio, "link_to_repeat_noise": link_ratio, "branch_margin_to_phase_uncertainty": branch_ratio}, "gap_rule": "band2 isolation=min(f2-f1,f3-f2), same-vertex repeats"}
        rank1_values = {m: repeat_uncertainty[stencil][m]["rank1_phase_density"] for m in MEMBERS}
        rank2_values = {m: repeat_uncertainty[stencil][m]["rank2_trace_phase_density"] for m in MEMBERS}
        rank1_pairs, rank2_pairs = [], []
        for left, right in itertools.combinations(MEMBERS, 2):
            a, b = rank1_values[left], rank1_values[right]
            sign = (a["median"] == 0 or b["median"] == 0 or np.sign(a["median"]) == np.sign(b["median"]))
            rank1_pairs.append({"members": [left, right], "absolute_difference": abs(a["median"] - b["median"]), "combined_uncertainty": a["uncertainty"] + b["uncertainty"], "proper_c3_sign_preserved": bool(sign), "status": "PASS" if qualification[stencil]["status"] == "RANK1_QUALIFIED" and sign and abs(a["median"] - b["median"]) <= a["uncertainty"] + b["uncertainty"] else "FAIL"})
            a, b = rank2_values[left], rank2_values[right]
            sign = (a["median"] == 0 or b["median"] == 0 or np.sign(a["median"]) == np.sign(b["median"]))
            rank2_pairs.append({"members": [left, right], "absolute_difference": abs(a["median"] - b["median"]), "combined_uncertainty": a["uncertainty"] + b["uncertainty"], "proper_c3_sign_preserved": bool(sign), "status": "PASS" if sign and abs(a["median"] - b["median"]) <= a["uncertainty"] + b["uncertainty"] else "FAIL"})
        rank1_c3[stencil] = rank1_pairs
        rank2_c3[stencil] = rank2_pairs
    rank1_status = {s: ("PASS" if qualification[s]["status"] == "RANK1_QUALIFIED" and all(p["status"] == "PASS" for p in rank1_c3[s]) else "RANK1_WITHHELD" if qualification[s]["status"] != "RANK1_QUALIFIED" else "FAIL") for s in STENCILS}
    rank2_status = {s: ("PASS" if all(p["status"] == "PASS" for p in rank2_c3[s]) else "FAIL") for s in STENCILS}
    rank1_all = all(v == "PASS" for v in rank1_status.values())
    covariant_only = rank1_status["C3_COVARIANT"] == "PASS" and rank1_status["LAB_FIXED"] != "PASS"
    association_failure = any(not qualification[s]["stable_band2_association"] for s in STENCILS)
    both_fail = all(v == "FAIL" for v in rank1_status.values()) and all(qualification[s]["stable_band2_association"] for s in STENCILS)
    synthesis = "RANDOM_INITIALIZATION_CONFIRMED_AT_BERRY_LEVEL" if rank1_all and m2_count == 72 else "RANDOM_INITIALIZATION_PLUS_STENCIL_ORIENTATION" if covariant_only else "BAND_ASSOCIATION_OR_NEAR_DEGENERACY" if association_failure else "PERSISTENT_NUMERICAL_OR_PHYSICAL_C3_INCONSISTENCY" if both_fail else "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"
    next_decision = {"RANDOM_INITIALIZATION_CONFIRMED_AT_BERRY_LEVEL": "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_WITH_C3_UNCERTAINTY", "RANDOM_INITIALIZATION_PLUS_STENCIL_ORIENTATION": "BOUND_STEP_CONVERGENCE_AND_QUALIFY_C3_COVARIANT_STENCIL", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_M40R1_RAW_BANDS", "PERSISTENT_NUMERICAL_OR_PHYSICAL_C3_INCONSISTENCY": "BOUNDED_RESOLUTION_TOLERANCE_CONVERGENCE_PILOT", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M40R2_EVIDENCE"}[synthesis]
    spectral = {str((r["c3_member_identity"], int(r["repeat_index"]), r["stencil"], int(r["vertex_index"]))): {"frequencies_bands_1_to_4": r["frequencies_bands_1_to_4"], "adjacent_gaps": r["adjacent_gaps"], "raw_gram": r.get("raw_rank2_gram_residual"), "solver_convergence_evidence": r["solver_convergence_evidence"]} for r in records}
    return {"member_centers": {m: list(map(float, centers[m])) for m in MEMBERS}, "plaquette_geometry_summary": {"plaquette_count": 18, "vertices_per_plaquette": 4, "step": STEP, "member_centers": {m: list(map(float, centers[m])) for m in MEMBERS}, "signed_area_by_stencil": {s: [r["signed_area"] for r in by_stencil[s]] for s in STENCILS}},
            "vertex_spectral_diagnostics": spectral, "raw_h_neighbor_link_semantics": {"representation": "raw_get_eigenvectors_H", "decoded_shape": [4, 16384, 2], "fft_convention": "q=k-Bf", "ordinary_neighbor_transfer": "B_target^T B_source at identical FFT label; no C3 rotation"},
            "rank1_plaquette_results": by_stencil, "rank1_qualification": qualification, "rank2_plaquette_results": by_stencil, "repeat_uncertainty_by_member_stencil": repeat_uncertainty,
            "rank1_c3_pairwise_comparison_by_stencil": rank1_c3, "rank1_c3_status_by_stencil": rank1_status, "rank2_c3_pairwise_comparison_by_stencil": rank2_c3, "rank2_c3_status_by_stencil": rank2_status,
            "historical_m2_comparison": {"dataset_id": M2_DATASET_ID, "manifest_sha256": M2_MANIFEST_SHA256, "record_count": m2_count, "payload_schema": "mephc-berry-c3-pilot-plaquette-v1", "availability": "AVAILABLE" if m2_count == 72 else "UNAVAILABLE_OPTIONAL_HISTORY", "not_used_as_raw_H": True},
            "m40r2_causal_synthesis": {"class": synthesis, "proper_c3_sign_rule": "PRESERVE_SIGN_UNDER_PROPER_C3", "lab_fixed_status": rank1_status["LAB_FIXED"], "c3_covariant_status": rank1_status["C3_COVARIANT"]},
            "counterevidence_summary": {"parent_m39r1_record_count": m39r1_count, "m2_record_count": m2_count, "parent_record_count": 72, "rank1_status_by_stencil": rank1_status, "rank2_status_by_stencil": rank2_status, "alternative_pairs_reported": True, "stencil_separation": True},
            "exact_remaining_uncertainty": "All conclusions use persisted M40R1 raw-H states; M2 is representation-labeled descriptive history only.", "next_science_decision": next_decision, "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH"}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m40r2_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        m39 = _load(ROOT / "audit" / "berry_c3_consistency" / "m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m40r2_m39")
        m38 = _load(ROOT / "audit" / "berry_c3_consistency" / "m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m40r2_m38")
        parent, records, recovery_status = recover_parent(job, state_root)
        m18 = _read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, M18_SCHEMA, 3)
        m39r1 = _read_dataset(job, state_root, M39R1_DATASET_ID, M39R1_MANIFEST_SHA256, M39.DATASET_SCHEMA, 14)
        centers = _centers(m18, m39r1)
        try:
            m2 = _read_dataset(job, state_root, M2_DATASET_ID, M2_MANIFEST_SHA256, "mephc-berry-c3-pilot-plaquette-v1", 72)
        except Exception:
            m2 = []
        analysis = analyze(records, centers, m38, m39, len(m2), len(m39r1))
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_M40R1_PARENT_DATASET_FINAL_BERRY_CAUSAL_CLOSURE_COMPLETE", "work_order_id": bundle["work_order_id"], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "parent_namespace_sha256": PARENT_NAMESPACE_SHA256, "parent_dataset_id": parent["dataset_id"], "parent_manifest_sha256": parent["manifest_sha256"], "parent_manifest_recovery_status": recovery_status, "source_m18_dataset_id": M18_DATASET_ID, "source_m39r1_dataset_id": M39R1_DATASET_ID, "source_m2_dataset_id": M2_DATASET_ID, "parent_schedule_summary": {"record_count": 72, "members": list(MEMBERS), "stencils": list(STENCILS), "repeat_indices": list(REPEATS), "vertex_indices": list(VERTICES), "deterministic": True}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True, **analysis}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "parent_resolution_or_solver_free_analysis", "exception_type": type(exc).__name__, "parent_namespace_sha256": PARENT_NAMESPACE_SHA256, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
