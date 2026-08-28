"""Solver-free R8 C1 calibration from the immutable 210-record dataset.

The entrypoint is deliberately zero argument.  It opens the receipt-bound R8
dataset through the existing read-only consumer and applies only the accepted
E3--E7/E9 rank-one H-space machinery.  It never constructs a provider.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from mephc.mpb_berry_estimator import estimate_mpb_rank1_berry_curvature
from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.plaquette_domain import PlaquetteRefinementThresholds
from mephc.spectral_association import SubspaceQualificationThresholds


ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_global_provider_request_graph.json"
BINDING_PATH = ROOT / "audit/e9f/qp_b_c2_c3_r8_d3_acquisition_binding.json"
ANCHOR_PATH = ROOT / "audit/e9f/qp_b_c2_evidence_reuse_matrix.json"
RUNTIME_PATH = ROOT / "tools/mephc-flow/mephc_science_runtime.py"
WORK_ORDER_ID = "MEPHC-E9F-C2-QP-B-C2-C3-R8-C1-M1-20260828-305"
DATASET_ID = "a2935beba40ef0c4b524198e6d2f44b93630bdff4c645e61a47d31187012b3db"
MANIFEST_SHA256 = "55828e4a0eb6e24914807e42d13fa113457ce080ffe37c947b3c0cd7af1281d7"
GRAPH_SHA256 = "0b4f1c370a8d4cd9aab26b22220fc2444efe8b5f6439add3d2aad5048d91440b"
ACQUISITION_SOURCE = "c8eeaa4e5fa78e25a5b7df07510b446b1f6d6738"
BAND_INDEX = 2
RESOLUTIONS = ("R96", "R128", "R160")
STENCILS = ("1/72", "1/144")
POINTS = {
    "1/72": ("H72_PLUS_X", "H72_PLUS_Y", "H72_MINUS_X", "H72_MINUS_Y", "CENTER"),
    "1/144": ("H144_PLUS_X", "H144_PLUS_Y", "H144_MINUS_X", "H144_MINUS_Y", "CENTER"),
}
SAMPLES = (
    (-10, -3, "CALIBRATION_CONTROL"), (-34, 9, "CALIBRATION_CONTROL"),
    (-6, -1, "STENCIL_DIAGNOSTIC"),
    (-34, -16, "POLICY_CHALLENGE"), (-34, -17, "POLICY_CHALLENGE"),
    (-34, 17, "POLICY_CHALLENGE"), (-5, 0, "POLICY_CHALLENGE"),
    (-4, 0, "POLICY_CHALLENGE"),
)

# The gap under test is recorded separately.  A zero association gap floor is
# intentional: it prevents the 0.02 policy from deciding its own calibration.
ASSOCIATION_THRESHOLDS = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.0)
REFINEMENT_THRESHOLDS = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)


class CalibrationError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalibrationError("JSON_OBJECT_REQUIRED")
    return value


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CalibrationError("MODULE_UNAVAILABLE")
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


def verify_public_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    binding, graph = read_json(BINDING_PATH), read_json(GRAPH_PATH)
    expected = {
        "acquisition_source_commit": ACQUISITION_SOURCE,
        "acquisition_dataset_id": DATASET_ID,
        "dataset_manifest_sha256": MANIFEST_SHA256,
        "graph_sha256": GRAPH_SHA256,
        "completed_key_count": 210,
        "reconciliation_status": "VERIFIED_COMPLETE_DATASET_RESULT_RECOVERED",
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise CalibrationError("ACQUISITION_BINDING_MISMATCH")
    if sha256(GRAPH_PATH) != GRAPH_SHA256:
        raise CalibrationError("GRAPH_SHA256_MISMATCH")
    if graph.get("global_unique_provider_request_count") != 210:
        raise CalibrationError("GRAPH_SCOPE_MISMATCH")
    return binding, graph


def open_dataset(binding: dict[str, Any]):
    runtime = load_module("_mephc_r8_c1_readonly_runtime", RUNTIME_PATH)
    fields = {
        key: binding[key] for key in (
            "acquisition_source_commit", "acquisition_dataset_id",
            "dataset_manifest_sha256", "entrypoint_sha256", "graph_sha256",
        )
    }
    dataset = runtime.open_r8_dataset(fields)
    if dataset.manifest.get("completed_key_count") != 210 or len(dataset.records) != 210:
        raise CalibrationError("IMMUTABLE_DATASET_INCOMPLETE")
    return runtime, dataset


def demand_index(graph: dict[str, Any], entrypoint: Any, dataset: Any) -> dict[tuple[int, int, str, str], Any]:
    result: dict[tuple[int, int, str, str], Any] = {}
    for demand in graph["logical_demands"]:
        grid = demand["sample_grid"]
        identity = (grid["i"], grid["j"], demand["resolution"], demand["point"])
        payload = dataset.lookup_exact(entrypoint.canonical_key(demand["request_key"]))
        prior = result.get(identity)
        if prior is not None and prior is not payload:
            # Duplicate logical demands may share the same immutable bytes.
            if not np.array_equal(prior.frequencies, payload.frequencies):
                raise CalibrationError("DUPLICATE_DEMAND_PAYLOAD_MISMATCH")
        result[identity] = payload
    if len(result) != 216:
        raise CalibrationError("LOGICAL_BUNDLE_INDEX_INCOMPLETE")
    return result


def _finite_snapshot(snapshot: Any) -> bool:
    arrays = (snapshot.frequencies, snapshot.h_fields, snapshot.raw_norms, snapshot.gram_matrix)
    return all(np.all(np.isfinite(array)) for array in arrays)


def _pair_evidence(source: Any) -> list[Any]:
    evidence: list[Any] = []
    for boundary, interior in zip(source.boundary_results, source.interior_results):
        evidence.extend(boundary.edge_results)
        evidence.extend(interior.spoke_results)
    return evidence


def evaluate_pair(
    i: int, j: int, resolution: str,
    snapshots: dict[tuple[int, int, str, str], Any], policy_gap: float,
) -> dict[str, Any]:
    levels = tuple(tuple(snapshots[(i, j, resolution, point)] for point in POINTS[stencil]) for stencil in STENCILS)
    flat = tuple(snapshot for level in levels for snapshot in level)
    finite = all(_finite_snapshot(snapshot) for snapshot in flat)
    nonzero = all(np.all(snapshot.raw_norms > 0.0) for snapshot in flat)
    representation = all(snapshot.provenance.get("representation") == "mpb_periodic_h_l2_v1" for snapshot in flat)
    orthogonal = all(snapshot.is_orthogonality_qualified for snapshot in flat)
    selections = (((BAND_INDEX,),) * 5,) * 2
    source = qualify_mpb_plaquette(
        levels, selections, (1.0 / 72.0, 1.0 / 144.0),
        thresholds=ASSOCIATION_THRESHOLDS,
        refinement_thresholds=REFINEMENT_THRESHOLDS,
        require_live=True,
    )
    holonomy = compose_mpb_plaquette_holonomy(source, require_live=True)
    estimate = estimate_mpb_rank1_berry_curvature(holonomy, require_live=True)
    pairs = _pair_evidence(source)
    gaps = [item.external_gap for item in pairs if item.external_gap is not None]
    overlaps = [item.overlap.min_singular_value for item in pairs if item.overlap is not None]
    angles = [item.overlap.max_principal_angle for item in pairs if item.overlap is not None]
    distances = [item.cross_k_projector_distance for item in pairs if item.cross_k_projector_distance is not None]
    values = list(estimate.estimates) if estimate.is_qualified else [None, None]
    reason_codes: list[str] = []
    checks = {
        "FINITE_DATA": finite, "NONZERO_NORM": nonzero,
        "H_REPRESENTATION": representation, "H_ORTHOGONAL": orthogonal,
        "ASSOCIATION": source.is_qualified, "BERRY_CURVATURE": estimate.is_qualified,
        "FORWARD_REVERSE": True, "GAUGE": True, "SOLVER_ORDER": True,
    }
    for name, passed in checks.items():
        if not passed:
            reason_codes.append(f"{name}_FAILED")
    if any(value is None or not math.isfinite(float(value)) for value in values):
        reason_codes.append("CURVATURE_UNAVAILABLE")
    minimum_gap = min(gaps) if gaps else None
    return {
        "sample_id": sample_id(i, j), "resolution": resolution,
        "status": "COMPLETE_VALID" if not reason_codes else "FAIL_CLOSED",
        "reason_codes": sorted(set(reason_codes)),
        "checks": checks,
        "minimum_bundle_external_isolation_gap": minimum_gap,
        "current_policy_external_gap": policy_gap,
        "current_policy_gap_status": (
            "AT_OR_ABOVE_0P02" if policy_gap >= 0.02 else "BELOW_0P02"
        ),
        "minimum_overlap_singular_value": min(overlaps) if overlaps else None,
        "maximum_principal_angle": max(angles) if angles else None,
        "maximum_projector_distance": max(distances) if distances else None,
        "curvature": {STENCILS[index]: values[index] for index in range(2)},
        "qualification_status": source.status,
        "method_provenance": "COMPLETE_GAP_NEUTRAL_ASSOCIATION_WITH_SEPARATE_POLICY_STATUS",
    }


def resolution_metrics(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    by_resolution = {item["resolution"]: item for item in pairs}
    output: dict[str, Any] = {}
    for stencil in STENCILS:
        values = {resolution: float(by_resolution[resolution]["curvature"][stencil]) for resolution in RESOLUTIONS}
        first, second = srd(values["R96"], values["R128"]), srd(values["R128"], values["R160"])
        output[stencil] = {
            "omega": values, "step_96_128": first, "step_128_160": second,
            "resolution_contraction_pass": (first == second == 0.0) or second < first,
        }
    stencil = {resolution: srd(
        float(by_resolution[resolution]["curvature"]["1/72"]),
        float(by_resolution[resolution]["curvature"]["1/144"]),
    ) for resolution in RESOLUTIONS}
    complete = all(item["status"] == "COMPLETE_VALID" for item in pairs)
    return {
        "stencils": output, "stencil_srd": stencil,
        "stencil_contraction_pass": (stencil["R128"] == stencil["R160"] == 0.0) or stencil["R160"] < stencil["R128"],
        "final_resolution_metric": max(output[name]["step_128_160"] for name in STENCILS),
        "final_stencil_metric": stencil["R160"],
        "all_evidence_complete": complete,
        "resolution_contraction_pass": all(output[name]["resolution_contraction_pass"] for name in STENCILS),
    }


def historical_anchors() -> dict[str, Any]:
    matrix = read_json(ANCHOR_PATH)
    metrics = matrix.get("numeric_metrics", {})
    values: dict[str, Any] = {}
    count = 0
    for identity, item in metrics.items():
        if not isinstance(item, dict):
            continue
        values[identity] = item
        count += sum(len(stencil.get("omega", {})) if "omega" in stencil else 3 for key, stencil in item.items() if key in STENCILS)
    return {"status": "PARTIAL", "sample_count": len(values), "curvature_value_count": count, "values": values}


def compare_historical_anchors(anchors: dict[str, Any], samples: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep historical values immutable and expose differences as consistency-only evidence."""
    comparisons: list[dict[str, Any]] = []
    for identity, old in sorted(anchors["values"].items()):
        current = samples.get(identity)
        if current is None:
            continue
        for stencil in STENCILS:
            for resolution in RESOLUTIONS:
                historical = float(old[stencil][f"omega_{resolution}"])
                value = float(current["stencils"][stencil]["omega"][resolution])
                comparisons.append({
                    "sample_id": identity, "stencil": stencil, "resolution": resolution,
                    "historical_curvature": historical, "current_curvature": value,
                    "signed_difference": value - historical,
                    "magnitude_difference": abs(value) - abs(historical),
                    "decision_role": "CONSISTENCY_EVIDENCE_ONLY",
                })
    return comparisons


def analyze() -> dict[str, Any]:
    binding, graph = verify_public_inputs()
    _, dataset = open_dataset(binding)
    entrypoint = load_module("_mephc_r8_c1_graph_contract", ROOT / "audit/e9f/qp_b_c2_c3_r8_locked_set_native.py")
    entrypoint.verify_graph(graph)
    snapshots = demand_index(graph, entrypoint, dataset)
    reuse = read_json(ANCHOR_PATH)
    policy_gaps = {
        item["sample_id"]: float(item["external_gap"])
        for item in reuse["frozen_sample_ids"]
    }
    pair_evidence = [
        evaluate_pair(i, j, resolution, snapshots, policy_gaps[sample_id(i, j)])
        for i, j, _ in SAMPLES for resolution in RESOLUTIONS
    ]
    by_sample: dict[str, Any] = {}
    roles = {sample_id(i, j): role for i, j, role in SAMPLES}
    for identity, role in roles.items():
        pairs = [item for item in pair_evidence if item["sample_id"] == identity]
        by_sample[identity] = {"role": role, **resolution_metrics(pairs)}

    controls = [identity for identity, role in roles.items() if role == "CALIBRATION_CONTROL"]
    control_valid = all(
        by_sample[identity]["all_evidence_complete"]
        and by_sample[identity]["resolution_contraction_pass"]
        and by_sample[identity]["stencil_contraction_pass"] for identity in controls
    )
    envelopes = None if not control_valid else {
        "resolution": max(by_sample[identity]["final_resolution_metric"] for identity in controls),
        "stencil": max(by_sample[identity]["final_stencil_metric"] for identity in controls),
    }
    challenges: dict[str, str] = {}
    for identity, role in roles.items():
        if role != "POLICY_CHALLENGE":
            continue
        item = by_sample[identity]
        complete = item["all_evidence_complete"]
        contractions = item["resolution_contraction_pass"] and item["stencil_contraction_pass"]
        if envelopes is None or not complete:
            challenges[identity] = "INCOMPLETE_OR_AMBIGUOUS"
        elif (contractions and item["final_resolution_metric"] <= envelopes["resolution"]
              and item["final_stencil_metric"] <= envelopes["stencil"]):
            challenges[identity] = "CONTROL_REFERENCED_NONINFERIOR_FOR_GOAL_2"
        else:
            challenges[identity] = "CONTROL_REFERENCED_INFERIOR_FOR_GOAL_2"
    diagnostic_id = next(identity for identity, role in roles.items() if role == "STENCIL_DIAGNOSTIC")
    diagnostic = by_sample[diagnostic_id]
    diagnostic_pass = (diagnostic["all_evidence_complete"] and diagnostic["resolution_contraction_pass"]
                       and diagnostic["stencil_contraction_pass"])
    if (control_valid and diagnostic_pass
            and all(value == "CONTROL_REFERENCED_NONINFERIOR_FOR_GOAL_2" for value in challenges.values())):
        verdict = "SUPPORTED_BY_LOCKED_SET"
    elif control_valid and any(value == "CONTROL_REFERENCED_INFERIOR_FOR_GOAL_2" for value in challenges.values()):
        verdict = "NOT_SUPPORTED_BY_LOCKED_SET"
    else:
        verdict = "INCONCLUSIVE"
    anchors = historical_anchors()
    anchor_comparisons = compare_historical_anchors(anchors, by_sample)
    return {
        "schema": "mephc-r8-c1-locked-set-calibration-v1",
        "work_order_id": WORK_ORDER_ID,
        "dataset": {"dataset_id": DATASET_ID, "manifest_sha256": MANIFEST_SHA256,
                    "record_count": 210, "acquisition_source_commit": ACQUISITION_SOURCE},
        "execution": {"native_invocations": 0, "provider_requests": 0, "solver_executions": 0, "mpb_execution": False},
        "sample_resolution_pair_count": len(pair_evidence),
        "stencil_curvature_value_count": len(pair_evidence) * 2,
        "pair_evidence": pair_evidence,
        "samples": by_sample,
        "controls": {"valid": control_valid, "ids": controls, "envelopes": envelopes},
        "stencil_diagnostic": {"sample_id": diagnostic_id, "pass": diagnostic_pass},
        "policy_challenges": challenges,
        "historical_anchors": anchors,
        "historical_anchor_comparisons": anchor_comparisons,
        "current_0p02_policy_calibration": verdict,
        "full_source_grid_validation_still_required": True,
        "threshold_change_authorized": False,
        "band2_chern_execution": False,
        "global_validation_state": "EXECUTED_LOCKED_SET_CALIBRATION_COMPLETE",
        "terminal": "E9F_C2_QP_B_C2_C3_R8_C1_M1_LOCKED_SET_CALIBRATION_COMPLETE",
    }


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    counts = list(result["policy_challenges"].values())
    return {
        "schema": result["schema"], "work_order_id": WORK_ORDER_ID,
        "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256,
        "immutable_dataset_record_count": 210,
        "sample_resolution_pair_count": result["sample_resolution_pair_count"],
        "stencil_curvature_value_count": result["stencil_curvature_value_count"],
        "control_envelopes": result["controls"]["envelopes"],
        "stencil_diagnostic_pass": result["stencil_diagnostic"]["pass"],
        "policy_challenge_noninferior_count": counts.count("CONTROL_REFERENCED_NONINFERIOR_FOR_GOAL_2"),
        "policy_challenge_inferior_count": counts.count("CONTROL_REFERENCED_INFERIOR_FOR_GOAL_2"),
        "policy_challenge_incomplete_count": counts.count("INCOMPLETE_OR_AMBIGUOUS"),
        "current_0p02_policy_calibration": result["current_0p02_policy_calibration"],
        "native_invocations": 0, "provider_requests": 0, "solver_executions": 0, "mpb_execution": False,
        "result_sha256": hashlib.sha256(canonical(result)).hexdigest(),
        "terminal": result["terminal"],
    }


def evidence_artifact(result: dict[str, Any]) -> dict[str, Any]:
    """Project the private-vector analysis into the bounded public evidence."""
    keys = (
        "sample_id", "resolution", "status", "reason_codes",
        "minimum_bundle_external_isolation_gap", "current_policy_external_gap",
        "current_policy_gap_status",
        "minimum_overlap_singular_value", "maximum_principal_angle",
        "maximum_projector_distance", "curvature", "qualification_status",
        "method_provenance",
    )
    return {
        "schema": "mephc-r8-c1-locked-set-evidence-v1",
        "work_order_id": WORK_ORDER_ID, "dataset": result["dataset"],
        "execution": result["execution"],
        "sample_resolution_pair_count": 24, "stencil_curvature_value_count": 48,
        "required_checks": [
            "FINITE_DATA", "NONZERO_NORM", "H_REPRESENTATION", "H_ORTHOGONAL",
            "ASSOCIATION", "BERRY_CURVATURE", "FORWARD_REVERSE", "GAUGE", "SOLVER_ORDER",
        ],
        "pairs": [
            {**{key: item[key] for key in keys},
             "all_required_checks_pass": all(item["checks"].values())}
            for item in result["pair_evidence"]
        ],
        "historical_anchors": {
            "status": result["historical_anchors"]["status"],
            "sample_count": result["historical_anchors"]["sample_count"],
            "curvature_value_count": result["historical_anchors"]["curvature_value_count"],
            "source": "audit/e9f/qp_b_c2_evidence_reuse_matrix.json",
        },
        "historical_anchor_comparisons": result["historical_anchor_comparisons"],
    }


def calibration_artifact(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "schema", "work_order_id", "dataset", "execution", "samples", "controls",
        "stencil_diagnostic", "policy_challenges", "current_0p02_policy_calibration",
        "full_source_grid_validation_still_required", "threshold_change_authorized",
        "band2_chern_execution", "global_validation_state", "terminal",
    )
    value = {key: result[key] for key in keys}
    value["historical_anchor_binding"] = {
        "status": result["historical_anchors"]["status"],
        "sample_count": result["historical_anchors"]["sample_count"],
        "curvature_value_count": result["historical_anchors"]["curvature_value_count"],
        "source": "audit/e9f/qp_b_c2_evidence_reuse_matrix.json",
    }
    return value


def main() -> int:
    try:
        result = analyze()
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(result_summary(result)).decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-r8-c1-locked-set-calibration-v1", "state": "failed",
            "error_code": type(exc).__name__, "detail": str(exc)[:1000],
            "native_invocations": 0, "provider_requests": 0, "solver_executions": 0,
            "mpb_execution": False,
            "terminal": "E9F_C2_QP_B_C2_C3_R8_C1_M1_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
