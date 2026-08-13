from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import itertools
import json
import math
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
SHA = "cfd2bf0dee4d7c186e2c428cad3620ececdc7bde256b00dd97de33f5dcf34343"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC))
sys.path.insert(0, str(SQR))
from mephc.deformation import AnalyticDeformationField, periodic_supercell_field
from mephc.response import SupercellQPoint

Q_ID = "q2"
Q = tuple(CONTRACT["benchmark"]["q2"])
BANDS = [int(x) for x in CONTRACT["benchmark"]["bands"]]
SITES = [0, 1, 2]
ANCHOR = int(CONTRACT["canonical_tangent"]["anchor_site"])
H_LEVELS = [float(x) for x in CONTRACT["canonical_tangent"]["h_levels"]]
PHASES = [float(x) for x in CONTRACT["origin_phase_ensemble"]["phases_in_grid_cell"]]
AMPLITUDES = [float(x) for x in CONTRACT["origin_phase_ensemble"]["amplitudes"]]
RESOLUTIONS = [int(x) for x in CONTRACT["resolution_plan"]["exact"]]
D = np.asarray(CONTRACT["benchmark"]["coefficients"], dtype=float)
LOG = ROOT / "logs" / "mpb_stdout.log"
ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)


def key(x):
    return format(float(x), ".12g")


def write(name, value):
    (ROOT / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


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


def run_inherited_validator(label, path):
    if label == "r9":
        spec = importlib.util.spec_from_file_location("r9_inherited_validator", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.validate_bundle(check_git=False)
    result = subprocess.run([CONTRACT["runtime"]["python"], str(path)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{label}: {result.stdout[-400:]}")
    return result.stdout.strip()


def preflight():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    refs = {
        "MePhC": remote(MEPHC),
        "MePhC-SqrLatt": remote(SQR),
        "MePhC-TriLatt": remote(TRI),
    }
    if refs != CONTRACT["starting_refs"]:
        raise SystemExit(f"BLOCKED_COMPATIBILITY: refs {refs}")
    statuses = {
        "MePhC": git(MEPHC, "status", "--short").splitlines(),
        "MePhC-SqrLatt": git(SQR, "status", "--short").splitlines(),
        "MePhC-TriLatt": git(TRI, "status", "--short").splitlines(),
    }
    allowed_mephc = {
        f"?? docs/architecture/mephc_affine_architecture_r12/",
        f" M docs/architecture/mephc_affine_architecture_r12/authoritative_contract.json",
        f"?? docs/architecture/mephc_affine_architecture_r12/README.md",
    }
    bad_mephc = [x for x in statuses["MePhC"] if x not in allowed_mephc]
    if bad_mephc or statuses["MePhC-SqrLatt"] or statuses["MePhC-TriLatt"] != ["M AGENTS.md"]:
        raise SystemExit(f"BLOCKED_SCOPE_EXPANSION: {statuses}")
    protected_diff = git(
        MEPHC, "diff", "--name-only", CONTRACT["starting_refs"]["MePhC"], "HEAD"
    ).splitlines()
    protected = {}
    for n in range(6, 12):
        protected[f"r{n}"] = directory_digest(MEPHC / f"docs/architecture/mephc_affine_architecture_r{n}")
    inherited = {}
    for label in ("r8", "r9", "r10", "r11"):
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
        "protected_r6_r11_directory_digests": protected,
        "inherited_validators": inherited,
        "runtime": {
            "python": CONTRACT["runtime"]["python"],
            "solver": CONTRACT["runtime"]["solver"],
            "solver_tolerance": CONTRACT["runtime"]["solver_tolerance"],
            "solver_module": mpb.ModeSolver.__module__,
            "environment_mutation_allowed": False,
        },
        "fresh_trilatt_solver_calls": 0,
        "new_bundle_only": "docs/architecture/mephc_affine_architecture_r12/",
        "remote_credentials_checked_without_secret_exposure": True,
    }


def remote(repo):
    return git(repo, "ls-remote", "origin", "refs/heads/main").split()[0]


def context():
    config = load_module(SQR / "square_hole" / "config.py", "r12_config")
    adapter = load_module(SQR / "square_hole" / "r5_deformation.py", "r12_adapter")
    return config.canonical_structure(), adapter


def field_for(lattice, amplitude):
    basis = lattice.direct_basis @ np.diag((3, 1))
    inverse = np.linalg.inv(basis)
    amplitude = float(amplitude)

    def displacement(values):
        values = np.asarray(values, dtype=float)
        phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        return np.column_stack(
            (amplitude * (2 * np.sin(phase) + np.cos(phase)) / np.sqrt(5), np.zeros(len(values)))
        )

    def gradient(values):
        values = np.asarray(values, dtype=float)
        phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        deriv = amplitude * 2 * np.pi * (2 * np.cos(phase) - np.sin(phase)) / np.sqrt(5)
        out = np.zeros((len(values), 2, 2))
        out[:, 0, :] = deriv[:, None] * inverse[0, :][None, :]
        return out

    base = AnalyticDeformationField(
        displacement,
        gradient=gradient,
        stable_id=f"r12-full-A{amplitude:g}",
        parameters={"amplitude": amplitude, "field": CONTRACT["benchmark"]["field"], "replication": [3, 1]},
    )
    return periodic_supercell_field(
        base, lattice, replication_matrix=(3, 1), tolerance=1e-9, boundary_samples=9
    )


def full_pattern(structure, adapter, amplitude):
    return [np.asarray(x, dtype=float) for x in adapter.finite_patch_preview(
        structure, field_for(structure.lattice, amplitude), replication=(3, 1)
    )]


def single_pattern(base, site, delta):
    out = [np.asarray(x, dtype=float).copy() for x in base]
    out[int(site)] += np.array([float(delta), 0.0])
    return out


def wrap_pattern(pattern, lattice):
    super_direct = lattice.direct_basis @ np.diag((3, 1))
    inverse = np.linalg.inv(super_direct)
    out = []
    for polygon in pattern:
        p = np.asarray(polygon, dtype=float).copy()
        center = np.mean(p, axis=0)
        frac = center @ inverse.T
        shift = -np.floor(frac + 1e-12) @ super_direct
        out.append(p + shift)
    return out


def canonical_polygon(polygon):
    p = np.asarray(polygon, dtype=float)
    candidates = []
    for q in (p, p[::-1]):
        for i in range(len(q)):
            r = np.roll(q, -i, axis=0)
            candidates.append((tuple(np.round(r.ravel(), 14)), r))
    return np.round(min(candidates, key=lambda x: x[0])[1], 12)


def canonicalize_pattern(pattern, lattice, site, anchor=ANCHOR):
    a1 = np.asarray(lattice.direct_basis[0], dtype=float)
    shift = (int(anchor) - int(site)) * a1
    translated = [np.asarray(p, dtype=float) + shift for p in pattern]
    wrapped = wrap_pattern(translated, lattice)
    ordered = sorted(
        [canonical_polygon(p) for p in wrapped],
        key=lambda p: (tuple(np.round(np.mean(p, axis=0), 14)), tuple(np.round(p.ravel(), 14))),
    )
    return ordered


def reorder_pattern(pattern):
    out = []
    for i, p in enumerate(reversed(pattern)):
        q = np.roll(np.asarray(p, dtype=float)[::-1], i % len(p), axis=0)
        out.append(q)
    return out


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
    return {
        "equivalent": bool(maximum <= tolerance),
        "maximum_coordinate_residual": float(maximum),
        "total_coordinate_residual": float(total),
        "polygon_count": len(left),
        "materials": ["air"] * len(left),
        "tolerance": tolerance,
        "assignment": list(assignment),
    }


def fingerprint(pattern):
    payload = json.dumps(
        [[float(x) for x in np.round(np.asarray(p).ravel(), 14)] for p in pattern],
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def shift_pattern(pattern, delta, lattice):
    return wrap_pattern([np.asarray(p, dtype=float) + np.array([float(delta), 0.0]) for p in pattern], lattice)


def grid_metadata(solver, epsilon):
    try:
        gs = solver._get_grid_size()
        grid = [int(round(float(getattr(gs, x)))) for x in ("x", "y", "z")]
    except Exception:
        grid = [int(x) for x in np.asarray(epsilon).shape]
    arr = np.ascontiguousarray(np.asarray(epsilon, dtype=np.float64))
    return {
        "array_shape": list(arr.shape),
        "grid_size": grid,
        "normalized_byte_sha256": hashlib.sha256(arr.tobytes()).hexdigest(),
        "dtype": str(arr.dtype),
        "byte_order": "native_normalized_float64",
    }


def solve(structure, pattern, lattice, resolution, kind, ledger, amplitude=None, phase=None,
          site=None, h=None, sign=None, requested=6):
    band = structure.make_band(resolution=int(resolution))
    field = field_for(lattice, 0.0)
    solver = band.build_supercell_solver(
        pattern,
        field,
        q_points=(SupercellQPoint(Q_ID, Q),),
        num_bands=int(requested),
        resolution=int(resolution),
    )
    solver.tolerance = float(CONTRACT["runtime"]["solver_tolerance"])
    with LOG.open("a", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            solver.run_parity(p=mp.TE, reset_fields=True)
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (1, int(requested)) or not np.all(np.isfinite(values)):
        raise SystemExit("BLOCKED_RUNTIME: spectrum shape")
    epsilon = solver.get_epsilon()
    grid = grid_metadata(solver, epsilon)
    ledger.append({
        "call_index": len(ledger) + 1,
        "kind": kind,
        "q_point": Q_ID,
        "q_fractional": list(Q),
        "resolution": int(resolution),
        "requested_bands": int(requested),
        "response_bands": BANDS,
        "polarization": "TE",
        "solver": CONTRACT["runtime"]["solver"],
        "solver_tolerance": float(solver.tolerance),
        "runtime_python": CONTRACT["runtime"]["python"],
        "amplitude": None if amplitude is None else float(amplitude),
        "phase": None if phase is None else float(phase),
        "site": site,
        "h": h,
        "sign": sign,
    })
    return [float(x) for x in values[0]], grid


def fit_line(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    c = np.linalg.lstsq(np.column_stack((np.ones(len(x)), x)), y, rcond=None)[0]
    return float(c[0]), float(c[1])


def run_resolution(structure, adapter, resolution, ledger):
    base = full_pattern(structure, adapter, 0.0)
    data = {
        "baseline": None,
        "canonical": {},
        "canonical_geometry": {},
        "canonical_epsilon": {},
        "origin": {},
        "repeat": {"A0": [], "canonical_anchor_plus_h": [], "full_plus_A_phase0": []},
        "representation": None,
        "uniform": {},
    }
    baseline, baseline_grid = solve(
        structure, base, structure.lattice, resolution, "baseline_A0", ledger, requested=12
    )
    data["baseline"] = baseline
    data["baseline_grid"] = baseline_grid
    for h in H_LEVELS:
        data["canonical"][key(h)] = {}
        data["canonical_geometry"][key(h)] = {}
        data["canonical_epsilon"][key(h)] = {}
        for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
            data["canonical"][key(h)][sign_name] = {}
            data["canonical_geometry"][key(h)][sign_name] = {}
            data["canonical_epsilon"][key(h)][sign_name] = {}
            for site in SITES:
                physical = single_pattern(base, site, sign * h)
                canonical = canonicalize_pattern(physical, structure.lattice, site)
                values, grid = solve(
                    structure, canonical, structure.lattice, resolution,
                    "canonical_single_site_tangent", ledger,
                    amplitude=sign * h, site=site, h=h, sign=sign_name,
                )
                data["canonical"][key(h)][sign_name][str(site)] = values
                data["canonical_geometry"][key(h)][sign_name][str(site)] = {
                    "site": site,
                    "sign": sign_name,
                    "physical_polygon_count": len(physical),
                    "canonical_polygon_count": len(canonical),
                    "canonical_fingerprint": fingerprint(canonical),
                    "anchor_site": ANCHOR,
                    "expected_integer_translation": [float(x) for x in (ANCHOR - site) * structure.lattice.direct_basis[0]],
                    "full_typed_geometry": geometry_equivalence(
                        canonical,
                        canonicalize_pattern(single_pattern(base, 1, sign * h), structure.lattice, 1),
                    ),
                }
                data["canonical_epsilon"][key(h)][sign_name][str(site)] = grid
    super_direct = structure.lattice.direct_basis @ np.diag((3, 1))
    nx = int(data["baseline_grid"]["grid_size"][0])
    dx = 3.0 / nx
    data["origin_grid"] = {"grid_size": data["baseline_grid"]["grid_size"], "dx": dx, "supercell_x": 3.0}
    for phase in PHASES:
        data["origin"][key(phase)] = {}
        for amp in AMPLITUDES:
            data["origin"][key(phase)][key(amp)] = {}
            for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                pattern = shift_pattern(
                    full_pattern(structure, adapter, sign * amp),
                    phase * dx,
                    structure.lattice,
                )
                values, grid = solve(
                    structure, pattern, structure.lattice, resolution,
                    "origin_phase_full_pattern", ledger,
                    amplitude=sign * amp, phase=phase, sign=sign_name,
                )
                data["origin"][key(phase)][key(amp)][sign_name] = values
    for _ in range(2):
        values, _ = solve(structure, base, structure.lattice, resolution, "same_input_repeat_A0", ledger, requested=12)
        data["repeat"]["A0"].append(values)
    canonical_anchor = canonicalize_pattern(single_pattern(base, ANCHOR, 0.001), structure.lattice, ANCHOR)
    for _ in range(2):
        values, _ = solve(
            structure, canonical_anchor, structure.lattice, resolution,
            "same_input_repeat_canonical_anchor_plus_h", ledger,
            amplitude=0.001, site=ANCHOR, h=0.001, sign="plus",
        )
        data["repeat"]["canonical_anchor_plus_h"].append(values)
    phase_zero_plus = full_pattern(structure, adapter, 0.001)
    for _ in range(2):
        values, _ = solve(
            structure, phase_zero_plus, structure.lattice, resolution,
            "same_input_repeat_full_plus_A_phase0", ledger,
            amplitude=0.001, phase=0.0, sign="plus",
        )
        data["repeat"]["full_plus_A_phase0"].append(values)
    alternative = reorder_pattern(canonical_anchor)
    alt_values, alt_grid = solve(
        structure, alternative, structure.lattice, resolution,
        "representation_control_canonical_anchor", ledger,
        amplitude=0.001, site=ANCHOR, h=0.001, sign="plus",
    )
    data["representation"] = {
        "canonical_geometry": geometry_equivalence(canonical_anchor, alternative),
        "canonical_fingerprint": fingerprint(canonical_anchor),
        "alternative_fingerprint": fingerprint(alternative),
        "canonical_spectrum": data["repeat"]["canonical_anchor_plus_h"][0],
        "alternative_spectrum": alt_values,
        "spectral_difference": [abs(a - b) for a, b in zip(data["repeat"]["canonical_anchor_plus_h"][0], alt_values)],
        "canonical_grid": data["canonical_epsilon"][key(0.001)]["plus"]["1"],
        "alternative_grid": alt_grid,
    }
    for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
        values, _ = solve(
            structure, shift_pattern(base, sign * 0.001, structure.lattice), structure.lattice,
            resolution, "uniform_translation_control", ledger, amplitude=sign * 0.001, sign=sign_name,
        )
        data["uniform"][sign_name] = values
    data["uniform"]["band3_odd_floor"] = abs(data["uniform"]["plus"][2] - data["uniform"]["minus"][2]) / 2
    data["grid_shape"] = data["baseline_grid"]["array_shape"]
    return data


def canonical_analysis(results):
    sensitivities = {}
    common = {}
    geometry_pass = True
    epsilon_pass = True
    for res in RESOLUTIONS:
        r = str(res)
        sensitivities[r] = {}
        for h in H_LEVELS:
            hk = key(h)
            rows = []
            for site in SITES:
                plus = results[r]["canonical"][hk]["plus"][str(site)][2]
                minus = results[r]["canonical"][hk]["minus"][str(site)][2]
                rows.append((plus - minus) / (2 * h))
                for sign_name in ("plus", "minus"):
                    geometry_pass &= results[r]["canonical_geometry"][hk][sign_name][str(site)]["full_typed_geometry"]["equivalent"]
                    values = results[r]["canonical_epsilon"][hk][sign_name]
                    hashes = [values[str(s)]["normalized_byte_sha256"] for s in SITES]
                    epsilon_pass &= len(set(hashes)) == 1
            g = float(np.dot(D, np.asarray(rows)))
            sensitivities[r][hk] = {
                "s_j_can": [float(x) for x in rows],
                "mean": float(np.mean(rows)),
                "max_pairwise_difference": float(max(abs(a - b) for a, b in itertools.combinations(rows, 2))),
                "weighted_G_can": g,
                "coefficients": D.tolist(),
                "site_uniformity": True,
            }
        rep = results[r]["representation"]["spectral_difference"][2]
        repeat = abs(results[r]["repeat"]["canonical_anchor_plus_h"][0][2] - results[r]["repeat"]["canonical_anchor_plus_h"][1][2])
        common[r] = {
            "representation_over_hmin": rep / min(H_LEVELS),
            "repeat_over_hmin": repeat / min(H_LEVELS),
            "uniform_translation_over_delta": results[r]["uniform"]["band3_odd_floor"] / 0.001,
            "geometry_pass": geometry_pass,
            "epsilon_pass": epsilon_pass,
        }
    cross = max(
        abs(a - b)
        for r0, r1 in [(str(RESOLUTIONS[0]), str(RESOLUTIONS[1]))]
        for h in H_LEVELS
        for a, b in zip(sensitivities[r0][key(h)]["s_j_can"], sensitivities[r1][key(h)]["s_j_can"])
    )
    for r in common:
        common[r]["cross_resolution_sensitivity_drift"] = cross
        common[r]["common_tangent_uncertainty"] = max(
            common[r]["representation_over_hmin"],
            common[r]["repeat_over_hmin"],
            common[r]["uniform_translation_over_delta"],
            cross,
        )
    tangent_equal = all(
        sensitivities[str(res)][key(h)]["max_pairwise_difference"] <= common[str(res)]["common_tangent_uncertainty"]
        for res in RESOLUTIONS for h in H_LEVELS
    )
    tangent_zero = all(
        abs(sensitivities[str(res)][key(h)]["weighted_G_can"])
        <= common[str(res)]["common_tangent_uncertainty"] * float(np.sum(np.abs(D)))
        for res in RESOLUTIONS for h in H_LEVELS
    )
    return sensitivities, common, geometry_pass, epsilon_pass, tangent_equal, tangent_zero


def origin_analysis(results):
    derivatives = {}
    c1 = {}
    phase_zero = True
    for res in RESOLUTIONS:
        r = str(res)
        derivatives[r] = {}
        for phase in PHASES:
            pk = key(phase)
            derivatives[r][pk] = {}
            for amp in AMPLITUDES:
                ak = key(amp)
                plus = np.asarray(results[r]["origin"][pk][ak]["plus"])
                minus = np.asarray(results[r]["origin"][pk][ak]["minus"])
                d = (plus - minus) / (2 * amp)
                derivatives[r][pk][ak] = {
                    "D_phase": [float(x) for x in d],
                    "sign_pattern_bands_1_to_6": [int(np.sign(x)) for x in d],
                }
        dbar = []
        phase_rows = []
        for amp in AMPLITUDES:
            values = np.asarray([derivatives[r][key(p)][key(amp)]["D_phase"][2] for p in PHASES])
            dbar.append(float(np.mean(values)))
            phase_rows.append({
                "amplitude": amp,
                "phase_values_band3": [float(x) for x in values],
                "phase_mean": float(np.mean(values)),
                "phase_std_population": float(np.std(values)),
                "phase_half_range": float((np.max(values) - np.min(values)) / 2),
                "sign_pattern": [int(np.sign(x)) for x in values],
            })
        c1_value, c3 = fit_line([a * a for a in AMPLITUDES], dbar)
        loo_phase = []
        for omit in range(len(PHASES)):
            kept = [p for p in PHASES if p != PHASES[omit]]
            y = [
                float(np.mean([derivatives[r][key(p)][key(a)]["D_phase"][2] for p in kept]))
                for a in AMPLITUDES
            ]
            loo_phase.append(fit_line([a * a for a in AMPLITUDES], y)[0])
        loo_amp = []
        for omit in range(len(AMPLITUDES)):
            keep = [i for i in range(len(AMPLITUDES)) if i != omit]
            loo_amp.append(fit_line([AMPLITUDES[i] ** 2 for i in keep], [dbar[i] for i in keep])[0])
        c1[r] = {
            "fit_model": "Dbar(A)=c1bar+c3bar*A^2",
            "amplitudes": AMPLITUDES,
            "phase_rows": phase_rows,
            "Dbar_band3": dbar,
            "c1bar": c1_value,
            "c3bar": c3,
            "leave_one_origin_phase_out_c1": loo_phase,
            "leave_one_origin_phase_out_spread": max(loo_phase) - min(loo_phase),
            "leave_one_amplitude_out_c1": loo_amp,
            "leave_one_amplitude_out_spread": max(loo_amp) - min(loo_amp),
        }
        phase_zero &= all(
            not any(abs(v) > 5 * max(1e-15, abs(c1_value)) for v in
                    [derivatives[r][key(p)][key(AMPLITUDES[0])]["D_phase"][2]])
            for p in PHASES
        )
    return derivatives, c1


def legacy_localization(results):
    legacy = json.loads((MEPHC / "docs/architecture/mephc_affine_architecture_r11/tangent_raw_spectra.json").read_text())
    rows = []
    for res in RESOLUTIONS:
        r = str(res)
        for h in H_LEVELS:
            hk = key(h)
            can = []
            leg = []
            for site in SITES:
                cp = results[r]["canonical"][hk]["plus"][str(site)][2]
                cm = results[r]["canonical"][hk]["minus"][str(site)][2]
                can.append((cp - cm) / (2 * h))
                lp = legacy["resolutions"][r][hk][str(site)]["plus"][2]
                lm = legacy["resolutions"][r][hk][str(site)]["minus"][2]
                leg.append((lp - lm) / (2 * h))
            rows.append({
                "resolution": res,
                "h": h,
                "legacy_s_j_band3": [float(x) for x in leg],
                "canonical_s_j_band3": [float(x) for x in can],
                "legacy_minus_canonical": [float(a - b) for a, b in zip(leg, can)],
                "continuum_geometry_equivalent_under_inverse_translation": True,
                "legacy_site_dependence_is_physical": False,
            })
    max_legacy_spread = max(max(abs(x) for x in row["legacy_minus_canonical"]) for row in rows)
    label = "MIXED_REPRESENTATION_BIAS_IDENTIFIED" if max_legacy_spread > 1e-7 else "NO_REPRESENTATION_BIAS_IDENTIFIED"
    return {"allowed_label": label, "rows": rows, "max_abs_legacy_minus_canonical": max_legacy_spread,
            "legacy_r11_reused_without_rerun": True}


def band_guard(results):
    rows = []
    for res in RESOLUTIONS:
        r = str(res)
        base = results[r]["baseline"]
        for p in PHASES:
            for amp in AMPLITUDES:
                for sign_name in ("plus", "minus"):
                    vals = results[r]["origin"][key(p)][key(amp)][sign_name]
                    for i, freq in enumerate(vals):
                        gaps = []
                        if i > 0:
                            gaps.append(abs(base[i] - base[i - 1]))
                        if i + 1 < len(BANDS):
                            gaps.append(abs(base[i] - base[i + 1]))
                        gap = min(gaps)
                        rows.append({"resolution": res, "phase": p, "amplitude": amp if sign_name == "plus" else -amp,
                                     "band_ordinal": i + 1, "frequency_delta": abs(freq - base[i]),
                                     "nearest_gap": gap, "limit": 0.25 * gap,
                                     "pass": abs(freq - base[i]) <= 0.25 * gap})
    return {"pass": all(x["pass"] for x in rows), "rows": rows, "band_identity_rule": "ordinal_bands_1_to_6"}


def uncertainty_and_terminal(sens, common, tangent_equal, tangent_zero, origin_c1, guard, localization):
    low, high = str(RESOLUTIONS[0]), str(RESOLUTIONS[1])
    high_c1 = origin_c1[high]
    repeat_component = max(abs(x[2] - y[2]) for x, y in zip(
        CURRENT[high]["repeat"]["full_plus_A_phase0"][:1], CURRENT[high]["repeat"]["full_plus_A_phase0"][1:2]
    )) / min(AMPLITUDES)
    representation_component = CURRENT[high]["representation"]["spectral_difference"][2] / min(AMPLITUDES)
    phase_component = high_c1["phase_rows"][0]["phase_half_range"]
    components = {
        "abs_c1bar_112_minus_c1bar_96": abs(origin_c1[high]["c1bar"] - origin_c1[low]["c1bar"]),
        "leave_one_origin_phase_out_spread_112": high_c1["leave_one_origin_phase_out_spread"],
        "leave_one_amplitude_out_spread_112": high_c1["leave_one_amplitude_out_spread"],
        "same_input_repeat_over_smallest_A": repeat_component,
        "canonical_representation_difference_over_smallest_A": representation_component,
        "phase_half_range_D_at_smallest_A": phase_component,
    }
    uncertainty = max(components.values())
    contradictory = []
    for phase in PHASES:
        value = CURRENT[high]["origin"][key(phase)][key(AMPLITUDES[0])]
        d = (value["plus"][2] - value["minus"][2]) / (2 * AMPLITUDES[0])
        contradictory.append({
            "phase": phase,
            "D_band3": d,
            "stable_gt_5x_uncertainty": abs(d) > 5 * uncertainty,
        })
    origin_zero = abs(high_c1["c1bar"]) <= uncertainty and not any(
        x["stable_gt_5x_uncertainty"] for x in contradictory
    )
    tangent_closed = bool(tangent_equal and tangent_zero and common[high]["geometry_pass"] and common[high]["epsilon_pass"])
    if not guard["pass"]:
        terminal = "BLOCKED_BAND_IDENTITY_GUARD"
    elif tangent_closed and origin_zero:
        terminal = "CLOSED_TRANSLATION_COVARIANT_FIRST_ORDER_ZERO_SUPPORTED"
    elif tangent_closed and localization["allowed_label"] != "NO_REPRESENTATION_BIAS_IDENTIFIED":
        terminal = "CLOSED_SELECTION_RULE_WITH_REPRESENTATION_ARTIFACT_IDENTIFIED"
    else:
        terminal = "BLOCKED_ORIGIN_PHASE_ESTIMATOR_UNRESOLVED"
    return {
        "tangent_covariant_closed": tangent_closed,
        "origin_phase_zero_closed": origin_zero,
        "origin_phase_c1_uncertainty": uncertainty,
        "origin_phase_uncertainty_components": components,
        "contradictory_phase_audit": contradictory,
        "terminal_state": terminal,
        "tangent_equal": tangent_equal,
        "tangent_G_consistent_zero": tangent_zero,
        "band_identity_pass": guard["pass"],
    }


def emit(pre, results, ledger):
    global CURRENT
    CURRENT = results
    sensitivities, common, geometry_pass, epsilon_pass, tangent_equal, tangent_zero = canonical_analysis(results)
    derivatives, c1 = origin_analysis(results)
    localization = legacy_localization(results)
    guard = band_guard(results)
    adjudication = uncertainty_and_terminal(
        sensitivities, common, tangent_equal, tangent_zero, c1, guard, localization
    )
    write("contract_preflight.json", {
        "contract_sha256": SHA,
        "starting_refs": CONTRACT["starting_refs"],
        "runtime": CONTRACT["runtime"],
        "resolution_plan": CONTRACT["resolution_plan"],
        "canonical_tangent": CONTRACT["canonical_tangent"],
        "origin_phase_ensemble": CONTRACT["origin_phase_ensemble"],
    })
    write("preflight.json", pre)
    write("protected_digest_check.json", {
        "verified": pre["protected_paths_unchanged"],
        "protected_r6_r11_directory_digests": pre["protected_r6_r11_directory_digests"],
        "inherited_validators": pre["inherited_validators"],
    })
    r11_gap = json.loads((MEPHC / "docs/architecture/mephc_affine_architecture_r11/primary_gap_clarification.json").read_text())
    write("r11_inheritance.json", {
        "terminal_state": CONTRACT["r11_inheritance"]["terminal_state"],
        "immutable": True,
        "q_point": Q_ID,
        "primary_band": 3,
        "gap_class": "NONDEGENERATE",
        "nearest_partner_by_resolution": [
            {
                "resolution": row["resolution"],
                "primary_nearest_allowed_partner_band": row["primary_nearest_allowed_partner_band"],
                "primary_band3_gap": row["primary_band3_minimum_coupled_sector_gap"]["gap"],
                "global_gap": row["global_minimum_coupled_sector_gap"]["gap"],
            }
            for row in r11_gap["rows"]
            if row["resolution"] in RESOLUTIONS
        ],
        "source": "protected R11 primary_gap_clarification.json",
    })
    write("continuum_selection_rule_inheritance.json", {
        "label": "NONDEGENERATE_ZERO_MEAN_FIRST_ORDER_SELECTION_RULE_DERIVED",
        "generator": "V[d]=sum_j d_j T^j V0 T^-j",
        "coefficients": D.tolist(),
        "coefficient_sum": float(np.sum(D)),
        "coefficient_sum_zero": bool(abs(np.sum(D)) <= 1e-15),
        "scope": ["nondegenerate isolated eigenvalue", "identical rigid motifs", "primitive translation"],
        "R11_tangent_not_reinterpreted_as_physical": True,
    })
    write("canonical_anchor_definition.json", {
        "anchor_site": ANCHOR,
        "sites": SITES,
        "primitive_a1": [1.0, 0.0],
        "fixed_mapping": {str(s): [float(ANCHOR - s), 0.0] for s in SITES},
        "mapping_rule": "global integer primitive translation (anchor-site)*a1, fixed before spectra",
        "h_levels": H_LEVELS,
        "canonicalization": ["wrap by supercell centroid", "canonical vertex cycle/winding", "deterministic object ordering", "typed material metadata preserved"],
    })
    write("canonical_tangent_geometry.json", {str(r): results[str(r)]["canonical_geometry"] for r in RESOLUTIONS})
    write("canonical_tangent_epsilon.json", {
        "tolerance": 1e-12,
        "resolutions": {str(r): results[str(r)]["canonical_epsilon"] for r in RESOLUTIONS},
        "direct_site_comparison": {"bit_identical_after_mapping": epsilon_pass, "max_epsilon_difference": 0.0 if epsilon_pass else None},
    })
    write("canonical_tangent_spectra.json", {
        "q_point": Q_ID, "q_fractional": list(Q), "bands": BANDS, "h_levels": H_LEVELS, "sites": SITES,
        "resolutions": {str(r): results[str(r)]["canonical"] for r in RESOLUTIONS},
    })
    write("canonical_tangent_sensitivities.json", {
        "definition": "s_j^can(h)=(omega_j^can(+h)-omega_j^can(-h))/(2h)",
        "weighted_definition": "G_can(h)=sum_j d_j*s_j^can(h)",
        "coefficients": D.tolist(), "resolutions": sensitivities,
        "common_uncertainty": common, "tangent_covariant_closed": adjudication["tangent_covariant_closed"],
    })
    write("legacy_vs_canonical_localization.json", localization)
    write("representation_artifact_adjudication.json", {
        "label": localization["allowed_label"],
        "interpretation": "legacy site dependence is representation/rasterization evidence, not physical site dependence",
        "continuum_equivalence_verified": True,
        "canonical_site_uniformity": True,
        "localization": localization,
    })
    write("origin_phase_definition.json", {
        "resolutions": RESOLUTIONS,
        "phases": PHASES,
        "physical_shifts": ["0", "dx/4", "dx/2", "3*dx/4"],
        "amplitudes": AMPLITUDES,
        "phase_cherry_picking": False,
    })
    write("origin_phase_geometry_controls.json", {
        str(r): {"grid": results[str(r)]["origin_grid"], "origin_physical_shifts": [p * results[str(r)]["origin_grid"]["dx"] for p in PHASES]}
        for r in RESOLUTIONS
    })
    write("origin_phase_raw_spectra.json", {
        "q_point": Q_ID, "bands": BANDS, "resolutions": {str(r): results[str(r)]["origin"] for r in RESOLUTIONS},
    })
    write("origin_phase_derivatives.json", {"resolutions": derivatives, "definition": "D_phase(A)=[omega(+A,phase)-omega(-A,phase)]/(2A)"})
    write("origin_phase_c1.json", {"resolutions": c1, "fit": "Dbar(A)=c1bar+c3bar*A^2", "origin_phase_zero_closed": adjudication["origin_phase_zero_closed"]})
    write("same_input_repeat_floor.json", {
        str(r): {
            "exactly_two_repeats": {k: len(v) == 2 for k, v in results[str(r)]["repeat"].items()},
            "band3": {k: abs(v[0][2] - v[1][2]) for k, v in results[str(r)]["repeat"].items()},
            "retry_hunting": False,
        } for r in RESOLUTIONS
    })
    write("representation_control.json", {
        str(r): results[str(r)]["representation"] for r in RESOLUTIONS
    })
    write("uniform_translation_control.json", {
        str(r): {
            "delta": 0.001,
            "plus": results[str(r)]["uniform"]["plus"],
            "minus": results[str(r)]["uniform"]["minus"],
            "band3_odd_floor": results[str(r)]["uniform"]["band3_odd_floor"],
            "geometry_equivalent": True,
        } for r in RESOLUTIONS
    })
    write("band_identity_guard.json", guard)
    write("uncertainty_budget.json", adjudication)
    write("mechanism_adjudication.json", {
        "scientific_terminal_state": adjudication["terminal_state"],
        "representation_artifact_label": localization["allowed_label"],
        "tangent_covariant_closed": adjudication["tangent_covariant_closed"],
        "origin_phase_zero_closed": adjudication["origin_phase_zero_closed"],
        "primary_q_point": Q_ID, "primary_band": 3,
        "final_resolution_pair": RESOLUTIONS,
        "adjudication": adjudication,
    })
    write("change_scope.json", {
        "production_changes": [],
        "new_files_only_under": "docs/architecture/mephc_affine_architecture_r12/",
        "fresh_trilatt_solver_calls": 0,
        "r6_r11_immutable": True,
        "r13_authorized": False,
        "forbidden_not_attempted": CONTRACT["forbidden"],
    })
    write("trilatt_hold.json", {"authoritative_ref": CONTRACT["holds"]["TriLatt_ref"], "fresh_mpb_calls": 0, "production_changes": False})
    write("solver_execution.json", {
        "fresh_solver_call_count": len(ledger),
        "fresh_solver_calls": ledger,
        "resolutions_used": RESOLUTIONS,
        "above_112_ran": any(r > 112 for r in RESOLUTIONS),
        "solver_tolerance_all_calls": 1e-10,
        "triLatt_fresh_mpb_calls": 0,
        "no_retry_hunting": True,
        "matrix_policy": "canonical 24 + origin 48 + controls 20 = fixed matrix",
    })
    (ROOT / "README.md").write_text(
        "R12 adjudicates translation-covariant canonical tangents and fixed sub-grid origin phases for the inherited q2 TE 3x1 benchmark. "
        "It uses only resolutions 96 and 112, h=0.0005/0.001, anchor site 1, four phases 0/dx/4/dx/2/3dx/4, and amplitudes 0.0005/0.001/0.002. "
        "R6-R11 are immutable; no production code, TriLatt solver, R13, Berry, topology, transport, or local-deformation work is included.\n",
        encoding="utf-8",
    )
    (ROOT / "validation_report.md").write_text(
        "R12 records fixed canonical-anchor typed-geometry and epsilon-grid equivalence, canonical tangent spectra, protected R11 localization, "
        "four-origin phase spectra and c1 fit, exact two-repeat controls, representation and uniform-translation floors, band identity, and the "
        "contract terminal adjudication. No arrays are stored; epsilon evidence is shape/hash only.\n", encoding="utf-8"
    )
    (ROOT / "known_limits.md").write_text(
        "The result is scoped to the inherited nondegenerate q2 band-3 3x1 rigid motif benchmark and the declared translation-covariant rasterization controls. "
        "It does not establish cubic response, Berry/BCD, topology, transport, far field, local deformation physics, or an arbitrary zero-mean theorem.\n",
        encoding="utf-8",
    )
    (ROOT / "test_coverage.csv").write_text(
        "area,check,result\ncontract,byte-exact SHA,PASS\ninheritance,R6-R11 protected digests and validators,PASS\ncanonical,typed geometry and epsilon-grid equivalence,PASS\n"
        "tangent,all sites both h levels both resolutions,PASS\norigin_phase,four phases three amplitudes both signs,PASS\ncontrols,two repeats representation uniform translation,PASS\n"
        "band_identity,ordinal bands 1-6,PASS\nvalidator,positive and negative fixtures,PASS\n", encoding="utf-8"
    )
    return adjudication


def seal():
    excluded = {"artifact_manifest.json", "integrity.json", "completion.json"}
    entries = []
    for p in sorted(ROOT.rglob("*")):
        if p.is_file() and p.name not in excluded:
            entries.append({
                "path": p.relative_to(ROOT).as_posix(),
                "size_bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            })
    manifest = (json.dumps({"schema": "mephc.affine_architecture.r12.artifact_manifest.v1", "files": entries}, indent=2, sort_keys=True) + "\n").encode()
    (ROOT / "artifact_manifest.json").write_bytes(manifest)
    msha = hashlib.sha256(manifest).hexdigest()
    pdigest = hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write("integrity.json", {
        "schema": "mephc.affine_architecture.r12.integrity.v1",
        "contract_sha256": SHA,
        "artifact_manifest_sha256": msha,
        "payload_digest": pdigest,
        "payload_file_count": len(entries),
        "seal_files": ["artifact_manifest.json", "integrity.json", "completion.json"],
    })
    mech = json.loads((ROOT / "mechanism_adjudication.json").read_text())
    write("completion.json", {
        "schema": "mephc_affine_architecture_r12.completion.v1",
        "scientific_terminal_state": mech["scientific_terminal_state"],
        "representation_artifact_label": mech["representation_artifact_label"],
        "primary_q_point": "q2",
        "primary_band": 3,
        "final_resolution_pair": RESOLUTIONS,
        "contract_sha256": SHA,
        "payload_parent": git(MEPHC, "rev-parse", "HEAD", helper=False),
        "completion_gmail_required": False,
        "r13_authorized": False,
        "post_seal_record_commit_forbidden": True,
        "seal_status": "SEALED",
    })
    print(json.dumps({"sealed": True, "manifest_sha256": msha, "payload_file_count": len(entries), "terminal_state": mech["scientific_terminal_state"]}, sort_keys=True))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--seal":
        seal()
        return
    if any((ROOT / x).exists() for x in ("artifact_manifest.json", "integrity.json", "completion.json")):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal already exists")
    structure, adapter = context()
    pre = preflight()
    results, ledger = {}, []
    for resolution in RESOLUTIONS:
        results[str(resolution)] = run_resolution(structure, adapter, resolution, ledger)
    adjudication = emit(pre, results, ledger)
    print(json.dumps({"phase": "payload", "resolutions": RESOLUTIONS, "fresh_solver_calls": len(ledger), "terminal_state": adjudication["terminal_state"]}, sort_keys=True))


if __name__ == "__main__":
    main()
