"""Acquire the frozen thirteen-state dataset with the certified TM provider."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import (
    canonical_state_identity,
    digest_state_identity,
    geometry_anchor_status,
    make_state,
)
from mephc.local_affine_state_provider import LocalAffineStateProvider, local_affine_reference_cell_contract


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P4-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-367"
BASE_INPUT_COMMIT = "72263e3a700b7e99f39baa74e72cc66eef9de1a0"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
PROVIDER_SHA = "e83aa9768b53ad5e0f151636982e91a1193b269cf4e5baef1da1a0ca33965128"
PROVIDER_CONTRACT_SHA = "19d514a83f80e29fad9ad8e9d4f2d56442a9334df1398d8722d37c796002e334"
P1R1_CERTIFICATION_SHA = "c8cf96dcee7a8283d6e987c4cd09adf5851366b53669eed03dfee906abad6ade"
P3_VALIDATION_SHA = "de6177f3628f66888f9d19cefc545b2f8432e6ed6f70645b911b6ad52da8a550"
GRAPH_SHA = "b33771c08eff0c989c10ae3bd80704d6eaeb71659c40931479c42055a6746ed4"
STATE_SET_SHA = "d38510a2a29996334dccb8fc697d6cec20179a7e510e11cea90806e8560d7549"
P2R2_ENTRYPOINT_SHA = "a2b29008bbcd2d20a5bdee5f42335beba51bc6084501c6ba41915aa961b43de2"
FAILED_ORDERS = (
    ("MEPHC-LOCALAFFINE-P2-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-361",
     "872efed7f7fb79bc6335d083343c2bb5144ffde3",
     "SCIENCE_SOURCE_COMMIT_INVALID", False),
    ("MEPHC-LOCALAFFINE-P2R1-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-362",
     "31646d54daba115e1379acf87f0c970c8e44fbec",
     "P2R1_FAILED_P2_RECONCILIATION_INPUT_PATH_FAIL_CLOSED", True),
    ("MEPHC-LOCALAFFINE-P2R2-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-363",
     "8f03fefcee59df2251c513f0f65adf48c1ef805e",
     "P2R2_PROVIDER_POLARIZATION_CONTRACT_MISMATCH_FAIL_CLOSED", True),
)
P1R1_REPORT = ROOT / "audit/local_affine/p1r1_provider_contract_validation.json"
P3_VALIDATION = ROOT / "audit/local_affine/p3_polarization_identity_validation.json"
PROVIDER_CONTRACT = ROOT / "audit/e10f/local_affine_state_provider_contract.json"
GRAPH_PATH = ROOT / "audit/local_affine/p2r1_frozen_13_state_request_graph.json"
OLD_P2_ENTRYPOINT = ROOT / "audit/local_affine/p2_frozen_13_state_acquisition.py"
OLD_P2R1_ENTRYPOINT = ROOT / "audit/local_affine/p2r1_frozen_13_state_acquisition.py"
OLD_P2R2_ENTRYPOINT = ROOT / "audit/local_affine/p2r2_frozen_13_state_acquisition.py"
OLD_P2_GRAPH = ROOT / "audit/local_affine/p2_frozen_13_state_request_graph.json"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def state_set(graph: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [(item["state_id"], item["role"], item["public_q"], item["s"]) for item in graph["states"]]


def state_set_digest(states: list[tuple[Any, ...]]) -> str:
    return hashlib.sha256(canonical(states)).hexdigest()


def _job_candidates(science_jobs: Path, work_order_id: str) -> list[Path]:
    candidates = []
    for path in sorted(science_jobs.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("work_order_id") == work_order_id:
            candidates.append(path)
    return candidates


def reconcile_failed_attempt(science_jobs: Path, native_runs: Path, order: tuple[str, str, str, bool]) -> dict[str, Any]:
    work_order_id, expected_source, expected_error, allow_underlying = order
    candidates = _job_candidates(science_jobs, work_order_id)
    require(len(candidates) == 1, "FAILED_SCIENCE_JOB_UNIQUE_BY_WORK_ORDER_REQUIRED")
    job = json.loads(candidates[0].read_text(encoding="utf-8"))
    require(job.get("job_id") and job.get("work_order_id") == work_order_id, "FAILED_SCIENCE_JOB_IDENTITY_INVALID")
    require(job.get("state") == "failed", "FAILED_SCIENCE_STATE_INVALID")
    source = job.get("source_commit", "")
    require(re.fullmatch(r"[0-9a-f]{40}", source) is not None and source == expected_source,
            "FAILED_SCIENCE_SOURCE_INVALID")
    native_run_id = job.get("native_run_id")
    require(isinstance(native_run_id, str) and native_run_id, "FAILED_SCIENCE_NATIVE_LINK_MISSING")
    fields = ("actual_provider_execution_count", "actual_solver_execution_count", "actual_dataset_record_count")
    require(tuple(job.get(field, 0) for field in fields) == (0, 0, 0), "FAILED_SCIENCE_SIDE_EFFECT_COUNTS_NONZERO")
    result = job.get("result", {})
    require(isinstance(result, dict) and tuple(result.get(field, 0) for field in fields) == (0, 0, 0),
            "FAILED_SCIENCE_RESULT_SIDE_EFFECT_COUNTS_NONZERO")
    native_path = native_runs / f"{native_run_id}.json"
    require(native_path.is_file(), "FAILED_NATIVE_RUN_RECORD_MISSING")
    native = json.loads(native_path.read_text(encoding="utf-8"))
    require(native.get("run_id") == native_run_id and native.get("state") == "failed",
            "FAILED_NATIVE_RUN_STATE_INVALID")
    require(tuple(native.get(field, 0) for field in fields) == (0, 0, 0), "FAILED_NATIVE_SIDE_EFFECT_COUNTS_NONZERO")
    stderr = (native_runs / f"{native_run_id}.stderr.log").read_text(encoding="utf-8")
    if allow_underlying:
        require(expected_error in stderr or "FileNotFoundError" in stderr
                or "LOCAL_AFFINE_STATE_CONTRACT_MISMATCH:polarization" in stderr,
                "FAILED_HISTORICAL_EXACT_ERROR_UNCONFIRMED")
    else:
        require(expected_error in stderr, "FAILED_HISTORICAL_EXACT_ERROR_UNCONFIRMED")
    return {"job_id": job["job_id"], "source_sha": source, "return_error": expected_error,
            "provider_count": 0, "solver_count": 0, "dataset_count": 0}


def verify_inputs(counters_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    native_runs = counters_path.parent
    flow_root = native_runs.parent
    science_jobs = flow_root / "science-jobs"
    require(native_runs.is_dir() and science_jobs.is_dir(), "DURABLE_FLOW_ROOT_DIRECTORIES_MISSING")
    reconciled = tuple(reconcile_failed_attempt(science_jobs, native_runs, order) for order in FAILED_ORDERS)
    require(sha256_file(OLD_P2_GRAPH) == "73df70ca5eecd728f07d6f6a954324c211366923ab5ef963107743baebc485c1",
            "FAILED_P2_GRAPH_MUTATED")
    require(sha256_file(OLD_P2_ENTRYPOINT) == "3c8ea4af35ea1f6a921b6b52a33215fc4289204a331efe853f33cfb4ac865a02",
            "FAILED_P2_ENTRYPOINT_MUTATED")
    require(sha256_file(OLD_P2R1_ENTRYPOINT) == "df09ebd383880b306f447a3be6b3270fdbb9ae12f38e014e82cb9d98c59dffb0",
            "FAILED_P2R1_ENTRYPOINT_MUTATED")
    require(sha256_file(OLD_P2R2_ENTRYPOINT) == P2R2_ENTRYPOINT_SHA, "FAILED_P2R2_ENTRYPOINT_MUTATED")
    require(sha256_file(P1R1_REPORT) == P1R1_CERTIFICATION_SHA, "P1R1_CERTIFICATION_HASH_MISMATCH")
    require(sha256_file(P3_VALIDATION) == P3_VALIDATION_SHA, "P3_VALIDATION_HASH_MISMATCH")
    require(sha256_file(ROOT / "mephc/local_affine_state_provider.py") == PROVIDER_SHA, "PROVIDER_HASH_MISMATCH")
    require(sha256_file(PROVIDER_CONTRACT) == PROVIDER_CONTRACT_SHA, "PROVIDER_CONTRACT_HASH_MISMATCH")
    return reconciled


def runtime_contract() -> dict[str, Any]:
    return {"resolution": 64, "num_bands": 6, "polarization": "TM", "eigensolver_tolerance": 1e-7,
            "mesh_size": 3, "deterministic": True, "phase_callback": None}


def vector_digest(vectors: tuple[np.ndarray, ...]) -> str:
    value = [[[float(item.real), float(item.imag)] for item in np.asarray(vector, dtype=np.complex128)]
             for vector in vectors]
    return hashlib.sha256(canonical(value)).hexdigest()


def verify_snapshot(snapshot: Any, spec: Any, identity: dict[str, Any], expected_shape: tuple[int, int]) -> dict[str, Any]:
    provenance = snapshot.to_dict()["provenance"]
    required = ("representation", "spatial_shape", "component_count", "component_order",
                "periodic_h_envelope", "bloch_phase_excluded", "mpb_k_point")
    require(snapshot.component_count == 3 and tuple(snapshot.spatial_shape) == expected_shape,
            "PROVIDER_RESULT_SHAPE_INVALID")
    require(all(field in provenance for field in required), "PROVIDER_RESULT_MANDATORY_METADATA_MISSING")
    require(provenance["representation"] == "mpb_periodic_h_l2_v1"
            and provenance["spatial_shape"] == list(expected_shape)
            and provenance["component_count"] == 3
            and provenance["component_order"] == "supplied final axis order"
            and provenance["periodic_h_envelope"] is True
            and provenance["bloch_phase_excluded"] is True, "PROVIDER_RESULT_METADATA_INVALID")
    require(provenance.get("local_affine_solver_polarization_identity") == "TM",
            "EXPLICIT_POLARIZATION_IDENTITY_BINDING_FAIL_CLOSED")
    caller = provenance.get("caller_provenance")
    settings = provenance.get("solver_settings")
    if not isinstance(settings, dict) and isinstance(caller, dict):
        settings = caller.get("solver_settings")
    require(isinstance(settings, dict) and settings.get("resolution") == 64, "PROVIDER_RESULT_RESOLUTION_MISSING")
    require(provenance.get("local_affine_state_identity") == identity,
            "LOCAL_AFFINE_STATE_IDENTITY_MISMATCH_BEFORE_PERSISTENCE")
    require(provenance.get("local_affine_state_identity_sha256") == digest_state_identity(identity),
            "LOCAL_AFFINE_STATE_IDENTITY_DIGEST_MISMATCH_BEFORE_PERSISTENCE")
    lattice = spec.geometry_lattice.size
    expected_contract = local_affine_reference_cell_contract(
        spec, spatial_shape=expected_shape, identity=identity,
        lattice_size=(float(lattice.x), float(lattice.y)))
    require(provenance.get("local_affine_reference_cell_contract") == expected_contract,
            "REFERENCE_CELL_CONTRACT_MISMATCH_BEFORE_PERSISTENCE")
    reciprocal = np.asarray(provenance["mpb_k_point"], dtype=float)
    require(reciprocal.shape == (3,) and np.all(np.isfinite(reciprocal))
            and np.allclose(reciprocal[:2], identity["derived_kappa"], rtol=0.0, atol=1e-9)
            and abs(float(reciprocal[2])) <= 1e-12, "CANONICAL_RECIPROCAL_METADATA_MISMATCH")
    if isinstance(caller, dict) and "mpb_reciprocal_k_point" in caller:
        require(np.allclose(np.asarray(caller["mpb_reciprocal_k_point"], dtype=float), reciprocal,
                            rtol=0.0, atol=1e-9), "CALLER_RECIPROCAL_METADATA_MISMATCH")
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    raw_norms = np.asarray(snapshot.raw_norms, dtype=float)
    require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies)) and np.all(frequencies > 0.0),
            "PERIODIC_H_FREQUENCIES_INVALID")
    require(raw_norms.shape == (6,) and np.all(np.isfinite(raw_norms)) and np.all(raw_norms > 0.0),
            "PERIODIC_H_NORMS_INVALID")
    require(snapshot.h_fields.shape == (6, expected_shape[0], expected_shape[1], 3), "PERIODIC_H_FIELDS_INVALID")
    norms = []
    for vector in snapshot.normalized_vectors:
        norm = float(np.linalg.norm(np.asarray(vector, dtype=np.complex128)))
        require(np.isfinite(norm) and np.isclose(norm, 1.0, rtol=0.0, atol=1e-10),
                "PERIODIC_H_NORMALIZED_VECTOR_INVALID")
        norms.append(norm)
    require(snapshot.is_qualified, "PERIODIC_H_ORTHOGONALITY_UNQUALIFIED")
    return {"frequencies": [float(value) for value in frequencies], "raw_norms": [float(value) for value in raw_norms],
            "normalized_vector_norms": norms, "normalized_vector_digest": vector_digest(snapshot.normalized_vectors),
            "provenance": provenance, "contract": expected_contract}


def main() -> int:
    execution_source = os.environ.get("MEPHC_SOURCE_COMMIT", "")
    require(re.fullmatch(r"[0-9a-f]{40}", execution_source) is not None, "SCIENCE_EXECUTION_IDENTITY_INVALID")
    counters_path = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"])
    failed_p2, failed_p2r1, failed_p2r2 = verify_inputs(counters_path)
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    require(sha256_file(GRAPH_PATH) == GRAPH_SHA and isinstance(graph, dict), "FROZEN_STATE_GRAPH_INVALID")
    current_states = state_set(graph)
    require(len(current_states) == 13 and state_set_digest(current_states) == STATE_SET_SHA,
            "SCIENTIFIC_STATE_SET_IDENTITY_MISMATCH")
    require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_FAIL_CLOSED")
    specs = [make_state(tuple(item["public_q"]), float(item["s"])) for item in graph["states"]]
    for spec in specs:
        require(canonical_state_identity(spec).get("polarization") == "TM", "STATE_POLARIZATION_IDENTITY_MISMATCH")
    runtime = load_module("_mephc_p4_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_p4_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    require(scientific_job.runtime_hash(ROOT) == RUNTIME_SHA, "SCIENCE_RUNTIME_IDENTITY_MISMATCH")
    state_root = runtime._trusted_science_state_root()
    certification = json.loads((state_root / "certifications" / f"{RUNTIME_SHA}.json").read_text(encoding="utf-8"))
    smoke = certification.get("mpb_smoke", {})
    require(certification.get("schema") == "mephc-science-runtime-certification-v1" and smoke.get("executed") is True,
            "SCIENCE_RUNTIME_MPB_SMOKE_NOT_CERTIFIED")
    namespace = {"project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID, "source_commit": execution_source,
                 "entrypoint_sha256": sha256_file(ROOT / "audit/local_affine/p4_frozen_13_state_acquisition.py"),
                 "request_graph_sha256": sha256_file(GRAPH_PATH)}
    store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    require(not store.root.exists(), "P4_DATASET_NAMESPACE_ALREADY_EXISTS")
    import meep as mp
    provider = LocalAffineStateProvider(
        polarization=mp.TM, polarization_identity="TM", default_material=mp.air,
        resolution=64, num_bands=6, eigensolver_tolerance=1e-7, mesh_size=3, deterministic=True)
    counter = scientific_job.BudgetCounter(13, 13)
    records = []
    common_shape = None
    minimum_gap = float("inf")
    for item, spec in zip(graph["states"], specs):
        identity = canonical_state_identity(spec)
        expected_shape = (int(spec.geometry_lattice.size.x * 64), int(spec.geometry_lattice.size.y * 64))
        counter.consume_provider()
        counter.consume_solver()
        snapshot = provider.solve(spec)
        evidence = verify_snapshot(snapshot, spec, identity, expected_shape)
        common_shape = expected_shape if common_shape is None else common_shape
        require(expected_shape == common_shape, "REFERENCE_CELL_SPATIAL_SHAPE_INCONSISTENT")
        gap = float(evidence["frequencies"][1] - evidence["frequencies"][0])
        minimum_gap = min(minimum_gap, gap)
        key_identity = {"work_order_id": WORK_ORDER_ID, "state_id": item["state_id"], "role": item["role"],
                        "public_q": list(item["public_q"]), "s": float(item["s"])}
        payload = runtime.encode_snapshot(snapshot)
        metadata = {**identity, "state_id": item["state_id"], "role": item["role"], "key_identity": key_identity,
                    "frequencies": evidence["frequencies"], "raw_norms": evidence["raw_norms"],
                    "normalized_vector_norms": evidence["normalized_vector_norms"],
                    "normalized_vector_digest": evidence["normalized_vector_digest"],
                    "periodic_h_envelope_payload": True, "complete_snapshot_provenance": evidence["provenance"],
                    "reference_cell_contract": evidence["contract"], "band0_external_gap": gap,
                    "solver_configuration": runtime_contract(), "science_execution_source": execution_source,
                    "request_graph_identity": namespace["request_graph_sha256"],
                    "scientific_state_set_identity": STATE_SET_SHA, "payload_sha256": hashlib.sha256(payload).hexdigest()}
        record = store.put(canonical(key_identity), payload, metadata)
        records.append({"state_id": item["state_id"], "role": item["role"], "key_sha256": record["key_sha256"],
                        "payload_sha256": record["payload_sha256"], "band0_external_gap": gap})
    require(len(records) == 13 and minimum_gap >= 0.05, "RANK1_EXTERNAL_GAP_GATE_FAIL_CLOSED")
    manifest = store.finalize(13, {"work_order_id": WORK_ORDER_ID, "source_commit": execution_source,
                                   "request_graph_sha256": namespace["request_graph_sha256"],
                                   "state_set_sha256": STATE_SET_SHA, "fresh_solve_count": 13,
                                   "cache_reuse_count": 0, "retry_count": 0, "mpb_execution": True})
    job_id = counters_path.name.split(".", 1)[0]
    result = {
        "WORK_ORDER_ID": WORK_ORDER_ID, "BASE_INPUT_COMMIT": BASE_INPUT_COMMIT,
        "IMPLEMENTATION_SOURCE_IDENTITY": execution_source, "SCIENCE_EXECUTION_IDENTITY": execution_source,
        "FINAL_SANDBOX_SHA": execution_source, "ORIGIN_SANDBOX_SHA": execution_source, "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS",
        "P2_SCIENCE_JOB_ID": failed_p2["job_id"], "P2_PROVIDER_EXECUTION_COUNT": 0,
        "P2_DATASET_SOLVER_EXECUTION_COUNT": 0, "P2_DATASET_RECORD_COUNT": 0,
        "P2R1_SCIENCE_JOB_ID": failed_p2r1["job_id"], "P2R1_PROVIDER_EXECUTION_COUNT": 0,
        "P2R1_DATASET_SOLVER_EXECUTION_COUNT": 0, "P2R1_DATASET_RECORD_COUNT": 0,
        "P2R2_SCIENCE_JOB_ID": failed_p2r2["job_id"], "P2R2_PROVIDER_EXECUTION_COUNT": 0,
        "P2R2_DATASET_SOLVER_EXECUTION_COUNT": 0, "P2R2_DATASET_RECORD_COUNT": 0,
        "P2_EXECUTION_RECONCILED": True, "P2R1_EXECUTION_RECONCILED": True, "P2R2_EXECUTION_RECONCILED": True,
        "SCIENCE_RUNTIME_MPB_SMOKE_STATUS": "PASS", "SCIENCE_RUNTIME_MPB_SMOKE_SOLVER_EXECUTIONS": int(smoke.get("solver_executions", 0)),
        "PROVIDER_MODULE_SHA256": PROVIDER_SHA, "REQUEST_GRAPH_SHA256": namespace["request_graph_sha256"],
        "SCIENTIFIC_STATE_SET_IDENTITY": STATE_SET_SHA, "SCIENCE_JOB_ID": job_id,
        "SCIENCE_SOURCE_SHA": execution_source, "LOCAL_AFFINE_P4_ACQUISITION_STATUS": "PASS",
        "REQUEST_GRAPH_IDENTITY_STATUS": "PASS", "SCIENTIFIC_STATE_SET_IDENTITY_STATUS": "PASS",
        "P3_PROVIDER_CERTIFICATION_STATUS": "VERIFIED", "EXPLICIT_POLARIZATION_IDENTITY_BINDING_STATUS": "PASS",
        "E8B_GEOMETRY_BINDING_STATUS": "PASS", "FIXED_Q_TO_LOCAL_KAPPA_STATUS": "PASS",
        "CANONICAL_RECIPROCAL_METADATA_STATUS": "PASS", "REFERENCE_CELL_METADATA_STATUS": "PASS",
        "PERIODIC_H_SNAPSHOT_STATUS": "PASS", "RANK1_PREFLIGHT_ISOLATION_STATUS": "PASS",
        "MIN_BAND0_EXTERNAL_GAP": minimum_gap, "DATASET_ID": manifest["dataset_id"],
        "DATASET_MANIFEST_SHA256": manifest["manifest_sha256"], "DATASET_RECORD_COUNT": 13,
        "COMPLETED_STATE_COUNT": 13, "FAILED_STATE_COUNT": 0, "NATIVE_INVOCATION_COUNT": 1,
        "PROVIDER_EXECUTION_COUNT": 13, "SOLVER_EXECUTION_COUNT": 13, "CACHE_REUSE_COUNT": 0,
        "RETRY_COUNT": 0, "MPB_EXECUTION": True, "LOCAL_AFFINE_P4_DATASET_STATUS": "COMPLETE_IMMUTABLE_13_STATE",
        "LOCAL_AFFINE_P4_DATASET_READY_FOR_REDUCTION": True, "LOCAL_AFFINE_LIVE_ACQUISITION_EXECUTED": True,
        "ORIGINAL_FAILED_SOLVE_REUSED": False, "FAILED_P2_PAYLOAD_REUSED": False,
        "FAILED_P2R1_PAYLOAD_REUSED": False, "FAILED_P2R2_PAYLOAD_REUSED": False,
        "NEXT_LIVE_SOLVER_AUTHORIZATION": False, "PIPELINE_HEALTH": "HEALTHY",
        "BLOCKED_BY_INFRASTRUCTURE": False, "SCIENTIFIC_WORK_MUST_STOP": False,
        "NEXT_SCIENTIFIC_STATE": "LOCAL_AFFINE_P4_DATASET_READY_FOR_SOLVER_FREE_TWO_SCALE_BERRY_MIXED_CURVATURE_AND_LOCAL_BAND_DERIVATIVE_REDUCTION",
        "RETURN_TO_SUPERVISOR": True, "TERMINAL": "LOCALAFFINE_P4_FROZEN_13_STATE_LIVE_ACQUISITION_COMPLETE",
    }
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
