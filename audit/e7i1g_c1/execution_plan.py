"""Deterministic exact-domain quadrature plan without result caching."""
from __future__ import annotations

from geometry_generator import mesh


def triangle_area(triangle):
    a, b, c = triangle
    return abs(0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])))


def centroid(triangle):
    return [sum(point[0] for point in triangle) / 3.0, sum(point[1] for point in triangle) / 3.0]


def three_point(triangle):
    a, b, c = triangle
    return [
        [(2 * a[0] + b[0] + c[0]) / 4.0, (2 * a[1] + b[1] + c[1]) / 4.0],
        [(a[0] + 2 * b[0] + c[0]) / 4.0, (a[1] + 2 * b[1] + c[1]) / 4.0],
        [(a[0] + b[0] + 2 * c[0]) / 4.0, (a[1] + b[1] + 2 * c[1]) / 4.0],
    ]


def sample_key(q):
    return (round(float(q[0]), 10), round(float(q[1]), 10))


def requested_records():
    records = {}
    rules = (
        ("coarse", "coarse_centroid", lambda triangle: [(centroid(triangle), 1.0)]),
        ("fine", "fine_centroid", lambda triangle: [(centroid(triangle), 1.0)]),
        ("fine", "fine_three_point", lambda triangle: [(q, 1.0 / 3.0) for q in three_point(triangle)]),
        ("refined", "refined_centroid", lambda triangle: [(centroid(triangle), 1.0)]),
    )
    for level, rule, samples in rules:
        for index, triangle in enumerate(mesh(level)["triangles"]):
            area = triangle_area(triangle)
            for sample_index, (q, weight) in enumerate(samples(triangle)):
                records[f"{rule}:{index}:{sample_index}"] = {
                    "rule": rule,
                    "triangle_index": index,
                    "sample_index": sample_index,
                    "sample_key": list(sample_key(q)),
                    "qx": float(q[0]),
                    "qy": float(q[1]),
                    "triangle_area": area,
                    "sample_weight": weight,
                    "result": None,
                }
    return records
