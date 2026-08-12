"""Geometry realization helpers for the shared R5 deformation field."""

from __future__ import annotations

import numpy as np

from .deformation import canonicalize_field


def deform_points(points, field):
    return canonicalize_field(field).map_points(points)


def deform_polygon_rigid(polygon, field):
    values = np.asarray(polygon, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2 or len(values) == 0 or not np.all(np.isfinite(values)):
        raise ValueError("polygon must have shape (N, 2) with finite N > 0")
    field = canonicalize_field(field)
    center = np.mean(values, axis=0)
    return values + field.displacement(center)[0]


def deform_pattern_rigid(pattern, field):
    """Apply one center displacement per polygon; vertices stay rigid."""
    if isinstance(pattern, np.ndarray) and pattern.ndim == 2:
        return deform_polygon_rigid(pattern, field)
    if isinstance(pattern, (list, tuple)):
        return type(pattern)(deform_pattern_rigid(item, field) for item in pattern)
    raise ValueError("pattern must be a polygon array or nested list/tuple of polygons")


def replicated_lattice_sites(lattice, replication=(1, 1), field=None):
    """Generate canonical integer-cell positions in stable row-major order."""
    if len(replication) != 2 or any(int(value) != value or int(value) < 1 for value in replication):
        raise ValueError("replication must contain two positive integers")
    nx, ny = int(replication[0]), int(replication[1])
    values, ids = [], []
    basis = np.asarray(lattice.direct_basis, dtype=float)
    for i in range(nx):
        for j in range(ny):
            values.append(np.array([i, j], dtype=float) @ basis.T)
            ids.append(f"site-{i:04d}-{j:04d}")
    reference = np.asarray(values, dtype=float)
    return {
        "ids": tuple(ids),
        "reference_positions": reference,
        "positions": canonicalize_field(field).map_points(reference),
    }


def replicated_rigid_pattern(pattern, lattice, replication=(1, 1), field=None):
    """Replicate motifs from canonical lattice coordinates and then deform centers."""
    if isinstance(pattern, np.ndarray) and pattern.ndim == 2:
        base = [pattern]
    else:
        base = [np.asarray(item, dtype=float) for item in pattern]
    sites = replicated_lattice_sites(lattice, replication=replication, field=field)
    result = []
    for reference_center, displaced_center in zip(sites["reference_positions"], sites["positions"]):
        delta = displaced_center - reference_center
        result.extend([polygon + reference_center + delta for polygon in base])
    return result


__all__ = [
    "deform_points", "deform_polygon_rigid", "deform_pattern_rigid",
    "replicated_lattice_sites", "replicated_rigid_pattern",
]
