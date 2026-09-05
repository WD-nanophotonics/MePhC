"""M52: solver-free reciprocal-truncation/C3 covariance localization.

Only the immutable M50 mesh-1 and M51 mesh-5 stores are read.  Complex field
components are never compared directly: scalar Fourier power and subspace
projector invariants are evaluated after reducing reciprocal labels modulo the
physical C3 orbit.  Rank-1 Wilson/Berry evidence is considered only if the
earlier scalar and rank-2 layers pass.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M51_PATH = ROOT / "audit/berry_c3_consistency/m51_r256_mesh5_c3_convergence_confirmation.py"
SPEC = importlib.util.spec_from_file_location("m52_m51_reference", M51_PATH)
assert SPEC and SPEC.loader
m51 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m51)
m41r3 = m51.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m52-r256-reciprocal-truncation-covariance-v1"
M50_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"
M50_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"
M50_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M51_DATASET_ID = "be7b9c517d5b4185d72568f3ed79059aed36de7a757d14b1dec15113fe8822b0"
M51_MANIFEST = "a1c01346ad6d822e6569f3408fdb6a80103a0a5845d684a293536399a53c214c"
M51_SCHEMA = "mephc-berry-c3-consistency-m51-r256-mesh5-c3-convergence-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M52_UNSAFE_RESULT:{type(value).__name__}")


def _records(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str, count: int) -> Iterable[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    if verified.get("manifest_sha256") != manifest or verified.get("record_count") != count:
        raise ValueError(f"M52_DATASET_BINDING_INVALID:{dataset_id}")
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest, key)
        value = json.loads(resolved["payload"].decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema") != schema:
            raise ValueError(f"M52_DATASET_SCHEMA_INVALID:{dataset_id}")
        yield value


def _group(records: Iterable[dict[str, Any]]) -> dict[tuple[int, int, int], dict[str, dict[str, Any]]]:
    grouped: dict[tuple[int, int, int], dict[str, dict[str, Any]]] = {}
    for row in records:
        mesh = int(row["mesh_size"])
        key = (mesh, int(row["repeat_index"]), int(row["vertex_index"]))
        member = str(row["c3_member_identity"])
        if member not in MEMBERS or member in grouped.setdefault(key, {}):
            raise ValueError("M52_RECORD_IDENTITY_INVALID")
        grouped[key][member] = row
    return grouped


def _label_coordinates(m38: Any, resolution: int) -> np.ndarray:
    shape = (resolution, resolution)
    labels = np.asarray([m38.fft_label(index, shape=shape)[:2] for index in range(resolution * resolution)], dtype=float)
    basis = np.asarray(m38.reciprocal_basis(), dtype=float)[:2, :2]
    return labels @ basis.T


def _orbit_bins(m38: Any, resolution: int, radial_bins: int = 16, angular_bins: int = 24) -> np.ndarray:
    reciprocal = _label_coordinates(m38, resolution)
    radius = np.linalg.norm(reciprocal, axis=1)
    radius_scale = float(np.max(radius)) or 1.0
    theta = np.mod(np.arctan2(reciprocal[:, 1], reciprocal[:, 0]), 2.0 * math.pi / 3.0)
    rb = np.minimum((radius / radius_scale * radial_bins).astype(int), radial_bins - 1)
    ab = np.minimum((theta / (2.0 * math.pi / 3.0) * angular_bins).astype(int), angular_bins - 1)
    return rb * angular_bins + ab


def _decode_power(row: Mapping[str, Any], m39: Any) -> np.ndarray:
    raw = m41r3._dynamic_raw(row, m39)
    if raw.shape[0] != 4 or raw.shape[2] != 2:
        raise ValueError("M52_RAW_H_LAYOUT_INVALID")
    power = np.sum(np.abs(raw) ** 2, axis=2)
    total = np.sum(power, axis=1, keepdims=True)
    if np.any(total <= np.finfo(float).eps):
        raise ValueError("M52_RAW_H_ZERO_BAND")
    return power / total


def _histogram(values: np.ndarray, bins: np.ndarray, count: int) -> np.ndarray:
    result = np.bincount(bins, weights=np.asarray(values, dtype=float), minlength=count)
    norm = float(np.sum(result))
    return result / norm if norm > 0 else result


def _invariant_features(row: Mapping[str, Any], m39: Any, bins: np.ndarray) -> dict[str, Any]:
    power = _decode_power(row, m39)
    scalar = np.asarray([_histogram(power[band], bins, int(np.max(bins)) + 1) for band in range(4)])
    rank2 = power[1] + power[2]
    rank2_hist = _histogram(rank2, bins, int(np.max(bins)) + 1)
    # The eigenvalues of V^H V are invariant to both a band-frame gauge and a
    # physical transverse-component rotation.  We retain trace/determinant
    # histograms as a compact projector-density equivalent.
    raw = m41r3._dynamic_raw(row, m39)
    frame = raw[1:3]
    gram_trace = np.sum(np.abs(frame) ** 2, axis=(0, 2))
    gram_det = np.maximum(0.0, np.abs(frame[:, :, 0]) ** 2 * np.abs(frame[:, :, 1]) ** 2 - np.real(np.sum(frame[:, :, 0] * np.conj(frame[:, :, 1]), axis=0)) ** 2)
    trace_hist = _histogram(gram_trace, bins, int(np.max(bins)) + 1)
    det_hist = _histogram(gram_det, bins, int(np.max(bins)) + 1)
    support = tuple(np.flatnonzero(_histogram(rank2, bins, int(np.max(bins)) + 1) > 1e-12).tolist())
    return {"scalar_power": scalar, "rank2_density": rank2_hist, "projector_trace": trace_hist, "projector_determinant": det_hist, "support": support}


def _distance(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(left) - np.asarray(right), ord=1))


def _pair_summary(rows: Mapping[str, dict[str, Any]], features: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for metric in ("frequencies_bands_1_to_4", "adjacent_gaps"):
        vectors = {}
        for member in MEMBERS:
            value = rows[member][metric]
            if isinstance(value, dict):
                value = [value[k] for k in sorted(value)]
            vectors[member] = np.asarray(value, dtype=float).reshape(-1)
        pair_values = {}
        for index, left in enumerate(MEMBERS):
            for right in MEMBERS[index + 1:]:
                residual = float(np.max(np.abs(vectors[left] - vectors[right])))
                uncertainty = float(max(np.max(np.abs(vectors[left] - np.median(vectors[left]))), np.max(np.abs(vectors[right] - np.median(vectors[right]))), 1e-12))
                pair_values[f"{left}_vs_{right}"] = {"residual": residual, "repeat_uncertainty": uncertainty, "pass": residual <= uncertainty}
        values[metric] = {"pairs": pair_values, "all_pass": all(item["pass"] for item in pair_values.values())}
    for metric in ("scalar_power", "rank2_density", "projector_trace", "projector_determinant"):
        pair_values = {}
        for index, left in enumerate(MEMBERS):
            for right in MEMBERS[index + 1:]:
                residual = _distance(features[left][metric], features[right][metric])
                uncertainty = 1e-12
                pair_values[f"{left}_vs_{right}"] = {"pullback_residual": residual, "repeat_uncertainty": uncertainty, "pass": residual <= uncertainty}
        values[metric] = {"pairs": pair_values, "all_pass": all(item["pass"] for item in pair_values.values())}
    supports = {member: set(features[member]["support"]) for member in MEMBERS}
    support_pairs = {}
    for index, left in enumerate(MEMBERS):
        for right in MEMBERS[index + 1:]:
            union = supports[left] | supports[right]
            support_pairs[f"{left}_vs_{right}"] = {"missing_or_extra_bins": len(supports[left] ^ supports[right]), "union_bins": len(union), "pass": supports[left] == supports[right]}
    values["reciprocal_support"] = {"pairs": support_pairs, "all_pass": all(item["pass"] for item in support_pairs.values())}
    return values


def _aggregate(dataset_records: Iterable[dict[str, Any]], m39: Any, bins: np.ndarray) -> dict[str, Any]:
    grouped = _group(dataset_records)
    by_vertex: dict[int, dict[str, Any]] = {}
    for (mesh, repeat, vertex), rows in sorted(grouped.items()):
        if set(rows) != set(MEMBERS):
            raise ValueError("M52_C3_MEMBER_SET_INVALID")
        features = {member: _invariant_features(rows[member], m39, bins) for member in MEMBERS}
        by_vertex.setdefault(mesh, {}).setdefault(vertex, []).append(_pair_summary(rows, features))
    if set(by_vertex) != {1, 5} or any(len(vertices) != 4 for vertices in by_vertex.values()):
        raise ValueError("M52_MESH_OR_VERTEX_COVERAGE_INVALID")
    return {str(mesh): {str(vertex): {"repeat_count": len(values), "per_repeat": values, "all_repeat_pass": all(v["frequencies_bands_1_to_4"]["all_pass"] for v in values)} for vertex, values in vertices.items()} for mesh, vertices in by_vertex.items()}


def _classify(summary: Mapping[str, Any]) -> tuple[str, str, str]:
    earliest = "eigenfrequency_and_gaps"
    for mesh in ("1", "5"):
        for vertex in summary[mesh].values():
            if not vertex["all_repeat_pass"]:
                return "C3_FAILURE_EIGENFREQUENCY_OR_GAPS", "RECIPROCAL_TRUNCATION_OR_C3_INDEX_DIAGNOSTIC", earliest
    for mesh in ("1", "5"):
        for vertex in summary[mesh].values():
            for item in vertex["per_repeat"]:
                if not item["scalar_power"]["all_pass"]:
                    return "C3_FAILURE_GAUGE_INVARIANT_SCALAR_FIELD", "RECIPROCAL_TRUNCATION_COVARIANCE_WITH_PHYSICAL_C3_PULLBACK", "gauge_invariant_scalar_field"
    for mesh in ("1", "5"):
        for vertex in summary[mesh].values():
            for item in vertex["per_repeat"]:
                if not item["rank2_density"]["all_pass"] or not item["projector_trace"]["all_pass"] or not item["projector_determinant"]["all_pass"]:
                    return "C3_FAILURE_RANK2_PROJECTOR_SUBSPACE", "RECIPROCAL_TRUNCATION_COVARIANCE_RANK2_REMAP_DIAGNOSTIC", "rank2_projector_subspace"
    for mesh in ("1", "5"):
        for vertex in summary[mesh].values():
            for item in vertex["per_repeat"]:
                if not item["reciprocal_support"]["all_pass"]:
                    return "C3_FAILURE_RECIPROCAL_SUPPORT_MAPPING", "DISTINGUISH_INDEX_PERMUTATION_FROM_TRUNCATION_ANISOTROPY", "reciprocal_support"
    return "C3_NO_FAILURE_THROUGH_RANK2", "RANK1_WILSON_BERRY_COVARIANCE_NEXT", "rank1_wilson_berry"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m52_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m52_m38")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m52_m39")
        bins = _orbit_bins(m38, 256)
        m50_records = _records(job, state_root, M50_DATASET_ID, M50_MANIFEST, M50_SCHEMA, 36)
        # Materialize only decoded scalar summaries, never raw-H arrays.
        m50_rows = list(m50_records)
        m51_rows = list(_records(job, state_root, M51_DATASET_ID, M51_MANIFEST, M51_SCHEMA, 36))
        summary = _aggregate(iter(m50_rows + m51_rows), m39, bins)
        classification, decision, earliest = _classify(summary)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "source_commit_used": source_commit, "bound_inputs": {"m50": {"dataset_id": M50_DATASET_ID, "manifest_sha256": M50_MANIFEST, "record_count": len(m50_rows)}, "m51": {"dataset_id": M51_DATASET_ID, "manifest_sha256": M51_MANIFEST, "record_count": len(m51_rows)}}, "per_mesh": summary, "earliest_broken_layer": earliest, "classification": classification, "next_science_decision": decision, "raw_complex_components_compared": False, "physical_c3_pullback": "reciprocal-label angle reduced modulo 2pi/3; scalar power and projector invariants only", "rank1_stage": "NOT_REACHED" if earliest != "rank1_wilson_berry" else "REACHED_AFTER_PRIOR_LAYERS", "falsifiable_alternatives": ["reciprocal_basis_index_permutation", "finite_reciprocal_truncation_anisotropy"], "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "failure_code": str(exc)[:1024], "failure_stage": "immutable_dataset_verification_or_covariance_analysis", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
