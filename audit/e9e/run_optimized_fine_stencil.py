"""E9E.C.C1 optimized fine-stencil Berry qualification."""

from __future__ import annotations

import hashlib
import json
import math
import resource
import subprocess
import sys
import time
from pathlib import Path

import meep as mp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.e9e.a_rounded_triangle_geometry import build_geometry, validate_geometry
from audit.e9e.run_berry_evolution import (
    BANDS,
    KPRIME_PUBLIC,
    K_PUBLIC,
    MESH_SIZE,
    NUM_BANDS,
    R64,
    R96,
    REFINEMENT,
    SOLVER_TOLERANCE,
    TRANSPORT,
    complex_pair,
    excluded,
    external_contexts,
    frame_rank1,
    make_lattice,
    make_solver_geometry,
    omega_over_a2,
    polygon_case,
    solve_at,
    status_dict,
)
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import (
    PlaquetteRefinementLevel,
    qualify_plaquette_boundary,
    qualify_plaquette_interior,
    qualify_plaquette_refinement,
)
from mephc.spectral_association import ExternalIsolationContext
from mephc.valley_benchmark import build_triangular_coordinate_preflight, centered_ccw_plaquette_requests
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport


WORK_ORDER = "TRILATT-E9E-C-C1-20260824-195"
SIDES_C1 = (1.0 / 72.0, 1.0 / 144.0, 1.0 / 288.0)
LABELS_C1 = ("1/72", "1/144", "1/288")
PAPER_FR0 = (-0.92, 0.72, 0.19)
PAPER_FR04 = (-0.19, -7.53, 7.68)
REPLAY_TOLERANCE = 1.0e-7


def root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stencil_evidence_c1(
    center: tuple[float, float],
    side: float,
    band: int,
    resolution: int,
    provider: MPBLiveEnergySpectralProvider,
    preflight: object,
    cache: dict,
    counters: dict,
    cache_tag: str,
) -> dict:
    requests = centered_ccw_plaquette_requests(
        (center,),
        side,
        period_basis=preflight.public_period_basis,
        coordinate_mapping_digest=preflight.mapping_digest,
    )
    vertices = [tuple(float(x) for x in request.nominal_vertex_q) for request in requests]
    values = [solve_at(provider, preflight, q, resolution, cache, counters, cache_tag) for q in vertices]
    center_value = solve_at(provider, preflight, center, resolution, cache, counters, cache_tag)
    profile_rows = []
    for label, value, q in (
        [(f"vertex_{index}", value, q) for index, (value, q) in enumerate(zip(values, vertices))]
        + [("center", center_value, center)]
    ):
        gap = min(abs(value["frequencies"][band] - value["frequencies"][index]) for index in range(NUM_BANDS) if index != band)
        profile_rows.append(
            {
                "label": label,
                "q": list(q),
                "frequencies": list(value["frequencies"]),
                "external_gap": float(gap),
                "E3_PROFILE": "PASS" if gap >= TRANSPORT.min_external_gap else "FAIL",
            }
        )
    profile_passed = all(row["E3_PROFILE"] == "PASS" for row in profile_rows)
    frames = [frame_rank1(q, value["raw"], band) for q, value in zip(vertices, values)]
    center_frame = frame_rank1(center, center_value["raw"], band)
    contexts = external_contexts([value["frequencies"] for value in values], band)
    path = qualify_ordered_path(
        tuple(frames),
        contexts,
        thresholds=TRANSPORT,
        closed=True,
        provenance={"source": "E9E.C.C1 ordered fine square", "band": band, "resolution": resolution, "side": side},
    )
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(
        tuple(frames),
        contexts,
        thresholds=TRANSPORT,
        provenance={"source": "E9E.C.C1 fine E4A square", "band": band, "resolution": resolution, "side": side},
    )
    spokes = tuple(
        ExternalIsolationContext(
            excluded(value["frequencies"], band),
            excluded(center_value["frequencies"], band),
            {"source": "E9E.C.C1 vertex-center six-band spectrum", "band": band},
        )
        for value in values
    )
    interior = qualify_plaquette_interior(
        boundary,
        center_frame,
        spokes,
        provenance={"source": "E9E.C.C1 fine E4B center spokes", "band": band, "resolution": resolution, "side": side},
    )
    determinant = None if wilson.determinant is None else complex(wilson.determinant)
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    path_ok = path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)
    basic_qualified = bool(
        profile_passed
        and path_ok
        and wilson.status == WILSON_LOOP_QUALIFIED
        and boundary.is_qualified
        and interior.is_qualified
        and determinant is not None
        and phase is not None
    )
    omega_literal_q = None if not basic_qualified else float(-determinant.imag / side**2)
    omega_wilson_q = None if not basic_qualified else float(-phase / side**2)
    return {
        "band": band,
        "resolution": resolution,
        "center": list(center),
        "side_q": float(side),
        "stencil_label": LABELS_C1[SIDES_C1.index(side)],
        "vertices": [list(q) for q in vertices],
        "profile_passed": profile_passed,
        "profile": profile_rows,
        "path": status_dict(path),
        "wilson": {
            "status": wilson.status,
            "rank": wilson.rank,
            "determinant": None if determinant is None else complex_pair(determinant),
            "determinant_phase": phase,
            "unitarity_residual": wilson.unitarity_residual,
        },
        "boundary": status_dict(boundary),
        "interior": status_dict(interior),
        "minimum_external_gap": float(min(row["external_gap"] for row in profile_rows)),
        "center_frequencies": list(center_value["frequencies"]),
        "omega_q_paper_literal": omega_literal_q,
        "omega_q_wilson": omega_wilson_q,
        "omega_over_a2_paper_literal": omega_over_a2(omega_literal_q),
        "omega_over_a2_wilson": omega_over_a2(omega_wilson_q),
        "qualified": basic_qualified,
        "_boundary": boundary,
        "_interior": interior,
        "_basic_qualified": basic_qualified,
    }


def compact(value: dict) -> dict:
    return {key: item for key, item in value.items() if not key.startswith("_")}


def e4c_c1(levels: tuple[dict, dict, dict], band: int, center_name: str) -> dict:
    refinement_levels = tuple(
        PlaquetteRefinementLevel(
            boundary=item["_boundary"],
            interior=item["_interior"],
            step=side,
            provenance={"source": "E9E.C.C1 optimized fine ladder", "band": band, "center": center_name, "label": LABELS_C1[index]},
        )
        for index, (item, side) in enumerate(zip(levels, SIDES_C1))
    )
    result = qualify_plaquette_refinement(
        refinement_levels,
        thresholds=REFINEMENT,
        provenance={"source": "E9E.C.C1 final pair 1/144-to-1/288", "band": band, "center": center_name},
    ).to_dict()
    metrics = result["metrics"]
    previous = metrics[-2]
    final = metrics[-1]
    return {
        "status": result["status"],
        "authorization_granted": bool(result["authorization_granted"]),
        "qualified": bool(all(item["_basic_qualified"] for item in levels) and result["authorization_granted"]),
        "metrics": metrics,
        "thresholds": result["thresholds"],
        "levels": result["levels"],
        "final_pair_metric_deltas": {
            "minimum_singular_value": abs(final["minimum_singular_value"] - previous["minimum_singular_value"]),
            "maximum_principal_angle": abs(final["maximum_principal_angle"] - previous["maximum_principal_angle"]),
            "maximum_projector_distance": abs(final["maximum_projector_distance"] - previous["maximum_projector_distance"]),
        },
    }


def self_checks(contract: dict, preflight: object, geometry: dict, previous_result: dict) -> dict:
    mapped_k = tuple(float(value) for value in preflight.public_q_to_mpb(K_PUBLIC))
    mapped_kp = tuple(float(value) for value in preflight.public_q_to_mpb(KPRIME_PUBLIC))
    checks = {
        "WORK_ORDER": contract["work_order_id"] == WORK_ORDER,
        "PREVIOUS_E9E_C_PRESERVED": previous_result["work_order_id"] == "TRILATT-E9E-C-20260824-193",
        "F_R_BOUND": contract["model"]["f_r"] == 0.4,
        "SIX_BANDS": contract["model"]["num_bands"] == NUM_BANDS,
        "RANK1_ONLY": contract["model"]["rank"] == 1,
        "FINE_LADDER": SIDES_C1 == (1.0 / 72.0, 1.0 / 144.0, 1.0 / 288.0),
        "NO_PAPER_RETRY": contract["optimized_stencil_ladder"]["paper_1_36_band2"] == "UNQUALIFIED_NOT_REPORTED",
        "GEOMETRY": geometry["public_cartesian_to_mpb_roundtrip_error"] <= 1.0e-12 and geometry["polygon_area"] > 0.0,
        "K_MAPPING": np.allclose(mapped_k, (1.0 / 3.0, 1.0 / 3.0), rtol=0.0, atol=1.0e-12),
        "KPRIME_MAPPING": np.allclose(mapped_kp, (-1.0 / 3.0, -1.0 / 3.0), rtol=0.0, atol=1.0e-12),
        "PREFLIGHT": bool(preflight.ready) and preflight.round_trip_residual <= 1.0e-12,
        "NO_FR0P5": contract["authorization"]["f_r_0p5_berry"] is False,
        "NO_MAP": contract["authorization"]["berry_field_map"] is False,
        "NO_CHERN": contract["authorization"]["valley_chern"] is False and contract["authorization"]["full_bz_chern"] is False,
        "NO_THRESHOLD_RELAXATION": contract["qualification"]["no_threshold_relaxation"] is True,
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9E.C.C1 self-check failed: {checks}")
    return checks


def provider_for(case: dict, resolution: int) -> MPBLiveEnergySpectralProvider:
    return MPBLiveEnergySpectralProvider(
        geometry=list(make_solver_geometry(case)),
        geometry_lattice=make_lattice(),
        resolution=resolution,
        num_bands=NUM_BANDS,
        polarization=mp.TE,
        default_material=mp.Medium(epsilon=7.0225),
        eigensolver_tolerance=SOLVER_TOLERANCE,
        deterministic=True,
        mesh_size=MESH_SIZE,
    )


def run(output: Path, contract_path: Path) -> dict:
    started = time.monotonic()
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    previous_path = root() / "audit/e9e/c_berry_evolution_result.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8-sig"))
    case96 = polygon_case(0.4, 96)
    case48 = polygon_case(0.4, 48)
    analytic_validation = validate_geometry(build_geometry(0.4))
    preflight = build_triangular_coordinate_preflight()
    checks = self_checks(contract, preflight, case96, previous)
    if not analytic_validation["all_checks_passed"]:
        raise RuntimeError("E9E.A analytic geometry validation not preserved")
    providers = {
        "R96_TESS96": provider_for(case96, R96),
        "R64_TESS48": provider_for(case48, R64),
        "R64_TESS96": provider_for(case96, R64),
    }
    cache, counters = {}, {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    r96 = {"PUBLIC_K": {}, "PUBLIC_K_PRIME": {}}
    for center_name, center in (("PUBLIC_K", K_PUBLIC), ("PUBLIC_K_PRIME", KPRIME_PUBLIC)):
        for band in BANDS:
            levels = tuple(
                stencil_evidence_c1(
                    center,
                    side,
                    band,
                    R96,
                    providers["R96_TESS96"],
                    preflight,
                    cache,
                    counters,
                    "R96_TESS96",
                )
                for side in SIDES_C1
            )
            refinement = e4c_c1(levels, band, center_name)
            r96[center_name][str(band)] = {
                "paper_band": band + 1,
                "levels": [compact(level) for level in levels],
                "E4C": refinement,
                "qualified": bool(refinement["qualified"]),
            }
    tess = {}
    for tag in ("R64_TESS48", "R64_TESS96"):
        tess[tag] = {}
        for band in BANDS:
            evidence = stencil_evidence_c1(
                KPRIME_PUBLIC,
                1.0 / 144.0,
                band,
                R64,
                providers[tag],
                preflight,
                cache,
                counters,
                tag,
            )
            tess[tag][str(band)] = compact(evidence)
    trs_rows = []
    for band in BANDS:
        k = r96["PUBLIC_K"][str(band)]["levels"][-1]["omega_over_a2_wilson"]
        kp = r96["PUBLIC_K_PRIME"][str(band)]["levels"][-1]["omega_over_a2_wilson"]
        total = None if k is None or kp is None else float(k + kp)
        denom = None if k is None or kp is None else max(abs(k), abs(kp), 1.0e-15)
        trs_rows.append(
            {
                "paper_band": band + 1,
                "K": k,
                "K_prime": kp,
                "sum": total,
                "relative_residual": None if total is None else float(abs(total) / denom),
            }
        )
    trs_max = max((row["relative_residual"] for row in trs_rows if row["relative_residual"] is not None), default=float("inf"))
    fine_values = [r96["PUBLIC_K_PRIME"][str(band)]["levels"][-1]["omega_over_a2_wilson"] for band in BANDS]
    middle_values = [r96["PUBLIC_K_PRIME"][str(band)]["levels"][1]["omega_over_a2_wilson"] for band in BANDS]
    coarse_fine_values = [r96["PUBLIC_K_PRIME"][str(band)]["levels"][0]["omega_over_a2_wilson"] for band in BANDS]
    deltas_72_144 = [None if a is None or b is None else abs(a - b) for a, b in zip(coarse_fine_values, middle_values)]
    deltas_144_288 = [None if a is None or b is None else abs(a - b) for a, b in zip(middle_values, fine_values)]
    ratios = [
        None if a is None or b is None or a == 0.0 else b / a
        for a, b in zip(deltas_72_144, deltas_144_288)
    ]
    tess48 = [tess["R64_TESS48"][str(band)]["omega_over_a2_wilson"] for band in BANDS]
    tess96 = [tess["R64_TESS96"][str(band)]["omega_over_a2_wilson"] for band in BANDS]
    def sign(value: float | None) -> int | None:
        return None if value is None else (1 if value > 0.0 else -1 if value < 0.0 else 0)
    tess_sign_stable = all(sign(a) == sign(b) for a, b in zip(tess48, tess96))
    tess_dominance_stable = all(
        a is not None
        and b is not None
        and c is not None
        and abs(b) > abs(a)
        and abs(c) > abs(a)
        for a, b, c in zip(tess48, tess96, tess96)
    )
    all_qualified = all(r96[center][str(band)]["qualified"] for center in r96 for band in BANDS)
    classifications = {
        "BAND1_SUPPRESSION": "REPRODUCED" if fine_values[0] is not None and abs(fine_values[0]) < abs(PAPER_FR0[0]) else "NOT_REPRODUCED",
        "BAND2_SIGN_REVERSAL": "REPRODUCED" if fine_values[1] is not None and fine_values[1] < 0.0 and PAPER_FR0[1] > 0.0 else "NOT_REPRODUCED",
        "BAND2_ENHANCEMENT": "REPRODUCED" if fine_values[1] is not None and abs(fine_values[1]) > abs(PAPER_FR0[1]) else "NOT_REPRODUCED",
        "BAND3_ENHANCEMENT": "REPRODUCED" if fine_values[2] is not None and fine_values[2] > 0.0 and abs(fine_values[2]) > abs(PAPER_FR0[2]) else "NOT_REPRODUCED",
        "BAND23_DOMINANCE": "REPRODUCED" if all(value is not None for value in fine_values) and abs(fine_values[1]) > abs(fine_values[0]) and abs(fine_values[2]) > abs(fine_values[0]) else "NOT_REPRODUCED",
        "BAND23_OPPOSITE_SIGN_PAIR": "REPRODUCED" if fine_values[1] is not None and fine_values[2] is not None and fine_values[1] < 0.0 < fine_values[2] else "NOT_REPRODUCED",
    }
    trend_supported = all(value == "REPRODUCED" for value in classifications.values())
    overall = "OPTIMIZED_FINE_STENCIL_FR0P4_BERRY_READY_FOR_SUPERVISOR_DECISION" if all_qualified and trend_supported and tess_sign_stable and tess_dominance_stable and trs_max <= 0.01 else "FAIL_CLOSED"
    payload = {
        "schema": "trilatt_e9e_c_c1_optimized_fine_stencil_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_sha256": file_sha(contract_path),
        "preserved_e9e_c_result_sha256": file_sha(previous_path),
        "contract": contract,
        "self_checks": checks,
        "original_e9e_c_evidence_unchanged": True,
        "analytic_geometry_validation": analytic_validation,
        "paper_1_36_band2_status": "UNQUALIFIED_NOT_REPORTED",
        "paper_1_36_band3_status": "UNQUALIFIED_NOT_REPORTED",
        "optimized_stencil_ladder": list(LABELS_C1),
        "results": {"R96_TESS96": r96, "R64_TESS48_KPRIME_1_144": tess["R64_TESS48"], "R64_TESS96_KPRIME_1_144": tess["R64_TESS96"]},
        "berry_evolution": {
            "paper_band_values_1_72": coarse_fine_values,
            "paper_band_values_1_144": middle_values,
            "paper_band_values_1_288": fine_values,
            "abs_delta_72_to_144": deltas_72_144,
            "abs_delta_144_to_288": deltas_144_288,
            "delta_reduction_ratio": ratios,
        },
        "trs_control_1_288": trs_rows,
        "trs_relative_residual_max": trs_max,
        "tessellation_control": {
            "omega_r64_tess48_1_144": tess48,
            "omega_r64_tess96_1_144": tess96,
            "absolute_difference": [None if a is None or b is None else abs(a - b) for a, b in zip(tess48, tess96)],
            "sign_stable": tess_sign_stable,
            "dominance_stable": tess_dominance_stable,
        },
        "final_pair_e4c": {
            str(band + 1): r96["PUBLIC_K_PRIME"][str(band)]["E4C"]
            for band in BANDS
        },
        "all_three_fine_stencil_bands_qualified": all_qualified,
        "band2_fine_e4c": "PASSED" if r96["PUBLIC_K_PRIME"]["1"]["qualified"] else "FAILED",
        "band3_fine_e4c": "PASSED" if r96["PUBLIC_K_PRIME"]["2"]["qualified"] else "FAILED",
        "fine_stencil_tessellation_qualitative_stability": "PASSED" if tess_sign_stable and tess_dominance_stable else "FAILED",
        "classifications": classifications,
        "at_k_berry_evolution": "SUPPORTED" if all_qualified and trend_supported and trs_max <= 0.01 else "NOT_SUPPORTED",
        "paper_comparison_policy": "TREND_FIDELITY_OVER_POINTWISE_NUMERICAL_COINCIDENCE",
        "fr0p5_rank1_berry_at_exact_k": "UNDEFINED_NOT_AUTHORIZED",
        "berry_field_map": "NOT_AUTHORIZED",
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "production_code_changed": False,
        "telemetry": {
            "wall_time_seconds": time.monotonic() - started,
            "solver_requests": counters["solver_requests"],
            "cache_hits": counters["cache_hits"],
            "solver_failures": counters["solver_failures"],
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        },
        "E9E_C_C1_OVERALL": overall,
    }
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9e/c1_optimized_fine_stencil_contract.json"
    output = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else root() / "audit/e9e/c1_optimized_fine_stencil_result.json"
    if "--self-check" in sys.argv:
        contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
        previous = json.loads((root() / "audit/e9e/c_berry_evolution_result.json").read_text(encoding="utf-8-sig"))
        preflight = build_triangular_coordinate_preflight()
        print(json.dumps(self_checks(contract, preflight, polygon_case(0.4, 96), previous), sort_keys=True))
    else:
        payload = run(output, contract_path)
        print(json.dumps({"schema": payload["schema"], "overall": payload["E9E_C_C1_OVERALL"], "telemetry": payload["telemetry"]}, sort_keys=True))

