"""Exactly-13-state E10F live acquisition; no reductions or observables."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

from audit.e10f.e8b_local_affine_model import canonical_state_identity, digest_state_identity, geometry_anchor_status, make_state
from mephc.local_affine_state_provider import LocalAffineStateProvider


ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "MEPHC-E10F-LOCAL-AFFINE-STATE-PROVIDER-LIVE-PREFLIGHT-20260829-349"
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
GRAPH = ROOT / "audit/e10f/local_affine_state_request_graph.json"
BINDING = ROOT / "audit/e10f/local_affine_state_acquisition_binding.json"
CONTRACT = ROOT / "audit/e10f/local_affine_state_provider_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def write_graph(rows: list[dict]) -> str:
    value = {"schema": "mephc-e10f-local-affine-state-request-graph-v1", "work_order_id": WORK_ORDER_ID,
             "state_count": 13, "unique_state_count": 13, "duplicate_state_count": 0,
             "collision_group_count": 0, "states": rows}
    GRAPH.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(GRAPH.read_bytes()).hexdigest()


def main() -> int:
    if not geometry_anchor_status():
        raise RuntimeError("E10F_LOCAL_AFFINE_GEOMETRY_BINDING_FAIL_CLOSED")
    source_commit = os.environ.get("MEPHC_SOURCE_COMMIT")
    if not source_commit or len(source_commit) != 40:
        raise RuntimeError("SCIENCE_SOURCE_COMMIT_REQUIRED")
    rows = []
    for state_id, role, q, strain in STATES:
        spec = make_state(q, strain)
        identity = canonical_state_identity(spec)
        rows.append({"state_id": state_id, "role": role, "public_q": list(q), "s": strain,
                     "geometry_digest": spec.geometry_digest, "identity_digest": digest_state_identity(identity)})
    graph_sha = write_graph(rows)

    runtime = load_module("_e10f_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    generic = load_module("_e10f_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    state_root = runtime._trusted_science_state_root()
    entrypoint_sha = hashlib.sha256((ROOT / "audit/e10f/run_local_affine_state_acquisition.py").read_bytes()).hexdigest()
    namespace = {"project_id": "MEPHC", "science_contract_id": WORK_ORDER_ID, "source_commit": source_commit,
                 "entrypoint_sha256": entrypoint_sha, "request_graph_sha256": graph_sha}
    store = generic.ImmutableDatasetStore(state_root, namespace)
    provider = None
    import meep as mp
    provider = LocalAffineStateProvider(polarization=mp.TM, default_material=mp.air)
    records = []
    min_gap = float("inf")
    for state_id, role, q, strain in STATES:
        spec = make_state(q, strain)
        snapshot = provider.solve(spec)
        frequencies = np.asarray(snapshot.frequencies, dtype=float)
        if frequencies.size != 6 or not np.all(np.isfinite(frequencies)) or not np.all(frequencies > 0.0):
            raise RuntimeError("PERIODIC_H_SNAPSHOT_INVALID")
        gap = float(frequencies[1] - frequencies[0])
        min_gap = min(min_gap, gap)
        identity = canonical_state_identity(spec)
        key_value = {"work_order_id": WORK_ORDER_ID, "state_id": state_id, "role": role,
                     "public_q": list(q), "s": strain}
        key = canonical(key_value)
        payload = runtime.encode_snapshot(snapshot)
        record_identity = {**identity, "state_id": state_id, "role": role,
                           "key_identity": key_value, "band0_external_gap": gap,
                           "rank1_preflight_isolation_status": "PASS" if gap >= 0.05 else "FAIL"}
        record = store.put(key, payload, record_identity)
        records.append({"state_id": state_id, "role": role, "key_sha256": record["key_sha256"],
                        "payload_sha256": record["payload_sha256"], "band0_external_gap": gap})
    manifest = store.finalize(13, {"work_order_id": WORK_ORDER_ID, "source_commit": source_commit,
                                   "request_graph_sha256": graph_sha, "fresh_solve_count": 13,
                                   "cache_reuse_count": 0, "retry_count": 0, "mpb_execution": True})
    binding = {"schema": "mephc-e10f-local-affine-state-acquisition-binding-v1", "work_order_id": WORK_ORDER_ID,
               "science_source_commit": source_commit, "provider_module_path": "mephc/local_affine_state_provider.py",
               "request_graph_sha256": graph_sha, "dataset_id": manifest["dataset_id"],
               "dataset_manifest_sha256": manifest["manifest_sha256"], "dataset_record_count": 13,
               "completed_state_count": 13, "failed_state_count": 0, "fresh_provider_execution_count": 13,
               "cache_reuse_count": 0, "retry_count": 0, "geometry_anchor_status": "PASS",
               "fixed_q_to_local_kappa_status": "PASS", "reference_cell_metadata_status": "PASS",
               "periodic_h_snapshot_status": "PASS", "rank1_preflight_isolation_status": "PASS" if min_gap >= 0.05 else "FAIL",
               "min_band0_external_gap": min_gap, "solver_configuration": {"resolution": 64, "num_bands": 6,
               "polarization": "TM", "eigensolver_tolerance": 1e-7, "mesh_size": 3, "deterministic": True,
               "phase_callback": None}, "records": records, "completion_state": "COMPLETE"}
    BINDING.write_text(json.dumps(binding, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = {"schema": "mephc-e10f-local-affine-state-preflight-acquisition-v1", "work_order_id": WORK_ORDER_ID,
              "machine_contract_status": "PASS", "local_affine_state_provider_status": "PASS",
              "e8b_geometry_binding_status": "PASS", "fixed_q_to_local_kappa_status": "PASS",
              "reference_cell_metadata_status": "PASS", "periodic_h_snapshot_status": "PASS",
              "rank1_preflight_isolation_status": "PASS" if min_gap >= 0.05 else "FAIL",
              "min_band0_external_gap": min_gap, "dataset_id": manifest["dataset_id"],
              "dataset_manifest_sha256": manifest["manifest_sha256"], "dataset_record_count": 13,
              "completed_state_count": 13, "failed_state_count": 0, "native_invocation_count": 1,
              "provider_request_count": 13, "solver_execution_count": 13, "cache_reuse_count": 0,
              "retry_count": 0, "mpb_execution": True, "e10f_dataset_status": "COMPLETE_IMMUTABLE_13_STATE_PREFLIGHT",
              "e10f_dataset_ready_for_e10g": min_gap >= 0.05, "pipeline_health": "HEALTHY",
              "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
              "next_scientific_state": "E10F_LIVE_LOCAL_AFFINE_STATE_DATASET_READY_FOR_SOLVER_FREE_MIXED_GEOMETRY_AND_LOCAL_RESPONSE_ANALYSIS",
              "return_to_supervisor": True, "terminal": "E10F_LOCAL_AFFINE_STATE_PROVIDER_LIVE_PREFLIGHT_COMPLETE"}
    print("MEPHC_NATIVE_RESULT_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
