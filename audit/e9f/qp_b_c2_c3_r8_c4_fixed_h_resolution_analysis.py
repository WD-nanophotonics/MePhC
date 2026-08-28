"""Solver-free fixed-h solver-resolution analysis for the receipt-bound R8.C4.M1 work order.

The R96/R128/R160 values are read from the immutable R8 parent dataset and
the R192 values are read from the separately reconciled immutable R192
dataset.  The accepted C1 rank-one H-space estimator is reused; this module
never constructs a provider and never executes Native, MPB, or a solver.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT_BINDING_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_d3_acquisition_binding.json"
PARENT_GRAPH_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_global_provider_request_graph.json"
PARENT_C1_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c1_solver_free_calibration.py"
PARENT_C1_ARTIFACT_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c1_calibration.json"
R192_BINDING_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_acquisition_binding.json"
R192_RECONCILIATION_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_provenance_reconciliation.json"
R192_GRAPH_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_request_graph.json"
R192_ACQUISITION_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c3_r192_acquisition.py"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
SCIENCE_JOB_PATH = ROOT / "tools/mephc-flow/scientific_job.py"
EVIDENCE_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c4_fixed_h_resolution_evidence.json"
NEXT_AXIS_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_c4_next_axis_contract.json"

WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C4-M1-20260828-311"
BASE_SANDBOX_SHA = "801b9e0b4e2b6158aee5c8f4486ccb00fba50982"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
PARENT_DATASET_ID = "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db"
PARENT_MANIFEST_SHA256 = "55828e4a0eb6e24914807e42d13fa113457ce080ffe37c947b3c0cd7af1281d7"
PARENT_SOURCE_COMMIT = "c8eeaa4e5fa78e25a5b7df07510b446b1f6d6738"
R192_DATASET_ID = "446ad69a302c9eb3524b67fe2127701030f62986dd1ccc570e3b0830a3dc488c"
R192_MANIFEST_SHA256 = "4db0377cf2126fcc1ed8fb4b74a0ed6a2bd0ccf2e58e4a22e922262bc427d7d5"
R192_DECLARED_SOURCE_COMMIT = "56f7e51a2cb910a7187d982366a492c9cb17bd09"
R192_VERIFIED_SOURCE_COMMIT = "f468e6016fed3019fcdf5937722abf47d20995e6"
R192_RECONCILIATION_SHA256 = "bc49f09faaaa2eeb27d47e41f846361218d40d32f8cebf3078dfe3db1261ba10"
R192_ENTRYPOINT_SHA256 = "2e690c68a1a270189d15cbaf1a9c173f684c64acf6309c8635d72cc395c18b2f"
R192_GRAPH_SHA256 = "c0dc7ba7600e2bd18a7c57cb91683ece237f432cb68e70f325725535a0091008"
R192_RUNTIME_SHA256 = "d292915b021769ae3c5ee2be3181b6aef4acf021bb178ec2af5ea6ac9905f022"
RESOLUTIONS = ("R96", "R128", "R160", "R192")
STENCILS = ("1/72", "1/144")
SAMPLES = (
    (-10, -3, "CALIBRATION_CONTROL"), (-34, 9, "CALIBRATION_CONTROL"),
    (-6, -1, "STENCIL_DIAGNOSTIC"), (-34, -16, "POLICY_CHALLENGE"),
    (-34, -17, "POLICY_CHALLENGE"), (-34, 17, "POLICY_CHALLENGE"),
    (-5, 0, "POLICY_CHALLENGE"), (-4, 0, "POLICY_CHALLENGE"),
)
POINTS = {
    "1/72": ("H72_PLUS_X", "H72_PLUS_Y", "H72_MINUS_X", "H72_MINUS_Y", "CENTER"),
    "1/144": ("H144_PLUS_X", "H144_PLUS_Y", "H144_MINUS_X", "H144_MINUS_Y", "CENTER"),
}
SAMPLE_ROLES = {f"fr=0;grid_i={i};grid_j={j};estimator=SOURCE_GRID": role for i, j, role in SAMPLES}


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


def srd(left: float, right: float) -> float:
    left, right = float(left), float(right)
    if left == 0.0 and right == 0.0:
        return 0.0
    return 2.0 * abs(left - right) / (abs(left) + abs(right))


def sample_id(i: int, j: int) -> str:
    return f"fr=0;grid_i={i};grid_j={j};estimator=SOURCE_GRID"


def current_source_commit() -> str:
    value = os.environ.get("MEPHC_SOURCE_COMMIT", BASE_SANDBOX_SHA)
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise AnalysisError("CURRENT_SOURCE_COMMIT_INVALID")
    return value


def verify_parent_inputs(c1: Any) -> tuple[dict[str, Any], dict[str, Any], Any, Any, Any]:
    binding, graph = c1.verify_public_inputs()
    if sha256(PARENT_GRAPH_PATH) != c1.GRAPH_SHA256:
        raise AnalysisError("PARENT_GRAPH_SHA256_MISMATCH")
    runtime, dataset = c1.open_dataset(binding)
    entrypoint = load_module("_r8_c4_parent_entrypoint", ROOT / "audit/e9f/qp_b_c2_c3_r8_locked_set_native.py")
    entrypoint.verify_graph(graph)
    snapshots = c1.demand_index(graph, entrypoint, dataset)
    if len(snapshots) != 216:
        raise AnalysisError("PARENT_LOGICAL_BUNDLE_INCOMPLETE")
    return binding, graph, runtime, entrypoint, snapshots


def verify_r192_binding() -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    binding = read_json(R192_BINDING_PATH)
    expected = {
        "schema": "mephc_e9f_qp_b_c2_c3_r8_c3_r192_acquisition_binding_v2",
        "raw_immutable_dataset_id": R192_DATASET_ID,
        "raw_immutable_dataset_manifest_sha256": R192_MANIFEST_SHA256,
        "raw_dataset_declared_source_commit": R192_DECLARED_SOURCE_COMMIT,
        "verified_execution_source_commit": R192_VERIFIED_SOURCE_COMMIT,
        "provenance_reconciliation_sha256": R192_RECONCILIATION_SHA256,
        "provenance_status": "RECONCILED", "R192_dataset_record_count": 70,
        "parent_dataset_id": PARENT_DATASET_ID, "entrypoint_sha256": R192_ENTRYPOINT_SHA256,
        "graph_sha256": R192_GRAPH_SHA256, "runtime_sha256": R192_RUNTIME_SHA256,
        "future_consumer_requires_reconciliation": True,
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise AnalysisError("R192_BINDING_MISMATCH")
    reconciliation = read_json(R192_RECONCILIATION_PATH)
    unsigned = {key: value for key, value in reconciliation.items() if key != "canonical_reconciliation_sha256"}
    if (reconciliation.get("canonical_reconciliation_sha256") != R192_RECONCILIATION_SHA256
            or hashlib.sha256(canonical(unsigned)).hexdigest() != R192_RECONCILIATION_SHA256
            or reconciliation.get("verified_execution_source_commit") != R192_VERIFIED_SOURCE_COMMIT
            or reconciliation.get("reconciliation_status") != "VERIFIED_EXECUTION_SOURCE_REBOUND_WITHOUT_DATASET_MUTATION"
            or reconciliation.get("full_r192_record_integrity_pass_count") != 70):
        raise AnalysisError("R192_RECONCILIATION_INVALID")
    if sha256(R192_GRAPH_PATH) != R192_GRAPH_SHA256:
        raise AnalysisError("R192_GRAPH_SHA256_MISMATCH")
    acquisition = load_module("_r8_c4_r192_acquisition", R192_ACQUISITION_PATH)
    graph = read_json(R192_GRAPH_PATH)
    acquisition.verify_graph(graph)
    return binding, graph, reconciliation, acquisition


def open_r192_dataset(binding: dict[str, Any], graph: dict[str, Any], acquisition: Any) -> dict[tuple[int, int, str, str], Any]:
    runtime = load_module("_r8_c4_r192_runtime", RUNTIME_PATH)
    scientific_job = load_module("_r8_c4_scientific_job", SCIENCE_JOB_PATH)
    namespace = {
        "project_id": "MEPHC", "science_contract_id": "E9F_QP_B_C2_C3_R8_LOCKED_SET_R192",
        "source_commit": R192_DECLARED_SOURCE_COMMIT,
        "work_order_id": "MEPHC-E9F-C2-QP-B-C2-C3-R8-C3-A1-20260828-307",
        "resolution": "R192", "entrypoint_sha256": R192_ENTRYPOINT_SHA256,
        "graph_sha256": R192_GRAPH_SHA256, "science_runtime_sha256": R192_RUNTIME_SHA256,
    }
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    manifest_path = store.root / "acquisition-dataset-manifest.json"
    manifest = read_json(manifest_path)
    unsigned_id = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("dataset_id") != R192_DATASET_ID
            or hashlib.sha256(canonical(unsigned_id)).hexdigest() != R192_DATASET_ID
            or manifest.get("manifest_sha256") != R192_MANIFEST_SHA256
            or hashlib.sha256(canonical(unsigned_manifest)).hexdigest() != R192_MANIFEST_SHA256
            or manifest.get("completed_key_count") != 70
            or manifest.get("completion_state") != "COMPLETE"
            or manifest.get("acquisition_source_commit") != R192_DECLARED_SOURCE_COMMIT):
        raise AnalysisError("R192_MANIFEST_INVALID")
    graph_plan = acquisition.build_provider_plan(graph)
    records = {item.get("key_sha256"): item for item in manifest.get("records", [])}
    if len(records) != 70:
        raise AnalysisError("R192_RECORD_INDEX_INVALID")
    snapshots: dict[tuple[int, int, str, str], Any] = {}
    for demand in graph["logical_demands"]:
        grid = demand["sample_grid"]
        key = acquisition.canonical_key(demand["request_key"])
        key_sha = hashlib.sha256(key).hexdigest()
        payload, metadata = store.get(key)
        listed = records.get(key_sha)
        if listed is None or any(metadata.get(field) != listed.get(field) for field in ("key_sha256", "payload_sha256", "payload_size_bytes")):
            raise AnalysisError("R192_RECORD_METADATA_MISMATCH")
        identity = metadata.get("identity", {})
        if (identity.get("resolution") != "R192"
                or identity.get("source_model_identity") != "FROZEN_QP_B_SOURCE_MODEL"
                or identity.get("provider_configuration_identity") != "FROZEN_QP_B_PROVIDER_CONFIGURATION"
                or identity.get("band_request_configuration") != "FROZEN_QP_B_LOCKED_BAND_REQUEST"):
            raise AnalysisError("R192_RECORD_IDENTITY_MISMATCH")
        snapshot = runtime.decode_snapshot(payload)
        coordinate = demand["request_key"]["canonical_k_coordinate_units_1_over_144"]
        if (snapshot.provenance.get("representation") != "mpb_periodic_h_l2_v1"
                or tuple(snapshot.k_point) != (coordinate["i"] / 144.0, coordinate["j"] / 144.0)):
            raise AnalysisError("R192_SNAPSHOT_IDENTITY_MISMATCH")
        identity_key = (grid["i"], grid["j"], "R192", demand["point"])
        prior = snapshots.get(identity_key)
        if prior is not None and not np.array_equal(prior.frequencies, snapshot.frequencies):
            raise AnalysisError("R192_DUPLICATE_PAYLOAD_MISMATCH")
        snapshots[identity_key] = snapshot
        del payload, metadata, snapshot
    if len(snapshots) != 72:
        raise AnalysisError("R192_LOGICAL_BUNDLE_INCOMPLETE")
    if {acquisition.canonical_key(item["request_key"]) for item in graph_plan} != {
        acquisition.canonical_key(demand["request_key"]) for demand in graph["logical_demands"]
    }:
        raise AnalysisError("R192_PLAN_KEY_SET_MISMATCH")
    return snapshots


def evaluate_pair(c1: Any, i: int, j: int, resolution: str, snapshots: dict[tuple[int, int, str, str], Any], policy_gap: float) -> dict[str, Any]:
    pair = c1.evaluate_pair(i, j, resolution, snapshots, policy_gap)
    pair["r192_provenance_valid"] = True
    return pair


def relation(first: float, second: float) -> str:
    if second < first:
        return "FINAL_INCREMENT_CONTRACTS"
    if second > first:
        return "FINAL_INCREMENT_EXPANDS"
    if first == 0.0 and second == 0.0:
        return "ALL_ZERO_STABLE"
    return "FINAL_INCREMENT_EQUAL_NONZERO"


def signed_behavior(first: float, second: float) -> str:
    return "MONOTONIC_LAST_TWO_STEPS" if first == 0.0 or second == 0.0 or first * second > 0.0 else "OSCILLATORY_OR_OVERSHOOT_LAST_TWO_STEPS"


def resolution_metrics(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    by_resolution = {item["resolution"]: item for item in pairs}
    if set(by_resolution) != set(RESOLUTIONS):
        raise AnalysisError("RESOLUTION_SEQUENCE_INCOMPLETE")
    stencils: dict[str, Any] = {}
    for stencil in STENCILS:
        omega = {resolution: float(by_resolution[resolution]["curvature"][stencil]) for resolution in RESOLUTIONS}
        signed = {resolution: omega[resolution] - omega[previous] for previous, resolution in zip(RESOLUTIONS, RESOLUTIONS[1:])}
        absolute = {name: abs(value) for name, value in signed.items()}
        classifications = {
            "96_128": relation(absolute["R128"], absolute["R160"]),
            "128_160": relation(absolute["R160"], absolute["R192"]),
        }
        stencils[stencil] = {
            "omega": omega,
            "signed_increment_96_128": signed["R128"],
            "signed_increment_128_160": signed["R160"],
            "signed_increment_160_192": signed["R192"],
            "abs_increment_96_128": absolute["R128"],
            "abs_increment_128_160": absolute["R160"],
            "abs_increment_160_192": absolute["R192"],
            "step_srd_96_128": srd(omega["R96"], omega["R128"]),
            "step_srd_128_160": srd(omega["R128"], omega["R160"]),
            "step_srd_160_192": srd(omega["R160"], omega["R192"]),
            "final_increment_classification": classifications["128_160"],
            "last_two_step_sign_classification": signed_behavior(signed["R160"], signed["R192"]),
        }
    complete = all(item["status"] == "COMPLETE_VALID" for item in pairs)
    final_pass = all(item["final_increment_classification"] in {"FINAL_INCREMENT_CONTRACTS", "ALL_ZERO_STABLE"} for item in stencils.values())
    return {
        "stencils": stencils,
        "final_fixed_h_resolution_metric": max(item["step_srd_160_192"] for item in stencils.values()),
        "final_fixed_h_contraction_pass": final_pass,
        "all_evidence_complete": complete,
        "r192_provenance_valid": all(item["r192_provenance_valid"] for item in pairs),
    }


def prospective_graph(samples: list[tuple[int, int, str, dict[str, Any]]], decision: str) -> dict[str, Any]:
    if decision == "PROCEED_TO_R192_H_1_288_THIRD_STENCIL_DESIGN":
        resolution, denominator = "R192", 288
        selected = [(i, j, role) for i, j, role, _ in samples]
        points = ("H288_PLUS_X", "H288_MINUS_X", "H288_PLUS_Y", "H288_MINUS_Y")
        offsets = ((1, 0), (-1, 0), (0, 1), (0, -1))
        logical: list[dict[str, Any]] = []
        for i, j, role in selected:
            for point, (di, dj) in zip(points, offsets):
                logical.append({"sample_id": sample_id(i, j), "role": role, "resolution": resolution, "point": point,
                                "coordinate": {"i_numerator": 8 * i + di, "j_numerator": 8 * j + dj, "denominator": denominator}})
        axis = "H_1_288"
    elif decision == "TARGETED_HIGHER_RESOLUTION_REQUIRED_BEFORE_THIRD_STENCIL":
        resolution, denominator = "R224", 144
        selected = [item for item in samples if not item[3]["final_fixed_h_contraction_pass"]]
        points = ("CENTER", "H72_PLUS_X", "H72_MINUS_X", "H72_PLUS_Y", "H72_MINUS_Y", "H144_PLUS_X", "H144_MINUS_X", "H144_PLUS_Y", "H144_MINUS_Y")
        offsets = ((0, 0), (2, 0), (-2, 0), (0, 2), (0, -2), (1, 0), (-1, 0), (0, 1), (0, -1))
        logical = []
        for i, j, role, _ in selected:
            for point, (di, dj) in zip(points, offsets):
                logical.append({"sample_id": sample_id(i, j), "role": role, "resolution": resolution, "point": point,
                                "coordinate": {"i_numerator": 4 * i + di, "j_numerator": 4 * j + dj, "denominator": denominator}})
        axis = "R224"
    else:
        return {"status": "NOT_APPLICABLE", "logical_demand_count": 0, "unique_provider_request_count": 0, "duplicate_count": 0, "collisions": []}
    keys: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in logical:
        coordinate = item["coordinate"]
        key = (item["resolution"], coordinate["i_numerator"], coordinate["j_numerator"], coordinate["denominator"], "FROZEN_QP_B_SOURCE_MODEL", "FROZEN_QP_B_PROVIDER_CONFIGURATION", "FROZEN_QP_B_LOCKED_BAND_REQUEST")
        keys.setdefault(key, []).append(item)
    collisions = [refs for refs in keys.values() if len(refs) > 1]
    selected_ids = [item[0] if isinstance(item, tuple) else item["sample_id"] for item in selected]
    return {
        "status": "DESIGNED_NOT_EXECUTED", "axis": axis,
        "selected_sample_ids": selected_ids,
        "logical_demand_count": len(logical), "unique_provider_request_count": len(keys),
        "duplicate_count": len(logical) - len(keys),
        "collisions": collisions,
        "logical_demands": logical,
    }


def analyze() -> dict[str, Any]:
    c1 = load_module("_r8_c4_c1_calibration", PARENT_C1_PATH)
    parent_binding, parent_graph, _, _, parent_snapshots = verify_parent_inputs(c1)
    r192_binding, r192_graph, reconciliation, _ = verify_r192_binding()
    r192_snapshots = open_r192_dataset(r192_binding, r192_graph, load_module("_r8_c4_r192_acquisition_again", R192_ACQUISITION_PATH))
    snapshots = {**parent_snapshots, **r192_snapshots}
    prior = read_json(PARENT_C1_ARTIFACT_PATH)
    policy_gaps = {item["sample_id"]: float(item["external_gap"]) for item in read_json(c1.ANCHOR_PATH)["frozen_sample_ids"]}
    pairs = [evaluate_pair(c1, i, j, resolution, snapshots, policy_gaps[sample_id(i, j)]) for i, j, _ in SAMPLES for resolution in RESOLUTIONS]
    by_sample: dict[str, Any] = {}
    for i, j, role in SAMPLES:
        identity = sample_id(i, j)
        sample_pairs = [item for item in pairs if item["sample_id"] == identity]
        metrics = resolution_metrics(sample_pairs)
        by_sample[identity] = {"sample_id": identity, "role": role, **metrics,
                               "current_policy_gap_status": sample_pairs[0]["current_policy_gap_status"]}
    controls = [identity for identity, role in SAMPLE_ROLES.items() if role == "CALIBRATION_CONTROL"]
    control_valid = all(by_sample[identity]["all_evidence_complete"] and by_sample[identity]["r192_provenance_valid"] and by_sample[identity]["final_fixed_h_contraction_pass"] for identity in controls)
    envelope = max(by_sample[identity]["final_fixed_h_resolution_metric"] for identity in controls) if control_valid else None
    challenges: dict[str, str] = {}
    for identity, role in SAMPLE_ROLES.items():
        if role != "POLICY_CHALLENGE":
            continue
        sample = by_sample[identity]
        valid = sample["all_evidence_complete"] and sample["r192_provenance_valid"] and sample["final_fixed_h_contraction_pass"]
        if envelope is None or not valid:
            challenges[identity] = "INCOMPLETE_NO_CONTROL_ENVELOPE" if envelope is None else "INCOMPLETE_FIXED_H_EVIDENCE"
        elif sample["final_fixed_h_resolution_metric"] <= envelope:
            challenges[identity] = "CONTROL_REFERENCED_FIXED_H_NONINFERIOR"
        else:
            challenges[identity] = "CONTROL_REFERENCED_FIXED_H_INFERIOR"
    diagnostic_id = next(identity for identity, role in SAMPLE_ROLES.items() if role == "STENCIL_DIAGNOSTIC")
    diagnostic = by_sample[diagnostic_id]
    if control_valid and all(value == "CONTROL_REFERENCED_FIXED_H_NONINFERIOR" for value in challenges.values()):
        q1 = "BELOW_POLICY_SAMPLES_CONTROL_REFERENCED_NONINFERIOR"
    elif control_valid and any(value == "CONTROL_REFERENCED_FIXED_H_INFERIOR" for value in challenges.values()):
        q1 = "BELOW_POLICY_SAMPLE_FIXED_H_INFERIORITY_OBSERVED"
    else:
        q1 = "INCONCLUSIVE"
    all_eight_pass = all(item["final_fixed_h_contraction_pass"] and item["all_evidence_complete"] and item["r192_provenance_valid"] for item in by_sample.values())
    any_complete_fail = any(item["all_evidence_complete"] and item["r192_provenance_valid"] and not item["final_fixed_h_contraction_pass"] for item in by_sample.values())
    next_decision = "PROCEED_TO_R192_H_1_288_THIRD_STENCIL_DESIGN" if all_eight_pass else "TARGETED_HIGHER_RESOLUTION_REQUIRED_BEFORE_THIRD_STENCIL" if any_complete_fail else "INCONCLUSIVE_DATA_OR_PROVENANCE"
    sample_entries = [(i, j, role, by_sample[sample_id(i, j)]) for i, j, role in SAMPLES]
    graph = prospective_graph(sample_entries, next_decision)
    result = {
        "schema": "mephc-r8-c4-fixed-h-resolution-analysis-v1", "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": current_source_commit(),
        "origin_sandbox_sha": current_source_commit(), "main_sha": MAIN_SHA, "machine_contract_status": "PASS",
        "parent_dataset_binding": {"status": "VERIFIED", "dataset_id": parent_binding["acquisition_dataset_id"], "manifest_sha256": parent_binding["dataset_manifest_sha256"], "record_count": 210, "source_commit": PARENT_SOURCE_COMMIT},
        "r192_dataset_binding": {"status": "VERIFIED", "dataset_id": R192_DATASET_ID, "manifest_sha256": R192_MANIFEST_SHA256, "record_count": 70, "declared_source_commit": R192_DECLARED_SOURCE_COMMIT, "verified_execution_source_commit": R192_VERIFIED_SOURCE_COMMIT, "reconciliation_sha256": R192_RECONCILIATION_SHA256},
        "r192_provenance_status": reconciliation["reconciliation_status"], "sample_count": 8,
        "samples": by_sample, "controls": {"ids": controls, "valid": control_valid, "fixed_h_resolution_envelope": envelope},
        "policy_challenges": challenges, "stencil_diagnostic": {"sample_id": diagnostic_id, "fixed_h_status": diagnostic["final_fixed_h_contraction_pass"], "metric": diagnostic["final_fixed_h_resolution_metric"]},
        "all_eight_fixed_h_contraction_pass_count": sum(1 for item in by_sample.values() if item["final_fixed_h_contraction_pass"]),
        "locked_set_0p02_fixed_h_policy_evidence": q1, "q2_finite_stencil_convergence_status": "NOT_ESTABLISHED_WITH_TWO_STENCILS",
        "next_axis_decision": next_decision, "unresolved_sample_ids": [identity for identity, item in by_sample.items() if not item["final_fixed_h_contraction_pass"]],
        "prospective_graph": graph, "prior_c1_artifact_sha256": sha256(PARENT_C1_ARTIFACT_PATH),
        "current_0p02_policy_calibration": "INCONCLUSIVE", "c1_rescoring": False, "threshold_change_authorized": False,
        "holdout_used": False, "band2_chern_execution": False,
        "execution": {"native_invocation_count": 0, "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False},
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C4_M1_FIXED_H_RESOLUTION_ANALYSIS_COMPLETE",
    }
    return result


def evidence_artifact(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": result["schema"], "work_order_id": result["work_order_id"],
        "base_sandbox_sha": result["base_sandbox_sha"], "final_sandbox_sha": result["final_sandbox_sha"],
        "origin_sandbox_sha": result["origin_sandbox_sha"], "main_sha": result["main_sha"],
        "machine_contract_status": result["machine_contract_status"],
        "parent_dataset_binding": result["parent_dataset_binding"], "r192_dataset_binding": result["r192_dataset_binding"],
        "r192_provenance_status": result["r192_provenance_status"], "sample_count": result["sample_count"],
        "samples": result["samples"], "controls": result["controls"], "policy_challenges": result["policy_challenges"],
        "stencil_diagnostic": result["stencil_diagnostic"],
        "all_eight_fixed_h_contraction_pass_count": result["all_eight_fixed_h_contraction_pass_count"],
        "locked_set_0p02_fixed_h_policy_evidence": result["locked_set_0p02_fixed_h_policy_evidence"],
        "q2_finite_stencil_convergence_status": result["q2_finite_stencil_convergence_status"],
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"],
        "c1_rescoring": result["c1_rescoring"], "threshold_change_authorized": result["threshold_change_authorized"],
        "holdout_used": result["holdout_used"], "band2_chern_execution": result["band2_chern_execution"],
        "execution": result["execution"], "pipeline_health": result["pipeline_health"],
        "blocked_by_infrastructure": result["blocked_by_infrastructure"], "scientific_work_must_stop": result["scientific_work_must_stop"],
        "terminal": result["terminal"],
    }


def next_axis_artifact(result: dict[str, Any]) -> dict[str, Any]:
    graph = result["prospective_graph"]
    return {
        "schema": "mephc-r8-c4-next-axis-contract-v1", "work_order_id": result["work_order_id"],
        "status": graph["status"], "next_axis_decision": result["next_axis_decision"],
        "unresolved_sample_ids": result["unresolved_sample_ids"],
        "logical_demand_count": graph["logical_demand_count"],
        "unique_provider_request_count": graph["unique_provider_request_count"],
        "duplicate_count": graph["duplicate_count"], "collisions": graph["collisions"],
        "selected_sample_ids": graph.get("selected_sample_ids", []), "axis": graph.get("axis"),
        "designed_not_executed": True, "h_1_288_execution": False, "r224_execution": False,
        "q2_finite_stencil_convergence_status": result["q2_finite_stencil_convergence_status"],
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"],
        "c1_rescoring": result["c1_rescoring"], "threshold_change_authorized": result["threshold_change_authorized"],
        "terminal": result["terminal"],
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
        "r192_dataset_binding_status": result["r192_dataset_binding"]["status"],
        "r192_provenance_status": result["r192_provenance_status"], "sample_count": result["sample_count"],
        "control_1_fixed_h_status": result["samples"]["fr=0;grid_i=-10;grid_j=-3;estimator=SOURCE_GRID"]["final_fixed_h_contraction_pass"],
        "control_2_fixed_h_status": result["samples"]["fr=0;grid_i=-34;grid_j=9;estimator=SOURCE_GRID"]["final_fixed_h_contraction_pass"],
        "control_fixed_h_resolution_envelope": result["controls"]["fixed_h_resolution_envelope"],
        "policy_challenge_fixed_h_noninferior_count": challenges.count("CONTROL_REFERENCED_FIXED_H_NONINFERIOR"),
        "policy_challenge_fixed_h_inferior_count": challenges.count("CONTROL_REFERENCED_FIXED_H_INFERIOR"),
        "policy_challenge_fixed_h_incomplete_count": sum(value not in {"CONTROL_REFERENCED_FIXED_H_NONINFERIOR", "CONTROL_REFERENCED_FIXED_H_INFERIOR"} for value in challenges),
        "stencil_diagnostic_fixed_h_status": result["stencil_diagnostic"]["fixed_h_status"],
        "all_eight_fixed_h_contraction_pass_count": result["all_eight_fixed_h_contraction_pass_count"],
        "locked_set_0p02_fixed_h_policy_evidence": result["locked_set_0p02_fixed_h_policy_evidence"],
        "q2_finite_stencil_convergence_status": result["q2_finite_stencil_convergence_status"],
        "next_axis_decision": result["next_axis_decision"], "unresolved_sample_count": len(result["unresolved_sample_ids"]),
        "unresolved_sample_ids": result["unresolved_sample_ids"],
        "prospective_logical_demand_count": graph["logical_demand_count"],
        "prospective_unique_provider_request_count": graph["unique_provider_request_count"],
        "prospective_duplicate_count": graph["duplicate_count"],
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"], "c1_rescoring": False,
        "threshold_change_authorized": False, "native_invocation_count": 0, "provider_request_count": 0,
        "native_solves": 0, "mpb_execution": False, "pipeline_health": "HEALTHY",
        "blocked_by_infrastructure": False, "scientific_work_must_stop": False, "result_sha256": hashlib.sha256(canonical(result)).hexdigest(),
        "terminal": result["terminal"],
    }


def main() -> int:
    try:
        result = analyze()
        scientific_job = load_module("_r8_c4_output_job", SCIENCE_JOB_PATH)
        scientific_job.atomic_json(EVIDENCE_PATH, evidence_artifact(result))
        scientific_job.atomic_json(NEXT_AXIS_PATH, next_axis_artifact(result))
        output = canonical(result_summary(result))
        if len(output) > 65536:
            raise AnalysisError("SUCCESS_STDOUT_LIMIT_EXCEEDED")
        print("MEPHC_NATIVE_RESULT_JSON=" + output.decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-r8-c4-fixed-h-resolution-analysis-v1", "state": "failed",
            "error_code": type(exc).__name__, "detail": str(exc)[:1000],
            "native_invocation_count": 0, "provider_request_count": 0,
            "solver_executions": 0, "native_solves": 0, "mpb_execution": False,
            "terminal": "E9F_C2_QP_B_C2_C3_R8_C4_M1_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
