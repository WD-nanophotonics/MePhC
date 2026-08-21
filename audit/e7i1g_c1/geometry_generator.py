"""Compact deterministic meshes for the exact K-point Voronoi domain.

The domain is the six-triangle analytic decomposition of the exact Voronoi
cell.  Meshes are generated only by midpoint subdivision, so every level has
the same domain and positive signed area.  The public q coordinate is the
domain coordinate translated by ``-K`` (K_y = -2/3).

This module is solver-neutral and intentionally emits meshes in memory.  Full
generated meshes are execution artefacts, not repository fixtures.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable

SQRT3 = math.sqrt(3.0)
INV_SQRT3 = 1.0 / SQRT3
K = (0.0, -2.0 / 3.0)
EXPECTED_AREA = INV_SQRT3

# The exact Voronoi pieces are retained as a compact analytic specification.
# The six seed triangles are a non-overlapping triangulation of those pieces.
DOMAIN_PIECES = (
    ((INV_SQRT3 / 2, -0.5), (0.0, -2.0 / 3), (-INV_SQRT3 / 2, -0.5),
     (INV_SQRT3 / 2, 0.5), (INV_SQRT3, 1.0 / 3), (INV_SQRT3, 0.0), (0.0, 0.0)),
    ((-INV_SQRT3, 1.0 / 3), (-INV_SQRT3 / 2, 0.5), (0.0, 0.0),
     (-INV_SQRT3, 0.0)),
)

SEED_TRIANGLES = (
    ((INV_SQRT3 / 2, 0.5), (0.0, 0.0), (INV_SQRT3, 0.0)),
    ((INV_SQRT3 / 2, 0.5), (INV_SQRT3, 0.0), (INV_SQRT3, 1.0 / 3)),
    ((INV_SQRT3 / 2, -0.5), (0.0, 0.0), (0.0, -2.0 / 3)),
    ((0.0, -2.0 / 3), (0.0, 0.0), (-INV_SQRT3 / 2, -0.5)),
    ((-INV_SQRT3, 1.0 / 3), (-INV_SQRT3, 0.0), (-INV_SQRT3 / 2, 0.5)),
    ((-INV_SQRT3 / 2, 0.5), (-INV_SQRT3, 0.0), (0.0, 0.0)),
)

LEVELS = {"coarse": 0.06, "fine": 0.03, "refined": 0.015}
EXPECTED_TRIANGLE_COUNTS = {"coarse": 1536, "fine": 6144, "refined": 24576}


def signed_area(triangle: tuple[tuple[float, float], ...]) -> float:
    a, b, c = triangle
    return 0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def edge_length(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _subdivide(triangle: tuple[tuple[float, float], ...], limit: float) -> list[tuple[tuple[float, float], ...]]:
    if max(edge_length(triangle[i], triangle[(i + 1) % 3]) for i in range(3)) <= limit + 1e-12:
        return [triangle]
    a, b, c = triangle
    ab = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    bc = ((b[0] + c[0]) / 2, (b[1] + c[1]) / 2)
    ca = ((c[0] + a[0]) / 2, (c[1] + a[1]) / 2)
    children = ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))
    result: list[tuple[tuple[float, float], ...]] = []
    for child in children:
        result.extend(_subdivide(child, limit))
    return result


def _public_triangle(triangle: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    return tuple((float(x), float(y - K[1])) for x, y in triangle)


def mesh(level: str | float) -> dict:
    limit = LEVELS[level] if isinstance(level, str) else float(level)
    triangles = [_public_triangle(t) for seed in SEED_TRIANGLES for t in _subdivide(seed, limit)]
    if any(signed_area(t) <= 0 for t in triangles):
        raise ValueError("generator produced a non-CCW triangle")
    area = sum(signed_area(t) for t in triangles)
    maximum = max(edge_length(t[i], t[(i + 1) % 3]) for t in triangles for i in range(3))
    return {
        "level": next((name for name, value in LEVELS.items() if value == limit), "custom"),
        "max_edge_limit": limit,
        "triangles": triangles,
        "triangle_count": len(triangles),
        "signed_area": area,
        "max_edge": maximum,
        "coordinate_space": "public_q=k_phys*a/(2*pi)",
    }


def mesh_fingerprint(mesh_value: dict) -> str:
    payload = [[list(point) for point in triangle] for triangle in mesh_value["triangles"]]
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def summary() -> dict:
    result = {
        "expected_area": EXPECTED_AREA,
        "seed_triangle_count": len(SEED_TRIANGLES),
        "levels": {},
    }
    for name in LEVELS:
        generated = mesh(name)
        result["levels"][name] = {
            key: generated[key]
            for key in ("triangle_count", "signed_area", "max_edge", "max_edge_limit")
        }
        result["levels"][name]["mesh_sha256"] = mesh_fingerprint(generated)
    return result


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2, sort_keys=True))
