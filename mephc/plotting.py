from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import Normalize
import numpy as np
from scipy.interpolate import griddata
from scipy.spatial import ConvexHull, cKDTree
from shapely.geometry import MultiPoint, Polygon as ShapelyPolygon
from shapely.ops import unary_union, voronoi_diagram


def _save_show_close(fig, save_path=None, show: bool = False, dpi: int = 100):
    if save_path is not None:
        save_path = Path(save_path)
        if save_path.parent:
            save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    else:
        plt.close(fig)


def _sequence_value(values, index):
    if values is None:
        return None
    values = list(values)
    if not values:
        return None
    return values[index % len(values)]


def _apply_axes_style(
    ax,
    *,
    title=None,
    xlabel=None,
    ylabel=None,
    font_size=None,
    tick_size=None,
    grid=True,
    grid_kwargs=None,
    legend=True,
    legend_kwargs=None,
):
    if title is not None:
        ax.set_title(title, fontsize=font_size)
    if xlabel is not None:
        ax.set_xlabel(xlabel, fontsize=font_size)
    if ylabel is not None:
        ax.set_ylabel(ylabel, fontsize=font_size)
    if tick_size is not None:
        ax.tick_params(labelsize=tick_size)
    if grid:
        default_grid = {"linestyle": ":", "linewidth": 0.5}
        if grid_kwargs:
            default_grid.update(grid_kwargs)
        ax.grid(True, **default_grid)
    else:
        ax.grid(False)
    if legend:
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(**(legend_kwargs or {}))


def _add_colorbar(fig, ax, mappable, *, colorbar=True, colorbar_label=None, colorbar_kwargs=None):
    if not colorbar or mappable is None:
        return None
    kwargs = dict(colorbar_kwargs or {})
    if colorbar_label is not None and "label" not in kwargs:
        kwargs["label"] = colorbar_label
    return fig.colorbar(mappable, ax=ax, **kwargs)


def _band_bc_values(bc_values, band_index, expected_len):
    if bc_values is None:
        return None
    values = np.asarray(bc_values, dtype=float)
    if values.ndim == 2:
        if band_index < 0 or band_index >= values.shape[1]:
            raise ValueError(f"band_index must be between 0 and {values.shape[1] - 1} for bc_values.")
        values = values[:, band_index]
    elif values.ndim != 1:
        raise ValueError("bc_values must have shape (N,) or (N, num_bands).")
    if values.shape[0] != expected_len:
        raise ValueError("bc_values must have the same first dimension as freqs.")
    return values


def _colored_line(ax, x, y, colors, *, cmap, norm, linewidth, alpha, linestyle, label, zorder=None):
    points = np.column_stack([x, y]).reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    segment_colors = 0.5 * (colors[:-1] + colors[1:]) if len(colors) > 1 else colors
    collection = LineCollection(
        segments,
        array=segment_colors,
        cmap=cmap,
        norm=norm,
        linewidths=linewidth,
        alpha=alpha,
        linestyles=linestyle,
        label=label,
        zorder=zorder,
    )
    ax.add_collection(collection)
    ax.autoscale_view()
    return collection


def plot_band_path(
    result: dict,
    use_actual: bool = True,
    band_indices=None,
    title: str | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
    figsize=(6, 4),
    dpi: int = 100,
    line: bool = True,
    scatter: bool = False,
    color_list=None,
    linewidth: float = 1.5,
    markersize: float = 18,
    scatter_edgecolor="black",
    scatter_linewidth: float = 0.5,
    line_zorder: float = 2,
    scatter_zorder: float = 3,
    alpha: float = 1.0,
    linestyle: str = "-",
    marker: str = "o",
    xlabel: str | None = None,
    ylabel: str | None = None,
    font_size: float | None = None,
    tick_size: float | None = None,
    grid: bool = True,
    grid_kwargs: dict | None = None,
    legend: bool | None = None,
    legend_kwargs: dict | None = None,
    colorbar: bool = True,
    colorbar_kwargs: dict | None = None,
    bc_values=None,
    bc_cmap: str = "RdBu_r",
    bc_vmin=None,
    bc_vmax=None,
    bc_label: str = "Berry curvature",
):
    """Plot frequency along a high-symmetry path.

    ``use_actual`` selects THz data when available. ``band_indices`` uses
    Python 0-based indices; ``None`` draws all bands. ``line`` and ``scatter``
    are independent switches, and scatter is drawn above line by default.

    ``color_list`` is indexed cyclically by band; ``None`` uses Matplotlib's
    color cycle. ``markersize`` is scatter area in points squared.
    ``scatter_edgecolor`` defaults to black so zero-BC white markers remain
    visible.

    When ``bc_values`` is supplied with shape ``(N,)`` or
    ``(N, num_bands)``, it controls line/marker color only. Use ``bc_vmin`` and
    ``bc_vmax`` for normalization. ``colorbar_kwargs`` controls the colorbar
    appearance, not its value limits.

    Returns ``(fig, ax)``. With ``show=False`` the figure is closed after
    creation, but the returned objects remain inspectable.
    """
    freqs = np.asarray(result["actual_freqs"] if use_actual and "actual_freqs" in result else result["freqs"], dtype=float)
    distances = np.asarray(result["distances"], dtype=float)
    if freqs.ndim != 2 or freqs.shape[0] != distances.shape[0]:
        raise ValueError("Band path result must contain freqs with shape (N, num_bands).")
    if band_indices is None:
        band_indices = range(freqs.shape[1])
    band_indices = list(band_indices)
    if not line and not scatter:
        raise ValueError("At least one of line or scatter must be True.")

    if legend is None:
        legend = freqs.shape[1] <= 8 and bc_values is None

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    mappable = None
    bc_array = None if bc_values is None else np.asarray(bc_values, dtype=float)
    norm = None
    if bc_array is not None:
        finite = bc_array[np.isfinite(bc_array)]
        if finite.size:
            limit = float(np.nanmax(np.abs(finite)))
            if bc_vmin is None:
                bc_vmin = -limit
            if bc_vmax is None:
                bc_vmax = limit
        norm = Normalize(vmin=bc_vmin, vmax=bc_vmax)

    for band_index in band_indices:
        if band_index < 0 or band_index >= freqs.shape[1]:
            raise ValueError(f"band_index must be between 0 and {freqs.shape[1] - 1}")
        y = freqs[:, band_index]
        label = f"Band {band_index + 1}"
        bc_band = _band_bc_values(bc_values, band_index, len(distances))
        if bc_band is not None:
            if line:
                mappable = _colored_line(
                    ax,
                    distances,
                    y,
                    bc_band,
                    cmap=bc_cmap,
                    norm=norm,
                    linewidth=linewidth,
                    alpha=alpha,
                    linestyle=linestyle,
                    label=label,
                    zorder=line_zorder,
                )
            if scatter:
                mappable = ax.scatter(
                    distances,
                    y,
                    c=bc_band,
                    cmap=bc_cmap,
                    norm=norm,
                    s=markersize,
                    edgecolors=scatter_edgecolor,
                    linewidths=scatter_linewidth,
                    alpha=alpha,
                    marker=marker,
                    label=label if not line else None,
                    zorder=scatter_zorder,
                )
        else:
            color = _sequence_value(color_list, band_index)
            if line:
                ax.plot(
                    distances,
                    y,
                    color=color,
                    linewidth=linewidth,
                    alpha=alpha,
                    linestyle=linestyle,
                    label=label,
                    zorder=line_zorder,
                )
            if scatter:
                ax.scatter(
                    distances,
                    y,
                    color=color,
                    s=markersize,
                    edgecolors=scatter_edgecolor,
                    linewidths=scatter_linewidth,
                    alpha=alpha,
                    marker=marker,
                    label=label if not line else None,
                    zorder=scatter_zorder,
                )

    tick_positions = result.get("tick_positions")
    labels = result.get("labels")
    if tick_positions is not None and labels is not None:
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(labels)
        for position in tick_positions:
            ax.axvline(position, color="0.8", linewidth=0.8, zorder=0)

    ax.set_xlim(float(distances.min()), float(distances.max()))
    default_ylabel = "Frequency (THz)" if use_actual else "Normalized frequency"
    _apply_axes_style(
        ax,
        title=title or "Band structure",
        xlabel=xlabel,
        ylabel=ylabel or default_ylabel,
        font_size=font_size,
        tick_size=tick_size,
        grid=grid,
        grid_kwargs=grid_kwargs,
        legend=legend,
        legend_kwargs=legend_kwargs,
    )
    _add_colorbar(fig, ax, mappable, colorbar=colorbar, colorbar_label=bc_label, colorbar_kwargs=colorbar_kwargs)
    fig.tight_layout()
    _save_show_close(fig, save_path=save_path, show=show, dpi=dpi)
    return fig, ax



def _regular_grid_from_points(k_points, values, tolerance: float = 1e-10):
    xs = np.unique(np.round(k_points[:, 0] / tolerance).astype(np.int64)) * tolerance
    ys = np.unique(np.round(k_points[:, 1] / tolerance).astype(np.int64)) * tolerance
    if len(xs) * len(ys) != len(k_points):
        return None
    x_index = {int(round(x / tolerance)): idx for idx, x in enumerate(xs)}
    y_index = {int(round(y / tolerance)): idx for idx, y in enumerate(ys)}
    grid_z = np.full((len(ys), len(xs)), np.nan, dtype=float)
    for point, value in zip(k_points, values):
        xi = x_index[int(round(point[0] / tolerance))]
        yi = y_index[int(round(point[1] / tolerance))]
        if np.isfinite(grid_z[yi, xi]):
            return None
        grid_z[yi, xi] = value
    if np.isnan(grid_z).any():
        return None
    grid_x, grid_y = np.meshgrid(xs, ys)
    return grid_x, grid_y, grid_z


def _coalesce_scalar_samples(k_points, values, tolerance: float = 1e-10):
    """Merge coordinate duplicates only when their scalar values agree."""
    scale = 1.0 / float(tolerance)
    unique_points = []
    unique_values = []
    positions = {}
    for point, value in zip(k_points, values):
        key = tuple(np.round(np.asarray(point, dtype=float) * scale).astype(np.int64))
        if key in positions:
            previous = unique_values[positions[key]]
            if not np.isclose(previous, value, rtol=1e-9, atol=tolerance, equal_nan=True):
                raise ValueError("Duplicate k-point coordinates contain conflicting scalar values.")
            continue
        positions[key] = len(unique_points)
        unique_points.append(np.asarray(point, dtype=float))
        unique_values.append(float(value))
    return np.asarray(unique_points, dtype=float), np.asarray(unique_values, dtype=float)


def sample_cell_polygons(k_points, domain_outline=None):
    """Return disjoint Voronoi sample cells clipped to one physical domain."""
    points = np.asarray(k_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        raise ValueError("Sample-cell tiling requires at least three 2D k-points.")
    if len(np.unique(np.round(points, 12), axis=0)) != len(points):
        raise ValueError("Sample-cell tiling requires unique k-point coordinates.")
    if domain_outline is None:
        hull = ConvexHull(points)
        domain = ShapelyPolygon(points[hull.vertices])
    else:
        outline = np.asarray(domain_outline, dtype=float)
        if outline.ndim != 2 or outline.shape[1] != 2 or len(outline) < 3:
            raise ValueError("domain_outline must have shape (N, 2) with N >= 3.")
        domain = ShapelyPolygon(outline)
    if not domain.is_valid or domain.area <= 0:
        raise ValueError("domain_outline must define a valid non-empty polygon.")

    diagram = voronoi_diagram(MultiPoint(points), envelope=domain.envelope, edges=False)
    tree = cKDTree(points)
    cells = []
    indices = []
    covered_sites = set()
    for polygon in diagram.geoms:
        representative = polygon.representative_point()
        index = int(tree.query((representative.x, representative.y))[1])
        clipped = polygon.intersection(domain)
        if clipped.is_empty:
            continue
        pieces = [clipped] if clipped.geom_type == "Polygon" else list(getattr(clipped, "geoms", ()))
        for piece in pieces:
            if piece.geom_type != "Polygon" or piece.area <= 0:
                continue
            cells.append(np.asarray(piece.exterior.coords[:-1], dtype=float))
            indices.append(index)
            covered_sites.add(index)
    if len(covered_sites) != len(points):
        raise ValueError("Some k-points do not have a sample cell inside the plotting domain.")
    union = unary_union([ShapelyPolygon(vertices) for vertices in cells])
    tolerance = 1e-9 * max(1.0, float(domain.area))
    total_area = sum(float(ShapelyPolygon(vertices).area) for vertices in cells)
    if abs(total_area - float(union.area)) > tolerance:
        raise ValueError("Sample cells overlap inside the plotting domain.")
    if abs(float(union.area) - float(domain.area)) > tolerance:
        raise ValueError("Sample cells do not cover the complete plotting domain.")
    return cells, np.asarray(indices, dtype=int), domain


def plot_scalar_field(
    k_points,
    values,
    mesh_size: int = 200,
    interpolation: str = "linear",
    cmap: str = "RdBu_r",
    title: str | None = None,
    colorbar_label: str = "Value",
    save_path: str | Path | None = None,
    show: bool = False,
    figsize=(5, 5),
    dpi: int = 100,
    vmin=None,
    vmax=None,
    xlabel: str | None = "kx",
    ylabel: str | None = "ky",
    font_size: float | None = None,
    tick_size: float | None = None,
    grid: bool = True,
    grid_kwargs: dict | None = None,
    colorbar: bool = True,
    colorbar_kwargs: dict | None = None,
    shading: str = "auto",
    render_mode: str = "linear",
    domain_outline=None,
):
    """Plot scalar values over 2D Cartesian reciprocal space.

    ``render_mode='sample_cells'`` displays one disjoint Voronoi cell per
    original sample and clips the cells to ``domain_outline``. A complete
    regular grid is reshaped directly for the other modes. For scattered input,
    ``render_mode='native'`` renders the original samples on their Delaunay
    triangles without creating a regular display grid. ``render_mode='linear'``
    uses SciPy ``griddata``; only then does ``mesh_size`` control output pixels.
    ``vmin``/``vmax`` set colormap limits.
    """
    k_points = np.asarray(k_points, dtype=float)
    values = np.asarray(values, dtype=float)
    if k_points.ndim != 2 or k_points.shape[1] != 2:
        raise ValueError("k_points must have shape (N, 2).")
    if values.ndim != 1 or values.shape[0] != k_points.shape[0]:
        raise ValueError("values must have shape (N,).")
    if len(k_points) < 3:
        raise ValueError("At least three k-points are required to plot a scalar field.")

    if render_mode not in {"sample_cells", "native", "linear"}:
        raise ValueError("render_mode must be 'sample_cells', 'native', or 'linear'")

    k_points, values = _coalesce_scalar_samples(k_points, values)

    regular_grid = _regular_grid_from_points(k_points, values)
    if regular_grid is None and render_mode == "linear":
        grid_x, grid_y = np.meshgrid(
            np.linspace(k_points[:, 0].min(), k_points[:, 0].max(), int(mesh_size)),
            np.linspace(k_points[:, 1].min(), k_points[:, 1].max(), int(mesh_size)),
        )
        grid_z = griddata(k_points, values, (grid_x, grid_y), method=interpolation)
    elif regular_grid is not None:
        grid_x, grid_y, grid_z = regular_grid

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    if render_mode == "sample_cells":
        polygons, value_indices, domain = sample_cell_polygons(k_points, domain_outline)
        norm = Normalize(vmin=vmin, vmax=vmax)
        norm.autoscale_None(values[value_indices])
        image = PolyCollection(
            polygons,
            array=values[value_indices],
            cmap=cmap,
            norm=norm,
            edgecolors="none",
            linewidths=0.0,
            antialiased=False,
        )
        ax.add_collection(image)
        min_x, min_y, max_x, max_y = domain.bounds
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(min_y, max_y)
    elif regular_grid is None and render_mode == "native":
        image = ax.tripcolor(
            k_points[:, 0], k_points[:, 1], values,
            shading="flat", cmap=cmap, vmin=vmin, vmax=vmax,
        )
    else:
        image = ax.pcolormesh(grid_x, grid_y, grid_z, shading=shading, cmap=cmap, vmin=vmin, vmax=vmax)
    _add_colorbar(fig, ax, image, colorbar=colorbar, colorbar_label=colorbar_label, colorbar_kwargs=colorbar_kwargs)
    ax.set_aspect("equal", adjustable="box")
    _apply_axes_style(
        ax,
        title=title or "K-space scalar field",
        xlabel=xlabel,
        ylabel=ylabel,
        font_size=font_size,
        tick_size=tick_size,
        grid=grid,
        grid_kwargs=grid_kwargs,
        legend=False,
    )
    fig.tight_layout()
    _save_show_close(fig, save_path=save_path, show=show, dpi=dpi)
    return fig, ax
