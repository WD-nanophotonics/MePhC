"""E7I.5B bounded FR00 K-point individual-band Berry reference benchmark."""
from __future__ import annotations

import json
import math
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from audit.e7i3c.run_representation_bridge import (
    build_reference_mpb_adapter,
    build_triangular_coordinate_preflight,
    build_triangular_reference_geometry,
    lowdin_snapshot,
)
from audit.e7i4a.run_composite_valley_chern import centered_loop, frame_to_subspace
from audit.e7i5a.run_rank1_stage1_worker import external_contexts, frame_rank1, nearest_gap, solve_at
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import (
    PlaquetteRefinementLevel,
    PlaquetteRefinementThresholds,
    qualify_plaquette_boundary,
    qualify_plaquette_interior,
    qualify_plaquette_refinement,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.valley_benchmark import centered_ccw_plaquette_requests
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

WORK_ORDER = "TRILATT-E7I5B-20260824-150"
FR = 0.0
R48 = 48
R64 = 64
NUM_BANDS = 4
BANDS = (0, 1, 2)
POLARIZATION = "TE"
REPRESENTATION = "mpb_energy_eh_v1"
TOLERANCE = 1e-7
MESH_SIZE = 3
K_PUBLIC = (2.0 / 3.0, 0.0)
DELTAS = (1.0 / 36.0, 1.0 / 72.0, 1.0 / 144.0)
TRANSPORT = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.0)
REFINEMENT = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)
MAIN_BASELINE = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
E7I5A_C1_CALC = "c7571f4c9354489b453d78801b174609d1918d54"
E7I5A_C1_EVIDENCE = "35336e09b76cd843ade7697221d510c629c26478"
E7I5A_C1_BUNDLE = "4c17023f8e5183a09187cd33a9781ee37307a2b3b95d35ab86f1c0be0a26e2ad"


def omega_over_a2(omega_q):
    return None if omega_q is None else float(omega_q / (2.0 * math.pi) ** 2)


def profile_row(f48, f64, band, label, q):
    gap48 = nearest_gap(f48, band)
    gap64 = nearest_gap(f64, band)
    target48 = float(f48[band])
    target64 = float(f64[band])
    if gap48 >= 0.05:
        profile, rel48, rel64, ratio = "LEGACY_STRICT_PASS", None, None, None
    else:
        rel48 = gap48 / target48 if target48 > 0 else 0.0
        rel64 = gap64 / target64 if target64 > 0 else 0.0
        ratio = min(gap48, gap64) / max(abs(gap64 - gap48), 1e-12)
        profile = "LOW_GAP_PASS" if gap48 > 0 and gap64 > 0 and rel48 >= 0.01 and rel64 >= 0.01 and ratio >= 10 else "LOW_GAP_FAIL"
    return {
        "label": label,
        "q": list(q),
        "band": band,
        "R48_frequencies": [float(x) for x in f48],
        "R64_frequencies": [float(x) for x in f64],
        "R48_nearest_gap": float(gap48),
        "R64_nearest_gap": float(gap64),
        "relative_R48": None if rel48 is None else float(rel48),
        "relative_R64": None if rel64 is None else float(rel64),
        "stability_ratio": None if ratio is None else float(ratio),
        "profile": profile,
    }


def status_dict(value):
    return {"status": value.status, "is_qualified": bool(value.is_qualified)}


def evaluate_local(band, delta, resolution, adapter, geometry, preflight, cache, counters):
    delta_vectors = preflight.delta_k_vectors_to_public_q(delta)
    requests = centered_ccw_plaquette_requests(
        (K_PUBLIC,), delta_vectors,
        period_basis=preflight.public_period_basis,
        coordinate_mapping_digest=preflight.mapping_digest,
    )
    vertices_q = [tuple(float(x) for x in request.canonical_periodic_vertex_q) for request in requests]
    points = [("vertex", q) for q in vertices_q] + [("center", K_PUBLIC)]
    profile, values = [], {}
    for label, q in points:
        raw48, f48, _ = solve_at(adapter, geometry, preflight, q, R48, cache, counters)
        raw64, f64, _ = solve_at(adapter, geometry, preflight, q, R64, cache, counters)
        values[(label, q)] = {"raw48": raw48, "f48": f48, "raw64": raw64, "f64": f64}
        profile.append(profile_row(f48, f64, band, label, q))
    profile_passed = all(row["profile"] in ("LEGACY_STRICT_PASS", "LOW_GAP_PASS") for row in profile)
    vertex_values = [values[("vertex", q)] for q in vertices_q]
    center_value = values[("center", K_PUBLIC)]
    raw_key, freq_key = ("raw48", "f48") if resolution == R48 else ("raw64", "f64")
    vertex_frames = [frame_rank1(q, value[raw_key], band) for q, value in zip(vertices_q, vertex_values)]
    center_frame = frame_rank1(K_PUBLIC, center_value[raw_key], band)
    vertex_frequencies = [value[freq_key] for value in vertex_values]
    center_frequencies = center_value[freq_key]
    contexts = external_contexts(vertex_frequencies, center_frequencies, band)
    path = qualify_ordered_path(tuple(vertex_frames), contexts, thresholds=TRANSPORT, closed=True, provenance={"source": "E7I.5B rank-1 local Berry", "band": band, "delta": delta, "resolution": resolution})
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(tuple(vertex_frames), contexts, thresholds=TRANSPORT, provenance={"source": "E7I.5B rank-1 local boundary", "band": band})
    spoke_contexts = []
    for value in vertex_values:
        left = tuple(float(x) for i, x in enumerate(value[freq_key]) if i != band)
        right = tuple(float(x) for i, x in enumerate(center_frequencies) if i != band)
        spoke_contexts.append(ExternalIsolationContext(left, right, {"source": "E7I.5B complete vertex-center excluded spectrum", "band": band}))
    interior = qualify_plaquette_interior(boundary, center_frame, tuple(spoke_contexts), provenance={"source": "E7I.5B rank-1 local interior", "band": band})
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    area = abs(float(np.linalg.det(np.asarray(delta_vectors, dtype=float))))
    path_qualified = path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)
    qualified = bool(profile_passed and path_qualified and wilson.status == WILSON_LOOP_QUALIFIED and boundary.is_qualified and interior.is_qualified and phase is not None and math.isfinite(phase))
    omega_q = None if not qualified else float(-phase / area)
    return {
        "band": band,
        "delta": delta,
        "resolution": resolution,
        "vertices_q": [list(q) for q in vertices_q],
        "profile_passed": profile_passed,
        "profile": profile,
        "path_status": path.status,
        "wilson_status": wilson.status,
        "boundary": status_dict(boundary),
        "interior": status_dict(interior),
        "determinant_phase": phase,
        "omega_q": omega_q,
        "omega_over_a2": omega_over_a2(omega_q),
        "qualified": qualified,
        "_boundary": boundary,
        "_interior": interior,
        "_values": values,
    }


def rank3_trace(delta, local_results, adapter, geometry, preflight, cache, counters):
    if not all(result["qualified"] for result in local_results):
        return {"status": "NOT_AUTHORIZED", "reason": "all_three_rank1_local_results_not_qualified_at_same_delta"}
    vertices_q = [tuple(x) for x in local_results[0]["vertices_q"]]
    frames, frequencies = [], []
    for q in vertices_q:
        raw, freq, _ = solve_at(adapter, geometry, preflight, q, R48, cache, counters)
        lowdin, _ = lowdin_snapshot(raw)
        frames.append(frame_to_subspace(q, lowdin))
        frequencies.append(freq)
    path, wilson, qualified = centered_loop(frames, frequencies)
    area = abs(float(np.linalg.det(np.asarray(preflight.delta_k_vectors_to_public_q(delta), dtype=float))))
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    omega_q = None if not qualified or phase is None else float(-phase / area)
    rank1_sum = float(sum(float(result["omega_q"]) for result in local_results))
    return {
        "status": "QUALIFIED" if qualified and omega_q is not None else "UNQUALIFIED",
        "path_status": path.status,
        "wilson_status": wilson.status,
        "determinant_phase": phase,
        "omega_q": omega_q,
        "omega_over_a2": omega_over_a2(omega_q),
        "rank1_sum_omega_q": rank1_sum,
        "absolute_difference_omega_q": None if omega_q is None else float(abs(omega_q - rank1_sum)),
    }


def self_checks(preflight):
    assert BANDS == (0, 1, 2)
    assert DELTAS == (1.0 / 36.0, 1.0 / 72.0, 1.0 / 144.0)
    mapped = tuple(round(float(x), 12) for x in preflight.public_q_to_mpb(K_PUBLIC))
    assert mapped == (round(1.0 / 3.0, 12), round(1.0 / 3.0, 12))
    assert len(tuple(x for i, x in enumerate((1.0, 2.0, 3.0, 4.0)) if i != 1)) == 3
    assert math.isclose(omega_over_a2((2.0 * math.pi) ** 2), 1.0, rel_tol=0.0, abs_tol=1e-15)
    assert math.isclose(-(-0.25) / 0.5, 0.5, rel_tol=0.0, abs_tol=1e-15)


def git_head(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def run(output: Path):
    root = Path(__file__).resolve().parents[2]
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    self_checks(preflight)
    adapter = build_reference_mpb_adapter(geometry, preflight)
    cache, counters = {}, {"raw_requests": 0, "cache_hits": 0, "solver_failures": 0}
    started = time.monotonic()
    k_preflight = []
    for band in range(NUM_BANDS):
        _, f48, _ = solve_at(adapter, geometry, preflight, K_PUBLIC, R48, cache, counters)
        _, f64, _ = solve_at(adapter, geometry, preflight, K_PUBLIC, R64, cache, counters)
        row = profile_row(f48, f64, band, "K", K_PUBLIC)
        row.update({"paper_band": band + 1, "zero_based_band": band, "mapping": {"public_q": list(K_PUBLIC), "mpb_fractional_q": list(preflight.public_q_to_mpb(K_PUBLIC))}})
        k_preflight.append(row)
    private_by_band, bands = {}, {}
    for band in BANDS:
        levels = [evaluate_local(band, delta, R48, adapter, geometry, preflight, cache, counters) for delta in DELTAS]
        private_by_band[band] = levels
        for index in range(len(levels) - 1):
            l1 = PlaquetteRefinementLevel(boundary=levels[index]["_boundary"], interior=levels[index]["_interior"], step=DELTAS[index], provenance={"source": "E7I.5B independent local estimate"})
            l2 = PlaquetteRefinementLevel(boundary=levels[index + 1]["_boundary"], interior=levels[index + 1]["_interior"], step=DELTAS[index + 1], provenance={"source": "E7I.5B independent local estimate"})
            levels[index]["refinement_to_next_delta"] = qualify_plaquette_refinement((l1, l2), thresholds=REFINEMENT, provenance={"source": "E7I.5B pairwise refinement diagnostic", "band": band}).to_dict()
        levels[-1]["refinement_to_next_delta"] = None
        r64_smallest = evaluate_local(band, DELTAS[-1], R64, adapter, geometry, preflight, cache, counters) if levels[-1]["qualified"] else None
        clean_levels = [{key: value for key, value in level.items() if not key.startswith("_")} for level in levels]
        bands[str(band)] = {"paper_band": band + 1, "zero_based_band": band, "levels": clean_levels, "R64_smallest_stencil": None if r64_smallest is None else {key: value for key, value in r64_smallest.items() if not key.startswith("_")}}
    rank3 = {str(delta): rank3_trace(delta, [private_by_band[band][index] for band in BANDS], adapter, geometry, preflight, cache, counters) for index, delta in enumerate(DELTAS)}
    payload = {
        "schema": "e7i5b_k_local_berry_reference_v1",
        "complete": True,
        "work_order": WORK_ORDER,
        "base_sandbox_sha": E7I5A_C1_EVIDENCE,
        "calculation_commit": E7I5A_C1_CALC,
        "evidence_commit": E7I5A_C1_EVIDENCE,
        "calculation_bundle_sha256": E7I5A_C1_BUNDLE,
        "main_baseline": MAIN_BASELINE,
        "current_git_head": git_head(root),
        "geometry": {"fr": FR, "effective_permittivity": 2.65, "polarization": POLARIZATION, "representation": REPRESENTATION, "resolution": R48, "R64": R64, "mesh_size": MESH_SIZE, "solver_tolerance": TOLERANCE, "deterministic": True},
        "K_preflight": k_preflight,
        "bands": bands,
        "rank3_trace_diagnostic": rank3,
        "paper_reference": {"paper_band_1_omega_over_a2": -0.92, "paper_band_2_omega_over_a2": 0.72, "paper_band_3_omega_over_a2": 0.19, "absolute_sign_gate": False},
        "telemetry": {"wall_time_seconds": time.monotonic() - started, "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), **counters},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        self_checks(build_triangular_coordinate_preflight())
        print("E7I5B_SELF_CHECK=PASS")
    else:
        target = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else Path("audit/e7i5b/result.json")
        result = run(target)
        print(json.dumps({"schema": result["schema"], "current_git_head": result["current_git_head"], "telemetry": result["telemetry"]}, sort_keys=True))
