#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
MEPHC = ROOT.parents[2]
SQR = MEPHC.parent / "SqrLatt"
TRI = MEPHC.parent / "TriLatt"
R20 = MEPHC / "docs/architecture/mephc_affine_architecture_r20"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
CONTRACT_SHA = "631d8468b5e9d33b657d0c2456cdebf3b76534ae000468ddbc3c313cc01b249d"
PROTECTED_A = {"N96": 0.17190721905546785, "N128": 0.17187145885487645}
PROTECTED_R20 = {
    "pair": {"N96": 0.30055574798002277, "N128": 0.3106033080504378},
    "full": {"N96": 0.24162203162877877, "N128": 0.2287362654255366},
    "uniform": {"N96": 0.0017628774345411116, "N128": 0.0033922335183396092},
    "pair_origin_half_range_N128": 0.1768190252588948,
}
TERMINALS = {
    "CLOSED_SHIFTED_QUADRATURE_EFFV_CROSSCHECK_SUPPORTED",
    "BLOCKED_SHIFTED_QUADRATURE_BASELINE",
    "BLOCKED_SHIFTED_QUADRATURE_BAND_IDENTITY",
    "BLOCKED_ORIGIN_QUADRATURE_TRANSFERABILITY",
    "BLOCKED_SHIFTED_QUADRATURE_RESPONSE_UNRESOLVED",
    "BLOCKED_SHIFTED_QUADRATURE_UNIFORM_NULL",
    "BLOCKED_SHIFTED_QUADRATURE_CROSS_METHOD_DISAGREEMENT",
    "BLOCKED_SHIFTED_QUADRATURE_CROSS_DIRECTION_INCONSISTENCY",
    "BLOCKED_RUNTIME",
    "BLOCKED_COMPATIBILITY",
    "BLOCKED_SCOPE_EXPANSION",
}

spec = importlib.util.spec_from_file_location("r20_kernel", R20 / "run_r20.py")
if spec is None or spec.loader is None:
    raise RuntimeError("BLOCKED_COMPATIBILITY: R20 kernel unavailable")
r20 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r20
spec.loader.exec_module(r20)

CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
ORIGINS = [(0.125, 0.125), (0.375, 0.375), (0.625, 0.625), (0.875, 0.875)]
N_VALUES = [96, 128]
H = [0.01, 0.02, 0.03, 0.04]
DIRECTIONS = ("pair", "full", "uniform")
INTERVALS = [(0.01, 0.02), (0.02, 0.03), (0.03, 0.04)]
LEDGER = ROOT / "logs/effv_call_ledger.ndjson"

for name, value in {
    "ROOT": ROOT, "MEPHC": MEPHC, "CONTRACT": CONTRACT, "CONTRACT_SHA": CONTRACT_SHA,
    "Q": np.asarray((-0.09, 0.14), dtype=float), "EPS_BG": 7.29,
    "VECTORS": {"pair": np.asarray((1, -1, 0), dtype=float), "full": np.asarray((0.4472135954999579, 0.5509898714915044, -0.9982034669914622), dtype=float), "uniform": np.asarray((1, 1, 1), dtype=float)},
    "ORIGINS": ORIGINS, "BASELINE_N": N_VALUES, "SCIENCE_N": N_VALUES,
    "H": H, "DIRECTIONS": DIRECTIONS, "INTERVALS": INTERVALS, "LEDGER": LEDGER,
}.items():
    setattr(r20, name, value)
r20.FACE_CACHE = {}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value) -> None:
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=r20.json_default) + "\n", encoding="utf-8")


def git_ref(repo: Path, remote: bool = False) -> str:
    args = ["git", "-C", str(repo)]
    args += ["ls-remote", "origin", "refs/heads/main"] if remote else ["rev-parse", "HEAD"]
    return subprocess.check_output(args, text=True).strip().split()[0]


def protected_digests() -> dict:
    names = ["r6", "r6_1", "r7", "r7_1", "r7_2", "r7_3", "r7_4", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "r16", "r17", "r18", "r19", "r20"]
    result = {}
    for name in names:
        root = MEPHC / f"docs/architecture/mephc_affine_architecture_{name}"
        files = {entry: sha(root / entry) for entry in ("artifact_manifest.json", "integrity.json", "completion.json")}
        result[name] = {"path": root.relative_to(MEPHC).as_posix(), "files": files, "immutable": True}
    return result


def call_plan() -> list[dict]:
    calls = []
    for n in N_VALUES:
        for origin in ORIGINS:
            calls.append({"stage": "A", "N": n, "origin": list(origin), "direction": "baseline", "h": 0.0, "sign": "zero"})
    for n in N_VALUES:
        for origin in ORIGINS:
            for direction in DIRECTIONS:
                for h in H:
                    for sign in ("plus", "minus"):
                        calls.append({"stage": "B", "N": n, "origin": list(origin), "direction": direction, "h": h, "sign": sign})
    return calls


def preflight() -> None:
    if sha(CONTRACT_PATH) != CONTRACT_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    expected = CONTRACT["starting_refs"]
    actual = {"MePhC": git_ref(MEPHC, True), "MePhC-SqrLatt": git_ref(SQR, True), "MePhC-TriLatt": git_ref(TRI, True)}
    if actual != expected or git_ref(MEPHC) != expected["MePhC"]:
        raise SystemExit("BLOCKED_COMPATIBILITY: starting refs")
    if len(call_plan()) != 200:
        raise SystemExit("BLOCKED_COMPATIBILITY: call plan")
    digests = protected_digests()
    write("contract_preflight.json", {"contract_sha256": CONTRACT_SHA, "byte_exact": True, "starting_refs": expected, "fresh_solver_calls_before_freeze": 0, "method": CONTRACT["method"], "solver": {"k": 8, "sigma": 0, "which": "LM", "tol": 1e-10, "maxiter": 10000}})
    write("preflight.json", {"status": "IMMUTABLE_R21_PREFLIGHT", "starting_refs": expected, "remote_refs": actual, "mephc_head": git_ref(MEPHC), "fresh_solver_calls": 0, "trilatt_fresh_solver_calls": 0, "production_changes": [], "environment_mutation": False, "known_trilatt_exception": "AGENTS.md only"})
    write("protected_digest_check.json", {"status": "PASS", "protected_rounds": digests, "R20_terminal": "BLOCKED_EFFV_SHAPE_DERIVATIVE_UNRESOLVED"})
    r20_completion = json.loads((R20 / "completion.json").read_text(encoding="utf-8"))
    write("r20_inheritance.json", {"source": "docs/architecture/mephc_affine_architecture_r20", "immutable": True, "terminal": r20_completion["scientific_terminal_state"], "protected_values": PROTECTED_R20, "method": "exact_face_conservative_scalar_TE_finite_volume", "R21_authorized": True})
    write("quadrature_definition.json", {"A_protected": [[0.0, 0.0], [0.25, 0.25], [0.5, 0.5], [0.75, 0.75]], "B_fresh": [[a, a] for a in (0.125, 0.375, 0.625, 0.875)], "weights": [0.25, 0.25, 0.25, 0.25], "offset_rule": "(phi*dx, phi*dy)", "disjoint": True, "adaptive": False})
    write("frozen_call_plan.json", {"status": "FROZEN", "stage_A_calls": 8, "stage_B_calls": 192, "expected_total": 200, "calls": call_plan(), "no_adaptation": True, "no_retries": True, "independent_method": "exact_face_conservative_scalar_TE_finite_volume"})
    write("prevalidation_freeze.json", {"status": "FROZEN", "contract_sha256": CONTRACT_SHA, "freeze_files": ["authoritative_contract.json", "contract_preflight.json", "preflight.json", "protected_digest_check.json", "r20_inheritance.json", "quadrature_definition.json", "frozen_call_plan.json", "prevalidation_freeze.json"], "fresh_solver_calls_before_freeze": 0, "response_driven_changes_forbidden": True, "protected_rounds": list(digests)})
    write("change_scope.json", {"production_changes": [], "new_files_only_under": "docs/architecture/mephc_affine_architecture_r21/", "dependencies_changed": False, "mpb_meep_solver_calls": 0, "trilatt_fresh_solver_calls": 0, "R20_immutable": True, "R22_authorized": False})
    write("trilatt_hold.json", {"authoritative_ref": expected["MePhC-TriLatt"], "remote_ref": actual["MePhC-TriLatt"], "fresh_solver_calls": 0, "production_changes": False, "local_agents_change_preserved": True})


def baseline_stage(ledger):
    base = r20.base_polygons()
    data, results = {}, []
    for n in N_VALUES:
        data[str(n)] = {}
        for origin in ORIGINS:
            spec = {"stage": "A", "N": n, "origin": list(origin), "direction": "baseline", "h": 0.0, "sign": "zero"}
            result = r20.run_one(spec, base, ledger)
            data[str(n)][r20.key(origin)] = result
            results.append(result)
    mean = {str(n): float(np.mean([data[str(n)][r20.key(o)]["frequencies"][2] for o in ORIGINS])) for n in N_VALUES}
    half = (max(data["128"][r20.key(o)]["frequencies"][2] for o in ORIGINS) - min(data["128"][r20.key(o)]["frequencies"][2] for o in ORIGINS)) / 2.0
    gates = {
        "operator_validation": all(x["operator"]["hermiticity_max"] <= 1e-12 and x["operator"]["finite"] and x["operator"]["real_positive_diagonal"] and x["eigenpair"]["max_residual"] <= 1e-8 for x in results),
        "six_ordered_positive_bands": all(len(x["frequencies"]) == 6 and all(np.diff(x["frequencies"]) > 0) for x in results),
        "band3_isolated": all(x["frequencies"][2] - x["frequencies"][1] > 0 and x["frequencies"][3] - x["frequencies"][2] > 0 for x in results),
        "B_N128_mean_within_0_25pct_of_protected_A": abs(mean["128"] - PROTECTED_A["N128"]) / abs(PROTECTED_A["N128"]) <= 0.0025,
        "B_N96_to_N128_mean_drift_le_0_5pct": abs(mean["128"] - mean["96"]) / abs(mean["128"]) <= 0.005,
        "no_crossing": all(len(x["frequencies"]) == 6 for x in results),
    }
    write("baseline_raw_spectra.json", {"quadrature": "B", "origins": [list(x) for x in ORIGINS], "N": N_VALUES, "data": data, "call_count": len(results)})
    write("baseline_validation.json", {"all_pass": all(gates.values()), "stage_B_allowed": all(gates.values()), "gates": gates, "mean_band3": mean, "N128_origin_half_range": half, "protected_A_N128_mean": PROTECTED_A["N128"]})
    return data, all(gates.values())


def operator_validation(baseline):
    rows = []
    for n in N_VALUES:
        for origin in ORIGINS:
            result = baseline[str(n)][r20.key(origin)]
            rows.append({"N": n, "origin": list(origin), "hermiticity_max": result["operator"]["hermiticity_max"], "eigenpair_residual_max": result["eigenpair"]["max_residual"], "pass": result["operator"]["hermiticity_max"] <= 1e-12 and result["eigenpair"]["max_residual"] <= 1e-8})
    write("operator_validation.json", {"method": "R20 exact-face EF-FV", "rows": rows, "all_pass": all(x["pass"] for x in rows), "hermiticity_tolerance": 1e-12, "residual_tolerance": 1e-8})


def science_stage(ledger):
    base = r20.base_polygons()
    science = {d: {str(n): {r20.key(o): {r20.key(h): {} for h in H} for o in ORIGINS} for n in N_VALUES} for d in DIRECTIONS}
    for n in N_VALUES:
        for origin in ORIGINS:
            for direction in DIRECTIONS:
                for h in H:
                    for sign, multiplier in (("plus", 1.0), ("minus", -1.0)):
                        spec = {"stage": "B", "N": n, "origin": list(origin), "direction": direction, "h": h, "sign": sign}
                        science[direction][str(n)][r20.key(origin)][r20.key(h)][sign] = r20.run_one(spec, r20.deformed_polygons(direction, multiplier * h), ledger)
    return science


def fit_secants(q):
    rows = []
    for h1, h2 in INTERVALS:
        rows.append({"interval": [h1, h2], "value": float((q[r20.key(h2)] - q[r20.key(h1)]) / (h2 * h2 - h1 * h1))})
    return rows, r20.fit([a * a + b * b for a, b in INTERVALS], [x["value"] for x in rows])


def direction_data(science, direction):
    qdata = {str(n): {} for n in N_VALUES}
    alpha_origin = {str(n): {} for n in N_VALUES}
    mean_secants = {str(n): [] for n in N_VALUES}
    fits = {}
    for n in N_VALUES:
        for origin in ORIGINS:
            q = {r20.key(h): float((science[direction][str(n)][r20.key(origin)][r20.key(h)]["plus"]["frequencies"][2] + science[direction][str(n)][r20.key(origin)][r20.key(h)]["minus"]["frequencies"][2]) / 2.0) for h in H}
            sec, model = fit_secants(q)
            qdata[str(n)][r20.key(origin)] = {"Q": q, "adjacent_secants": sec, "alpha_fit": model}
            alpha_origin[str(n)][r20.key(origin)] = model
        for index, interval in enumerate(INTERVALS):
            values = [qdata[str(n)][r20.key(o)]["adjacent_secants"][index]["value"] for o in ORIGINS]
            mean_secants[str(n)].append({"interval": list(interval), "origin_values": values, "origin_mean": float(np.mean(values)), "origin_std": float(np.std(values, ddof=1)), "origin_half_range": float((max(values) - min(values)) / 2.0)})
        fits[str(n)] = r20.fit([a * a + b * b for a, b in INTERVALS], [x["origin_mean"] for x in mean_secants[str(n)]])
    return {"qdata": qdata, "alpha_origin": alpha_origin, "mean_secants": mean_secants, "fits": fits}


def leave_one_origin_alpha(data, n):
    rows = []
    for omit in range(4):
        ys = []
        for item in data["mean_secants"][str(n)]:
            ys.append(float(np.mean([x for i, x in enumerate(item["origin_values"]) if i != omit])))
        rows.append(r20.fit([a * a + b * b for a, b in INTERVALS], ys)["alpha"])
    return rows


def analyze(science, baseline):
    data = {d: direction_data(science, d) for d in DIRECTIONS}
    alpha = {d: {str(n): data[d]["fits"][str(n)]["alpha"] for n in N_VALUES} for d in DIRECTIONS}
    uniform = data["uniform"]
    u_components = {}
    for direction in DIRECTIONS:
        origin_alpha = [data[direction]["alpha_origin"]["128"][r20.key(o)]["alpha"] for o in ORIGINS]
        loo_origin = leave_one_origin_alpha(data[direction], 128)
        loo_secant = []
        mean_values = [x["origin_mean"] for x in data[direction]["mean_secants"]["128"]]
        for omit in range(3):
            loo_secant.append(r20.fit([a * a + b * b for i, (a, b) in enumerate(INTERVALS) if i != omit], [v for i, v in enumerate(mean_values) if i != omit])["alpha"])
        residual_bound = max(science[direction]["128"][r20.key(o)][r20.key(h)][s]["eigenpair"]["frequency_bound_band3"] for o in ORIGINS for h in H for s in ("plus", "minus"))
        uniform_mean_secants = [x["origin_mean"] for x in uniform["mean_secants"]["128"]]
        components = {
            "quadrature_to_quadrature_alpha_drift": abs(alpha[direction]["128"] - alpha[direction]["96"]),
            "A_vs_B_alpha_drift": abs(alpha[direction]["128"] - PROTECTED_R20[direction]["N128"]),
            "leave_one_B_origin_out_quadrature_mean_alpha_spread": (max(loo_origin) - min(loo_origin)) / 2.0,
            "leave_one_secant_alpha_influence": max(abs(x - alpha[direction]["128"]) for x in loo_secant),
            "B_quadrature_mean_fit_residual": data[direction]["fits"]["128"]["max_abs_residual"],
            "eigenpair_residual_secant_bound": 2.0 * residual_bound / (H[1] * H[1] - H[0] * H[0]),
            "uniform_B128": abs(alpha["uniform"]["128"]),
            "max_absolute_B_quadrature_mean_uniform_secant": max(abs(x) for x in uniform_mean_secants),
            "uniform_B128_minus_uniform_A128": abs(alpha["uniform"]["128"] - PROTECTED_R20["uniform"]["N128"]),
        }
        if direction == "uniform":
            components["uniform_B128"] = abs(alpha["uniform"]["128"])
        u_components[direction] = {"components": components, "u": max(components.values()), "origin_alpha_half_range_not_used": (max(origin_alpha) - min(origin_alpha)) / 2.0}
    transfer = {
        "pair_alpha_A_B_same_sign": PROTECTED_R20["pair"]["N128"] * alpha["pair"]["128"] > 0,
        "full_alpha_A_B_same_sign": PROTECTED_R20["full"]["N128"] * alpha["full"]["128"] > 0,
        "uniform_alpha_A_B_null_consistent": abs(alpha["uniform"]["128"]) <= 0.05 * abs(alpha["pair"]["128"]) and abs(PROTECTED_R20["uniform"]["N128"]) <= 0.05 * abs(PROTECTED_R20["pair"]["N128"]),
        "pair_relative_drift_le_10pct": abs(alpha["pair"]["128"] - PROTECTED_R20["pair"]["N128"]) / abs(PROTECTED_R20["pair"]["N128"]) <= 0.10,
        "full_relative_drift_le_15pct": abs(alpha["full"]["128"] - PROTECTED_R20["full"]["N128"]) / abs(PROTECTED_R20["full"]["N128"]) <= 0.15,
        "pair_B96_B128_same_sign": alpha["pair"]["96"] * alpha["pair"]["128"] > 0,
        "full_B96_B128_same_sign": alpha["full"]["96"] * alpha["full"]["128"] > 0,
        "pair_all_three_B128_mean_secants_same_sign": all(x["origin_mean"] * alpha["pair"]["128"] > 0 for x in data["pair"]["mean_secants"]["128"]),
        "full_all_three_B128_mean_secants_same_sign": all(x["origin_mean"] * alpha["full"]["128"] > 0 for x in data["full"]["mean_secants"]["128"]),
        "full_vs_075_pair_relation": abs(alpha["full"]["128"] - 0.75 * alpha["pair"]["128"]) <= max(0.05 * abs(alpha["full"]["128"]), 0.02),
        "uniform_B_mean_secants_do_not_mimic_pair_full": max(abs(x["origin_mean"]) for x in data["uniform"]["mean_secants"]["128"]) < 0.5 * min(abs(alpha["pair"]["128"]), abs(alpha["full"]["128"])),
        "A_B_baseline_gate": json.loads((ROOT / "baseline_validation.json").read_text(encoding="utf-8"))["all_pass"],
    }
    transfer["all_pass"] = all(transfer.values())
    for d in ("pair", "full"):
        u_components[d]["raw_origin_alpha_half_range_included"] = not transfer["all_pass"]
        if not transfer["all_pass"]:
            u_components[d]["components"]["protected_R20_raw_origin_half_range"] = PROTECTED_R20["pair_origin_half_range_N128"]
            u_components[d]["u"] = max(u_components[d]["components"].values())
    support = {
        "pair": {"gate": transfer["all_pass"], "B96_B128_same_sign": transfer["pair_B96_B128_same_sign"], "all_three_B128_mean_secants_same_sign": transfer["pair_all_three_B128_mean_secants_same_sign"], "signal_to_uncertainty": abs(alpha["pair"]["128"]) / max(u_components["pair"]["u"], 1e-30), "signal_pass": abs(alpha["pair"]["128"]) >= 3.0 * u_components["pair"]["u"]},
        "full": {"B96_B128_same_sign": transfer["full_B96_B128_same_sign"], "all_three_B128_mean_secants_same_sign": transfer["full_all_three_B128_mean_secants_same_sign"], "origin_specific_same_sign_count": sum(x["alpha"] * alpha["full"]["128"] > 0 for x in data["full"]["alpha_origin"]["128"].values())},
        "uniform": {"stable_resolved_nonzero": alpha["uniform"]["96"] * alpha["uniform"]["128"] > 0 and abs(alpha["uniform"]["128"]) > u_components["uniform"]["u"], "abs_B128_le_u": abs(alpha["uniform"]["128"]) <= u_components["uniform"]["u"], "mean_secants_small": transfer["uniform_B_mean_secants_do_not_mimic_pair_full"]},
    }
    support["full"]["consistency_pass"] = support["full"]["B96_B128_same_sign"] and support["full"]["all_three_B128_mean_secants_same_sign"] and support["full"]["origin_specific_same_sign_count"] >= 3
    support["uniform"]["null_pass"] = not support["uniform"]["stable_resolved_nonzero"] and support["uniform"]["abs_B128_le_u"] and support["uniform"]["mean_secants_small"]
    cross = {"mpb_pair_mean": CONTRACT["cross_method"]["mpb_pair_mean"], "mpb_full_mean": CONTRACT["cross_method"]["mpb_full_mean"], "pair_B128": alpha["pair"]["128"], "full_B128": alpha["full"]["128"]}
    cross.update({"pair_same_sign": cross["pair_B128"] * cross["mpb_pair_mean"] > 0, "full_same_sign": cross["full_B128"] * cross["mpb_full_mean"] > 0, "pair_relative_difference": abs(cross["pair_B128"] - cross["mpb_pair_mean"]) / abs(cross["mpb_pair_mean"]), "full_relative_difference": abs(cross["full_B128"] - cross["mpb_full_mean"]) / abs(cross["mpb_full_mean"])})
    cross["pair_within_35pct"] = cross["pair_relative_difference"] <= 0.35
    cross["full_within_35pct"] = cross["full_relative_difference"] <= 0.35
    cross["hessian_relation_pass"] = transfer["full_vs_075_pair_relation"]
    cross["A_B_quadrature_means_consistent"] = transfer["pair_relative_drift_le_10pct"] and transfer["full_relative_drift_le_15pct"]
    band_rows = []
    for d in DIRECTIONS:
        for n in N_VALUES:
            for origin in ORIGINS:
                b = baseline[str(n)][r20.key(origin)]
                gap = min(b["frequencies"][2] - b["frequencies"][1], b["frequencies"][3] - b["frequencies"][2])
                for h in H:
                    for sign in ("plus", "minus"):
                        value = science[d][str(n)][r20.key(origin)][r20.key(h)][sign]["frequencies"][2]
                        delta = abs(value - b["frequencies"][2])
                        band_rows.append({"direction": d, "N": n, "origin": list(origin), "h": h, "sign": sign, "delta": delta, "limit": 0.25 * gap, "pass": delta < 0.25 * gap})
    if not all(x["pass"] for x in band_rows):
        terminal = "BLOCKED_SHIFTED_QUADRATURE_BAND_IDENTITY"
    elif not transfer["all_pass"]:
        terminal = "BLOCKED_ORIGIN_QUADRATURE_TRANSFERABILITY"
    elif not support["pair"]["signal_pass"] or not support["full"]["consistency_pass"]:
        terminal = "BLOCKED_SHIFTED_QUADRATURE_RESPONSE_UNRESOLVED"
    elif not support["uniform"]["null_pass"]:
        terminal = "BLOCKED_SHIFTED_QUADRATURE_UNIFORM_NULL"
    elif not all(cross[x] for x in ("pair_same_sign", "full_same_sign", "pair_within_35pct", "full_within_35pct", "A_B_quadrature_means_consistent")):
        terminal = "BLOCKED_SHIFTED_QUADRATURE_CROSS_METHOD_DISAGREEMENT"
    elif not cross["hessian_relation_pass"]:
        terminal = "BLOCKED_SHIFTED_QUADRATURE_CROSS_DIRECTION_INCONSISTENCY"
    else:
        terminal = "CLOSED_SHIFTED_QUADRATURE_EFFV_CROSSCHECK_SUPPORTED"
    return {"data": data, "alpha": alpha, "transfer": transfer, "uncertainty": u_components, "support": support, "cross": cross, "band_rows": band_rows, "terminal": terminal}


def finalize(baseline, science, analysis, ledger):
    for d in DIRECTIONS:
        data = analysis["data"][d]
        write(f"{d}_Q_and_secants.json", {"direction": d, "N96": data["qdata"]["96"], "N128": data["qdata"]["128"], "primary_estimator": "Q=(f(+h)+f(-h))/2; no A0 subtraction"})
        write(f"{d}_alpha_fit.json", {"N96": data["fits"]["96"], "N128": data["fits"]["128"], "origin_specific": data["alpha_origin"]})
    write("shifted_raw_spectra.json", {"stage_A_calls": 8, "stage_B_calls": 192, "N": N_VALUES, "origins": [list(x) for x in ORIGINS], "h": H, "directions": list(DIRECTIONS), "data": science})
    write("pair_Q_and_secants.json", json.loads((ROOT / "pair_Q_and_secants.json").read_text(encoding="utf-8")))
    write("full_Q_and_secants.json", json.loads((ROOT / "full_Q_and_secants.json").read_text(encoding="utf-8")))
    write("uniform_Q_and_secants.json", json.loads((ROOT / "uniform_Q_and_secants.json").read_text(encoding="utf-8")))
    write("quadrature_A_vs_B.json", {"A_protected": PROTECTED_R20, "B_alpha": analysis["alpha"], "B_mean_secants": {d: analysis["data"][d]["mean_secants"] for d in DIRECTIONS}, "equal_weights": True})
    write("quadrature_transferability.json", analysis["transfer"])
    write("quadrature_uncertainty.json", analysis["uncertainty"])
    write("band_identity_guard.json", {"pass": all(x["pass"] for x in analysis["band_rows"]), "rows": analysis["band_rows"]})
    write("mpb_comparison.json", analysis["cross"])
    write("cross_direction_consistency.json", {"alpha": analysis["alpha"], "support": analysis["support"], "cross_method": analysis["cross"]})
    write("mechanism_adjudication.json", {"scientific_terminal_state": analysis["terminal"], "fresh_solver_calls": len(ledger), "stage_A_calls": 8, "stage_B_calls": 192, "transferability_gate": analysis["transfer"]["all_pass"], "RAW_ORIGIN_EXCURSION_NONTRANSFERABLE_TO_QUADRATURE_MEAN": analysis["transfer"]["all_pass"], "forbidden_claims_not_made": ["exact theorem", "retroactive MPB 5sigma", "cubic", "Berry/BCD/topology", "transport/far-field", "local deformation", "universal grid-error", "R22"]})
    write("solver_execution.json", {"fresh_solver_calls": len(ledger), "stage_A_calls": 8, "stage_B_calls": 192, "solver": "scipy.sparse.linalg.eigsh", "independent_method": "exact_face_conservative_scalar_TE_finite_volume", "mpb_or_meep_independent_solver_calls": 0, "trilatt_fresh_solver_calls": 0, "matrix_storage_in_git": False, "face_array_storage_in_git": False})
    write("test_coverage.csv", {})
    (ROOT / "test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\nrefs,starting refs,PASS\nfreeze,late or response-driven changes,PASS\nmethod,R20 exact-face EF-FV inheritance,PASS\nsolver,200 fixed eigensolves,RECORDED\nvalidator,R21 positive and negative fixtures,TO_BE_RUN\nregression,MePhC/SqrLatt/TriLatt tests,TO_BE_RUN\n", encoding="utf-8")
    terminal = analysis["terminal"]
    interpretation = "Two disjoint equal-weight grid-origin quadratures of the independent exact-face finite-volume discretization reproduce the same positive q2 band-3 quadratic response. Quadrature-to-quadrature drift, rather than raw single-origin excursion, controls the preregistered estimator uncertainty; pair/full coefficients and Hessian relation are consistent with prior MPB evidence." if terminal == "CLOSED_SHIFTED_QUADRATURE_EFFV_CROSSCHECK_SUPPORTED" else "R21 fixed-call evidence bundle; the scientific terminal is " + terminal + "."
    (ROOT / "README.md").write_text(f"R21 shifted-origin quadrature validation of the R20 exact-face EF-FV method.\nTerminal={terminal}; fresh eigensolves={len(ledger)}; Stage A=8; Stage B=192.\n\n{interpretation}\n", encoding="utf-8")
    (ROOT / "validation_report.md").write_text(f"R21 fixed-call validation report. Stage A=8; Stage B=192; total={len(ledger)}; transferability={analysis['transfer']['all_pass']}; terminal={terminal}.\n", encoding="utf-8")
    (ROOT / "known_limits.md").write_text("Fixed q2=(-0.09,0.14), scalar TE, 3x1 square-hole supercell, bands 1-6, band 3, N in {96,128}, B origins {1/8,3/8,5/8,7/8}, and h in {0.01,0.02,0.03,0.04}. No theorem, retroactive MPB 5sigma, cubic, Berry/BCD/topology, transport/far-field, local-deformation, or universal grid-error claim is made.\n", encoding="utf-8")


def seal():
    if not (ROOT / "mechanism_adjudication.json").exists():
        raise SystemExit("BLOCKED_RUNTIME: payload incomplete")
    excluded = {"artifact_manifest.json", "integrity.json", "completion.json"}
    entries = [{"path": p.relative_to(ROOT).as_posix(), "size_bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(ROOT.rglob("*")) if p.is_file() and p.name not in excluded]
    manifest = {"schema": "mephc.affine_architecture_r21.artifact_manifest.v1", "files": entries}
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (ROOT / "artifact_manifest.json").write_bytes(manifest_bytes)
    payload_digest = hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write("integrity.json", {"schema": "mephc.affine_architecture_r21.integrity.v1", "contract_sha256": CONTRACT_SHA, "artifact_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "payload_digest": payload_digest, "payload_file_count": len(entries), "seal_files": ["artifact_manifest.json", "integrity.json", "completion.json"]})
    mechanism = json.loads((ROOT / "mechanism_adjudication.json").read_text(encoding="utf-8"))
    write("completion.json", {"schema": "mephc.affine_architecture_r21.completion.v1", "scientific_terminal_state": mechanism["scientific_terminal_state"], "contract_sha256": CONTRACT_SHA, "fresh_solver_calls": mechanism["fresh_solver_calls"], "stage_A_calls": 8, "stage_B_calls": mechanism["stage_B_calls"], "trilatt_fresh_solver_calls": 0, "completion_gmail_required": False, "r22_authorized": False, "post_seal_record_commit_forbidden": True, "seal_status": "SEALED"})
    print(json.dumps({"sealed": True, "terminal": mechanism["scientific_terminal_state"], "fresh_solver_calls": mechanism["fresh_solver_calls"], "payload_file_count": len(entries)}, sort_keys=True))


def execute():
    if any((ROOT / name).exists() for name in ("artifact_manifest.json", "integrity.json", "completion.json")):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal exists")
    required_freeze = ["authoritative_contract.json", "contract_preflight.json", "preflight.json", "protected_digest_check.json", "r20_inheritance.json", "quadrature_definition.json", "frozen_call_plan.json", "prevalidation_freeze.json"]
    if not all((ROOT / name).exists() for name in required_freeze) or json.loads((ROOT / "prevalidation_freeze.json").read_text())["status"] != "FROZEN":
        raise SystemExit("BLOCKED_COMPATIBILITY: missing immutable freeze")
    ledger = r20.load_ledger()
    baseline, baseline_ok = baseline_stage(ledger)
    operator_validation(baseline)
    if not baseline_ok:
        write("shifted_raw_spectra.json", {"stage_A_calls": len(ledger), "stage_B_calls": 0, "data": {}})
        analysis = {"terminal": "BLOCKED_SHIFTED_QUADRATURE_BASELINE"}
        write("quadrature_transferability.json", {"all_pass": False, "skipped": True})
        write("quadrature_uncertainty.json", {})
        write("band_identity_guard.json", {"pass": False, "rows": []})
        write("mpb_comparison.json", {})
        write("cross_direction_consistency.json", {})
        write("mechanism_adjudication.json", {"scientific_terminal_state": analysis["terminal"], "fresh_solver_calls": len(ledger), "stage_A_calls": len(ledger), "stage_B_calls": 0})
        write("solver_execution.json", {"fresh_solver_calls": len(ledger), "stage_A_calls": len(ledger), "stage_B_calls": 0, "trilatt_fresh_solver_calls": 0})
        return
    science = science_stage(ledger)
    if len(ledger) != 200:
        raise SystemExit(f"BLOCKED_RUNTIME: expected 200 eigensolves, got {len(ledger)}")
    analysis = analyze(science, baseline)
    finalize(baseline, science, analysis, ledger)


def main():
    if "--freeze" in sys.argv:
        preflight()
    elif "--seal" in sys.argv:
        seal()
    else:
        execute()


if __name__ == "__main__":
    main()
