"""One bounded D9 Native acquisition for the ten residual composite cells."""
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GRAPH_PATH = ROOT / "audit/e9f/d9_fr04_residual_composite_request_graph.json"
BINDING_PATH = ROOT / "audit/e9f/d9_fr04_residual_composite_acquisition_binding.json"
D8_ASSESSMENT_PATH = ROOT / "audit/e9f/d8_fr04_composite_source_assessment.json"
D8_PROVENANCE_PATH = ROOT / "audit/e9f/d8_fr04_nonabelian_provenance_replay.json"
D8_RANK2_PATH = ROOT / "audit/e9f/d8_fr04_rank2_pair12_qualification_berry.json"
D8_RANK3_PATH = ROOT / "audit/e9f/d8_fr04_rank3_first3_qualification_berry.json"
DOMAIN_PATH = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
GEOMETRY_PATH = ROOT / "audit/e9e/a_rounded_triangle_geometry.py"
EMBEDDING_PATH = ROOT / "audit/e9e/run_spectral_embedding.py"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
SCIENTIFIC_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"

WORK_ORDER_ID = "MEPHC-E9F-D9-FR04-RESIDUAL-COMPOSITE-CONVERGENCE-ACQ-20260829-337"
BASE_SANDBOX_SHA = "5e6cac51f8f6932571db7d0b41cc70356b82d451"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
GEOMETRY_BOUNDARY_DIGEST = "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71"
SOURCE_MODEL_IDENTITY = "E9E_FR04_ROUNDED_TRIANGLE_V1"
BAND_REQUEST_CONFIGURATION = "E9F_D5_FR04_R64_SIX_BAND_TE_LOCKED"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
FR = 0.4
ARC_SEGMENTS = 96
NUM_BANDS = 6
EPSILON = 7.0225
MESH_SIZE = 3
EIGENSOLVER_TOLERANCE = 1.0e-7
RESOLUTIONS = (96, 128, 160, 192, 224, 256)
ODD_RESOLUTIONS = (96, 160, 224)
EVEN_RESOLUTIONS = (128, 192, 256)
TARGET_CELLS = ((-35, -16), (-35, -15), (-35, 15), (-35, 16), (-33, -17), (-33, 17), (-32, -17), (-32, 17), (-5, -1), (-5, 1))
REFINED_REPRESENTATIVES = ((-35, -16), (-35, -15), (-33, -17), (-32, -17), (-5, -1))
PRIMARY_H_DENOMINATOR = 144
REFINED_H_DENOMINATOR = 288
EXPECTED_REQUEST_COUNT = 420
D8_ASSESSMENT_SHA256 = "c3e3a2f301908a39210e8d674e8d6521739535ae9538d9dfb21da53ad853615b"
D8_PROVENANCE_SHA256 = "fbc6a4e789420e9de8e0e46535857ef32cb20cb9f4fc89c5570e9c09996b7356"
D8_RANK2_SHA256 = "fa5917b07c7e4fc7c2e6d923a6465b1549e3745538eab9501dca7da4f8a8ff12"
D8_RANK3_SHA256 = "3fac3d442b45d0dd389f804550304a8b8d5b40d52e3422e4cd0ab5793f9f56fd"


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
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise AcquisitionError("FILE_UNAVAILABLE", path.name) from exc


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
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AcquisitionError("MODULE_UNAVAILABLE", path.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def current_source_commit() -> str:
    expected = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    if len(expected) != 40 or result.returncode or result.stdout.strip() != expected:
        raise AcquisitionError("EXECUTION_SOURCE_CHECKOUT_MISMATCH")
    return expected


def d8_inputs() -> None:
    expected = ((D8_ASSESSMENT_PATH, D8_ASSESSMENT_SHA256), (D8_PROVENANCE_PATH, D8_PROVENANCE_SHA256), (D8_RANK2_PATH, D8_RANK2_SHA256), (D8_RANK3_PATH, D8_RANK3_SHA256))
    if any(sha256_file(path) != digest for path, digest in expected):
        raise AcquisitionError("D8_ARTIFACT_BYTE_HASH_MISMATCH")
    assessment, provenance, rank2, rank3 = (read_json(path) for path, _ in expected)
    if assessment.get("terminal") != "E9F_D8_FR04_R64_COMPOSITE_SUBSPACE_ASSESSMENT_COMPLETE" or provenance.get("status") != "PASS_EXACT_ACCEPTED_IMPLEMENTATION_REPLAY":
        raise AcquisitionError("D8_ACCEPTED_EVIDENCE_INVALID")
    failed = assessment.get("d7_failure_set_reconciliation", {})
    if failed.get("band1_band2_failure_intersection_count") != 100 or failed.get("band1_only_failure_count") != 0 or failed.get("band2_only_failure_count") != 10:
        raise AcquisitionError("D8_RESIDUAL_SET_INVALID")
    expected_residuals = {"fr=0.4;grid_i=-35;grid_j=-16;estimator=SOURCE_GRID", "fr=0.4;grid_i=-35;grid_j=-15;estimator=SOURCE_GRID", "fr=0.4;grid_i=-35;grid_j=15;estimator=SOURCE_GRID", "fr=0.4;grid_i=-35;grid_j=16;estimator=SOURCE_GRID", "fr=0.4;grid_i=-33;grid_j=-17;estimator=SOURCE_GRID", "fr=0.4;grid_i=-33;grid_j=17;estimator=SOURCE_GRID", "fr=0.4;grid_i=-32;grid_j=-17;estimator=SOURCE_GRID", "fr=0.4;grid_i=-32;grid_j=17;estimator=SOURCE_GRID", "fr=0.4;grid_i=-5;grid_j=-1;estimator=SOURCE_GRID", "fr=0.4;grid_i=-5;grid_j=1;estimator=SOURCE_GRID"}
    if set(failed.get("d8_residual_failed_sample_ids", [])) not in (expected_residuals, set()):
        residual = set(failed.get("band2_only_failure_sample_ids", []))
        if residual != expected_residuals:
            raise AcquisitionError("D8_RESIDUAL_SAMPLE_SET_INVALID")
    if rank2.get("summary", {}).get("not_reported_count") != 10 or rank3.get("summary", {}).get("not_reported_count") != 10:
        raise AcquisitionError("D8_RESIDUAL_QUALIFICATION_INVALID")


def request_key(cell: tuple[int, int], resolution: int, role: str, denominator: int, offset: tuple[int, int]) -> dict[str, Any]:
    return {
        "fr": FR, "resolution": f"R{resolution}", "resolution_value": resolution,
        "canonical_k_coordinate": {"numerator": [denominator * cell[0] // 36 + offset[0], denominator * cell[1] // 36 + offset[1]], "denominator": denominator},
        "canonical_k_coordinate_units_1_over_288": {"i": 8 * cell[0] + offset[0] * (2 if denominator == PRIMARY_H_DENOMINATOR else 1), "j": 8 * cell[1] + offset[1] * (2 if denominator == PRIMARY_H_DENOMINATOR else 1)},
        "stencil_role": role, "parent_cell_index": [cell[0], cell[1]], "stencil_h": f"1/{denominator}",
        "source_model_identity": SOURCE_MODEL_IDENTITY, "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS, "band_request_configuration": BAND_REQUEST_CONFIGURATION,
        "h_representation": H_REPRESENTATION,
    }


def generate_graph(source_commit: str | None = None) -> dict[str, Any]:
    source_commit = source_commit or current_source_commit()
    requests: list[dict[str, Any]] = []
    roles = (("CENTER", (0, 0)), ("PLUS_X", (1, 0)), ("MINUS_X", (-1, 0)), ("PLUS_Y", (0, 1)), ("MINUS_Y", (0, -1)))
    for cell in TARGET_CELLS:
        for resolution in RESOLUTIONS:
            for role, offset in roles:
                requests.append({"request_key": request_key(cell, resolution, role, PRIMARY_H_DENOMINATOR, offset), "request_class": "primary"})
    refined_set = set(REFINED_REPRESENTATIVES)
    for cell in REFINED_REPRESENTATIVES:
        for resolution in RESOLUTIONS:
            for role, offset in (("PLUS_X_288", (1, 0)), ("MINUS_X_288", (-1, 0)), ("PLUS_Y_288", (0, 1)), ("MINUS_Y_288", (0, -1))):
                requests.append({"request_key": request_key(cell, resolution, role, REFINED_H_DENOMINATOR, offset), "request_class": "refined"})
    if len(requests) != EXPECTED_REQUEST_COUNT or len({canonical(item["request_key"]) for item in requests}) != EXPECTED_REQUEST_COUNT or not refined_set:
        raise AcquisitionError("D9_REQUEST_GRAPH_CARDINALITY_INVALID")
    graph = {"schema": "mephc-e9f-d9-fr04-residual-composite-request-graph-v1", "work_order_id": WORK_ORDER_ID, "source_commit": source_commit, "fr": FR, "target_cells": [list(cell) for cell in TARGET_CELLS], "refined_stencil_representatives": [list(cell) for cell in REFINED_REPRESENTATIVES], "resolutions": list(RESOLUTIONS), "odd_resolution_class": list(ODD_RESOLUTIONS), "even_resolution_class": list(EVEN_RESOLUTIONS), "primary_stencil": "1/144", "refined_stencil": "1/288", "logical_provider_demand_count": EXPECTED_REQUEST_COUNT, "unique_provider_request_count": EXPECTED_REQUEST_COUNT, "duplicate_provider_request_count": 0, "collision_group_count": 0, "unique_provider_requests": requests}
    if GRAPH_PATH.is_file():
        existing = read_json(GRAPH_PATH)
        if canonical(existing) != canonical(graph):
            raise AcquisitionError("D9_REQUEST_GRAPH_MISMATCH")
    else:
        atomic_json(GRAPH_PATH, graph)
    return graph


def verify_geometry(embedding: Any, geometry: Any) -> dict[str, Any]:
    case = embedding.polygon_case(FR, ARC_SEGMENTS)
    direct = geometry.build_geometry(FR)
    if case.get("analytic_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or direct.get("boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or case.get("posthoc_area_rescale") is not False or case.get("c3_vertex_symmetry") is not True:
        raise AcquisitionError("CORRECT_GEOMETRY_BINDING_INVALID")
    return case


def verify_runtime(scientific_job: Any, runtime: Any) -> None:
    if scientific_job.runtime_hash(ROOT) != RUNTIME_SHA256:
        raise AcquisitionError("SCIENCE_RUNTIME_HASH_MISMATCH")
    cert = read_json(runtime._trusted_science_state_root() / "certifications" / f"{RUNTIME_SHA256}.json")
    if cert.get("schema") != "mephc-science-runtime-certification-v1" or cert.get("runtime_sha256") != RUNTIME_SHA256 or cert.get("mpb_smoke", {}).get("executed") is not True:
        raise AcquisitionError("SCIENCE_RUNTIME_CERTIFICATION_INVALID")


def acquire() -> dict[str, Any]:
    source_commit = current_source_commit()
    d8_inputs()
    graph = generate_graph(source_commit)
    embedding = load_module("_mephc_d9_spectral_embedding", EMBEDDING_PATH)
    geometry = load_module("_mephc_d9_rounded_geometry", GEOMETRY_PATH)
    case = verify_geometry(embedding, geometry)
    runtime = load_module("_mephc_d9_science_runtime", RUNTIME_PATH)
    scientific_job = load_module("_mephc_d9_scientific_job", SCIENTIFIC_JOB_PATH)
    verify_runtime(scientific_job, runtime)
    state_root = runtime._trusted_science_state_root()
    namespace = {"project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID, "work_order_id": WORK_ORDER_ID, "source_commit": source_commit, "fr": FR, "resolutions": list(RESOLUTIONS), "target_cells": [list(cell) for cell in TARGET_CELLS], "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST, "arc_segments_per_corner": ARC_SEGMENTS, "source_model_identity": SOURCE_MODEL_IDENTITY, "band_request_configuration": BAND_REQUEST_CONFIGURATION, "science_runtime_sha256": RUNTIME_SHA256}
    store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    checkpoint = store.root / "checkpoint.json"
    if store.root.exists() or BINDING_PATH.exists():
        raise AcquisitionError("EXISTING_D9_RESIDUAL_CONVERGENCE_STATE_RECONCILIATION_REQUIRED")
    atomic_json(checkpoint, {"schema": "mephc-e9f-d9-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": 0, "failed_key_count": 0, "state": "RUNNING"})
    counter = scientific_job.BudgetCounter(EXPECTED_REQUEST_COUNT, EXPECTED_REQUEST_COUNT)
    import meep as mp
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    provider = MPBLiveSpectralProvider(geometry=list(embedding.make_solver_geometry(case)), geometry_lattice=embedding.make_lattice(), resolution=RESOLUTIONS[0], num_bands=NUM_BANDS, polarization=mp.TE, default_material=mp.Medium(epsilon=EPSILON), eigensolver_tolerance=EIGENSOLVER_TOLERANCE, deterministic=True, mesh_size=MESH_SIZE)
    completed = 0
    for item in graph["unique_provider_requests"]:
        key = item["request_key"]
        key_bytes = canonical(key)
        key_sha = sha256_bytes(key_bytes)
        try:
            counter.consume_provider(); counter.consume_solver()
            coordinate = key["canonical_k_coordinate"]; denominator = int(coordinate["denominator"])
            q = tuple(float(value) / denominator for value in coordinate["numerator"])
            provider.resolution = int(key["resolution_value"])
            snapshot = provider.solve(q)
            payload = runtime.encode_snapshot(snapshot)
            decoded = runtime.decode_snapshot(payload)
            if tuple(decoded.k_point) != q or len(decoded.frequencies) != NUM_BANDS:
                raise AcquisitionError("SNAPSHOT_ROUNDTRIP_MISMATCH")
            metadata = {"schema": "mephc-e9f-d9-residual-composite-record-v1", "key_sha256": key_sha, "identity": key, "k_point": list(q), "resolution": key["resolution"], "stencil_role": key["stencil_role"], "h_representation": H_REPRESENTATION}
            store.put(key_bytes, payload, metadata)
            completed += 1
            del decoded, payload, snapshot
            atomic_json(checkpoint, {"schema": "mephc-e9f-d9-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 0, "last_key_sha256": key_sha, "state": "RUNNING"})
        except AcquisitionError:
            atomic_json(checkpoint, {"schema": "mephc-e9f-d9-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 1, "failed_key_sha256": key_sha, "state": "PARTIAL_CHECKPOINT_PRESERVED"})
            raise
        except Exception as exc:
            atomic_json(checkpoint, {"schema": "mephc-e9f-d9-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 1, "failed_key_sha256": key_sha, "failure_class": type(exc).__name__, "state": "PARTIAL_CHECKPOINT_PRESERVED"})
            raise AcquisitionError("D9_REQUEST_FAILED", f"{key_sha}:{type(exc).__name__}") from exc
    dataset = store.finalize(EXPECTED_REQUEST_COUNT, {"work_order_id": WORK_ORDER_ID, "source_commit": source_commit, "fr": FR, "target_cell_count": len(TARGET_CELLS), "refined_stencil_representative_count": len(REFINED_REPRESENTATIVES), "resolutions": list(RESOLUTIONS), "odd_resolution_class": list(ODD_RESOLUTIONS), "even_resolution_class": list(EVEN_RESOLUTIONS), "request_graph_sha256": sha256_file(GRAPH_PATH), "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST, "source_model_identity": SOURCE_MODEL_IDENTITY, "band_request_configuration": BAND_REQUEST_CONFIGURATION, "science_runtime_sha256": RUNTIME_SHA256})
    atomic_json(checkpoint, {"schema": "mephc-e9f-d9-checkpoint-v1", "work_order_id": WORK_ORDER_ID, "completed_key_count": completed, "failed_key_count": 0, "state": "COMPLETE"})
    entrypoint_sha = sha256_file(Path(__file__))
    graph_sha = sha256_file(GRAPH_PATH)
    binding = {"schema": "mephc-e9f-d9-fr04-residual-composite-acquisition-binding-v1", "work_order_id": WORK_ORDER_ID, "acquisition_source_commit": source_commit, "dataset_id": dataset["dataset_id"], "dataset_manifest_sha256": dataset["manifest_sha256"], "dataset_record_count": EXPECTED_REQUEST_COUNT, "entrypoint_sha256": entrypoint_sha, "request_graph_sha256": graph_sha, "science_runtime_sha256": RUNTIME_SHA256, "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST, "source_model_identity": SOURCE_MODEL_IDENTITY, "band_request_configuration": BAND_REQUEST_CONFIGURATION, "target_cell_count": len(TARGET_CELLS), "refined_stencil_representative_count": len(REFINED_REPRESENTATIVES), "logical_provider_demand_count": EXPECTED_REQUEST_COUNT, "unique_provider_request_count": EXPECTED_REQUEST_COUNT, "duplicate_provider_request_count": 0, "collision_group_count": 0, "completed_key_count": completed, "failed_key_count": 0, "provider_failure_count": 0, "fresh_provider_execution_count": EXPECTED_REQUEST_COUNT, "cache_reuse_count": 0, "native_invocation_count": 1, "provider_request_count": EXPECTED_REQUEST_COUNT, "solver_executions": EXPECTED_REQUEST_COUNT, "native_solves": EXPECTED_REQUEST_COUNT, "mpb_execution": True, "native_retry_count": 0, "completion_state": "COMPLETE"}
    atomic_json(BINDING_PATH, binding)
    result = {"schema": "mephc-e9f-d9-fr04-residual-composite-convergence-acquisition-v1", "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": source_commit, "origin_sandbox_sha": source_commit, "main_sha": MAIN_SHA, "machine_contract_status": "PASS", "execution_source_commit": source_commit, "science_runtime_sha256": RUNTIME_SHA256, "target_cell_count": len(TARGET_CELLS), "refined_stencil_representative_count": len(REFINED_REPRESENTATIVES), "odd_resolution_class": list(ODD_RESOLUTIONS), "even_resolution_class": list(EVEN_RESOLUTIONS), "logical_provider_demand_count": EXPECTED_REQUEST_COUNT, "unique_provider_request_count": EXPECTED_REQUEST_COUNT, "native_invocation_count": 1, "provider_request_count": EXPECTED_REQUEST_COUNT, "fresh_provider_execution_count": EXPECTED_REQUEST_COUNT, "solver_executions": EXPECTED_REQUEST_COUNT, "native_solves": EXPECTED_REQUEST_COUNT, "completed_key_count": completed, "failed_key_count": 0, "cache_reuse_count": 0, "mpb_execution": True, "d9_dataset_id": dataset["dataset_id"], "d9_dataset_manifest_sha256": dataset["manifest_sha256"], "d9_dataset_record_count": EXPECTED_REQUEST_COUNT, "d9_acquisition_source_commit": source_commit, "d9_entrypoint_sha256": entrypoint_sha, "d9_request_graph_sha256": graph_sha, "native_retry_count": 0, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False, "next_scientific_state": "FR04_RESIDUAL_COMPOSITE_10_CELL_MULTIRESOLUTION_DATASET_READY_FOR_SOLVER_FREE_CONVERGENCE_AND_METHOD_VALIDATION", "terminal": "E9F_D9_FR04_RESIDUAL_COMPOSITE_CONVERGENCE_DATASET_ACQUIRED"}
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
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({"schema": "mephc-e9f-d9-fr04-residual-composite-convergence-acquisition-v1", "state": "failed", "error_code": exc.code, "detail": exc.detail[:1000], "native_invocation_count": 1, "provider_request_count": 0, "solver_executions": 0, "mpb_execution": False, "terminal": "E9F_D9_FR04_RESIDUAL_COMPOSITE_CONVERGENCE_ACQUISITION_FAIL_CLOSED_NO_NATIVE_RETRY", "work_order_id": WORK_ORDER_ID}).decode("utf-8"))
        raise SystemExit(2)
