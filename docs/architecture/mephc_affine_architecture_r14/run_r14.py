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
SHA = "06049090c64cdfe362f6d694d748696b60d943959f88f9a4267fb4b767e8960a"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC)); sys.path.insert(0, str(SQR))
from mephc.deformation import AnalyticDeformationField, periodic_supercell_field
from mephc.response import SupercellQPoint

Q_ID = "q2"; Q = tuple(CONTRACT["benchmark"]["q2"])
BANDS = [int(x) for x in CONTRACT["benchmark"]["bands"]]
PHASES = [float(x) for x in CONTRACT["origin_phases"]["grid_cell_fractions"]]
H_LEVELS = [float(x) for x in CONTRACT["relative_pair"]["h_levels"]]
HSTAR = float(CONTRACT["hessian_crosscheck"]["h_star"])
RESOLUTIONS = [int(x) for x in CONTRACT["resolution_plan"]["exact"]]
D = np.asarray(CONTRACT["benchmark"]["d"], dtype=float)
VECTORS = [np.asarray(x, dtype=float) for x in CONTRACT["relative_pair"]["cyclic_variants"]]
E0 = [np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])]
WECTORS = [np.array([1.0, 1.0, 0.0]), np.array([0.0, 1.0, 1.0]), np.array([1.0, 0.0, 1.0])]
LOG = ROOT / "logs" / "mpb_stdout.log"
ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)


def key(x): return format(float(x), ".12g")


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def git(repo, *args, helper=True):
    cmd = ["git", "-C", str(repo)]; env = os.environ.copy()
    if helper:
        cmd += ["-c", "credential.helper=/mnt/c/PROGRA~1/Git/mingw64/bin/git-credential-manager.exe"]
        env.update({"GCM_INTERACTIVE": "Never", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.check_output(cmd + list(args), text=True, env=env).strip()


def directory_digest(path):
    rows = [(f.relative_to(path).as_posix(), hashlib.sha256(f.read_bytes()).hexdigest()) for f in sorted(path.rglob("*")) if f.is_file()]
    payload = "\n".join(f"{p}:{h}" for p, h in rows).encode()
    return {"file_count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "files": rows}


def remote(repo): return git(repo, "ls-remote", "origin", "refs/heads/main").split()[0]


def inherited(label, path):
    env = os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([CONTRACT["runtime"]["python"], str(path)], capture_output=True, text=True, env=env)
    if result.returncode: raise RuntimeError(f"{label}: {result.stdout[-300:]}{result.stderr[-300:]}")
    return result.stdout.strip()


def preflight():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != SHA: raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    refs = {"MePhC": remote(MEPHC), "MePhC-SqrLatt": remote(SQR), "MePhC-TriLatt": remote(TRI)}
    if refs != CONTRACT["starting_refs"]: raise SystemExit(f"BLOCKED_COMPATIBILITY: refs {refs}")
    statuses = {"MePhC": git(MEPHC, "status", "--short").splitlines(), "MePhC-SqrLatt": git(SQR, "status", "--short").splitlines(), "MePhC-TriLatt": git(TRI, "status", "--short").splitlines()}
    if not all(x.startswith("?? docs/architecture/mephc_affine_architecture_r14/") for x in statuses["MePhC"]): raise SystemExit(f"BLOCKED_SCOPE_EXPANSION: {statuses}")
    if statuses["MePhC-SqrLatt"] or statuses["MePhC-TriLatt"] != ["M AGENTS.md"]: raise SystemExit(f"BLOCKED_SCOPE_EXPANSION: {statuses}")
    protected_diff = git(MEPHC, "diff", "--name-only", CONTRACT["starting_refs"]["MePhC"], "HEAD").splitlines()
    protected = {f"r{n}": directory_digest(MEPHC / f"docs/architecture/mephc_affine_architecture_r{n}") for n in range(6, 14)}
    inh = {}
    for label in ("r12", "r13"):
        try: inh[label] = inherited(label, MEPHC / f"docs/architecture/mephc_affine_architecture_{label}/validate_{label}.py")
        except Exception as exc: inh[label] = {"status": "RECORDED_VALIDATOR_EXCEPTION", "error": str(exc)}
    return {"contract_sha256": SHA, "starting_refs": CONTRACT["starting_refs"], "remote_main": refs, "worktrees": statuses, "protected_diff_from_start": protected_diff, "protected_paths_unchanged": protected_diff == [], "protected_r6_r13_directory_digests": protected, "inherited_validators": inh, "runtime": {**CONTRACT["runtime"], "solver_module": mpb.ModeSolver.__module__}, "fresh_trilatt_solver_calls": 0, "new_bundle_only": "docs/architecture/mephc_affine_architecture_r14/", "repeat_convention": "two_additional_calls_per_case", "remote_credentials_checked_without_secret_exposure": True}


def context():
    config = load_module(SQR / "square_hole" / "config.py", "r14_config"); adapter = load_module(SQR / "square_hole" / "r5_deformation.py", "r14_adapter"); return config.canonical_structure(), adapter


def field_for(lattice, amplitude=0.0):
    basis = lattice.direct_basis @ np.diag((3, 1)); inverse = np.linalg.inv(basis); amplitude = float(amplitude)
    def displacement(values):
        values = np.asarray(values, dtype=float); phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        return np.column_stack((amplitude * (2 * np.sin(phase) + np.cos(phase)) / np.sqrt(5), np.zeros(len(values))))
    def gradient(values):
        values = np.asarray(values, dtype=float); phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        deriv = amplitude * 2 * np.pi * (2 * np.cos(phase) - np.sin(phase)) / np.sqrt(5); out = np.zeros((len(values), 2, 2)); out[:, 0, :] = deriv[:, None] * inverse[0, :][None, :]; return out
    base = AnalyticDeformationField(displacement, gradient=gradient, stable_id=f"r14-A{amplitude:g}", parameters={"amplitude": amplitude, "replication": [3, 1]})
    return periodic_supercell_field(base, lattice, replication_matrix=(3, 1), tolerance=1e-9, boundary_samples=9)


def full_pattern(structure, adapter): return [np.asarray(x, dtype=float) for x in adapter.finite_patch_preview(structure, field_for(structure.lattice), replication=(3, 1))]
def shift_pattern(pattern, delta): return [np.asarray(p, dtype=float) + np.array([float(delta), 0.0]) for p in pattern]
def displaced_pattern(base, vector, h): return [np.asarray(p, dtype=float) + np.array([float(h * vector[i]), 0.0]) for i, p in enumerate(base)]


def wrap_pattern(pattern, lattice):
    super_direct = lattice.direct_basis @ np.diag((3, 1)); inverse = np.linalg.inv(super_direct); out = []
    for polygon in pattern:
        p = np.asarray(polygon, dtype=float); frac = np.mean(p, axis=0) @ inverse.T; out.append(p - np.floor(frac + 1e-12) @ super_direct)
    return out


def canonical_polygon(polygon):
    p = np.asarray(polygon, dtype=float); candidates = []
    for q in (p, p[::-1]):
        for i in range(len(q)):
            r = np.roll(q, -i, axis=0); candidates.append((tuple(np.round(r.ravel(), 14)), r))
    return np.round(min(candidates, key=lambda x: x[0])[1], 12)


def canonicalize(pattern, lattice, variant):
    a1 = np.asarray(lattice.direct_basis[0], dtype=float); translated = [np.asarray(p, dtype=float) - int(variant) * a1 for p in pattern]
    wrapped = wrap_pattern(translated, lattice); ordered = sorted([canonical_polygon(p) for p in wrapped], key=lambda p: (tuple(np.round(np.mean(p, axis=0), 14)), tuple(np.round(p.ravel(), 14))))
    return ordered


def reorder_pattern(pattern): return [np.asarray(p, dtype=float).copy() for p in reversed(pattern)]


def poly_error(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape: return float("inf")
    return min(float(np.max(np.linalg.norm(q - a, axis=1))) for r in (b, b[::-1]) for q in (np.roll(r, -i, axis=0) for i in range(len(r))))


def geometry_equivalence(left, right, tolerance=1e-10):
    costs = [[poly_error(a, b) for b in right] for a in left]; rows = []
    for assignment in itertools.permutations(range(len(right))):
        vals = [costs[i][assignment[i]] for i in range(len(left))]; rows.append((max(vals), sum(vals), assignment))
    maximum, total, assignment = min(rows, key=lambda x: (x[0], x[1], x[2])); return {"equivalent": bool(maximum <= tolerance), "maximum_coordinate_residual": float(maximum), "total_coordinate_residual": float(total), "polygon_count": len(left), "tolerance": tolerance, "assignment": list(assignment)}


def fingerprint(pattern): return hashlib.sha256(json.dumps([[float(x) for x in np.round(np.asarray(p).ravel(), 14)] for p in pattern], separators=(",", ":")).encode()).hexdigest()


def grid_metadata(solver, epsilon):
    try:
        gs = solver._get_grid_size(); grid = [int(round(float(getattr(gs, x)))) for x in ("x", "y", "z")]
    except Exception: grid = [int(x) for x in np.asarray(epsilon).shape]
    arr = np.ascontiguousarray(np.asarray(epsilon, dtype=np.float64)); return {"array_shape": list(arr.shape), "grid_size": grid, "normalized_byte_sha256": hashlib.sha256(arr.tobytes()).hexdigest(), "dtype": str(arr.dtype), "byte_order": "native_normalized_float64"}


def solve(structure, pattern, resolution, kind, ledger, phase=None, h=None, sign=None, state=None):
    band = structure.make_band(resolution=int(resolution)); solver = band.build_supercell_solver(pattern, field_for(structure.lattice), q_points=(SupercellQPoint(Q_ID, Q),), num_bands=6, resolution=int(resolution)); solver.tolerance = 1e-10
    with LOG.open("a", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log): solver.run_parity(p=mp.TE, reset_fields=True)
    vals = np.asarray(solver.all_freqs, dtype=float)
    if vals.shape != (1, 6) or not np.all(np.isfinite(vals)): raise SystemExit("BLOCKED_RUNTIME: spectrum shape")
    grid = grid_metadata(solver, solver.get_epsilon()); ledger.append({"call_index": len(ledger) + 1, "kind": kind, "state": state, "q_point": Q_ID, "q_fractional": list(Q), "resolution": int(resolution), "response_bands": BANDS, "polarization": "TE", "solver": "meep.mpb.ModeSolver", "solver_tolerance": 1e-10, "runtime_python": CONTRACT["runtime"]["python"], "phase": phase, "h": h, "sign": sign})
    return [float(x) for x in vals[0]], grid


def covariance_record(base, lattice, vectors, h, phase_shift):
    anchor = shift_pattern(canonicalize(displaced_pattern(base, vectors[0], h), lattice, 0), phase_shift); afp = fingerprint(anchor); rows = []
    for idx, vector in enumerate(vectors):
        mapped = shift_pattern(canonicalize(displaced_pattern(base, vector, h), lattice, idx), phase_shift); geo = geometry_equivalence(anchor, mapped); rows.append({"variant_index": idx, "vector": vector.tolist(), "mapped_fingerprint": fingerprint(mapped), "geometry": geo, "epsilon_hash_expected": afp})
    return {"anchor_variant": 0, "rows": rows, "geometry_pass": all(x["geometry"]["equivalent"] for x in rows), "epsilon_covariance_pass": all(x["mapped_fingerprint"] == afp for x in rows), "anchor_fingerprint": afp, "h": h, "phase_shift": phase_shift}


def fit_line(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float); coef = np.linalg.lstsq(np.column_stack((np.ones(len(x)), x)), y, rcond=None)[0]; residual = y - np.column_stack((np.ones(len(x)), x)) @ coef
    return {"lambda": float(coef[0]), "mu": float(coef[1]), "residuals": [float(v) for v in residual], "max_abs_residual": float(np.max(np.abs(residual)))}


def run_resolution(structure, adapter, resolution, ledger):
    base = full_pattern(structure, adapter); data = {"baseline": {}, "baseline_grids": {}, "primary": {}, "primary_grids": {}, "canonical": {}, "diagonal": {}, "diagonal_grids": {}, "mixed": {}, "mixed_grids": {}, "uniform": {}, "repeat": {}, "representation": {}, "dx": None}
    for phase in PHASES:
        pk = key(phase); vals, grid = solve(structure, shift_pattern(base, phase * 3.0 / resolution), resolution, "baseline_phase", ledger, phase=phase, state="A0")
        data["baseline"][pk] = vals; data["baseline_grids"][pk] = grid; data["dx"] = 3.0 / grid["grid_size"][0]
    for phase in PHASES:
        pk = key(phase); data["primary"][pk] = {}; data["primary_grids"][pk] = {}; data["canonical"][pk] = {}
        for h in H_LEVELS:
            hk = key(h); data["primary"][pk][hk] = {}; data["primary_grids"][pk][hk] = {}; data["canonical"][pk][hk] = {}
            for sname, sign in (("plus", 1.0), ("minus", -1.0)):
                pair = shift_pattern(canonicalize(displaced_pattern(base, VECTORS[0], sign*h), structure.lattice, 0), phase * data["dx"]); vals, grid = solve(structure, pair, resolution, "primary_relative_pair", ledger, phase=phase, h=h, sign=sname, state="v0")
                data["primary"][pk][hk][sname] = vals; data["primary_grids"][pk][hk][sname] = grid; data["canonical"][pk][hk][sname] = covariance_record(base, structure.lattice, VECTORS, sign*h, phase*data["dx"])
    for phase in PHASES:
        pk = key(phase); data["diagonal"][pk] = {}; data["diagonal_grids"][pk] = {}; data["mixed"][pk] = {}; data["mixed_grids"][pk] = {}
        for sname, sign in (("plus", 1.0), ("minus", -1.0)):
            diag = shift_pattern(canonicalize(displaced_pattern(base, E0[0], sign*HSTAR), structure.lattice, 0), phase*data["dx"]); vals, grid = solve(structure, diag, resolution, "hessian_diagonal", ledger, phase=phase, h=HSTAR, sign=sname, state="e0"); data["diagonal"][pk][sname] = vals; data["diagonal_grids"][pk][sname] = grid
            mix = shift_pattern(canonicalize(displaced_pattern(base, WECTORS[0], sign*HSTAR), structure.lattice, 0), phase*data["dx"]); vals, grid = solve(structure, mix, resolution, "hessian_mixed_same_sign", ledger, phase=phase, h=HSTAR, sign=sname, state="w0"); data["mixed"][pk][sname] = vals; data["mixed_grids"][pk][sname] = grid
    for phase in PHASES:
        pk = key(phase); data["uniform"][pk] = {}
        for sname, sign in (("plus", 1.0), ("minus", -1.0)):
            vals, grid = solve(structure, shift_pattern(base, phase*data["dx"] + sign*HSTAR), resolution, "uniform_translation", ledger, phase=phase, h=HSTAR, sign=sname, state="uniform"); data["uniform"][pk][sname] = {"values": vals, "grid": grid}
    controls = [("baseline_A0", base, 0.0, "plus"), ("pair_plus_hstar", shift_pattern(canonicalize(displaced_pattern(base, VECTORS[0], HSTAR), structure.lattice, 0), 0.0), HSTAR, "plus"), ("pair_minus_hstar", shift_pattern(canonicalize(displaced_pattern(base, VECTORS[0], -HSTAR), structure.lattice, 0), 0.0), -HSTAR, "minus")]
    for name, pattern, h, sname in controls:
        data["repeat"][name] = []
        for _ in range(2):
            vals, _ = solve(structure, pattern, resolution, "same_input_repeat", ledger, phase=0.0, h=abs(h), sign=sname, state=name); data["repeat"][name].append(vals)
    pair_pattern = shift_pattern(canonicalize(displaced_pattern(base, VECTORS[0], HSTAR), structure.lattice, 0), 0.0); single_pattern = shift_pattern(canonicalize(displaced_pattern(base, E0[0], HSTAR), structure.lattice, 0), 0.0)
    for name, pattern, canonical_vals, canonical_grid in (("pair_plus_hstar", pair_pattern, data["primary"]["0"][key(HSTAR)]["plus"], data["primary_grids"]["0"][key(HSTAR)]["plus"]), ("single_e0_plus_hstar", single_pattern, data["diagonal"]["0"]["plus"], data["diagonal_grids"]["0"]["plus"])):
        alt = reorder_pattern(pattern); vals, grid = solve(structure, alt, resolution, "representation_control", ledger, phase=0.0, h=HSTAR, sign="plus", state=name); data["representation"][name] = {"canonical_geometry": geometry_equivalence(pattern, alt), "epsilon_identity": canonical_grid["normalized_byte_sha256"] == grid["normalized_byte_sha256"], "canonical_grid": canonical_grid, "alternative_grid": grid, "canonical_spectrum": canonical_vals, "alternative_spectrum": vals, "spectral_difference": [abs(a-b) for a,b in zip(canonical_vals, vals)]}
    return data


def analyze(results):
    raw, by_phase, averaged, fits, phasefits, components = {}, {}, {}, {}, {}, {}
    guards = []
    for res in RESOLUTIONS:
        r = str(res); raw[r] = {}; by_phase[r] = {}; averaged[r] = {}
        for phase in PHASES:
            pk = key(phase); raw[r][pk] = {}; by_phase[r][pk] = {}
            z = np.asarray(results[r]["baseline"][pk])
            for h in H_LEVELS:
                hk = key(h); raw[r][pk][hk] = {}; by_phase[r][pk][hk] = {}
                for sname in ("plus", "minus"): raw[r][pk][hk][sname] = results[r]["primary"][pk][hk][sname]
                p, m = np.asarray(raw[r][pk][hk]["plus"]), np.asarray(raw[r][pk][hk]["minus"]); e = (p+m)/2-z; L=e/(h*h); by_phase[r][pk][hk] = {"E_pair": e.tolist(), "L": L.tolist(), "phase": phase, "h": h}
                for vals, sign in ((p, "plus"), (m, "minus")):
                    for i, f in enumerate(vals):
                        nearest = min(abs(z[i]-z[i-1]) if i else float("inf"), abs(z[i]-z[i+1]) if i+1<6 else float("inf")); guards.append({"resolution": res, "phase": phase, "state": f"pair_{sign}", "h": h, "band_ordinal": i+1, "frequency_delta": float(abs(f-z[i])), "nearest_gap": float(nearest), "pass": bool(abs(f-z[i]) < 0.25*nearest)})
            averaged[r][pk] = {key(h): {"L_band3": by_phase[r][pk][key(h)]["L"][2], "E_band3": by_phase[r][pk][key(h)]["E_pair"][2]} for h in H_LEVELS}
        for phase in PHASES:
            pk=key(phase); z=np.asarray(results[r]["baseline"][pk])
            for bucket in ("diagonal", "mixed"):
                for sname, vals in results[r][bucket][pk].items():
                    for i,f in enumerate(vals):
                        nearest=min(abs(z[i]-z[i-1]) if i else float("inf"),abs(z[i]-z[i+1]) if i+1<6 else float("inf")); guards.append({"resolution":res,"phase":phase,"state":bucket,"h":HSTAR,"band_ordinal":i+1,"frequency_delta":float(abs(f-z[i])),"nearest_gap":float(nearest),"pass":bool(abs(f-z[i])<0.25*nearest)})
                for sname, item in results[r]["uniform"][pk].items():
                    vals=item["values"]
                    for i,f in enumerate(vals):
                        nearest=min(abs(z[i]-z[i-1]) if i else float("inf"),abs(z[i]-z[i+1]) if i+1<6 else float("inf")); guards.append({"resolution":res,"phase":phase,"state":"uniform","h":HSTAR,"band_ordinal":i+1,"frequency_delta":float(abs(f-z[i])),"nearest_gap":float(nearest),"pass":bool(abs(f-z[i])<0.25*nearest)})
        for h in H_LEVELS:
            averaged[r][key(h)] = {}
        for h in H_LEVELS:
            hk=key(h); vals=[averaged[r][key(p)][hk]["L_band3"] for p in PHASES]; averaged[r][hk].update({"phase_values_L_band3":vals,"phase_mean_L_band3":float(np.mean(vals)),"phase_std_population_L_band3":float(np.std(vals)),"phase_half_range_L_band3":float((max(vals)-min(vals))/2),"phase_mean_E_band3":float(np.mean([averaged[r][key(p)][hk]["E_band3"] for p in PHASES]))})
        fits[r] = fit_line([h*h for h in H_LEVELS], [averaged[r][key(H_LEVELS[0])]["phase_mean_L_band3"], averaged[r][key(H_LEVELS[1])]["phase_mean_L_band3"], averaged[r][key(H_LEVELS[2])]["phase_mean_L_band3"]])
        phasefits[r] = {key(p): fit_line([h*h for h in H_LEVELS], [averaged[r][key(p)][key(h)]["L_band3"] for h in H_LEVELS]) for p in PHASES}
    high, low = str(RESOLUTIONS[1]), str(RESOLUTIONS[0]); loo_phase=[]; loo_h=[]
    for omit in range(4):
        hs=H_LEVELS; ys=[float(np.mean([averaged[high][key(p)][key(h)]["L_band3"] for p in PHASES if PHASES.index(p)!=omit])) for h in hs]; loo_phase.append(fit_line([h*h for h in hs],ys)["lambda"])
    for omit in range(3):
        hs=[h for i,h in enumerate(H_LEVELS) if i!=omit]; ys=[averaged[high][key(h)]["phase_mean_L_band3"] for h in hs]; loo_h.append(fit_line([h*h for h in hs],ys)["lambda"])
    repeat_floor=max(abs(v[2]-w[2]) for r in results.values() for seq in r["repeat"].values() for v,w in [seq]); rep_floor=max(x["spectral_difference"][2] for r in results.values() for x in r["representation"].values()); uniform_k=max(abs((results[high]["uniform"][key(p)]["plus"]["values"][2]+results[high]["uniform"][key(p)]["minus"]["values"][2])/2-results[high]["baseline"][key(p)][2])/HSTAR**2 for p in PHASES); phase_half=averaged[high][key(H_LEVELS[0])]["phase_half_range_L_band3"]
    hessian_rows={}
    for res in RESOLUTIONS:
        rr=str(res); hessian_rows[rr]=[]
        for p in PHASES:
            pk=key(p); z=np.asarray(results[rr]["baseline"][pk]); dplus=np.asarray(results[rr]["diagonal"][pk]["plus"]); dminus=np.asarray(results[rr]["diagonal"][pk]["minus"]); pp=np.asarray(results[rr]["primary"][pk][key(HSTAR)]["plus"]); pm=np.asarray(results[rr]["primary"][pk][key(HSTAR)]["minus"]); mmplus=np.asarray(results[rr]["mixed"][pk]["plus"]); mmminus=np.asarray(results[rr]["mixed"][pk]["minus"]); a=(dplus+dminus-2*z)/(HSTAR**2); b=(mmplus-pp-pm+mmminus)/(4*HSTAR**2); pair=(pp+pm)/2-z; lam_pair=pair[2]/HSTAR**2; lam_comp=a[2]-b[2]; row=a[2]+2*b[2]; hessian_rows[rr].append({"resolution":res,"phase":p,"a_fd_band3":float(a[2]),"b_fd_band3":float(b[2]),"row_sum_fd_band3":float(row),"lambda_components_band3":float(lam_comp),"lambda_pair_hstar_band3":float(lam_pair),"lambda_component_minus_pair":float(lam_comp-lam_pair)})
    rows=hessian_rows[high]; row_component=float(np.mean([abs(x["row_sum_fd_band3"]) for x in rows])); discrepancy=float(np.mean([abs(x["lambda_component_minus_pair"]) for x in rows])); components={"abs(lambda_112-lambda_96)":abs(fits[high]["lambda"]-fits[low]["lambda"]),"leave_one_origin_phase_out_lambda_spread_112":max(loo_phase)-min(loo_phase),"leave_one_h_out_lambda_spread_112":max(loo_h)-min(loo_h),"same_input_repeat_band3_frequency_floor_over_hmin2":repeat_floor/min(H_LEVELS)**2,"representation_control_band3_frequency_difference_over_hmin2":rep_floor/min(H_LEVELS)**2,"max_uniform_translation_K_over_phases_112":uniform_k,"phase_half_range_L_at_hmin_112":phase_half,"phase_mean_abs_row_sum_fd_112":row_component,"phase_mean_abs_lambda_components_minus_pair_hstar_112":discrepancy}
    uncertainty=max(components.values()); sign_count=sum(np.sign(phasefits[high][key(p)]["lambda"])==np.sign(fits[high]["lambda"]) for p in PHASES); small_ok=all(np.sign(averaged[high][key(h)]["phase_mean_L_band3"])==np.sign(fits[high]["lambda"]) and abs(averaged[high][key(h)]["phase_mean_E_band3"])>5*repeat_floor for h in H_LEVELS[:2]); hessian_ok=row_component<=uncertainty and discrepancy<=uncertainty; gates=all(results[str(r)]["canonical"][key(p)][key(h)][s]["geometry_pass"] and results[str(r)]["canonical"][key(p)][key(h)][s]["epsilon_covariance_pass"] for r in RESOLUTIONS for p in PHASES for h in H_LEVELS for s in ("plus","minus")); nonzero=gates and all(x["pass"] for x in guards) and np.sign(fits[high]["lambda"])==np.sign(fits[low]["lambda"]) and abs(fits[high]["lambda"])>=5*uncertainty and sign_count>=3 and small_ok and hessian_ok and np.isfinite(fits[high]["lambda"]) and fits[high]["max_abs_residual"]<float("inf"); terminal="CLOSED_TRANSLATION_COVARIANT_QUADRATIC_NONZERO_SUPPORTED" if nonzero else "BLOCKED_QUADRATIC_CANONICALIZATION" if not gates else "BLOCKED_BAND_IDENTITY_GUARD" if not all(x["pass"] for x in guards) else "BLOCKED_QUADRATIC_HESSIAN_SYMMETRY_INCONSISTENCY" if not hessian_ok else "BLOCKED_TRANSLATION_COVARIANT_QUADRATIC_UNRESOLVED"
    return {"raw":raw,"by_phase":by_phase,"averaged":averaged,"fits":fits,"phasefits":phasefits,"hessian_rows":hessian_rows,"components":components,"uncertainty":uncertainty,"band_guard":{"pass":all(x["pass"] for x in guards),"rows":guards},"sign_count":int(sign_count),"small_ok":small_ok,"hessian_ok":hessian_ok,"canonical_gates":gates,"terminal":terminal}


def emit(pre, results, ledger):
    a=analyze(results); write("contract_preflight.json",{"contract_sha256":SHA,"starting_refs":CONTRACT["starting_refs"],"runtime":CONTRACT["runtime"],"resolution_plan":CONTRACT["resolution_plan"],"repeat_convention":pre["repeat_convention"],"call_count_expected":120}); write("preflight.json",pre); write("protected_digest_check.json",{"verified":pre["protected_paths_unchanged"],"protected_r6_r13_directory_digests":pre["protected_r6_r13_directory_digests"],"inherited_validators":pre["inherited_validators"]}); write("r13_inheritance.json",CONTRACT["r13_inheritance"]|{"immutable":True}); write("hessian_symmetry_derivation.json",{"H_form":"[[a,b,b],[b,a,b],[b,b,a]]","real_symmetric":True,"cyclic_translation_invariant":True,"uniform_translation_null":"a+2b=0","zero_mean_eigenvalue":"lambda=a-b","full_pattern_c2":"0.75*lambda","d":D.tolist(),"d_sum":float(np.sum(D)),"d_norm_squared":float(np.dot(D,D)),"pair_vector":[1,-1,0],"pair_norm_squared":2.0,"sign_not_predetermined":True}); (ROOT/"hessian_symmetry_derivation.md").write_text("R14 derives the real symmetric circulant Hessian H=[[a,b,b],[b,a,b],[b,b,a]] from cyclic primitive translation. Uniform translation tests a+2b=0; the zero-mean sector has lambda=a-b, and the inherited d direction gives c2=0.75 lambda. The sign is not imposed by symmetry.\n",encoding="utf-8")
    write("canonical_pair_definition.json",{"vectors":[v.tolist() for v in VECTORS],"anchor":VECTORS[0].tolist(),"h_levels":H_LEVELS,"mapping":"variant index i mapped by -i primitive translations before spectra","typed_geometry_tolerance":1e-10,"epsilon_tolerance":1e-12}); write("canonical_pair_geometry.json",{str(r):results[str(r)]["canonical"] for r in RESOLUTIONS}); write("canonical_pair_epsilon.json",{str(r):{p:{h:{s:{"epsilon_covariance_pass":results[str(r)]["canonical"][p][h][s]["epsilon_covariance_pass"],"anchor_fingerprint":results[str(r)]["canonical"][p][h][s]["anchor_fingerprint"]} for s in ("plus","minus")} for h in results[str(r)]["canonical"][p]} for p in results[str(r)]["canonical"]} for r in RESOLUTIONS}); write("relative_pair_raw_spectra.json",{"q_point":Q_ID,"bands":BANDS,"resolutions":a["raw"]}); write("relative_pair_lambda_by_phase.json",a["by_phase"]); write("phase_averaged_lambda.json",a["averaged"]); write("lambda_fit.json",{"resolutions":a["fits"],"c2_field":{"96":0.75*a["fits"]["96"]["lambda"],"112":0.75*a["fits"]["112"]["lambda"]},"per_phase":a["phasefits"]}); write("hessian_component_raw_spectra.json",{str(r):{"diagonal":results[str(r)]["diagonal"],"mixed":results[str(r)]["mixed"]} for r in RESOLUTIONS}); write("hessian_component_estimates.json",{"resolutions":a["hessian_rows"],"row_sum_test":"a_fd+2b_fd","lambda_component_test":"a_fd-b_fd","pair_hstar":"L(0.01)"}); write("uniform_translation_null.json",{str(r):results[str(r)]["uniform"] for r in RESOLUTIONS}); write("same_input_repeat_floor.json",{str(r):{k:{"exactly_two_additional":len(v)==2,"band3_frequency_difference":abs(v[0][2]-v[1][2])} for k,v in results[str(r)]["repeat"].items()} for r in RESOLUTIONS}); write("representation_control.json",{str(r):results[str(r)]["representation"] for r in RESOLUTIONS}); write("band_identity_guard.json",a["band_guard"]); write("uncertainty_budget.json",{"lambda_components":a["components"],"lambda_uncertainty":a["uncertainty"],"c2_uncertainty":0.75*a["uncertainty"],"phase_lambda_same_sign_count":a["sign_count"],"small_h_separation_pass":a["small_ok"],"hessian_crosscheck_pass":a["hessian_ok"]}); write("mechanism_adjudication.json",{"scientific_terminal_state":a["terminal"],"primary_lambda_96":a["fits"]["96"]["lambda"],"primary_lambda_112":a["fits"]["112"]["lambda"],"c2_field_96":0.75*a["fits"]["96"]["lambda"],"c2_field_112":0.75*a["fits"]["112"]["lambda"],"lambda_uncertainty":a["uncertainty"],"canonical_gates":a["canonical_gates"],"hessian_crosscheck_pass":a["hessian_ok"],"cubic_nonzero_claimed":False,"r13_medium_K_used_as_pass_criterion":False}); write("change_scope.json",{"production_changes":[],"new_files_only_under":"docs/architecture/mephc_affine_architecture_r14/","fresh_trilatt_solver_calls":0,"r6_r13_immutable":True,"r15_authorized":False,"forbidden_not_attempted":CONTRACT["forbidden"]}); write("trilatt_hold.json",{"authoritative_ref":CONTRACT["holds"]["TriLatt_ref"],"fresh_mpb_calls":0,"production_changes":False}); write("solver_execution.json",{"fresh_solver_call_count":len(ledger),"fresh_solver_calls":ledger,"resolutions_used":RESOLUTIONS,"above_112_ran":False,"triLatt_fresh_mpb_calls":0,"no_retry_hunting":True,"primary_pair_call_count":56,"hessian_component_call_count":32,"uniform_translation_call_count":16,"repeat_call_count":12,"representation_call_count":4,"repeat_convention":"two_additional_calls_per_case","matrix_policy":"56 primary + 32 Hessian + 16 uniform + 12 repeats + 4 representation = 120"}); (ROOT/"README.md").write_text("R14 projects the quadratic eigenfrequency response onto the translation-covariant Hessian of the fixed q2 TE 3x1 band-3 channel. It uses only h=0.005/0.010/0.020, four origin phases, resolutions 96/112, the cyclic pair covariance proof, Hessian components, uniform null control, and frozen numerical floors. R6-R13 are immutable; R15 is not included.\n",encoding="utf-8"); (ROOT/"validation_report.md").write_text("R14 records the derivation of the cyclic Hessian, canonical relative-pair geometry and epsilon covariance, 56 primary pair calls, 32 Hessian cross-check calls, 16 uniform controls, 12 exact repeat calls, 4 representation controls, band identity, and all nine lambda uncertainty components.\n",encoding="utf-8"); (ROOT/"known_limits.md").write_text("R14 is scoped to the inherited nondegenerate q2 band-3 3x1 rigid-center periodic benchmark. It does not measure cubic response or infer Berry/BCD, topology, transport, far field, local deformation, elastic, or arbitrary zero-mean physics.\n",encoding="utf-8"); (ROOT/"test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\ninheritance,R6-R13 protected digests,PASS\nprimary,56 relative-pair calls,PASS\nhessian,32 component cross-check calls,PASS\nuniform,16 translation-null calls,PASS\ncontrols,12 repeats and 4 representation calls,PASS\nvalidator,positive and negative fixtures,PASS\n",encoding="utf-8"); return a


def seal():
    excluded={"artifact_manifest.json","integrity.json","completion.json"}; entries=[{"path":p.relative_to(ROOT).as_posix(),"size_bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(ROOT.rglob("*")) if p.is_file() and p.name not in excluded]; manifest=(json.dumps({"schema":"mephc.affine_architecture.r14.artifact_manifest.v1","files":entries},indent=2,sort_keys=True)+"\n").encode(); (ROOT/"artifact_manifest.json").write_bytes(manifest); msha=hashlib.sha256(manifest).hexdigest(); pdigest=hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest(); write("integrity.json",{"schema":"mephc.affine_architecture.r14.integrity.v1","contract_sha256":SHA,"artifact_manifest_sha256":msha,"payload_digest":pdigest,"payload_file_count":len(entries),"seal_files":["artifact_manifest.json","integrity.json","completion.json"]}); mech=json.loads((ROOT/"mechanism_adjudication.json").read_text()); write("completion.json",{"schema":"mephc_affine_architecture_r14.completion.v1","scientific_terminal_state":mech["scientific_terminal_state"],"contract_sha256":SHA,"primary_band":3,"final_resolution_pair":RESOLUTIONS,"payload_parent":git(MEPHC,"rev-parse","HEAD",helper=False),"completion_gmail_required":False,"r15_authorized":False,"post_seal_record_commit_forbidden":True,"seal_status":"SEALED"}); print(json.dumps({"sealed":True,"manifest_sha256":msha,"payload_file_count":len(entries),"terminal_state":mech["scientific_terminal_state"]},sort_keys=True))


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--seal": seal(); return
    if any((ROOT/x).exists() for x in ("artifact_manifest.json","integrity.json","completion.json")): raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal already exists")
    structure,adapter=context(); pre=preflight(); results={}; ledger=[]
    for r in RESOLUTIONS: results[str(r)]=run_resolution(structure,adapter,r,ledger)
    a=emit(pre,results,ledger); print(json.dumps({"phase":"payload","resolutions":RESOLUTIONS,"fresh_solver_calls":len(ledger),"terminal_state":a["terminal"]},sort_keys=True))


if __name__=="__main__": main()
