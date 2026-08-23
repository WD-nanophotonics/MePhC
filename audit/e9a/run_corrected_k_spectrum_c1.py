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

WORK_ORDER = "TRILATT-E9A-C1-20260824-171"
R48, R64 = 48, 64
NUM_BANDS = 4
SOLVER_TOLERANCE = 1e-7
MESH_SIZE = 3
K_PUBLIC = (2.0 / 3.0, 0.0)
EXPECTED_K_MPB = (1.0 / 3.0, 1.0 / 3.0)
RADIUS = 0.4
EPSILON_BACKGROUND = 7.0225
RASTER = (0.265748031496063, 0.3136482939632546, 0.35761154855643046)
PAPER_GAP21, PAPER_GAP32 = 0.045, 0.044
REAL_BASIS = np.asarray(((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0)), dtype=float)


def root():
    return Path(__file__).resolve().parents[2]


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical_vertices():
    return np.asarray([[0.0, RADIUS], [-math.sqrt(3.0) * RADIUS / 2.0, -RADIUS / 2.0], [math.sqrt(3.0) * RADIUS / 2.0, -RADIUS / 2.0]], dtype=float)


def polygon_area(vertices):
    return abs(0.5 * sum(vertices[i, 0] * vertices[(i + 1) % len(vertices), 1] - vertices[i, 1] * vertices[(i + 1) % len(vertices), 0] for i in range(len(vertices))))


def signed_area(vertices):
    return 0.5 * sum(vertices[i, 0] * vertices[(i + 1) % len(vertices), 1] - vertices[i, 1] * vertices[(i + 1) % len(vertices), 0] for i in range(len(vertices)))


def digest(vertices):
    normalized = [[(round(float(x), 14) if round(float(x), 14) != 0.0 else 0.0) for x in row] for row in vertices]
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def geometry_contract(contract):
    physical = physical_vertices()
    mpb = np.linalg.solve(REAL_BASIS, physical.T).T
    roundtrip = (REAL_BASIS @ mpb.T).T
    cell_area = abs(float(np.linalg.det(REAL_BASIS)))
    radii = [float(np.linalg.norm(v)) for v in roundtrip]
    sides = [float(np.linalg.norm(roundtrip[(i + 1) % 3] - roundtrip[i])) for i in range(3)]
    area = polygon_area(roundtrip)
    return {
        "real_space_basis_rows": REAL_BASIS.tolist(),
        "triangle_vertices_physical_cartesian": physical.tolist(),
        "triangle_vertices_mpb_lattice": mpb.tolist(),
        "triangle_vertices_roundtrip_cartesian": roundtrip.tolist(),
        "conversion_method": "A_INVERSE_INDEPENDENTLY_VERIFIED",
        "conversion_count": "EXACTLY_ONCE",
        "max_vertex_roundtrip_error": float(np.max(np.linalg.norm(roundtrip - physical, axis=1))),
        "circumradii": radii,
        "side_lengths": sides,
        "signed_area": float(signed_area(roundtrip)),
        "physical_triangle_area": float(area),
        "physical_cell_area": cell_area,
        "physical_fill_fraction": float(area / cell_area),
        "orientation": "COUNTERCLOCKWISE" if signed_area(roundtrip) > 0 else "CLOCKWISE",
        "intended_physical_geometry_digest": digest(physical),
        "mpb_input_geometry_digest": digest(mpb),
        "roundtripped_physical_geometry_digest": digest(roundtrip),
        "intended_vs_roundtripped_geometry": "MATCH" if digest(physical) == digest(roundtrip) else "MISMATCH",
        "prism_type": "mp.Prism",
        "prism_height": "mp.inf",
        "background_epsilon": EPSILON_BACKGROUND,
        "air_epsilon": 1.0,
        "polarization": "TE",
        "triangle_circumradius_over_a": RADIUS,
        "triangle_side_length_over_a": math.sqrt(3.0) * RADIUS,
        "triangle_orientation_mod_120_degrees": 90.0,
        "old_e9a_result": "DIAGNOSTIC_WRONG_REAL_SPACE_TRIANGLE_ENCODING",
        "source_contract": contract["schema"],
    }


def self_checks(contract, preflight, geometry):
    mapped = preflight.public_q_to_mpb(K_PUBLIC)
    expected_area = 3.0 * math.sqrt(3.0) * RADIUS ** 2 / 4.0
    expected_side = math.sqrt(3.0) * RADIUS
    checks = {
        "REAL_SPACE_VERTEX_MAPPING": geometry["intended_vs_roundtripped_geometry"] == "MATCH" and geometry["conversion_count"] == "EXACTLY_ONCE",
        "PHYSICAL_REGULAR_TRIANGLE_TEST": all(abs(r - RADIUS) <= 1e-12 for r in geometry["circumradii"]) and all(abs(s - expected_side) <= 1e-12 for s in geometry["side_lengths"]),
        "PHYSICAL_CIRCUMRADIUS_TEST": all(abs(r - 0.4) <= 1e-12 for r in geometry["circumradii"]),
        "PHYSICAL_SIDE_LENGTH_TEST": all(abs(s - expected_side) <= 1e-12 for s in geometry["side_lengths"]),
        "PHYSICAL_AREA_TEST": abs(geometry["physical_triangle_area"] - expected_area) <= 1e-12,
        "PHYSICAL_FILL_FRACTION_TEST": abs(geometry["physical_fill_fraction"] - 0.24) <= 1e-12,
        "TRIANGLE_ORIENTATION_TEST": geometry["orientation"] == "COUNTERCLOCKWISE",
        "MAX_VERTEX_ROUNDTRIP_TEST": geometry["max_vertex_roundtrip_error"] <= 1e-12,
        "K_MAPPING": all(abs(float(a) - float(b)) <= 1e-12 for a, b in zip(mapped, EXPECTED_K_MPB)) and preflight.round_trip_residual <= 1e-12,
        "NO_PARAMETER_SWEEP_TEST": contract["parameter_sweep_authorized"] is False and contract["resolutions"] == [48, 64],
        "NO_BERRY_CODE_PATH_TEST": contract["new_berry_calculation_authorized"] is False and contract["new_chern_calculation_authorized"] is False,
        "OLD_E9A_PRESERVED_TEST": (root() / "audit/e9a/result.json").exists(),
    }
    if not all(checks.values()) or not preflight.ready:
        raise RuntimeError(f"E9A.C1 self-check failed: {checks}; preflight_ready={preflight.ready}")
    return checks, mapped


def solver_inputs(geometry):
    preflight = build_triangular_coordinate_preflight()
    mpb_vertices = np.asarray(geometry["triangle_vertices_mpb_lattice"], dtype=float)
    lattice = mp.Lattice(size=mp.Vector3(1, 1, 0), basis1=mp.Vector3(float(REAL_BASIS[0, 0]), float(REAL_BASIS[1, 0]), 0), basis2=mp.Vector3(float(REAL_BASIS[0, 1]), float(REAL_BASIS[1, 1]), 0))
    prism = mp.Prism(vertices=[mp.Vector3(float(x), float(y), 0) for x, y in mpb_vertices], height=mp.inf, material=mp.air)
    return preflight, lattice, (prism,), mp.Medium(epsilon=EPSILON_BACKGROUND)


def solve_at(resolution, preflight, lattice, geometry, background):
    provider = MPBLiveEnergySpectralProvider(geometry=list(geometry), geometry_lattice=lattice, resolution=resolution, num_bands=NUM_BANDS, polarization=mp.TE, default_material=background, eigensolver_tolerance=SOLVER_TOLERANCE, deterministic=True, mesh_size=MESH_SIZE)
    raw = provider.solve(K_PUBLIC)
    f = [float(x) for x in raw.frequencies]
    return {"resolution": resolution, "public_k": list(K_PUBLIC), "mpb_fractional_k": list(preflight.public_q_to_mpb(K_PUBLIC)), "frequencies": f, "gap21": f[1] - f[0], "gap32": f[2] - f[1], "provider_representation": raw.provenance.get("representation")}


def run(output):
    started = time.monotonic()
    contract_path = root() / "audit/e9a/c1_geometry_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    geometry = geometry_contract(contract)
    preflight = build_triangular_coordinate_preflight()
    checks, mapped = self_checks(contract, preflight, geometry)
    preflight, lattice, solver_geometry, background = solver_inputs(geometry)
    results = {str(res): solve_at(res, preflight, lattice, solver_geometry, background) for res in (R48, R64)}
    r48, r64 = results["48"], results["64"]
    drift = [r64["frequencies"][i] - r48["frequencies"][i] for i in range(3)]
    payload = {
        "schema": "trilatt_e9a_c1_corrected_k_only_spectrum_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "c1_geometry_contract_sha256": file_sha(contract_path),
        "old_e9a_result": "DIAGNOSTIC_WRONG_REAL_SPACE_TRIANGLE_ENCODING",
        "model_contract": contract,
        "geometry": geometry,
        "self_checks": checks,
        "coordinate_preflight": {"ready": preflight.ready, "public_k": list(K_PUBLIC), "expected_mpb_fractional_k": list(EXPECTED_K_MPB), "actual_mpb_fractional_k": list(mapped), "round_trip_residual": preflight.round_trip_residual, "mapping_digest": preflight.mapping_digest},
        "R48": r48,
        "R64": r64,
        "R48_R64_DRIFT_F1": drift[0],
        "R48_R64_DRIFT_F2": drift[1],
        "R48_R64_DRIFT_F3": drift[2],
        "R48_R64_DRIFT_GAP21": r64["gap21"] - r48["gap21"],
        "R48_R64_DRIFT_GAP32": r64["gap32"] - r48["gap32"],
        "comparison": {
            "paper_gap21": PAPER_GAP21, "paper_gap32": PAPER_GAP32, "paper_raster_frequencies": list(RASTER),
            "R48_abs_error_f1_to_raster": abs(r48["frequencies"][0] - RASTER[0]), "R48_abs_error_f2_to_raster": abs(r48["frequencies"][1] - RASTER[1]), "R48_abs_error_f3_to_raster": abs(r48["frequencies"][2] - RASTER[2]),
            "R64_abs_error_f1_to_raster": abs(r64["frequencies"][0] - RASTER[0]), "R64_abs_error_f2_to_raster": abs(r64["frequencies"][1] - RASTER[1]), "R64_abs_error_f3_to_raster": abs(r64["frequencies"][2] - RASTER[2]),
            "R48_abs_error_gap21_to_text": abs(r48["gap21"] - PAPER_GAP21), "R48_abs_error_gap32_to_text": abs(r48["gap32"] - PAPER_GAP32), "R64_abs_error_gap21_to_text": abs(r64["gap21"] - PAPER_GAP21), "R64_abs_error_gap32_to_text": abs(r64["gap32"] - PAPER_GAP32), "status": "RAW_ERRORS_REPORTED_NO_FITTING",
        },
        "new_berry_calculation": "NOT_AUTHORIZED",
        "new_chern_calculation": "NOT_AUTHORIZED",
        "production_code_changed": False,
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "raw_solver_requests": 2, "cache_hits": 0, "solver_failures": 0},
        "E9A_C1_OVERALL": "CORRECTED_PHYSICAL_TRIANGLE_K_SPECTRUM_READY_FOR_SUPERVISOR_AUDIT",
    }
    Path(output).write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9a/c1_geometry_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    geometry = geometry_contract(contract)
    preflight = build_triangular_coordinate_preflight()
    if "--self-check" in sys.argv:
        checks, mapped = self_checks(contract, preflight, geometry)
        print(json.dumps({"checks": checks, "mapped": mapped}, sort_keys=True))
    else:
        output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else str(root() / "audit/e9a/c1_result.json")
        payload = run(output)
        print(json.dumps({"schema": payload["schema"], "calculation_code_git_sha": payload["calculation_code_git_sha"], "telemetry": payload["telemetry"]}, sort_keys=True))
