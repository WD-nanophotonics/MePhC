from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

from mephc.lattice import show_coordinate
from mephc.preview import _as_polygons, preview_pattern

from .cases import CASES, get_geometry_id, load_config


def _case_geometry(case_id, config):
    pattern = config.build_pattern()
    if case_id == "square":
        preview_data = config.preview_pattern_data()
        outline = np.asarray(config.unit_cell_outline(), dtype=float)
        lattice = config.canonical_structure().lattice
    else:
        preview_data = pattern
        outer = getattr(pattern, "outer_instance", None)
        outline = np.asarray(getattr(outer, "outline", []), dtype=float)
        lattice = config.canonical_lattice()
    polygons = _deduplicate_polygons(_as_polygons(preview_data))
    return polygons, outline, np.asarray(lattice.direct_basis, dtype=float)


def _deduplicate_polygons(polygons):
    unique = []
    seen = set()
    for polygon in polygons:
        polygon = np.asarray(polygon, dtype=float)
        key = tuple(np.round(np.mean(polygon, axis=0), 10))
        if key not in seen:
            seen.add(key)
            unique.append(polygon)
    return unique


def _indices(count: int) -> np.ndarray:
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > 31:
        raise ValueError("preview cell counts must be integers from 1 to 31")
    return np.arange(count, dtype=float) - 0.5 * (count - 1)


def _translations(basis: np.ndarray, cells_x: int, cells_y: int) -> np.ndarray:
    return np.asarray([basis @ np.array([i, j]) for i in _indices(cells_x) for j in _indices(cells_y)])


def _square_translations(basis: np.ndarray, span: float, *, margin: float = 0.0) -> np.ndarray:
    """Return every lattice translation inside a Cartesian square viewport."""
    basis = np.asarray(basis, dtype=float)
    span = float(span)
    if basis.shape != (2, 2) or abs(float(np.linalg.det(basis))) < 1e-12:
        raise ValueError("preview requires an invertible 2D direct basis")
    if not 1 <= span <= 31:
        raise ValueError("preview span must be from 1 to 31")
    half = 0.5 * span + float(margin)
    corners = np.asarray([[-half, -half], [-half, half], [half, -half], [half, half]])
    coefficients = (np.linalg.inv(basis) @ corners.T).T
    lower = np.floor(coefficients.min(axis=0)).astype(int) - 1
    upper = np.ceil(coefficients.max(axis=0)).astype(int) + 1
    points = []
    for i in range(lower[0], upper[0] + 1):
        for j in range(lower[1], upper[1] + 1):
            point = basis @ np.asarray([i, j], dtype=float)
            if np.max(np.abs(point)) <= half + 1e-10:
                points.append(point)
    return np.asarray(points, dtype=float).reshape(-1, 2)


def _style_axes(axes, title):
    axes.set_aspect("equal", adjustable="box")
    axes.set_title(title)
    axes.set_xlabel("x / a")
    axes.set_ylabel("y / a")
    axes.grid(True, linestyle=":", linewidth=0.5, alpha=0.6)


def _set_square_limits(axes, points, *, padding_fraction: float = 0.08):
    """Set centered square data limits that contain every supplied point."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    finite = points[np.isfinite(points).all(axis=1)]
    if not len(finite):
        finite = np.zeros((1, 2), dtype=float)
    lower = finite.min(axis=0)
    upper = finite.max(axis=0)
    center = 0.5 * (lower + upper)
    span = max(float(np.max(upper - lower)), 1.0)
    half = 0.5 * span * (1.0 + 2.0 * padding_fraction)
    axes.set_xlim(center[0] - half, center[0] + half)
    axes.set_ylim(center[1] - half, center[1] + half)


def build_preview_figures(
    case_id: str,
    geometry: dict,
    *,
    span: float | None = None,
    cells_x: int = 7,
    cells_y: int = 5,
    root=None,
) -> dict:
    # cells_x/cells_y remain keyword-compatible for callers and old tests;
    # Studio profiles migrate them to one physical square span.
    span = float(max(cells_x, cells_y) if span is None else span)
    config = load_config(case_id, geometry, root)
    polygons, outline, basis = _case_geometry(case_id, config)
    label = f"{CASES[case_id].label}: {get_geometry_id(case_id, config)}"

    unit_data = config.preview_pattern_data() if case_id == "square" else config.build_pattern()
    unit_figure, unit_axes = preview_pattern(unit_data, outline=outline, show=False)
    unit_axes.set_aspect("equal", adjustable="box")
    unit_axes.set_title(f"Unit cell — {label}")

    motif_margin = max((float(np.max(np.abs(polygon))) for polygon in polygons), default=0.0)
    candidate_translations = _square_translations(basis, span, margin=motif_margin)
    half = 0.5 * span
    translations = _square_translations(basis, span)
    motif_figure, motif_axes = plt.subplots()
    shifted_polygons = []
    for shift in candidate_translations:
        for polygon in polygons:
            shifted = polygon + shift
            lower, upper = shifted.min(axis=0), shifted.max(axis=0)
            if np.all(upper >= -half) and np.all(lower <= half):
                shifted_polygons.append(shifted)
                motif_axes.add_patch(Polygon(shifted, closed=True, edgecolor="C0", facecolor="C0", alpha=0.24, linewidth=0.8))
    motif_axes.set_xlim(-half, half)
    motif_axes.set_ylim(-half, half)
    _style_axes(motif_axes, f"Motif array ({span:g}a square) — {label}")
    motif_figure.tight_layout()

    sites_figure, sites_axes = plt.subplots()
    scatter = sites_axes.scatter(translations[:, 0], translations[:, 1], s=24, c="C1", edgecolors="black", linewidths=0.4)
    show_coordinate(sites_figure, sites_axes, scatter)
    origin = np.zeros(2)
    for index, color in ((0, "C0"), (1, "C3")):
        vector = basis[:, index]
        sites_axes.arrow(*origin, *vector, color=color, width=0.01, length_includes_head=True)
        sites_axes.text(*(1.08 * vector), f"a{index + 1}", color=color)
    sites_axes.set_xlim(-half, half)
    sites_axes.set_ylim(-half, half)
    _style_axes(sites_axes, f"Lattice sites ({span:g}a square) — {label}")
    sites_figure.tight_layout()
    return {"unit": unit_figure, "motif": motif_figure, "sites": sites_figure}
