"""Solver-free C8 parity-aware terminal fixed-h analysis.

This entrypoint consumes the immutable R8 parent, reconciled R192, and
reconciled R224 datasets.  It reuses the accepted C1 rank-one estimator and
only produces bounded scalar evidence plus a prospective, non-executing
next-axis graph.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

C4_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c4_fixed_h_resolution_analysis.py"
C5_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c5_r224_targeted_acquisition.py"
C4_EVIDENCE_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c4_fixed_h_resolution_evidence.json"
C4_NEXT_AXIS_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c4_next_axis_contract.json"
R224_GRAPH_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c5_r224_request_graph.json"
R224_RECONCILIATION_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c5_r224_state_reconciliation.json"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
C7_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c7_r256_targeted_acquisition.py"
C7_GRAPH_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c7_r256_request_graph.json"
C7_BINDING_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c7_r256_acquisition_binding.json"
C7_RECONCILIATION_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c7_r256_closeout_reconciliation.json"
C7_METHOD_CONTRACT_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c7_parity_aware_method_contract.json"
C6_EVIDENCE_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c6_adaptive_terminal_fixed_h_evidence.json"
SCIENCE_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"
EVIDENCE_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c8_parity_aware_terminal_evidence.json"
NEXT_AXIS_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c8_next_axis_contract.json"

WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C8-M1-20260828-317"
BASE_SANDBOX_SHA = "496bb6dcd8c6a25d35f35d17a7c03a18897668f1"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
C4_RESULT_SHA256 = "d07e2d2962ce7283098a70ee70444c406309b6581f1be4fd4407d01de55443df"
C4_EVIDENCE_SHA256 = "58dd6dbcfcad91ada4ac4a45184bda05f502db4b378047d4068646310d802bad"
C4_NEXT_AXIS_SHA256 = "e43db4389cb2717c8e5703651950feaa8a98fc711dcdf5ca302309835c34753c"
R224_RECONCILIATION_SHA256 = "ed26664f48ff001ffc8c4e679c19635922df8c14878aeaae11d75fbbaa5cf2af"
R224_SOURCE_COMMIT = "f9e4561e34423c5d90389c7a54f40bf59c057718"
R224_ACQUISITION_DATASET_ID = "df64679167793d7797330d234c3d7ec7525070d6699066aa609409a121af6d3e"
R224_ACQUISITION_MANIFEST_SHA256 = "0a32c402376bb11ab88e772fa8c40d695e11e8dea6645087a7410bb9bfd37335"
R224_GENERIC_DATASET_ID = "574097e09e10a4dcd951b068eeef89dc208899600656a525bed265e790c168cd"
R224_GENERIC_MANIFEST_SHA256 = "dd913ff7b640e911363c28b3f471a521cc0fea86d7a616a4fb26ab562fcb8bdd"
R224_ENTRYPOINT_SHA256 = "6ce9d6fa34a8b988f9aa70974f67629729512b474b221442a3d40a4784977699"
R224_GRAPH_SHA256 = "fec37a1395ee438003f3bb3913d9aefedcd53dee2545f3ea4b1d5c7607b3dcdc"
R224_RUNTIME_SHA256 = "a540fc7af70bf5ac2d75caa614b788abb6cc7502f594fcd618b5ab8fb691f1ad"
R224_NAMESPACE_SHA256 = "d247bf45c563c62625788514434d2904042ce639cb4bf817817f15c64b9fe7df"
R256_BINDING_SHA256 = "0872b26cb37d695ae4cf532f17cc7116eb3f798491d59e25f11dc74819be90b9"
R256_RECONCILIATION_SHA256 = "0cbfcde4e6736bc68a0563ff36daab98a2b79fab05da4ebb95d9a80d87f6453e"
R256_SOURCE_COMMIT = "66990c1613660328762ce3344b9808d7a0e38983"
R256_ACQUISITION_DATASET_ID = "4d7cd0afd3c9601d6d8f921c8b614a7654055adcfe540bef06f8f76de49a10d2"
R256_ACQUISITION_MANIFEST_SHA256 = "e352f49bd1f60f3ba13a5681fc4f6d7a8291916117551c20cfa3e733e55d4773"
R256_GENERIC_DATASET_ID = "e50684c539ac5456108f9157ea852e12717ad55b38fc25c05fce9df00a4ba765"
R256_GENERIC_MANIFEST_SHA256 = "cbd852da18cbd8e3923e4f7c01f0f40a218960eae969fa747dbe2a73e34d0b05"
R256_ENTRYPOINT_SHA256 = "7df6ecd5eec63b91e7fa28f2295d4fa918b4e8d56f4251c2ee4999f5d606dac4"
R256_GRAPH_SHA256 = "a86cea5a0aedbeb9c94ebbc5cd58c8b68c9002e461c2149a1c8b3c044d32a49c"
R256_RUNTIME_SHA256 = "a540fc7af70bf5ac2d75caa614b788abb6cc7502f594fcd618b5ab8fb691f1ad"
R256_NAMESPACE_SHA256 = "47dc7692334d2e36fb1bde6a989193008c330a18c278ee73b5d85ec754b08f89"
PARITY_METHOD_SHA256 = "813b079a49865a65424b117bdbb9e825f28680a2dffbfc9cca636b638eb17da8"
C7_RECONCILIATION_SHA256 = R256_RECONCILIATION_SHA256
C6_EVIDENCE_SHA256 = "ab28d543e7701245f0d37ea102a7d17c3c9d90568aa20f98a264c94858c185a7"

RESOLUTIONS = ("R96", "R128", "R160", "R192", "R224", "R256")
RESOLUTION_ORDER = {value: index for index, value in enumerate(RESOLUTIONS)}
STENCILS = ("1/72", "1/144")
TARGETED_SAMPLES = (
    (-10, -3, "CALIBRATION_CONTROL"), (-6, -1, "STENCIL_DIAGNOSTIC"),
    (-5, 0, "POLICY_CHALLENGE"), (-4, 0, "POLICY_CHALLENGE"),
)
ALL_SAMPLES = (
    (-10, -3, "CALIBRATION_CONTROL"), (-34, 9, "CALIBRATION_CONTROL"),
    (-6, -1, "STENCIL_DIAGNOSTIC"), (-34, -16, "POLICY_CHALLENGE"),
    (-34, -17, "POLICY_CHALLENGE"), (-34, 17, "POLICY_CHALLENGE"),
    (-5, 0, "POLICY_CHALLENGE"), (-4, 0, "POLICY_CHALLENGE"),
)
TARGETED_IDS = {f"fr=0;grid_i={i};grid_j={j};estimator=SOURCE_GRID" for i, j, _ in TARGETED_SAMPLES}
POINTS = {
    "1/72": ("H72_PLUS_X", "H72_PLUS_Y", "H72_MINUS_X", "H72_MINUS_Y", "CENTER"),
    "1/144": ("H144_PLUS_X", "H144_PLUS_Y", "H144_MINUS_X", "H144_MINUS_Y", "CENTER"),
}


class AnalysisError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"JSON_UNAVAILABLE:{path.name}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name: str, path: Path) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AnalysisError(f"MODULE_UNAVAILABLE:{path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sample_id(i: int, j: int) -> str:
    return f"fr=0;grid_i={i};grid_j={j};estimator=SOURCE_GRID"


def current_source_commit() -> str:
    value = os.environ.get("MEPHC_SOURCE_COMMIT", BASE_SANDBOX_SHA)
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise AnalysisError("CURRENT_SOURCE_COMMIT_INVALID")
    return value


def relation(first: float, second: float) -> str:
    if first == 0.0 and second == 0.0:
        return "ALL_ZERO_STABLE"
    if second < first:
        return "FINAL_INCREMENT_CONTRACTS"
    if second > first:
        return "FINAL_INCREMENT_EXPANDS"
    return "FINAL_INCREMENT_EQUAL_NONZERO"


def srd(left: float, right: float) -> float:
    left, right = float(left), float(right)
    if left == 0.0 and right == 0.0:
        return 0.0
    return 2.0 * abs(left - right) / (abs(left) + abs(right))



def verify_r224_reconciliation() -> dict[str, Any]:
    if sha256(R224_RECONCILIATION_PATH) != R224_RECONCILIATION_SHA256:
        raise AnalysisError("R224_RECONCILIATION_SHA256_MISMATCH")
    value = read_json(R224_RECONCILIATION_PATH)
    expected = {
        "schema": "mephc-r8-c5-r224-state-reconciliation-v1",
        "work_order_id": "MEPHC-E9F-C2-QP-B-C2-C3-R8-C5-I1-20260828-313",
        "reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED",
        "source_commit": R224_SOURCE_COMMIT,
        "native_rerun": False, "mpb_retry": False, "recomputation": False,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise AnalysisError("R224_RECONCILIATION_INVALID")
    dataset = value.get("dataset", {})
    if (not isinstance(dataset, dict)
            or dataset.get("namespace_sha256") != R224_NAMESPACE_SHA256
            or dataset.get("acquisition_dataset_id") != R224_ACQUISITION_DATASET_ID
            or dataset.get("acquisition_manifest_sha256") != R224_ACQUISITION_MANIFEST_SHA256
            or dataset.get("dataset_id") != R224_GENERIC_DATASET_ID
            or dataset.get("dataset_manifest_sha256") != R224_GENERIC_MANIFEST_SHA256
            or dataset.get("completion_state") != "COMPLETE"
            or dataset.get("record_count") != 35
            or dataset.get("json_record_count") != 35
            or dataset.get("payload_count") != 35
            or dataset.get("resolution") != "R224"):
        raise AnalysisError("R224_RECONCILIATION_DATASET_INVALID")
    native = value.get("native_result", {})
    if (not isinstance(native, dict) or native.get("state") != "succeeded"
            or native.get("process_started") is not True
            or native.get("return_code") != 0
            or native.get("launcher_return_code") != 0):
        raise AnalysisError("R224_RECONCILIATION_NATIVE_INVALID")
    return value


def open_r224_dataset(c5: Any) -> tuple[dict[tuple[int, int, str, str], Any], dict[str, Any]]:
    reconciliation = verify_r224_reconciliation()
    graph = read_json(R224_GRAPH_PATH)
    if sha256(R224_GRAPH_PATH) != R224_GRAPH_SHA256:
        raise AnalysisError("R224_GRAPH_SHA256_MISMATCH")
    c5.verify_graph(graph)
    plan = c5.build_provider_plan(graph)
    if len(graph.get("logical_demands", [])) != 36 or len(plan) != 35:
        raise AnalysisError("R224_GRAPH_CARDINALITY_INVALID")
    runtime = load_module("_r8_c6_r224_runtime", RUNTIME_PATH)
    scientific_job = load_module("_r8_c6_scientific_job", SCIENCE_JOB_PATH)
    namespace = {
        "project_id": "MEPHC", "science_contract_id": "E9F_QP_B_C2_C3_R8_C5_R224",
        "source_commit": R224_SOURCE_COMMIT,
        "work_order_id": "MEPHC-E9F-C2-QP-B-C2-C3-R8-C5-A1-20260828-312",
        "resolution": "R224", "entrypoint_sha256": R224_ENTRYPOINT_SHA256,
        "graph_sha256": R224_GRAPH_SHA256, "science_runtime_sha256": R224_RUNTIME_SHA256,
    }
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    if store.root.name != R224_NAMESPACE_SHA256:
        raise AnalysisError("R224_NAMESPACE_SHA256_MISMATCH")
    generic = scientific_job.verify_dataset(runtime._trusted_science_state_root(), R224_GENERIC_DATASET_ID)
    if (generic.get("state") != "verified" or generic.get("manifest_sha256") != R224_GENERIC_MANIFEST_SHA256
            or generic.get("record_count") != 35):
        raise AnalysisError("R224_GENERIC_DATASET_INVALID")
    manifest = read_json(store.root / "acquisition-dataset-manifest.json")
    unsigned_id = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("dataset_id") != R224_ACQUISITION_DATASET_ID
            or hashlib.sha256(canonical(unsigned_id)).hexdigest() != R224_ACQUISITION_DATASET_ID
            or manifest.get("manifest_sha256") != R224_ACQUISITION_MANIFEST_SHA256
            or hashlib.sha256(canonical(unsigned_manifest)).hexdigest() != R224_ACQUISITION_MANIFEST_SHA256
            or manifest.get("completed_key_count") != 35
            or manifest.get("unique_provider_request_count") != 35
            or manifest.get("completion_state") != "COMPLETE"
            or manifest.get("acquisition_source_commit") != R224_SOURCE_COMMIT):
        raise AnalysisError("R224_ACQUISITION_MANIFEST_INVALID")
    records = {item.get("key_sha256"): item for item in manifest.get("records", [])}
    if len(records) != 35:
        raise AnalysisError("R224_RECORD_INDEX_INVALID")
    snapshots: dict[tuple[int, int, str, str], Any] = {}
    for demand in graph["logical_demands"]:
        grid = demand["sample_grid"]
        key = c5.canonical_key(demand["request_key"])
        key_sha = hashlib.sha256(key).hexdigest()
        payload, metadata = store.get(key)
        listed = records.get(key_sha)
        if listed is None or any(metadata.get(field) != listed.get(field)
                                 for field in ("key_sha256", "payload_sha256", "payload_size_bytes")):
            raise AnalysisError("R224_RECORD_METADATA_MISMATCH")
        identity = metadata.get("identity", {})
        if (identity.get("resolution") != "R224"
                or identity.get("source_model_identity") != "FROZEN_QP_B_SOURCE_MODEL"
                or identity.get("provider_configuration_identity") != "FROZEN_QP_B_PROVIDER_CONFIGURATION"
                or identity.get("band_request_configuration") != "FROZEN_QP_B_LOCKED_BAND_REQUEST"):
            raise AnalysisError("R224_RECORD_IDENTITY_MISMATCH")
        snapshot = runtime.decode_snapshot(payload)
        coordinate = demand["request_key"]["canonical_k_coordinate_units_1_over_144"]
        if (snapshot.provenance.get("representation") != "mpb_periodic_h_l2_v1"
                or tuple(snapshot.k_point) != (coordinate["i"] / 144.0, coordinate["j"] / 144.0)):
            raise AnalysisError("R224_SNAPSHOT_IDENTITY_MISMATCH")
        identity_key = (grid["i"], grid["j"], "R224", demand["point"])
        prior = snapshots.get(identity_key)
        if prior is not None and not np.array_equal(prior.frequencies, snapshot.frequencies):
            raise AnalysisError("R224_DUPLICATE_PAYLOAD_MISMATCH")
        snapshots[identity_key] = snapshot
    if len(snapshots) != 36:
        raise AnalysisError("R224_LOGICAL_BUNDLE_INCOMPLETE")
    return snapshots, {
        "status": "VERIFIED", "acquisition_dataset_id": R224_ACQUISITION_DATASET_ID,
        "acquisition_manifest_sha256": R224_ACQUISITION_MANIFEST_SHA256,
        "generic_dataset_id": R224_GENERIC_DATASET_ID, "generic_manifest_sha256": R224_GENERIC_MANIFEST_SHA256,
        "record_count": 35, "source_commit": R224_SOURCE_COMMIT,
        "reconciliation_file_sha256": sha256(R224_RECONCILIATION_PATH),
        "reconciliation_status": reconciliation["reconciliation_status"],
    }


def verify_r256_reconciliation() -> dict[str, Any]:
    if sha256(C7_RECONCILIATION_PATH) != R256_RECONCILIATION_SHA256:
        raise AnalysisError("R256_RECONCILIATION_SHA256_MISMATCH")
    value = read_json(C7_RECONCILIATION_PATH)
    expected = {
        "schema": "mephc-r8-c7-r256-closeout-reconciliation-v1",
        "work_order_id": "MEPHC-E9F-C2-QP-B-C2-C3-R8-C7-I1-20260828-316",
        "execution_source_commit": R256_SOURCE_COMMIT,
        "original_native_state": "succeeded",
        "original_native_process_started": True,
        "original_child_return_code": 0,
        "native_retry_count": 0,
        "r256_native_rerun_required": False,
        "post_execution_diff_status": "PASS_EXACTLY_ONE_ADDED_BINDING",
        "post_execution_binding_verification_status": "PASS",
        "full_r256_record_integrity_pass_count": 35,
        "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise AnalysisError("R256_RECONCILIATION_INVALID")
    if (value.get("r256_acquisition_dataset_id") != R256_ACQUISITION_DATASET_ID
            or value.get("r256_acquisition_dataset_manifest_sha256") != R256_ACQUISITION_MANIFEST_SHA256
            or value.get("generic_dataset_id") != R256_GENERIC_DATASET_ID
            or value.get("generic_dataset_manifest_sha256") != R256_GENERIC_MANIFEST_SHA256
            or value.get("r256_dataset_record_count") != 35
            or value.get("provider_request_count") != 35
            or value.get("solver_executions") != 35
            or value.get("science_runtime_sha256") != R256_RUNTIME_SHA256):
        raise AnalysisError("R256_RECONCILIATION_DATASET_INVALID")
    return value


def verify_parity_method_contract() -> dict[str, Any]:
    if sha256(C7_METHOD_CONTRACT_PATH) != PARITY_METHOD_SHA256:
        raise AnalysisError("PARITY_METHOD_CONTRACT_SHA256_MISMATCH")
    value = read_json(C7_METHOD_CONTRACT_PATH)
    if (value.get("schema") != "mephc-r8-c7-parity-aware-method-contract-v1"
            or value.get("resolution_classes") != {"odd": ["R96", "R160", "R224"], "even": ["R128", "R192", "R256"]}
            or value.get("r256_adjacent_step_primary_gate") is not False
            or value.get("status") != "PUBLISHED_PROSPECTIVE_METHOD_ONLY"):
        raise AnalysisError("PARITY_METHOD_CONTRACT_INVALID")
    gate = value.get("gate", {})
    if (gate.get("odd_pre_increment") != "abs(OMEGA_R160-OMEGA_R96)"
            or gate.get("odd_final_increment") != "abs(OMEGA_R224-OMEGA_R160)"
            or gate.get("even_subsequence") != "R128,R192,R256"
            or gate.get("primary_future_gate") != "EVEN_FINAL_INCREMENT < EVEN_PRE_INCREMENT"):
        raise AnalysisError("PARITY_METHOD_GATE_INVALID")
    return value


def open_r256_dataset(c7: Any) -> tuple[dict[tuple[int, int, str, str], Any], dict[str, Any]]:
    verify_r256_reconciliation()
    if sha256(C7_BINDING_PATH) != R256_BINDING_SHA256:
        raise AnalysisError("R256_BINDING_SHA256_MISMATCH")
    binding = read_json(C7_BINDING_PATH)
    required = {
        "work_order_id": "MEPHC-E9F-C2-QP-B-C2-C3-R8-C7-A1-20260828-315",
        "acquisition_source_commit": R256_SOURCE_COMMIT,
        "resolution": "R256",
        "acquisition_dataset_id": R256_ACQUISITION_DATASET_ID,
        "dataset_manifest_sha256": R256_ACQUISITION_MANIFEST_SHA256,
        "entrypoint_sha256": R256_ENTRYPOINT_SHA256,
        "graph_sha256": R256_GRAPH_SHA256,
        "science_runtime_sha256": R256_RUNTIME_SHA256,
        "parent_dataset_id": R224_GENERIC_DATASET_ID,
        "parent_dataset_manifest_sha256": R224_GENERIC_MANIFEST_SHA256,
        "parent_provenance_reconciliation_sha256": R224_RECONCILIATION_SHA256,
        "logical_provider_demand_count": 36,
        "unique_provider_request_count": 35,
        "duplicate_logical_demand_count": 1,
        "completed_key_count": 35,
        "fresh_provider_execution_count": 35,
        "cache_reuse_count": 0,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "completion_state": "COMPLETE",
        "mpb_execution": True,
        "third_stencil_executed": False,
        "holdout_used": False,
    }
    if any(binding.get(key) != expected for key, expected in required.items()):
        raise AnalysisError("R256_BINDING_INVALID")
    graph = read_json(C7_GRAPH_PATH)
    if sha256(C7_GRAPH_PATH) != R256_GRAPH_SHA256:
        raise AnalysisError("R256_GRAPH_SHA256_MISMATCH")
    c7.verify_graph(graph)
    plan = c7.build_provider_plan(graph)
    if len(graph.get("logical_demands", [])) != 36 or len(plan) != 35:
        raise AnalysisError("R256_GRAPH_CARDINALITY_INVALID")
    runtime = load_module("_r8_c8_r256_runtime", RUNTIME_PATH)
    scientific_job = load_module("_r8_c8_scientific_job", SCIENCE_JOB_PATH)
    namespace = {
        "project_id": "MEPHC", "science_contract_id": "E9F_QP_B_C2_C3_R8_C7_A1_R256",
        "source_commit": R256_SOURCE_COMMIT,
        "work_order_id": "MEPHC-E9F-C2-QP-B-C2-C3-R8-C7-A1-20260828-315",
        "resolution": "R256", "entrypoint_sha256": R256_ENTRYPOINT_SHA256,
        "graph_sha256": R256_GRAPH_SHA256, "science_runtime_sha256": R256_RUNTIME_SHA256,
    }
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    if store.root.name != R256_NAMESPACE_SHA256:
        raise AnalysisError("R256_NAMESPACE_SHA256_MISMATCH")
    generic = scientific_job.verify_dataset(runtime._trusted_science_state_root(), R256_GENERIC_DATASET_ID)
    if (generic.get("state") != "verified" or generic.get("manifest_sha256") != R256_GENERIC_MANIFEST_SHA256
            or generic.get("record_count") != 35):
        raise AnalysisError("R256_GENERIC_DATASET_INVALID")
    manifest = read_json(store.root / "acquisition-dataset-manifest.json")
    unsigned_id = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("dataset_id") != R256_ACQUISITION_DATASET_ID
            or hashlib.sha256(canonical(unsigned_id)).hexdigest() != R256_ACQUISITION_DATASET_ID
            or manifest.get("manifest_sha256") != R256_ACQUISITION_MANIFEST_SHA256
            or hashlib.sha256(canonical(unsigned_manifest)).hexdigest() != R256_ACQUISITION_MANIFEST_SHA256
            or manifest.get("completed_key_count") != 35
            or manifest.get("unique_provider_request_count") != 35
            or manifest.get("completion_state") != "COMPLETE"
            or manifest.get("acquisition_source_commit") != R256_SOURCE_COMMIT):
        raise AnalysisError("R256_ACQUISITION_MANIFEST_INVALID")
    records = {item.get("key_sha256"): item for item in manifest.get("records", [])}
    if len(records) != 35:
        raise AnalysisError("R256_RECORD_INDEX_INVALID")
    snapshots: dict[tuple[int, int, str, str], Any] = {}
    for demand in graph["logical_demands"]:
        grid = demand["sample_grid"]
        key = c7.canonical_key(demand["request_key"])
        key_sha = hashlib.sha256(key).hexdigest()
        payload, metadata = store.get(key)
        listed = records.get(key_sha)
        if listed is None or any(metadata.get(field) != listed.get(field)
                                 for field in ("key_sha256", "payload_sha256", "payload_size_bytes")):
            raise AnalysisError("R256_RECORD_METADATA_MISMATCH")
        identity = metadata.get("identity", {})
        if (identity.get("resolution") != "R256"
                or identity.get("source_model_identity") != "FROZEN_QP_B_SOURCE_MODEL"
                or identity.get("provider_configuration_identity") != "FROZEN_QP_B_PROVIDER_CONFIGURATION"
                or identity.get("band_request_configuration") != "FROZEN_QP_B_LOCKED_BAND_REQUEST"):
            raise AnalysisError("R256_RECORD_IDENTITY_MISMATCH")
        snapshot = runtime.decode_snapshot(payload)
        coordinate = demand["request_key"]["canonical_k_coordinate_units_1_over_144"]
        if (snapshot.provenance.get("representation") != "mpb_periodic_h_l2_v1"
                or tuple(snapshot.k_point) != (coordinate["i"] / 144.0, coordinate["j"] / 144.0)):
            raise AnalysisError("R256_SNAPSHOT_IDENTITY_MISMATCH")
        identity_key = (grid["i"], grid["j"], "R256", demand["point"])
        prior = snapshots.get(identity_key)
        if prior is not None and not np.array_equal(prior.frequencies, snapshot.frequencies):
            raise AnalysisError("R256_DUPLICATE_PAYLOAD_MISMATCH")
        snapshots[identity_key] = snapshot
    if len(snapshots) != 36:
        raise AnalysisError("R256_LOGICAL_BUNDLE_INCOMPLETE")
    return snapshots, {
        "status": "VERIFIED", "acquisition_dataset_id": R256_ACQUISITION_DATASET_ID,
        "acquisition_manifest_sha256": R256_ACQUISITION_MANIFEST_SHA256,
        "generic_dataset_id": R256_GENERIC_DATASET_ID, "generic_manifest_sha256": R256_GENERIC_MANIFEST_SHA256,
        "record_count": 35, "source_commit": R256_SOURCE_COMMIT,
        "entrypoint_sha256": R256_ENTRYPOINT_SHA256, "graph_sha256": R256_GRAPH_SHA256,
        "runtime_sha256": R256_RUNTIME_SHA256, "namespace_sha256": R256_NAMESPACE_SHA256,
        "reconciliation_file_sha256": R256_RECONCILIATION_SHA256,
        "reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED",
    }


def pair_metrics(c4: Any, c1: Any, i: int, j: int, snapshots: dict[tuple[int, int, str, str], Any], gap: float) -> dict[str, Any]:
    pairs = []
    for resolution in RESOLUTIONS:
        pair = c4.evaluate_pair(c1, i, j, resolution, snapshots, gap)
        pair["r192_provenance_valid"] = True
        pair["r224_provenance_valid"] = True
        pair["r256_provenance_valid"] = True
        pairs.append(pair)
    by_resolution = {item["resolution"]: item for item in pairs}
    if set(by_resolution) != set(RESOLUTIONS):
        raise AnalysisError("RESOLUTION_SEQUENCE_INCOMPLETE")
    stencils: dict[str, Any] = {}
    for stencil in STENCILS:
        omega = {resolution: float(by_resolution[resolution]["curvature"][stencil]) for resolution in RESOLUTIONS}
        signed = {resolution: omega[resolution] - omega[previous]
                  for previous, resolution in zip(RESOLUTIONS, RESOLUTIONS[1:])}
        absolute = {resolution: abs(value) for resolution, value in signed.items()}
        odd_pre = abs(omega["R160"] - omega["R96"])
        odd_final = abs(omega["R224"] - omega["R160"])
        even_pre = abs(omega["R192"] - omega["R128"])
        even_final = abs(omega["R256"] - omega["R192"])
        odd_pass = odd_final < odd_pre or (odd_final == 0.0 and odd_pre == 0.0)
        even_pass = even_final < even_pre or (even_final == 0.0 and even_pre == 0.0)
        stencils[stencil] = {
            "omega": omega,
            "signed_increment_96_128": signed["R128"],
            "signed_increment_128_160": signed["R160"],
            "signed_increment_160_192": signed["R192"],
            "signed_increment_192_224": signed["R224"],
            "signed_increment_224_256": signed["R256"],
            "abs_increment_96_128": absolute["R128"],
            "abs_increment_128_160": absolute["R160"],
            "abs_increment_160_192": absolute["R192"],
            "abs_increment_192_224": absolute["R224"],
            "abs_increment_224_256": absolute["R256"],
            "odd_pre_increment": odd_pre,
            "odd_final_increment": odd_final,
            "even_pre_increment": even_pre,
            "even_final_increment": even_final,
            "odd_final_increment_classification": relation(odd_pre, odd_final),
            "even_final_increment_classification": relation(even_pre, even_final),
            "odd_subsequence_contraction_pass": odd_pass,
            "even_subsequence_contraction_pass": even_pass,
            "odd_final_srd": srd(omega["R160"], omega["R224"]),
            "even_final_srd": srd(omega["R192"], omega["R256"]),
            "r256_minus_r224_diagnostic_srd": srd(omega["R224"], omega["R256"]),
            "r256_minus_r224_diagnostic_signed": signed["R256"],
        }
    complete = all(item["status"] == "COMPLETE_VALID" for item in pairs)
    odd_pass = all(item["odd_subsequence_contraction_pass"] for item in stencils.values())
    even_pass = all(item["even_subsequence_contraction_pass"] for item in stencils.values())
    fixed_h_pass = complete and odd_pass and even_pass
    return {
        "pairs": pairs, "stencils": stencils,
        "odd_subsequence_contraction_pass": odd_pass,
        "even_subsequence_contraction_pass": even_pass,
        "parity_aware_fixed_h_resolution_metric": max(
            max(item["odd_final_srd"], item["even_final_srd"]) for item in stencils.values()
        ),
        "parity_aware_fixed_h_contraction_pass": fixed_h_pass,
        "all_evidence_complete": complete,
        "r192_provenance_valid": True, "r224_provenance_valid": True, "r256_provenance_valid": True,
        "r256_adjacent_step_primary_gate": False,
    }


def prospective_graph(samples: list[dict[str, Any]], decision: str) -> dict[str, Any]:
    if decision != "PROCEED_TO_TERMINAL_RESOLUTION_H_1_288_THIRD_STENCIL_DESIGN":
        return {
            "status": "NOT_APPLICABLE", "axis": None, "selected_sample_ids": [],
            "logical_demand_count": 0, "unique_provider_request_count": 0,
            "duplicate_count": 0, "collisions": [], "counts_by_resolution": {},
            "logical_demands": [],
        }
    logical: list[dict[str, Any]] = []
    for sample in samples:
        i, j = sample["grid_i"], sample["grid_j"]
        resolution = sample["terminal_fixed_h_resolution"]
        for point, (di, dj) in zip(
            ("H288_PLUS_X", "H288_MINUS_X", "H288_PLUS_Y", "H288_MINUS_Y"),
            ((1, 0), (-1, 0), (0, 1), (0, -1)),
        ):
            logical.append({
                "sample_id": sample["sample_id"], "role": sample["role"],
                "resolution": resolution, "point": point,
                "coordinate": {"i_numerator": 8 * i + di, "j_numerator": 8 * j + dj, "denominator": 288},
            })
    keys: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in logical:
        coordinate = item["coordinate"]
        key = (
            item["resolution"], coordinate["i_numerator"], coordinate["j_numerator"],
            coordinate["denominator"], "FROZEN_QP_B_SOURCE_MODEL",
            "FROZEN_QP_B_PROVIDER_CONFIGURATION", "FROZEN_QP_B_LOCKED_BAND_REQUEST",
        )
        keys.setdefault(key, []).append(item)
    collisions = [refs for refs in keys.values() if len(refs) > 1]
    return {
        "status": "DESIGNED_NOT_EXECUTED", "axis": "H_1_288",
        "selected_sample_ids": sorted({item["sample_id"] for item in logical}),
        "logical_demand_count": len(logical), "unique_provider_request_count": len(keys),
        "duplicate_count": len(logical) - len(keys), "collisions": collisions,
        "counts_by_resolution": {
            resolution: sum(1 for item in logical if item["resolution"] == resolution)
            for resolution in ("R192", "R256")
        },
        "logical_demands": logical,
    }


def analyze() -> dict[str, Any]:
    c4 = load_module("_r8_c8_c4", C4_PATH)
    c5 = load_module("_r8_c8_c5", C5_PATH)
    c7 = load_module("_r8_c8_c7", C7_PATH)
    c1 = load_module("_r8_c8_c1", c4.PARENT_C1_PATH)
    parent_binding, parent_graph, _, _, parent_snapshots = c4.verify_parent_inputs(c1)
    r192_binding, r192_graph, r192_reconciliation, r192_acquisition = c4.verify_r192_binding()
    r192_snapshots = c4.open_r192_dataset(r192_binding, r192_graph, r192_acquisition)
    r224_snapshots, r224_binding = open_r224_dataset(c5)
    verify_parity_method_contract()
    r256_snapshots, r256_binding = open_r256_dataset(c7)
    snapshots = {**parent_snapshots, **r192_snapshots, **r224_snapshots, **r256_snapshots}
    prior = read_json(C4_EVIDENCE_PATH)
    if sha256(C4_EVIDENCE_PATH) != C4_EVIDENCE_SHA256 or prior.get("all_eight_fixed_h_contraction_pass_count") != 4:
        raise AnalysisError("C4_EVIDENCE_INVALID")
    if sha256(C4_NEXT_AXIS_PATH) != C4_NEXT_AXIS_SHA256:
        raise AnalysisError("C4_NEXT_AXIS_SHA256_MISMATCH")
    c6_prior = read_json(C6_EVIDENCE_PATH)
    if sha256(C6_EVIDENCE_PATH) != C6_EVIDENCE_SHA256:
        raise AnalysisError("C6_EVIDENCE_SHA256_MISMATCH")
    expected_stable_metrics = {
        sample_id(-34, 9): 0.006449531456011454,
        sample_id(-34, -16): 0.003374622966536901,
        sample_id(-34, -17): 0.014748781425972798,
        sample_id(-34, 17): 0.012461380472423192,
    }
    for identity, expected_metric in expected_stable_metrics.items():
        frozen = c6_prior.get("samples", {}).get(identity)
        if (not isinstance(frozen, dict) or frozen.get("terminal_fixed_h_contraction_pass") is not True
                or frozen.get("terminal_fixed_h_resolution") != "R192"
                or frozen.get("terminal_fixed_h_resolution_metric") != expected_metric):
            raise AnalysisError("C4_STABLE_SAMPLE_NOT_FROZEN")
    c7_reconciliation = verify_r256_reconciliation()
    method_contract = verify_parity_method_contract()
    anchor = read_json(c1.ANCHOR_PATH)
    policy_gaps = {item["sample_id"]: float(item["external_gap"]) for item in anchor["frozen_sample_ids"]}
    target_results: dict[str, Any] = {}
    for i, j, role in TARGETED_SAMPLES:
        identity = sample_id(i, j)
        target_results[identity] = {
            "sample_id": identity, "role": role, "grid_i": i, "grid_j": j,
            "targeted_r224": True, "targeted_r256": True,
            **pair_metrics(c4, c1, i, j, snapshots, policy_gaps[identity]),
        }
        passed = target_results[identity]["parity_aware_fixed_h_contraction_pass"]
        target_results[identity]["terminal_fixed_h_pass"] = passed
        target_results[identity]["terminal_fixed_h_method"] = (
            "PARITY_AWARE_R96_R160_R224_AND_R128_R192_R256" if passed
            else "PARITY_AWARE_BOUNDED_REFINEMENT_FAILED"
        )
        target_results[identity]["terminal_fixed_h_resolution"] = "R256" if passed else "R256_CEILING"
        target_results[identity]["terminal_fixed_h_resolution_metric"] = (
            target_results[identity]["parity_aware_fixed_h_resolution_metric"] if passed else None
        )
    samples: dict[str, Any] = {}
    for i, j, role in ALL_SAMPLES:
        identity = sample_id(i, j)
        if identity in target_results:
            samples[identity] = target_results[identity]
            continue
        frozen = c6_prior["samples"][identity]
        samples[identity] = {
            "sample_id": identity, "role": role, "grid_i": i, "grid_j": j,
            "preserved_from_c4": True, "targeted_r224": False, "targeted_r256": False,
            "terminal_fixed_h_method": "PRESERVED_C4_STABLE_SAMPLE",
            "terminal_fixed_h_resolution": "R192",
            "terminal_fixed_h_resolution_metric": frozen["terminal_fixed_h_resolution_metric"],
            "terminal_fixed_h_pass": True, "terminal_fixed_h_contraction_pass": True,
        }
    controls = [sample_id(-10, -3), sample_id(-34, 9)]
    control_valid = all(samples[item]["terminal_fixed_h_pass"] for item in controls)
    envelope = max(samples[item]["terminal_fixed_h_resolution_metric"] for item in controls) if control_valid else None
    max_resolution = max((samples[item]["terminal_fixed_h_resolution"] for item in controls),
                         key=lambda value: RESOLUTION_ORDER[value]) if control_valid else None
    challenges: dict[str, str] = {}
    for identity, sample in samples.items():
        if sample["role"] != "POLICY_CHALLENGE":
            continue
        if not control_valid:
            challenges[identity] = "INCOMPLETE_NO_CONTROL_ENVELOPE"
        elif not sample["terminal_fixed_h_pass"]:
            challenges[identity] = "CONTROL_REFERENCED_TERMINAL_FIXED_H_INFERIOR_WITHIN_BOUNDED_REFINEMENT"
        elif RESOLUTION_ORDER[sample["terminal_fixed_h_resolution"]] > RESOLUTION_ORDER[max_resolution]:
            challenges[identity] = "CONTROL_REFERENCED_TERMINAL_FIXED_H_INFERIOR_WITHIN_BOUNDED_REFINEMENT"
        elif sample["terminal_fixed_h_resolution_metric"] <= envelope:
            challenges[identity] = "CONTROL_REFERENCED_TERMINAL_FIXED_H_NONINFERIOR"
        else:
            challenges[identity] = "CONTROL_REFERENCED_TERMINAL_FIXED_H_INFERIOR_METRIC"
    diagnostic = samples[sample_id(-6, -1)]
    noninferior = "CONTROL_REFERENCED_TERMINAL_FIXED_H_NONINFERIOR"
    inferior_prefix = "CONTROL_REFERENCED_TERMINAL_FIXED_H_INFERIOR"
    diagnostic_pass = diagnostic["terminal_fixed_h_pass"] is True
    if (control_valid and diagnostic_pass and len(challenges) == 5
            and all(value == noninferior for value in challenges.values())):
        policy_evidence = "BELOW_POLICY_SAMPLES_CONTROL_REFERENCED_NONINFERIOR"
    elif (control_valid and diagnostic_pass
          and any(value.startswith(inferior_prefix) for value in challenges.values())):
        policy_evidence = "BELOW_POLICY_SAMPLE_FIXED_H_INFERIORITY_OBSERVED"
    else:
        policy_evidence = "INCONCLUSIVE"
    all_pass = all(sample["terminal_fixed_h_pass"] for sample in samples.values())
    targeted_incomplete = any(not item["all_evidence_complete"] for item in target_results.values())
    targeted_failure = any(
        item["all_evidence_complete"] and not item["parity_aware_fixed_h_contraction_pass"]
        for item in target_results.values()
    )
    next_decision = (
        "PROCEED_TO_TERMINAL_RESOLUTION_H_1_288_THIRD_STENCIL_DESIGN" if all_pass
        else "STOP_FIXED_H_REFINEMENT_METHOD_LIMIT_REACHED" if targeted_failure
        else "INCONCLUSIVE_DATA_OR_PROVENANCE"
    )
    graph = prospective_graph(list(samples.values()), next_decision)
    unresolved = [identity for identity, item in samples.items() if not item["terminal_fixed_h_pass"]]
    unresolved_stencils = [
        f"{identity}|{stencil}"
        for identity, item in target_results.items()
        if not item["parity_aware_fixed_h_contraction_pass"]
        for stencil, values in item["stencils"].items()
        if not (values["odd_subsequence_contraction_pass"] and values["even_subsequence_contraction_pass"])
    ]
    result = {
        "schema": "mephc-r8-c8-parity-aware-terminal-analysis-v1",
        "work_order_id": WORK_ORDER_ID, "base_sandbox_sha": BASE_SANDBOX_SHA,
        "final_sandbox_sha": current_source_commit(), "origin_sandbox_sha": current_source_commit(),
        "main_sha": MAIN_SHA, "machine_contract_status": "PASS",
        "parent_dataset_binding": {"status": "VERIFIED", "dataset_id": parent_binding["acquisition_dataset_id"], "manifest_sha256": parent_binding["dataset_manifest_sha256"], "record_count": 210, "source_commit": c4.PARENT_SOURCE_COMMIT},
        "r192_dataset_binding": {"status": "VERIFIED", "dataset_id": c4.R192_DATASET_ID, "manifest_sha256": c4.R192_MANIFEST_SHA256, "record_count": 70, "declared_source_commit": c4.R192_DECLARED_SOURCE_COMMIT, "verified_execution_source_commit": c4.R192_VERIFIED_SOURCE_COMMIT, "reconciliation_sha256": c4.R192_RECONCILIATION_SHA256},
        "r192_dataset_binding_status": "VERIFIED", "r192_provenance_status": r192_reconciliation["reconciliation_status"],
        "r224_dataset_binding": r224_binding, "r224_dataset_binding_status": "VERIFIED",
        "r224_state_reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED",
        "r256_dataset_binding": r256_binding, "r256_dataset_binding_status": "VERIFIED",
        "r256_closeout_reconciliation_status": c7_reconciliation["schema"].replace("mephc-r8-c7-r256-closeout-reconciliation-v1", "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED"),
        "parity_aware_method_contract_status": "PASS", "target_sample_count": 4,
        "samples": samples, "controls": {"ids": controls, "valid": control_valid, "terminal_fixed_h_metric_envelope": envelope, "max_terminal_resolution": max_resolution},
        "policy_challenges": challenges,
        "stencil_diagnostic": {"sample_id": diagnostic["sample_id"], "terminal_status": diagnostic["terminal_fixed_h_pass"], "terminal_resolution": diagnostic["terminal_fixed_h_resolution"], "metric": diagnostic["terminal_fixed_h_resolution_metric"]},
        "odd_subsequence_stencil_pass_count": sum(sum(1 for value in item["stencils"].values() if value["odd_subsequence_contraction_pass"]) for item in target_results.values()),
        "even_subsequence_stencil_pass_count": sum(sum(1 for value in item["stencils"].values() if value["even_subsequence_contraction_pass"]) for item in target_results.values()),
        "parity_aware_target_sample_pass_count": sum(1 for item in target_results.values() if item["parity_aware_fixed_h_contraction_pass"]),
        "total_terminal_fixed_h_pass_count": sum(1 for item in samples.values() if item["terminal_fixed_h_pass"]),
        "locked_set_0p02_parity_aware_fixed_h_policy_evidence": policy_evidence,
        "q2_finite_stencil_convergence_status": "NOT_ESTABLISHED_WITH_TWO_STENCILS",
        "next_axis_decision": next_decision, "unresolved_sample_ids": unresolved,
        "unresolved_sample_stencils": unresolved_stencils, "prospective_axis": graph["axis"],
        "prospective_graph": graph,
        "c4_result_sha256": C4_RESULT_SHA256, "c4_evidence_sha256": C4_EVIDENCE_SHA256,
        "c4_next_axis_sha256": C4_NEXT_AXIS_SHA256, "c6_evidence_sha256": C6_EVIDENCE_SHA256,
        "r224_reconciliation_file_sha256": R224_RECONCILIATION_SHA256,
        "r256_closeout_reconciliation_file_sha256": R256_RECONCILIATION_SHA256,
        "parity_aware_method_contract_file_sha256": PARITY_METHOD_SHA256,
        "current_0p02_policy_calibration": "INCONCLUSIVE", "c1_rescoring": False,
        "threshold_change_authorized": False, "holdout_used": False, "band2_chern_execution": False,
        "execution": {"native_invocation_count": 0, "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False},
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C8_M1_PARITY_AWARE_TERMINAL_ANALYSIS_COMPLETE",
    }
    return result


def evidence_artifact(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in (
        "schema", "work_order_id", "base_sandbox_sha", "final_sandbox_sha", "origin_sandbox_sha", "main_sha",
        "machine_contract_status", "parent_dataset_binding", "r192_dataset_binding", "r192_provenance_status",
        "r224_dataset_binding", "r224_state_reconciliation_status", "r256_dataset_binding",
        "r256_closeout_reconciliation_status", "parity_aware_method_contract_status", "target_sample_count",
        "samples", "controls", "policy_challenges", "stencil_diagnostic",
        "odd_subsequence_stencil_pass_count", "even_subsequence_stencil_pass_count",
        "parity_aware_target_sample_pass_count", "total_terminal_fixed_h_pass_count",
        "locked_set_0p02_parity_aware_fixed_h_policy_evidence", "q2_finite_stencil_convergence_status",
        "next_axis_decision", "unresolved_sample_ids", "unresolved_sample_stencils", "prospective_axis",
        "prospective_graph", "current_0p02_policy_calibration", "c1_rescoring", "threshold_change_authorized",
        "holdout_used", "band2_chern_execution", "execution", "pipeline_health", "blocked_by_infrastructure",
        "scientific_work_must_stop", "terminal")}


def next_axis_artifact(result: dict[str, Any]) -> dict[str, Any]:
    graph = result["prospective_graph"]
    return {
        "schema": "mephc-r8-c8-next-axis-contract-v1", "work_order_id": result["work_order_id"],
        "status": graph["status"], "next_axis_decision": result["next_axis_decision"],
        "unresolved_sample_ids": result["unresolved_sample_ids"],
        "unresolved_sample_stencils": result["unresolved_sample_stencils"],
        "axis": graph["axis"], "selected_sample_ids": graph["selected_sample_ids"],
        "logical_demand_count": graph["logical_demand_count"],
        "unique_provider_request_count": graph["unique_provider_request_count"],
        "duplicate_count": graph["duplicate_count"], "collisions": graph["collisions"],
        "counts_by_resolution": graph["counts_by_resolution"], "designed_not_executed": True,
        "h_1_288_execution": False, "r288_execution": False, "r256_execution": False,
        "r224_execution": False, "q2_finite_stencil_convergence_status": result["q2_finite_stencil_convergence_status"],
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"],
        "c1_rescoring": False, "threshold_change_authorized": False, "terminal": result["terminal"],
    }


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    challenges = list(result["policy_challenges"].values())
    graph = result["prospective_graph"]
    return {
        "schema": result["schema"], "work_order_id": result["work_order_id"],
        "base_sandbox_sha": result["base_sandbox_sha"], "final_sandbox_sha": result["final_sandbox_sha"],
        "origin_sandbox_sha": result["origin_sandbox_sha"], "main_sha": result["main_sha"],
        "machine_contract_status": result["machine_contract_status"],
        "parent_dataset_binding_status": result["parent_dataset_binding"]["status"],
        "r192_dataset_binding_status": result["r192_dataset_binding_status"],
        "r224_dataset_binding_status": result["r224_dataset_binding_status"],
        "r256_dataset_binding_status": result["r256_dataset_binding_status"],
        "r256_closeout_reconciliation_status": result["r256_closeout_reconciliation_status"],
        "parity_aware_method_contract_status": result["parity_aware_method_contract_status"],
        "target_sample_count": result["target_sample_count"],
        "odd_subsequence_stencil_pass_count": result["odd_subsequence_stencil_pass_count"],
        "even_subsequence_stencil_pass_count": result["even_subsequence_stencil_pass_count"],
        "parity_aware_target_sample_pass_count": result["parity_aware_target_sample_pass_count"],
        "total_terminal_fixed_h_pass_count": result["total_terminal_fixed_h_pass_count"],
        "control_1_terminal_status": result["samples"][sample_id(-10, -3)]["terminal_fixed_h_pass"],
        "control_1_terminal_metric": result["samples"][sample_id(-10, -3)]["terminal_fixed_h_resolution_metric"],
        "control_2_terminal_status": result["samples"][sample_id(-34, 9)]["terminal_fixed_h_pass"],
        "control_2_terminal_metric": result["samples"][sample_id(-34, 9)]["terminal_fixed_h_resolution_metric"],
        "control_terminal_fixed_h_metric_envelope": result["controls"]["terminal_fixed_h_metric_envelope"],
        "control_max_terminal_resolution": result["controls"]["max_terminal_resolution"],
        "stencil_diagnostic_terminal_pass": result["stencil_diagnostic"]["terminal_status"],
        "policy_challenge_noninferior_count": challenges.count("CONTROL_REFERENCED_TERMINAL_FIXED_H_NONINFERIOR"),
        "policy_challenge_inferior_count": sum(value.startswith("CONTROL_REFERENCED_TERMINAL_FIXED_H_INFERIOR") for value in challenges),
        "policy_challenge_incomplete_count": sum(value.startswith("INCOMPLETE") for value in challenges),
        "locked_set_0p02_parity_aware_fixed_h_policy_evidence": result["locked_set_0p02_parity_aware_fixed_h_policy_evidence"],
        "q2_finite_stencil_convergence_status": result["q2_finite_stencil_convergence_status"],
        "next_axis_decision": result["next_axis_decision"],
        "unresolved_sample_count": len(result["unresolved_sample_ids"]),
        "unresolved_sample_ids": result["unresolved_sample_ids"],
        "unresolved_sample_stencils": result["unresolved_sample_stencils"],
        "prospective_axis": graph["axis"], "prospective_logical_demand_count": graph["logical_demand_count"],
        "prospective_unique_provider_request_count": graph["unique_provider_request_count"],
        "prospective_duplicate_count": graph["duplicate_count"],
        "prospective_r192_request_count": graph["counts_by_resolution"].get("R192", 0),
        "prospective_r256_request_count": graph["counts_by_resolution"].get("R256", 0),
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"],
        "c1_rescoring": False, "threshold_change_authorized": False,
        "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0,
        "mpb_execution": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False, "terminal": result["terminal"],
        "result_sha256": hashlib.sha256(canonical(result)).hexdigest(),
    }


def main() -> int:
    try:
        result = analyze()
        scientific_job = load_module("_r8_c8_output_job", SCIENCE_JOB_PATH)
        scientific_job.atomic_json(EVIDENCE_PATH, evidence_artifact(result))
        scientific_job.atomic_json(NEXT_AXIS_PATH, next_axis_artifact(result))
        output = canonical(result_summary(result))
        if len(output) > 65536:
            raise AnalysisError("SUCCESS_STDOUT_LIMIT_EXCEEDED")
        print("MEPHC_NATIVE_RESULT_JSON=" + output.decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-r8-c8-parity-aware-terminal-analysis-v1", "state": "failed",
            "error_code": type(exc).__name__, "detail": str(exc)[:1000],
            "native_invocation_count": 0, "provider_request_count": 0,
            "solver_executions": 0, "native_solves": 0, "mpb_execution": False,
            "terminal": "E9F_C2_QP_B_C2_C3_R8_C8_M1_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
