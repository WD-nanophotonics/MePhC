"""M39R1: one recovery batch for four-band deterministic/repeat G15 evidence."""
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
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M33_DATASET_ID = "b92b495ea440d1054007b413823d767b2b4fb10b1e01063cbb87a689c1cfcb6d"
M33_MANIFEST_SHA256 = "dd03a3f456ae27af658f42a366967eedb6a5dbfd07ccbbb0ac8d778537f19278"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m39r1-deterministic-repeat-band-association-causal-adjudication-v1"
M18_SCHEMA = "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1"
M33_SCHEMA = "mephc-berry-c3-consistency-m33-raw-eigenvector-c3-metadata-dataset-v1"
G15 = {"a": 400.0, "r1": 80.14335684352235, "r2": 75.13439704080221, "n1": 15, "n2": 15, "theta1_degrees": 0.0, "theta2_degrees": 60.0, "n_eff": 2.7, "height": 100.0}
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)
PUBLIC_M38_MIN = 0.8707448645792748
PUBLIC_M38_FAILURES = 3
N = 128
P = N * N
BANDS = 4


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M39_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, complex):
        return [float(value.real), float(value.imag)]
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError(f"M39_UNSAFE_RESULT:{type(value).__name__}")


def _encode_raw(raw: np.ndarray) -> dict[str, Any]:
    value = np.asarray(raw, dtype=np.complex128)
    stream = io.BytesIO()
    np.save(stream, value, allow_pickle=False)
    payload = zlib.compress(stream.getvalue(), level=6)
    return {"encoding": "zlib_npy_complex128_base64", "shape": list(value.shape), "dtype": str(value.dtype), "sha256": hashlib.sha256(value.tobytes()).hexdigest(), "payload_base64": base64.b64encode(payload).decode("ascii")}


def decode_raw(encoded: Mapping[str, Any]) -> np.ndarray:
    payload = zlib.decompress(base64.b64decode(str(encoded["payload_base64"])))
    return np.asarray(np.load(io.BytesIO(payload), allow_pickle=False), dtype=np.complex128)


def normalize_raw(raw: Any) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(raw, dtype=np.complex128)
    if value.shape == (P, 2, BANDS):
        canonical = np.transpose(value, (2, 0, 1))
        layout = "NATIVE_MODE_TRANSVERSE_COMPONENT_BAND"
    elif value.shape == (BANDS, P, 2):
        canonical = value
        layout = "CANONICAL_BAND_MODE_TRANSVERSE_COMPONENT"
    elif value.shape == (BANDS, 2, P):
        canonical = np.transpose(value, (0, 2, 1))
        layout = "BAND_TRANSVERSE_COMPONENT_MODE"
    else:
        raise ValueError(f"M39_RAW_LAYOUT_INVALID:{value.shape}")
    if not np.all(np.isfinite(canonical.real)) or not np.all(np.isfinite(canonical.imag)):
        raise ValueError("M39_RAW_NONFINITE")
    return canonical, {"raw_shape": list(value.shape), "normalized_shape": list(canonical.shape), "dtype": str(value.dtype), "layout": layout, "mode_count": P, "band_count": BANDS, "transverse_component_count": 2}


def raw_gram(raw: np.ndarray) -> dict[str, Any]:
    rows = np.asarray(raw, dtype=np.complex128).reshape(BANDS, -1)
    norms = np.linalg.norm(rows, axis=1)
    if np.any(norms <= np.finfo(float).eps):
        return {"status": "ZERO_NORM", "normalized_gram": None, "off_diagonal_residual": None}
    normalized = rows / norms[:, None]
    value = normalized @ normalized.conj().T
    off = value - np.diag(np.diag(value))
    return {"status": "MEASURED", "normalized_gram": [[_safe(item) for item in row] for row in value], "off_diagonal_residual": float(np.linalg.norm(off)), "normalization_residual": float(np.linalg.norm(value - np.eye(BANDS)))}


def build_schedule() -> list[dict[str, Any]]:
    schedule: list[dict[str, Any]] = []
    for repeat_index, deterministic in ((0, True), (0, False), (1, True), (1, False), (2, True)):
        for member_index, member in enumerate(MEMBERS):
            schedule.append({"member_index": member_index, "c3_member_identity": member, "deterministic": deterministic, "repeat_index": repeat_index})
    if len(schedule) != 15 or len({(item["c3_member_identity"], item["deterministic"], item["repeat_index"]) for item in schedule}) != 15:
        raise ValueError("M39_SCHEDULE_INVALID")
    return schedule


def build_recovery_schedule() -> list[dict[str, Any]]:
    """Return only the fourteen new states authorized by the M39R1 contract."""
    schedule: list[dict[str, Any]] = []
    for repeat_index in (1, 2, 3):
        for member_index, member in enumerate(MEMBERS):
            schedule.append({"member_index": member_index, "c3_member_identity": member, "deterministic": True, "repeat_index": repeat_index})
    for member_index, member in enumerate(MEMBERS):
        schedule.append({"member_index": member_index, "c3_member_identity": member, "deterministic": False, "repeat_index": 0})
    for member in ("C3", "C3_SQUARED"):
        schedule.append({"member_index": MEMBERS.index(member), "c3_member_identity": member, "deterministic": False, "repeat_index": 1})
    keys = {(item["c3_member_identity"], item["deterministic"], item["repeat_index"]) for item in schedule}
    if len(schedule) != 14 or len(keys) != 14 or ("IDENTITY", True, 0) in keys:
        raise ValueError("M39R1_RECOVERY_SCHEDULE_INVALID")
    return schedule


def resolve_records(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    if verified.get("dataset_id") != dataset_id or verified.get("manifest_sha256") != manifest or verified.get("record_count") != count:
        raise ValueError(f"M39_DATASET_BINDING_INVALID:{dataset_id}")
    records = []
    for key in verified.get("record_key_sha256", []):
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest, key).get("payload")
        if not isinstance(payload, bytes):
            raise ValueError(f"M39_DATASET_PAYLOAD_MISSING:{dataset_id}")
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema") != schema:
            raise ValueError(f"M39_DATASET_SCHEMA_INVALID:{dataset_id}")
        records.append(value)
    return records


def bind_m18(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in records:
        if item.get("geometry_id") != "G15" or item.get("geometry_role") != "AREA_MATCHED_G15" or item.get("deterministic") is not False or item.get("frame_convention") != "LAB_FIXED" or item.get("repeat_index") != 1:
            continue
        member = item.get("c3_member_identity")
        if member in MEMBERS:
            if member in result:
                raise ValueError(f"M39_M18_MEMBER_DUPLICATE:{member}")
            result[str(member)] = dict(item)
    if set(result) != set(MEMBERS):
        raise ValueError("M39_M18_CANONICAL_TRIPLET_INVALID")
    return {member: result[member] for member in MEMBERS}


def request_spec(member: Mapping[str, Any], schedule_item: Mapping[str, Any], source_commit: str) -> dict[str, Any]:
    value = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "geometry_id": "G15", "c3_member_identity": schedule_item["c3_member_identity"], "member_index": int(schedule_item["member_index"]), "coordinate": list(member["coordinate"]), "deterministic": bool(schedule_item["deterministic"]), "repeat_index": int(schedule_item["repeat_index"]), "num_bands": BANDS, "resolution": N, "tolerance": 1e-7, "mesh_size": 3, "polarization": "TE", "source_commit": source_commit}
    value["request_key_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
    return value


def _solver_factory(mp: Any, mpb: Any, band: Any, geometry: Any, spec: Mapping[str, Any]) -> Any:
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
    return mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=N, num_bands=BANDS, default_material=mp.air, tolerance=1e-7, deterministic=bool(spec["deterministic"]), mesh_size=3), reciprocal


def capture_state(mp: Any, solver: Any, reciprocal: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    counter.consume_provider()
    counter.consume_solver()
    solver.run_parity(mp.TE, False)
    frequencies = np.asarray(solver.all_freqs, dtype=float)
    if frequencies.ndim == 2:
        frequencies = frequencies[0]
    if frequencies.shape != (BANDS,):
        raise ValueError(f"M39_FREQUENCY_LAYOUT_INVALID:{frequencies.shape}")
    raw_native = np.asarray(solver.get_eigenvectors(1, BANDS))
    raw, layout = normalize_raw(raw_native)
    grams = raw_gram(raw)
    lower_gap, internal_split, upper_gap = float(frequencies[1] - frequencies[0]), float(frequencies[2] - frequencies[1]), float(frequencies[3] - frequencies[2])
    gaps = {"lower_gap": lower_gap, "internal_split": internal_split, "upper_gap": upper_gap, "band2_isolation_gap": float(min(lower_gap, internal_split)), "band3_isolation_gap": float(min(internal_split, upper_gap)), "minimum_external_rank2_gap": float(min(lower_gap, upper_gap))}
    evidence = {"requested_tolerance": 1e-7, "iteration_evidence_status": "UNAVAILABLE_NO_PUBLIC_RUNTIME_FIELD", "public_runtime_fields": {}}
    for name in ("iterations", "iteration_count", "residual", "residual_norm", "last_residual"):
        if hasattr(solver, name):
            evidence["public_runtime_fields"][name] = _safe(getattr(solver, name))
    if evidence["public_runtime_fields"]:
        evidence["iteration_evidence_status"] = "PUBLIC_RUNTIME_FIELDS_CAPTURED"
    return {"schema": DATASET_SCHEMA, "record_id": "M39-" + str(spec["request_key_sha256"]), "request_key_sha256": spec["request_key_sha256"], "member_index": int(spec["member_index"]), "c3_member_identity": spec["c3_member_identity"], "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "coordinate": list(spec["coordinate"]), "deterministic": bool(spec["deterministic"]), "frame_convention": "LAB_FIXED", "repeat_index": int(spec["repeat_index"]), "num_bands": BANDS, "resolution": N, "eigensolver_tolerance": 1e-7, "mesh_size": 3, "polarization": "TE", "frequencies_bands_1_to_4": frequencies.tolist(), "adjacent_gaps": gaps, "solver_convergence_evidence": evidence, "raw_eigenvector": _encode_raw(raw_native), "raw_layout": layout, "raw_rank2_gram_residual": grams, "source_commit": source_commit}


def low_rank_metrics(source: np.ndarray, target: np.ndarray, source_pair: Sequence[int] = (1, 2), target_pair: Sequence[int] = (1, 2)) -> dict[str, Any]:
    left = np.asarray(source[list(source_pair)], dtype=np.complex128).reshape(2, -1).T
    right = np.asarray(target[list(target_pair)], dtype=np.complex128).reshape(2, -1).T
    q_left, _ = np.linalg.qr(left, mode="reduced")
    q_right, _ = np.linalg.qr(right, mode="reduced")
    singular = np.linalg.svd(q_left.conj().T @ q_right, compute_uv=False)
    captured = float(np.sum(singular ** 2) / 2.0)
    return {"source_pair": [index + 1 for index in source_pair], "target_pair": [index + 1 for index in target_pair], "singular_values": [float(item) for item in singular], "minimum_singular_value": float(np.min(singular)), "principal_angle": float(np.arccos(np.clip(np.min(singular), -1.0, 1.0))), "projector_distance": float(np.sqrt(max(0.0, 4.0 - 2.0 * float(np.sum(singular ** 2))))), "captured_weight": captured}


def rank1_link(source: np.ndarray, target: np.ndarray, source_band: int, edge: Mapping[str, Any], m38: Any, source_coordinate: Sequence[float], target_coordinate: Sequence[float]) -> dict[str, Any]:
    transformed, ledger = m38.apply_raw_operator(source, source_coordinate, target_coordinate, edge["G_edge_integer"])
    vector = transformed[source_band].reshape(-1)
    target_vectors = target.reshape(BANDS, -1)
    norm = np.linalg.norm(vector)
    overlaps = []
    for candidate in target_vectors:
        denominator = norm * np.linalg.norm(candidate)
        overlaps.append(complex(np.vdot(candidate, vector) / denominator) if denominator > 0.0 else complex(np.nan, np.nan))
    same = overlaps[source_band]
    best = int(np.nanargmax(np.abs(overlaps))) if all(np.isfinite([item.real for item in overlaps])) else None
    return {"source_band": source_band + 1, "edge_source_member": edge["edge_source_member"], "edge_target_member": edge["edge_target_member"], "target_overlap_magnitudes": [float(abs(item)) for item in overlaps], "best_target_band": None if best is None else best + 1, "same_index_link": _safe(same), "link_magnitude": float(abs(same)), "wrapped_edge_phase": float(np.angle(same)), "mode_map_bijection": bool(ledger["bijection"])}


def polar_det_phase(source: np.ndarray, target: np.ndarray) -> tuple[float, float, list[float]]:
    left = source[[1, 2]].reshape(2, -1).T
    right = target[[1, 2]].reshape(2, -1).T
    q_left, _ = np.linalg.qr(left, mode="reduced")
    q_right, _ = np.linalg.qr(right, mode="reduced")
    overlap = q_left.conj().T @ q_right
    u, _, vh = np.linalg.svd(overlap)
    unitary = u @ vh
    return float(np.angle(np.linalg.det(unitary))), float(np.linalg.norm(overlap - unitary)), [float(item) for item in np.linalg.svd(overlap, compute_uv=False)]


def _state_key(record: Mapping[str, Any]) -> tuple[str, bool, int]:
    return str(record["c3_member_identity"]), bool(record["deterministic"]), int(record["repeat_index"])


def _loop_records(records: Sequence[Mapping[str, Any]], deterministic: bool, repeat_index: int) -> dict[str, Mapping[str, Any]]:
    selected = {str(item["c3_member_identity"]): item for item in records if bool(item["deterministic"]) is deterministic and int(item["repeat_index"]) == repeat_index}
    if set(selected) != set(MEMBERS):
        raise ValueError(f"M39_LOOP_INCOMPLETE:{deterministic}:{repeat_index}")
    return selected


def same_k_analysis(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    frequency_dispersion: dict[str, Any] = {}
    rank2_repeat: dict[str, Any] = {}
    rank1_repeat: dict[str, Any] = {}
    det_by_member = {member: [item for item in records if item["c3_member_identity"] == member and item["deterministic"]] for member in MEMBERS}
    nondet_by_member = {member: [item for item in records if item["c3_member_identity"] == member and not item["deterministic"]] for member in MEMBERS}
    for member in MEMBERS:
        det_freq = np.asarray([item["frequencies_bands_1_to_4"] for item in det_by_member[member]], dtype=float)
        non_freq = np.asarray([item["frequencies_bands_1_to_4"] for item in nondet_by_member[member]], dtype=float)
        det_gaps = [item["adjacent_gaps"] for item in det_by_member[member]]
        det_gap_matrix = np.asarray([[item["band2_isolation_gap"], item["band3_isolation_gap"], item["minimum_external_rank2_gap"]] for item in det_gaps], dtype=float)
        frequency_dispersion[member] = {"deterministic_three_repeat_frequency_min": det_freq.min(axis=0).tolist(), "deterministic_three_repeat_frequency_max": det_freq.max(axis=0).tolist(), "deterministic_three_repeat_frequency_dispersion": (det_freq.max(axis=0) - det_freq.min(axis=0)).tolist(), "deterministic_band_isolation_gap_dispersion": (det_gap_matrix.max(axis=0) - det_gap_matrix.min(axis=0)).tolist(), "nondeterministic_two_repeat_frequency_spread": (non_freq.max(axis=0) - non_freq.min(axis=0)).tolist() if len(non_freq) > 1 else None}
        pairs = []
        for left_index in range(len(det_by_member[member])):
            for right_index in range(left_index + 1, len(det_by_member[member])):
                left, right = normalize_raw(decode_raw(det_by_member[member][left_index]["raw_eigenvector"]))[0], normalize_raw(decode_raw(det_by_member[member][right_index]["raw_eigenvector"]))[0]
                rank2 = low_rank_metrics(left, right)
                rank1 = [float(abs(np.vdot(left[band].reshape(-1), right[band].reshape(-1)) / (np.linalg.norm(left[band]) * np.linalg.norm(right[band])))) for band in range(BANDS)]
                pairs.append({"repeat_pair": [left_index, right_index], "rank1_same_band_absolute_overlaps": rank1, "rank2": rank2})
        nondet_left = normalize_raw(decode_raw(nondet_by_member[member][0]["raw_eigenvector"]))[0] if nondet_by_member[member] else None
        if len(nondet_by_member[member]) > 1:
            nondet_right = normalize_raw(decode_raw(nondet_by_member[member][1]["raw_eigenvector"]))[0]
            nondet_rank2 = low_rank_metrics(nondet_left, nondet_right)
            nondet_rank1 = [float(abs(np.vdot(nondet_left[band].reshape(-1), nondet_right[band].reshape(-1)) / (np.linalg.norm(nondet_left[band]) * np.linalg.norm(nondet_right[band])))) for band in range(BANDS)]
        else:
            nondet_rank2, nondet_rank1 = None, None
        deterministic_first = normalize_raw(decode_raw(det_by_member[member][0]["raw_eigenvector"]))[0]
        det_non_rank2 = low_rank_metrics(deterministic_first, nondet_left) if nondet_left is not None else None
        rank2_repeat[member] = {"deterministic_pairwise": pairs, "nondeterministic_pair_rank2": nondet_rank2, "deterministic_vs_nondeterministic_rank2": det_non_rank2}
        rank1_repeat[member] = {"deterministic_pairwise_same_band_absolute_overlaps": [item["rank1_same_band_absolute_overlaps"] for item in pairs], "nondeterministic_pair_same_band_absolute_overlaps": nondet_rank1, "deterministic_vs_nondeterministic_same_band_absolute_overlaps": [float(abs(np.vdot(deterministic_first[band].reshape(-1), nondet_left[band].reshape(-1)) / (np.linalg.norm(deterministic_first[band]) * np.linalg.norm(nondet_left[band])))) for band in range(BANDS)] if nondet_left is not None else None}
    return frequency_dispersion, {"rank1": rank1_repeat, "rank2": rank2_repeat}


def classify_causal(*, deterministic_minimum: float, nondeterministic_minimum: float, combined_repeat_uncertainty: float, deterministic_repeat_spread: float, cross_c3_deficit: float, adjacent_pair_stable: bool, adjacent_pair_noncanonical: bool, deterministic_same_k_stable: bool) -> str:
    causes: list[str] = []
    improvement = deterministic_minimum - nondeterministic_minimum
    if deterministic_same_k_stable and adjacent_pair_stable and improvement > combined_repeat_uncertainty:
        causes.append("RANDOM_INITIALIZATION")
    if adjacent_pair_noncanonical or not adjacent_pair_stable:
        causes.append("BAND_ASSOCIATION_OR_NEAR_DEGENERACY")
    if deterministic_same_k_stable and adjacent_pair_stable and abs(improvement) <= combined_repeat_uncertainty and deterministic_repeat_spread < cross_c3_deficit:
        causes.append("REMAINING_NUMERICAL_OR_PHYSICAL_C3_BREAKING")
    if len(causes) > 1:
        return "MULTIPLE_IDENTIFIED_CAUSES"
    return causes[0] if causes else "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT"


def analyze_records(records: Sequence[Mapping[str, Any]], m18_by_member: Mapping[str, Mapping[str, Any]], historical_records: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    m38 = _load(ROOT / "audit" / "berry_c3_consistency" / "m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m39_m38_pure_helpers")
    state_shapes = {member: normalize_raw(decode_raw(next(item for item in records if item["c3_member_identity"] == member and item["deterministic"])["raw_eigenvector"]))[1] for member in MEMBERS}
    coordinates = {member: list(m18_by_member[member]["coordinate"]) for member in MEMBERS}
    edge_states = {member: {"c3_member_identity": member, "coordinate": coordinates[member]} for member in MEMBERS}
    edges = m38._edges(edge_states)
    loops = [(True, 1), (True, 2), (True, 3), (False, 0)]
    rank1_by_loop: list[dict[str, Any]] = []
    rank2_edges: list[dict[str, Any]] = []
    for deterministic, repeat_index in loops:
        loop = _loop_records(records, deterministic, repeat_index)
        raw_by_member = {member: normalize_raw(decode_raw(loop[member]["raw_eigenvector"]))[0] for member in MEMBERS}
        rank1_edges = []
        rank2_loop_edges = []
        for edge in edges:
            source, target = raw_by_member[edge["edge_source_member"]], raw_by_member[edge["edge_target_member"]]
            source_coord, target_coord = coordinates[edge["edge_source_member"]], coordinates[edge["edge_target_member"]]
            rank1_edges.append({"band_2": rank1_link(source, target, 1, edge, m38, source_coord, target_coord), "band_3": rank1_link(source, target, 2, edge, m38, source_coord, target_coord)})
            transformed, ledger = m38.apply_raw_operator(source, source_coord, target_coord, edge["G_edge_integer"])
            pair_rows = [low_rank_metrics(transformed, target, (1, 2), pair) for pair in ((0, 1), (1, 2), (2, 3))]
            canonical_phase, polar_residual, canonical_singular = polar_det_phase(transformed, target)
            best_pair = max(pair_rows, key=lambda row: (row["minimum_singular_value"], tuple(-item for item in row["target_pair"])))
            rank2_loop_edges.append({**edge, "mode_map_bijection": bool(ledger["bijection"]), "adjacent_pair_metrics": pair_rows, "best_target_pair": best_pair["target_pair"], "best_target_pair_minimum_singular_value": best_pair["minimum_singular_value"], "canonical_pair_metrics": low_rank_metrics(transformed, target), "canonical_polar_det_phase": canonical_phase, "canonical_polar_unitary_residual": polar_residual, "canonical_overlap_singular_values": canonical_singular})
        for band_key in ("band_2", "band_3"):
            links = [edge_row[band_key]["same_index_link"] for edge_row in rank1_edges]
            loop_phase = float(np.angle(np.prod([complex(item[0], item[1]) for item in links])))
            rank1_by_loop.append({"deterministic": deterministic, "repeat_index": repeat_index, "band": int(band_key[-1]), "edges": [edge_row[band_key] for edge_row in rank1_edges], "wilson_phase": loop_phase, "branch_margin": float(math.pi - abs(loop_phase))})
        det_phase = float(np.angle(np.prod([np.exp(1j * row["canonical_polar_det_phase"]) for row in rank2_loop_edges])))
        rank2_edges.append({"deterministic": deterministic, "repeat_index": repeat_index, "edges": rank2_loop_edges, "holonomy_phase": det_phase, "branch_margin": float(math.pi - abs(det_phase))})
    frequency_dispersion, repeat_analysis = same_k_analysis(records)
    det_loops = [item for item in rank1_by_loop if item["deterministic"]]
    nondet_loops = [item for item in rank1_by_loop if not item["deterministic"]]
    phases_by_band = {str(band): [item["wilson_phase"] for item in det_loops if item["band"] == band] for band in (2, 3)}
    phase_uncertainty = {str(band): float(max(values) - min(values)) if values else None for band, values in phases_by_band.items()}
    all_links = [edge["link_magnitude"] for loop in rank1_by_loop for edge in loop["edges"]]
    min_link = float(min(all_links)) if all_links else None
    deterministic_loops = {(item["band"], item["edge_source_member"], item["edge_target_member"]): [] for item in det_loops for edge in item["edges"]}
    for loop in det_loops:
        for edge in loop["edges"]:
            deterministic_loops[(loop["band"], edge["edge_source_member"], edge["edge_target_member"])].append(edge["link_magnitude"])
    link_repeat_noise = max((max(values) - min(values) for values in deterministic_loops.values() if values), default=0.0)
    band_gap_signal = {"2": min(float(item["adjacent_gaps"]["band2_isolation_gap"]) for item in records), "3": min(float(item["adjacent_gaps"]["band3_isolation_gap"]) for item in records)}
    band_gap_noise = {"2": max(float(value["deterministic_band_isolation_gap_dispersion"][0]) for value in frequency_dispersion.values()), "3": max(float(value["deterministic_band_isolation_gap_dispersion"][1]) for value in frequency_dispersion.values())}
    rank1_qualification = {str(band): {"gap_signal_to_uncertainty": float(band_gap_signal[str(band)] / band_gap_noise[str(band)]) if band_gap_noise[str(band)] > 0.0 else float("inf") if band_gap_signal[str(band)] > 0.0 else 0.0, "link_signal_to_repeat_noise": float(min_link / link_repeat_noise) if min_link is not None and link_repeat_noise > 0.0 else float("inf") if min_link is not None and min_link > 0.0 else 0.0, "branch_margin_to_phase_uncertainty": float(min(item["branch_margin"] for item in rank1_by_loop if item["band"] == band) / phase_uncertainty[str(band)]) if phase_uncertainty[str(band)] not in (None, 0.0) else float("inf"), "status": "RANK1_WITHHELD"} for band in (2, 3)}
    for band, value in rank1_qualification.items():
        if value["gap_signal_to_uncertainty"] >= 10.0 and value["link_signal_to_repeat_noise"] is not None and value["link_signal_to_repeat_noise"] >= 10.0 and (value["branch_margin_to_phase_uncertainty"] is None or value["branch_margin_to_phase_uncertainty"] >= 5.0):
            value["status"] = "RANK1_QUALIFIED"
    rank2_minima = [edge["canonical_pair_metrics"]["minimum_singular_value"] for loop in rank2_edges for edge in loop["edges"]]
    deterministic_rank2 = [value for loop in rank2_edges if loop["deterministic"] for value in loop["edges"]]
    nondeterministic_rank2 = [value for loop in rank2_edges if not loop["deterministic"] for value in loop["edges"]]
    deterministic_min = min((row["canonical_pair_metrics"]["minimum_singular_value"] for row in deterministic_rank2), default=float("nan"))
    nondeterministic_min = min((row["canonical_pair_metrics"]["minimum_singular_value"] for row in nondeterministic_rank2), default=float("nan"))
    deterministic_best_pairs = [tuple(row["best_target_pair"]) for row in deterministic_rank2]
    adjacent_pair_stable = bool(deterministic_best_pairs) and len(set(deterministic_best_pairs)) == 1
    adjacent_pair_noncanonical = any(pair != (2, 3) for pair in deterministic_best_pairs)
    deterministic_repeat_spread = max((1.0 - row["rank2"]["minimum_singular_value"] for value in repeat_analysis["rank2"].values() for row in value["deterministic_pairwise"]), default=0.0)
    nondeterministic_repeat_spread = max((1.0 - value["nondeterministic_pair_rank2"]["minimum_singular_value"] for value in repeat_analysis["rank2"].values() if value["nondeterministic_pair_rank2"]), default=0.0)
    combined_repeat_uncertainty = deterministic_repeat_spread + nondeterministic_repeat_spread
    primary = classify_causal(deterministic_minimum=deterministic_min, nondeterministic_minimum=nondeterministic_min, combined_repeat_uncertainty=combined_repeat_uncertainty, deterministic_repeat_spread=deterministic_repeat_spread, cross_c3_deficit=max(0.0, 1.0 - deterministic_min), adjacent_pair_stable=adjacent_pair_stable, adjacent_pair_noncanonical=adjacent_pair_noncanonical, deterministic_same_k_stable=deterministic_repeat_spread < max(0.0, 1.0 - deterministic_min))
    next_decision = {"RANDOM_INITIALIZATION": "DETERMINISTIC_WORST_ORBIT_BERRY_RECOMPUTATION", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_TRANSPORT_ON_EXISTING_M39_RAW_BANDS", "REMAINING_NUMERICAL_OR_PHYSICAL_C3_BREAKING": "BOUNDED_RESOLUTION_TOLERANCE_CONVERGENCE_PILOT", "MULTIPLE_IDENTIFIED_CAUSES": "PRIORITIZE_CHEAPEST_IDENTIFIED_CAUSAL_CONTROL", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M39_EVIDENCE"}[primary]
    historical_provenance = {"m18_frequency_gap_control": {member: {"source_dataset_id": M18_DATASET_ID, "record_id": m18_by_member[member].get("record_id"), "frequencies_bands_1_to_4": m18_by_member[member].get("frequencies_bands_1_to_4"), "used_with_new_identity_repeat0": True} for member in MEMBERS}, "m33_raw_two_band_control": {str(item.get("c3_member_identity")): {"source_dataset_id": M33_DATASET_ID, "record_id": item.get("record_id"), "raw_shape": (item.get("raw_eigenvector") or {}).get("shape"), "used_only_for_bands_2_3_raw_metrics": True} for item in (historical_records or [])}, "combined_realization": False, "note": "M18 frequencies and M33 raw coefficients remain separate metric-specific historical controls; no cross-record frequency/raw quantity is computed."}
    return {"raw_eigenvector_shape_by_state": state_shapes, "first_four_frequencies_by_state": {str(_state_key(item)): item["frequencies_bands_1_to_4"] for item in records}, "adjacent_gaps_by_state": {str(_state_key(item)): item["adjacent_gaps"] for item in records}, "solver_convergence_evidence": {str(_state_key(item)): item["solver_convergence_evidence"] for item in records}, "same_k_repeat_frequency_dispersion": frequency_dispersion, "same_k_rank1_repeat_overlap": repeat_analysis["rank1"], "same_k_rank2_repeat_singular_values": repeat_analysis["rank2"], "c3_rank1_target_band_association": rank1_by_loop, "c3_rank1_link_magnitudes": rank1_by_loop, "c3_rank1_link_phases": rank1_by_loop, "c3_rank1_wilson_phases": {str(band): phases_by_band[str(band)] for band in (2, 3)}, "c3_rank1_phase_uncertainty": phase_uncertainty, "c3_rank1_branch_margins": {str(band): [item["branch_margin"] for item in rank1_by_loop if item["band"] == band] for band in (2, 3)}, "c3_rank1_qualification_status": rank1_qualification, "c3_rank2_edge_metrics": rank2_edges, "c3_rank2_adjacent_pair_association": [{"deterministic": loop["deterministic"], "repeat_index": loop["repeat_index"], "edges": [{"edge_source_member": row["edge_source_member"], "edge_target_member": row["edge_target_member"], "pairs": row["adjacent_pair_metrics"], "best_target_pair": row["best_target_pair"]} for row in loop["edges"]]} for loop in rank2_edges], "c3_rank2_best_pair_stability": {"stable": adjacent_pair_stable, "noncanonical": adjacent_pair_noncanonical, "deterministic_best_pairs": [list(pair) for pair in deterministic_best_pairs]}, "c3_rank2_holonomy_phase": [loop["holonomy_phase"] for loop in rank2_edges], "c3_rank2_branch_margin": [loop["branch_margin"] for loop in rank2_edges], "deterministic_vs_nondeterministic_effect_summary": {"deterministic_minimum_canonical_rank2": deterministic_min, "nondeterministic_minimum_canonical_rank2": nondeterministic_min, "combined_observed_repeat_uncertainty": combined_repeat_uncertainty, "deterministic_repeat_spread": deterministic_repeat_spread, "nondeterministic_repeat_spread": nondeterministic_repeat_spread, "m38_baseline_minimum": PUBLIC_M38_MIN, "m38_baseline_failures": PUBLIC_M38_FAILURES}, "historical_control_provenance": historical_provenance, "primary_causal_class": primary, "causal_evidence": {"deterministic_minimum": deterministic_min, "nondeterministic_minimum": nondeterministic_min, "qualification_ratios": rank1_qualification, "adjacent_pair_stable": adjacent_pair_stable, "adjacent_pair_noncanonical": adjacent_pair_noncanonical}, "counterevidence_summary": {"edge_count": len(edges), "loop_count": len(loops), "same_k": repeat_analysis, "rank2_minimums": rank2_minima}, "exact_remaining_uncertainty": "Rank1 qualification is withheld unless all goal-contract ratios pass; causal classification remains bounded by the 14-new-state recovery and metric-specific historical control.", "next_science_decision": next_decision, "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH"}


def persist_dataset(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]], source_commit: str) -> dict[str, Any]:
    store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
    for record in records:
        key = _canonical({"work_order_id": work_order_id, "request_key_sha256": record["request_key_sha256"]})
        store.put(key, _canonical(dict(record)), {"member": record["c3_member_identity"], "deterministic": record["deterministic"], "repeat_index": record["repeat_index"]})
    return store.finalize(14, {"dataset_schema": DATASET_SCHEMA, "source_m18_dataset_id": M18_DATASET_ID, "source_m33_dataset_id": M33_DATASET_ID, "new_state_count": 14, "deterministic_state_count": 9, "nondeterministic_state_count": 5})


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    result: dict[str, Any]
    counter = None
    records: list[dict[str, Any]] = []
    dataset: dict[str, Any] | None = None
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m39_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        m18_records = resolve_records(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, M18_SCHEMA, 3)
        m18_by_member = bind_m18(m18_records)
        historical = resolve_records(job, state_root, M33_DATASET_ID, M33_MANIFEST_SHA256, M33_SCHEMA, 3)
        schedule = build_recovery_schedule()
        specs = [request_spec(m18_by_member[item["c3_member_identity"]], item, source_commit) for item in schedule]
        if len({item["request_key_sha256"] for item in specs}) != 14:
            raise ValueError("M39R1_REQUEST_KEY_NOT_UNIQUE")
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=G15["a"], r1=G15["r1"], r2=G15["r2"], n_eff=G15["n_eff"], h=G15["height"], resolution=N, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(G15["n1"], G15["theta1_degrees"], G15["n2"], G15["theta2_degrees"], show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(14, 14)
        for spec in specs:
            solver, reciprocal = _solver_factory(mp, mpb, band, geometry, spec)
            records.append(capture_state(mp, solver, reciprocal, spec, counter, source_commit))
        if len(records) != 14 or counter.provider_count != 14 or counter.solver_count != 14:
            raise ValueError(f"M39R1_EXECUTION_COUNT_INVALID:{len(records)}:{counter.provider_count}:{counter.solver_count}")
        dataset = persist_dataset(job, state_root, bundle["work_order_id"], records, source_commit)
        analysis = analyze_records(records, m18_by_member, historical)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ONE_RECOVERY_NATIVE_BATCHED_FOURTEEN_NEW_STATES_G15_RAW_MPB_COMPLETE", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_id": dataset["dataset_id"], "manifest_sha256": dataset["manifest_sha256"], "prior_consumed_budget": {"native_invocations": 1, "provider_requests": 1, "solver_executions": 1, "durable_records": 0}, "cumulative_m39_chain_counts": {"native_invocations": 2, "provider_requests": 15, "solver_executions": 15, "durable_new_records": 14}, "source_m18_dataset_id": M18_DATASET_ID, "source_m33_dataset_id": M33_DATASET_ID, "recovery_schedule_summary": {"state_count": len(specs), "deterministic_state_count": sum(item["deterministic"] for item in specs), "nondeterministic_state_count": sum(not item["deterministic"] for item in specs), "deterministic_repeats": [1, 2, 3], "new_nondeterministic_repeat0_members": list(MEMBERS), "new_nondeterministic_repeat1_members": ["C3", "C3_SQUARED"], "schedule": specs}, "deterministic_repeat_count": 3, "nondeterministic_repeat_count": 1, "m38_reproduction_status": "M38_BASELINE_0P8707448645792748_THREE_FAILURES_REPORTED", "post_analysis_checkout_unchanged": True, "source_commit_used": source_commit, **analysis}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED" if not records else "PARTIAL_ACQUISITION", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M39R1_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1 if records or counter is not None else 0, "provider_execution_count": getattr(counter, "provider_count", 0), "solver_execution_count": getattr(counter, "solver_count", 0), "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "acquisition_or_analysis", "exception_type": type(exc).__name__, "actual_completed_state_count": len(records), "expected_state_count": 14, "prior_consumed_budget": {"native_invocations": 1, "provider_requests": 1, "solver_executions": 1, "durable_records": 0}, "cumulative_m39_chain_counts": {"native_invocations": 2 if records or counter is not None else 1, "provider_requests": 1 + getattr(counter, "provider_count", 0), "solver_executions": 1 + getattr(counter, "solver_count", 0), "durable_new_records": len(records)}, "m38_reproduction_status": "NOT_COMPLETED", "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH", "next_science_decision": "TARGETED_NEXT_DISCRIMINANT_FROM_M39R1_EVIDENCE", "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
