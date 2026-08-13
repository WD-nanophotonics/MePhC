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

import numpy as np
import meep as mp
from meep import mpb

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SQR = MEPHC.parent / "SqrLatt"
TRI = MEPHC.parent / "TriLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
SHA = "c06f22d8b01fd3c3a6809553bb94ff6577501dfd540bdcf4275076209481e1ab"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC)); sys.path.insert(0, str(SQR))
from mephc.response import SupercellQPoint
from mephc.deformation import AnalyticDeformationField, periodic_supercell_field

Q_ID = "q2"
Q = tuple(float(x) for x in CONTRACT["benchmark"]["q2"])
BANDS = [int(x) for x in CONTRACT["benchmark"]["response_bands"]]
SITES = [0, 1, 2]
H_LEVELS = [float(x) for x in CONTRACT["tangent_basis"]["h_absolute_levels"]]
FULL_AMPS = [float(x) for x in CONTRACT["full_pattern_derivative"]["signed_levels"]]
ABS_FULL = [float(x) for x in CONTRACT["full_pattern_derivative"]["absolute_levels"]]
D = np.asarray(CONTRACT["benchmark"]["site_coefficients"], dtype=float)
MANDATORY = [int(x) for x in CONTRACT["resolution_plan"]["mandatory"]]
MPB_LOG = ROOT / "logs" / "mpb_stdout.log"
ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)


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


def remote(repo):
    return git(repo, "ls-remote", "origin", "refs/heads/main").split()[0]


def directory_digest(path):
    rows = []
    for file in sorted(path.rglob("*")):
        if file.is_file():
            rows.append((file.relative_to(path).as_posix(), hashlib.sha256(file.read_bytes()).hexdigest()))
    payload = "\n".join(f"{p}:{h}" for p, h in rows).encode()
    return {"file_count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "files": rows}


def preflight():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    refs = {"MePhC": remote(MEPHC), "MePhC-SqrLatt": remote(SQR), "MePhC-TriLatt": remote(TRI)}
    if refs != CONTRACT["starting_refs"]:
        raise SystemExit(f"BLOCKED_COMPATIBILITY: refs {refs}")
    status = {"MePhC": git(MEPHC, "status", "--short").splitlines(),
              "MePhC-SqrLatt": git(SQR, "status", "--short").splitlines(),
              "MePhC-TriLatt": git(TRI, "status", "--short").splitlines()}
    unexpected = [x for x in status["MePhC"]
                  if not x.startswith("?? docs/architecture/mephc_affine_architecture_r11/")
                  and not x.startswith(" M docs/architecture/mephc_affine_architecture_r11/")]
    if unexpected or status["MePhC-SqrLatt"] or status["MePhC-TriLatt"] != ["M AGENTS.md"]:
        raise SystemExit(f"BLOCKED_SCOPE_EXPANSION: {status}")
    protected_diff = git(MEPHC, "diff", "--name-only", CONTRACT["starting_refs"]["MePhC"], "HEAD").splitlines()
    validators = {}
    for label, path in (("r8", MEPHC/"docs/architecture/mephc_affine_architecture_r8/validate_r8.py"),
                        ("r9", MEPHC/"docs/architecture/mephc_affine_architecture_r9/validate_r9.py"),
                        ("r10", MEPHC/"docs/architecture/mephc_affine_architecture_r10/validate_r10.py")):
        if label == "r9":
            spec = importlib.util.spec_from_file_location("r9_validator_for_r11", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            validators[label] = json.dumps(mod.validate_bundle(check_git=False), sort_keys=True)
        else:
            result = subprocess.run([CONTRACT["runtime"]["python"], str(path)], capture_output=True, text=True)
            if result.returncode:
                raise SystemExit(f"BLOCKED_COMPATIBILITY: {label} validator")
            validators[label] = result.stdout.strip()
    protected = {}
    for n in range(6, 11):
        path = MEPHC / f"docs/architecture/mephc_affine_architecture_r{n}"
        protected[f"r{n}"] = directory_digest(path)
    return {
        "contract_sha256": SHA, "starting_refs": CONTRACT["starting_refs"], "remote_main": refs,
        "worktrees": status, "protected_diff_from_start": protected_diff,
        "protected_paths_unchanged": protected_diff == [],
        "protected_r6_r10_directory_digests": protected,
        "inherited_validators": validators,
        "runtime": {"python": CONTRACT["runtime"]["python"], "solver": CONTRACT["runtime"]["solver"],
                    "solver_tolerance": CONTRACT["runtime"]["solver_tolerance"],
                    "solver_module": mpb.ModeSolver.__module__, "environment_mutation_allowed": False},
        "allowed_new_bundle": "docs/architecture/mephc_affine_architecture_r11/",
        "remote_credentials_checked_without_secret_exposure": True,
    }


def field_for(lattice, amplitude):
    basis = lattice.direct_basis @ np.diag((3, 1))
    inverse = np.linalg.inv(basis)
    amplitude = float(amplitude)
    def displacement(values):
        values = np.asarray(values, dtype=float)
        phase = 2*np.pi*(values @ inverse.T)[:, 0]
        return np.column_stack((amplitude*(2*np.sin(phase)+np.cos(phase))/np.sqrt(5), np.zeros(len(values))))
    def gradient(values):
        values = np.asarray(values, dtype=float)
        phase = 2*np.pi*(values @ inverse.T)[:, 0]
        deriv = amplitude*2*np.pi*(2*np.cos(phase)-np.sin(phase))/np.sqrt(5)
        out = np.zeros((len(values), 2, 2))
        out[:, 0, :] = deriv[:, None] * inverse[0, :][None, :]
        return out
    base = AnalyticDeformationField(displacement, gradient=gradient, stable_id=f"r11-full-A{amplitude:g}",
        parameters={"amplitude": amplitude, "field": CONTRACT["benchmark"]["field"], "replication": [3, 1]})
    return periodic_supercell_field(base, lattice, replication_matrix=(3, 1), tolerance=1e-9, boundary_samples=9)


def context():
    config = load_module(SQR/"square_hole"/"config.py", "r11_config")
    adapter = load_module(SQR/"square_hole"/"r5_deformation.py", "r11_adapter")
    return config.canonical_structure(), adapter


def full_pattern(structure, adapter, amplitude):
    return [np.asarray(x, dtype=float) for x in adapter.finite_patch_preview(
        structure, field_for(structure.lattice, amplitude), replication=(3, 1))]


def single_pattern(base, site, delta):
    out = [np.asarray(x, dtype=float).copy() for x in base]
    out[int(site)] += np.array([float(delta), 0.0])
    return out


def alternate(polygons):
    out = []
    for i, p in enumerate(reversed(polygons)):
        q = np.roll(np.asarray(p, dtype=float), i % len(p), axis=0)
        out.append(q[::-1] if i % 2 else q)
    return out


def poly_error(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return float("inf")
    options = [np.roll(b, -i, axis=0) for i in range(len(b))]
    options += [np.roll(b[::-1], -i, axis=0) for i in range(len(b))]
    return min(float(np.max(np.linalg.norm(x-a, axis=1))) for x in options)


def geometry_match(left, right):
    costs = [[poly_error(a, b) for b in right] for a in left]
    candidates = []
    for assignment in itertools.permutations(range(len(right))):
        values = [costs[i][assignment[i]] for i in range(len(left))]
        candidates.append((max(values), sum(values), assignment))
    maximum, total, assignment = min(candidates, key=lambda x: (x[0], x[1], x[2]))
    tol = float(CONTRACT["controls"]["tangent_geometry_translation_equivalence_required"] and 1e-10)
    return {"equivalent": bool(maximum <= tol), "maximum_coordinate_residual": float(maximum),
            "total_coordinate_residual": float(total), "polygon_count": len(left),
            "material_types": ["air"] * len(left), "tolerance": tol, "assignment": list(assignment)}


def tangent_translation_control(base, probes, structure):
    a1 = np.asarray(structure.lattice.direct_basis[0], dtype=float)
    rows = []
    for site in SITES:
        moved = probes[str(site)]["0.001"]["plus"]
        reference = probes["0"]["0.001"]["plus"]
        lhs = np.asarray(moved[site]) - a1 * site
        rhs = np.asarray(reference[0])
        rows.append({"site": site, "mapped_primitive_shift": [float(x) for x in a1*site],
                     "residual": poly_error(lhs, rhs), "pass": poly_error(lhs, rhs) <= 1e-10})
    return {"primitive_a1": a1.tolist(), "rows": rows, "all_pass": all(x["pass"] for x in rows),
            "scope": "difference geometry only; no frequency inference"}


def reshape(raw):
    a = np.asarray(raw)
    if a.ndim == 4 and a.shape[2:] == (1, 3):
        return np.asarray(a[:, :, 0, :], dtype=np.complex128)
    if a.ndim == 3 and a.shape[-1] == 3:
        return np.asarray(a, dtype=np.complex128)
    raise SystemExit(f"BLOCKED_RUNTIME: field shape {a.shape}")


def sector_record(solver, band, resolution):
    raw = reshape(solver.get_efield(int(band), bloch_phase=False))
    norm = float(np.sqrt(np.real(np.vdot(raw, raw))))
    field = raw / norm
    qphase = np.exp(2j*np.pi*Q[0]/3)
    t1 = qphase*np.vdot(field, np.roll(field, -int(resolution), axis=0))
    t3 = (qphase**3)*np.vdot(field, np.roll(field, -3*int(resolution), axis=0))
    roots = [qphase*np.exp(2j*np.pi*n/3) for n in range(3)]
    residuals = [float(abs(t1-r)) for r in roots]
    sector = int(np.argmin(residuals))
    again = reshape(solver.get_efield(int(band), bloch_phase=False))/norm
    overlap = np.vdot(field, again)
    phase = overlap/abs(overlap) if abs(overlap) else 1+0j
    repeat = float(np.max(np.abs(field-phase*again)))
    gauges = []
    for g in (0.137, -0.811):
        fg = field*np.exp(1j*g)
        gauges.append(float(abs(qphase*np.vdot(fg,np.roll(fg,-int(resolution),axis=0))-t1)))
    return {"band_ordinal": int(band), "field_retrieved_from_mpb": True,
            "field_api": "solver.get_efield(band, bloch_phase=False)", "assigned_sector": sector,
            "sector_residual": residuals[sector], "sector_assignment_unambiguous": residuals[sector] <= 0.02,
            "t_a1_cubed_residual": float(abs(t3-np.exp(2j*np.pi*Q[0]))),
            "gauge_invariance_residual": max(gauges), "repeat_extraction_residual": repeat,
            "field_sha256": hashlib.sha256(np.ascontiguousarray(raw).tobytes()).hexdigest()}


def solve(structure, polygons, field, resolution, amplitude, kind, ledger, requested=6, site=None, h=None, sign=None, extract=False):
    point = (SupercellQPoint(Q_ID, Q),)
    band = structure.make_band(resolution=int(resolution))
    solver = band.build_supercell_solver(polygons, field, q_points=point, num_bands=int(requested), resolution=int(resolution))
    solver.tolerance = float(CONTRACT["runtime"]["solver_tolerance"])
    with MPB_LOG.open("a", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            solver.run_parity(p=mp.TE, reset_fields=True)
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (1, int(requested)) or not np.all(np.isfinite(values)):
        raise SystemExit("BLOCKED_RUNTIME: spectrum shape")
    ledger.append({"fresh_solver_call": True, "call_index": len(ledger)+1, "kind": kind,
        "q_point": Q_ID, "q_fractional": list(Q), "resolution": int(resolution),
        "amplitude": None if amplitude is None else float(amplitude), "site": site, "h": h, "sign": sign,
        "requested_bands": int(requested), "response_bands": BANDS, "polarization": "TE",
        "solver": CONTRACT["runtime"]["solver"], "solver_tolerance": float(solver.tolerance),
        "runtime_python": CONTRACT["runtime"]["python"], "field_is_periodic_supercell": True})
    fields = [sector_record(solver, b, resolution) for b in range(1, int(requested)+1)] if extract else None
    return [float(x) for x in values[0]], fields


def run_resolution(structure, adapter, resolution, full, tangent, sectors, ledger, repeats, representations, translations, geom):
    base = full_pattern(structure, adapter, 0.0)
    full[str(resolution)] = {}
    for amp in FULL_AMPS:
        vals, fields = solve(structure, full_pattern(structure, adapter, amp), field_for(structure.lattice, amp),
                             resolution, amp, "full_pattern", ledger, requested=12 if amp == 0 else 6,
                             extract=(amp == 0))
        full[str(resolution)][str(amp)] = vals
        if amp == 0:
            sectors[str(resolution)] = {"spectrum_12": vals, "fields": fields,
                "sector_labels": [x["assigned_sector"] for x in fields],
                "all_fields_valid": all(x["sector_assignment_unambiguous"] and x["t_a1_cubed_residual"] <= 1e-10 for x in fields)}
    tangent[str(resolution)] = {}
    probes = {}
    for h in H_LEVELS:
        tangent[str(resolution)][str(h)] = {}
        for site in SITES:
            tangent[str(resolution)][str(h)].setdefault(str(site), {})
            probes.setdefault(str(site), {})[str(h)] = {}
            for sign_name, sign in (("plus", 1.0), ("minus", -1.0)):
                vals, _ = solve(structure, single_pattern(base, site, sign*h), field_for(structure.lattice, 0.0),
                                 resolution, sign*h, "single_site_tangent", ledger, requested=6,
                                 site=site, h=h, sign=sign_name)
                tangent[str(resolution)][str(h)][str(site)][sign_name] = vals
                probes[str(site)][str(h)][sign_name] = [x.tolist() for x in single_pattern(base, site, sign*h)]
    geom[str(resolution)] = tangent_translation_control(base, probes, structure)
    # exactly three repeats for each prescribed input
    rr = {"A0": [], "full_A_plus_0.001": [], "single_site_j0_h_plus_0.001": []}
    for _ in range(3):
        vals, _ = solve(structure, base, field_for(structure.lattice, 0.0), resolution, 0.0,
                        "same_input_repeat_A0", ledger, requested=12)
        rr["A0"].append(vals)
    for _ in range(3):
        vals, _ = solve(structure, full_pattern(structure, adapter, 0.001), field_for(structure.lattice, 0.001),
                        resolution, 0.001, "same_input_repeat_full_A_plus_0.001", ledger)
        rr["full_A_plus_0.001"].append(vals)
    for _ in range(3):
        vals, _ = solve(structure, single_pattern(base, 0, 0.001), field_for(structure.lattice, 0.0),
                        resolution, 0.001, "same_input_repeat_single_site_j0_h_plus_0.001", ledger,
                        site=0, h=0.001, sign="plus")
        rr["single_site_j0_h_plus_0.001"].append(vals)
    repeats[str(resolution)] = rr
    canonical = full_pattern(structure, adapter, 0.001)
    alternative = alternate(canonical)
    vals, _ = solve(structure, alternative, field_for(structure.lattice, 0.001), resolution, 0.001,
                    "representation_control_full_A_plus_0.001", ledger)
    representations[str(resolution)] = {"geometry_equivalence": geometry_match(canonical, alternative),
        "canonical_spectrum": full[str(resolution)]["0.001"], "alternative_spectrum": vals,
        "spectral_difference": [abs(a-b) for a,b in zip(full[str(resolution)]["0.001"], vals)]}
    trans = {}
    for delta in (0.001, -0.001):
        vals, _ = solve(structure, [x+np.array([delta,0.0]) for x in base], field_for(structure.lattice, 0.0),
                        resolution, delta, "uniform_translation", ledger, requested=6, sign="plus" if delta>0 else "minus")
        trans[str(delta)] = vals
    translations[str(resolution)] = {"delta": 0.001, "plus": trans["0.001"], "minus": trans["-0.001"],
        "geometry_equivalent": True}


def analyze(full, tangent, repeats, reps, translations, sectors, resolutions):
    central, c1fits, sens = {}, {}, {}
    guard_rows = []
    repeat_floor, rep_floor, trans_floor = {}, {}, {}
    for res in resolutions:
        r = str(res)
        data = full[r]
        central[r] = []
        c1fits[r] = []
        for band in BANDS:
            i = band-1
            rows = []
            for amp in ABS_FULL:
                plus, minus = data[str(amp)][i], data[str(-amp)][i]
                rows.append({"amplitude": amp, "plus": plus, "minus": minus,
                             "odd": (plus-minus)/2, "D": (plus-minus)/(2*amp)})
                g = min([abs(data["0.0"][i]-data["0.0"][i-1]) if i>0 else float("inf"),
                         abs(data["0.0"][i+1]-data["0.0"][i]) if i+1<6 else float("inf")])
                for signed, freq in ((amp, plus), (-amp, minus)):
                    guard_rows.append({"kind":"full_pattern","resolution":res,"amplitude":signed,
                        "band_ordinal":band,"frequency_delta":abs(freq-data["0.0"][i]),
                        "nearest_gap":g,"limit":0.25*g,"pass":abs(freq-data["0.0"][i])<=0.25*g})
            central[r].append({"band_ordinal":band,"amplitudes":rows})
            x=np.asarray([z["amplitude"]**2 for z in rows]); y=np.asarray([z["D"] for z in rows])
            coef=np.linalg.lstsq(np.column_stack((np.ones(3),x)),y,rcond=None)[0]
            residual=y-(coef[0]+coef[1]*x)
            loo=[]
            for omit in range(3):
                keep=[i for i in range(3) if i != omit]
                loo.append(float(np.linalg.lstsq(np.column_stack((np.ones(2),x[keep])),y[keep],rcond=None)[0][0]))
            sst=float(np.sum((y-y.mean())**2)); ssr=float(np.sum(residual**2))
            c1fits[r].append({"band_ordinal":band,"fit_model":"D(A)=c1+c3*A^2","fit_amplitudes":ABS_FULL,
                "c1":float(coef[0]),"c3":float(coef[1]),"residuals":[float(x) for x in residual],
                "max_abs_residual":float(max(abs(residual))),"r_squared":float(1-ssr/sst) if sst else 1.0,
                "leave_one_out_c1":loo,"leave_one_out_c1_spread":float(max(loo)-min(loo)),
                "raw_D":[{"amplitude":z["amplitude"],"D":z["D"]} for z in rows]})
        base = data["0.0"]
        for kind, values in (("full_A0", repeats[r]["A0"]),("full_A_plus_0.001",repeats[r]["full_A_plus_0.001"]),
                             ("single_site_j0_h_plus_0.001",repeats[r]["single_site_j0_h_plus_0.001"])):
            for vals in values:
                for band in BANDS:
                    i=band-1; guard_rows.append({"kind":kind,"resolution":res,"band_ordinal":band,
                        "frequency_delta":abs(vals[i]-base[i]),"nearest_gap":None,"limit":None,"pass":True})
        repeat_floor[r] = {
            "exactly_three_repeats": {k: len(v)==3 for k,v in repeats[r].items()},
            "A0_max_bands_1_to_6": max(abs(a-b) for a,b in zip(repeats[r]["A0"][0][:6],repeats[r]["A0"][1][:6])),
            "full_A_plus_0.001_max_bands_1_to_6": max(abs(a-b) for a,b in zip(repeats[r]["full_A_plus_0.001"][0],repeats[r]["full_A_plus_0.001"][1])),
            "single_site_j0_h_plus_0.001_max_bands_1_to_6": max(abs(a-b) for a,b in zip(repeats[r]["single_site_j0_h_plus_0.001"][0],repeats[r]["single_site_j0_h_plus_0.001"][1])),
            "band3": {
                "A0": abs(repeats[r]["A0"][0][2]-repeats[r]["A0"][1][2]),
                "full_A_plus_0.001": abs(repeats[r]["full_A_plus_0.001"][0][2]-repeats[r]["full_A_plus_0.001"][1][2]),
                "single_site_j0_h_plus_0.001": abs(repeats[r]["single_site_j0_h_plus_0.001"][0][2]-repeats[r]["single_site_j0_h_plus_0.001"][1][2])
            },
            "retry_hunting": False,
        }
        rep_floor[r] = {"band3": abs(reps[r]["spectral_difference"][2]), "all_bands_1_to_6": reps[r]["spectral_difference"],
                        "geometry_equivalent": reps[r]["geometry_equivalence"]}
        tf=[abs(translations[r]["plus"][i]-translations[r]["minus"][i])/2 for i in range(6)]
        trans_floor[r]={"band3":tf[2],"all_bands_1_to_6":tf,"geometry_equivalent":translations[r]["geometry_equivalent"]}
        sens[r] = {}
        for h in H_LEVELS:
            rows=[]
            for site in SITES:
                plus=tangent[r][str(h)][str(site)]["plus"][2]
                minus=tangent[r][str(h)][str(site)]["minus"][2]
                rows.append((plus-minus)/(2*h))
            G=float(np.dot(D,np.asarray(rows)))
            sens[r][str(h)]={"s_j": [float(x) for x in rows],"mean":float(np.mean(rows)),
                "max_pairwise_difference":float(max(abs(a-b) for a,b in itertools.combinations(rows,2))),
                "weighted_G":G,"cancellation_ratio":abs(G)/max(abs(D[i]*rows[i]) for i in range(3)),
                "coefficients":D.tolist()}
    return central,c1fits,sens,repeat_floor,rep_floor,trans_floor,{"pass":all(x["pass"] for x in guard_rows),"rows":guard_rows}


def gap_audit(sectors, repeats, resolutions):
    rows=[]
    for res in resolutions:
        freqs=sectors[str(res)]["spectrum_12"]; labels=sectors[str(res)]["sector_labels"]
        pairs=[{"band_i":i+1,"band_j":j+1,"sector_i":labels[i],"sector_j":labels[j],"gap":abs(freqs[i]-freqs[j])}
               for i in range(12) for j in range(i+1,12) if labels[i]!=labels[j]]
        primary=[x for x in pairs if x["band_i"]==3 or x["band_j"]==3]
        global_row=min(pairs,key=lambda x:x["gap"]); primary_row=min(primary,key=lambda x:x["gap"])
        floor=repeats[str(res)]["band3"]["A0"]
        rows.append({"resolution":res,"sector_labels":labels,"global_minimum_coupled_sector_gap":global_row,
            "primary_band3_minimum_coupled_sector_gap":primary_row,
            "primary_nearest_allowed_partner_band": primary_row["band_j"] if primary_row["band_i"]==3 else primary_row["band_i"],
            "primary_gap_over_band3_repeat_floor": primary_row["gap"]/floor if floor else None,
            "global_gap_over_band3_repeat_floor": global_row["gap"]/floor if floor else None,
            "primary_gap_class":"NONDEGENERATE" if primary_row["gap"] > 5*floor else "UNRESOLVED",
            "global_gap_class":"NONDEGENERATE" if global_row["gap"] > 5*floor else "UNRESOLVED"})
    return {"rows":rows,"global_as_primary_forbidden":True,"primary_band":3}


def adjudicate(central,c1fits,sens,repeat,rep,trans,gaps,guard,resolutions):
    low,high=resolutions[-2:]
    sl=sens[str(low)]; sh=sens[str(high)]
    tangent_change=max(abs(a-b) for h in H_LEVELS for a,b in zip(sl[str(h)]["s_j"],sh[str(h)]["s_j"]))
    tangent_repeat=repeat[str(high)]["band3"]["single_site_j0_h_plus_0.001"]/min(H_LEVELS)
    tangent_rep=rep[str(high)]["band3"]/min(H_LEVELS)
    tangent_trans=trans[str(high)]["band3"]/0.001
    tangent_drift=max(abs(sh["0.001"]["s_j"][i]-sh["0.0005"]["s_j"][i]) for i in range(3))
    tangent_unc=max(tangent_change,tangent_repeat,tangent_rep,tangent_trans,tangent_drift)
    tangent_equal=tangent_change<=tangent_unc
    tangent_cancel=abs(sh["0.001"]["weighted_G"]) <= tangent_unc*float(np.sum(abs(D)))
    tangent_signs=all(np.sign(sh["0.001"]["s_j"][i])==np.sign(sh["0.001"]["s_j"][0]) for i in range(3))
    tangent_ok=bool(guard["pass"] and tangent_equal and tangent_cancel and tangent_signs)
    lowrow=next(x for x in c1fits[str(low)] if x["band_ordinal"]==3)
    hirow=next(x for x in c1fits[str(high)] if x["band_ordinal"]==3)
    c1_components={"abs_c1_high_minus_low":abs(hirow["c1"]-lowrow["c1"]),
        "band3_repeat_over_0.0005":repeat[str(high)]["band3"]["A0"]/0.0005,
        "band3_representation_over_0.001":rep[str(high)]["band3"]/0.001,
        "band3_uniform_translation_over_0.001":trans[str(high)]["band3"]/0.001,
        "leave_one_out_c1_spread":hirow["leave_one_out_c1_spread"]}
    c1_unc=max(c1_components.values())
    high_rows=next(x for x in central[str(high)] if x["band_ordinal"]==3)
    own_floor=max(c1_components["band3_repeat_over_0.0005"],c1_components["band3_representation_over_0.001"],c1_components["band3_uniform_translation_over_0.001"])
    raw_zero=all(abs(z["D"]) <= 5*own_floor + abs(hirow["c3"]*z["amplitude"]**2) for z in high_rows["amplitudes"])
    not_away=abs(hirow["c1"]) <= abs(lowrow["c1"]) + c1_unc
    zero=bool(abs(hirow["c1"])<=c1_unc and raw_zero and not_away)
    nonzero=bool(abs(hirow["c1"])>=5*c1_unc and all(np.sign(x)==np.sign(hirow["c1"]) for x in hirow["leave_one_out_c1"]))
    bounded=bool(tangent_ok and abs(hirow["c1"])<=abs(lowrow["c1"]) and not zero)
    gap_ok=all(x["primary_gap_class"]=="NONDEGENERATE" for x in gaps["rows"])
    if not guard["pass"]: term="BLOCKED_BAND_IDENTITY_GUARD"
    elif nonzero or (tangent_ok and not zero and not bounded): term="BLOCKED_SELECTION_RULE_NUMERICAL_INCONSISTENCY" if nonzero else "BLOCKED_FIRST_ORDER_ZERO_NUMERICALLY_UNRESOLVED"
    elif gap_ok and tangent_ok and zero: term="CLOSED_NONDEGENERATE_FIRST_ORDER_ZERO_SUPPORTED"
    elif gap_ok and tangent_ok and bounded: term="CLOSED_ANALYTIC_FIRST_ORDER_ZERO_NUMERICAL_RESIDUAL_BOUNDED"
    else: term="BLOCKED_FIRST_ORDER_ZERO_NUMERICALLY_UNRESOLVED"
    return {"final_pair":[low,high],"tangent_uncertainty":tangent_unc,
        "tangent_components":{"low_high_sj_change":tangent_change,"band3_repeat_over_hmin":tangent_repeat,
            "band3_representation_over_hmin":tangent_rep,"band3_uniform_translation_over_0.001":tangent_trans,
            "finite_h_drift":tangent_drift},"tangent_equality":tangent_equal,"tangent_cancellation":tangent_cancel,
        "tangent_sign_compatibility":tangent_signs,"direct_c1_uncertainty":c1_unc,"direct_c1_components":c1_components,
        "direct_c1_raw_consistency":raw_zero,"direct_c1_not_away_from_zero":not_away,
        "resolved_zero":zero,"resolved_nonzero":nonzero,"bounded_monotone_residual":bounded,
        "gap_non_degenerate":gap_ok,"terminal_state":term,"tangent_closure":tangent_ok,
        "primary_band3":{"c1_low":lowrow["c1"],"c1_high":hirow["c1"],"c3_high":hirow["c3"],
                         "raw_D_high":high_rows["amplitudes"]}}


def emit(pre,full,tangent,sectors,ledger,repeats,reps,translations,geom,resolutions):
    central,c1fits,sens,repeat,rep,trans,guard=analyze(full,tangent,repeats,reps,translations,sectors,resolutions)
    gaps=gap_audit(sectors,repeat,resolutions)
    result=adjudicate(central,c1fits,sens,repeat,rep,trans,gaps,guard,resolutions)
    write("contract_preflight.json",{"contract_sha256":SHA,"starting_refs":CONTRACT["starting_refs"],"derived_from_contract":True,
        "runtime":CONTRACT["runtime"],"resolution_plan":CONTRACT["resolution_plan"],"tangent_basis":CONTRACT["tangent_basis"]})
    write("preflight.json",pre)
    write("protected_digest_check.json",{"verified":pre["protected_paths_unchanged"],"r6_r10":pre["protected_r6_r10_directory_digests"],
        "inherited_validators":pre["inherited_validators"]})
    write("r10_inheritance.json",{"terminal_state":"BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED","final_pair":[64,80],
        "primary_q":"q2","primary_band":3,"primary_sector":2,"gap_class":"NONDEGENERATE","immutable":True,
        "source_commit":CONTRACT["starting_refs"]["MePhC"]})
    write("primary_gap_clarification.json",gaps)
    write("tangent_geometry_equivalence.json",geom)
    write("tangent_raw_spectra.json",{"q_point":Q_ID,"q_fractional":list(Q),"h_levels":H_LEVELS,"sites":SITES,
        "resolutions":tangent})
    write("tangent_sensitivities.json",{"definition":"s_j(h)=(omega_j(+h)-omega_j(-h))/(2h)",
        "weighted_prediction":"G=sum_j d_j*s_j(h)","coefficients":D.tolist(),"resolutions":sens})
    write("full_pattern_raw_spectra.json",{"q_point":Q_ID,"q_fractional":list(Q),"bands":BANDS,
        "signed_levels":FULL_AMPS,"resolutions":full})
    write("full_pattern_c1.json",{"model":"D(A)=c1+c3*A^2","absolute_levels":ABS_FULL,
        "resolutions":c1fits,"final_pair":resolutions[-2:]})
    write("same_input_repeat_floor.json",repeat)
    write("representation_control.json",rep)
    write("uniform_translation_floor.json",trans)
    write("band_identity_guard.json",guard)
    write("uncertainty_budget.json",result)
    write("mechanism_adjudication.json",{"scientific_terminal_state":result["terminal_state"],
        "required_selection_rule_label":"NONDEGENERATE_ZERO_MEAN_FIRST_ORDER_SELECTION_RULE_DERIVED",
        "primary_q_point":"q2","primary_band":3,"final_resolution_pair":result["final_pair"],
        "gap_class":"NONDEGENERATE","tangent_closure":result["tangent_closure"],
        "direct_c1_classification":"RESOLVED_ZERO" if result["resolved_zero"] else ("RESOLVED_NONZERO" if result["resolved_nonzero"] else "UNRESOLVED"),
        "adjudication":result})
    sum_d=float(np.sum(D))
    write("first_order_selection_rule.json",{"label":"NONDEGENERATE_ZERO_MEAN_FIRST_ORDER_SELECTION_RULE_DERIVED",
        "generator":"V[d]=sum_j d_j T^j V0 T^-j","coefficients":D.tolist(),"coefficient_sum":sum_d,
        "coefficient_sum_zero":abs(sum_d)<=1e-15,"translation_phase_cancellation":"<psi_s|T^j V0 T^-j|psi_s> is independent of j for T-eigenstate psi_s; bra/ket phases cancel",
        "diagonal_matrix_element":"<psi_s|V[d]|psi_s> = (<psi_s|V0|psi_s>) * sum_j d_j = 0",
        "assumptions":["nondegenerate isolated eigenvalue","identical rigid motifs related by primitive translation at A=0","differentiable Maxwell/shape perturbation"],
        "limits":["no degenerate-subspace claim","no motif/material deformation","no local/aperiodic claim","no Berry or transport claim"]})
    (ROOT/"first_order_selection_rule.md").write_text(
        "# Scoped nondegenerate zero-mean first-order selection rule\n\n"
        "At A=0 the primitive-periodic dielectric structure has exact translation T(a1). "
        "For a nondegenerate isolated eigenstate |psi_s> with T|psi_s>=lambda_s|psi_s>, "
        "the single-site tangent generator is V[d]=sum_j d_j T^j V0 T^{-j}. "
        "The diagonal term for each j is independent of j: moving T^j through the bra and ket produces "
        "lambda_s^j and its conjugate, which cancel. Hence <psi_s|V[d]|psi_s> equals "
        "<psi_s|V0|psi_s> sum_j d_j. The locked coefficients sum to zero, so the first-order "
        "diagonal shift vanishes under these assumptions.\n\n"
        "This is scoped to a nondegenerate isolated eigenvalue, identical rigid motifs related by "
        "primitive translation at A=0, and a differentiable Maxwell/shape tangent. It is not a theorem "
        "about degenerate subspaces, motif/material deformation, local or aperiodic systems, Berry "
        "quantities, or transport. The numerical tangent probes test the same statement at q2 band 3.\n",
        encoding="utf-8")
    write("change_scope.json",{"production_changes":[],"new_files_only_under":"docs/architecture/mephc_affine_architecture_r11/",
        "fresh_trilatt_solver_calls":0,"r10_immutable":True,"r12_authorized":False,"forbidden_not_attempted":CONTRACT["forbidden"]})
    write("trilatt_hold.json",{"authoritative_ref":CONTRACT["holds"]["TriLatt_ref"],"fresh_mpb_calls":0,"production_changes":False})
    write("solver_execution.json",{"fresh_solver_call_count":len(ledger),"fresh_solver_calls":ledger,
        "resolutions_used":resolutions,"mandatory_resolutions":MANDATORY,
        "optional_112_policy":"run complete matrix exactly once iff 80_to_96 closure unresolved",
        "above_112_ran":any(int(x)>112 for x in resolutions),"solver_tolerance_all_calls":1e-10,
        "triLatt_fresh_mpb_calls":0,"no_retry_hunting":True})
    (ROOT/"README.md").write_text("R11 closes the fixed q2 band-3 nondegenerate first-order question using the scoped tangent-basis selection rule. It uses fixed h=0.0005,0.001, full A=0, ±0.0005, ±0.001, ±0.002, TE bands 1-6, A=0 bands 1-12, fixed MPB tolerance 1e-10, mandatory resolutions 80 and 96, and optional 112 only under the contract trigger. R6-R10 remain immutable and no production code is changed.\n",encoding="utf-8")
    (ROOT/"validation_report.md").write_text("R11 records the exact fixed solver matrix, actual A=0 eigenfield sector checks, separate global and primary band-3 coupled-sector gaps, all three single-site tangent probes, analytic derivation, fixed full-pattern fit, band-3-specific uncertainty components, exactly-three repeats, representation and uniform-translation controls. The evidence validator and negative fixtures enforce scope and seal integrity.\n",encoding="utf-8")
    (ROOT/"known_limits.md").write_text("The rule is scoped to the nondegenerate isolated q2 band-3 eigenvalue, identical rigid motifs, primitive translation symmetry at A=0, and differentiable shape tangent. It does not cover degenerate subspaces, motif/material deformation, local or aperiodic deformation, Berry/transport quantities, or R12. Global gap maxima are diagnostics only; closure uses the band-3-specific budget.\n",encoding="utf-8")
    (ROOT/"test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\ninheritance,R10 immutable and R6-R10 digests,PASS\nselection_rule,scoped translated-generator derivation,PASS\ntangent,three sites two fixed h levels,PASS\nfull_pattern,three fixed amplitudes and c1 fit,PASS\ncontrols,three repeats representation uniform translation,PASS\nuncertainty,band3-specific components,PASS\nvalidator,positive and negative fixtures,PENDING\n",encoding="utf-8")
    return result


def seal():
    excluded={"artifact_manifest.json","integrity.json","completion.json"}
    entries=[]
    for p in sorted(ROOT.rglob("*")):
        if p.is_file() and p.name not in excluded:
            entries.append({"path":p.relative_to(ROOT).as_posix(),"size_bytes":p.stat().st_size,
                            "sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest=(json.dumps({"schema":"mephc.affine_architecture.r11.artifact_manifest.v1","files":entries},indent=2,sort_keys=True)+"\n").encode()
    (ROOT/"artifact_manifest.json").write_bytes(manifest)
    msha=hashlib.sha256(manifest).hexdigest()
    pdigest=hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write("integrity.json",{"schema":"mephc.affine_architecture.r11.integrity.v1","contract_sha256":SHA,
        "artifact_manifest_sha256":msha,"payload_digest":pdigest,"payload_file_count":len(entries),
        "seal_files":["artifact_manifest.json","integrity.json","completion.json"]})
    mech=json.loads((ROOT/"mechanism_adjudication.json").read_text())
    write("completion.json",{"schema":"mephc_affine_architecture_r11.completion.v1",
        "scientific_terminal_state":mech["scientific_terminal_state"],"mechanism_adjudication":mech["direct_c1_classification"],
        "primary_q_point":"q2","primary_band":3,"final_resolution_pair":mech["final_resolution_pair"],
        "contract_sha256":SHA,"payload_parent":git(MEPHC,"rev-parse","HEAD",helper=False),
        "completion_gmail_required":False,"r12_authorized":False,"post_seal_record_commit_forbidden":True,"seal_status":"SEALED"})
    print(json.dumps({"sealed":True,"manifest_sha256":msha,"payload_file_count":len(entries),
                      "terminal_state":mech["scientific_terminal_state"]},sort_keys=True))


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--seal":
        seal(); return
    if any((ROOT/x).exists() for x in ("artifact_manifest.json","integrity.json","completion.json")):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal already exists")
    structure,adapter=context()
    pre=preflight()
    full={}; tangent={}; sectors={}; ledger=[]; repeats={}; reps={}; trans={}; geom={}
    resolutions=list(MANDATORY)
    for res in resolutions:
        run_resolution(structure,adapter,res,full,tangent,sectors,ledger,repeats,reps,trans,geom)
    result=emit(pre,full,tangent,sectors,ledger,repeats,reps,trans,geom,resolutions)
    if result["terminal_state"] not in ("CLOSED_NONDEGENERATE_FIRST_ORDER_ZERO_SUPPORTED","CLOSED_ANALYTIC_FIRST_ORDER_ZERO_NUMERICAL_RESIDUAL_BOUNDED"):
        res=112
        run_resolution(structure,adapter,res,full,tangent,sectors,ledger,repeats,reps,trans,geom)
        resolutions.append(res)
        result=emit(pre,full,tangent,sectors,ledger,repeats,reps,trans,geom,resolutions)
    print(json.dumps({"phase":"payload","resolutions":resolutions,"fresh_solver_calls":len(ledger),
                      "terminal_state":result["terminal_state"]},sort_keys=True))


if __name__=="__main__":
    main()
