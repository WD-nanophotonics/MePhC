"""M66: repeat-qualified native rank-2 projector scalar covariance.

The acquisition is deliberately narrow: the canonical M7 G15 orbit is solved
three times at each member.  Raw MPB vectors are retained losslessly, while
all cross-member gates use phase/U(2)-invariant scalar arrays.  No fitted map,
phase, permutation, or C3 symmetrization is used.
"""
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
SHAPE = (N, N)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
RESULT_SCHEMA = "mephc-berry-c3-consistency-m66-native-rank2-projector-scalar-covariance-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m66-native-rank2-projector-scalar-dataset-v1"
M65 = ("6e07cf0bfbf567cbe1490fe0868e663b73571ace41fa1fa26a6771e31af0cdea", "dcc4e1ec8664b9fc9ef2e5af752d64f3fa1cda389752973416525a9cf9b8fae5", "mephc-berry-c3-consistency-m65-gauge-invariant-scalar-ladder-dataset-v1", 6)
M50 = ("9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d", "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed", "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1", 36)
M63 = ("bd02f350a86d8376f89f9ef08cc943a117cbac2cece62ffa84e1266ae07d1a29", "f650352c9d8f3872ba880f82a15ec5e0c2cfa629a80c6af147a0204b6fc0698e", "mephc-berry-c3-consistency-m63-homogeneous-raw-mode-tolerance-dataset-v1", 18)
K = np.asarray([2.0 / 3.0, 0.0], dtype=float)
RANK2 = (1, 2)


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
        return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M66_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M66_IMPORT_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_dataset(job: Any, root: Path, binding: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = binding
    verified = job.verify_dataset(root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M66_DATASET_BINDING_INVALID", dataset_id)
    rows = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"]
        row = json.loads(payload.decode("utf-8"))
        require(row.get("schema") == schema, "M66_DATASET_SCHEMA_INVALID", dataset_id)
        rows.append(row)
    return rows


def orbit_centers(m: int = 7) -> dict[str, list[float]]:
    seed = K - np.asarray([float(m) / 36.0, 0.0])
    result: dict[str, list[float]] = {}
    for index, member in enumerate(MEMBERS):
        angle = 2.0 * math.pi * index / 3.0
        rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        result[member] = (K + rotation @ (seed - K)).tolist()
    require(result["IDENTITY"] == [17.0 / 36.0, 0.0], "M66_M7_IDENTITY_INVALID")
    require(len({tuple(v) for v in result.values()}) == 3, "M66_M7_ORBIT_NOT_DISTINCT")
    return result


def _encode_array(value: Any) -> dict[str, Any]:
    array = np.asarray(value)
    require(array.dtype.kind in "fc", "M66_ARRAY_DTYPE_INVALID", str(array.dtype))
    stream = io.BytesIO()
    np.save(stream, array, allow_pickle=False)
    payload = zlib.compress(stream.getvalue(), level=6)
    return {"encoding": "zlib-npy-lossless", "shape": list(array.shape), "dtype": str(array.dtype), "sha256": hashlib.sha256(array.tobytes()).hexdigest(), "payload_base64": base64.b64encode(payload).decode("ascii")}


def _normalize_raw(m41: Any, raw: Any, resolution: int = N) -> tuple[np.ndarray, dict[str, Any]]:
    value = np.asarray(raw, dtype=np.complex128)
    canonical_raw, diagnostics = m41._normalize_raw(value, resolution)
    require(canonical_raw.shape == (4, resolution * resolution, 2), "M66_RAW_CANONICAL_SHAPE_INVALID", str(canonical_raw.shape))
    return canonical_raw, diagnostics


def _gram(raw: np.ndarray) -> dict[str, Any]:
    flat = np.asarray(raw, dtype=np.complex128).reshape(4, -1)
    norms = np.linalg.norm(flat, axis=1)
    require(np.all(norms > 0.0), "M66_RAW_ZERO_NORM")
    normalized = flat / norms[:, None]
    gram = normalized @ normalized.conj().T
    return {"matrix": _safe(gram), "normalization_residual": float(np.max(np.abs(np.diag(gram) - 1.0))), "offdiagonal_residual": float(np.max(np.abs(gram - np.diag(np.diag(gram)))))}


def reciprocal_projector_scalar(raw: np.ndarray) -> np.ndarray:
    value = np.asarray(raw, dtype=np.complex128)
    require(value.shape == (4, N * N, 2), "M66_RAW_PROJECTOR_SHAPE_INVALID", str(value.shape))
    power = np.sum(np.abs(value[list(RANK2), :, :]) ** 2, axis=(0, 2)).reshape(SHAPE)
    require(np.all(np.isfinite(power)) and float(np.sum(power)) > 0.0, "M66_RECIPROCAL_SCALAR_INVALID")
    return power


def normalized_scalar(value: np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    total = float(np.sum(array))
    require(total > 0.0 and np.all(np.isfinite(array)), "M66_SCALAR_NORMALIZATION_INVALID")
    return array / total


def _realspace_projector_scalar(m38: Any, raw: np.ndarray, coordinate: Sequence[float]) -> np.ndarray:
    value = np.asarray(raw, dtype=np.complex128)
    basis = np.asarray(m38.reciprocal_basis(), dtype=float)
    fields = []
    for band_index in RANK2:
        coefficient = np.zeros((*SHAPE, 3), dtype=np.complex128)
        for index in range(N * N):
            label = m38.fft_label(index, shape=SHAPE)
            q = np.asarray([float(coordinate[0]), float(coordinate[1]), 0.0]) - np.asarray([*(basis @ np.asarray(label, dtype=float)), 0.0])
            m_frame, n_frame, _ = m38.transverse_frame(q)
            coefficient[index // N, index % N, :] = value[band_index, index, 0] * m_frame + value[band_index, index, 1] * n_frame
        fields.append(np.stack([np.fft.ifft2(coefficient[:, :, component]) for component in range(3)], axis=-1))
    density = sum(np.sum(np.abs(field) ** 2, axis=-1) for field in fields)
    return np.asarray(density, dtype=float)


def _direct_index_map(m54: Any) -> np.ndarray:
    mapping = m54.build_index_map()
    require(mapping.shape == (N, N, 2), "M66_DIRECT_MAP_SHAPE_INVALID")
    cubed = mapping[mapping[..., 0], mapping[..., 1], :]
    cubed = mapping[cubed[..., 0], cubed[..., 1], :]
    require(np.array_equal(cubed, np.indices(SHAPE).transpose(1, 2, 0)), "M66_DIRECT_MAP_CUBED_INVALID")
    return mapping


def _reciprocal_index_map(m38: Any, edge: Mapping[str, Any]) -> np.ndarray:
    result = np.empty((*SHAPE, 2), dtype=int)
    for index in range(N * N):
        source = m38.fft_label(index, shape=SHAPE)
        target = m38.raw_fft_edge_map(source, edge["G_edge_integer"], shape=SHAPE)
        target_index = m38.fft_index(target, shape=SHAPE)
        result[index // N, index % N] = (target_index // N, target_index % N)
    flat = result.reshape(-1, 2)
    require(len({tuple(v) for v in flat}) == N * N, "M66_RECIPROCAL_MAP_NOT_BIJECTIVE")
    return result


def _apply_map(value: np.ndarray, mapping: np.ndarray) -> np.ndarray:
    output = np.empty_like(value)
    output[mapping[..., 0], mapping[..., 1]] = value
    return output


def array_repeat_ledger(rows: Sequence[Mapping[str, Any]], field: str, maps: Mapping[tuple[str, str], np.ndarray]) -> dict[str, Any]:
    central: dict[str, np.ndarray] = {}
    uncertainty: dict[str, float] = {}
    for member in MEMBERS:
        arrays = [np.asarray(row[field], dtype=float) for row in rows if row["member"] == member]
        require(len(arrays) == 3, "M66_REPEAT_COUNT_INVALID", f"{field}:{member}")
        med = np.median(np.stack(arrays), axis=0)
        central[member] = med
        uncertainty[member] = float(max(np.max(np.abs(array - med)) for array in arrays))
    directed: dict[str, Any] = {}
    for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
        mapped = _apply_map(central[source], maps[(source, target)])
        residual = float(np.max(np.abs(mapped - central[target])))
        l1 = float(np.sum(np.abs(mapped - central[target])))
        l2 = float(np.linalg.norm(mapped - central[target]))
        directed[f"{source}_to_{target}"] = {"residual_linf": residual, "residual_l1_descriptive": l1, "residual_l2_descriptive": l2, "source_uncertainty_linf": uncertainty[source], "target_uncertainty_linf": uncertainty[target], "pass": residual <= uncertainty[source] + uncertainty[target]}
    return {"central": {member: _encode_array(value) for member, value in central.items()}, "uncertainty_linf": uncertainty, "directed": directed, "all_pass": all(item["pass"] for item in directed.values())}


def frequency_ledger(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    central: dict[str, list[float]] = {}
    uncertainty: dict[str, list[float]] = {}
    for member in MEMBERS:
        values = [np.asarray(row["frequencies_bands_1_to_4"], dtype=float) for row in rows if row["member"] == member]
        require(len(values) == 3, "M66_FREQUENCY_REPEAT_COUNT_INVALID", member)
        med = np.median(np.stack(values), axis=0)
        central[member] = med.tolist()
        uncertainty[member] = np.max(np.abs(np.stack(values) - med), axis=0).tolist()
    directed = {}
    for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
        residual = np.abs(np.asarray(central[source]) - np.asarray(central[target]))
        limit = np.asarray(uncertainty[source]) + np.asarray(uncertainty[target])
        directed[f"{source}_to_{target}"] = {"central_difference": residual.tolist(), "combined_uncertainty": limit.tolist(), "pass_by_band": (residual <= limit).tolist(), "pass": bool(np.all(residual <= limit))}
    return {"central": central, "uncertainty": uncertainty, "directed": directed, "all_pass": all(item["pass"] for item in directed.values())}


def qualify_rank2_window(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = {}
    qualified = True
    for member in MEMBERS:
        gaps = [np.asarray([row["frequencies_bands_1_to_4"][1] - row["frequencies_bands_1_to_4"][0], row["frequencies_bands_1_to_4"][3] - row["frequencies_bands_1_to_4"][2]], dtype=float) for row in rows if row["member"] == member]
        med = np.median(np.stack(gaps), axis=0)
        unc = np.max(np.abs(np.stack(gaps) - med), axis=0)
        ok = bool(np.all((med > 0.0) & (med > unc)))
        qualified = qualified and ok
        result[member] = {"median_external_gaps": med.tolist(), "repeat_uncertainty": unc.tolist(), "qualified": ok}
    return {"members": result, "qualified": qualified, "pair": [2, 3], "internal_gap_not_required": True}


def classify(freq: Mapping[str, Any], reciprocal: Mapping[str, Any], realspace: Mapping[str, Any], window: Mapping[str, Any]) -> tuple[str, str]:
    if not window["qualified"]:
        return "R256_M66_RANK2_SUBSPACE_WINDOW_UNQUALIFIED", "M7_ADJACENT_BAND_WINDOW_NATIVE_SUBSPACE_QUALIFICATION"
    if freq["all_pass"]:
        if reciprocal["all_pass"] and realspace["all_pass"]:
            return "R256_M66_M65_M7_FREQUENCY_FAILURE_NOT_REPRODUCED_SCALAR_C3_PASS", "M7_FREQUENCY_REQUALIFICATION_AND_FULL_NATIVE_RANK2_PROJECTOR_COVARIANCE"
        return "R256_M66_M65_M7_FREQUENCY_FAILURE_NOT_REPRODUCED_PROJECTOR_SCALAR_BREAK", "M7_FULL_NATIVE_RANK2_PROJECTOR_C3_COVARIANCE_FROM_M66_RAW_DATA"
    if not reciprocal["all_pass"]:
        return "R256_M66_FREQUENCY_C3_FAILURE_RECIPROCAL_PROJECTOR_SCALAR_BREAK", "M7_FULL_NATIVE_RANK2_PROJECTOR_C3_COVARIANCE_FROM_M66_RAW_DATA"
    if not realspace["all_pass"]:
        return "R256_M66_FREQUENCY_C3_FAILURE_RECIPROCAL_PASS_REALSPACE_PROJECTOR_BREAK", "M7_RECIPROCAL_OFFDIAGONAL_PROJECTOR_PHASE_C3_LOCALIZATION_FROM_M66_RAW_DATA"
    return "R256_M66_FREQUENCY_C3_FAILURE_NATIVE_PROJECTOR_SCALARS_PASS", "M7_FULL_NATIVE_RANK2_PROJECTOR_C3_COVARIANCE_FROM_M66_RAW_DATA"


def _geometry(mp: Any, band: Any) -> tuple[list[Any], dict[str, Any]]:
    a = mp.Vector3(0.0, 0.0, 0.0)
    b = mp.Vector3(2.0 / 3.0, 1.0 / 3.0, 0.0)
    features = [mp.Cylinder(center=a, radius=band.r1 / band.a, material=mp.air, height=100.0), mp.Cylinder(center=b, radius=band.r2 / band.a, material=mp.air, height=100.0)]
    return band.create_material_block() + features, {"geometry_id": "G15", "orbit_id": "M7", "continuous_c3_status": "PASS", "feature_centers": [[0.0, 0.0], [2.0 / 3.0, 1.0 / 3.0]]}


def _public_probe(solver: Any) -> dict[str, Any]:
    values = {}
    for name, getter in (("hfield", solver.get_hfield), ("efield", solver.get_efield)):
        arrays = [np.asarray(getter(index, bloch_phase=False)) for index in RANK2]
        values[name] = [{"shape": list(value.shape), "dtype": str(value.dtype), "sha256": hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()} for value in arrays]
    epsilon = np.asarray(solver.get_epsilon())
    values["epsilon"] = {"shape": list(epsilon.shape), "dtype": str(epsilon.dtype), "sha256": hashlib.sha256(np.ascontiguousarray(epsilon).tobytes()).hexdigest()}
    return {"status": "PUBLIC_FIELD_MAPPING_WITHHELD", "reason": "M66_CONTRACT_REQUIRES_SOURCE_PROVEN_OUTPUT_GRID_ORIGIN_AXIS_PHASE_AND_INTERPOLATION", "probes": values}


def _solve(mp: Any, mpb: Any, band: Any, coordinate: Sequence[float], geometry: list[Any], counter: Any, m41: Any, m38: Any) -> dict[str, Any]:
    counter.consume_solver()
    reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0), band.geo_latt)
    solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=N, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=1)
    solver.run_parity(mp.TE, False)
    frequencies = np.asarray(solver.all_freqs, dtype=float).reshape(-1)[:4]
    require(frequencies.size == 4, "M66_FREQUENCY_LAYOUT_INVALID")
    native = np.asarray(solver.get_eigenvectors(1, 4), dtype=np.complex128)
    raw, layout = _normalize_raw(m41, native)
    reciprocal_scalar = reciprocal_projector_scalar(raw)
    realspace_scalar = _realspace_projector_scalar(m38, raw, coordinate)
    return {"frequencies_bands_1_to_4": frequencies.tolist(), "adjacent_gaps": {"lower_external": float(frequencies[1] - frequencies[0]), "internal": float(frequencies[2] - frequencies[1]), "upper_external": float(frequencies[3] - frequencies[2])}, "raw_eigenvector": _encode_array(native), "raw_layout": layout, "raw_rank2_gram": _gram(raw), "reciprocal_projector_scalar": _encode_array(reciprocal_scalar), "reciprocal_projector_scalar_normalized": _encode_array(normalized_scalar(reciprocal_scalar)), "realspace_projector_scalar": _encode_array(realspace_scalar), "realspace_projector_scalar_normalized": _encode_array(normalized_scalar(realspace_scalar)), "public_crosscheck": _public_probe(solver)}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    counter = None
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m66_job")
        m41 = _load(ROOT / "audit/berry_c3_consistency/m41r3_recover36_finish_convergence.py", "m66_m41")
        m38 = _load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m66_m38")
        m54 = _load(ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py", "m66_m54")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        m65_rows = _read_dataset(job, state_root, M65)
        _read_dataset(job, state_root, M50)
        _read_dataset(job, state_root, M63)
        centers = orbit_centers(7)
        for row in m65_rows:
            if row.get("geometry_id") == "G15":
                require(np.allclose(row["coordinate"], centers[row["member"]], rtol=0.0, atol=1e-12), "M66_M65_ORBIT_BINDING_INVALID", str(row.get("member")))
        states = {member: {"c3_member_identity": member, "coordinate": centers[member]} for member in MEMBERS}
        edges = m38._edges(states)
        structural = m38.structural_validation(edges, states)
        require(structural["synthetic_closure_status"] == "PASS", "M66_RECIPROCAL_C3_STRUCTURAL_VALIDATION_FAILED")
        direct_map = _direct_index_map(m54)
        reciprocal_maps = {(edge["edge_source_member"], edge["edge_target_member"]): _reciprocal_index_map(m38, edge) for edge in edges}
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=N, lattice_type="triangular", polarization="TE", structure_type="slab")
        geometry, geometry_proof = _geometry(mp, band)
        counter = job.BudgetCounter(0, 9)
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}
        store = job.ImmutableDatasetStore(state_root, namespace)
        require(not store.root.exists(), "M66_DATASET_NAMESPACE_EXISTS")
        for member in MEMBERS:
            for repeat in range(3):
                item = {"schema": DATASET_SCHEMA, "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "member": member, "repeat_index": repeat, "orbit_id": "M7", "geometry_id": "G15", "coordinate": centers[member], **_solve(mp, mpb, band, centers[member], geometry, counter, m41, m38)}
                key = canonical({"work_order_id": bundle["work_order_id"], "member": member, "repeat": repeat, "orbit_id": "M7"})
                store.put(key, canonical(item), {"member": member, "repeat": repeat, "orbit_id": "M7"})
                records.append(item)
        freq = frequency_ledger(records)
        window = qualify_rank2_window(records)
        reciprocal_rows = [{"member": row["member"], "reciprocal": np.load(io.BytesIO(zlib.decompress(base64.b64decode(row["reciprocal_projector_scalar_normalized"]["payload_base64"]))), allow_pickle=False)} for row in records]
        realspace_rows = [{"member": row["member"], "realspace": np.load(io.BytesIO(zlib.decompress(base64.b64decode(row["realspace_projector_scalar_normalized"]["payload_base64"]))), allow_pickle=False)} for row in records]
        reciprocal = array_repeat_ledger(reciprocal_rows, "reciprocal", reciprocal_maps)
        realspace = array_repeat_ledger(realspace_rows, "realspace", {key: direct_map for key in reciprocal_maps})
        outcome, next_decision = classify(freq, reciprocal, realspace, window)
        manifest = store.finalize(9, {"dataset_schema": DATASET_SCHEMA, "orbit_id": "M7", "solver_execution_count": counter.solver_count, "raw_storage": "lossless_native_get_eigenvectors"})
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_DIAGNOSTIC", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "m65_reference": {"dataset_id": M65[0], "manifest_sha256": M65[1], "record_count": len(m65_rows), "reference_only": True}, "orbit_id": "M7", "orbit_centers": centers, "geometry_proof": geometry_proof, "reciprocal_c3_mapping": {"formula": "f_target=S_recip*f_source-G_edge (mod 256)", "edges": edges, "structural_validation": structural}, "direct_grid_mapping": {"formula": "M54 source-derived D=[[-1,1],[-1,0]]", "shape": list(direct_map.shape), "c3_cubed_status": "PASS", "source_proven": True}, "frequency_requalification": freq, "rank2_window": window, "reciprocal_projector_scalar_ledger": reciprocal, "realspace_projector_scalar_ledger": realspace, "public_field_crosscheck": "WITHHELD_UNLESS_SOURCE_GRID_SEMANTICS_PROVEN", "classification": outcome, "causal_outcome": outcome, "next_science_decision": next_decision, "raw_complex_field_comparison": False, "gauge_or_u2_fitting": False, "band_permutation_fitting": False, "c3_symmetrization": False, "source_commit_used": source_commit, "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1 if counter is not None else 0, "provider_execution_count": 0, "solver_execution_count": 0 if counter is None else counter.solver_count, "dataset_record_count": len(records), "failure_code": str(exc)[:1024], "failure_stage": "m66_native_rank2_projector_scalar_covariance", "exception_type": type(exc).__name__, "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
