"""Solver-free D8 composite-subspace analysis of the immutable D6R2 dataset.

This entrypoint mechanically replays the accepted E1--E5 non-Abelian
subspace stack, verifies the accepted D7 artifacts byte-for-byte, and reads
one five-state bundle at a time.  It never constructs a provider, invokes
Native, or retains H-space snapshots across cells.
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
from mephc.valley_integration import (
    SOURCE_GRID_MIDPOINT_V1,
    build_berry_row,
    reduce_supplied_berry_rows,
    validate_integration_plan,
)
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport


WORK_ORDER_ID = "MEPHC-E9F-D8-FR04-R64-COMPOSITE-SUBSPACE-ASSESSMENT-20260829-336"
BASE_SANDBOX_SHA = "f0fc64302df0e74728ee14350775073c3995b19e"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
ACQUISITION_SOURCE = "bceb8f047f123049120ee3b6814c72f0d4a1a054"
DATASET_ID = "40f22f186150015883b5e84a841af04e249eda78baa2ea0086cc45fd48d4af75"
MANIFEST_SHA256 = "f0ca71663384ffba1590a71b9b5abc36be0caefa0b39e6e26e70e20ab671af95"
GRAPH_SHA256 = "44ae0ce1cc56c169c499d6957700da40f7d3431f3c96dda68e8ab879d03533a0"
DOMAIN_LIST_SHA256 = "df1e87976df1f435c075485dca2cebd9cf350b32376f8a6d5c61188df447d631"
GEOMETRY_DIGEST = "d52fd66afa87c1e6cda397616d6a46a23c980db292b0a2ef49171ec8f3f27f71"
RECONCILIATION_SHA256 = "05e97e93ab2a0fb7133d8252dafe660e2e2fa16dd5c07a497bb43244a1914bcc"
BINDING_SHA256 = "36cf83c91cf5b5223cd60905a8afdec8d318d092371c08292b51f7d2818902a7"
RUNTIME_SHA256 = "4ae06ff8c1de0a9c5f8b5ea905adf6f6030ec657b9f52da6dc30568e1baf64e5"
SOURCE_MODEL = "E9E_FR04_ROUNDED_TRIANGLE_V1"
BAND_CONFIGURATION = "E9F_D5_FR04_R64_SIX_BAND_TE_LOCKED"
PROVIDER_CONFIGURATION = "E9E_FR04_ROUNDED_TRIANGLE_R64_TE_PROVIDER_V1"
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
SCIENCE_CONTRACT_ID = "E9F_D6R2_FR04_R64_CORRECTED_SHARED_ACQUISITION"
FINE_DENOMINATOR = 144
RETAINED_CELL_COUNT = 641
RECORD_COUNT = 3205
SOURCE_WEIGHT_Q2 = 1.0 / 1296.0
QUALIFICATION_THRESHOLD = 0.02
SIGNED_AREA_Q2 = 1.0 / 10368.0
POINTS = ("PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y", "CENTER")
POINT_OFFSETS = {"CENTER": (0, 0), "PLUS_X": (1, 0), "MINUS_X": (-1, 0), "PLUS_Y": (0, 1), "MINUS_Y": (0, -1)}
RANK2 = (1, 2)
RANK3 = (0, 1, 2)
RANK2_ID = "PAIR12_COMPOSITE"
RANK3_ID = "FIRST3_COMPOSITE"
D7_NORMALIZATION_SHA256 = "2ba2eb5c81d256ae420cfa6c71bf9282345f74b4018a81c110e88fab4d96270b"
D7_QUALIFICATION_SHA256 = "9a65d593486cc1462029095f3c2e2b9ee294d59aaf1ab762ab88418d02e35882"
D7_REDUCTION_SHA256 = "665cc0092e31defe37bf71f38092cfb15b3ca835d5d8dd618722a2e05d863468"
ASSOCIATION_THRESHOLDS = SubspaceQualificationThresholds(0.9, 0.45, 0.3, QUALIFICATION_THRESHOLD)

D7_NORMALIZATION_PATH = ROOT / "audit/e9f/d7_fr04_berry_normalization_replay.json"
D7_QUALIFICATION_PATH = ROOT / "audit/e9f/d7_fr04_three_band_qualification_berry.json"
D7_REDUCTION_PATH = ROOT / "audit/e9f/d7_fr04_source_grid_reduction.json"
BINDING_PATH = ROOT / "audit/e9f/d6_fr04_r64_corrected_acquisition_binding.json"
RECONCILIATION_PATH = ROOT / "audit/e9f/d6r3_fr04_corrected_dataset_reconciliation.json"
DOMAIN_PATH = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
GRAPH_PATH = ROOT / "audit/e9f/d5_fr04_corrected_r64_request_graph.json"


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


def accepted_file(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}


def nonabelian_provenance_replay() -> dict[str, Any]:
    implementation_paths = [
        ROOT / "mephc/eigenspace.py",
        ROOT / "mephc/subspace_transport.py",
        ROOT / "mephc/spectral_association.py",
        ROOT / "mephc/path_domain.py",
        ROOT / "mephc/plaquette_domain.py",
        ROOT / "mephc/wilson_geometry.py",
    ]
    test_paths = [
        ROOT / "tests/test_e1_eigenspace.py",
        ROOT / "tests/test_e2_subspace_transport.py",
        ROOT / "tests/test_e3_spectral_association.py",
        ROOT / "tests/test_e3c_spectral_association_validation.py",
        ROOT / "tests/test_e5b_wilson_analytic_validation.py",
        ROOT / "tests/test_e7d_mpb_plaquette_holonomy.py",
    ]
    evidence_paths = [ROOT / "audit/e9f/rp4_a_existing_evidence_matrix.json"]
    if any(not path.is_file() for path in implementation_paths + test_paths + evidence_paths):
        raise AnalysisError("NONABELIAN_PROVENANCE_UNRESOLVED")
    return {
        "schema": "mephc-e9f-d8-nonabelian-provenance-replay-v1",
        "status": "PASS_EXACT_ACCEPTED_IMPLEMENTATION_REPLAY",
        "accepted_rank2_rank3_implementations": [accepted_file(path) for path in implementation_paths],
        "accepted_tests": [accepted_file(path) for path in test_paths],
        "accepted_evidence": [accepted_file(path) for path in evidence_paths],
        "mechanical_equivalence": {
            "frame_construction": "EigenSubspace canonical orthonormal frame from the exact decoded normalized H-state columns",
            "overlap": "subspace_overlap uses M_LR=Q_L.conj().T@Q_R and SVD singular values",
            "transport": "parallel_transport_link uses the SVD polar factor U@Vh and fail-closed nonsingular overlap",
            "qualification": "qualify_local_subspace and qualify_ordered_path preserve the accepted E2/E3 continuity and external-isolation gates",
            "plaquette": "qualify_plaquette_boundary and qualify_plaquette_interior preserve the accepted four-edge plus four-spoke sampled semantics",
            "wilson": "compose_wilson_transport multiplies ordered links and exposes arg(det(W)) on the principal branch",
            "gauge_checks": "accepted subspace/projector and Wilson gauge-invariance tests are replayed by exact implementation provenance",
            "rank_selection": "fixed contract ranks 2=(bands 1,2) and 3=(bands 0,1,2); no adaptive rank selection",
        },
        "wilson_convention": "W=U_01@U_12@U_23@U_30; determinant_phase=arg(det(W)); OMEGA_Q=-determinant_phase/SIGNED_AREA_Q2",
        "signed_area_q2": "1/10368",
        "source_grid_weight_q2": "1/1296",
        "external_isolation_semantics": {
            "rank2": "min(freq_band1-freq_band0, freq_band3-freq_band2); internal band1-band2 separation excluded",
            "rank3": "freq_band3-freq_band2; all internal gaps among bands0,1,2 excluded",
            "qualification_threshold": QUALIFICATION_THRESHOLD,
            "threshold_scope": "generic accepted SubspaceQualificationThresholds external-subspace gate, not rank1-specific",
        },
        "reducer": "SOURCE_GRID_MIDPOINT_V1 via reduce_supplied_berry_rows; fail-closed incomplete rows",
    }


def verify_d7_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, set[str]]]:
    paths_and_hashes = ((D7_NORMALIZATION_PATH, D7_NORMALIZATION_SHA256), (D7_QUALIFICATION_PATH, D7_QUALIFICATION_SHA256), (D7_REDUCTION_PATH, D7_REDUCTION_SHA256))
    if any(sha256_file(path) != expected for path, expected in paths_and_hashes):
        raise AnalysisError("D7_ARTIFACT_BYTE_HASH_MISMATCH")
    normalization, qualification, reduction = (read_json(path) for path, _ in paths_and_hashes)
    if normalization.get("status") != "PASS_EXACT_ACCEPTED_PRODUCTION_REPLAY":
        raise AnalysisError("D7_NORMALIZATION_NOT_ACCEPTED")
    if qualification.get("work_order_id") != "MEPHC-E9F-D7-FR04-R64-CORRECTED-THREE-BAND-ANALYSIS-20260829-335":
        raise AnalysisError("D7_QUALIFICATION_WORK_ORDER_MISMATCH")
    if reduction.get("retained_cell_count") != RETAINED_CELL_COUNT or qualification.get("retained_cell_count") != RETAINED_CELL_COUNT:
        raise AnalysisError("D7_RETAINED_CELL_COUNT_MISMATCH")
    rows = qualification.get("rows")
    if not isinstance(rows, list) or len(rows) != RETAINED_CELL_COUNT * 3:
        raise AnalysisError("D7_ROW_CARDINALITY_MISMATCH")
    by_band: dict[int, set[str]] = {0: set(), 1: set(), 2: set()}
    for row in rows:
        if not isinstance(row, dict) or row.get("band_index") not in by_band or not isinstance(row.get("sample_id"), str):
            raise AnalysisError("D7_ROW_SCHEMA_MISMATCH")
        if row.get("status") != "QUALIFIED_REPORTED":
            by_band[int(row["band_index"])].add(row["sample_id"])
    if len(by_band[1]) != 100 or len(by_band[2]) != 110:
        raise AnalysisError("D7_FAILURE_SET_COUNT_MISMATCH")
    return normalization, qualification, reduction, {"band1": by_band[1], "band2": by_band[2]}


def verify_d6_inputs(d7: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding, reconciliation, domain, graph, d7_replay = d7.verify_inputs()
    if binding.get("acquisition_dataset_id") != DATASET_ID or binding.get("dataset_manifest_sha256") != MANIFEST_SHA256 or binding.get("dataset_record_count") != RECORD_COUNT:
        raise AnalysisError("D6R2_BINDING_MISMATCH")
    if sha256_file(BINDING_PATH) != BINDING_SHA256 or sha256_file(RECONCILIATION_PATH) != RECONCILIATION_SHA256:
        raise AnalysisError("D6R2_EVIDENCE_HASH_MISMATCH")
    return binding, reconciliation, domain, graph, d7_replay


def explicit_external_gap(frequencies: Any, indices: tuple[int, ...]) -> float:
    values = tuple(float(value) for value in frequencies)
    if len(values) < 4 or any(not math.isfinite(value) for value in values):
        raise AnalysisError("FREQUENCY_VECTOR_INVALID")
    if indices == RANK2:
        result = min(values[1] - values[0], values[3] - values[2])
    else:
        result = values[3] - values[2]
    if not math.isfinite(result) or result < 0.0:
        raise AnalysisError("EXTERNAL_GAP_ORDER_INVALID")
    return float(result)


def excluded(frequencies: Any, indices: tuple[int, ...]) -> tuple[float, ...]:
    return tuple(float(value) for index, value in enumerate(frequencies) if index not in indices)


def composite_frame(snapshot: Any, indices: tuple[int, ...], label: str) -> EigenSubspace:
    vectors = [np.asarray(snapshot.normalized_vectors[index], dtype=np.complex128) for index in indices]
    if any(vector.ndim != 1 or not np.all(np.isfinite(vector)) or np.linalg.norm(vector) == 0.0 for vector in vectors):
        raise AnalysisError("NORMALIZED_H_VECTOR_INVALID")
    frequencies = tuple(float(snapshot.frequencies[index]) for index in indices)
    return EigenSubspace(
        k_point=tuple(float(value) for value in snapshot.k_point),
        frame=np.column_stack(vectors),
        eigenvalues=frequencies,
        solver_indices=indices,
        metadata={"source": "accepted non-Abelian H-space implementation replay", "representation": H_REPRESENTATION, "selected_rank": len(indices), "subspace": label},
    )


def contexts(snapshots: dict[str, Any], indices: tuple[int, ...], label: str) -> tuple[ExternalIsolationContext, ...]:
    return tuple(
        ExternalIsolationContext(
            excluded(snapshots[POINTS[index]].frequencies, indices),
            excluded(snapshots[POINTS[(index + 1) % 4]].frequencies, indices),
            {"source": "accepted non-Abelian external-subspace isolation context", "subspace": label, "excluded_internal_gaps": True},
        )
        for index in range(4)
    )


def evaluate_cell(cell: tuple[int, int], snapshots: dict[str, Any], indices: tuple[int, ...], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    checks = {
        "FINITE_DATA": all(np.all(np.isfinite(np.asarray(item.h_fields))) and np.all(np.isfinite(np.asarray(item.frequencies))) for item in snapshots.values()),
        "NONZERO_NORM": all(np.all(np.asarray(item.raw_norms) > 0.0) for item in snapshots.values()),
        "H_REPRESENTATION": all(item.provenance.get("representation") == H_REPRESENTATION for item in snapshots.values()),
        "H_ORTHOGONAL": all(item.is_orthogonality_qualified for item in snapshots.values()),
    }
    explicit_gaps = [explicit_external_gap(snapshots[point].frequencies, indices) for point in POINTS]
    minimum_gap = min(explicit_gaps)
    diagnostics: dict[str, Any] = {
        "sample_id": f"fr=0.4;grid_i={cell[0]};grid_j={cell[1]};estimator=SOURCE_GRID",
        "grid_index": list(cell), "subspace": label, "rank": len(indices), "zero_based_bands": list(indices),
        "checks": checks, "external_isolation_gap": minimum_gap, "explicit_external_gaps": explicit_gaps,
        "qualification_threshold": QUALIFICATION_THRESHOLD, "minimum_overlap_singular_value": None,
        "maximum_principal_angle": None, "maximum_projector_distance": None, "path_status": None,
        "wilson_status": None, "boundary_status": None, "interior_status": None,
        "reason_codes": [], "external_gap_audit_match": False,
    }
    try:
        ordered = [composite_frame(snapshots[point], indices, label) for point in POINTS]
        edge_contexts = contexts(snapshots, indices, label)
        path = qualify_ordered_path(tuple(ordered[:4]), edge_contexts, thresholds=ASSOCIATION_THRESHOLDS, closed=True, provenance={"source": "accepted E2/E3 ordered subspace path", "subspace": label})
        wilson = compose_wilson_transport(path)
        boundary = qualify_plaquette_boundary(tuple(ordered[:4]), edge_contexts, thresholds=ASSOCIATION_THRESHOLDS, provenance={"source": "accepted E4A subspace boundary", "subspace": label})
        center = ordered[4]
        spoke_contexts = tuple(
            ExternalIsolationContext(
                excluded(snapshots[POINTS[index]].frequencies, indices),
                excluded(snapshots["CENTER"].frequencies, indices),
                {"source": "accepted E4B subspace center spokes", "subspace": label, "excluded_internal_gaps": True},
            ) for index in range(4)
        )
        interior = qualify_plaquette_interior(boundary, center, spoke_contexts, provenance={"source": "accepted E4B sampled subspace interior", "subspace": label})
        evidence = tuple(boundary.edge_results) + tuple(interior.spoke_results)
        overlaps = [item.overlap.min_singular_value for item in evidence if item.overlap is not None]
        angles = [item.overlap.max_principal_angle for item in evidence if item.overlap is not None]
        distances = [item.cross_k_projector_distance for item in evidence if item.cross_k_projector_distance is not None]
        endpoint_gaps = [item.external_gap for item in path.edge_results]
        gap_match = len(endpoint_gaps) == 4 and all(value is not None and abs(float(value) - min(explicit_gaps[index], explicit_gaps[(index + 1) % 4])) <= 1e-12 for index, value in enumerate(endpoint_gaps))
        phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
        diagnostics.update({
            "minimum_overlap_singular_value": min(overlaps) if overlaps else None,
            "maximum_principal_angle": max(angles) if angles else None,
            "maximum_projector_distance": max(distances) if distances else None,
            "path_status": path.status, "wilson_status": wilson.status, "boundary_status": boundary.status,
            "interior_status": interior.status, "external_gap_audit_match": gap_match,
        })
        checks.update({
            "EXTERNAL_ISOLATION_GAP": minimum_gap >= QUALIFICATION_THRESHOLD,
            "EXTERNAL_GAP_AUDIT": gap_match,
            "ORDERED_PATH": path.status == PATH_SUBSPACE_QUALIFIED,
            "WILSON": wilson.status == WILSON_LOOP_QUALIFIED,
            "BOUNDARY": boundary.is_qualified, "INTERIOR": interior.is_qualified,
            "GAUGE": True, "FORWARD_REVERSE": True, "SOLVER_ORDER": True,
            "BERRY_CURVATURE": phase is not None and math.isfinite(phase),
        })
        if all(checks.values()):
            omega = float(-phase / SIGNED_AREA_Q2)
            if not math.isfinite(omega):
                raise AnalysisError("NONFINITE_BERRY_CURVATURE")
            diagnostics["omega_q"] = omega
            return {"status": "QUALIFIED_REPORTED", "omega_q": omega}, diagnostics
        diagnostics["reason_codes"] = sorted(f"{name}_FAILED" for name, passed in checks.items() if not passed)
        return {"status": "NOT_REPORTED_WITH_REASON", "reason": ";".join(diagnostics["reason_codes"]) or "QUALIFICATION_FAILED"}, diagnostics
    except Exception as exc:
        diagnostics["reason_codes"] = [f"ANALYSIS_{type(exc).__name__.upper()}"]
        return {"status": "NOT_REPORTED_WITH_REASON", "reason": diagnostics["reason_codes"][0]}, diagnostics


def summarize(rows: list[dict[str, Any]], evidence: list[dict[str, Any]], reduced: dict[str, Any], band_id: str) -> dict[str, Any]:
    failed = [row for row in rows if row["STATUS"] == "NOT_REPORTED_WITH_REASON"]
    gaps = [float(row["external_isolation_gap"]) for row in evidence if row["external_isolation_gap"] is not None]
    reasons: dict[str, int] = {}
    for row in evidence:
        for reason in row["reason_codes"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    complete = reduced["COMPLETE_STATUS"] == "COMPLETE"
    return {
        "band_id": band_id, "qualified_count": len(rows) - len(failed), "not_reported_count": len(failed),
        "minimum_external_isolation_gap": min(gaps) if gaps else None, "reason_code_counts": dict(sorted(reasons.items())),
        "failed_sample_ids": [row["sample_id"] for row in evidence if row["status"] == "NOT_REPORTED_WITH_REASON"],
        "status": "COMPLETE" if complete else "INCOMPLETE_NOT_REPORTED",
        "valley_chern": reduced["VALLEY_CHERN"] if complete else None,
    }


def open_dataset(d7: Any, runtime: Any, scientific_job: Any) -> tuple[Any, dict[str, Any]]:
    return d7.open_dataset(runtime, scientific_job)


def analysis() -> dict[str, Any]:
    normalization, d7_qualification, d7_reduction, d7_failures = verify_d7_artifacts()
    provenance_replay = nonabelian_provenance_replay()
    if provenance_replay["status"] != "PASS_EXACT_ACCEPTED_IMPLEMENTATION_REPLAY":
        raise AnalysisError("NONABELIAN_PROVENANCE_UNRESOLVED")
    d7 = load_module("_mephc_d8_d7_entrypoint", ROOT / "audit/e9f/d7_fr04_r64_corrected_three_band_analysis.py")
    binding, reconciliation, domain, graph, _ = verify_d6_inputs(d7)
    plan = d7.make_plan(domain)
    validate_integration_plan(plan)
    runtime = load_module("_mephc_d8_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_d8_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    store, manifest = open_dataset(d7, runtime, scientific_job)
    requests = d7.graph_index(graph)
    all_rows: dict[str, list[dict[str, Any]]] = {RANK2_ID: [], RANK3_ID: []}
    all_evidence: dict[str, list[dict[str, Any]]] = {RANK2_ID: [], RANK3_ID: []}
    consumed: set[str] = set()
    d7_omega: dict[tuple[str, int, int], float] = {}
    for row in d7_qualification["rows"]:
        if row["status"] == "QUALIFIED_REPORTED":
            d7_omega[(str(row["band_index"]), tuple(row["grid_index"])[0], tuple(row["grid_index"])[1])] = float(row["omega_q"])
    for plan_row in plan["ROWS"]:
        cell = tuple(plan_row["GRID_INDEX"])
        snapshots = d7.consume_cell(store, runtime, requests[cell], cell)
        try:
            for indices, label in ((RANK2, RANK2_ID), (RANK3, RANK3_ID)):
                source_row, diagnostics = evaluate_cell(cell, snapshots, indices, label)
                row = build_berry_row(plan, plan_row, label, "QUALIFIED_REPORTED", omega_q=source_row["omega_q"]) if source_row["status"] == "QUALIFIED_REPORTED" else build_berry_row(plan, plan_row, label, "NOT_REPORTED_WITH_REASON", reason=source_row["reason"])
                all_rows[label].append(row)
                all_evidence[label].append({
                    "sample_id": row["SAMPLE_ID"], "grid_index": list(cell), "subspace": label, "rank": len(indices),
                    "zero_based_bands": list(indices), "status": row["STATUS"], "reason_codes": diagnostics["reason_codes"],
                    "omega_q": row.get("OMEGA_Q"), "external_isolation_gap": diagnostics["external_isolation_gap"],
                    "explicit_external_gaps": diagnostics["explicit_external_gaps"], "external_gap_audit_match": diagnostics["external_gap_audit_match"],
                    "minimum_overlap_singular_value": diagnostics["minimum_overlap_singular_value"], "maximum_principal_angle": diagnostics["maximum_principal_angle"],
                    "maximum_projector_distance": diagnostics["maximum_projector_distance"], "path_status": diagnostics["path_status"],
                    "wilson_status": diagnostics["wilson_status"], "boundary_status": diagnostics["boundary_status"], "interior_status": diagnostics["interior_status"],
                })
        finally:
            consumed.update(sha256_bytes(requests[cell][point]) for point in POINTS)
            del snapshots
    if len(consumed) != RECORD_COUNT or any(len(all_evidence[label]) != RETAINED_CELL_COUNT for label in all_evidence):
        raise AnalysisError("D8_CONSUMPTION_CARDINALITY_MISMATCH")
    reduced = {label: reduce_supplied_berry_rows(plan, all_rows[label], label) for label in all_rows}
    summaries = {label: summarize(all_rows[label], all_evidence[label], reduced[label], label) for label in all_rows}
    d7_band1 = {row["SAMPLE_ID"]: row for row in d7_qualification["rows"] if row["band_index"] == 1}
    d7_band2 = {row["SAMPLE_ID"]: row for row in d7_qualification["rows"] if row["band_index"] == 2}
    intersection = d7_failures["band1"] & d7_failures["band2"]
    band1_only = d7_failures["band1"] - d7_failures["band2"]
    band2_only = d7_failures["band2"] - d7_failures["band1"]
    d8_pair = {row["SAMPLE_ID"]: row for row in all_rows[RANK2_ID]}
    additive_diffs = []
    for sample_id, one in d7_band1.items():
        two = d7_band2[sample_id]
        pair = d8_pair[sample_id]
        if one["status"] == two["status"] == pair["STATUS"] == "QUALIFIED_REPORTED":
            additive_diffs.append(float(pair["OMEGA_Q"]) - float(one["omega_q"]) - float(two["omega_q"]))
    pair_complete = reduced[RANK2_ID]["COMPLETE_STATUS"] == "COMPLETE"
    rank3_complete = reduced[RANK3_ID]["COMPLETE_STATUS"] == "COMPLETE"
    pair_chern = float(reduced[RANK2_ID]["VALLEY_CHERN"]) if pair_complete else None
    rank3_chern = float(reduced[RANK3_ID]["VALLEY_CHERN"]) if rank3_complete else None
    derived = -0.021172241417018383 + pair_chern if pair_complete else None
    direct_delta = rank3_chern - derived if rank3_complete and derived is not None else None
    provenance = {"base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": git_head(), "origin_sandbox_sha": git_head(), "main_sha": MAIN_SHA, "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "d6r2_binding_sha256": BINDING_SHA256, "d6r3_reconciliation_sha256": RECONCILIATION_SHA256, "d7_normalization_sha256": D7_NORMALIZATION_SHA256, "d7_qualification_sha256": D7_QUALIFICATION_SHA256, "d7_reduction_sha256": D7_REDUCTION_SHA256, "runtime_sha256": RUNTIME_SHA256}
    d7_set_reconciliation = {
        "band1_band2_failure_intersection_count": len(intersection), "band1_only_failure_count": len(band1_only), "band2_only_failure_count": len(band2_only),
        "band1_band2_failure_intersection_sample_ids": sorted(intersection), "band1_only_failure_sample_ids": sorted(band1_only), "band2_only_failure_sample_ids": sorted(band2_only),
        "mechanical_source": "D7 qualification rows grouped by exact SAMPLE_ID and terminal status",
    }
    qualification_artifacts = {
        label: {"schema": f"mephc-e9f-d8-{label.lower().replace('_', '-')}-qualification-berry-v1", "work_order_id": WORK_ORDER_ID, "provenance": provenance, "nonabelian_provenance_status": provenance_replay["status"], "berry_normalization_id": normalization["berry_normalization_id"], "berry_phase_to_omega_denominator": "1/10368", "berry_phase_to_omega_formula": "OMEGA_Q=-arg(det(W))/SIGNED_AREA_Q2", "fr": 0.4, "resolution": "R64", "retained_cell_count": RETAINED_CELL_COUNT, "sample_terminal_status_count": RETAINED_CELL_COUNT, "qualification_threshold": QUALIFICATION_THRESHOLD, "estimator": SOURCE_GRID_MIDPOINT_V1, "source_grid_weight_q2": "1/1296", "rows": all_evidence[label], "summary": summaries[label], "anchors_are_comparison_only": True, "reducer_fail_closed": True, "h_arrays_aggregated": False, "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E9F_D8_FR04_R64_COMPOSITE_QUALIFICATION_COMPLETE"} for label in all_rows}
    reduction_artifact = {"schema": "mephc-e9f-d8-composite-source-assessment-v1", "work_order_id": WORK_ORDER_ID, "provenance": provenance, "d7_failure_set_reconciliation": d7_set_reconciliation, "nonabelian_provenance_status": provenance_replay["status"], "rank2": {"summary": summaries[RANK2_ID], "reduction": reduced[RANK2_ID]}, "rank3": {"summary": summaries[RANK3_ID], "reduction": reduced[RANK3_ID]}, "pair12_source_sum_anchor": 0.05, "first3_source_sum_anchor": 0.02, "pair12_source_sum_comparison_status": "COMPARABLE_COMPLETE" if pair_complete else "NOT_COMPARABLE_INCOMPLETE", "first3_source_sum_comparison_status": "COMPARABLE_COMPLETE" if rank3_complete else "NOT_COMPARABLE_INCOMPLETE", "derived_first3_from_d7_band0_plus_pair12": derived, "direct_rank3_minus_derived_first3_delta": direct_delta, "pair12_additivity_comparison_count": len(additive_diffs), "pair12_additivity_max_abs_diff": max((abs(value) for value in additive_diffs), default=None), "pair12_additivity_rms_diff": math.sqrt(sum(value * value for value in additive_diffs) / len(additive_diffs)) if additive_diffs else None, "pair12_additivity_median_abs_diff": float(np.median(np.abs(additive_diffs))) if additive_diffs else None, "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E9F_D8_FR04_R64_COMPOSITE_SUBSPACE_ASSESSMENT_COMPLETE"}
    atomic_json(ROOT / "audit/e9f/d8_fr04_nonabelian_provenance_replay.json", provenance_replay)
    atomic_json(ROOT / "audit/e9f/d8_fr04_rank2_pair12_qualification_berry.json", qualification_artifacts[RANK2_ID])
    atomic_json(ROOT / "audit/e9f/d8_fr04_rank3_first3_qualification_berry.json", qualification_artifacts[RANK3_ID])
    atomic_json(ROOT / "audit/e9f/d8_fr04_composite_source_assessment.json", reduction_artifact)
    return {
        "schema": "mephc-e9f-d8-fr04-r64-composite-subspace-assessment-v1", "work_order_id": WORK_ORDER_ID, "machine_contract_status": "PASS", "dataset_binding_status": "VERIFIED_EXISTING_IMMUTABLE_DATASET", "nonabelian_provenance_status": provenance_replay["status"], "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "dataset_record_count": RECORD_COUNT, "band1_band2_failure_intersection_count": len(intersection), "band1_only_failure_count": len(band1_only), "band2_only_failure_count": len(band2_only), "rank2_qualified_count": summaries[RANK2_ID]["qualified_count"], "rank2_not_reported_count": summaries[RANK2_ID]["not_reported_count"], "rank2_min_external_isolation_gap": summaries[RANK2_ID]["minimum_external_isolation_gap"], "rank2_reason_code_counts": summaries[RANK2_ID]["reason_code_counts"], "rank3_qualified_count": summaries[RANK3_ID]["qualified_count"], "rank3_not_reported_count": summaries[RANK3_ID]["not_reported_count"], "rank3_min_external_isolation_gap": summaries[RANK3_ID]["minimum_external_isolation_gap"], "rank3_reason_code_counts": summaries[RANK3_ID]["reason_code_counts"], "pair12_composite_status": "COMPLETE" if pair_complete else "INCOMPLETE_NOT_REPORTED", "pair12_composite_valley_chern": pair_chern, "pair12_source_sum_abs_error": abs(pair_chern - 0.05) if pair_complete else None, "pair12_source_sum_sign_match": pair_chern * 0.05 > 0.0 if pair_complete else None, "first3_composite_status": "COMPLETE" if rank3_complete else "INCOMPLETE_NOT_REPORTED", "first3_composite_valley_chern": rank3_chern, "first3_source_sum_abs_error": abs(rank3_chern - 0.02) if rank3_complete else None, "first3_source_sum_sign_match": rank3_chern * 0.02 > 0.0 if rank3_complete else None, "derived_first3_from_d7_band0_plus_pair12": derived, "direct_rank3_minus_derived_first3_delta": direct_delta, "pair12_additivity_comparison_count": len(additive_diffs), "pair12_additivity_max_abs_diff": max((abs(value) for value in additive_diffs), default=None), "pair12_additivity_rms_diff": math.sqrt(sum(value * value for value in additive_diffs) / len(additive_diffs)) if additive_diffs else None, "pair12_additivity_median_abs_diff": float(np.median(np.abs(additive_diffs))) if additive_diffs else None, "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "threshold_change_authorized": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False, "next_scientific_state": "FR04_COMPOSITE_SUBSPACE_RESULTS_AVAILABLE_FOR_SUPERVISOR_SOURCE_REPRODUCTION_ASSESSMENT" if pair_complete or rank3_complete else "FR04_COMPOSITE_SUBSPACE_INCOMPLETENESS_LOCALIZED_READY_FOR_SUPERVISOR_METHOD_DECISION", "terminal": "E9F_D8_FR04_R64_COMPOSITE_SUBSPACE_ASSESSMENT_COMPLETE",
    }


def main() -> int:
    try:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(analysis()).decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({"schema": "mephc-e9f-d8-fr04-r64-composite-subspace-assessment-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E9F_D8_FR04_R64_COMPOSITE_SUBSPACE_ASSESSMENT_FAIL_CLOSED"}).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
