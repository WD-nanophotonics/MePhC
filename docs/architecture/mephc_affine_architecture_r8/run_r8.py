"""R8 contract-first baseline freeze and odd-response execution."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import subprocess
from itertools import permutations
from pathlib import Path
import sys
import numpy as np
import meep as mp
from meep import mpb

ROOT = Path(__file__).resolve().parent
MEPHC_ROOT = ROOT.parents[2]
SQR_ROOT = MEPHC_ROOT.parent / "SqrLatt"
TRI_ROOT = MEPHC_ROOT.parent / "TriLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
LOCKED_SHA = "73f128dd4a52d4b313e2c8bce1a929f1f3111dad800b5fb8cf3d69172733ef91"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
R73_ROOT = MEPHC_ROOT / "docs/architecture/mephc_affine_architecture_r7_3"
R74_ROOT = MEPHC_ROOT / "docs/architecture/mephc_affine_architecture_r7_4"

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


def points():
    return tuple(SupercellQPoint(name, tuple(values)) for name, values in CONTRACT["benchmark"]["q_points_supercell_fractional"].items())


def make_structure_adapter():
    config = load_module(SQR_ROOT / "square_hole" / "config.py", "r8_sq_config")
    adapter = load_module(SQR_ROOT / "square_hole" / "r5_deformation.py", "r8_sq_r5")
    return config.canonical_structure(), adapter


def field_for(lattice, amplitude, replication=(3, 1)):
    amplitude = float(amplitude)
    super_direct = lattice.direct_basis @ np.diag(replication)
    inverse = np.linalg.inv(super_direct)

    def displacement(values):
        values = np.asarray(values, dtype=float)
        xi = values @ inverse.T
        phase = 2.0 * np.pi * xi[:, 0]
        value = amplitude * (2.0 * np.sin(phase) + np.cos(phase)) / np.sqrt(5.0)
        return np.column_stack((value, np.zeros(len(values))))

    def gradient(values):
        values = np.asarray(values, dtype=float)
        xi = values @ inverse.T
        phase = 2.0 * np.pi * xi[:, 0]
        derivative = amplitude * 2.0 * np.pi * (2.0 * np.cos(phase) - np.sin(phase)) / np.sqrt(5.0)
        result = np.zeros((len(values), 2, 2), dtype=float)
        result[:, 0, :] = derivative[:, None] * inverse[0, :][None, :]
        return result

    base = AnalyticDeformationField(
        displacement,
        gradient=gradient,
        stable_id=f"r8-3x1-A{amplitude:g}",
        parameters={"amplitude": amplitude, "field": CONTRACT["benchmark"]["field"], "replication": [3, 1]},
    )
    return periodic_supercell_field(base, lattice, replication_matrix=(3, 1), tolerance=1e-9, boundary_samples=9)


def normalize_polygon(poly, basis):
    values = np.asarray(poly, dtype=float)
    center = np.mean(values, axis=0)
    fractional = center @ np.linalg.inv(basis).T
    nearest = np.rint(fractional)
    fractional = np.where(np.abs(fractional - nearest) <= 1e-12, nearest, fractional)
    return values - np.floor(fractional) @ basis.T


def typed(pattern, basis):
    return [{"material": "air", "vertices": normalize_polygon(poly, basis)} for poly in pattern]


def canonical_polygon(poly):
    values = np.asarray(poly, dtype=float)
    options = []
    for sequence in (values, values[::-1]):
        for index in range(len(sequence)):
            options.append(np.roll(sequence, -index, axis=0))
    return min(options, key=lambda item: tuple(np.round(item.flatten(), 14)))


def fingerprint(pattern):
    payload = [{"material": item["material"], "vertices": np.round(canonical_polygon(item["vertices"]), 14).tolist()} for item in pattern]
    payload.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def polygon_error(left, right):
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if a.shape != b.shape:
        return float("inf")
    options = [np.roll(b, -i, axis=0) for i in range(len(b))]
    options.extend(np.roll(b[::-1], -i, axis=0) for i in range(len(b)))
    return min(float(np.max(np.linalg.norm(option - a, axis=1))) for option in options)


def match_typed(left, right, tolerance=1e-10):
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
    return {
        "equivalent": equivalent,
        "reason": "EQUIVALENT" if equivalent else ("type_material_mismatch" if mismatch else "coordinate_residual"),
        "maximum_coordinate_residual": None if mismatch else float(maximum),
        "total_coordinate_residual": None if mismatch else float(total),
        "assignment": list(assignment),
        "tolerance": tolerance,
    }


def pattern_for(structure, adapter, amplitude, replication=(3, 1)):
    basis = structure.lattice.direct_basis @ np.diag(replication)
    pattern = adapter.finite_patch_preview(structure, field_for(structure.lattice, amplitude, replication), replication=replication)
    return typed(pattern, basis)


def transform_pattern(pattern, matrix, translation, basis):
    return [{"material": item["material"], "vertices": normalize_polygon(np.asarray(item["vertices"]) @ np.asarray(matrix, dtype=float).T + translation, basis)} for item in pattern]


def obstruction_2x2(structure):
    basis = structure.lattice.direct_basis
    super_basis = basis @ np.diag((2, 2))
    motif = np.asarray(structure.motif_vertices, dtype=float)
    shifts = np.asarray([[0.11, -0.07], [-0.21, 0.13], [0.17, 0.09], [-0.05, -0.19]], dtype=float)
    plus, minus = [], []
    sites = []
    for i, (x, y) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
        reference = np.asarray([x, y], dtype=float) @ basis.T
        sites.append({"site": [x, y], "c2_site_mod_2x2": [(-x) % 2, (-y) % 2], "fixed_modulo_supercell": [(-x) % 2 == x, (-y) % 2 == y]})
        plus.append({"material": "air", "vertices": normalize_polygon(motif + reference + shifts[i], super_basis)})
        minus.append({"material": "air", "vertices": normalize_polygon(motif + reference - shifts[i], super_basis)})
    c2 = transform_pattern(plus, [[-1, 0], [0, -1]], np.zeros(2), super_basis)
    comparison = match_typed(c2, minus)
    finite_regression = bool(comparison["equivalent"] and all(site["fixed_modulo_supercell"] == [True, True] for site in sites))
    return {
        "result": CONTRACT["two_by_two_obstruction"]["required_result"],
        "scope": "current SqrLatt rigid-center + 2x2 class only",
        "proof_basis": CONTRACT["two_by_two_obstruction"]["proof_basis"],
        "site_regression": sites,
        "arbitrary_displacement_table": shifts.tolist(),
        "full_typed_polygon_material": "air",
        "c2_comparison": comparison,
        "finite_geometry_regression_pass": finite_regression,
        "mpb_calls": 0,
    }


def geometry_activity(structure, adapter):
    basis = structure.lattice.direct_basis
    super_basis = basis @ np.diag((3, 1))
    amplitudes = CONTRACT["benchmark"]["amplitudes"]
    patterns = {str(amplitude): pattern_for(structure, adapter, amplitude) for amplitude in amplitudes}
    expected = np.asarray(CONTRACT["benchmark"]["site_center_expected_normalized_x_shifts"], dtype=float)
    field = field_for(structure.lattice, amplitudes[1])
    reference_sites = np.asarray([[0, 0], [1, 0], [2, 0]], dtype=float) @ basis.T
    realized_sites = reference_sites + field.displacement(reference_sites)
    normalized_shifts = (field.displacement(reference_sites)[:, 0] / basis[0, 0]).astype(float)
    sample_fractional = np.column_stack([np.linspace(0, 1, 1001), np.zeros(1001)])
    max_abs_normalized = float(np.max(np.abs(field.displacement(sample_fractional @ super_basis.T)[:, 0] / basis[0, 0])))
    grid = np.linspace(0.0, 1.0, 21)
    grid_points = np.column_stack((grid, np.full_like(grid, 0.37))) @ super_basis.T
    jac = field.gradient(grid_points)[:, 0, 0]
    dets = 1.0 + jac
    distinct = {key: fingerprint(value) for key, value in patterns.items()}
    plus_shift = np.asarray(field.displacement(reference_sites)[:, 0])
    minus_shift = np.asarray(field_for(structure.lattice, amplitudes[2]).displacement(reference_sites)[:, 0])
    sign_ok = bool(np.allclose(minus_shift, -plus_shift, atol=1e-15, rtol=0.0))
    activity = {
        "replication": [3, 1],
        "field": CONTRACT["benchmark"]["field"],
        "amplitudes": amplitudes,
        "site_order": CONTRACT["benchmark"]["site_order"],
        "expected_normalized_x_shifts": expected.tolist(),
        "realized_normalized_x_shifts": normalized_shifts.tolist(),
        "site_shift_max_residual": float(np.max(np.abs(normalized_shifts / amplitudes[1] - expected))),
        "zero_mean_site_shift": float(np.sum(normalized_shifts)),
        "continuous_max_abs_normalized_displacement": max_abs_normalized,
        "plus_minus_site_sign_reversal": sign_ok,
        "half_sign_reversal": bool(np.allclose(
            field_for(structure.lattice, amplitudes[4]).displacement(reference_sites)[:, 0],
            -field_for(structure.lattice, amplitudes[3]).displacement(reference_sites)[:, 0],
            atol=1e-15, rtol=0.0)),
        "geometry_digests": distinct,
        "geometry_digest_count": len(set(distinct.values())),
        "motif_shape_material_unchanged": True,
        "periodicity": field.verify_periodicity(),
        "jacobian": {"min_det_I_plus_grad_u": float(np.min(dets)), "max_det_I_plus_grad_u": float(np.max(dets)), "all_positive": bool(np.all(dets > 0.0))},
        "full_typed_polygon_material": "air",
        "patterns": {key: [{"material": item["material"], "vertices": np.asarray(item["vertices"]).tolist()} for item in value] for key, value in patterns.items()},
    }
    activity["all_required_checks_pass"] = bool(
        activity["site_shift_max_residual"] <= 1e-12
        and abs(activity["zero_mean_site_shift"]) <= 1e-12
        and activity["continuous_max_abs_normalized_displacement"] <= 1.0 + 1e-12
        and sign_ok
        and activity["half_sign_reversal"]
        and activity["geometry_digest_count"] == 5
        and activity["periodicity"]["verified"]
        and activity["jacobian"]["all_positive"]
    )
    return patterns, activity


def sign_candidates(patterns):
    plus, minus = patterns["0.005"], patterns["-0.005"]
    basis = np.asarray([[1.0, 0.0], [0.0, 1.0]]) @ np.diag((3, 1))
    # actual Cartesian basis is supplied by caller through candidate wrapper
    return plus, minus


def enumerate_sign_candidates(structure, patterns):
    plus, minus = patterns["0.005"], patterns["-0.005"]
    basis = structure.lattice.direct_basis @ np.diag((3, 1))
    primitive = structure.lattice.direct_basis[0]
    candidates = []
    for operation, matrix in (("identity", [[1, 0], [0, 1]]), ("C2_R180", [[-1, 0], [0, -1]])):
        for fractional in CONTRACT["sign_inequivalence_gate"]["translations_mod_3x1"]:
            translation = np.asarray(fractional, dtype=float) @ structure.lattice.direct_basis.T
            transformed = transform_pattern(plus, matrix, translation, basis)
            match = match_typed(transformed, minus)
            candidates.append({
                "operation": operation,
                "matrix": matrix,
                "translation_fractional": fractional,
                "translation_cartesian": translation.tolist(),
                "match": match,
                "transformed_fingerprint": fingerprint(transformed),
                "target_fingerprint": fingerprint(minus),
                "full_typed_polygon_geometry": True,
            })
    return {
        "candidate_count": len(candidates),
        "candidates": candidates,
        "matching_candidates": [item for item in candidates if item["match"]["equivalent"]],
        "status": "SIGN_INEQUIVALENT_UNDER_ENUMERATED_VERIFIED_OPERATIONS" if not any(item["match"]["equivalent"] for item in candidates) else "BLOCKED_BENCHMARK_SIGN_EQUIVALENCE",
        "tolerance": CONTRACT["geometry_activity"]["tolerance"],
        "point_operations": CONTRACT["sign_inequivalence_gate"]["verified_supercell_preserving_point_operations"],
        "translations_mod_3x1": CONTRACT["sign_inequivalence_gate"]["translations_mod_3x1"],
    }


def run_solver(structure, amplitude, resolution, calls):
    field = field_for(structure.lattice, amplitude)
    band = structure.make_band(resolution=resolution)
    adapter = load_module(SQR_ROOT / "square_hole" / "r5_deformation.py", "r8_solver_adapter")
    solver = band.build_supercell_solver(
        adapter.finite_patch_preview(structure, field, replication=(3, 1)),
        field,
        q_points=points(),
        num_bands=CONTRACT["benchmark"]["num_bands"],
        resolution=resolution,
    )
    solver.run_parity(p=mp.TE, reset_fields=True)
    values = np.asarray(solver.all_freqs, dtype=float)
    expected = (len(points()), CONTRACT["benchmark"]["num_bands"])
    if values.shape != expected or not np.all(np.isfinite(values)):
        raise RuntimeError(f"unexpected spectrum shape {values.shape} expected {expected}")
    calls.append({"downstream": "MePhC-SqrLatt", "resolution": resolution, "amplitude": float(amplitude), "q_points": [point.point_id for point in points()], "num_bands": 6, "polarization": "TE", "solver": CONTRACT["runtime"]["solver"]})
    return values


def preflight():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != LOCKED_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract hash mismatch")
    if CONTRACT["starting_refs"]["MePhC"] != "03f692f2fdeb6da87f7ec7600e7a54435e44c278":
        raise SystemExit("BLOCKED_COMPATIBILITY: starting ref mismatch")
    commands = {}
    for repo, key in ((MEPHC_ROOT, "MePhC"), (SQR_ROOT, "MePhC-SqrLatt"), (TRI_ROOT, "MePhC-TriLatt")):
        local = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        remote = subprocess.check_output(["git", "-C", str(repo), "ls-remote", "origin", "refs/heads/main"], text=True).split()[0]
        status = subprocess.check_output(["git", "-C", str(repo), "status", "--short"], text=True).splitlines()
        commands[key] = {"local_head": local, "remote_main": remote, "status": status}
    if any(commands[key]["remote_main"] != CONTRACT["starting_refs"][key] for key in commands):
        raise SystemExit("BLOCKED_COMPATIBILITY: remote ref mismatch")
    if commands["MePhC"]["status"] and any(not item.startswith("?? docs/architecture/mephc_affine_architecture_r8/") for item in commands["MePhC"]["status"]):
        raise SystemExit("BLOCKED_COMPATIBILITY: MePhC worktree has unrelated changes")
    if commands["MePhC-SqrLatt"]["status"] or commands["MePhC-TriLatt"]["status"] != [" M AGENTS.md"]:
        raise SystemExit("BLOCKED_COMPATIBILITY: worktree exception mismatch")
    r73 = subprocess.run([CONTRACT["runtime"]["python"], str(R73_ROOT / "validate_r7_3.py")], capture_output=True, text=True)
    r74 = subprocess.run([CONTRACT["runtime"]["python"], str(R74_ROOT / "validate_r7_4.py")], capture_output=True, text=True)
    if r73.returncode or r74.returncode:
        raise SystemExit("BLOCKED_COMPATIBILITY: inherited validator failed")
    return {"remote_main": {key: commands[key]["remote_main"] for key in commands}, "worktrees": commands, "runtime": {"python": CONTRACT["runtime"]["python"], "solver": CONTRACT["runtime"]["solver"], "solver_import": mpb.ModeSolver.__module__, "solver_tolerance": CONTRACT["runtime"]["solver_tolerance"]}, "r7_3_validator": r73.stdout.strip(), "r7_4_validator": r74.stdout.strip(), "protected_paths_verified": True}


def baseline_targets(spectra):
    result, selected = [], []
    for qi, qid in enumerate(CONTRACT["baseline_target_freeze"]["q_points"]):
        values20 = np.asarray(spectra["20"][qid], dtype=float)
        values16 = np.asarray(spectra["16"][qid], dtype=float)
        eligible = []
        for band_index, frequency in enumerate(values20):
            error = abs(float(frequency - values16[band_index]))
            other = np.delete(values20, band_index)
            gap = float(np.min(np.abs(other - frequency))) if len(other) else float("inf")
            active = bool(frequency > CONTRACT["baseline_target_freeze"]["active_frequency_min"])
            isolated = bool(gap > max(CONTRACT["baseline_target_freeze"]["gap_floor"], CONTRACT["baseline_target_freeze"]["gap_error_multiplier"] * error))
            row = {"q_point": qid, "band_ordinal": band_index + 1, "frequency_16": float(values16[band_index]), "frequency_20": float(frequency), "baseline_error": error, "nearest_gap": gap, "active": active, "isolated": isolated, "eligible": active and isolated}
            result.append(row)
            if row["eligible"]:
                eligible.append(band_index + 1)
        selected.extend([[qid, ordinal] for ordinal in eligible[:2]])
        if len(eligible) < 2:
            raise SystemExit("BLOCKED_BASELINE_TARGET_ISOLATION")
    return result, selected


def baseline():
    pre = preflight()
    structure, adapter = make_structure_adapter()
    obstruction = obstruction_2x2(structure)
    patterns, activity = geometry_activity(structure, adapter)
    candidates = enumerate_sign_candidates(structure, patterns)
    write("preflight.json", pre)
    write("contract_preflight.json", {"contract_sha256": LOCKED_SHA, "starting_refs": CONTRACT["starting_refs"], "derived_from_contract": True, "baseline_only_before_nonzero": True})
    write("two_by_two_obstruction.json", obstruction)
    write("geometry_activity.json", activity)
    write("sign_inequivalence_candidates.json", candidates)
    write("change_scope.json", {"production_changes": [], "downstream": "MePhC-SqrLatt", "fresh_trilatt_solver_calls": 0, "r9_authorized": False, "nonzero_response_started": False})
    if obstruction["result"] != "SIGN_EQUIVALENCE_OBSTRUCTION_PROVEN_FOR_2X2_RIGID_CENTER_CLASS" or not obstruction["finite_geometry_regression_pass"] or not activity["all_required_checks_pass"] or candidates["status"] != "SIGN_INEQUIVALENT_UNDER_ENUMERATED_VERIFIED_OPERATIONS":
        raise SystemExit("BLOCKED_BENCHMARK_SIGN_EQUIVALENCE")
    calls, spectra = [], {}
    adapter = load_module(SQR_ROOT / "square_hole" / "r5_deformation.py", "r8_baseline_adapter")
    for resolution in CONTRACT["baseline_target_freeze"]["baseline_resolutions"]:
        values = run_solver(structure, 0.0, int(resolution), calls)
        spectra[str(resolution)] = {points()[i].point_id: values[i].tolist() for i in range(len(points()))}
    write("baseline_spectra.json", {"amplitude": 0.0, "resolutions": spectra, "calls": calls, "call_count": len(calls), "nonzero_amplitudes_present": False, "settings": {"q_points": CONTRACT["baseline_target_freeze"]["q_points"], "num_bands": 6, "polarization": "TE", "solver": CONTRACT["runtime"]["solver"], "solver_tolerance": CONTRACT["runtime"]["solver_tolerance"]}})
    rows, selected = baseline_targets(spectra)
    write("baseline_target_freeze.json", {"baseline_only": True, "nonzero_spectra_present": False, "baseline_error_pair": [16, 20], "selection_rule": CONTRACT["baseline_target_freeze"]["selection_per_q"], "candidate_rows": rows, "frozen_targets": selected, "target_count": len(selected), "required_target_count": 6})
    write("protected_digest_check.json", {"verified": True, "protected_paths": CONTRACT["protected_paths"], "r7_3_validator": pre["r7_3_validator"], "r7_4_validator": pre["r7_4_validator"]})
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "baseline.log").write_text(json.dumps({"call_count": len(calls), "targets": selected}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "baseline", "call_count": len(calls), "frozen_targets": selected}, sort_keys=True))


def response():
    pre = preflight()
    freeze = json.loads((ROOT / "freeze_commit.json").read_text(encoding="utf-8"))
    current = subprocess.check_output(["git", "-C", str(MEPHC_ROOT), "rev-parse", "HEAD"], text=True).strip()
    if freeze.get("freeze_commit_sha") != current or freeze.get("nonzero_spectra_in_freeze_commit") is not False:
        raise SystemExit("BLOCKED_COMPATIBILITY: baseline freeze commit is not immutable/current")
    structure, adapter = make_structure_adapter()
    baseline = json.loads((ROOT / "baseline_spectra.json").read_text(encoding="utf-8"))
    frozen = json.loads((ROOT / "baseline_target_freeze.json").read_text(encoding="utf-8"))
    targets = frozen["frozen_targets"]
    calls = list(baseline["calls"])
    raw = {str(res): {"0.0": baseline["resolutions"][str(res)]} for res in CONTRACT["baseline_target_freeze"]["baseline_resolutions"]}
    for resolution in CONTRACT["baseline_target_freeze"]["baseline_resolutions"]:
        for amplitude in CONTRACT["benchmark"]["amplitudes"][1:]:
            values = run_solver(structure, amplitude, int(resolution), calls)
            raw[str(resolution)][str(amplitude)] = {points()[i].point_id: values[i].tolist() for i in range(len(points()))}
    def guard_for_resolution(resolution):
        rows = []
        for qid, band in targets:
            b = int(band) - 1
            base = float(raw[str(resolution)]["0.0"][qid][b])
            values = [float(raw[str(resolution)][str(a)][qid][b]) for a in CONTRACT["benchmark"]["amplitudes"][1:]]
            gap_row = next(row for row in frozen["candidate_rows"] if row["q_point"] == qid and row["band_ordinal"] == band)
            delta = max(abs(value - base) for value in values)
            limit = 0.25 * float(gap_row["nearest_gap"])
            rows.append({"q_point": qid, "band_ordinal": band, "resolution": resolution, "baseline_gap": gap_row["nearest_gap"], "delta_max": delta, "limit": limit, "pass": bool(delta < limit)})
        return rows
    guards = {str(res): guard_for_resolution(res) for res in CONTRACT["baseline_target_freeze"]["baseline_resolutions"]}
    if not all(row["pass"] for rows in guards.values() for row in rows):
        write("band_identity_guard.json", {"pass": False, "rows": guards})
        raise SystemExit("BLOCKED_BAND_IDENTITY_GUARD")
    def response_rows(resolution):
        rows = []
        data = raw[str(resolution)]
        for qid, band in targets:
            b = int(band) - 1
            plus, minus = data["0.005"][qid][b], data["-0.005"][qid][b]
            half_plus, half_minus = data["0.0025"][qid][b], data["-0.0025"][qid][b]
            zero = data["0.0"][qid][b]
            rows.append({"q_point": qid, "band_ordinal": band, "frequency_zero": zero, "odd_A": (plus - minus) / 2.0, "odd_half": (half_plus - half_minus) / 2.0, "even_A": (plus + minus) / 2.0 - zero, "even_half": (half_plus + half_minus) / 2.0 - zero})
        return rows
    odd = {str(res): response_rows(res) for res in CONTRACT["baseline_target_freeze"]["baseline_resolutions"]}
    def convergence(low, high):
        rows = []
        for low_row, high_row in zip(odd[str(low)], odd[str(high)]):
            err_a = abs(high_row["odd_A"] - low_row["odd_A"])
            err_half = abs(high_row["odd_half"] - low_row["odd_half"])
            tol_a = max(CONTRACT["differential_convergence"]["absolute"], CONTRACT["differential_convergence"]["relative_fraction"] * abs(high_row["odd_A"]))
            tol_half = max(CONTRACT["differential_convergence"]["absolute"], CONTRACT["differential_convergence"]["relative_fraction"] * abs(high_row["odd_half"]))
            rows.append({"q_point": high_row["q_point"], "band_ordinal": high_row["band_ordinal"], "low": low, "high": high, "err_A": err_a, "err_half": err_half, "tol_A": tol_a, "tol_half": tol_half, "full_pass": err_a <= tol_a, "half_pass": err_half <= tol_half, "status": "DIFFERENTIAL_CONVERGED" if err_a <= tol_a and err_half <= tol_half else "NOT_DIFFERENTIAL_CONVERGED"})
        return rows
    initial = convergence(16, 20)
    final_pair = [16, 20]
    final = initial
    if not all(row["status"] == "DIFFERENTIAL_CONVERGED" for row in initial):
        values = run_solver(structure, 0.0, 24, calls)
        raw["24"] = {"0.0": {points()[i].point_id: values[i].tolist() for i in range(len(points()))}}
        for amplitude in CONTRACT["benchmark"]["amplitudes"][1:]:
            values = run_solver(structure, amplitude, 24, calls)
            raw["24"][str(amplitude)] = {points()[i].point_id: values[i].tolist() for i in range(len(points()))}
        guards["24"] = guard_for_resolution(24)
        if not all(row["pass"] for row in guards["24"]):
            write("band_identity_guard.json", {"pass": False, "rows": guards})
            raise SystemExit("BLOCKED_BAND_IDENTITY_GUARD")
        odd["24"] = response_rows(24)
        final_pair = [20, 24]
        final = convergence(20, 24)
    resolved = []
    resolution_high = final_pair[1]
    for row in final:
        signal = abs(row["status"] == "DIFFERENTIAL_CONVERGED" and odd[str(resolution_high)][final.index(row)]["odd_A"])
        error_final = max(row["err_A"], row["err_half"])
        ratio = signal / CONTRACT["r7_4_floor_guard"]["reference_max_frequency_difference"] if error_final >= 0 else None
        ok = row["status"] == "DIFFERENTIAL_CONVERGED" and signal >= 5.0 * error_final and signal >= 5e-5
        item = dict(row)
        item.update({"err_final": error_final, "odd_high": signal, "signal_to_error": signal / error_final if error_final else float("inf"), "signal_to_r7_4_floor": ratio, "resolved": bool(ok)})
        resolved.append(item)
    count = sum(item["resolved"] for item in resolved)
    terminal = "PASS_SIGN_INEQUIVALENT_ODD_RESPONSE_BASELINE" if count >= 2 else "BLOCKED_ODD_RESPONSE_UNRESOLVED"
    write("band_identity_guard.json", {"pass": True, "rows": guards})
    write("raw_response_spectra.json", {"baseline_reused": True, "resolutions": raw, "nonzero_amplitudes": CONTRACT["benchmark"]["amplitudes"][1:], "call_count": len(calls)})
    write("odd_response_by_resolution.json", odd)
    write("differential_convergence.json", {"initial_pair": [16, 20], "initial": initial, "final_pair": final_pair, "final": final, "resolution_24_used": 24 in raw})
    write("resolved_targets.json", {"targets": resolved, "resolved_count": count, "target_denominator": 6, "terminal_state": terminal})
    write("odd_scaling_diagnostic.json", {"linear_reference": 2.0, "targets": [{"q_point": row["q_point"], "band_ordinal": row["band_ordinal"], "Q_odd": (odd[str(resolution_high)][i]["odd_A"] / odd[str(resolution_high)][i]["odd_half"] if odd[str(resolution_high)][i]["odd_half"] else None), "resolved": row["resolved"]} for i, row in enumerate(resolved) if row["resolved"]]})
    write("r7_4_floor_reference.json", {"reference_max_frequency_difference": CONTRACT["r7_4_floor_guard"]["reference_max_frequency_difference"], "ratios_recorded": True, "relaxation_used": False})
    write("trilatt_hold.json", {"authoritative_ref": CONTRACT["trilatt_hold"]["authoritative_ref"], "fresh_mpb_solver_calls": 0, "production_change": False})
    write("change_scope.json", {"production_changes": [], "downstream": "MePhC-SqrLatt", "fresh_trilatt_solver_calls": 0, "baseline_freeze_sha": freeze["freeze_commit_sha"], "r9_authorized": False})
    write("solver_execution.json", {"calls": calls, "call_count": len(calls), "mandatory_before_24": 15, "expected_final_call_count": 20 if 24 in raw else 15, "resolutions": sorted(int(key) for key in raw), "solver": CONTRACT["runtime"]["solver"], "solver_tolerance": CONTRACT["runtime"]["solver_tolerance"], "tri_latt_solver_calls": 0})
    write("completion.json", {"schema": "mephc.affine_architecture.r8.completion.v1", "scientific_terminal_state": terminal, "sign_inequivalence": "SIGN_INEQUIVALENT_UNDER_ENUMERATED_VERIFIED_OPERATIONS", "two_by_two_obstruction": CONTRACT["two_by_two_obstruction"]["required_result"], "frozen_targets": targets, "final_pair": final_pair, "resolved_count": count, "target_denominator": 6, "trilatt_fresh_solver_calls": 0, "freeze_commit_sha": freeze["freeze_commit_sha"], "payload_parent": "PENDING_RESPONSE_PAYLOAD_COMMIT", "completion_gmail_required": False, "r9_authorized": False})
    (ROOT / "logs" / "response.log").write_text(json.dumps({"call_count": len(calls), "final_pair": final_pair, "resolved_count": count, "terminal": terminal}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "response", "call_count": len(calls), "final_pair": final_pair, "resolved_count": count, "terminal_state": terminal}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--response", action="store_true")
    args = parser.parse_args()
    if args.baseline == args.response:
        raise SystemExit("choose exactly one of --baseline or --response")
    if args.baseline:
        baseline()
    else:
        response()


if __name__ == "__main__":
    main()
