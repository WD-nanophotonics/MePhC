"""E9E.D bounded f_r=0.4 local Berry distribution runner."""
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit.e9e.a_rounded_triangle_geometry import build_geometry, validate_geometry
from audit.e9e.run_spectral_embedding import make_lattice, make_solver_geometry, polygon_case
from audit.e9e.run_berry_evolution import (
    BANDS,
    KPRIME_PUBLIC,
    K_PUBLIC,
    TRANSPORT,
    excluded,
    external_contexts,
    frame_rank1,
    omega_over_a2,
)
from mephc.eigenspace import EigenSubspace
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import qualify_plaquette_boundary, qualify_plaquette_interior
from mephc.spectral_association import ExternalIsolationContext
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

WORK_ORDER = "TRILATT-E9E-D-20260824-197"
R64, R96 = 64, 96
NUM_BANDS = 6
SIDE = 1.0 / 144.0
NODE_DENOM = 288
KPRIME_NODE = (-192, 0)
K_NODE = (192, 0)
CONTEXT_OFFSETS = tuple((i, j) for i in range(-6, 7) for j in range(-6, 7))
CORE_OFFSETS = tuple((i, j) for i in range(-4, 5) for j in range(-4, 5))
R96_OFFSETS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
TRS_OFFSETS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
TESS_OFFSETS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
SOLVER_TOLERANCE = 1.0e-7
MESH_SIZE = 3
F_R = 0.4
REPRESENTATION = "mpb_energy_eh_v1"
EXPECTED_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
BASE_SANDBOX = "2737bf48384c75cc7b283a5e2c2f422624a8b4d2"
REPLAY_EXPECTED = (-0.18897993050559894, -9.463335640897164, 9.655478906791302)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def node_id(node: tuple[int, int]) -> list[int]:
    return [int(node[0]), int(node[1]), NODE_DENOM]


def public_q(node: tuple[int, int]) -> tuple[float, float]:
    return (float(node[0]) / NODE_DENOM, float(node[1]) / NODE_DENOM)


def offset_node(center: tuple[int, int], dx_units: int, dy_units: int) -> tuple[int, int]:
    return (int(center[0] + dx_units), int(center[1] + dy_units))


def cache_key(node, resolution, tessellation, geometry_digest):
    return (
        F_R, geometry_digest, int(tessellation), int(resolution),
        (int(node[0]), int(node[1]), NODE_DENOM), REPRESENTATION,
        NUM_BANDS, SOLVER_TOLERANCE, MESH_SIZE,
    )


def solve_node(provider, preflight, node, resolution, tessellation, geometry_digest, cache, counters):
    node = (int(node[0]), int(node[1]))
    key = cache_key(node, resolution, tessellation, geometry_digest)
    if key in cache:
        counters["cache_hits"] += 1
        return cache[key]
    counters["solver_requests"] += 1
    q = public_q(node)
    raw = provider.solve(q)
    frequencies = tuple(float(x) for x in raw.frequencies)
    vectors = tuple(np.asarray(x, dtype=np.complex128) for x in raw.normalized_vectors)
    if len(frequencies) != NUM_BANDS or len(vectors) != NUM_BANDS:
        counters["solver_failures"] += 1
        raise RuntimeError(f"incomplete six-band snapshot at {node}")
    if not all(math.isfinite(x) for x in frequencies) or any(not np.all(np.isfinite(v)) for v in vectors):
        counters["solver_failures"] += 1
        raise RuntimeError(f"non-finite six-band snapshot at {node}")
    value = {
        "node": node_id(node),
        "public_q": list(q),
        "mpb_fractional_q": [float(x) for x in preflight.public_q_to_mpb(q)],
        "frequencies": frequencies,
        "raw": raw,
    }
    cache[key] = value
    return value


def status_dict(value):
    return {"status": value.status, "is_qualified": bool(value.is_qualified)}


def nearest_external_gap(frequencies, band):
    target = float(frequencies[band])
    return min(abs(target - float(value)) for index, value in enumerate(frequencies) if index != band)


def evaluate(node, grid_name, grid_i, grid_j, center, band, resolution, tessellation, provider, preflight, geometry_digest, cache, counters):
    corners = (
        (node[0] - 1, node[1] - 1),
        (node[0] + 1, node[1] - 1),
        (node[0] + 1, node[1] + 1),
        (node[0] - 1, node[1] + 1),
    )
    values = [solve_node(provider, preflight, corner, resolution, tessellation, geometry_digest, cache, counters) for corner in corners]
    center_value = solve_node(provider, preflight, node, resolution, tessellation, geometry_digest, cache, counters)
    profile = []
    for label, value in [(f"vertex_{i}", value) for i, value in enumerate(values)] + [("center", center_value)]:
        gap = nearest_external_gap(value["frequencies"], band)
        profile.append({
            "label": label,
            "node": value["node"],
            "q": value["public_q"],
            "frequencies": list(value["frequencies"]),
            "external_gap": float(gap),
            "E3_PROFILE": "PASS" if gap >= TRANSPORT.min_external_gap else "FAIL",
        })
    frames = [frame_rank1(tuple(value["public_q"]), value["raw"], band) for value in values]
    center_frame = frame_rank1(tuple(center_value["public_q"]), center_value["raw"], band)
    contexts = external_contexts([value["frequencies"] for value in values], band)
    path = qualify_ordered_path(tuple(frames), contexts, thresholds=TRANSPORT, closed=True, provenance={"source": "E9E.D rational-grid local map", "band": band, "grid": grid_name, "resolution": resolution, "tessellation": tessellation})
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(tuple(frames), contexts, thresholds=TRANSPORT, provenance={"source": "E9E.D E4A", "band": band, "grid": grid_name})
    spokes = tuple(
        ExternalIsolationContext(
            excluded(value["frequencies"], band),
            excluded(center_value["frequencies"], band),
            {"source": "E9E.D E4B six-band context", "band": band, "grid": grid_name},
        )
        for value in values
    )
    interior = qualify_plaquette_interior(boundary, center_frame, spokes, provenance={"source": "E9E.D E4B", "band": band, "grid": grid_name})
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    determinant = None if wilson.determinant is None else complex(wilson.determinant)
    path_ok = path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)
    qualified = bool(
        all(row["E3_PROFILE"] == "PASS" for row in profile)
        and path_ok and wilson.status == WILSON_LOOP_QUALIFIED
        and boundary.is_qualified and interior.is_qualified
        and phase is not None and determinant is not None and math.isfinite(phase)
    )
    omega = None if not qualified else omega_over_a2(float(-phase / (SIDE ** 2)))
    literal = None if not qualified else omega_over_a2(float(-determinant.imag / (SIDE ** 2)))
    reasons = [] if qualified else [
        reason for reason, failed in (
            ("external_gap", not all(row["E3_PROFILE"] == "PASS" for row in profile)),
            ("ordered_path", not path_ok),
            ("wilson", wilson.status != WILSON_LOOP_QUALIFIED),
            ("boundary", not boundary.is_qualified),
            ("interior", not interior.is_qualified),
            ("finite_estimator", phase is None or determinant is None),
        ) if failed
    ]
    return {
        "grid_name": grid_name,
        "grid_i": int(grid_i),
        "grid_j": int(grid_j),
        "band": int(band + 1),
        "public_q": list(center),
        "offset_from_K_prime": [float(center[0] - KPRIME_PUBLIC[0]), float(center[1] - KPRIME_PUBLIC[1])],
        "mpb_fractional_q": center_value["mpb_fractional_q"],
        "center_frequency": float(center_value["frequencies"][band]),
        "minimum_external_gap": float(min(row["external_gap"] for row in profile)),
        "E3_status": "PASSED" if all(row["E3_PROFILE"] == "PASS" for row in profile) else "FAILED",
        "E4A_status": boundary.status,
        "E4B_status": interior.status,
        "Wilson_status": wilson.status,
        "Omega_over_a2": omega,
        "Omega_literal_over_a2": literal,
        "qualification_status": "QUALIFIED" if qualified else "NOT_REPORTED",
        "failure_reason": None if qualified else ";".join(reasons),
        "evidence": {
            "profile": profile,
            "path": status_dict(path),
            "boundary": status_dict(boundary),
            "interior": status_dict(interior),
            "wilson": {
                "status": wilson.status,
                "rank": wilson.rank,
                "determinant_phase": phase,
                "unitarity_residual": wilson.unitarity_residual,
            },
        },
    }


def provider_bundle(geometry_case):
    preflight = build_triangular_coordinate_preflight()
    lattice = make_lattice()
    return preflight, {
        (R64, 96): MPBLiveEnergySpectralProvider(
            geometry=list(make_solver_geometry(geometry_case)), geometry_lattice=lattice,
            resolution=R64, num_bands=NUM_BANDS, polarization=mp.TE,
            default_material=mp.Medium(epsilon=7.0225), eigensolver_tolerance=SOLVER_TOLERANCE,
            deterministic=True, mesh_size=MESH_SIZE,
        ),
        (R64, 48): MPBLiveEnergySpectralProvider(
            geometry=list(make_solver_geometry(polygon_case(F_R, 48))), geometry_lattice=lattice,
            resolution=R64, num_bands=NUM_BANDS, polarization=mp.TE,
            default_material=mp.Medium(epsilon=7.0225), eigensolver_tolerance=SOLVER_TOLERANCE,
            deterministic=True, mesh_size=MESH_SIZE,
        ),
        (R96, 96): MPBLiveEnergySpectralProvider(
            geometry=list(make_solver_geometry(geometry_case)), geometry_lattice=lattice,
            resolution=R96, num_bands=NUM_BANDS, polarization=mp.TE,
            default_material=mp.Medium(epsilon=7.0225), eigensolver_tolerance=SOLVER_TOLERANCE,
            deterministic=True, mesh_size=MESH_SIZE,
        ),
    }


def self_checks(contract, source_contract, geometry_case, analytic_validation, preflight, previous):
    checks = {
        "WORK_ORDER": contract["work_order_id"] == WORK_ORDER,
        "BASE_SANDBOX": contract["base_sandbox_sha"] == BASE_SANDBOX,
        "EXPECTED_MAIN": contract["expected_main_head"] == EXPECTED_MAIN,
        "SOURCE_FR04_PANELS_BOUND": source_contract["binding_policy"]["source_panels_bound"] is True and source_contract["source"]["panel_identifier_band1"] == "Figure 3(g)" and source_contract["source"]["panel_identifier_band2"] == "Figure 3(h)" and source_contract["source"]["panel_identifier_band3"] == "Figure 3(i)",
        "PHYSICAL_MODEL": contract["model"]["f_r"] == 0.4 and geometry_case["f_r"] == 0.4,
        "FR04_GEOMETRY_DIGEST_REPLAY": geometry_case["analytic_boundary_digest"] == analytic_validation["boundary_digest"],
        "PHYSICAL_MODEL_REPLAY": abs(geometry_case["analytic_area"] - 0.2078460969082653) <= 1.0e-10 and geometry_case["posthoc_area_rescale"] is False,
        "PUBLIC_REAL_SPACE_CONVERSION": geometry_case["public_cartesian_to_mpb_roundtrip_error"] <= 1.0e-12,
        "PUBLIC_RECIPROCAL_CONVERSION": bool(preflight.ready) and preflight.round_trip_residual <= 1.0e-12,
        "CONTEXT_GRID": len(CONTEXT_OFFSETS) == 169,
        "CORE_GRID": len(CORE_OFFSETS) == 81,
        "MAP_STEP": contract["map"]["context_step"] == "1/36" and contract["map"]["core_step"] == "1/144" and contract["map"]["plaquette_side"] == "1/144",
        "RATIONAL_NODE_IDENTITY": contract["rational_grid"]["node_denominator"] == NODE_DENOM and contract["rational_grid"]["identity_fields"] == ["f_r","geometry_digest","tessellation","resolution","public_rational_node","representation","num_bands","solver_tolerance","mesh_size"],
        "CORE_GATE": contract["qualification"]["core_3x3_all_bands_required"] is True,
        "R96_POINTS_PRECOMMITTED": tuple(tuple(x) for x in contract["r96_validation"]["offsets_in_1_over_72_units"]) == R96_OFFSETS,
        "TRS_POINTS_PRECOMMITTED": tuple(tuple(x) for x in contract["trs_control"]["offsets_in_1_over_72_units"]) == TRS_OFFSETS,
        "TESSELLATION_POINTS_PRECOMMITTED": tuple(tuple(x) for x in contract["tessellation_control"]["offsets_in_1_over_18_units"]) == TESS_OFFSETS,
        "KPRIME_REPLAY_BINDING": tuple(contract["replay"]["expected_kprime_omega_wilson"]) == REPLAY_EXPECTED,
        "PREVIOUS_E9E_C1_PRESERVED": previous["E9E_C_C1_OVERALL"] == "OPTIMIZED_FINE_STENCIL_FR0P4_BERRY_READY_FOR_SUPERVISOR_DECISION",
        "NO_FR0_RECOMPUTE": True,
        "NO_FR0P5_WORK": contract["authorization"]["fr0p5_work"] is False,
        "NO_CHERN_CODE_PATH": contract["authorization"]["valley_chern"] is False and contract["authorization"]["full_bz_chern"] is False and contract["authorization"]["hbz_integration"] is False,
        "NO_PARAMETER_SWEEP": contract["authorization"]["parameter_sweep"] is False,
        "NO_PAPER_RETRY": contract["authorization"]["paper_retry"] is False,
        "RANK1_ONLY": contract["authorization"]["rank2_or_rank3_substitution"] is False and contract["model"]["rank"] == 1,
        "NO_ZERO_FILL": contract["map"]["no_zero_fill"] is True,
        "NO_INTERPOLATION": contract["map"]["no_interpolation"] is True,
        "ANALYTIC_VALIDATION": analytic_validation["all_checks_passed"] is True,
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9E.D self-check failed: {checks}")
    return checks


def row_set(center_node, offsets, step_node, grid_name, provider, resolution, tessellation, preflight, geometry_digest, cache, counters):
    rows = []
    for i, j in offsets:
        node = offset_node(center_node, i * step_node, j * step_node)
        center = public_q(node)
        bands = [evaluate(node, grid_name, i, j, center, band, resolution, tessellation, provider, preflight, geometry_digest, cache, counters) for band in BANDS]
        rows.append({"grid_name": grid_name, "grid_i": i, "grid_j": j, "node": node_id(node), "public_q": list(center), "offset_from_K_prime": [float(center[0] - KPRIME_PUBLIC[0]), float(center[1] - KPRIME_PUBLIC[1])], "bands": bands})
    return rows


def run(output: Path, contract_path: Path):
    started = time.monotonic()
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    source_path = ROOT / "audit/e9e/d_source_panel_contract.json"
    source_contract = json.loads(source_path.read_text(encoding="utf-8-sig"))
    previous_path = ROOT / "audit/e9e/c1_optimized_fine_stencil_result.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8-sig"))
    geometry_case = polygon_case(F_R, 96)
    analytic_validation = validate_geometry(build_geometry(F_R))
    preflight, providers = provider_bundle(geometry_case)
    checks = self_checks(contract, source_contract, geometry_case, analytic_validation, preflight, previous)
    geometry_digest = hashlib.sha256(json.dumps({"f_r": F_R, "tessellation": 96, "analytic_boundary_digest": geometry_case["analytic_boundary_digest"], "mpb_vertices": geometry_case["mpb_vertices"]}, sort_keys=True).encode()).hexdigest()
    cache, counters = {}, {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    context_rows = row_set(KPRIME_NODE, CONTEXT_OFFSETS, 8, "context", providers[(R64,96)], R64, 96, preflight, geometry_digest, cache, counters)
    core_rows = row_set(KPRIME_NODE, CORE_OFFSETS, 2, "core", providers[(R64,96)], R64, 96, preflight, geometry_digest, cache, counters)
    r96_rows = []
    for dx, dy in R96_OFFSETS:
        node = offset_node(KPRIME_NODE, dx * 4, dy * 4)
        center = public_q(node)
        r64_bands = [evaluate(node, "r96_validation_R64", dx, dy, center, band, R64, 96, providers[(R64,96)], preflight, geometry_digest, cache, counters) for band in BANDS]
        r96_bands = [evaluate(node, "r96_validation_R96", dx, dy, center, band, R96, 96, providers[(R96,96)], preflight, geometry_digest, cache, counters) for band in BANDS]
        r96_rows.append({"offset_in_1_over_72_units":[dx,dy], "node":node_id(node), "public_q":list(center), "R64":r64_bands, "R96":r96_bands})
    trs_rows = []
    for dx, dy in TRS_OFFSETS:
        k_node = offset_node(K_NODE, dx * 4, dy * 4)
        kp_node = offset_node(KPRIME_NODE, -dx * 4, -dy * 4)
        k_bands = [evaluate(k_node, "trs_K", dx, dy, public_q(k_node), band, R64, 96, providers[(R64,96)], preflight, geometry_digest, cache, counters) for band in BANDS]
        kp_bands = [evaluate(kp_node, "trs_K_prime", dx, dy, public_q(kp_node), band, R64, 96, providers[(R64,96)], preflight, geometry_digest, cache, counters) for band in BANDS]
        trs_rows.append({"offset_in_1_over_72_units": [dx,dy], "K": k_bands, "K_prime": kp_bands})
    tess_rows = []
    tess_digest = {48: hashlib.sha256(json.dumps({"f_r":F_R,"tessellation":48,"analytic_boundary_digest":polygon_case(F_R,48)["analytic_boundary_digest"]},sort_keys=True).encode()).hexdigest(), 96: geometry_digest}
    for dx, dy in TESS_OFFSETS:
        node = offset_node(KPRIME_NODE, dx * 16, dy * 16)
        rows_by_tess = {}
        for tess in (48,96):
            rows_by_tess[str(tess)] = [evaluate(node, f"tess{tess}", dx, dy, public_q(node), band, R64, tess, providers[(R64,tess)], preflight, tess_digest[tess], cache, counters) for band in BANDS]
        tess_rows.append({"offset_in_1_over_18_units":[dx,dy], "node":node_id(node), "public_q":list(public_q(node)), "tessellations":rows_by_tess})
    center = next(row for row in context_rows if row["grid_i"] == 0 and row["grid_j"] == 0)
    replay = [{"band": band + 1, "expected": REPLAY_EXPECTED[band], "actual": center["bands"][band]["Omega_over_a2"], "abs_error": abs(center["bands"][band]["Omega_over_a2"] - REPLAY_EXPECTED[band])} for band in BANDS]
    payload = {
        "schema": "trilatt_e9e_d_fr04_local_berry_distribution_raw_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": BASE_SANDBOX,
        "expected_main_head": EXPECTED_MAIN,
        "calculation_code_git_sha": git_head(),
        "contract_sha256": file_sha(contract_path),
        "source_contract_sha256": file_sha(source_path),
        "previous_e9e_c1_result_sha256": file_sha(previous_path),
        "contract": contract,
        "source_contract": source_contract,
        "source_status": "BOUND",
        "self_checks": checks,
        "geometry": {key: geometry_case[key] for key in ("f_r","arc_segments_per_corner","analytic_boundary_digest","polygon_vertex_count","polygon_area","analytic_area","relative_area_error_to_analytic","public_cartesian_to_mpb_roundtrip_error","c3_vertex_symmetry","posthoc_area_rescale")},
        "analytic_geometry_validation": analytic_validation,
        "coordinate_preflight": {"ready": preflight.ready, "public_K": list(K_PUBLIC), "public_K_prime": list(KPRIME_PUBLIC), "mpb_K": [float(x) for x in preflight.public_q_to_mpb(K_PUBLIC)], "mpb_K_prime": [float(x) for x in preflight.public_q_to_mpb(KPRIME_PUBLIC)], "mapping_digest": preflight.mapping_digest, "round_trip_residual": preflight.round_trip_residual},
        "map_definition": {"context_center": list(KPRIME_PUBLIC), "context_count": len(context_rows), "context_step": 1.0/36.0, "core_count": len(core_rows), "core_step": 1.0/144.0, "plaquette_side": SIDE, "resolution": R64, "tessellation": 96},
        "context_map_rows": context_rows,
        "core_map_rows": core_rows,
        "r96_validation_rows": r96_rows,
        "trs_rows": trs_rows,
        "tessellation_control_rows": tess_rows,
        "exact_k_replay": replay,
        "cache_identity": {"f_r":F_R,"geometry_digest_tess96":geometry_digest,"node_denominator":NODE_DENOM,"representation":REPRESENTATION,"num_bands":NUM_BANDS,"solver_tolerance":SOLVER_TOLERANCE,"mesh_size":MESH_SIZE,"identity_fields":contract["rational_grid"]["identity_fields"]},
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), **counters},
        "berry_field_map": "FR04_LOCAL_PATCH_ONLY",
        "fr0p5_work": "NOT_AUTHORIZED",
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "hbz_integration": "NOT_AUTHORIZED",
        "parameter_sweep": "NOT_AUTHORIZED",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = ROOT / "audit/e9e/d_berry_distribution_contract.json"
    if "--self-check" in sys.argv:
        contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
        source = json.loads((ROOT / "audit/e9e/d_source_panel_contract.json").read_text(encoding="utf-8-sig"))
        previous = json.loads((ROOT / "audit/e9e/c1_optimized_fine_stencil_result.json").read_text(encoding="utf-8-sig"))
        geometry_case = polygon_case(F_R, 96)
        analytic = validate_geometry(build_geometry(F_R))
        preflight = build_triangular_coordinate_preflight()
        print(json.dumps(self_checks(contract, source, geometry_case, analytic, preflight, previous), sort_keys=True))
    else:
        output = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else ROOT / "audit/e9e/d_raw_result.json"
        payload = run(output, contract_path)
        print(json.dumps({"schema":payload["schema"],"calculation_code_git_sha":payload["calculation_code_git_sha"],"telemetry":payload["telemetry"]}, sort_keys=True))


