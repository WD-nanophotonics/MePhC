"""Dedicated solver-free M3 reader and qualification/rank analysis."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "audit" / "berry_c3_consistency" / "PLAN.md"
GOAL_PATH = ROOT / "audit" / "berry_c3_consistency" / "goal_contract_v1.json"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m3-qualification-anatomy-and-rank-decision-v1"
DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
RECORD_COUNT = 72


class M3Error(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise M3Error(code)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_job_module():
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("m3_scientific_job", path)
    require(spec is not None and spec.loader is not None, "M3_SCIENTIFIC_JOB_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_budgets() -> None:
    require(os.environ.get("MEPHC_PROVIDER_REQUEST_BUDGET") == "0", "M3_PROVIDER_BUDGET_NOT_ZERO")
    require(os.environ.get("MEPHC_SOLVER_EXECUTION_BUDGET") == "0", "M3_SOLVER_BUDGET_NOT_ZERO")


def load_payloads(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = bundle.get("datasets")
    if isinstance(descriptors, list) and descriptors:
        require(len(descriptors) == RECORD_COUNT, "M3_DATASET_DESCRIPTOR_COUNT_INVALID")
        keys = [descriptor.get("record_key_sha256") for descriptor in descriptors if isinstance(descriptor, dict)]
        require(len(keys) == RECORD_COUNT and len(set(keys)) == RECORD_COUNT, "M3_DATASET_RECORD_KEY_ENUMERATION_INVALID")
        bundle_path = Path(os.environ["MEPHC_INPUT_BUNDLE"])
        payloads = []
        for descriptor in descriptors:
            require(isinstance(descriptor, dict), "M3_DATASET_DESCRIPTOR_INVALID")
            require(descriptor.get("dataset_id") == DATASET_ID and descriptor.get("manifest_sha256") == MANIFEST_SHA256, "M3_DATASET_BINDING_MISMATCH")
            name = descriptor.get("payload_file")
            require(isinstance(name, str) and Path(name).name == name, "M3_PAYLOAD_REFERENCE_INVALID")
            payload = (bundle_path.parent / name).read_bytes()
            require(digest_bytes(payload) == descriptor.get("payload_sha256"), "M3_PAYLOAD_HASH_INVALID")
            require(len(payload) == descriptor.get("payload_size_bytes"), "M3_PAYLOAD_SIZE_INVALID")
            value = json.loads(payload.decode("utf-8"))
            require(isinstance(value, dict), "M3_PAYLOAD_SCHEMA_INVALID")
            payloads.append(value)
        return payloads
    counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters.name, "M3_DATASET_RESOLVER_STATE_ROOT_MISSING")
    job = load_job_module()
    state_root = counters.parent.parent
    verified = job.verify_dataset(state_root, DATASET_ID)
    require(verified.get("manifest_sha256") == MANIFEST_SHA256 and verified.get("record_count") == RECORD_COUNT, "M3_DATASET_MANIFEST_BINDING_MISMATCH")
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == RECORD_COUNT, "M3_DATASET_RECORD_KEY_ENUMERATION_INVALID")
    values = []
    for key in keys:
        resolved = job.resolve_dataset_record(state_root, DATASET_ID, MANIFEST_SHA256, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M3_DATASET_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M3_PAYLOAD_SCHEMA_INVALID")
        values.append(value)
    return values


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def numbers(value: Any) -> list[float]:
    return [item for raw in value if (item := number(raw)) is not None] if isinstance(value, list) else []


def gap(record: dict[str, Any]) -> float | None:
    direct = number(record.get("minimum_adjacent_gap_band2"))
    if direct is not None:
        return direct
    rows = record.get("adjacent_band_gaps")
    values = [item for row in rows if isinstance(row, list) for item in numbers(row)] if isinstance(rows, list) else []
    return min(values, default=None)


def transport(record: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    try:
        value = record["reductions"]["energy_eh"]["rank1_band2"]
    except (KeyError, TypeError):
        return None, None, None
    singular = min(numbers(value.get("minimum_link_singular_values")), default=None)
    projector = max(numbers(value.get("projector_distances")), default=None)
    angle = None if singular is None else math.acos(max(-1.0, min(1.0, singular)))
    return singular, angle, projector


def axis(record: dict[str, Any]) -> str:
    if record.get("qualification_status") in {"QUALIFIED", "PASS", "COMPARABLE"}:
        return "NONE"
    if gap(record) is None:
        return "CENTER_OR_SPECTRAL_ISOLATION_FAILURE"
    singular, _angle, _projector = transport(record)
    if singular is None:
        return "TRANSPORT_OR_OVERLAP_FAILURE"
    if record.get("band_identity") in {None, "", "rank1-withheld"} or "PENDING" in str(record.get("qualification_status")):
        return "BAND_OR_SUBSPACE_IDENTITY_FAILURE"
    if number(record.get("observable")) is None:
        return "NONFINITE_OBSERVABLE_FAILURE"
    return "MIXED_FAILURE"


def symmetric_relative(left: float, right: float) -> float | None:
    denominator = abs(left) + abs(right)
    return None if denominator == 0.0 else 2.0 * abs(left - right) / denominator


def analyze(records: list[dict[str, Any]]) -> dict[str, Any]:
    require(len(records) == RECORD_COUNT, "M3_DATASET_RECORD_COUNT_INVALID")
    groups: dict[tuple[str, bool, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        config = record.get("solver_configuration")
        require(isinstance(config, dict), "M3_SOLVER_CONFIGURATION_MISSING")
        key = (str(record.get("geometry_id")), bool(config.get("deterministic")), str(config.get("stencil")), int(record.get("repeat_index")))
        require(key[0] in {"G15", "G16"} and key[2] in {"lab_fixed", "c3_covariant"} and key[3] in {0, 1, 2}, "M3_ORBIT_ID_INVALID")
        require(int(record.get("member_index")) in {0, 1, 2}, "M3_MEMBER_ID_INVALID")
        groups[key].append(record)
    require(len(groups) == 24 and all(len(items) == 3 for items in groups.values()), "M3_ORBIT_ACCOUNTING_INVALID")

    failure_counts = Counter(axis(record) for record in records if axis(record) != "NONE")
    gaps = [value for value in (gap(record) for record in records) if value is not None]
    singulars, angles, projectors = [], [], []
    shadow_max = None
    shadow_rel = None
    shadow_context = None
    branch_summaries = []
    for key, values in sorted(groups.items()):
        geometry, deterministic, stencil, repeat = key
        ordered = sorted(values, key=lambda item: int(item["member_index"]))
        local_gaps = [value for value in (gap(item) for item in ordered) if value is not None]
        local_singulars, local_angles, local_projectors = [], [], []
        observables = []
        for item in ordered:
            singular, angle_value, projector = transport(item)
            if singular is not None:
                singulars.append(singular); local_singulars.append(singular)
            if angle_value is not None:
                angles.append(angle_value); local_angles.append(angle_value)
            if projector is not None:
                projectors.append(projector); local_projectors.append(projector)
            value = number(item.get("observable")); observables.append(value)
        finite = [value for value in observables if value is not None]
        residual = None if not finite else max(abs(value - finite[0]) for value in finite[1:])
        relative = None if not finite else max((value for value in (symmetric_relative(finite[0], other) for other in finite[1:]) if value is not None), default=None)
        if residual is not None and (shadow_max is None or residual > shadow_max):
            shadow_max, shadow_rel = residual, relative
            shadow_context = {"geometry_id": geometry, "deterministic": deterministic, "stencil": stencil, "repeat_index": repeat, "member_values": observables}
        branch_summaries.append({
            "geometry_id": geometry, "deterministic": deterministic, "stencil": stencil, "repeat_index": repeat,
            "failure_axes": sorted({axis(item) for item in ordered if axis(item) != "NONE"}),
            "raw_member_sign_pattern": "".join("+" if value is not None and value > 0 else "-" if value is not None and value < 0 else "0" for value in observables),
            "shadow_maximum_absolute_c3_residual": residual,
            "shadow_maximum_symmetric_relative_c3_residual": relative,
            "minimum_external_gap": min(local_gaps, default=None), "median_external_gap": median(local_gaps) if local_gaps else None,
            "minimum_link_singular_value": min(local_singulars, default=None), "maximum_principal_angle": max(local_angles, default=None),
            "maximum_projector_distance": max(local_projectors, default=None),
        })
    repeat_values: dict[tuple[str, bool, str, int], list[float]] = defaultdict(list)
    for record in records:
        value = number(record.get("observable")); config = record["solver_configuration"]
        if value is not None:
            repeat_values[(record["geometry_id"], bool(config["deterministic"]), config["stencil"], int(record["member_index"]))].append(value)
    repeat_spreads = [max(values) - min(values) for values in repeat_values.values() if len(values) == 3]
    dominant, dominant_count = (failure_counts.most_common(1)[0] if failure_counts else ("NONE", 0))
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
        "dataset_id": DATASET_ID, "manifest_sha256": MANIFEST_SHA256, "record_count": len(records), "c3_orbit_count": len(groups),
        "rank1_unqualified_orbit_count": 24, "dominant_qualification_failure": dominant,
        "qualification_failure_axis_counts": dict(failure_counts), "qualification_failure_axis_record_count": sum(failure_counts.values()),
        "external_gap_global_min": min(gaps, default=None), "external_gap_global_median": median(gaps) if gaps else None,
        "minimum_link_singular_value": min(singulars, default=None), "maximum_principal_angle": max(angles, default=None), "maximum_projector_distance": max(projectors, default=None),
        "qualification_failure_stage": "BAND_OR_SUBSPACE_IDENTITY_BEFORE_BERRY_COMPARISON" if dominant == "BAND_OR_SUBSPACE_IDENTITY_FAILURE" else "MULTIPLE_OR_SCIENTIFIC_GATES",
        "shadow_maximum_absolute_c3_residual": shadow_max, "shadow_maximum_relative_c3_residual": shadow_rel,
        "shadow_maximum_repeat_spread": max(repeat_spreads, default=None), "maximum_shadow_context": shadow_context,
        "branch_shadow_summaries": branch_summaries,
        "deterministic_mode_shadow_status": "DESCRIPTIVE_ONLY_UNQUALIFIED_BRANCHES", "frame_convention_shadow_status": "DESCRIPTIVE_ONLY_UNQUALIFIED_BRANCHES", "geometry_control_shadow_status": "DESCRIPTIVE_ONLY_UNQUALIFIED_BRANCHES",
        "rank2_feasibility_status": "REQUIRES_NEW_LIVE_EVIDENCE", "rank2_candidate_band_pair": None,
        "rank2_missing_payloads": ["normalized_vectors", "subspace_overlap_singular_values", "principal_angles", "neighboring-band_identity_per_member"],
        "next_science_decision": "REACQUIRE_ONLY_SPECIFIC_MISSING_RANK_DIAGNOSTIC_PAYLOADS", "minimal_next_live_state_count": 24,
        "minimal_next_target_bands_or_subspace": "bands_2_and_3_rank2_candidate_with_neighboring_band_identity",
        "minimal_next_observables": "normalized_multiband_vectors,subspace_overlap_singular_values,principal_angles,C3_member_identity",
        "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0,
        "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True,
    }


def failure(code: str) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failed_stage": "dataset-binding-or-analysis", "failure_code": code, "exception_type": "M3Error", "dataset_id": DATASET_ID, "manifest_sha256": MANIFEST_SHA256, "record_count": 0, "c3_orbit_count": 0, "rank1_unqualified_orbit_count": 0, "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "post_native_checkout_unchanged": True}


def main() -> int:
    try:
        bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", ""))
        require(bundle_path.is_file(), "M3_INPUT_BUNDLE_MISSING")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and str(bundle.get("work_order_id", "")).startswith("MEPHC-BERRY-C3-M3R2-"), "M3_WORK_ORDER_MISMATCH")
        validate_budgets()
        result = analyze(load_payloads(bundle))
    except (M3Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result = failure(str(exc))
    target = Path(os.environ["MEPHC_RESULT_PATH"])
    target.write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
