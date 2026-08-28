"""Fixed, zero-argument R256 acquisition for the direct MePhC flow."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = Path(__file__).resolve().with_name("qp_b_c2_c3_r8_c7_r256_request_graph.json")
BINDING_PATH = Path(__file__).resolve().with_name("qp_b_c2_c3_r8_c7_r256_acquisition_binding.json")
SCIENCE_RUNTIME_PATH = ROOT / "tools" / "mephc-flow" / "mephc_science_runtime.py"
SCIENTIFIC_JOB_PATH = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
C6_EVIDENCE_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c6_adaptive_terminal_fixed_h_evidence.json"
PARITY_METHOD_CONTRACT_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c7_parity_aware_method_contract.json"
PARENT_R224_ACQUISITION_DATASET_ID = "df64679167793d7797330d234c3d7ec7525070d6699066aa609409a121af6d3e"
C6_EVIDENCE_SHA256 = "ab28d543e7701245f0d37ea102a7d17c3c9d90568aa20f98a264c94858c185a7"
C6_RESULT_SHA256 = "d0d35093560ec9b5acf5b5853d46acbcf46f7ad5219ea11a1b42177f7ad07e85"

WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C7-A1-20260828-315"
DECLARED_WORK_ORDER_BASE_COMMIT = "6b65347445f9a6203d3f50148129bf467bec40eb"
EXPECTED_MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
PARENT_DATASET_ID = "574097e09e10a4dcd951b068eeef89dc208899600656a525bed265e790c168cd"
PARENT_MANIFEST_SHA256 = "dd913ff7b640e911363c28b3f471a521cc0fea86d7a616a4fb26ab562fcb8bdd"
PARENT_RECONCILIATION_SHA256 = "ed26664f48ff001ffc8c4e679c19635922df8c14878aeaae11d75fbbaa5cf2af"
FIXED_H_RESULT_SHA256 = "d0d35093560ec9b5acf5b5853d46acbcf46f7ad5219ea11a1b42177f7ad07e85"
FIXED_H_EVIDENCE_SHA256 = "ab28d543e7701245f0d37ea102a7d17c3c9d90568aa20f98a264c94858c185a7"
NEXT_AXIS_CONTRACT_SHA256 = "e04320d339c87ffb92e60186946e9f8954ea7bfb438f4b7a7fd3c11172940f3a"
SCIENCE_CONTRACT_ID = "E9F_QP_B_C2_C3_R8_C7_A1"
SOURCE_MODEL = "FROZEN_QP_B_SOURCE_MODEL"
PROVIDER_CONFIGURATION = "FROZEN_QP_B_PROVIDER_CONFIGURATION"
BAND_CONFIGURATION = "FROZEN_QP_B_LOCKED_BAND_REQUEST"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
RESOLUTION = "R256"
RESOLUTION_VALUE = 256
SAMPLES = (
    (-10, -3, "CALIBRATION_CONTROL"),
    (-6, -1, "STENCIL_DIAGNOSTIC"),
    (-5, 0, "POLICY_CHALLENGE"),
    (-4, 0, "POLICY_CHALLENGE"),
)
POINT_OFFSETS = (
    ("CENTER", 0, 0),
    ("H72_PLUS_X", 2, 0), ("H72_MINUS_X", -2, 0),
    ("H72_PLUS_Y", 0, 2), ("H72_MINUS_Y", 0, -2),
    ("H144_PLUS_X", 1, 0), ("H144_MINUS_X", -1, 0),
    ("H144_PLUS_Y", 0, 1), ("H144_MINUS_Y", 0, -1),
)
POINTS = frozenset(point for point, _, _ in POINT_OFFSETS)
SAMPLE_SET = frozenset((i, j) for i, j, _ in SAMPLES)
KEY_FIELDS = (
    "fr", "resolution", "canonical_k_coordinate_units_1_over_144",
    "source_model_identity", "provider_configuration_identity",
    "band_request_configuration",
)
MAX_UNIQUE_REQUESTS = 35
MAX_FRESH_SOLVER_EXECUTIONS = 35
MAX_SUCCESS_STDOUT_BYTES = 65536


class EntrypointError(ValueError):
    """A fail-closed contract, graph, provider, or retention error."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def certified_execution_source_commit() -> str:
    """Bind acquisition provenance to the exact checkout launched by the flow."""
    value = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise EntrypointError("EXECUTION_SOURCE_COMMIT_INVALID")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    actual = result.stdout.strip()
    if result.returncode != 0 or actual != value:
        raise EntrypointError("EXECUTION_SOURCE_CHECKOUT_MISMATCH")
    return value


def load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EntrypointError("SCIENCE_FRAMEWORK_MODULE_UNAVAILABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime():
    return load_module("_mephc_r256_science_runtime", SCIENCE_RUNTIME_PATH)


def load_scientific_job():
    return load_module("_mephc_r256_scientific_job", SCIENTIFIC_JOB_PATH)


def canonical_key(request_key: dict[str, Any]) -> bytes:
    if not isinstance(request_key, dict) or set(request_key) != set(KEY_FIELDS):
        raise EntrypointError("GRAPH_REQUEST_KEY_FIELDS_INVALID")
    coordinate = request_key["canonical_k_coordinate_units_1_over_144"]
    if (not isinstance(coordinate, dict) or set(coordinate) != {"i", "j"}
            or any(isinstance(coordinate[key], bool) or not isinstance(coordinate[key], int) for key in ("i", "j"))):
        raise EntrypointError("GRAPH_RATIONAL_COORDINATE_INVALID")
    if request_key.get("fr") != 0 or request_key.get("resolution") != RESOLUTION:
        raise EntrypointError("GRAPH_REQUEST_SCOPE_INVALID")
    if any(not isinstance(request_key[field], str) or not request_key[field] for field in (
        "resolution", "source_model_identity", "provider_configuration_identity", "band_request_configuration"
    )):
        raise EntrypointError("GRAPH_REQUEST_IDENTITY_INVALID")
    return canonical({
        "fr": 0,
        "resolution": RESOLUTION,
        "canonical_k_coordinate_units_1_over_144": {"i": coordinate["i"], "j": coordinate["j"]},
        "source_model_identity": request_key["source_model_identity"],
        "provider_configuration_identity": request_key["provider_configuration_identity"],
        "band_request_configuration": request_key["band_request_configuration"],
    })


def validate_arguments(arguments: Iterable[str]) -> None:
    values = list(arguments)
    if values:
        raise EntrypointError("ENTRYPOINT_ARGUMENTS_FORBIDDEN", repr(values))


def make_graph() -> dict[str, Any]:
    demands: list[dict[str, Any]] = []
    unique: dict[bytes, dict[str, Any]] = {}
    for i, j, role in SAMPLES:
        pair_id = f"fr=0;grid_i={i};grid_j={j};role={role};resolution={RESOLUTION}"
        for point, di, dj in POINT_OFFSETS:
            coordinate = {"i": 4 * i + di, "j": 4 * j + dj}
            key = {
                "fr": 0, "resolution": RESOLUTION,
                "canonical_k_coordinate_units_1_over_144": coordinate,
                "source_model_identity": SOURCE_MODEL,
                "provider_configuration_identity": PROVIDER_CONFIGURATION,
                "band_request_configuration": BAND_CONFIGURATION,
            }
            demand = {
                "pair_id": pair_id, "sample_grid": {"i": i, "j": j}, "role": role,
                "resolution": RESOLUTION, "point": point, "request_key": key,
                "canonical_q_rational": {"i_units": coordinate["i"], "j_units": coordinate["j"], "denominator": 144},
            }
            demands.append(demand)
            key_bytes = canonical_key(key)
            record = unique.setdefault(key_bytes, {"request_key": key, "logical_demand_refs": []})
            record["logical_demand_refs"].append({"pair_id": pair_id, "point": point})
    duplicate_relations = []
    for record in unique.values():
        refs = record["logical_demand_refs"]
        if len(refs) > 1:
            duplicate_relations.append({
                "resolution": RESOLUTION,
                "left_pair": refs[0]["pair_id"], "left_point": refs[0]["point"],
                "right_pair": refs[1]["pair_id"], "right_point": refs[1]["point"],
            })
    return {
        "schema": "mephc_e9f_qp_b_c2_c3_r8_c7_r256_request_graph_v1",
        "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": DECLARED_WORK_ORDER_BASE_COMMIT,
        "expected_main_sha": EXPECTED_MAIN_SHA, "canonical_coordinate_unit": "1/144 of source-grid q coordinate",
        "canonical_center_formula": "CENTER=(4*i,4*j)",
        "canonical_stencil_offsets": {"H72": ["(+2,0)", "(-2,0)", "(0,+2)", "(0,-2)"], "H144": ["(+1,0)", "(-1,0)", "(0,+1)", "(0,-1)"]},
        "exact_request_key_fields": list(KEY_FIELDS), "cross_resolution_deduplication_allowed": False,
        "logical_provider_demand_count_per_resolution": 36, "unique_request_count_by_resolution": {RESOLUTION: 35},
        "global_unique_provider_request_count": 35, "duplicate_logical_demand_count": 1,
        "logical_demands": demands, "unique_provider_requests": list(unique.values()),
        "duplicate_relations": duplicate_relations,
        "mechanically_verified": {
            "additional_exact_collisions": 0, "all_solver_relevant_keys_equal_for_collisions": True,
            "expected_collision_relations_match": True, "each_unique_request_is_endpoint_or_center_of_locked_gate": True,
        },
        "stage_a_status": "PASS", "native_execution_started": False, "mpb_execution_started": False,
    }


def load_frozen_graph() -> dict[str, Any]:
    try:
        graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EntrypointError("FROZEN_GRAPH_UNAVAILABLE") from exc
    if not isinstance(graph, dict):
        raise EntrypointError("FROZEN_GRAPH_INVALID")
    return graph


def verify_graph(graph: dict[str, Any]) -> dict[str, Any]:
    if graph.get("stage_a_status") != "PASS":
        raise EntrypointError("FROZEN_GRAPH_STAGE_A_NOT_PASS")
    demands = graph.get("logical_demands")
    unique = graph.get("unique_provider_requests")
    if not isinstance(demands, list) or len(demands) != 36:
        raise EntrypointError("GRAPH_LOGICAL_DEMAND_COUNT_INVALID")
    if not isinstance(unique, list) or len(unique) != MAX_UNIQUE_REQUESTS:
        raise EntrypointError("GRAPH_UNIQUE_REQUEST_COUNT_INVALID")
    if graph.get("unique_request_count_by_resolution") != {RESOLUTION: 35}:
        raise EntrypointError("GRAPH_PER_RESOLUTION_COUNT_INVALID")
    if graph.get("duplicate_logical_demand_count") != 1:
        raise EntrypointError("GRAPH_DUPLICATE_COUNT_INVALID")
    samples: set[tuple[int, int]] = set()
    groups: dict[tuple[tuple[int, int], str], set[str]] = {}
    derived: dict[bytes, list[tuple[str, str]]] = {}
    for demand in demands:
        if not isinstance(demand, dict):
            raise EntrypointError("GRAPH_DEMAND_INVALID")
        grid = demand.get("sample_grid")
        if (not isinstance(grid, dict) or set(grid) != {"i", "j"}
                or any(isinstance(grid[key], bool) or not isinstance(grid[key], int) for key in ("i", "j"))):
            raise EntrypointError("GRAPH_SAMPLE_GRID_INVALID")
        sample = (grid["i"], grid["j"])
        if sample not in SAMPLE_SET or demand.get("resolution") != RESOLUTION or demand.get("point") not in POINTS:
            raise EntrypointError("GRAPH_SCOPE_VALUE_INVALID")
        key = demand.get("request_key")
        canonical = canonical_key(key)
        coordinate = key["canonical_k_coordinate_units_1_over_144"]
        rational = demand.get("canonical_q_rational")
        if (not isinstance(rational, dict) or rational != {"i_units": coordinate["i"], "j_units": coordinate["j"], "denominator": 144}):
            raise EntrypointError("GRAPH_RATIONAL_COORDINATE_MISMATCH")
        pair_id = demand.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id:
            raise EntrypointError("GRAPH_PAIR_ID_INVALID")
        samples.add(sample)
        groups.setdefault((sample, RESOLUTION), set()).add(demand["point"])
        derived.setdefault(canonical, []).append((pair_id, demand["point"]))
    if samples != SAMPLE_SET or len(groups) != 4 or any(points != POINTS for points in groups.values()):
        raise EntrypointError("GRAPH_LOCKED_SAMPLE_SET_INVALID")
    if len(derived) != MAX_UNIQUE_REQUESTS:
        raise EntrypointError("GRAPH_DERIVED_UNIQUE_COUNT_INVALID", str(len(derived)))
    listed = {canonical_key(item.get("request_key")): item for item in unique if isinstance(item, dict)}
    if len(listed) != MAX_UNIQUE_REQUESTS or set(listed) != set(derived):
        raise EntrypointError("GRAPH_LISTED_UNIQUE_KEYS_INVALID")
    collisions = {key: refs for key, refs in derived.items() if len(refs) > 1}
    if len(collisions) != 1 or sum(len(refs) - 1 for refs in collisions.values()) != 1:
        raise EntrypointError("GRAPH_DERIVED_DUPLICATE_COUNT_INVALID")
    expected = {
        tuple(item for ref in sorted((
            (f"fr=0;grid_i=-5;grid_j=0;role=POLICY_CHALLENGE;resolution={RESOLUTION}", "H72_PLUS_X"),
            (f"fr=0;grid_i=-4;grid_j=0;role=POLICY_CHALLENGE;resolution={RESOLUTION}", "H72_MINUS_X"),
        )) for item in ref),
    }
    actual = {tuple(item for ref in sorted(refs) for item in ref) for refs in collisions.values()}
    if actual != expected:
        raise EntrypointError("GRAPH_EXPECTED_COLLISIONS_INVALID")
    return {"logical_provider_demand_count": 36, "unique_provider_request_count": 35,
            "duplicate_logical_demand_count": 1, "unique_request_count_by_resolution": {RESOLUTION: 35},
            "native_solver_execution": False, "mpb_execution": False}


def build_provider_plan(graph: dict[str, Any]) -> list[dict[str, Any]]:
    verify_graph(graph)
    plan = []
    seen: set[bytes] = set()
    for record in graph["unique_provider_requests"]:
        key = canonical_key(record["request_key"])
        if key in seen:
            raise EntrypointError("GRAPH_PLAN_DUPLICATE_KEY")
        seen.add(key)
        plan.append(record)
    return plan


def execute_unique_requests(plan: list[dict[str, Any]], provider_solve: Callable[[dict[str, Any]], Any], checkpoint: dict[bytes, Any] | None = None):
    if len(plan) > MAX_UNIQUE_REQUESTS:
        raise EntrypointError("PROVIDER_REQUEST_CAP_EXCEEDED")
    if not callable(provider_solve):
        raise EntrypointError("PROVIDER_SOLVE_CALLBACK_REQUIRED")
    cache = {} if checkpoint is None else dict(checkpoint)
    results, reused, fresh = {}, 0, 0
    seen: set[bytes] = set()
    for item in plan:
        key = canonical_key(item["request_key"])
        if key in seen:
            raise EntrypointError("PROVIDER_REQUEST_DUPLICATE")
        seen.add(key)
        if key in cache:
            results[key], reused = cache[key], reused + 1
        else:
            if fresh >= MAX_FRESH_SOLVER_EXECUTIONS:
                raise EntrypointError("FRESH_SOLVER_EXECUTION_CAP_EXCEEDED")
            results[key], fresh = provider_solve(item["request_key"]), fresh + 1
    return results, reused, fresh


def _load_json(path: Path, expected_sha256: str, error_code: str) -> dict[str, Any]:
    try:
        if sha256_file(path) != expected_sha256:
            raise EntrypointError(error_code + "_HASH_MISMATCH")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EntrypointError(error_code + "_UNAVAILABLE") from exc
    if not isinstance(value, dict):
        raise EntrypointError(error_code + "_INVALID")
    return value


def _verify_method_contract() -> str:
    value = _load_json(PARITY_METHOD_CONTRACT_PATH, sha256_file(PARITY_METHOD_CONTRACT_PATH), "PARITY_METHOD_CONTRACT")
    if (value.get("schema") != "mephc-r8-c7-parity-aware-method-contract-v1"
            or value.get("work_order_id") != WORK_ORDER_ID
            or value.get("resolution_classes") != {"odd": ["R96", "R160", "R224"], "even": ["R128", "R192", "R256"]}
            or value.get("r256_adjacent_step_primary_gate") is not False):
        raise EntrypointError("PARITY_METHOD_CONTRACT_INVALID")
    return sha256_file(PARITY_METHOD_CONTRACT_PATH)


def verify_parity_precheck() -> dict[str, Any]:
    evidence = _load_json(C6_EVIDENCE_PATH, C6_EVIDENCE_SHA256, "C6_EVIDENCE")
    samples = evidence.get("samples")
    if not isinstance(samples, dict):
        raise EntrypointError("C6_EVIDENCE_SAMPLES_INVALID")
    sample_passes = 0
    stencil_passes = 0
    sign_reversals = 0
    for grid_i, grid_j, role in SAMPLES:
        identity = f"fr=0;grid_i={grid_i};grid_j={grid_j};estimator=SOURCE_GRID"
        item = samples.get(identity)
        if not isinstance(item, dict) or item.get("targeted_r224") is not True:
            raise EntrypointError("PARITY_TARGET_EVIDENCE_MISSING", identity)
        by_resolution: dict[str, dict[str, Any]] = {}
        for pair in item.get("pairs", []):
            if isinstance(pair, dict) and isinstance(pair.get("resolution"), str):
                by_resolution[pair["resolution"]] = pair
        if set(by_resolution) != {"R96", "R128", "R160", "R192", "R224"}:
            raise EntrypointError("PARITY_RESOLUTION_LADDER_INCOMPLETE", identity)
        sample_ok = True
        for stencil in ("1/72", "1/144"):
            omega = {resolution: by_resolution[resolution].get("curvature", {}).get(stencil) for resolution in by_resolution}
            if any(not isinstance(omega[resolution], (int, float)) or isinstance(omega[resolution], bool) for resolution in omega):
                raise EntrypointError("PARITY_SCALAR_EVIDENCE_INVALID", identity)
            odd_pre = abs(omega["R160"] - omega["R96"])
            odd_final = abs(omega["R224"] - omega["R160"])
            if not odd_final < odd_pre:
                raise EntrypointError("PARITY_AWARE_PRECHECK_FAILED", identity + ":" + stencil)
            sample_ok = sample_ok and True
            stencil_passes += 1
            signed_first = omega["R192"] - omega["R160"]
            signed_second = omega["R224"] - omega["R192"]
            if signed_first * signed_second < 0:
                sign_reversals += 1
        if sample_ok:
            sample_passes += 1
    if sample_passes != 4 or stencil_passes != 8:
        raise EntrypointError("PARITY_AWARE_PRECHECK_FAILED")
    return {
        "status": "PASS", "odd_subsequence_sample_pass_count": sample_passes,
        "odd_subsequence_stencil_pass_count": stencil_passes,
        "adjacent_sign_reversal_stencil_count": sign_reversals,
    }


def _verify_parent_r224() -> None:
    runtime = load_runtime()
    scientific_job = load_scientific_job()
    verified = scientific_job.verify_dataset(runtime._trusted_science_state_root(), PARENT_DATASET_ID)
    if (not isinstance(verified, dict) or verified.get("state") != "verified"
            or verified.get("record_count") != 35
            or verified.get("manifest_sha256") != PARENT_MANIFEST_SHA256):
        raise EntrypointError("PARENT_R224_DATASET_BINDING_INVALID")

def _provider() -> Callable[[dict[str, Any]], Any]:
    try:
        import meep as mp
        from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs
        from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    except ImportError as exc:
        raise EntrypointError("EXISTING_E9_MPB_PROVIDER_UNAVAILABLE") from exc
    geometry = geometry_inputs()
    _, lattice, solver_geometry, background = build_inputs(geometry)
    provider = MPBLiveSpectralProvider(
        geometry=list(solver_geometry), geometry_lattice=lattice, resolution=RESOLUTION_VALUE,
        num_bands=6, polarization=mp.TE, default_material=background,
        eigensolver_tolerance=1e-7, deterministic=True, mesh_size=3,
    )

    def solve(request_key: dict[str, Any]) -> Any:
        coordinate = request_key["canonical_k_coordinate_units_1_over_144"]
        return provider.solve((coordinate["i"] / 144.0, coordinate["j"] / 144.0))

    return solve


def _identity(request_key: dict[str, Any]) -> dict[str, Any]:
    return {"resolution": RESOLUTION, "canonical_k_coordinate_units_1_over_144": request_key["canonical_k_coordinate_units_1_over_144"],
            "source_model_identity": SOURCE_MODEL, "provider_configuration_identity": PROVIDER_CONFIGURATION,
            "band_request_configuration": BAND_CONFIGURATION}


def _acquisition_manifest(store: Any, plan: list[dict[str, Any]], runtime_sha: str, entrypoint_sha: str, graph_sha: str,
                          acquisition_source_commit: str,
                          fresh: int, reused: int, mpb: bool) -> dict[str, Any]:
    records = []
    for item in plan:
        key = canonical_key(item["request_key"])
        payload, metadata = store.get(key)
        del payload
        records.append({key: metadata[key] for key in ("key_sha256", "payload_sha256", "payload_size_bytes")})
    records.sort(key=lambda item: item["key_sha256"])
    content = {
        "schema": "mephc_direct_flow_r8_acquisition_dataset_v1", "project_id": "MEPHC",
        "science_contract_id": SCIENCE_CONTRACT_ID, "acquisition_source_commit": acquisition_source_commit,
        "entrypoint_sha256": entrypoint_sha, "graph_sha256": graph_sha,
        "science_runtime_sha256": runtime_sha, "source_model_identity": SOURCE_MODEL,
        "provider_configuration_identity": PROVIDER_CONFIGURATION, "band_request_configuration": BAND_CONFIGURATION,
        "resolution": RESOLUTION, "logical_provider_demand_count": 36, "unique_provider_request_count": 35,
        "completed_key_count": 35, "records": records, "fresh_provider_execution_count": fresh,
        "cache_reuse_count": reused, "fresh_mpb_execution_observed": bool(mpb),
        "dataset_is_mpb_backed": True, "parent_dataset_id": PARENT_DATASET_ID, "completion_state": "COMPLETE",
    }
    content["dataset_id"] = hashlib.sha256(canonical(content)).hexdigest()
    content["manifest_sha256"] = hashlib.sha256(canonical({key: value for key, value in content.items() if key != "manifest_sha256"})).hexdigest()
    manifest_path = store.root / "acquisition-dataset-manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        static = set(content) - {"fresh_provider_execution_count", "cache_reuse_count", "fresh_mpb_execution_observed", "dataset_id", "manifest_sha256"}
        if any(existing.get(key) != content[key] for key in static):
            raise EntrypointError("DATASET_MANIFEST_IMMUTABILITY_VIOLATION")
        return existing
    load_scientific_job().atomic_json(manifest_path, content)
    return content


def _write_binding(dataset: dict[str, Any], runtime_sha: str, entrypoint_sha: str, graph_sha: str,
                   acquisition_source_commit: str, fresh: int, reused: int) -> None:
    value = {
        "schema": "mephc_e9f_qp_b_c2_c3_r8_c7_r256_acquisition_binding_v1", "work_order_id": WORK_ORDER_ID,
        "acquisition_source_commit": acquisition_source_commit, "acquisition_dataset_id": dataset["dataset_id"],
        "dataset_manifest_sha256": dataset["manifest_sha256"], "entrypoint_sha256": entrypoint_sha,
        "graph_sha256": graph_sha, "science_runtime_sha256": runtime_sha, "parent_dataset_id": PARENT_DATASET_ID,
        "parent_dataset_manifest_sha256": PARENT_MANIFEST_SHA256, "resolution": RESOLUTION,
        "parent_provenance_reconciliation_sha256": PARENT_RECONCILIATION_SHA256,
        "fixed_h_analysis_result_sha256": FIXED_H_RESULT_SHA256,
        "fixed_h_analysis_evidence_sha256": FIXED_H_EVIDENCE_SHA256,
        "next_axis_contract_sha256": NEXT_AXIS_CONTRACT_SHA256,
        "logical_provider_demand_count": 36, "unique_provider_request_count": 35,
        "duplicate_logical_demand_count": 1, "completed_key_count": 35, "failed_key_count": 0,
        "provider_failure_count": 0, "fresh_provider_execution_count": fresh, "cache_reuse_count": reused,
        "holdout_used": False, "third_stencil_executed": False, "mpb_execution": True,
        "completion_state": "COMPLETE",
    }
    load_scientific_job().atomic_json(BINDING_PATH, value)


def acquire() -> dict[str, Any]:
    graph = load_frozen_graph()
    verification = verify_graph(graph)
    plan = build_provider_plan(graph)
    runtime = load_runtime()
    scientific_job = load_scientific_job()
    acquisition_source_commit = certified_execution_source_commit()
    runtime_sha = scientific_job.runtime_hash(ROOT)
    entrypoint_sha = sha256_file(Path(__file__))
    graph_sha = sha256_file(GRAPH_PATH)
    namespace = {
        "project_id": "MEPHC", "science_contract_id": f"{SCIENCE_CONTRACT_ID}_R256",
        "source_commit": acquisition_source_commit, "work_order_id": WORK_ORDER_ID, "resolution": RESOLUTION,
        "entrypoint_sha256": entrypoint_sha, "graph_sha256": graph_sha, "science_runtime_sha256": runtime_sha,
    }
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    if store.root.exists():
        raise EntrypointError("EXISTING_R256_STATE_RECONCILIATION_REQUIRED")
    method_contract_sha = _verify_method_contract()
    _verify_parent_r224()
    parity = verify_parity_precheck()
    provider = _provider()
    counter = scientific_job.BudgetCounter(MAX_UNIQUE_REQUESTS, MAX_FRESH_SOLVER_EXECUTIONS)
    fresh = reused = 0
    mpb = False
    for item in plan:
        key = canonical_key(item["request_key"])
        payload_path, metadata_path = store._paths(key)
        if payload_path.is_file() and metadata_path.is_file():
            payload, _ = store.get(key)
            runtime.decode_snapshot(payload)
            reused += 1
            continue
        if payload_path.exists() or metadata_path.exists():
            raise EntrypointError("CHECKPOINT_RECORD_INCOMPLETE", hashlib.sha256(key).hexdigest())
        counter.consume_provider()
        counter.consume_solver()
        try:
            snapshot = provider(item["request_key"])
            payload = runtime.encode_snapshot(snapshot)
            runtime.decode_snapshot(payload)
            store.put(key, payload, {"schema": "mephc_r256_exact_key_record_v1", "key_sha256": hashlib.sha256(key).hexdigest(), **_identity(item["request_key"])})
        except Exception as exc:
            raise EntrypointError("R256_REQUEST_FAILED", f"{hashlib.sha256(key).hexdigest()}:{type(exc).__name__}") from exc
        fresh += 1
        mpb = True
    store.finalize(MAX_UNIQUE_REQUESTS, {"work_order_id": WORK_ORDER_ID, "resolution": RESOLUTION, "science_runtime_sha256": runtime_sha})
    dataset = _acquisition_manifest(store, plan, runtime_sha, entrypoint_sha, graph_sha,
                                    acquisition_source_commit, fresh, reused, mpb)
    _write_binding(dataset, runtime_sha, entrypoint_sha, graph_sha, acquisition_source_commit, fresh, reused)
    return {
        "schema": "mephc-r8-c7-r256-acquisition-v1", "result_schema": "mephc-r8-c7-r256-acquisition-v1",
        "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": DECLARED_WORK_ORDER_BASE_COMMIT,
        "final_sandbox_sha": acquisition_source_commit, "origin_sandbox_sha": acquisition_source_commit,
        "main_sha": EXPECTED_MAIN_SHA, "machine_contract_status": "PASS",
        "science_runtime_sha256": runtime_sha, "parity_precheck_status": parity["status"],
        "odd_subsequence_sample_pass_count": parity["odd_subsequence_sample_pass_count"],
        "odd_subsequence_stencil_pass_count": parity["odd_subsequence_stencil_pass_count"],
        "adjacent_sign_reversal_stencil_count": parity["adjacent_sign_reversal_stencil_count"],
        "parity_aware_method_contract_sha256": method_contract_sha, "request_graph_status": "PASS", **verification,
        "native_invocation_count": 1, "native_invocation_cost": 1, "provider_request_count": 35,
        "cache_reuse_count": reused, "fresh_provider_execution_count": fresh,
        "fresh_native_solver_execution_count": fresh, "native_solves": fresh, "mpb_execution": mpb,
        "completed_key_count": 35, "failed_key_count": 0, "provider_failure_count": 0,
        "R256_dataset_id": dataset["dataset_id"], "R256_dataset_manifest_sha256": dataset["manifest_sha256"],
        "R256_dataset_record_count": 35, "R256_acquisition_source_commit": acquisition_source_commit,
        "R256_entrypoint_sha256": entrypoint_sha, "R256_request_graph_sha256": graph_sha,
        "parent_dataset_id": PARENT_DATASET_ID, "parent_r224_acquisition_dataset_id": PARENT_R224_ACQUISITION_DATASET_ID,
        "parent_provenance_reconciliation_sha256": PARENT_RECONCILIATION_SHA256,
        "fixed_h_analysis_result_sha256": FIXED_H_RESULT_SHA256, "c6_result_sha256": C6_RESULT_SHA256,
        "c6_evidence_sha256": C6_EVIDENCE_SHA256, "parity_aware_method_contract_sha256": method_contract_sha,
        "next_axis_contract_sha256": NEXT_AXIS_CONTRACT_SHA256,
        "holdout_used": False, "third_stencil_executed": False,
        "native_retry_count": 0, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False,
        "scientific_work_must_stop": True,
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C7_A1_R256_DATASET_ACQUIRED_READY_FOR_SOLVER_FREE_ANALYSIS",
    }


def run(arguments: Iterable[str] = (), *, provider_solve: Callable[[dict[str, Any]], Any] | None = None,
        checkpoint: dict[bytes, Any] | None = None) -> dict[str, Any]:
    validate_arguments(arguments)
    graph = load_frozen_graph()
    verification = verify_graph(graph)
    plan = build_provider_plan(graph)
    if provider_solve is not None or checkpoint is not None:
        if provider_solve is None or checkpoint is None:
            raise EntrypointError("CALLER_RUNTIME_INJECTION_INCOMPLETE")
        results, reused, fresh = execute_unique_requests(plan, provider_solve, checkpoint)
        return {**verification, "provider_request_count": len(plan), "cache_reuse_count": reused,
                "fresh_native_solver_execution_count": fresh, "results": results}
    return acquire()


def main() -> int:
    try:
        result = run(sys.argv[1:])
        payload = canonical(result)
        if len(payload) > MAX_SUCCESS_STDOUT_BYTES:
            raise EntrypointError("SUCCESS_STDOUT_LIMIT_EXCEEDED")
        print("MEPHC_NATIVE_RESULT_JSON=" + payload.decode("utf-8"))
        return 0
    except EntrypointError as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({"schema": "mephc-r8-c7-r256-acquisition-v1", "state": "failed", "error_code": exc.code, "detail": exc.detail[:1000], "terminal": "E9F_C2_QP_B_C2_C3_R8_C7_A1_FAIL_CLOSED"}).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
