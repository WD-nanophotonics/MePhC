"""Run exactly one corrected FR0.4/R64 public-K spectral replay."""
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
GRAPH_PATH = ROOT / "audit/e9f/d5_fr04_corrected_r64_request_graph.json"
INCIDENT_PATH = ROOT / "audit/e9f/d5_fr04_source_binding_incident.json"
RECONCILIATION_PATH = ROOT / "audit/e9f/d5r2_fr04_validation_state_reconciliation.json"
BINDING_PATH = ROOT / "audit/e9f/d5r3_fr04_corrected_k_replay_binding.json"
GEOMETRY_PATH = ROOT / "audit/e9e/a_rounded_triangle_geometry.py"
EMBEDDING_PATH = ROOT / "audit/e9e/run_spectral_embedding.py"
REFERENCE_PATH = ROOT / "audit/e9e/b_spectral_embedding_result.json"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
SCIENTIFIC_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"

WORK_ORDER_ID = "MEPHC-E9F-D5R3-FR04-CORRECTED-K-REPLAY-20260829-329"
BASE_SANDBOX_SHA = "a0442b5a8591b42496e8bba2fa1f19d82ce1401a"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
GRAPH_SHA256 = "44ae0ce1cc56c169c499d6957700da40f7d3431f3c96dda68e8ab879d03533a0"
INCIDENT_SHA256 = "00796dd1ed484b7ed279849caa068600e30027ed9518a539e3a59786390c090d"
RECONCILIATION_SHA256 = "dc7cd5bf181dedb764ecc187f19b2e89c20e9f442b8922157b48daeb9c716617"
GEOMETRY_BOUNDARY_DIGEST = "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71"
FR = 0.4
RESOLUTION = "R64"
RESOLUTION_VALUE = 64
ARC_SEGMENTS = 96
PUBLIC_K = (2.0 / 3.0, 0.0)
PUBLIC_Q = {"i": 96, "j": 0, "denominator": 144}
NUM_BANDS = 6
SPECTRAL_ATOL = 1.0e-7
SOURCE_MODEL_IDENTITY = "E9E_FR04_ROUNDED_TRIANGLE_V1"
PROVIDER_CONFIGURATION_IDENTITY = "E9E_FR04_ROUNDED_TRIANGLE_R64_TE_PROVIDER_V1"
BAND_REQUEST_CONFIGURATION = "E9F_D5R3_FR04_R64_SIX_BAND_TE_LOCKED"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"


class ReplayError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayError("JSON_UNAVAILABLE", path.name) from exc
    if not isinstance(value, dict):
        raise ReplayError("JSON_OBJECT_REQUIRED", path.name)
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
        raise ReplayError("MODULE_UNAVAILABLE", path.name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def current_source_commit() -> str:
    expected = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    if len(expected) != 40 or any(char not in "0123456789abcdef" for char in expected):
        raise ReplayError("EXECUTION_SOURCE_COMMIT_INVALID")
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    actual = result.stdout.strip()
    if result.returncode or actual != expected:
        raise ReplayError("EXECUTION_SOURCE_CHECKOUT_MISMATCH")
    return expected


def verify_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    graph = read_json(GRAPH_PATH)
    incident = read_json(INCIDENT_PATH)
    reconciliation = read_json(RECONCILIATION_PATH)
    if sha256_file(GRAPH_PATH) != GRAPH_SHA256 or sha256_file(INCIDENT_PATH) != INCIDENT_SHA256 or sha256_file(RECONCILIATION_PATH) != RECONCILIATION_SHA256:
        raise ReplayError("FROZEN_INPUT_SHA256_MISMATCH")
    if graph.get("logical_provider_demand_count") != 3205 or graph.get("unique_provider_request_count") != 3205:
        raise ReplayError("CORRECTED_GRAPH_COUNT_INVALID")
    if graph.get("duplicate_logical_demand_count") != 0 or graph.get("collision_group_count") != 0 or graph.get("coordinate_set_equal_to_d1") is not True:
        raise ReplayError("CORRECTED_GRAPH_IDENTITY_INVALID")
    if graph.get("source_model_identity") != SOURCE_MODEL_IDENTITY or graph.get("analytic_geometry_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or graph.get("arc_segments_per_corner") != ARC_SEGMENTS:
        raise ReplayError("CORRECTED_GRAPH_BINDING_INVALID")
    requests = graph.get("unique_provider_requests")
    if not isinstance(requests, list) or len(requests) != 3205:
        raise ReplayError("CORRECTED_GRAPH_REQUESTS_INVALID")
    for item in requests:
        key = item.get("request_key") if isinstance(item, dict) else None
        if not isinstance(key, dict) or key.get("source_model_identity") != SOURCE_MODEL_IDENTITY or key.get("analytic_geometry_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or key.get("arc_segments_per_corner") != ARC_SEGMENTS:
            raise ReplayError("CORRECTED_GRAPH_REQUEST_IDENTITY_INVALID")
    if incident.get("old_d3_dataset_reuse_authorized") is not False or incident.get("old_d3_dataset_mutation_authorized") is not False:
        raise ReplayError("INCIDENT_POLICY_INVALID")
    if reconciliation.get("original_d5_lineage_reconciliation_status") != "PASS_ZERO_PROVIDER_ZERO_SOLVER_NO_DATASET" or reconciliation.get("one_fresh_corrected_k_replay_can_be_authorized") is not True:
        raise ReplayError("STATE_RECONCILIATION_NOT_AUTHORIZED")
    if reconciliation.get("blocked_by_infrastructure") is not False or reconciliation.get("scientific_work_must_stop") is not False:
        raise ReplayError("STATE_RECONCILIATION_FAIL_CLOSED")
    return graph, incident, reconciliation


def verify_geometry_and_reference() -> tuple[Any, dict[str, Any], list[float]]:
    sys.path.insert(0, str(ROOT))
    embedding = load_module("_mephc_d5r3_spectral_embedding", EMBEDDING_PATH)
    geometry = load_module("_mephc_d5r3_rounded_geometry", GEOMETRY_PATH)
    case = embedding.polygon_case(FR, ARC_SEGMENTS)
    direct = geometry.build_geometry(FR)
    if case.get("f_r") != FR or case.get("arc_segments_per_corner") != ARC_SEGMENTS or case.get("analytic_boundary_digest") != GEOMETRY_BOUNDARY_DIGEST or direct.get("boundary_digest") != GEOMETRY_BOUNDARY_DIGEST:
        raise ReplayError("CORRECT_GEOMETRY_BINDING_INVALID")
    if case.get("posthoc_area_rescale") is not False or case.get("c3_vertex_symmetry") is not True or case.get("public_cartesian_to_mpb_roundtrip_error", math.inf) > 1.0e-12:
        raise ReplayError("CORRECT_GEOMETRY_PRECHECK_INVALID")
    reference = read_json(REFERENCE_PATH)
    record = reference.get("results", {}).get("FR0P4_R64_TESS96")
    frequencies = record.get("frequencies") if isinstance(record, dict) else None
    if not isinstance(record, dict) or record.get("public_k") != [2.0 / 3.0, 0.0] or record.get("resolution") != 64 or not isinstance(frequencies, list) or len(frequencies) != NUM_BANDS or not all(math.isfinite(float(item)) for item in frequencies):
        raise ReplayError("ACCEPTED_SPECTRAL_REFERENCE_INVALID")
    if reference.get("fr0p4_tessellation_geometry_convergence") != "PASSED" or reference.get("gap21_trend") != "REPRODUCED" or reference.get("gap32_trend") != "REPRODUCED":
        raise ReplayError("LOCAL_FR04_REFERENCE_EVIDENCE_INVALID")
    return embedding, case, [float(item) for item in frequencies]


def verify_runtime(scientific_job: Any, runtime: Any) -> None:
    if scientific_job.runtime_hash(ROOT) != RUNTIME_SHA256:
        raise ReplayError("SCIENCE_RUNTIME_HASH_MISMATCH")
    certification = read_json(runtime._trusted_science_state_root() / "certifications" / f"{RUNTIME_SHA256}.json")
    smoke = certification.get("mpb_smoke", {})
    if certification.get("schema") != "mephc-science-runtime-certification-v1" or certification.get("runtime_sha256") != RUNTIME_SHA256 or smoke.get("executed") is not True or smoke.get("solver_executions") != 1:
        raise ReplayError("SCIENCE_RUNTIME_MPB_CERTIFICATION_INVALID")


def acquire() -> dict[str, Any]:
    graph, incident, reconciliation = verify_frozen_inputs()
    embedding, case, reference_frequencies = verify_geometry_and_reference()
    source_commit = current_source_commit()
    runtime = load_module("_mephc_d5r3_science_runtime", RUNTIME_PATH)
    scientific_job = load_module("_mephc_d5r3_scientific_job", SCIENTIFIC_JOB_PATH)
    verify_runtime(scientific_job, runtime)
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": "E9F_D5R3_FR04_CORRECTED_K_REPLAY",
        "work_order_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        "fr": FR,
        "resolution": RESOLUTION,
        "validation_point": "PUBLIC_K",
        "validation_q": PUBLIC_Q,
        "source_model_identity": SOURCE_MODEL_IDENTITY,
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "arc_segments_per_corner": ARC_SEGMENTS,
        "science_runtime_sha256": RUNTIME_SHA256,
        "reference_artifact_sha256": sha256_file(REFERENCE_PATH),
        "corrected_graph_sha256": GRAPH_SHA256,
        "state_reconciliation_sha256": RECONCILIATION_SHA256,
    }
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    if store.root.exists() or BINDING_PATH.exists():
        raise ReplayError("EXISTING_D5R3_VALIDATION_STATE_RECONCILIATION_REQUIRED")
    counter = scientific_job.BudgetCounter(1, 1)
    import meep as mp
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider

    provider = MPBLiveSpectralProvider(
        geometry=list(embedding.make_solver_geometry(case)),
        geometry_lattice=embedding.make_lattice(),
        resolution=RESOLUTION_VALUE,
        num_bands=NUM_BANDS,
        polarization=mp.TE,
        default_material=mp.Medium(epsilon=7.0225),
        eigensolver_tolerance=1.0e-7,
        deterministic=True,
        mesh_size=3,
    )
    counter.consume_provider()
    counter.consume_solver()
    snapshot = provider.solve(PUBLIC_K)
    actual = [float(item) for item in snapshot.frequencies]
    if len(actual) != NUM_BANDS or not all(math.isfinite(item) for item in actual):
        raise ReplayError("SPECTRAL_REPLAY_NONFINITE")
    errors = [abs(actual[index] - reference_frequencies[index]) for index in range(NUM_BANDS)]
    gap01 = actual[1] - actual[0]
    gap12 = actual[2] - actual[1]
    if not all(error <= SPECTRAL_ATOL for error in errors) or gap12 >= 0.02:
        raise ReplayError("SPECTRAL_REPLAY_FAIL_CLOSED")
    payload = runtime.encode_snapshot(snapshot)
    decoded = runtime.decode_snapshot(payload)
    if tuple(float(item) for item in decoded.frequencies) != tuple(actual):
        raise ReplayError("VALIDATION_SNAPSHOT_ROUNDTRIP_MISMATCH")
    key = canonical({"validation_point": "PUBLIC_K", "q": PUBLIC_Q})
    store.put(key, payload, {
        "schema": "mephc-e9f-d5r3-fr04-corrected-k-replay-record-v1",
        "validation_point": "PUBLIC_K",
        "canonical_k_coordinate_units_1_over_144": {"i": PUBLIC_Q["i"], "j": PUBLIC_Q["j"]},
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
        "validation_point": "PUBLIC_K",
        "geometry_boundary_digest": GEOMETRY_BOUNDARY_DIGEST,
        "corrected_graph_sha256": GRAPH_SHA256,
        "state_reconciliation_sha256": RECONCILIATION_SHA256,
        "reference_artifact_sha256": sha256_file(REFERENCE_PATH),
        "spectral_replay_pass": True,
    })
    entrypoint_sha = sha256_file(Path(__file__))
    binding = {
        "schema": "mephc-e9f-d5r3-fr04-corrected-k-replay-binding-v1",
        "work_order_id": WORK_ORDER_ID,
        "acquisition_source_commit": source_commit,
        "acquisition_dataset_id": dataset["dataset_id"],
        "dataset_manifest_sha256": dataset["manifest_sha256"],
        "dataset_record_count": 1,
        "entrypoint_sha256": entrypoint_sha,
        "science_runtime_sha256": RUNTIME_SHA256,
        "corrected_graph_sha256": GRAPH_SHA256,
        "state_reconciliation_sha256": RECONCILIATION_SHA256,
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
        "validation_q": PUBLIC_Q,
        "reference_case": "FR0P4_R64_TESS96",
        "reference_frequencies": reference_frequencies,
        "actual_frequencies": actual,
        "absolute_errors": errors,
        "maximum_absolute_frequency_error": max(errors),
        "k_gap_band0_band1": gap01,
        "k_gap_band1_band2": gap12,
        "spectral_replay_pass": True,
        "native_invocation_count": 1,
        "provider_request_count": 1,
        "fresh_provider_execution_count": 1,
        "solver_executions": 1,
        "native_solves": 1,
        "mpb_execution": True,
        "native_retry_count": 0,
        "completion_state": "COMPLETE",
    }
    atomic_json(BINDING_PATH, binding)
    result = {
        "schema": "mephc-e9f-d5r3-fr04-corrected-k-replay-v1",
        "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": source_commit,
        "origin_sandbox_sha": source_commit,
        "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS",
        "execution_source_commit": source_commit,
        "science_runtime_sha256": RUNTIME_SHA256,
        "corrected_graph_status": "PASS",
        "corrected_graph_sha256": GRAPH_SHA256,
        "corrected_geometry_status": "PASS",
        "reference_fr04_r64_tess96_six_band_spectrum": reference_frequencies,
        "native_invocation_count": 1,
        "provider_request_count": 1,
        "fresh_provider_execution_count": 1,
        "solver_executions": 1,
        "native_solves": 1,
        "mpb_execution": True,
        "live_fr04_r64_six_band_spectrum": actual,
        "maximum_absolute_frequency_error": max(errors),
        "live_k_gap_band0_band1": gap01,
        "live_k_gap_band1_band2": gap12,
        "spectral_replay_pass": True,
        "validation_dataset_id": dataset["dataset_id"],
        "validation_dataset_manifest_sha256": dataset["manifest_sha256"],
        "validation_dataset_record_count": 1,
        "validation_acquisition_source_commit": source_commit,
        "validation_entrypoint_sha256": entrypoint_sha,
        "d3_source_model_defect_confirmed_and_corrected": True,
        "corrected_fr04_provider_validated": True,
        "full_3205_reacquisition_authorized": False,
        "native_retry_count": 0,
        "old_d3_dataset_reuse_authorized": False,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "CORRECTED_FR04_3205_STATE_GRAPH_VALIDATED_READY_FOR_SUPERVISOR_FRESH_ACQUISITION_AUTHORIZATION",
        "terminal": "E9F_D5R3_FR04_CORRECTED_K_REPLAY_VALIDATED",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + canonical(result).decode("utf-8"))
    return result


def run(arguments: list[str] | None = None) -> dict[str, Any]:
    if arguments:
        raise ReplayError("ENTRYPOINT_ARGUMENTS_FORBIDDEN")
    return acquire()


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except ReplayError as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-e9f-d5r3-fr04-corrected-k-replay-v1",
            "state": "failed", "error_code": exc.code, "detail": exc.detail[:1000],
            "terminal": "E9F_D5R3_FR04_CORRECTED_K_REPLAY_FAIL_CLOSED_NO_RETRY",
        }).decode("utf-8"))
        raise SystemExit(2)
