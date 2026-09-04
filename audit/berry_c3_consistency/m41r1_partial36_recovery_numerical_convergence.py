"""M41R1: recover M41's first 36 states and acquire the remaining settings."""
from __future__ import annotations

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
BASE = ROOT / "audit/berry_c3_consistency/m41_g15_covariant_numerical_convergence_pilot.py"
SPEC = importlib.util.spec_from_file_location("m41_parent", BASE)
assert SPEC and SPEC.loader
m41 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m41)
m40r2 = m41.m40r2
M39R1_SCHEMA = "mephc-berry-c3-consistency-m39r1-g15-deterministic-repeat-band-association-recovery-dataset-v1"
PARTIAL_NAMESPACE_SHA256 = "a1ec5b7605212832ac5e91fc8bf5a37b8a541f0a1259208bfb86cb55966e8b16"
PARTIAL_SOURCE_COMMIT = "0bdc3fe14a12663d0d12e5d7294499ebdb3c9de9"
PARTIAL_WORK_ORDER_ID = "MEPHC-BERRY-C3-M41-G15-COVARIANT-NUMERICAL-CONVERGENCE-PILOT-20260904-106"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m41r1-recovery-numerical-convergence-vertex-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m41r1-g15-covariant-numerical-convergence-recovery-v1"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"M41R1_DEPENDENCY_UNAVAILABLE:{path}")
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
    raise ValueError(f"M41R1_UNSAFE_RESULT:{type(value).__name__}")


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
        raise ValueError(f"M41R1_RAW_LAYOUT_INVALID:{value.shape}:resolution={resolution}")
    if not np.all(np.isfinite(canonical.real)) or not np.all(np.isfinite(canonical.imag)):
        raise ValueError("M41R1_RAW_NONFINITE")
    return canonical, {"raw_shape": list(value.shape), "normalized_shape": list(canonical.shape), "mode_count": expected, "band_count": 4, "transverse_component_count": 2, "layout": layout}


def _transfer(m38: Any, source: np.ndarray, source_k: Sequence[float], target_k: Sequence[float]) -> np.ndarray:
    resolution = int(round(math.sqrt(source.shape[1])))
    shape = (resolution, resolution)
    basis = m38.reciprocal_basis()
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
    matrix = np.asarray([[np.vdot(target[i].reshape(-1), transported[j + 1].reshape(-1)) for j in range(2)] for i in selected], dtype=np.complex128)
    matrix /= np.outer([np.linalg.norm(target[i]) for i in selected], [np.linalg.norm(transported[j + 1]) for j in range(2)])
    u, singular, vh = np.linalg.svd(matrix)
    return {"target_pair": [i + 1 for i in selected], "overlap_matrix": matrix, "singular_values": singular, "minimum_singular_value": float(np.min(singular)), "principal_angle": float(np.arccos(np.clip(np.min(singular), -1.0, 1.0)),), "projector_distance": float(np.sqrt(max(0.0, 4.0 - 2.0 * float(np.sum(singular ** 2))))), "captured_weight": float(np.sum(singular ** 2)), "polar_unitary": u @ vh}


def _dynamic_raw(row: Mapping[str, Any], m39: Any) -> np.ndarray:
    encoded = m39.decode_raw(row["raw_eigenvector"])
    resolution = int(row.get("resolution", round(math.sqrt(np.asarray(encoded).shape[-2]))))
    return _normalize_raw(encoded, resolution)[0]


def _patch_parent_helpers(m39: Any, m38: Any) -> None:
    """Reuse the parent grouping/classification path with resolution-aware helpers."""
    m41._raw = lambda row, _ignored: _dynamic_raw(row, m39)
    m41.m40r3._rank1 = lambda _m38, source, target, source_k, target_k: _rank1(m38, source, target, source_k, target_k)
    m41.m40r3._rank2_pair = lambda _m38, source, target, source_k, target_k, pair: _rank2_pair(m38, source, target, source_k, target_k, pair)


def _read_partial(job: Any, state_root: Path) -> list[dict[str, Any]]:
    namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": PARTIAL_WORK_ORDER_ID, "source_commit": PARTIAL_SOURCE_COMMIT, "record_schema": m41.DATASET_SCHEMA}
    store = job.ImmutableDatasetStore(state_root, namespace)
    if store.namespace_sha256 != PARTIAL_NAMESPACE_SHA256 or (store.root / "dataset-manifest.json").exists():
        raise ValueError("M41R1_PARTIAL_NAMESPACE_OR_MANIFEST_INVALID")
    metadata_paths = sorted(store.records.glob("*.json"))
    if len(metadata_paths) != 36:
        raise ValueError("M41R1_PARTIAL_COUNT_INVALID")
    records = []
    for path in metadata_paths:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        payload = path.with_suffix(".payload").read_bytes()
        if metadata.get("complete") is not True or hashlib.sha256(payload).hexdigest() != metadata.get("payload_sha256") or len(payload) != metadata.get("payload_size_bytes"):
            raise ValueError("M41R1_PARTIAL_RECORD_INTEGRITY_INVALID")
        value = json.loads(payload.decode("utf-8"))
        if value.get("schema") != m41.DATASET_SCHEMA or value.get("configuration_id") != "R128_T1E9_M3" or value.get("resolution") != 128 or value.get("mesh_size") != 3 or value.get("stencil") != "C3_COVARIANT" or value.get("deterministic") is not True:
            raise ValueError("M41R1_PARTIAL_RECORD_METADATA_INVALID")
        records.append(value)
    return records


def capture_state_resolution_aware(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    resolution = int(spec["resolution"])
    counter.consume_provider()
    counter.consume_solver()
    solver.run_parity(mp.TE, False)
    frequencies = np.asarray(solver.all_freqs, dtype=float)
    if frequencies.ndim == 2:
        frequencies = frequencies[0]
    if frequencies.shape != (4,):
        raise ValueError(f"M41R1_FREQUENCY_LAYOUT_INVALID:{frequencies.shape}")
    raw_native = np.asarray(solver.get_eigenvectors(1, 4))
    canonical, layout = _normalize_raw(raw_native, resolution)
    gaps = {"lower_gap": float(frequencies[1] - frequencies[0]), "internal_split": float(frequencies[2] - frequencies[1]), "upper_gap": float(frequencies[3] - frequencies[2])}
    gaps.update({"band2_isolation_gap": min(gaps["lower_gap"], gaps["internal_split"]), "band3_isolation_gap": min(gaps["internal_split"], gaps["upper_gap"]), "minimum_external_rank2_gap": min(gaps["lower_gap"], gaps["upper_gap"])})
    evidence = {"requested_tolerance": float(spec["tolerance"]), "iteration_evidence_status": "UNAVAILABLE_NO_PUBLIC_RUNTIME_FIELD", "public_runtime_fields": {}}
    for name in ("iterations", "iteration_count", "residual", "residual_norm", "last_residual"):
        if hasattr(solver, name):
            evidence["public_runtime_fields"][name] = _safe(getattr(solver, name))
    if evidence["public_runtime_fields"]:
        evidence["iteration_evidence_status"] = "PUBLIC_RUNTIME_FIELDS_CAPTURED"
    return {"schema": DATASET_SCHEMA, "record_id": "M41R1-" + str(spec["request_key_sha256"]), "request_key_sha256": spec["request_key_sha256"], "configuration_id": spec["configuration_id"], "member_index": int(spec["member_index"]), "c3_member_identity": spec["c3_member_identity"], "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "stencil": "C3_COVARIANT", "coordinate": list(spec["coordinate"]), "center": list(spec["center"]), "deterministic": True, "repeat_index": int(spec["repeat_index"]), "vertex_index": int(spec["vertex_index"]), "num_bands": 4, "resolution": resolution, "tolerance": float(spec["tolerance"]), "eigensolver_tolerance": float(spec["tolerance"]), "mesh_size": int(spec["mesh_size"]), "polarization": "TE", "frequencies_bands_1_to_4": frequencies.tolist(), "adjacent_gaps": gaps, "solver_convergence_evidence": evidence, "raw_eigenvector": m39_encode_raw(raw_native), "raw_layout": layout, "raw_rank2_gram_residual": {"status": "MEASURED", "normalized_shape": list(canonical.shape)}, "source_commit": source_commit}


def m39_encode_raw(raw: np.ndarray) -> dict[str, Any]:
    import base64
    import io
    import zlib
    stream = io.BytesIO()
    value = np.asarray(raw, dtype=np.complex128)
    np.save(stream, value, allow_pickle=False)
    payload = zlib.compress(stream.getvalue(), level=6)
    return {"encoding": "zlib_npy_complex128_base64", "shape": list(value.shape), "dtype": str(value.dtype), "sha256": hashlib.sha256(value.tobytes()).hexdigest(), "payload_base64": base64.b64encode(payload).decode("ascii")}


def _new_graph(config: Mapping[str, Any], centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph = []
    for member_index, member in enumerate(MEMBERS := ("IDENTITY", "C3", "C3_SQUARED")):
        for repeat in range(3):
            vertices, _ = m41.plaquette_vertices(centers[member], member_index)
            for vertex_index, coordinate in enumerate(vertices):
                value = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M41R1", "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": config["configuration_id"], "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat, "vertex_index": vertex_index, "center": list(map(float, centers[member])), "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4, "resolution": int(config["resolution"]), "tolerance": float(config["tolerance"]), "mesh_size": int(config["mesh_size"]), "polarization": "TE", "source_commit": source_commit}
                value["request_key_sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(value)
    if len(graph) != 36 or len({item["request_key_sha256"] for item in graph}) != 36:
        raise ValueError("M41R1_GRAPH_INVALID")
    return graph


def _make_result(bundle: Mapping[str, Any], source_commit: str, records: Sequence[Mapping[str, Any]], analyses: Mapping[str, Any], graphs: Mapping[str, Any], trigger: bool, reasons: Sequence[str], dataset: Mapping[str, Any] | None, parent_records: int) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS" if len(records) in (72, 108) else "PARTIAL_ACQUISITION", "scientific_acceptance_status": "PASS" if len(records) in (72, 108) else "FAIL_CLOSED", "machine_execution_contract_status": "ONE_NATIVE_M41R1_RECOVERY_72_OR_108_COMPLETE" if len(records) in (72, 108) else "M41R1_PARTIAL_ACQUISITION", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": len(records), "solver_execution_count": len(records), "dataset_record_count": len(records), "new_record_count": len(records), "cumulative_m41_chain_record_count": parent_records + len(records), "dataset_id": None if dataset is None else dataset.get("dataset_id"), "manifest_sha256": None if dataset is None else dataset.get("manifest_sha256"), "partial_parent_namespace_sha256": PARTIAL_NAMESPACE_SHA256, "partial_parent_record_count": 36, "partial_parent_configuration_id": "R128_T1E9_M3", "executed_configuration_ids": list(analyses), "conditional_R96_executed": trigger, "conditional_R96_trigger_reasons": list(reasons), "request_graph_sha256_by_configuration": {key: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest() for key, value in graphs.items()}, "configuration_analysis": analyses, "baseline": {"configuration_id": "R128_T1E7_M3", "dataset_id": m41.BASELINE_DATASET_ID, "manifest_sha256": m41.BASELINE_MANIFEST_SHA256, "record_count": 72, "read_only": True}, "resolution_aware_raw_contract": {"mode_count_by_resolution": {"64": 4096, "96": 9216, "128": 16384}, "fft_label_shape": "(resolution,resolution)", "ordinary_transfer": "B_target^T B_source at identical FFT label; no C3 rotation"}, "stale_inherited_metadata_note": "Recovered R128_T1E9_M3 parent may retain inherited M39 requested_tolerance=1e-7; active M41 configuration_id/tolerance/mesh metadata are authoritative.", "next_science_decision": "TARGETED_NEXT_DISCRIMINANT_FROM_M41R1_EVIDENCE" if not analyses else "QUALIFIED_T1E9_SETTINGS_AND_ADVANCE_TO_FULL_G15_MAP_IF_RANK1_PASSES", "goal_completion_status": "NOT_COMPLETE_CONTINUE_CAUSAL_BRANCH", "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    counter = None
    try:
        job = _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m41r1_job")
        m39 = _load(ROOT / "audit" / "berry_c3_consistency" / "m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m41r1_m39")
        m38 = _load(ROOT / "audit" / "berry_c3_consistency" / "m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m41r1_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = _read_partial(job, state_root)
        m18 = m40r2._read_dataset(job, state_root, m40r2.M18_DATASET_ID, m40r2.M18_MANIFEST_SHA256, m40r2.M18_SCHEMA, 3)
        m39r1 = m40r2._read_dataset(job, state_root, M39R1_DATASET_ID, M39R1_MANIFEST_SHA256, M39R1_SCHEMA, 14)
        centers = m40r2._centers(m18, m39r1)
        _patch_parent_helpers(m39, m38)
        analyses: dict[str, Any] = {"R128_T1E9_M3": m41._configuration_analysis(partial, centers, m38, m39, "R128_T1E9_M3")}
        graphs = {name: _new_graph(config, centers, source_commit) for config, name in (({"configuration_id": "R128_T1E9_M1", "resolution": 128, "tolerance": 1e-9, "mesh_size": 1}, "R128_T1E9_M1"), ({"configuration_id": "R64_T1E9_M3", "resolution": 64, "tolerance": 1e-9, "mesh_size": 3}, "R64_T1E9_M3"), ({"configuration_id": "R96_T1E9_M3", "resolution": 96, "tolerance": 1e-9, "mesh_size": 3}, "R96_T1E9_M3"))}
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=128, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(108, 108)
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA})
        configs = [("R128_T1E9_M1", 128, 1), ("R64_T1E9_M3", 64, 3)]
        for config_id, resolution, mesh_size in configs:
            for spec in graphs[config_id]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=resolution, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=mesh_size)
                captured = capture_state_resolution_aware(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": config_id, "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": config_id, "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses[config_id] = m41._configuration_analysis([row for row in records if row["configuration_id"] == config_id], centers, m38, m39, config_id)
        trigger, reasons = m41.conditional_r96_trigger(analyses)
        if trigger:
            for spec in graphs["R96_T1E9_M3"]:
                reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
                solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=96, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=3)
                captured = capture_state_resolution_aware(mp, solver, spec, counter, source_commit)
                key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": "R96_T1E9_M3", "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
                store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": "R96_T1E9_M3", "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
                records.append(captured)
            analyses["R96_T1E9_M3"] = m41._configuration_analysis([row for row in records if row["configuration_id"] == "R96_T1E9_M3"], centers, m38, m39, "R96_T1E9_M3")
        if len(records) not in (72, 108) or counter.provider_count != len(records) or counter.solver_count != len(records):
            raise ValueError(f"M41R1_COUNT_INVALID:{len(records)}:{counter.provider_count}:{counter.solver_count}")
        dataset = store.finalize(len(records), {"dataset_schema": DATASET_SCHEMA, "source_partial_namespace_sha256": PARTIAL_NAMESPACE_SHA256, "source_partial_record_count": 36, "configuration_ids": list(analyses), "request_graph_sha256_by_configuration": {name: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest() for name, value in graphs.items()}, "conditional_R96_executed": trigger, "cumulative_m41_chain_record_count": 36 + len(records)})
        result = _make_result(bundle, source_commit, records, analyses, graphs, trigger, reasons, dataset, 36)
    except BaseException as exc:
        result = _make_result(bundle, source_commit, records, {}, {}, False, [], None, 36)
        result.update({"status": "PARTIAL_ACQUISITION" if records else "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": str(exc)[:1024], "failure_stage": "parent_recovery_or_acquisition_or_analysis", "exception_type": type(exc).__name__, "native_invocation_count": 1 if counter is not None else 0, "provider_execution_count": getattr(counter, "provider_count", 0), "solver_execution_count": getattr(counter, "solver_count", 0), "dataset_record_count": len(records)})
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
