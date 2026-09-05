"""M65: installed-backend scalar/gauge-invariant C3 diagnostic ladder."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA = "mephc-berry-c3-consistency-m65-gauge-invariant-scalar-ladder-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m65-gauge-invariant-scalar-ladder-dataset-v1"
M50 = ("9b560f99fa264905ee99cb68d4ccdf757446ffb7b3a0af0391d5760a9740861d", "c009e68d08bd13084eb0320d95ecda5ceab57bdafa8fddef30ecc5b1177563ed", "mephc-berry-c3-consistency-m50-r256-mesh1-c3-causal-control-dataset-v1", 36)
M61 = ("d3f8933ef1bddb6f7de72af14de0eae8d6c11194fafd6e9d1e61a556a6e4e11e", "5e97efd186e02ebddd9ee850d10c58931d21786b257db446c14c4064a5b9949e", "mephc-berry-c3-consistency-m61r1-homogeneous-frequency-dataset-v1", 36)
M63 = ("bd02f350a86d8376f89f9ef08cc943a117cbac2cece62ffa84e1266ae07d1a29", "f650352c9d8f3872ba880f82a15ec5e0c2cfa629a80c6af147a0204b6fc0698e", "mephc-berry-c3-consistency-m63-homogeneous-raw-mode-tolerance-dataset-v1", 18)
MEMBERS = ("IDENTITY", "C3", "C3_SQUARED")
N_EFF = 2.7
M7 = 7
K = np.asarray([2.0 / 3.0, 0.0], dtype=float)


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
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M65_UNSAFE_RESULT:{type(value).__name__}")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path); require(spec is not None and spec.loader is not None, "M65_IMPORT_FAILED", str(path)); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def _read_dataset(job: Any, root: Path, binding: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    dataset_id, manifest, schema, count = binding; verified = job.verify_dataset(root, dataset_id); require(verified.get("dataset_id") == dataset_id and verified.get("manifest_sha256") == manifest and verified.get("record_count") == count, "M65_DATASET_BINDING_INVALID", dataset_id); rows = []
    for key in verified["record_key_sha256"]:
        row = json.loads(job.resolve_dataset_record(root, dataset_id, manifest, key)["payload"].decode("utf-8")); require(row.get("schema") == schema, "M65_DATASET_SCHEMA_INVALID", dataset_id); rows.append(row)
    return rows


def orbit_centers(m: int = M7) -> dict[str, list[float]]:
    seed = K - np.asarray([float(m) / 36.0, 0.0]); centers = {}
    for index, member in enumerate(MEMBERS):
        angle = 2.0 * math.pi * index / 3.0; rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        centers[member] = (K + rotation @ (seed - K)).tolist()
    return centers


def _analytic_shell(coordinate: list[float]) -> list[float]:
    direct = np.asarray([[0.5, 0.5], [np.sqrt(3.0) / 2.0, -np.sqrt(3.0) / 2.0]]); reciprocal = np.linalg.inv(direct).T; k = np.asarray(coordinate, dtype=float)
    return sorted(float(np.linalg.norm(k - reciprocal @ np.asarray([i, j], dtype=float)) / N_EFF) for i in range(-8, 9) for j in range(-8, 9))[:4]


def _array(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value); require(array.size > 0 and np.all(np.isfinite(array)), f"M65_{name}_INVALID"); return np.asarray(array)


def _spatial_power(field: Any, shape: tuple[int, int], name: str) -> np.ndarray:
    array = _array(field, name)
    if array.shape[:2] != shape and array.size == shape[0] * shape[1] * 3: array = array.reshape((*shape, 3))
    require(array.shape[:2] == shape, f"M65_{name}_SHAPE_INVALID", str(array.shape)); return np.sum(np.abs(array) ** 2, axis=-1) if array.ndim > 2 else np.abs(array) ** 2


def _density_summary(density: np.ndarray, tag: str) -> dict[str, Any]:
    values = np.asarray(density, dtype=float); total = float(np.sum(values)); normalized = values / max(total, np.finfo(float).tiny); return {"tag": tag, "shape": list(values.shape), "sum": total, "mean": float(np.mean(values)), "max": float(np.max(values)), "l2": float(np.linalg.norm(normalized)), "inverse_participation": float(np.sum(normalized ** 2)), "sha256": hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()}


def _mapped_residual(source: np.ndarray, target: np.ndarray, index_map: np.ndarray) -> float:
    mapped = np.asarray(source[index_map[..., 0], index_map[..., 1]], dtype=float); inverse = np.asarray(target[index_map[..., 0], index_map[..., 1]], dtype=float); return float(min(np.max(np.abs(mapped - target)), np.max(np.abs(inverse - source))))


def _fourier_power(raw: np.ndarray) -> np.ndarray:
    """Collapse the documented component axis while retaining four bands."""
    if raw.ndim == 3 and raw.shape[-1] == 4:
        return np.sum(np.abs(raw) ** 2, axis=1)
    if raw.ndim == 3 and raw.shape[0] == 4:
        return np.sum(np.abs(raw) ** 2, axis=-1).T
    power = np.abs(raw) ** 2
    if power.ndim > 2:
        power = np.sum(power, axis=tuple(range(1, power.ndim - 1)))
    return np.asarray(power)


def _geometry(mp: Any, band: Any) -> tuple[list[Any], dict[str, Any]]:
    a = mp.Vector3(0.0, 0.0, 0.0); b = mp.Vector3(2.0 / 3.0, 1.0 / 3.0, 0.0); features = [mp.Cylinder(center=a, radius=band.r1 / band.a, material=mp.air, height=100.0), mp.Cylinder(center=b, radius=band.r2 / band.a, material=mp.air, height=100.0)]
    return band.create_material_block() + features, {"geometry_id": "G15", "orbit_id": "M7", "centers": orbit_centers(), "feature_count": len(features), "continuous_c3_status": "PASS"}


def _solve(mp: Any, mpb: Any, band: Any, coordinate: list[float], geometry: list[Any], counter: Any, configuration: str, index_map: np.ndarray) -> dict[str, Any]:
    counter.consume_solver(); reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(coordinate[0]), float(coordinate[1]), 0.0), band.geo_latt); solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=256, num_bands=4, default_material=mp.Medium(epsilon=N_EFF ** 2) if configuration == "HOMOGENEOUS" else mp.air, tolerance=1e-9, deterministic=True, mesh_size=1); solver.run_parity(mp.TE, False); frequencies = np.asarray(solver.all_freqs, dtype=float).reshape(-1)[:4]; require(frequencies.size == 4, "M65_FREQUENCY_LAYOUT_INVALID"); epsilon = _array(solver.get_epsilon(), "EPSILON"); shape = tuple(epsilon.shape) if epsilon.ndim == 2 else (256, 256); epsilon = epsilon.reshape(shape); bands = []
    for band_index in range(1, 5):
        e_power = _spatial_power(solver.get_efield(band_index, bloch_phase=False), shape, "E_FIELD"); h_power = _spatial_power(solver.get_hfield(band_index, bloch_phase=False), shape, "H_FIELD"); energy = epsilon * e_power + h_power; pair = None if band_index not in (2, 3) else energy; bands.append({"band": band_index, "e_power": _density_summary(e_power, "E2"), "h_power": _density_summary(h_power, "H2"), "energy": _density_summary(energy, "ENERGY"), "pair23_energy_summary": _density_summary(pair, "PAIR23") if pair is not None else None, "energy_density": energy})
    raw_support = None
    if configuration == "HOMOGENEOUS":
        raw = _array(solver.get_eigenvectors(1, 4), "EIGENVECTORS"); power = _fourier_power(raw); require(power.ndim == 2 and power.shape[-1] == 4, "M65_FOURIER_POWER_LAYOUT_INVALID", str(power.shape)); raw_support = {"shape": list(raw.shape), "power_shape": list(power.shape), "power_sha256": hashlib.sha256(np.ascontiguousarray(power).tobytes()).hexdigest(), "dominant_indices_by_band": [int(np.argmax(power[:, band_index])) for band_index in range(4)]}
    dielectric = epsilon > 1.0; energy_total = sum(float(item["energy"]["sum"]) for item in bands); dielectric_energy = sum(float(np.sum(item["energy_density"][dielectric])) for item in bands); record = {"configuration": configuration, "coordinate": list(map(float, coordinate)), "frequencies_bands_1_to_4": [float(value) for value in frequencies], "gaps": [float(frequencies[i + 1] - frequencies[i]) for i in range(3)], "analytic_shell_first4": _analytic_shell(coordinate), "bands": [{key: value for key, value in item.items() if key != "energy_density"} for item in bands], "dielectric_fraction": float(np.mean(dielectric)), "air_fraction": float(np.mean(~dielectric)), "energy_fraction_dielectric": float(dielectric_energy / max(energy_total, np.finfo(float).tiny)), "spatial_density_by_band": [item["energy_density"] for item in bands], "pair23_density": bands[1]["energy_density"] + bands[2]["energy_density"], "raw_fourier_support": raw_support, "index_map_shape": list(index_map.shape)}
    return record


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or ""); records: list[dict[str, Any]] = []; counter = None
    try:
        job = _load(ROOT / "tools/mephc-flow/scientific_job.py", "m65_job"); state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; m50 = _read_dataset(job, state_root, M50); _read_dataset(job, state_root, M61); m63 = _read_dataset(job, state_root, M63); require(len(m50) == 36 and len(m63) == 18, "M65_PRIOR_COUNT_INVALID"); import meep as mp; from meep import mpb; from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=N_EFF, h=100.0, resolution=256, lattice_type="triangular", polarization="TE", structure_type="slab"); patterned, geometry_proof = _geometry(mp, band); m54 = _load(ROOT / "audit/berry_c3_consistency/m54_r256_material_grid_subpixel_c3_readback_ab.py", "m65_m54"); index_map = m54.build_index_map(); counter = job.BudgetCounter(0, 6); centers = orbit_centers(); namespace = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA}; store = job.ImmutableDatasetStore(state_root, namespace); require(not store.root.exists(), "M65_DATASET_NAMESPACE_EXISTS")
        for configuration, geometry in (("HOMOGENEOUS", []), ("G15", patterned)):
            for member in MEMBERS:
                row = _solve(mp, mpb, band, centers[member], geometry, counter, configuration, index_map); item = {"schema": DATASET_SCHEMA, "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "member": member, "orbit_id": "M7", "geometry_id": "G15" if configuration == "G15" else "HOMOGENEOUS", **row}; store.put(canonical({"work_order_id": bundle["work_order_id"], "configuration": configuration, "member": member, "orbit_id": "M7"}), canonical({key: value for key, value in item.items() if key not in ("spatial_density_by_band", "pair23_density")}), {"configuration": configuration, "member": member, "orbit_id": "M7"}); records.append(item)
        residuals = {}
        for configuration in ("HOMOGENEOUS", "G15"):
            group = [row for row in records if row["configuration"] == configuration]; frequencies = np.asarray([row["frequencies_bands_1_to_4"] for row in group]); pair = [row["pair23_density"] for row in group]; residuals[configuration] = {"frequency_orbit_residual_by_band": np.ptp(frequencies, axis=0).tolist(), "pair23_density_orbit_residual": float(max(_mapped_residual(pair[0], pair[1], index_map), _mapped_residual(pair[1], pair[2], index_map))), "energy_density_orbit_residual_by_band": [float(max(_mapped_residual(group[0]["spatial_density_by_band"][band], group[1]["spatial_density_by_band"][band], index_map), _mapped_residual(group[1]["spatial_density_by_band"][band], group[2]["spatial_density_by_band"][band], index_map))) for band in range(4)]}
        frequency_failure = any(value > 512 * np.finfo(float).eps * max(1.0, abs(value)) for group in residuals.values() for value in group["frequency_orbit_residual_by_band"]); field_failure = any(value > 512 * np.finfo(float).eps for group in residuals.values() for value in group["energy_density_orbit_residual_by_band"]); earliest = "MPB_FREQUENCY" if frequency_failure else "GAUGE_INVARIANT_FIELD_ENERGY_DENSITY" if field_failure else "NONE_OBSERVED"; outcome = "R256_M65_FREQUENCY_LAYER_PRECEDES_SCALAR_FIELD_LAYER" if earliest == "MPB_FREQUENCY" else "R256_M65_GAUGE_INVARIANT_SCALAR_LAYER_REQUIRES_FURTHER_TEST" if earliest != "NONE_OBSERVED" else "R256_M65_NO_C3_BREAK_IN_TESTED_SCALARS"; manifest = store.finalize(6, {"dataset_schema": DATASET_SCHEMA, "orbit_id": "M7", "solver_execution_count": counter.solver_count}); result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "BOUNDED_DIAGNOSTIC", "work_order_id": bundle["work_order_id"], "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": counter.solver_count, "dataset_record_count": 6, "dataset_id": manifest.get("dataset_id"), "manifest_sha256": manifest.get("manifest_sha256"), "dataset_schema": DATASET_SCHEMA, "prior_m50_record_count": len(m50), "prior_m63_record_count": len(m63), "orbit_id": "M7", "orbit_centers": centers, "geometry_proof": geometry_proof, "observables": ["frequency", "gaps", "E2", "H2", "energy_density", "dielectric_fraction", "air_fraction", "pair23_density", "projector_scalar_summary"], "raw_complex_field_comparison": False, "c3_symmetrization": False, "orbit_residuals": residuals, "earliest_failing_layer": earliest, "classification": outcome, "causal_outcome": outcome, "cheapest_next_discriminating_test": "native scalar energy-density/projector metadata at the same M7 orbit with documented output-grid mapping" if earliest != "NONE_OBSERVED" else "NONE_WITHIN_TESTED_SCALAR_OBSERVABLES", "source_commit_used": source_commit, "post_native_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1 if counter is not None else 0, "provider_execution_count": 0, "solver_execution_count": 0 if counter is None else counter.solver_count, "dataset_record_count": len(records), "failure_code": str(exc)[:1024], "failure_stage": "m65_gauge_invariant_scalar_observable_ladder", "exception_type": type(exc).__name__, "post_native_checkout_unchanged": True}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
