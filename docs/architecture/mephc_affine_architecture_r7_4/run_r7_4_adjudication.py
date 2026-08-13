"""Execute the R7.4 fixed SqrLatt numerical-equivalence controls."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import meep as mp
from meep import mpb
import numpy as np

ROOT = Path(__file__).resolve().parent
MEPHC_ROOT = ROOT.parents[2]
SQR_ROOT = MEPHC_ROOT.parent / "SqrLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
R73_ROOT = MEPHC_ROOT / "docs/architecture/mephc_affine_architecture_r7_3"
LOCKED_SHA = "60b1979544d6ba3c6fe4840c97f8e291fed1c591836d4b8d52860d2997951a47"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
R73_CONTRACT = json.loads((R73_ROOT / "authoritative_contract.json").read_text(encoding="utf-8"))

sys.path.insert(0, str(MEPHC_ROOT))
sys.path.insert(0, str(SQR_ROOT))

from mephc.deformation import AnalyticDeformationField, periodic_supercell_field
from mephc.response import SupercellQPoint


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


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


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract_points():
    return tuple(SupercellQPoint(name, tuple(values)) for name, values in R73_CONTRACT["benchmark"]["q_points"].items())


def make_structure_and_adapter():
    config = load_module(SQR_ROOT / "square_hole" / "config.py", "r74_sq_config")
    adapter = load_module(SQR_ROOT / "square_hole" / "r5_deformation.py", "r74_sq_r5")
    return config.canonical_structure(), adapter


def contract_field(lattice, amplitude):
    benchmark = R73_CONTRACT["benchmark"]
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
        stable_id=f"r7.4-contract-A{amplitude:g}",
        parameters={"amplitude": amplitude, "field": benchmark["field"], "replication": list(replication)},
    )
    return periodic_supercell_field(base, lattice, replication_matrix=replication, tolerance=1e-9, boundary_samples=9)


def normalize_polygon(poly, basis):
    values = np.asarray(poly, dtype=float)
    center = np.mean(values, axis=0)
    fractional = center @ np.linalg.inv(basis).T
    nearest = np.rint(fractional)
    fractional = np.where(np.abs(fractional - nearest) <= 1e-12, nearest, fractional)
    return values - np.floor(fractional) @ basis.T


def typed(pattern, basis):
    return [{"material": "air", "vertices": normalize_polygon(poly, basis)} for poly in pattern]


def translated(pattern, vector, basis):
    return [{"material": item["material"], "vertices": normalize_polygon(np.asarray(item["vertices"]) + vector, basis)} for item in pattern]


def arrays(pattern):
    return [np.asarray(item["vertices"], dtype=float) for item in pattern]


def canonical_polygon(poly):
    values = np.asarray(poly, dtype=float)
    options = []
    for sequence in (values, values[::-1]):
        for index in range(len(sequence)):
            options.append(np.roll(sequence, -index, axis=0))
    return min(options, key=lambda item: tuple(np.round(item.flatten(), 14)))


def geometry_fingerprint(pattern):
    payload = []
    for item in pattern:
        payload.append({"material": item["material"], "vertices": np.round(canonical_polygon(item["vertices"]), 14).tolist()})
    payload.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def polygon_error(left, right):
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    if a.shape != b.shape:
        return float("inf")
    options = [np.roll(b, -i, axis=0) for i in range(len(b))]
    options.extend(np.roll(b[::-1], -i, axis=0) for i in range(len(b)))
    return min(float(np.max(np.linalg.norm(option - a, axis=1))) for option in options)


def match_typed(left, right, tolerance):
    from itertools import permutations
    if len(left) != len(right):
        return {"equivalent": False, "reason": "polygon_count", "maximum_coordinate_residual": None, "assignment": []}
    costs = [[polygon_error(a["vertices"], b["vertices"]) if a["material"] == b["material"] else float("inf") for b in right] for a in left]
    candidates = []
    for assignment in permutations(range(len(right))):
        values = [costs[i][assignment[i]] for i in range(len(left))]
        candidates.append((max(values), sum(values), assignment))
    maximum, total, assignment = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    equivalent = bool(maximum <= tolerance)
    mismatch = not np.isfinite(maximum)
    return {"equivalent": equivalent, "reason": "EQUIVALENT" if equivalent else ("type_material_mismatch" if mismatch else "coordinate_residual"), "maximum_coordinate_residual": None if mismatch else float(maximum), "total_coordinate_residual": None if mismatch else float(total), "assignment": list(assignment), "tolerance": tolerance}


def geometry_controls(structure, adapter):
    replication = tuple(int(v) for v in R73_CONTRACT["benchmark"]["replication"])
    basis = structure.lattice.direct_basis @ np.diag(replication)
    plus_amp = float(R73_CONTRACT["benchmark"]["amplitudes"][1])
    minus_amp = float(R73_CONTRACT["benchmark"]["amplitudes"][2])
    plus = typed(adapter.finite_patch_preview(structure, contract_field(structure.lattice, plus_amp), replication=replication), basis)
    minus = typed(adapter.finite_patch_preview(structure, contract_field(structure.lattice, minus_amp), replication=replication), basis)
    primitive = np.asarray(structure.lattice.direct_basis[0], dtype=float)
    full = 2.0 * primitive
    cycle = []
    for index, item in enumerate(plus):
        vertices = np.roll(np.asarray(item["vertices"]), index % len(item["vertices"]), axis=0)
        if index % 2:
            vertices = vertices[::-1]
        cycle.append({"material": item["material"], "vertices": vertices})
    controls = {
        "canonical_plus_A": plus,
        "polygon_list_reversed_plus_A": list(reversed(plus)),
        "deterministic_vertex_cycle_and_winding_plus_A": cycle,
        "supercell_vector_wrap_plus_A": translated(plus, full, basis),
        "primitive_a1_translated_plus_A": translated(plus, primitive, basis),
        "canonical_minus_A": minus,
    }
    reference = controls["canonical_plus_A"]
    comparisons = {}
    for name in ("polygon_list_reversed_plus_A", "deterministic_vertex_cycle_and_winding_plus_A", "supercell_vector_wrap_plus_A"):
        comparisons[name] = match_typed(reference, controls[name], CONTRACT["geometry_control"]["tolerance"])
    comparisons["primitive_a1_translated_plus_A_vs_canonical_minus_A"] = match_typed(controls["primitive_a1_translated_plus_A"], controls["canonical_minus_A"], CONTRACT["geometry_control"]["tolerance"])
    comparisons["primitive_a1_translated_plus_A_vs_primitive_image"] = match_typed(controls["primitive_a1_translated_plus_A"], translated(reference, primitive, basis), CONTRACT["geometry_control"]["tolerance"])
    result = {"full_typed_polygon_material": "air", "tolerance": CONTRACT["geometry_control"]["tolerance"], "controls": {name: {"polygon_count": len(value), "fingerprint": geometry_fingerprint(value), "vertices": [{"material": item["material"], "vertices": np.asarray(item["vertices"]).tolist()} for item in value]} for name, value in controls.items()}, "comparisons": comparisons, "all_required_geometry_controls_pass": all(value.get("equivalent") for value in comparisons.values())}
    return controls, result


def epsilon_summary(array):
    values = np.asarray(array, dtype=float)
    normalized = np.ascontiguousarray(values, dtype="<f8")
    return {"shape": list(values.shape), "sha256": hashlib.sha256(normalized.tobytes()).hexdigest()}


def epsilon_array(solver, resolution):
    values = np.asarray(solver.get_epsilon(), dtype=float)
    if values.ndim == 1 and values.size == (2 * resolution) ** 2:
        values = values.reshape(2 * resolution, 2 * resolution)
    if values.ndim != 2:
        raise RuntimeError(f"EPSILON_GRID_API_UNAVAILABLE: unexpected epsilon shape {values.shape}")
    return values


def run_one(structure, pattern, field, resolution, points):
    band = structure.make_band(resolution=resolution)
    solver = band.build_supercell_solver(arrays(pattern), field, q_points=points, num_bands=int(CONTRACT["diagnostic_scope"]["num_bands"]), resolution=resolution)
    tolerance = getattr(solver, "tolerance", None)
    solver.run_parity(p=mp.TE, reset_fields=True)
    freqs = np.asarray(solver.all_freqs, dtype=float)
    epsilon = epsilon_array(solver, resolution)
    expected = (len(points), int(CONTRACT["diagnostic_scope"]["num_bands"]))
    if freqs.shape != expected or not np.all(np.isfinite(freqs)):
        raise RuntimeError(f"unexpected frequency shape {freqs.shape}; expected {expected}")
    return freqs, epsilon, {"solver": CONTRACT["runtime"]["solver"], "resolution": resolution, "num_bands": int(CONTRACT["diagnostic_scope"]["num_bands"]), "polarization": CONTRACT["diagnostic_scope"]["polarization"], "tolerance": tolerance, "environment": CONTRACT["runtime"]["python"]}


def q_max(values, q_index):
    return float(np.max(np.abs(values[q_index])))


def main():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != LOCKED_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract digest mismatch")
    if CONTRACT["starting_refs"]["MePhC"] != "d51c90bc8d1489139912415af85c0c5a887dc4d2":
        raise SystemExit("BLOCKED_COMPATIBILITY: starting ref mismatch")
    structure, adapter = make_structure_and_adapter()
    points = contract_points()
    r73 = subprocess.run([CONTRACT["runtime"]["python"], str(R73_ROOT / "validate_r7_3.py")], capture_output=True, text=True)
    r73neg = subprocess.run([CONTRACT["runtime"]["python"], str(R73_ROOT / "validator_negative_fixtures.py")], capture_output=True, text=True)
    if r73.returncode or r73neg.returncode:
        raise SystemExit("BLOCKED_COMPATIBILITY: inherited R7.3 validation failed")
    refs = {}
    for repo, key in ((MEPHC_ROOT, "MePhC"), (SQR_ROOT, "MePhC-SqrLatt"), (MEPHC_ROOT.parent / "TriLatt", "MePhC-TriLatt")):
        remote = subprocess.check_output(["git", "-C", str(repo), "ls-remote", "origin", "refs/heads/main"], text=True).split()[0]
        local = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        status = subprocess.check_output(["git", "-C", str(repo), "status", "--short"], text=True)
        refs[key] = {"local_head": local, "remote_main": remote, "status": status.splitlines()}
    if any(refs[key]["remote_main"] != CONTRACT["starting_refs"][key] for key in refs):
        raise SystemExit("BLOCKED_COMPATIBILITY: remote ref mismatch")
    mephc_unexpected = [line for line in refs["MePhC"]["status"] if not line.startswith("?? docs/architecture/mephc_affine_architecture_r7_4/")]
    if mephc_unexpected or refs["MePhC-SqrLatt"]["status"] or refs["MePhC-TriLatt"]["status"] != [" M AGENTS.md"]:
        raise SystemExit("BLOCKED_COMPATIBILITY: worktree boundary mismatch")
    write("contract_preflight.json", {"contract_sha256": LOCKED_SHA, "starting_refs": CONTRACT["starting_refs"], "derived": {"diagnostic_scope": CONTRACT["diagnostic_scope"], "representation_controls": CONTRACT["representation_controls"], "geometry_control": CONTRACT["geometry_control"], "epsilon_grid_control": CONTRACT["epsilon_grid_control"], "classification": CONTRACT["classification"], "scientific_terminal_states": CONTRACT["scientific_terminal_states"]}})
    write("preflight.json", {"remote_main_matches_contract": True, "remote_main": {key: refs[key]["remote_main"] for key in refs}, "runtime": {"python": CONTRACT["runtime"]["python"], "solver": CONTRACT["runtime"]["solver"], "solver_import": mpb.ModeSolver.__module__, "environment_mutation_allowed": False}, "r7_3_validator": r73.stdout.strip(), "r7_3_negative_fixtures": r73neg.stdout.strip(), "worktrees": {"MePhC": {"clean": not mephc_unexpected, "clean_except": [line for line in refs["MePhC"]["status"] if line not in mephc_unexpected]}, "MePhC-SqrLatt": {"clean": not refs["MePhC-SqrLatt"]["status"], "clean_except": []}, "MePhC-TriLatt": {"clean": False, "clean_except": refs["MePhC-TriLatt"]["status"]}}, "protected_paths_verified": True, "allowed_new_bundle": "docs/architecture/mephc_affine_architecture_r7_4/"})
    write("protected_digest_check.json", {"verified": True, "protected_paths": CONTRACT["protected_paths"], "method": "R7.3 contract-first validator and protected evidence digest check", "r7_3_validator": r73.stdout.strip()})
    controls, geometry = geometry_controls(structure, adapter)
    if not geometry["all_required_geometry_controls_pass"]:
        write("representation_geometry_controls.json", geometry)
        raise SystemExit("BLOCKED_CONTROL_CONSTRUCTION: geometry control failed")
    write("representation_geometry_controls.json", geometry)
    amplitudes = {"canonical_plus_A": float(R73_CONTRACT["benchmark"]["amplitudes"][1]), "canonical_minus_A": float(R73_CONTRACT["benchmark"]["amplitudes"][2])}
    fields = {name: contract_field(structure.lattice, amplitude) for name, amplitude in amplitudes.items()}
    resolutions = [int(value) for value in CONTRACT["diagnostic_scope"]["resolutions"]]
    spectra, epsilons, ledger, settings = {}, {}, [], []
    for resolution in resolutions:
        spectra[str(resolution)] = {}
        epsilons[str(resolution)] = {}
        raw = {}
        for name in CONTRACT["representation_controls"]:
            field = fields["canonical_minus_A"] if name == "canonical_minus_A" else fields["canonical_plus_A"]
            freqs, epsilon, setting = run_one(structure, controls[name], field, resolution, points)
            raw[name] = freqs
            spectra[str(resolution)][name] = freqs.tolist()
            epsilons[str(resolution)][name] = {"summary": epsilon_summary(epsilon), "array": epsilon}
            settings.append(setting)
            ledger.append({"downstream": CONTRACT["diagnostic_scope"]["downstream"], "resolution": resolution, "representation": name, "q_points": [point.point_id for point in points], "num_bands": int(CONTRACT["diagnostic_scope"]["num_bands"]), "polarization": CONTRACT["diagnostic_scope"]["polarization"], "solver": CONTRACT["runtime"]["solver"], "purpose": "representation_control"})
        baseline = raw["canonical_plus_A"]
        differences = {}
        for name, label in (("polygon_list_reversed_plus_A", "D_reorder"), ("deterministic_vertex_cycle_and_winding_plus_A", "D_vertex"), ("supercell_vector_wrap_plus_A", "D_superwrap"), ("primitive_a1_translated_plus_A", "D_translate"), ("canonical_minus_A", "D_sign")):
            diff = np.abs(raw[name] - baseline)
            differences[label] = {"by_q": {points[i].point_id: diff[i].tolist() for i in range(len(points))}, "max_by_q": {points[i].point_id: q_max(diff, i) for i in range(len(points))}, "max_all": float(np.max(diff))}
        construct = np.abs(raw["canonical_minus_A"] - raw["primitive_a1_translated_plus_A"])
        differences["D_construct"] = {"by_q": {points[i].point_id: construct[i].tolist() for i in range(len(points))}, "max_by_q": {points[i].point_id: q_max(construct, i) for i in range(len(points))}, "max_all": float(np.max(construct))}
        write(f"representation_spectra_{resolution}.json", {"resolution": resolution, "spectra": {key: value.tolist() for key, value in raw.items()}, "differences": differences})
        eps_map = {name: np.asarray(item["array"], dtype=float) for name, item in epsilons[str(resolution)].items()}
        epsilon_comparisons = {}
        for name in ("polygon_list_reversed_plus_A", "deterministic_vertex_cycle_and_winding_plus_A", "supercell_vector_wrap_plus_A"):
            epsilon_comparisons[f"canonical_plus_A_vs_{name}"] = float(np.max(np.abs(eps_map["canonical_plus_A"] - eps_map[name])))
        reference = eps_map["canonical_plus_A"]
        translated = eps_map["primitive_a1_translated_plus_A"]
        minus_grid = eps_map["canonical_minus_A"]
        shape_supported = reference.ndim == 2 and reference.shape == (2 * resolution, 2 * resolution)
        if shape_supported:
            aligned = np.roll(translated, -resolution, axis=0)
            epsilon_comparisons["primitive_a1_translated_plus_A_vs_canonical_plus_A_after_expected_roll"] = float(np.max(np.abs(aligned - reference)))
            epsilon_comparisons["primitive_a1_translated_plus_A_vs_canonical_minus_A"] = float(np.max(np.abs(translated - minus_grid)))
            epsilon_comparisons["primitive_a1_translated_plus_A_vs_canonical_minus_A_after_expected_roll"] = float(np.max(np.abs(aligned - minus_grid)))
            aligned_hash = hashlib.sha256(np.ascontiguousarray(aligned, dtype="<f8").tobytes()).hexdigest()
        else:
            aligned = None
            epsilon_comparisons["primitive_a1_translated_plus_A_vs_canonical_plus_A_after_expected_roll"] = None
            epsilon_comparisons["primitive_a1_translated_plus_A_vs_canonical_minus_A"] = None
            epsilon_comparisons["primitive_a1_translated_plus_A_vs_canonical_minus_A_after_expected_roll"] = None
            aligned_hash = None
        epsilons[str(resolution)] = {name: {"summary": value["summary"]} for name, value in epsilons[str(resolution)].items()}
        epsilons[str(resolution)]["comparisons"] = {"shape_supported": shape_supported, "axis": 0 if shape_supported else None, "shift": -resolution if shape_supported else None, "max_abs_difference": epsilon_comparisons, "primitive_aligned_hash": aligned_hash}
        for name, value in differences.items():
            pass
        if "all_differences" not in locals():
            all_differences = {}
        all_differences[str(resolution)] = differences
        raw_spectra = spectra
        write("epsilon_grid_controls.json", {"attempted": True, "api_state": "AVAILABLE", "resolutions": epsilons})
        write("representation_spectra.json", {"resolutions": raw_spectra, "differences_by_resolution": all_differences, "q_points": [point.point_id for point in points], "num_bands": 6})
    q0_index = 0
    d_sign_q0 = {resolution: all_differences[resolution]["D_sign"]["max_by_q"]["q0"] for resolution in all_differences}
    d_translate_q0 = {resolution: all_differences[resolution]["D_translate"]["max_by_q"]["q0"] for resolution in all_differences}
    d_construct_q0 = {resolution: all_differences[resolution]["D_construct"]["max_by_q"]["q0"] for resolution in all_differences}
    aligned_ok = all(value["comparisons"]["max_abs_difference"]["primitive_a1_translated_plus_A_vs_canonical_plus_A_after_expected_roll"] is not None and value["comparisons"]["max_abs_difference"]["primitive_a1_translated_plus_A_vs_canonical_plus_A_after_expected_roll"] <= 1e-12 and value["comparisons"]["max_abs_difference"]["primitive_a1_translated_plus_A_vs_canonical_minus_A"] <= 1e-12 for value in epsilons.values())
    geometry_ok = geometry["all_required_geometry_controls_pass"]
    nonzero = any(value > 0.0 for value in d_sign_q0.values())
    if geometry_ok and aligned_ok and nonzero:
        classification = "DISCRETE_OPERATOR_EQUIVALENT_EIGENSOLVER_FLOOR"
    elif geometry_ok and all(value["comparisons"]["max_abs_difference"]["primitive_a1_translated_plus_A_vs_canonical_plus_A_after_expected_roll"] is not None and value["comparisons"]["max_abs_difference"]["primitive_a1_translated_plus_A_vs_canonical_plus_A_after_expected_roll"] > 1e-12 for value in epsilons.values()) and all(d_construct_q0[key] <= d_sign_q0[key] for key in d_sign_q0):
        classification = "DISCRETIZATION_TRANSLATION_REPRESENTATION_FLOOR"
    else:
        classification = "UNEXPLAINED_EQUIVALENCE_MISMATCH"
    terminal = "CLOSED_NUMERICAL_EQUIVALENCE_FLOOR_DIFFERENTIAL_UNRESOLVED" if classification != "UNEXPLAINED_EQUIVALENCE_MISMATCH" else "BLOCKED_UNEXPLAINED_EQUIVALENCE_MISMATCH"
    write("solver_execution.json", {"call_count": len(ledger), "expected_call_count": 4 * 6, "downstream_calls": ledger, "fresh_trilatt_solver_calls": 0, "fresh_five_amplitude_response_sweep": False, "resolutions": resolutions, "representations": CONTRACT["representation_controls"], "solver_settings": settings, "solver_tolerance_values": sorted({item["tolerance"] for item in settings}, key=lambda value: str(value))})
    write("numerical_floor_adjudication.json", {"classification": classification, "scientific_terminal_state": terminal, "geometry_controls_pass": geometry_ok, "epsilon_grid_classification": "IDENTICAL_AFTER_EXPECTED_ROLL_AND_DIRECT_SIGN_PAIR" if aligned_ok else "NOT_IDENTICAL_AFTER_EXPECTED_ROLL", "q0_maxima_by_resolution": {"D_sign": d_sign_q0, "D_translate": d_translate_q0, "D_construct": d_construct_q0}, "no_tolerance_widening": True, "inherited_r7_3_response_baseline": {"resolved_count": 1, "target_denominator": 5, "pass_forbidden": True}})
    write("completion.json", {"schema": "mephc.affine_architecture.r7_4.completion.v1", "scientific_terminal_state": terminal, "numerical_floor_classification": classification, "max_q0": {"D_sign": max(d_sign_q0.values()), "D_translate": max(d_translate_q0.values()), "D_construct": max(d_construct_q0.values())}, "epsilon_grid_classification": "IDENTICAL_AFTER_EXPECTED_ROLL_AND_DIRECT_SIGN_PAIR" if aligned_ok else "NOT_IDENTICAL_AFTER_EXPECTED_ROLL", "inherited_r7_3_resolved_count": 1, "inherited_r7_3_target_denominator": 5, "response_baseline_pass": False, "trilatt_fresh_solver_calls": 0, "final_refs": CONTRACT["starting_refs"], "payload_parent": "PENDING_PAYLOAD_COMMIT", "push_status": "PENDING_FINAL_SEAL_PUSH", "remote_equal": False, "completion_gmail_required": False, "r8_authorized": False})
    (ROOT / "logs" / "execution.log").write_text(json.dumps({"solver_calls": len(ledger), "classification": classification, "terminal": terminal}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"classification": classification, "terminal_state": terminal, "q0_max": {"D_sign": max(d_sign_q0.values()), "D_translate": max(d_translate_q0.values()), "D_construct": max(d_construct_q0.values())}, "call_count": len(ledger)}, sort_keys=True))


if __name__ == "__main__":
    main()
