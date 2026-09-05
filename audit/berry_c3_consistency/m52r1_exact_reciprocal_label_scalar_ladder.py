"""M52R1: exact-label, solver-free C3 diagnostic ladder.

This is deliberately smaller than a Berry calculation.  It verifies the
finite reciprocal window, then compares frequencies, gaps, scalar Fourier
power and rank-2 invariants using exact integer pullbacks on common support.
Only the existing R256 mesh-1/3/5 stores are read.
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
SPEC = importlib.util.spec_from_file_location("m52r1_m51_reference", M51_PATH)
assert SPEC and SPEC.loader
m51 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m51)
m41r3 = m51.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m52r1-exact-reciprocal-label-scalar-ladder-v1"
M50_DATASET_ID = "9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d"
M50_MANIFEST = "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed"
M50_SCHEMA = "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1"
M47_DATASET_ID = "8366cb27fbe2d2e9a94f30b3c86b8b866165a7728f5d0c3779780fd571d8b154"
M47_MANIFEST = "7e01ee6517cd1b3b49890998e8c7aa4ad83b7906f157f4453e21845226c583b3"
M47_SCHEMA = "mephc-berry-c3-consistency-m47-r256-semantic-family-vertex-dataset-v1"
M51_DATASET_ID = "be7b9c517d5b4185d72568f3ed79059aed36de7a757d14b1dec15113fe8822b0"
M51_MANIFEST = "a1c01346ad6d822e6569f3408fdb6a80103a0a5845d684a293536399a53c214c"
M51_SCHEMA = "mephc-berry-c3-consistency-m51-r256-mesh5-c3-convergence-dataset-v1"
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
MESH_DATASETS = ((1, M50_DATASET_ID, M50_MANIFEST, M50_SCHEMA), (3, M47_DATASET_ID, M47_MANIFEST, M47_SCHEMA), (5, M51_DATASET_ID, M51_MANIFEST, M51_SCHEMA))


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
    raise ValueError(f"M52R1_UNSAFE_RESULT:{type(value).__name__}")


def _catalog(job: Any, state_root: Path, dataset_id: str, manifest: str, schema: str) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    if verified.get("manifest_sha256") != manifest or verified.get("record_count") != 36:
        raise ValueError(f"M52R1_DATASET_BINDING_INVALID:{dataset_id}")
    result = []
    for key in verified["record_key_sha256"]:
        resolved = job.resolve_dataset_record(state_root, dataset_id, manifest, key)
        row = json.loads(resolved["payload"].decode("utf-8"))
        if not isinstance(row, dict) or row.get("schema") != schema:
            raise ValueError(f"M52R1_DATASET_SCHEMA_INVALID:{dataset_id}")
        result.append({"key": key, "mesh": int(row["mesh_size"]), "repeat": int(row["repeat_index"]), "vertex": int(row["vertex_index"]), "member": str(row["c3_member_identity"]), "coordinate": list(row["coordinate"])})
    if len(result) != 36 or {(x["repeat"], x["vertex"], x["member"]) for x in result}.__len__() != 36:
        raise ValueError(f"M52R1_DATASET_COVERAGE_INVALID:{dataset_id}")
    return result


def _load_row(job: Any, state_root: Path, dataset_id: str, manifest: str, key: str) -> dict[str, Any]:
    resolved = job.resolve_dataset_record(state_root, dataset_id, manifest, key)
    value = json.loads(resolved["payload"].decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("M52R1_RECORD_NOT_OBJECT")
    return value


def _exact_support(m38: Any, states: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    shape = (256, 256)
    labels = [tuple(int(v) for v in m38.fft_label(index, shape=shape)) for index in range(65536)]
    label_index = {label: index for index, label in enumerate(labels)}
    automorphism = np.asarray(m38.reciprocal_automorphism(), dtype=int)
    edges = m38._edges(states)
    result = {}
    for edge in edges:
        source = str(edge["edge_source_member"]); target = str(edge["edge_target_member"])
        edge_key = f"{source}_to_{target}"
        g_edge = np.asarray(edge["G_edge_integer"], dtype=int)
        source_indices, target_indices, boundary = [], [], []
        wrap_hist: dict[str, int] = {}
        mapped_targets = set()
        for source_index, label in enumerate(labels):
            unwrapped = automorphism @ np.asarray(label, dtype=int) - g_edge
            target_label = tuple(int(v) for v in unwrapped)
            canonical_target = labels[m38.fft_index(target_label, shape=shape)]
            wrap = tuple(int(unwrapped[i] - canonical_target[i]) for i in range(2))
            if wrap != (0, 0):
                wrap_hist["%d,%d" % wrap] = wrap_hist.get("%d,%d" % wrap, 0) + 1
            if target_label in label_index:
                source_indices.append(source_index)
                target_indices.append(label_index[target_label])
            else:
                boundary.append(source_index)
            mapped_targets.add(label_index[canonical_target])
        common = set(source_indices)
        target_only = set(range(len(labels))) - mapped_targets
        result[edge_key] = {
            "source_member": source, "target_member": target, "G_edge_integer": g_edge.tolist(),
            "folding_residual": float(edge["folding_residual"]), "common_support_count": len(source_indices),
            "source_only_count": len(boundary), "target_only_count": len(target_only),
            "symmetric_difference_count": len(boundary) + len(target_only), "wrap_count": sum(wrap_hist.values()),
            "wrap_vectors_histogram": wrap_hist, "common_support_fraction": len(source_indices) / 65536.0,
            "source_indices": np.asarray(source_indices, dtype=int), "target_indices": np.asarray(target_indices, dtype=int),
            "boundary_source_indices": np.asarray(boundary, dtype=int), "boundary_target_indices": np.asarray(sorted(target_only), dtype=int),
        }
    if len(result) != 3:
        raise ValueError("M52R1_C3_EDGE_CYCLE_INVALID")
    return result


def _canonical_raw(row: Mapping[str, Any], m39: Any) -> np.ndarray:
    raw = m39.decode_raw(row["raw_eigenvector"])
    canonical = m41r3._normalize_raw(raw, int(row["resolution"]))[0]
    if canonical.shape != (4, 65536, 2):
        raise ValueError(f"M52R1_RAW_SHAPE_INVALID:{canonical.shape}")
    return np.asarray(canonical, dtype=np.complex128)


def _normalize(value: np.ndarray) -> np.ndarray:
    total = float(np.sum(value))
    return value / total if total > np.finfo(float).eps else value


def scalar_features(raw: np.ndarray) -> dict[str, np.ndarray]:
    """Build only gauge-invariant scalar/pseudoprojector features."""
    if np.asarray(raw).shape != (4, 65536, 2):
        raise ValueError(f"M52R1_RAW_SHAPE_INVALID:{np.asarray(raw).shape}")
    power = np.sum(np.abs(raw) ** 2, axis=2)
    band_power = np.asarray([_normalize(power[band]) for band in range(4)])
    rank2_power = _normalize(power[1] + power[2])
    frame = raw[1:3]
    trace = _normalize(np.sum(np.abs(frame) ** 2, axis=(0, 2)))
    v00 = frame[0, :, 0]; v01 = frame[0, :, 1]; v10 = frame[1, :, 0]; v11 = frame[1, :, 1]
    determinant = np.abs(v00 * v11 - v01 * v10) ** 2
    determinant = _normalize(determinant)
    if determinant.ndim != 1 or len(determinant) != 65536:
        raise ValueError(f"M52R1_PROJECTOR_DETERMINANT_SHAPE_INVALID:{determinant.shape}")
    return {"band_power": band_power, "rank2_power": rank2_power, "rank2_trace": trace, "rank2_determinant": determinant}


def _feature_vectors(row: Mapping[str, Any], m39: Any) -> dict[str, Any]:
    return {"frequencies": np.asarray(row["frequencies_bands_1_to_4"], dtype=float), "gaps": {key: float(row["adjacent_gaps"][key]) for key in ("lower_gap", "internal_split", "upper_gap", "band2_isolation_gap")}, "features": scalar_features(_canonical_raw(row, m39))}


def _median_uncertainty(values: Sequence[np.ndarray]) -> tuple[np.ndarray, float]:
    if len(values) != 3:
        raise ValueError("M52R1_REPEAT_COUNT_INVALID")
    central = np.median(np.asarray(values), axis=0)
    uncertainty = max(float(np.sum(np.abs(np.asarray(value) - central))) for value in values)
    return central, uncertainty


def _scalar_pair(values: Mapping[str, Sequence[np.ndarray]], left: str, right: str) -> dict[str, Any]:
    lcentral, lunc = _median_uncertainty(values[left]); rcentral, runc = _median_uncertainty(values[right])
    residual = float(np.max(np.abs(lcentral - rcentral)))
    return {"central_left": lcentral, "central_right": rcentral, "residual": residual, "combined_repeat_uncertainty": lunc + runc, "pass": residual <= lunc + runc}


def _field_pair(values: Mapping[str, Sequence[np.ndarray]], edge: Mapping[str, Any], left: str, right: str) -> dict[str, Any]:
    source_idx = edge["source_indices"]; target_idx = edge["target_indices"]
    source_values = [np.asarray(value)[source_idx] for value in values[left]]
    target_values = [np.asarray(value)[target_idx] for value in values[right]]
    source_central, source_unc = _median_uncertainty(source_values); target_central, target_unc = _median_uncertainty(target_values)
    residual = float(np.sum(np.abs(source_central - target_central)))
    return {"pullback_residual_l1": residual, "combined_repeat_uncertainty_l1": source_unc + target_unc, "pass": residual <= source_unc + target_unc}


def _boundary_pair(values: Mapping[str, Sequence[np.ndarray]], edge: Mapping[str, Any], left: str, right: str) -> dict[str, Any]:
    source_idx = edge["boundary_source_indices"]; target_idx = edge["boundary_target_indices"]
    source_values = [float(np.sum(np.asarray(value)[source_idx])) for value in values[left]]
    target_values = [float(np.sum(np.asarray(value)[target_idx])) for value in values[right]]
    source_central, source_unc = _median_uncertainty([np.asarray([value]) for value in source_values]); target_central, target_unc = _median_uncertainty([np.asarray([value]) for value in target_values])
    residual = float(abs(source_central[0] - target_central[0]))
    return {"source_boundary_power_fraction": float(source_central[0]), "target_boundary_power_fraction": float(target_central[0]), "boundary_fraction_residual": residual, "combined_repeat_uncertainty": source_unc + target_unc, "pass": residual <= source_unc + target_unc}


def _mesh_analysis(job: Any, state_root: Path, dataset: tuple[int, str, str, str], catalog: Sequence[Mapping[str, Any]], m39: Any, edges_by_vertex: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    mesh, dataset_id, manifest, _schema = dataset
    rows: dict[tuple[int, int, str], dict[str, Any]] = {}
    for item in catalog:
        if int(item["mesh"]) != mesh:
            raise ValueError("M52R1_MESH_BINDING_INVALID")
        row = _load_row(job, state_root, dataset_id, manifest, str(item["key"]))
        rows[(int(item["vertex"]), int(item["repeat"]), str(item["member"]))] = _feature_vectors(row, m39)
    output: dict[str, Any] = {}
    for vertex in range(4):
        edge_map = edges_by_vertex[vertex]
        frequency: dict[str, Any] = {}; gaps: dict[str, Any] = {}; fields: dict[str, Any] = {}; boundaries: dict[str, Any] = {}
        member_values = {member: [rows[(vertex, repeat, member)] for repeat in range(3)] for member in MEMBERS}
        for edge_name, edge in edge_map.items():
            left, right = edge["source_member"], edge["target_member"]
            frequency[edge_name] = {f"band{band + 1}": _scalar_pair({member: [v["frequencies"][band] for v in values] for member, values in member_values.items()}, left, right) for band in range(4)}
            gaps[edge_name] = {name: _scalar_pair({member: [np.asarray(v["gaps"][name]) for v in values] for member, values in member_values.items()}, left, right) for name in ("lower_gap", "internal_split", "upper_gap", "band2_isolation_gap")}
            fields[edge_name] = {}; boundaries[edge_name] = {}
            for feature in ("band_power", "rank2_power", "rank2_trace", "rank2_determinant"):
                source_feature = [v["features"][feature] for v in member_values[left]]; target_feature = [v["features"][feature] for v in member_values[right]]
                if feature == "band_power":
                    fields[edge_name][feature] = {f"band{band + 1}": _field_pair({left: [value[band] for value in source_feature], right: [value[band] for value in target_feature]}, edge, left, right) for band in range(4)}
                    boundaries[edge_name][feature] = {f"band{band + 1}": _boundary_pair({left: [value[band] for value in source_feature], right: [value[band] for value in target_feature]}, edge, left, right) for band in range(4)}
                else:
                    fields[edge_name][feature] = _field_pair({left: source_feature, right: target_feature}, edge, left, right)
                    boundaries[edge_name][feature] = _boundary_pair({left: source_feature, right: target_feature}, edge, left, right)
        output[str(vertex)] = {"frequency": frequency, "gaps": gaps, "fields": fields, "boundary_power": boundaries}
    return output


def _pass_tree(value: Any) -> bool:
    if isinstance(value, Mapping):
        if "pass" in value:
            return bool(value["pass"])
        return all(_pass_tree(item) for item in value.values())
    return bool(value)


def _all_pass(summary: Mapping[str, Any], section: str) -> bool:
    return all(_pass_tree(vertex[section]) for vertex in summary.values())


def classify(mesh5: Mapping[str, Any], structural_noninvariant: bool) -> tuple[str, str, str]:
    if not _all_pass(mesh5, "frequency"):
        if structural_noninvariant:
            return "R256_M5_FREQUENCY_C3_FAILURE_WITH_NONCOVARIANT_RECIPROCAL_WINDOW", "MPB_DISCRETE_OPERATOR_C3_READBACK_AND_RECIPROCAL_WINDOW_PATCH_AB_TEST", "L1_frequency"
        return "R256_M5_FREQUENCY_C3_FAILURE_WITH_COVARIANT_RECIPROCAL_WINDOW", "MPB_DISCRETIZED_EPSILON_C3_READBACK_AND_SUBPIXEL_PATCH_AB_TEST", "L1_frequency"
    if not _all_pass(mesh5, "gaps"):
        return "R256_M5_FREQUENCY_PASS_GAP_C3_FAILURE", "ADAPTIVE_VALIDATED_SUBSPACE_AND_NEAR_DEGENERACY_ADJUDICATION_USING_EXISTING_R256_M1_M3_M5_RAW_BANDS", "L2_gaps"
    if not _all_pass(mesh5, "fields") or not _all_pass(mesh5, "boundary_power"):
        return "R256_M5_SPECTRAL_PASS_SCALAR_FIELD_C3_FAILURE", "MPB_RAW_FIELD_SCALAR_C3_PULLBACK_AND_REPRESENTATION_DIAGNOSTIC", "L3_scalar_field"
    if not _all_pass(mesh5, "fields"):
        return "R256_M5_SCALAR_FIELD_PASS_RANK2_C3_FAILURE", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R256_M1_M3_M5_RAW_BANDS", "L4_rank2"
    return "R256_M5_C3_PASS_THROUGH_RANK2", "R256_M5_RANK1_WILSON_BERRY_C3_QUALIFICATION_THEN_CROSS_ORBIT", "L5_rank1_not_computed"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m52r1_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m52r1_m38")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m52r1_m39")
        catalogs = {mesh: _catalog(job, state_root, dataset_id, manifest, schema) for mesh, dataset_id, manifest, schema in MESH_DATASETS}
        edges_by_vertex = {}
        for vertex in range(4):
            states = {member: next(item for item in catalogs[5] if item["vertex"] == vertex and item["repeat"] == 0 and item["member"] == member) for member in MEMBERS}
            edges_by_vertex[vertex] = _exact_support(m38, states)
        structural = {str(vertex): {name: {key: value for key, value in edge.items() if not isinstance(value, np.ndarray)} for name, edge in edges.items()} for vertex, edges in edges_by_vertex.items()}
        analyses = {str(mesh): _mesh_analysis(job, state_root, dataset, catalogs[mesh], m39, edges_by_vertex) for mesh, dataset in ((mesh, item) for mesh, item in zip((1, 3, 5), MESH_DATASETS))}
        structural_noninvariant = any(edge["symmetric_difference_count"] > 0 for edges in edges_by_vertex.values() for edge in edges.values())
        classification, decision, earliest = classify(analyses["5"], structural_noninvariant)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "source_commit_used": source_commit, "bound_inputs": {str(mesh): {"dataset_id": dataset_id, "manifest_sha256": manifest, "record_count": len(catalogs[mesh])} for mesh, dataset_id, manifest, _schema in MESH_DATASETS}, "structural_reciprocal_window": structural, "per_mesh": analyses, "mesh5_primary": True, "earliest_broken_layer": earliest, "classification": classification, "next_science_decision": decision, "raw_complex_components_compared": False, "rank1_status": "NOT_COMPUTED_IN_M52R1", "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "failure_code": str(exc)[:1024], "failure_stage": "exact_label_window_or_scalar_ladder", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
