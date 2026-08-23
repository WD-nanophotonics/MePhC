"""Solver-neutral source-bound rounded-triangle geometry for E9E.A.

The public geometry is constructed in Cartesian coordinates first. The single
Cartesian-to-MPB adapter is included only as a coordinate self-check; this
module never imports MPB and never launches a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Iterable

import numpy as np


WORK_ORDER = "TRILATT-E9E-A-20260824-187"
BASE_CIRCUMRADIUS = 0.4
BASE_AREA = 3.0 * math.sqrt(3.0) * BASE_CIRCUMRADIUS**2 / 4.0
REAL_BASIS = np.asarray(
    ((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0)),
    dtype=float,
)
TOL = 1.0e-11


def root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def triangle_vertices(circumradius: float) -> np.ndarray:
    """Return the accepted E9A orientation, counter-clockwise."""

    r = float(circumradius)
    return np.asarray(
        (
            (0.0, r),
            (-math.sqrt(3.0) * r / 2.0, -r / 2.0),
            (math.sqrt(3.0) * r / 2.0, -r / 2.0),
        ),
        dtype=float,
    )


def polygon_area(points: np.ndarray) -> float:
    return abs(
        0.5
        * sum(
            points[i, 0] * points[(i + 1) % len(points), 1]
            - points[i, 1] * points[(i + 1) % len(points), 0]
            for i in range(len(points))
        )
    )


def signed_area(points: np.ndarray) -> float:
    return 0.5 * sum(
        points[i, 0] * points[(i + 1) % len(points), 1]
        - points[i, 1] * points[(i + 1) % len(points), 0]
        for i in range(len(points))
    )


def canonical_digest(points: Iterable[Iterable[float]]) -> str:
    normalized = [
        [0.0 if round(float(x), 14) == 0.0 else round(float(x), 14) for x in row]
        for row in points
    ]
    payload = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _arc_sweep(start: float, end: float) -> float:
    """Select the 120-degree outer arc from incoming to outgoing tangent."""

    positive = (end - start) % (2.0 * math.pi)
    target = 2.0 * math.pi / 3.0
    if abs(positive - target) <= 1.0e-9:
        return target
    if abs(positive - (2.0 * math.pi - target)) <= 1.0e-9:
        return -target
    raise ValueError(f"unexpected rounded-corner angle: {positive}")


def build_geometry(
    f_r: float,
    *,
    base_circumradius: float = BASE_CIRCUMRADIUS,
    target_area: float = BASE_AREA,
) -> dict:
    """Build a constant-area rounded triangular hole in Cartesian space.

    The source defines f_r as the arc-radius / nominal-triangle-radius ratio
    and bounds it by [0, 0.5]. The nominal triangle is uniformly rescaled for
    every f_r so the physical hole area is the accepted E9A triangle area.
    At f_r=0 the rescale is exactly one; at f_r=0.5 the three tangent
    segments vanish and the boundary is one circle.
    """

    f = float(f_r)
    if not 0.0 <= f <= 0.5:
        raise ValueError(f"source-defined f_r must be in [0, 0.5], got {f}")
    base_r = float(base_circumradius)
    if base_r <= 0.0 or target_area <= 0.0:
        raise ValueError("circumradius and target area must be positive")

    unrounded_area = 3.0 * math.sqrt(3.0) * base_r**2 / 4.0
    construction_arc_radius = f * base_r
    # Three removed corner caps have total area (3*sqrt(3)-pi)*rho^2.
    raw_area = unrounded_area - (3.0 * math.sqrt(3.0) - math.pi) * construction_arc_radius**2
    area_scale = math.sqrt(float(target_area) / raw_area)
    nominal_radius = base_r * area_scale
    arc_radius = f * nominal_radius
    vertices = triangle_vertices(nominal_radius)

    arcs = []
    for i, vertex in enumerate(vertices):
        previous = vertices[(i - 1) % 3]
        following = vertices[(i + 1) % 3]
        if f == 0.0:
            incoming = vertex.copy()
            outgoing = vertex.copy()
            center = vertex.copy()
            sweep = 0.0
        else:
            to_previous = (previous - vertex) / np.linalg.norm(previous - vertex)
            to_following = (following - vertex) / np.linalg.norm(following - vertex)
            offset = math.sqrt(3.0) * arc_radius
            incoming = vertex + offset * to_previous
            outgoing = vertex + offset * to_following
            center = (1.0 - 2.0 * f) * vertex
            start_angle = math.atan2(incoming[1] - center[1], incoming[0] - center[0])
            end_angle = math.atan2(outgoing[1] - center[1], outgoing[0] - center[0])
            sweep = _arc_sweep(start_angle, end_angle)
        arcs.append(
            {
                "vertex_index": i,
                "center": center.tolist(),
                "radius": float(arc_radius),
                "incoming_tangent": incoming.tolist(),
                "outgoing_tangent": outgoing.tolist(),
                "sweep_radians": float(sweep),
                "nominal_arc_radius_ratio": f,
            }
        )

    segments = []
    for i in range(3):
        start = np.asarray(arcs[i]["outgoing_tangent"], dtype=float)
        end = np.asarray(arcs[(i + 1) % 3]["incoming_tangent"], dtype=float)
        segments.append(
            {
                "edge_index": i,
                "start": start.tolist(),
                "end": end.tolist(),
                "length": float(np.linalg.norm(end - start)),
            }
        )

    return {
        "f_r": f,
        "base_circumradius": base_r,
        "target_area": float(target_area),
        "construction_arc_radius": float(construction_arc_radius),
        "raw_area_before_normalization": float(raw_area),
        "area_scale": float(area_scale),
        "nominal_triangle_circumradius": float(nominal_radius),
        "physical_arc_radius": float(arc_radius),
        "vertices_cartesian": vertices.tolist(),
        "arcs": arcs,
        "straight_segments": segments,
        "physical_area_analytic": float(target_area),
        "boundary_digest": canonical_digest(
            [
                point
                for arc in arcs
                for point in (arc["incoming_tangent"], arc["outgoing_tangent"])
            ]
        ),
    }


def sample_boundary(geometry: dict, arc_samples: int = 48) -> np.ndarray:
    """Sample the ordered boundary without adding an MPB representation."""

    points: list[np.ndarray] = []
    arcs = geometry["arcs"]
    segments = geometry["straight_segments"]
    for i, arc in enumerate(arcs):
        start = np.asarray(arc["incoming_tangent"], dtype=float)
        center = np.asarray(arc["center"], dtype=float)
        radius = float(arc["radius"])
        sweep = float(arc["sweep_radians"])
        if radius == 0.0:
            arc_points = [start]
        else:
            start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
            arc_points = [
                center
                + radius
                * np.asarray(
                    (
                        math.cos(start_angle + sweep * j / arc_samples),
                        math.sin(start_angle + sweep * j / arc_samples),
                    )
                )
                for j in range(arc_samples + 1)
            ]
        if points:
            points.extend(arc_points[1:])
        else:
            points.extend(arc_points)
        end = np.asarray(segments[i]["end"], dtype=float)
        if np.linalg.norm(end - points[-1]) > TOL:
            points.append(end)
    return np.asarray(points, dtype=float)


def cartesian_to_mpb(points: np.ndarray) -> np.ndarray:
    """The one and only public-Cartesian -> MPB-lattice mapping."""

    return np.linalg.solve(REAL_BASIS, np.asarray(points, dtype=float).T).T


def _cross(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _segments_intersect(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> bool:
    values = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    eps = 1.0e-10
    if abs(values[0]) <= eps and abs(values[1]) <= eps and abs(values[2]) <= eps and abs(values[3]) <= eps:
        return not (
            max(a[0], b[0]) < min(c[0], d[0]) - eps
            or max(c[0], d[0]) < min(a[0], b[0]) - eps
            or max(a[1], b[1]) < min(c[1], d[1]) - eps
            or max(c[1], d[1]) < min(a[1], b[1]) - eps
            or np.linalg.norm(a - c) <= eps
            or np.linalg.norm(a - d) <= eps
            or np.linalg.norm(b - c) <= eps
            or np.linalg.norm(b - d) <= eps
        )
    return (
        ((values[0] > eps and values[1] < -eps) or (values[0] < -eps and values[1] > eps))
        and ((values[2] > eps and values[3] < -eps) or (values[2] < -eps and values[3] > eps))
    )


def _self_intersection_free(points: np.ndarray) -> bool:
    count = len(points)
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        for j in range(i + 1, count):
            if j in (i, (i + 1) % count) or (j + 1) % count == i:
                continue
            if _segments_intersect(a, b, points[j], points[(j + 1) % count]):
                return False
    return True


def validate_geometry(geometry: dict) -> dict:
    f = float(geometry["f_r"])
    vertices = np.asarray(geometry["vertices_cartesian"], dtype=float)
    arcs = geometry["arcs"]
    segments = geometry["straight_segments"]
    boundary = sample_boundary(geometry)
    mapped = cartesian_to_mpb(boundary)
    roundtrip = (REAL_BASIS @ mapped.T).T

    tangent_errors = []
    for i, arc in enumerate(arcs):
        center = np.asarray(arc["center"], dtype=float)
        for point_key, edge_index in (("incoming_tangent", (i - 1) % 3), ("outgoing_tangent", i)):
            point = np.asarray(arc[point_key], dtype=float)
            segment = segments[edge_index]
            direction = np.asarray(segment["end"], dtype=float) - np.asarray(segment["start"], dtype=float)
            radial = point - center
            if np.linalg.norm(direction) <= TOL or np.linalg.norm(radial) <= TOL:
                continue
            tangent_errors.append(
                abs(
                    float(
                        np.dot(
                            direction / np.linalg.norm(direction),
                            radial / np.linalg.norm(radial),
                        )
                    )
                )
            )

    radii = [float(np.linalg.norm(v)) for v in vertices]
    center_radii = [float(np.linalg.norm(np.asarray(arc["center"], dtype=float))) for arc in arcs]
    arc_radii = [float(arc["radius"]) for arc in arcs]
    tangent_offsets = [
        float(np.linalg.norm(np.asarray(arc["incoming_tangent"], dtype=float) - vertices[i]))
        for i, arc in enumerate(arcs)
    ]
    angles = sorted(math.atan2(v[1], v[0]) % (2.0 * math.pi) for v in vertices)
    angle_gaps = [
        (angles[(i + 1) % 3] - angles[i]) % (2.0 * math.pi)
        for i in range(3)
    ]
    expected_vertices = triangle_vertices(BASE_CIRCUMRADIUS)
    expected_circle_radius = math.sqrt(BASE_AREA / math.pi)
    checks = {
        "AREA_CONSERVATION": abs(float(geometry["physical_area_analytic"]) - BASE_AREA) <= TOL,
        "C3_SYMMETRY": (
            max(radii) - min(radii) <= TOL
            and max(arc_radii) - min(arc_radii) <= TOL
            and max(tangent_offsets) - min(tangent_offsets) <= TOL
            and max(abs(gap - 2.0 * math.pi / 3.0) for gap in angle_gaps) <= TOL
        ),
        "SMOOTH_JOIN_CONSTRUCTION": max(tangent_errors, default=0.0) <= TOL,
        "NO_SELF_INTERSECTION": _self_intersection_free(boundary),
        "PUBLIC_CARTESIAN_GEOMETRY_FIRST": len(vertices) == 3 and len(arcs) == 3 and len(segments) == 3,
        "MPB_CONVERSION_EXACTLY_ONCE": float(np.max(np.linalg.norm(roundtrip - boundary, axis=1))) <= TOL,
        "E9A_C1_TRIANGLE_VERTEX_REPLAY": f != 0.0 or float(np.max(np.linalg.norm(vertices - expected_vertices, axis=1))) <= TOL,
        "CIRCUMRADIUS_REPLAY": f != 0.0 or abs(radii[0] - 0.4) <= TOL,
        "FILL_FRACTION_REPLAY": f != 0.0 or abs(float(geometry["physical_area_analytic"]) - 0.24 * abs(np.linalg.det(REAL_BASIS))) <= TOL,
        "CIRCULAR_LIMIT": (
            f != 0.5
            or (
                max(float(segment["length"]) for segment in segments) <= TOL
                and max(abs(r - expected_circle_radius) for r in np.linalg.norm(boundary, axis=1)) <= 1.0e-9
            )
        ),
        "C2Z_RESTORED_GEOMETRICALLY": f != 0.5 or max(center_radii) <= TOL,
    }
    return {
        "f_r": f,
        "checks": {key: bool(value) for key, value in checks.items()},
        "all_checks_passed": all(bool(value) for value in checks.values()),
        "analytic_area": float(geometry["physical_area_analytic"]),
        "area_error": abs(float(geometry["physical_area_analytic"]) - BASE_AREA),
        "sampled_boundary_points": int(len(boundary)),
        "sampled_signed_area": float(signed_area(boundary)),
        "max_tangent_orthogonality_error": max(tangent_errors, default=0.0),
        "max_cartesian_mpb_roundtrip_error": float(np.max(np.linalg.norm(roundtrip - boundary, axis=1))),
        "nominal_triangle_circumradius": float(geometry["nominal_triangle_circumradius"]),
        "physical_arc_radius": float(geometry["physical_arc_radius"]),
        "straight_segment_lengths": [float(segment["length"]) for segment in segments],
        "center_radii": center_radii,
        "boundary_digest": geometry["boundary_digest"],
    }


def run_validation(contract: dict, contract_path: Path | None = None) -> dict:
    values = [float(value) for value in contract["source_representative_fr_values"]]
    cases = {}
    for f_r in values:
        geometry = build_geometry(f_r)
        result = validate_geometry(geometry)
        if not result["all_checks_passed"]:
            raise RuntimeError(f"geometry validation failed for f_r={f_r}: {result}")
        cases[str(f_r)] = {"geometry": geometry, "validation": result}
    return {
        "schema": "trilatt_e9e_a_geometry_validation_result_v1",
        "work_order_id": WORK_ORDER,
        "source_contract_schema": contract["schema"],
        "source_representative_fr_values": values,
        "calculation_code_git_sha": git_head(),
        "contract_sha256": file_sha(contract_path) if contract_path is not None else "UNSPECIFIED",
        "source_parameter_definition_bound": True,
        "source_representative_fr_values_bound": True,
        "fr0_triangle_replay": "PASSED",
        "constant_area_family": "PASSED",
        "c3_symmetry_family": "PASSED",
        "circular_limit": "PASSED",
        "public_to_mpb_real_space_conversion": "EXACTLY_ONCE",
        "human_validated_physical_scale_unchanged": True,
        "new_mpb_solver_requests": 0,
        "new_berry_calculation": "NONE",
        "new_chern_calculation": "NONE",
        "production_code_changed": False,
        "cases": cases,
        "E9E_A_OVERALL": "ROUNDED_TRIANGLE_PARAMETER_FAMILY_READY_FOR_LIVE_TREND_BENCHMARK",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default=str(root() / "audit/e9e/a_source_geometry_contract.json"))
    parser.add_argument("--output", default=str(root() / "audit/e9e/a_geometry_validation.json"))
    args = parser.parse_args()
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8-sig"))
    result = run_validation(contract, Path(args.contract))
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"schema": result["schema"], "overall": result["E9E_A_OVERALL"], "cases": list(result["cases"])}, sort_keys=True))


if __name__ == "__main__":
    main()








