from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
import numpy as np
from scipy.interpolate import griddata


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
):
    """Plot scalar values over 2D Cartesian reciprocal space.

    A complete regular grid is reshaped directly, with no Delaunay or scattered
    interpolation. Only incomplete input uses SciPy ``griddata``; then
    ``mesh_size`` controls output pixels and ``interpolation`` selects the
    method. ``vmin``/``vmax`` set colormap limits, while ``colorbar_kwargs``
    controls colorbar appearance.
    """
    k_points = np.asarray(k_points, dtype=float)
    values = np.asarray(values, dtype=float)
    if k_points.ndim != 2 or k_points.shape[1] != 2:
        raise ValueError("k_points must have shape (N, 2).")
    if values.ndim != 1 or values.shape[0] != k_points.shape[0]:
        raise ValueError("values must have shape (N,).")
    if len(k_points) < 3:
        raise ValueError("At least three k-points are required to plot a scalar field.")

    regular_grid = _regular_grid_from_points(k_points, values)
    if regular_grid is None:
        grid_x, grid_y = np.meshgrid(
            np.linspace(k_points[:, 0].min(), k_points[:, 0].max(), int(mesh_size)),
            np.linspace(k_points[:, 1].min(), k_points[:, 1].max(), int(mesh_size)),
        )
        grid_z = griddata(k_points, values, (grid_x, grid_y), method=interpolation)
    else:
        grid_x, grid_y, grid_z = regular_grid

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
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
