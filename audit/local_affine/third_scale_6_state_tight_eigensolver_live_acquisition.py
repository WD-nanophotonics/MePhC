"""Future tight-tolerance third-scale acquisition entrypoint."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from audit.e10f.e8b_local_affine_model import canonical_state_identity, digest_state_identity, make_state
from audit.local_affine.local_affine_snapshot_codec import encode_snapshot
from mephc.local_affine_state_provider import LocalAffineStateProvider, canonical_local_affine_state_identity, local_affine_reference_cell_contract


ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "audit" / "local_affine" / "p84_third_scale_6_state_request_graph.json"
Q0 = (0.0, -0.6166666666666667)
STATE_ORDER = tuple(f"STATE_{index:02d}" for index in range(14, 20))
RESULT_SCHEMA = "mephc-local-affine-third-scale-tight-eigensolver-live-acquisition-v1"
SOLVER_CONFIGURATION = {
    "resolution": 64,
    "num_bands": 6,
    "polarization": "TM",
    "eigensolver_tolerance": 1e-9,
    "mesh_size": 3,
    "deterministic": True,
    "phase_callback": None,
}


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
    spec = importlib.util.spec_from_file_location("_mephc_p92_scientific_job", path)
    require(spec is not None and spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BudgetCounter


def load_current_runtime() -> Any:
    path = ROOT / "tools" / "mephc-flow" / "mephc_runtime.py"
    spec = importlib.util.spec_from_file_location("_mephc_p92_runtime", path)
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
    if type(value) is float and math.isfinite(value):
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
        candidates.extend((inputs.get("dataset_namespace"), inputs.get("namespace")))
    namespace = next((item for item in candidates if isinstance(item, dict) and item), None)
    require(namespace is not None, "DATASET_NAMESPACE_INPUT_MISSING")
    return json.loads(json.dumps(namespace))


def load_graph(bundle: dict[str, Any]) -> tuple[dict[str, Any], str]:
    graph_sha = bundle.get("request_graph_sha256")
    if graph_sha is None and isinstance(bundle.get("inputs"), dict):
        graph_sha = bundle["inputs"].get("request_graph_sha256")
    observed_sha = sha256_file(GRAPH_PATH)
    if graph_sha is not None:
        require(observed_sha == graph_sha, "THIRD_SCALE_GRAPH_SHA_MISMATCH")
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    require(isinstance(graph, dict) and graph.get("schema") == "mephc-local-affine-p84-third-scale-6-state-request-graph-v1", "THIRD_SCALE_GRAPH_SCHEMA_INVALID")
    states = graph.get("states")
    require(graph.get("state_count") == 6 and graph.get("logical_state_count") == 6 and graph.get("unique_state_count") == 6, "THIRD_SCALE_GRAPH_COUNT_INVALID")
    require(isinstance(states, list) and len(states) == 6, "THIRD_SCALE_GRAPH_STATE_LIST_INVALID")
    require([item.get("state_id") for item in states] == list(STATE_ORDER), "THIRD_SCALE_GRAPH_ORDER_INVALID")
    require(len({item.get("state_id") for item in states}) == 6, "THIRD_SCALE_GRAPH_DUPLICATE")
    return graph, observed_sha


def validate_acquisition_budgets(budgets: Any) -> bool:
    require(isinstance(budgets, dict) and budgets.get("native_invocations") == 1 and budgets.get("provider_requests") == 6 and budgets.get("solver_executions") == 6, "ACQUISITION_BUDGET_NOT_1_6_6")
    return True


def validate_framework_budgets(environment: Mapping[str, str] | None = None) -> dict[str, int]:
    values = os.environ if environment is None else environment
    result: dict[str, int] = {}
    for name, output_name in (("MEPHC_PROVIDER_REQUEST_BUDGET", "provider_requests"), ("MEPHC_SOLVER_EXECUTION_BUDGET", "solver_executions")):
        raw = values.get(name)
        require(isinstance(raw, str) and raw.isdigit() and str(int(raw)) == raw, f"{name}_INVALID")
        value = int(raw)
        require(value == 6, f"{name}_NOT_6")
        result[output_name] = value
    return result


def rank1_preflight(minimum_gap: float, threshold: float = 0.05) -> bool:
    return bool(math.isfinite(minimum_gap) and minimum_gap >= threshold)


def solver_free_reduction_ready(record_count: int, rank1_pass: bool) -> bool:
    return record_count == 6 and rank1_pass


def derive_record_key_sha256(work_order_id: str, state_id: str, role: str, public_q: Any, s: float) -> str:
    key_identity = {"work_order_id": work_order_id, "state_id": state_id, "role": role, "public_q": list(public_q), "s": float(s)}
    return hashlib.sha256(canonical(key_identity)).hexdigest()


def vector_digest(vectors: Any) -> str:
    values = [[[float(item.real), float(item.imag)] for item in np.asarray(vector, dtype=np.complex128)] for vector in vectors]
    return hashlib.sha256(canonical(values)).hexdigest()


def make_tight_state(public_q: Any, s: float) -> Any:
    base = make_state(tuple(public_q), float(s))
    return replace(base, eigensolver_tolerance=SOLVER_CONFIGURATION["eigensolver_tolerance"])


def canonical_tight_state_identity(spec: Any) -> dict[str, Any]:
    return canonical_local_affine_state_identity(
        spec,
        resolution=SOLVER_CONFIGURATION["resolution"],
        num_bands=SOLVER_CONFIGURATION["num_bands"],
        polarization_identity=SOLVER_CONFIGURATION["polarization"],
        eigensolver_tolerance=SOLVER_CONFIGURATION["eigensolver_tolerance"],
        mesh_size=SOLVER_CONFIGURATION["mesh_size"],
        deterministic=SOLVER_CONFIGURATION["deterministic"],
    )


def validate_snapshot(snapshot: Any, spec: Any, identity: dict[str, Any]) -> dict[str, Any]:
    require(tuple(snapshot.spatial_shape) == (64, 64) and snapshot.component_count == 3, "SNAPSHOT_SHAPE_INVALID")
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    raw_norms = np.asarray(snapshot.raw_norms, dtype=float)
    require(frequencies.shape == (6,) and bool(np.all(np.isfinite(frequencies))) and bool(np.all(frequencies > 0.0)), "SNAPSHOT_FREQUENCIES_INVALID")
    require(raw_norms.shape == (6,) and bool(np.all(np.isfinite(raw_norms))) and bool(np.all(raw_norms > 0.0)), "SNAPSHOT_RAW_NORMS_INVALID")
    require(len(snapshot.normalized_vectors) == 6, "SNAPSHOT_VECTOR_COUNT_INVALID")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        require(bool(np.all(np.isfinite(values))) and math.isclose(float(np.linalg.norm(values)), 1.0, rel_tol=0.0, abs_tol=1e-10), "SNAPSHOT_VECTOR_INVALID")
    gram = np.asarray(snapshot.gram_matrix, dtype=np.complex128)
    require(gram.shape == (6, 6) and bool(np.all(np.isfinite(gram))), "SNAPSHOT_GRAM_INVALID")
    provenance = normalize_json(snapshot.provenance)
    require(isinstance(provenance, dict) and provenance.get("representation") == "mpb_periodic_h_l2_v1", "SNAPSHOT_PROVENANCE_INVALID")
    reciprocal = provenance.get("mpb_k_point")
    require(isinstance(reciprocal, list) and len(reciprocal) == 3, "RECIPROCAL_METADATA_INVALID")
    require(bool(np.allclose(np.asarray(reciprocal[:2], dtype=float), np.asarray(identity["derived_kappa"]), rtol=0.0, atol=1e-9)) and float(reciprocal[2]) == 0.0, "RECIPROCAL_METADATA_MISMATCH")
    actual = normalize_json(provenance.get("local_affine_reference_cell_contract"))
    expected = normalize_json(local_affine_reference_cell_contract(spec, spatial_shape=(64, 64), identity=identity, lattice_size=(float(spec.geometry_lattice.size.x), float(spec.geometry_lattice.size.y))))
    actual_sha = hashlib.sha256(canonical(actual)).hexdigest()
    expected_sha = hashlib.sha256(canonical(expected)).hexdigest()
    require(actual_sha == expected_sha and canonical(actual) == canonical(expected), "REFERENCE_CELL_METADATA_INVALID")
    require(provenance.get("local_affine_solver_polarization_identity") == "TM", "POLARIZATION_IDENTITY_INVALID")
    require(provenance.get("phase_callback") in (None, "None") or "phase_callback" not in provenance, "PHASE_CALLBACK_INVALID")
    return {"frequencies": [float(item) for item in frequencies], "raw_norms": [float(item) for item in raw_norms], "normalized_vector_digest": vector_digest(snapshot.normalized_vectors), "reference_cell_contract_sha256": actual_sha, "reciprocal_metadata": [float(item) for item in reciprocal]}


def write_result(value: dict[str, Any]) -> None:
    write_json(Path(os.environ["MEPHC_RESULT_PATH"]), value)


def failure_result(work_order_id: str, failed: dict[str, Any], provider_count: int, solver_count: int, dataset_record_count: int) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "work_order_id": work_order_id,
        "status": "PASS",
        "scientific_acceptance_status": "FAIL",
        "native_invocation_count": 1,
        "provider_execution_count": provider_count,
        "solver_execution_count": solver_count,
        "dataset_record_count": dataset_record_count,
        "failed_state_id": failed["failed_state_id"],
        "failed_stage": failed["failed_stage"],
        "failure_code": failed["failure_code"],
        "exception_type": failed["exception_type"],
        "completed_state_count": failed["completed_state_count"],
        "field_payload_retained": False,
    }


def success_result(work_order_id: str, manifest: Mapping[str, Any], minimum_gap: float, rank1_pass: bool, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "work_order_id": work_order_id,
        "status": "PASS",
        "scientific_acceptance_status": "PASS",
        "dataset_id": manifest["dataset_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "dataset_record_count": 6,
        "completed_state_count": 6,
        "failed_state_count": 0,
        "minimum_external_gap": minimum_gap,
        "rank1_preflight_threshold": 0.05,
        "rank1_preflight_pass": rank1_pass,
        "solver_free_reduction_ready": solver_free_reduction_ready(6, rank1_pass),
        "provider_execution_count": 6,
        "solver_execution_count": 6,
        "native_invocation_count": 1,
        "records": records,
        "field_payload_retained": False,
    }


def main() -> int:
    bundle = load_bundle()
    graph, graph_sha = load_graph(bundle)
    framework_budgets = validate_framework_budgets()
    source_commit = os.environ.get("MEPHC_SOURCE_COMMIT")
    require(isinstance(source_commit, str) and source_commit, "SCIENCE_SOURCE_COMMIT_MISSING")
    namespace = supplied_namespace(bundle)
    runtime = load_current_runtime()
    BudgetCounter = load_budget_counter()
    job_spec = importlib.util.spec_from_file_location("_mephc_p92_job", ROOT / "tools" / "mephc-flow" / "scientific_job.py")
    require(job_spec is not None and job_spec.loader is not None, "SCIENTIFIC_JOB_MODULE_UNAVAILABLE")
    job_module = importlib.util.module_from_spec(job_spec)
    job_spec.loader.exec_module(job_module)
    store = job_module.ImmutableDatasetStore(runtime.SCIENCE_STATE, namespace)
    require(not store.root.exists(), "DATASET_NAMESPACE_ALREADY_EXISTS")
    import meep as mp
    provider = LocalAffineStateProvider(resolution=64, num_bands=6, eigensolver_tolerance=1e-9, mesh_size=3, deterministic=True, polarization=mp.TM, polarization_identity="TM", default_material=mp.air)
    counter = BudgetCounter(framework_budgets["provider_requests"], framework_budgets["solver_executions"])
    records: list[dict[str, Any]] = []
    minimum_gap = float("inf")
    failed: dict[str, Any] | None = None
    for item in graph["states"]:
        state_id = item["state_id"]
        stage = "STATE_CONSTRUCTION"
        try:
            spec = make_tight_state(item["public_q"], float(item["s"]))
            identity_before = canonical_tight_state_identity(spec)
            require(identity_before["public_q"] == list(item["public_q"]) and identity_before["s"] == float(item["s"]), "STATE_IDENTITY_INPUT_INVALID")
            require(isinstance(spec.geometry, tuple), "STATE_GEOMETRY_NOT_TUPLE")
            stage = "PROVIDER_SOLVE"
            counter.consume_provider()
            counter.consume_solver()
            snapshot = provider.solve(spec)
            stage = "SNAPSHOT_VALIDATION"
            identity_after = canonical_tight_state_identity(spec)
            require(identity_before == identity_after and isinstance(spec.geometry, tuple), "STATE_IDENTITY_MUTATED")
            evidence = validate_snapshot(snapshot, spec, identity_before)
            gap = evidence["frequencies"][1] - evidence["frequencies"][0]
            require(math.isfinite(gap), "EXTERNAL_GAP_NONFINITE")
            minimum_gap = min(minimum_gap, gap)
            payload = encode_snapshot(snapshot)
            record_identity = {
                "state_id": state_id, "role": item["role"], "public_q": list(item["public_q"]), "s": float(item["s"]),
                "canonical_state_identity": identity_before, "canonical_state_identity_sha256": digest_state_identity(identity_before),
                "solver_configuration": SOLVER_CONFIGURATION, "reciprocal_metadata": evidence["reciprocal_metadata"],
                "reference_cell_contract_sha256": evidence["reference_cell_contract_sha256"], "frequencies": evidence["frequencies"], "raw_norms": evidence["raw_norms"],
                "normalized_vector_digest": evidence["normalized_vector_digest"], "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "request_graph_sha256": graph_sha, "science_source_commit": source_commit,
            }
            stored = store.put(canonical({"work_order_id": bundle["work_order_id"], "state_id": state_id, "role": item["role"], "public_q": list(item["public_q"]), "s": float(item["s"])}), payload, record_identity)
            require(stored["key_sha256"] == derive_record_key_sha256(bundle["work_order_id"], state_id, item["role"], item["public_q"], item["s"]), "RECORD_KEY_DERIVATION_INVALID")
            records.append({"state_id": state_id, "key_sha256": stored["key_sha256"], "payload_sha256": stored["payload_sha256"], "band0_external_gap": gap})
        except Exception as exc:
            failed = {"failed_state_id": state_id, "failed_stage": stage, "failure_code": str(exc).strip() or type(exc).__name__, "exception_type": type(exc).__name__, "completed_state_count": len(records)}
            break
    if failed is not None:
        write_result(failure_result(bundle["work_order_id"], failed, counter.provider_count, counter.solver_count, len(records)))
        return 0
    require(len(records) == 6, "DATASET_COMPLETION_COUNT_INVALID")
    rank1_pass = rank1_preflight(minimum_gap)
    manifest = store.finalize(6, {"work_order_id": bundle["work_order_id"], "source_commit": source_commit, "request_graph_sha256": graph_sha, "fresh_solve_count": 6, "cache_reuse_count": 0, "retry_count": 0})
    write_result(success_result(bundle["work_order_id"], manifest, minimum_gap, rank1_pass, records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
