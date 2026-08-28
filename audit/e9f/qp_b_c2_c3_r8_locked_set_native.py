"""Fixed, zero-argument R8 locked-set direct-flow entrypoint."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable


FROZEN_GRAPH_PATH = Path(__file__).resolve().with_name(
    "qp_b_c2_c3_r8_global_provider_request_graph.json"
)
SCIENCE_RUNTIME_PATH = Path(__file__).resolve().parents[2] / "tools" / "mephc-flow" / "mephc_science_runtime.py"
EXPECTED_RESOLUTIONS = ("R96", "R128", "R160")
EXPECTED_POINTS = frozenset({
    "CENTER", "H72_PLUS_X", "H72_MINUS_X", "H72_PLUS_Y", "H72_MINUS_Y",
    "H144_PLUS_X", "H144_MINUS_X", "H144_PLUS_Y", "H144_MINUS_Y",
})
EXPECTED_SAMPLES = frozenset({
    (-10, -3), (-34, 9), (-6, -1), (-34, -16),
    (-34, -17), (-34, 17), (-5, 0), (-4, 0),
})
KEY_FIELDS = (
    "fr", "resolution", "canonical_k_coordinate_units_1_over_144",
    "source_model_identity", "provider_configuration_identity",
    "band_request_configuration",
)
MAX_UNIQUE_REQUESTS = 210
MAX_FRESH_SOLVER_EXECUTIONS = 210
OUTPUT_FIELDS = (
    "logical_provider_demands", "unique_provider_requests",
    "deduplicated_collisions", "cache_reuse_count",
    "fresh_native_solver_execution_count", "provider_failures_retries",
    "sample_resolution_gate_results", "historically_missing_curvature_pairs",
    "validation_cross_check_curvature_pairs", "srd_contraction_quantities",
    "control_envelopes", "policy_challenge_noninferiority_results",
    "stencil_diagnostic_result", "locked_set_calibration_verdict",
)


class EntrypointError(ValueError):
    """A fail-closed contract or graph error."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load_science_runtime():
    """Load only the fixed direct-flow science runtime module."""
    module_name = "_mephc_direct_flow_science_runtime"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, SCIENCE_RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise EntrypointError("DIRECT_FLOW_SCIENCE_RUNTIME_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def canonical_key(request_key: dict[str, Any]) -> bytes:
    """Return the exact, solver-relevant provider key bytes."""
    if not isinstance(request_key, dict) or set(request_key) != set(KEY_FIELDS):
        raise EntrypointError("GRAPH_REQUEST_KEY_FIELDS_INVALID")
    coordinate = request_key["canonical_k_coordinate_units_1_over_144"]
    if (not isinstance(coordinate, dict) or set(coordinate) != {"i", "j"}
            or isinstance(coordinate["i"], bool)
            or isinstance(coordinate["j"], bool)
            or not isinstance(coordinate["i"], int)
            or not isinstance(coordinate["j"], int)):
        raise EntrypointError("GRAPH_RATIONAL_COORDINATE_INVALID")
    if not isinstance(request_key["fr"], int) or isinstance(request_key["fr"], bool):
        raise EntrypointError("GRAPH_FR_INVALID")
    for field in ("resolution", "source_model_identity",
                  "provider_configuration_identity", "band_request_configuration"):
        if not isinstance(request_key[field], str) or not request_key[field]:
            raise EntrypointError("GRAPH_REQUEST_IDENTITY_INVALID", field)
    normalized = {
        "fr": request_key["fr"],
        "resolution": request_key["resolution"],
        "canonical_k_coordinate_units_1_over_144": {
            "i": coordinate["i"], "j": coordinate["j"]
        },
        "source_model_identity": request_key["source_model_identity"],
        "provider_configuration_identity": request_key["provider_configuration_identity"],
        "band_request_configuration": request_key["band_request_configuration"],
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def validate_arguments(arguments: Iterable[str]) -> None:
    """Accept no arguments; reject before graph/provider initialization."""
    values = list(arguments)
    if values:
        raise EntrypointError("ENTRYPOINT_ARGUMENTS_FORBIDDEN", repr(values))


def load_frozen_graph() -> dict[str, Any]:
    try:
        value = json.loads(FROZEN_GRAPH_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EntrypointError("FROZEN_GRAPH_UNAVAILABLE") from exc
    if not isinstance(value, dict):
        raise EntrypointError("FROZEN_GRAPH_INVALID")
    return value


def verify_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Independently verify all Stage A invariants without solving."""
    if graph.get("stage_a_status") != "PASS":
        raise EntrypointError("FROZEN_GRAPH_STAGE_A_NOT_PASS")
    demands = graph.get("logical_demands")
    unique_records = graph.get("unique_provider_requests")
    if not isinstance(demands, list) or len(demands) != 216:
        raise EntrypointError("GRAPH_LOGICAL_DEMAND_COUNT_INVALID")
    if not isinstance(unique_records, list) or len(unique_records) != 210:
        raise EntrypointError("GRAPH_UNIQUE_REQUEST_COUNT_INVALID")
    if graph.get("unique_request_count_by_resolution") != {
        "R96": 70, "R128": 70, "R160": 70
    }:
        raise EntrypointError("GRAPH_PER_RESOLUTION_COUNT_INVALID")
    if graph.get("duplicate_logical_demand_count") != 6:
        raise EntrypointError("GRAPH_DUPLICATE_COUNT_INVALID")
    if graph.get("cross_resolution_deduplication_allowed") is not False:
        raise EntrypointError("GRAPH_CROSS_RESOLUTION_DEDUPLICATION_FORBIDDEN")

    samples: set[tuple[int, int]] = set()
    groups: dict[tuple[tuple[int, int], str], set[str]] = {}
    derived: dict[bytes, list[tuple[str, str]]] = {}
    per_resolution: dict[str, int] = {resolution: 0 for resolution in EXPECTED_RESOLUTIONS}
    for demand in demands:
        if not isinstance(demand, dict):
            raise EntrypointError("GRAPH_DEMAND_INVALID")
        grid = demand.get("sample_grid")
        if (not isinstance(grid, dict) or set(grid) != {"i", "j"}
                or isinstance(grid["i"], bool) or isinstance(grid["j"], bool)
                or not isinstance(grid["i"], int) or not isinstance(grid["j"], int)):
            raise EntrypointError("GRAPH_SAMPLE_GRID_INVALID")
        sample = (grid["i"], grid["j"])
        resolution = demand.get("resolution")
        point = demand.get("point")
        pair_id = demand.get("pair_id")
        if resolution not in EXPECTED_RESOLUTIONS or point not in EXPECTED_POINTS:
            raise EntrypointError("GRAPH_SCOPE_VALUE_INVALID")
        if not isinstance(pair_id, str) or not pair_id:
            raise EntrypointError("GRAPH_PAIR_ID_INVALID")
        samples.add(sample)
        groups.setdefault((sample, resolution), set()).add(point)
        key = canonical_key(demand.get("request_key"))
        rational = demand.get("canonical_q_rational")
        coordinate = demand["request_key"]["canonical_k_coordinate_units_1_over_144"]
        if (not isinstance(rational, dict)
                or rational.get("denominator") != 144
                or rational.get("i_units") != coordinate["i"]
                or rational.get("j_units") != coordinate["j"]):
            raise EntrypointError("GRAPH_RATIONAL_COORDINATE_MISMATCH")
        if demand["request_key"]["fr"] != 0:
            raise EntrypointError("GRAPH_FR_SCOPE_INVALID")
        derived.setdefault(key, []).append((pair_id, point))

    if samples != EXPECTED_SAMPLES or len(groups) != 24:
        raise EntrypointError("GRAPH_LOCKED_SAMPLE_SET_INVALID")
    if any(points != EXPECTED_POINTS for points in groups.values()):
        raise EntrypointError("GRAPH_STENCIL_BUNDLE_INCOMPLETE")
    if len(derived) != MAX_UNIQUE_REQUESTS:
        raise EntrypointError("GRAPH_DERIVED_UNIQUE_COUNT_INVALID", str(len(derived)))
    for resolution in EXPECTED_RESOLUTIONS:
        per_resolution[resolution] = sum(
            1 for key in derived
            if json.loads(key.decode("utf-8"))["resolution"] == resolution
        )
    if per_resolution != {"R96": 70, "R128": 70, "R160": 70}:
        raise EntrypointError("GRAPH_DERIVED_PER_RESOLUTION_COUNT_INVALID")
    duplicate_groups = {key: refs for key, refs in derived.items() if len(refs) > 1}
    if len(duplicate_groups) != 6 or sum(len(refs) - 1 for refs in duplicate_groups.values()) != 6:
        raise EntrypointError("GRAPH_DERIVED_DUPLICATE_COUNT_INVALID")

    expected_relations = {
        (
            resolution,
            tuple(sorted((
                ("fr=0;grid_i=-34;grid_j=-17;role=POLICY_CHALLENGE;resolution=" + resolution, "H72_PLUS_Y"),
                ("fr=0;grid_i=-34;grid_j=-16;role=POLICY_CHALLENGE;resolution=" + resolution, "H72_MINUS_Y"),
            )))
        )
        for resolution in EXPECTED_RESOLUTIONS
    } | {
        (
            resolution,
            tuple(sorted((
                ("fr=0;grid_i=-5;grid_j=0;role=POLICY_CHALLENGE;resolution=" + resolution, "H72_PLUS_X"),
                ("fr=0;grid_i=-4;grid_j=0;role=POLICY_CHALLENGE;resolution=" + resolution, "H72_MINUS_X"),
            )))
        )
        for resolution in EXPECTED_RESOLUTIONS
    }
    actual_relations: set[tuple[str, tuple[tuple[str, str], tuple[str, str]]]] = set()
    for key, refs in duplicate_groups.items():
        resolution = json.loads(key.decode("utf-8"))["resolution"]
        actual_relations.add((resolution, tuple(sorted(refs))))
    if actual_relations != expected_relations:
        raise EntrypointError("GRAPH_EXPECTED_COLLISIONS_INVALID")

    listed = {canonical_key(record.get("request_key")): record for record in unique_records
              if isinstance(record, dict)}
    if len(listed) != MAX_UNIQUE_REQUESTS or set(listed) != set(derived):
        raise EntrypointError("GRAPH_LISTED_UNIQUE_KEYS_INVALID")
    return {
        "logical_provider_demand_count": len(demands),
        "unique_provider_request_count": len(derived),
        "duplicate_logical_demand_count": sum(len(refs) - 1 for refs in duplicate_groups.values()),
        "unique_request_count_by_resolution": per_resolution,
        "duplicate_groups": duplicate_groups,
        "native_solver_execution": False,
        "mpb_execution": False,
    }


def build_provider_plan(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Return exactly the verified unique keys; never generate new points."""
    verify_graph(graph)
    plan: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    for record in graph["unique_provider_requests"]:
        key = canonical_key(record["request_key"])
        if key in seen:
            raise EntrypointError("GRAPH_PLAN_DUPLICATE_KEY")
        seen.add(key)
        plan.append({"request_key": record["request_key"],
                     "logical_demand_refs": record.get("logical_demand_refs", [])})
    if len(plan) != MAX_UNIQUE_REQUESTS:
        raise EntrypointError("GRAPH_PLAN_CAP_INVALID")
    return plan


def execute_unique_requests(
    plan: list[dict[str, Any]],
    provider_solve: Callable[[dict[str, Any]], Any],
    checkpoint: dict[bytes, Any] | None = None,
) -> tuple[dict[bytes, Any], int, int]:
    """Execute each exact key once, reusing only exact-key checkpoint entries."""
    if len(plan) > MAX_UNIQUE_REQUESTS:
        raise EntrypointError("PROVIDER_REQUEST_CAP_EXCEEDED")
    if not callable(provider_solve):
        raise EntrypointError("PROVIDER_SOLVE_CALLBACK_REQUIRED")
    cache = {} if checkpoint is None else dict(checkpoint)
    results: dict[bytes, Any] = {}
    fresh = 0
    reused = 0
    seen: set[bytes] = set()
    for item in plan:
        key = canonical_key(item["request_key"])
        if key in seen:
            raise EntrypointError("PROVIDER_REQUEST_DUPLICATE")
        seen.add(key)
        if key in cache:
            results[key] = cache[key]
            reused += 1
            continue
        if fresh >= MAX_FRESH_SOLVER_EXECUTIONS:
            raise EntrypointError("FRESH_SOLVER_EXECUTION_CAP_EXCEEDED")
        results[key] = provider_solve(item["request_key"])
        fresh += 1
    return results, reused, fresh


def validate_output_contract(output: dict[str, Any]) -> None:
    if not isinstance(output, dict) or any(field not in output for field in OUTPUT_FIELDS):
        raise EntrypointError("NATIVE_OUTPUT_CONTRACT_INCOMPLETE")


def run(
    arguments: Iterable[str] = (),
    *,
    provider_solve: Callable[[dict[str, Any]], Any] | None = None,
    checkpoint: dict[bytes, Any] | None = None,
) -> dict[str, Any]:
    """Validate the frozen scope, then use the official runtime when un-injected."""
    validate_arguments(arguments)
    graph = load_frozen_graph()
    verification = verify_graph(graph)
    plan = build_provider_plan(graph)
    if provider_solve is None and checkpoint is None:
        try:
            runtime = load_science_runtime().create_r8_runtime()
            results, reused, fresh = runtime.execute(plan)
        except Exception as exc:
            if isinstance(exc, EntrypointError):
                raise
            raise EntrypointError("DIRECT_FLOW_SCIENCE_RUNTIME_FAILED", str(exc)) from exc
        return {
            **verification,
            "provider_request_count": len(plan),
            "cache_reuse_count": reused,
            "fresh_native_solver_execution_count": fresh,
            "results": results,
        }
    if provider_solve is None or checkpoint is None:
        raise EntrypointError("CALLER_RUNTIME_INJECTION_INCOMPLETE")
    results, reused, fresh = execute_unique_requests(plan, provider_solve, checkpoint)
    return {
        **verification,
        "provider_request_count": len(plan),
        "cache_reuse_count": reused,
        "fresh_native_solver_execution_count": fresh,
        "results": results,
    }


def main() -> int:
    try:
        result = run(sys.argv[1:])
    except EntrypointError as exc:
        print(json.dumps({"error_code": exc.code, "detail": exc.detail}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
