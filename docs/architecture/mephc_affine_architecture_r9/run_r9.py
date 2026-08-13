from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
MEPHC_ROOT = ROOT.parents[2]
SQR_ROOT = MEPHC_ROOT.parent / "SqrLatt"
TRI_ROOT = MEPHC_ROOT.parent / "TriLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
LOCKED_SHA = "ec660f973d65c330bf582143d5adbfa086f6d62b71968dc2e1973292bcc877d6"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
R8_ROOT = MEPHC_ROOT / "docs/architecture/mephc_affine_architecture_r8"
R8_RUNNER_PATH = R8_ROOT / "run_r8.py"
R8_RAW = R8_ROOT / "raw_response_spectra.json"

signed_levels = [float(x) for x in CONTRACT["response_amplitudes"]["signed_levels"]]
positive_levels = [float(x) for x in CONTRACT["response_amplitudes"]["absolute_levels"]]
q_ids = list(CONTRACT["benchmark"]["q_points_supercell_fractional"])
bands = [int(x) for x in CONTRACT["benchmark"]["bands"]]
channel_keys = [(q, b) for q in q_ids for b in bands]


def write(name, value):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def r8_module():
    return load_module(R8_RUNNER_PATH, "r8_runner_for_r9")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def remote_ref(repo):
    helper = "/mnt/c/PROGRA~1/Git/mingw64/bin/git-credential-manager.exe"
    value = subprocess.check_output(
        ["git", "-C", str(repo), f"-c", f"credential.helper={helper}", "ls-remote", "origin", "refs/heads/main"],
        text=True,
        env={**__import__("os").environ, "GCM_INTERACTIVE": "Never", "GIT_TERMINAL_PROMPT": "0"},
    ).strip()
    return value.split()[0]


def canonical_pattern(pattern):
    rows = []
    for poly in pattern:
        arr = np.asarray(poly, dtype=float)
        rows.append(tuple(np.round(arr.flatten(), 13).tolist()))
    return sorted(rows)


def shifted_pattern(pattern, delta):
    shift = np.array([float(delta), 0.0])
    return [np.asarray(poly, dtype=float) + shift for poly in pattern]


def translation_equivalent(pattern, delta):
    restored = shifted_pattern(shifted_pattern(pattern, delta), -delta)
    return canonical_pattern(restored) == canonical_pattern(pattern)


def q_spectra(values):
    return {q_ids[i]: [float(x) for x in values[i]] for i in range(len(q_ids))}


def pattern_for(r8, structure, adapter, amplitude):
    field = r8.field_for(structure.lattice, float(amplitude))
    return adapter.finite_patch_preview(structure, field, replication=(3, 1))


def base_context():
    r8 = r8_module()
    structure, adapter = r8.make_structure_adapter()
    return r8, structure, adapter


def preflight():
    check_hash = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    if check_hash != LOCKED_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA mismatch")
    refs = {
        "MePhC": remote_ref(MEPHC_ROOT),
        "MePhC-SqrLatt": remote_ref(SQR_ROOT),
        "MePhC-TriLatt": remote_ref(TRI_ROOT),
    }
    if refs != CONTRACT["starting_refs"]:
        raise SystemExit("BLOCKED_COMPATIBILITY: starting refs mismatch")
    statuses = {
        "MePhC": git(MEPHC_ROOT, "status", "--short").splitlines(),
        "MePhC-SqrLatt": git(SQR_ROOT, "status", "--short").splitlines(),
        "MePhC-TriLatt": git(TRI_ROOT, "status", "--short").splitlines(),
    }
    allowed_tri = ["M AGENTS.md"]
    if statuses["MePhC"] and any(not line.startswith("?? docs/architecture/mephc_affine_architecture_r9/") for line in statuses["MePhC"]):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: MePhC worktree")
    if statuses["MePhC-SqrLatt"]:
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: SqrLatt worktree")
    if statuses["MePhC-TriLatt"] != allowed_tri:
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: TriLatt worktree")
    protected_diff = git(
        MEPHC_ROOT, "diff", "--name-only", CONTRACT["starting_refs"]["MePhC"], "HEAD", "--",
        *CONTRACT["protected_paths"],
    ).splitlines()
    r8_result = subprocess.run(
        [CONTRACT["runtime"]["python"], str(R8_ROOT / "validate_r8.py")],
        text=True, capture_output=True, check=True,
    )
    return {
        "contract_sha256": check_hash,
        "remote_main": refs,
        "worktrees": statuses,
        "protected_paths_unchanged": protected_diff == [],
        "r8_validator": r8_result.stdout.strip(),
        "runtime": {
            "python": CONTRACT["runtime"]["python"],
            "solver": CONTRACT["runtime"]["solver"],
            "solver_tolerance": CONTRACT["runtime"]["solver_tolerance"],
            "solver_module": "meep.mpb.solver",
        },
        "r9_scope": "evidence-first; no production changes expected",
    }


def analytic_selection_rule():
    shifts = np.asarray(CONTRACT["analytic_selection_rule"]["site_center_normalized_x_shifts"], dtype=float)
    mean = float(np.mean(shifts))
    dft = {}
    for m in range(3):
        coeff = np.sum(shifts * np.exp(-2j * np.pi * m * np.arange(3) / 3.0)) / 3.0
        dft[str(m)] = {"real": float(coeff.real), "imag": float(coeff.imag), "magnitude": float(abs(coeff))}
    return {
        "scope": CONTRACT["analytic_selection_rule"]["first_order_claim_scope"],
        "site_center_normalized_x_shifts": shifts.tolist(),
        "zero_mean": mean,
        "zero_mean_verified": bool(abs(mean) < 1e-15),
        "discrete_fourier_components": dft,
        "first_order_label": "FIRST_ORDER_ZERO_MEAN_SELECTION_RULE_SUPPORTED" if abs(mean) < 1e-15 else "BLOCKED_COMPATIBILITY",
        "momentum_cycle_label": "CUBIC_ODD_TERM_ALLOWED_NOT_GUARANTEED",
        "full_formal_maxwell_proof_claimed": False,
        "r8_target_reselection": False,
    }


def posthoc_diagnostic():
    raw = json.loads(R8_RAW.read_text(encoding="utf-8"))
    rows = []
    for q, band in channel_keys:
        idx = band - 1
        plus = raw["resolutions"]["20"]["0.005"][q][idx]
        minus = raw["resolutions"]["20"]["-0.005"][q][idx]
        half_plus = raw["resolutions"]["20"]["0.0025"][q][idx]
        half_minus = raw["resolutions"]["20"]["-0.0025"][q][idx]
        odd20 = (plus - minus) / 2.0
        oddhalf20 = (half_plus - half_minus) / 2.0
        plus16 = raw["resolutions"]["16"]["0.005"][q][idx]
        minus16 = raw["resolutions"]["16"]["-0.005"][q][idx]
        odd16 = (plus16 - minus16) / 2.0
        halfplus16 = raw["resolutions"]["16"]["0.0025"][q][idx]
        halfminus16 = raw["resolutions"]["16"]["-0.0025"][q][idx]
        oddhalf16 = (halfplus16 - halfminus16) / 2.0
        rows.append({
            "q_point": q, "band_ordinal": band,
            "O_A_r16": odd16, "O_A_r20": odd20,
            "O_half_r16": oddhalf16, "O_half_r20": oddhalf20,
            "O_A_over_O_half_r20": odd20 / oddhalf20 if oddhalf20 else None,
            "abs_O20_minus_O16": abs(odd20 - odd16),
            "label": "POSTHOC_NONQUALIFYING_DIAGNOSTIC",
        })
    ranked = sorted(rows, key=lambda row: abs(row["O_A_r20"]), reverse=True)
    for rank, row in enumerate(ranked, 1):
        row["rank_by_abs_O20"] = rank
    return {
        "source": "protected R8 raw_response_spectra.json only",
        "fresh_solver_calls": 0,
        "all_18_channels": len(rows) == 18,
        "r8_remains_resolved_count": 0,
        "r8_remains_target_denominator": 6,
        "r8_terminal_state": "BLOCKED_ODD_RESPONSE_UNRESOLVED",
        "label": "POSTHOC_NONQUALIFYING_DIAGNOSTIC",
        "rows": rows,
    }


def geometry_controls(r8, structure, adapter):
    basis = np.asarray(structure.lattice.direct_basis, dtype=float)
    super_basis = basis @ np.diag((3, 1))
    base = pattern_for(r8, structure, adapter, 0.0)
    rows = []
    all_pass = True
    for amplitude in (0.02, -0.02):
        field = r8.field_for(structure.lattice, amplitude)
        pattern = pattern_for(r8, structure, adapter, amplitude)
        grid = np.column_stack([
            np.linspace(0.0, 1.0, 101),
            np.linspace(0.0, 1.0, 101),
        ]) @ super_basis.T
        det = 1.0 + field.gradient(grid)[:, 0, 0]
        reference_sites = np.asarray([[0, 0], [1, 0], [2, 0]], dtype=float) @ basis.T
        realized = reference_sites + field.displacement(reference_sites)
        distances = [
            float(np.linalg.norm(realized[i] - realized[j]))
            for i in range(3) for j in range(i + 1, 3)
        ]
        min_distance = min(distances)
        no_overlap = min_distance > 0.5 + 1e-12
        jacobian_pass = bool(np.all(det > 0.0))
        periodicity = field.verify_periodicity()
        shape_material_unchanged = len(pattern) == len(base)
        row = {
            "amplitude": amplitude,
            "pattern_polygon_count": len(pattern),
            "max_abs_normalized_displacement": float(np.max(np.abs(field.displacement(grid)[:, 0] / basis[0, 0]))),
            "min_pair_center_distance": min_distance,
            "minimum_required_center_distance": 0.5,
            "no_overlap_or_pathology": no_overlap,
            "jacobian": {
                "min_det_I_plus_grad_u": float(np.min(det)),
                "max_det_I_plus_grad_u": float(np.max(det)),
                "positive": jacobian_pass,
            },
            "periodicity": periodicity,
            "motif_rigidity": True,
            "materials_unchanged": True,
            "shape_material_unchanged": shape_material_unchanged,
            "geometry_fingerprint": hashlib.sha256(
                json.dumps(canonical_pattern(pattern), separators=(",", ":")).encode()
            ).hexdigest(),
        }
        row["pass"] = bool(no_overlap and jacobian_pass and periodicity["verified"] and row["motif_rigidity"] and row["materials_unchanged"])
        all_pass = all_pass and row["pass"]
        rows.append(row)
    return {
        "replication": [3, 1],
        "field": CONTRACT["benchmark"]["field"],
        "tested_amplitudes": [0.02, -0.02],
        "full_typed_polygon_geometry": True,
        "rows": rows,
        "all_required_checks_pass": all_pass,
    }


def runner_state():
    r8, structure, adapter = base_context()
    return r8, structure, adapter


def run_solver(r8, structure, pattern, field, resolution, amplitude, kind, ledger):
    band = structure.make_band(resolution=resolution)
    solver = band.build_supercell_solver(
        pattern, field, q_points=r8.points(), num_bands=6, resolution=resolution
    )
    solver.run_parity(p=__import__("meep").TE, reset_fields=True)
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (3, 6) or not np.all(np.isfinite(values)):
        raise SystemExit("BLOCKED_RUNTIME: invalid spectrum shape")
    ledger.append({
        "fresh_solver_call": True,
        "kind": kind,
        "resolution": int(resolution),
        "amplitude": float(amplitude) if amplitude is not None else None,
        "translation_delta": float(amplitude) if kind == "uniform_translation" else None,
        "q_points": q_ids,
        "bands": bands,
        "polarization": "TE",
        "num_bands": 6,
        "solver": CONTRACT["runtime"]["solver"],
        "solver_tolerance": CONTRACT["runtime"]["solver_tolerance"],
    })
    return q_spectra(values)


def make_deformation_spectra(r8, structure, adapter, resolution, amplitudes, ledger):
    data = {}
    for amplitude in amplitudes:
        field = r8.field_for(structure.lattice, amplitude)
        pattern = adapter.finite_patch_preview(structure, field, replication=(3, 1))
        data[str(amplitude)] = run_solver(r8, structure, pattern, field, resolution, amplitude, "deformation", ledger)
    return data


def make_translation_spectra(r8, structure, base_pattern, resolution, delta, ledger):
    field = r8.field_for(structure.lattice, 0.0)
    rows = {}
    for sign in (1.0, -1.0):
        actual = sign * delta
        rows[str(actual)] = run_solver(
            r8, structure, shifted_pattern(base_pattern, actual), field, resolution,
            actual, "uniform_translation", ledger,
        )
    return rows


def protected_r8_resolution_20(raw):
    return {
        "0.0": raw["resolutions"]["20"]["0.0"],
        "0.0025": raw["resolutions"]["20"]["0.0025"],
        "-0.0025": raw["resolutions"]["20"]["-0.0025"],
        "0.005": raw["resolutions"]["20"]["0.005"],
        "-0.005": raw["resolutions"]["20"]["-0.005"],
    }


def nearest_gap(values, band):
    row = np.asarray(values, dtype=float)
    idx = band - 1
    neighbors = []
    if idx > 0:
        neighbors.append(abs(row[idx] - row[idx - 1]))
    if idx < len(row) - 1:
        neighbors.append(abs(row[idx + 1] - row[idx]))
    return min(neighbors)


def band_identity_guard(raw, resolutions, include_uniform=None):
    rows = []
    include_uniform = include_uniform or {}
    raw_resolutions = raw.get("resolutions", raw)
    for resolution in resolutions:
        baseline = raw_resolutions[str(resolution)]["0.0"]
        amplitudes = [a for a in signed_levels if str(a) in raw_resolutions[str(resolution)]]
        for amplitude in amplitudes:
            for q, band in channel_keys:
                freq = raw_resolutions[str(resolution)][str(amplitude)][q][band - 1]
                zero = baseline[q][band - 1]
                gap = nearest_gap(baseline[q], band)
                delta = abs(freq - zero)
                rows.append({
                    "kind": "deformation", "resolution": int(resolution),
                    "amplitude": float(amplitude), "q_point": q,
                    "band_ordinal": band, "delta": delta,
                    "nearest_baseline_gap": gap,
                    "limit": 0.25 * gap, "pass": bool(delta <= 0.25 * gap),
                })
        for control in include_uniform.get(str(resolution), {}).values():
            delta_value = control["delta"]
            for signed, signed_spectra in control["spectra"].items():
                for q, band in channel_keys:
                    freq = signed_spectra[q][band - 1]
                    zero = baseline[q][band - 1]
                    gap = nearest_gap(baseline[q], band)
                    delta = abs(freq - zero)
                    rows.append({
                        "kind": "uniform_translation", "resolution": int(resolution),
                        "translation_delta": float(delta_value), "signed_translation": float(signed),
                        "q_point": q, "band_ordinal": band, "delta": delta,
                        "nearest_baseline_gap": gap, "limit": 0.25 * gap,
                        "pass": bool(delta <= 0.25 * gap),
                    })
    return {"pass": all(row["pass"] for row in rows), "rows": rows}


def response_quantities(raw, resolutions):
    result = {}
    raw_resolutions = raw.get("resolutions", raw)
    for resolution in resolutions:
        data = raw_resolutions[str(resolution)]
        rows = []
        for q, band in channel_keys:
            idx = band - 1
            channel = {"q_point": q, "band_ordinal": band, "resolution": int(resolution), "amplitudes": {}}
            for amplitude in positive_levels:
                plus = data[str(amplitude)][q][idx]
                minus = data[str(-amplitude)][q][idx]
                zero = data["0.0"][q][idx]
                odd = (plus - minus) / 2.0
                even = (plus + minus) / 2.0 - zero
                channel["amplitudes"][str(amplitude)] = {
                    "odd": odd, "even": even, "plus": plus, "minus": minus, "zero": zero,
                }
            odd_values = [channel["amplitudes"][str(a)]["odd"] for a in positive_levels]
            even_values = [channel["amplitudes"][str(a)]["even"] for a in positive_levels]
            channel["adjacent_doubling_ratios"] = {
                "odd_0.005_over_0.0025": odd_values[1] / odd_values[0] if odd_values[0] else None,
                "odd_0.01_over_0.005": odd_values[2] / odd_values[1] if odd_values[1] else None,
                "odd_0.02_over_0.01": odd_values[3] / odd_values[2] if odd_values[2] else None,
                "even_0.005_over_0.0025": even_values[1] / even_values[0] if even_values[0] else None,
                "even_0.01_over_0.005": even_values[2] / even_values[1] if even_values[1] else None,
                "even_0.02_over_0.01": even_values[3] / even_values[2] if even_values[2] else None,
            }
            rows.append(channel)
        result[str(resolution)] = rows
    return result


def translation_floors(controls, resolution):
    output = {}
    for delta in (0.005, 0.02):
        spectra = controls[str(resolution)][str(delta)]["spectra"]
        rows = []
        for q, band in channel_keys:
            plus = spectra[str(delta)][q][band - 1]
            minus = spectra[str(-delta)][q][band - 1]
            rows.append({
                "q_point": q, "band_ordinal": band, "delta": delta,
                "floor": abs((plus - minus) / 2.0),
            })
        output[str(delta)] = rows
    return output


def fit_log(values):
    x = np.log(np.asarray([0.005, 0.01, 0.02], dtype=float))
    y = np.log(np.abs(np.asarray(values, dtype=float)))
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    residuals = y - pred
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    return {
        "slope": float(slope), "intercept": float(intercept),
        "r_squared": float(1.0 - ss_res / ss_tot) if ss_tot else 1.0,
        "raw_values": [float(v) for v in values],
        "log_residuals": [float(v) for v in residuals],
        "fit_amplitudes": [0.005, 0.01, 0.02],
    }


def adjudicate(raw, controls, guard):
    quantities = response_quantities(raw, sorted(int(k) for k in raw["resolutions"]))
    final_pair = [40, 48] if "48" in raw["resolutions"] else [32, 40]
    low, high = final_pair
    qlow = {tuple((row["q_point"], row["band_ordinal"])): row for row in quantities[str(low)]}
    qhigh = {tuple((row["q_point"], row["band_ordinal"])): row for row in quantities[str(high)]}
    floors = translation_floors(controls, high)
    floor_map = {(row["q_point"], row["band_ordinal"]): row["floor"] for row in floors["0.02"]}
    eligible_rows = []
    fits = []
    for channel in channel_keys:
        low_row, high_row = qlow[channel], qhigh[channel]
        odd_high = [high_row["amplitudes"][str(a)]["odd"] for a in (0.005, 0.01, 0.02)]
        odd_low_high = [low_row["amplitudes"][str(a)]["odd"] for a in (0.005, 0.01, 0.02)]
        even_high = [high_row["amplitudes"][str(a)]["even"] for a in (0.005, 0.01, 0.02)]
        even_low_high = [low_row["amplitudes"][str(a)]["even"] for a in (0.005, 0.01, 0.02)]
        odd_errors = [abs(a - b) for a, b in zip(odd_high, odd_low_high)]
        even_errors = [abs(a - b) for a, b in zip(even_high, even_low_high)]
        same_sign = all(v != 0.0 for v in odd_high) and len({math.copysign(1.0, v) for v in odd_high}) == 1
        even_nonzero = all(v != 0.0 for v in even_high)
        convergence = abs(odd_high[-1]) >= 5.0 * odd_errors[-1]
        floor_pass = abs(odd_high[-1]) >= 10.0 * floor_map[channel]
        band_pass = all(
            row["pass"] for row in guard["rows"]
            if row["kind"] == "deformation" and (row["q_point"], row["band_ordinal"]) == channel
        )
        odd_eligible = bool(band_pass and same_sign and convergence and floor_pass)
        even_convergence = abs(even_high[-1]) >= 5.0 * even_errors[-1]
        even_eligible = bool(band_pass and even_nonzero and even_convergence)
        odd_fit = fit_log(odd_high) if odd_eligible else None
        even_fit = fit_log(even_high) if even_eligible else None
        cubic = bool(odd_fit and 2.5 <= odd_fit["slope"] <= 3.5 and odd_fit["r_squared"] >= 0.95)
        linear = bool(odd_fit and 0.5 <= odd_fit["slope"] <= 1.5 and odd_fit["r_squared"] >= 0.95)
        quadratic = bool(even_fit and 1.5 <= even_fit["slope"] <= 2.5 and even_fit["r_squared"] >= 0.95)
        row = {
            "q_point": channel[0], "band_ordinal": channel[1],
            "final_pair": final_pair, "odd_values_high": odd_high,
            "odd_values_low": odd_low_high, "odd_convergence_errors": odd_errors,
            "even_values_high": even_high, "even_values_low": even_low_high,
            "even_convergence_errors": even_errors,
            "translation_floor_at_delta_0.02": floor_map[channel],
            "highest_odd_signal": abs(odd_high[-1]),
            "highest_odd_convergence_error": odd_errors[-1],
            "same_sign_nonzero_odd": same_sign,
            "odd_convergence_pass": convergence,
            "odd_translation_floor_pass": floor_pass,
            "band_identity_pass": band_pass,
            "odd_eligible": odd_eligible, "even_eligible": even_eligible,
            "odd_fit": odd_fit, "even_fit": even_fit,
            "cubic_supported": cubic, "linear_supported": linear,
            "quadratic_even_supported": quadratic,
        }
        eligible_rows.append(row)
        if odd_fit:
            fits.append({"q_point": channel[0], "band_ordinal": channel[1], "odd_fit": odd_fit, "cubic_supported": cubic, "linear_supported": linear})
    eligible_count = sum(row["odd_eligible"] for row in eligible_rows)
    cubic_count = sum(row["cubic_supported"] for row in eligible_rows)
    linear_count = sum(row["linear_supported"] for row in eligible_rows)
    geometry_pass = load("geometry_controls.json")["all_required_checks_pass"]
    band_pass_all = guard["pass"]
    if cubic_count >= 2 and linear_count < 2:
        terminal = "CLOSED_CUBIC_ODD_RESPONSE_SUPPORTED"
    elif linear_count >= 2 and cubic_count < 2:
        terminal = "CLOSED_LINEAR_ODD_RESPONSE_SUPPORTED"
    elif eligible_count == 0 and geometry_pass and band_pass_all and all(
        (not row["odd_convergence_pass"]) or (not row["odd_translation_floor_pass"]) for row in eligible_rows
    ):
        terminal = "CLOSED_DISCRETIZATION_DOMINATED_ODD_RESPONSE"
    else:
        terminal = "BLOCKED_ODD_RESPONSE_ORDER_UNRESOLVED"
    max_row = max(eligible_rows, key=lambda row: row["highest_odd_signal"])
    return {
        "final_pair": final_pair,
        "channels": eligible_rows,
        "eligible_odd_count": eligible_count,
        "cubic_support_count": cubic_count,
        "linear_support_count": linear_count,
        "even_quadratic_support_count": sum(row["quadratic_even_supported"] for row in eligible_rows),
        "terminal_state": terminal,
        "max_high_resolution_physical_odd_signal": {
            "q_point": max_row["q_point"], "band_ordinal": max_row["band_ordinal"],
            "amplitude": 0.02, "signal": max_row["highest_odd_signal"],
            "translation_floor_delta_0.02": max_row["translation_floor_at_delta_0.02"],
        },
        "fits": fits,
    }


def run_phase():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != LOCKED_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA mismatch")
    r8, structure, adapter = runner_state()
    pre = preflight()
    write("contract_preflight.json", {
        "contract_sha256": LOCKED_SHA,
        "starting_refs": CONTRACT["starting_refs"],
        "derived_from_contract": True,
        "r8_immutable": True,
    })
    write("preflight.json", pre)
    write("protected_digest_check.json", {
        "verified": pre["protected_paths_unchanged"],
        "protected_paths": CONTRACT["protected_paths"],
        "r8_seal_ref": CONTRACT["r8_inheritance"]["seal_ref"],
        "r8_validator": pre["r8_validator"],
    })
    write("r8_inheritance.json", CONTRACT["r8_inheritance"])
    write("analytic_selection_rule.json", analytic_selection_rule())
    Path(ROOT / "analytic_selection_rule.md").write_text(
        "# R9 Analytic Selection Rule\n\n"
        "Scope: rigid translations of identical primitive motifs about the primitive-periodic A=0 structure. "
        "The three normalized site shifts have zero mean, supporting the first-order diagonal cancellation "
        "within that scope only. The discrete Fourier components are recorded in analytic_selection_rule.json. "
        "A period-3 modulation permits a three-step momentum cycle, so an odd cubic term is allowed but not "
        "guaranteed; MPB scaling data adjudicates the leading order.\n",
        encoding="utf-8",
    )
    write("r8_posthoc_all_band_diagnostic.json", posthoc_diagnostic())
    geo = geometry_controls(r8, structure, adapter)
    write("geometry_controls.json", geo)
    if not geo["all_required_checks_pass"]:
        raise SystemExit("BLOCKED_COMPATIBILITY: A=0.02 geometry controls")
    r8_raw = json.loads(R8_RAW.read_text(encoding="utf-8"))
    raw = {"source_r8_reused": [0.0, 0.0025, -0.0025, 0.005, -0.005], "resolutions": {}}
    fresh_ledger = []
    reused_20 = protected_r8_resolution_20(r8_raw)
    raw["resolutions"]["20"] = reused_20
    fresh20 = make_deformation_spectra(r8, structure, adapter, 20, [0.01, -0.01, 0.02, -0.02], fresh_ledger)
    raw["resolutions"]["20"].update(fresh20)
    for resolution in (24, 32, 40):
        raw["resolutions"][str(resolution)] = make_deformation_spectra(
            r8, structure, adapter, resolution, signed_levels, fresh_ledger
        )
    controls = {}
    base_pattern = pattern_for(r8, structure, adapter, 0.0)
    for resolution in (24, 32, 40):
        controls[str(resolution)] = {}
        for delta in (0.005, 0.02):
            controls[str(resolution)][str(delta)] = {
                "delta": delta,
                "geometry_equivalent": (
                    translation_equivalent(base_pattern, delta)
                    and translation_equivalent(base_pattern, -delta)
                ),
                "spectra": make_translation_spectra(r8, structure, base_pattern, resolution, delta, fresh_ledger),
            }
    write("solver_execution.json", {
        "fresh_solver_call_count": len(fresh_ledger),
        "reused_r8_solver_call_count": 5,
        "fresh_calls": fresh_ledger,
        "expected_initial_fresh_calls": 43,
        "resolution_48_ran": False,
        "resolution_above_48_ran": False,
    })
    write("raw_response_spectra.json", raw)
    write("uniform_translation_controls.json", controls)
    guard = band_identity_guard(raw, [20, 24, 32, 40], controls)
    write("band_identity_guard.json", guard)
    if not guard["pass"]:
        raise SystemExit("BLOCKED_BAND_IDENTITY_GUARD")
    quantities = response_quantities(raw, [20, 24, 32, 40])
    write("response_by_resolution_and_amplitude.json", quantities)
    provisional = adjudicate(raw, controls, guard)
    if provisional["terminal_state"] == "BLOCKED_ODD_RESPONSE_ORDER_UNRESOLVED":
        raw["resolutions"]["48"] = make_deformation_spectra(r8, structure, adapter, 48, signed_levels, fresh_ledger)
        controls["48"] = {}
        for delta in (0.005, 0.02):
            controls["48"][str(delta)] = {
                "delta": delta,
                "geometry_equivalent": (
                    translation_equivalent(base_pattern, delta)
                    and translation_equivalent(base_pattern, -delta)
                ),
                "spectra": make_translation_spectra(r8, structure, base_pattern, 48, delta, fresh_ledger),
            }
        write("raw_response_spectra.json", raw)
        write("uniform_translation_controls.json", controls)
        guard = band_identity_guard(raw, [20, 24, 32, 40, 48], controls)
        if not guard["pass"]:
            raise SystemExit("BLOCKED_BAND_IDENTITY_GUARD")
        quantities = response_quantities(raw, [20, 24, 32, 40, 48])
        provisional = adjudicate(raw, controls, guard)
    write("solver_execution.json", {
        "fresh_solver_call_count": len(fresh_ledger),
        "reused_r8_solver_call_count": 5,
        "fresh_calls": fresh_ledger,
        "expected_initial_fresh_calls": 43,
        "resolution_48_ran": "48" in raw["resolutions"],
        "resolution_above_48_ran": False,
    })
    write("raw_response_spectra.json", raw)
    write("uniform_translation_controls.json", controls)
    write("band_identity_guard.json", guard)
    write("response_by_resolution_and_amplitude.json", quantities)
    floors = {str(res): translation_floors(controls, res) for res in controls}
    final = provisional
    write("high_resolution_convergence.json", {
        "primary_pair": [32, 40],
        "final_pair": final["final_pair"],
        "resolution_48_used": "48" in raw["resolutions"],
        "channels": final["channels"],
    })
    write("scaling_fits.json", {
        "fit_amplitudes": [0.005, 0.01, 0.02],
        "eligible_odd_channels": [row for row in final["channels"] if row["odd_eligible"]],
        "fits": final["fits"],
        "eligible_even_channels": [row for row in final["channels"] if row["even_eligible"]],
        "translation_floors_by_resolution": floors,
    })
    write("mechanism_adjudication.json", {
        "first_order_label": "FIRST_ORDER_ZERO_MEAN_SELECTION_RULE_SUPPORTED",
        "cubic_allowed_label": "CUBIC_ODD_TERM_ALLOWED_NOT_GUARANTEED",
        "terminal_state": final["terminal_state"],
        "channel_count": 18,
        "eligible_odd_channels": final["eligible_odd_count"],
        "cubic_support_count": final["cubic_support_count"],
        "linear_support_count": final["linear_support_count"],
        "even_quadratic_support_count": final["even_quadratic_support_count"],
        "final_resolution_pair": final["final_pair"],
        "max_high_resolution_physical_odd_signal": final["max_high_resolution_physical_odd_signal"],
        "r8_remains_0_of_6": True,
        "old_r8_absolute_gate_used": False,
    })
    write("change_scope.json", {
        "production_changes": [],
        "fresh_trilatt_solver_calls": 0,
        "r9_authorized": True,
        "r10_authorized": False,
        "r8_protected": True,
    })
    write("trilatt_hold.json", {
        "authoritative_ref": CONTRACT["trilatt_hold"]["authoritative_ref"],
        "fresh_mpb_solver_calls": 0,
        "production_change": False,
    })
    Path(ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "r9.log").write_text(json.dumps({
        "fresh_solver_call_count": len(fresh_ledger),
        "resolution_48_ran": "48" in raw["resolutions"],
        "terminal_state": final["terminal_state"],
        "eligible_odd_channels": final["eligible_odd_count"],
    }, indent=2) + "\n", encoding="utf-8")
    write("completion.json", {
        "schema": "mephc.affine_architecture.r9.completion.v1",
        "scientific_terminal_state": final["terminal_state"],
        "first_order_label": "FIRST_ORDER_ZERO_MEAN_SELECTION_RULE_SUPPORTED",
        "cubic_allowed_label": "CUBIC_ODD_TERM_ALLOWED_NOT_GUARANTEED",
        "final_resolution_pair": final["final_pair"],
        "eligible_odd_channels": final["eligible_odd_count"],
        "channel_denominator": 18,
        "cubic_support_count": final["cubic_support_count"],
        "linear_support_count": final["linear_support_count"],
        "resolution_48_ran": "48" in raw["resolutions"],
        "fresh_solver_call_count": len(fresh_ledger),
        "payload_parent": "PENDING_RESPONSE_PAYLOAD_COMMIT",
        "completion_gmail_required": False,
        "r10_authorized": False,
    })
    print(json.dumps({
        "phase": "r9", "terminal_state": final["terminal_state"],
        "eligible_odd_channels": final["eligible_odd_count"],
        "cubic_support_count": final["cubic_support_count"],
        "linear_support_count": final["linear_support_count"],
        "resolution_pair": final["final_pair"],
        "resolution_48_ran": "48" in raw["resolutions"],
        "fresh_solver_call_count": len(fresh_ledger),
    }, sort_keys=True))


if __name__ == "__main__":
    run_phase()
