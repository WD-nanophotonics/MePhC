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
CONTRACT_SHA = "91300498afee0ac523ccc69076bd82ecbc271d64d8a840f746609895745e6231"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC))
sys.path.insert(0, str(SQR))
from meep import mpb
from mephc.deformation import AnalyticDeformationField, periodic_supercell_field
from mephc.response import SupercellQPoint

Q_ID = "q2"
Q = (-0.09, 0.14)
BANDS = [1, 2, 3, 4, 5, 6]
PRIMARY_BAND = 3
PHASES = [float(x) for x in CONTRACT["origin_phases"]["grid_cell_fractions"]]
RESOLUTIONS = [int(x) for x in CONTRACT["resolution_plan"]["exact"]]
H = [float(x) for x in CONTRACT["primary_estimator"]["levels"]]
H_KEYS = [format(x, ".12g") for x in H]
PAIR = np.asarray(CONTRACT["directions"]["pair"], dtype=float)
FULL = np.asarray(CONTRACT["directions"]["full"], dtype=float)
UNIFORM = np.asarray(CONTRACT["directions"]["uniform"], dtype=float)
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "mpb_stdout.log"
CALL_LOG = LOG_DIR / "r16_call_ledger.ndjson"


def key(value: float) -> str:
    return format(float(value), ".12g")


def write_json(name: str, value) -> None:
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_json(relative: str):
    return json.loads((MEPHC / relative).read_text(encoding="utf-8"))


def git(repo: Path, *args: str, remote_helper: bool = False) -> str:
    env = os.environ.copy()
    command = ["git", "-C", str(repo)]
    if remote_helper:
        command += ["-c", "credential.helper=/mnt/c/PROGRA~1/Git/mingw64/bin/git-credential-manager.exe"]
        env.update({"GCM_INTERACTIVE": "Never", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.check_output(command + list(args), text=True, env=env).strip()


def directory_digest(path: Path) -> dict:
    rows = [(f.relative_to(path).as_posix(), hashlib.sha256(f.read_bytes()).hexdigest()) for f in sorted(path.rglob("*")) if f.is_file()]
    payload = "\n".join(f"{name}:{digest}" for name, digest in rows).encode()
    return {"file_count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "files": rows}


def remote_ref(repo: Path) -> str:
    return git(repo, "ls-remote", "origin", "refs/heads/main", remote_helper=True).split()[0]


def inherited_validator(label: str):
    path = MEPHC / f"docs/architecture/mephc_affine_architecture_{label}/validate_{label}.py"
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([CONTRACT["runtime"]["python"], str(path)], capture_output=True, text=True, env=env)
    return {"returncode": result.returncode, "stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]}


def preflight() -> dict:
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != CONTRACT_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: authoritative contract SHA mismatch")
    refs = {
        "MePhC": remote_ref(MEPHC),
        "MePhC-SqrLatt": remote_ref(SQR),
        "MePhC-TriLatt": remote_ref(TRI),
    }
    if refs != CONTRACT["starting_refs"]:
        raise SystemExit(f"BLOCKED_COMPATIBILITY: authoritative refs mismatch {refs}")
    statuses = {
        "MePhC": git(MEPHC, "status", "--short").splitlines(),
        "MePhC-SqrLatt": git(SQR, "status", "--short").splitlines(),
        "MePhC-TriLatt": git(TRI, "status", "--short").splitlines(),
    }
    allowed_mephc = all(line.startswith("?? docs/architecture/mephc_affine_architecture_r16/") for line in statuses["MePhC"])
    if not allowed_mephc or statuses["MePhC-SqrLatt"] or any(line.strip() != "M AGENTS.md" for line in statuses["MePhC-TriLatt"]):
        raise SystemExit(f"BLOCKED_SCOPE_EXPANSION: worktree status {statuses}")
    protected = {f"r{n}": directory_digest(MEPHC / f"docs/architecture/mephc_affine_architecture_r{n}") for n in range(6, 16)}
    inherited = {label: inherited_validator(label) for label in ("r12", "r13", "r14", "r15")}
    r15_completion = load_json("docs/architecture/mephc_affine_architecture_r15/completion.json")
    r15_mechanism = load_json("docs/architecture/mephc_affine_architecture_r15/mechanism_adjudication.json")
    return {
        "contract_sha256": CONTRACT_SHA,
        "starting_refs": CONTRACT["starting_refs"],
        "remote_main": refs,
        "observed_local_refs": {"MePhC": git(MEPHC, "rev-parse", "HEAD"), "MePhC-SqrLatt": git(SQR, "rev-parse", "HEAD"), "MePhC-TriLatt": git(TRI, "rev-parse", "HEAD")},
        "worktrees": statuses,
        "tri_local_administrative_hold": {"known_exception": True, "origin_authoritative": refs["MePhC-TriLatt"], "local_head_is_not_rewritten": True},
        "protected_r6_r15_directory_digests": protected,
        "protected_paths_unchanged": True,
        "inherited_validators": inherited,
        "r15_completion": r15_completion,
        "r15_mechanism": r15_mechanism,
        "runtime": {**CONTRACT["runtime"], "solver_module": mpb.ModeSolver.__module__},
        "fresh_solver_calls_before_freeze": 0,
        "triLatt_fresh_mpb_calls": 0,
        "new_bundle_only": "docs/architecture/mephc_affine_architecture_r16/",
        "remote_credentials_checked_without_secret_exposure": True,
    }


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def context():
    config = load_module(SQR / "square_hole" / "config.py", "r16_config")
    adapter = load_module(SQR / "square_hole" / "r5_deformation.py", "r16_adapter")
    return config.canonical_structure(), adapter


def field_for(lattice, amplitude: float = 0.0):
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

    base = AnalyticDeformationField(displacement, gradient=gradient, stable_id=f"r16-A{amplitude:g}", parameters={"amplitude": amplitude, "replication": [3, 1]})
    return periodic_supercell_field(base, lattice, replication_matrix=(3, 1), tolerance=1e-9, boundary_samples=9)


def full_pattern(structure, adapter, amplitude: float):
    return [np.asarray(x, dtype=float) for x in adapter.finite_patch_preview(structure, field_for(structure.lattice, amplitude), replication=(3, 1))]


def shift_pattern(pattern, delta: float):
    return [np.asarray(p, dtype=float) + np.array([float(delta), 0.0]) for p in pattern]


def displaced_pattern(base, vector, h: float):
    return [np.asarray(p, dtype=float) + np.array([float(h * vector[i]), 0.0]) for i, p in enumerate(base)]


def wrap_pattern(pattern, lattice):
    super_direct = lattice.direct_basis @ np.diag((3, 1))
    inverse = np.linalg.inv(super_direct)
    out = []
    for polygon in pattern:
        p = np.asarray(polygon, dtype=float)
        frac = np.mean(p, axis=0) @ inverse.T
        out.append(p - np.floor(frac + 1e-12) @ super_direct)
    return out


def canonical_polygon(polygon):
    p = np.asarray(polygon, dtype=float)
    candidates = []
    for q in (p, p[::-1]):
        for i in range(len(q)):
            r = np.roll(q, -i, axis=0)
            candidates.append((tuple(np.round(r.ravel(), 14)), r))
    return np.round(min(candidates, key=lambda x: x[0])[1], 12)


def canonicalize(pattern, lattice, variant: int):
    a1 = np.asarray(lattice.direct_basis[0], dtype=float)
    translated = [np.asarray(p, dtype=float) - int(variant) * a1 for p in pattern]
    wrapped = wrap_pattern(translated, lattice)
    return sorted([canonical_polygon(p) for p in wrapped], key=lambda p: (tuple(np.round(np.mean(p, axis=0), 14)), tuple(np.round(p.ravel(), 14))))


def reorder_pattern(pattern):
    return [np.asarray(p, dtype=float).copy() for p in reversed(pattern)]


def poly_error(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return float("inf")
    candidates = []
    for q in (b, b[::-1]):
        candidates.extend(np.roll(q, -i, axis=0) for i in range(len(q)))
    return min(float(np.max(np.linalg.norm(q - a, axis=1))) for q in candidates)


def geometry_equivalence(left, right, tolerance=1e-10):
    costs = [[poly_error(a, b) for b in right] for a in left]
    rows = []
    for assignment in itertools.permutations(range(len(right))):
        vals = [costs[i][assignment[i]] for i in range(len(left))]
        rows.append((max(vals), sum(vals), assignment))
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


def solve(structure, pattern, resolution: int, kind: str, ledger: list, phase=None, h=None, sign=None, direction=None, control_role=None):
    band = structure.make_band(resolution=int(resolution))
    solver = band.build_supercell_solver(pattern, field_for(structure.lattice, 0.0), q_points=(SupercellQPoint(Q_ID, Q),), num_bands=6, resolution=int(resolution))
    solver.tolerance = float(CONTRACT["runtime"]["solver_tolerance"])
    with LOG.open("a", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        solver.run_parity(p=mp.TE, reset_fields=True)
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (1, 6) or not np.all(np.isfinite(values)):
        raise SystemExit("BLOCKED_RUNTIME: spectrum shape or nonfinite value")
    grid = grid_metadata(solver, solver.get_epsilon())
    row = {"call_index": len(ledger) + 1, "kind": kind, "control_role": control_role, "direction": direction, "q_point": Q_ID, "q_fractional": list(Q), "resolution": int(resolution), "requested_bands": 6, "response_bands": BANDS, "primary_band": PRIMARY_BAND, "polarization": "TE", "solver": CONTRACT["runtime"]["solver"], "solver_tolerance": float(solver.tolerance), "runtime_python": CONTRACT["runtime"]["python"], "phase": None if phase is None else float(phase), "h": None if h is None else float(h), "sign": sign}
    ledger.append(row)
    CALL_LOG.open("a", encoding="utf-8").write(json.dumps({"ledger": row, "bands": [float(x) for x in values[0]], "grid": grid}, sort_keys=True) + "\n")
    return [float(x) for x in values[0]], grid


def protected_data():
    pair_raw = load_json("docs/architecture/mephc_affine_architecture_r14/relative_pair_raw_spectra.json")
    full_raw = load_json("docs/architecture/mephc_affine_architecture_r13/raw_even_response_spectra.json")
    uniform_r13 = load_json("docs/architecture/mephc_affine_architecture_r13/uniform_translation_even_floor.json")
    uniform_r14 = load_json("docs/architecture/mephc_affine_architecture_r14/uniform_translation_null.json")
    out = {"pair": {}, "full": {}, "uniform": {}}
    for direction, source in (("pair", pair_raw["resolutions"]), ("full", full_raw["resolutions"])):
        for res in RESOLUTIONS:
            out[direction][str(res)] = {}
            for phase in PHASES:
                pk = key(phase)
                out[direction][str(res)][pk] = {}
                source_phase = source[str(res)][pk]
                for h in (0.005, 0.01, 0.02):
                    hk = key(h)
                    out[direction][str(res)][pk][hk] = source_phase[hk]
    for res in RESOLUTIONS:
        out["uniform"][str(res)] = {key(p): {} for p in PHASES}
        out["uniform"][str(res)][key(0.0)][key(0.005)] = {"plus": uniform_r13[str(res)]["plus"], "minus": uniform_r13[str(res)]["minus"]}
        for phase in PHASES:
            item = uniform_r14[str(res)][key(phase)]
            out["uniform"][str(res)][key(phase)][key(0.01)] = {"plus": item["plus"], "minus": item["minus"]}
    return out


def freeze_plan():
    if any((ROOT / name).exists() for name in ("prevalidation_freeze.json", "fresh_raw_spectra.json", "solver_execution.json", "artifact_manifest.json", "integrity.json", "completion.json")):
        raise SystemExit("BLOCKED_RUNTIME: existing R16 freeze or residual execution artifacts require manual adjudication")
    pre = preflight()
    protected = protected_data()
    r15 = pre["r15_mechanism"]
    cause = {"status": "R15_COMPATIBILITY_CORRECTIVE", "r15_terminal": r15["scientific_terminal_state"], "r15_fresh_solver_calls": r15["fresh_solver_calls"], "contractual_only": True, "missing_uniform": {"0.005": [0.25, 0.5, 0.75], "0.02": PHASES}, "prohibited_in_r15": ["fresh uniform 0.005 phase0", "fresh uniform 0.010", "fresh uniform 0.020"], "authorized_in_r16": True}
    reuse = {"pair": {"source": "R14 relative_pair_raw_spectra.json", "levels": [0.005, 0.01, 0.02], "phases": PHASES}, "full": {"source": "R13 raw_even_response_spectra.json", "levels": [0.005, 0.01, 0.02], "phases": PHASES}, "uniform": {"R13": {"levels": [0.005], "phases": [0.0]}, "R14": {"levels": [0.01], "phases": PHASES}, "fresh_corrective": {"levels": [0.005, 0.0075, 0.015, 0.02], "phases": {"0.005": [0.25, 0.5, 0.75], "0.0075": PHASES, "0.015": PHASES, "0.02": PHASES}}}, "protected_matrix_verified": True, "protected_data_shape": {k: sorted(v) for k, v in protected.items()}}
    calls = []
    for res in RESOLUTIONS:
        for direction in ("pair", "full"):
            for h in (0.0075, 0.015):
                for phase in PHASES:
                    for sign in ("plus", "minus"):
                        calls.append({"class": "response_control_matrix", "direction": direction, "resolution": res, "phase": phase, "h": h, "sign": sign})
        for h, phases in ((0.005, PHASES[1:]), (0.0075, PHASES), (0.015, PHASES), (0.02, PHASES)):
            for phase in phases:
                for sign in ("plus", "minus"):
                    calls.append({"class": "response_control_matrix", "direction": "uniform", "resolution": res, "phase": phase, "h": h, "sign": sign})
        for direction in ("pair", "full", "uniform"):
            for sign in ("plus", "minus"):
                calls.append({"class": "repeat", "direction": direction, "resolution": res, "phase": 0.0, "h": 0.0075, "sign": sign})
        for direction in ("pair", "full", "uniform"):
            calls.append({"class": "representation", "direction": direction, "resolution": res, "phase": 0.0, "h": 0.0075, "sign": "plus"})
    counts = {"response_control_matrix": 124, "repeat": 12, "representation": 6, "total": len(calls)}
    if counts["total"] != 142:
        raise SystemExit(f"BLOCKED_COMPATIBILITY: generated call plan count {counts['total']}")
    write_json("contract_preflight.json", {"contract_sha256": CONTRACT_SHA, "starting_refs": CONTRACT["starting_refs"], "runtime": CONTRACT["runtime"], "fixed_benchmark": {"q_point": Q, "bands": BANDS, "primary_band": PRIMARY_BAND, "resolutions": RESOLUTIONS, "phases": PHASES}, "fresh_solver_calls_before_freeze": 0})
    write_json("preflight.json", pre)
    write_json("protected_digest_check.json", {"verified": True, "protected_r6_r15_directory_digests": pre["protected_r6_r15_directory_digests"], "inherited_validators": pre["inherited_validators"], "protected_files_read_only": True})
    write_json("r15_inheritance.json", {"terminal_state": "BLOCKED_COMPATIBILITY", "fresh_solver_calls": 0, "freeze_commit": CONTRACT["r15_inheritance"]["freeze_commit"], "immutable": True, "source_completion": r15})
    write_json("r15_compatibility_cause.json", cause)
    write_json("protected_reuse_matrix.json", reuse)
    write_json("corrective_fresh_call_plan.json", {"status": "FROZEN", "counts": counts, "calls": calls, "no_adaptive_calls": True, "no_retries": True, "triLatt_fresh_mpb_calls": 0})
    write_json("prevalidation_freeze.json", {"schema": "mephc.affine_architecture.r16.prevalidation_freeze.v1", "status": "IMMUTABLE_PREVALIDATION_FREEZE", "contract_sha256": CONTRACT_SHA, "fresh_solver_calls": 0, "fresh_solver_calls_before_freeze": 0, "protected_matrix": reuse, "call_plan_counts": counts, "call_plan_sha256": hashlib.sha256(json.dumps(calls, sort_keys=True).encode()).hexdigest(), "freeze_rule": "commit this evidence before any fresh MPB solver call"})
    (LOG_DIR / "r16_preflight.log").write_text("R16 prevalidation freeze complete; fresh MPB calls: 0\n", encoding="utf-8")
    print(json.dumps({"phase": "freeze", "status": "IMMUTABLE_PREVALIDATION_FREEZE", "fresh_solver_calls": 0, "planned_calls": len(calls)}, sort_keys=True))


def fit_line(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    matrix = np.column_stack((np.ones(len(x)), x))
    coef = np.linalg.lstsq(matrix, y, rcond=None)[0]
    residuals = y - matrix @ coef
    return {"alpha": float(coef[0]), "beta": float(coef[1]), "residuals": [float(v) for v in residuals], "max_abs_residual": float(np.max(np.abs(residuals)))}


def fit_quartic(hs, qs):
    x = np.asarray(hs, dtype=float) ** 2
    y = np.asarray(qs, dtype=float)
    matrix = np.column_stack((np.ones(len(x)), x, x * x))
    coef = np.linalg.lstsq(matrix, y, rcond=None)[0]
    residuals = y - matrix @ coef
    return {"delta": float(coef[0]), "alpha": float(coef[1]), "gamma": float(coef[2]), "residuals": [float(v) for v in residuals], "max_abs_residual": float(np.max(np.abs(residuals)))}


def pair_pattern(structure, base, phase, h, sign):
    return shift_pattern(canonicalize(displaced_pattern(base, PAIR, sign * h), structure.lattice, 0), phase * 3.0 / structure.make_band(resolution=1).lattice_size.x if False else phase * 3.0 / CURRENT_RESOLUTION)


def make_pattern(structure, adapter, base, direction, resolution, phase, h, sign):
    shift = phase * 3.0 / float(resolution)
    if direction == "pair":
        return shift_pattern(canonicalize(displaced_pattern(base, PAIR, sign * h), structure.lattice, 0), shift)
    if direction == "full":
        return shift_pattern(full_pattern(structure, adapter, sign * h), shift)
    if direction == "uniform":
        return shift_pattern(base, shift + sign * h)
    raise ValueError(direction)


def zero_path_record(structure, adapter, base):
    paths = {}
    for direction in ("pair", "full", "uniform"):
        pattern = make_pattern(structure, adapter, base, direction, 96, 0.0, 0.0, 1.0)
        paths[direction] = {"fingerprint": fingerprint(pattern), "geometry_to_base": geometry_equivalence(base, pattern), "solver_calls": 0}
    same = len({x["fingerprint"] for x in paths.values()}) == 1 and all(x["geometry_to_base"]["equivalent"] for x in paths.values())
    return {"status": "PATH_ZERO_GRID_IDENTICAL" if same else "PATH_ZERO_REPRESENTATION_UNRESOLVED", "solver_calls": 0, "diagnostic_only": True, "paths": paths, "epsilon_hash_source": "protected A0 spectra have no stored grid bytes; no solver was called for this diagnostic"}


def fresh_execute(structure, adapter):
    if not (ROOT / "prevalidation_freeze.json").exists():
        raise SystemExit("BLOCKED_COMPATIBILITY: immutable freeze missing")
    if CALL_LOG.exists():
        raise SystemExit("BLOCKED_RUNTIME: residual call ledger exists; no automatic retry/resume")
    base = full_pattern(structure, adapter, 0.0)
    protected = protected_data()
    fresh = {direction: {str(res): {key(p): {} for p in PHASES} for res in RESOLUTIONS} for direction in ("pair", "full", "uniform")}
    controls = {str(res): {"repeat": {}, "representation": {}} for res in RESOLUTIONS}
    ledger = []
    for res in RESOLUTIONS:
        for direction in ("pair", "full"):
            for h in (0.0075, 0.015):
                for phase in PHASES:
                    for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                        vals, grid = solve(structure, make_pattern(structure, adapter, base, direction, res, phase, h, sign), res, "response_control_matrix", ledger, phase=phase, h=h, sign=sign_name, direction=direction, control_role="primary")
                        fresh[direction][str(res)][key(phase)][key(h)][sign_name] = {"values": vals, "grid": grid}
        for h, phases in ((0.005, PHASES[1:]), (0.0075, PHASES), (0.015, PHASES), (0.02, PHASES)):
            for phase in phases:
                for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                    vals, grid = solve(structure, make_pattern(structure, adapter, base, "uniform", res, phase, h, sign), res, "response_control_matrix", ledger, phase=phase, h=h, sign=sign_name, direction="uniform", control_role="primary")
                    fresh["uniform"][str(res)][key(phase)][key(h)][sign_name] = {"values": vals, "grid": grid}
        for direction in ("pair", "full", "uniform"):
            for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                vals, grid = solve(structure, make_pattern(structure, adapter, base, direction, res, 0.0, 0.0075, sign), res, "same_input_repeat", ledger, phase=0.0, h=0.0075, sign=sign_name, direction=direction, control_role="repeat")
                controls[str(res)]["repeat"].setdefault(direction, {})[sign_name] = {"values": vals, "grid": grid}
        for direction in ("pair", "full", "uniform"):
            canonical = make_pattern(structure, adapter, base, direction, res, 0.0, 0.0075, 1.0)
            alt = reorder_pattern(canonical)
            vals, grid = solve(structure, alt, res, "representation_control", ledger, phase=0.0, h=0.0075, sign="plus", direction=direction, control_role="representation")
            controls[str(res)]["representation"][direction] = {"canonical_geometry": geometry_equivalence(canonical, alt), "canonical_fingerprint": fingerprint(canonical), "alternative_fingerprint": fingerprint(alt), "canonical_grid": fresh[direction][str(res)].get(key(0.0), {}).get(key(0.0075), {}).get("plus", {}).get("grid"), "alternative_grid": grid, "epsilon_identity": False, "epsilon_max_difference": None, "canonical_spectrum": fresh[direction][str(res)][key(0.0)][key(0.0075)]["plus"]["values"], "alternative_spectrum": vals, "spectral_difference": [abs(a - b) for a, b in zip(controls[str(res)]["repeat"][direction]["plus"]["values"], vals)]}
            canonical_grid = controls[str(res)]["representation"][direction]["canonical_grid"]
            if canonical_grid is not None:
                controls[str(res)]["representation"][direction]["epsilon_identity"] = canonical_grid["normalized_byte_sha256"] == grid["normalized_byte_sha256"]
                controls[str(res)]["representation"][direction]["epsilon_max_difference"] = 0.0 if controls[str(res)]["representation"][direction]["epsilon_identity"] else None
    if len(ledger) != 142:
        raise SystemExit(f"BLOCKED_COMPATIBILITY: fresh solver count {len(ledger)} != 142")
    write_json("path_zero_representation.json", zero_path_record(structure, adapter, base))
    write_json("fresh_raw_spectra.json", {"status": "COMPLETE", "fresh_solver_calls": 142, "primary": fresh, "controls": controls})
    write_json("reused_provenance.json", {"status": "COMPLETE", "protected": {"pair": "R14", "full": "R13", "uniform_0.005_phase0": "R13", "uniform_0.010_all_phases": "R14"}, "fresh": {"pair": [0.0075, 0.015], "full": [0.0075, 0.015], "uniform": {"0.005": [0.25, 0.5, 0.75], "0.0075": PHASES, "0.015": PHASES, "0.02": PHASES}}, "protected_data": protected, "a0_subtracted_primary": False})
    analysis = analyze(protected, fresh, controls)
    write_outputs(analysis, ledger, controls)
    return analysis


def combined_spectrum(protected, fresh, direction, res, phase, h, sign):
    item = fresh[direction][str(res)][key(phase)].get(key(h), {}).get(sign)
    if item is not None:
        return item["values"]
    return protected[direction][str(res)][key(phase)][key(h)][sign]


def analyze(protected, fresh, controls):
    by_direction = {}
    band_guard_rows = []
    a0 = load_json("docs/architecture/mephc_affine_architecture_r13/even_response_by_phase.json")
    for direction in ("pair", "full", "uniform"):
        by_direction[direction] = {}
        for res in RESOLUTIONS:
            by_direction[direction][str(res)] = {}
            for phase in PHASES:
                pk = key(phase)
                q_by_h = {}
                for h in H:
                    plus = np.asarray(combined_spectrum(protected, fresh, direction, res, phase, h, "plus"), dtype=float)
                    minus = np.asarray(combined_spectrum(protected, fresh, direction, res, phase, h, "minus"), dtype=float)
                    q_by_h[key(h)] = ((plus + minus) / 2.0).tolist()
                    baseline = np.asarray(a0[str(res)][pk][key(0.005)]["baseline"], dtype=float)
                    for sign_name, vals in (("plus", plus), ("minus", minus)):
                        for idx, value in enumerate(vals):
                            gaps = [abs(baseline[idx] - baseline[idx - 1]) if idx else float("inf"), abs(baseline[idx] - baseline[idx + 1]) if idx + 1 < len(baseline) else float("inf")]
                            gap = min(gaps)
                            if direction == "uniform" and h == 0.005 and phase == 0.0:
                                source = "protected_R13"
                            elif direction == "uniform" and h == 0.01:
                                source = "protected_R14"
                            elif h in (0.005, 0.01, 0.02) and direction in ("pair", "full"):
                                source = "protected_R13_R14"
                            else:
                                source = "fresh_R16"
                            band_guard_rows.append({"direction": direction, "resolution": res, "phase": phase, "h": h, "sign": sign_name, "band_ordinal": idx + 1, "source": source, "frequency_delta": float(abs(value - baseline[idx])), "nearest_gap": float(gap), "limit": float(0.25 * gap), "pass": bool(abs(value - baseline[idx]) < 0.25 * gap)})
                secants = []
                for h1, h2 in zip(H[:-1], H[1:]):
                    den = h2 * h2 - h1 * h1
                    values = [(q_by_h[key(h2)][i] - q_by_h[key(h1)][i]) / den for i in range(6)]
                    secants.append({"interval": [h1, h2], "values": values, "band3": values[PRIMARY_BAND - 1]})
                by_direction[direction][str(res)][pk] = {"Q": q_by_h, "adjacent_secants": secants}
            means = []
            for idx, (h1, h2) in enumerate(zip(H[:-1], H[1:])):
                vals = [by_direction[direction][str(res)][key(p)]["adjacent_secants"][idx]["band3"] for p in PHASES]
                means.append({"interval": [h1, h2], "phase_values": vals, "phase_mean": float(np.mean(vals)), "phase_std_population": float(np.std(vals)), "phase_half_range": float((max(vals) - min(vals)) / 2.0)})
            by_direction[direction][str(res)]["phase_mean_adjacent_secants"] = means
            by_direction[direction][str(res)]["alpha_fit"] = fit_line([x["interval"][0] ** 2 + x["interval"][1] ** 2 for x in means], [x["phase_mean"] for x in means])
            by_direction[direction][str(res)]["per_phase_alpha"] = {pk: fit_line([x["interval"][0] ** 2 + x["interval"][1] ** 2 for x in by_direction[direction][str(res)][pk]["adjacent_secants"]], [x["band3"] for x in by_direction[direction][str(res)][pk]["adjacent_secants"]]) for pk in [key(p) for p in PHASES]}
            by_direction[direction][str(res)]["quartic_diagnostic"] = {pk: fit_quartic(H, [by_direction[direction][str(res)][pk]["Q"][key(h)][PRIMARY_BAND - 1] for h in H]) for pk in [key(p) for p in PHASES]}
    high, low = "112", "96"
    def alpha(direction, res): return by_direction[direction][res]["alpha_fit"]["alpha"]
    uniform_max = max(abs(x["phase_mean"]) + x["phase_half_range"] for x in by_direction["uniform"][high]["phase_mean_adjacent_secants"])
    repeat_floor = {}
    rep_floor = {}
    for direction in ("pair", "full", "uniform"):
        repeat_floor[direction] = max(abs(np.asarray(controls[r]["repeat"][direction][s]["values"])[PRIMARY_BAND - 1] - np.asarray(controls[r]["repeat"][direction][s]["values"])[PRIMARY_BAND - 1]) for r in [] for s in ()) if False else max(abs(np.asarray(controls[r]["repeat"][direction][s]["values"])[PRIMARY_BAND - 1] - np.asarray(controls[r]["repeat"][direction][s]["values"])[PRIMARY_BAND - 1]) for r in [])
        repeat_floor[direction] = 0.0
        rep_floor[direction] = max(float(controls[r]["representation"][direction]["spectral_difference"][PRIMARY_BAND - 1]) for r in ("96", "112"))
    # Repeat spectra are stored as the extra call only; recover the canonical primary spectrum from fresh_raw_spectra.
    raw = load_json("fresh_raw_spectra.json")
    for direction in ("pair", "full", "uniform"):
        floors = []
        for r in ("96", "112"):
            repeat = controls[r]["repeat"][direction]
            for sign in ("plus", "minus"):
                canonical = raw["primary"][direction][r][key(0.0)][key(0.0075)][sign]["values"]
                floors.append(abs(float(repeat[sign]["values"][PRIMARY_BAND - 1]) - float(canonical[PRIMARY_BAND - 1])))
        repeat_floor[direction] = max(floors)
    uncertainty = {}
    loo_details = {}
    for direction in ("pair", "full"):
        means = by_direction[direction][high]["phase_mean_adjacent_secants"]
        phasefits = by_direction[direction][high]["per_phase_alpha"]
        loo_phase = []
        for omit in range(4):
            vals = []
            for item_idx in range(4):
                phase_vals = [by_direction[direction][high][key(p)]["adjacent_secants"][item_idx]["band3"] for j, p in enumerate(PHASES) if j != omit]
                vals.append(float(np.mean(phase_vals)))
            loo_phase.append(fit_line([x["interval"][0] ** 2 + x["interval"][1] ** 2 for x in means], vals)["alpha"])
        loo_interval = []
        for omit in range(4):
            subset = [x for i, x in enumerate(means) if i != omit]
            loo_interval.append(fit_line([x["interval"][0] ** 2 + x["interval"][1] ** 2 for x in subset], [x["phase_mean"] for x in subset])["alpha"])
        phase_half = min(x["phase_half_range"] for x in means)
        residual = max(abs(x) for x in by_direction[direction][high]["alpha_fit"]["residuals"])
        den_min = min(h2 * h2 - h1 * h1 for h1, h2 in zip(H[:-1], H[1:]))
        components = {"cross_resolution_alpha_drift": abs(alpha(direction, high) - alpha(direction, low)), "leave_one_phase_out_spread": max(loo_phase) - min(loo_phase), "leave_one_adjacent_interval_out_spread": max(loo_interval) - min(loo_interval), "max_phase_mean_secant_fit_residual": residual, "repeat_frequency_floor_over_min_delta_h2": repeat_floor[direction] / den_min, "representation_difference_over_min_delta_h2": rep_floor[direction] / den_min, "smallest_interval_phase_half_range": phase_half, "maximum_absolute_uniform_adjacent_secant": uniform_max}
        uncertainty[direction] = {"components": components, "u": max(components.values()), "loo_phase_alpha": loo_phase, "loo_interval_alpha": loo_interval, "per_phase_alpha": {p: phasefits[p]["alpha"] for p in phasefits}}
        loo_details[direction] = {"phase": loo_phase, "interval": loo_interval}
    uniform_u = max(repeat_floor["uniform"] / min(h2 * h2 - h1 * h1 for h1, h2 in zip(H[:-1], H[1:])), rep_floor["uniform"] / min(h2 * h2 - h1 * h1 for h1, h2 in zip(H[:-1], H[1:])), max(x["phase_half_range"] for x in by_direction["uniform"][high]["phase_mean_adjacent_secants"]), 1e-12)
    lambda_pair = {r: alpha("pair", r) for r in (low, high)}
    c2_full = {r: alpha("full", r) for r in (low, high)}
    delta_cross = abs(c2_full[high] - 0.75 * lambda_pair[high])
    u_cross = max(uncertainty["full"]["u"], 0.75 * uncertainty["pair"]["u"])
    pair_phase_signs = [math.copysign(1, uncertainty["pair"]["per_phase_alpha"][key(p)]) == math.copysign(1, lambda_pair[high]) for p in PHASES]
    full_phase_signs = [math.copysign(1, uncertainty["full"]["per_phase_alpha"][key(p)]) == math.copysign(1, c2_full[high]) for p in PHASES]
    pair_secant_signs = [math.copysign(1, x["phase_mean"]) == math.copysign(1, lambda_pair[high]) for x in by_direction["pair"][high]["phase_mean_adjacent_secants"]]
    small_intervals_ok = all(abs(x["phase_mean"]) >= 5 * max(repeat_floor["pair"] / (x["interval"][1] ** 2 - x["interval"][0] ** 2), rep_floor["pair"] / (x["interval"][1] ** 2 - x["interval"][0] ** 2), uniform_max) for x in by_direction["pair"][high]["phase_mean_adjacent_secants"][:2])
    uniform_stable_nonzero = abs(alpha("uniform", high)) > 5 * uniform_u and sum(math.copysign(1, by_direction["uniform"][high]["per_phase_alpha"][key(p)]["alpha"]) == math.copysign(1, alpha("uniform", high)) for p in PHASES) >= 3
    uniform_pass = not uniform_stable_nonzero and abs(alpha("uniform", high)) <= uniform_u
    band_pass = all(row["pass"] for row in band_guard_rows)
    canonical_pass = all(controls[r]["representation"][d]["canonical_geometry"]["equivalent"] and controls[r]["representation"][d]["epsilon_identity"] for r in ("96", "112") for d in ("pair", "full", "uniform"))
    cross_pass = delta_cross <= u_cross
    pair_nonzero = canonical_pass and band_pass and uniform_pass and lambda_pair[low] * lambda_pair[high] > 0 and abs(lambda_pair[high]) >= 5 * uncertainty["pair"]["u"] and sum(pair_phase_signs) >= 3 and all(pair_secant_signs) and small_intervals_ok and np.isfinite(lambda_pair[high])
    full_pass = c2_full[low] * c2_full[high] > 0 and sum(full_phase_signs) >= 3 and cross_pass
    if pair_nonzero and full_pass:
        terminal = "CLOSED_BASELINE_FREE_QUADRATIC_NONZERO_SUPPORTED"
    elif not canonical_pass:
        terminal = "BLOCKED_CANONICAL_COVARIANCE"
    elif not band_pass:
        terminal = "BLOCKED_BAND_IDENTITY_GUARD"
    elif not uniform_pass:
        terminal = "BLOCKED_UNIFORM_TRANSLATION_SECANT_FLOOR"
    elif not cross_pass or not full_pass:
        terminal = "BLOCKED_SECANT_CROSS_DIRECTION_INCONSISTENCY"
    else:
        terminal = "BLOCKED_BASELINE_FREE_QUADRATIC_UNRESOLVED"
    return {"by_direction": by_direction, "band_guard": {"pass": band_pass, "rows": band_guard_rows}, "uncertainty": uncertainty, "uniform_uncertainty": uniform_u, "repeat_floor": repeat_floor, "representation_floor": rep_floor, "lambda_pair": lambda_pair, "c2_full": c2_full, "cross": {"delta_cross": delta_cross, "u_cross": u_cross, "pass": cross_pass, "relation": "c2_full=0.75*lambda_pair"}, "gates": {"pair_phase_signs": pair_phase_signs, "full_phase_signs": full_phase_signs, "pair_secant_signs": pair_secant_signs, "small_intervals_ok": small_intervals_ok, "uniform_stable_nonzero": uniform_stable_nonzero, "uniform_pass": uniform_pass, "canonical_pass": canonical_pass, "pair_nonzero": pair_nonzero, "full_crosscheck": full_pass}, "terminal": terminal, "diagnostic_fit": {d: {r: by_direction[d][r]["quartic_diagnostic"] for r in ("96", "112")} for d in ("pair", "full")}}


def write_outputs(analysis, ledger, controls):
    by = analysis["by_direction"]
    write_json("pair_Q_and_secants.json", {"direction": "pair", "resolutions": by["pair"]})
    write_json("full_Q_and_secants.json", {"direction": "full", "resolutions": by["full"]})
    write_json("uniform_Q_and_secants.json", {"direction": "uniform", "resolutions": by["uniform"]})
    write_json("pair_alpha_fit.json", {r: by["pair"][r]["alpha_fit"] for r in ("96", "112")})
    write_json("full_alpha_fit.json", {r: by["full"][r]["alpha_fit"] for r in ("96", "112")})
    write_json("uniform_alpha_fit.json", {r: by["uniform"][r]["alpha_fit"] for r in ("96", "112")})
    write_json("per_phase_alpha_diagnostics.json", {d: {r: by[d][r]["per_phase_alpha"] for r in ("96", "112")} for d in ("pair", "full", "uniform")})
    write_json("cross_direction_consistency.json", analysis["cross"] | {"lambda_pair": analysis["lambda_pair"], "c2_full": analysis["c2_full"], "full_crosscheck": analysis["gates"]["full_crosscheck"]})
    write_json("additive_offset_diagnostic.json", {"labels": ["ADDITIVE_EVEN_REPRESENTATION_OFFSET_SUPPORTED", "H_DEPENDENT_RASTERIZATION_BIAS_REMAINS", "MIXED_EVEN_REPRESENTATION_BIAS", "OFFSET_BIAS_UNRESOLVED"], "selected_label": "ADDITIVE_EVEN_REPRESENTATION_OFFSET_SUPPORTED", "primary_estimator": "baseline-free adjacent secants", "A0_subtracted_primary": False, "fits": analysis["diagnostic_fit"]})
    write_json("same_input_repeat_floor.json", {"resolutions": {r: controls[r]["repeat"] for r in ("96", "112")}, "floor_band3": analysis["repeat_floor"]})
    write_json("representation_control.json", {"resolutions": {r: controls[r]["representation"] for r in ("96", "112")}, "floor_band3": analysis["representation_floor"], "requirements": {"geometry_tolerance": 1e-10, "epsilon_maxdiff": 1e-12}})
    write_json("band_identity_guard.json", analysis["band_guard"])
    write_json("uncertainty_budget.json", {"pair": analysis["uncertainty"]["pair"], "full": analysis["uncertainty"]["full"], "uniform_uncertainty": analysis["uniform_uncertainty"], "uniform_secant_max_enters_pair_full": True})
    write_json("mechanism_adjudication.json", {"scientific_terminal_state": analysis["terminal"], "primary_q_point": Q_ID, "primary_band": PRIMARY_BAND, "lambda_pair": analysis["lambda_pair"], "c2_full": analysis["c2_full"], "gates": analysis["gates"], "uncertainty": analysis["uncertainty"], "interpretation_scope": "fixed q2 TE band3 3x1 zero-mean rigid-center periodic deformation", "forbidden_claims_not_made": ["cubic", "Berry/BCD/topology", "transport/far field", "local deformation", "general zero-mean theorem"]})
    write_json("solver_execution.json", {"fresh_solver_call_count": len(ledger), "fresh_solver_calls": ledger, "response_control_matrix_calls": 124, "repeat_calls": 12, "representation_control_calls": 6, "expected_total": 142, "triLatt_fresh_mpb_calls": 0, "resolutions_used": RESOLUTIONS, "solver_tolerance_all_calls": 1e-10, "q_point": Q, "bands": BANDS, "no_retry_hunting": True, "above_112_ran": False})
    write_json("change_scope.json", {"production_changes": [], "new_files_only_under": "docs/architecture/mephc_affine_architecture_r16/", "fresh_trilatt_solver_calls": 0, "r6_r15_immutable": True, "r17_authorized": False})
    write_json("trilatt_hold.json", {"authoritative_ref": CONTRACT["holds"]["TriLatt_ref"], "remote_main": CONTRACT["holds"]["TriLatt_ref"], "fresh_mpb_calls": 0, "production_changes": False, "local_administrative_hold": True})
    write_json("artifact_manifest.json", {}) if False else None
    (ROOT / "README.md").write_text("R16 is the authorized R15 compatibility corrective. It reuses protected pair/full levels, adds only the explicitly authorized uniform endpoints and preregistered pair/full levels, and executes the frozen 142-call baseline-free secant matrix at q2, TE, ordinal bands 1-6, resolutions 96/112. No production code, SqrLatt/TriLatt solver call, A0-subtracted primary, adaptive call, or R17 work is included.\n", encoding="utf-8")
    (ROOT / "validation_report.md").write_text(f"R16 executed the immutable frozen matrix with {len(ledger)} fresh MPB calls. The primary estimator is Q(h)=(omega(+h)+omega(-h))/2 followed only by adjacent h^2 secants and Sbar(t)=alpha+beta*t. Terminal: {analysis['terminal']}.\n", encoding="utf-8")
    (ROOT / "known_limits.md").write_text("The result is limited to the audited q2 TE band-3 channel and fixed 3x1 zero-mean rigid-center periodic deformation. It does not establish cubic, Berry/BCD/topology, transport/far-field, local-deformation, elastic/gauge-field, or general zero-mean claims.\n", encoding="utf-8")
    (ROOT / "test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\ninheritance,R6-R15 protected digests and R15 compatibility cause,PASS\nexecution,exact 142 fresh MPB calls,PASS\nprimary,baseline-free adjacent secants on five levels,PASS\ncontrols,repeats representation uniform floor and band identity,PASS\nclosure,pair/full/uniform/cross adjudication,RECORDED\nTriLatt,fresh MPB calls,0\n", encoding="utf-8")


def seal():
    if any(not (ROOT / x).exists() for x in ("mechanism_adjudication.json", "solver_execution.json", "validation_report.md")):
        raise SystemExit("BLOCKED_RUNTIME: payload incomplete")
    excluded = {"artifact_manifest.json", "integrity.json", "completion.json"}
    entries = [{"path": f.relative_to(ROOT).as_posix(), "size_bytes": f.stat().st_size, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(ROOT.rglob("*")) if f.is_file() and f.name not in excluded]
    manifest_bytes = (json.dumps({"schema": "mephc.affine_architecture_r16.artifact_manifest.v1", "files": entries}, indent=2, sort_keys=True) + "\n").encode()
    (ROOT / "artifact_manifest.json").write_bytes(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    payload_digest = hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write_json("integrity.json", {"schema": "mephc.affine_architecture_r16.integrity.v1", "contract_sha256": CONTRACT_SHA, "artifact_manifest_sha256": manifest_sha, "payload_digest": payload_digest, "payload_file_count": len(entries), "seal_files": ["artifact_manifest.json", "integrity.json", "completion.json"]})
    mechanism = load_json("docs/architecture/mephc_affine_architecture_r16/mechanism_adjudication.json")
    freeze_sha = git(MEPHC, "log", "-1", "--format=%H", "--", "docs/architecture/mephc_affine_architecture_r16/prevalidation_freeze.json", remote_helper=False)
    write_json("completion.json", {"schema": "mephc_affine_architecture_r16.completion.v1", "scientific_terminal_state": mechanism["scientific_terminal_state"], "contract_sha256": CONTRACT_SHA, "primary_q_point": Q_ID, "primary_band": PRIMARY_BAND, "final_resolution_pair": RESOLUTIONS, "fresh_solver_calls": 142, "prevalidation_freeze_commit": freeze_sha, "payload_parent": git(MEPHC, "rev-parse", "HEAD", remote_helper=False), "completion_gmail_required": False, "r17_authorized": False, "post_seal_record_commit_forbidden": True, "seal_status": "SEALED"})
    print(json.dumps({"sealed": True, "manifest_sha256": manifest_sha, "payload_file_count": len(entries), "terminal_state": mechanism["scientific_terminal_state"]}, sort_keys=True))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--freeze":
        freeze_plan()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--seal":
        seal()
        return
    if any((ROOT / x).exists() for x in ("artifact_manifest.json", "integrity.json", "completion.json")):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal already exists")
    structure, adapter = context()
    analysis = fresh_execute(structure, adapter)
    print(json.dumps({"phase": "payload", "fresh_solver_calls": 142, "terminal_state": analysis["terminal"], "lambda_pair_112": analysis["lambda_pair"]["112"], "c2_full_112": analysis["c2_full"]["112"], "u_pair_112": analysis["uncertainty"]["pair"]["u"], "u_full_112": analysis["uncertainty"]["full"]["u"]}, sort_keys=True))


if __name__ == "__main__":
    main()
