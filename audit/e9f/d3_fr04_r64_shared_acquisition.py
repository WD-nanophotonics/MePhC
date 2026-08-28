"""Complete shared fr=0.4 R64 acquisition for the frozen D1 graph."""
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
DOMAIN_PATH = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
GRAPH_PATH = ROOT / "audit/e9f/d1_fr04_r64_request_graph.json"
BINDING_PATH = ROOT / "audit/e9f/d3_fr04_r64_acquisition_binding.json"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
SCIENTIFIC_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"
SOURCE_MODEL_PATH = ROOT / "audit/e9c/run_k_kprime_rank1_berry.py"

WORK_ORDER_ID = "MEPHC-E9F-D3-FR04-R64-SHARED-ACQUISITION-20260828-323"
BASE_SANDBOX_SHA = "a2f39e6cc12ab4c2337c85edb0e76198cea3a8f6"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
DOMAIN_SHA256 = "85f395e03c8d4ac1b73d2a1a5ef0c2bc083ac736ed59542809e10225edb3489f"
DOMAIN_LIST_SHA256 = "df1e87976df1f435c075485dca2cebd9cf350b32376f8a6d5c61188df447d631"
GRAPH_SHA256 = "cafee7826fbadfec4cc57c5950f0ff4004906f27f790b466cf1d31c49d56e855"
FR = 0.4
RESOLUTION = "R64"
RESOLUTION_VALUE = 64
RETAINED_CELL_COUNT = 641
LOGICAL_DEMAND_COUNT = 3205
UNIQUE_REQUEST_COUNT = 3205
SOURCE_MODEL_IDENTITY = "FROZEN_E9_SOURCE_MODEL"
PROVIDER_CONFIGURATION_IDENTITY = "FROZEN_QP_B_PROVIDER_CONFIGURATION"
BAND_REQUEST_CONFIGURATION = "FROZEN_QP_B_LOCKED_BAND_REQUEST"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
KEY_FIELDS = (
    "fr", "resolution", "canonical_k_coordinate_units_1_over_144",
    "source_model_identity", "provider_configuration_identity", "band_request_configuration",
)
MAX_SUCCESS_STDOUT_BYTES = 65536


class AcquisitionError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


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
        raise AcquisitionError("JSON_UNAVAILABLE", path.name) from exc
    if not isinstance(value, dict):
        raise AcquisitionError("JSON_OBJECT_REQUIRED", path.name)
    return value


def load_module(name: str, path: Path) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AcquisitionError("MODULE_UNAVAILABLE", path.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def current_source_commit() -> str:
    expected = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    if len(expected) != 40 or any(char not in "0123456789abcdef" for char in expected):
        raise AcquisitionError("EXECUTION_SOURCE_COMMIT_INVALID")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    actual = result.stdout.strip()
    if result.returncode != 0 or actual != expected:
        raise AcquisitionError("EXECUTION_SOURCE_CHECKOUT_MISMATCH")
    return expected


def canonical_key(key: dict[str, Any]) -> bytes:
    if not isinstance(key, dict) or set(key) != set(KEY_FIELDS):
        raise AcquisitionError("GRAPH_REQUEST_KEY_FIELDS_INVALID")
    coordinate = key.get("canonical_k_coordinate_units_1_over_144")
    if (not isinstance(coordinate, dict) or set(coordinate) != {"i", "j"}
            or any(type(coordinate[item]) is not int for item in ("i", "j"))):
        raise AcquisitionError("GRAPH_RATIONAL_COORDINATE_INVALID")
    if key.get("fr") != FR or key.get("resolution") != RESOLUTION:
        raise AcquisitionError("GRAPH_SCOPE_INVALID")
    if key.get("source_model_identity") != SOURCE_MODEL_IDENTITY:
        raise AcquisitionError("GRAPH_SOURCE_MODEL_INVALID")
    if key.get("provider_configuration_identity") != PROVIDER_CONFIGURATION_IDENTITY:
        raise AcquisitionError("GRAPH_PROVIDER_CONFIGURATION_INVALID")
    if key.get("band_request_configuration") != BAND_REQUEST_CONFIGURATION:
        raise AcquisitionError("GRAPH_BAND_CONFIGURATION_INVALID")
    return canonical(key)


def verify_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if sha256_file(DOMAIN_PATH) != DOMAIN_SHA256:
        raise AcquisitionError("D1_DOMAIN_HASH_MISMATCH")
    if sha256_file(GRAPH_PATH) != GRAPH_SHA256:
        raise AcquisitionError("D1_GRAPH_HASH_MISMATCH")
    domain = read_json(DOMAIN_PATH)
    graph = read_json(GRAPH_PATH)
    if (domain.get("schema") != "mephc-e9f-d1-fr04-source-grid-domain-v1"
            or domain.get("retained_cell_count") != RETAINED_CELL_COUNT
            or domain.get("domain_list_sha256") != DOMAIN_LIST_SHA256):
        raise AcquisitionError("D1_DOMAIN_CONTENT_INVALID")
    if (graph.get("schema") != "mephc-e9f-d1-fr04-r64-request-graph-v1"
            or graph.get("fr") != FR or graph.get("resolution") != RESOLUTION
            or graph.get("logical_provider_demand_count") != LOGICAL_DEMAND_COUNT
            or graph.get("unique_provider_request_count") != UNIQUE_REQUEST_COUNT
            or graph.get("collision_group_count") != 0
            or graph.get("duplicate_logical_demand_count") != 0
            or graph.get("h_representation") != H_REPRESENTATION):
        raise AcquisitionError("D1_GRAPH_CONTENT_INVALID")
    if graph.get("source_model_identity") != SOURCE_MODEL_IDENTITY:
        raise AcquisitionError("D1_GRAPH_SOURCE_MODEL_INVALID")
    demands = graph.get("logical_demands")
    unique = graph.get("unique_provider_requests")
    if not isinstance(demands, list) or not isinstance(unique, list) or len(demands) != LOGICAL_DEMAND_COUNT or len(unique) != UNIQUE_REQUEST_COUNT:
        raise AcquisitionError("D1_GRAPH_COUNTS_INVALID")
    keys: set[bytes] = set()
    for item in unique:
        if not isinstance(item, dict):
            raise AcquisitionError("D1_UNIQUE_REQUEST_INVALID")
        key_bytes = canonical_key(item.get("request_key"))
        if key_bytes in keys:
            raise AcquisitionError("D1_UNIQUE_REQUEST_DUPLICATE")
        keys.add(key_bytes)
        if len(item.get("logical_demand_refs", [])) != 1:
            raise AcquisitionError("D1_UNEXPECTED_COLLISION")
    demand_keys = {canonical_key(item.get("request_key")) for item in demands if isinstance(item, dict)}
    if len(demand_keys) != UNIQUE_REQUEST_COUNT or demand_keys != keys:
        raise AcquisitionError("D1_DEMAND_UNIQUE_KEY_MISMATCH")
    return domain, graph, unique


def load_runtime() -> Any:
    return load_module("_mephc_d3_science_runtime", RUNTIME_PATH)


def load_scientific_job() -> Any:
    return load_module("_mephc_d3_scientific_job", SCIENTIFIC_JOB_PATH)


def verify_runtime(scientific_job: Any, runtime: Any) -> None:
    if scientific_job.runtime_hash(ROOT) != RUNTIME_SHA256:
        raise AcquisitionError("SCIENCE_RUNTIME_HASH_MISMATCH")
    certification_path = runtime._trusted_science_state_root() / "certifications" / f"{RUNTIME_SHA256}.json"
    certification = read_json(certification_path)
    smoke = certification.get("mpb_smoke", {})
    if (certification.get("schema") != "mephc-science-runtime-certification-v1"
            or certification.get("runtime_sha256") != RUNTIME_SHA256
            or smoke.get("executed") is not True
            or smoke.get("solver_executions") != 1):
        raise AcquisitionError("SCIENCE_RUNTIME_MPB_CERTIFICATION_INVALID")


def provider() -> Callable[[dict[str, Any]], Any]:
    try:
        import meep as mp
        source = load_module("_mephc_d3_corrected_e9_source_model", SOURCE_MODEL_PATH)
        from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    except ImportError as exc:
        raise AcquisitionError("CORRECTED_E9_PROVIDER_UNAVAILABLE") from exc
    geometry = source.geometry_inputs()
    _, lattice, solver_geometry, background = source.build_inputs(geometry)
    live = MPBLiveSpectralProvider(
        geometry=list(solver_geometry), geometry_lattice=lattice, resolution=RESOLUTION_VALUE,
        num_bands=6, polarization=mp.TE, default_material=background,
        eigensolver_tolerance=1e-7, deterministic=True, mesh_size=3,
    )

    def solve(key: dict[str, Any]) -> Any:
        coordinate = key["canonical_k_coordinate_units_1_over_144"]
        return live.solve((coordinate["i"] / 144.0, coordinate["j"] / 144.0))

    return solve


def identity(key: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolution": RESOLUTION,
        "canonical_k_coordinate_units_1_over_144": key["canonical_k_coordinate_units_1_over_144"],
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION,
        "h_representation": H_REPRESENTATION,
    }


def write_binding(dataset: dict[str, Any], source_commit: str, entrypoint_sha: str) -> None:
    value = {
        "schema": "mephc-e9f-d3-fr04-r64-acquisition-binding-v1",
        "work_order_id": WORK_ORDER_ID,
        "acquisition_source_commit": source_commit,
        "acquisition_dataset_id": dataset["dataset_id"],
        "dataset_manifest_sha256": dataset["manifest_sha256"],
        "entrypoint_sha256": entrypoint_sha,
        "request_graph_sha256": GRAPH_SHA256,
        "domain_artifact_sha256": DOMAIN_SHA256,
        "domain_list_sha256": DOMAIN_LIST_SHA256,
        "science_runtime_sha256": RUNTIME_SHA256,
        "fr": FR,
        "resolution": RESOLUTION,
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION,
        "h_representation": H_REPRESENTATION,
        "retained_cell_count": RETAINED_CELL_COUNT,
        "logical_provider_demand_count": LOGICAL_DEMAND_COUNT,
        "unique_provider_request_count": UNIQUE_REQUEST_COUNT,
        "completed_key_count": UNIQUE_REQUEST_COUNT,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "fresh_provider_execution_count": UNIQUE_REQUEST_COUNT,
        "fresh_native_solver_execution_count": UNIQUE_REQUEST_COUNT,
        "cache_reuse_count": 0,
        "native_invocation_count": 1,
        "native_retry_count": 0,
        "mpb_execution": True,
        "dataset_record_count": UNIQUE_REQUEST_COUNT,
        "completion_state": "COMPLETE",
    }
    load_scientific_job().atomic_json(BINDING_PATH, value)


def acquire() -> dict[str, Any]:
    domain, graph, plan = verify_frozen_inputs()
    runtime = load_runtime()
    scientific_job = load_scientific_job()
    source_commit = current_source_commit()
    verify_runtime(scientific_job, runtime)
    entrypoint_sha = sha256_file(Path(__file__))
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": "E9F_D3_FR04_R64_SHARED_ACQUISITION",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        "resolution": RESOLUTION,
        "fr": FR,
        "domain_list_sha256": DOMAIN_LIST_SHA256,
        "graph_sha256": GRAPH_SHA256,
        "science_runtime_sha256": RUNTIME_SHA256,
        "source_model_identity": SOURCE_MODEL_IDENTITY,
    }
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    if store.root.exists() or BINDING_PATH.exists():
        raise AcquisitionError("EXISTING_FR04_R64_STATE_RECONCILIATION_REQUIRED")
    solve = provider()
    counter = scientific_job.BudgetCounter(UNIQUE_REQUEST_COUNT, UNIQUE_REQUEST_COUNT)
    fresh = 0
    for item in plan:
        key = canonical_key(item["request_key"])
        payload_path, metadata_path = store._paths(key)
        if payload_path.exists() or metadata_path.exists():
            raise AcquisitionError("EXISTING_FR04_R64_STATE_RECONCILIATION_REQUIRED")
        counter.consume_provider()
        counter.consume_solver()
        try:
            snapshot = solve(item["request_key"])
            payload = runtime.encode_snapshot(snapshot)
            runtime.decode_snapshot(payload)
            store.put(key, payload, {"schema": "mephc-e9f-d3-r64-exact-key-record-v1", "key_sha256": sha256_bytes(key), **identity(item["request_key"])})
            del snapshot, payload
        except Exception as exc:
            raise AcquisitionError("FR04_R64_REQUEST_FAILED", f"{sha256_bytes(key)}:{type(exc).__name__}") from exc
        fresh += 1
    dataset = store.finalize(UNIQUE_REQUEST_COUNT, {
        "work_order_id": WORK_ORDER_ID, "source_commit": source_commit,
        "resolution": RESOLUTION, "fr": FR, "graph_sha256": GRAPH_SHA256,
        "domain_list_sha256": DOMAIN_LIST_SHA256, "science_runtime_sha256": RUNTIME_SHA256,
    })
    write_binding(dataset, source_commit, entrypoint_sha)
    result = {
        "schema": "mephc-e9f-d3-fr04-r64-shared-acquisition-v1",
        "result_schema": "mephc-e9f-d3-fr04-r64-shared-acquisition-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": source_commit,
        "origin_sandbox_sha": source_commit,
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "science_runtime_sha256": RUNTIME_SHA256,
        "execution_source_commit_status": "PASS",
        "domain_status": "PASS",
        "request_graph_status": "PASS",
        "fr": FR,
        "resolution": RESOLUTION,
        "retained_cell_count": RETAINED_CELL_COUNT,
        "logical_provider_demand_count": LOGICAL_DEMAND_COUNT,
        "unique_provider_request_count": UNIQUE_REQUEST_COUNT,
        "native_invocation_count": 1,
        "native_invocation_cost": 1,
        "provider_request_count": UNIQUE_REQUEST_COUNT,
        "cache_reuse_count": 0,
        "fresh_provider_execution_count": fresh,
        "fresh_native_solver_execution_count": fresh,
        "native_solves": fresh,
        "mpb_execution": True,
        "completed_key_count": UNIQUE_REQUEST_COUNT,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "FR04_R64_dataset_id": dataset["dataset_id"],
        "FR04_R64_dataset_manifest_sha256": dataset["manifest_sha256"],
        "FR04_R64_dataset_record_count": UNIQUE_REQUEST_COUNT,
        "FR04_R64_acquisition_source_commit": source_commit,
        "FR04_R64_entrypoint_sha256": entrypoint_sha,
        "FR04_R64_request_graph_sha256": GRAPH_SHA256,
        "FR04_R64_domain_list_sha256": DOMAIN_LIST_SHA256,
        "immutable_dataset_completion_state": "COMPLETE",
        "native_retry_count": 0,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "FR04_R64_COMPLETE_SHARED_DATASET_READY_FOR_SOLVER_FREE_THREE_BAND_QUALIFICATION_BERRY_AND_SOURCE_GRID_REDUCTION",
        "terminal": "E9F_D3_FR04_R64_SHARED_DATASET_ACQUIRED_READY_FOR_SOLVER_FREE_THREE_BAND_ANALYSIS",
    }
    payload = canonical(result)
    if len(payload) > MAX_SUCCESS_STDOUT_BYTES:
        raise AcquisitionError("SUCCESS_STDOUT_LIMIT_EXCEEDED")
    print("MEPHC_NATIVE_RESULT_JSON=" + payload.decode("utf-8"))
    return result


def run(arguments: Iterable[str] = ()) -> dict[str, Any]:
    if list(arguments):
        raise AcquisitionError("ENTRYPOINT_ARGUMENTS_FORBIDDEN")
    return acquire()


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except AcquisitionError as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-e9f-d3-fr04-r64-shared-acquisition-v1",
            "state": "failed", "error_code": exc.code, "detail": exc.detail[:1000],
            "terminal": "E9F_D3_FR04_R64_SHARED_ACQUISITION_FAIL_CLOSED_NO_NATIVE_RETRY",
        }).decode("utf-8"))
        raise SystemExit(2)
