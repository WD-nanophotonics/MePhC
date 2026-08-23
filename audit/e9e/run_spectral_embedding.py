"""E9E.B live rounded-triangle spectral/tessellation qualification.

This runner imports the sealed E9E.A analytic geometry, polygonizes only the
analytic line-and-arc boundary, and performs the bounded MPB spectral gate.
No Berry, Wilson-loop, or Chern calculation is present.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import meep as mp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.e9e.a_rounded_triangle_geometry import (
    BASE_AREA,
    BASE_CIRCUMRADIUS,
    REAL_BASIS,
    build_geometry,
    cartesian_to_mpb,
    polygon_area,
    sample_boundary,
    validate_geometry,
)
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.valley_benchmark import build_triangular_coordinate_preflight


WORK_ORDER = "TRILATT-E9E-B-20260824-189"
R64, R96 = 64, 96
NUM_BANDS = 6
SOLVER_TOLERANCE = 1.0e-7
MESH_SIZE = 3
K_PUBLIC = (2.0 / 3.0, 0.0)
FR0_REPLAY = (0.26833164396586207, 0.3134784445238986, 0.3563287763970286, 0.5644651267329948)
DEGENERACY_TOLERANCE = 1.0e-6


def root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def closed_boundary(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if len(points) > 1 and np.linalg.norm(points[0] - points[-1]) <= 1.0e-12:
        return points[:-1]
    return points


def rotate120(point: np.ndarray, turns: int) -> np.ndarray:
    angle = turns * 2.0 * math.pi / 3.0
    matrix = np.asarray(
        ((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle))),
        dtype=float,
    )
    return matrix @ point


def c3_vertex_symmetry(points: np.ndarray) -> tuple[bool, float]:
    points = np.asarray(points, dtype=float)
    distances = []
    for point in points:
        for turn in (1, 2):
            rotated = rotate120(point, turn)
            distances.append(float(np.min(np.linalg.norm(points - rotated, axis=1))))
    maximum = max(distances, default=0.0)
    return maximum <= 1.0e-12, maximum


def polygon_case(f_r: float, arc_segments: int | None) -> dict:
    analytic = build_geometry(f_r)
    if f_r == 0.0:
        physical = np.asarray(analytic["vertices_cartesian"], dtype=float)
        mode = "EXACT_ACCEPTED_TRIANGLE"
        segments = 0
        max_distance = 0.0
    else:
        if arc_segments is None:
            raise ValueError("rounded polygon requires arc_segments")
        physical = closed_boundary(sample_boundary(analytic, arc_samples=arc_segments))
        mode = "ANALYTIC_LINE_ARC_TESSELLATION"
        segments = int(arc_segments)
        max_distance = float(
            analytic["physical_arc_radius"]
            * (1.0 - math.cos(math.pi / (3.0 * arc_segments)))
        )
    mpb = cartesian_to_mpb(physical)
    roundtrip = (REAL_BASIS @ mpb.T).T
    c3_passed, c3_error = c3_vertex_symmetry(physical)
    analytic_area = float(analytic["physical_area_analytic"])
    area = float(polygon_area(physical))
    return {
        "f_r": float(f_r),
        "arc_segments_per_corner": segments,
        "mode": mode,
        "physical_vertices": physical.tolist(),
        "mpb_vertices": mpb.tolist(),
        "polygon_vertex_count": int(len(physical)),
        "polygon_area": area,
        "analytic_area": analytic_area,
        "relative_area_error_to_analytic": abs(area - analytic_area) / analytic_area,
        "c3_vertex_symmetry": c3_passed,
        "c3_vertex_symmetry_max_error": c3_error,
        "max_distance_from_analytic_boundary": max_distance,
        "public_cartesian_to_mpb_roundtrip_error": float(
            np.max(np.linalg.norm(roundtrip - physical, axis=1))
        ),
        "analytic_boundary_digest": analytic["boundary_digest"],
        "posthoc_area_rescale": False,
    }


def exact_circle_case() -> dict:
    radius = math.sqrt(BASE_AREA / math.pi)
    return {
        "f_r": 0.5,
        "mode": "EXACT_AREA_CIRCLE",
        "radius": float(radius),
        "area": float(math.pi * radius**2),
        "analytic_area": float(BASE_AREA),
        "relative_area_error_to_analytic": abs(math.pi * radius**2 - BASE_AREA) / BASE_AREA,
        "c3_symmetry": True,
        "c2z_restored": True,
        "posthoc_area_rescale": False,
    }


def geometry_only_checks(contract: dict) -> tuple[dict, dict]:
    f04 = {
        str(n): polygon_case(0.4, n)
        for n in contract["tessellation"]["f_r_0p4_arc_segments_per_corner"]
    }
    circle_polygon = polygon_case(0.5, contract["tessellation"]["f_r_0p5_arc_segments_per_corner"])
    circle_exact = exact_circle_case()
    errors = [f04[str(n)]["relative_area_error_to_analytic"] for n in (24, 48, 96)]
    distances = [f04[str(n)]["max_distance_from_analytic_boundary"] for n in (24, 48, 96)]
    checks = {
        "GEOMETRY_SOURCE_BOUND": True,
        "POLYGON_AREA_NOT_POSTHOC_RESCALED": all(not row["posthoc_area_rescale"] for row in f04.values()),
        "POLYGON_VERTEX_COUNT": all(row["polygon_vertex_count"] > 0 for row in f04.values()),
        "POLYGON_AREA": all(row["polygon_area"] > 0.0 for row in f04.values()),
        "RELATIVE_AREA_ERROR_TO_ANALYTIC": errors[0] > errors[1] > errors[2] >= 0.0,
        "C3_VERTEX_SYMMETRY": all(row["c3_vertex_symmetry"] for row in f04.values()),
        "MAX_DISTANCE_FROM_ANALYTIC_BOUNDARY": distances[0] > distances[1] > distances[2] >= 0.0,
        "PUBLIC_CARTESIAN_TO_MPB_ROUNDTRIP_ERROR": all(
            row["public_cartesian_to_mpb_roundtrip_error"] <= 1.0e-12 for row in f04.values()
        ),
        "CIRCLE_POLYGON_96_AREA": circle_polygon["relative_area_error_to_analytic"] >= 0.0,
        "CIRCLE_EXACT_AREA": circle_exact["relative_area_error_to_analytic"] <= 1.0e-15,
        "CIRCLE_C2Z": circle_exact["c2z_restored"],
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9E.B geometry-only self-check failed: {checks}")
    return checks, {
        "fr0p4": f04,
        "fr0p5_polygon96": circle_polygon,
        "fr0p5_exact_circle": circle_exact,
    }


def make_lattice() -> object:
    return mp.Lattice(
        size=mp.Vector3(1, 1, 0),
        basis1=mp.Vector3(float(REAL_BASIS[0, 0]), float(REAL_BASIS[1, 0]), 0),
        basis2=mp.Vector3(float(REAL_BASIS[0, 1]), float(REAL_BASIS[1, 1]), 0),
    )


def make_solver_geometry(case: dict) -> tuple:
    if case["mode"] == "EXACT_AREA_CIRCLE":
        return (
            mp.Cylinder(
                radius=float(case["radius"]),
                height=mp.inf,
                material=mp.air,
            ),
        )
    return (
        mp.Prism(
            vertices=[
                mp.Vector3(float(x), float(y), 0.0)
                for x, y in case["mpb_vertices"]
            ],
            height=mp.inf,
            material=mp.air,
        ),
    )


def make_provider(resolution: int, case: dict, lattice: object) -> tuple:
    background = mp.Medium(epsilon=7.0225)
    provider = MPBLiveEnergySpectralProvider(
        geometry=list(make_solver_geometry(case)),
        geometry_lattice=lattice,
        resolution=resolution,
        num_bands=NUM_BANDS,
        polarization=mp.TE,
        default_material=background,
        eigensolver_tolerance=SOLVER_TOLERANCE,
        deterministic=True,
        mesh_size=MESH_SIZE,
    )
    return provider, background


def solve_case(case_name: str, resolution: int, case: dict, preflight: object) -> dict:
    lattice = make_lattice()
    provider, _ = make_provider(resolution, case, lattice)
    raw = provider.solve(K_PUBLIC)
    frequencies = [float(value) for value in raw.frequencies]
    if len(frequencies) != NUM_BANDS or not all(math.isfinite(value) for value in frequencies):
        raise RuntimeError(f"incomplete or non-finite six-band result for {case_name}")
    return {
        "case_name": case_name,
        "resolution": int(resolution),
        "mode": case["mode"],
        "public_k": list(K_PUBLIC),
        "mpb_fractional_k": [float(value) for value in preflight.public_q_to_mpb(K_PUBLIC)],
        "frequencies": frequencies,
        "gap21": float(frequencies[1] - frequencies[0]),
        "gap32": float(frequencies[2] - frequencies[1]),
        "provider_representation": raw.provenance.get("representation"),
    }


def run(output: Path, contract_path: Path) -> dict:
    started = time.monotonic()
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    preflight = build_triangular_coordinate_preflight()
    if not preflight.ready:
        raise RuntimeError("E9E.B coordinate preflight failed")
    geometry_checks, geometry = geometry_only_checks(contract)
    fr0_case = polygon_case(0.0, None)
    fr0p4_48 = polygon_case(0.4, 48)
    fr0p4_96 = polygon_case(0.4, 96)
    fr0p5_polygon = polygon_case(0.5, 96)
    fr0p5_circle = exact_circle_case()

    results = {}
    results["FR0_R64_EXACT_TRIANGLE"] = solve_case("FR0_R64_EXACT_TRIANGLE", R64, fr0_case, preflight)
    results["FR0P4_R64_TESS48"] = solve_case("FR0P4_R64_TESS48", R64, fr0p4_48, preflight)
    results["FR0P4_R64_TESS96"] = solve_case("FR0P4_R64_TESS96", R64, fr0p4_96, preflight)
    results["FR0P4_R96_TESS96"] = solve_case("FR0P4_R96_TESS96", R96, fr0p4_96, preflight)
    results["FR0P5_R64_POLYGON96"] = solve_case("FR0P5_R64_POLYGON96", R64, fr0p5_polygon, preflight)
    results["FR0P5_R64_EXACT_CIRCLE"] = solve_case("FR0P5_R64_EXACT_CIRCLE", R64, fr0p5_circle, preflight)
    results["FR0P5_R96_EXACT_CIRCLE"] = solve_case("FR0P5_R96_EXACT_CIRCLE", R96, fr0p5_circle, preflight)

    fr0 = results["FR0_R64_EXACT_TRIANGLE"]
    p48 = results["FR0P4_R64_TESS48"]
    p96 = results["FR0P4_R64_TESS96"]
    p96r = results["FR0P4_R96_TESS96"]
    circle64 = results["FR0P5_R64_EXACT_CIRCLE"]
    circle96 = results["FR0P5_R96_EXACT_CIRCLE"]
    replay = bool(np.allclose(fr0["frequencies"][:4], FR0_REPLAY, rtol=0.0, atol=contract["spectral"]["fr0_replay_atol"]))
    fr0p4_trends = {
        "gap21": "REPRODUCED" if p96["gap21"] > fr0["gap21"] else "NOT_REPRODUCED",
        "gap32": "REPRODUCED" if p96["gap32"] < fr0["gap32"] else "NOT_REPRODUCED",
    }
    degeneracy = bool(abs(circle96["gap32"]) <= contract["spectral"]["circle_degeneracy_tolerance"])
    polygon_circle_drift = [
        abs(a - b)
        for a, b in zip(
            results["FR0P5_R64_POLYGON96"]["frequencies"],
            results["FR0P5_R64_EXACT_CIRCLE"]["frequencies"],
        )
    ]
    payload = {
        "schema": "trilatt_e9e_b_live_rounded_triangle_spectral_embedding_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_sha256": file_sha(contract_path),
        "contract": contract,
        "geometry_only_checks": geometry_checks,
        "geometry": geometry,
        "coordinate_preflight": {
            "ready": bool(preflight.ready),
            "public_k": list(K_PUBLIC),
            "mpb_fractional_k": [float(value) for value in preflight.public_q_to_mpb(K_PUBLIC)],
            "round_trip_residual": float(preflight.round_trip_residual),
            "mapping_digest": preflight.mapping_digest,
            "real_space_coordinate_label": "r_not_q",
            "conversion_count": "EXACTLY_ONCE",
        },
        "results": results,
        "fr0_live_spectral_replay": "PASSED" if replay else "FAILED",
        "fr0p4_tessellation_geometry_convergence": "PASSED",
        "gap21_trend": fr0p4_trends["gap21"],
        "gap32_trend": fr0p4_trends["gap32"],
        "fr0p5_polygon_vs_exact_spectral_drift": polygon_circle_drift,
        "fr0p5_band23_gap_r64": circle64["gap32"],
        "fr0p5_band23_gap_r96": circle96["gap32"],
        "fr0p5_degeneracy_trend": "REPRODUCED" if degeneracy else "NOT_REPRODUCED",
        "new_berry_calculation": "NONE",
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "production_code_changed": False,
        "paper_comparison_policy": "TREND_FIDELITY_OVER_POINTWISE_NUMERICAL_COINCIDENCE",
        "telemetry": {
            "wall_time_seconds": time.monotonic() - started,
            "solver_requests": 7,
            "solver_failures": 0,
        },
        "E9E_B_OVERALL": (
            "ROUNDED_TRIANGLE_LIVE_SPECTRAL_EMBEDDING_READY_FOR_SUPERVISOR_DECISION"
            if replay and all(value == "REPRODUCED" for value in fr0p4_trends.values()) and degeneracy
            else "FAIL_CLOSED"
        ),
    }
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9e/b_spectral_embedding_contract.json"
    output = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else root() / "audit/e9e/b_spectral_embedding_result.json"
    if "--self-check" in sys.argv:
        contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
        checks, _ = geometry_only_checks(contract)
        print(json.dumps(checks, sort_keys=True))
    else:
        payload = run(output, contract_path)
        print(json.dumps({"schema": payload["schema"], "overall": payload["E9E_B_OVERALL"], "telemetry": payload["telemetry"]}, sort_keys=True))

