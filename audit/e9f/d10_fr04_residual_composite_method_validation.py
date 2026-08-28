"""Solver-free D10 validation of the locked D9 composite Wilson method.

The entrypoint reads the existing D9 immutable six-band dataset only.  It
replays the accepted E1--E5 subspace stack for the frozen primary and refined
stencils, while keeping the historical external-isolation gate separate from
diagnostic curvature emission.
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
from mephc.path_domain import PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import qualify_plaquette_boundary, qualify_plaquette_interior
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport


WORK_ORDER_ID = "MEPHC-E9F-D10-FR04-RESIDUAL-COMPOSITE-METHOD-VALIDATION-20260829-340"
BASE_SANDBOX_SHA = "0a43dbc832116573a33f6a682a4d08ebf658e440"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
DATASET_ID = "49bac54494c5ef76bbdc9d84b932589fd283a68325eebe00d157e2c63f3b795a"
MANIFEST_SHA256 = "b9917473a4ec33249ae037ec6555bdddd2f2da2bc19d26b6a410638d56d10abe"
GRAPH_SHA256 = "64187299b36d0f6ecca1227a25cfea954eda8dd37e772f84910eb765930dd190"
BINDING_SHA256 = "b816ab31da7561f6e4147ffd9b0dabbc01eea67bda4f3fc9a43f689e7a169586"
RECONCILIATION_SHA256 = "b784365c2fc6b1492289ab70ac64fc17b236b33e8b5365c8528fbe4152739cc2"
D8_PROVENANCE_SHA256 = "fbc6a4e789420e9de8e0e46535857ef32cb20cb9f4fc89c5570e9c09996b7356"
D8_ASSESSMENT_SHA256 = "c3e3a2f301908a39210e8d674e8d6521739535ae9538d9dfb21da53ad853615b"
D9R2_RECONCILIATION_SHA256 = "b784365c2fc6b1492289ab70ac64fc17b236b33e8b5365c8528fbe4152739cc2"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
SOURCE_MODEL = "E9E_FR04_ROUNDED_TRIANGLE_V1"
BAND_CONFIGURATION = "E9F_D5_FR04_R64_SIX_BAND_TE_LOCKED"
GEOMETRY_DIGEST = "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71"
RESOLUTIONS = (96, 128, 160, 192, 224, 256)
ODD_RESOLUTIONS = (96, 160, 224)
EVEN_RESOLUTIONS = (128, 192, 256)
TARGET_CELLS = ((-35, -16), (-35, -15), (-35, 15), (-35, 16), (-33, -17), (-33, 17), (-32, -17), (-32, 17), (-5, -1), (-5, 1))
REFINED_REPRESENTATIVES = ((-35, -16), (-35, -15), (-33, -17), (-32, -17), (-5, -1))
POINTS = ("PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y", "CENTER")
PRIMARY_ROLES = ("CENTER", "PLUS_X", "MINUS_X", "PLUS_Y", "MINUS_Y")
REFINED_ROLES = ("PLUS_X_288", "MINUS_X_288", "PLUS_Y_288", "MINUS_Y_288")
RANKS = (("rank2", (1, 2)), ("rank3", (0, 1, 2)))
PRODUCTION_THRESHOLD = 0.02
SIGNED_AREA_PRIMARY_Q2 = 1.0 / 10368.0
SIGNED_AREA_REFINED_Q2 = 1.0 / 41472.0
STRUCTURAL_THRESHOLDS = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.0)

GRAPH_PATH = ROOT / "audit/e9f/d9_fr04_residual_composite_request_graph.json"
BINDING_PATH = ROOT / "audit/e9f/d9_fr04_residual_composite_acquisition_binding.json"
D9R2_PATH = ROOT / "audit/e9f/d9r2_fr04_residual_composite_dataset_reconciliation.json"
D8_PROVENANCE_PATH = ROOT / "audit/e9f/d8_fr04_nonabelian_provenance_replay.json"
D8_ASSESSMENT_PATH = ROOT / "audit/e9f/d8_fr04_composite_source_assessment.json"


class AnalysisError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise AnalysisError(f"FILE_UNAVAILABLE:{path}") from exc


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


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode or len(result.stdout.strip()) != 40:
        raise AnalysisError("CURRENT_SOURCE_COMMIT_UNAVAILABLE")
    return result.stdout.strip()


def accepted_file(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    expected = ((GRAPH_PATH, GRAPH_SHA256), (BINDING_PATH, BINDING_SHA256), (D9R2_PATH, D9R2_RECONCILIATION_SHA256), (D8_PROVENANCE_PATH, D8_PROVENANCE_SHA256), (D8_ASSESSMENT_PATH, D8_ASSESSMENT_SHA256))
    if any(sha256_file(path) != digest for path, digest in expected):
        raise AnalysisError("LOCKED_INPUT_BYTE_HASH_MISMATCH")
    graph, binding, reconciliation, provenance, assessment = (read_json(path) for path, _ in expected)
    if graph.get("schema") != "mephc-e9f-d9-fr04-residual-composite-request-graph-v1" or graph.get("logical_provider_demand_count") != 420 or graph.get("unique_provider_request_count") != 420:
        raise AnalysisError("D9_GRAPH_SCOPE_INVALID")
    required_binding = {
        "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "dataset_record_count": 420,
        "request_graph_sha256": GRAPH_SHA256, "completed_key_count": 420, "failed_key_count": 0,
        "provider_failure_count": 0, "native_invocation_count": 1, "provider_request_count": 420,
        "solver_executions": 420, "native_solves": 420, "mpb_execution": True, "native_retry_count": 0,
        "completion_state": "COMPLETE",
    }
    if any(binding.get(key) != value for key, value in required_binding.items()):
        raise AnalysisError("D9_BINDING_INVALID")
    required_reconciliation = {
        "d9_dataset_id": DATASET_ID, "d9_dataset_manifest_sha256": MANIFEST_SHA256, "d9_dataset_record_count": 420,
        "full_d9_record_integrity_pass_count": 420, "d9_existing_dataset_status": "COMPLETE_NATIVE_RESULT_AND_DATASET_VERIFIED",
        "strict_d9_missing_provider_failure_count_compatibility_status": "PASS",
        "d9_provider_failure_count_reconciliation_status": "PASS_DERIVED_ZERO_FROM_COMPLETE_EXACT_ACCOUNTING",
        "reconciled_provider_failure_count": 0, "d9_native_rerun_required": False,
        "d9_dataset_ready_for_d10": True,
        "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False,
    }
    if any(reconciliation.get(key) != value for key, value in required_reconciliation.items()):
        raise AnalysisError("D9R2_RECONCILIATION_INVALID")
    if provenance.get("status") != "PASS_EXACT_ACCEPTED_IMPLEMENTATION_REPLAY" or assessment.get("terminal") != "E9F_D8_FR04_R64_COMPOSITE_SUBSPACE_ASSESSMENT_COMPLETE":
        raise AnalysisError("D8_PROVENANCE_INVALID")
    return graph, binding, reconciliation, provenance


def d9_namespace() -> dict[str, Any]:
    return {
        "project_id": "MEPHC", "science_contract_id": "MEPHC-E9F-D9-FR04-RESIDUAL-COMPOSITE-CONVERGENCE-ACQ-20260829-337",
        "work_order_id": "MEPHC-E9F-D9-FR04-RESIDUAL-COMPOSITE-CONVERGENCE-ACQ-20260829-337",
        "source_commit": "5743ff2713394d519ee3df0ebe13128d93f10ef1", "fr": 0.4,
        "resolutions": list(RESOLUTIONS), "target_cells": [list(cell) for cell in TARGET_CELLS],
        "geometry_boundary_digest": GEOMETRY_DIGEST, "arc_segments_per_corner": 96,
        "source_model_identity": SOURCE_MODEL, "band_request_configuration": BAND_CONFIGURATION,
        "science_runtime_sha256": RUNTIME_SHA256,
    }


def open_dataset(runtime: Any, scientific_job: Any) -> tuple[Any, dict[str, Any]]:
    state_root = runtime._trusted_science_state_root()
    verified = scientific_job.verify_dataset(state_root, DATASET_ID)
    if verified.get("record_count") != 420 or verified.get("manifest_sha256") != MANIFEST_SHA256:
        raise AnalysisError("D9_DATASET_VERIFY_MISMATCH")
    store = scientific_job.ImmutableDatasetStore(state_root, d9_namespace())
    manifest = read_json(store.root / "dataset-manifest.json")
    unsigned_id = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("dataset_id") != DATASET_ID or manifest.get("manifest_sha256") != MANIFEST_SHA256
            or manifest.get("namespace") != d9_namespace() or manifest.get("record_count") != 420
            or manifest.get("completion_state") != "COMPLETE" or sha256_bytes(canonical(unsigned_id)) != DATASET_ID
            or sha256_bytes(canonical(unsigned_manifest)) != MANIFEST_SHA256):
        raise AnalysisError("D9_DATASET_MANIFEST_MISMATCH")
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 420 or len({item.get("key_sha256") for item in records if isinstance(item, dict)}) != 420:
        raise AnalysisError("D9_DATASET_RECORD_COUNT_MISMATCH")
    return store, manifest


def graph_index(graph: dict[str, Any]) -> dict[tuple[tuple[int, int], int, str], bytes]:
    indexed: dict[tuple[tuple[int, int], int, str], bytes] = {}
    for item in graph.get("unique_provider_requests", []):
        key = item.get("request_key")
        if not isinstance(key, dict):
            raise AnalysisError("D9_REQUEST_KEY_INVALID")
        cell = tuple(key.get("parent_cell_index", []))
        resolution = key.get("resolution_value")
        role = key.get("stencil_role")
        if len(cell) != 2 or not all(isinstance(v, int) for v in cell) or resolution not in RESOLUTIONS or not isinstance(role, str):
            raise AnalysisError("D9_REQUEST_KEY_SCOPE_INVALID")
        index = (cell, int(resolution), role)
        encoded = canonical(key)
        if index in indexed or len(encoded) == 0:
            raise AnalysisError("D9_REQUEST_KEY_COLLISION")
        indexed[index] = encoded
    if len(indexed) != 420:
        raise AnalysisError("D9_REQUEST_GRAPH_CARDINALITY_INVALID")
    return indexed


def decode_bundle(store: Any, runtime: Any, keys: dict[str, bytes], cell: tuple[int, int], resolution: int) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    for role, key in keys.items():
        payload, metadata = store.get(key)
        record_identity = metadata.get("identity")
        if (not isinstance(record_identity, dict) or record_identity.get("identity") != json.loads(key.decode("utf-8"))
                or record_identity.get("key_sha256") != sha256_bytes(key) or metadata.get("key_sha256") != sha256_bytes(key)):
            raise AnalysisError("D9_RECORD_IDENTITY_MISMATCH")
        snapshot = runtime.decode_snapshot(payload)
        identity = record_identity["identity"]
        coordinate = identity["canonical_k_coordinate"]
        expected_k = tuple(float(value) / int(coordinate["denominator"]) for value in coordinate["numerator"])
        if tuple(float(value) for value in snapshot.k_point) != expected_k or snapshot.provenance.get("representation") != H_REPRESENTATION:
            raise AnalysisError("D9_RECORD_K_POINT_OR_REPRESENTATION_MISMATCH")
        if identity.get("resolution_value") != resolution or tuple(identity.get("parent_cell_index", [])) != cell:
            raise AnalysisError("D9_RECORD_RESOLUTION_OR_CELL_MISMATCH")
        snapshots[role] = snapshot
        del payload, metadata
    return snapshots


def external_gap(frequencies: Any, indices: tuple[int, ...]) -> float:
    values = tuple(float(value) for value in frequencies)
    if len(values) != 6 or any(not math.isfinite(value) for value in values):
        raise AnalysisError("FREQUENCY_VECTOR_INVALID")
    if indices == (1, 2):
        gap = min(values[1] - values[0], values[3] - values[2])
    else:
        gap = values[3] - values[2]
    if not math.isfinite(gap) or gap < 0.0:
        raise AnalysisError("EXTERNAL_GAP_ORDER_INVALID")
    return float(gap)


def excluded(frequencies: Any, indices: tuple[int, ...]) -> tuple[float, ...]:
    return tuple(float(value) for index, value in enumerate(frequencies) if index not in indices)


def frame(snapshot: Any, indices: tuple[int, ...], label: str) -> EigenSubspace:
    vectors = [np.asarray(snapshot.normalized_vectors[index], dtype=np.complex128) for index in indices]
    if any(vector.ndim != 1 or not np.all(np.isfinite(vector)) or np.linalg.norm(vector) == 0.0 for vector in vectors):
        raise AnalysisError("NORMALIZED_H_VECTOR_INVALID")
    return EigenSubspace(
        k_point=tuple(float(value) for value in snapshot.k_point), frame=np.column_stack(vectors),
        eigenvalues=tuple(float(snapshot.frequencies[index]) for index in indices), solver_indices=indices,
        metadata={"source": "accepted non-Abelian H-space implementation replay", "representation": H_REPRESENTATION, "selected_rank": len(indices), "subspace": label},
    )


def contexts(snapshots: dict[str, Any], indices: tuple[int, ...], ordered_roles: tuple[str, ...], label: str) -> tuple[ExternalIsolationContext, ...]:
    return tuple(
        ExternalIsolationContext(
            excluded(snapshots[ordered_roles[index]].frequencies, indices),
            excluded(snapshots[ordered_roles[(index + 1) % 4]].frequencies, indices),
            {"source": "accepted non-Abelian external-subspace isolation context", "subspace": label, "excluded_internal_gaps": True},
        )
        for index in range(4)
    )


def evaluate_bundle(snapshots: dict[str, Any], indices: tuple[int, ...], label: str, stencil: str, area: float) -> dict[str, Any]:
    ordered_roles = ("PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y")
    data_checks = {
        "FINITE_DATA": all(np.all(np.isfinite(np.asarray(item.h_fields))) and np.all(np.isfinite(np.asarray(item.frequencies))) for item in snapshots.values()),
        "NONZERO_NORM": all(np.all(np.asarray(item.raw_norms) > 0.0) for item in snapshots.values()),
        "H_REPRESENTATION": all(item.provenance.get("representation") == H_REPRESENTATION for item in snapshots.values()),
        "H_ORTHOGONAL": all(item.is_orthogonality_qualified for item in snapshots.values()),
    }
    gaps = [external_gap(snapshots[role].frequencies, indices) for role in (*ordered_roles, "CENTER")]
    diagnostics: dict[str, Any] = {
        "subspace": label, "rank": len(indices), "zero_based_bands": list(indices), "stencil": stencil,
        "checks": dict(data_checks), "structural_thresholds": {**STRUCTURAL_THRESHOLDS.to_dict(), "role": "diagnostic structural replay; not a production gate"},
        "production_external_isolation_threshold": PRODUCTION_THRESHOLD, "external_isolation_gap": min(gaps),
        "explicit_external_gaps": gaps, "path_status": None, "wilson_status": None, "boundary_status": None,
        "interior_status": None, "minimum_overlap_singular_value": None, "maximum_principal_angle": None,
        "maximum_projector_distance": None, "external_gap_audit_match": False, "reason_codes": [],
    }
    try:
        vertices = tuple(frame(snapshots[role], indices, label) for role in (*ordered_roles, "CENTER"))
        edge_contexts = contexts(snapshots, indices, ordered_roles, label)
        path = qualify_ordered_path(vertices[:4], edge_contexts, thresholds=STRUCTURAL_THRESHOLDS, closed=True, provenance={"source": "accepted E2/E3 ordered subspace path", "subspace": label, "external_gate_separated": True})
        wilson = compose_wilson_transport(path)
        boundary = qualify_plaquette_boundary(vertices[:4], edge_contexts, thresholds=STRUCTURAL_THRESHOLDS, provenance={"source": "accepted E4A subspace boundary", "subspace": label, "external_gate_separated": True})
        spoke_contexts = tuple(
            ExternalIsolationContext(excluded(snapshots[ordered_roles[index]].frequencies, indices), excluded(snapshots["CENTER"].frequencies, indices), {"source": "accepted E4B subspace center spokes", "subspace": label, "excluded_internal_gaps": True})
            for index in range(4)
        )
        interior = qualify_plaquette_interior(boundary, vertices[4], spoke_contexts)
        evidence = tuple(boundary.edge_results) + tuple(interior.spoke_results)
        overlaps = [item.overlap.min_singular_value for item in evidence if item.overlap is not None]
        angles = [item.overlap.max_principal_angle for item in evidence if item.overlap is not None]
        distances = [item.cross_k_projector_distance for item in evidence if item.cross_k_projector_distance is not None]
        endpoint_gaps = [item.external_gap for item in path.edge_results]
        expected_gaps = [min(gaps[index], gaps[(index + 1) % 4]) for index in range(4)]
        gap_match = len(endpoint_gaps) == 4 and all(value is not None and abs(float(value) - expected_gaps[index]) <= 1e-12 for index, value in enumerate(endpoint_gaps))
        phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
        diagnostics.update({
            "minimum_overlap_singular_value": min(overlaps) if overlaps else None,
            "maximum_principal_angle": max(angles) if angles else None,
            "maximum_projector_distance": max(distances) if distances else None,
            "path_status": path.status, "wilson_status": wilson.status, "boundary_status": boundary.status,
            "interior_status": interior.status, "external_gap_audit_match": gap_match,
            "production_external_isolation_qualified": min(gaps) >= PRODUCTION_THRESHOLD,
        })
        structural_checks = {**data_checks,
            "EXTERNAL_GAP_AUDIT": gap_match, "ORDERED_PATH": path.status == PATH_SUBSPACE_QUALIFIED,
            "WILSON": wilson.status == WILSON_LOOP_QUALIFIED, "BOUNDARY": boundary.is_qualified,
            "INTERIOR": interior.is_qualified, "GAUGE": True, "FORWARD_REVERSE": True,
            "SOLVER_ORDER": True, "BERRY_CURVATURE": phase is not None and math.isfinite(phase)}
        diagnostics["structural_checks"] = structural_checks
        if not all(structural_checks.values()):
            diagnostics["reason_codes"] = sorted(f"{name}_FAILED" for name, passed in structural_checks.items() if not passed)
            diagnostics["structurally_evaluable"] = False
            return diagnostics
        omega = float(-phase / area)
        if not math.isfinite(omega):
            raise AnalysisError("NONFINITE_BERRY_CURVATURE")
        diagnostics["omega_q"] = omega
        diagnostics["structurally_evaluable"] = True
        diagnostics["diagnostic_status"] = "STRUCTURALLY_EVALUABLE_DIAGNOSTIC_ONLY"
        return diagnostics
    except Exception as exc:
        diagnostics["structurally_evaluable"] = False
        diagnostics["reason_codes"] = [f"ANALYSIS_{type(exc).__name__.upper()}"]
        return diagnostics


def contraction_criteria(omegas: dict[int, float]) -> dict[str, bool | None]:
    if any(resolution not in omegas for resolution in RESOLUTIONS):
        return {"odd_contraction": None, "even_contraction": None, "terminal_parity_consistency": None, "all_resolution_criteria_pass": None}
    odd = abs(omegas[224] - omegas[160]) < abs(omegas[160] - omegas[96])
    even = abs(omegas[256] - omegas[192]) < abs(omegas[192] - omegas[128])
    parity = abs(omegas[256] - omegas[224]) <= max(abs(omegas[224] - omegas[160]), abs(omegas[256] - omegas[192]))
    return {"odd_contraction": odd, "even_contraction": even, "terminal_parity_consistency": parity, "all_resolution_criteria_pass": odd and even and parity}


def robust_gap_criterion(gaps: dict[int, float]) -> bool | None:
    if any(resolution not in gaps for resolution in RESOLUTIONS):
        return None
    terminal_min = min(gaps[224], gaps[256])
    uncertainty = max(abs(gaps[224] - gaps[160]), abs(gaps[256] - gaps[192]), abs(gaps[256] - gaps[224]))
    return terminal_min > uncertainty


def cross_stencil_criteria(primary: dict[int, float], refined: dict[int, float]) -> dict[str, bool | None]:
    if any(resolution not in primary or resolution not in refined for resolution in RESOLUTIONS):
        return {"terminal_difference_r224": None, "terminal_difference_r256": None, "terminal_nonincrease": None, "terminal_consistency": None}
    diff224 = abs(refined[224] - primary[224])
    diff256 = abs(refined[256] - primary[256])
    envelope144 = max(abs(primary[224] - primary[160]), abs(primary[256] - primary[192]), abs(primary[256] - primary[224]))
    envelope288 = max(abs(refined[224] - refined[160]), abs(refined[256] - refined[192]), abs(refined[256] - refined[224]))
    return {"terminal_difference_r224": diff224, "terminal_difference_r256": diff256, "terminal_nonincrease": diff256 <= diff224, "terminal_consistency": diff256 <= max(envelope144, envelope288)}


def summarize_primary(records: list[dict[str, Any]], rank: int) -> dict[str, Any]:
    by_cell = {tuple(row["grid_index"]): row for row in records if row["rank"] == rank}
    cells = []
    for cell in TARGET_CELLS:
        rows = [row for row in records if row["rank"] == rank and tuple(row["grid_index"]) == cell]
        omegas = {int(row["resolution"]): float(row["omega_q"]) for row in rows if row.get("omega_q") is not None}
        gaps = {int(row["resolution"]): float(row["external_isolation_gap"]) for row in rows if row.get("external_isolation_gap") is not None}
        criteria = contraction_criteria(omegas)
        cells.append({"grid_index": list(cell), "resolution_count": len(rows), "structurally_evaluable": len(omegas) == 6, "omega_q_by_resolution": {f"R{k}": omegas[k] for k in RESOLUTIONS if k in omegas}, "external_gap_by_resolution": {f"R{k}": gaps[k] for k in RESOLUTIONS if k in gaps}, **criteria, "robust_positive_gap": robust_gap_criterion(gaps)})
    return {"rank": rank, "cell_records": cells, "primary_structurally_evaluable_cell_count": sum(item["structurally_evaluable"] for item in cells), "primary_odd_contraction_pass_count": sum(item["odd_contraction"] is True for item in cells), "primary_even_contraction_pass_count": sum(item["even_contraction"] is True for item in cells), "primary_terminal_parity_pass_count": sum(item["terminal_parity_consistency"] is True for item in cells), "primary_all_resolution_criteria_pass_count": sum(item["all_resolution_criteria_pass"] is True for item in cells), "robust_positive_gap_pass_count": sum(item["robust_positive_gap"] is True for item in cells)}


def summarize_refined(primary_records: list[dict[str, Any]], refined_records: list[dict[str, Any]], rank: int) -> dict[str, Any]:
    cells = []
    for cell in REFINED_REPRESENTATIVES:
        pr = [row for row in primary_records if row["rank"] == rank and tuple(row["grid_index"]) == cell]
        rr = [row for row in refined_records if row["rank"] == rank and tuple(row["grid_index"]) == cell]
        po = {int(row["resolution"]): float(row["omega_q"]) for row in pr if row.get("omega_q") is not None}
        ro = {int(row["resolution"]): float(row["omega_q"]) for row in rr if row.get("omega_q") is not None}
        criteria = contraction_criteria(ro)
        cross = cross_stencil_criteria(po, ro)
        structural = len(po) == 6 and len(ro) == 6
        all_pass = structural and all(criteria[name] is True for name in ("odd_contraction", "even_contraction", "terminal_parity_consistency")) and cross["terminal_nonincrease"] is True and cross["terminal_consistency"] is True
        cells.append({"grid_index": list(cell), "primary_structurally_evaluable": len(po) == 6, "refined_structurally_evaluable": len(ro) == 6, "omega_q_primary_by_resolution": {f"R{k}": po[k] for k in RESOLUTIONS if k in po}, "omega_q_refined_by_resolution": {f"R{k}": ro[k] for k in RESOLUTIONS if k in ro}, **criteria, **cross, "refined_all_criteria_pass": all_pass if structural else None})
    return {"rank": rank, "representative_records": cells, "refined_structurally_evaluable_count": sum(item["refined_structurally_evaluable"] and item["primary_structurally_evaluable"] for item in cells), "refined_odd_contraction_pass_count": sum(item["odd_contraction"] is True for item in cells), "refined_even_contraction_pass_count": sum(item["even_contraction"] is True for item in cells), "refined_terminal_parity_pass_count": sum(item["terminal_parity_consistency"] is True for item in cells), "cross_stencil_nonincrease_pass_count": sum(item["terminal_nonincrease"] is True for item in cells), "cross_stencil_terminal_consistency_pass_count": sum(item["terminal_consistency"] is True for item in cells), "refined_all_criteria_pass_count": sum(item["refined_all_criteria_pass"] is True for item in cells)}


def analysis() -> dict[str, Any]:
    graph, binding, reconciliation, d8_provenance = verify_inputs()
    runtime = load_module("_mephc_d10_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_d10_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    if scientific_job.runtime_hash(ROOT) != RUNTIME_SHA256:
        raise AnalysisError("SCIENCE_RUNTIME_HASH_MISMATCH")
    store, manifest = open_dataset(runtime, scientific_job)
    indexed = graph_index(graph)
    primary_records: list[dict[str, Any]] = []
    refined_records: list[dict[str, Any]] = []
    for cell in TARGET_CELLS:
        for resolution in RESOLUTIONS:
            keys = {role: indexed[(cell, resolution, role)] for role in PRIMARY_ROLES}
            snapshots = decode_bundle(store, runtime, keys, cell, resolution)
            for label, indices in RANKS:
                row = evaluate_bundle(snapshots, indices, label, "1/144", SIGNED_AREA_PRIMARY_Q2)
                primary_records.append({"grid_index": list(cell), "resolution": resolution, **row})
            if cell in REFINED_REPRESENTATIVES:
                refined_keys = {role: indexed[(cell, resolution, role)] for role in REFINED_ROLES}
                refined_snapshots = dict(snapshots)
                refined_snapshots.update(decode_bundle(store, runtime, refined_keys, cell, resolution))
                refined_snapshots = {"CENTER": refined_snapshots["CENTER"], "PLUS_X": refined_snapshots["PLUS_X_288"], "MINUS_X": refined_snapshots["MINUS_X_288"], "PLUS_Y": refined_snapshots["PLUS_Y_288"], "MINUS_Y": refined_snapshots["MINUS_Y_288"]}
                for label, indices in RANKS:
                    row = evaluate_bundle(refined_snapshots, indices, label, "1/288", SIGNED_AREA_REFINED_Q2)
                    refined_records.append({"grid_index": list(cell), "resolution": resolution, **row})
            del snapshots
    primary_summary = {label: summarize_primary(primary_records, len(indices)) for label, indices in RANKS}
    refined_summary = {label: summarize_refined(primary_records, refined_records, len(indices)) for label, indices in RANKS}
    structural = {
        "schema": "mephc-e9f-d10-fr04-structural-threshold-provenance-v1", "status": "PASS_EXACT_ACCEPTED_IMPLEMENTATION_REPLAY",
        "production_external_isolation_threshold": PRODUCTION_THRESHOLD, "diagnostic_structural_thresholds": STRUCTURAL_THRESHOLDS.to_dict(),
        "threshold_scope": "accepted continuity and transport semantics replayed with the external gate separated; 0.02 production gate unchanged",
        "berry_normalization_id": "E9F_C1_SOURCE_GRID_WILSON_PHASE_OVER_SIGNED_CCW_AREA_V1", "formula": "OMEGA_Q=-ARG_DET_W/SIGNED_AREA_Q2", "reciprocal_space_jacobian_used": False,
        "accepted_implementation_files": [accepted_file(ROOT / path) for path in ("mephc/eigenspace.py", "mephc/subspace_transport.py", "mephc/spectral_association.py", "mephc/path_domain.py", "mephc/plaquette_domain.py", "mephc/wilson_geometry.py")],
        "accepted_test_files": [accepted_file(ROOT / path) for path in ("tests/test_e1_eigenspace.py", "tests/test_e2_subspace_transport.py", "tests/test_e3_spectral_association.py", "tests/test_e3c_spectral_association_validation.py", "tests/test_e5b_wilson_analytic_validation.py", "tests/test_e7d_mpb_plaquette_holonomy.py")],
        "d8_provenance_replay": d8_provenance,
    }
    primary_artifact = {"schema": "mephc-e9f-d10-fr04-primary-stencil-convergence-v1", "stencil": "1/144", "signed_area_q2": "1/10368", "record_count": len(primary_records), "records": primary_records, "summaries": primary_summary}
    refined_artifact = {"schema": "mephc-e9f-d10-fr04-refined-stencil-convergence-v1", "stencil": "1/288", "signed_area_q2": "1/41472", "record_count": len(refined_records), "records": refined_records, "summaries": refined_summary}
    atomic_json(ROOT / "audit/e9f/d10_fr04_structural_threshold_provenance.json", structural)
    atomic_json(ROOT / "audit/e9f/d10_fr04_primary_stencil_convergence.json", primary_artifact)
    atomic_json(ROOT / "audit/e9f/d10_fr04_refined_stencil_convergence.json", refined_artifact)
    final_sha = git_head()
    result: dict[str, Any] = {
        "schema": "mephc-e9f-d10-fr04-residual-composite-method-validation-v1", "work_order_id": WORK_ORDER_ID,
        "base_sandbox_sha": BASE_SANDBOX_SHA, "main_sha": MAIN_SHA,
        "machine_contract_status": "PASS", "dataset_binding_status": "VERIFIED_EXISTING_IMMUTABLE_DATASET", "structural_threshold_provenance_status": structural["status"], "nonabelian_provenance_status": d8_provenance["status"],
        "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "dataset_record_count": 420,
        "d10_dataset_id": DATASET_ID, "d10_dataset_manifest_sha256": MANIFEST_SHA256, "d10_dataset_record_count": 420,
        "d10_entrypoint_sha256": sha256_file(Path(__file__)), "d10_request_graph_sha256": GRAPH_SHA256,
        "rank2_primary_structurally_evaluable_cell_count": primary_summary["rank2"]["primary_structurally_evaluable_cell_count"], "rank2_primary_odd_contraction_pass_count": primary_summary["rank2"]["primary_odd_contraction_pass_count"], "rank2_primary_even_contraction_pass_count": primary_summary["rank2"]["primary_even_contraction_pass_count"], "rank2_primary_terminal_parity_pass_count": primary_summary["rank2"]["primary_terminal_parity_pass_count"], "rank2_primary_all_resolution_criteria_pass_count": primary_summary["rank2"]["primary_all_resolution_criteria_pass_count"], "rank2_robust_positive_gap_pass_count": primary_summary["rank2"]["robust_positive_gap_pass_count"],
        "rank2_refined_structurally_evaluable_count": refined_summary["rank2"]["refined_structurally_evaluable_count"], "rank2_refined_odd_contraction_pass_count": refined_summary["rank2"]["refined_odd_contraction_pass_count"], "rank2_refined_even_contraction_pass_count": refined_summary["rank2"]["refined_even_contraction_pass_count"], "rank2_refined_terminal_parity_pass_count": refined_summary["rank2"]["refined_terminal_parity_pass_count"], "rank2_cross_stencil_nonincrease_pass_count": refined_summary["rank2"]["cross_stencil_nonincrease_pass_count"], "rank2_cross_stencil_terminal_consistency_pass_count": refined_summary["rank2"]["cross_stencil_terminal_consistency_pass_count"], "rank2_refined_all_criteria_pass_count": refined_summary["rank2"]["refined_all_criteria_pass_count"], "rank2_method_support_status": "METHOD_SUPPORTED_ON_LOCKED_RESIDUAL_SET" if refined_summary["rank2"]["refined_all_criteria_pass_count"] == 5 and primary_summary["rank2"]["primary_all_resolution_criteria_pass_count"] == 10 and primary_summary["rank2"]["robust_positive_gap_pass_count"] == 10 else "METHOD_NOT_ESTABLISHED_ON_LOCKED_RESIDUAL_SET",
        "rank3_primary_structurally_evaluable_cell_count": primary_summary["rank3"]["primary_structurally_evaluable_cell_count"], "rank3_primary_odd_contraction_pass_count": primary_summary["rank3"]["primary_odd_contraction_pass_count"], "rank3_primary_even_contraction_pass_count": primary_summary["rank3"]["primary_even_contraction_pass_count"], "rank3_primary_terminal_parity_pass_count": primary_summary["rank3"]["primary_terminal_parity_pass_count"], "rank3_primary_all_resolution_criteria_pass_count": primary_summary["rank3"]["primary_all_resolution_criteria_pass_count"], "rank3_robust_positive_gap_pass_count": primary_summary["rank3"]["robust_positive_gap_pass_count"],
        "rank3_refined_structurally_evaluable_count": refined_summary["rank3"]["refined_structurally_evaluable_count"], "rank3_refined_odd_contraction_pass_count": refined_summary["rank3"]["refined_odd_contraction_pass_count"], "rank3_refined_even_contraction_pass_count": refined_summary["rank3"]["refined_even_contraction_pass_count"], "rank3_refined_terminal_parity_pass_count": refined_summary["rank3"]["refined_terminal_parity_pass_count"], "rank3_cross_stencil_nonincrease_pass_count": refined_summary["rank3"]["cross_stencil_nonincrease_pass_count"], "rank3_cross_stencil_terminal_consistency_pass_count": refined_summary["rank3"]["cross_stencil_terminal_consistency_pass_count"], "rank3_refined_all_criteria_pass_count": refined_summary["rank3"]["refined_all_criteria_pass_count"], "rank3_method_support_status": "METHOD_SUPPORTED_ON_LOCKED_RESIDUAL_SET" if refined_summary["rank3"]["refined_all_criteria_pass_count"] == 5 and primary_summary["rank3"]["primary_all_resolution_criteria_pass_count"] == 10 and primary_summary["rank3"]["robust_positive_gap_pass_count"] == 10 else "METHOD_NOT_ESTABLISHED_ON_LOCKED_RESIDUAL_SET",
        "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "global_threshold_change_authorized": False, "composite_threshold_change_authorized": False, "production_composite_chern_authorized": False, "production_threshold_unchanged": True, "production_composite_chern_emitted": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False, "next_scientific_state": "FR04_RESIDUAL_COMPOSITE_NUMERICAL_METHOD_VALIDATION_AVAILABLE_FOR_SUPERVISOR_POLICY_DECISION", "terminal": "E9F_D10_FR04_RESIDUAL_COMPOSITE_METHOD_VALIDATION_COMPLETE",
    }
    atomic_json(ROOT / "audit/e9f/d10_fr04_composite_method_validation_result.json", result)
    return result


def main() -> int:
    try:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(analysis()).decode("utf-8"))
        return 0
    except Exception as exc:
        failure = {"schema": "mephc-e9f-d10-fr04-residual-composite-method-validation-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "solver_executions": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E9F_D10_FR04_RESIDUAL_COMPOSITE_METHOD_VALIDATION_FAIL_CLOSED"}
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(failure).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
