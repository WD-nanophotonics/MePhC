"""Validate the corrected rounded-triangle source binding at one public k point."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DOMAIN_PATH = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
OLD_GRAPH_PATH = ROOT / "audit/e9f/d1_fr04_r64_request_graph.json"
INCIDENT_PATH = ROOT / "audit/e9f/d5_fr04_source_binding_incident.json"
GRAPH_PATH = ROOT / "audit/e9f/d5_fr04_corrected_r64_request_graph.json"
BINDING_PATH = ROOT / "audit/e9f/d5_fr04_source_binding_validation_binding.json"
DIAGNOSIS_PATH = ROOT / "audit/e9f/d5r1_fr04_precheck_diagnosis.json"
GEOMETRY_PATH = ROOT / "audit/e9e/a_rounded_triangle_geometry.py"
EMBEDDING_PATH = ROOT / "audit/e9e/run_spectral_embedding.py"
REFERENCE_PATH = ROOT / "audit/e9e/b_spectral_embedding_result.json"
OLD_ENTRYPOINT_PATH = ROOT / "audit/e9f/d3_fr04_r64_shared_acquisition.py"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
SCIENTIFIC_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"

WORK_ORDER_ID = "MEPHC-E9F-D5-FR04-SOURCE-BINDING-CORRECTIVE-20260829-326"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
BASE_SANDBOX_SHA = "b2f534baa0ba668efd580be439abf7efe12f82b4"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
DOMAIN_LIST_SHA256 = "df1e87976df1f435c075485dca2cebd9cf350b32376f8a6d5c61188df447d631"
GEOMETRY_BOUNDARY_DIGEST = "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71"
FR = 0.4
RESOLUTION = "R64"
RESOLUTION_VALUE = 64
ARC_SEGMENTS = 96
PUBLIC_K = (2.0 / 3.0, 0.0)
NUM_BANDS = 6
SPECTRAL_ATOL = 1.0e-7
SOURCE_MODEL_IDENTITY = "E9E_FR04_ROUNDED_TRIANGLE_V1"
PROVIDER_CONFIGURATION_IDENTITY = "E9E_FR04_ROUNDED_TRIANGLE_R64_TE_PROVIDER_V1"
BAND_REQUEST_CONFIGURATION = "E9F_D5_FR04_R64_SIX_BAND_TE_LOCKED"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
D5R1_WORK_ORDER_ID = "MEPHC-E9F-D5R1-FR04-PRECHECK-REPAIR-20260829-327"
D5R1_BASE_SANDBOX_SHA = "47862ced1a4b769acf4a1f096ca1794febfae475"
D5R1_GRAPH_SHA256 = "44ae0ce1cc56c169c499d6957700da40f7d3431f3c96dda68e8ab879d03533a0"
D5R1_INCIDENT_SHA256 = "00796dd1ed484b7ed279849caa068600e30027ed9518a539e3a59786390c090d"
ORIGINAL_D5_WORK_ORDER_ID = "MEPHC-E9F-D5-FR04-SOURCE-BINDING-CORRECTIVE-20260829-326"


class ValidationError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("JSON_UNAVAILABLE", path.name) from exc
    if not isinstance(value, dict):
        raise ValidationError("JSON_OBJECT_REQUIRED", path.name)
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
        raise ValidationError("MODULE_UNAVAILABLE", path.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def current_source_commit() -> str:
    expected = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    if len(expected) != 40 or any(char not in "0123456789abcdef" for char in expected):
        raise ValidationError("EXECUTION_SOURCE_COMMIT_INVALID")
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    actual = result.stdout.strip()
    if result.returncode or actual != expected:
        raise ValidationError("EXECUTION_SOURCE_CHECKOUT_MISMATCH")
    return expected


def corrected_key(original: dict[str, Any]) -> dict[str, Any]:
    coordinate = original.get("canonical_k_coordinate_units_1_over_144")
    if not isinstance(coordinate, dict) or set(coordinate) != {"i", "j"}:
        raise ValidationError("D1_COORDINATE_INVALID")
    if any(type(coordinate[item]) is not int for item in ("i", "j")):
        raise ValidationError("D1_COORDINATE_INVALID")
    return {
        "fr": FR,
        "resolution": RESOLUTION,
        "canonical_k_coordinate_units_1_over_144": {"i": coordinate["i"], "j": coordinate["j"]},
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "analytic_geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION,
        "h_representation": H_REPRESENTATION,
    }


def build_incident() -> dict[str, Any]:
    old_text = OLD_ENTRYPOINT_PATH.read_text(encoding="utf-8")
    checks = {
        "old_entrypoint_imports_e9c_provider": '"audit/e9c/run_k_kprime_rank1_berry.py"' in old_text,
        "old_provider_calls_geometry_inputs": "source.geometry_inputs()" in old_text,
        "old_provider_calls_build_inputs": "source.build_inputs(geometry)" in old_text,
        "old_fr_label_is_not_provider_geometry_binding": "fr=0.4" in old_text and "geometry_inputs" in old_text,
    }
    if not all(checks.values()):
        raise ValidationError("OLD_D3_MISBIND_MECHANICAL_CHECK_FAILED")
    return {
        "schema": "mephc-e9f-d5-fr04-source-binding-incident-v1",
        "work_order_id": WORK_ORDER_ID,
        "incident_id": "SCI-FR04-SOURCE-BIND-001",
        "classification": "WRONG_SOURCE_GEOMETRY_MISBOUND_FR04_LABEL",
        "d3_dataset_id": "57c9b6bc0775ef76951cc63518b29c2b4bcc9db8665337be0607d4393bfcb6ec",
        "d3_dataset_manifest_sha256": "3e5146c6c988f5d5eacef2d102188f14694d8f3d09fa9b62198064e06f207707",
        "d4_invalidated_result_sha256": "879e2edbed8b83559d6433c22a07c376d91e4a7a114e72a5eff171dc721a23a1",
        "old_d3_dataset_reuse_authorized": False,
        "old_d3_dataset_mutation_authorized": False,
        "old_d3_dataset_deletion_authorized": False,
        "d4_artifacts_immutable_preservation_required": True,
        "mechanical_old_provider_checks": checks,
        "old_provider_source_path": "audit/e9c/run_k_kprime_rank1_berry.py",
        "old_provider_geometry_calls": ["geometry_inputs", "build_inputs"],
        "correct_source_model_identity": SOURCE_MODEL_IDENTITY,
        "correct_geometry_module": "audit/e9e/a_rounded_triangle_geometry.py",
        "correct_embedding_module": "audit/e9e/run_spectral_embedding.py",
        "correct_geometry_build_rule": "polygon_case(0.4,96) -> make_solver_geometry(case)",
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "preservation_status": "OLD_D3_DATASET_AND_D4_ARTIFACTS_PRESERVED_BYTE_FOR_BYTE",
    }


def build_corrected_graph() -> dict[str, Any]:
    domain = read_json(DOMAIN_PATH)
    old_graph = read_json(OLD_GRAPH_PATH)
    if (sha256_file(DOMAIN_PATH) != "85f395e03c8d4ac1b73d2a1a5ef0c2bc083ac736ed59542809e10225edb3489f"
            or domain.get("domain_list_sha256") != DOMAIN_LIST_SHA256
            or domain.get("retained_cell_count") != 641):
        raise ValidationError("D1_DOMAIN_INVALID")
    old_demands = old_graph.get("logical_demands")
    old_unique = old_graph.get("unique_provider_requests")
    if not isinstance(old_demands, list) or not isinstance(old_unique, list) or len(old_demands) != 3205 or len(old_unique) != 3205:
        raise ValidationError("D1_GRAPH_COUNT_INVALID")

    def convert(item: dict[str, Any]) -> dict[str, Any]:
        key = corrected_key(item.get("request_key", {}))
        result = dict(item)
        result["request_key"] = key
        return result

    logical = [convert(item) for item in old_demands]
    unique = [convert(item) for item in old_unique]
    key_bytes = [canonical(item["request_key"]) for item in unique]
    if len(set(key_bytes)) != 3205:
        raise ValidationError("CORRECTED_GRAPH_DUPLICATE_REQUEST")
    old_coordinates = {
        (item["request_key"]["canonical_k_coordinate_units_1_over_144"]["i"], item["request_key"]["canonical_k_coordinate_units_1_over_144"]["j"])
        for item in old_unique
    }
    new_coordinates = {
        (item["request_key"]["canonical_k_coordinate_units_1_over_144"]["i"], item["request_key"]["canonical_k_coordinate_units_1_over_144"]["j"])
        for item in unique
    }
    if old_coordinates != new_coordinates:
        raise ValidationError("CORRECTED_GRAPH_COORDINATE_SET_MISMATCH")
    return {
        "schema": "mephc-e9f-d5-fr04-corrected-r64-request-graph-v1",
        "work_order_id": WORK_ORDER_ID,
        "fr": FR,
        "resolution": RESOLUTION,
        "retained_cell_count": 641,
        "domain_list_sha256": DOMAIN_LIST_SHA256,
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "analytic_geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION,
        "h_representation": H_REPRESENTATION,
        "logical_provider_demand_count": len(logical),
        "unique_provider_request_count": len(unique),
        "duplicate_logical_demand_count": 0,
        "collision_group_count": 0,
        "coordinate_set_equal_to_d1": True,
        "mechanically_verified": True,
        "logical_demands": logical,
        "unique_provider_requests": unique,
    }


def prepare_artifacts() -> None:
    incident = build_incident()
    graph = build_corrected_graph()
    atomic_json(INCIDENT_PATH, incident)
    atomic_json(GRAPH_PATH, graph)


def verify_pre_execution_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    incident = read_json(INCIDENT_PATH)
    graph = read_json(GRAPH_PATH)
    if incident != build_incident() or graph != build_corrected_graph():
        raise ValidationError("PRE_EXECUTION_ARTIFACT_MISMATCH")
    return incident, graph


def verify_geometry_and_reference() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    sys.path.insert(0, str(ROOT))
    embedding = load_module("_mephc_d5_spectral_embedding", EMBEDDING_PATH)
    geometry = load_module("_mephc_d5_rounded_geometry", GEOMETRY_PATH)
    case = embedding.polygon_case(FR, ARC_SEGMENTS)
    if (case.get("f_r") != FR or case.get("arc_segments_per_corner") != ARC_SEGMENTS
            or case.get("analytic_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST
            or case.get("posthoc_area_rescale") is not False
            or case.get("c3_vertex_symmetry") is not True
            or case.get("public_cartesian_to_mpb_roundtrip_error", math.inf) > 1.0e-12):
        raise ValidationError("CORRECT_GEOMETRY_BINDING_INVALID")
    direct = geometry.build_geometry(FR)
    if direct.get("boundary_digest") != GEOMETRY_BOUNDARY_DIGEST:
        raise ValidationError("CORRECT_GEOMETRY_DIGEST_INVALID")
    reference = read_json(REFERENCE_PATH)
    expected = reference.get("results", {}).get("FR0P4_R64_TESS96", {})
    frequencies = expected.get("frequencies")
    if not isinstance(frequencies, list) or len(frequencies) != NUM_BANDS or not all(math.isfinite(float(item)) for item in frequencies):
        raise ValidationError("ACCEPTED_SPECTRAL_REFERENCE_INVALID")
    return embedding, case, {"reference": reference, "expected_frequencies": [float(item) for item in frequencies]}


def load_runtime() -> Any:
    return load_module("_mephc_d5_science_runtime", RUNTIME_PATH)


def load_scientific_job() -> Any:
    return load_module("_mephc_d5_scientific_job", SCIENTIFIC_JOB_PATH)


def initial_acquire() -> dict[str, Any]:
    verify_pre_execution_artifacts()
    embedding, case, reference = verify_geometry_and_reference()
    source_commit = current_source_commit()
    runtime = load_runtime()
    scientific_job = load_scientific_job()
    if scientific_job.runtime_hash(ROOT) != RUNTIME_SHA256:
        raise ValidationError("SCIENCE_RUNTIME_HASH_MISMATCH")
    state_root = runtime._trusted_science_state_root()
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": "E9F_D5_FR04_SOURCE_BINDING_VALIDATION",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        "fr": FR,
        "resolution": RESOLUTION,
        "validation_point": "PUBLIC_K",
        "validation_q": {"i": 96, "j": 0, "denominator": 144},
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "science_runtime_sha256": RUNTIME_SHA256,
        "reference_artifact_sha256": sha256_file(REFERENCE_PATH),
    }
    store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    if store.root.exists() or BINDING_PATH.exists():
        raise ValidationError("D5_VALIDATION_DATASET_ALREADY_EXISTS")
    import meep as mp
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

    lattice = embedding.make_lattice()
    provider = MPBLiveSpectralProvider(
        geometry=list(embedding.make_solver_geometry(case)),
        geometry_lattice=lattice,
        resolution=RESOLUTION_VALUE,
        num_bands=NUM_BANDS,
        polarization=mp.TE,
        default_material=mp.Medium(epsilon=7.0225),
        eigensolver_tolerance=1.0e-7,
        deterministic=True,
        mesh_size=3,
    )
    snapshot = provider.solve(PUBLIC_K)
    actual = [float(item) for item in snapshot.frequencies]
    if len(actual) != NUM_BANDS or not all(math.isfinite(item) for item in actual):
        raise ValidationError("SPECTRAL_REPLAY_NONFINITE")
    errors = [abs(actual[i] - reference["expected_frequencies"][i]) for i in range(NUM_BANDS)]
    replay_pass = all(error <= SPECTRAL_ATOL for error in errors)
    gap01 = actual[1] - actual[0]
    gap12 = actual[2] - actual[1]
    if not replay_pass or gap12 >= 0.02:
        raise ValidationError("SPECTRAL_REPLAY_FAIL_CLOSED")
    payload = runtime.encode_snapshot(snapshot)
    decoded = runtime.decode_snapshot(payload)
    if tuple(float(item) for item in decoded.frequencies) != tuple(actual):
        raise ValidationError("VALIDATION_SNAPSHOT_ROUNDTRIP_MISMATCH")
    key = canonical({"validation_point": "PUBLIC_K", "q": {"i": 96, "j": 0, "denominator": 144}})
    store.put(key, payload, {
        "schema": "mephc-e9f-d5-fr04-source-binding-validation-record-v1",
        "validation_point": "PUBLIC_K",
        "canonical_k_coordinate_units_1_over_144": {"i": 96, "j": 0},
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "resolution": RESOLUTION,
        "h_representation": H_REPRESENTATION,
    })
    dataset = store.finalize(1, {
        "work_order_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        "fr": FR,
        "resolution": RESOLUTION,
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "reference_artifact_sha256": sha256_file(REFERENCE_PATH),
        "spectral_replay_pass": True,
    })
    entrypoint_sha = sha256_file(Path(__file__))
    binding = {
        "schema": "mephc-e9f-d5-fr04-source-binding-validation-binding-v1",
        "work_order_id": WORK_ORDER_ID,
        "acquisition_source_commit": source_commit,
        "acquisition_dataset_id": dataset["dataset_id"],
        "dataset_manifest_sha256": dataset["manifest_sha256"],
        "entrypoint_sha256": entrypoint_sha,
        "correct_geometry_module": "audit/e9e/a_rounded_triangle_geometry.py",
        "correct_embedding_module": "audit/e9e/run_spectral_embedding.py",
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "provider_configuration_identity": PROVIDER_CONFIGURATION_IDENTITY,
        "band_request_configuration": BAND_REQUEST_CONFIGURATION,
        "resolution": RESOLUTION,
        "fr": FR,
        "validation_point": "PUBLIC_K",
        "validation_q": {"i": 96, "j": 0, "denominator": 144},
        "reference_artifact_sha256": sha256_file(REFERENCE_PATH),
        "reference_case": "FR0P4_R64_TESS96",
        "actual_frequencies": actual,
        "reference_frequencies": reference["expected_frequencies"],
        "absolute_errors": errors,
        "spectral_replay_pass": True,
        "k_gap_band0_band1": gap01,
        "k_gap_band1_band2": gap12,
        "dataset_record_count": 1,
        "native_invocation_count": 1,
        "provider_request_count": 1,
        "solver_executions": 1,
        "mpb_execution": True,
        "native_retry_count": 0,
        "completion_state": "COMPLETE",
    }
    atomic_json(BINDING_PATH, binding)
    result = {
        "schema": "mephc-e9f-d5-fr04-source-binding-validation-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": source_commit,
        "origin_sandbox_sha": source_commit,
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "fr": FR,
        "resolution": RESOLUTION,
        "validation_point": "PUBLIC_K",
        "validation_q": {"i": 96, "j": 0, "denominator": 144},
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "corrected_geometry_binding_status": "PASS",
        "spectral_reference_case": "FR0P4_R64_TESS96",
        "spectral_replay_pass": True,
        "actual_frequencies": actual,
        "reference_frequencies": reference["expected_frequencies"],
        "maximum_absolute_error": max(errors),
        "k_gap_band0_band1": gap01,
        "k_gap_band1_band2": gap12,
        "dataset_id": dataset["dataset_id"],
        "dataset_manifest_sha256": dataset["manifest_sha256"],
        "dataset_record_count": 1,
        "native_invocation_count": 1,
        "provider_request_count": 1,
        "native_solves": 1,
        "solver_executions": 1,
        "mpb_execution": True,
        "native_retry_count": 0,
        "old_d3_dataset_reuse_authorized": False,
        "full_3205_acquisition_authorized": False,
        "berry_calculation": False,
        "qualification": False,
        "reducer_execution": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "CORRECTED_FR04_3205_STATE_GRAPH_READY_FOR_FRESH_SHARED_R64_ACQUISITION",
        "terminal": "E9F_D5_FR04_CORRECT_SOURCE_BINDING_VALIDATED_READY_FOR_FRESH_R64_ACQUISITION",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + canonical(result).decode("utf-8"))
    return result


def _original_d5_state() -> dict[str, Any]:
    flow_root = Path("/home/icy/.local/state/mephc-runner/MEPHC/flow")
    jobs_root = flow_root / "science-jobs"
    jobs = []
    if jobs_root.is_dir():
        for path in sorted(jobs_root.glob("MEPHC-SCIENCE-*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("work_order_id") == ORIGINAL_D5_WORK_ORDER_ID:
                jobs.append(value)
    native_ids = [value.get("native_run_id") for value in jobs if isinstance(value.get("native_run_id"), str)]
    native_runs = []
    native_root = flow_root / "native-runs"
    for run_id in native_ids:
        path = native_root / f"{run_id}.json"
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                value = {}
            if isinstance(value, dict):
                native_runs.append(value)
    dataset_root = Path("/home/icy/.local/share/mephc-runtime/science/datasets")
    validation_datasets = 0
    if dataset_root.is_dir():
        for manifest in dataset_root.glob("*/dataset-manifest.json"):
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            namespace = value.get("namespace", {}) if isinstance(value, dict) else {}
            if isinstance(namespace, dict) and namespace.get("work_order_id") == ORIGINAL_D5_WORK_ORDER_ID:
                validation_datasets += 1
    provider_started = any(isinstance(value.get("result_summary"), dict) for value in native_runs)
    return {
        "science_job_exists": bool(jobs),
        "science_job_count": len(jobs),
        "native_run_exists": bool(native_runs),
        "native_run_count": len(native_runs),
        "native_process_started": any(value.get("process_started") is True for value in native_runs),
        "provider_execution_started": provider_started,
        "validation_dataset_exists": validation_datasets > 0,
        "validation_dataset_count": validation_datasets,
        "checkpoint_exists": any(value.get("checkpoint") is not None for value in jobs + native_runs),
        "original_job_state": jobs[-1].get("state") if jobs else None,
        "original_native_error": native_runs[-1].get("result_error") if native_runs else None,
    }


def _d5r1_diagnosis() -> dict[str, Any]:
    state = _original_d5_state()
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: dict[str, Any]) -> None:
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    durable_clear = not any(state[key] for key in (
        "science_job_exists", "native_run_exists", "validation_dataset_exists", "checkpoint_exists",
    ))
    add("ORIGINAL_D5_DURABLE_STATE_CLEAR", durable_clear, state)

    graph = read_json(GRAPH_PATH)
    incident = read_json(INCIDENT_PATH)
    graph_hash = sha256_file(GRAPH_PATH)
    incident_hash = sha256_file(INCIDENT_PATH)
    graph_ok = graph_hash == D5R1_GRAPH_SHA256 and graph.get("logical_provider_demand_count") == 3205 and graph.get("unique_provider_request_count") == 3205 and graph.get("duplicate_logical_demand_count") == 0 and graph.get("collision_group_count") == 0
    add("CORRECTED_GRAPH_UNCHANGED", graph_ok, {"sha256": graph_hash, "expected_sha256": D5R1_GRAPH_SHA256, "logical_count": graph.get("logical_provider_demand_count"), "unique_count": graph.get("unique_provider_request_count")})
    incident_ok = incident_hash == D5R1_INCIDENT_SHA256 and incident.get("old_d3_dataset_reuse_authorized") is False
    add("INCIDENT_UNCHANGED", incident_ok, {"sha256": incident_hash, "expected_sha256": D5R1_INCIDENT_SHA256})

    reference = read_json(REFERENCE_PATH)
    record = reference.get("results", {}).get("FR0P4_R64_TESS96")
    frequencies = record.get("frequencies") if isinstance(record, dict) else None
    reference_ok = isinstance(record, dict) and record.get("public_k") == [2.0 / 3.0, 0.0] and record.get("resolution") == 64 and isinstance(frequencies, list) and len(frequencies) == 6 and all(math.isfinite(float(item)) for item in frequencies)
    reference_values = [float(item) for item in frequencies] if reference_ok else []
    add("FR04_REFERENCE_RECORD_FOUND", reference_ok, {"case": "FR0P4_R64_TESS96", "public_k": record.get("public_k") if isinstance(record, dict) else None, "resolution": record.get("resolution") if isinstance(record, dict) else None, "six_band_spectrum": reference_values})
    local_ok = isinstance(record, dict) and reference.get("fr0p4_tessellation_geometry_convergence") == "PASSED" and reference.get("gap21_trend") == "REPRODUCED" and reference.get("gap32_trend") == "REPRODUCED"
    add("FR04_REFERENCE_LOCAL_EVIDENCE_USABLE", local_ok, {"geometry_convergence": reference.get("fr0p4_tessellation_geometry_convergence"), "gap21_trend": reference.get("gap21_trend"), "gap32_trend": reference.get("gap32_trend")})
    add("E9E_B_GLOBAL_STATUS_NOT_USED_AS_FR04_GATE", True, {"e9e_b_overall": reference.get("E9E_B_OVERALL"), "local_gate": "FR0P4_R64_TESS96_ONLY"})

    try:
        embedding = load_module("_mephc_d5r1_spectral_embedding", EMBEDDING_PATH)
        geometry = load_module("_mephc_d5r1_rounded_geometry", GEOMETRY_PATH)
        case = embedding.polygon_case(FR, ARC_SEGMENTS)
        direct = geometry.build_geometry(FR)
        geometry_ok = (case.get("f_r") == FR and case.get("arc_segments_per_corner") == ARC_SEGMENTS and case.get("analytic_boundary_digest") == GEOMETRY_BOUNDARY_DIGEST and direct.get("boundary_digest") == GEOMETRY_BOUNDARY_DIGEST and case.get("posthoc_area_rescale") is False and case.get("c3_vertex_symmetry") is True and case.get("public_cartesian_to_mpb_roundtrip_error", math.inf) <= 1.0e-12)
        geometry_detail = {"f_r": case.get("f_r"), "arc_segments_per_corner": case.get("arc_segments_per_corner"), "analytic_boundary_digest": case.get("analytic_boundary_digest"), "posthoc_area_rescale": case.get("posthoc_area_rescale"), "c3_vertex_symmetry": case.get("c3_vertex_symmetry"), "roundtrip_error": case.get("public_cartesian_to_mpb_roundtrip_error")}
    except (ValidationError, ImportError, OSError, KeyError, TypeError, ValueError) as exc:
        geometry_ok = False
        geometry_detail = {"error": type(exc).__name__}
    add("CORRECTED_GEOMETRY_SOLVER_FREE_RECHECK", geometry_ok, geometry_detail)

    requests = graph.get("unique_provider_requests", [])
    request_ok = isinstance(requests, list) and len(requests) == 3205 and all(
        isinstance(item, dict) and item.get("request_key", {}).get("source_model_identity") == SOURCE_MODEL_IDENTITY and item.get("request_key", {}).get("analytic_geometry_boundary_digest") == GEOMETRY_BOUNDARY_DIGEST and item.get("request_key", {}).get("arc_segments_per_corner") == ARC_SEGMENTS for item in requests
    )
    add("CORRECTED_GRAPH_REQUEST_IDENTITY", request_ok, {"checked_unique_requests": len(requests) if isinstance(requests, list) else 0, "coordinate_set_equal_to_d1": graph.get("coordinate_set_equal_to_d1")})
    first_failure = next((item["name"] for item in checks if item["status"] == "FAIL"), None)
    return {
        "schema": "mephc-e9f-d5r1-fr04-precheck-diagnosis-v1",
        "work_order_id": D5R1_WORK_ORDER_ID,
        "original_d5_work_order_id": ORIGINAL_D5_WORK_ORDER_ID,
        "original_d5_state": state,
        "prechecks": checks,
        "first_failing_precheck": first_failure,
        "precheck_status": "FAIL_CLOSED" if first_failure else "PASS",
        "e9e_b_global_status": reference.get("E9E_B_OVERALL"),
        "fr04_reference_local_status": "USABLE" if local_ok and reference_ok else "INVALID",
        "reference_fr04_r64_tess96_six_band_spectrum": reference_values,
        "reference_k_gap_band0_band1": reference_values[1] - reference_values[0] if reference_ok else None,
        "reference_k_gap_band1_band2": reference_values[2] - reference_values[1] if reference_ok else None,
        "corrected_graph_sha256": graph_hash,
        "corrected_geometry_status": "PASS" if geometry_ok else "FAIL",
        "corrected_graph_status": "PASS" if graph_ok and request_ok else "FAIL",
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "native_solves": 0,
        "mpb_execution": False,
        "no_second_validation_solve": True,
        "pipeline_health": "HEALTHY",
        "scientific_work_must_stop": True if first_failure else False,
        "terminal": "E9F_D5R1_FR04_PRECHECK_OR_REPLAY_FAIL_CLOSED" if first_failure else "E9F_D5R1_FR04_CORRECT_SOURCE_BINDING_REPLAY_VALIDATED",
    }


def acquire() -> dict[str, Any]:
    diagnosis = _d5r1_diagnosis()
    atomic_json(DIAGNOSIS_PATH, diagnosis)
    if diagnosis["first_failing_precheck"] is not None:
        raise ValidationError("EXISTING_D5_VALIDATION_STATE_RECONCILIATION_REQUIRED")
    return initial_acquire()


def run(arguments: list[str] | None = None) -> dict[str, Any] | None:
    if arguments:
        raise ValidationError("ENTRYPOINT_ARGUMENTS_FORBIDDEN")
    if os.environ.get("MEPHC_D5_PREPARE_ONLY") == "1":
        prepare_artifacts()
        return None
    return acquire()


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except ValidationError as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-e9f-d5-fr04-source-binding-validation-v1",
            "state": "failed", "error_code": exc.code, "detail": exc.detail[:1000],
            "terminal": "E9F_D5_FR04_SOURCE_BINDING_VALIDATION_FAIL_CLOSED",
        }).decode("utf-8"))
        raise SystemExit(2)
