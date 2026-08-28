"""Acquire the corrected FR0.4/R64 shared six-band state graph once."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_PATH = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
GRAPH_PATH = ROOT / "audit/e9f/d5_fr04_corrected_r64_request_graph.json"
D5R4_PATH = ROOT / "audit/e9f/d5r4_fr04_corrected_k_replay_reconciliation.json"
BINDING_PATH = ROOT / "audit/e9f/d6_fr04_r64_corrected_acquisition_binding.json"
GEOMETRY_PATH = ROOT / "audit/e9e/a_rounded_triangle_geometry.py"
EMBEDDING_PATH = ROOT / "audit/e9e/run_spectral_embedding.py"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
SCIENTIFIC_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"

WORK_ORDER_ID = "MEPHC-E9F-D6-FR04-R64-CORRECTED-SHARED-ACQUISITION-20260829-331"
BASE_SANDBOX_SHA = "e80ecf622c34248fd79134f89ac42e83c08d8771"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
DOMAIN_LIST_SHA256 = "df1e87976df1f435c075485dca2cebd9cf350b32376f8a6d5c61188df447d631"
GRAPH_SHA256 = "44ae0ce1cc56c169c499d6957700da40f7d3431f3c96dda68e8ab879d03533a0"
D5R4_SHA256 = "1593da439d89c1fedd2f79dbed6fcaaed68cee6d072547652ac8e90b8dbc072c"
D5R3_DATASET_ID = "02946988af3ef592d8a5390be2a48abac01b97f859b8368b0690655ab891e900"
D5R3_MANIFEST_SHA256 = "4a2896a3b1f9f76b4f9865ae7468fd3ea26ecaa81523b55e70218edb34a70c91"
GEOMETRY_BOUNDARY_DIGEST = "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71"
FR = 0.4
RESOLUTION = "R64"
RESOLUTION_VALUE = 64
RETAINED_CELL_COUNT = 641
LOGICAL_COUNT = 3205
UNIQUE_COUNT = 3205
ARC_SEGMENTS = 96
SOURCE_MODEL_IDENTITY = "E9E_FR04_ROUNDED_TRIANGLE_V1"
PROVIDER_CONFIGURATION_IDENTITY = "E9E_FR04_ROUNDED_TRIANGLE_R64_TE_PROVIDER_V1"
BAND_REQUEST_CONFIGURATION = "E9F_D6_FR04_R64_SIX_BAND_TE_LOCKED"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
NUM_BANDS = 6


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


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    os.replace(temporary, path)


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
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode or result.stdout.strip() != expected:
        raise AcquisitionError("EXECUTION_SOURCE_CHECKOUT_MISMATCH")
    return expected


def canonical_key(key: dict[str, Any]) -> bytes:
    expected = {
        "fr", "resolution", "canonical_k_coordinate_units_1_over_144",
        "source_model_identity", "analytic_geometry_boundary_digest",
        "arc_segments_per_corner", "provider_configuration_identity",
        "band_request_configuration", "h_representation",
    }
    if not isinstance(key, dict) or set(key) != expected:
        raise AcquisitionError("GRAPH_REQUEST_KEY_FIELDS_INVALID")
    coordinate = key.get("canonical_k_coordinate_units_1_over_144")
    if not isinstance(coordinate, dict) or set(coordinate) != {"i", "j"} or any(type(coordinate[item]) is not int for item in ("i", "j")):
        raise AcquisitionError("GRAPH_RATIONAL_COORDINATE_INVALID")
    if (key.get("fr") != FR or key.get("resolution") != RESOLUTION or key.get("source_model_identity") != SOURCE_MODEL_IDENTITY
            or key.get("analytic_geometry_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or key.get("arc_segments_per_corner") != ARC_SEGMENTS
            or key.get("provider_configuration_identity") != PROVIDER_CONFIGURATION_IDENTITY
            or key.get("band_request_configuration") != BAND_REQUEST_CONFIGURATION or key.get("h_representation") != H_REPRESENTATION):
        raise AcquisitionError("GRAPH_REQUEST_BINDING_INVALID")
    return canonical(key)


def verify_frozen_inputs() -> list[dict[str, Any]]:
    if sha256_file(DOMAIN_PATH) != "85f395e03c8d4ac1b73d2a1a5ef0c2bc083ac736ed59542809e10225edb3489f" or sha256_file(GRAPH_PATH) != GRAPH_SHA256 or sha256_file(D5R4_PATH) != D5R4_SHA256:
        raise AcquisitionError("FROZEN_INPUT_SHA256_MISMATCH")
    domain = read_json(DOMAIN_PATH)
    graph = read_json(GRAPH_PATH)
    reconciliation = read_json(D5R4_PATH)
    if domain.get("retained_cell_count") != RETAINED_CELL_COUNT or domain.get("domain_list_sha256") != DOMAIN_LIST_SHA256:
        raise AcquisitionError("D1_DOMAIN_INVALID")
    if (graph.get("logical_provider_demand_count") != LOGICAL_COUNT or graph.get("unique_provider_request_count") != UNIQUE_COUNT
            or graph.get("duplicate_logical_demand_count") != 0 or graph.get("collision_group_count") != 0
            or graph.get("coordinate_set_equal_to_d1") is not True or graph.get("source_model_identity") != SOURCE_MODEL_IDENTITY
            or graph.get("analytic_geometry_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or graph.get("arc_segments_per_corner") != ARC_SEGMENTS):
        raise AcquisitionError("CORRECTED_GRAPH_CONTENT_INVALID")
    if (reconciliation.get("d5r3_existing_validation_status") != "COMPLETE_NATIVE_RESULT_AND_DATASET_VERIFIED"
            or reconciliation.get("corrected_fr04_provider_validated") is not True
            or reconciliation.get("spectral_replay_pass") is not True
            or reconciliation.get("maximum_absolute_frequency_error") != 0.0):
        raise AcquisitionError("D5R4_RECONCILIATION_INVALID")
    requests = graph.get("unique_provider_requests")
    if not isinstance(requests, list) or len(requests) != UNIQUE_COUNT:
        raise AcquisitionError("CORRECTED_GRAPH_REQUEST_COUNT_INVALID")
    keys: set[bytes] = set()
    for item in requests:
        if not isinstance(item, dict):
            raise AcquisitionError("CORRECTED_GRAPH_REQUEST_INVALID")
        key_bytes = canonical_key(item.get("request_key"))
        if key_bytes in keys:
            raise AcquisitionError("CORRECTED_GRAPH_DUPLICATE_REQUEST")
        keys.add(key_bytes)
    return [item["request_key"] for item in requests]


def verify_geometry(embedding: Any, geometry: Any) -> dict[str, Any]:
    case = embedding.polygon_case(FR, ARC_SEGMENTS)
    direct = geometry.build_geometry(FR)
    if (case.get("f_r") != FR or case.get("arc_segments_per_corner") != ARC_SEGMENTS
            or case.get("analytic_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or direct.get("boundary_digest") != GEOMETRY_BOUNDARY_DIGEST
            or case.get("posthoc_area_rescale") is not False or case.get("c3_vertex_symmetry") is not True
            or case.get("public_cartesian_to_mpb_roundtrip_error", float("inf")) > 1.0e-12):
        raise AcquisitionError("CORRECT_GEOMETRY_BINDING_INVALID")
    return case


def verify_runtime(scientific_job: Any, runtime: Any) -> None:
    if scientific_job.runtime_hash(ROOT) != RUNTIME_SHA256:
        raise AcquisitionError("SCIENCE_RUNTIME_HASH_MISMATCH")
    certification = read_json(runtime._trusted_science_state_root() / "certifications" / f"{RUNTIME_SHA256}.json")
    smoke = certification.get("mpb_smoke", {})
    if certification.get("schema") != "mephc-science-runtime-certification-v1" or certification.get("runtime_sha256") != RUNTIME_SHA256 or smoke.get("executed") is not True or smoke.get("solver_executions") != 1:
        raise AcquisitionError("SCIENCE_RUNTIME_MPB_CERTIFICATION_INVALID")


def acquire() -> dict[str, Any]:
    requests = verify_frozen_inputs()
    sys.path.insert(0, str(ROOT))
    embedding = load_module("_mephc_d6_spectral_embedding", EMBEDDING_PATH)
    geometry = load_module("_mephc_d6_rounded_geometry", GEOMETRY_PATH)
    case = verify_geometry(embedding, geometry)
    source_commit = current_source_commit()
    runtime = load_module("_mephc_d6_science_runtime", RUNTIME_PATH)
    scientific_job = load_module("_mephc_d6_scientific_job", SCIENTIFIC_JOB_PATH)
    verify_runtime(scientific_job, runtime)
    state_root = runtime._trusted_science_state_root()
    namespace = {
        "project_id": "MEPHC", "science_contract_id": "E9F_D6_FR04_R64_CORRECTED_SHARED_ACQUISITION",
        "work_order_id": WORK_ORDER_ID, "source_commit": source_commit, "fr": FR, "resolution": RESOLUTION,
        "corrected_graph_sha256": GRAPH_SHA256, "domain_list_sha256": DOMAIN_LIST_SHA256,
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST, "arc_segments_per_corner": ARC_SEGMENTS,
        "source_model_identity": SOURCE_MODEL_IDENTITY, "science_runtime_sha256": RUNTIME_SHA256,
    }
    store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    key_bytes = [canonical_key(key) for key in requests]
    if store.root.exists() or BINDING_PATH.exists():
        raise AcquisitionError("EXISTING_D6_FR04_R64_STATE_RECONCILIATION_REQUIRED")
    checkpoint = store.root / "checkpoint.json"
    atomic_json(checkpoint, {"schema": "mephc-e9f-d6-fr04-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": 0, "failed_key_count": 0, "state": "RUNNING"})
    counter = scientific_job.BudgetCounter(UNIQUE_COUNT, UNIQUE_COUNT)
    import meep as mp
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

    provider = MPBLiveSpectralProvider(
        geometry=list(embedding.make_solver_geometry(case)), geometry_lattice=embedding.make_lattice(),
        resolution=RESOLUTION_VALUE, num_bands=NUM_BANDS, polarization=mp.TE,
        default_material=mp.Medium(epsilon=7.0225), eigensolver_tolerance=1.0e-7,
        deterministic=True, mesh_size=3,
    )
    completed = 0
    for request, key in zip(requests, key_bytes):
        key_sha = sha256_bytes(key)
        try:
            counter.consume_provider()
            counter.consume_solver()
            coordinate = request["canonical_k_coordinate_units_1_over_144"]
            snapshot = provider.solve((coordinate["i"] / 144.0, coordinate["j"] / 144.0))
            payload = runtime.encode_snapshot(snapshot)
            decoded = runtime.decode_snapshot(payload)
            if tuple(decoded.frequencies) != tuple(snapshot.frequencies):
                raise AcquisitionError("SNAPSHOT_ROUNDTRIP_MISMATCH")
            store.put(key, payload, {
                "schema": "mephc-e9f-d6-fr04-r64-corrected-record-v1", "key_sha256": key_sha,
                "canonical_k_coordinate_units_1_over_144": request["canonical_k_coordinate_units_1_over_144"],
                "fr": FR, "resolution": RESOLUTION, "source_model_identity": SOURCE_MODEL_IDENTITY,
                "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST, "arc_segments_per_corner": ARC_SEGMENTS,
                "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
                "band_request_configuration": BAND_REQUEST_CONFIGURATION, "h_representation": H_REPRESENTATION,
            })
            completed += 1
            del decoded, payload, snapshot
            atomic_json(checkpoint, {"schema": "mephc-e9f-d6-fr04-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 0, "last_key_sha256": key_sha, "state": "RUNNING"})
        except AcquisitionError:
            atomic_json(checkpoint, {"schema": "mephc-e9f-d6-fr04-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 1, "failed_key_sha256": key_sha, "state": "PARTIAL_CHECKPOINT_PRESERVED"})
            raise
        except Exception as exc:
            atomic_json(checkpoint, {"schema": "mephc-e9f-d6-fr04-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 1, "failed_key_sha256": key_sha, "failure_class": type(exc).__name__, "state": "PARTIAL_CHECKPOINT_PRESERVED"})
            raise AcquisitionError("D6_REQUEST_FAILED", f"{key_sha}:{type(exc).__name__}") from exc
    dataset = store.finalize(UNIQUE_COUNT, {
        "work_order_id": WORK_ORDER_ID, "source_commit": source_commit, "fr": FR, "resolution": RESOLUTION,
        "retained_cell_count": RETAINED_CELL_COUNT, "corrected_graph_sha256": GRAPH_SHA256,
        "domain_list_sha256": DOMAIN_LIST_SHA256, "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS, "source_model_identity": SOURCE_MODEL_IDENTITY,
        "science_runtime_sha256": RUNTIME_SHA256,
    })
    atomic_json(checkpoint, {"schema": "mephc-e9f-d6-fr04-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 0, "state": "COMPLETE"})
    entrypoint_sha = sha256_file(Path(__file__))
    binding = {
        "schema": "mephc-e9f-d6-fr04-r64-corrected-acquisition-binding-v1", "work_order_id": WORK_ORDER_ID,
        "acquisition_source_commit": source_commit, "acquisition_dataset_id": dataset["dataset_id"],
        "dataset_manifest_sha256": dataset["manifest_sha256"], "dataset_record_count": UNIQUE_COUNT,
        "entrypoint_sha256": entrypoint_sha, "science_runtime_sha256": RUNTIME_SHA256,
        "corrected_graph_sha256": GRAPH_SHA256, "domain_list_sha256": DOMAIN_LIST_SHA256,
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST, "arc_segments_per_corner": ARC_SEGMENTS,
        "source_model_identity": SOURCE_MODEL_IDENTITY, "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION, "resolution": RESOLUTION, "fr": FR,
        "logical_provider_demand_count": LOGICAL_COUNT, "unique_provider_request_count": UNIQUE_COUNT,
        "duplicate_logical_demand_count": 0, "collision_group_count": 0, "completed_key_count": completed,
        "failed_key_count": 0, "provider_failure_count": 0, "fresh_provider_execution_count": UNIQUE_COUNT,
        "cache_reuse_count": 0, "native_invocation_count": 1, "provider_request_count": UNIQUE_COUNT,
        "solver_executions": UNIQUE_COUNT, "native_solves": UNIQUE_COUNT, "mpb_execution": True,
        "native_retry_count": 0, "completion_state": "COMPLETE",
    }
    atomic_json(BINDING_PATH, binding)
    result = {
        "schema": "mephc-e9f-d6-fr04-r64-corrected-shared-acquisition-v1", "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": source_commit, "origin_sandbox_sha": source_commit,
        "main_sha": MAIN_SHA, "machine_contract_status": "PASS", "science_runtime_sha256": RUNTIME_SHA256,
        "execution_source_commit_status": "PASS", "corrected_graph_status": "PASS", "corrected_geometry_status": "PASS",
        "fr": FR, "resolution": RESOLUTION, "retained_cell_count": RETAINED_CELL_COUNT,
        "logical_provider_demand_count": LOGICAL_COUNT, "unique_provider_request_count": UNIQUE_COUNT,
        "native_invocation_count": 1, "provider_request_count": UNIQUE_COUNT, "cache_reuse_count": 0,
        "fresh_provider_execution_count": UNIQUE_COUNT, "solver_executions": UNIQUE_COUNT, "native_solves": UNIQUE_COUNT,
        "mpb_execution": True, "completed_key_count": completed, "failed_key_count": 0, "provider_failure_count": 0,
        "fr04_corrected_r64_dataset_id": dataset["dataset_id"], "fr04_corrected_r64_dataset_manifest_sha256": dataset["manifest_sha256"],
        "fr04_corrected_r64_dataset_record_count": UNIQUE_COUNT, "fr04_corrected_r64_acquisition_source_commit": source_commit,
        "fr04_corrected_r64_entrypoint_sha256": entrypoint_sha, "fr04_corrected_r64_request_graph_sha256": GRAPH_SHA256,
        "fr04_corrected_r64_domain_list_sha256": DOMAIN_LIST_SHA256, "fr04_corrected_r64_geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "fr04_corrected_r64_arc_segments_per_corner": ARC_SEGMENTS, "fr04_corrected_r64_source_model_identity": SOURCE_MODEL_IDENTITY,
        "immutable_dataset_completion_state": "COMPLETE", "dataset_is_mpb_backed": True, "native_retry_count": 0,
        "old_d3_dataset_reuse_authorized": False, "old_d4_result_reuse_authorized": False,
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "next_scientific_state": "CORRECTED_FR04_R64_COMPLETE_SHARED_DATASET_READY_FOR_SOLVER_FREE_THREE_BAND_QUALIFICATION_BERRY_AND_SOURCE_GRID_REDUCTION",
        "terminal": "E9F_D6_FR04_R64_CORRECTED_SHARED_DATASET_ACQUIRED",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + canonical(result).decode("utf-8"))
    return result


def run(arguments: list[str] | None = None) -> dict[str, Any]:
    if arguments:
        raise AcquisitionError("ENTRYPOINT_ARGUMENTS_FORBIDDEN")
    return acquire()


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except AcquisitionError as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-e9f-d6-fr04-r64-corrected-shared-acquisition-v1", "state": "failed",
            "error_code": exc.code, "detail": exc.detail[:1000],
            "terminal": "E9F_D6_FR04_R64_CORRECTED_SHARED_ACQUISITION_FAIL_CLOSED_NO_NATIVE_RETRY",
        }).decode("utf-8"))
        raise SystemExit(2)
