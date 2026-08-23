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
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.valley_benchmark import build_triangular_coordinate_preflight

WORK_ORDER = "TRILATT-E9B-20260824-173"
R64, R96 = 64, 96
NUM_BANDS = 4
SOLVER_TOLERANCE = 1e-7
MESH_SIZE = 3
GAMMA = np.asarray((0.0, 0.0), dtype=float)
K = np.asarray((2.0 / 3.0, 0.0), dtype=float)
M = np.asarray((0.5, math.sqrt(3.0) / 6.0), dtype=float)
EXPECTED_K_MPB = (1.0 / 3.0, 1.0 / 3.0)
RADIUS = 0.4
EPSILON_BACKGROUND = 7.0225
REAL_BASIS = np.asarray(((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0)), dtype=float)
C1_K = np.asarray((0.26833164396586207, 0.3134784445238986, 0.3563287763970286, 0.5644651267329948), dtype=float)


def root():
    return Path(__file__).resolve().parents[2]


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical_vertices():
    return np.asarray([[0.0, RADIUS], [-math.sqrt(3.0) * RADIUS / 2.0, -RADIUS / 2.0], [math.sqrt(3.0) * RADIUS / 2.0, -RADIUS / 2.0]], dtype=float)


def polygon_area(vertices):
    return abs(0.5 * sum(vertices[i, 0] * vertices[(i + 1) % len(vertices), 1] - vertices[i, 1] * vertices[(i + 1) % len(vertices), 0] for i in range(len(vertices))))


def geometry_inputs():
    physical = physical_vertices()
    mpb = np.linalg.solve(REAL_BASIS, physical.T).T
    roundtrip = (REAL_BASIS @ mpb.T).T
    return {
        "physical_vertices": physical,
        "mpb_vertices": mpb,
        "roundtrip_vertices": roundtrip,
        "max_roundtrip_error": float(np.max(np.linalg.norm(roundtrip - physical, axis=1))),
        "physical_area": float(polygon_area(roundtrip)),
        "cell_area": abs(float(np.linalg.det(REAL_BASIS))),
    }


def build_inputs(geometry):
    preflight = build_triangular_coordinate_preflight()
    lattice = mp.Lattice(size=mp.Vector3(1, 1, 0), basis1=mp.Vector3(float(REAL_BASIS[0, 0]), float(REAL_BASIS[1, 0]), 0), basis2=mp.Vector3(float(REAL_BASIS[0, 1]), float(REAL_BASIS[1, 1]), 0))
    prism = mp.Prism(vertices=[mp.Vector3(float(x), float(y), 0) for x, y in geometry["mpb_vertices"]], height=mp.inf, material=mp.air)
    return preflight, lattice, (prism,), mp.Medium(epsilon=EPSILON_BACKGROUND)


def path_points(n_per_segment=36):
    segments = (("GAMMA_TO_K", GAMMA, K), ("K_TO_M", K, M), ("M_TO_GAMMA", M, GAMMA))
    rows = []
    distance = 0.0
    previous = None
    for segment, (name, start, end) in enumerate(segments):
        for i in range(n_per_segment + 1):
            if segment > 0 and i == 0:
                continue
            point = start + (end - start) * (i / n_per_segment)
            if previous is not None:
                distance += float(np.linalg.norm(point - previous))
            rows.append({"path_index": len(rows), "segment": name, "segment_index": i, "path_distance": distance, "public_q": point.tolist()})
            previous = point
    return rows


def self_checks(contract, preflight, geometry, points):
    mapped = preflight.public_q_to_mpb(K)
    checks = {
        "E9A_C1_R64_K_CONTRACT_BOUND": contract["e9a_c1_evidence_sha"] == "c11438bcbac29abbf7f615c048e252dd835a902b",
        "PHYSICAL_VERTEX_MAPPING_PRESERVED": geometry["max_roundtrip_error"] <= 1e-12,
        "PHYSICAL_TRIANGLE_FILL_FRACTION": abs(geometry["physical_area"] / geometry["cell_area"] - 0.24) <= 1e-12,
        "K_MAPPING": all(abs(float(a) - float(b)) <= 1e-12 for a, b in zip(mapped, EXPECTED_K_MPB)) and preflight.round_trip_residual <= 1e-12,
        "PATH_POINT_COUNT": len(points) == 109,
        "PATH_ENDPOINTS": np.allclose(points[0]["public_q"], GAMMA, atol=1e-15) and np.allclose(points[36]["public_q"], K, atol=1e-15) and np.allclose(points[72]["public_q"], M, atol=1e-15) and np.allclose(points[-1]["public_q"], GAMMA, atol=1e-15),
        "N_PER_SEGMENT": contract["n_per_segment"] == 36,
        "NO_BERRY_PATH": contract["new_berry_calculation_authorized"] is False and contract["new_wilson_calculation_authorized"] is False and contract["new_chern_calculation_authorized"] is False,
        "NO_PARAMETER_SWEEP": contract["parameter_sweep_authorized"] is False,
    }
    if not all(checks.values()) or not preflight.ready:
        raise RuntimeError(f"E9B self-check failed: {checks}; preflight_ready={preflight.ready}")
    return checks, mapped


def make_provider(resolution, lattice, geometry, background):
    return MPBLiveEnergySpectralProvider(geometry=list(geometry), geometry_lattice=lattice, resolution=resolution, num_bands=NUM_BANDS, polarization=mp.TE, default_material=background, eigensolver_tolerance=SOLVER_TOLERANCE, deterministic=True, mesh_size=MESH_SIZE)


def solve(provider, preflight, public_q):
    raw = provider.solve(tuple(float(x) for x in public_q))
    frequencies = [float(x) for x in raw.frequencies]
    return {"public_q": [float(x) for x in public_q], "mpb_fractional_q": list(preflight.public_q_to_mpb(public_q)), "frequencies": frequencies}


def run(output):
    started = time.monotonic()
    contract_path = root() / "audit/e9b/human_reference_path_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    points = path_points(contract["n_per_segment"])
    checks, mapped = self_checks(contract, preflight, geometry, points)
    provider64 = make_provider(R64, lattice, solver_geometry, background)
    path = []
    for point in points:
        row = dict(point)
        row.update(solve(provider64, preflight, point["public_q"]))
        path.append(row)
    anchors64 = {"GAMMA": path[0], "K": path[36], "M": path[72]}
    provider96 = make_provider(R96, lattice, solver_geometry, background)
    anchors96 = {name: solve(provider96, preflight, q) for name, q in (("GAMMA", GAMMA), ("K", K), ("M", M))}
    k_drift = [anchors96["K"]["frequencies"][i] - anchors64["K"]["frequencies"][i] for i in range(3)]
    k_replay = bool(np.allclose(anchors64["K"]["frequencies"], C1_K, rtol=0.0, atol=1e-12))
    payload = {
        "schema": "trilatt_e9b_gamma_k_m_gamma_path_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "path_contract_sha256": sha(contract_path),
        "contract": contract,
        "geometry": {"physical_vertices": geometry["physical_vertices"].tolist(), "mpb_vertices": geometry["mpb_vertices"].tolist(), "roundtrip_vertices": geometry["roundtrip_vertices"].tolist(), "max_roundtrip_error": geometry["max_roundtrip_error"], "physical_area": geometry["physical_area"], "cell_area": geometry["cell_area"], "physical_fill_fraction": geometry["physical_area"] / geometry["cell_area"]},
        "self_checks": checks,
        "coordinate_preflight": {"ready": preflight.ready, "public_k": list(K), "expected_mpb_k": list(EXPECTED_K_MPB), "actual_mpb_k": list(mapped), "round_trip_residual": preflight.round_trip_residual, "mapping_digest": preflight.mapping_digest},
        "R64_path": path,
        "R64_GAMMA_FREQUENCIES": anchors64["GAMMA"]["frequencies"],
        "R64_K_FREQUENCIES": anchors64["K"]["frequencies"],
        "R64_M_FREQUENCIES": anchors64["M"]["frequencies"],
        "R96_GAMMA_FREQUENCIES": anchors96["GAMMA"]["frequencies"],
        "R96_K_FREQUENCIES": anchors96["K"]["frequencies"],
        "R96_M_FREQUENCIES": anchors96["M"]["frequencies"],
        "E9A_C1_R64_K_REPLAY": "PASSED" if k_replay else "FAILED",
        "R64_R96_K_DRIFT_F1": k_drift[0],
        "R64_R96_K_DRIFT_F2": k_drift[1],
        "R64_R96_K_DRIFT_F3": k_drift[2],
        "new_berry_calculation": "NOT_AUTHORIZED",
        "new_wilson_calculation": "NOT_AUTHORIZED",
        "new_chern_calculation": "NOT_AUTHORIZED",
        "production_code_changed": False,
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "r64_solver_requests": len(path), "r96_anchor_solver_requests": 3, "cache_hits": 0, "solver_failures": 0},
        "E9B_OVERALL": "CORRECTED_DAI_GAMMA_K_M_GAMMA_BAND_PATH_READY_FOR_SUPERVISOR_AUDIT",
    }
    Path(output).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9b/human_reference_path_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    geometry = geometry_inputs()
    preflight = build_triangular_coordinate_preflight()
    points = path_points(contract["n_per_segment"])
    if "--self-check" in sys.argv:
        checks, mapped = self_checks(contract, preflight, geometry, points)
        print(json.dumps({"checks": checks, "mapped": mapped, "path_point_count": len(points)}, sort_keys=True))
    else:
        output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else str(root() / "audit/e9b/result.json")
        payload = run(output)
        print(json.dumps({"schema": payload["schema"], "calculation_code_git_sha": payload["calculation_code_git_sha"], "telemetry": payload["telemetry"]}, sort_keys=True))
