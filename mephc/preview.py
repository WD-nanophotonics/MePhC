from __future__ import annotations

from collections.abc import Mapping

import matplotlib.pyplot as plt
import meep as mp
from meep import mpb
import numpy as np

from .geometry import regular_polygon_vertices
from .lattice import plot_many


def _dict_to_preview_polygons(radius_by_position):
    return [regular_polygon_vertices(tuple(position), float(radius), 32) for position, radius in radius_by_position.items()]


def preview_pattern(pattern, outline=None, show: bool = True):
    """Preview pattern geometry without running MPB or saving records.

    ``outline`` is an optional unit-cell polygon. ``show=False`` creates and
    closes the figure for non-interactive validation.
    """
    preview_data = _dict_to_preview_polygons(pattern) if isinstance(pattern, Mapping) else pattern
    outlines = [] if outline is None else [np.asarray(outline, dtype=float)]
    fig, ax = plt.subplots()

    if preview_data is not None:
        for poly in _dict_to_preview_polygons(pattern) if isinstance(pattern, Mapping) else _as_polygons(preview_data):
            poly = np.asarray(poly, dtype=float)
            x = np.append(poly[:, 0], poly[0, 0])
            y = np.append(poly[:, 1], poly[0, 1])
            ax.plot(x, y, "b-")
            ax.fill(poly[:, 0], poly[:, 1], alpha=0.2)

    for outline_poly in outlines:
        x = np.append(outline_poly[:, 0], outline_poly[0, 0])
        y = np.append(outline_poly[:, 1], outline_poly[0, 1])
        ax.plot(x, y, "k--", linewidth=1.0)

    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Unit-cell pattern preview")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.grid(True, linestyle=":", linewidth=0.5)
    fig.tight_layout()
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig, ax


def _as_polygons(data):
    if hasattr(data, "pattern"):
        data = data.pattern
    if isinstance(data, np.ndarray):
        array = np.asarray(data, dtype=float)
        if array.ndim != 2 or array.shape[1] != 2:
            raise ValueError("Pattern arrays must have shape (N, 2).")
        return [array]
    if isinstance(data, list):
        result = []
        for item in data:
            result.extend(_as_polygons(item))
        return result
    raise ValueError("Invalid pattern data type for preview.")


def preview_mpb_dielectric(band, pattern, num_bands: int = 1, k_point=None, periods: int = 3, show: bool = True):
    """Preview raw and rectified MPB dielectric arrays without saving records.

    ``k_point`` uses Cartesian reciprocal coordinates unless it is already an
    ``mp.Vector3``. ``periods`` changes only the rectified preview extent, not
    the simulated unit cell.
    """
    if k_point is None:
        k_point = mp.Vector3()
    elif not isinstance(k_point, mp.Vector3):
        k_point = mp.cartesian_to_reciprocal(mp.Vector3(float(k_point[0]), float(k_point[1]), 0), band.geo_latt)

    feature_geometry = band.convert_ndarray_to_meep_geo(pattern, rectify=True)
    solver = mpb.ModeSolver(
        geometry_lattice=band.geo_latt,
        geometry=band.create_material_block() + feature_geometry,
        default_material=mp.air,
        resolution=band.resolution,
        num_bands=num_bands,
        k_points=[k_point],
        verbose=False,
    )
    solver.run_parity(p=band.mpb_parity, reset_fields=True)
    epsilon = solver.get_epsilon()

    fig_raw, ax_raw = plt.subplots()
    raw_image = ax_raw.imshow(epsilon.T, interpolation="spline36", cmap="binary", origin="lower")
    fig_raw.colorbar(raw_image, ax=ax_raw, label="epsilon")
    ax_raw.set_title("MPB epsilon preview")
    ax_raw.axis("off")
    fig_raw.tight_layout()

    md = mpb.MPBData(rectify=True, resolution=max(16, band.resolution), periods=periods)
    rectangular = md.convert(epsilon)
    fig_rect, ax_rect = plt.subplots()
    rect_image = ax_rect.imshow(rectangular.T, interpolation="spline36", cmap="binary", origin="lower")
    fig_rect.colorbar(rect_image, ax=ax_rect, label="epsilon")
    ax_rect.set_title("MPB rectified epsilon preview")
    ax_rect.axis("off")
    fig_rect.tight_layout()

    if show:
        plt.show()
    else:
        plt.close(fig_raw)
        plt.close(fig_rect)
    return (fig_raw, ax_raw), (fig_rect, ax_rect)
