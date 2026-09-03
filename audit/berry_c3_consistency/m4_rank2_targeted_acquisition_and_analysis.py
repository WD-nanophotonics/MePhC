"""Targeted M4 rank-2 diagnostic acquisition and solver-free analysis."""
from __future__ import annotations

import importlib.util
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
M2_ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m2_live_c3_acquisition_and_reduction.py"
SOURCE_M3_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
SOURCE_M3_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m4-rank2-diagnostic-feasibility-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m4-rank2-diagnostic-live-state-dataset-v1"
TARGET_REPEAT = 1
TARGET_COUNT = 24
TRIPLET_COUNT = 8


class M4Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M4Error(f"{code}:{detail}" if detail else code)


def load_m2():
    spec = importlib.util.spec_from_file_location("m4_m2_runtime", M2_ENTRYPOINT)
    require(spec is not None and spec.loader is not None, "M4_M2_ENTRYPOINT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_source_records(m2: Any) -> list[dict[str, Any]]:
    counters = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
    require(counters.name, "M4_EXECUTION_COUNTERS_PATH_MISSING")
    scientific_job = m2._load_scientific_job()
    state_root = counters.parent.parent
    verified = scientific_job.verify_dataset(state_root, SOURCE_M3_DATASET_ID)
    require(verified.get("dataset_id") == SOURCE_M3_DATASET_ID, "M4_SOURCE_DATASET_ID_MISMATCH")
    require(verified.get("manifest_sha256") == SOURCE_M3_MANIFEST_SHA256, "M4_SOURCE_MANIFEST_MISMATCH")
    keys = verified.get("record_key_sha256")
    require(isinstance(keys, list) and len(keys) == len(set(keys)) == 72, "M4_SOURCE_RECORD_ENUMERATION_INVALID")
    records = []
    for key in keys:
        resolved = scientific_job.resolve_dataset_record(state_root, SOURCE_M3_DATASET_ID, SOURCE_M3_MANIFEST_SHA256, key)
        payload = resolved.get("payload")
        require(isinstance(payload, bytes), "M4_SOURCE_PAYLOAD_MISSING")
        value = json.loads(payload.decode("utf-8"))
        require(isinstance(value, dict), "M4_SOURCE_PAYLOAD_SCHEMA_INVALID")
        records.append(value)
    return records


def select_fixed_targets(records: Sequence[Mapping[str, Any]], plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Select the preregistered repeat-1 member of every branch cell."""
    selected_keys = {
        str(record.get("request_key_sha256"))
        for record in records
        if record.get("repeat_index") == TARGET_REPEAT
    }
    require(len(selected_keys) == TARGET_COUNT, "M4_TARGET_REPEAT_RECORD_COUNT_INVALID")
    requests = []
    for item in plan.get("live_requests", []):
        if item.get("repeat_index") == TARGET_REPEAT and item.get("request_key_sha256") in selected_keys:
            requests.append(dict(item))
    require(len(requests) == TARGET_COUNT, "M4_TARGET_PLAN_BINDING_COUNT_INVALID")
    cells: dict[tuple[str, bool, str], list[dict[str, Any]]] = defaultdict(list)
    for item in requests:
        semantic = item.get("semantic_identity")
        require(isinstance(semantic, dict), "M4_TARGET_SEMANTIC_MISSING")
        key = (str(semantic.get("geometry_id")), bool(semantic.get("solver_configuration", {}).get("deterministic")), str(semantic.get("solver_configuration", {}).get("stencil")))
        require(key[0] in {"G15", "G16"} and key[2] in {"lab_fixed", "c3_covariant"}, "M4_TARGET_BRANCH_INVALID")
        cells[key].append(item)
    require(set(cells) == {(geometry, deterministic, stencil) for geometry in ("G15", "G16") for deterministic in (False, True) for stencil in ("lab_fixed", "c3_covariant")}, "M4_TARGET_BRANCH_SET_INVALID")
    require(len(cells) == TRIPLET_COUNT and all(len(items) == 3 for items in cells.values()), "M4_TARGET_TRIPLET_ACCOUNTING_INVALID")
    for items in cells.values():
        require({item["semantic_identity"].get("member_index") for item in items} == {0, 1, 2}, "M4_TARGET_MEMBER_SET_INVALID")
    return sorted(requests, key=lambda item: (str(item["semantic_identity"]["geometry_id"]), bool(item["semantic_identity"]["solver_configuration"]["deterministic"]), str(item["semantic_identity"]["solver_configuration"]["stencil"]), int(item["semantic_identity"]["member_index"])))


def single_point_request(item: Mapping[str, Any]) -> dict[str, Any]:
    semantic = item["semantic_identity"]
    coordinate = semantic.get("public_coordinate")
    require(isinstance(coordinate, list) and len(coordinate) == 2, "M4_TARGET_COORDINATE_INVALID")
    return {
        "provider_symbol": "MPBLiveEnergySpectralProvider",
        "request_key_sha256": item["request_key_sha256"],
        "repeat_index": TARGET_REPEAT,
        "geometry_id": semantic["geometry_id"],
        "domain_id": semantic["domain_id"],
        "orbit_id": semantic["orbit_id"],
        "member_index": semantic["member_index"],
        "band_target": {"band_indices_zero_based": [0, 1, 2, 3], "vector_bands_zero_based": [1, 2]},
        "solver_configuration": semantic["solver_configuration"],
        "coordinate": coordinate,
    }


def encode_vector(value: Any) -> list[list[float]]:
    import numpy as np
    flat = np.asarray(value, dtype=np.complex128).reshape(-1)
    return [[float(item.real), float(item.imag)] for item in flat]


def decode_vectors(value: Any):
    import numpy as np
    require(isinstance(value, list) and len(value) == 2, "M4_VECTOR_PAYLOAD_INVALID")
    vectors = []
    for vector in value:
        require(isinstance(vector, list), "M4_VECTOR_PAYLOAD_INVALID")
        vectors.append(np.asarray([complex(pair[0], pair[1]) for pair in vector], dtype=np.complex128))
    return np.column_stack(vectors)


def record_from_snapshot(item: Mapping[str, Any], snapshot: Any, geometry_digest: str | None) -> dict[str, Any]:
    import numpy as np
    frequencies = np.asarray(snapshot.frequencies[:4], dtype=float)
    require(frequencies.shape == (4,) and np.isfinite(frequencies).all(), "M4_FREQUENCY_PAYLOAD_INVALID")
    vectors = [snapshot.normalized_vectors[index] for index in (1, 2)]
    semantic = item["semantic_identity"]
    return {
        "schema": "mephc-berry-c3-rank2-diagnostic-live-state-v1",
        "record_id": f"{item['request_key_sha256']}:r{TARGET_REPEAT}",
        "request_key_sha256": item["request_key_sha256"],
        "repeat_index": TARGET_REPEAT,
        "geometry_id": semantic["geometry_id"],
        "orbit_id": semantic["orbit_id"],
        "member_index": semantic["member_index"],
        "coordinate": semantic["public_coordinate"],
        "frame_convention": "LAB_FIXED" if semantic["solver_configuration"]["stencil"] == "lab_fixed" else "C3_COVARIANT",
        "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[int(semantic["member_index"])],
        "deterministic": bool(semantic["solver_configuration"]["deterministic"]),
        "solver_configuration": semantic["solver_configuration"],
        "geometry_digest": geometry_digest,
        "first_four_frequencies": frequencies.tolist(),
        "normalized_vectors_bands_2_3": [encode_vector(vector) for vector in vectors],
        "payload_scope": "bands_1_to_4_frequencies_and_normalized_bands_2_3",
        "source_m3_dataset_id": SOURCE_M3_DATASET_ID,
        "source_m3_manifest_sha256": SOURCE_M3_MANIFEST_SHA256,
    }


def acquire_targets(
    targets: Sequence[Mapping[str, Any]],
    provider_getter: Callable[[Mapping[str, Any]], Any],
    solve: Callable[[Any, Mapping[str, Any]], Any],
    counter: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    records = []
    for target in targets:
        semantic = target["semantic_identity"]
        try:
            provider = provider_getter(semantic)
            request = single_point_request(target)
            counter.consume_provider()
            counter.consume_solver()
            snapshot = solve(provider, request)
            records.append(record_from_snapshot(target, snapshot, None))
        except Exception as exc:
            return records, {
                "target_request_key_sha256": target.get("request_key_sha256"),
                "target_geometry_id": semantic.get("geometry_id"),
                "target_member_index": semantic.get("member_index"),
                "failure_code": getattr(exc, "code", type(exc).__name__),
                "exception_message": str(exc)[:512],
            }
    return records, None


def rank2_metrics(left: Any, right: Any) -> dict[str, Any]:
    import numpy as np
    overlap = left.conj().T @ right
    singular = np.linalg.svd(overlap, compute_uv=False)
    singular = np.asarray(singular, dtype=float)
    principal = float(math.acos(max(-1.0, min(1.0, float(np.min(singular))))))
    projector = float(math.sqrt(max(0.0, 4.0 - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2))))
    return {"overlap_singular_values": singular.tolist(), "minimum_overlap_singular_value": float(np.min(singular)), "maximum_principal_angle": principal, "projector_distance": projector}


def analyze_triplets(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    import numpy as np
    require(len(records) == TARGET_COUNT, "M4_RECORD_COUNT_INVALID")
    groups: dict[tuple[str, bool, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        require(record.get("repeat_index") == TARGET_REPEAT, "M4_REPEAT_IDENTITY_INVALID")
        groups[(str(record.get("geometry_id")), bool(record.get("deterministic")), str(record.get("frame_convention")))].append(record)
    require(len(groups) == TRIPLET_COUNT and all(len(items) == 3 for items in groups.values()), "M4_TRIPLET_ACCOUNTING_INVALID")
    triplets = []
    internal, external, singulars, angles, projectors = [], [], [], [], []
    closure_failures = 0
    for key, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: int(item["member_index"]))
        vectors = [decode_vectors(item["normalized_vectors_bands_2_3"]) for item in ordered]
        frequencies = [item["first_four_frequencies"] for item in ordered]
        edge_metrics = [rank2_metrics(vectors[index], vectors[(index + 1) % 3]) for index in range(3)]
        for metric in edge_metrics:
            singulars.append(metric["minimum_overlap_singular_value"]); angles.append(metric["maximum_principal_angle"]); projectors.append(metric["projector_distance"])
        pair_splitting = [abs(float(freq[2]) - float(freq[1])) for freq in frequencies]
        pair_external_gap = [min(abs(float(freq[1]) - float(freq[0])), abs(float(freq[3]) - float(freq[2]))) for freq in frequencies]
        internal.extend(pair_splitting); external.extend(pair_external_gap)
        closure = "DEFERRED_NO_EXPLICIT_C3_OPERATOR"
        closure_failures += 1
        triplets.append({
            "geometry_id": key[0], "deterministic": key[1], "frame_convention": key[2], "repeat_index": TARGET_REPEAT,
            "member_indices": [0, 1, 2], "pair_internal_splitting_min": min(pair_splitting), "pair_internal_splitting_max": max(pair_splitting),
            "external_pair_gap_min": min(pair_external_gap), "rank2_edge_metrics": edge_metrics,
            "c3_subspace_closure_status": closure,
        })
    return {
        "triplets": triplets, "pair_internal_splitting_min": min(internal), "pair_internal_splitting_max": max(internal),
        "external_pair_gap_min": min(external), "external_pair_gap_median": float(np.median(external)),
        "rank2_minimum_overlap_singular_value": min(singulars), "rank2_maximum_principal_angle": max(angles), "rank2_maximum_projector_distance": max(projectors),
        "c3_subspace_complete_triplet_count": TRIPLET_COUNT, "c3_subspace_closure_failure_count": closure_failures,
        "rank2_feasibility_status": "INSUFFICIENT_EVIDENCE", "next_science_decision": "INSUFFICIENT_EVIDENCE",
        "threshold_status": "THRESHOLD_DEFERRED",
    }


def failure(code: str, *, counts: Mapping[str, int] | None = None, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    counts = dict(counts or {})
    return {
        "schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "failure_code": code,
        "source_m3_dataset_id": SOURCE_M3_DATASET_ID, "target_state_count": counts.get("target", 0), "c3_triplet_count": 0,
        "native_invocation_count": 1, "provider_execution_count": counts.get("provider", 0), "solver_execution_count": counts.get("solver", 0),
        "dataset_record_count": counts.get("dataset", 0), "new_live_record_count": counts.get("dataset", 0), "failed_request_count": 1 if detail else 0,
        "failure_detail": detail, "post_native_checkout_unchanged": True,
    }


def main() -> int:
    result: dict[str, Any]
    counter = None
    try:
        bundle_path = Path(os.environ.get("MEPHC_INPUT_BUNDLE", ""))
        require(bundle_path.is_file(), "M4_INPUT_BUNDLE_MISSING")
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M4_WORK_ORDER_MISSING")
        m2 = load_m2()
        source_records = load_source_records(m2)
        plan = m2.derive_plan(m2.verify_m1_bundle())
        targets = select_fixed_targets(source_records, plan)
        counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
        scientific_job = m2._load_scientific_job()
        counter = scientific_job.BudgetCounter(TARGET_COUNT, TARGET_COUNT)
        pilot = object.__new__(m2.ProductionPilot)
        pilot._providers = {}; pilot._geometry_digests = {}
        records, failed = acquire_targets(
            targets,
            lambda semantic: m2.ProductionPilot._provider(pilot, semantic),
            lambda provider, request: m2.invoke_production_request(provider, request),
            counter,
        )
        counts = {"target": len(records), "provider": counter.provider_count, "solver": counter.solver_count, "dataset": 0}
        if failed:
            result = failure("M4_PROVIDER_OR_SOLVER_FAILURE", counts=counts, detail=failed)
        else:
            store = scientific_job.ImmutableDatasetStore(counters_path.parent.parent, {
                "goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"],
                "source_m3_dataset_id": SOURCE_M3_DATASET_ID, "record_schema": DATASET_SCHEMA,
                "target_policy": "fixed_repeat_1_eight_c3_triplets",
            })
            for record in records:
                key = m2.canonical({"request_key_sha256": record["request_key_sha256"], "repeat_index": TARGET_REPEAT})
                store.put(key, json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"), {
                    "request_key_sha256": record["request_key_sha256"], "repeat_index": TARGET_REPEAT,
                    "geometry_id": record["geometry_id"], "member_index": record["member_index"],
                })
            manifest = store.finalize(TARGET_COUNT, {"source_m3_dataset_id": SOURCE_M3_DATASET_ID, "source_m3_manifest_sha256": SOURCE_M3_MANIFEST_SHA256, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count})
            counts["dataset"] = TARGET_COUNT
            analysis = analyze_triplets(records)
            result = {
                "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS",
                "source_m3_dataset_id": SOURCE_M3_DATASET_ID, "target_state_count": TARGET_COUNT, "c3_triplet_count": TRIPLET_COUNT,
                "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count,
                "dataset_record_count": TARGET_COUNT, "new_live_record_count": TARGET_COUNT, "failed_request_count": 0,
                "dataset_id": manifest["dataset_id"], "manifest_sha256": manifest["manifest_sha256"], "candidate_band_pair": "bands_2_and_3",
                **analysis, "deterministic_mode_status": "DESCRIPTIVE_ALL_FIXED_REPEAT_1_BRANCHES", "frame_convention_status": "DESCRIPTIVE_ALL_FIXED_REPEAT_1_BRANCHES",
                "geometry_control_status": "DESCRIPTIVE_ALL_FIXED_REPEAT_1_BRANCHES", "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"), "post_native_checkout_unchanged": True,
            }
    except (M4Error, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        values = {"provider": getattr(counter, "provider_count", 0), "solver": getattr(counter, "solver_count", 0), "dataset": 0, "target": 0}
        result = failure(str(exc), counts=values)
    Path(os.environ["MEPHC_RESULT_PATH"]).write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
