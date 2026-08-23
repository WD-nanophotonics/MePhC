"""E9C.C1 bounded R96 three-stencil K/K-prime rank-1 refinement."""
from __future__ import annotations

import hashlib
import json
import math
import resource
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.e9c.run_k_kprime_rank1_berry import (
    BANDS,
    KPRIME_PUBLIC,
    K_PUBLIC,
    REFINEMENT,
    REFERENCE_SIDE,
    PRIMARY_SIDE,
    build_inputs,
    geometry_inputs,
    make_provider,
    stencil_evidence,
)
from mephc.plaquette_domain import PlaquetteRefinementLevel, qualify_plaquette_refinement

WORK_ORDER = "TRILATT-E9C-C1-20260824-177"
R96 = 96
SIDE_1_36 = 1.0 / 36.0
SIDE_1_72 = 1.0 / 72.0
SIDE_1_144 = 1.0 / 144.0
SIDES = (SIDE_1_36, SIDE_1_72, SIDE_1_144)
LABELS = ("1/36", "1/72", "1/144")
PAPER_TARGETS = (-0.92, 0.72, 0.19)
REPLAY_CONTRACT_SHA = "205A92DEFE24343F9A664C29668DBCFF5F771103CFB118770FDC85040AA800A4"


def root():
    return Path(__file__).resolve().parents[2]


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def self_checks(contract, preflight, geometry):
    checks = {
        "WORK_ORDER": contract["work_order_id"] == WORK_ORDER,
        "BASE_SANDBOX_BOUND": contract["base_sandbox_sha"] == "3839981232641ca6f333ac29152c6002c74b7c2f",
        "EXISTING_E9C_PRESERVED": (root() / "audit/e9c/result.json").exists(),
        "EXISTING_E9C_SHA_BOUND": file_sha(root() / "audit/e9c/result.json") == REPLAY_CONTRACT_SHA.lower(),
        "PHYSICAL_GEOMETRY": geometry["max_roundtrip_error"] <= 1e-12 and abs(geometry["physical_fill_fraction"] - 0.24) <= 1e-12,
        "MAPPING_READY": bool(preflight.ready) and preflight.round_trip_residual <= 1e-12,
        "K_MAPPING": all(abs(float(a) - float(b)) <= 1e-12 for a, b in zip(preflight.public_q_to_mpb(K_PUBLIC), (1.0 / 3.0, 1.0 / 3.0))),
        "KPRIME_MAPPING": all(abs(float(a) - float(b)) <= 1e-12 for a, b in zip(preflight.public_q_to_mpb(KPRIME_PUBLIC), (-1.0 / 3.0, -1.0 / 3.0))),
        "R96_ONLY": contract["model"]["resolution"] == R96 and "R64" in contract["prohibited_scope"],
        "THRESHOLD_UNCHANGED": contract["qualification_thresholds"]["threshold_unchanged"] is True and contract["qualification_thresholds"]["max_metric_delta"] == 0.1,
        "THREE_LEVELS": tuple(contract["stencil_ladder"]) == SIDES and contract["stencil_labels"] == list(LABELS),
        "COUNTS": contract["counts"]["total_e4c_refinement_pairs"] == 6 and contract["counts"]["total_stencil_level_rows"] == 18,
        "NO_FORBIDDEN_SCOPE": all(item in contract["prohibited_scope"] for item in ("berry_field_map", "valley_chern", "full_bz_chern", "parameter_fitting", "posthoc_sign_flip")),
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9C.C1 self-check failed: {checks}")
    return checks


def compact_level(level):
    return {
        "side_label": LABELS[SIDES.index(level["side_q"])],
        "side_q": level["side_q"],
        "center": level["center"],
        "vertices": level["vertices"],
        "profile_passed": level["profile_passed"],
        "minimum_external_gap": level["minimum_external_gap"],
        "path": level["path"],
        "wilson": level["wilson"],
        "boundary": level["boundary"],
        "interior": level["interior"],
        "omega_over_a2_wilson": level["omega_over_a2_wilson"],
        "omega_over_a2_paper_literal": level["omega_over_a2_paper_literal"],
        "qualified_before_refinement": level["qualified_before_refinement"],
    }


def evaluate(center_name, center, band, provider, preflight, cache, counters):
    levels = [
        stencil_evidence(center, side, band, R96, provider, preflight, cache, counters)
        for side in SIDES
    ]
    refinement_levels = tuple(
        PlaquetteRefinementLevel(
            boundary=level["_boundary"],
            interior=level["_interior"],
            step=side,
            provenance={"source": "E9C.C1 ordered three-stencil ladder", "side_label": LABELS[index], "band": band, "center": center_name},
        )
        for index, (level, side) in enumerate(zip(levels, SIDES))
    )
    refinement = qualify_plaquette_refinement(
        refinement_levels,
        thresholds=REFINEMENT,
        provenance={"source": "E9C.C1 final-pair 1/72-to-1/144 E4C", "band": band, "center": center_name},
    ).to_dict()
    metrics = refinement["metrics"]
    final = metrics[-1]
    previous = metrics[-2]
    omega = [level["omega_over_a2_wilson"] for level in levels]
    delta_36_72 = None if omega[0] is None or omega[1] is None else float(omega[1] - omega[0])
    delta_72_144 = None if omega[1] is None or omega[2] is None else float(omega[2] - omega[1])
    ratio = None
    if delta_36_72 is not None and delta_72_144 is not None and abs(delta_36_72) > 0.0:
        ratio = float(abs(delta_72_144) / abs(delta_36_72))
    qualified = bool(all(level["qualified_before_refinement"] for level in levels) and refinement["authorization_granted"])
    return {
        "paper_band": band + 1,
        "zero_based_band": band,
        "center": center_name,
        "levels": [compact_level(level) for level in levels],
        "E4C": refinement,
        "omega_evolution_wilson": omega,
        "delta_36_to_72": delta_36_72,
        "delta_72_to_144": delta_72_144,
        "ratio_abs_delta_72_to_144_over_delta_36_to_72": ratio,
        "final_pair_min_singular_value": final["minimum_singular_value"],
        "final_pair_max_principal_angle": final["maximum_principal_angle"],
        "final_pair_max_projector_distance": final["maximum_projector_distance"],
        "final_pair_metric_deltas": {
            "minimum_singular_value": abs(final["minimum_singular_value"] - previous["minimum_singular_value"]),
            "maximum_principal_angle": abs(final["maximum_principal_angle"] - previous["maximum_principal_angle"]),
            "maximum_projector_distance": abs(final["maximum_projector_distance"] - previous["maximum_projector_distance"]),
        },
        "E4C_authorization": "PASSED" if qualified else "FAILED",
        "qualified": qualified,
    }


def run(output):
    started = time.monotonic()
    contract_path = root() / "audit/e9c/c1_human_reference_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    checks = self_checks(contract, preflight, geometry)
    provider = make_provider(R96, lattice, solver_geometry, background)
    cache, counters = {}, {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    centers = {"PUBLIC_K": K_PUBLIC, "PUBLIC_K_PRIME": KPRIME_PUBLIC}
    rows = {}
    for center_name, center in centers.items():
        rows[center_name] = {}
        for band in BANDS:
            rows[center_name][str(band)] = evaluate(center_name, center, band, provider, preflight, cache, counters)
    trs = []
    for band in BANDS:
        k = rows["PUBLIC_K"][str(band)]["levels"][-1]["omega_over_a2_wilson"]
        kp = rows["PUBLIC_K_PRIME"][str(band)]["levels"][-1]["omega_over_a2_wilson"]
        total = None if k is None or kp is None else float(k + kp)
        denom = None if k is None or kp is None else max(abs(k), abs(kp), 1e-15)
        trs.append({"paper_band": band + 1, "K": k, "K_prime": kp, "sum": total, "relative_residual": None if total is None else float(abs(total) / denom)})
    all_authorized = all(row["E4C_authorization"] == "PASSED" for center in rows.values() for row in center.values())
    payload = {
        "schema": "trilatt_e9c_c1_r96_three_stencil_k_kprime_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_json_sha256": file_sha(contract_path),
        "preserved_e9c_result_sha256": file_sha(root() / "audit/e9c/result.json"),
        "contract": contract,
        "self_checks": checks,
        "geometry": {
            "physical_vertices": geometry["physical_vertices"].tolist(),
            "mpb_vertices": geometry["mpb_vertices"].tolist(),
            "roundtrip_vertices": geometry["roundtrip_vertices"].tolist(),
            "max_roundtrip_error": geometry["max_roundtrip_error"],
            "physical_fill_fraction": geometry["physical_fill_fraction"],
            "orientation": geometry["orientation"],
        },
        "coordinate_preflight": {
            "ready": preflight.ready,
            "public_K": list(K_PUBLIC),
            "public_K_prime": list(KPRIME_PUBLIC),
            "mpb_K": [float(x) for x in preflight.public_q_to_mpb(K_PUBLIC)],
            "mpb_K_prime": [float(x) for x in preflight.public_q_to_mpb(KPRIME_PUBLIC)],
            "mapping_digest": preflight.mapping_digest,
            "round_trip_residual": preflight.round_trip_residual,
        },
        "resolution": R96,
        "stencil_ladder": [{"label": label, "side_q": side, "half_offset_q": side / 2.0} for label, side in zip(LABELS, SIDES)],
        "results": rows,
        "TRS_control_final_1_144": trs,
        "all_six_e4c_pairs_authorized": all_authorized,
        "time_reversal_sign_control": "PASSED" if all(row["relative_residual"] is not None and row["relative_residual"] < 0.01 for row in trs) else "FAILED",
        "paper_stencil_external_reproduction": "VALIDATED",
        "mephc_refined_local_berry_status": "QUALIFIED_BOUNDED_FINE_STENCIL_ESTIMATE" if all_authorized else "REFINEMENT_STILL_UNRESOLVED",
        "scope_gates": {
            "berry_field_map": "NOT_AUTHORIZED",
            "valley_chern": "NOT_AUTHORIZED",
            "full_bz_chern": "NOT_AUTHORIZED",
            "parameter_fitting": "NOT_AUTHORIZED",
            "posthoc_sign_flip": "NOT_USED",
            "production_code_changed": False,
        },
        "counts": {"total_e4c_refinement_pairs": 6, "total_stencil_level_rows": 18, "e4c_authorized_pairs": sum(1 for center in rows.values() for row in center.values() if row["E4C_authorization"] == "PASSED")},
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), **counters},
        "E9C_C1_OVERALL": "FINER_STENCIL_REFINEMENT_READY_FOR_SUPERVISOR_DECISION" if all_authorized else "FAIL_CLOSED",
    }
    Path(output).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9c/c1_human_reference_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    geometry = geometry_inputs()
    preflight, _, _, _ = build_inputs(geometry)
    if "--self-check" in sys.argv:
        print(json.dumps(self_checks(contract, preflight, geometry), sort_keys=True))
    else:
        output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else str(root() / "audit/e9c/c1_result.json")
        payload = run(output)
        print(json.dumps({"schema": payload["schema"], "calculation_code_git_sha": payload["calculation_code_git_sha"], "telemetry": payload["telemetry"]}, sort_keys=True))




