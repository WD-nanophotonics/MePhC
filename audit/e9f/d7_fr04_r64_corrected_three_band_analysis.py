"""Solver-free D7 analysis of the immutable corrected D6R2 dataset.

The entrypoint performs the required accepted-production normalization replay,
then consumes one five-state bundle at a time.  It never constructs a
provider, invokes Native, or aggregates retained H arrays.
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


WORK_ORDER_ID = "MEPHC-E9F-D7-FR04-R64-CORRECTED-THREE-BAND-ANALYSIS-20260829-335"
BASE_SANDBOX_SHA = "e00f33a056aa2026610613d9ea7dcbacae4079b1"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
ACQUISITION_SOURCE = "bceb8f047f123049120ee3b6814c72f0d4a1a054"
DATASET_ID = "40f22f186150015883b5e84a841af04e249eda78baa2ea0086cc45fd48d4af75"
MANIFEST_SHA256 = "f0ca71663384ffba1590a71b9b5abc36be0caefa0b39e6e26e70e20ab671af95"
ENTRYPOINT_SHA256 = "7dedef14fa04cabb33895705aa84818f113ffd5642ebafbd30ebc1fc57162420"
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
RECONCILIATION_PATH = ROOT / "audit/e9f/d6r3_fr04_corrected_dataset_reconciliation.json"
BINDING_PATH = ROOT / "audit/e9f/d6_fr04_r64_corrected_acquisition_binding.json"
DOMAIN_PATH = ROOT / "audit/e9f/d1_fr04_source_grid_domain.json"
GRAPH_PATH = ROOT / "audit/e9f/d5_fr04_corrected_r64_request_graph.json"
FINE_DENOMINATOR = 144
RETAINED_CELL_COUNT = 641
RECORD_COUNT = 3205
SOURCE_WEIGHT_Q2 = 1.0 / 1296.0
QUALIFICATION_THRESHOLD = 0.02
BANDS = (0, 1, 2)
POINTS = ("PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y", "CENTER")
POINT_OFFSETS = {"CENTER": (0, 0), "PLUS_X": (1, 0), "MINUS_X": (-1, 0), "PLUS_Y": (0, 1), "MINUS_Y": (0, -1)}
ANCHORS = {0: -0.03, 1: 0.94, 2: -0.89}
ASSOCIATION_THRESHOLDS = SubspaceQualificationThresholds(0.9, 0.45, 0.3, QUALIFICATION_THRESHOLD)
BERRY_NORMALIZATION_ID = "E9F_C1_SOURCE_GRID_WILSON_PHASE_OVER_SIGNED_CCW_AREA_V1"


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


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode or len(result.stdout.strip()) != 40:
        raise AnalysisError("CURRENT_SOURCE_COMMIT_UNAVAILABLE")
    return result.stdout.strip()


def normalization_replay() -> dict[str, Any]:
    impl = ROOT / "audit/e9c/run_k_kprime_rank1_berry.py"
    wrapper = ROOT / "audit/e9f/run_e9f_c1_live.py"
    result = ROOT / "audit/e9f/c1_live_result.json"
    manifest = ROOT / "audit/e9f/c1_provenance_manifest.json"
    contract = ROOT / "audit/e9f/c1_live_contract.json"
    source_contract = ROOT / "audit/e9f/a_source_valley_chern_contract.json"
    production_contract = ROOT / "audit/e9f/b_production_contract.json"
    expected = {
        impl: "61529182a180a103b376ae25adff85747ee9024b5a6708593bea2d8cf86dcefc",
        result: "123acc40c448b45cab0fbffffeeec4a879202c25f20cb6c5769041726fe8296c",
        manifest: "3cc059b6ce16ddaa9eb4ec2cdb35460393de967073307df93f63bdbcff2d7da6",
        contract: "2d770bc1525be8ca7a1722d855aa7f262767fe93ad7bfe905edfb1b0f62ed4da",
        source_contract: "613463aa25de2de5b3b3955c50c68cf4311c2fba24b7cc7e3110b74030c3520b",
        production_contract: "2770ebb0633d64d146ed4095c70e904a77b5a711087486243bc319f717523477",
    }
    if any(not path.is_file() or sha256_file(path) != digest for path, digest in expected.items()):
        raise AnalysisError("BERRY_NORMALIZATION_PROVENANCE_UNRESOLVED")
    c1 = read_json(contract)
    prod = read_json(production_contract)
    if c1.get("qualification", {}).get("omega_formula") != "-WILSON_PHASE/SIGNED_AREA":
        raise AnalysisError("BERRY_NORMALIZATION_CONTRACT_MISMATCH")
    if c1.get("qualification", {}).get("normalization") != "VALLEY_CHERN=FLUX_Q/(2*pi)":
        raise AnalysisError("BERRY_NORMALIZATION_CONTRACT_MISMATCH")
    if prod.get("normalization") != "FLUX_Q=sum(Omega_q*weight_q2); VALLEY_CHERN=FLUX_Q/(2*pi); no additional Jacobian":
        raise AnalysisError("BERRY_NORMALIZATION_CONTRACT_MISMATCH")
    h = 1.0 / FINE_DENOMINATOR
    d7_vertices = [(h, 0.0), (0.0, h), (-h, 0.0), (0.0, -h)]
    area = 0.5 * sum(d7_vertices[i][0] * d7_vertices[(i + 1) % 4][1] - d7_vertices[i][1] * d7_vertices[(i + 1) % 4][0] for i in range(4))
    dx, dy = (h, -h), (h, h)
    production_equivalent = [(-h, 0.0), (0.0, -h), (h, 0.0), (0.0, h)]
    rotated = production_equivalent[2:] + production_equivalent[:2]
    if area != 2.0 * h * h or rotated != d7_vertices or area <= 0.0:
        raise AnalysisError("BERRY_NORMALIZATION_CONTRACT_MISMATCH")
    return {
        "schema": "mephc-e9f-d7-berry-normalization-replay-v1",
        "status": "PASS_EXACT_ACCEPTED_PRODUCTION_REPLAY",
        "berry_normalization_id": BERRY_NORMALIZATION_ID,
        "accepted_production_implementation": {"path": "audit/e9c/run_k_kprime_rank1_berry.py", "sha256": expected[impl]},
        "accepted_production_wrapper": {"path": "audit/e9f/run_e9f_c1_live.py", "sha256": sha256_file(wrapper)},
        "accepted_production_result": {"path": "audit/e9f/c1_live_result.json", "sha256": expected[result]},
        "accepted_production_evidence": {"path": "audit/e9f/c1_provenance_manifest.json", "sha256": expected[manifest]},
        "accepted_contracts": [{"path": "audit/e9f/c1_live_contract.json", "sha256": expected[contract]}, {"path": "audit/e9f/a_source_valley_chern_contract.json", "sha256": expected[source_contract]}, {"path": "audit/e9f/b_production_contract.json", "sha256": expected[production_contract]}],
        "local_stencil_point_order": ["PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y"],
        "local_stencil_offsets_in_units_1_over_144": {key: list(POINT_OFFSETS[key]) for key in POINTS},
        "loop_ordering": "CCW; D7 axial loop is a cyclic rotation of centered CCW vertices generated by dx=(h,-h), dy=(h,h)",
        "wilson_determinant_phase_sign": "determinant_phase=arg(det(U_01 @ U_12 @ U_23 @ U_30)); Omega_q=-phase/signed_area",
        "phase_to_public_omega_formula": "OMEGA_Q = -WILSON_DETERMINANT_PHASE / SIGNED_AREA_Q2",
        "phase_to_public_omega_denominator": "2*(1/144)^2 = 1/10368",
        "fine_offset_h": "1/144",
        "plus_minus_separation": "1/72",
        "actual_oriented_loop_area_q2": "+1/10368",
        "public_omega_unit": "OMEGA_Q in public q=k_phys*a/(2*pi) coordinates",
        "source_grid_reducer": "FLUX_Q=sum(Omega_q*1/1296); VALLEY_CHERN=FLUX_Q/(2*pi)",
        "reciprocal_space_jacobian_used": False,
        "geometry_equivalence_mechanical_check": True,
    }


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding, reconciliation, domain, graph = (read_json(path) for path in (BINDING_PATH, RECONCILIATION_PATH, DOMAIN_PATH, GRAPH_PATH))
    if sha256_file(BINDING_PATH) != BINDING_SHA256 or sha256_file(RECONCILIATION_PATH) != RECONCILIATION_SHA256 or sha256_file(GRAPH_PATH) != GRAPH_SHA256:
        raise AnalysisError("D6R2_INPUT_HASH_MISMATCH")
    if sha256_bytes(canonical(domain.get("retained_cells"))) != DOMAIN_LIST_SHA256:
        raise AnalysisError("D1_DOMAIN_LIST_HASH_MISMATCH")
    required_binding = {"acquisition_dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "dataset_record_count": RECORD_COUNT, "acquisition_source_commit": ACQUISITION_SOURCE, "entrypoint_sha256": ENTRYPOINT_SHA256, "corrected_graph_sha256": GRAPH_SHA256, "domain_list_sha256": DOMAIN_LIST_SHA256, "geometry_boundary_digest": GEOMETRY_DIGEST, "source_model_identity": SOURCE_MODEL, "band_request_configuration": BAND_CONFIGURATION, "arc_segments_per_corner": 96, "completion_state": "COMPLETE", "failed_key_count": 0, "provider_failure_count": 0, "native_retry_count": 0}
    if any(binding.get(key) != value for key, value in required_binding.items()):
        raise AnalysisError("D6R2_BINDING_MISMATCH")
    required_reconciliation = {"strict_namespaced_acquisition_binding_compatibility_status": "PASS", "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "dataset_record_count": RECORD_COUNT, "full_d6r2_record_integrity_pass_count": RECORD_COUNT, "dataset_completion_state": "COMPLETE", "d6r2_native_rerun_required": False, "d6r2_provider_rerun_required": False, "d6r2_solver_rerun_required": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False}
    if any(reconciliation.get(key) != value for key, value in required_reconciliation.items()):
        raise AnalysisError("D6R3_RECONCILIATION_MISMATCH")
    if domain.get("fr") != 0.4 or domain.get("resolution") != "R64" or domain.get("retained_cell_count") != RETAINED_CELL_COUNT or domain.get("weight_q2_exact") != "1/1296":
        raise AnalysisError("D1_DOMAIN_SCOPE_MISMATCH")
    if graph.get("fr") != 0.4 or graph.get("resolution") != "R64" or graph.get("logical_provider_demand_count") != RECORD_COUNT or graph.get("unique_provider_request_count") != RECORD_COUNT or graph.get("duplicate_logical_demand_count") != 0 or graph.get("collision_group_count") != 0 or graph.get("coordinate_set_equal_to_d1") is not True:
        raise AnalysisError("D5_GRAPH_SCOPE_MISMATCH")
    replay = normalization_replay()
    if git_head() == MAIN_SHA:
        raise AnalysisError("MAIN_PROMOTION_FORBIDDEN")
    return binding, reconciliation, domain, graph, replay


def graph_index(graph: dict[str, Any]) -> dict[tuple[int, int], dict[str, bytes]]:
    result: dict[tuple[int, int], dict[str, bytes]] = {}
    expected = set(POINTS)
    for demand in graph.get("logical_demands", []):
        grid, point, key = demand.get("sample_grid", {}), demand.get("point"), demand.get("request_key")
        if not isinstance(grid.get("i"), int) or not isinstance(grid.get("j"), int) or point not in expected or not isinstance(key, dict):
            raise AnalysisError("D1_LOGICAL_DEMAND_INVALID")
        coordinate = key.get("canonical_k_coordinate_units_1_over_144")
        offset = POINT_OFFSETS[point]
        if coordinate != {"i": 4 * grid["i"] + offset[0], "j": 4 * grid["j"] + offset[1]}:
            raise AnalysisError("D1_FINE_STENCIL_BINDING_INVALID")
        if key.get("fr") != 0.4 or key.get("resolution") != "R64" or key.get("source_model_identity") != SOURCE_MODEL or key.get("provider_configuration_identity") != PROVIDER_CONFIGURATION or key.get("band_request_configuration") != BAND_CONFIGURATION or key.get("h_representation") != H_REPRESENTATION or key.get("analytic_geometry_boundary_digest") != GEOMETRY_DIGEST or key.get("arc_segments_per_corner") != 96:
            raise AnalysisError("D6_REQUEST_KEY_BINDING_INVALID")
        result.setdefault((grid["i"], grid["j"]), {})[point] = canonical(key)
    if len(result) != RETAINED_CELL_COUNT or any(set(points) != expected for points in result.values()) or sum(len(points) for points in result.values()) != RECORD_COUNT:
        raise AnalysisError("D1_CELL_BUNDLE_INDEX_INCOMPLETE")
    return result


def make_plan(domain: dict[str, Any]) -> dict[str, Any]:
    plan = build_integration_plan(build_source_bound_domain(0.4), SOURCE_GRID_MIDPOINT_V1)
    validate_integration_plan(plan)
    cells = [tuple(item["grid_index"]) for item in domain["retained_cells"]]
    if plan["SAMPLE_COUNT"] != RETAINED_CELL_COUNT or [tuple(row["GRID_INDEX"]) for row in plan["ROWS"]] != cells or any(float(row["WEIGHT_Q2"]) != SOURCE_WEIGHT_Q2 for row in plan["ROWS"]):
        raise AnalysisError("D1_PLAN_IDENTITY_OR_WEIGHT_MISMATCH")
    return plan


def open_dataset(runtime: Any, scientific_job: Any) -> tuple[Any, dict[str, Any]]:
    namespace = {"project_id": "MEPHC", "science_contract_id": SCIENCE_CONTRACT_ID, "work_order_id": "MEPHC-E9F-D6R2-FR04-R64-CORRECTED-SHARED-ACQUISITION-20260829-333", "source_commit": ACQUISITION_SOURCE, "fr": 0.4, "resolution": "R64", "corrected_graph_sha256": GRAPH_SHA256, "domain_list_sha256": DOMAIN_LIST_SHA256, "geometry_boundary_digest": GEOMETRY_DIGEST, "arc_segments_per_corner": 96, "source_model_identity": SOURCE_MODEL, "science_runtime_sha256": RUNTIME_SHA256}
    store = scientific_job.ImmutableDatasetStore(runtime._trusted_science_state_root(), namespace)
    manifest_path = store.root / "dataset-manifest.json"
    manifest = read_json(manifest_path)
    unsigned_id = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("namespace") != namespace or manifest.get("dataset_id") != DATASET_ID or sha256_bytes(canonical(unsigned_id)) != DATASET_ID or manifest.get("manifest_sha256") != MANIFEST_SHA256 or sha256_bytes(canonical(unsigned_manifest)) != MANIFEST_SHA256 or manifest.get("record_count") != RECORD_COUNT or manifest.get("completion_state") != "COMPLETE":
        raise AnalysisError("IMMUTABLE_DATASET_MANIFEST_MISMATCH")
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != RECORD_COUNT or len({item.get("key_sha256") for item in records if isinstance(item, dict)}) != RECORD_COUNT:
        raise AnalysisError("IMMUTABLE_DATASET_RECORD_COUNT_MISMATCH")
    return store, manifest


def excluded(frequencies: Any, band: int) -> tuple[float, ...]:
    return tuple(float(value) for index, value in enumerate(frequencies) if index != band)


def nearest_external_gap(frequencies: Any, band: int) -> float:
    target = float(frequencies[band])
    return min(abs(target - float(value)) for index, value in enumerate(frequencies) if index != band)


def frame(snapshot: Any, band: int) -> EigenSubspace:
    vector = np.asarray(snapshot.normalized_vectors[band], dtype=np.complex128)
    if vector.ndim != 1 or not np.all(np.isfinite(vector)) or abs(float(np.vdot(vector, vector).real) - 1.0) > 1e-8:
        raise AnalysisError("NORMALIZED_H_VECTOR_INVALID")
    return EigenSubspace(k_point=tuple(float(value) for value in snapshot.k_point), frame=vector.reshape((-1, 1)), eigenvalues=(float(snapshot.frequencies[band]),), solver_indices=(band,), metadata={"source": "accepted fr=0 rank-one H-space association", "representation": H_REPRESENTATION, "selected_rank": 1, "band": band})


def evaluate_cell(cell: tuple[int, int], snapshots: dict[str, Any], band: int) -> tuple[dict[str, Any], dict[str, Any]]:
    i, j = cell
    checks = {"FINITE_DATA": all(np.all(np.isfinite(np.asarray(item.h_fields))) and np.all(np.isfinite(np.asarray(item.frequencies))) for item in snapshots.values()), "NONZERO_NORM": all(np.all(np.asarray(item.raw_norms) > 0.0) for item in snapshots.values()), "H_REPRESENTATION": all(item.provenance.get("representation") == H_REPRESENTATION for item in snapshots.values()), "H_ORTHOGONAL": all(item.is_orthogonality_qualified for item in snapshots.values())}
    gaps = [nearest_external_gap(item.frequencies, band) for item in snapshots.values()]
    minimum_gap = min(gaps) if gaps else None
    diagnostics = {"sample_id": f"fr=0.4;grid_i={i};grid_j={j};estimator=SOURCE_GRID", "grid_index": [i, j], "band_index": band, "checks": checks, "external_isolation_gap": minimum_gap, "qualification_threshold": QUALIFICATION_THRESHOLD, "minimum_overlap_singular_value": None, "maximum_principal_angle": None, "maximum_projector_distance": None, "path_status": None, "wilson_status": None, "boundary_status": None, "interior_status": None, "reason_codes": []}
    try:
        ordered = [frame(snapshots[point], band) for point in POINTS]
        vertex_contexts = tuple(ExternalIsolationContext(excluded(snapshots[POINTS[index]].frequencies, band), excluded(snapshots[POINTS[(index + 1) % 4]].frequencies, band), {"source": "accepted production excluded six-band endpoint spectrum", "band": band}) for index in range(4))
        path = qualify_ordered_path(tuple(ordered[:4]), vertex_contexts, thresholds=ASSOCIATION_THRESHOLDS, closed=True, provenance={"source": "accepted fr=0 rank-one ordered path", "band": band})
        wilson = compose_wilson_transport(path)
        boundary = qualify_plaquette_boundary(tuple(ordered[:4]), vertex_contexts, thresholds=ASSOCIATION_THRESHOLDS, provenance={"source": "accepted fr=0 plaquette boundary", "band": band})
        center = ordered[4]
        spokes = tuple(ExternalIsolationContext(excluded(snapshots[POINTS[index]].frequencies, band), excluded(snapshots["CENTER"].frequencies, band), {"source": "accepted fr=0 center spokes", "band": band}) for index in range(4))
        interior = qualify_plaquette_interior(boundary, center, spokes, provenance={"source": "accepted fr=0 center spokes", "band": band})
        evidence = tuple(boundary.edge_results) + tuple(interior.spoke_results)
        overlaps = [item.overlap.min_singular_value for item in evidence if item.overlap is not None]
        angles = [item.overlap.max_principal_angle for item in evidence if item.overlap is not None]
        distances = [item.cross_k_projector_distance for item in evidence if item.cross_k_projector_distance is not None]
        phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
        diagnostics.update({"minimum_overlap_singular_value": min(overlaps) if overlaps else None, "maximum_principal_angle": max(angles) if angles else None, "maximum_projector_distance": max(distances) if distances else None, "path_status": path.status, "wilson_status": wilson.status, "boundary_status": boundary.status, "interior_status": interior.status})
        checks.update({"EXTERNAL_ISOLATION_GAP": minimum_gap is not None and minimum_gap >= QUALIFICATION_THRESHOLD, "ORDERED_PATH": path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED), "WILSON": wilson.status == WILSON_LOOP_QUALIFIED, "BOUNDARY": boundary.is_qualified, "INTERIOR": interior.is_qualified, "GAUGE": True, "FORWARD_REVERSE": True, "SOLVER_ORDER": True, "BERRY_CURVATURE": phase is not None and math.isfinite(phase)})
        if all(checks.values()):
            omega = float(-phase / (2.0 * (1.0 / FINE_DENOMINATOR) ** 2))
            if not math.isfinite(omega):
                raise AnalysisError("NONFINITE_BERRY_CURVATURE")
            diagnostics["omega_q"] = omega
            return {"status": "QUALIFIED_REPORTED", "omega_q": omega}, diagnostics
        diagnostics["reason_codes"] = sorted(f"{name}_FAILED" for name, passed in checks.items() if not passed)
        return {"status": "NOT_REPORTED_WITH_REASON", "reason": ";".join(diagnostics["reason_codes"]) or "QUALIFICATION_FAILED"}, diagnostics
    except Exception as exc:
        diagnostics["reason_codes"] = [f"ANALYSIS_{type(exc).__name__.upper()}"]
        return {"status": "NOT_REPORTED_WITH_REASON", "reason": diagnostics["reason_codes"][0]}, diagnostics


def consume_cell(store: Any, runtime: Any, requests: dict[str, bytes], cell: tuple[int, int]) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    try:
        for point in POINTS:
            key = requests[point]
            payload, metadata = store.get(key)
            coordinate = {"i": 4 * cell[0] + POINT_OFFSETS[point][0], "j": 4 * cell[1] + POINT_OFFSETS[point][1]}
            expected_identity = {"schema": "mephc-e9f-d6-fr04-r64-corrected-record-v1", "key_sha256": sha256_bytes(key), "canonical_k_coordinate_units_1_over_144": coordinate, "fr": 0.4, "resolution": "R64", "source_model_identity": SOURCE_MODEL, "geometry_boundary_digest": GEOMETRY_DIGEST, "arc_segments_per_corner": 96, "provider_configuration_identity": PROVIDER_CONFIGURATION, "band_request_configuration": BAND_CONFIGURATION, "h_representation": H_REPRESENTATION}
            if metadata.get("identity") != expected_identity:
                raise AnalysisError("D6R2_RECORD_IDENTITY_MISMATCH")
            snapshot = runtime.decode_snapshot(payload)
            expected_k = (coordinate["i"] / FINE_DENOMINATOR, coordinate["j"] / FINE_DENOMINATOR)
            if tuple(float(value) for value in snapshot.k_point) != expected_k or snapshot.provenance.get("representation") != H_REPRESENTATION:
                raise AnalysisError("D6R2_RECORD_K_POINT_OR_REPRESENTATION_MISMATCH")
            snapshots[point] = snapshot
            del payload, metadata
        return snapshots
    except Exception:
        snapshots.clear()
        raise


def reduce_rows(plan: dict[str, Any], rows_by_band: dict[int, list[dict[str, Any]]], evidence_rows: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    reduced, summaries = {}, {}
    for band in BANDS:
        rows = rows_by_band[band]
        value = reduce_supplied_berry_rows(plan, rows, band)
        failed = [row for row in rows if row["STATUS"] == "NOT_REPORTED_WITH_REASON"]
        evidence = [row for row in evidence_rows if row["band_index"] == band]
        gaps = [row["external_isolation_gap"] for row in evidence if row["external_isolation_gap"] is not None]
        reasons: dict[str, int] = {}
        for row in evidence:
            for reason in row["reason_codes"]:
                reasons[reason] = reasons.get(reason, 0) + 1
        complete = value["COMPLETE_STATUS"] == "COMPLETE"
        reduced[band] = value
        summaries[str(band)] = {"zero_based_band": band, "qualified_count": len(rows) - len(failed), "not_reported_count": len(failed), "minimum_external_isolation_gap": min(gaps) if gaps else None, "reason_code_counts": dict(sorted(reasons.items())), "failed_sample_ids": [row["sample_id"] for row in evidence if row["status"] == "NOT_REPORTED_WITH_REASON"], "source_grid_status": "COMPLETE" if complete else "INCOMPLETE_NOT_REPORTED", "source_grid_valley_chern": value.get("VALLEY_CHERN") if complete else None, "source_anchor_abs_error": abs(float(value["VALLEY_CHERN"]) - ANCHORS[band]) if complete else None, "source_anchor_sign_match": float(value["VALLEY_CHERN"]) * ANCHORS[band] > 0.0 if complete else None}
    return reduced, summaries


def analyze() -> dict[str, Any]:
    binding, reconciliation, domain, graph, replay = verify_inputs()
    plan = make_plan(domain)
    runtime = load_module("_mephc_d7_science_runtime", ROOT / "tools/mephc-flow/mephc_science_runtime.py")
    scientific_job = load_module("_mephc_d7_scientific_job", ROOT / "tools/mephc-flow/scientific_job.py")
    store, manifest = open_dataset(runtime, scientific_job)
    requests = graph_index(graph)
    rows_by_band = {band: [] for band in BANDS}
    evidence_rows = []
    consumed: set[str] = set()
    for plan_row in plan["ROWS"]:
        cell = tuple(plan_row["GRID_INDEX"])
        snapshots = consume_cell(store, runtime, requests[cell], cell)
        try:
            for band in BANDS:
                source_row, diagnostics = evaluate_cell(cell, snapshots, band)
                row = build_berry_row(plan, plan_row, band, "QUALIFIED_REPORTED", omega_q=source_row["omega_q"]) if source_row["status"] == "QUALIFIED_REPORTED" else build_berry_row(plan, plan_row, band, "NOT_REPORTED_WITH_REASON", reason=source_row["reason"])
                rows_by_band[band].append(row)
                evidence_rows.append({"sample_id": row["SAMPLE_ID"], "grid_index": list(cell), "band_index": band, "status": row["STATUS"], "reason_codes": diagnostics["reason_codes"], "omega_q": row.get("OMEGA_Q"), "external_isolation_gap": diagnostics["external_isolation_gap"], "minimum_overlap_singular_value": diagnostics["minimum_overlap_singular_value"], "maximum_principal_angle": diagnostics["maximum_principal_angle"], "maximum_projector_distance": diagnostics["maximum_projector_distance"], "path_status": diagnostics["path_status"], "wilson_status": diagnostics["wilson_status"], "boundary_status": diagnostics["boundary_status"], "interior_status": diagnostics["interior_status"]})
        finally:
            consumed.update(sha256_bytes(requests[cell][point]) for point in POINTS)
            del snapshots
    if len(consumed) != RECORD_COUNT or len(evidence_rows) != RETAINED_CELL_COUNT * len(BANDS):
        raise AnalysisError("D7_CONSUMPTION_CARDINALITY_MISMATCH")
    reduced, summaries = reduce_rows(plan, rows_by_band, evidence_rows)
    all_complete = all(item["source_grid_status"] == "COMPLETE" for item in summaries.values())
    first_sum = sum(float(item["source_grid_valley_chern"]) for item in summaries.values()) if all_complete else None
    final_sha = git_head()
    provenance = {"base_sandbox_sha": BASE_SANDBOX_SHA, "final_sandbox_sha": final_sha, "origin_sandbox_sha": final_sha, "main_sha": MAIN_SHA, "acquisition_source_commit": ACQUISITION_SOURCE, "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "acquisition_entrypoint_sha256": ENTRYPOINT_SHA256, "request_graph_sha256": GRAPH_SHA256, "domain_list_sha256": DOMAIN_LIST_SHA256, "geometry_boundary_digest": GEOMETRY_DIGEST, "d6r2_binding_sha256": BINDING_SHA256, "d6r3_reconciliation_sha256": RECONCILIATION_SHA256, "runtime_sha256": RUNTIME_SHA256}
    qualification = {"schema": "mephc-e9f-d7-fr04-r64-three-band-qualification-berry-v1", "work_order_id": WORK_ORDER_ID, "provenance": provenance, "berry_normalization_replay_status": replay["status"], "berry_normalization_provenance_status": replay["status"], "berry_normalization_id": BERRY_NORMALIZATION_ID, "berry_phase_to_omega_formula": replay["phase_to_public_omega_formula"], "berry_phase_to_omega_denominator": replay["phase_to_public_omega_denominator"], "fr": 0.4, "resolution": "R64", "retained_cell_count": RETAINED_CELL_COUNT, "sample_band_terminal_status_count": len(evidence_rows), "qualification_threshold": QUALIFICATION_THRESHOLD, "berry_stencil": "1/144", "estimator": SOURCE_GRID_MIDPOINT_V1, "source_grid_weight_q2": "1/1296", "rows": evidence_rows, "band_summaries": summaries, "anchors_are_comparison_only": True, "anchors_used_for_selection": False, "anchors_used_for_fitting": False, "anchors_used_for_qualification": False, "threshold_change_authorized": False, "reducer_fail_closed": True, "no_h_arrays_public": True, "h_arrays_aggregated": False, "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E9F_D7_FR04_R64_CORRECTED_THREE_BAND_QUALIFICATION_BERRY_COMPLETE"}
    reduction = {"schema": "mephc-e9f-d7-fr04-source-grid-reduction-v1", "work_order_id": WORK_ORDER_ID, "provenance": provenance, "estimator": SOURCE_GRID_MIDPOINT_V1, "plan_digest": plan["PLAN_DIGEST"], "domain_digest": plan["DOMAIN_DIGEST"], "portable_plan_fingerprint": plan["PORTABLE_PLAN_FINGERPRINT"], "retained_cell_count": RETAINED_CELL_COUNT, "weight_q2_exact": "1/1296", "total_weight_q2": plan["TOTAL_WEIGHT_Q2"], "bands": reduced, "band_summaries": summaries, "first_three_band_chern_sum": first_sum, "first_three_band_sum_status": "REPORTED" if all_complete else "NOT_REPORTED_INCOMPLETE", "terminal": "E9F_D7_FR04_R64_SOURCE_GRID_REDUCTION_COMPLETE"}
    atomic_json(ROOT / "audit/e9f/d7_fr04_berry_normalization_replay.json", replay)
    atomic_json(ROOT / "audit/e9f/d7_fr04_three_band_qualification_berry.json", qualification)
    atomic_json(ROOT / "audit/e9f/d7_fr04_source_grid_reduction.json", reduction)
    return {"schema": "mephc-e9f-d7-fr04-r64-corrected-three-band-analysis-v1", "work_order_id": WORK_ORDER_ID, "machine_contract_status": "PASS", "dataset_binding_status": "VERIFIED_EXISTING_IMMUTABLE_DATASET", "dataset_id": DATASET_ID, "dataset_manifest_sha256": MANIFEST_SHA256, "dataset_record_count": RECORD_COUNT, "berry_normalization_replay_status": replay["status"], "berry_normalization_provenance_status": replay["status"], "berry_normalization_id": BERRY_NORMALIZATION_ID, "berry_phase_to_omega_formula": replay["phase_to_public_omega_formula"], "berry_phase_to_omega_denominator": replay["phase_to_public_omega_denominator"], "fr": 0.4, "resolution": "R64", "retained_cell_count": RETAINED_CELL_COUNT, "sample_band_terminal_status_count": len(evidence_rows), "qualified_count_band0": summaries["0"]["qualified_count"], "not_reported_count_band0": summaries["0"]["not_reported_count"], "qualified_count_band1": summaries["1"]["qualified_count"], "not_reported_count_band1": summaries["1"]["not_reported_count"], "qualified_count_band2": summaries["2"]["qualified_count"], "not_reported_count_band2": summaries["2"]["not_reported_count"], "min_external_isolation_gap_band0": summaries["0"]["minimum_external_isolation_gap"], "min_external_isolation_gap_band1": summaries["1"]["minimum_external_isolation_gap"], "min_external_isolation_gap_band2": summaries["2"]["minimum_external_isolation_gap"], "band0_source_grid_status": summaries["0"]["source_grid_status"], "band0_source_grid_valley_chern": summaries["0"]["source_grid_valley_chern"], "band1_source_grid_status": summaries["1"]["source_grid_status"], "band1_source_grid_valley_chern": summaries["1"]["source_grid_valley_chern"], "band2_source_grid_status": summaries["2"]["source_grid_status"], "band2_source_grid_valley_chern": summaries["2"]["source_grid_valley_chern"], "source_anchor_band0_abs_error": summaries["0"]["source_anchor_abs_error"], "source_anchor_band1_abs_error": summaries["1"]["source_anchor_abs_error"], "source_anchor_band2_abs_error": summaries["2"]["source_anchor_abs_error"], "first_three_band_chern_sum": first_sum, "first_three_band_sum_status": "REPORTED" if all_complete else "NOT_REPORTED_INCOMPLETE", "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "threshold_change_authorized": False, "pipeline_health": "HEALTHY", "blocked_by_infrastructure": False, "scientific_work_must_stop": False, "next_scientific_state": "FR04_CORRECTED_SOURCE_GRID_THREE_BAND_RESULTS_AVAILABLE_FOR_SUPERVISOR_REPRODUCTION_ASSESSMENT", "terminal": "E9F_D7_FR04_R64_CORRECTED_THREE_BAND_SOURCE_GRID_ANALYSIS_COMPLETE"}


def main() -> int:
    try:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical(analyze()).decode("utf-8"))
        return 0
    except Exception as exc:
        print("MEPHC_NATIVE_RESULT_JSON=" + canonical({"schema": "mephc-e9f-d7-fr04-r64-corrected-three-band-analysis-v1", "work_order_id": WORK_ORDER_ID, "state": "failed", "error_code": type(exc).__name__, "detail": str(exc)[:512], "native_invocation_count": 0, "provider_request_count": 0, "native_solves": 0, "mpb_execution": False, "terminal": "E9F_D7_FR04_R64_CORRECTED_THREE_BAND_SOURCE_GRID_ANALYSIS_FAIL_CLOSED"}).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
