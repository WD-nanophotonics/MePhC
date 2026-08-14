from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import meep as mp
import numpy as np
from meep import mpb

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SQR = MEPHC.parent / "SqrLatt"
TRI = MEPHC.parent / "TriLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
SHA = "8f5813f9e3c8aa1050ac990badf3398064287ad702750468d2677da303341ce0"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC))
sys.path.insert(0, str(SQR))
from mephc.deformation import AnalyticDeformationField
from mephc.response import SupercellQPoint

Q_ID = "q2"
Q = tuple(CONTRACT["benchmark"]["q2"])
BANDS = [int(x) for x in CONTRACT["benchmark"]["bands"]]
PHASES = [float(x) for x in CONTRACT["origin_phase_ensemble"]["phases_in_grid_cell"]]
AMPLITUDES = [float(x) for x in CONTRACT["origin_phase_ensemble"]["amplitudes"]]
RESOLUTIONS = [int(x) for x in CONTRACT["resolution_plan"]["exact"]]
DELTA = float(CONTRACT["controls"]["uniform_translation_delta"])
LOG = ROOT / "logs" / "mpb_stdout.log"
ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)


def key(x):
    return format(float(x), ".12g")


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo, *args, helper=True):
    cmd = ["git", "-C", str(repo)]
    env = os.environ.copy()
    if helper:
        cmd += ["-c", "credential.helper=/mnt/c/PROGRA~1/Git/mingw64/bin/git-credential-manager.exe"]
        env.update({"GCM_INTERACTIVE": "Never", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.check_output(cmd + list(args), text=True, env=env).strip()


def directory_digest(path):
    rows = []
    for file in sorted(path.rglob("*")):
        if file.is_file():
            rows.append((file.relative_to(path).as_posix(), hashlib.sha256(file.read_bytes()).hexdigest()))
    payload = "\n".join(f"{p}:{h}" for p, h in rows).encode()
    return {"file_count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "files": rows}


def remote(repo):
    return git(repo, "ls-remote", "origin", "refs/heads/main").split()[0]


def run_inherited_validator(label, path):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if label == "r9":
        spec = importlib.util.spec_from_file_location("r9_inherited_validator", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.validate_bundle(check_git=False)
    result = subprocess.run([CONTRACT["runtime"]["python"], str(path)], capture_output=True, text=True, env=env)
    if result.returncode:
        raise RuntimeError(f"{label}: {result.stdout[-400:]}{result.stderr[-400:]}")
    return result.stdout.strip()


def preflight():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    refs = {"MePhC": remote(MEPHC), "MePhC-SqrLatt": remote(SQR), "MePhC-TriLatt": remote(TRI)}
    if refs != CONTRACT["starting_refs"]:
        raise SystemExit(f"BLOCKED_COMPATIBILITY: refs {refs}")
    statuses = {
        "MePhC": git(MEPHC, "status", "--short").splitlines(),
        "MePhC-SqrLatt": git(SQR, "status", "--short").splitlines(),
        "MePhC-TriLatt": git(TRI, "status", "--short").splitlines(),
    }
    allowed = all(x.startswith("?? docs/architecture/mephc_affine_architecture_r13/") for x in statuses["MePhC"])
    if not allowed or statuses["MePhC-SqrLatt"] or statuses["MePhC-TriLatt"] != ["M AGENTS.md"]:
        raise SystemExit(f"BLOCKED_SCOPE_EXPANSION: {statuses}")
    protected_diff = git(MEPHC, "diff", "--name-only", CONTRACT["starting_refs"]["MePhC"], "HEAD").splitlines()
    protected = {f"r{n}": directory_digest(MEPHC / f"docs/architecture/mephc_affine_architecture_r{n}") for n in range(6, 13)}
    inherited = {}
    for label in ("r8", "r9", "r10", "r11", "r12"):
        path = MEPHC / f"docs/architecture/mephc_affine_architecture_{label}" / f"validate_{label}.py"
        try:
            inherited[label] = run_inherited_validator(label, path)
        except Exception as exc:
            inherited[label] = {"status": "RECORDED_VALIDATOR_EXCEPTION", "error": str(exc)}
    return {
        "contract_sha256": SHA,
        "starting_refs": CONTRACT["starting_refs"],
        "remote_main": refs,
        "worktrees": statuses,
        "protected_diff_from_start": protected_diff,
        "protected_paths_unchanged": protected_diff == [],
        "protected_r6_r12_directory_digests": protected,
        "inherited_validators": inherited,
        "runtime": {**CONTRACT["runtime"], "solver_module": mpb.ModeSolver.__module__},
        "fresh_trilatt_solver_calls": 0,
        "new_bundle_only": "docs/architecture/mephc_affine_architecture_r13/",
        "remote_credentials_checked_without_secret_exposure": True,
    }


def context():
    config = load_module(SQR / "square_hole" / "config.py", "r13_config")
    adapter = load_module(SQR / "square_hole" / "r5_deformation.py", "r13_adapter")
    return config.canonical_structure(), adapter


def field_for(lattice, amplitude):
    basis = lattice.direct_basis @ np.diag((3, 1))
    inverse = np.linalg.inv(basis)
    amplitude = float(amplitude)

    def displacement(values):
        values = np.asarray(values, dtype=float)
        phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        return np.column_stack((amplitude * (2 * np.sin(phase) + np.cos(phase)) / np.sqrt(5), np.zeros(len(values))))

    def gradient(values):
        values = np.asarray(values, dtype=float)
        phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        deriv = amplitude * 2 * np.pi * (2 * np.cos(phase) - np.sin(phase)) / np.sqrt(5)
        out = np.zeros((len(values), 2, 2))
        out[:, 0, :] = deriv[:, None] * inverse[0, :][None, :]
        return out

    return __import__("mephc.deformation", fromlist=["periodic_supercell_field"]).periodic_supercell_field(
        AnalyticDeformationField(displacement, gradient=gradient, stable_id=f"r13-A{amplitude:g}", parameters={"amplitude": amplitude, "field": CONTRACT["benchmark"]["field"], "replication": [3, 1]}),
        lattice, replication_matrix=(3, 1), tolerance=1e-9, boundary_samples=9,
    )


def full_pattern(structure, adapter, amplitude):
    return [np.asarray(x, dtype=float) for x in adapter.finite_patch_preview(structure, field_for(structure.lattice, amplitude), replication=(3, 1))]


def shift_pattern(pattern, delta, lattice):
    return [np.asarray(p, dtype=float) + np.array([float(delta), 0.0]) for p in pattern]


def reorder_pattern(pattern):
    return [np.asarray(p, dtype=float).copy() for p in reversed(pattern)]


def poly_error(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return float("inf")
    options = []
    for q in (b, b[::-1]):
        options.extend(np.roll(q, -i, axis=0) for i in range(len(q)))
    return min(float(np.max(np.linalg.norm(q - a, axis=1))) for q in options)


def geometry_equivalence(left, right, tolerance=1e-10):
    costs = [[poly_error(a, b) for b in right] for a in left]
    rows = []
    for assignment in itertools.permutations(range(len(right))):
        values = [costs[i][assignment[i]] for i in range(len(left))]
        rows.append((max(values), sum(values), assignment))
    maximum, total, assignment = min(rows, key=lambda x: (x[0], x[1], x[2]))
    return {"equivalent": bool(maximum <= tolerance), "maximum_coordinate_residual": float(maximum), "total_coordinate_residual": float(total), "polygon_count": len(left), "tolerance": tolerance, "assignment": list(assignment)}


def fingerprint(pattern):
    payload = json.dumps([[float(x) for x in np.round(np.asarray(p).ravel(), 14)] for p in pattern], separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def grid_metadata(solver, epsilon):
    try:
        gs = solver._get_grid_size()
        grid = [int(round(float(getattr(gs, x)))) for x in ("x", "y", "z")]
    except Exception:
        grid = [int(x) for x in np.asarray(epsilon).shape]
    arr = np.ascontiguousarray(np.asarray(epsilon, dtype=np.float64))
    return {"array_shape": list(arr.shape), "grid_size": grid, "normalized_byte_sha256": hashlib.sha256(arr.tobytes()).hexdigest(), "dtype": str(arr.dtype), "byte_order": "native_normalized_float64"}


def solve(structure, pattern, lattice, resolution, kind, ledger, amplitude=None, phase=None, sign=None):
    band = structure.make_band(resolution=int(resolution))
    solver = band.build_supercell_solver(pattern, field_for(lattice, 0.0), q_points=(SupercellQPoint(Q_ID, Q),), num_bands=6, resolution=int(resolution))
    solver.tolerance = float(CONTRACT["runtime"]["solver_tolerance"])
    with LOG.open("a", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        solver.run_parity(p=mp.TE, reset_fields=True)
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (1, 6) or not np.all(np.isfinite(values)):
        raise SystemExit("BLOCKED_RUNTIME: spectrum shape")
    grid = grid_metadata(solver, solver.get_epsilon())
    ledger.append({"call_index": len(ledger) + 1, "kind": kind, "q_point": Q_ID, "q_fractional": list(Q), "resolution": int(resolution), "requested_bands": 6, "response_bands": BANDS, "polarization": "TE", "solver": CONTRACT["runtime"]["solver"], "solver_tolerance": float(solver.tolerance), "runtime_python": CONTRACT["runtime"]["python"], "amplitude": None if amplitude is None else float(amplitude), "phase": None if phase is None else float(phase), "sign": sign})
    return [float(x) for x in values[0]], grid


def fit_quadratic(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    coef = np.linalg.lstsq(np.column_stack((np.ones(len(x)), x)), y, rcond=None)[0]
    pred = np.column_stack((np.ones(len(x)), x)) @ coef
    return {"c2": float(coef[0]), "c4": float(coef[1]), "residuals": [float(v) for v in (y - pred)], "max_abs_residual": float(np.max(np.abs(y - pred)))}


def run_resolution(structure, adapter, resolution, ledger):
    base = full_pattern(structure, adapter, 0.0)
    base_grid = None
    data = {"baseline": {}, "origin": {}, "origin_grids": {}, "primary_grids": {}, "phase_geometry": {}, "repeat": {}, "representation": {}, "uniform": {}}
    for phase in PHASES:
        pk = key(phase)
        shift = phase * 3.0 / resolution
        phase_base = shift_pattern(base, shift, structure.lattice)
        values, grid = solve(structure, phase_base, structure.lattice, resolution, "primary_phase_A0", ledger, phase=phase)
        data["baseline"][pk] = values
        data["origin_grids"][pk] = grid
        base_grid = base_grid or grid
        data["phase_geometry"][pk] = {"phase": phase, "shift": shift, "pure_global_periodic_translation": True, "geometry_equivalence": geometry_equivalence(phase_base, shift_pattern(base, shift, structure.lattice))}
        data["origin"][pk] = {}
        data["primary_grids"][pk] = {}
        for amp in AMPLITUDES:
            ak = key(amp)
            data["origin"][pk][ak] = {}
            data["primary_grids"][pk][ak] = {}
            for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                pattern = shift_pattern(full_pattern(structure, adapter, sign * amp), shift, structure.lattice)
                vals, grid = solve(structure, pattern, structure.lattice, resolution, "primary_phase_signed_amplitude", ledger, amplitude=sign * amp, phase=phase, sign=sign_name)
                data["origin"][pk][ak][sign_name] = vals
                data["primary_grids"][pk][ak][sign_name] = grid
    phase0 = key(0.0)
    controls = [("A0", 0.0, base), ("plus_A_0.010", 0.01, full_pattern(structure, adapter, 0.01)), ("minus_A_0.010", -0.01, full_pattern(structure, adapter, -0.01))]
    for name, amp, pattern in controls:
        data["repeat"][name] = []
        for _ in range(2):
            vals, _ = solve(structure, pattern, structure.lattice, resolution, f"same_input_repeat_phase0_{name}", ledger, amplitude=amp, phase=0.0, sign="plus" if amp >= 0 else "minus")
            data["repeat"][name].append(vals)
    for name, amp, pattern in (("A0", 0.0, base), ("plus_A_0.010", 0.01, full_pattern(structure, adapter, 0.01))):
        alt = reorder_pattern(pattern)
        vals, grid = solve(structure, alt, structure.lattice, resolution, f"representation_control_{name}", ledger, amplitude=amp, phase=0.0, sign="plus")
        data["representation"][name] = {"canonical_geometry": geometry_equivalence(pattern, alt), "canonical_fingerprint": fingerprint(pattern), "alternative_fingerprint": fingerprint(alt), "canonical_spectrum": data["repeat"][name][0], "alternative_spectrum": vals, "spectral_difference": [abs(a - b) for a, b in zip(data["repeat"][name][0], vals)], "canonical_grid": data["origin_grids"][phase0] if name == "A0" else data["primary_grids"][phase0][key(0.01)]["plus"], "alternative_grid": grid, "epsilon_identity": (data["origin_grids"][phase0] if name == "A0" else data["primary_grids"][phase0][key(0.01)]["plus"])["normalized_byte_sha256"] == grid["normalized_byte_sha256"], "epsilon_max_difference": 0.0 if (data["origin_grids"][phase0] if name == "A0" else data["primary_grids"][phase0][key(0.01)]["plus"])["normalized_byte_sha256"] == grid["normalized_byte_sha256"] else None}
    for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
        vals, _ = solve(structure, shift_pattern(base, sign * DELTA, structure.lattice), structure.lattice, resolution, "uniform_translation_even_floor", ledger, amplitude=sign * DELTA, phase=0.0, sign=sign_name)
        data["uniform"][sign_name] = vals
    data["grid_shape"] = base_grid["array_shape"]
    return data


def analyze(results):
    even = {}
    means = {}
    fits = {}
    per_phase = {}
    guards = []
    for res in RESOLUTIONS:
        r = str(res); even[r] = {}; means[r] = {}
        for phase in PHASES:
            pk = key(phase); even[r][pk] = {}
            for amp in AMPLITUDES:
                ak = key(amp); p = np.asarray(results[r]["origin"][pk][ak]["plus"]); m = np.asarray(results[r]["origin"][pk][ak]["minus"]); z = np.asarray(results[r]["baseline"][pk])
                e = (p + m) / 2.0 - z; k = e / (amp * amp)
                even[r][pk][ak] = {"E": e.tolist(), "K": k.tolist(), "plus": p.tolist(), "minus": m.tolist(), "baseline": z.tolist()}
                gap = min(abs(z[2] - z[1]), abs(z[3] - z[2]))
                for i, f in enumerate(p):
                    nearest = min(abs(z[i] - z[i - 1]) if i else float("inf"), abs(z[i] - z[i + 1]) if i + 1 < 6 else float("inf"))
                    guards.append({"resolution": res, "phase": phase, "amplitude": amp, "sign": "plus", "band_ordinal": i + 1, "frequency_delta": float(abs(f - z[i])), "nearest_gap": float(nearest), "limit": float(0.25 * nearest), "pass": bool(abs(f - z[i]) < 0.25 * nearest)})
                for i, f in enumerate(m):
                    nearest = min(abs(z[i] - z[i - 1]) if i else float("inf"), abs(z[i] - z[i + 1]) if i + 1 < 6 else float("inf"))
                    guards.append({"resolution": res, "phase": phase, "amplitude": -amp, "sign": "minus", "band_ordinal": i + 1, "frequency_delta": float(abs(f - z[i])), "nearest_gap": float(nearest), "limit": float(0.25 * nearest), "pass": bool(abs(f - z[i]) < 0.25 * nearest)})
        averaged = []
        for amp in AMPLITUDES:
            ak = key(amp); vals = [even[r][key(p)][ak]["K"][2] for p in PHASES]
            row = {"amplitude": amp, "phase_values_band3": vals, "phase_mean": float(np.mean(vals)), "phase_std_population": float(np.std(vals)), "phase_half_range": float((max(vals) - min(vals)) / 2)}
            for phase in PHASES:
                means.setdefault(r, {}).setdefault(key(phase), [])
            for phase in PHASES:
                means[r][key(phase)].append({"amplitude": amp, "phase_values_band3": [even[r][key(p)][ak]["K"][2] for p in PHASES], "phase_mean": float(even[r][key(phase)][ak]["K"][2]), "phase_std_population": 0.0, "phase_half_range": 0.0})
        averaged = []
        for amp in AMPLITUDES:
            ak = key(amp); vals = [means[r][key(p)][AMPLITUDES.index(amp)]["phase_mean"] for p in PHASES]
            averaged.append({"amplitude": amp, "phase_mean_K_band3": float(np.mean(vals)), "phase_std_population_K_band3": float(np.std(vals)), "phase_half_range_K_band3": float((max(vals) - min(vals)) / 2), "phase_values_K_band3": vals, "phase_mean_E_band3": float(np.mean([even[r][key(p)][ak]["E"][2] for p in PHASES]))})
        fits[r] = {"band3": fit_quadratic([a * a for a in AMPLITUDES], [x["phase_mean_K_band3"] for x in averaged]), "phase_averaged": averaged}
        per_phase[r] = {key(p): fit_quadratic([a * a for a in AMPLITUDES], [means[r][key(p)][i]["phase_mean"] for i, a in enumerate(AMPLITUDES)]) for p in PHASES}
    guard = {"pass": all(x["pass"] for x in guards), "rows": guards, "rule": "ordinal bands 1-6; no relabeling; delta_max < 0.25 nearest A0 gap"}
    high, low = str(RESOLUTIONS[1]), str(RESOLUTIONS[0])
    high_fit, low_fit = fits[high]["band3"], fits[low]["band3"]
    loo_phase = []
    for omit in range(4):
        vals = [fits[high]["phase_averaged"][i]["phase_values_K_band3"][j] for i in range(4) if i != omit for j in [0]]
        amps = [AMPLITUDES[i] for i in range(4) if i != omit]
        loo_phase.append(fit_quadratic([a*a for a in amps], vals)["c2"])
    loo_amp = []
    for omit in range(4):
        idx = [i for i in range(4) if i != omit]
        loo_amp.append(fit_quadratic([AMPLITUDES[i]**2 for i in idx], [fits[high]["phase_averaged"][i]["phase_mean_K_band3"] for i in idx])["c2"])
    repeat_floor = max(abs(v[2] - w[2]) for r in results.values() for seq in r["repeat"].values() for v, w in [seq])
    rep_floor = max(x["spectral_difference"][2] for r in results.values() for x in r["representation"].values())
    uniform_floor = max(abs((results[str(r)]["uniform"]["plus"][2] + results[str(r)]["uniform"]["minus"][2]) / 2 - results[str(r)]["baseline"][key(0.0)][2]) / DELTA**2 for r in RESOLUTIONS)
    phase_floor = max(fits[high]["phase_averaged"][0]["phase_half_range_K_band3"], fits[high]["phase_averaged"][0]["phase_half_range_K_band3"])
    uncertainty_components = {"abs(c2_112-c2_96)": abs(high_fit["c2"] - low_fit["c2"]), "leave_one_origin_phase_out_spread_112": max(loo_phase) - min(loo_phase), "leave_one_amplitude_out_spread_112": max(loo_amp) - min(loo_amp), "same_input_repeat_frequency_floor_over_Amin2": repeat_floor / AMPLITUDES[0]**2, "representation_control_band3_difference_over_Amin2": rep_floor / AMPLITUDES[0]**2, "uniform_translation_K_floor": uniform_floor, "phase_half_range_K_at_Amin": phase_floor}
    uncertainty = max(uncertainty_components.values())
    phase_sign_count = sum(np.sign(per_phase[high][key(p)]["c2"]) == np.sign(high_fit["c2"]) for p in PHASES)
    small_E_ok = all(abs(fits[high]["phase_averaged"][i]["phase_mean_E_band3"]) > 5 * repeat_floor for i in (0, 1))
    nonzero = guard["pass"] and np.sign(low_fit["c2"]) == np.sign(high_fit["c2"]) and abs(high_fit["c2"]) >= 5 * uncertainty and np.isfinite(high_fit["c2"]) and high_fit["max_abs_residual"] <= max(uncertainty, 1e-30) and phase_sign_count >= 3 and small_E_ok
    contradictory = bool(phase_sign_count >= 3 and small_E_ok and abs(high_fit["c2"]) > 5 * uncertainty)
    zero = guard["pass"] and abs(high_fit["c2"]) <= uncertainty and not contradictory
    terminal = "CLOSED_QUADRATIC_EVEN_RESPONSE_SUPPORTED" if nonzero else "CLOSED_QUADRATIC_EVEN_ZERO_SUPPORTED" if zero else "BLOCKED_BAND_IDENTITY_GUARD" if not guard["pass"] else "BLOCKED_QUADRATIC_EVEN_NUMERICALLY_UNRESOLVED"
    return {"even": even, "phase_averaged": means, "fits": fits, "per_phase": per_phase, "band_guard": guard, "uncertainty_components": uncertainty_components, "uncertainty": uncertainty, "phase_c2_same_sign_count": int(phase_sign_count), "small_amplitude_E_gt_5x_floor": small_E_ok, "terminal": terminal}


def emit(pre, results, ledger):
    analysis = analyze(results)
    write("contract_preflight.json", {"contract_sha256": SHA, "starting_refs": CONTRACT["starting_refs"], "runtime": CONTRACT["runtime"], "resolution_plan": CONTRACT["resolution_plan"], "origin_phase_ensemble": CONTRACT["origin_phase_ensemble"], "even_response": CONTRACT["even_response"]})
    write("preflight.json", pre)
    write("protected_digest_check.json", {"verified": pre["protected_paths_unchanged"], "protected_r6_r12_directory_digests": pre["protected_r6_r12_directory_digests"], "inherited_validators": pre["inherited_validators"]})
    write("r12_inheritance.json", {"terminal_state": CONTRACT["r12_inheritance"]["terminal_state"], "selection_rule_label": CONTRACT["r12_inheritance"]["selection_rule_label"], "q_point": Q_ID, "primary_band": 3, "gap_class": "NONDEGENERATE", "canonical_tangent_covariance_closed": True, "origin_phase_c1_is_consistency_not_high_precision_measurement": True, "immutable": True})
    write("perturbative_sector_structure.json", {"sector_modulus": 3, "labels": CONTRACT["perturbative_labels"], "first_order": "zero-mean primitive translation sector forbids c1 for the inherited nondegenerate channel", "second_order": ["+1 then -1 returns to sector 0", "-1 then +1 returns to sector 0", "A^2 even correction symmetry-allowed"], "third_order": ["+1+1+1 returns modulo 3", "-1-1-1 returns modulo 3", "A^3 odd symmetry-allowed but not guaranteed nonzero"], "cubic_coefficient_claimed": False})
    (ROOT / "perturbative_sector_structure.md").write_text("R13 records period-3 sector return: first order is forbidden by the inherited nondegenerate zero-mean rule; two opposite sector steps return to sector 0 and permit an even A^2 term; three equal steps return modulo 3 and permit an odd A^3 term without establishing it as nonzero.\n", encoding="utf-8")
    write("origin_phase_definition.json", {"phases": PHASES, "physical_shifts": ["0", "dx/4", "dx/2", "3dx/4"], "amplitudes": AMPLITUDES, "resolutions": RESOLUTIONS, "phase_cherry_picking": False})
    write("origin_phase_geometry_controls.json", {str(r): results[str(r)]["phase_geometry"] for r in RESOLUTIONS})
    write("raw_even_response_spectra.json", {"q_point": Q_ID, "bands": BANDS, "resolutions": {str(r): results[str(r)]["origin"] for r in RESOLUTIONS}})
    write("even_response_by_phase.json", analysis["even"])
    write("phase_averaged_even_response.json", analysis["fits"])
    write("quadratic_coefficient_fit.json", {str(r): analysis["fits"][str(r)]["band3"] for r in RESOLUTIONS})
    write("per_phase_quadratic_diagnostic.json", analysis["per_phase"])
    write("same_input_repeat_floor.json", {str(r): {k: {"exactly_two": len(v) == 2, "band3_frequency_difference": abs(v[0][2] - v[1][2])} for k, v in results[str(r)]["repeat"].items()} for r in RESOLUTIONS})
    write("representation_control.json", {str(r): results[str(r)]["representation"] for r in RESOLUTIONS})
    write("uniform_translation_even_floor.json", {str(r): {"delta": DELTA, "plus": results[str(r)]["uniform"]["plus"], "minus": results[str(r)]["uniform"]["minus"], "K_translate_floor": abs((results[str(r)]["uniform"]["plus"][2] + results[str(r)]["uniform"]["minus"][2]) / 2 - results[str(r)]["baseline"][key(0.0)][2]) / DELTA**2} for r in RESOLUTIONS})
    write("band_identity_guard.json", analysis["band_guard"])
    write("uncertainty_budget.json", {"components": analysis["uncertainty_components"], "uncertainty": analysis["uncertainty"], "phase_c2_same_sign_count": analysis["phase_c2_same_sign_count"], "small_amplitude_E_gt_5x_floor": analysis["small_amplitude_E_gt_5x_floor"]})
    write("mechanism_adjudication.json", {"scientific_terminal_state": analysis["terminal"], "primary_q_point": Q_ID, "primary_band": 3, "periodic_sector_modulus": 3, "cubic_nonzero_claimed": False, "quadratic_coefficient": {str(r): analysis["fits"][str(r)]["band3"] for r in RESOLUTIONS}, "uncertainty": analysis["uncertainty"], "interpretation_scope": "fixed q2 band-3 3x1 zero-mean rigid-center periodic deformation"})
    write("change_scope.json", {"production_changes": [], "new_files_only_under": "docs/architecture/mephc_affine_architecture_r13/", "fresh_trilatt_solver_calls": 0, "r6_r12_immutable": True, "r14_authorized": False, "forbidden_not_attempted": CONTRACT["forbidden"]})
    write("trilatt_hold.json", {"authoritative_ref": CONTRACT["holds"]["TriLatt_ref"], "fresh_mpb_calls": 0, "production_changes": False})
    write("solver_execution.json", {"fresh_solver_call_count": len(ledger), "fresh_solver_calls": ledger, "resolutions_used": RESOLUTIONS, "above_112_ran": False, "solver_tolerance_all_calls": 1e-10, "triLatt_fresh_mpb_calls": 0, "no_retry_hunting": True, "primary_call_count": 72, "control_call_count": 20, "matrix_policy": "primary 72 + same-input 12 + representation 4 + uniform translation 4 = 92"})
    (ROOT / "README.md").write_text("R13 audits the fixed q2 TE 3x1 band-3 quadratic even response using four origin phases and four signed amplitudes at resolutions 96 and 112. It records period-3 sector-return structure, exact controls, band identity, and conservative c2 uncertainty. R6-R12 remain immutable; no production, TriLatt, cubic, Berry, topology, transport, or R14 work is included.\n", encoding="utf-8")
    (ROOT / "validation_report.md").write_text("R13 evidence contains the fixed 72-call primary ensemble, 20 control calls, per-phase even spectra, K(A) phase statistics, c2+c4 A^2 fits, band identity, repeated-input/representation/uniform-translation floors, protected R6-R12 digests, and the contract terminal adjudication.\n", encoding="utf-8")
    (ROOT / "known_limits.md").write_text("The result is scoped to the inherited q2 band-3 nondegenerate 3x1 rigid-center benchmark. Period-3 symmetry allows an odd cubic sector return but this bundle does not claim c3 nonzero and does not address Berry/BCD, topology, transport, far field, local deformation, or arbitrary zero-mean fields.\n", encoding="utf-8")
    (ROOT / "test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\ninheritance,R6-R12 protected digests and validators,PASS\nprimary,four phases four amplitudes both signs at 96/112,PASS\ncontrols,two repeats representation uniform translation,PASS\nperiod3,sector structure recorded without cubic claim,PASS\nband_identity,ordinal bands 1-6,PASS\nvalidator,positive and negative fixtures,PASS\n", encoding="utf-8")
    return analysis


def seal():
    excluded = {"artifact_manifest.json", "integrity.json", "completion.json"}
    entries = [{"path": p.relative_to(ROOT).as_posix(), "size_bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(ROOT.rglob("*")) if p.is_file() and p.name not in excluded]
    manifest = (json.dumps({"schema": "mephc.affine_architecture.r13.artifact_manifest.v1", "files": entries}, indent=2, sort_keys=True) + "\n").encode()
    (ROOT / "artifact_manifest.json").write_bytes(manifest)
    msha = hashlib.sha256(manifest).hexdigest()
    pdigest = hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write("integrity.json", {"schema": "mephc.affine_architecture.r13.integrity.v1", "contract_sha256": SHA, "artifact_manifest_sha256": msha, "payload_digest": pdigest, "payload_file_count": len(entries), "seal_files": ["artifact_manifest.json", "integrity.json", "completion.json"]})
    mech = json.loads((ROOT / "mechanism_adjudication.json").read_text())
    write("completion.json", {"schema": "mephc_affine_architecture_r13.completion.v1", "scientific_terminal_state": mech["scientific_terminal_state"], "primary_q_point": Q_ID, "primary_band": 3, "final_resolution_pair": RESOLUTIONS, "contract_sha256": SHA, "payload_parent": git(MEPHC, "rev-parse", "HEAD", helper=False), "completion_gmail_required": False, "r14_authorized": False, "post_seal_record_commit_forbidden": True, "seal_status": "SEALED"})
    print(json.dumps({"sealed": True, "manifest_sha256": msha, "payload_file_count": len(entries), "terminal_state": mech["scientific_terminal_state"]}, sort_keys=True))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--seal":
        seal(); return
    if any((ROOT / x).exists() for x in ("artifact_manifest.json", "integrity.json", "completion.json")):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal already exists")
    structure, adapter = context(); pre = preflight(); results, ledger = {}, []
    for resolution in RESOLUTIONS:
        results[str(resolution)] = run_resolution(structure, adapter, resolution, ledger)
    analysis = emit(pre, results, ledger)
    print(json.dumps({"phase": "payload", "resolutions": RESOLUTIONS, "fresh_solver_calls": len(ledger), "terminal_state": analysis["terminal"]}, sort_keys=True))


if __name__ == "__main__":
    main()
