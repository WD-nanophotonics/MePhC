"""Reusable receipt-bound thirteen-state LocalAffine acquisition entrypoint."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import canonical_state_identity, digest_state_identity, make_state
from mephc.local_affine_state_provider import LocalAffineStateProvider, local_affine_reference_cell_contract


ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json"
Q0 = (0.0, -0.6166666666666667)
STATE_ORDER = tuple(f"STATE_{index:02d}" for index in range(1, 14))


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, path)


def load_budget_counter() -> Any:
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("_mephc_frozen_13_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def load_runtime() -> Any:
    path = ROOT / "tools" / "mephc-flow" / "mephc_science_runtime.py"
    spec = importlib.util.spec_from_file_location("_mephc_frozen_13_runtime", path)
    require(spec is not None and spec.loader is not None, "SCIENCE_RUNTIME_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize_json(item) for item in value]
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float and np.isfinite(value):
        return value
    raise TypeError(f"UNSAFE_JSON_VALUE:{type(value).__name__}")


def load_bundle() -> dict[str, Any]:
    path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", ""))
    require(path.is_file(), "INPUT_BUNDLE_MISSING")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict) and value.get("schema") == "mephc-thin-input-bundle-v1", "INPUT_BUNDLE_SCHEMA_INVALID")
    require(isinstance(value.get("work_order_id"), str) and value["work_order_id"], "INPUT_WORK_ORDER_ID_MISSING")
    contract_sha = os.environ.get("MEPHC_SCIENCE_CONTRACT_SHA256")
    if contract_sha:
        require(value.get("contract_sha256") == contract_sha, "INPUT_CONTRACT_MISMATCH")
    return value


def supplied_namespace(bundle: dict[str, Any]) -> dict[str, Any]:
    candidates = [bundle.get("dataset_namespace"), bundle.get("namespace")]
    inputs = bundle.get("inputs")
    if isinstance(inputs, dict):
        candidates.append(inputs.get("dataset_namespace"))
        candidates.append(inputs.get("namespace"))
    namespace = next((item for item in candidates if isinstance(item, dict)), None)
    require(namespace is not None and namespace, "DATASET_NAMESPACE_INPUT_MISSING")
    return json.loads(json.dumps(namespace))


def load_graph(bundle: dict[str, Any]) -> tuple[dict[str, Any], str]:
    graph_sha = bundle.get("request_graph_sha256")
    if graph_sha is None and isinstance(bundle.get("inputs"), dict):
        graph_sha = bundle["inputs"].get("request_graph_sha256")
    observed_sha = sha256_file(GRAPH_PATH)
    if graph_sha is not None:
        require(observed_sha == graph_sha, "FROZEN_STATE_GRAPH_SHA_MISMATCH")
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    require(isinstance(graph, dict), "FROZEN_STATE_GRAPH_OBJECT_REQUIRED")
    states = graph.get("states")
    require(graph.get("state_count") == 13 and graph.get("logical_state_count") == 13 and graph.get("unique_state_count") == 13, "FROZEN_STATE_GRAPH_COUNT_INVALID")
    require(isinstance(states, list) and len(states) == 13, "FROZEN_STATE_GRAPH_STATE_LIST_INVALID")
    require([item.get("state_id") for item in states] == list(STATE_ORDER), "FROZEN_STATE_GRAPH_ORDER_INVALID")
    require(len({item.get("state_id") for item in states}) == 13, "FROZEN_STATE_GRAPH_DUPLICATE")
    return graph, observed_sha


def solver_configuration() -> dict[str, Any]:
    return {"resolution": 64, "num_bands": 6, "polarization": "TM", "eigensolver_tolerance": 1e-7, "mesh_size": 3, "deterministic": True, "phase_callback": None}


def vector_digest(vectors: Any) -> str:
    values = [[[float(item.real), float(item.imag)] for item in np.asarray(vector, dtype=np.complex128)] for vector in vectors]
    return hashlib.sha256(canonical(values)).hexdigest()


def validate_snapshot(snapshot: Any, spec: Any, identity: dict[str, Any]) -> dict[str, Any]:
    require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3, "SNAPSHOT_SHAPE_INVALID")
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    raw_norms = np.asarray(snapshot.raw_norms, dtype=float)
    require(frequencies.shape == (6,) and np.all(np.isfinite(frequencies)) and np.all(frequencies > 0.0), "SNAPSHOT_FREQUENCIES_INVALID")
    require(raw_norms.shape == (6,) and np.all(np.isfinite(raw_norms)) and np.all(raw_norms > 0.0), "SNAPSHOT_RAW_NORMS_INVALID")
    require(len(snapshot.normalized_vectors) == 6, "SNAPSHOT_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        require(np.all(np.isfinite(values)) and np.isclose(float(np.linalg.norm(values)), 1.0, rtol=0.0, atol=1e-10), "SNAPSHOT_VECTOR_INVALID")
    gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
    require(gram.shape == (6, 6) and np.all(np.isfinite(gram)), "SNAPSHOT_GRAM_INVALID")
    provenance = snapshot.provenance
    require(isinstance(provenance, Mapping), "SNAPSHOT_PROVENANCE_INVALID")
    metadata = dict(provenance)
    require(metadata.get("representation") == "mpb_periodic_h_l2_v1", "SNAPSHOT_REPRESENTATION_INVALID")
    from mephc.local_affine_state_provider import _metadata
    flattened = _metadata(snapshot)
    require(flattened.get("resolution") == 64, "EFFECTIVE_RESOLUTION_INVALID")
    reciprocal = provenance.get("mpb_k_point")
    require(isinstance(reciprocal, (list, tuple)) and len(reciprocal) == 3, "RECIPROCAL_METADATA_INVALID")
    require(np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity["derived_kappa"]), rtol=0.0, atol=1e-9) and float(reciprocal[2]) == 0.0, "RECIPROCAL_METADATA_MISMATCH")
    actual = normalize_json(provenance.get("local_affine_reference_cell_contract"))
    expected = normalize_json(local_affine_reference_cell_contract(spec, spatial_shape=tuple(snapshot.spatial_shape), identity=identity, lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y))))
    actual_sha = hashlib.sha256(canonical(actual)).hexdigest()
    expected_sha = hashlib.sha256(canonical(expected)).hexdigest()
    require(actual_sha == expected_sha and canonical(actual) == canonical(expected), "REFERENCE_CELL_METADATA_INVALID")
    require(provenance.get("local_affine_solver_polarization_identity") == "TM", "POLARIZATION_IDENTITY_INVALID")
    require(provenance.get("phase_callback") in (None, "None") or "phase_callback" not in provenance, "PHASE_CALLBACK_INVALID")
    return {
        "frequencies": [float(item) for item in frequencies],
        "raw_norms": [float(item) for item in raw_norms],
        "normalized_vector_digest": vector_digest(snapshot.normalized_vectors),
        "reference_cell_contract_sha256": actual_sha,
        "reciprocal_metadata": [float(item) for item in reciprocal],
        "payload_snapshot_validated": True,
    }


def main() -> int:
    bundle = load_bundle()
    graph, graph_sha = load_graph(bundle)
    budgets = bundle.get("budgets") or (bundle.get("contract") or {}).get("budgets") or (bundle.get("inputs") or {}).get("budgets")
    require(isinstance(budgets, dict) and budgets.get("native_invocations") == 13 and budgets.get("provider_requests") == 13 and budgets.get("solver_executions") == 13, "ACQUISITION_BUDGET_NOT_THIRTEEN")
    source_commit = os.environ.get("MEPHC_SOURCE_COMMIT")
    require(isinstance(source_commit, str) and source_commit, "SCIENCE_SOURCE_COMMIT_MISSING")
    namespace = supplied_namespace(bundle)
    runtime = load_runtime()
    BudgetCounter = load_budget_counter()
    job_module = importlib.util.spec_from_file_location("_mephc_frozen_13_job", ROOT / "tools" / "mephc-flow" / "scientific_job.py")
    require(job_module is not None and job_module.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    job = importlib.util.module_from_spec(job_module)
    job_module.loader.exec_module(job)
    state_root = runtime._trusted_science_state_root()
    namespace["request_graph_sha256"] = namespace.get("request_graph_sha256", graph_sha)
    store = job.ImmutableDatasetStore(state_root, namespace)
    require(not store.root.exists(), "DATASET_NAMESPACE_ALREADY_EXISTS")
    import meep as mp
    provider = LocalAffineStateProvider(resolution=64, num_bands=6, eigensolver_tolerance=1e-7, mesh_size=3, deterministic=True, polarization=mp.TM, polarization_identity="TM", default_material=mp.air)
    counter = BudgetCounter(13, 13)
    records: list[dict[str, Any]] = []
    min_gap = float("inf")
    common_shape: tuple[int, int] | None = None
    failed: dict[str, Any] | None = None
    for item in graph["states"]:
        state_id = item["state_id"]
        stage = "STATE_CONSTRUCTION"
        try:
            spec = make_state(tuple(item["public_q"]), float(item["s"]))
            identity_before = canonical_state_identity(spec)
            require(identity_before["public_q"] == list(item["public_q"]) and identity_before["s"] == float(item["s"]), "STATE_IDENTITY_INPUT_INVALID")
            require(isinstance(spec.geometry, tuple), "STATE_GEOMETRY_NOT_TUPLE")
            stage = "PROVIDER_SOLVE"
            counter.consume_provider()
            counter.consume_solver()
            snapshot = provider.solve(spec)
            stage = "SNAPSHOT_VALIDATION"
            identity_after = canonical_state_identity(spec)
            require(identity_before == identity_after and isinstance(spec.geometry, tuple), "STATE_IDENTITY_MUTATED")
            evidence = validate_snapshot(snapshot, spec, identity_before)
            expected_shape = tuple(snapshot.spatial_shape)
            if common_shape is None:
                common_shape = expected_shape
            require(expected_shape == common_shape, "COMMON_SPATIAL_SHAPE_INVALID")
            gap = float(evidence["frequencies"][1] - evidence["frequencies"][0])
            require(math.isfinite(gap), "EXTERNAL_GAP_NONFINITE")
            min_gap = min(min_gap, gap)
            key_identity = {"work_order_id": bundle["work_order_id"], "state_id": state_id, "role": item["role"], "public_q": list(item["public_q"]), "s": float(item["s"])}
            key = canonical(key_identity)
            payload = runtime.encode_snapshot(snapshot)
            record_identity = {
                "state_id": state_id, "role": item["role"], "public_q": list(item["public_q"]), "s": float(item["s"]),
                "canonical_state_identity": identity_before, "canonical_state_identity_sha256": digest_state_identity(identity_before),
                "solver_configuration": solver_configuration(), "reciprocal_metadata": evidence["reciprocal_metadata"],
                "reference_cell_contract_sha256": evidence["reference_cell_contract_sha256"], "frequencies": evidence["frequencies"], "raw_norms": evidence["raw_norms"],
                "normalized_vector_digest": evidence["normalized_vector_digest"], "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "request_graph_sha256": graph_sha, "science_source_commit": source_commit,
            }
            stored = store.put(key, payload, record_identity)
            records.append({"state_id": state_id, "key_sha256": stored["key_sha256"], "payload_sha256": stored["payload_sha256"], "band0_external_gap": gap})
        except Exception as exc:
            failed = {"failed_state_id": state_id, "failed_stage": stage, "failure_code": str(exc).strip() or type(exc).__name__, "exception_type": type(exc).__name__, "completed_state_count": len(records)}
            break
    if failed is not None:
        write_result({"schema": "mephc-local-affine-frozen-13-state-live-acquisition-v2-result-v1", "work_order_id": bundle["work_order_id"], "status": "FAIL", "scientific_status": "FAIL_CLOSED", "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "failed_state": failed, "field_payload_retained": False})
        return 1
    require(len(records) == 13 and min_gap >= 0.05, "RANK1_EXTERNAL_GAP_GATE_FAIL_CLOSED")
    manifest = store.finalize(13, {"work_order_id": bundle["work_order_id"], "source_commit": source_commit, "request_graph_sha256": graph_sha, "fresh_solve_count": 13, "cache_reuse_count": 0, "retry_count": 0})
    write_result({"schema": "mephc-local-affine-frozen-13-state-live-acquisition-v2-result-v1", "work_order_id": bundle["work_order_id"], "status": "PASS", "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "dataset_record_count": 13, "completed_state_count": 13, "failed_state_count": 0, "native_invocation_count": 1, "provider_execution_count": 13, "solver_execution_count": 13, "minimum_external_gap": min_gap, "rank1_preflight_threshold": 0.05, "rank1_preflight_pass": True, "records": records, "field_payload_retained": False, "retry_count": 0, "cache_reuse_count": 0})
    return 0


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


if __name__ == "__main__":
    raise SystemExit(main())
