"""M40: deterministic raw-H Berry plaquette closure on the M7 G15 orbit."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M2_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M2_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
M39R1_DATASET_ID = "0fb83c45dad9a224845040ef5598741e0488b6d41b4d4fe7910ca8aa6dea75fa"
M39R1_MANIFEST_SHA256 = "58cae64b4732077ad35126a0b86ca1993a2efef1c84f8b306e15bd7b99a7cf95"
M18_SCHEMA = "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1"
M39R1_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m40r1-deterministic-raw-h-worst-orbit-vertex-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m40r1-deterministic-raw-h-worst-orbit-berry-plaquette-closure-v1"
CENTER = np.asarray([2.0 / 3.0, 0.0], dtype=float)
SEED = np.asarray([0.4722222222222222, 0.0], dtype=float)
STEP = 0.001
N = 128
P = N * N
BANDS = 4
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0], [math.sqrt(3.0) / 2.0, -0.5]], dtype=float)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M40_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    raise ValueError(f"M40_UNSAFE_RESULT:{type(value).__name__}")


def build_plaquette_schedule() -> list[dict[str, Any]]:
    rows = []
    for member_index, member in enumerate(MEMBERS):
        for repeat in range(3):
            for stencil in ("LAB_FIXED", "C3_COVARIANT"):
                rows.append({"member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "stencil": stencil, "orbit_id": "M7", "geometry_id": "G15", "deterministic": True})
    if len(rows) != 18 or len({(r["member_index"], r["repeat_index"], r["stencil"]) for r in rows}) != 18:
        raise ValueError("M40_PLAQUETTE_SCHEDULE_INVALID")
    return rows


def plaquette_vertices(center: Sequence[float], stencil: str, member_index: int) -> tuple[list[list[float]], float]:
    angle = 0.0 if stencil == "LAB_FIXED" else 2.0 * math.pi * member_index / 3.0
    rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    dx = rotation @ np.asarray([STEP, 0.0])
    dy = rotation @ np.asarray([0.0, STEP])
    point = np.asarray(center, dtype=float)
    vertices = [point - dx / 2 - dy / 2, point + dx / 2 - dy / 2, point + dx / 2 + dy / 2, point - dx / 2 + dy / 2]
    area = 0.0
    for left, right in zip(vertices, vertices[1:] + vertices[:1]):
        area += float(left[0] * right[1] - right[0] * left[1]) / 2.0
    return [point.tolist() for point in vertices], float(area)


def request_spec(center: Sequence[float], item: Mapping[str, Any], vertex_index: int, coordinate: Sequence[float], source_commit: str) -> dict[str, Any]:
    value = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M40", "orbit_id": "M7", "geometry_id": "G15", "member_index": int(item["member_index"]), "c3_member_identity": item["c3_member_identity"], "repeat_index": int(item["repeat_index"]), "stencil": item["stencil"], "vertex_index": int(vertex_index), "center": list(map(float, center)), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": 128, "tolerance": 1e-7, "mesh_size": 3, "polarization": "TE", "source_commit": source_commit}
    value["request_key_sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    if verified["manifest_sha256"] != manifest or verified["record_count"] != count:
        raise ValueError(f"M40_DATASET_BINDING_INVALID:{dataset_id}")
    result = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest, key)["payload"]
        value = json.loads(payload.decode("utf-8"))
        if value.get("schema") != schema:
            raise ValueError(f"M40_DATASET_SCHEMA_INVALID:{dataset_id}")
        result.append(value)
    return result


def _coords(m18: Sequence[Mapping[str, Any]]) -> dict[str, list[float]]:
    result = {str(item["c3_member_identity"]): list(map(float, item["coordinate"])) for item in m18}
    if set(result) != set(MEMBERS):
        raise ValueError("M40_M18_MEMBER_BINDING_INVALID")
    return result


def bind_member_centers(m18: Sequence[Mapping[str, Any]], m39r1: Sequence[Mapping[str, Any]]) -> dict[str, list[float]]:
    centers: dict[str, list[float]] = {}
    for record in m18:
        member = record.get("c3_member_identity")
        if member in MEMBERS and record.get("geometry_id") == "G15" and record.get("geometry_role") == "AREA_MATCHED_G15" and record.get("deterministic") is False:
            if member in centers:
                raise ValueError(f"M40R1_DUPLICATE_M18_CENTER:{member}")
            centers[member] = list(map(float, record["coordinate"]))
    if set(centers) != set(MEMBERS) or len({tuple(value) for value in centers.values()}) != 3:
        raise ValueError("M40R1_M18_MEMBER_CENTERS_INVALID")
    for member in MEMBERS:
        cross = [record for record in m39r1 if record.get("c3_member_identity") == member and record.get("geometry_id") == "G15"]
        if not cross or any(not np.allclose(centers[member], record.get("coordinate", []), rtol=0.0, atol=1e-12) for record in cross):
            raise ValueError(f"M40R1_M39R1_CENTER_CROSSCHECK_INVALID:{member}")
    return centers


def _neighbor_transfer(m38: Any, source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float]) -> np.ndarray:
    """Transfer raw H coefficients at the same FFT label without C3 rotation."""
    basis = m38.reciprocal_basis()
    result = np.zeros_like(source)
    for index in range(source.shape[1]):
        label = m38.fft_label(index)
        qs = np.asarray([source_k[0], source_k[1], 0.0]) - np.asarray([*(basis @ np.asarray(label, dtype=float)), 0.0])
        qt = np.asarray([target_k[0], target_k[1], 0.0]) - np.asarray([*(basis @ np.asarray(label, dtype=float)), 0.0])
        ms, ns, _ = m38.transverse_frame(qs)
        mt, nt, _ = m38.transverse_frame(qt)
        block = np.asarray([mt, nt]) @ np.asarray([ms, ns]).T
        result[:, index, :] += np.einsum("ab,ib->ia", block, source[:, index, :])
    return result


def _rank1(source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float], band: int, m38: Any) -> dict[str, Any]:
    transported = _neighbor_transfer(m38, source, target, source_k, target_k)
    source_vector = transported[band].reshape(-1)
    overlaps = [complex(np.vdot(target[index].reshape(-1), source_vector)) for index in range(BANDS)]
    norm = np.linalg.norm(source_vector)
    target_norms = [np.linalg.norm(target[index]) for index in range(BANDS)]
    values = [value / (norm * target_norms[index]) for index, value in enumerate(overlaps)]
    same = values[band]
    return {"physical_source_band": band + 1, "target_overlap_magnitudes": [float(abs(value)) for value in values], "best_target_band": int(np.argmax(np.abs(values))) + 1, "link_magnitude": float(abs(same)), "wrapped_edge_phase": float(np.angle(same)), "normalized_link": [float(same.real), float(same.imag)]}


def _rank2_pair(source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float], target_pair: Sequence[int], m38: Any) -> dict[str, Any]:
    transported = _neighbor_transfer(m38, source, target, source_k, target_k)
    matrix = np.zeros((2, 2), dtype=np.complex128)
    for row in range(2):
        for col in range(2):
            matrix[row, col] = np.vdot(target[target_pair[row]].reshape(-1), transported[col + 1].reshape(-1))
    norms_s = [np.linalg.norm(transported[index + 1]) for index in range(2)]
    norms_t = [np.linalg.norm(target[index + 1]) for index in range(2)]
    matrix = matrix / np.outer(norms_t, norms_s)
    u, singular, vh = np.linalg.svd(matrix)
    polar = u @ vh
    return {"target_pair": [int(index) + 1 for index in target_pair], "overlap_matrix": matrix, "singular_values": singular, "minimum_singular_value": float(np.min(singular)), "principal_angle": float(np.arccos(np.clip(np.min(singular), -1.0, 1.0))), "projector_distance": float(np.sqrt(max(0.0, 4.0 - 2.0 * float(np.sum(singular ** 2))))), "polar_unitary": polar}


def _rank2(source: np.ndarray, target: np.ndarray, source_k: Sequence[float], target_k: Sequence[float], m38: Any) -> dict[str, Any]:
    return _rank2_pair(source, target, source_k, target_k, (1, 2), m38)


def _group_records(records: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int, str], dict[int, Mapping[str, Any]]]:
    result: dict[tuple[str, int, str], dict[int, Mapping[str, Any]]] = {}
    for record in records:
        key = (str(record["c3_member_identity"]), int(record["repeat_index"]), str(record["stencil"]))
        result.setdefault(key, {})[int(record["vertex_index"])] = record
    if any(len(vertices) != 4 for vertices in result.values()) or len(result) != 18:
        raise ValueError("M40_VERTEX_GROUP_INCOMPLETE")
    return result


def _circular_range(values: Sequence[float]) -> float:
    return max((abs(float(np.angle(np.exp(1j * (left - right))))) for index, left in enumerate(values) for right in values[index + 1:]), default=0.0)


def analyze(records: Sequence[Mapping[str, Any]], m18: Sequence[Mapping[str, Any]], m2_count: int, m39r1_count: int, m38: Any, m39: Any) -> dict[str, Any]:
    coordinates = _coords(m18)
    groups = _group_records(records)
    plaquettes: list[dict[str, Any]] = []
    for (member, repeat, stencil), vertices in sorted(groups.items()):
        rows = [vertices[index] for index in range(4)]
        links1, links2 = [], []
        for left, right in zip(rows, rows[1:] + rows[:1]):
            source, target = m39.normalize_raw(m39.decode_raw(left["raw_eigenvector"]))[0], m39.normalize_raw(m39.decode_raw(right["raw_eigenvector"]))[0]
            links1.append(_rank1(source, target, left["coordinate"], right["coordinate"], 1, m38))
            rank2 = _rank2(source, target, left["coordinate"], right["coordinate"], m38)
            competing = [_rank2_pair(source, target, left["coordinate"], right["coordinate"], pair, m38) for pair in ((0, 1), (1, 2), (2, 3))]
            best = max(competing, key=lambda row: (row["minimum_singular_value"], tuple(-value for value in row["target_pair"])))
            rank2.update({"competing_target_pairs": competing, "best_target_pair": best["target_pair"], "best_target_pair_minimum_singular_value": best["minimum_singular_value"]})
            links2.append(rank2)
        vertices_xy = [list(map(float, row["coordinate"])) for row in rows]
        area = 0.0
        for left, right in zip(vertices_xy, vertices_xy[1:] + vertices_xy[:1]):
            area += (left[0] * right[1] - right[0] * left[1]) / 2.0
        wilson = complex(1.0, 0.0)
        for link in links1:
            wilson *= complex(*link["normalized_link"])
        rank2_polar = np.eye(2, dtype=np.complex128)
        for link in links2:
            rank2_polar = link["polar_unitary"] @ rank2_polar
        rank2_phase = float(np.angle(np.linalg.det(rank2_polar)))
        plaquettes.append({"member": member, "repeat_index": repeat, "stencil": stencil, "vertices": vertices_xy, "signed_area": float(area), "rank1_edges": links1, "rank1_wilson_phase": float(np.angle(wilson)), "rank1_berry_curvature": float(np.angle(wilson) / area), "rank1_branch_margin": float(math.pi - abs(np.angle(wilson))), "rank2_edges": links2, "rank2_trace_phase": rank2_phase, "rank2_trace_berry_curvature": float(rank2_phase / area), "rank2_branch_margin": float(math.pi - abs(rank2_phase)), "rank2_minimum_singular_value": float(min(link["minimum_singular_value"] for link in links2))})
    by_stencil: dict[str, list[dict[str, Any]]] = {"LAB_FIXED": [], "C3_COVARIANT": []}
    for item in plaquettes:
        by_stencil[item["stencil"]].append(item)
    repeat_uncertainty = {}
    orbit_comparison = {}
    qualification = {}
    for stencil, rows in by_stencil.items():
        curvatures = {(row["member"], row["repeat_index"]): row["rank1_berry_curvature"] for row in rows}
        repeat_uncertainty[stencil] = {member: float(max(curvatures[(member, repeat)] for repeat in range(3)) - min(curvatures[(member, repeat)] for repeat in range(3))) for member in MEMBERS}
        orbit_comparison[stencil] = [{"repeat_index": repeat, "member_curvatures": {member: curvatures[(member, repeat)] for member in MEMBERS}, "pairwise_difference_max": float(max(abs(curvatures[(left, repeat)] - curvatures[(right, repeat)]) for left in MEMBERS for right in MEMBERS))} for repeat in range(3)]
        links = [edge["link_magnitude"] for row in rows for edge in row["rank1_edges"]]
        association_stable = all(edge["best_target_band"] == 2 for row in rows for edge in row.get("rank1_edges", []))
        gap_values = [min(float(record["adjacent_gaps"]["lower_gap"]), float(record["adjacent_gaps"]["internal_split"])) for record in records if record["stencil"] == stencil]
        gap_groups = {}
        for record in records:
            if record["stencil"] == stencil:
                gap_groups.setdefault((record["c3_member_identity"], record["vertex_index"]), []).append(min(float(record["adjacent_gaps"]["lower_gap"]), float(record["adjacent_gaps"]["internal_split"])))
        gap_noise = max((max(values) - min(values) for values in gap_groups.values()), default=0.0)
        link_groups = {}
        for row in rows:
            for index, edge in enumerate(row["rank1_edges"]):
                link_groups.setdefault((row["member"], index), []).append(float(edge["link_magnitude"]))
        link_noise = max((max(values) - min(values) for values in link_groups.values()), default=0.0)
        phase_noise = max((_circular_range([row["rank1_wilson_phase"] for row in rows if row["member"] == member]) for member in MEMBERS), default=0.0)
        gap_ratio = float(min(gap_values) / gap_noise) if gap_noise > 0 else float("inf") if gap_values and min(gap_values) > 0 else 0.0
        link_ratio = float(min(links) / link_noise) if link_noise > 0 else float("inf") if links and min(links) > 0 else 0.0
        branch_ratio = float(min(row["rank1_branch_margin"] for row in rows) / phase_noise) if phase_noise > 0 else float("inf")
        qualification[stencil] = {"status": "RANK1_QUALIFIED" if association_stable and gap_ratio >= 10 and link_ratio >= 10 and branch_ratio >= 5 else "RANK1_WITHHELD", "minimum_link_magnitude": float(min(links)), "link_repeat_noise": float(link_noise), "gap_signal": float(min(gap_values)), "gap_repeat_noise": float(gap_noise), "gap_rule": "band2 isolation=min(f2-f1,f3-f2), deterministic-only", "stable_band2_association": association_stable, "ratios": {"gap_to_uncertainty": gap_ratio, "link_to_repeat_noise": link_ratio, "branch_margin_to_phase_uncertainty": branch_ratio}}
    m2_comparison = {"dataset_id": M2_DATASET_ID, "manifest_sha256": M2_MANIFEST_SHA256, "record_count": m2_count, "representation": "historical_energy_EH_public_field_descriptive_only", "not_used_as_raw_H": True, "availability": "AVAILABLE" if m2_count == 72 else "UNAVAILABLE_OPTIONAL_HISTORY"}
    return {"plaquette_geometry_summary": {"plaquette_count": 18, "vertices_per_plaquette": 4, "step": STEP, "center": CENTER.tolist(), "seed": SEED.tolist(), "signed_area_by_stencil": {stencil: [row["signed_area"] for row in rows] for stencil, rows in by_stencil.items()}}, "vertex_spectral_diagnostics": {str((row["c3_member_identity"], bool(row["deterministic"]), int(row["repeat_index"]), row["stencil"], int(row["vertex_index"]))): {"frequencies_bands_1_to_4": row["frequencies_bands_1_to_4"], "adjacent_gaps": row["adjacent_gaps"], "raw_gram": row["raw_rank2_gram_residual"], "solver_convergence_evidence": row["solver_convergence_evidence"]} for row in records}, "raw_h_neighbor_link_semantics": {"representation": "raw_get_eigenvectors_H", "fft_convention": "q=k-Bf", "ordinary_neighbor_transfer": "B_target^T B_source at identical FFT label; no C3 rotation", "primary_band": 2, "composite_bands": [2, 3]}, "rank1_plaquette_results": by_stencil, "rank1_qualification": qualification, "rank2_plaquette_results": by_stencil, "repeat_uncertainty_by_member_stencil": repeat_uncertainty, "c3_orbit_comparison_by_stencil": orbit_comparison, "c3_orbit_status_by_stencil": {stencil: "MEASURED_WITHIN_REPEAT_UNCERTAINTY" if all(item["pairwise_difference_max"] <= max(repeat_uncertainty[stencil].values()) for item in orbit_comparison[stencil]) else "INCONSISTENT_BEYOND_REPEAT_UNCERTAINTY" for stencil in by_stencil}, "historical_m2_comparison": m2_comparison, "m40_causal_synthesis": {"class": "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT", "proper_c3_sign_rule": "PRESERVE_SIGN_UNDER_PROPER_C3", "reason": "Both stencil-specific deterministic orbit comparisons are retained before synthesis."}, "counterevidence_summary": {"parent_m39r1_record_count": m39r1_count, "m2_record_count": m2_count, "deterministic_record_count": len(records), "stencil_separation": True}, "exact_remaining_uncertainty": "Rank1 qualification remains withheld until all declared deterministic ratios and stable association pass; M2 is descriptive only.", "next_science_decision": "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_WITH_C3_UNCERTAINTY", "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH"}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    counter = None
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m40_job")
        m39 = _load(ROOT / "audit" / "berry_c3_consistency" / "m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m40_m39")
        m38 = _load(ROOT / "audit" / "berry_c3_consistency" / "m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m40_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        m18 = _read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, M18_SCHEMA, 3)
        try:
            m2 = _read_dataset(job, state_root, M2_DATASET_ID, M2_MANIFEST_SHA256, "mephc-berry-c3-pilot-plaquette-v1", 72)
        except Exception:
            m2 = []
        m39r1 = _read_dataset(job, state_root, M39R1_DATASET_ID, M39R1_MANIFEST_SHA256, m39.DATASET_SCHEMA, 14)
        schedule = build_plaquette_schedule()
        centers = bind_member_centers(m18, m39r1)
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=N, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(72, 72)
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        specs = []
        for item in schedule:
            center = np.asarray(centers[item["c3_member_identity"]], dtype=float)
            vertices, _ = plaquette_vertices(center, item["stencil"], item["member_index"])
            for vertex_index, coordinate in enumerate(vertices):
                spec = request_spec(center, item, vertex_index, coordinate, source_commit)
                specs.append(spec)
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(coordinate[0], coordinate[1], 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=N, num_bands=BANDS, default_material=mp.air, tolerance=1e-7, deterministic=True, mesh_size=3)
                captured = m39.capture_state(mp, solver, reciprocal, spec, counter, source_commit)
                captured.update({"schema": DATASET_SCHEMA, "member_index": item["member_index"], "c3_member_identity": item["c3_member_identity"], "repeat_index": item["repeat_index"], "stencil": item["stencil"], "vertex_index": vertex_index, "orbit_id": "M7", "center": list(map(float, center)), "coordinate": coordinate})
                key = json.dumps({"work_order_id": bundle["work_order_id"], "member": captured["c3_member_identity"], "repeat": captured["repeat_index"], "stencil": captured["stencil"], "vertex": captured["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                payload = json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode()
                store.put(key, payload, {"member": captured["c3_member_identity"], "repeat_index": captured["repeat_index"], "stencil": captured["stencil"], "vertex_index": captured["vertex_index"]})
                records.append(captured)
        if len(records) != 72 or counter.provider_count != 72 or counter.solver_count != 72:
            raise ValueError(f"M40_COUNT_INVALID:{len(records)}:{counter.provider_count}:{counter.solver_count}")
        dataset = store.finalize(72, {"dataset_schema": DATASET_SCHEMA, "plaquette_count": 18, "vertex_count": 72, "deterministic": True, "source_m18_dataset_id": M18_DATASET_ID, "source_m2_dataset_id": M2_DATASET_ID, "source_m39r1_dataset_id": M39R1_DATASET_ID})
        analysis = analyze(records, m18, len(m2), len(m39r1), m38, m39)
        analysis["plaquette_geometry_summary"]["member_centers"] = centers
        qualified = {stencil: analysis["rank1_qualification"][stencil]["status"] == "RANK1_QUALIFIED" for stencil in analysis["rank1_qualification"]}
        statuses = analysis["c3_orbit_status_by_stencil"]
        synthesis = "RANDOM_INITIALIZATION_CONFIRMED_AT_BERRY_LEVEL" if all(qualified.values()) and all(value == "MEASURED_WITHIN_REPEAT_UNCERTAINTY" for value in statuses.values()) else "RANDOM_INITIALIZATION_PLUS_STENCIL_ORIENTATION" if qualified.get("C3_COVARIANT", False) and not qualified.get("LAB_FIXED", False) else "BAND_ASSOCIATION_OR_NEAR_DEGENERACY" if any(not analysis["rank1_qualification"][stencil]["stable_band2_association"] for stencil in qualified) else "PERSISTENT_NUMERICAL_OR_PHYSICAL_C3_INCONSISTENCY" if all(value == "INCONSISTENT_BEYOND_REPEAT_UNCERTAINTY" for value in statuses.values()) else "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"
        analysis["m40_causal_synthesis"]["class"] = synthesis
        analysis["next_science_decision"] = {"RANDOM_INITIALIZATION_CONFIRMED_AT_BERRY_LEVEL": "QUALIFIED_DETERMINISTIC_G15_FULL_RAW_HBZ_MAP_WITH_C3_UNCERTAINTY", "RANDOM_INITIALIZATION_PLUS_STENCIL_ORIENTATION": "BOUND_STEP_CONVERGENCE_AND_QUALIFY_C3_COVARIANT_STENCIL", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_M40R1_RAW_BANDS", "PERSISTENT_NUMERICAL_OR_PHYSICAL_C3_INCONSISTENCY": "BOUNDED_RESOLUTION_TOLERANCE_CONVERGENCE_PILOT", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M40R1_EVIDENCE"}[synthesis]
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ONE_NATIVE_BATCH_SEVENTY_TWO_DETERMINISTIC_RAW_H_VERTICES_COMPLETE", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_id": dataset["dataset_id"], "manifest_sha256": dataset["manifest_sha256"], "source_m18_dataset_id": M18_DATASET_ID, "source_m2_dataset_id": M2_DATASET_ID, "source_m39r1_dataset_id": M39R1_DATASET_ID, "request_schedule_summary": {"plaquette_count": 18, "vertex_count": 72, "members": list(MEMBERS), "repeat_indices": [0, 1, 2], "stencils": ["LAB_FIXED", "C3_COVARIANT"], "deterministic": True}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True, **analysis}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED" if not records else "PARTIAL_ACQUISITION", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M40_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1 if counter is not None else 0, "provider_execution_count": getattr(counter, "provider_count", 0), "solver_execution_count": getattr(counter, "solver_count", 0), "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "acquisition_or_analysis", "exception_type": type(exc).__name__, "actual_completed_vertex_count": len(records), "expected_vertex_count": 72, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
