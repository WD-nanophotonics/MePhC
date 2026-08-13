"""Execute the R7.3 authoritative contract literally for SqrLatt only."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
MEPHC_ROOT = ROOT.parents[2]
SQR_ROOT = MEPHC_ROOT.parent / "SqrLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
LOCKED_SHA = "c2f9d2c8f1b0742cb032abf8b9bd94172ba49d8bcf1a814342b0b181d684a37a"

sys.path.insert(0, str(MEPHC_ROOT))
sys.path.insert(0, str(SQR_ROOT))

from mephc.deformation import AnalyticDeformationField, periodic_supercell_field
from mephc.response import SupercellQPoint


def jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def write(name, value):
    (ROOT / name).write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract_points():
    return tuple(SupercellQPoint(name, tuple(values)) for name, values in CONTRACT["benchmark"]["q_points"].items())


def make_structure_and_adapter():
    config = load_module(SQR_ROOT / "square_hole" / "config.py", "r73_sq_config")
    adapter = load_module(SQR_ROOT / "square_hole" / "r5_deformation.py", "r73_sq_r5")
    return config.canonical_structure(), adapter


def contract_field(lattice, amplitude):
    benchmark = CONTRACT["benchmark"]
    replication = tuple(int(v) for v in benchmark["replication"])
    super_direct = lattice.direct_basis @ np.diag(replication)
    inverse = np.linalg.inv(super_direct)
    amplitude = float(amplitude)

    def displacement(points):
        values = np.asarray(points, dtype=float)
        xi = values @ inverse.T
        shape = np.cos(2.0 * np.pi * xi[:, 0]) * np.cos(2.0 * np.pi * xi[:, 1])
        return np.column_stack((amplitude * shape, np.zeros(len(values))))

    base = AnalyticDeformationField(
        displacement,
        stable_id=f"r7.3-contract-A{amplitude:g}",
        parameters={"amplitude": amplitude, "field": benchmark["field"], "replication": list(replication)},
    )
    return periodic_supercell_field(base, lattice, replication_matrix=replication, tolerance=1e-9, boundary_samples=9)


def geometry_digest(pattern):
    payload = []
    for poly in pattern:
        values = canonical_polygon(np.asarray(poly, dtype=float))
        payload.append({"material": "air", "vertices": np.round(values, 14).tolist()})
    payload.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def canonical_polygon(poly):
    values = np.asarray(poly, dtype=float)
    options = []
    for seq in (values, values[::-1]):
        for index in range(len(seq)):
            options.append(np.roll(seq, -index, axis=0))
    return min(options, key=lambda item: tuple(np.round(item.flatten(), 14)))


def polygon_error(left, right):
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    if a.shape != b.shape:
        return float("inf")
    options = [np.roll(b, -i, axis=0) for i in range(len(b))] + [np.roll(b[::-1], -i, axis=0) for i in range(len(b))]
    return min(float(np.max(np.linalg.norm(option - a, axis=1))) for option in options)


def match_typed(left, right, tolerance):
    from itertools import permutations
    if len(left) != len(right):
        return {"equivalent": False, "reason": "polygon_count", "maximum_coordinate_residual": float("inf"), "assignment": []}
    costs = [[polygon_error(a["vertices"], b["vertices"]) if a["material"] == b["material"] else float("inf") for b in right] for a in left]
    candidates = []
    for assignment in permutations(range(len(right))):
        values = [costs[i][assignment[i]] for i in range(len(left))]
        candidates.append((max(values), sum(values), assignment))
    maximum, total, assignment = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    equivalent = bool(maximum <= tolerance)
    material_mismatch = not np.isfinite(maximum)
    return {"equivalent": equivalent, "reason": "EQUIVALENT" if equivalent else ("type_material_mismatch" if material_mismatch else "coordinate_residual"), "maximum_coordinate_residual": None if material_mismatch else float(maximum), "total_coordinate_residual": None if material_mismatch else float(total), "assignment": list(assignment), "tolerance": tolerance}


def normalize_polygon(poly, basis):
    values = np.asarray(poly, dtype=float)
    center = np.mean(values, axis=0)
    fractional = center @ np.linalg.inv(basis).T
    nearest_integer = np.rint(fractional)
    fractional = np.where(np.abs(fractional - nearest_integer) <= 1e-12, nearest_integer, fractional)
    wrapped = np.floor(fractional)
    return values - wrapped @ basis.T


def transform_typed(pattern, matrix, translation, super_basis):
    transformed = []
    for poly in pattern:
        values = np.asarray(poly, dtype=float) @ np.asarray(matrix, dtype=float).T + translation
        transformed.append({"material": "air", "vertices": normalize_polygon(values, super_basis)})
    return transformed


def geometry_sign(structure, adapter):
    amplitudes = CONTRACT["benchmark"]["amplitudes"]
    plus = adapter.finite_patch_preview(structure, contract_field(structure.lattice, amplitudes[1]), replication=tuple(CONTRACT["benchmark"]["replication"]))
    minus = adapter.finite_patch_preview(structure, contract_field(structure.lattice, amplitudes[2]), replication=tuple(CONTRACT["benchmark"]["replication"]))
    target = [{"material": "air", "vertices": normalize_polygon(poly, structure.lattice.direct_basis @ np.diag(CONTRACT["benchmark"]["replication"]))} for poly in minus]
    basis = structure.lattice.direct_basis
    super_basis = basis @ np.diag(CONTRACT["benchmark"]["replication"])
    operations = [
        ("identity", [[1, 0], [0, 1]]),
        ("C4_R90", [[0, -1], [1, 0]]),
        ("C2_R180", [[-1, 0], [0, -1]]),
        ("C4_R270", [[0, 1], [-1, 0]]),
    ]
    translations = CONTRACT["geometry_equivalence"]["translations_mod_2x2"]
    candidates = []
    for operation_name, matrix in operations:
        for translation_index, fractional in enumerate(translations):
            cartesian = np.asarray(fractional, dtype=float) @ basis.T
            transformed = transform_typed(plus, matrix, cartesian, super_basis)
            match = match_typed(transformed, target, CONTRACT["geometry_equivalence"]["tolerance"])
            candidates.append({"operation": operation_name, "matrix": matrix, "translation_fractional": fractional, "translation_cartesian": cartesian.tolist(), "match": match, "transformed_fingerprint": geometry_digest([item["vertices"] for item in transformed]), "target_fingerprint": geometry_digest([item["vertices"] for item in target])})
    matches = [item for item in candidates if item["match"]["equivalent"]]
    result = {"status": "EQUIVALENT_BY_VERIFIED_OPERATION" if matches else "NOT_EQUIVALENT_UNDER_ENUMERATED_VERIFIED_OPERATIONS", "operation_source": CONTRACT["geometry_equivalence"]["point_operations_source"], "candidate_count": len(candidates), "candidates": candidates, "matching_candidates": matches, "tolerance": CONTRACT["geometry_equivalence"]["tolerance"], "typed_polygon_material": "air", "full_structure": True}
    write("candidate_operations.json", result)
    write("geometry_sign_equivalence.json", result)
    return result


def negative_geometry_fixtures(structure, adapter):
    amplitude = CONTRACT["benchmark"]["amplitudes"][1]
    field = contract_field(structure.lattice, amplitude)
    pattern = adapter.finite_patch_preview(structure, field, replication=tuple(CONTRACT["benchmark"]["replication"]))
    basis = structure.lattice.direct_basis @ np.diag(CONTRACT["benchmark"]["replication"])
    target = [{"material": "air", "vertices": normalize_polygon(poly, basis)} for poly in pattern]
    perturbed_center = [dict(item, vertices=np.asarray(item["vertices"]) + (np.array([1e-3, 0.0]) if i == 0 else 0.0)) for i, item in enumerate(target)]
    resized = [dict(item, vertices=np.asarray(item["vertices"]) * (1.001 if i == 0 else 1.0)) for i, item in enumerate(target)]
    material_changed = [dict(item, material=("dielectric" if i == 0 else item["material"])) for i, item in enumerate(target)]
    cases = {"one_center_plus_1e-3": perturbed_center, "polygon_size_change": resized, "type_material_identity_change": material_changed}
    results = {}
    for name, mutated in cases.items():
        results[name] = match_typed(target, mutated, CONTRACT["geometry_equivalence"]["tolerance"])
        results[name]["expected_rejection"] = True
    write("geometry_negative_fixtures.json", results)
    return results


def run_solver(structure, adapter, amplitude, resolution, points, calls, purpose):
    field = contract_field(structure.lattice, amplitude)
    solver, context = adapter.build_supercell_solver(structure, field, q_points=points, resolution=resolution, num_bands=CONTRACT["benchmark"]["num_bands"])
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (len(points), CONTRACT["benchmark"]["num_bands"]) or not np.all(np.isfinite(values)):
        raise RuntimeError(f"unexpected solver shape at r={resolution}, A={amplitude}: {values.shape}")
    calls.append({"downstream": CONTRACT["benchmark"]["downstream"], "resolution": resolution, "amplitude": amplitude, "q_points": [point.point_id for point in points], "num_bands": CONTRACT["benchmark"]["num_bands"], "polarization": CONTRACT["benchmark"]["polarization"], "solver": CONTRACT["runtime"]["solver"], "purpose": purpose})
    return values


def differential(raw, resolution):
    rows = []
    targets = CONTRACT["locked_targets"]
    for point_id, band in targets:
        index = {point.point_id: i for i, point in enumerate(contract_points())}[point_id]
        w0 = float(raw[resolution]["0.0"][index][band])
        plus = float(raw[resolution]["0.005"][index][band])
        minus = float(raw[resolution]["-0.005"][index][band])
        half_plus = float(raw[resolution]["0.0025"][index][band])
        half_minus = float(raw[resolution]["-0.0025"][index][band])
        rows.append({"target": [point_id, band], "resolution": resolution, "raw_frequency_inputs": {"zero": w0, "plus_A": plus, "minus_A": minus, "plus_half": half_plus, "minus_half": half_minus}, "even_A": (plus + minus) / 2.0 - w0, "even_half": (half_plus + half_minus) / 2.0 - w0, "odd_A": (plus - minus) / 2.0, "odd_half": (half_plus - half_minus) / 2.0})
    return rows


def convergence(rows_by_resolution, low, high):
    absolute = float(CONTRACT["differential_convergence"]["absolute"])
    relative = float(CONTRACT["differential_convergence"]["relative_fraction"])
    result = []
    for low_row, high_row in zip(rows_by_resolution[low], rows_by_resolution[high]):
        err_a = abs(high_row["even_A"] - low_row["even_A"])
        err_half = abs(high_row["even_half"] - low_row["even_half"])
        tol_a = max(absolute, relative * abs(high_row["even_A"]))
        tol_half = max(absolute, relative * abs(high_row["even_half"]))
        result.append({"target": high_row["target"], "low": low, "high": high, "err_A": err_a, "err_half": err_half, "tol_A": tol_a, "tol_half": tol_half, "full_pass": err_a <= tol_a, "half_pass": err_half <= tol_half, "status": "DIFFERENTIAL_CONVERGED" if err_a <= tol_a and err_half <= tol_half else "NOT_DIFFERENTIAL_CONVERGED"})
    return result


def main():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != LOCKED_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract digest mismatch")
    structure, adapter = make_structure_and_adapter()
    points = contract_points()
    geometry = geometry_sign(structure, adapter)
    negatives = negative_geometry_fixtures(structure, adapter)
    resolutions = list(CONTRACT["mandatory_fresh_sqrlatt_resolutions"])
    amplitudes = [float(v) for v in CONTRACT["benchmark"]["amplitudes"]]
    raw = {}
    calls = []
    replay = {}
    for resolution in resolutions:
        raw[resolution] = {}
        for amplitude in amplitudes:
            raw[resolution][str(amplitude)] = run_solver(structure, adapter, amplitude, resolution, points, calls, "contracted_spectrum")
        replay_a = [run_solver(structure, adapter, amplitudes[1], resolution, points, calls, f"exact_plus_A_replay_{i}") for i in (1, 2)]
        replay[resolution] = {"replayed_amplitude": amplitudes[1], "q_points_used": CONTRACT["replay_tolerance"]["q_points_used"], "additional_replays": 2, "max_difference": float(max(np.max(np.abs(replay_a[0][i] - replay_a[1][i])) for i, point in enumerate(points) if point.point_id in CONTRACT["replay_tolerance"]["q_points_used"])), "replay_1": replay_a[0], "replay_2": replay_a[1]}
        replay[resolution]["replay_tolerance"] = max(1e-10, 10.0 * replay[resolution]["max_difference"])
        sign_differences = [float(np.max(np.abs(raw[resolution][str(amplitudes[1])][i] - raw[resolution][str(amplitudes[2])][i]))) for i in range(len(points))]
        replay[resolution]["plus_minus_max_difference_by_q"] = {points[i].point_id: sign_differences[i] for i in range(len(points))}
        replay[resolution]["spectral_equivalence"] = all(value <= replay[resolution]["replay_tolerance"] for value in sign_differences)
    rows = {resolution: differential(raw, resolution) for resolution in resolutions}
    final_pair = (16, 20)
    initial_convergence = convergence(rows, 16, 20)
    convergence_final = initial_convergence
    if not all(item["status"] == "DIFFERENTIAL_CONVERGED" for item in convergence_final):
        resolutions.append(24)
        raw[24] = {}
        for amplitude in amplitudes:
            raw[24][str(amplitude)] = run_solver(structure, adapter, amplitude, 24, points, calls, "contracted_spectrum_optional_24")
        replay_a = [run_solver(structure, adapter, amplitudes[1], 24, points, calls, f"exact_plus_A_replay_24_{i}") for i in (1, 2)]
        replay[24] = {"replayed_amplitude": amplitudes[1], "q_points_used": CONTRACT["replay_tolerance"]["q_points_used"], "additional_replays": 2, "max_difference": float(max(np.max(np.abs(replay_a[0][i] - replay_a[1][i])) for i, point in enumerate(points) if point.point_id in CONTRACT["replay_tolerance"]["q_points_used"])), "replay_1": replay_a[0], "replay_2": replay_a[1]}
        replay[24]["replay_tolerance"] = max(1e-10, 10.0 * replay[24]["max_difference"])
        replay[24]["spectral_equivalence"] = all(float(np.max(np.abs(raw[24][str(amplitudes[1])][i] - raw[24][str(amplitudes[2])][i]))) <= replay[24]["replay_tolerance"] for i in range(len(points)))
        rows[24] = differential(raw, 24)
        final_pair = (20, 24)
        convergence_final = convergence(rows, *final_pair)
    resolved = []
    signal_to_error = float(CONTRACT["resolvability"]["signal_to_error_min"])
    minimum_shift = float(CONTRACT["resolvability"]["absolute_even_shift_min"])
    for item in convergence_final:
        high_row = next(row for row in rows[item["high"]] if row["target"] == item["target"])
        error = max(item["err_A"], item["err_half"])
        resolved_flag = item["status"] == "DIFFERENTIAL_CONVERGED" and abs(high_row["even_A"]) >= signal_to_error * error and abs(high_row["even_A"]) >= minimum_shift
        q = high_row["even_A"] / high_row["even_half"] if high_row["even_half"] else None
        q_uncertainty = None if q is None else abs(q) * (error / max(abs(high_row["even_A"]), 1e-30) + error / max(abs(high_row["even_half"]), 1e-30))
        resolved.append({"target": item["target"], "status": "RESOLVED" if resolved_flag else ("CONVERGED_BUT_UNRESOLVED" if item["status"] == "DIFFERENTIAL_CONVERGED" else item["status"]), "err_final": error, "even_A_high": high_row["even_A"], "even_half_high": high_row["even_half"], "Q": q, "Q_uncertainty": q_uncertainty})
    sign_ok = all(value["spectral_equivalence"] for value in replay.values())
    if not geometry["matching_candidates"]:
        terminal = "BLOCKED_COMPATIBILITY"
    elif not sign_ok:
        terminal = "BLOCKED_EQUIVALENCE_SPECTRAL_MISMATCH"
    elif sum(item["status"] == "RESOLVED" for item in resolved) >= int(CONTRACT["resolvability"]["minimum_resolved_targets_for_pass"]):
        terminal = "PASS_DIFFERENTIAL_RESPONSE_BASELINE"
    else:
        terminal = "BLOCKED_DIFFERENTIAL_RESPONSE_UNRESOLVED"
    write("fresh_solver_execution.json", {"schema": "mephc.affine_architecture.r7_3.fresh_solver_execution.v1", "downstream_calls": calls, "call_count": len(calls), "tri_latt_solver_calls": 0, "resolutions": resolutions, "forbidden_resolution_8_used": any(item["resolution"] == 8 for item in calls)})
    write("raw_spectra.json", {str(resolution): {amp: values.tolist() for amp, values in by_amp.items()} for resolution, by_amp in raw.items()})
    write("replay_floor.json", replay)
    write("target_differential_by_resolution.json", {str(k): v for k, v in rows.items()})
    write("differential_convergence.json", {"initial_16_to_20": initial_convergence, "final_pair": list(final_pair), "targets": convergence_final, "target_denominator": CONTRACT["target_denominator"], "terminal_state": terminal})
    write("resolved_targets.json", {"final_pair": list(final_pair), "targets": resolved, "resolved_count": sum(item["status"] == "RESOLVED" for item in resolved), "denominator": CONTRACT["target_denominator"]})
    write("quadratic_diagnostic.json", {"definition": "Q=E(A)/E(A/2)", "targets": resolved, "diagnostic_only": True})
    write("trilatt_hold.json", {"downstream": "MePhC-TriLatt", "authoritative_ref": CONTRACT["trilatt_hold"]["authoritative_ref"], "fresh_mpb_solver_calls": 0, "new_nonzero_mpb_runs": 0, "five_amplitude_sweep": False, "production_change": False})
    write("completion.json", {"schema": "mephc.affine_architecture.r7_3.completion.v1", "terminal_state": terminal, "scientific_terminal_state": terminal, "final_comparison_pair": list(final_pair), "resolved_count": sum(item["status"] == "RESOLVED" for item in resolved), "target_denominator": CONTRACT["target_denominator"], "accepted_final_resolution": (final_pair[1] if terminal == "PASS_DIFFERENTIAL_RESPONSE_BASELINE" else None), "geometry_equivalence": geometry["status"], "geometry_matching_candidate": geometry["matching_candidates"][0] if geometry["matching_candidates"] else None, "trilatt_fresh_solver_calls": 0, "email_sent": False, "completion_gmail_required": False, "r8_authorized": False, "remote_equal": False, "push_status": "PENDING"})
    (ROOT / "logs" / "execution.log").write_text(f"terminal_state={terminal}\nfinal_pair={final_pair[0]}->{final_pair[1]}\nresolved={sum(item['status'] == 'RESOLVED' for item in resolved)}/{CONTRACT['target_denominator']}\ncall_count={len(calls)}\ntri_calls=0\n", encoding="utf-8")
    print(terminal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
