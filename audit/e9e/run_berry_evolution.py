"""E9E.C bounded f_r=0.4 K/K-prime rank-1 Berry evolution benchmark."""

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

from audit.e9e.a_rounded_triangle_geometry import (
    BASE_AREA,
    REAL_BASIS,
    build_geometry,
    cartesian_to_mpb,
    validate_geometry,
)
from audit.e9e.run_spectral_embedding import make_lattice, make_solver_geometry, polygon_case
from mephc.eigenspace import EigenSubspace
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import (
    PlaquetteRefinementLevel,
    PlaquetteRefinementThresholds,
    qualify_plaquette_boundary,
    qualify_plaquette_interior,
    qualify_plaquette_refinement,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.valley_benchmark import build_triangular_coordinate_preflight, centered_ccw_plaquette_requests
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport


WORK_ORDER = "TRILATT-E9E-C-20260824-193"
R64, R96 = 64, 96
NUM_BANDS = 6
BANDS = (0, 1, 2)
K_PUBLIC = (2.0 / 3.0, 0.0)
KPRIME_PUBLIC = (-2.0 / 3.0, 0.0)
SIDE_1_36 = 1.0 / 36.0
SIDE_1_72 = 1.0 / 72.0
SIDE_1_144 = 1.0 / 144.0
SIDES = (SIDE_1_36, SIDE_1_72, SIDE_1_144)
LABELS = ("1/36", "1/72", "1/144")
PAPER_FR0 = (-0.92, 0.72, 0.19)
PAPER_FR04 = (-0.19, -7.53, 7.68)
SOLVER_TOLERANCE = 1.0e-7
MESH_SIZE = 3
TRANSPORT = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.005)
REFINEMENT = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)
REPLAY_TOLERANCE = 1.0e-7


def root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def complex_pair(value: complex) -> dict:
    return {"real": float(np.real(value)), "imag": float(np.imag(value))}


def omega_over_a2(value: float | None) -> float | None:
    return None if value is None else float(value / (2.0 * math.pi) ** 2)


def excluded(frequencies: tuple[float, ...], band: int) -> tuple[float, ...]:
    return tuple(float(value) for index, value in enumerate(frequencies) if index != band)


def external_contexts(vertex_frequencies: list[tuple[float, ...]], band: int) -> tuple[ExternalIsolationContext, ...]:
    return tuple(
        ExternalIsolationContext(
            excluded(vertex_frequencies[index], band),
            excluded(vertex_frequencies[(index + 1) % 4], band),
            {"source": "E9E.C complete excluded six-band vertex spectrum", "band": band},
        )
        for index in range(4)
    )


def frame_rank1(public_q: tuple[float, float], raw: object, band: int) -> EigenSubspace:
    vector = np.asarray(raw.normalized_vectors[band], dtype=np.complex128)
    norm_error = abs(float(np.vdot(vector, vector).real) - 1.0)
    if vector.ndim != 1 or not np.all(np.isfinite(vector)) or norm_error > 1.0e-8:
        raise RuntimeError(f"rank-1 normalization failure at {public_q}, band {band}")
    return EigenSubspace(
        k_point=tuple(float(x) for x in public_q),
        frame=vector.reshape((-1, 1)),
        eigenvalues=(float(raw.frequencies[band]),),
        solver_indices=(band,),
        metadata={
            "source": "E9E.C normalized MPB E+H state",
            "representation": "mpb_energy_eh_v1",
            "selected_rank": 1,
            "band": band,
            "lowdin_mixing": False,
            "posthoc_sign_flip": False,
        },
    )


def solve_at(
    provider: MPBLiveEnergySpectralProvider,
    preflight: object,
    public_q: tuple[float, float],
    resolution: int,
    cache: dict,
    counters: dict,
    cache_tag: str,
) -> dict:
    q = tuple(float(x) for x in public_q)
    key = (cache_tag, int(resolution), q)
    if key in cache:
        counters["cache_hits"] += 1
        return cache[key]
    counters["solver_requests"] += 1
    raw = provider.solve(q)
    frequencies = tuple(float(value) for value in raw.frequencies)
    vectors = tuple(np.asarray(value, dtype=np.complex128) for value in raw.normalized_vectors)
    if len(frequencies) != NUM_BANDS or len(vectors) != NUM_BANDS:
        counters["solver_failures"] += 1
        raise RuntimeError(f"incomplete six-band snapshot at {q}")
    if not all(math.isfinite(value) for value in frequencies) or any(not np.all(np.isfinite(value)) for value in vectors):
        counters["solver_failures"] += 1
        raise RuntimeError(f"non-finite snapshot at {q}")
    result = {
        "raw": raw,
        "frequencies": frequencies,
        "record": {
            "public_q": list(q),
            "mpb_fractional_q": [float(value) for value in preflight.public_q_to_mpb(q)],
            "frequencies": list(frequencies),
            "provider_representation": raw.provenance.get("representation"),
        },
    }
    cache[key] = result
    return result


def status_dict(value: object) -> dict:
    return {"status": value.status, "is_qualified": bool(value.is_qualified)}


def stencil_evidence(
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
                "E3_PROFILE": "PASS" if gap >= TRANSPORT.minimum_external_gap else "FAIL",
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
        provenance={"source": "E9E.C rank-1 E3 ordered square", "band": band, "resolution": resolution, "side": side},
    )
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(
        tuple(frames),
        contexts,
        thresholds=TRANSPORT,
        provenance={"source": "E9E.C rank-1 E4A square", "band": band, "resolution": resolution, "side": side},
    )
    spokes = tuple(
        ExternalIsolationContext(
            excluded(value["frequencies"], band),
            excluded(center_value["frequencies"], band),
            {"source": "E9E.C vertex-center excluded six-band spectrum", "band": band},
        )
        for value in values
    )
    interior = qualify_plaquette_interior(
        boundary,
        center_frame,
        spokes,
        provenance={"source": "E9E.C E4B center spokes", "band": band, "resolution": resolution, "side": side},
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
        "stencil_label": LABELS[SIDES.index(side)],
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
        "qualified_before_refinement": basic_qualified,
        "_boundary": boundary,
        "_interior": interior,
        "_basic_qualified": basic_qualified,
    }


def compact_evidence(value: dict) -> dict:
    return {key: item for key, item in value.items() if not key.startswith("_")}


def e4c(primary: dict, reference: dict, fine: dict, band: int, center_name: str) -> dict:
    levels = tuple(
        PlaquetteRefinementLevel(
            boundary=item["_boundary"],
            interior=item["_interior"],
            step=side,
            provenance={"source": "E9E.C ordered three-stencil ladder", "band": band, "center": center_name, "label": LABELS[index]},
        )
        for index, (item, side) in enumerate(zip((primary, reference, fine), SIDES))
    )
    result = qualify_plaquette_refinement(
        levels,
        thresholds=REFINEMENT,
        provenance={"source": "E9E.C final pair 1/72-to-1/144 E4C", "band": band, "center": center_name},
    ).to_dict()
    metrics = result["metrics"]
    final = metrics[-1]
    previous = metrics[-2]
    qualified = bool(
        all(item["_basic_qualified"] for item in (primary, reference, fine))
        and result["authorization_granted"]
    )
    return {
        "status": result["status"],
        "authorization_granted": bool(result["authorization_granted"]),
        "qualified": qualified,
        "metrics": metrics,
        "thresholds": result["thresholds"],
        "levels": result["levels"],
        "final_pair_metric_deltas": {
            "minimum_singular_value": abs(final["minimum_singular_value"] - previous["minimum_singular_value"]),
            "maximum_principal_angle": abs(final["maximum_principal_angle"] - previous["maximum_principal_angle"]),
            "maximum_projector_distance": abs(final["maximum_projector_distance"] - previous["maximum_projector_distance"]),
        },
    }


def self_checks(contract: dict, preflight: object, geometry: dict, e9e_b_result: dict) -> dict:
    mapped_k = tuple(float(value) for value in preflight.public_q_to_mpb(K_PUBLIC))
    mapped_kp = tuple(float(value) for value in preflight.public_q_to_mpb(KPRIME_PUBLIC))
    checks = {
        "WORK_ORDER": contract["work_order_id"] == WORK_ORDER,
        "F_R_BOUND": contract["model"]["f_r"] == 0.4,
        "SIX_BANDS": contract["model"]["num_bands"] == NUM_BANDS,
        "RANK1_ONLY": contract["model"]["rank"] == 1 and contract["model"]["composite_subspace_mixing"] is False,
        "E9E_B_PRESERVED": e9e_b_result["work_order_id"] == "TRILATT-E9E-B-20260824-189",
        "GEOMETRY_VALIDATED": geometry["public_cartesian_to_mpb_roundtrip_error"] <= 1.0e-12 and geometry["polygon_area"] > 0.0,
        "K_MAPPING": np.allclose(mapped_k, (1.0 / 3.0, 1.0 / 3.0), rtol=0.0, atol=1.0e-12),
        "KPRIME_MAPPING": np.allclose(mapped_kp, (-1.0 / 3.0, -1.0 / 3.0), rtol=0.0, atol=1.0e-12),
        "PREFLIGHT": bool(preflight.ready) and preflight.round_trip_residual <= 1.0e-12,
        "PAPER_STENCIL": math.isclose(SIDE_1_36, 1.0 / 36.0) and math.isclose(SIDE_1_36 / 2.0, SIDE_1_72),
        "THREE_STENCILS": SIDES == (1.0 / 36.0, 1.0 / 72.0, 1.0 / 144.0),
        "NO_FR0P5_BERRY": contract["authorization"]["f_r_0p5_berry"] is False,
        "NO_MAP": contract["authorization"]["berry_field_map"] is False,
        "NO_CHERN": contract["authorization"]["valley_chern"] is False and contract["authorization"]["full_bz_chern"] is False,
        "NO_POSTHOC_SIGN_FLIP": contract["paper_comparison"]["no_posthoc_sign_flip"] is True,
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9E.C self-check failed: {checks}")
    return checks


def run(output: Path, contract_path: Path) -> dict:
    started = time.monotonic()
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    e9e_b_result_path = root() / "audit/e9e/b_spectral_embedding_result.json"
    e9e_b_result = json.loads(e9e_b_result_path.read_text(encoding="utf-8-sig"))
    geometry_case = polygon_case(0.4, 96)
    analytic_geometry = build_geometry(0.4)
    analytic_validation = validate_geometry(analytic_geometry)
    preflight = build_triangular_coordinate_preflight()
    checks = self_checks(contract, preflight, geometry_case, e9e_b_result)
    if not analytic_validation["all_checks_passed"]:
        raise RuntimeError("E9E.A analytic geometry validation was not preserved")
    providers = {
        "R96_TESS96": (
            MPBLiveEnergySpectralProvider(
                geometry=list(make_solver_geometry(geometry_case)),
                geometry_lattice=make_lattice(),
                resolution=R96,
                num_bands=NUM_BANDS,
                polarization=mp.TE,
                default_material=mp.Medium(epsilon=7.0225),
                eigensolver_tolerance=SOLVER_TOLERANCE,
                deterministic=True,
                mesh_size=MESH_SIZE,
            ),
            R96,
            "R96_TESS96",
        ),
        "R64_TESS48": (
            MPBLiveEnergySpectralProvider(
                geometry=list(make_solver_geometry(polygon_case(0.4, 48))),
                geometry_lattice=make_lattice(),
                resolution=R64,
                num_bands=NUM_BANDS,
                polarization=mp.TE,
                default_material=mp.Medium(epsilon=7.0225),
                eigensolver_tolerance=SOLVER_TOLERANCE,
                deterministic=True,
                mesh_size=MESH_SIZE,
            ),
            R64,
            "R64_TESS48",
        ),
        "R64_TESS96": (
            MPBLiveEnergySpectralProvider(
                geometry=list(make_solver_geometry(geometry_case)),
                geometry_lattice=make_lattice(),
                resolution=R64,
                num_bands=NUM_BANDS,
                polarization=mp.TE,
                default_material=mp.Medium(epsilon=7.0225),
                eigensolver_tolerance=SOLVER_TOLERANCE,
                deterministic=True,
                mesh_size=MESH_SIZE,
            ),
            R64,
            "R64_TESS96",
        ),
    }
    cache, counters = {}, {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    r96 = {"PUBLIC_K": {}, "PUBLIC_K_PRIME": {}}
    for center_name, center in (("PUBLIC_K", K_PUBLIC), ("PUBLIC_K_PRIME", KPRIME_PUBLIC)):
        for band in BANDS:
            evidences = [
                stencil_evidence(center, side, band, R96, providers["R96_TESS96"][0], preflight, cache, counters, "R96_TESS96")
                for side in SIDES
            ]
            r96[center_name][str(band)] = {
                "paper_band": band + 1,
                "primary": compact_evidence(evidences[0]),
                "reference": compact_evidence(evidences[1]),
                "fine": compact_evidence(evidences[2]),
                "E4C": e4c(*evidences, band, center_name),
                "qualified": bool(e4c(*evidences, band, center_name)["qualified"]),
            }
    tess_control = {}
    for tag in ("R64_TESS48", "R64_TESS96"):
        tess_control[tag] = {}
        for band in BANDS:
            evidence = stencil_evidence(K_PUBLIC, SIDE_1_36, band, R64, providers[tag][0], preflight, cache, counters, tag)
            tess_control[tag][str(band)] = compact_evidence(evidence)
    trs = {}
    for stencil_key, label in (("primary", "1/36"), ("fine", "1/144")):
        rows = []
        for band in BANDS:
            k = r96["PUBLIC_K"][str(band)][stencil_key]["omega_over_a2_wilson"]
            kp = r96["PUBLIC_K_PRIME"][str(band)][stencil_key]["omega_over_a2_wilson"]
            total = None if k is None or kp is None else float(k + kp)
            denom = None if k is None or kp is None else max(abs(k), abs(kp), 1.0e-15)
            rows.append(
                {
                    "paper_band": band + 1,
                    "K": k,
                    "K_prime": kp,
                    "sum": total,
                    "relative_residual": None if total is None else float(abs(total) / denom),
                }
            )
        trs[label] = rows
    replay_actual = r96["PUBLIC_K"]["0"]["primary"]["center_frequencies"]
    replay_expected = contract["spectral_replay"]["expected_first_six"]
    replay = all(abs(float(a) - float(b)) <= contract["spectral_replay"]["absolute_tolerance"] for a, b in zip(replay_actual, replay_expected))
    paper_values = [
        r96["PUBLIC_K_PRIME"][str(band)]["primary"]["omega_over_a2_wilson"]
        for band in BANDS
    ]
    fine_values = [
        r96["PUBLIC_K_PRIME"][str(band)]["fine"]["omega_over_a2_wilson"]
        for band in BANDS
    ]
    tess48_values = [tess_control["R64_TESS48"][str(band)]["omega_over_a2_wilson"] for band in BANDS]
    tess96_values = [tess_control["R64_TESS96"][str(band)]["omega_over_a2_wilson"] for band in BANDS]
    tess_sign_stable = all(
        (a == 0.0 and b == 0.0) or (a is not None and b is not None and math.copysign(1.0, a) == math.copysign(1.0, b))
        for a, b in zip(tess48_values, tess96_values)
    )
    all_qualified = all(r96[center][str(band)]["qualified"] for center in r96 for band in BANDS)
    trs_max = max(
        (row["relative_residual"] for rows in trs.values() for row in rows if row["relative_residual"] is not None),
        default=float("inf"),
    )
    classifications = {
        "BAND1_SUPPRESSION": "REPRODUCED" if paper_values[0] is not None and abs(paper_values[0]) < abs(PAPER_FR0[0]) else "NOT_REPRODUCED",
        "BAND2_SIGN_REVERSAL": "REPRODUCED" if paper_values[1] is not None and paper_values[1] < 0.0 and PAPER_FR0[1] > 0.0 else "NOT_REPRODUCED",
        "BAND2_ENHANCEMENT": "REPRODUCED" if paper_values[1] is not None and abs(paper_values[1]) > abs(PAPER_FR0[1]) else "NOT_REPRODUCED",
        "BAND3_ENHANCEMENT": "REPRODUCED" if paper_values[2] is not None and paper_values[2] > 0.0 and abs(paper_values[2]) > abs(PAPER_FR0[2]) else "NOT_REPRODUCED",
        "BAND23_DOMINANCE": "REPRODUCED" if all(value is not None for value in paper_values) and abs(paper_values[1]) > abs(paper_values[0]) and abs(paper_values[2]) > abs(paper_values[0]) else "NOT_REPRODUCED",
        "BAND23_OPPOSITE_SIGN_PAIR": "REPRODUCED" if paper_values[1] is not None and paper_values[2] is not None and paper_values[1] < 0.0 < paper_values[2] else "NOT_REPRODUCED",
    }
    qualitative_ok = all(value == "REPRODUCED" for value in classifications.values()) and tess_sign_stable
    payload = {
        "schema": "trilatt_e9e_c_fr04_k_kprime_berry_evolution_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_sha256": file_sha(contract_path),
        "preserved_e9e_b_result_sha256": file_sha(e9e_b_result_path),
        "contract": contract,
        "self_checks": checks,
        "analytic_geometry_validation": analytic_validation,
        "geometry": {
            "primary_tessellation": 96,
            "polygon_vertex_count": geometry_case["polygon_vertex_count"],
            "polygon_area": geometry_case["polygon_area"],
            "analytic_area": geometry_case["analytic_area"],
            "relative_area_error": geometry_case["relative_area_error_to_analytic"],
            "roundtrip_error": geometry_case["public_cartesian_to_mpb_roundtrip_error"],
            "c3_symmetry": geometry_case["c3_vertex_symmetry"],
        },
        "spectral_replay": {
            "expected": replay_expected,
            "actual": replay_actual,
            "max_abs_error": max(abs(float(a) - float(b)) for a, b in zip(replay_actual, replay_expected)),
            "status": "PASSED" if replay else "FAILED",
        },
        "results": {
            "R96_TESS96": r96,
            "R64_TESS48_PRIMARY_K": tess_control["R64_TESS48"],
            "R64_TESS96_PRIMARY_K": tess_control["R64_TESS96"],
        },
        "tessellation_control": {
            "omega_r64_tess48": tess48_values,
            "omega_r64_tess96": tess96_values,
            "absolute_difference": [None if a is None or b is None else abs(a - b) for a, b in zip(tess48_values, tess96_values)],
            "qualitative_sign_stability": tess_sign_stable,
        },
        "trs_control": trs,
        "trs_relative_residual_max": trs_max,
        "paper_comparison": {
            "center": "PUBLIC_K_PRIME",
            "paper_stencil_omega_over_a2": paper_values,
            "fine_stencil_omega_over_a2": fine_values,
            "paper_targets": list(PAPER_FR04),
            "signed_error_paper_stencil": [None if value is None else value - target for value, target in zip(paper_values, PAPER_FR04)],
            "signed_error_fine_stencil": [None if value is None else value - target for value, target in zip(fine_values, PAPER_FR04)],
            "band1_suppression": classifications["BAND1_SUPPRESSION"],
            "band2_sign_reversal": classifications["BAND2_SIGN_REVERSAL"],
            "band2_enhancement": classifications["BAND2_ENHANCEMENT"],
            "band3_enhancement": classifications["BAND3_ENHANCEMENT"],
            "band23_dominance": classifications["BAND23_DOMINANCE"],
            "band23_opposite_sign_pair": classifications["BAND23_OPPOSITE_SIGN_PAIR"],
        },
        "all_three_r96_rank1_bands_qualified": all_qualified,
        "classifications": classifications,
        "at_k_berry_evolution": "SUPPORTED" if qualitative_ok and all_qualified and replay and trs_max <= 0.01 else "NOT_SUPPORTED",
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
        "E9E_C_OVERALL": (
            "FR0P4_K_POINT_BERRY_EVOLUTION_READY_FOR_SUPERVISOR_DECISION"
            if qualitative_ok and all_qualified and replay and trs_max <= 0.01
            else "FAIL_CLOSED"
        ),
    }
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9e/c_berry_evolution_contract.json"
    output = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else root() / "audit/e9e/c_berry_evolution_result.json"
    if "--self-check" in sys.argv:
        contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
        e9e_b_result = json.loads((root() / "audit/e9e/b_spectral_embedding_result.json").read_text(encoding="utf-8-sig"))
        geometry_case = polygon_case(0.4, 96)
        preflight = build_triangular_coordinate_preflight()
        print(json.dumps(self_checks(contract, preflight, geometry_case, e9e_b_result), sort_keys=True))
    else:
        payload = run(output, contract_path)
        print(json.dumps({"schema": payload["schema"], "overall": payload["E9E_C_OVERALL"], "telemetry": payload["telemetry"]}, sort_keys=True))


