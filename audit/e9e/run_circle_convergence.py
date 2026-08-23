"""E9E.B.C1 single-solve exact-circle convergence confirmation."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import meep as mp

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.e9e.a_rounded_triangle_geometry import BASE_AREA, REAL_BASIS
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.valley_benchmark import build_triangular_coordinate_preflight


WORK_ORDER = "TRILATT-E9E-B-C1-20260824-191"
K_PUBLIC = (2.0 / 3.0, 0.0)
R128 = 128
NUM_BANDS = 6
SOLVER_TOLERANCE = 1.0e-7
MESH_SIZE = 3


def root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_circle_radius() -> float:
    return math.sqrt(BASE_AREA / math.pi)


def make_lattice() -> object:
    return mp.Lattice(
        size=mp.Vector3(1, 1, 0),
        basis1=mp.Vector3(float(REAL_BASIS[0, 0]), float(REAL_BASIS[1, 0]), 0),
        basis2=mp.Vector3(float(REAL_BASIS[0, 1]), float(REAL_BASIS[1, 1]), 0),
    )


def make_provider() -> MPBLiveEnergySpectralProvider:
    lattice = make_lattice()
    geometry = (
        mp.Cylinder(
            radius=exact_circle_radius(),
            height=mp.inf,
            material=mp.air,
        ),
    )
    return MPBLiveEnergySpectralProvider(
        geometry=list(geometry),
        geometry_lattice=lattice,
        resolution=R128,
        num_bands=NUM_BANDS,
        polarization=mp.TE,
        default_material=mp.Medium(epsilon=7.0225),
        eigensolver_tolerance=SOLVER_TOLERANCE,
        deterministic=True,
        mesh_size=MESH_SIZE,
    )


def self_check(contract: dict, contract_path: Path, e9e_b_contract: Path, e9e_b_result: Path) -> dict:
    checks = {
        "WORK_ORDER_BOUND": contract["work_order_id"] == WORK_ORDER,
        "E9E_B_CONTRACT_PRESERVED": file_sha(e9e_b_contract) == contract["preserved_e9e_b_contract_sha256"],
        "E9E_B_RESULT_PRESERVED": file_sha(e9e_b_result) == contract["preserved_e9e_b_result_sha256"],
        "EXACT_CIRCLE_ONLY": contract["new_live_solve"]["representation"] == "IDENTICAL_EXACT_MP_CYLINDER_AS_E9E_B",
        "ONE_NEW_SOLVE": contract["new_live_solve"]["count"] == 1 and contract["new_live_solve"]["resolution"] == 128,
        "NO_R64_RERUN": contract["new_live_solve"]["rerun_r64"] is False,
        "NO_R96_RERUN": contract["new_live_solve"]["rerun_r96"] is False,
        "NO_POLYGON": contract["new_live_solve"]["polygon_solve"] is False,
        "NO_REPLACEMENT_ABSOLUTE_THRESHOLD": contract["convergence_gate"]["replacement_absolute_threshold"] == "FORBIDDEN",
        "NO_BERRY": contract["authorization"]["new_berry_calculation"] is False,
        "NO_CHERN": contract["authorization"]["valley_chern"] is False and contract["authorization"]["full_bz_chern"] is False,
        "NO_PRODUCTION_CODE": contract["authorization"]["production_code_change"] is False,
        "CONTRACT_PATH_EXISTS": contract_path.exists(),
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9E.B.C1 self-check failed: {checks}")
    return checks


def relative_gap(row: dict) -> float:
    f2 = float(row["frequencies"][1])
    f3 = float(row["frequencies"][2])
    return abs(float(row["gap32"])) / ((f2 + f3) / 2.0)


def solve_r128(preflight: object) -> dict:
    provider = make_provider()
    raw = provider.solve(K_PUBLIC)
    frequencies = [float(value) for value in raw.frequencies]
    if len(frequencies) != NUM_BANDS or not all(math.isfinite(value) for value in frequencies):
        raise RuntimeError("R128 exact-circle result is incomplete or non-finite")
    return {
        "case_name": "FR0P5_R128_EXACT_CIRCLE",
        "resolution": R128,
        "geometry": "EXACT_EQUAL_AREA_CIRCLE",
        "radius": exact_circle_radius(),
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
    e9e_b_contract_path = root() / "audit/e9e/b_spectral_embedding_contract.json"
    e9e_b_result_path = root() / "audit/e9e/b_spectral_embedding_result.json"
    e9e_b_contract = json.loads(e9e_b_contract_path.read_text(encoding="utf-8-sig"))
    e9e_b_result = json.loads(e9e_b_result_path.read_text(encoding="utf-8-sig"))
    checks = self_check(contract, contract_path, e9e_b_contract_path, e9e_b_result_path)
    preflight = build_triangular_coordinate_preflight()
    if not preflight.ready:
        raise RuntimeError("E9E.B.C1 coordinate preflight failed")
    new = solve_r128(preflight)
    old64 = e9e_b_result["results"]["FR0P5_R64_EXACT_CIRCLE"]
    old96 = e9e_b_result["results"]["FR0P5_R96_EXACT_CIRCLE"]
    gap64 = float(old64["gap32"])
    gap96 = float(old96["gap32"])
    gap128 = float(new["gap32"])
    rel64 = relative_gap(old64)
    rel96 = relative_gap(old96)
    rel128 = relative_gap(new)
    abs_monotonic = bool(gap64 > gap96 > gap128 >= 0.0)
    rel_monotonic = bool(rel64 > rel96 > rel128 >= 0.0)
    exponent_64_96 = math.log(gap64 / gap96) / math.log(96.0 / 64.0)
    exponent_96_128 = math.log(gap96 / gap128) / math.log(128.0 / 96.0)
    payload = {
        "schema": "trilatt_e9e_b_c1_exact_circle_convergence_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_sha256": file_sha(contract_path),
        "preserved_e9e_b_contract_sha256": file_sha(e9e_b_contract_path),
        "preserved_e9e_b_result_sha256": file_sha(e9e_b_result_path),
        "contract": contract,
        "self_checks": checks,
        "new_mpb_solver_requests": 1,
        "new_berry_calculation": "NONE",
        "geometry": "EXACT_EQUAL_AREA_CIRCLE",
        "resolutions_used": ["64_EXISTING", "96_EXISTING", "128_NEW"],
        "existing_e9e_b_values_reused_without_rerun": True,
        "existing_e9e_b_work_order": e9e_b_result["work_order_id"],
        "existing_e9e_b_authoritative_code_sha": e9e_b_result["calculation_code_git_sha"],
        "existing_e9e_b_result_sha": file_sha(e9e_b_result_path),
        "coordinate_preflight": {
            "ready": bool(preflight.ready),
            "public_k": list(K_PUBLIC),
            "mpb_fractional_k": [float(value) for value in preflight.public_q_to_mpb(K_PUBLIC)],
            "round_trip_residual": float(preflight.round_trip_residual),
            "mapping_digest": preflight.mapping_digest,
            "real_space_coordinate_label": "r_not_q",
            "conversion_count": "EXACTLY_ONCE",
        },
        "gap32_r64": gap64,
        "gap32_r96": gap96,
        "gap32_r128": gap128,
        "relative_gap_r64": rel64,
        "relative_gap_r96": rel96,
        "relative_gap_r128": rel128,
        "r128_result": new,
        "absolute_gap_monotonic_decrease": abs_monotonic,
        "relative_gap_monotonic_decrease": rel_monotonic,
        "effective_convergence_exponent_64_96": exponent_64_96,
        "effective_convergence_exponent_96_128": exponent_96_128,
        "original_absolute_1e6_gate": "HISTORICAL_FAILED_UNCHANGED",
        "fr0p5_degeneracy_trend": (
            "REPRODUCED_AS_CONVERGENT_NUMERICAL_SYMMETRY_RESIDUAL"
            if abs_monotonic and rel_monotonic
            else "UNRESOLVED_FAIL_CLOSED"
        ),
        "fr0p5_rank1_berry_at_exact_k": "UNDEFINED_NOT_AUTHORIZED",
        "fr0_replay": "VALIDATED_FROM_E9E_B",
        "fr0p4_gap21_trend": "VALIDATED_FROM_E9E_B",
        "fr0p4_gap32_trend": "VALIDATED_FROM_E9E_B",
        "valley_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "production_code_changed": False,
        "main_push": False,
        "telemetry": {
            "wall_time_seconds": time.monotonic() - started,
            "new_solver_requests": 1,
            "solver_failures": 0,
        },
        "E9E_B_C1_OVERALL": (
            "EXACT_CIRCLE_DEGENERACY_CONVERGENCE_READY_FOR_SUPERVISOR_DECISION"
            if abs_monotonic and rel_monotonic
            else "FAIL_CLOSED"
        ),
    }
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9e/c1_circle_convergence_contract.json"
    output = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else root() / "audit/e9e/c1_circle_convergence_result.json"
    if "--self-check" in sys.argv:
        contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
        checks = self_check(
            contract,
            contract_path,
            root() / "audit/e9e/b_spectral_embedding_contract.json",
            root() / "audit/e9e/b_spectral_embedding_result.json",
        )
        print(json.dumps(checks, sort_keys=True))
    else:
        payload = run(output, contract_path)
        print(json.dumps({"schema": payload["schema"], "overall": payload["E9E_B_C1_OVERALL"], "telemetry": payload["telemetry"]}, sort_keys=True))

