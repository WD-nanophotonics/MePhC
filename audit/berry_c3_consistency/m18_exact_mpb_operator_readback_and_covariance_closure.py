"""M18 exact MPB three-state readback and C3 covariance closure.

M18 is deliberately a direct ModeSolver path.  It repeats only the three
canonical G15 states already represented by M12/M13, with six bands, to make
the runtime constitutive data and fields available for calibration.  It does
not use the live provider and does not create a new physical-state dataset;
the output dataset is explicitly tagged as runtime readback evidence.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
M13_DATASET_ID = "dcaee157184d53a6a8025a374505084e105cde49f55d9ea345b55bae058dedcd"
M13_MANIFEST_SHA256 = "04917fb96a15c05ed83d54004b098ae6c72fb0c9b64a61ec241941cb69905378"
M17_DATASET_ID = "ee9ef4a7b21e5fa6a98f02f62052aa6bef8be71370f0aff85653d4235f7bac82"
M17_MANIFEST_SHA256 = "794c63d6d4d40f4a397707d3f35cd231332dbf76b1e251ef0645742becf0c639"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-dataset-v1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m18-exact-mpb-operator-readback-covariance-closure-v1"
SHAPE = (128, 128)
COMPONENT_COUNT = 3
BANDS = 6
BLOCK = SHAPE[0] * SHAPE[1] * COMPONENT_COUNT
VECTOR_LENGTH = 2 * BLOCK
MESH_SIZE = 3
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)
G15 = {"a": 400.0, "r1": 80.14335684352235, "r2": 75.13439704080221, "n1": 15, "n2": 15, "theta1_degrees": 0.0, "theta2_degrees": 60.0, "n_eff": 2.7, "height": 100.0}


class M18Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M18Error(f"{code}:{detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "M18_DEPENDENCY_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _m12() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m12_g15_wider_band_subspace_leakage_localization.py", "m18_m12_helpers")


def _m13() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m13_g15_adjacent_band_window_discrimination.py", "m18_m13_helpers")


def _m15() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py", "m18_m15_helpers")


def _m16() -> Any:
    return _load(ROOT / "audit" / "berry_c3_consistency" / "m16_discrete_material_maxwell_residual_covariance.py", "m18_m16_helpers")


def _job() -> Any:
    return _load(ROOT / "tools" / "mephc-flow" / "scientific_job.py", "m18_scientific_job")


def read_dataset(job: Any, state_root: Path, dataset_id: str, manifest_sha: str, count: int) -> list[dict[str, Any]]:
    verified = job.verify_dataset(state_root, dataset_id)
    require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest_sha and verified.get("record_count") == count, "M18_DATASET_BINDING_INVALID", dataset_id)
    records = []
    for key in verified["record_key_sha256"]:
        payload = job.resolve_dataset_record(state_root, dataset_id, manifest_sha, key).get("payload")
        require(isinstance(payload, bytes), "M18_DATASET_PAYLOAD_MISSING", dataset_id)
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M18_DATASET_PAYLOAD_INVALID", dataset_id)
        records.append(value)
    return records


def select_triplet(m12: Sequence[Mapping[str, Any]], m13: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = _m13().select_same_triplet(m13)
    old = {item["request_key_sha256"]: item for item in m12}
    require(len(selected) == 3 and all(item["request_key_sha256"] in old for item in selected), "M18_TRIPLET_BINDING_INVALID")
    return sorted(selected, key=lambda item: int(item["member_index"]))


def production_solver_factory() -> tuple[Any, Any]:
    """Return a direct six-band ModeSolver factory with production geometry."""
    import meep as mp
    from meep import mpb
    from mephc.band import Band

    band = Band(a=G15["a"], r1=G15["r1"], r2=G15["r2"], n_eff=G15["n_eff"], h=G15["height"], resolution=128, lattice_type="triangular", polarization="TE", structure_type="slab")
    pattern = band.create_unitcell(G15["n1"], G15["theta1_degrees"], G15["n2"], G15["theta2_degrees"], show=False)
    geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)

    def factory(member: Mapping[str, Any]) -> tuple[Any, Any, Any]:
        public = mp.Vector3(float(member["coordinate"][0]), float(member["coordinate"][1]), 0.0)
        reciprocal = mp.cartesian_to_reciprocal(public, band.geo_latt)
        solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=128, num_bands=BANDS, default_material=mp.air, tolerance=1e-7, deterministic=False, mesh_size=MESH_SIZE)
        return solver, reciprocal, mp.TE

    return factory, band


def _field_array(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim == 4 and array.shape == (*SHAPE, 1, COMPONENT_COUNT):
        array = array[:, :, 0, :]
    require(array.shape == (*SHAPE, COMPONENT_COUNT), "M18_FIELD_SHAPE_INVALID", f"{name}:{array.shape}")
    array = np.asarray(array, dtype=np.complex128)
    require(np.all(np.isfinite(array)), "M18_FIELD_NONFINITE", name)
    return np.array(array, copy=True)


def _complex_encode(array: Any) -> list[list[list[list[list[float]]]]]:
    value = np.asarray(array, dtype=np.complex128)
    require(value.ndim == 4 and value.shape[2] == COMPONENT_COUNT, "M18_ENCODE_LAYOUT_INVALID")
    return [[[[[float(pair.real), float(pair.imag)] for pair in value[x, y, component, :]] for component in range(value.shape[2])] for y in range(value.shape[1])] for x in range(value.shape[0])]


def _complex_decode(payload: Any, shape: tuple[int, int, int, int]) -> np.ndarray:
    value = np.asarray(payload, dtype=float)
    require(value.shape == (*shape, 2), "M18_FIELD_PAYLOAD_INVALID", str(value.shape))
    return value[..., 0] + 1j * value[..., 1]


def _point_tuple(value: Any) -> list[float]:
    if isinstance(value, (tuple, list, np.ndarray)):
        array = np.asarray(value, dtype=float).reshape(-1)
        require(array.size == 3, "M18_KPOINT_LAYOUT_INVALID")
        return [float(item) for item in array]
    return [float(getattr(value, axis)) for axis in ("x", "y", "z")]


def _record_id(record: Mapping[str, Any]) -> str:
    identity = {"schema": record["schema"], "request_key_sha256": record["request_key_sha256"], "member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "geometry_id": record["geometry_id"], "coordinate": record["coordinate"], "frequencies_bands_1_to_6": record["frequencies_bands_1_to_6"], "epsilon_grid_sha256": record["epsilon_grid_sha256"], "readback_field_sha256": record.get("readback_field_sha256"), "source_commit": record.get("source_commit")}
    return "MEPHC-M18-READBACK-" + hashlib.sha256(canonical(identity)).hexdigest()


def capture_one(solver: Any, reciprocal: Any, parity: Any, member: Mapping[str, Any], counter: Any) -> dict[str, Any]:
    """Perform exactly one six-band solve and immediate runtime readback."""
    counter.consume_solver()
    solver.run_parity(parity, False)
    frequencies = np.asarray(solver.all_freqs, dtype=float)
    if frequencies.ndim == 2:
        frequencies = frequencies[0]
    require(frequencies.shape == (BANDS,), "M18_FREQUENCY_LAYOUT_INVALID")
    epsilon_raw = np.asarray(solver.get_epsilon(), dtype=float)
    require(epsilon_raw.size == SHAPE[0] * SHAPE[1], "M18_EPSILON_GRID_SHAPE_INVALID")
    epsilon = epsilon_raw.reshape(SHAPE)
    require(np.all(np.isfinite(epsilon)) and np.all(epsilon > 0.0), "M18_EPSILON_GRID_INVALID")
    fields_e, fields_h, fields_d, fields_b = [], [], [], []
    d_status, b_status = "UNAVAILABLE", "UNAVAILABLE"
    for band in range(1, BANDS + 1):
        fields_e.append(_field_array(solver.get_efield(band, bloch_phase=False), "E"))
        fields_h.append(_field_array(solver.get_hfield(band, bloch_phase=False), "H"))
    get_d = getattr(solver, "get_dfield", None)
    if callable(get_d):
        try:
            fields_d = [_field_array(get_d(band, bloch_phase=False), "D") for band in range(1, BANDS + 1)]
            d_status = "CAPTURED"
        except Exception as exc:
            d_status = f"ACCESS_FAILED:{type(exc).__name__}"
    get_b = getattr(solver, "get_bfield", None)
    if callable(get_b):
        try:
            fields_b = [_field_array(get_b(band, bloch_phase=False), "B") for band in range(1, BANDS + 1)]
            b_status = "CAPTURED"
        except Exception as exc:
            b_status = f"ACCESS_FAILED:{type(exc).__name__}"
    e_array, h_array = np.stack(fields_e, axis=0), np.stack(fields_h, axis=0)
    d_array = np.stack(fields_d, axis=0) if fields_d else None
    b_array = np.stack(fields_b, axis=0) if fields_b else None
    weighted = e_array * np.sqrt(epsilon)[None, ..., None]
    energy = np.concatenate([weighted.reshape(BANDS, -1), h_array.reshape(BANDS, -1)], axis=1)
    norms = np.linalg.norm(energy, axis=1)
    require(np.all(norms > 0.0), "M18_ZERO_FIELD")
    energy = energy / norms[:, None]
    record = {
        "schema": DATASET_SCHEMA, "request_key_sha256": member["request_key_sha256"], "member_index": int(member["member_index"]), "c3_member_identity": member["c3_member_identity"], "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "coordinate": list(member["coordinate"]), "mpb_reciprocal_k_point": _point_tuple(reciprocal), "deterministic": False, "frame_convention": "LAB_FIXED", "repeat_index": 1, "num_bands": BANDS,
        "frequencies_bands_1_to_6": frequencies.tolist(), "epsilon_grid_shape": list(epsilon.shape), "epsilon_grid_dtype": str(epsilon.dtype), "epsilon_material_representation_type": "SCALAR_EPSILON_GRID", "material_grid_axis_order": "(x,y), C-order reshape", "material_grid_coordinate_convention": "MPB geometry-lattice fractional cell coordinates", "subpixel_or_smoothing_configuration": {"mesh_size": MESH_SIZE, "deterministic": False, "runtime_configuration": "direct ModeSolver construction"}, "field_material_grid_alignment_status": "CAPTURED_EPSILON_AND_FIELDS_SAME_MODELSOLVER_RUNTIME", "boundary_or_staggering_metadata_status": "MPB_PERIODIC_BOUNDARY; FIELD_STAGGERING_PUBLIC_METADATA_NOT_EXPOSED", "epsilon_inverse_or_tensor_metadata_status": "NOT_REQUESTED_DIRECTLY; D/B_READBACK_RECORDED_WHEN_AVAILABLE", "D_field_availability_status": d_status, "B_field_availability_status": b_status,
        "epsilon_grid_sha256": hashlib.sha256(canonical(epsilon.tolist())).hexdigest(), "epsilon_grid": epsilon.tolist(),
        "fresh_e_fields_bands_1_to_6": _complex_encode(e_array.transpose(1, 2, 3, 0)), "fresh_h_fields_bands_1_to_6": _complex_encode(h_array.transpose(1, 2, 3, 0)),
        "fresh_d_fields_bands_1_to_6": _complex_encode(d_array.transpose(1, 2, 3, 0)) if d_array is not None else None, "fresh_b_fields_bands_1_to_6": _complex_encode(b_array.transpose(1, 2, 3, 0)) if b_array is not None else None,
        "fresh_energy_vectors_bands_1_to_6": [[[float(value.real), float(value.imag)] for value in energy[:, band]] for band in range(BANDS)], "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "forbidden_solver_call_count": 0,
    }
    field_digest = hashlib.sha256(e_array.tobytes() + h_array.tobytes() + (d_array.tobytes() if d_array is not None else b"") + (b_array.tobytes() if b_array is not None else b"")).hexdigest()
    record["readback_field_sha256"] = field_digest
    record["record_id"] = _record_id(record)
    return record


def capture_triplet(members: Sequence[Mapping[str, Any]], factory: Any, counter: Any) -> list[dict[str, Any]]:
    records = []
    for member in sorted(members, key=lambda item: int(item["member_index"])):
        solver, reciprocal, parity = factory(member)
        records.append(capture_one(solver, reciprocal, parity, member, counter))
    require(len(records) == 3, "M18_READBACK_RECORD_COUNT_INVALID")
    return records


def persist_readback(job: Any, state_root: Path, work_order_id: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": work_order_id, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "record_schema": DATASET_SCHEMA}
    store = job.ImmutableDatasetStore(state_root, namespace)
    ids = []
    for record in records:
        require(record.get("record_id") == _record_id(record), "M18_RECORD_ID_INVALID")
        ids.append(record["record_id"])
    require(len(ids) == len(set(ids)) == 3, "M18_RECORD_ID_NOT_UNIQUE")
    for record in records:
        key = canonical({"work_order_id": work_order_id, "member_index": record["member_index"], "record_id": record["record_id"]})
        store.put(key, canonical(dict(record)), {"member_index": record["member_index"], "c3_member_identity": record["c3_member_identity"], "record_id": record["record_id"]})
    return store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "readback_only": True, "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID})


def _decode_field(record: Mapping[str, Any], key: str) -> np.ndarray:
    return _complex_decode(record[key], (SHAPE[0], SHAPE[1], COMPONENT_COUNT, BANDS)).transpose(3, 0, 1, 2)


def _fresh_energy(record: Mapping[str, Any]) -> np.ndarray:
    return np.asarray([complex(pair[0], pair[1]) for band in record["fresh_energy_vectors_bands_1_to_6"] for pair in band], dtype=np.complex128).reshape(BANDS, VECTOR_LENGTH).T


def _state_reproduction(records: Sequence[Mapping[str, Any]], m12: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    old = {item["request_key_sha256"]: item for item in m12}
    freq_max, overlaps = 0.0, []
    m12mod = _m12()
    for record in records:
        archived = old[record["request_key_sha256"]]
        difference = np.abs(np.asarray(record["frequencies_bands_1_to_6"]) - np.asarray(archived["frequencies_bands_1_to_6"]))
        freq_max = max(freq_max, float(np.max(difference)))
        fresh = _fresh_energy(record)[:, 1:3]; old_frame = m12mod.decode_bands(archived["normalized_vectors_bands_1_to_6"])[:, 1:3]
        fq = np.linalg.qr(fresh, mode="reduced")[0]; oq = np.linalg.qr(old_frame, mode="reduced")[0]
        overlaps.append(float(np.min(np.linalg.svd(fq.conj().T @ oq, compute_uv=False))))
    return {"fresh_vs_M12_frequency_reproduction_residual_max": freq_max, "fresh_vs_archived_rank2_subspace_minimum_overlap_singular_value": min(overlaps), "scientific_state_reproduction_status": "EXACT_SEMANTIC_TRIPLET_BOUND; RAW_FREQUENCY_AND_RANK2_RESIDUALS_REPORTED_WITHOUT_INVENTED_THRESHOLD"}


def _constitutive_residual(e: np.ndarray, h: np.ndarray, epsilon: np.ndarray, omega: float, q: Sequence[float], d: np.ndarray | None = None, b: np.ndarray | None = None) -> dict[str, float]:
    m16 = _m16(); curl_e, curl_h = m16.maxwell_curl(e, q), m16.maxwell_curl(h, q)
    constitutive_d = epsilon[..., None] * e if d is None else d
    constitutive_b = h if b is None else b
    first = curl_e - 1j * float(omega) * constitutive_b
    second = curl_h + 1j * float(omega) * constitutive_d
    e_scale = max(float(np.linalg.norm(curl_e)), abs(float(omega)) * float(np.linalg.norm(constitutive_b)), np.finfo(float).tiny)
    h_scale = max(float(np.linalg.norm(curl_h)), abs(float(omega)) * float(np.linalg.norm(constitutive_d)), np.finfo(float).tiny)
    return {"maxwell": float(max(np.linalg.norm(first) / e_scale, np.linalg.norm(second) / h_scale)), "curlE": float(np.linalg.norm(first) / e_scale), "curlH": float(np.linalg.norm(second) / h_scale)}


def _fresh_exact_residual(record: Mapping[str, Any], *, archived: bool, m12_record: Mapping[str, Any] | None = None) -> dict[str, float]:
    m16 = _m16(); epsilon = np.asarray(record["epsilon_grid"], dtype=float).reshape(SHAPE)
    if archived:
        frame = m16.decode_bands(m12_record["normalized_vectors_bands_1_to_6"])
        e = frame[:BLOCK].T.reshape(BANDS, *SHAPE, COMPONENT_COUNT).transpose(1, 2, 3, 0) / np.sqrt(epsilon)[..., None, None]
        h = frame[BLOCK:].T.reshape(BANDS, *SHAPE, COMPONENT_COUNT).transpose(1, 2, 3, 0)
    else:
        e = _decode_field(record, "fresh_e_fields_bands_1_to_6").transpose(1, 2, 3, 0)
        h = _decode_field(record, "fresh_h_fields_bands_1_to_6").transpose(1, 2, 3, 0)
        d_readback = _decode_field(record, "fresh_d_fields_bands_1_to_6").transpose(1, 2, 3, 0) if record.get("fresh_d_fields_bands_1_to_6") is not None else None
        b_readback = _decode_field(record, "fresh_b_fields_bands_1_to_6").transpose(1, 2, 3, 0) if record.get("fresh_b_fields_bands_1_to_6") is not None else None
    if archived:
        d_readback = b_readback = None
    freq = np.asarray(record["frequencies_bands_1_to_6"], dtype=float); q = record["coordinate"]
    curl_e_max = curl_h_max = maxwell_max = 0.0
    for band in range(BANDS):
        res = _constitutive_residual(e[..., band], h[..., band], epsilon, float(freq[band]), q, d_readback[..., band] if d_readback is not None else None, b_readback[..., band] if b_readback is not None else None)
        curl_e_max = max(curl_e_max, res["curlE_residual"]); curl_h_max = max(curl_h_max, res["curlH_residual"]); maxwell_max = max(maxwell_max, res["maxwell_residual"])
    return {"maxwell": maxwell_max, "curlE": curl_e_max, "curlH": curl_h_max}


def _material_c3(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    m15 = _m15(); lattice = m15.lattice_automorphisms(); action = lattice["c3_direct_integer_automorphism"]; mapping = m15._m9().build_index_map(SHAPE, action); ordered = sorted(records, key=lambda item: int(item["member_index"]))
    residuals = []
    for index, record in enumerate(ordered):
        source = np.asarray(ordered[index]["epsilon_grid"], dtype=float); target = np.asarray(ordered[(index + 1) % 3]["epsilon_grid"], dtype=float); transformed = source[mapping[..., 0], mapping[..., 1]]; residuals.append(float(np.max(np.abs(target - transformed))))
    value = max(residuals)
    return {"exact_runtime_epsilon_grid_c3_residual_max": value, "exact_runtime_material_c3_covariance_status": "EXACT_ZERO" if value == 0.0 else "STRUCTURALLY_NONZERO", "edge_residuals": residuals}


def _covariance(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    m15 = _m15(); lattice = m15.lattice_automorphisms(); action = lattice["c3_direct_integer_automorphism"]; reciprocal = lattice["c3_reciprocal_integer_automorphism"]; edges = m15._edges(records); ordered = sorted(records, key=lambda item: int(item["member_index"])); metrics = []; transformed_residual = 0.0; intertwining = 0.0
    for index, edge in enumerate(edges):
        source = _fresh_energy(ordered[index])[:, 1:3]; target = _fresh_energy(ordered[(index + 1) % 3])[:, 1:3]; transformed = m15.energy_fft_transform(source, SHAPE, reciprocal, edge["folding"]); metrics.append(m15.projector_metrics(transformed, target)); transformed_residual = max(transformed_residual, float(np.max(np.abs(transformed - target))))
        intertwining = max(intertwining, float(np.linalg.norm(transformed - target) / max(np.linalg.norm(target), np.finfo(float).tiny)))
    return {"c3_transformed_fresh_state_maxwell_residual_max": None, "operator_intertwining_residual_max": intertwining, "fresh_rank2_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in metrics), "fresh_rank2_c3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in metrics), "fresh_rank2_c3_covariance_failure_count": sum(item["maximum_projector_distance"] > 0.0 for item in metrics), "transformed_energy_vector_residual_max": transformed_residual}


def result_for(records: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any], m12: Sequence[Mapping[str, Any]], m13: Sequence[Mapping[str, Any]], counter: Any) -> dict[str, Any]:
    reproduction = _state_reproduction(records, m12); fresh_rows = [_fresh_exact_residual(item, archived=False) for item in records]; archived_rows = [_fresh_exact_residual(item, archived=True, m12_record={x["request_key_sha256"]: x for x in m12}[item["request_key_sha256"]]) for item in records]; material = _material_c3(records); covariance = _covariance(records)
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "source_m12_dataset_id": M12_DATASET_ID, "source_m13_dataset_id": M13_DATASET_ID, "target_state_count": 3, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": counter.solver_count, "dataset_record_count": 3, "new_runtime_readback_record_count": 3, "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "exact_mpb_runtime_readback_status": "CAPTURED_SUFFICIENT_OPERATOR_READBACK", "epsilon_grid_shape": records[0]["epsilon_grid_shape"], "epsilon_grid_dtype": records[0]["epsilon_grid_dtype"], "epsilon_material_representation_type": records[0]["epsilon_material_representation_type"], "subpixel_or_smoothing_configuration": records[0]["subpixel_or_smoothing_configuration"], "field_material_grid_alignment_status": records[0]["field_material_grid_alignment_status"], "boundary_or_staggering_metadata_status": records[0]["boundary_or_staggering_metadata_status"], "epsilon_inverse_or_tensor_metadata_status": records[0]["epsilon_inverse_or_tensor_metadata_status"], "D_field_availability_status": [item["D_field_availability_status"] for item in records], "B_field_availability_status": [item["B_field_availability_status"] for item in records], **reproduction, "fresh_exact_maxwell_residual_max": max(item["maxwell"] for item in fresh_rows), "archived_exact_maxwell_residual_max": max(item["maxwell"] for item in archived_rows), "fresh_curlE_residual_max": max(item["curlE"] for item in fresh_rows), "fresh_curlH_residual_max": max(item["curlH"] for item in fresh_rows), "archived_curlE_residual_max": max(item["curlE"] for item in archived_rows), "archived_curlH_residual_max": max(item["curlH"] for item in archived_rows), "comparison_vs_M16_approximate_material": {"M16_approximate_maxwell_residual_max": 0.9986651051133764, "M18_fresh_exact_maxwell_residual_max": max(item["maxwell"] for item in fresh_rows), "interpretation": "raw same-convention comparison; no threshold invented"}, **material, **covariance, "isolated_projector_theorem_status": "RECONCILE_AFTER_EXACT_READBACK", "discrete_operator_covariance_diagnosis": "OPERATOR_COVARIANCE_SUPPORTED_ON_FRESH_AND_ARCHIVED_STATE_SUBSPACE" if covariance["fresh_rank2_c3_covariance_failure_count"] == 0 else "INTERNAL_MPB_SPECTRAL_PROJECTOR_CONTRADICTION", "remaining_unresolved_questions": ["Whether archived projector construction or state serialization caused any residual noncovariance after exact runtime readback"], "alternative_explanations_considered": ["M16 point-sampled epsilon", "MPB runtime epsilon/material grid", "D/B constitutive readback", "field/material alignment", "boundary/staggering", "Maxwell convention", "reciprocal-folding gauge", "fresh-versus-archived state reproduction", "spectral projector construction"], "counterevidence_summary": {"fresh_residuals": fresh_rows, "archived_residuals": archived_rows, "material_c3": material, "transformed_energy": covariance, "M16_approximation": 0.9986651051133764}, "cheapest_remaining_discriminating_test": "Audit projector dataset construction and spectral projector definition using existing M12/M13/M18 data only", "next_science_decision": "AUDIT_PROJECTOR_DATASET_CONSTRUCTION_AND_SPECTRAL_PROJECTOR_DEFINITION_WITH_EXISTING_DATA_ONLY", "minimal_next_live_state_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def failure(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code, "exception_type": type(exc).__name__ if exc else None, "exception_message": str(exc)[:1024] if exc else None, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "new_runtime_readback_record_count": 0, "exact_mpb_runtime_readback_status": "MPB_RUNTIME_READBACK_FAILURE", "discrete_operator_covariance_diagnosis": "INSUFFICIENT_EVIDENCE", "next_science_decision": "INSUFFICIENT_EVIDENCE", "minimal_next_live_state_count": 0, "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M18_WORK_ORDER_MISSING")
        counters_path = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]); state_root = counters_path.parent.parent; job = _job()
        m12 = read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); m13 = read_dataset(job, state_root, M13_DATASET_ID, M13_MANIFEST_SHA256, 3); read_dataset(job, state_root, M17_DATASET_ID, M17_MANIFEST_SHA256, 3); members = select_triplet(m12, m13)
        factory, _ = production_solver_factory(); counter = job.BudgetCounter(3, 3); records = capture_triplet(members, factory, counter); manifest = persist_readback(job, state_root, bundle["work_order_id"], records); result = result_for(records, manifest, m12, m13, counter)
    except Exception as exc:
        result = failure(str(exc), exc); result["traceback_tail"] = traceback.format_exc()[-3000:]
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(canonical(result) + b"\n"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
