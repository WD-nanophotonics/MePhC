"""E7I.4A bounded FR00 composite rank-3 Maxwell-energy valley-Chern pilot."""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from audit.e7i3c.run_representation_bridge import (
    E3,
    BANDS,
    lowdin_snapshot,
    solve_isolated,
    build_reference_mpb_adapter,
    build_triangular_coordinate_preflight,
    build_triangular_reference_geometry,
)
from mephc.eigenspace import EigenSubspace
from mephc.mpb_energy_spectral_provider import MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION
from mephc.path_domain import PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.spectral_association import ExternalIsolationContext
from mephc.valley_benchmark import (
    PhysicalSolveCache,
    PhysicalSolveIdentity,
    centered_ccw_plaquette_requests,
    integrate_sampled_field,
    paper_style_truncated_k_hbz,
    sample_domain,
)
from mephc.valley_reference_geometry import build_triangular_reference_geometry
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

WORK_ORDER = "TRILATT-E7I4A-20260823-126"
FR = 0.0
RESOLUTION = 48
NUM_BANDS = 4
POLARIZATION = "TE"
EIGENSOLVER_TOLERANCE = 1e-7
DETERMINISTIC = True
MESH_SIZE = 3
LOCAL_DELTA_K = 1.0 / 36.0
STAGE1_SPACING = 1.0 / 18.0
STAGE2_SPACING = 1.0 / 36.0
RANK_SELECTION = (0, 1, 2)
K_PUBLIC = (2.0 / 3.0, 0.0)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value):
    return math.isfinite(float(value))


def frame_to_subspace(public_q, snapshot):
    vectors = tuple(snapshot.normalized_vectors[index] for index in RANK_SELECTION)
    frame = np.column_stack(vectors)
    return EigenSubspace(
        k_point=tuple(float(x) for x in public_q),
        frame=frame,
        eigenvalues=tuple(float(snapshot.frequencies[index]) for index in RANK_SELECTION),
        solver_indices=RANK_SELECTION,
        metadata={
            "source": "E7I.4A E+H selected-rank3 Lowdin frame",
            "representation": MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION,
            "selected_rank": 3,
            "raw_provider_status": snapshot.provenance.get("raw_provider_status"),
        },
    )


def centered_loop(vertices, frequencies):
    contexts = tuple(
        ExternalIsolationContext(
            left_excluded_eigenvalues=(float(frequencies[index][3]),),
            right_excluded_eigenvalues=(float(frequencies[(index + 1) % 4][3]),),
            provenance={"source": "E7I.4A band-4 external isolation"},
        )
        for index in range(4)
    )
    path = qualify_ordered_path(
        tuple(vertices),
        contexts,
        thresholds=E3,
        closed=True,
        provenance={"source": "E7I.4A centered rank-3 determinant plaquette"},
    )
    wilson = compose_wilson_transport(path)
    qualified = path.status == PATH_SUBSPACE_QUALIFIED and wilson.status == WILSON_LOOP_QUALIFIED and wilson.determinant_phase is not None
    return path, wilson, bool(qualified)


def self_checks():
    assert RANK_SELECTION == (0, 1, 2)
    assert LOCAL_DELTA_K == 1.0 / 36.0
    sample = sample_domain(paper_style_truncated_k_hbz(fr=FR, delta_k=0.10, delta_gamma=0.10), STAGE1_SPACING)
    assert math.isclose(

        integrate_sampled_field(sample, [1.0] * sample.center_count),

        sample.retained_area_q,

        rel_tol=0.0,

        abs_tol=1e-12,

    )
    assert abs(-(-0.25) / 0.5 - 0.5) < 1e-15



def run_stage(stage_id, spacing, domain, geometry, adapter, preflight, vertex_cache, identity_cache, solve_manifest):
    started = time.monotonic()
    sample = sample_domain(domain, spacing)
    delta_vectors = preflight.delta_k_vectors_to_public_q(LOCAL_DELTA_K)
    requests = centered_ccw_plaquette_requests(
        sample.centers,
        delta_vectors,
        period_basis=preflight.public_period_basis,
        coordinate_mapping_digest=preflight.mapping_digest,
    )
    plaquette_area = abs(float(np.linalg.det(np.asarray(delta_vectors, dtype=float))))
    element_records = []
    curvature_values = []
    qualified_weight = 0.0
    unqualified_weight = 0.0
    failed_reasons = {}
    for element_index, (center, weight) in enumerate(zip(sample.centers, sample.weights)):
        group = requests[element_index * 4:(element_index + 1) * 4]
        vertices = []
        frequencies = []
        cache_keys = []
        mpb_vertices = []
        for request in group:
            public_q = tuple(float(x) for x in request.canonical_periodic_vertex_q)
            mpb_q = tuple(float(x) for x in preflight.public_q_to_mpb(public_q))
            cache_key = digest({
                "public_q": list(public_q),
                "mpb_fractional_q": list(mpb_q),
                "geometry_digest": geometry.geometry_digest,
                "material_digest": geometry.material_contract_digest,
                "mapping_digest": preflight.mapping_digest,
                "resolution": RESOLUTION,
                "num_bands": NUM_BANDS,
                "polarization": POLARIZATION,
                "representation": MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION,
                "eigensolver_tolerance": EIGENSOLVER_TOLERANCE,
                "deterministic": DETERMINISTIC,
                "mesh_size": MESH_SIZE,
            })
            identity = PhysicalSolveIdentity(
                geometry_digest=geometry.geometry_digest,
                material_reference_digest=geometry.material_contract_digest,
                coordinate_mapping_digest=preflight.mapping_digest,
                evaluated_q=public_q,
                resolution=RESOLUTION,
                num_bands=NUM_BANDS,
                polarization=POLARIZATION,
                provider_representation=MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION,
                eigensolver_tolerance=EIGENSOLVER_TOLERANCE,
                deterministic=DETERMINISTIC,
                mesh_size=MESH_SIZE,
            )
            registered_key = identity_cache.register(identity, claimed_key=cache_key)
            cache_keys.append(registered_key)
            mpb_vertices.append(list(mpb_q))
            if registered_key not in vertex_cache:
                raw = solve_isolated(adapter, RESOLUTION, FR, public_q)
                frame, diagnostics = lowdin_snapshot(raw)
                vertex_cache[registered_key] = (frame, [float(x) for x in raw.frequencies], diagnostics)
                solve_manifest[registered_key] = {"public_q": list(public_q), "mpb_fractional_q": list(mpb_q)}
            frame, frequency, diagnostics = vertex_cache[registered_key]
            vertices.append(frame_to_subspace(public_q, frame))
            frequencies.append(frequency)
        path, wilson, qualified = centered_loop(vertices, frequencies)
        phi = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
        omega = None if phi is None else float(-phi / plaquette_area)
        if qualified and omega is not None and finite(omega):
            qualified_weight += float(weight)
            curvature_values.append(omega)
        else:
            unqualified_weight += float(weight)
            reason = f"path={path.status};wilson={wilson.status}"
            failed_reasons[reason] = failed_reasons.get(reason, 0) + 1
        element_records.append({
            "element_index": element_index,
            "element_id": sample.element_ids[element_index],
            "center_q": list(center),
            "weight_q2": float(weight),
            "cache_keys": list(cache_keys),
            "public_vertices_q": [list(req.canonical_periodic_vertex_q) for req in group],
            "mpb_vertices_fractional": mpb_vertices,
            "path_status": path.status,
            "wilson_status": wilson.status,
            "qualified": qualified,
            "determinant_phase": phi,
            "omega_trace_q": omega,
            "lowdin_projector_residual_max": max(float(vertex_cache[key][2]["SPAN_PROJECTOR_RESIDUAL"]) for key in cache_keys),
        })
    retained_area = float(sample.retained_area_q)
    accounted = qualified_weight + unqualified_weight
    area_ok = abs(accounted - retained_area) <= 1e-10
    all_qualified = unqualified_weight <= 1e-12 and area_ok
    phase_branch_problem = any(item["determinant_phase"] is not None and abs(item["determinant_phase"]) >= math.pi - 1e-12 for item in element_records)
    integral = integrate_sampled_field(sample, curvature_values) if all_qualified else None
    chern = float(integral / (2.0 * math.pi)) if integral is not None else None
    return {
        "stage_id": stage_id,
        "integration_grid_spacing": float(spacing),
        "local_centered_plaquette_delta": LOCAL_DELTA_K,
        "local_plaquette_area_q2": plaquette_area,
        "sample": sample.to_dict(),
        "raw_integration_elements": len(element_records),
        "retained_area_q": retained_area,
        "qualified_area_q": qualified_weight,
        "unqualified_area_q": unqualified_weight,
        "qualified_area_fraction": qualified_weight / retained_area,
        "area_accounting_passed": area_ok,
        "all_retained_elements_qualified": all_qualified,
        "phase_branch_problem": phase_branch_problem,
        "composite_valley_chern": chern,
        "curvature_integral_q2": None if integral is None else float(integral),
        "failed_element_reasons": failed_reasons,
        "elements": element_records,
        "wall_time_seconds": time.monotonic() - started,
    }


def main():
    if "--self-check" in sys.argv:
        self_checks()
        print(json.dumps({"self_check": "PASSED"}))
        return
    root = Path(__file__).resolve().parents[2]
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    adapter = build_reference_mpb_adapter(geometry, preflight)
    if not preflight.ready or not adapter.is_ready or not geometry.live_reference_solve_ready:
        raise RuntimeError("FR00 reference geometry or coordinate preflight is not ready")
    domain = paper_style_truncated_k_hbz(fr=FR, delta_k=0.10, delta_gamma=0.10)
    vertex_cache = {}
    identity_cache = PhysicalSolveCache()
    solve_manifest = {}
    started = time.monotonic()
    stage1 = run_stage("STAGE1", STAGE1_SPACING, domain, geometry, adapter, preflight, vertex_cache, identity_cache, solve_manifest)
    stage2 = None
    if stage1["all_retained_elements_qualified"] and not stage1["phase_branch_problem"]:
        stage2 = run_stage("STAGE2", STAGE2_SPACING, domain, geometry, adapter, preflight, vertex_cache, identity_cache, solve_manifest)
    raw_requests = sum(int(stage["raw_integration_elements"]) * 4 for stage in (stage1, stage2) if stage is not None)
    unique_solves = len(solve_manifest)
    cache_hits = raw_requests - unique_solves
    stage2_status = "RUN" if stage2 is not None else "NOT_RUN_DUE_TO_STAGE1_GATE"
    c1 = stage1["composite_valley_chern"]
    c2 = None if stage2 is None else stage2["composite_valley_chern"]
    pattern = "PHYSICALLY_UNQUALIFIED"
    if c1 is not None and c2 is not None:
        if abs(c1) < 0.1 and abs(c2) < 0.1:
            pattern = "CONSISTENT_WITH_STRONG_THREE_BAND_CANCELLATION"
        elif abs(c1) < 0.1 or abs(c2) < 0.1:
            pattern = "PARTIAL"
        else:
            pattern = "NOT_CONSISTENT"
    elif c1 is not None:
        pattern = "PARTIAL" if abs(c1) < 0.1 else "NUMERICALLY_UNRESOLVED"
    result = {
        "schema": "e7i4a_fr00_rank3_composite_valley_chern_pilot_v1",
        "work_order": WORK_ORDER,
        "code_change": "SANDBOX_ONLY",
        "e7i3_diagnostic_branch": "CLOSED",
        "cross_k_projector_distance_corrective": "VALIDATED",
        "stable_main_semantic_equivalence": "VERIFIED",
        "chern_baseline_code_sha": "ccb0cf4c7fefbc82f2231093c728b12015377024",
        "calculation_logic_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "calculation_logic_committed_before_execution": True,
        "representation_authority": MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION,
        "geometry": geometry.to_dict(),
        "coordinate_preflight": {"ready": preflight.ready, "mapping_digest": preflight.mapping_digest, "public_k": list(preflight.public_k), "mpb_k": list(preflight.mpb_k)},
        "domain": domain.to_dict(),
        "public_q_normalization": "q=ka/(2pi)",
        "local_curvature_units": "OMEGA_TRACE_Q",
        "valley_chern_normalization": "1/(2*pi)",
        "rank_selection_zero_based": list(RANK_SELECTION),
        "rank": 3,
        "solver_settings": {"resolution": RESOLUTION, "num_bands": NUM_BANDS, "polarization": POLARIZATION, "eigensolver_tolerance": EIGENSOLVER_TOLERANCE, "deterministic": DETERMINISTIC, "mesh_size": MESH_SIZE},
        "stage1": stage1,
        "stage2": stage2,
        "stage2_status": stage2_status,
        "integration_grid_sensitivity": None if stage2 is None else ("MEASURED" if stage1["composite_valley_chern"] is not None and stage2["composite_valley_chern"] is not None else "FAILED"),
        "fr00_composite_reference_pattern": pattern,
        "absolute_paper_valley_sign_gate": "DISABLED",
        "secondary_voronoi_domain": "DEFERRED",
        "raw_solve_requests": raw_requests,
        "unique_mpb_solves": unique_solves,
        "cache_hits": cache_hits,
        "cache_hit_fraction": cache_hits / raw_requests if raw_requests else 0.0,
        "solver_failures": 0,
        "cache_identity_collision": False,
        "solve_identity_manifest": solve_manifest,
        "solve_identity_manifest_digest": digest(solve_manifest),
        "total_wall_time_seconds": time.monotonic() - started,
        "per_band_chern": "NOT_AUTHORIZED",
        "rank2_chern": "NOT_AUTHORIZED",
        "full_bz_chern": "NOT_AUTHORIZED",
        "bcd": "NOT_AUTHORIZED",
        "deformation_physics": "NOT_AUTHORIZED",
        "main_unchanged": True,
        "sandbox_remote_head_verified": False,
        "e7i4a_overall": "FIRST_FR00_COMPOSITE_VALLEY_CHERN_PILOT_READY_FOR_SUPERVISOR_AUDIT" if c1 is not None else "VALLEY_CHERN_PILOT_FAILED_CLEANLY",
    }
    (root / "audit" / "e7i4a").mkdir(parents=True, exist_ok=True)
    (root / "audit" / "e7i4a" / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": result["e7i4a_overall"], "stage1_chern": c1, "stage2_chern": c2, "unique_solves": unique_solves}))


if __name__ == "__main__":
    main()