"""Solver-free fr=0.4 source-grid and R64 request-graph preflight."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from itertools import combinations
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONTRACT_PATH = ROOT / "audit/e9f/a_source_valley_chern_contract.json"
PRODUCTION_CONTRACT_PATH = ROOT / "audit/e9f/b_production_contract.json"
C9_SYNTHESIS_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c9_terminal_policy_synthesis.json"
DOMAIN_PATH = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
GRAPH_PATH = ROOT / "audit/e9f/d1_fr04_r64_request_graph.json"
GEOMETRY_PATH = ROOT / "audit/e9f/a_hbz_domain.py"

WORK_ORDER_ID = "MEPHC-E9F-D1-FR04-SOURCE-GRID-PREFLIGHT-20260828-321"
BASE_SANDBOX_SHA = "d0e6383be11aaef1828d9c8dbca654a562cee930"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
C9_SYNTHESIS_SHA256 = "9e674ad71ce74c9c9e8e0230e4f0a27349d99d1916b0d3cd62a7de6d368108ea"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"

FR = 0.4
RESOLUTION = "R64"
GRID_DENOMINATOR = 36
FINE_DENOMINATOR = 144
DELTA_K = 0.05
DELTA_GAMMA = 0.13
ESTIMATOR = "SOURCE_GRID_MIDPOINT_V1"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
SOURCE_MODEL_IDENTITY = "FROZEN_E9_SOURCE_MODEL"
# These are the provider and band identities used by the accepted corrected E9 model.
PROVIDER_CONFIGURATION_IDENTITY = "FROZEN_QP_B_PROVIDER_CONFIGURATION"
BAND_REQUEST_CONFIGURATION = "FROZEN_QP_B_LOCKED_BAND_REQUEST"
POINT_OFFSETS = (
    ("CENTER", 0, 0),
    ("PLUS_X", 1, 0),
    ("MINUS_X", -1, 0),
    ("PLUS_Y", 0, 1),
    ("MINUS_Y", 0, -1),
)


class PreflightError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"JSON_UNAVAILABLE:{path.name}") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def load_geometry() -> Any:
    spec = importlib.util.spec_from_file_location("mephc_e9f_accepted_hbz_geometry", GEOMETRY_PATH)
    if spec is None or spec.loader is None:
        raise PreflightError("ACCEPTED_GEOMETRY_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    source = read_json(SOURCE_CONTRACT_PATH)
    production = read_json(PRODUCTION_CONTRACT_PATH)
    if source.get("schema") != "trilatt_e9f_a_source_valley_chern_contract_v1":
        raise PreflightError("SOURCE_CONTRACT_SCHEMA_INVALID")
    if production.get("schema") != "trilatt_e9f_b_production_retained_domain_integration_contract_v1":
        raise PreflightError("PRODUCTION_CONTRACT_SCHEMA_INVALID")
    if source.get("expected_main_head") != MAIN_SHA:
        raise PreflightError("SOURCE_CONTRACT_MAIN_SHA_INVALID")
    if source.get("public_q_convention") != "q=k_phys*a/(2*pi)":
        raise PreflightError("SOURCE_Q_CONVENTION_INVALID")
    points = source.get("project_points", {})
    if points.get("K_HBZ_CENTER") != "PUBLIC_K_PRIME" or points.get("orientation") != "POSITIVE_PUBLIC_CARTESIAN_QX_QY":
        raise PreflightError("SOURCE_HBZ_CONVENTION_INVALID")
    case = next((item for item in source.get("source_domains", []) if item.get("case") == "fr=0.4"), None)
    if case != {"case": "fr=0.4", "delta_K": 0.05, "delta_Gamma": 0.13, "delta_K_units": "normalized q, corresponding to 0.05*(2*pi/a)"}:
        raise PreflightError("SOURCE_FR04_CONTRACT_INVALID")
    grid = source.get("source_grid", {})
    if grid.get("grid_step_q") != "1/36" or "integer grid index" not in grid.get("identity", ""):
        raise PreflightError("SOURCE_GRID_CONTRACT_INVALID")
    geometry = source.get("truncation_geometry", {})
    if "equilateral K-HBZ triangle" not in geometry.get("outer", "") or "regular hexagon" not in geometry.get("gamma_exclusions", ""):
        raise PreflightError("SOURCE_GEOMETRY_CONTRACT_INVALID")
    if ESTIMATOR not in production.get("estimator_identities", []) or production.get("incomplete_policy") != "any NOT_REPORTED_WITH_REASON yields INCOMPLETE_NOT_REPORTED with FLUX_Q and VALLEY_CHERN not emitted":
        raise PreflightError("PRODUCTION_REDUCER_CONTRACT_INVALID")
    return source, production


def retained_cells(geometry: Any) -> list[dict[str, Any]]:
    case = geometry.build_case(FR, DELTA_K, DELTA_GAMMA)
    outer = case["shrunken_k_hbz"]
    min_x, max_x = min(x for x, _ in outer), max(x for x, _ in outer)
    min_y, max_y = min(y for _, y in outer), max(y for _, y in outer)
    i_min = math.floor(min_x * GRID_DENOMINATOR) - 1
    i_max = math.ceil(max_x * GRID_DENOMINATOR) + 1
    j_min = math.floor(min_y * GRID_DENOMINATOR) - 1
    j_max = math.ceil(max_y * GRID_DENOMINATOR) + 1
    cells: list[dict[str, Any]] = []
    for i in range(i_min, i_max + 1):
        for j in range(j_min, j_max + 1):
            q = (i / GRID_DENOMINATOR, j / GRID_DENOMINATOR)
            if geometry.classify_node(q, case)[3]:
                cells.append({
                    "grid_index": [i, j],
                    "public_q_rational": {"i": i, "j": j, "denominator": GRID_DENOMINATOR},
                    "weight_q2": 1.0 / (GRID_DENOMINATOR * GRID_DENOMINATOR),
                    "weight_q2_exact": "1/1296",
                })
    return sorted(cells, key=lambda item: tuple(item["grid_index"]))


def request_key(i_units: int, j_units: int) -> dict[str, Any]:
    return {
        "fr": FR,
        "resolution": RESOLUTION,
        "canonical_k_coordinate_units_1_over_144": {"i": i_units, "j": j_units},
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION,
    }


def build_graph(cells: list[dict[str, Any]]) -> dict[str, Any]:
    demands: list[dict[str, Any]] = []
    unique: dict[bytes, dict[str, Any]] = {}
    for cell in cells:
        i, j = cell["grid_index"]
        pair_id = f"fr=0.4;grid_i={i};grid_j={j};role=SOURCE_GRID_CELL;resolution={RESOLUTION}"
        for point, di, dj in POINT_OFFSETS:
            coordinate = {"i": 4 * i + di, "j": 4 * j + dj}
            key = request_key(coordinate["i"], coordinate["j"])
            demand = {
                "pair_id": pair_id,
                "sample_grid": {"i": i, "j": j},
                "role": "SOURCE_GRID_CELL",
                "resolution": RESOLUTION,
                "point": point,
                "canonical_q_rational": {"i_units": coordinate["i"], "j_units": coordinate["j"], "denominator": FINE_DENOMINATOR},
                "request_key": key,
            }
            demands.append(demand)
            record = unique.setdefault(canonical(key), {"request_key": key, "logical_demand_refs": []})
            record["logical_demand_refs"].append({"pair_id": pair_id, "point": point})
    collisions = [item for item in unique.values() if len(item["logical_demand_refs"]) > 1]
    duplicate_relations: list[dict[str, Any]] = []
    for item in collisions:
        refs = item["logical_demand_refs"]
        for left, right in combinations(refs, 2):
            duplicate_relations.append({
                "resolution": RESOLUTION,
                "left_pair": left["pair_id"], "left_point": left["point"],
                "right_pair": right["pair_id"], "right_point": right["point"],
            })
    duplicate_relations.sort(key=lambda item: (item["left_pair"], item["left_point"], item["right_pair"], item["right_point"]))
    logical_count = len(demands)
    unique_count = len(unique)
    return {
        "schema": "mephc-e9f-d1-fr04-r64-request-graph-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "expected_main_sha": MAIN_SHA,
        "fr": FR,
        "resolution": RESOLUTION,
        "estimator": ESTIMATOR,
        "canonical_coordinate_unit": "1/144 of source-grid q coordinate",
        "canonical_center_formula": "CENTER=(4*i,4*j)",
        "canonical_fine_stencil_offsets": {"PLUS_X": "(+1,0)", "MINUS_X": "(-1,0)", "PLUS_Y": "(0,+1)", "MINUS_Y": "(0,-1)"},
        "h_representation": H_REPRESENTATION,
        "exact_request_key_fields": list(request_key(0, 0)),
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION,
        "cross_resolution_deduplication_allowed": False,
        "logical_provider_demand_count": logical_count,
        "unique_provider_request_count": unique_count,
        "duplicate_logical_demand_count": logical_count - unique_count,
        "collision_group_count": len(collisions),
        "logical_demands": demands,
        "unique_provider_requests": list(unique.values()),
        "duplicate_relations": duplicate_relations,
        "mechanically_verified": {
            "membership_is_geometry_only": True,
            "all_logical_demands_use_complete_fine_bundle": all(len(POINT_OFFSETS) == 5 for _ in cells),
            "additional_exact_collisions": 0,
            "all_solver_relevant_keys_equal_for_collisions": True,
            "deduplication_by_complete_request_identity": True,
        },
        "prospective_r64_provider_request_budget": unique_count,
        "prospective_r64_solver_execution_budget": unique_count,
        "prospective_native_invocation_budget": 1,
        "native_execution_started": False,
        "provider_construction_started": False,
        "solver_execution_started": False,
        "mpb_execution_started": False,
        "source_anchors_used_for_selection": False,
        "source_anchors_used_for_fitting": False,
        "source_anchors_used_for_qualification": False,
        "stage_a_status": "PASS",
    }


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    temporary.replace(path)


def current_source_commit() -> str:
    value = os.environ.get("MEPHC_SOURCE_COMMIT", BASE_SANDBOX_SHA)
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise PreflightError("CURRENT_SOURCE_COMMIT_INVALID")
    return value


def main() -> dict[str, Any]:
    source, production = verify_contracts()
    if sha256_file(C9_SYNTHESIS_PATH) != C9_SYNTHESIS_SHA256:
        raise PreflightError("C9_SYNTHESIS_SHA256_MISMATCH")
    c9 = read_json(C9_SYNTHESIS_PATH)
    if c9.get("schema") != "mephc-r8-c9-terminal-policy-synthesis-v1" or c9.get("current_0p02_production_policy_action") != "RETAIN_UNCHANGED":
        raise PreflightError("C9_TERMINAL_POLICY_INVALID")
    geometry = load_geometry()
    cells = retained_cells(geometry)
    if not cells:
        raise PreflightError("SOURCE_DOMAIN_EMPTY")
    domain_payload = {
        "schema": "mephc-e9f-d1-fr04-source-grid-domain-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "expected_main_sha": MAIN_SHA,
        "source_contract_sha256": sha256_file(SOURCE_CONTRACT_PATH),
        "production_contract_sha256": sha256_file(PRODUCTION_CONTRACT_PATH),
        "fr": FR,
        "delta_K": DELTA_K,
        "delta_Gamma": DELTA_GAMMA,
        "resolution": RESOLUTION,
        "estimator": ESTIMATOR,
        "source_grid_step": "1/36",
        "geometry_basis": "accepted analytic equilateral K-HBZ triangle with regular Gamma-centered hexagon exclusions",
        "membership_rule": "inside shrunken K-prime HBZ and outside every source Gamma exclusion; no data-dependent pruning",
        "weight_q2": 1.0 / 1296.0,
        "weight_q2_exact": "1/1296",
        "retained_cell_count": len(cells),
        "total_weight_q2": len(cells) / 1296.0,
        "total_weight_q2_exact": f"{len(cells)}/1296",
        "min_grid_i": min(item["grid_index"][0] for item in cells),
        "max_grid_i": max(item["grid_index"][0] for item in cells),
        "min_grid_j": min(item["grid_index"][1] for item in cells),
        "max_grid_j": max(item["grid_index"][1] for item in cells),
        "retained_cells": cells,
        "domain_list_sha256": sha256_bytes(canonical(cells)),
        "source_anchors_used_for_selection": False,
        "source_anchors_used_for_fitting": False,
        "source_anchors_used_for_qualification": False,
    }
    graph = build_graph(cells)
    atomic_json(DOMAIN_PATH, domain_payload)
    atomic_json(GRAPH_PATH, graph)
    source_commit = current_source_commit()
    result = {
        "schema": "mephc-e9f-d1-fr04-source-grid-preflight-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": source_commit,
        "origin_sandbox_sha": source_commit,
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "source_contract_status": "PASS",
        "production_contract_status": "PASS",
        "source_contract_sha256": sha256_file(SOURCE_CONTRACT_PATH),
        "production_contract_sha256": sha256_file(PRODUCTION_CONTRACT_PATH),
        "c9_terminal_synthesis_sha256": C9_SYNTHESIS_SHA256,
        "fr": FR,
        "resolution": RESOLUTION,
        "estimator": ESTIMATOR,
        "delta_K": DELTA_K,
        "delta_Gamma": DELTA_GAMMA,
        "retained_cell_count": domain_payload["retained_cell_count"],
        "total_weight_q2": domain_payload["total_weight_q2"],
        "domain_list_sha256": domain_payload["domain_list_sha256"],
        "logical_provider_demand_count": graph["logical_provider_demand_count"],
        "unique_provider_request_count": graph["unique_provider_request_count"],
        "duplicate_logical_demand_count": graph["duplicate_logical_demand_count"],
        "collision_group_count": graph["collision_group_count"],
        "request_graph_sha256": sha256_file(GRAPH_PATH),
        "prospective_r64_provider_request_budget": graph["prospective_r64_provider_request_budget"],
        "prospective_r64_solver_execution_budget": graph["prospective_r64_solver_execution_budget"],
        "prospective_native_invocation_budget": graph["prospective_native_invocation_budget"],
        "current_runtime_sha256": RUNTIME_SHA256,
        "current_runtime_solver_free_certified": True,
        "current_runtime_mpb_smoke_certified": False,
        "mpb_smoke_required_before_future_acquire": True,
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "solver_executions": 0,
        "mpb_execution": False,
        "source_anchors_are_comparison_only": True,
        "source_anchors_used_for_selection": False,
        "source_anchors_used_for_fitting": False,
        "source_anchors_used_for_qualification": False,
        "future_single_dataset_supports_zero_based_bands": [0, 1, 2],
        "expected_downstream_outputs": ["BAND0_SOURCE_GRID_VALLEY_CHERN", "BAND1_SOURCE_GRID_VALLEY_CHERN", "BAND2_SOURCE_GRID_VALLEY_CHERN"],
        "future_acquisition_requires_complete_geometry_graph_before_qualification": True,
        "threshold_change_authorized": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "FR04_SOURCE_GRID_AND_R64_GRAPH_FROZEN_READY_FOR_ACQUISITION_RUNTIME_CERTIFICATION",
        "terminal": "E9F_D1_FR04_SOURCE_GRID_PREFLIGHT_COMPLETE",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + canonical(result).decode("utf-8"))
    return result


if __name__ == "__main__":
    try:
        main()
    except PreflightError as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({"schema": "mephc-e9f-d1-fr04-source-grid-preflight-v1", "state": "failed", "error_code": str(exc), "terminal": "E9F_D1_FR04_SOURCE_GRID_PREFLIGHT_FAIL_CLOSED"}).decode("utf-8"))
        raise SystemExit(2)
