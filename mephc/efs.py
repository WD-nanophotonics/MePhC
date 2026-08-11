from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import Rbf, griddata


@dataclass
class EFSResult:
    """Frequency samples on 2D Cartesian reciprocal k-points.

    Arrays have shape ``(num_k_points, num_bands)``. ``freqs`` is normalized
    MPB frequency and ``actual_freqs`` optionally contains THz.
    """

    k_points: np.ndarray
    freqs: np.ndarray
    actual_freqs: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.k_points = np.asarray(self.k_points, dtype=float)
        self.freqs = np.asarray(self.freqs, dtype=float)
        if self.k_points.ndim != 2 or self.k_points.shape[1] != 2:
            raise ValueError("k_points must have shape (N, 2).")
        if self.freqs.ndim != 2:
            raise ValueError("freqs must have shape (N, num_bands).")
        if self.freqs.shape[0] != self.k_points.shape[0]:
            raise ValueError("k_points and freqs must have the same first dimension.")
        if self.actual_freqs is not None:
            self.actual_freqs = np.asarray(self.actual_freqs, dtype=float)
            if self.actual_freqs.shape != self.freqs.shape:
                raise ValueError("actual_freqs must have the same shape as freqs.")

    @property
    def num_bands(self) -> int:
        return int(self.freqs.shape[1])

    def band_values(self, band_index: int, use_actual: bool = False) -> np.ndarray:
        if band_index < 0 or band_index >= self.num_bands:
            raise ValueError(f"band_index must be between 0 and {self.num_bands - 1}")
        values = self.actual_freqs if use_actual and self.actual_freqs is not None else self.freqs
        return values[:, band_index]


class EFSInterpolator:
    """Interpolate one band's EFS samples and evaluate contour normals."""

    def __init__(self, k_points, values, mesh_size: int = 300, method: str = "cubic"):
        """Configure interpolation for values sampled at ``(N, 2)`` points.

        ``mesh_size`` and ``method`` are defaults for :meth:`prepare_grid`.
        Point queries use an RBF and choose their method separately.
        """
        self.k_points = np.asarray(k_points, dtype=float)
        self.values = np.asarray(values, dtype=float)
        if self.k_points.ndim != 2 or self.k_points.shape[1] != 2:
            raise ValueError("k_points must have shape (N, 2).")
        if self.values.ndim != 1 or self.values.shape[0] != self.k_points.shape[0]:
            raise ValueError("values must have shape (N,).")
        if self.k_points.shape[0] < 3:
            raise ValueError("At least three k-points are required for EFS interpolation.")
        self.mesh_size = mesh_size
        self.method = method
        self.grid_x = None
        self.grid_y = None
        self.grid_z = None
        self._rbf_cache: dict[str, Rbf] = {}

    def prepare_grid(self, mesh_size: int | None = None, method: str | None = None):
        """Interpolate samples onto a square plotting mesh and cache it."""
        mesh_size = int(mesh_size or self.mesh_size)
        method = method or self.method
        grid_x, grid_y = np.meshgrid(
            np.linspace(self.k_points[:, 0].min(), self.k_points[:, 0].max(), mesh_size),
            np.linspace(self.k_points[:, 1].min(), self.k_points[:, 1].max(), mesh_size),
        )
        grid_z = griddata(self.k_points, self.values, (grid_x, grid_y), method=method)
        self.grid_x = grid_x
        self.grid_y = grid_y
        self.grid_z = grid_z
        return grid_x, grid_y, grid_z

    def _rbf(self, method: str = "linear") -> Rbf:
        if method not in self._rbf_cache:
            self._rbf_cache[method] = Rbf(self.k_points[:, 0], self.k_points[:, 1], self.values, function=method)
        return self._rbf_cache[method]

    def value_at(self, kx: float, ky: float, method: str = "linear") -> float:
        """Evaluate interpolated frequency at one Cartesian k-point."""
        return float(self._rbf(method)(kx, ky))

    def normal_angle(self, kx: float, ky: float, epsilon: float = 1e-5, method: str = "linear") -> float:
        """Return gradient angle in degrees from the positive kx axis."""
        rbf = self._rbf(method)
        dz_dx = (rbf(kx + epsilon, ky) - rbf(kx - epsilon, ky)) / (2 * epsilon)
        dz_dy = (rbf(kx, ky + epsilon) - rbf(kx, ky - epsilon)) / (2 * epsilon)
        return float(np.degrees(np.arctan2(dz_dy, dz_dx)))

    def cutline(self, ky: float, kx_values, method: str = "linear", epsilon: float = 1e-5):
        """Return frequencies and normal angles along a constant-ky line."""
        kx_values = np.asarray(kx_values, dtype=float)
        freqs = np.asarray([self.value_at(kx, ky, method=method) for kx in kx_values], dtype=float)
        angles = np.asarray([self.normal_angle(kx, ky, epsilon=epsilon, method=method) for kx in kx_values], dtype=float)
        return freqs, angles


def _levels_and_limits(grid_x, grid_y, grid_z, levels):
    if levels is None:
        return 10, grid_x.min(), grid_x.max(), grid_y.min(), grid_y.max()
    if isinstance(levels, int):
        return levels, grid_x.min(), grid_x.max(), grid_y.min(), grid_y.max()

    level_values = np.asarray(levels, dtype=float)
    start = np.nanmin(level_values)
    end = np.nanmax(level_values)
    relevant = (grid_z >= start) & (grid_z <= end)
    if np.any(relevant):
        return level_values, grid_x[relevant].min(), grid_x[relevant].max(), grid_y[relevant].min(), grid_y[relevant].max()
    return level_values, grid_x.min(), grid_x.max(), grid_y.min(), grid_y.max()


def plot_efs(
    result: EFSResult,
    band_index: int = 0,
    use_actual: bool = False,
    mesh_size: int = 300,
    interpolation: str = "cubic",
    levels=None,
    cmap: str = "viridis",
    linewidth: float = 1.5,
    cutline: tuple[float, np.ndarray] | None = None,
    title: str | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
    figsize=(6, 5),
    dpi: int = 100,
    xlabel: str | None = "kx",
    ylabel: str | None = "ky",
    font_size: float | None = None,
    tick_size: float | None = None,
    grid: bool = True,
    grid_kwargs: dict | None = None,
    colorbar: bool = True,
    colorbar_kwargs: dict | None = None,
    colorbar_label: str | None = None,
    cutline_kwargs: dict | None = None,
    arrow_kwargs: dict | None = None,
):
    """Plot equi-frequency contours for one Python 0-based band.

    ``use_actual=True`` selects THz values when available. ``levels`` is either
    a contour count or explicit frequency values. ``mesh_size`` and
    ``interpolation`` control interpolation before contouring. ``cutline`` is
    ``(ky, kx_values)`` and adds a horizontal line plus one normal arrow.
    """
    values = result.band_values(band_index, use_actual=use_actual)
    interpolator = EFSInterpolator(result.k_points, values, mesh_size=mesh_size, method=interpolation)
    grid_x, grid_y, grid_z = interpolator.prepare_grid()
    contour_levels, x_min, x_max, y_min, y_max = _levels_and_limits(grid_x, grid_y, grid_z, levels)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    contour = ax.contour(grid_x, grid_y, grid_z, levels=contour_levels, cmap=cmap, linewidths=linewidth)
    if colorbar:
        cbar_kwargs = dict(colorbar_kwargs or {})
        if "label" not in cbar_kwargs:
            cbar_kwargs["label"] = colorbar_label or ("Frequency (THz)" if use_actual and result.actual_freqs is not None else "Normalized frequency")
        fig.colorbar(contour, ax=ax, **cbar_kwargs)

    if cutline is not None:
        ky, kx_values = cutline
        kx_values = np.asarray(kx_values, dtype=float)
        line_kwargs = {"color": "red", "linewidth": linewidth}
        if cutline_kwargs:
            line_kwargs.update(cutline_kwargs)
        ax.plot(kx_values, np.full_like(kx_values, ky), **line_kwargs)
        if len(kx_values) > 0:
            angle = np.radians(interpolator.normal_angle(float(kx_values[0]), float(ky)))
            arr_kwargs = {
                "width": 0.001,
                "head_width": 0.01,
                "head_length": 0.01,
                "color": "black",
            }
            if arrow_kwargs:
                arr_kwargs.update(arrow_kwargs)
            ax.arrow(
                float(kx_values[0]),
                float(ky),
                0.03 * np.cos(angle),
                0.03 * np.sin(angle),
                **arr_kwargs,
            )

    ax.set_xlim(float(x_min), float(x_max))
    ax.set_ylim(float(y_min), float(y_max))
    ax.set_aspect("equal", adjustable="box")
    if xlabel is not None:
        ax.set_xlabel(xlabel, fontsize=font_size)
    if ylabel is not None:
        ax.set_ylabel(ylabel, fontsize=font_size)
    ax.set_title(title or f"Equi-frequency contour (Band {band_index + 1})", fontsize=font_size)
    if tick_size is not None:
        ax.tick_params(labelsize=tick_size)
    if grid:
        default_grid = {"linestyle": ":", "linewidth": 0.5}
        if grid_kwargs:
            default_grid.update(grid_kwargs)
        ax.grid(True, **default_grid)
    else:
        ax.grid(False)
    fig.tight_layout()

    if save_path is not None:
        save_path = Path(save_path)
        if save_path.parent:
            save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig, ax
