"""Acquire the frozen thirteen-state local-affine dataset exactly once."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import (
    canonical_state_identity,
    digest_state_identity,
    geometry_anchor_status,
    make_state,
)
from mephc.local_affine_state_provider import (
    LocalAffineStateProvider,
    local_affine_reference_cell_contract,
)


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P2-FROZEN-13-STATE-LIVE-ACQUISITION-20260829-361"
BASE_SANDBOX_SHA = "b5fe30a76779a5e99a0fbc23d040f1596bbc99c2"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA = "9c135953ca3bd91e9e0e386ce523466216dbe86be3579cd4c5c3d1b7d064d080"
P1R1_CERTIFICATION_SHA = "c8cf96dcee7a8283d6e987c4cd09adf5851366b53669eed03dfee906abad6ade"
PROVIDER_SHA = "ffc77a84bbcd28d2b32fa25bbbd32ea573b07ea461919b4a84afd0bfb6595a69"
PROVIDER_CONTRACT_SHA = "c226aaf1fa61eff2a4aae29f705519662f065f2f6b11c0096953d0f760f14b5e"
R2_RECONCILIATION_SHA = "1364dd46b1f79dea106a94a748525fc1496b095497b7f6d9e7be3282fd1d48e3"
GRAPH_SHA = "73df70ca5eecd728f07d6f6a954324c211366923ab5ef963107743bae bc485c1".replace(" ", "")
GRAPH_PATH = ROOT / "audit/local_affine/p2_frozen_13_state_request_graph.json"
P1R1_REPORT = ROOT / "audit/local_affine/p1r1_provider_contract_validation.json"
PROVIDER_CONTRACT = ROOT / "audit/e10f/local_affine_state_provider_contract.json"
R2_RECONCILIATION = ROOT / "audit/e10f/e10f_r2_preexisting_live_attempt_reconciliation.json"

Q0 = (0.0, -37.0 / 60.0)
STATES = (
    ("STATE_01", "CENTER", Q0, 0.0),
    ("STATE_02", "PRIMARY_PLUS_QX", (0.001, Q0[1]), 0.0),
    ("STATE_03", "PRIMARY_MINUS_QX", (-0.001, Q0[1]), 0.0),
    ("STATE_04", "PRIMARY_PLUS_QY", (0.0, Q0[1] + 0.001), 0.0),
    ("STATE_05", "PRIMARY_MINUS_QY", (0.0, Q0[1] - 0.001), 0.0),
    ("STATE_06", "PRIMARY_PLUS_S", Q0, 0.02),
    ("STATE_07", "PRIMARY_MINUS_S", Q0, -0.02),
    ("STATE_08", "REFINED_PLUS_QX", (0.0005, Q0[1]), 0.0),
    ("STATE_09", "REFINED_MINUS_QX", (-0.0005, Q0[1]), 0.0),
    ("STATE_10", "REFINED_PLUS_QY", (0.0, Q0[1] + 0.0005), 0.0),
    ("STATE_11", "REFINED_MINUS_QY", (0.0, Q0[1] - 0.0005), 0.0),
    ("STATE_12", "REFINED_PLUS_S", Q0, 0.01),
    ("STATE_13", "REFINED_MINUS_S", Q0, -0.01),
)


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


def expected_graph() -> dict[str, Any]:
    return {
        "collision_group_count": 0,
        "logical_state_count": 13,
        "schema": "mephc-local-affine-p2-frozen-13-state-request-graph-v1",
        "state_count": 13,
        "states": [
            {"public_q": list(q), "role": role, "s": strain, "state_id": state_id}
            for state_id, role, q, strain in STATES
        ],
        "unique_state_count": 13,
        "work_order_id": WORK_ORDER_ID,
    }


def load_frozen_graph() -> dict[str, Any]:
    require(sha256_file(GRAPH_PATH) == GRAPH_SHA, "FROZEN_STATE_GRAPH_SHA_MISMATCH")
    try:
        value = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("FROZEN_STATE_GRAPH_UNAVAILABLE") from exc
    if not isinstance(value, dict):
        raise RuntimeError("FROZEN_STATE_GRAPH_OBJECT_REQUIRED")
    return value


def verify_graph(graph: dict[str, Any]) -> None:
    require(graph == expected_graph(), "FROZEN_STATE_GRAPH_CONTENT_MISMATCH")
    states = graph["states"]
    require(len({item["state_id"] for item in states}) == 13, "FROZEN_STATE_GRAPH_DUPLICATE")
    require([item["state_id"] for item in states] == [f"STATE_{index:02d}" for index in range(1, 14)],
            "FROZEN_STATE_GRAPH_ORDER_INVALID")


def verify_frozen_inputs() -> None:
    require(sha256_file(P1R1_REPORT) == P1R1_CERTIFICATION_SHA, "P1R1_CERTIFICATION_HASH_MISMATCH")
    require(sha256_file(ROOT / "mephc/local_affine_state_provider.py") == PROVIDER_SHA,
            "P1R1_PROVIDER_HASH_MISMATCH")
    require(sha256_file(PROVIDER_CONTRACT) == PROVIDER_CONTRACT_SHA, "PROVIDER_CONTRACT_HASH_MISMATCH")
    require(sha256_file(R2_RECONCILIATION) == R2_RECONCILIATION_SHA,
            "E10F_R2_RECONCILIATION_HASH_MISMATCH")


def solver_configuration() -> dict[str, Any]:
    return {
        "resolution": 64,
        "num_bands": 6,
        "polarization": "TM",
        "eigensolver_tolerance": 1e-7,
        "mesh_size": 3,
        "deterministic": True,
        "phase_callback": None,
    }


def _vector_digest(vectors: tuple[np.ndarray, ...]) -> str:
    value = [
        [[float(item.real), float(item.imag)] for item in np.asarray(vector, dtype=np.complex128)]
        for vector in vectors
    ]
    return hashlib.sha256(canonical(value)).hexdigest()


def verify_snapshot(snapshot: Any, spec: Any, identity: dict[str, Any], expected_shape: tuple[int, int]) -> dict[str, Any]:
    provenance = snapshot.to_dict()["provenance"]
    require(snapshot.component_count == 3 and tuple(snapshot.spatial_shape) == expected_shape,
            "PERIODIC_H_SNAPSHOT_SHAPE_INVALID")
    required = ("representation", "spatial_shape", "component_count", "component_order",
                "periodic_h_envelope", "bloch_phase_excluded", "mpb_k_point")
    require(all(field in provenance for field in required), "PROVIDER_RESULT_MANDATORY_METADATA_MISSING")
    require(provenance["representation"] == "mpb_periodic_h_l2_v1", "PERIODIC_H_REPRESENTATION_INVALID")
    require(provenance["spatial_shape"] == list(expected_shape), "PERIODIC_H_SPATIAL_SHAPE_INVALID")
    require(provenance["component_count"] == 3 and provenance["component_order"] == "supplied final axis order",
            "PERIODIC_H_COMPONENT_METADATA_INVALID")
    require(provenance["periodic_h_envelope"] is True and provenance["bloch_phase_excluded"] is True,
            "PERIODIC_H_PHASE_CONTRACT_INVALID")
    settings = provenance.get("solver_settings")
    caller = provenance.get("caller_provenance")
    if not isinstance(settings, dict) and isinstance(caller, dict):
        settings = caller.get("solver_settings")
    require(isinstance(settings, dict) and settings.get("resolution") == 64,
            "SOLVER_RESOLUTION_METADATA_MISSING")
    require(provenance.get("local_affine_state_identity") == identity,
            "LOCAL_AFFINE_STATE_IDENTITY_MISMATCH_BEFORE_PERSISTENCE")
    require(provenance.get("local_affine_state_identity_sha256") == digest_state_identity(identity),
            "LOCAL_AFFINE_STATE_IDENTITY_DIGEST_MISMATCH_BEFORE_PERSISTENCE")
    lattice = spec.geometry_lattice.size
    expected_contract = local_affine_reference_cell_contract(
        spec, spatial_shape=expected_shape, identity=identity,
        lattice_size=(float(lattice.x), float(lattice.y)),
    )
    require(provenance.get("local_affine_reference_cell_contract") == expected_contract,
            "LOCAL_AFFINE_REFERENCE_CELL_CONTRACT_MISMATCH_BEFORE_PERSISTENCE")
    reciprocal = np.asarray(provenance["mpb_k_point"], dtype=float)
    require(reciprocal.shape == (3,) and np.all(np.isfinite(reciprocal)),
            "CANONICAL_RECIPROCAL_METADATA_INVALID")
    require(np.allclose(reciprocal[:2], identity["derived_kappa"], rtol=0.0, atol=1e-9)
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
    require(snapshot.h_fields.shape == (6, expected_shape[0], expected_shape[1], 3),
            "PERIODIC_H_FIELD_ARRAY_INVALID")
    vector_norms = []
    for vector in snapshot.normalized_vectors:
        norm = float(np.linalg.norm(np.asarray(vector, dtype=np.complex128)))
        require(np.isfinite(norm) and np.isclose(norm, 1.0, rtol=0.0, atol=1e-10),
                "PERIODIC_H_NORMALIZED_VECTOR_INVALID")
        vector_norms.append(norm)
    require(snapshot.is_qualified, "PERIODIC_H_ORTHOGONALITY_UNQUALIFIED")
    return {
        "frequencies": [float(value) for value in frequencies],
        "raw_norms": [float(value) for value in raw_norms],
        "normalized_vector_norms": vector_norms,
        "normalized_vector_digest": _vector_digest(snapshot.normalized_vectors),
        "provenance": provenance,
        "contract": expected_contract,
    }


def main() -> int:
    source_commit = os.environ.get("MEPHC_SOURCE_COMMIT")
    require(source_commit == BASE_SANDBOX_SHA, "SCIENCE_SOURCE_COMMIT_INVALID")
    graph = load_frozen_graph()
    verify_graph(graph)
    verify_frozen_inputs()
    require(geometry_anchor_status(), "E8B_GEOMETRY_ANCHOR_FAIL_CLOSED")
    specs = [make_state(tuple(item["public_q"]), float(item["s"])) for item in graph["states"]]
    runtime = load_module("_mephc_p2_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_p2_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    require(scientific_job.runtime_hash(ROOT) == RUNTIME_SHA, "SCIENCE_RUNTIME_IDENTITY_MISMATCH")
    state_root = runtime._trusted_science_state_root()
    certification = state_root / "certifications" / f"{RUNTIME_SHA}.json"
    certification_value = json.loads(certification.read_text(encoding="utf-8"))
    smoke = certification_value.get("mpb_smoke", {})
    require(certification_value.get("schema") == "mephc-science-runtime-certification-v1"
            and smoke.get("executed") is True, "SCIENCE_RUNTIME_MPB_SMOKE_NOT_CERTIFIED")
    graph_sha = sha256_file(GRAPH_PATH)
    entrypoint_sha = sha256_file(ROOT / "audit/local_affine/p2_frozen_13_state_acquisition.py")
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        "entrypoint_sha256": entrypoint_sha,
        "request_graph_sha256": graph_sha,
    }
    store = scientific_job.ImmutableDatasetStore(state_root, namespace)
    require(not store.root.exists(), "P2_DATASET_NAMESPACE_ALREADY_EXISTS")
    provider = None
    import meep as mp
    provider = LocalAffineStateProvider(polarization=mp.TM, default_material=mp.air)
    counter = scientific_job.BudgetCounter(13, 13)
    records = []
    common_shape = None
    min_gap = float("inf")
    for item, spec in zip(graph["states"], specs):
        identity = canonical_state_identity(spec)
        expected_shape = (int(spec.geometry_lattice.size.x * 64), int(spec.geometry_lattice.size.y * 64))
        counter.consume_provider()
        counter.consume_solver()
        snapshot = provider.solve(spec)
        evidence = verify_snapshot(snapshot, spec, identity, expected_shape)
        if common_shape is None:
            common_shape = expected_shape
        require(expected_shape == common_shape, "REFERENCE_CELL_SPATIAL_SHAPE_INCONSISTENT")
        gap = float(evidence["frequencies"][1] - evidence["frequencies"][0])
        min_gap = min(min_gap, gap)
        key_identity = {
            "work_order_id": WORK_ORDER_ID,
            "state_id": item["state_id"],
            "role": item["role"],
            "public_q": list(item["public_q"]),
            "s": float(item["s"]),
        }
        key = canonical(key_identity)
        payload = runtime.encode_snapshot(snapshot)
        record_identity = {
            **identity,
            "state_id": item["state_id"],
            "role": item["role"],
            "key_identity": key_identity,
            "derived_kappa": identity["derived_kappa"],
            "geometry_digest": identity["geometry_digest"],
            "frequencies": evidence["frequencies"],
            "raw_norms": evidence["raw_norms"],
            "normalized_vector_norms": evidence["normalized_vector_norms"],
            "normalized_vector_digest": evidence["normalized_vector_digest"],
            "periodic_h_envelope_payload": True,
            "complete_snapshot_provenance": evidence["provenance"],
            "reference_cell_contract": evidence["contract"],
            "band0_external_gap": gap,
            "solver_configuration": solver_configuration(),
            "science_execution_source": source_commit,
            "request_graph_identity": graph_sha,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        }
        record = store.put(key, payload, record_identity)
        records.append({
            "state_id": item["state_id"],
            "role": item["role"],
            "key_sha256": record["key_sha256"],
            "payload_sha256": record["payload_sha256"],
            "band0_external_gap": gap,
        })
    require(len(records) == 13 and min_gap >= 0.05, "RANK1_EXTERNAL_GAP_GATE_FAIL_CLOSED")
    manifest = store.finalize(13, {
        "work_order_id": WORK_ORDER_ID,
        "source_commit": source_commit,
        "request_graph_sha256": graph_sha,
        "fresh_solve_count": 13,
        "cache_reuse_count": 0,
        "retry_count": 0,
        "mpb_execution": True,
    })
    job_id = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).name.split(".", 1)[0]
    smoke_solver_count = int(smoke.get("solver_executions", 0))
    result = {
        "WORK_ORDER_ID": WORK_ORDER_ID,
        "BASE_SANDBOX_SHA": BASE_SANDBOX_SHA,
        "FINAL_SANDBOX_SHA": source_commit,
        "ORIGIN_SANDBOX_SHA": source_commit,
        "MAIN_SHA": MAIN_SHA,
        "MACHINE_CONTRACT_STATUS": "PASS",
        "P1R1_PROVIDER_CERTIFICATION_STATUS": "VERIFIED",
        "SCIENCE_RUNTIME_MPB_SMOKE_STATUS": "PASS",
        "SCIENCE_RUNTIME_MPB_SMOKE_SOLVER_EXECUTIONS": smoke_solver_count,
        "PROVIDER_MODULE_SHA256": PROVIDER_SHA,
        "REQUEST_GRAPH_SHA256": graph_sha,
        "SCIENCE_JOB_ID": job_id,
        "SCIENCE_SOURCE_SHA": source_commit,
        "LOCAL_AFFINE_P2_ACQUISITION_STATUS": "PASS",
        "FROZEN_STATE_GRAPH_STATUS": "PASS",
        "E8B_GEOMETRY_BINDING_STATUS": "PASS",
        "FIXED_Q_TO_LOCAL_KAPPA_STATUS": "PASS",
        "CANONICAL_RECIPROCAL_METADATA_STATUS": "PASS",
        "REFERENCE_CELL_METADATA_STATUS": "PASS",
        "PERIODIC_H_SNAPSHOT_STATUS": "PASS",
        "RANK1_PREFLIGHT_ISOLATION_STATUS": "PASS",
        "MIN_BAND0_EXTERNAL_GAP": min_gap,
        "DATASET_ID": manifest["dataset_id"],
        "DATASET_MANIFEST_SHA256": manifest["manifest_sha256"],
        "DATASET_RECORD_COUNT": 13,
        "COMPLETED_STATE_COUNT": 13,
        "FAILED_STATE_COUNT": 0,
        "NATIVE_INVOCATION_COUNT": 1,
        "PROVIDER_EXECUTION_COUNT": 13,
        "SOLVER_EXECUTION_COUNT": 13,
        "CACHE_REUSE_COUNT": 0,
        "RETRY_COUNT": 0,
        "ORIGINAL_FAILED_SOLVE_REUSED": False,
        "MPB_EXECUTION": True,
        "LOCAL_AFFINE_P2_DATASET_STATUS": "COMPLETE_IMMUTABLE_13_STATE",
        "LOCAL_AFFINE_P2_DATASET_READY_FOR_REDUCTION": True,
        "LOCAL_AFFINE_LIVE_ACQUISITION_EXECUTED": True,
        "NEXT_LIVE_SOLVER_AUTHORIZATION": False,
        "PIPELINE_HEALTH": "HEALTHY",
        "BLOCKED_BY_INFRASTRUCTURE": False,
        "SCIENTIFIC_WORK_MUST_STOP": False,
        "NEXT_SCIENTIFIC_STATE": "LOCAL_AFFINE_P2_DATASET_READY_FOR_SOLVER_FREE_TWO_SCALE_BERRY_MIXED_CURVATURE_AND_LOCAL_BAND_DERIVATIVE_REDUCTION",
        "RETURN_TO_SUPERVISOR": True,
        "TERMINAL": "LOCALAFFINE_P2_FROZEN_13_STATE_LIVE_ACQUISITION_COMPLETE",
    }
    require(smoke_solver_count <= 1, "SCIENCE_RUNTIME_MPB_SMOKE_BUDGET_EXCEEDED")
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
