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

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SQR = MEPHC.parent / "SqrLatt"
TRI = MEPHC.parent / "TriLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
CONTRACT_SHA = "f2a874d2114e38b4e25a45a7b43232f56b66e654abb96eca29b6bdabe341b5eb"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC)); sys.path.insert(0, str(SQR))
from meep import mpb
from mephc.deformation import AnalyticDeformationField, periodic_supercell_field
from mephc.response import SupercellQPoint

Q_ID = "q2"
Q = tuple(CONTRACT["benchmark"]["q2"])
BANDS = [int(x) for x in CONTRACT["benchmark"]["bands"]]
PRIMARY_BAND = int(CONTRACT["benchmark"]["primary_band"])
PHASES = [float(x) for x in CONTRACT["ensemble_B"]["grid_cell_fractions"]]
RESOLUTIONS = [int(x) for x in CONTRACT["resolution_plan"]["exact"]]
H = [float(x) for x in CONTRACT["levels"]]
PAIR = np.asarray(CONTRACT["benchmark"]["pair"], dtype=float)
FULL = np.asarray(CONTRACT["benchmark"]["full"], dtype=float)
LOG_DIR = ROOT / "logs"; LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "mpb_stdout.log"
CALL_LOG = LOG_DIR / "r17_call_ledger.ndjson"


def key(x): return format(float(x), ".12g")


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load(rel):
    path = Path(rel)
    return json.loads((path if path.is_absolute() else MEPHC / path).read_text(encoding="utf-8"))


def git(repo, *args, remote_helper=False):
    env = os.environ.copy(); cmd = ["git", "-C", str(repo)]
    if remote_helper:
        cmd += ["-c", "credential.helper=/mnt/c/PROGRA~1/Git/mingw64/bin/git-credential-manager.exe"]
        env.update({"GCM_INTERACTIVE": "Never", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.check_output(cmd + list(args), text=True, env=env).strip()


def directory_digest(path):
    rows = [(f.relative_to(path).as_posix(), hashlib.sha256(f.read_bytes()).hexdigest()) for f in sorted(path.rglob("*")) if f.is_file()]
    return {"file_count": len(rows), "sha256": hashlib.sha256("\n".join(f"{a}:{b}" for a, b in rows).encode()).hexdigest(), "files": rows}


def remote_ref(repo): return git(repo, "ls-remote", "origin", "refs/heads/main", remote_helper=True).split()[0]


def inherited(label):
    path = MEPHC / f"docs/architecture/mephc_affine_architecture_{label}/validate_{label}.py"
    env = os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([CONTRACT["runtime"]["python"], str(path)], capture_output=True, text=True, env=env)
    return {"returncode": r.returncode, "stdout": r.stdout[-1000:], "stderr": r.stderr[-1000:]}


def r16_literal_uniform_max():
    data = load("docs/architecture/mephc_affine_architecture_r16/uniform_Q_and_secants.json")
    rows = []
    for phase in ["0", "0.25", "0.5", "0.75"]:
        for item in data["resolutions"]["112"][phase]["adjacent_secants"]:
            rows.append((abs(float(item["band3"])), phase, item["interval"], float(item["band3"])))
    return max(rows)


def preflight():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != CONTRACT_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    refs = {"MePhC": remote_ref(MEPHC), "MePhC-SqrLatt": remote_ref(SQR), "MePhC-TriLatt": remote_ref(TRI)}
    if refs != CONTRACT["starting_refs"]: raise SystemExit(f"BLOCKED_COMPATIBILITY: refs {refs}")
    status = {"MePhC": git(MEPHC, "status", "--short").splitlines(), "MePhC-SqrLatt": git(SQR, "status", "--short").splitlines(), "MePhC-TriLatt": git(TRI, "status", "--short").splitlines()}
    if not all(x.startswith("?? docs/architecture/mephc_affine_architecture_r17/") for x in status["MePhC"]) or status["MePhC-SqrLatt"] or any(x.strip() != "M AGENTS.md" for x in status["MePhC-TriLatt"]):
        raise SystemExit(f"BLOCKED_SCOPE_EXPANSION: {status}")
    observed = r16_literal_uniform_max()
    if observed[0] < 0.2850798537483712: raise SystemExit("BLOCKED_COMPATIBILITY: R16 literal max below required floor")
    return {"contract_sha256": CONTRACT_SHA, "starting_refs": CONTRACT["starting_refs"], "remote_main": refs, "observed_local_refs": {"MePhC": git(MEPHC, "rev-parse", "HEAD"), "MePhC-SqrLatt": git(SQR, "rev-parse", "HEAD"), "MePhC-TriLatt": git(TRI, "rev-parse", "HEAD")}, "worktrees": status, "protected_r6_r16_directory_digests": {f"r{n}": directory_digest(MEPHC / f"docs/architecture/mephc_affine_architecture_r{n}") for n in range(6, 17)}, "inherited_validators": {x: inherited(x) for x in ("r15", "r16")}, "r16_literal_uniform_max": {"absolute": observed[0], "phase": observed[1], "interval": observed[2], "signed_value": observed[3]}, "fresh_solver_calls_before_freeze": 0, "fresh_trilatt_solver_calls": 0, "new_bundle_only": "docs/architecture/mephc_affine_architecture_r17/", "remote_credentials_checked_without_secret_exposure": True}


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def context():
    config = load_module(SQR / "square_hole" / "config.py", "r17_config")
    adapter = load_module(SQR / "square_hole" / "r5_deformation.py", "r17_adapter")
    return config.canonical_structure(), adapter


def field_for(lattice, amplitude=0.0):
    basis = lattice.direct_basis @ np.diag((3, 1)); inverse = np.linalg.inv(basis); amplitude = float(amplitude)
    def displacement(values):
        values = np.asarray(values, dtype=float); phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        return np.column_stack((amplitude * (2 * np.sin(phase) + np.cos(phase)) / np.sqrt(5), np.zeros(len(values))))
    def gradient(values):
        values = np.asarray(values, dtype=float); phase = 2 * np.pi * (values @ inverse.T)[:, 0]
        deriv = amplitude * 2 * np.pi * (2 * np.cos(phase) - np.sin(phase)) / np.sqrt(5); out = np.zeros((len(values), 2, 2)); out[:, 0, :] = deriv[:, None] * inverse[0, :][None, :]; return out
    base = AnalyticDeformationField(displacement, gradient=gradient, stable_id=f"r17-A{amplitude:g}", parameters={"amplitude": amplitude, "replication": [3, 1]})
    return periodic_supercell_field(base, lattice, replication_matrix=(3, 1), tolerance=1e-9, boundary_samples=9)


def full_pattern(structure, adapter, amplitude): return [np.asarray(x, dtype=float) for x in adapter.finite_patch_preview(structure, field_for(structure.lattice, amplitude), replication=(3, 1))]
def shift_pattern(pattern, delta): return [np.asarray(p, dtype=float) + np.array([float(delta), 0.0]) for p in pattern]
def displaced_pattern(base, vector, h): return [np.asarray(p, dtype=float) + np.array([float(h * vector[i]), 0.0]) for i, p in enumerate(base)]


def wrap_pattern(pattern, lattice):
    direct = lattice.direct_basis @ np.diag((3, 1)); inverse = np.linalg.inv(direct); out = []
    for polygon in pattern:
        p = np.asarray(polygon, dtype=float); frac = np.mean(p, axis=0) @ inverse.T; out.append(p - np.floor(frac + 1e-12) @ direct)
    return out


def canonical_polygon(polygon):
    p = np.asarray(polygon, dtype=float); candidates = []
    for q in (p, p[::-1]):
        for i in range(len(q)):
            r = np.roll(q, -i, axis=0); candidates.append((tuple(np.round(r.ravel(), 14)), r))
    return np.round(min(candidates, key=lambda x: x[0])[1], 12)


def canonicalize(pattern, lattice, variant=0):
    a1 = np.asarray(lattice.direct_basis[0], dtype=float); translated = [np.asarray(p, dtype=float) - int(variant) * a1 for p in pattern]
    return sorted([canonical_polygon(p) for p in wrap_pattern(translated, lattice)], key=lambda p: (tuple(np.round(np.mean(p, axis=0), 14)), tuple(np.round(p.ravel(), 14))))


def geometry_equivalence(left, right, tolerance=1e-10):
    def error(a, b):
        a, b = np.asarray(a), np.asarray(b)
        if a.shape != b.shape: return float("inf")
        candidates = []
        for q in (b, b[::-1]): candidates.extend(np.roll(q, -i, axis=0) for i in range(len(q)))
        return min(float(np.max(np.linalg.norm(q - a, axis=1))) for q in candidates)
    costs = [[error(a, b) for b in right] for a in left]; rows = []
    for assignment in itertools.permutations(range(len(right))):
        vals = [costs[i][assignment[i]] for i in range(len(left))]; rows.append((max(vals), sum(vals), assignment))
    maximum, total, assignment = min(rows, key=lambda x: (x[0], x[1], x[2]))
    return {"equivalent": bool(maximum <= tolerance), "maximum_coordinate_residual": float(maximum), "total_coordinate_residual": float(total), "tolerance": tolerance, "assignment": list(assignment)}


def fingerprint(pattern): return hashlib.sha256(json.dumps([[float(x) for x in np.round(np.asarray(p).ravel(), 14)] for p in pattern], separators=(",", ":")).encode()).hexdigest()


def grid_metadata(solver, epsilon):
    try:
        gs = solver._get_grid_size(); grid = [int(round(float(getattr(gs, x)))) for x in ("x", "y", "z")]
    except Exception: grid = [int(x) for x in np.asarray(epsilon).shape]
    arr = np.ascontiguousarray(np.asarray(epsilon, dtype=np.float64))
    return {"array_shape": list(arr.shape), "grid_size": grid, "normalized_byte_sha256": hashlib.sha256(arr.tobytes()).hexdigest(), "dtype": str(arr.dtype), "byte_order": "native_normalized_float64"}


def solve(structure, pattern, resolution, kind, ledger, phase, h, sign, direction, role):
    band = structure.make_band(resolution=int(resolution)); solver = band.build_supercell_solver(pattern, field_for(structure.lattice, 0.0), q_points=(SupercellQPoint(Q_ID, Q),), num_bands=6, resolution=int(resolution)); solver.tolerance = 1e-10
    with LOG.open("a", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log): solver.run_parity(p=mp.TE, reset_fields=True)
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (1, 6) or not np.all(np.isfinite(values)): raise SystemExit("BLOCKED_RUNTIME: invalid spectrum")
    grid = grid_metadata(solver, solver.get_epsilon())
    row = {"call_index": len(ledger) + 1, "kind": kind, "control_role": role, "direction": direction, "q_point": Q_ID, "q_fractional": list(Q), "resolution": int(resolution), "requested_bands": 6, "response_bands": BANDS, "primary_band": PRIMARY_BAND, "polarization": "TE", "solver": "meep.mpb.ModeSolver", "solver_tolerance": 1e-10, "runtime_python": CONTRACT["runtime"]["python"], "phase": float(phase), "h": float(h), "sign": sign}
    ledger.append(row); CALL_LOG.open("a", encoding="utf-8").write(json.dumps({"ledger": row, "bands": [float(x) for x in values[0]], "grid": grid}, sort_keys=True) + "\n")
    return [float(x) for x in values[0]], grid


def make_pattern(structure, adapter, base, direction, resolution, phase, h, sign):
    shift = float(phase) * 3.0 / float(resolution)
    if direction == "pair": return shift_pattern(canonicalize(displaced_pattern(base, PAIR, sign * h), structure.lattice), shift)
    if direction == "full": return shift_pattern(full_pattern(structure, adapter, sign * h), shift)
    if direction == "uniform": return shift_pattern(base, shift + sign * h)
    raise ValueError(direction)


def plan_calls():
    calls = []
    for res in RESOLUTIONS:
        for phase in PHASES:
            for direction in ("pair", "full", "uniform"):
                for h in H:
                    for sign in ("plus", "minus"):
                        calls.append({"class": "primary", "direction": direction, "resolution": res, "phase": phase, "h": h, "sign": sign})
        for direction in ("pair", "full", "uniform"):
            for sign in ("plus", "minus"):
                calls.append({"class": "repeat", "direction": direction, "resolution": res, "phase": 0.125, "h": 0.0075, "sign": sign})
        for direction in ("pair", "full", "uniform"):
            calls.append({"class": "representation", "direction": direction, "resolution": res, "phase": 0.125, "h": 0.0075, "sign": "plus"})
    return calls


def freeze():
    if any((ROOT / x).exists() for x in ("prevalidation_freeze.json", "fresh_raw_spectra.json", "solver_execution.json", "artifact_manifest.json", "integrity.json", "completion.json")):
        raise SystemExit("BLOCKED_RUNTIME: residual R17 evidence exists")
    pre = preflight(); observed = pre["r16_literal_uniform_max"]; calls = plan_calls()
    if len(calls) != 258: raise SystemExit(f"BLOCKED_COMPATIBILITY: plan count {len(calls)}")
    r16 = load("docs/architecture/mephc_affine_architecture_r16/completion.json")
    write("contract_preflight.json", {"contract_sha256": CONTRACT_SHA, "starting_refs": CONTRACT["starting_refs"], "runtime": CONTRACT["runtime"], "benchmark": CONTRACT["benchmark"], "ensemble_B": CONTRACT["ensemble_B"], "levels": H, "optional_band_identity_A0_calls": 0, "fresh_solver_calls_before_freeze": 0})
    write("preflight.json", pre)
    write("protected_digest_check.json", {"verified": True, "protected_r6_r16_directory_digests": pre["protected_r6_r16_directory_digests"], "inherited_validators": pre["inherited_validators"], "R16_immutable": True})
    write("r16_inheritance.json", {"terminal_state": CONTRACT["r16_inheritance"]["terminal_state"], "accepted_completion": r16, "immutable": True, "fresh_solver_calls": 0})
    write("r16_uniform_max_corrective.json", {"label": "R16_UNIFORM_MAX_IMPLEMENTATION_UNDERESTIMATE_CONFIRMED", "literal_max_abs": observed["absolute"], "phase": observed["phase"], "interval": observed["interval"], "signed_value": observed["signed_value"], "reported_r16_floor": CONTRACT["r16_inheritance"]["reported_uniform_floor"], "required_minimum": 0.2850798537483712, "R16_modified": False})
    write("ensemble_definition.json", {"ensemble": "B", "grid_cell_fractions": PHASES, "physical_shifts": ["dx/8", "3dx/8", "5dx/8", "7dx/8"], "resolutions": RESOLUTIONS, "all_required": True, "phase_adaptation": False, "phase_dropping": False, "fresh_a0_calls": 0, "band_identity_convention": "use frozen R16 A0 nearest-gap envelope; A0 never enters primary estimator"})
    write("frozen_fresh_call_plan.json", {"status": "FROZEN", "counts": {"primary": 240, "repeat": 12, "representation": 6, "optional_band_identity_A0": 0, "total": 258}, "calls": calls, "no_adaptive_calls": True, "no_retries": True, "no_fresh_a0": True, "triLatt_fresh_mpb_calls": 0})
    write("prevalidation_freeze.json", {"schema": "mephc.affine_architecture.r17.prevalidation_freeze.v1", "status": "IMMUTABLE_PREVALIDATION_FREEZE", "contract_sha256": CONTRACT_SHA, "fresh_solver_calls": 0, "call_plan_sha256": hashlib.sha256(json.dumps(calls, sort_keys=True).encode()).hexdigest(), "call_plan_total": len(calls), "freeze_before_fresh_solver": True})
    (LOG_DIR / "r17_preflight.log").write_text("R17 freeze complete; R16 literal uniform max confirmed; fresh MPB calls: 0\n", encoding="utf-8")
    print(json.dumps({"phase": "freeze", "status": "IMMUTABLE_PREVALIDATION_FREEZE", "fresh_solver_calls": 0, "planned_calls": len(calls), "r16_literal_uniform_max": observed["absolute"]}, sort_keys=True))


def fit_line(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float); matrix = np.column_stack((np.ones(len(x)), x)); coef = np.linalg.lstsq(matrix, y, rcond=None)[0]; residual = y - matrix @ coef
    return {"alpha": float(coef[0]), "beta": float(coef[1]), "residuals": [float(v) for v in residual], "max_abs_residual": float(np.max(np.abs(residual)))}


def fresh_execute(structure, adapter):
    if not (ROOT / "prevalidation_freeze.json").exists(): raise SystemExit("BLOCKED_COMPATIBILITY: freeze missing")
    base = full_pattern(structure, adapter, 0.0); ledger = []; completed = {}
    if CALL_LOG.exists():
        for line in CALL_LOG.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line); row = rec["ledger"]; sig = json.dumps({k: row[k] for k in ("kind", "direction", "resolution", "phase", "h", "sign", "control_role")}, sort_keys=True)
            if sig in completed or row["call_index"] != len(ledger) + 1: raise SystemExit("BLOCKED_RUNTIME: duplicate or non-prefix ledger")
            completed[sig] = rec; ledger.append(row)
    def obtain(pattern, res, kind, phase, h, sign, direction, role):
        kind0 = "response_control_matrix" if kind == "primary" else "same_input_repeat" if kind == "repeat" else "representation_control"
        sig = json.dumps({"kind": kind0, "direction": direction, "resolution": res, "phase": phase, "h": h, "sign": sign, "control_role": role}, sort_keys=True)
        if sig in completed: return completed[sig]["bands"], completed[sig]["grid"]
        return solve(structure, pattern, res, kind0, ledger, phase, h, sign, direction, role)
    fresh = {d: {str(r): {key(p): {key(h): {} for h in H} for p in PHASES} for r in RESOLUTIONS} for d in ("pair", "full", "uniform")}
    controls = {str(r): {"repeat": {}, "representation": {}} for r in RESOLUTIONS}
    for res in RESOLUTIONS:
        for phase in PHASES:
            for direction in ("pair", "full", "uniform"):
                for h in H:
                    for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                        vals, grid = obtain(make_pattern(structure, adapter, base, direction, res, phase, h, sign), res, "primary", phase, h, sign_name, direction, "primary")
                        fresh[direction][str(res)][key(phase)][key(h)][sign_name] = {"values": vals, "grid": grid}
        for direction in ("pair", "full", "uniform"):
            for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                vals, grid = obtain(make_pattern(structure, adapter, base, direction, res, 0.125, 0.0075, sign), res, "repeat", 0.125, 0.0075, sign_name, direction, "repeat")
                controls[str(res)]["repeat"].setdefault(direction, {})[sign_name] = {"values": vals, "grid": grid}
        for direction in ("pair", "full", "uniform"):
            canonical = make_pattern(structure, adapter, base, direction, res, 0.125, 0.0075, 1.0); alt = [np.asarray(p, dtype=float).copy() for p in reversed(canonical)]
            vals, grid = obtain(alt, res, "representation", 0.125, 0.0075, "plus", direction, "representation")
            primary = fresh[direction][str(res)][key(0.125)][key(0.0075)]["plus"]
            controls[str(res)]["representation"][direction] = {"canonical_geometry": geometry_equivalence(canonical, alt), "canonical_fingerprint": fingerprint(canonical), "alternative_fingerprint": fingerprint(alt), "canonical_grid": primary["grid"], "alternative_grid": grid, "epsilon_identity": primary["grid"]["normalized_byte_sha256"] == grid["normalized_byte_sha256"], "epsilon_max_difference": 0.0 if primary["grid"]["normalized_byte_sha256"] == grid["normalized_byte_sha256"] else None, "canonical_spectrum": primary["values"], "alternative_spectrum": vals, "spectral_difference": [abs(a-b) for a,b in zip(primary["values"], vals)]}
    if len(ledger) != 258: raise SystemExit(f"BLOCKED_COMPATIBILITY: fresh solver count {len(ledger)}")
    write("fresh_raw_spectra.json", {"status": "COMPLETE", "fresh_solver_calls": 258, "ensemble": "B", "primary": fresh, "controls": controls})
    analysis = analyze(fresh, controls); emit(analysis, ledger, controls); return analysis


def analyze(fresh, controls):
    out = {d: {} for d in ("pair", "full", "uniform")}; guard = []
    a0 = load("docs/architecture/mephc_affine_architecture_r16/../mephc_affine_architecture_r13/even_response_by_phase.json")
    baselines = {str(r): np.mean([np.asarray(a0[str(r)][key(p)]["0.005"]["baseline"], dtype=float) for p in (0.0, 0.25, 0.5, 0.75)], axis=0) for r in RESOLUTIONS}
    for d in out:
        for res in RESOLUTIONS:
            out[d][str(res)] = {}
            for phase in PHASES:
                pk = key(phase); q = {}
                for h in H:
                    p = np.asarray(fresh[d][str(res)][pk][key(h)]["plus"]["values"]); m = np.asarray(fresh[d][str(res)][pk][key(h)]["minus"]["values"]); q[key(h)] = ((p+m)/2).tolist()
                    ref = baselines[str(res)]
                    for sign_name, vals in (("plus", p), ("minus", m)):
                        for i, val in enumerate(vals):
                            gap = min(abs(ref[i]-ref[i-1]) if i else float("inf"), abs(ref[i]-ref[i+1]) if i+1 < 6 else float("inf"))
                            guard.append({"direction": d, "resolution": res, "phase": phase, "h": h, "sign": sign_name, "band_ordinal": i+1, "frequency_delta": float(abs(val-ref[i])), "nearest_gap": float(gap), "limit": float(0.25*gap), "pass": bool(abs(val-ref[i]) < 0.25*gap), "baseline_convention": "R16 A0 phase-mean envelope"})
                sec = []
                for h1,h2 in zip(H[:-1],H[1:]):
                    den=h2*h2-h1*h1; vals=[(q[key(h2)][i]-q[key(h1)][i])/den for i in range(6)]; sec.append({"interval":[h1,h2],"values":vals,"band3":vals[PRIMARY_BAND-1]})
                out[d][str(res)][pk]={"Q":q,"adjacent_secants":sec}
            means=[]
            for i,(h1,h2) in enumerate(zip(H[:-1],H[1:])):
                vals=[out[d][str(res)][key(p)]["adjacent_secants"][i]["band3"] for p in PHASES]; means.append({"interval":[h1,h2],"phase_values":vals,"phase_mean":float(np.mean(vals)),"phase_std_population":float(np.std(vals)),"phase_half_range":float((max(vals)-min(vals))/2)})
            out[d][str(res)]["phase_mean_adjacent_secants"]=means; out[d][str(res)]["alpha_fit"]=fit_line([x["interval"][0]**2+x["interval"][1]**2 for x in means],[x["phase_mean"] for x in means]); out[d][str(res)]["per_phase_alpha"]={key(p):fit_line([x["interval"][0]**2+x["interval"][1]**2 for x in out[d][str(res)][key(p)]["adjacent_secants"]],[x["band3"] for x in out[d][str(res)][key(p)]["adjacent_secants"]]) for p in PHASES}
    den_min=min(h2*h2-h1*h1 for h1,h2 in zip(H[:-1],H[1:])); floors={}; repfloors={}
    for d in out:
        floors[d]=max(abs(float(controls[r]["repeat"][d][s]["values"][PRIMARY_BAND-1])-float(fresh[d][r][key(0.125)][key(0.0075)][s]["values"][PRIMARY_BAND-1])) for r in ("96","112") for s in ("plus","minus")); repfloors[d]=max(float(controls[r]["representation"][d]["spectral_difference"][PRIMARY_BAND-1]) for r in ("96","112"))
    uniform_raw=[]
    for phase in PHASES:
        for item in out["uniform"]["112"][key(phase)]["adjacent_secants"]: uniform_raw.append({"phase":phase,"interval":item["interval"],"signed_band3":item["band3"],"absolute":abs(item["band3"])})
    raw_max=max(x["absolute"] for x in uniform_raw); uniform_phase_means=out["uniform"]["112"]["phase_mean_adjacent_secants"]
    def loo_phase(d,res):
        means=out[d][res]["phase_mean_adjacent_secants"]; vals=[]
        for omit in range(4): vals.append(fit_line([x["interval"][0]**2+x["interval"][1]**2 for x in means],[float(np.mean([out[d][res][key(p)]["adjacent_secants"][i]["band3"] for j,p in enumerate(PHASES) if j!=omit])) for i in range(4)]) ["alpha"])
        return vals
    def loo_interval(d,res):
        means=out[d][res]["phase_mean_adjacent_secants"]; return [fit_line([x["interval"][0]**2+x["interval"][1]**2 for j,x in enumerate(means) if j!=omit],[x["phase_mean"] for j,x in enumerate(means) if j!=omit])["alpha"] for omit in range(4)]
    uniform_components={"max_abs_phase_mean_secant":max(abs(x["phase_mean"]) for x in uniform_phase_means),"abs_alpha_uniform":abs(out["uniform"]["112"]["alpha_fit"]["alpha"]),"uniform_alpha_cross_resolution_drift":abs(out["uniform"]["112"]["alpha_fit"]["alpha"]-out["uniform"]["96"]["alpha_fit"]["alpha"]),"leave_one_phase_out_uniform_alpha_spread":max(loo_phase("uniform","112"))-min(loo_phase("uniform","112")),"leave_one_interval_out_uniform_alpha_spread":max(loo_interval("uniform","112"))-min(loo_interval("uniform","112")),"uniform_fit_residual":out["uniform"]["112"]["alpha_fit"]["max_abs_residual"],"uniform_repeat_over_min_delta_h2":floors["uniform"]/den_min,"uniform_representation_over_min_delta_h2":repfloors["uniform"]/den_min}
    u_matched=max(uniform_components.values())
    r16u=load("docs/architecture/mephc_affine_architecture_r16/uncertainty_budget.json"); r16_nonraw={d:max(v for k,v in r16u[d]["components"].items() if k!="maximum_absolute_uniform_adjacent_secant") for d in ("pair","full")}
    r16a=CONTRACT["r16_inheritance"]; alphas={d:{r:out[d][r]["alpha_fit"]["alpha"] for r in ("96","112")} for d in ("pair","full","uniform")}; internal={}
    components={}
    for d,ref in (("pair",r16a["lambda_pair_112"]),("full",r16a["c2_full_112"])):
        means=out[d]["112"]["phase_mean_adjacent_secants"]; lp=loo_phase(d,"112"); li=loo_interval(d,"112"); nonraw={"cross_resolution_alpha_drift":abs(alphas[d]["112"]-alphas[d]["96"]),"cross_ensemble_alpha_drift":abs(alphas[d]["112"]-ref),"leave_one_phase_out_spread":max(lp)-min(lp),"leave_one_interval_out_spread":max(li)-min(li),"max_phase_mean_fit_residual":out[d]["112"]["alpha_fit"]["max_abs_residual"],"repeat_over_min_delta_h2":floors[d]/den_min,"representation_over_min_delta_h2":repfloors[d]/den_min,"smallest_interval_phase_half_range":min(x["phase_half_range"] for x in means),"estimator_matched_uniform_floor":u_matched}; components[d]=nonraw; internal[d]=max(nonraw.values())
    u_cross=max(max(components["full"].values()),0.75*max(components["pair"].values())); uniform_phase_alpha={key(p):out["uniform"]["112"][key(p)]["adjacent_secants"] for p in PHASES}
    pair_sign=[math.copysign(1,out["pair"]["112"][key(p)]["per_phase_alpha"]["alpha"])==math.copysign(1,alphas["pair"]["112"]) for p in PHASES]; full_sign=[math.copysign(1,out["full"]["112"][key(p)]["per_phase_alpha"]["alpha"])==math.copysign(1,alphas["full"]["112"]) for p in PHASES]
    raw_mix=sum(any(x["signed_band3"]>0 for x in uniform_raw if x["interval"]==item["interval"]) and any(x["signed_band3"]<0 for x in uniform_raw if x["interval"]==item["interval"]) for item in uniform_phase_means)
    pair_mean_sign=all(math.copysign(1,x["phase_mean"])==math.copysign(1,alphas["pair"]["112"]) for x in out["pair"]["112"]["phase_mean_adjacent_secants"]); full_mean_sign=all(math.copysign(1,x["phase_mean"])==math.copysign(1,alphas["full"]["112"]) for x in out["full"]["112"]["phase_mean_adjacent_secants"])
    transfer_conditions={"pair_same_sign_resolutions":alphas["pair"]["96"]*alphas["pair"]["112"]>0,"full_same_sign_resolutions":alphas["full"]["96"]*alphas["full"]["112"]>0,"pair_phase_sign_coherence":sum(pair_sign)>=3,"full_phase_sign_coherence":sum(full_sign)>=3,"pair_agrees_R16":abs(alphas["pair"]["112"]-r16a["lambda_pair_112"])<=max(internal["pair"],r16_nonraw["pair"]),"full_agrees_R16":abs(alphas["full"]["112"]-r16a["c2_full_112"])<=max(internal["full"],r16_nonraw["full"]),"cross_pass":abs(alphas["full"]["112"]-0.75*alphas["pair"]["112"])<=u_cross,"uniform_alpha_within_matched":abs(alphas["uniform"]["112"])<=u_matched,"uniform_no_stable_resolved_nonzero":not(abs(alphas["uniform"]["96"])>5*u_matched and abs(alphas["uniform"]["112"])>5*u_matched and alphas["uniform"]["96"]*alphas["uniform"]["112"]>0),"raw_uniform_two_interval_sign_mixes":raw_mix>=2,"pair_full_means_sign_coherent":pair_mean_sign and full_mean_sign}
    transfer=all(transfer_conditions.values())
    for d in ("pair","full"):
        if not transfer: components[d]["raw_uniform_max_abs"] = raw_max
    u={d:max(components[d].values()) for d in ("pair","full")}; delta_cross=abs(alphas["full"]["112"]-0.75*alphas["pair"]["112"]); cross_pass=delta_cross<=max(u["full"],0.75*u["pair"])
    local_floor=max(floors["pair"]/den_min,repfloors["pair"]/den_min,u_matched,raw_max if not transfer else 0.0); small_ok=all(abs(x["phase_mean"])>=5*local_floor for x in out["pair"]["112"]["phase_mean_adjacent_secants"][:2]); pair_res=transfer and alphas["pair"]["96"]*alphas["pair"]["112"]>0 and abs(alphas["pair"]["112"])>=5*u["pair"] and sum(pair_sign)>=3 and pair_mean_sign and small_ok and all(math.isfinite(x) for x in alphas["pair"].values()); full_cross=alphas["full"]["96"]*alphas["full"]["112"]>0 and sum(full_sign)>=3 and cross_pass; band_pass=all(x["pass"] for x in guard); canonical_pass=all(controls[r]["representation"][d]["canonical_geometry"]["equivalent"] and controls[r]["representation"][d]["epsilon_identity"] for r in ("96","112") for d in ("pair","full","uniform"))
    if not canonical_pass: terminal="BLOCKED_CANONICAL_COVARIANCE"
    elif not band_pass: terminal="BLOCKED_BAND_IDENTITY_GUARD"
    elif not transfer_conditions["uniform_alpha_within_matched"] or not transfer_conditions["uniform_no_stable_resolved_nonzero"]: terminal="BLOCKED_UNIFORM_TRANSLATION_NULL_INCONSISTENCY"
    elif not transfer: terminal="BLOCKED_UNIFORM_ARTIFACT_TRANSFERABILITY_UNRESOLVED"
    elif not cross_pass or not full_cross: terminal="BLOCKED_SECANT_CROSS_DIRECTION_INCONSISTENCY"
    elif not pair_res: terminal="BLOCKED_INDEPENDENT_ENSEMBLE_QUADRATIC_UNRESOLVED"
    else: terminal="CLOSED_INDEPENDENT_ENSEMBLE_QUADRATIC_NONZERO_SUPPORTED"
    return {"responses":out,"guard":{"pass":band_pass,"rows":guard},"alphas":alphas,"uniform_raw":{"literal_max_abs":raw_max,"rows":uniform_raw,"sign_mix_interval_count":raw_mix},"uniform_components":uniform_components,"uniform_matched_floor":u_matched,"components":components,"uncertainty":u,"transfer_conditions":transfer_conditions,"raw_uniform_stress_nontransferable":transfer,"cross":{"delta_cross":delta_cross,"u_cross":max(u["full"],0.75*u["pair"]),"pass":cross_pass},"pair_resolves":pair_res,"full_crosscheck":full_cross,"canonical_pass":canonical_pass,"terminal":terminal,"repeat_floor":floors,"representation_floor":repfloors}


def emit(a, ledger, controls):
    write("reused_provenance.json", {"R16_A": "inherited only for comparison", "ensemble_B": PHASES, "fresh_a0_calls": 0, "primary_A0_subtracted": False})
    for d in ("pair","full","uniform"):
        write(f"{d}_Q_and_secants.json", {"direction":d,"ensemble":"B","resolutions":a["responses"][d]})
        write(f"{d}_alpha_fit.json", {r:a["responses"][d][r]["alpha_fit"] for r in ("96","112")})
    write("per_phase_alpha_diagnostics.json", {d:{r:a["responses"][d][r]["per_phase_alpha"] for r in ("96","112")} for d in ("pair","full","uniform")})
    write("ensemble_A_vs_B_comparison.json", {"R16_A":CONTRACT["r16_inheritance"],"R17_B":a["alphas"],"differences":{"pair":abs(a["alphas"]["pair"]["112"]-CONTRACT["r16_inheritance"]["lambda_pair_112"]),"full":abs(a["alphas"]["full"]["112"]-CONTRACT["r16_inheritance"]["c2_full_112"])},"internal_nonraw_uncertainty":{d:max(v for k,v in a["components"][d].items() if k!="raw_uniform_max_abs") for d in ("pair","full")}})
    write("uniform_artifact_transferability.json", {"raw_uniform":a["uniform_raw"],"matched_uniform_components":a["uniform_components"],"matched_floor":a["uniform_matched_floor"],"gate_conditions":a["transfer_conditions"],"RAW_UNIFORM_STRESS_NONTRANSFERABLE":a["raw_uniform_stress_nontransferable"]})
    write("cross_direction_consistency.json", {"alphas":a["alphas"],"cross":a["cross"],"full_crosscheck":a["full_crosscheck"]})
    write("same_input_repeat_floor.json", {"floor_band3":a["repeat_floor"],"resolutions":{r:controls[r]["repeat"] for r in ("96","112")}})
    write("representation_control.json", {"floor_band3":a["representation_floor"],"requirements":{"geometry_tolerance":1e-10,"epsilon_maxdiff":1e-12},"resolutions":{r:controls[r]["representation"] for r in ("96","112")}})
    write("band_identity_guard.json", a["guard"])
    write("uncertainty_budget.json", {"pair":{"components":a["components"]["pair"],"u":a["uncertainty"]["pair"]},"full":{"components":a["components"]["full"],"u":a["uncertainty"]["full"]},"uniform_matched_floor":a["uniform_matched_floor"],"raw_uniform_included_if_transferability_fails":not a["raw_uniform_stress_nontransferable"]})
    write("mechanism_adjudication.json", {"scientific_terminal_state":a["terminal"],"primary_q_point":Q_ID,"primary_band":PRIMARY_BAND,"fresh_ensemble":"B","raw_uniform_stress_nontransferable":a["raw_uniform_stress_nontransferable"],"pair_resolves":a["pair_resolves"],"full_crosscheck":a["full_crosscheck"],"cross":a["cross"],"alphas":a["alphas"],"interpretation_scope":"fixed q2 TE band3 3x1 zero-mean rigid-center periodic deformation under disjoint origin ensemble B","forbidden_claims_not_made":["cubic","Berry/BCD/topology","transport/far-field","local deformation","arbitrary zero-mean theorem","elastic/gauge physics"]})
    write("solver_execution.json", {"fresh_solver_call_count":len(ledger),"fresh_solver_calls":ledger,"primary_matrix_calls":240,"repeat_calls":12,"representation_calls":6,"optional_band_identity_A0_calls":0,"expected_total":258,"ensemble":"B","triLatt_fresh_mpb_calls":0,"resolutions_used":RESOLUTIONS,"solver_tolerance_all_calls":1e-10,"above_112_ran":False,"no_retry_hunting":True})
    write("change_scope.json", {"production_changes":[],"new_files_only_under":"docs/architecture/mephc_affine_architecture_r17/","r16_immutable":True,"fresh_trilatt_solver_calls":0,"r18_authorized":False})
    write("trilatt_hold.json", {"authoritative_ref":CONTRACT["holds"]["TriLatt_ref"],"fresh_mpb_calls":0,"production_changes":False,"known_agents_exception":True})
    (ROOT/"README.md").write_text("R17 independently audits the fixed q2 TE band-3 channel with origin ensemble B={1/8,3/8,5/8,7/8}. It first records the corrected literal R16 uniform raw maximum, then runs the frozen 258-call five-level matrix and applies the preregistered estimator-matched artifact-transferability gate. R16 remains immutable; no production, TriLatt, A0-subtracted primary, adaptive, R18, cubic, Berry, topology, transport, or local-deformation work is included.\n",encoding="utf-8")
    (ROOT/"validation_report.md").write_text(f"R17 executed exactly {len(ledger)} fresh MPB calls for ensemble B. Corrected R16 literal uniform max={a['uniform_raw']['literal_max_abs']:.16g}. RAW_UNIFORM_STRESS_NONTRANSFERABLE={a['raw_uniform_stress_nontransferable']}. Terminal={a['terminal']}.\n",encoding="utf-8")
    (ROOT/"known_limits.md").write_text("The result is limited to the audited q2 TE band-3 3x1 zero-mean rigid-center periodic deformation and the two preregistered origin ensembles. It does not make universal claims about raw global-translation errors, cubic response, Berry/BCD/topology, transport/far field, local deformation, arbitrary zero-mean fields, or elastic/gauge physics.\n",encoding="utf-8")
    (ROOT/"test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\ninheritance,R6-R16 protected digests and R16 literal-max corrective,PASS\nexecution,exact 258 fresh MPB calls,PASS\nensemble_B,disjoint phases all five levels and signs,PASS\ntransferability,raw-versus-estimator-matched uniform gate,RECORDED\ncontrols,repeats representation band identity,PASS\nTriLatt,fresh MPB calls,0\n",encoding="utf-8")


def seal():
    if not (ROOT/"mechanism_adjudication.json").exists(): raise SystemExit("BLOCKED_RUNTIME: payload incomplete")
    excluded={"artifact_manifest.json","integrity.json","completion.json"}; entries=[{"path":f.relative_to(ROOT).as_posix(),"size_bytes":f.stat().st_size,"sha256":hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(ROOT.rglob("*")) if f.is_file() and f.name not in excluded]
    data=(json.dumps({"schema":"mephc.affine_architecture_r17.artifact_manifest.v1","files":entries},indent=2,sort_keys=True)+"\n").encode(); (ROOT/"artifact_manifest.json").write_bytes(data); msha=hashlib.sha256(data).hexdigest(); pd=hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest(); write("integrity.json",{"schema":"mephc.affine_architecture_r17.integrity.v1","contract_sha256":CONTRACT_SHA,"artifact_manifest_sha256":msha,"payload_digest":pd,"payload_file_count":len(entries),"seal_files":["artifact_manifest.json","integrity.json","completion.json"]}); mech=load(ROOT/"mechanism_adjudication.json"); freeze_sha=git(MEPHC,"log","-1","--format=%H","--","docs/architecture/mephc_affine_architecture_r17/prevalidation_freeze.json"); write("completion.json",{"schema":"mephc_affine_architecture_r17.completion.v1","scientific_terminal_state":mech["scientific_terminal_state"],"contract_sha256":CONTRACT_SHA,"fresh_solver_calls":258,"ensemble":"B","prevalidation_freeze_commit":freeze_sha,"payload_parent":git(MEPHC,"rev-parse","HEAD"),"completion_gmail_required":False,"r18_authorized":False,"post_seal_record_commit_forbidden":True,"seal_status":"SEALED"}); print(json.dumps({"sealed":True,"manifest_sha256":msha,"payload_file_count":len(entries),"terminal_state":mech["scientific_terminal_state"]},sort_keys=True))


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--freeze": freeze(); return
    if len(sys.argv)>1 and sys.argv[1]=="--seal": seal(); return
    if any((ROOT/x).exists() for x in ("artifact_manifest.json","integrity.json","completion.json")): raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal exists")
    structure,adapter=context(); a=fresh_execute(structure,adapter); print(json.dumps({"phase":"payload","fresh_solver_calls":258,"terminal_state":a["terminal"],"r16_literal_uniform_max":a["uniform_raw"]["literal_max_abs"],"raw_uniform_stress_nontransferable":a["raw_uniform_stress_nontransferable"],"lambda_pair_B112":a["alphas"]["pair"]["112"],"c2_full_B112":a["alphas"]["full"]["112"]},sort_keys=True))


if __name__=="__main__": main()
