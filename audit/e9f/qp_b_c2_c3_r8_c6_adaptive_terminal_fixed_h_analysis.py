"""Solver-free C6 adaptive terminal fixed-h analysis.

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
SCIENCE_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"
EVIDENCE_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c6_adaptive_terminal_fixed_h_evidence.json"
NEXT_AXIS_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c6_next_axis_contract.json"

WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C6-M1-20260828-314"
BASE_SANDBOX_SHA = "dcf19829a812b20ebde2e448dc92720739974a09"
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

RESOLUTIONS = ("R96", "R128", "R160", "R192", "R224")
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
        return "R224_FINAL_INCREMENT_CONTRACTS"
    if second > first:
        return "R224_FINAL_INCREMENT_EXPANDS"
    return "R224_FINAL_INCREMENT_EQUAL_NONZERO"


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


def pair_metrics(c4: Any, c1: Any, i: int, j: int, snapshots: dict[tuple[int, int, str, str], Any], gap: float) -> dict[str, Any]:
    pairs = []
    for resolution in RESOLUTIONS:
        pair = c4.evaluate_pair(c1, i, j, resolution, snapshots, gap)
        pair["r192_provenance_valid"] = True
        pair["r224_provenance_valid"] = True
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
        final_classification = relation(absolute["R192"], absolute["R224"])
        stencils[stencil] = {
            "omega": omega,
            "signed_increment_160_192": signed["R192"],
            "signed_increment_192_224": signed["R224"],
            "abs_increment_160_192": absolute["R192"],
            "abs_increment_192_224": absolute["R224"],
            "step_srd_160_192": srd(omega["R160"], omega["R192"]),
            "step_srd_192_224": srd(omega["R192"], omega["R224"]),
            "final_increment_classification": final_classification,
        }
    complete = all(item["status"] == "COMPLETE_VALID" for item in pairs)
    fixed_h_pass = complete and all(
        item["final_increment_classification"] in {"R224_FINAL_INCREMENT_CONTRACTS", "ALL_ZERO_STABLE"}
        for item in stencils.values()
    )
    return {
        "pairs": pairs, "stencils": stencils,
        "r224_final_fixed_h_resolution_metric": max(item["step_srd_192_224"] for item in stencils.values()),
        "r224_final_fixed_h_contraction_pass": fixed_h_pass,
        "all_evidence_complete": complete,
        "r192_provenance_valid": True, "r224_provenance_valid": True,
    }


def prospective_graph(samples: list[dict[str, Any]], decision: str) -> dict[str, Any]:
    logical: list[dict[str, Any]] = []
    if decision == "PROCEED_TO_ADAPTIVE_TERMINAL_H_1_288_THIRD_STENCIL_DESIGN":
        for sample in samples:
            i, j = sample["grid_i"], sample["grid_j"]
            for point, (di, dj) in zip(("H288_PLUS_X", "H288_MINUS_X", "H288_PLUS_Y", "H288_MINUS_Y"), ((1, 0), (-1, 0), (0, 1), (0, -1))):
                logical.append({"sample_id": sample["sample_id"], "role": sample["role"],
                                "resolution": sample["terminal_fixed_h_resolution"], "point": point,
                                "coordinate": {"i_numerator": 8 * i + di, "j_numerator": 8 * j + dj, "denominator": 288}})
        axis = "H_1_288"
    elif decision == "TARGETED_R256_REQUIRED_BEFORE_THIRD_STENCIL":
        for sample in samples:
            if sample["sample_id"] not in TARGETED_IDS or sample["terminal_fixed_h_contraction_pass"]:
                continue
            i, j = sample["grid_i"], sample["grid_j"]
            points = ("CENTER", "H72_PLUS_X", "H72_MINUS_X", "H72_PLUS_Y", "H72_MINUS_Y",
                      "H144_PLUS_X", "H144_MINUS_X", "H144_PLUS_Y", "H144_MINUS_Y")
            offsets = ((0, 0), (2, 0), (-2, 0), (0, 2), (0, -2), (1, 0), (-1, 0), (0, 1), (0, -1))
            for point, (di, dj) in zip(points, offsets):
                logical.append({"sample_id": sample["sample_id"], "role": sample["role"],
                                "resolution": "R256", "point": point,
                                "coordinate": {"i_numerator": 4 * i + di, "j_numerator": 4 * j + dj, "denominator": 144}})
        axis = "R256"
    else:
        return {"status": "NOT_APPLICABLE", "axis": None, "selected_sample_ids": [],
                "logical_demand_count": 0, "unique_provider_request_count": 0,
                "duplicate_count": 0, "collisions": [], "logical_demands": []}
    keys: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in logical:
        coordinate = item["coordinate"]
        key = (item["resolution"], coordinate["i_numerator"], coordinate["j_numerator"], coordinate["denominator"],
               "FROZEN_QP_B_SOURCE_MODEL", "FROZEN_QP_B_PROVIDER_CONFIGURATION", "FROZEN_QP_B_LOCKED_BAND_REQUEST")
        keys.setdefault(key, []).append(item)
    collisions = [refs for refs in keys.values() if len(refs) > 1]
    return {
        "status": "DESIGNED_NOT_EXECUTED", "axis": axis,
        "selected_sample_ids": sorted({item["sample_id"] for item in logical}),
        "logical_demand_count": len(logical), "unique_provider_request_count": len(keys),
        "duplicate_count": len(logical) - len(keys), "collisions": collisions,
        "logical_demands": logical,
    }


def analyze() -> dict[str, Any]:
    c4 = load_module("_r8_c6_c4", C4_PATH)
    c5 = load_module("_r8_c6_c5", C5_PATH)
    c1 = load_module("_r8_c6_c1", c4.PARENT_C1_PATH)
    parent_binding, parent_graph, _, _, parent_snapshots = c4.verify_parent_inputs(c1)
    r192_binding, r192_graph, r192_reconciliation, r192_acquisition = c4.verify_r192_binding()
    r192_snapshots = c4.open_r192_dataset(r192_binding, r192_graph, r192_acquisition)
    r224_snapshots, r224_binding = open_r224_dataset(c5)
    snapshots = {**parent_snapshots, **r192_snapshots, **r224_snapshots}
    prior = read_json(C4_EVIDENCE_PATH)
    if sha256(C4_EVIDENCE_PATH) != C4_EVIDENCE_SHA256 or prior.get("all_eight_fixed_h_contraction_pass_count") != 4:
        raise AnalysisError("C4_EVIDENCE_INVALID")
    if sha256(C4_NEXT_AXIS_PATH) != C4_NEXT_AXIS_SHA256:
        raise AnalysisError("C4_NEXT_AXIS_SHA256_MISMATCH")
    anchor = read_json(c1.ANCHOR_PATH)
    policy_gaps = {item["sample_id"]: float(item["external_gap"]) for item in anchor["frozen_sample_ids"]}
    target_results: dict[str, Any] = {}
    for i, j, role in TARGETED_SAMPLES:
        identity = sample_id(i, j)
        target_results[identity] = {
            "sample_id": identity, "role": role, "grid_i": i, "grid_j": j,
            "targeted_r224": True, **pair_metrics(c4, c1, i, j, snapshots, policy_gaps[identity]),
        }
    samples: dict[str, Any] = {}
    for i, j, role in ALL_SAMPLES:
        identity = sample_id(i, j)
        if identity in target_results:
            sample = target_results[identity]
            sample["terminal_fixed_h_resolution"] = "R224" if sample["r224_final_fixed_h_contraction_pass"] else None
            sample["terminal_fixed_h_resolution_metric"] = sample["r224_final_fixed_h_resolution_metric"] if sample["r224_final_fixed_h_contraction_pass"] else None
            sample["terminal_fixed_h_contraction_pass"] = sample["r224_final_fixed_h_contraction_pass"]
            samples[identity] = sample
            continue
        frozen = prior["samples"].get(identity)
        if not isinstance(frozen, dict) or frozen.get("final_fixed_h_contraction_pass") is not True:
            raise AnalysisError("C4_STABLE_SAMPLE_NOT_FROZEN")
        samples[identity] = {
            "sample_id": identity, "role": role, "grid_i": i, "grid_j": j,
            "preserved_from_c4": True, "targeted_r224": False,
            "terminal_fixed_h_resolution": "R192",
            "terminal_fixed_h_resolution_metric": frozen["final_fixed_h_resolution_metric"],
            "terminal_fixed_h_contraction_pass": True,
        }
    controls = [sample_id(-10, -3), sample_id(-34, 9)]
    control_valid = all(samples[item]["terminal_fixed_h_contraction_pass"] for item in controls)
    envelope = max(samples[item]["terminal_fixed_h_resolution_metric"] for item in controls) if control_valid else None
    max_resolution = max((samples[item]["terminal_fixed_h_resolution"] for item in controls),
                         key=lambda value: RESOLUTION_ORDER[value]) if control_valid else None
    challenges: dict[str, str] = {}
    for identity, sample in samples.items():
        if sample["role"] != "POLICY_CHALLENGE":
            continue
        if not control_valid or not sample["terminal_fixed_h_contraction_pass"]:
            challenges[identity] = "INCOMPLETE_NO_CONTROL_ENVELOPE" if not control_valid else "INCOMPLETE_FIXED_H_EVIDENCE"
        elif sample["terminal_fixed_h_resolution"] and RESOLUTION_ORDER[sample["terminal_fixed_h_resolution"]] > RESOLUTION_ORDER[max_resolution]:
            challenges[identity] = "CONTROL_REFERENCED_ADAPTIVE_FIXED_H_INFERIOR_WITHIN_BOUNDED_REFINEMENT"
        elif sample["terminal_fixed_h_resolution_metric"] <= envelope:
            challenges[identity] = "CONTROL_REFERENCED_ADAPTIVE_FIXED_H_NONINFERIOR"
        else:
            challenges[identity] = "CONTROL_REFERENCED_ADAPTIVE_FIXED_H_INFERIOR_METRIC"
    diagnostic = samples[sample_id(-6, -1)]
    if control_valid and all(value == "CONTROL_REFERENCED_ADAPTIVE_FIXED_H_NONINFERIOR" for value in challenges.values()):
        policy_evidence = "BELOW_POLICY_SAMPLES_CONTROL_REFERENCED_NONINFERIOR"
    elif control_valid and any(value.startswith("CONTROL_REFERENCED_ADAPTIVE_FIXED_H_INFERIOR") for value in challenges.values()):
        policy_evidence = "BELOW_POLICY_SAMPLE_FIXED_H_INFERIORITY_OBSERVED"
    else:
        policy_evidence = "INCONCLUSIVE"
    all_pass = all(sample["terminal_fixed_h_contraction_pass"] for sample in samples.values())
    complete_failure = any(not sample["terminal_fixed_h_contraction_pass"] for sample in target_results.values())
    next_decision = (
        "PROCEED_TO_ADAPTIVE_TERMINAL_H_1_288_THIRD_STENCIL_DESIGN" if all_pass
        else "TARGETED_R256_REQUIRED_BEFORE_THIRD_STENCIL" if complete_failure
        else "INCONCLUSIVE_DATA_OR_PROVENANCE"
    )
    graph = prospective_graph(list(samples.values()), next_decision)
    result = {
        "schema": "mephc-r8-c6-adaptive-terminal-fixed-h-analysis-v1", "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": current_source_commit(),
        "origin_sandbox_sha": current_source_commit(), "main_sha": MAIN_SHA, "machine_contract_status": "PASS",
        "parent_dataset_binding": {"status": "VERIFIED", "dataset_id": parent_binding["acquisition_dataset_id"], "manifest_sha256": parent_binding["dataset_manifest_sha256"], "record_count": 210, "source_commit": c4.PARENT_SOURCE_COMMIT},
        "r192_dataset_binding": {"status": "VERIFIED", "dataset_id": c4.R192_DATASET_ID, "manifest_sha256": c4.R192_MANIFEST_SHA256, "record_count": 70, "declared_source_commit": c4.R192_DECLARED_SOURCE_COMMIT, "verified_execution_source_commit": c4.R192_VERIFIED_SOURCE_COMMIT, "reconciliation_sha256": c4.R192_RECONCILIATION_SHA256},
        "r192_provenance_status": r192_reconciliation["reconciliation_status"], "r224_dataset_binding": r224_binding,
        "r224_state_reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED", "targeted_r224_sample_count": 4,
        "samples": samples, "controls": {"ids": controls, "valid": control_valid, "terminal_fixed_h_metric_envelope": envelope, "max_terminal_resolution": max_resolution},
        "policy_challenges": challenges, "stencil_diagnostic": {"sample_id": diagnostic["sample_id"], "terminal_status": diagnostic["terminal_fixed_h_contraction_pass"], "terminal_resolution": diagnostic["terminal_fixed_h_resolution"], "metric": diagnostic["terminal_fixed_h_resolution_metric"]},
        "r224_final_contraction_pass_count": sum(1 for item in target_results.values() if item["r224_final_fixed_h_contraction_pass"]),
        "total_terminal_fixed_h_pass_count": sum(1 for item in samples.values() if item["terminal_fixed_h_contraction_pass"]),
        "locked_set_0p02_adaptive_fixed_h_policy_evidence": policy_evidence, "q2_finite_stencil_convergence_status": "NOT_ESTABLISHED_WITH_TWO_STENCILS",
        "next_axis_decision": next_decision, "unresolved_sample_ids": [identity for identity, item in samples.items() if not item["terminal_fixed_h_contraction_pass"]],
        "prospective_graph": graph, "c4_result_sha256": C4_RESULT_SHA256, "c4_evidence_sha256": C4_EVIDENCE_SHA256, "c4_next_axis_sha256": C4_NEXT_AXIS_SHA256,
        "r224_reconciliation_file_sha256": R224_RECONCILIATION_SHA256,
        "current_0p02_policy_calibration": "INCONCLUSIVE", "c1_rescoring": False, "threshold_change_authorized": False,
        "holdout_used": False, "band2_chern_execution": False,
        "execution": {"native_invocation_count": 0, "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False},
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C6_M1_ADAPTIVE_TERMINAL_FIXED_H_ANALYSIS_COMPLETE",
    }
    return result


def evidence_artifact(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in (
        "schema", "work_order_id", "base_sandbox_sha", "final_sandbox_sha", "origin_sandbox_sha", "main_sha",
        "machine_contract_status", "parent_dataset_binding", "r192_dataset_binding", "r192_provenance_status",
        "r224_dataset_binding", "r224_state_reconciliation_status", "targeted_r224_sample_count", "samples",
        "controls", "policy_challenges", "stencil_diagnostic", "r224_final_contraction_pass_count",
        "total_terminal_fixed_h_pass_count", "locked_set_0p02_adaptive_fixed_h_policy_evidence",
        "q2_finite_stencil_convergence_status", "current_0p02_policy_calibration", "c1_rescoring",
        "threshold_change_authorized", "holdout_used", "band2_chern_execution", "execution", "pipeline_health",
        "blocked_by_infrastructure", "scientific_work_must_stop", "terminal")}


def next_axis_artifact(result: dict[str, Any]) -> dict[str, Any]:
    graph = result["prospective_graph"]
    return {
        "schema": "mephc-r8-c6-next-axis-contract-v1", "work_order_id": result["work_order_id"],
        "status": graph["status"], "next_axis_decision": result["next_axis_decision"],
        "unresolved_sample_ids": result["unresolved_sample_ids"], "axis": graph["axis"],
        "selected_sample_ids": graph["selected_sample_ids"], "logical_demand_count": graph["logical_demand_count"],
        "unique_provider_request_count": graph["unique_provider_request_count"], "duplicate_count": graph["duplicate_count"],
        "collisions": graph["collisions"], "designed_not_executed": True, "h_1_288_execution": False,
        "r256_execution": False, "r224_execution": False, "q2_finite_stencil_convergence_status": result["q2_finite_stencil_convergence_status"],
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"], "c1_rescoring": False,
        "threshold_change_authorized": False, "terminal": result["terminal"],
    }


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    challenges = list(result["policy_challenges"].values())
    graph = result["prospective_graph"]
    return {
        "schema": result["schema"], "work_order_id": result["work_order_id"], "base_sandbox_sha": result["base_sandbox_sha"],
        "final_sandbox_sha": result["final_sandbox_sha"], "origin_sandbox_sha": result["origin_sandbox_sha"], "main_sha": result["main_sha"],
        "machine_contract_status": result["machine_contract_status"], "parent_dataset_binding_status": result["parent_dataset_binding"]["status"],
        "r192_dataset_binding_status": result["r192_dataset_binding"]["status"], "r224_dataset_binding_status": result["r224_dataset_binding"]["status"],
        "r224_state_reconciliation_status": result["r224_state_reconciliation_status"], "targeted_r224_sample_count": 4,
        "r224_final_contraction_pass_count": result["r224_final_contraction_pass_count"], "total_terminal_fixed_h_pass_count": result["total_terminal_fixed_h_pass_count"],
        "control_1_terminal_status": result["samples"][sample_id(-10, -3)]["terminal_fixed_h_contraction_pass"],
        "control_1_terminal_resolution": result["samples"][sample_id(-10, -3)]["terminal_fixed_h_resolution"],
        "control_2_terminal_status": result["samples"][sample_id(-34, 9)]["terminal_fixed_h_contraction_pass"],
        "control_2_terminal_resolution": result["samples"][sample_id(-34, 9)]["terminal_fixed_h_resolution"],
        "control_terminal_fixed_h_metric_envelope": result["controls"]["terminal_fixed_h_metric_envelope"],
        "control_max_terminal_resolution": result["controls"]["max_terminal_resolution"],
        "policy_challenge_adaptive_noninferior_count": challenges.count("CONTROL_REFERENCED_ADAPTIVE_FIXED_H_NONINFERIOR"),
        "policy_challenge_adaptive_inferior_count": sum(value.startswith("CONTROL_REFERENCED_ADAPTIVE_FIXED_H_INFERIOR") for value in challenges),
        "policy_challenge_adaptive_incomplete_count": sum(value.startswith("INCOMPLETE") for value in challenges),
        "stencil_diagnostic_terminal_status": result["stencil_diagnostic"]["terminal_status"],
        "locked_set_0p02_adaptive_fixed_h_policy_evidence": result["locked_set_0p02_adaptive_fixed_h_policy_evidence"],
        "q2_finite_stencil_convergence_status": result["q2_finite_stencil_convergence_status"], "next_axis_decision": result["next_axis_decision"],
        "unresolved_sample_count": len(result["unresolved_sample_ids"]), "unresolved_sample_ids": result["unresolved_sample_ids"],
        "prospective_axis": graph["axis"], "prospective_logical_demand_count": graph["logical_demand_count"],
        "prospective_unique_provider_request_count": graph["unique_provider_request_count"], "prospective_duplicate_count": graph["duplicate_count"],
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"], "c1_rescoring": False,
        "threshold_change_authorized": False, "native_invocation_count": 0, "provider_request_count": 0,
        "native_solves": 0, "mpb_execution": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False, "result_sha256": hashlib.sha256(canonical(result)).hexdigest(), "terminal": result["terminal"],
    }


def main() -> int:
    try:
        result = analyze()
        scientific_job = load_module("_r8_c6_output_job", SCIENCE_JOB_PATH)
        scientific_job.atomic_json(EVIDENCE_PATH, evidence_artifact(result))
        scientific_job.atomic_json(NEXT_AXIS_PATH, next_axis_artifact(result))
        output = canonical(result_summary(result))
        if len(output) > 65536:
            raise AnalysisError("SUCCESS_STDOUT_LIMIT_EXCEEDED")
        print("MEPHC_NATIVE_RESULT_JSON=" + output.decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-r8-c6-adaptive-terminal-fixed-h-analysis-v1", "state": "failed",
            "error_code": type(exc).__name__, "detail": str(exc)[:1000], "native_invocation_count": 0,
            "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False,
            "terminal": "E9F_C2_QP_B_C2_C3_R8_C6_M1_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
