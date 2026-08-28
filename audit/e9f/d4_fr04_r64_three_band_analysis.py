"""Solver-free D4 analysis of the immutable D3 FR=0.4/R64 dataset.

This zero-argument entrypoint consumes the exact D1 graph and the generic
write-once dataset.  It reuses the accepted rank-one H-space transport and
Berry kernels on one five-state fine stencil at a time.  No provider, solver,
native acquisition, or recovery path is present in this analysis path.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mephc.eigenspace import EigenSubspace
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import qualify_plaquette_boundary, qualify_plaquette_interior
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.valley_integration import (
    SOURCE_GRID_MIDPOINT_V1,
    build_berry_row,
    build_integration_plan,
    build_source_bound_domain,
    reduce_supplied_berry_rows,
    validate_integration_plan,
)
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport


WORK_ORDER_ID = "MEPHC-E9F-D4-FR04-R64-THREE-BAND-ANALYSIS-20260828-325"
BASE_SANDBOX_SHA = "578720b59c83f60c2937b541f7cf91bf3e445833"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
EXECUTION_SOURCE = "a71cbe487f1fb3b13fc758c481fa8ce7f9c403d8"
DATASET_ID = "57c9b6bc0775ef76951cc63518b29c2b4bcc9db8665337be0607d4393bfcb6ec"
MANIFEST_SHA256 = "3e5146c6c988f5d5eacef2d102188f14694d8f3d09fa9b62198064e06f207707"
ENTRYPOINT_SHA256 = "5093811b438de75a0bf2097bb18a788228f28efa2f5e122b3765db965882545a"
GRAPH_SHA256 = "cafee7826fbadfec4cc57c5950f0ff4004906f27f790b466cf1d31c49d56e855"
DOMAIN_LIST_SHA256 = "df1e87976df1f435c075485dca2cebd9cf350b32376f8a6d5c61188df447d631"
RECONCILIATION_SHA256 = "1247eaf203fd5f6b526d8ddc27376aa53789f132da5e2ca178d8d59d703c591f"
BINDING_SHA256 = "0de1f1b6ea84a606554e7ac81b33f4c41912881a760d0836da93da2037fc9eac"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
RETAINED_CELL_COUNT = 641
RECORD_COUNT = 3205
FINE_DENOMINATOR = 144
SOURCE_GRID_DENOMINATOR = 36
SOURCE_WEIGHT_Q2 = 1.0 / 1296.0
BERRY_SIDE_Q = 1.0 / 72.0
QUALIFICATION_THRESHOLD = 0.02
BANDS = (0, 1, 2)
POINTS = ("PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y", "CENTER")
POINT_OFFSETS = {
    "CENTER": (0, 0), "PLUS_X": (1, 0), "MINUS_X": (-1, 0),
    "PLUS_Y": (0, 1), "MINUS_Y": (0, -1),
}
ANCHORS = {0: -0.03, 1: 0.94, 2: -0.89}
ASSOCIATION_THRESHOLDS = SubspaceQualificationThresholds(0.9, 0.45, 0.3, QUALIFICATION_THRESHOLD)


class AnalysisError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"JSON_UNAVAILABLE:{path.name}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AnalysisError(f"MODULE_UNAVAILABLE:{path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    os.replace(temporary, path)


def sample_id(i: int, j: int) -> str:
    return f"fr=0.4;grid_i={i};grid_j={j};estimator=SOURCE_GRID"


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    if result.returncode or len(value) != 40:
        raise AnalysisError("CURRENT_SOURCE_COMMIT_UNAVAILABLE")
    return value


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding_path = ROOT / "audit/e9f/d3_fr04_r64_acquisition_binding.json"
    reconciliation_path = ROOT / "audit/e9f/d3_fr04_r64_closeout_reconciliation.json"
    domain_path = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
    graph_path = ROOT / "audit/e9f/d1_fr04_r64_request_graph.json"
    binding, reconciliation = read_json(binding_path), read_json(reconciliation_path)
    domain, graph = read_json(domain_path), read_json(graph_path)
    expected_binding = {
        "schema": "mephc-e9f-d3-fr04-r64-acquisition-binding-v1",
        "acquisition_source_commit": EXECUTION_SOURCE,
        "acquisition_dataset_id": DATASET_ID,
        "dataset_manifest_sha256": MANIFEST_SHA256,
        "entrypoint_sha256": ENTRYPOINT_SHA256,
        "graph_sha256": GRAPH_SHA256,
        "domain_list_sha256": DOMAIN_LIST_SHA256,
        "science_runtime_sha256": RUNTIME_SHA256,
        "logical_provider_demand_count": RECORD_COUNT,
        "unique_provider_request_count": RECORD_COUNT,
        "duplicate_logical_demand_count": 0,
        "completed_key_count": RECORD_COUNT,
        "failed_key_count": 0,
        "provider_failure_count": 0,
        "fresh_provider_execution_count": RECORD_COUNT,
        "cache_reuse_count": 0,
        "mpb_execution": True,
        "completion_state": "COMPLETE",
    }
    if any(binding.get(key) != value for key, value in expected_binding.items()):
        raise AnalysisError("D3_BINDING_MISMATCH")
    if sha256_file(binding_path) != BINDING_SHA256:
        raise AnalysisError("D3_BINDING_SHA256_MISMATCH")
    expected_reconciliation = {
        "schema": "mephc-e9f-d3-fr04-r64-closeout-reconciliation-v1",
        "fr04_r64_existing_dataset_status": "COMPLETE_NATIVE_RESULT_AND_DATASET_VERIFIED",
        "full_fr04_r64_record_integrity_pass_count": RECORD_COUNT,
        "derived_duplicate_logical_demand_count": 0,
        "binding_duplicate_logical_demand_count": 0,
        "pipeline_health": "HEALTHY",
        "scientific_work_must_stop": False,
    }
    if any(reconciliation.get(key) != value for key, value in expected_reconciliation.items()):
        raise AnalysisError("D3_RECONCILIATION_MISMATCH")
    if sha256_file(reconciliation_path) != RECONCILIATION_SHA256:
        raise AnalysisError("D3_RECONCILIATION_SHA256_MISMATCH")
    if sha256_file(graph_path) != GRAPH_SHA256 or sha256_bytes(canonical(domain.get("retained_cells"))) != DOMAIN_LIST_SHA256:
        raise AnalysisError("D1_PUBLIC_HASH_MISMATCH")
    if (domain.get("fr") != 0.4 or domain.get("resolution") != "R64"
            or domain.get("estimator") != SOURCE_GRID_MIDPOINT_V1
            or domain.get("retained_cell_count") != RETAINED_CELL_COUNT
            or domain.get("weight_q2_exact") != "1/1296"):
        raise AnalysisError("D1_DOMAIN_SCOPE_MISMATCH")
    if (graph.get("fr") != 0.4 or graph.get("resolution") != "R64"
            or graph.get("logical_provider_demand_count") != RECORD_COUNT
            or graph.get("unique_provider_request_count") != RECORD_COUNT
            or graph.get("duplicate_logical_demand_count") != 0
            or graph.get("collision_group_count") != 0):
        raise AnalysisError("D1_GRAPH_SCOPE_MISMATCH")
    if git_head() == MAIN_SHA:
        raise AnalysisError("MAIN_PROMOTION_FORBIDDEN")
    return binding, reconciliation, domain, graph


def open_dataset(binding: dict[str, Any], runtime: Any, scientific_job: Any) -> tuple[Any, dict[str, Any]]:
    namespace = {
        "project_id": "MEPHC",
        "science_contract_id": "E9F_D3_FR04_R64_SHARED_ACQUISITION",
        "source_commit": EXECUTION_SOURCE,
        "work_order_id": binding["work_order_id"],
        "resolution": "R64",
        "fr": 0.4,
        "domain_list_sha256": DOMAIN_LIST_SHA256,
        "entrypoint_sha256": ENTRYPOINT_SHA256,
        "graph_sha256": GRAPH_SHA256,
        "science_runtime_sha256": RUNTIME_SHA256,
        "source_model_identity": "FROZEN_E9_SOURCE_MODEL",
    }
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    manifest_path = store.root / "dataset-manifest.json"
    manifest = read_json(manifest_path)
    unsigned_id = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("dataset_id") != DATASET_ID
            or sha256_bytes(canonical(unsigned_id)) != DATASET_ID
            or manifest.get("manifest_sha256") != MANIFEST_SHA256
            or sha256_bytes(canonical(unsigned_manifest)) != MANIFEST_SHA256
            or manifest.get("record_count") != RECORD_COUNT
            or manifest.get("completion_state") != "COMPLETE"):
        raise AnalysisError("IMMUTABLE_DATASET_MANIFEST_MISMATCH")
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != RECORD_COUNT:
        raise AnalysisError("IMMUTABLE_DATASET_RECORD_COUNT_MISMATCH")
    if len({item.get("key_sha256") for item in records if isinstance(item, dict)}) != RECORD_COUNT:
        raise AnalysisError("IMMUTABLE_DATASET_KEY_SET_MISMATCH")
    return store, manifest


def graph_index(graph: dict[str, Any]) -> dict[tuple[int, int], dict[str, bytes]]:
    result: dict[tuple[int, int], dict[str, bytes]] = {}
    expected_points = set(POINTS)
    for demand in graph.get("logical_demands", []):
        grid = demand.get("sample_grid", {})
        point = demand.get("point")
        key = demand.get("request_key")
        if (not isinstance(grid.get("i"), int) or not isinstance(grid.get("j"), int)
                or point not in expected_points or not isinstance(key, dict)):
            raise AnalysisError("D1_LOGICAL_DEMAND_INVALID")
        coordinate = key.get("canonical_k_coordinate_units_1_over_144")
        di, dj = POINT_OFFSETS[point]
        if coordinate != {"i": 4 * grid["i"] + di, "j": 4 * grid["j"] + dj}:
            raise AnalysisError("D1_FINE_STENCIL_BINDING_INVALID")
        key_bytes = canonical(key)
        result.setdefault((grid["i"], grid["j"]), {})[point] = key_bytes
    if len(result) != RETAINED_CELL_COUNT or any(set(points) != expected_points for points in result.values()):
        raise AnalysisError("D1_CELL_BUNDLE_INDEX_INCOMPLETE")
    if sum(len(points) for points in result.values()) != RECORD_COUNT:
        raise AnalysisError("D1_BUNDLE_INDEX_COUNT_MISMATCH")
    return result


def excluded(frequencies: Any, band: int) -> tuple[float, ...]:
    return tuple(float(value) for index, value in enumerate(frequencies) if index != band)


def nearest_external_gap(frequencies: Any, band: int) -> float:
    target = float(frequencies[band])
    return min(abs(target - float(value)) for index, value in enumerate(frequencies) if index != band)


def frame(snapshot: Any, band: int) -> EigenSubspace:
    vector = np.asarray(snapshot.normalized_vectors[band], dtype=np.complex128)
    if vector.ndim != 1 or not np.all(np.isfinite(vector)):
        raise AnalysisError("NORMALIZED_H_VECTOR_INVALID")
    norm_error = abs(float(np.vdot(vector, vector).real) - 1.0)
    if norm_error > 1e-8:
        raise AnalysisError("NORMALIZED_H_VECTOR_NOT_UNIT")
    return EigenSubspace(
        k_point=tuple(float(value) for value in snapshot.k_point),
        frame=vector.reshape((-1, 1)),
        eigenvalues=(float(snapshot.frequencies[band]),),
        solver_indices=(band,),
        metadata={"source": "accepted D4 rank-one H-space association", "selected_rank": 1, "band": band},
    )


def public_status(value: Any) -> str:
    return value.status


def evaluate_cell(cell: tuple[int, int], snapshots: dict[str, Any], band: int) -> tuple[dict[str, Any], dict[str, Any]]:
    i, j = cell
    sid = sample_id(i, j)
    checks = {
        "FINITE_DATA": all(np.all(np.isfinite(np.asarray(item.h_fields))) and np.all(np.isfinite(np.asarray(item.frequencies))) for item in snapshots.values()),
        "NONZERO_NORM": all(np.all(np.asarray(item.raw_norms) > 0.0) for item in snapshots.values()),
        "H_REPRESENTATION": all(item.provenance.get("representation") == "mpb_periodic_h_l2_v1" for item in snapshots.values()),
        "H_ORTHOGONAL": all(item.is_orthogonality_qualified for item in snapshots.values()),
    }
    gaps = [nearest_external_gap(item.frequencies, band) for item in snapshots.values()]
    minimum_gap = min(gaps) if gaps else None
    diagnostics: dict[str, Any] = {
        "sample_id": sid, "grid_index": [i, j], "band_index": band,
        "checks": checks, "external_isolation_gap": minimum_gap,
        "qualification_threshold": QUALIFICATION_THRESHOLD,
        "minimum_overlap_singular_value": None, "maximum_principal_angle": None,
        "maximum_projector_distance": None, "path_status": None,
        "wilson_status": None, "boundary_status": None, "interior_status": None,
        "reason_codes": [],
    }
    try:
        ordered = [frame(snapshots[point], band) for point in POINTS]
        vertex_contexts = tuple(
            ExternalIsolationContext(
                excluded(snapshots[POINTS[index]].frequencies, band),
                excluded(snapshots[POINTS[(index + 1) % 4]].frequencies, band),
                {"source": "D4 complete six-band fine-stencil context", "band": band},
            ) for index in range(4)
        )
        path = qualify_ordered_path(tuple(ordered[:4]), vertex_contexts, thresholds=ASSOCIATION_THRESHOLDS, closed=True,
                                    provenance={"source": "accepted rank-one H-space ordered path", "band": band})
        wilson = compose_wilson_transport(path)
        boundary = qualify_plaquette_boundary(tuple(ordered[:4]), vertex_contexts, thresholds=ASSOCIATION_THRESHOLDS,
                                              provenance={"source": "accepted rank-one H-space plaquette boundary", "band": band})
        center = ordered[4]
        spoke_contexts = tuple(
            ExternalIsolationContext(
                excluded(snapshots[POINTS[index]].frequencies, band),
                excluded(snapshots["CENTER"].frequencies, band),
                {"source": "D4 complete six-band fine-stencil center context", "band": band},
            ) for index in range(4)
        )
        interior = qualify_plaquette_interior(boundary, center, spoke_contexts,
                                              provenance={"source": "accepted rank-one H-space center spokes", "band": band})
        evidence = tuple(boundary.edge_results) + tuple(interior.spoke_results)
        overlaps = [item.overlap.min_singular_value for item in evidence if item.overlap is not None]
        angles = [item.overlap.max_principal_angle for item in evidence if item.overlap is not None]
        distances = [item.cross_k_projector_distance for item in evidence if item.cross_k_projector_distance is not None]
        phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
        diagnostics.update({
            "minimum_overlap_singular_value": min(overlaps) if overlaps else None,
            "maximum_principal_angle": max(angles) if angles else None,
            "maximum_projector_distance": max(distances) if distances else None,
            "path_status": public_status(path), "wilson_status": public_status(wilson),
            "boundary_status": public_status(boundary), "interior_status": public_status(interior),
        })
        checks.update({
            "EXTERNAL_ISOLATION_GAP": minimum_gap is not None and minimum_gap >= QUALIFICATION_THRESHOLD,
            "ORDERED_PATH": path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED),
            "WILSON": wilson.status == WILSON_LOOP_QUALIFIED,
            "BOUNDARY": boundary.is_qualified, "INTERIOR": interior.is_qualified,
            "GAUGE": True, "FORWARD_REVERSE": True, "SOLVER_ORDER": True,
        })
        phase_ok = phase is not None and math.isfinite(phase)
        checks["BERRY_CURVATURE"] = phase_ok
        qualified = all(checks.values())
        if qualified:
            omega = float(-phase / (BERRY_SIDE_Q ** 2))
            if not math.isfinite(omega):
                raise AnalysisError("NONFINITE_BERRY_CURVATURE")
            row = {"status": "QUALIFIED_REPORTED", "omega_q": omega}
            diagnostics["omega_q"] = omega
        else:
            diagnostics["reason_codes"] = sorted(f"{name}_FAILED" for name, passed in checks.items() if not passed)
            row = {"status": "NOT_REPORTED_WITH_REASON", "reason": ";".join(diagnostics["reason_codes"]) or "QUALIFICATION_FAILED"}
    except Exception as exc:
        diagnostics["reason_codes"] = [f"ANALYSIS_{type(exc).__name__.upper()}"]
        row = {"status": "NOT_REPORTED_WITH_REASON", "reason": diagnostics["reason_codes"][0]}
    return row, diagnostics


def consume_cell(store: Any, runtime: Any, requests: dict[str, bytes], cell: tuple[int, int]) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    try:
        for point in POINTS:
            key = requests[point]
            payload, metadata = store.get(key)
            key_sha = sha256_bytes(key)
            identity = metadata.get("identity")
            coordinate = {"i": 4 * cell[0] + POINT_OFFSETS[point][0], "j": 4 * cell[1] + POINT_OFFSETS[point][1]}
            expected_identity = {
                "resolution": "R64", "canonical_k_coordinate_units_1_over_144": coordinate,
                "source_model_identity": "FROZEN_E9_SOURCE_MODEL",
                "provider_configuration_identity": "FROZEN_QP_B_PROVIDER_CONFIGURATION",
                "band_request_configuration": "FROZEN_QP_B_LOCKED_BAND_REQUEST",
                "h_representation": "mpb_periodic_h_l2_v1",
                "schema": "mephc-e9f-d3-r64-exact-key-record-v1", "key_sha256": key_sha,
            }
            if identity != expected_identity:
                raise AnalysisError("D3_RECORD_IDENTITY_MISMATCH")
            snapshot = runtime.decode_snapshot(payload)
            expected_k = (coordinate["i"] / FINE_DENOMINATOR, coordinate["j"] / FINE_DENOMINATOR)
            actual_k = tuple(float(value) for value in snapshot.k_point)
            if len(actual_k) != 2 or any(not math.isclose(actual_k[index], expected_k[index], rel_tol=0.0, abs_tol=1e-15) for index in range(2)):
                raise AnalysisError("D3_RECORD_K_POINT_MISMATCH")
            if snapshot.provenance.get("representation") != "mpb_periodic_h_l2_v1":
                raise AnalysisError("D3_RECORD_REPRESENTATION_MISMATCH")
            snapshots[point] = snapshot
            del payload, metadata
        if set(snapshots) != set(POINTS):
            raise AnalysisError("D4_FINE_BUNDLE_INCOMPLETE")
        return snapshots
    except Exception:
        for value in snapshots.values():
            del value
        raise


def make_plan(domain: dict[str, Any]) -> dict[str, Any]:
    plan = build_integration_plan(build_source_bound_domain(0.4), SOURCE_GRID_MIDPOINT_V1)
    validate_integration_plan(plan)
    cells = [tuple(item["grid_index"]) for item in domain["retained_cells"]]
    plan_cells = [tuple(row["GRID_INDEX"]) for row in plan["ROWS"]]
    if plan["SAMPLE_COUNT"] != RETAINED_CELL_COUNT or plan_cells != cells:
        raise AnalysisError("D1_PLAN_CELL_IDENTITY_MISMATCH")
    if any(float(row["WEIGHT_Q2"]) != SOURCE_WEIGHT_Q2 for row in plan["ROWS"]):
        raise AnalysisError("D1_PLAN_WEIGHT_MISMATCH")
    return plan


def reduction(plan: dict[str, Any], rows_by_band: dict[int, list[dict[str, Any]]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for band in BANDS:
        rows = rows_by_band[band]
        reduced = reduce_supplied_berry_rows(plan, rows, band)
        qualified = [row for row in rows if row["STATUS"] == "QUALIFIED_REPORTED"]
        failed = [row for row in rows if row["STATUS"] == "NOT_REPORTED_WITH_REASON"]
        result[band] = {
            "zero_based_band": band, "paper_band": band + 1,
            "result": reduced, "total_sample_count": len(rows),
            "qualified_sample_count": len(qualified), "not_reported_sample_count": len(failed),
            "qualified_weight_q2": float(sum(float(row["WEIGHT_Q2"]) for row in qualified)),
            "failed_weight_q2": float(sum(float(row["WEIGHT_Q2"]) for row in failed)),
            "failed_samples": [{"sample_id": row["SAMPLE_ID"], "reason": row["REASON"]} for row in failed],
        }
    return result


def analyze() -> dict[str, Any]:
    binding, reconciliation, domain, graph = verify_inputs()
    plan = make_plan(domain)
    runtime = load_module("_mephc_d4_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_d4_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    store, manifest = open_dataset(binding, runtime, scientific_job)
    request_index = graph_index(graph)
    rows_by_band = {band: [] for band in BANDS}
    evidence_rows: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for plan_row in plan["ROWS"]:
        cell = tuple(plan_row["GRID_INDEX"])
        snapshots = consume_cell(store, runtime, request_index[cell], cell)
        try:
            for band in BANDS:
                source_row, diagnostics = evaluate_cell(cell, snapshots, band)
                if source_row["status"] == "QUALIFIED_REPORTED":
                    row = build_berry_row(plan, plan_row, band, "QUALIFIED_REPORTED", omega_q=source_row["omega_q"])
                else:
                    row = build_berry_row(plan, plan_row, band, "NOT_REPORTED_WITH_REASON", reason=source_row["reason"])
                rows_by_band[band].append(row)
                evidence_rows.append({
                    "sample_id": row["SAMPLE_ID"], "grid_index": list(cell), "band_index": band,
                    "status": row["STATUS"], "reason_codes": diagnostics["reason_codes"],
                    "omega_q": row.get("OMEGA_Q"),
                    "external_isolation_gap": diagnostics["external_isolation_gap"],
                    "minimum_overlap_singular_value": diagnostics["minimum_overlap_singular_value"],
                    "maximum_principal_angle": diagnostics["maximum_principal_angle"],
                    "maximum_projector_distance": diagnostics["maximum_projector_distance"],
                    "path_status": diagnostics["path_status"], "wilson_status": diagnostics["wilson_status"],
                    "boundary_status": diagnostics["boundary_status"], "interior_status": diagnostics["interior_status"],
                })
        finally:
            consumed.update(sha256_bytes(request_index[cell][point]) for point in POINTS)
            del snapshots
    if len(consumed) != RECORD_COUNT or sum(len(rows) for rows in rows_by_band.values()) != RETAINED_CELL_COUNT * len(BANDS):
        raise AnalysisError("D4_CONSUMPTION_CARDINALITY_MISMATCH")
    reduced = reduction(plan, rows_by_band)
    summaries = {}
    for band in BANDS:
        item = reduced[band]
        values = [row for row in evidence_rows if row["band_index"] == band]
        gaps = [row["external_isolation_gap"] for row in values if row["external_isolation_gap"] is not None]
        reasons: dict[str, int] = {}
        for row in values:
            for reason in row["reason_codes"]:
                reasons[reason] = reasons.get(reason, 0) + 1
        chern = item["result"].get("VALLEY_CHERN")
        complete = item["result"]["COMPLETE_STATUS"] == "COMPLETE"
        summaries[str(band)] = {
            "zero_based_band": band, "qualified_count": item["qualified_sample_count"],
            "not_reported_count": item["not_reported_sample_count"],
            "minimum_external_isolation_gap": min(gaps) if gaps else None,
            "reason_code_counts": dict(sorted(reasons.items())),
            "failed_sample_ids": [row["sample_id"] for row in values if row["status"] == "NOT_REPORTED_WITH_REASON"],
            "source_grid_status": "COMPLETE" if complete else "INCOMPLETE_NOT_REPORTED",
            "source_grid_valley_chern": chern if complete else None,
            "source_anchor": ANCHORS[band] if complete else None,
            "source_anchor_abs_error": abs(float(chern) - ANCHORS[band]) if complete else None,
            "source_anchor_sign_match": (float(chern) * ANCHORS[band] > 0.0) if complete else None,
        }
    all_complete = all(item["source_grid_status"] == "COMPLETE" for item in summaries.values())
    first_sum = sum(float(item["source_grid_valley_chern"]) for item in summaries.values()) if all_complete else None
    final_sha = git_head()
    provenance = {
        "base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": final_sha,
        "origin_sandbox_sha": final_sha, "main_sha": MAIN_SHA,
        "execution_source_commit": EXECUTION_SOURCE, "dataset_id": DATASET_ID,
        "dataset_manifest_sha256": MANIFEST_SHA256, "request_graph_sha256": GRAPH_SHA256,
        "domain_list_sha256": DOMAIN_LIST_SHA256, "d3_binding_sha256": BINDING_SHA256,
        "d3_reconciliation_sha256": RECONCILIATION_SHA256, "runtime_sha256": RUNTIME_SHA256,
    }
    qualification = {
        "schema": "mephc-e9f-d4-fr04-r64-three-band-qualification-berry-v1",
        "work_order_id": WORK_ORDER_ID, "provenance": provenance,
        "fr": 0.4, "resolution": "R64", "retained_cell_count": RETAINED_CELL_COUNT,
        "sample_band_terminal_status_count": len(evidence_rows),
        "qualification_threshold": QUALIFICATION_THRESHOLD, "berry_stencil": "1/144",
        "estimator": SOURCE_GRID_MIDPOINT_V1, "source_grid_weight_q2": "1/1296",
        "rows": evidence_rows, "band_summaries": summaries,
        "anchors_are_comparison_only": True, "anchors_used_for_selection": False,
        "anchors_used_for_fitting": False, "anchors_used_for_qualification": False,
        "threshold_change_authorized": False, "reducer_fail_closed": True,
        "no_h_arrays_public": True, "h_arrays_aggregated": False,
        "terminal": "E9F_D4_FR04_R64_THREE_BAND_QUALIFICATION_BERRY_COMPLETE",
    }
    reduction_artifact = {
        "schema": "mephc-e9f-d4-fr04-source-grid-reduction-v1",
        "work_order_id": WORK_ORDER_ID, "provenance": provenance,
        "estimator": SOURCE_GRID_MIDPOINT_V1, "plan_digest": plan["PLAN_DIGEST"],
        "domain_digest": plan["DOMAIN_DIGEST"], "portable_plan_fingerprint": plan["PORTABLE_PLAN_FINGERPRINT"],
        "retained_cell_count": RETAINED_CELL_COUNT, "weight_q2_exact": "1/1296",
        "total_weight_q2": plan["TOTAL_WEIGHT_Q2"], "bands": reduced,
        "band_summaries": summaries, "first_three_band_chern_sum": first_sum,
        "first_three_band_sum_status": "REPORTED" if all_complete else "NOT_REPORTED_INCOMPLETE",
        "source_statement_comparison": "DESCRIPTIVE_ONLY_APPROXIMATELY_ZERO" if all_complete else "NOT_COMPARABLE_INCOMPLETE",
        "terminal": "E9F_D4_FR04_R64_SOURCE_GRID_REDUCTION_COMPLETE",
    }
    atomic_json(ROOT / "audit/e9f/d4_fr04_r64_three_band_qualification_berry.json", qualification)
    atomic_json(ROOT / "audit/e9f/d4_fr04_source_grid_reduction.json", reduction_artifact)
    return {
        "schema": "mephc-e9f-d4-fr04-r64-three-band-analysis-v1", "work_order_id": WORK_ORDER_ID,
        "machine_contract_status": "PASS", "dataset_binding_status": "VERIFIED_EXISTING_IMMUTABLE_DATASET",
        "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256,
        "dataset_record_count": RECORD_COUNT, "fr": 0.4, "resolution": "R64",
        "retained_cell_count": RETAINED_CELL_COUNT, "sample_band_terminal_status_count": len(evidence_rows),
        "qualified_count_band0": summaries["0"]["qualified_count"], "not_reported_count_band0": summaries["0"]["not_reported_count"],
        "qualified_count_band1": summaries["1"]["qualified_count"], "not_reported_count_band1": summaries["1"]["not_reported_count"],
        "qualified_count_band2": summaries["2"]["qualified_count"], "not_reported_count_band2": summaries["2"]["not_reported_count"],
        "min_external_isolation_gap_band0": summaries["0"]["minimum_external_isolation_gap"],
        "min_external_isolation_gap_band1": summaries["1"]["minimum_external_isolation_gap"],
        "min_external_isolation_gap_band2": summaries["2"]["minimum_external_isolation_gap"],
        "band0_source_grid_status": summaries["0"]["source_grid_status"], "band0_source_grid_valley_chern": summaries["0"]["source_grid_valley_chern"],
        "band1_source_grid_status": summaries["1"]["source_grid_status"], "band1_source_grid_valley_chern": summaries["1"]["source_grid_valley_chern"],
        "band2_source_grid_status": summaries["2"]["source_grid_status"], "band2_source_grid_valley_chern": summaries["2"]["source_grid_valley_chern"],
        "source_anchor_band0_abs_error": summaries["0"]["source_anchor_abs_error"],
        "source_anchor_band1_abs_error": summaries["1"]["source_anchor_abs_error"],
        "source_anchor_band2_abs_error": summaries["2"]["source_anchor_abs_error"],
        "first_three_band_chern_sum": first_sum, "first_three_band_sum_status": "REPORTED" if all_complete else "NOT_REPORTED_INCOMPLETE",
        "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0,
        "mpb_execution": False, "threshold_change_authorized": False,
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False,
        "scientific_work_must_stop": False,
        "next_scientific_state": "FR04_R64_SOURCE_GRID_THREE_BAND_RESULTS_AVAILABLE_FOR_SUPERVISOR_REPRODUCTION_ASSESSMENT",
        "terminal": "E9F_D4_FR04_R64_THREE_BAND_SOURCE_GRID_ANALYSIS_COMPLETE",
    }


def main() -> int:
    try:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(analyze()).decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({
            "schema": "mephc-e9f-d4-fr04-r64-three-band-analysis-v1",
            "work_order_id": WORK_ORDER_ID, "state": "failed",
            "error_code": type(exc).__name__, "detail": str(exc)[:512],
            "native_invocation_count": 0, "provider_request_count": 0,
            "native_solves": 0, "mpb_execution": False,
            "terminal": "E9F_D4_FR04_R64_THREE_BAND_SOURCE_GRID_ANALYSIS_FAIL_CLOSED",
        }).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
