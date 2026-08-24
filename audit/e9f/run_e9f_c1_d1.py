"""Bounded E9F.C1.D1 diagnostics for the exact 17 band-3 failed centers."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mephc.valley_integration import build_source_bound_domain, _point_in
from mephc.valley_benchmark import centered_ccw_plaquette_requests

WORK_ORDER = "TRILATT-E9F-C-C1-D1-20260824-215"
C1_RESULT = ROOT / "audit/e9f/c1_live_result.json"
C1_CONTRACT = ROOT / "audit/e9f/c1_live_contract.json"
C1_EXECUTION_SHA = "ca56f6fe85ec0591747ec22eebff8bb9e2d1d7b9"
C1_RESULT_SHA = "123acc40c448b45cab0fbffffeeec4a879202c25f20cb6c5769041726fe8296c"
C1_CHECKPOINT_SHA = "33d6f0a2eeacac23b71b302c0a2ddfbb1ba315d39a3db2cbf8ba72a55121ece2"
C1_CONTRACT_SHA = "2d770bc1525be8ca7a1722d855aa7f262767fe93ad7bfe905edfb1b0f62ed4da"
REMOTE_BASE = "06459b9767200a7a8c53e56618509d0015fc1c24"
MAIN_SHA = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
BAND = 2
RESOLUTION = 64
R96 = 96
NUM_BANDS = 6
SIDE_VALUES = (1.0 / 36.0, 1.0 / 72.0, 1.0 / 144.0)
MIN_GAP = 0.02
MIN_SINGULAR = 0.9
MAX_ANGLE = 0.45
MAX_PROJECTOR = 0.3


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_failed_centers() -> list[dict]:
    result = json.loads(C1_RESULT.read_text(encoding="utf-8"))
    assert result["work_order_id"] == "TRILATT-E9F-C-C1-20260824-214"
    failed = [item for item in result["band_summaries"][2]["failed_samples"]]
    assert len(failed) == 17
    plan = None
    from audit.e9f.run_e9f_c1_live import make_plan, load_contract
    plan = make_plan(load_contract())
    by_id = {row["SAMPLE_ID"]: row for row in plan["ROWS"]}
    return [{"sample_id": item["sample_id"], "public_q": list(by_id[item["sample_id"]]["PUBLIC_Q"])} for item in failed]


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a, b, p, eps=1e-12):
    return abs(cross(a, b, p)) <= eps and min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps


def segments_intersect(a, b, c, d):
    ab1, ab2, cd1, cd2 = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    if on_segment(a, b, c) or on_segment(a, b, d) or on_segment(c, d, a) or on_segment(c, d, b):
        return True
    return ((ab1 > 0) != (ab2 > 0)) and ((cd1 > 0) != (cd2 > 0))


def point_segment_distance(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / denom))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def polygon_edges(poly):
    return list(zip(poly, poly[1:] + poly[:1]))


def point_info(domain, point):
    outer_inside = bool(_point_in(domain.outer, point))
    gamma_inside = [bool(_point_in(hole, point)) for hole in domain.exclusions]
    outer_distance = min(point_segment_distance(point, a, b) for a, b in polygon_edges(list(domain.outer)))
    gamma_distance = min(point_segment_distance(point, a, b) for hole in domain.exclusions for a, b in polygon_edges(list(hole)))
    return {
        "q": [float(point[0]), float(point[1])],
        "outer_inside": outer_inside,
        "gamma_inside": gamma_inside,
        "retained_inside": outer_inside and not any(gamma_inside),
        "distance_to_outer_boundary": float(outer_distance),
        "distance_to_nearest_gamma_exclusion_boundary": float(gamma_distance),
    }


def segment_interacts(segment, polygons):
    a, b = segment
    for poly in polygons:
        if _point_in(poly, a) or _point_in(poly, b) or _point_in(poly, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)):
            return True
        if any(segments_intersect(a, b, c, d) for c, d in polygon_edges(list(poly))):
            return True
    return False


def geometry_for_side(domain, center, side):
    half = float(side) / 2.0
    cx, cy = float(center[0]), float(center[1])
    vertices = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]
    infos = [point_info(domain, point) for point in vertices]
    edges = []
    for index in range(4):
        segment = (vertices[index], vertices[(index + 1) % 4])
        edges.append({
            "from": list(segment[0]),
            "to": list(segment[1]),
            "crosses_outer_boundary": segment_interacts(segment, [domain.outer]),
            "enters_gamma_exclusion": segment_interacts(segment, list(domain.exclusions)),
        })
    return {
        "side": float(side),
        "center": point_info(domain, tuple(center)),
        "vertices": infos,
        "edges": edges,
        "any_edge_crosses_outer_boundary": any(item["crosses_outer_boundary"] for item in edges),
        "any_edge_enters_gamma_exclusion": any(item["enters_gamma_exclusion"] for item in edges),
    }


def detailed_stencil(center, side, resolution, provider, preflight, cache, counters):
    from audit.e9c.run_k_kprime_rank1_berry import (
        solve_at, frame_rank1, external_contexts, excluded,
    )
    from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
    from mephc.plaquette_domain import qualify_plaquette_boundary, qualify_plaquette_interior
    from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport
    from audit.e9c.run_k_kprime_rank1_berry import TRANSPORT

    requests = centered_ccw_plaquette_requests(
        (tuple(center),), side,
        period_basis=preflight.public_period_basis,
        coordinate_mapping_digest=preflight.mapping_digest,
    )
    vertices = [tuple(float(x) for x in req.nominal_vertex_q) for req in requests]
    values = [solve_at(provider, preflight, point, resolution, cache, counters) for point in vertices]
    center_value = solve_at(provider, preflight, tuple(center), resolution, cache, counters)
    profile = []
    for label, value, point in [(f"vertex_{i}", value, point) for i, (value, point) in enumerate(zip(values, vertices))] + [("center", center_value, tuple(center))]:
        gap = min(abs(float(value["frequencies"][BAND]) - float(other)) for index, other in enumerate(value["frequencies"]) if index != BAND)
        profile.append({"label": label, "q": list(point), "frequencies": list(value["frequencies"]), "external_gap": float(gap), "pass": bool(gap >= MIN_GAP)})
    frames = [frame_rank1(point, value["raw"], BAND) for point, value in zip(vertices, values)]
    center_frame = frame_rank1(tuple(center), center_value["raw"], BAND)
    contexts = external_contexts([value["frequencies"] for value in values], BAND)
    path = qualify_ordered_path(tuple(frames), contexts, thresholds=TRANSPORT, closed=True, provenance={"source": "D1 C1 replay", "side": side, "resolution": resolution})
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(tuple(frames), contexts, thresholds=TRANSPORT, provenance={"source": "D1 C1 replay", "side": side, "resolution": resolution})
    spokes = tuple(
        type(contexts[0])(excluded(value["frequencies"], BAND), excluded(center_value["frequencies"], BAND), {"source": "D1 spoke", "side": side})
        for value in values
    )
    interior = qualify_plaquette_interior(boundary, center_frame, spokes, provenance={"source": "D1 C1 replay", "side": side, "resolution": resolution})
    edge_results = list(path.edge_results) + list(boundary.edge_results) + list(interior.spoke_results)
    overlaps = [item.overlap for item in edge_results if item.overlap is not None]
    distances = [float(item.projector_distance) for item in edge_results if item.projector_distance is not None]
    metrics = {
        "minimum_singular_value": None if not overlaps else min(float(item.min_singular_value) for item in overlaps),
        "maximum_principal_angle": None if not overlaps else max(float(item.max_principal_angle) for item in overlaps),
        "maximum_projector_distance": None if not distances else max(distances),
    }
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    path_ok = path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)
    qualified = bool(all(row["pass"] for row in profile) and path_ok and wilson.status == WILSON_LOOP_QUALIFIED and boundary.is_qualified and interior.is_qualified and phase is not None and math.isfinite(phase))
    gates = []
    if not all(row["pass"] for row in profile): gates.append("external_gap")
    if metrics["minimum_singular_value"] is not None and metrics["minimum_singular_value"] < 0.9: gates.append("min_singular_value")
    if metrics["maximum_principal_angle"] is not None and metrics["maximum_principal_angle"] > 0.45: gates.append("max_principal_angle")
    if metrics["maximum_projector_distance"] is not None and metrics["maximum_projector_distance"] > 0.3: gates.append("max_projector_distance")
    if not path_ok: gates.append("ordered_path")
    if wilson.status != WILSON_LOOP_QUALIFIED: gates.append("wilson")
    if not boundary.is_qualified: gates.append("boundary")
    if not interior.is_qualified: gates.append("interior")
    if phase is None or not math.isfinite(phase): gates.append("finite_estimator")
    return {
        "center": list(center),
        "side": float(side),
        "resolution": int(resolution),
        "vertices": [list(point) for point in vertices],
        "profile": profile,
        "center_frequencies": list(center_value["frequencies"]),
        "center_adjacent_gaps": {"band2_minus_band1": float(center_value["frequencies"][2] - center_value["frequencies"][1]), "band3_minus_band2": float(center_value["frequencies"][3] - center_value["frequencies"][2])},
        "minimum_external_gap": min(row["external_gap"] for row in profile),
        "metrics": metrics,
        "path_status": path.status,
        "path_edges": [edge.to_dict(include_matrices=False) for edge in path.edge_results],
        "wilson_status": wilson.status,
        "wilson_phase": phase,
        "wilson_unitarity_residual": wilson.unitarity_residual,
        "boundary_status": boundary.status,
        "boundary_edges": [edge.to_dict(include_matrices=False) for edge in boundary.edge_results],
        "interior_status": interior.status,
        "interior_spokes": [edge.to_dict(include_matrices=False) for edge in interior.spoke_results],
        "finite_estimator_status": "FINITE" if phase is not None and math.isfinite(phase) else "NOT_FINITE_OR_MISSING",
        "qualified": qualified,
        "failure_gates": sorted(set(gates)),
    }


def classify(item):
    r64 = item["stencils"]["1/36"]["r64"]
    small = item["stencils"]["1/144"]["r64"]
    center_gap = min(abs(float(r64["center_frequencies"][BAND]) - float(x)) for i, x in enumerate(r64["center_frequencies"]) if i != BAND)
    boundary_hit = item["geometry"]["1/36"]["any_edge_crosses_outer_boundary"] or item["geometry"]["1/36"]["any_edge_enters_gamma_exclusion"]
    if small["qualified"] and center_gap >= MIN_GAP and boundary_hit:
        return "BOUNDARY_STENCIL_ARTIFACT_SUPPORTED"
    r96 = item["stencils"]["1/144"].get("r96")
    if r96 is not None and r96["qualified"] != small["qualified"]:
        return "RESOLUTION_SENSITIVE_UNRESOLVED"
    if center_gap < MIN_GAP and not small["qualified"]:
        return "TRUE_POINTWISE_LOW_GAP_BLOCKER"
    return "OTHER_NUMERICAL_OR_PATH_BLOCKER"


def run_worker(sample_index, output):
    centers = load_failed_centers()
    sample = centers[sample_index]
    domain = build_source_bound_domain(0.0)
    from audit.e9c.run_k_kprime_rank1_berry import geometry_inputs, build_inputs, make_provider
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    provider64 = make_provider(RESOLUTION, lattice, solver_geometry, background)
    cache = {}
    counters = {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    geometry_data = {label: geometry_for_side(domain, sample["public_q"], side) for label, side in (("1/36", SIDE_VALUES[0]), ("1/72", SIDE_VALUES[1]), ("1/144", SIDE_VALUES[2]))}
    stencils = {}
    for label, side in (("1/36", SIDE_VALUES[0]), ("1/72", SIDE_VALUES[1]), ("1/144", SIDE_VALUES[2])):
        stencils[label] = {"r64": detailed_stencil(sample["public_q"], side, RESOLUTION, provider64, preflight, cache, counters)}
    if not stencils["1/144"]["r64"]["qualified"]:
        provider96 = make_provider(R96, lattice, solver_geometry, background)
        stencils["1/144"]["r96"] = detailed_stencil(sample["public_q"], SIDE_VALUES[2], R96, provider96, preflight, {}, counters)
    payload = {
        "sample_index": sample_index,
        "sample_id": sample["sample_id"],
        "center": sample["public_q"],
        "geometry": geometry_data,
        "stencils": stencils,
        "classification": classify({"geometry": geometry_data, "stencils": stencils}),
        "counters": counters,
    }
    atomic_json(output, payload)


def run(output):
    failed = load_failed_centers()
    results = []
    for index, sample in enumerate(failed):
        worker_output = output.with_name(f"{output.stem}.sample_{index:02d}.json")
        if worker_output.exists():
            worker_output.unlink()
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(index), "--output", str(worker_output)], cwd=ROOT, check=True)
        payload = json.loads(worker_output.read_text(encoding="utf-8"))
        worker_output.unlink()
        results.append(payload)
    classes = {}
    for item in results:
        classes[item["classification"]] = classes.get(item["classification"], 0) + 1
    result = {
        "schema": "trilatt_e9f_c1_d1_diagnostic_v1",
        "status": "E9F_C1_BAND3_BLOCKER_DIAGNOSIS_MIXED_READY_FOR_SUPERVISOR_DECISION",
        "work_order_id": WORK_ORDER,
        "base_remote_sandbox_sha": REMOTE_BASE,
        "main_sha": MAIN_SHA,
        "main_unchanged": True,
        "c1_execution_sha": C1_EXECUTION_SHA,
        "c1_result_sha256": sha256_file(C1_RESULT),
        "c1_checkpoint_sha256": sha256_file(ROOT / "audit/e9f/c1_live_checkpoint.json"),
        "c1_contract_sha256": sha256_file(C1_CONTRACT),
        "c1_result_status": "E9F_C1_FR0_SOURCE_GRID_INCOMPLETE_FAIL_CLOSED_READY_FOR_BLOCKER_DIAGNOSIS",
        "failed_sample_count": len(results),
        "diagnostics": results,
        "classification_counts": classes,
        "overall_classification": (
            "MIXED_OR_UNRESOLVED"
            if len(classes) > 1 or "OTHER_NUMERICAL_OR_PATH_BLOCKER" in classes or "RESOLUTION_SENSITIVE_UNRESOLVED" in classes
            else ("ALL_BOUNDARY_STENCIL" if set(classes) == {"BOUNDARY_STENCIL_ARTIFACT_SUPPORTED"} else "ALL_TRUE_POINTWISE_LOW_GAP")
        ),
        "no_new_chern": True,
        "no_reducer_input": True,
        "no_threshold_change": True,
    }
    atomic_json(output, result)
    return result


if __name__ == "__main__":
    if "--worker" in sys.argv:
        run_worker(int(sys.argv[sys.argv.index("--worker") + 1]), Path(sys.argv[sys.argv.index("--output") + 1]))
    else:
        result = run(Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else ROOT / "audit/e9f/c1_d1_result.json")
        print(json.dumps({"status": result["overall_classification"], "failed_sample_count": result["failed_sample_count"], "classification_counts": result["classification_counts"]}, sort_keys=True))
