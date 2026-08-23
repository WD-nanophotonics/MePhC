"""E9D bounded local Berry distribution map and controls."""
from __future__ import annotations

import hashlib
import json
import math
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import meep as mp
from audit.e9c.run_k_kprime_rank1_berry import (
    KPRIME_PUBLIC,
    K_PUBLIC,
    TRANSPORT,
    build_inputs,
    excluded,
    external_contexts,
    frame_rank1,
    geometry_inputs,
    make_provider,
    nearest_external_gap,
    omega_over_a2,
)
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import qualify_plaquette_boundary, qualify_plaquette_interior
from mephc.spectral_association import ExternalIsolationContext
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

WORK_ORDER = "TRILATT-E9D-20260824-179"
R64, R96 = 64, 96
NUM_BANDS = 6
BANDS = (0, 1, 2)
SIDE = 1.0 / 36.0
NODE_DENOM = 72
KPRIME_NODE = (-48, 0)
K_NODE = (48, 0)
SOLVER_TOLERANCE = 1e-7
MESH_SIZE = 3
REPRESENTATION = "mpb_energy_eh_v1"
GEOMETRY_ID = "e9c_corrected_physical_triangle_v1"
TRS_OFFSETS = ((0, 0), (4, 0), (-4, 0), (0, 4), (0, -4), (4, 4), (4, -4), (-4, 4), (-4, -4))
R96_OFFSETS = ((0, 0), (4, 0), (-4, 0), (0, 4), (0, -4))


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def q_from_node(node):
    return (float(node[0]) / NODE_DENOM, float(node[1]) / NODE_DENOM)


def node_id(node):
    return [int(node[0]), int(node[1]), NODE_DENOM]


def cache_key(node, resolution):
    return (
        int(resolution), GEOMETRY_ID, REPRESENTATION, NUM_BANDS,
        "TE", SOLVER_TOLERANCE, True, MESH_SIZE, (int(node[0]), int(node[1]), NODE_DENOM),
    )


def solve_node(provider, preflight, node, resolution, cache, counters):
    node = (int(node[0]), int(node[1]))
    key = cache_key(node, resolution)
    if key in cache:
        counters["cache_hits"] += 1
        return cache[key]
    counters["solver_requests"] += 1
    q = q_from_node(node)
    raw = provider.solve(q)
    frequencies = tuple(float(x) for x in raw.frequencies)
    vectors = tuple(np.asarray(x, dtype=np.complex128) for x in raw.normalized_vectors)
    if len(frequencies) != NUM_BANDS or len(vectors) != NUM_BANDS or not all(math.isfinite(x) for x in frequencies) or any(not np.all(np.isfinite(v)) for v in vectors):
        counters["solver_failures"] += 1
        raise RuntimeError(f"invalid six-band snapshot at node {node}")
    value = {
        "node": node_id(node),
        "public_q": list(q),
        "mpb_fractional_q": [float(x) for x in preflight.public_q_to_mpb(q)],
        "raw": raw,
        "frequencies": frequencies,
    }
    cache[key] = value
    return value


def plaquette_nodes(center_node):
    x, y = int(center_node[0]), int(center_node[1])
    return ((x - 1, y - 1), (x + 1, y - 1), (x + 1, y + 1), (x - 1, y + 1))


def evaluate_plaquette(center_node, center_q, band, resolution, provider, preflight, cache, counters):
    corners = plaquette_nodes(center_node)
    corner_values = [solve_node(provider, preflight, node, resolution, cache, counters) for node in corners]
    center_value = solve_node(provider, preflight, center_node, resolution, cache, counters)
    profile = []
    for label, value in [(f"corner_{i}", value) for i, value in enumerate(corner_values)] + [("center", center_value)]:
        gap = nearest_external_gap(value["frequencies"], band)
        profile.append({
            "label": label,
            "node": value["node"],
            "public_q": value["public_q"],
            "frequencies": list(value["frequencies"]),
            "external_gap": float(gap),
            "E3_PROFILE": "PASS" if gap >= 0.02 else "FAIL",
        })
    frames = [frame_rank1(value["public_q"], value["raw"], band) for value in corner_values]
    center_frame = frame_rank1(center_value["public_q"], center_value["raw"], band)
    contexts = external_contexts([value["frequencies"] for value in corner_values], band)
    path = qualify_ordered_path(
        tuple(frames), contexts, thresholds=TRANSPORT, closed=True,
        provenance={"source": "E9D R64/R96 local map rank-1 E3", "band": band, "resolution": resolution, "center_node": node_id(center_node)},
    )
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(
        tuple(frames), contexts, thresholds=TRANSPORT,
        provenance={"source": "E9D local map E4A", "band": band, "resolution": resolution},
    )
    spokes = tuple(
        ExternalIsolationContext(
            excluded(value["frequencies"], band),
            excluded(center_value["frequencies"], band),
            {"source": "E9D actual center E4B six-band context", "band": band, "resolution": resolution},
        )
        for value in corner_values
    )
    interior = qualify_plaquette_interior(
        boundary, center_frame, spokes,
        provenance={"source": "E9D local map E4B", "band": band, "resolution": resolution},
    )
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    determinant = None if wilson.determinant is None else complex(wilson.determinant)
    path_ok = path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)
    qualified = bool(
        all(row["E3_PROFILE"] == "PASS" for row in profile)
        and path_ok and wilson.status == WILSON_LOOP_QUALIFIED
        and boundary.is_qualified and interior.is_qualified
        and phase is not None and determinant is not None
        and math.isfinite(phase)
    )
    omega_wilson = None if not qualified else omega_over_a2(float(-phase / (SIDE ** 2)))
    omega_literal = None if not qualified else omega_over_a2(float(-determinant.imag / (SIDE ** 2)))
    return {
        "band": band,
        "resolution": resolution,
        "center_node": node_id(center_node),
        "center_public_q": list(center_q),
        "frequency_at_center": float(center_value["frequencies"][band]),
        "minimum_external_gap": float(min(row["external_gap"] for row in profile)),
        "profile": profile,
        "E3_status": "PASSED" if all(row["E3_PROFILE"] == "PASS" for row in profile) else "FAILED",
        "E4A_status": boundary.status,
        "E4B_status": interior.status,
        "Wilson_status": wilson.status,
        "Omega_over_a2": omega_wilson,
        "Omega_literal_over_a2": omega_literal,
        "qualification_status": "QUALIFIED" if qualified else "NOT_REPORTED",
        "failure_reasons": [] if qualified else [
            reason for reason, failed in (
                ("external_gap", not all(row["E3_PROFILE"] == "PASS" for row in profile)),
                ("ordered_path", not path_ok),
                ("wilson", wilson.status != WILSON_LOOP_QUALIFIED),
                ("boundary", not boundary.is_qualified),
                ("interior", not interior.is_qualified),
                ("finite_estimator", phase is None or determinant is None),
            ) if failed
        ],
    }


def self_checks(contract, preflight, geometry):
    checks = {
        "WORK_ORDER": contract["work_order_id"] == WORK_ORDER,
        "BASE_SANDBOX": contract["base_sandbox_sha"] == "0b9ffafc025b65e282db8066508fc75e7fb9ac27",
        "PHYSICAL_MODEL": geometry["max_roundtrip_error"] <= 1e-12 and abs(geometry["physical_fill_fraction"] - 0.24) <= 1e-12,
        "REAL_SPACE_VERTEX_MAPPING": geometry["orientation"] == "COUNTERCLOCKWISE",
        "PUBLIC_RECIPROCAL_MAPPING": bool(preflight.ready) and preflight.round_trip_residual <= 1e-12,
        "GRID_SIZE": contract["model"]["map_grid"] == [13, 13],
        "GRID_CENTER_COUNT": 13 * 13 == 169,
        "GRID_STEP": math.isclose(contract["model"]["map_grid_step_q"], SIDE, rel_tol=0.0, abs_tol=1e-15),
        "PLAQUETTE_SIDE": math.isclose(contract["model"]["map_plaquette_side_q"], SIDE, rel_tol=0.0, abs_tol=1e-15),
        "GRID_CENTER_IS_KPRIME": q_from_node(KPRIME_NODE) == KPRIME_PUBLIC,
        "NODE_DENOMINATOR": contract["map"]["node_identity_denominator"] == NODE_DENOM,
        "TRS_POINTS_PRECOMMITTED": tuple(tuple(x) for x in contract["trs_control"]["offsets_in_1_72_units"]) == TRS_OFFSETS,
        "R96_POINTS_PRECOMMITTED": tuple(tuple(x) for x in contract["r96_validation"]["offsets_in_1_72_units"]) == R96_OFFSETS,
        "NO_ZERO_FILL": contract["map"]["zero_fill"] is False,
        "NO_INTERPOLATION": contract["map"]["interpolation"] is False,
        "NO_CHERN": all(contract[key] is False for key in ("valley_chern_authorized", "full_bz_chern_authorized", "hbz_integration_authorized")),
        "NO_PARAMETER_SWEEP": "parameter_fitting" in contract["prohibited_scope"],
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9D self-check failed: {checks}")
    return checks


def run(output):
    started = time.monotonic()
    contract_path = ROOT / "audit/e9d/human_reference_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    checks = self_checks(contract, preflight, geometry)
    providers = {
        R64: make_provider(R64, lattice, solver_geometry, background),
        R96: make_provider(R96, lattice, solver_geometry, background),
    }
    cache, counters = {}, {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    map_rows = []
    for i in range(-6, 7):
        for j in range(-6, 7):
            center_node = (KPRIME_NODE[0] + 2 * i, KPRIME_NODE[1] + 2 * j)
            center_q = q_from_node(center_node)
            bands = [
                evaluate_plaquette(center_node, center_q, band, R64, providers[R64], preflight, cache, counters)
                for band in BANDS
            ]
            map_rows.append({
                "grid_i": i,
                "grid_j": j,
                "center_node": node_id(center_node),
                "public_q": list(center_q),
                "offset_from_K_prime": [float(i) * SIDE, float(j) * SIDE],
                "bands": bands,
            })
    trs_rows = []
    for dx, dy in TRS_OFFSETS:
        k_node = (K_NODE[0] + dx, K_NODE[1] + dy)
        kp_node = (KPRIME_NODE[0] - dx, KPRIME_NODE[1] - dy)
        kq, kpq = q_from_node(k_node), q_from_node(kp_node)
        k_bands = [evaluate_plaquette(k_node, kq, band, R64, providers[R64], preflight, cache, counters) for band in BANDS]
        kp_bands = [evaluate_plaquette(kp_node, kpq, band, R64, providers[R64], preflight, cache, counters) for band in BANDS]
        trs_rows.append({"offset_1_72": [dx, dy], "K": k_bands, "K_prime": kp_bands})
    r96_rows = []
    for dx, dy in R96_OFFSETS:
        node = (KPRIME_NODE[0] + dx, KPRIME_NODE[1] + dy)
        q = q_from_node(node)
        r96_rows.append({
            "offset_1_72": [dx, dy],
            "center_node": node_id(node),
            "public_q": list(q),
            "bands": [evaluate_plaquette(node, q, band, R96, providers[R96], preflight, cache, counters) for band in BANDS],
        })
    payload = {
        "schema": "trilatt_e9d_local_berry_distribution_raw_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_json_sha256": file_sha(contract_path),
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
        "map_resolution": R64,
        "map_grid": {"i_min": -6, "i_max": 6, "j_min": -6, "j_max": 6, "step_q": SIDE, "plaquette_side_q": SIDE, "center": list(KPRIME_PUBLIC)},
        "map_rows": map_rows,
        "trs_rows": trs_rows,
        "r96_validation_rows": r96_rows,
        "cache_identity": {
            "geometry_id": GEOMETRY_ID,
            "representation": REPRESENTATION,
            "num_bands": NUM_BANDS,
            "solver_tolerance": SOLVER_TOLERANCE,
            "mesh_size": MESH_SIZE,
            "node_denominator": NODE_DENOM,
            "full_physical_identity": True,
        },
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), **counters},
        "berry_field_map": "BOUNDED_LOCAL_PATCH_ONLY",
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
    }
    Path(output).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = ROOT / "audit/e9d/human_reference_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    geometry = geometry_inputs()
    preflight, _, _, _ = build_inputs(geometry)
    if "--self-check" in sys.argv:
        print(json.dumps(self_checks(contract, preflight, geometry), sort_keys=True))
    else:
        output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else str(ROOT / "audit/e9d/raw_result.json")
        payload = run(output)
        print(json.dumps({"schema": payload["schema"], "calculation_code_git_sha": payload["calculation_code_git_sha"], "telemetry": payload["telemetry"]}, sort_keys=True))

