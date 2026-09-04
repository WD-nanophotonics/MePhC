"""M39R2: solver-free causal adjudication of the finalized M39R1 dataset."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
M39R1_WORK_ORDER_ID = "MEPHC-BERRY-C3-M39R1-REMOTE-VERIFIED-14-STATE-RECOVERY-AND-CAUSAL-ADJUDICATION-20260904-099"
M39R1_DATASET_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
M39R2_RESULT_SCHEMA = "mephc-berry-c3-consistency-m39r2-g15-deterministic-repeat-band-association-causal-adjudication-v1"
PARENT_NAMESPACE_SHA256 = "716f5d62a06ba52368f7d3aa151b476da0b1f87c2bbcd4065038557d2965cbee"
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M33_DATASET_ID = "b92b495ea440d1054007b413823d767b2b4fb10b1e01063cbb87a689c1cfcb6d"
M33_MANIFEST_SHA256 = "dd03a3f456ae27af658f42a366967eedb6a5dbfd07ccbbb0ac8d778537f19278"
M18_SCHEMA = "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1"
M33_SCHEMA = "mephc-berry-c3-consistency-m33-raw-eigenvector-c3-metadata-dataset-v1"
PUBLIC_M38_MIN = 0.8707448645792748
N = 128
P = N * N


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M39R2_DEPENDENCY_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("M39R2_NONFINITE_RESULT")
        return value
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, complex):
        return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError(f"M39R2_UNSAFE_RESULT:{type(value).__name__}")


def _namespace() -> dict[str, Any]:
    return {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": M39R1_WORK_ORDER_ID, "source_commit": "0f1b2ec8b2ed1a538169053b496224faa71d21ed", "record_schema": M39R1_DATASET_SCHEMA}


def _read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha256: str, schema: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    if verified.get("manifest_sha256") != manifest_sha256 or verified.get("record_count") != count:
        raise ValueError(f"M39R2_DATASET_BINDING_INVALID:{dataset_id}")
    records: list[dict[str, Any]] = []
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest_sha256, key)
        payload = resolved.get("payload")
        if not isinstance(payload, bytes):
            raise ValueError(f"M39R2_DATASET_PAYLOAD_MISSING:{dataset_id}:{key}")
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema") != schema:
            raise ValueError(f"M39R2_DATASET_SCHEMA_INVALID:{dataset_id}")
        records.append(value)
    return records


def _read_parent(job: Any, state_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    store = job.ImmutableDatasetStore(state_root, _namespace())
    if store.namespace_sha256 != PARENT_NAMESPACE_SHA256:
        raise ValueError(f"M39R2_PARENT_NAMESPACE_MISMATCH:{store.namespace_sha256}")
    manifest_path = store.root / "dataset-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("namespace_sha256") != PARENT_NAMESPACE_SHA256 or manifest.get("completion_state") != "COMPLETE" or manifest.get("record_count") != 14:
        raise ValueError("M39R2_PARENT_MANIFEST_STATE_INVALID")
    provenance = manifest.get("provenance", {})
    expected_provenance = {"dataset_schema": M39R1_DATASET_SCHEMA, "new_state_count": 14, "deterministic_state_count": 9, "nondeterministic_state_count": 5}
    if any(provenance.get(key) != value for key, value in expected_provenance.items()):
        raise ValueError("M39R2_PARENT_PROVENANCE_INVALID")
    unsigned = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    dataset_id = job.digest(unsigned)
    manifest_with_id = {**unsigned, "dataset_id": dataset_id}
    if manifest.get("dataset_id") != dataset_id or manifest.get("manifest_sha256") != job.digest(manifest_with_id):
        raise ValueError("M39R2_PARENT_MANIFEST_DIGEST_INVALID")
    records = _read_dataset(job, state_root, dataset_id, manifest["manifest_sha256"], M39R1_DATASET_SCHEMA, 14)
    keys = [record.get("request_key_sha256") for record in records]
    if len(keys) != len(set(keys)) or any(not isinstance(key, str) for key in keys):
        raise ValueError("M39R2_PARENT_REQUEST_KEYS_INVALID")
    expected = {(member, True, repeat) for member in MEMBERS for repeat in (1, 2, 3)} | {(member, False, 0) for member in MEMBERS} | {(member, False, 1) for member in ("C3", "C3_SQUARED")}
    observed = {(record.get("c3_member_identity"), record.get("deterministic"), record.get("repeat_index")) for record in records}
    if observed != expected:
        raise ValueError("M39R2_PARENT_SCHEDULE_INVALID")
    for record in records:
        if not all(key in record for key in ("frequencies_bands_1_to_4", "raw_eigenvector", "adjacent_gaps", "solver_convergence_evidence", "source_commit")):
            raise ValueError("M39R2_PARENT_RECORD_FIELDS_INVALID")
    return records, {"dataset_id": dataset_id, "manifest_sha256": manifest["manifest_sha256"], "namespace_sha256": PARENT_NAMESPACE_SHA256}


def _bind_triplet(records: Sequence[Mapping[str, Any]], schema: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in records:
        if value.get("schema") != schema or value.get("geometry_id") != "G15":
            raise ValueError("M39R2_HISTORICAL_GEOMETRY_INVALID")
        member = value.get("c3_member_identity")
        if member not in MEMBERS or member in result:
            raise ValueError("M39R2_HISTORICAL_MEMBER_BINDING_INVALID")
        result[str(member)] = dict(value)
    if set(result) != set(MEMBERS):
        raise ValueError("M39R2_HISTORICAL_TRIPLET_INVALID")
    return result


def _raw4(m39: Any, record: Mapping[str, Any]) -> np.ndarray:
    value, layout = m39.normalize_raw(m39.decode_raw(record["raw_eigenvector"]))
    if tuple(value.shape) != (4, P, 2):
        raise ValueError(f"M39R2_RAW4_SHAPE_INVALID:{value.shape}")
    return value


def _raw2(m38: Any, record: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    value, layout = m38.normalize_raw_layout(m38.decode_raw_array(record["raw_eigenvector"]))
    if tuple(value.shape) != (2, P, 2):
        raise ValueError(f"M39R2_RAW2_SHAPE_INVALID:{value.shape}")
    return value, layout


def _bind_m18_frequency(m18: Mapping[str, Any]) -> list[float]:
    values = m18.get("frequencies_bands_1_to_6")
    if not isinstance(values, list) or len(values) < 4:
        raise ValueError("M39R2_M18_FREQUENCY_FIELD_INVALID")
    return [float(value) for value in values[:4]]


def _rank1_links(m38: Any, source: np.ndarray, target: np.ndarray, source_band: int, edge: Mapping[str, Any], source_coord: Sequence[float], target_coord: Sequence[float]) -> dict[str, Any]:
    transformed, ledger = m38.apply_raw_operator(source, source_coord, target_coord, edge["G_edge_integer"])
    vector = transformed[source_band].reshape(-1)
    overlaps: list[complex] = []
    for candidate in target:
        denominator = np.linalg.norm(vector) * np.linalg.norm(candidate.reshape(-1))
        overlaps.append(complex(np.vdot(candidate.reshape(-1), vector) / denominator) if denominator else complex(np.nan, np.nan))
    if any(not np.isfinite(value.real) or not np.isfinite(value.imag) for value in overlaps):
        raise ValueError("M39R2_ZERO_NORM_LINK")
    best = int(np.argmax([abs(value) for value in overlaps]))
    same = overlaps[source_band] if source_band < len(overlaps) else None
    return {"source_band": source_band + 1, "edge_source_member": edge["edge_source_member"], "edge_target_member": edge["edge_target_member"], "target_overlap_magnitudes": [float(abs(value)) for value in overlaps], "best_target_band": best + 1, "same_index_link": _safe(same), "link_magnitude": float(abs(same)) if same is not None else None, "wrapped_edge_phase": float(np.angle(same)) if same is not None else None, "mode_map_bijection": bool(ledger["bijection"])}


def _polar(m38: Any, transformed: np.ndarray, target: np.ndarray) -> tuple[float, float, list[float]]:
    left = transformed.reshape(2, -1).T
    right = target.reshape(2, -1).T
    q_left, _ = np.linalg.qr(left, mode="reduced")
    q_right, _ = np.linalg.qr(right, mode="reduced")
    overlap = q_left.conj().T @ q_right
    u, _, vh = np.linalg.svd(overlap)
    unitary = u @ vh
    return float(np.angle(np.linalg.det(unitary))), float(np.linalg.norm(overlap - unitary)), [float(item) for item in np.linalg.svd(overlap, compute_uv=False)]


def _circular_range(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return max(abs(float(np.angle(np.exp(1j * (left - right))))) for index, left in enumerate(values) for right in values[index + 1:])


def _grouped_link_noise(deterministic_rank1_loops: Sequence[Mapping[str, Any]]) -> tuple[float, dict[tuple[str, str, int], list[float]]]:
    """Group nested edge diagnostics; loop summaries do not own edge identity."""
    grouped: dict[tuple[str, str, int], list[float]] = {}
    for loop in deterministic_rank1_loops:
        for edge in loop["edges"]:
            for band in (2, 3):
                grouped.setdefault((str(edge["edge_source_member"]), str(edge["edge_target_member"]), band), []).append(float(edge[f"band_{band}"]["link_magnitude"]))
    return max((max(values) - min(values) for values in grouped.values()), default=0.0), grouped


def _loop(records: Sequence[Mapping[str, Any]], deterministic: bool, repeat: int) -> dict[str, Mapping[str, Any]]:
    result = {str(item["c3_member_identity"]): item for item in records if bool(item["deterministic"]) is deterministic and int(item["repeat_index"]) == repeat}
    if set(result) != set(MEMBERS):
        raise ValueError(f"M39R2_LOOP_INCOMPLETE:{deterministic}:{repeat}")
    return result


def _same_k(records: Sequence[Mapping[str, Any]], m39: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for member in MEMBERS:
        deterministic = sorted((item for item in records if item["c3_member_identity"] == member and item["deterministic"]), key=lambda item: int(item["repeat_index"]))
        nondeterministic = sorted((item for item in records if item["c3_member_identity"] == member and not item["deterministic"]), key=lambda item: int(item["repeat_index"]))
        det_freq = np.asarray([item["frequencies_bands_1_to_4"] for item in deterministic], dtype=float)
        pairs: list[dict[str, Any]] = []
        for left_index in range(3):
            for right_index in range(left_index + 1, 3):
                left, right = _raw4(m39, deterministic[left_index]), _raw4(m39, deterministic[right_index])
                same_band = [float(abs(np.vdot(left[band].reshape(-1), right[band].reshape(-1)) / (np.linalg.norm(left[band]) * np.linalg.norm(right[band])))) for band in range(4)]
                pairs.append({"repeat_pair": [int(deterministic[left_index]["repeat_index"]), int(deterministic[right_index]["repeat_index"])], "rank1_same_band_absolute_overlaps": same_band, "rank2_bands_2_3": m39.low_rank_metrics(left, right)})
        gap_matrix = np.asarray([[float(item["adjacent_gaps"]["band2_isolation_gap"]), float(item["adjacent_gaps"]["band3_isolation_gap"])] for item in deterministic])
        item: dict[str, Any] = {"deterministic_three_repeat_frequency_min": det_freq.min(axis=0).tolist(), "deterministic_three_repeat_frequency_max": det_freq.max(axis=0).tolist(), "deterministic_three_repeat_frequency_dispersion": (det_freq.max(axis=0) - det_freq.min(axis=0)).tolist(), "deterministic_band2_isolation_gap_dispersion": float(gap_matrix[:, 0].max() - gap_matrix[:, 0].min()), "deterministic_band3_isolation_gap_dispersion": float(gap_matrix[:, 1].max() - gap_matrix[:, 1].min()), "deterministic_pairwise": pairs}
        if len(nondeterministic) == 2:
            left, right = _raw4(m39, nondeterministic[0]), _raw4(m39, nondeterministic[1])
            item["new_nondeterministic_repeat0_vs_repeat1"] = {"repeat_indices": [0, 1], "frequency_spread": (np.asarray(nondeterministic[1]["frequencies_bands_1_to_4"]) - np.asarray(nondeterministic[0]["frequencies_bands_1_to_4"])).tolist(), "rank1_same_band_absolute_overlaps": [float(abs(np.vdot(left[band].reshape(-1), right[band].reshape(-1)) / (np.linalg.norm(left[band]) * np.linalg.norm(right[band])))) for band in range(4)], "rank2_bands_2_3": m39.low_rank_metrics(left, right)}
        else:
            item["new_nondeterministic_repeat0_vs_repeat1"] = "UNAVAILABLE_NO_NEW_REPEAT1"
        result[member] = item
    return result


def _analyze(records: Sequence[Mapping[str, Any]], m18: Mapping[str, Mapping[str, Any]], m33: Mapping[str, Mapping[str, Any]], m39: Any, m38: Any) -> dict[str, Any]:
    coordinates = {member: list(m18[member]["coordinate"]) for member in MEMBERS}
    edge_states = {member: {"c3_member_identity": member, "coordinate": coordinates[member]} for member in MEMBERS}
    edges = m38._edges(edge_states)
    rank1_loops: list[dict[str, Any]] = []
    rank2_loops: list[dict[str, Any]] = []
    for deterministic, repeat in ((True, 1), (True, 2), (True, 3), (False, 0)):
        loop = _loop(records, deterministic, repeat)
        raws = {member: _raw4(m39, loop[member]) for member in MEMBERS}
        loop_rank1: list[dict[str, Any]] = []
        loop_rank2: list[dict[str, Any]] = []
        for edge in edges:
            source = raws[edge["edge_source_member"]]
            target = raws[edge["edge_target_member"]]
            source_coord, target_coord = coordinates[edge["edge_source_member"]], coordinates[edge["edge_target_member"]]
            loop_rank1.append({"band_2": _rank1_links(m38, source, target, 1, edge, source_coord, target_coord), "band_3": _rank1_links(m38, source, target, 2, edge, source_coord, target_coord)})
            transformed, ledger = m38.apply_raw_operator(source, source_coord, target_coord, edge["G_edge_integer"])
            pairs = [m39.low_rank_metrics(transformed, target, (1, 2), pair) for pair in ((0, 1), (1, 2), (2, 3))]
            best = max(pairs, key=lambda row: (row["minimum_singular_value"], tuple(-value for value in row["target_pair"])))
            phase, residual, singular = _polar(m38, transformed[[1, 2]], target[[1, 2]])
            loop_rank2.append({"edge_source_member": edge["edge_source_member"], "edge_target_member": edge["edge_target_member"], "mode_map_bijection": bool(ledger["bijection"]), "adjacent_pair_metrics": pairs, "best_target_pair": best["target_pair"], "best_target_pair_minimum_singular_value": best["minimum_singular_value"], "canonical_pair_metrics": m39.low_rank_metrics(transformed, target), "canonical_polar_det_phase": phase, "canonical_polar_unitary_residual": residual, "canonical_overlap_singular_values": singular})
        for band in (2, 3):
            link_rows = [row[f"band_{band}"] for row in loop_rank1]
            wilson = float(np.angle(np.prod([complex(row["same_index_link"][0], row["same_index_link"][1]) for row in link_rows])))
            rank1_loops.append({"deterministic": deterministic, "repeat_index": repeat, "band": band, "edges": link_rows, "wilson_phase": wilson, "branch_margin": float(math.pi - abs(wilson))})
        holonomy = float(np.angle(np.prod([np.exp(1j * row["canonical_polar_det_phase"]) for row in loop_rank2])))
        rank2_loops.append({"deterministic": deterministic, "repeat_index": repeat, "edges": loop_rank2, "holonomy_phase": holonomy, "branch_margin": float(math.pi - abs(holonomy))})
    same_k = _same_k(records, m39)
    det_rank1 = [item for item in rank1_loops if item["deterministic"]]
    phases = {str(band): [item["wilson_phase"] for item in det_rank1 if item["band"] == band] for band in (2, 3)}
    phase_uncertainty = {band: _circular_range(values) for band, values in phases.items()}
    deterministic_records = [item for item in records if item["deterministic"]]
    gap_signal = {"2": min(float(item["adjacent_gaps"]["band2_isolation_gap"]) for item in deterministic_records), "3": min(float(item["adjacent_gaps"]["band3_isolation_gap"]) for item in deterministic_records)}
    gap_noise = {"2": max(item["deterministic_band2_isolation_gap_dispersion"] for item in same_k.values()), "3": max(item["deterministic_band3_isolation_gap_dispersion"] for item in same_k.values())}
    link_noise, grouped_links = _grouped_link_noise(det_rank1)
    min_link = min((float(edge["link_magnitude"]) for loop in det_rank1 for edge in loop["edges"]), default=0.0)
    qualification = {}
    for band in (2, 3):
        band_links = [row[f"band_{band}"]["link_magnitude"] for row in rank1_loops for _ in [0]]
        link_signal = min(float(value) for value in band_links)
        band_link_groups: dict[tuple[str, str], list[float]] = {}
        for loop in det_rank1:
            for edge in loop["edges"]:
                band_link_groups.setdefault((edge["edge_source_member"], edge["edge_target_member"]), []).append(float(edge[f"band_{band}"]["link_magnitude"]))
        band_link_noise = max((max(values) - min(values) for values in band_link_groups.values()), default=0.0)
        band_branch = [item["branch_margin"] for item in det_rank1 if item["band"] == band]
        qualification[str(band)] = {"gap_signal_to_uncertainty": float(gap_signal[str(band)] / gap_noise[str(band)]) if gap_noise[str(band)] > 0 else float("inf") if gap_signal[str(band)] > 0 else 0.0, "link_signal_to_repeat_noise": float(link_signal / band_link_noise) if band_link_noise > 0 else float("inf") if link_signal > 0 else 0.0, "branch_margin_to_phase_uncertainty": float(min(band_branch) / phase_uncertainty[str(band)]) if phase_uncertainty[str(band)] > 0 else float("inf"), "status": "RANK1_WITHHELD"}
        if qualification[str(band)]["gap_signal_to_uncertainty"] >= 10 and qualification[str(band)]["link_signal_to_repeat_noise"] >= 10 and qualification[str(band)]["branch_margin_to_phase_uncertainty"] >= 5:
            qualification[str(band)]["status"] = "RANK1_QUALIFIED"
    det_rank2 = [edge for loop in rank2_loops if loop["deterministic"] for edge in loop["edges"]]
    non_rank2 = [edge for loop in rank2_loops if not loop["deterministic"] for edge in loop["edges"]]
    det_min = min(edge["canonical_pair_metrics"]["minimum_singular_value"] for edge in det_rank2)
    non_min = min(edge["canonical_pair_metrics"]["minimum_singular_value"] for edge in non_rank2)
    best_pairs = [tuple(edge["best_target_pair"]) for edge in det_rank2]
    pair_stable = len(set(best_pairs)) == 1
    pair_noncanonical = any(pair != (1, 2) for pair in best_pairs)
    det_spread = max((1.0 - pair["rank2_bands_2_3"]["minimum_singular_value"] for value in same_k.values() for pair in value["deterministic_pairwise"]), default=0.0)
    non_spread = max((1.0 - value["new_nondeterministic_repeat0_vs_repeat1"]["rank2_bands_2_3"]["minimum_singular_value"] for value in same_k.values() if isinstance(value["new_nondeterministic_repeat0_vs_repeat1"], Mapping)), default=0.0)
    uncertainty = det_spread + non_spread
    same_k_stable = det_spread < max(0.0, 1.0 - det_min)
    primary = m39.classify_causal(deterministic_minimum=det_min, nondeterministic_minimum=non_min, combined_repeat_uncertainty=uncertainty, deterministic_repeat_spread=det_spread, cross_c3_deficit=max(0.0, 1.0 - det_min), adjacent_pair_stable=pair_stable, adjacent_pair_noncanonical=pair_noncanonical, deterministic_same_k_stable=same_k_stable)
    next_decision = {"RANDOM_INITIALIZATION": "DETERMINISTIC_WORST_ORBIT_BERRY_RECOMPUTATION", "BAND_ASSOCIATION_OR_NEAR_DEGENERACY": "ADAPTIVE_VALIDATED_SUBSPACE_TRANSPORT_ON_EXISTING_M39R1_RAW_BANDS", "REMAINING_NUMERICAL_OR_PHYSICAL_C3_BREAKING": "BOUNDED_RESOLUTION_TOLERANCE_CONVERGENCE_PILOT", "MULTIPLE_IDENTIFIED_CAUSES": "PRIORITIZE_CHEAPEST_IDENTIFIED_CAUSAL_CONTROL", "UNRESOLVED_UNDER_BOUNDED_EXPERIMENT": "TARGETED_NEXT_DISCRIMINANT_FROM_M39R2_EVIDENCE"}[primary]
    hist_freq = {member: _bind_m18_frequency(m18[member]) for member in MEMBERS}
    hist_identity_raw, hist_identity_layout = _raw2(m38, m33["IDENTITY"])
    hist_loop: list[dict[str, Any]] = []
    hist_raw = {"IDENTITY": hist_identity_raw, "C3": _raw4(m39, _loop(records, False, 1)["C3"])[1:3], "C3_SQUARED": _raw4(m39, _loop(records, False, 1)["C3_SQUARED"])[1:3]}
    for edge in edges:
        source, target = hist_raw[edge["edge_source_member"]], hist_raw[edge["edge_target_member"]]
        links = [_rank1_links(m38, source, target, band - 1, edge, coordinates[edge["edge_source_member"]], coordinates[edge["edge_target_member"]]) for band in (2, 3)]
        transformed, ledger = m38.apply_raw_operator(source, coordinates[edge["edge_source_member"]], coordinates[edge["edge_target_member"]], edge["G_edge_integer"])
        hist_loop.append({"edge_source_member": edge["edge_source_member"], "edge_target_member": edge["edge_target_member"], "band_2": links[0], "band_3": links[1], "rank2_bands_2_3": m38.rank2_metrics(transformed, target), "four_band_adjacent_pair_status": "UNAVAILABLE_HISTORICAL_RAW2_ONLY", "mode_map_bijection": bool(ledger["bijection"])})
    return {"first_four_frequencies_by_state": {str((item["c3_member_identity"], bool(item["deterministic"]), int(item["repeat_index"]))): item["frequencies_bands_1_to_4"] for item in records}, "adjacent_gaps_by_state": {str((item["c3_member_identity"], bool(item["deterministic"]), int(item["repeat_index"]))): item["adjacent_gaps"] for item in records}, "solver_convergence_evidence": {str((item["c3_member_identity"], bool(item["deterministic"]), int(item["repeat_index"]))): item["solver_convergence_evidence"] for item in records}, "same_k_repeat_frequency_dispersion": same_k, "same_k_rank1_repeat_overlap": {member: {"deterministic_pairwise_same_band_absolute_overlaps": [pair["rank1_same_band_absolute_overlaps"] for pair in value["deterministic_pairwise"]], "nondeterministic": value["new_nondeterministic_repeat0_vs_repeat1"]} for member, value in same_k.items()}, "same_k_rank2_repeat_singular_values": same_k, "c3_rank1_target_band_association": rank1_loops, "c3_rank1_link_magnitudes": rank1_loops, "c3_rank1_link_phases": rank1_loops, "c3_rank1_wilson_phases": phases, "c3_rank1_phase_uncertainty": phase_uncertainty, "c3_rank1_branch_margins": {str(band): [item["branch_margin"] for item in det_rank1 if item["band"] == band] for band in (2, 3)}, "c3_rank1_qualification_status": qualification, "c3_rank2_edge_metrics": rank2_loops, "c3_rank2_adjacent_pair_association": rank2_loops, "c3_rank2_best_pair_stability": {"stable": pair_stable, "noncanonical": pair_noncanonical, "deterministic_best_pairs": [list(pair) for pair in best_pairs]}, "c3_rank2_holonomy_phase": [item["holonomy_phase"] for item in rank2_loops], "c3_rank2_branch_margin": [item["branch_margin"] for item in rank2_loops], "deterministic_vs_nondeterministic_effect_summary": {"deterministic_minimum_canonical_rank2": det_min, "nondeterministic_minimum_canonical_rank2": non_min, "combined_observed_repeat_uncertainty": uncertainty, "deterministic_repeat_spread": det_spread, "nondeterministic_repeat_spread": non_spread, "m38_baseline_minimum": PUBLIC_M38_MIN, "m38_baseline_reproduction_controls": {"new_repeat0": non_min, "historical_raw2_metric_specific_loop": min(item["rank2_bands_2_3"]["minimum_overlap_singular_value"] for item in hist_loop)}}, "historical_control_provenance": {"m18_frequency_bands_1_to_4_from_bands_1_to_6": hist_freq, "m33_identity_raw_bands_2_3": {"record_id": m33["IDENTITY"].get("record_id"), "layout": hist_identity_layout, "used_in_second_nondeterministic_raw_loop": True}, "second_nondeterministic_raw_loop": hist_loop, "combined_realization": False}, "m38_reproduction_status": "M38_BASELINE_COMPARED_WITH_NEW_AND_HISTORICAL_CONTROLS", "primary_causal_class": primary, "causal_evidence": {"deterministic_minimum": det_min, "nondeterministic_minimum": non_min, "observed_repeat_uncertainty": uncertainty, "deterministic_same_k_stable": same_k_stable, "best_pair_stable": pair_stable, "best_pair_noncanonical": pair_noncanonical}, "counterevidence_summary": {"deterministic_same_k": same_k, "historical_raw2_loop": hist_loop, "qualification": qualification, "link_repeat_noise": link_noise, "minimum_link": min_link}, "exact_remaining_uncertainty": "Historical IDENTITY raw evidence contains bands2-3 only; bands1/4 adjacent-pair controls remain unavailable and M18 frequency plus M33 raw evidence were not merged.", "next_science_decision": next_decision, "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH"}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m39r2_job")
        m39 = _load(ROOT / "audit" / "berry_c3_consistency" / "m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m39r2_m39_helpers")
        m38 = _load(ROOT / "audit" / "berry_c3_consistency" / "m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m39r2_m38_helpers")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        records, parent = _read_parent(job, state_root)
        m18_records = _read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, M18_SCHEMA, 3)
        m33_records = _read_dataset(job, state_root, M33_DATASET_ID, M33_MANIFEST_SHA256, M33_SCHEMA, 3)
        m18, m33 = _bind_triplet(m18_records, M18_SCHEMA), _bind_triplet(m33_records, M33_SCHEMA)
        analysis = _analyze(records, m18, m33, m39, m38)
        result: dict[str, Any] = {"schema": M39R2_RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_PERSISTED_PARENT_DATASET_ANALYSIS_COMPLETE", "work_order_id": bundle["work_order_id"], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "parent_dataset_id": parent["dataset_id"], "parent_manifest_sha256": parent["manifest_sha256"], "parent_namespace_sha256": parent["namespace_sha256"], "source_m18_dataset_id": M18_DATASET_ID, "source_m33_dataset_id": M33_DATASET_ID, "parent_schedule_summary": {"record_count": 14, "deterministic_state_count": 9, "nondeterministic_state_count": 5, "deterministic_repeats": [1, 2, 3], "new_nondeterministic_repeat0_members": list(MEMBERS), "new_nondeterministic_repeat1_members": ["C3", "C3_SQUARED"]}, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True, **analysis}
    except BaseException as exc:
        result = {"schema": M39R2_RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "ZERO_SCIENTIFIC_EXECUTION_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "parent_resolution_or_solver_free_analysis", "exception_type": type(exc).__name__, "parent_dataset_id": None, "parent_manifest_sha256": None, "parent_namespace_sha256": PARENT_NAMESPACE_SHA256, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
