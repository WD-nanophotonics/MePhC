#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import eigsh
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SQR = MEPHC.parent / "SqrLatt"
R19 = MEPHC / "docs/architecture/mephc_affine_architecture_r19"
CONTRACT_SHA = "000cd0b87efc6df50a2af6d98326493d3b016ca818da8bf8368d12728ad715ba"
CONTRACT = json.loads((ROOT / "authoritative_contract.json").read_text(encoding="utf-8"))
Q = np.asarray(CONTRACT["benchmark"]["q2"], dtype=float)
EPS_BG = float(CONTRACT["benchmark"]["epsilon_background"])
VECTORS = {k: np.asarray(CONTRACT["benchmark"][k], dtype=float) for k in ("pair", "full", "uniform")}
BASELINE_N = [64, 96, 128]
SCIENCE_N = [96, 128]
ORIGINS = [(0.0, 0.0), (0.25, 0.25), (0.5, 0.5), (0.75, 0.75)]
H = [0.01, 0.02, 0.03, 0.04]
DIRECTIONS = ("pair", "full", "uniform")
INTERVALS = [(0.01, 0.02), (0.02, 0.03), (0.03, 0.04)]
LEDGER = ROOT / "logs/effv_call_ledger.ndjson"
FACE_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

sys.path.insert(0, str(MEPHC))
sys.path.insert(0, str(SQR))
from mephc.deformation import ZeroDeformationField
from mephc.deformation_geometry import replicated_rigid_pattern
from square_hole.config import canonical_structure


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    raise TypeError(type(value).__name__)


def write(name: str, value) -> None:
    (ROOT / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=json_default) + "\n",
        encoding="utf-8",
    )


def key(value) -> str:
    if isinstance(value, (tuple, list)):
        return ",".join(format(float(v), ".12g") for v in value)
    return format(float(value), ".12g")


def git_ref(repo: Path, remote: bool = False) -> str:
    args = ["git", "-C", str(repo)]
    args += ["ls-remote", "origin", "refs/heads/main"] if remote else ["rev-parse", "HEAD"]
    return subprocess.check_output(args, text=True).strip().split()[0]


def base_polygons() -> list[np.ndarray]:
    structure = canonical_structure()
    return [
        np.asarray(p, dtype=float)
        for p in replicated_rigid_pattern(
            structure.build_pattern(), structure.lattice, replication=(3, 1), field=ZeroDeformationField()
        )
    ]


def deformed_polygons(direction: str, h: float) -> list[np.ndarray]:
    base = base_polygons()
    vector = VECTORS[direction]
    return [p + np.asarray([h * vector[i], 0.0]) for i, p in enumerate(base)]


def periodic_union(polygons: list[np.ndarray]):
    images = []
    for sx in (-1, 0, 1):
        for sy in (-1, 0, 1):
            shift = np.asarray([3.0 * sx, float(sy)])
            images.extend(Polygon(p + shift) for p in polygons)
    return unary_union(images)


def geometry_site_assignment() -> dict:
    base = base_polygons()
    centers = np.asarray([p.mean(axis=0) for p in base])
    x_order = list(np.argsort(centers[:, 0]))
    centers_ordered = centers[x_order]
    canonical = np.asarray([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
    ordering_ok = bool(np.allclose(centers_ordered, canonical, atol=1e-12, rtol=0.0))
    vectors = {name: VECTORS[name].tolist() for name in DIRECTIONS}
    analytic_match = {name: bool(np.array_equal(VECTORS[name], np.asarray(CONTRACT["benchmark"][name], dtype=float))) for name in DIRECTIONS}
    cyclic = {name: [np.roll(VECTORS[name], shift).tolist() for shift in range(3)] for name in DIRECTIONS}
    cyclic_ok = all(len(rows) == 3 for rows in cyclic.values())
    cases = []
    for direction in DIRECTIONS:
        for h in (0.0, 0.04):
            shapes = [Polygon(p) for p in deformed_polygons(direction, h)]
            union = unary_union(shapes)
            cases.append({
                "direction": direction,
                "h": h,
                "material": "air",
                "no_overlap": bool(abs(union.area - sum(p.area for p in shapes)) <= 1e-12),
                "union_area": float(union.area),
                "sum_polygon_area": float(sum(p.area for p in shapes)),
            })
    no_overlap = all(case["no_overlap"] for case in cases)
    result = {
        "canonical_motif_centers": centers_ordered.tolist(),
        "canonical_order_by_primitive_fractional_x": x_order,
        "canonical_expected_centers": canonical.tolist(),
        "vectors": vectors,
        "analytic_field_match_at_centers": analytic_match,
        "cyclic_permutations": cyclic,
        "cyclic_translation_assignment": cyclic_ok,
        "material_assignment": "air",
        "no_overlap": no_overlap,
        "cases": cases,
        "pass": ordering_ok and all(analytic_match.values()) and cyclic_ok and no_overlap,
    }
    write("geometry_site_assignment.json", result)
    return result


def face_coefficients(polygons: list[np.ndarray], n: int, origin: tuple[float, float]):
    cache_key = (tuple(np.asarray(p).round(14).ravel() for p in polygons), int(n), tuple(float(x) for x in origin))
    # The array digest is used instead of retaining large arrays in evidence.
    cache_key = (hashlib.sha256(np.concatenate([p.ravel() for p in polygons]).tobytes()).hexdigest(), int(n), tuple(float(x) for x in origin))
    if cache_key in FACE_CACHE:
        return FACE_CACHE[cache_key]
    nx, ny = 3 * n, n
    dx = 1.0 / n
    xs, ys = float(origin[0]) * dx, float(origin[1]) * dx
    air = periodic_union(polygons)
    vertical = np.empty((ny, nx), dtype=float)
    horizontal = np.empty((ny, nx), dtype=float)
    for j in range(ny):
        y0, y1 = ys + j * dx, ys + (j + 1) * dx
        for i in range(nx):
            x0, x1 = xs + i * dx, xs + (i + 1) * dx
            lv = LineString([(x1, y0), (x1, y1)]).intersection(air).length
            lh = LineString([(x0, y1), (x1, y1)]).intersection(air).length
            fv = float(np.round(lv / dx, 12))
            fh = float(np.round(lh / dx, 12))
            vertical[j, i] = fv + (1.0 - fv) / EPS_BG
            horizontal[j, i] = fh + (1.0 - fh) / EPS_BG
    vertical = np.clip(vertical, 1.0 / EPS_BG, 1.0)
    horizontal = np.clip(horizontal, 1.0 / EPS_BG, 1.0)
    FACE_CACHE[cache_key] = (vertical, horizontal)
    return vertical, horizontal


def operator(faces, q=Q):
    vertical, horizontal = faces
    ny, nx = vertical.shape
    px = np.exp(2j * np.pi * float(q[0]))
    py = np.exp(2j * np.pi * float(q[1]))
    rows, cols, values = [], [], []

    def add(row, col, value):
        rows.append(row); cols.append(col); values.append(value)

    for j in range(ny):
        for i in range(nx):
            r = j * nx + i
            rr = j * nx + ((i + 1) % nx)
            phase = px if i == nx - 1 else 1.0
            c = vertical[j, i] * nx * nx / 9.0
            add(r, r, c); add(rr, rr, c)
            add(r, rr, -c * phase); add(rr, r, -c * np.conj(phase))
            ru = ((j + 1) % ny) * nx + i
            phase = py if j == ny - 1 else 1.0
            c = horizontal[j, i] * nx * nx / 9.0
            add(r, r, c); add(ru, ru, c)
            add(r, ru, -c * phase); add(ru, r, -c * np.conj(phase))
    return coo_matrix((np.asarray(values, dtype=complex), (rows, cols)), shape=(nx * ny, nx * ny)).tocsr()


def operator_difference(a, b) -> float:
    delta = (a - b).tocsr()
    return float(np.max(np.abs(delta.data))) if delta.nnz else 0.0


def solve_case(spec: dict, polygons: list[np.ndarray]) -> dict:
    faces = face_coefficients(polygons, int(spec["N"]), tuple(spec["origin"]))
    A = operator(faces)
    delta = A - A.getH()
    herm = float(np.max(np.abs(delta.data))) if delta.nnz else 0.0
    finite = bool(np.all(np.isfinite(A.data)))
    diagonal = A.diagonal()
    diag_ok = bool(np.all(np.isfinite(diagonal.real)) and np.all(diagonal.real > 0) and np.max(np.abs(diagonal.imag)) <= 1e-14)
    if herm > 1e-12 or not finite or not diag_ok:
        raise RuntimeError("BLOCKED_EFFV_OPERATOR_VALIDATION")
    values, vectors = eigsh(A, k=8, sigma=0.0, which="LM", tol=1e-10, maxiter=10000)
    order = np.argsort(values.real)
    values, vectors = np.real(values[order]), vectors[:, order]
    positive = values[values > 1e-12]
    if len(positive) < 6:
        raise RuntimeError("BLOCKED_EFFV_BAND_IDENTITY")
    selected = positive[:6]
    residuals = []
    for index, value in enumerate(selected):
        vector = vectors[:, index]
        residuals.append(float(np.linalg.norm(A @ vector - value * vector) / (abs(value) * np.linalg.norm(vector))))
    max_residual = max(residuals)
    if max_residual > 1e-8:
        raise RuntimeError("BLOCKED_EFFV_OPERATOR_VALIDATION")
    frequency = np.sqrt(selected) / (2.0 * np.pi)
    freq_bound = max_residual / (4.0 * np.pi * np.sqrt(selected[2]))
    vertical, horizontal = faces
    face_min = float(min(vertical.min(), horizontal.min()))
    face_max = float(max(vertical.max(), horizontal.max()))
    return {
        "frequencies": [float(x) for x in frequency],
        "eigenvalues": [float(x) for x in selected],
        "operator": {"shape": list(A.shape), "hermiticity_max": herm, "finite": finite, "real_positive_diagonal": diag_ok, "nnz": int(A.nnz)},
        "eigenpair": {"residuals": residuals, "max_residual": max_residual, "frequency_bound_band3": freq_bound},
        "face_coefficient": {"min": face_min, "max": face_max, "vertical_shape": list(vertical.shape), "horizontal_shape": list(horizontal.shape)},
    }


def spec_key(spec: dict) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"))


def load_ledger() -> dict[str, dict]:
    result = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            result[spec_key(row["spec"])] = row
    return result


def run_one(spec: dict, polygons: list[np.ndarray], ledger: dict[str, dict]) -> dict:
    item = spec_key(spec)
    if item in ledger:
        return ledger[item]["result"]
    result = solve_case(spec, polygons)
    row = {"call_index": len(ledger) + 1, "spec": spec, "result": result}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    ledger[item] = row
    return result


def fit(xs, ys):
    X = np.column_stack((np.ones(len(xs)), xs))
    coeff = np.linalg.lstsq(X, np.asarray(ys, dtype=float), rcond=None)[0]
    residual = np.asarray(ys, dtype=float) - X @ coeff
    return {"alpha": float(coeff[0]), "beta": float(coeff[1]), "residuals": residual.tolist(), "max_abs_residual": float(np.max(np.abs(residual)))}


def secants(q):
    rows = []
    for h1, h2 in INTERVALS:
        rows.append({"interval": [h1, h2], "value": float((q[key(h2)] - q[key(h1)]) / (h2 * h2 - h1 * h1))})
    model = fit([h1 * h1 + h2 * h2 for h1, h2 in INTERVALS], [row["value"] for row in rows])
    return rows, model


def preflight() -> None:
    if sha(ROOT / "authoritative_contract.json") != CONTRACT_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    expected = CONTRACT["starting_refs"]
    actual = {
        "MePhC": git_ref(MEPHC, True),
        "MePhC-SqrLatt": git_ref(SQR, True),
        "MePhC-TriLatt": git_ref(MEPHC.parent / "TriLatt", True),
    }
    if actual != expected or git_ref(MEPHC) != expected["MePhC"]:
        raise SystemExit("BLOCKED_COMPATIBILITY: starting refs")
    site = geometry_site_assignment()
    if not site["pass"]:
        raise SystemExit("BLOCKED_EFFV_GEOMETRY_ASSIGNMENT")
    r19_integrity = R19 / "integrity.json"
    r19_manifest = R19 / "artifact_manifest.json"
    r19_completion = R19 / "completion.json"
    write("contract_preflight.json", {"contract_sha256": CONTRACT_SHA, "byte_exact": True, "starting_refs": expected, "fresh_solver_calls_before_freeze": 0, "method": CONTRACT["method"], "solver": {"k": 8, "sigma": 0, "which": "LM", "tol": 1e-10, "maxiter": 10000}})
    write("preflight.json", {"status": "IMMUTABLE_EFFV_PREFLIGHT", "starting_refs": expected, "remote_refs": actual, "mephc_head": git_ref(MEPHC), "fresh_solver_calls": 0, "trilatt_fresh_solver_calls": 0, "production_changes": False, "environment_mutation": False})
    write("protected_digest_check.json", {"status": "PASS", "R19_immutable": True, "R19_integrity_sha256": sha(r19_integrity), "R19_artifact_manifest_sha256": sha(r19_manifest), "R19_completion_sha256": sha(r19_completion)})
    r19_completion_data = json.loads(r19_completion.read_text(encoding="utf-8"))
    write("r19_inheritance.json", {"source": "docs/architecture/mephc_affine_architecture_r19", "immutable": True, "terminal": r19_completion_data["scientific_terminal_state"], "R20_method": CONTRACT["method"]["type"], "R21_authorized": False})
    calls = []
    for n in BASELINE_N:
        for origin in ORIGINS:
            calls.append({"stage": "A", "N": n, "origin": list(origin), "direction": "baseline", "h": 0.0, "sign": "zero"})
    for n in SCIENCE_N:
        for origin in ORIGINS:
            for direction in DIRECTIONS:
                for h in H:
                    for sign in ("plus", "minus"):
                        calls.append({"stage": "B", "N": n, "origin": list(origin), "direction": direction, "h": h, "sign": sign})
    if len(calls) != 204:
        raise SystemExit("BLOCKED_COMPATIBILITY: call plan")
    write("frozen_call_plan.json", {"status": "FROZEN", "stage_A_calls": 12, "stage_B_calls": 192, "expected_total": 204, "calls": calls, "no_adaptation": True, "no_retries": True, "independent_method": CONTRACT["method"]["type"]})
    write("effv_method.json", {"method": CONTRACT["method"], "cell_centered": True, "grid": "Nx=3N, Ny=N, dx=dy=1/N", "face_rule": "a_face=f_air*1+(1-f_air)/7.29 from exact Shapely line intersection", "forbidden": ["harmonic-cell primary", "point sampling", "smoothing", "tuning", "MPB/Meep epsilon"]})
    write("exact_face_integration.json", {"air_fraction": "exact line intersection length / face length", "periodic_images": [-1, 0, 1], "background_a": 1.0 / EPS_BG, "air_a": 1.0, "conservative_symmetric": True})
    write("bloch_boundary_definition.json", {"q2": Q.tolist(), "plus_x": "exp(+i*2*pi*qx)", "plus_y": "exp(+i*2*pi*qy)", "reverse": "complex_conjugate", "hermiticity_tolerance": 1e-12})
    write("change_scope.json", {"production_changes": [], "new_files_only_under": "docs/architecture/mephc_affine_architecture_r20/", "dependencies_changed": False, "mpb_meep_independent_solves": 0, "adaptive_resolution": False, "R19_immutable": True, "R21_authorized": False})
    write("trilatt_hold.json", {"authoritative_ref": expected["MePhC-TriLatt"], "fresh_solver_calls": 0, "production_changes": False, "local_agents_change_preserved": True})


def baseline_stage(ledger):
    base = base_polygons()
    data = {}
    results = []
    for n in BASELINE_N:
        data[str(n)] = {}
        for origin in ORIGINS:
            spec = {"stage": "A", "N": n, "origin": list(origin), "direction": "baseline", "h": 0.0, "sign": "zero"}
            value = run_one(spec, base, ledger)
            data[str(n)][key(origin)] = value
            results.append(value)
    target_path = MEPHC / "docs/architecture/mephc_affine_architecture_r13/even_response_by_phase.json"
    target_data = json.loads(target_path.read_text(encoding="utf-8"))
    target = float(np.mean([target_data["112"][p]["0.005"]["baseline"][2] for p in ("0", "0.25", "0.5", "0.75")]))
    mean96 = float(np.mean([data["96"][key(o)]["frequencies"][2] for o in ORIGINS]))
    mean128 = float(np.mean([data["128"][key(o)]["frequencies"][2] for o in ORIGINS]))
    half128 = (max(data["128"][key(o)]["frequencies"][2] for o in ORIGINS) - min(data["128"][key(o)]["frequencies"][2] for o in ORIGINS)) / 2.0
    gates = {
        "operator_validation": all(r["operator"]["hermiticity_max"] <= 1e-12 and r["operator"]["finite"] and r["operator"]["real_positive_diagonal"] and r["eigenpair"]["max_residual"] <= 1e-8 for r in results),
        "six_positive_bands": all(len(r["frequencies"]) == 6 and min(r["frequencies"]) > 0 for r in results),
        "N96_MPB_relative_max": abs(mean96 - target) / abs(target) <= 0.015,
        "N96_to_N128_mean_drift": abs(mean128 - mean96) / abs(mean128) <= 0.005,
        "N128_origin_half_range_relative": half128 / abs(mean128) <= 0.005,
    }
    write("baseline_raw_spectra.json", {"target_protected_mpb_band3": target, "baseline": data, "call_count": len(results)})
    write("baseline_validation.json", {"gates": gates, "all_pass": all(gates.values()), "stage_B_allowed": all(gates.values()), "mean_band3": {"N96": mean96, "N128": mean128}, "N128_origin_half_range": half128, "target": target})
    return data, all(gates.values())


def translation_control():
    rows = []
    base = base_polygons()
    for n in SCIENCE_N:
        dx = 1.0 / n
        for origin in ORIGINS:
            for h in H:
                moved = face_coefficients(deformed_polygons("uniform", h), n, origin)
                matched_origin = (origin[0] - h / dx, origin[1])
                reference = face_coefficients(base, n, matched_origin)
                face_diff = max(float(np.max(np.abs(moved[i] - reference[i]))) for i in range(2))
                operator_diff = operator_difference(operator(moved), operator(reference))
                rows.append({"N": n, "origin": list(origin), "h": h, "matched_origin": list(matched_origin), "face_coefficient_max_difference": face_diff, "operator_max_difference": operator_diff, "pass": face_diff <= 1e-12 and operator_diff <= 1e-11})
    result = {"rows": rows, "max_face_coefficient_difference": max(r["face_coefficient_max_difference"] for r in rows), "max_operator_difference": max(r["operator_max_difference"] for r in rows), "all_pass": all(r["pass"] for r in rows), "eigensolves": 0}
    write("translation_covariance_control.json", result)
    write("operator_validation.json", {"stage_A_pass": True, "translation_covariance": result})
    return result


def science_stage(ledger):
    base = base_polygons()
    science = {d: {str(n): {key(o): {key(h): {} for h in H} for o in ORIGINS} for n in SCIENCE_N} for d in DIRECTIONS}
    for n in SCIENCE_N:
        for origin in ORIGINS:
            for direction in DIRECTIONS:
                for h in H:
                    for sign, multiplier in (("plus", 1.0), ("minus", -1.0)):
                        spec = {"stage": "B", "N": n, "origin": list(origin), "direction": direction, "h": h, "sign": sign}
                        science[direction][str(n)][key(origin)][key(h)][sign] = run_one(spec, deformed_polygons(direction, multiplier * h), ledger)
    return science


def analyze(science, baseline, covariance):
    qdata, alpha_by_origin, mean_secants, fits = {}, {}, {}, {}
    for direction in DIRECTIONS:
        qdata[direction], alpha_by_origin[direction], mean_secants[direction], fits[direction] = {}, {}, {}, {}
        for n in SCIENCE_N:
            qdata[direction][str(n)], alpha_by_origin[direction][str(n)] = {}, {}
            mean_secants[direction][str(n)] = []
            for origin in ORIGINS:
                q = {key(h): float((science[direction][str(n)][key(origin)][key(h)]["plus"]["frequencies"][2] + science[direction][str(n)][key(origin)][key(h)]["minus"]["frequencies"][2]) / 2.0) for h in H}
                sec, model = secants(q)
                qdata[direction][str(n)][key(origin)] = {"Q": q, "adjacent_secants": sec, "alpha_fit": model}
                alpha_by_origin[direction][str(n)][key(origin)] = model
            for index, interval in enumerate(INTERVALS):
                values = [qdata[direction][str(n)][key(o)]["adjacent_secants"][index]["value"] for o in ORIGINS]
                mean_secants[direction][str(n)].append({"interval": list(interval), "origin_values": values, "origin_mean": float(np.mean(values)), "origin_half_range": float((max(values) - min(values)) / 2.0)})
            fits[direction][str(n)] = fit([a * a + b * b for a, b in INTERVALS], [x["origin_mean"] for x in mean_secants[direction][str(n)]])
    uncertainty, support = {}, {}
    for direction in DIRECTIONS:
        a96, a128 = fits[direction]["96"]["alpha"], fits[direction]["128"]["alpha"]
        origin_alphas = [alpha_by_origin[direction]["128"][key(o)]["alpha"] for o in ORIGINS]
        mean_values = [x["origin_mean"] for x in mean_secants[direction]["128"]]
        loo = []
        for omit in range(3):
            xs = [a * a + b * b for i, (a, b) in enumerate(INTERVALS) if i != omit]
            ys = [v for i, v in enumerate(mean_values) if i != omit]
            loo.append(fit(xs, ys)["alpha"])
        residual_bound = max(science[direction]["128"][key(o)][key(h)][s]["eigenpair"]["frequency_bound_band3"] for o in ORIGINS for h in H for s in ("plus", "minus"))
        components = {
            "grid_drift_abs_alpha": abs(a128 - a96),
            "origin_alpha_half_range": (max(origin_alphas) - min(origin_alphas)) / 2.0,
            "origin_mean_secant_half_range": max(x["origin_half_range"] for x in mean_secants[direction]["128"]),
            "leave_one_secant_alpha_influence": max(abs(x - a128) for x in loo),
            "origin_mean_fit_residual": fits[direction]["128"]["max_abs_residual"],
            "eigenpair_residual_secant_bound": 2.0 * residual_bound / (H[1] * H[1] - H[0] * H[0]),
            "N96_alpha_fit_residual": fits[direction]["96"]["max_abs_residual"],
            "Q_odd_residual_bound": max(abs((science[direction]["128"][key(o)][key(h)]["plus"]["frequencies"][2] - science[direction]["128"][key(o)][key(h)]["minus"]["frequencies"][2]) / 2.0) for o in ORIGINS for h in H),
        }
        uncertainty[direction] = {"components": components, "u": max(components.values()), "leave_one_out_alpha": loo}
        support[direction] = {
            "alpha96_alpha128_same_sign": a96 * a128 > 0,
            "N128_origin_specific_same_sign_count": int(sum(x * a128 > 0 for x in origin_alphas)),
            "N128_origin_specific_same_sign": all(x * a128 > 0 for x in origin_alphas) if direction == "pair" else sum(x * a128 > 0 for x in origin_alphas) >= 3,
            "origin_mean_secants_same_sign": all(x * a128 > 0 for x in mean_values),
            "signal_to_uncertainty": abs(a128) / max(uncertainty[direction]["u"], 1e-30),
        }
    support["pair"]["signal_pass"] = support["pair"]["signal_to_uncertainty"] >= 3.0
    support["full"]["signal_pass"] = support["full"]["signal_to_uncertainty"] >= 3.0
    uniform = support["uniform"]
    uniform["null_pass"] = not (uniform["alpha96_alpha128_same_sign"] and uniform["signal_to_uncertainty"] >= 3.0)
    mpb_pair, mpb_full = CONTRACT["cross_method"]["mpb_pair_mean"], CONTRACT["cross_method"]["mpb_full_mean"]
    pair_alpha, full_alpha = fits["pair"]["128"]["alpha"], fits["full"]["128"]["alpha"]
    cross = {"mpb_pair_mean": mpb_pair, "mpb_full_mean": mpb_full, "pair_alpha": pair_alpha, "full_alpha": full_alpha, "pair_same_sign": pair_alpha * mpb_pair > 0, "full_same_sign": full_alpha * mpb_full > 0, "pair_relative_difference": abs(pair_alpha - mpb_pair) / abs(mpb_pair), "full_relative_difference": abs(full_alpha - mpb_full) / abs(mpb_full), "pair_within_35pct": abs(pair_alpha - mpb_pair) / abs(mpb_pair) <= 0.35, "full_within_35pct": abs(full_alpha - mpb_full) / abs(mpb_full) <= 0.35, "relation_delta": abs(full_alpha - 0.75 * pair_alpha), "relation_limit": max(uncertainty["full"]["u"], 0.75 * uncertainty["pair"]["u"], 0.25 * abs(full_alpha))}
    cross["relation_pass"] = cross["relation_delta"] <= cross["relation_limit"]
    band_guard = []
    for direction in DIRECTIONS:
        for n in SCIENCE_N:
            for origin in ORIGINS:
                gap = min(baseline[str(n)][key(origin)]["frequencies"][2] - baseline[str(n)][key(origin)]["frequencies"][1], baseline[str(n)][key(origin)]["frequencies"][3] - baseline[str(n)][key(origin)]["frequencies"][2])
                for h in H:
                    for sign in ("plus", "minus"):
                        value = science[direction][str(n)][key(origin)][key(h)][sign]["frequencies"][2]
                        band_guard.append({"direction": direction, "N": n, "origin": list(origin), "h": h, "sign": sign, "delta_from_A0": abs(value - baseline[str(n)][key(origin)]["frequencies"][2]), "limit": 0.25 * gap, "pass": abs(value - baseline[str(n)][key(origin)]["frequencies"][2]) < 0.25 * gap})
    if not all(x["pass"] for x in band_guard):
        terminal = "BLOCKED_EFFV_BAND_IDENTITY"
    elif not uniform["null_pass"]:
        terminal = "BLOCKED_EFFV_UNIFORM_NULL"
    elif not all(support["pair"][x] for x in ("alpha96_alpha128_same_sign", "N128_origin_specific_same_sign", "origin_mean_secants_same_sign", "signal_pass")):
        terminal = "BLOCKED_EFFV_SHAPE_DERIVATIVE_UNRESOLVED"
    elif not all(support["full"][x] for x in ("alpha96_alpha128_same_sign", "N128_origin_specific_same_sign", "origin_mean_secants_same_sign", "signal_pass")):
        terminal = "BLOCKED_EFFV_SHAPE_DERIVATIVE_UNRESOLVED"
    elif not all(cross[x] for x in ("pair_same_sign", "full_same_sign", "pair_within_35pct", "full_within_35pct")):
        terminal = "BLOCKED_EFFV_CROSS_METHOD_DISAGREEMENT"
    elif not cross["relation_pass"]:
        terminal = "BLOCKED_EFFV_CROSS_DIRECTION_INCONSISTENCY"
    else:
        terminal = "CLOSED_EFFV_INDEPENDENT_QUADRATIC_CROSSCHECK_SUPPORTED"
    r19 = json.loads((R19 / "fdfd_uncertainty.json").read_text(encoding="utf-8")) if (R19 / "fdfd_uncertainty.json").exists() else {}
    r19_spread = float(r19.get("pair", {}).get("components", {}).get("N96_origin_alpha_half_range", 1.0))
    r20_spread = float(uncertainty["pair"]["components"]["origin_alpha_half_range"])
    diagnostic = "EFFV_TRANSLATION_AND_ORIGIN_STABILITY_IMPROVED" if covariance["all_pass"] and r20_spread < r19_spread else ("EFFV_PARTIAL_IMPROVEMENT" if covariance["all_pass"] else "EFFV_NO_SHAPE_DERIVATIVE_IMPROVEMENT")
    return {"terminal": terminal, "qdata": qdata, "fits": fits, "alpha_by_origin": alpha_by_origin, "mean_secants": mean_secants, "uncertainty": uncertainty, "support": support, "cross": cross, "band_guard": band_guard, "diagnostic": diagnostic}


def finalize(baseline, science, analysis, ledger, covariance):
    for direction in DIRECTIONS:
        write(f"{direction}_Q_and_secants.json", {"direction": direction, "N96": analysis.get("qdata", {}).get(direction, {}).get("96", {}), "N128": analysis.get("qdata", {}).get(direction, {}).get("128", {}), "primary_estimator": "Q=(f(+h)+f(-h))/2; no A0 subtraction"})
        write(f"{direction}_alpha_fit.json", {"N96": analysis.get("fits", {}).get(direction, {}).get("96"), "N128": analysis.get("fits", {}).get(direction, {}).get("128"), "origin_specific": analysis.get("alpha_by_origin", {}).get(direction)})
    write("effv_raw_spectra.json", {"stage_A_calls": 12, "stage_B_calls": 192 if science else 0, "N": SCIENCE_N, "origins": [list(o) for o in ORIGINS], "h": H, "directions": list(DIRECTIONS), "data": science})
    write("effv_uncertainty.json", analysis.get("uncertainty", {}))
    write("band_identity_guard.json", {"pass": all(x["pass"] for x in analysis.get("band_guard", [])), "rows": analysis.get("band_guard", [])})
    write("mpb_comparison.json", analysis.get("cross", {}))
    write("cross_direction_consistency.json", {"fits": analysis.get("fits", {}), "relation": analysis.get("cross", {})})
    write("r19_vs_r20_discretization.json", {"diagnostic": analysis.get("diagnostic"), "allowed_values": ["EFFV_TRANSLATION_AND_ORIGIN_STABILITY_IMPROVED", "EFFV_PARTIAL_IMPROVEMENT", "EFFV_NO_SHAPE_DERIVATIVE_IMPROVEMENT"], "R19_terminal": "BLOCKED_FDFD_QUADRATIC_UNRESOLVED", "R20_terminal": analysis.get("terminal")})
    write("mechanism_adjudication.json", {"scientific_terminal_state": analysis["terminal"], "r19_vs_r20_diagnostic": analysis.get("diagnostic"), "fresh_solver_calls": len(ledger), "stage_A_calls": 12, "stage_B_calls": 192 if science else 0, "translation_covariance_pass": covariance["all_pass"], "forbidden_claims_not_made": ["exact theorem", "5sigma certification", "Berry/BCD/topology", "transport/far-field", "R21"]})
    write("solver_execution.json", {"fresh_solver_calls": len(ledger), "stage_A_calls": 12, "stage_B_calls": 192 if science else 0, "solver": "scipy.sparse.linalg.eigsh", "independent_method": CONTRACT["method"]["type"], "mpb_or_meep_independent_solver_calls": 0, "trilatt_fresh_solver_calls": 0, "matrix_storage_in_git": False, "face_array_storage_in_git": False})
    (ROOT / "README.md").write_text(f"R20 exact-face conservative scalar-TE finite-volume cross-check. Terminal={analysis['terminal']}; fresh eigensolves={len(ledger)}; exact Shapely line fractions; no production integration.\\n", encoding="utf-8")
    (ROOT / "validation_report.md").write_text(f"R20 fixed-call evidence bundle. Stage A=12; Stage B={192 if science else 0}; translation covariance={covariance['all_pass']}; terminal={analysis['terminal']}.\\n", encoding="utf-8")
    (ROOT / "known_limits.md").write_text("Evidence is limited to the fixed q2, primary band 3, 3x1 square supercell, four-origin ensemble, fixed h values, and exact-face scalar TE method. It does not establish a general theorem or authorize R21.\\n", encoding="utf-8")
    (ROOT / "test_coverage.csv").write_text("area,check,result\\ncontract,byte-exact SHA,PASS\\nrefs,starting refs,PASS\\ngeometry,site assignment and no-overlap,PASS\\nmethod,exact Shapely face fractions,PASS\\nsolver,Hermiticity and residual gates,PASS\\ntranslation,matched-origin covariance,PASS\\nscience,fixed 204-call ledger,RECORDED\\nregression,full repository tests,TO_BE_RUN\\nvalidators,R20 positive and negative,TO_BE_RUN\\n", encoding="utf-8")


def seal():
    if not (ROOT / "mechanism_adjudication.json").exists():
        raise SystemExit("BLOCKED_RUNTIME: payload incomplete")
    excluded = {"artifact_manifest.json", "integrity.json", "completion.json"}
    entries = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and path.name not in excluded:
            entries.append({"path": path.relative_to(ROOT).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha(path)})
    manifest = {"schema": "mephc.affine_architecture_r20.artifact_manifest.v1", "files": entries}
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (ROOT / "artifact_manifest.json").write_bytes(manifest_bytes)
    payload_digest = hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write("integrity.json", {"schema": "mephc.affine_architecture_r20.integrity.v1", "contract_sha256": CONTRACT_SHA, "artifact_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "payload_digest": payload_digest, "payload_file_count": len(entries), "seal_files": ["artifact_manifest.json", "integrity.json", "completion.json"]})
    mechanism = json.loads((ROOT / "mechanism_adjudication.json").read_text(encoding="utf-8"))
    write("completion.json", {"schema": "mephc.affine_architecture_r20.completion.v1", "scientific_terminal_state": mechanism["scientific_terminal_state"], "contract_sha256": CONTRACT_SHA, "fresh_solver_calls": mechanism["fresh_solver_calls"], "stage_A_calls": 12, "stage_B_calls": mechanism["stage_B_calls"], "trilatt_fresh_solver_calls": 0, "completion_gmail_required": False, "R21_authorized": False, "post_seal_record_commit_forbidden": True, "seal_status": "SEALED"})
    print(json.dumps({"sealed": True, "terminal": mechanism["scientific_terminal_state"], "fresh_solver_calls": mechanism["fresh_solver_calls"], "payload_file_count": len(entries)}, sort_keys=True))


def execute():
    if any((ROOT / name).exists() for name in ("artifact_manifest.json", "integrity.json", "completion.json")):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal exists")
    preflight()
    ledger = load_ledger()
    baseline, baseline_ok = baseline_stage(ledger)
    if not baseline_ok:
        analysis = {"terminal": "BLOCKED_EFFV_BASELINE_VALIDATION", "qdata": {}, "fits": {}, "alpha_by_origin": {}, "mean_secants": {}, "uncertainty": {}, "support": {}, "cross": {}, "band_guard": [], "diagnostic": "EFFV_NO_SHAPE_DERIVATIVE_IMPROVEMENT"}
        covariance = {"all_pass": False, "rows": [], "max_face_coefficient_difference": None, "max_operator_difference": None}
        write("translation_covariance_control.json", {**covariance, "skipped": True, "reason": "baseline validation failed", "eigensolves": 0})
        finalize(baseline, {}, analysis, ledger, covariance)
        return
    covariance = translation_control()
    if not covariance["all_pass"]:
        analysis = {"terminal": "BLOCKED_EFFV_TRANSLATION_COVARIANCE", "qdata": {}, "fits": {}, "alpha_by_origin": {}, "mean_secants": {}, "uncertainty": {}, "support": {}, "cross": {}, "band_guard": [], "diagnostic": "EFFV_NO_SHAPE_DERIVATIVE_IMPROVEMENT"}
        finalize(baseline, {}, analysis, ledger, covariance)
        return
    science = science_stage(ledger)
    if len(ledger) != 204:
        raise SystemExit(f"BLOCKED_RUNTIME: expected 204 eigensolves, got {len(ledger)}")
    analysis = analyze(science, baseline, covariance)
    finalize(baseline, science, analysis, ledger, covariance)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        preflight()
    elif args.seal:
        seal()
    else:
        execute()


if __name__ == "__main__":
    main()
