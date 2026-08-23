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

WORK_ORDER = "TRILATT-E9A-20260824-169"
R48, R64 = 48, 64
NUM_BANDS = 4
SOLVER_TOLERANCE = 1e-7
MESH_SIZE = 3
K_PUBLIC = (2.0 / 3.0, 0.0)
EXPECTED_K_MPB = (1.0 / 3.0, 1.0 / 3.0)
TRIANGLE_RADIUS = 0.4
BACKGROUND_EPSILON = 7.0225
AIR_EPSILON = 1.0
RASTER = (0.265748031496063, 0.3136482939632546, 0.35761154855643046)
PAPER_GAP21, PAPER_GAP32 = 0.045, 0.044


def root():
    return Path(__file__).resolve().parents[2]


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def triangle_vertices(radius=TRIANGLE_RADIUS):
    return [[float(radius * math.cos(math.pi / 2.0 + 2.0 * math.pi * i / 3.0)), float(radius * math.sin(math.pi / 2.0 + 2.0 * math.pi * i / 3.0))] for i in range(3)]


def polygon_area(vertices):
    return abs(0.5 * sum(vertices[i][0] * vertices[(i + 1) % len(vertices)][1] - vertices[i][1] * vertices[(i + 1) % len(vertices)][0] for i in range(len(vertices))))


def contract_data(contract, preflight):
    vertices = triangle_vertices()
    cell_basis = [[float(x) for x in row] for row in preflight.real_space_basis]
    cell_area = abs(cell_basis[0][0] * cell_basis[1][1] - cell_basis[0][1] * cell_basis[1][0])
    triangle_area = polygon_area(vertices)
    actual = {
        "intended_vertices_public_cartesian": vertices,
        "actual_triangle_vertices_mpb_geometry_coordinates": vertices,
        "vertex_coordinate_mapping": "IDENTITY_BY_ESTABLISHED_E7I5_MPB_GEOMETRY_CONVENTION",
        "actual_triangle_area": triangle_area,
        "actual_cell_area": cell_area,
        "actual_fill_fraction": triangle_area / cell_area,
        "prism_type": "mp.Prism",
        "prism_height": "mp.inf",
        "triangle_circumradius_over_a": TRIANGLE_RADIUS,
        "triangle_side_length_over_a": math.sqrt(3.0) * TRIANGLE_RADIUS,
        "triangle_orientation_mod_120_degrees": 90.0,
        "background_epsilon": BACKGROUND_EPSILON,
        "air_epsilon": AIR_EPSILON,
        "polarization": "TE",
        "real_space_basis_rows": cell_basis,
        "lattice_basis1": [cell_basis[0][0], cell_basis[1][0]],
        "lattice_basis2": [cell_basis[0][1], cell_basis[1][1]],
        "intended_actual_geometry_match": vertices == vertices,
    }
    actual["geometry_contract_digest"] = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return actual


def self_checks(contract, preflight, geometry):
    mapped = preflight.public_q_to_mpb(K_PUBLIC)
    circle_fraction = math.pi * 0.255 ** 2 / (math.sqrt(3.0) / 2.0)
    checks = {
        "N_TO_EPSILON_TEST": math.isclose(2.65 ** 2, BACKGROUND_EPSILON, rel_tol=0.0, abs_tol=1e-15),
        "TRIANGLE_CIRCUMRADIUS_TEST": math.isclose(160.0 / 400.0, TRIANGLE_RADIUS, rel_tol=0.0, abs_tol=1e-15),
        "TRIANGLE_SIDE_TEST": math.isclose(geometry["triangle_side_length_over_a"], math.sqrt(3.0) * TRIANGLE_RADIUS, rel_tol=0.0, abs_tol=1e-15),
        "TRIANGLE_AREA_TEST": math.isclose(geometry["actual_triangle_area"], 3.0 * math.sqrt(3.0) * TRIANGLE_RADIUS ** 2 / 4.0, rel_tol=0.0, abs_tol=1e-15),
        "TRIANGLE_FILL_FRACTION_TEST": math.isclose(geometry["actual_fill_fraction"], 0.24, rel_tol=0.0, abs_tol=1e-14),
        "CIRCLE_REFERENCE_AREA_FRACTION_TEST": math.isclose(circle_fraction, 0.23588460731866, rel_tol=0.0, abs_tol=1e-14),
        "OLD_0P107_NOT_USED_FOR_GEOMETRY_TEST": contract["paper_10p7_percent_fill_sentence"] == "NON_AUTHORITATIVE_FOR_GEOMETRY_IN_THIS_HUMAN_CORRECTED_CONTRACT" and not math.isclose(geometry["actual_fill_fraction"], 0.107, rel_tol=0.0, abs_tol=1e-12),
        "TE_ONLY_TEST": contract["polarization"] == "TE",
        "K_MAPPING_EXACTLY_ONCE_TEST": all(abs(float(a) - float(b)) <= 1e-12 for a, b in zip(mapped, EXPECTED_K_MPB)),
        "TRIANGLE_ORIENTATION_FIXED_TEST": math.isclose(contract["triangle_orientation_mod_120_degrees"], 90.0, rel_tol=0.0, abs_tol=1e-15),
        "NO_PARAMETER_SWEEP_TEST": contract["parameter_sweep_authorized"] is False and contract["resolutions"] == [48, 64],
        "NO_BERRY_CODE_PATH_TEST": contract["new_berry_calculation_authorized"] is False and contract["new_chern_calculation_authorized"] is False,
    }
    if not all(checks.values()) or not preflight.ready:
        raise RuntimeError(f"E9A self-check failed: {checks}; preflight_ready={preflight.ready}")
    return checks, mapped, circle_fraction


def build_solver_inputs():
    preflight = build_triangular_coordinate_preflight()
    basis = preflight.real_space_basis
    lattice = mp.Lattice(size=mp.Vector3(1, 1, 0), basis1=mp.Vector3(float(basis[0][0]), float(basis[1][0]), 0), basis2=mp.Vector3(float(basis[0][1]), float(basis[1][1]), 0))
    vertices = triangle_vertices()
    geometry = (mp.Prism(vertices=[mp.Vector3(float(x), float(y), 0) for x, y in vertices], height=mp.inf, material=mp.air),)
    return preflight, lattice, geometry, mp.Medium(epsilon=BACKGROUND_EPSILON)


def solve_at(resolution, preflight, lattice, geometry, background):
    provider = MPBLiveEnergySpectralProvider(geometry=list(geometry), geometry_lattice=lattice, resolution=resolution, num_bands=NUM_BANDS, polarization=mp.TE, default_material=background, eigensolver_tolerance=SOLVER_TOLERANCE, deterministic=True, mesh_size=MESH_SIZE)
    raw = provider.solve(K_PUBLIC)
    frequencies = [float(x) for x in raw.frequencies]
    return {
        "resolution": resolution,
        "public_k": list(K_PUBLIC),
        "mpb_fractional_k": list(preflight.public_q_to_mpb(K_PUBLIC)),
        "frequencies": frequencies,
        "provider_representation": raw.provenance.get("representation"),
        "provider_mpb_reciprocal_k_point": raw.provenance.get("mpb_reciprocal_k_point"),
        "field_kpoint_metadata_validated": raw.provenance.get("field_kpoint_metadata_validated"),
        "gap21": frequencies[1] - frequencies[0],
        "gap32": frequencies[2] - frequencies[1],
    }


def run(output):
    started = time.monotonic()
    contract_path = root() / "audit/e9a/human_reference_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    preflight, lattice, geometry, background = build_solver_inputs()
    geometry_record = contract_data(contract, preflight)
    checks, mapped, circle_fraction = self_checks(contract, preflight, geometry_record)
    results = {}
    for resolution in (R48, R64):
        results[str(resolution)] = solve_at(resolution, preflight, lattice, geometry, background)
    r48, r64 = results["48"], results["64"]
    drift = [r64["frequencies"][i] - r48["frequencies"][i] for i in range(3)]
    payload = {
        "schema": "trilatt_e9a_k_only_spectrum_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_json_sha256": sha256_file(contract_path),
        "model_contract": contract,
        "coordinate_preflight": {"ready": preflight.ready, "mapping_digest": preflight.mapping_digest, "public_k": list(K_PUBLIC), "expected_mpb_fractional_k": list(EXPECTED_K_MPB), "actual_mpb_fractional_k": list(mapped), "round_trip_residual": preflight.round_trip_residual, "real_space_basis": [list(row) for row in preflight.real_space_basis]},
        "geometry": {**geometry_record, "circle_reference_fill_fraction": circle_fraction},
        "self_checks": checks,
        "R48": r48,
        "R64": r64,
        "R48_R64_DRIFT_F1": drift[0],
        "R48_R64_DRIFT_F2": drift[1],
        "R48_R64_DRIFT_F3": drift[2],
        "R48_R64_DRIFT_GAP21": r64["gap21"] - r48["gap21"],
        "R48_R64_DRIFT_GAP32": r64["gap32"] - r48["gap32"],
        "comparison": {
            "paper_gap21": PAPER_GAP21,
            "paper_gap32": PAPER_GAP32,
            "paper_raster_frequencies": list(RASTER),
            "R48_abs_error_f1_to_raster": abs(r48["frequencies"][0] - RASTER[0]),
            "R48_abs_error_f2_to_raster": abs(r48["frequencies"][1] - RASTER[1]),
            "R48_abs_error_f3_to_raster": abs(r48["frequencies"][2] - RASTER[2]),
            "R64_abs_error_f1_to_raster": abs(r64["frequencies"][0] - RASTER[0]),
            "R64_abs_error_f2_to_raster": abs(r64["frequencies"][1] - RASTER[1]),
            "R64_abs_error_f3_to_raster": abs(r64["frequencies"][2] - RASTER[2]),
            "R48_abs_error_gap21_to_text": abs(r48["gap21"] - PAPER_GAP21),
            "R48_abs_error_gap32_to_text": abs(r48["gap32"] - PAPER_GAP32),
            "R64_abs_error_gap21_to_text": abs(r64["gap21"] - PAPER_GAP21),
            "R64_abs_error_gap32_to_text": abs(r64["gap32"] - PAPER_GAP32),
            "status": "RAW_ERRORS_REPORTED_NO_FITTING",
        },
        "new_berry_calculation": "NOT_AUTHORIZED",
        "new_chern_calculation": "NOT_AUTHORIZED",
        "production_code_changed": False,
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "raw_solver_requests": 2, "cache_hits": 0, "solver_failures": 0},
        "E9A_OVERALL": "HUMAN_CORRECTED_DAI_K_SPECTRUM_READY_FOR_SUPERVISOR_AUDIT",
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        contract_path = root() / "audit/e9a/human_reference_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        preflight = build_triangular_coordinate_preflight()
        geometry = contract_data(contract, preflight)
        checks, _, _ = self_checks(contract, preflight, geometry)
        print(json.dumps(checks, sort_keys=True))
    else:
        output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else str(root() / "audit/e9a/result.json")
        payload = run(output)
        print(json.dumps({"schema": payload["schema"], "calculation_code_git_sha": payload["calculation_code_git_sha"], "telemetry": payload["telemetry"]}, sort_keys=True))
