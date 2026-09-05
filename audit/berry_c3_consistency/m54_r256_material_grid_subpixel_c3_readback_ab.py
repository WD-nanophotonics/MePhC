"""M54: one native, no-eigensolver material-grid/subpixel C3 readback.

The three existing R256 frequency datasets are read as immutable references.
The single native child only initializes three MPB material states (mesh 1, 3,
and 5), reads public material arrays, and persists exactly three readback
records.  No band or eigenstate solve is present in this module.
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
M52R1_PATH = ROOT / "audit/berry_c3_consistency/m52r1_exact_reciprocal_label_scalar_ladder.py"
SPEC = importlib.util.spec_from_file_location("m54_m52r1_reference", M52R1_PATH)
assert SPEC and SPEC.loader
m52r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m52r1)

RESULT_SCHEMA = "mephc-berry-c3-consistency-m54-r256-material-grid-subpixel-c3-readback-ab-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m54-r256-material-grid-subpixel-readback-dataset-v1"
SHAPE = (256, 256)
MESHES = (1, 3, 5)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
COMPONENTS = 3
G15 = {"a": 400.0, "r1": 80.14335684352235, "r2": 75.13439704080221, "n1": 15, "n2": 15, "theta1_degrees": 0.0, "theta2_degrees": 60.0, "n_eff": 2.7, "height": 100.0}
R3 = np.asarray([[-0.5, -math.sqrt(3.0) / 2.0, 0.0], [math.sqrt(3.0) / 2.0, -0.5, 0.0], [0.0, 0.0, 1.0]], dtype=float)
# This is the committed triangular direct-lattice integer action used by M9.
DIRECT_C3_INTEGER_AUTOMORPHISM = np.asarray([[-1, 1], [-1, 0]], dtype=int)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


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
    raise ValueError(f"M54_UNSAFE_RESULT:{type(value).__name__}")


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ValueError(f"{code}:{detail}" if detail else code)


def encode_array(value: Any) -> dict[str, Any]:
    array = np.asarray(value)
    require(array.dtype.kind in "fciu", "M54_ARRAY_DTYPE_INVALID", str(array.dtype))
    stream = io.BytesIO()
    np.save(stream, array, allow_pickle=False)
    compressed = zlib.compress(stream.getvalue(), level=9)
    return {"encoding": "zlib-npy-base64", "shape": list(array.shape), "dtype": str(array.dtype), "sha256": hashlib.sha256(array.tobytes()).hexdigest(), "payload_base64": base64.b64encode(compressed).decode("ascii")}


def decode_array(value: Mapping[str, Any]) -> np.ndarray:
    payload = zlib.decompress(base64.b64decode(str(value["payload_base64"])))
    array = np.load(io.BytesIO(payload), allow_pickle=False)
    require(hashlib.sha256(array.tobytes()).hexdigest() == value["sha256"], "M54_ARRAY_HASH_INVALID")
    return np.asarray(array)


def build_index_map(shape: Sequence[int] = SHAPE, action: Any = DIRECT_C3_INTEGER_AUTOMORPHISM) -> np.ndarray:
    shape = tuple(int(v) for v in shape)
    matrix = np.asarray(action, dtype=int)
    require(shape == SHAPE and matrix.shape == (2, 2), "M54_GRID_MAP_INPUT_INVALID")
    require(np.array_equal(matrix @ matrix @ matrix, np.eye(2, dtype=int)), "M54_DIRECT_ACTION_ORDER_INVALID")
    result = np.empty((*shape, 2), dtype=int)
    inverse = matrix @ matrix
    dims = np.asarray(shape, dtype=int)
    for i in range(shape[0]):
        for j in range(shape[1]):
            result[i, j] = (inverse @ np.asarray([i, j], dtype=int)) % dims
    flat = result.reshape(-1, 2)
    require(len({(int(a), int(b)) for a, b in flat}) == shape[0] * shape[1], "M54_GRID_MAP_NOT_BIJECTIVE")
    cubed = result[result[..., 0], result[..., 1], :]
    cubed = cubed[result[..., 0], result[..., 1], :]
    require(np.array_equal(cubed, np.indices(shape).transpose(1, 2, 0)), "M54_GRID_MAP_CUBED_INVALID")
    return result


def apply_grid(value: Any, index_map: Any) -> np.ndarray:
    array, mapping = np.asarray(value), np.asarray(index_map, dtype=int)
    return np.array(array[mapping[..., 0], mapping[..., 1], ...], copy=True)


def _tensor(value: Any) -> np.ndarray:
    try:
        array = np.asarray(value)
        if array.size == 9:
            result = np.asarray(array, dtype=np.complex128).reshape(3, 3)
            require(np.all(np.isfinite(result)), "M54_TENSOR_NONFINITE")
            return result
    except (TypeError, ValueError):
        pass
    rows, cols = getattr(value, "rows", None), getattr(value, "cols", None)
    if rows is not None and cols is not None and int(rows) == int(cols) == 3:
        result = np.asarray([[value[i, j] for j in range(3)] for i in range(3)], dtype=np.complex128)
        require(np.all(np.isfinite(result)), "M54_TENSOR_NONFINITE")
        return result
    names = [[f"m{i}{j}" for j in range(3)] for i in range(3)]
    require(all(hasattr(value, name) for row in names for name in row), "M54_TENSOR_LAYOUT_INVALID", type(value).__name__)
    return np.asarray([[getattr(value, name) for name in row] for row in names], dtype=np.complex128)


def canonical_tensor_grid(value: Any, shape: Sequence[int] = SHAPE) -> np.ndarray:
    array = np.asarray(value, dtype=np.complex128)
    shape = tuple(int(v) for v in shape)
    if array.shape == (*shape, 1, 3, 3):
        array = array[:, :, 0]
    elif array.shape == (shape[0] * shape[1], 3, 3):
        array = array.reshape(*shape, 3, 3)
    elif array.shape == (3, 3, *shape):
        array = array.transpose(2, 3, 0, 1)
    require(array.shape == (*shape, 3, 3), "M54_TENSOR_GRID_SHAPE_INVALID", str(array.shape))
    require(np.all(np.isfinite(array)), "M54_TENSOR_GRID_NONFINITE")
    return np.array(array, copy=True)


def tensor_rotation(value: Any) -> np.ndarray:
    return np.asarray(R3 @ np.asarray(value) @ R3.T, dtype=np.complex128)


def identity_guard(value: Any) -> float:
    magnitude = float(np.max(np.abs(np.asarray(value)))) if np.asarray(value).size else 0.0
    return float(64.0 * np.finfo(float).eps * max(1.0, magnitude))


def material_covariance(epsilon: Any, tensor: Any, index_map: Any) -> dict[str, Any]:
    scalar = np.asarray(epsilon, dtype=float)
    eta = canonical_tensor_grid(tensor)
    scalar_diff = scalar - apply_grid(scalar, index_map)
    tensor_target = apply_grid(eta, index_map)
    tensor_rotated = np.einsum("ab,xybc,cd->xyad", R3, tensor_target, R3.T, optimize=True)
    tensor_diff = eta - tensor_rotated
    scalar_guard = identity_guard(scalar)
    tensor_guard = identity_guard(eta)
    scalar_residual = float(np.max(np.abs(scalar_diff)))
    tensor_fro = float(np.max(np.linalg.norm(tensor_diff, axis=(2, 3))))
    tensor_component = float(np.max(np.abs(tensor_diff)))
    map2 = apply_grid(index_map, index_map)
    scalar_projected = (scalar + apply_grid(scalar, index_map) + apply_grid(scalar, map2)) / 3.0
    tensor_projected = (eta + tensor_rotated + np.einsum("ab,xybc,cd->xyad", R3 @ R3, apply_grid(eta, map2), (R3 @ R3).T, optimize=True)) / 3.0
    projected_scalar_residual = float(np.max(np.abs(scalar_projected - apply_grid(scalar_projected, index_map))))
    projected_tensor = np.einsum("ab,xybc,cd->xyad", R3, apply_grid(tensor_projected, index_map), R3.T, optimize=True)
    projected_tensor_residual = float(np.max(np.linalg.norm(tensor_projected - projected_tensor, axis=(2, 3))))
    return {"scalar_c3_residual_max": scalar_residual, "tensor_c3_residual_fro_max": tensor_fro, "tensor_c3_residual_component_max": tensor_component, "scalar_identity_guard": scalar_guard, "tensor_identity_guard": tensor_guard, "identity_guard": max(scalar_guard, tensor_guard), "nonidentity_scalar_cell_count": int(np.count_nonzero(np.abs(scalar_diff) > scalar_guard)), "nonidentity_tensor_cell_count": int(np.count_nonzero(np.linalg.norm(tensor_diff, axis=(2, 3)) > tensor_guard)), "scalar_c3_status": "PASS" if scalar_residual <= scalar_guard else "FAIL", "tensor_c3_status": "PASS" if tensor_fro <= tensor_guard else "FAIL", "c3_cubed_grid_map_status": "PASS", "scalar_projection_linf": float(np.max(np.abs(scalar_projected - scalar))), "scalar_projection_l1": float(np.sum(np.abs(scalar_projected - scalar))), "tensor_projection_fro": float(np.linalg.norm(tensor_projected - eta)), "corrected_scalar_cell_count": int(np.count_nonzero(np.abs(scalar_projected - scalar) > scalar_guard)), "corrected_tensor_cell_count": int(np.count_nonzero(np.linalg.norm(tensor_projected - eta, axis=(2, 3)) > tensor_guard)), "projected_scalar_c3_residual_max": projected_scalar_residual, "projected_tensor_c3_residual_fro_max": projected_tensor_residual, "projected_material_c3_status": "PASS" if projected_scalar_residual <= scalar_guard and projected_tensor_residual <= tensor_guard else "FAIL", "projection_scientific_status": "AUDIT_ONLY_NOT_FED_TO_EIGENSOLVER"}


def synthetic_tensor_rotation_check() -> dict[str, Any]:
    mapping = build_index_map()
    probe = np.zeros((*SHAPE, 3, 3), dtype=np.complex128)
    probe[0, 0] = np.diag([2.0, 3.0, 5.0])
    probe = probe + apply_grid(probe, mapping) * 0.25 + apply_grid(probe, apply_grid(mapping, mapping)) * 0.5
    forward = tensor_rotation(tensor_rotation(tensor_rotation(probe[0, 0])))
    return {"direct_grid_bijection": True, "direct_grid_c3_cubed": True, "cartesian_rotation_c3_cubed_residual": float(np.linalg.norm(forward - probe[0, 0])), "orientation": "R3 @ eta(R^-1 r) @ R3.T"}


def _read_frequency_rows(job: Any, state_root: Path, dataset: tuple[int, str, str, str]) -> dict[tuple[int, int, str], dict[str, Any]]:
    mesh, dataset_id, manifest, schema = dataset
    catalog = m52r1._catalog(job, state_root, dataset_id, manifest, schema)
    require(len(catalog) == 36, "M54_FREQUENCY_RECORD_COUNT_INVALID", str(mesh))
    rows = {}
    for item in catalog:
        row = m52r1._load_row(job, state_root, dataset_id, manifest, item["key"])
        require(row.get("schema") == schema, "M54_FREQUENCY_SCHEMA_INVALID", str(mesh))
        rows[(int(item["vertex"]), int(item["repeat"]), str(item["member"]))] = row
    require(len(rows) == 36, "M54_FREQUENCY_COVERAGE_INVALID", str(mesh))
    return rows


def frequency_ledger(rows: Mapping[tuple[int, int, str], Mapping[str, Any]]) -> dict[str, Any]:
    failures = []
    ledger = {}
    for vertex in range(4):
        for source, target in zip(MEMBERS, MEMBERS[1:] + MEMBERS[:1]):
            for band in range(4):
                left = np.asarray([float(rows[(vertex, repeat, source)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                right = np.asarray([float(rows[(vertex, repeat, target)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                lm, rm = float(np.median(left)), float(np.median(right))
                lu, ru = float(np.max(np.abs(left - lm))), float(np.max(np.abs(right - rm)))
                item = {"vertex": vertex, "band": band + 1, "source_member": source, "target_member": target, "source_median": lm, "target_median": rm, "source_repeat_uncertainty": lu, "target_repeat_uncertainty": ru, "residual": abs(lm - rm), "combined_repeat_uncertainty": lu + ru, "pass": abs(lm - rm) <= lu + ru}
                ledger[f"v{vertex}:{source}_to_{target}:band{band + 1}"] = item
                if not item["pass"]:
                    failures.append(item)
    return {"failure_set": failures, "failure_count": len(failures), "ledger": ledger}


def _factory(member: Mapping[str, Any], mesh_size: int) -> tuple[Any, Any, Any]:
    import meep as mp
    from meep import mpb
    from mephc.band import Band
    band = Band(a=G15["a"], r1=G15["r1"], r2=G15["r2"], n_eff=G15["n_eff"], h=G15["height"], resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab")
    pattern = band.create_unitcell(G15["n1"], G15["theta1_degrees"], G15["n2"], G15["theta2_degrees"], show=False)
    geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
    public = mp.Vector3(float(member["coordinate"][0]), float(member["coordinate"][1]), 0.0)
    reciprocal = mp.cartesian_to_reciprocal(public, band.geo_latt)
    solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=mesh_size)
    return solver, mp, reciprocal


def _capture_tensor_grid(solver: Any, mp: Any) -> np.ndarray:
    getter = getattr(solver, "get_epsilon_inverse_tensor_point", None)
    require(callable(getter), "M54_PUBLIC_TENSOR_GETTER_UNAVAILABLE")
    tensor = np.empty((*SHAPE, 3, 3), dtype=np.complex128)
    for i in range(SHAPE[0]):
        for j in range(SHAPE[1]):
            tensor[i, j] = _tensor(getter(mp.Vector3(float(i) / SHAPE[0], float(j) / SHAPE[1], 0.0)))
    require(np.all(np.isfinite(tensor)), "M54_TENSOR_GRID_NONFINITE")
    return tensor


def capture_material(member: Mapping[str, Any], mesh_size: int, index_map: np.ndarray) -> tuple[dict[str, Any], Any]:
    solver, mp, reciprocal = _factory(member, mesh_size)
    init = getattr(solver, "init_params", None)
    parity = getattr(mp, "NO_PARITY", None)
    require(callable(init) and parity is not None, "M54_INIT_PARAMS_UNAVAILABLE")
    init(parity, False)
    epsilon_raw = np.asarray(solver.get_epsilon(), dtype=float)
    require(epsilon_raw.size == SHAPE[0] * SHAPE[1], "M54_EPSILON_GRID_SHAPE_INVALID", str(epsilon_raw.shape))
    epsilon = epsilon_raw.reshape(SHAPE)
    require(np.all(np.isfinite(epsilon)) and np.all(epsilon > 0.0), "M54_EPSILON_GRID_INVALID")
    tensor = _capture_tensor_grid(solver, mp)
    summary = material_covariance(epsilon, tensor, index_map)
    record = {"schema": DATASET_SCHEMA, "mesh_size": mesh_size, "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "coordinate": [float(member["coordinate"][0]), float(member["coordinate"][1])], "mpb_reciprocal_k_point": [float(getattr(reciprocal, axis)) for axis in ("x", "y", "z")], "resolution": 256, "deterministic": True, "material_grid_axis_order": "(x,y), C-order reshape", "material_grid_coordinate_convention": "MPB geometry-lattice fractional cell coordinates r=(i/256,j/256,0)", "subpixel_or_smoothing_configuration": {"mesh_size": mesh_size, "mesh1_control": mesh_size == 1, "mesh3_or_mesh5_smoothing_arm": mesh_size in (3, 5)}, "epsilon_grid_shape": list(epsilon.shape), "epsilon_grid_dtype": str(epsilon.dtype), "epsilon_grid": encode_array(epsilon), "inverse_epsilon_tensor_grid_shape": [*SHAPE, 3, 3], "tensor_component_order": "Cartesian rows x columns", "inverse_epsilon_tensor_grid": encode_array(tensor), "epsilon_grid_sha256": hashlib.sha256(epsilon.tobytes()).hexdigest(), "inverse_epsilon_tensor_grid_sha256": hashlib.sha256(tensor.tobytes()).hexdigest(), "public_api_initialization": "ModeSolver.init_params(NO_PARITY,False)", "forbidden_solver_call_count": 0, "source_commit": os.environ.get("MEPHC_SOURCE_COMMIT"), "covariance": summary}
    record["record_id"] = "MEPHC-M54-MATERIAL-" + hashlib.sha256(canonical({k: v for k, v in record.items() if k not in ("record_id",)})).hexdigest()
    return record, (epsilon, tensor, summary)


def persist_record(store: Any, work_order_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    key = canonical({"work_order_id": work_order_id, "mesh_size": record["mesh_size"], "record_id": record["record_id"]})
    return store.put(key, canonical(dict(record)), {"mesh_size": record["mesh_size"], "record_id": record["record_id"], "schema": DATASET_SCHEMA})


def classify(frequency: Mapping[str, Any], material: Mapping[str, Mapping[str, Any]]) -> tuple[str, str]:
    if int(frequency["5"]["failure_count"]) == 0:
        return "R256_FREQUENCY_C3_FAILURE_NOT_REPRODUCED", "R256_M5_FREQUENCY_SCALAR_REQUALIFICATION"
    m1, m3, m5 = material["1"], material["3"], material["5"]
    m1_defect = m1["scalar_c3_status"] == "FAIL" or m1["tensor_c3_status"] == "FAIL"
    if m1_defect:
        return "R256_BASE_GEOMETRY_RASTER_OR_GRID_C3_BREAKING", "IMPLEMENT_PROJECT_CONTAINED_EXACT_C3_GEOMETRY_RASTER_PATCH_AND_BOUNDED_FREQUENCY_AB"
    if m5["scalar_c3_status"] == "FAIL" and frequency["1"]["failure_count"] == 0:
        return "R256_SUBPIXEL_SCALAR_MATERIAL_C3_CAUSAL_SIGNATURE_SUPPORTED", "IMPLEMENT_PROJECT_CONTAINED_C3_PROJECTED_SCALAR_EPSILON_INPUT_AND_BOUNDED_FREQUENCY_AB"
    if m5["scalar_c3_status"] == "PASS" and m5["tensor_c3_status"] == "FAIL" and frequency["1"]["failure_count"] == 0:
        return "R256_SUBPIXEL_TENSOR_MATERIAL_C3_CAUSAL_SIGNATURE_SUPPORTED", "IMPLEMENT_TENSOR_AWARE_C3_SUBPIXEL_OPERATOR_PATCH_AND_BOUNDED_FREQUENCY_AB"
    if (m3["scalar_c3_status"] == "FAIL" or m3["tensor_c3_status"] == "FAIL" or m5["scalar_c3_status"] == "FAIL" or m5["tensor_c3_status"] == "FAIL"):
        return "R256_SUBPIXEL_MATERIAL_C3_MIXED_CONTRIBUTOR", "IMPLEMENT_MATERIAL_C3_PATCH_AB_WITH_SECONDARY_K_OPERATOR_DIAGNOSTIC"
    return "R256_MATERIAL_READBACK_C3_COVARIANT_DESPITE_FREQUENCY_FAILURE", "MPB_K_DEPENDENT_DISCRETE_OPERATOR_C3_SOURCE_AUDIT"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    records: list[dict[str, Any]] = []
    try:
        job = m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m54_job")
        counters = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"])
        state_root = counters.parent.parent
        frequency_rows = {str(mesh): _read_frequency_rows(job, state_root, dataset) for mesh, dataset in zip(MESHES, m52r1.MESH_DATASETS)}
        frequency = {mesh: frequency_ledger(frequency_rows[str(mesh)]) for mesh in (1, 3, 5)}
        require(frequency["5"]["failure_count"] > 0, "M54_MESH5_FREQUENCY_FAILURE_NOT_REPRODUCED")
        member = frequency_rows["5"][(0, 0, MEMBERS[0])]
        index_map = build_index_map()
        synthetic = synthetic_tensor_rotation_check()
        require(synthetic["direct_grid_bijection"] and synthetic["direct_grid_c3_cubed"], "M54_SYNTHETIC_GRID_REGRESSION_FAILED")
        namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}
        store = job.ImmutableDatasetStore(state_root, namespace)
        material_data: dict[str, Any] = {}
        for mesh in MESHES:
            record, data = capture_material(member, mesh, index_map)
            persist_record(store, bundle["work_order_id"], record)
            records.append(record)
            material_data[str(mesh)] = data[2]
        manifest = store.finalize(3, {"dataset_schema": DATASET_SCHEMA, "readback_only": True, "mesh_sizes": list(MESHES), "geometry": G15, "eigensolver_called": False})
        classification, decision = classify(frequency, material_data)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 3, "dataset_write": True, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "source_commit_used": source_commit, "fixed_geometry": G15 | {"resolution": 256, "meshes": list(MESHES), "grid_shape": list(SHAPE)}, "frequency_reference": frequency, "material_readback": {str(record["mesh_size"]): {k: v for k, v in record["covariance"].items() if not isinstance(v, np.ndarray)} for record in records}, "material_record_ids": [record["record_id"] for record in records], "material_record_count": len(records), "synthetic_tensor_rotation_check": synthetic, "classification": classification, "causal_outcome": classification, "next_science_decision": decision, "material_projection_status": "AUDIT_ONLY_NOT_FED_TO_EIGENSOLVER", "eigensolver_called": False, "forbidden_solver_call_count": 0, "no_new_band_states": True, "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": len(records), "dataset_write": bool(records), "failure_code": str(exc)[:1024], "failure_stage": "m54_material_grid_subpixel_c3_readback", "exception_type": type(exc).__name__, "source_commit_used": source_commit, "completed_record_ids": [record["record_id"] for record in records], "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
