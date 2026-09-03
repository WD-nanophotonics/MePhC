from __future__ import annotations

from copy import deepcopy

from matplotlib.colors import is_color_like


def default_plot_style() -> dict:
    return {
        "common": {
            "figure_width": 6.0,
            "figure_height": 5.0,
            "dpi": 140,
            "title_enabled": False,
            "title": "",
            "title_font_size": 12,
            "xlabel": "",
            "ylabel": "",
            "label_font_size": 11,
            "tick_font_size": 10,
            "grid": True,
            "legend": True,
            "legend_font_size": 9,
            "xmin": "",
            "xmax": "",
            "ymin": "",
            "ymax": "",
        },
        "band": {
            "use_actual": True,
            "color_by_berry": True,
            "bc_cmap": "RdBu_r",
            "bc_vmin": "",
            "bc_vmax": "",
            "bc_colorbar": True,
            "bc_label": "Berry curvature",
            "line": True,
            "scatter": False,
            "linewidth": 1.5,
            "linestyle": "-",
            "marker": "o",
            "markersize": 18.0,
            "scatter_edgecolor": "black",
            "scatter_linewidth": 0.5,
            "color_mode": "default",
            "colors": [],
        },
        "berry": {
            "cmap": "RdBu_r",
            "render_mode": "sample_cells",
            "interpolation_resolution": 120,
            "vmin": "",
            "vmax": "",
            "colorbar": True,
            "colorbar_label": "Berry curvature",
        },
        "efs": {
            "use_actual": True,
            "cmap": "viridis",
            "interpolation_resolution": 120,
            "levels": 8,
            "colorbar": True,
            "colorbar_label": "",
        },
    }


def normalize_plot_style(value: dict | None) -> dict:
    """Return the current complete style and accept older profile fields."""
    result = default_plot_style()
    if not isinstance(value, dict):
        return result
    if any(key in value for key in ("common", "band", "berry", "efs")):
        for section in result:
            supplied = value.get(section)
            if isinstance(supplied, dict):
                supplied = deepcopy(supplied)
                if section in {"berry", "efs"} and "mesh_size" in supplied:
                    supplied.setdefault("interpolation_resolution", supplied.pop("mesh_size"))
                if section == "berry" and supplied.get("render_mode") == "native":
                    supplied["render_mode"] = "sample_cells"
                supplied.pop("band_index", None)
                result[section].update(supplied)
        return result

    # v1 had one flat plot object. Preserve every field with an unambiguous
    # destination while leaving newly introduced style fields at defaults.
    if "use_actual" in value:
        result["band"]["use_actual"] = bool(value["use_actual"])
        result["efs"]["use_actual"] = bool(value["use_actual"])
    if "cmap" in value:
        result["berry"]["cmap"] = deepcopy(value["cmap"])
        result["efs"]["cmap"] = deepcopy(value["cmap"])
    if "mesh_size" in value:
        result["berry"]["interpolation_resolution"] = deepcopy(value["mesh_size"])
        result["efs"]["interpolation_resolution"] = deepcopy(value["mesh_size"])
    if "levels" in value:
        result["efs"]["levels"] = deepcopy(value["levels"])
    return result


def validate_plot_style(style: dict) -> dict:
    style = normalize_plot_style(style)
    common, band = style["common"], style["band"]
    for key in ("figure_width", "figure_height", "dpi", "label_font_size", "tick_font_size", "legend_font_size", "title_font_size"):
        if float(common[key]) <= 0:
            raise ValueError(f"{key} must be positive")
    if not bool(band["line"]) and not bool(band["scatter"]):
        raise ValueError("Band plot requires line, scatter, or both.")
    if float(band["linewidth"]) <= 0:
        raise ValueError("band linewidth must be positive")
    if float(band["markersize"]) <= 0:
        raise ValueError("band marker size must be positive")
    if float(band["scatter_linewidth"]) < 0:
        raise ValueError("band marker edge width must be non-negative")
    band_berry_limits = [_optional_float(band[key]) for key in ("bc_vmin", "bc_vmax")]
    if band_berry_limits[0] is not None and band_berry_limits[1] is not None and band_berry_limits[0] >= band_berry_limits[1]:
        raise ValueError("Band Berry color minimum must be smaller than color maximum")
    if band["color_mode"] not in {"default", "custom"}:
        raise ValueError("color_mode must be 'default' or 'custom'")
    colors = list(band.get("colors", []))
    if band["color_mode"] == "custom" and not colors:
        raise ValueError("Custom band colors require at least one color.")
    invalid = [color for color in colors if not is_color_like(color)]
    if invalid:
        raise ValueError(f"Invalid Matplotlib color: {invalid[0]}")
    for section in ("berry", "efs"):
        if int(style[section]["interpolation_resolution"]) < 2:
            raise ValueError(f"{section} interpolation_resolution must be >= 2")
    if style["berry"]["render_mode"] not in {"sample_cells", "linear"}:
        raise ValueError("berry render_mode must be 'sample_cells' or 'linear'")
    berry_limits = [_optional_float(style["berry"][key]) for key in ("vmin", "vmax")]
    if berry_limits[0] is not None and berry_limits[1] is not None and berry_limits[0] >= berry_limits[1]:
        raise ValueError("Berry color minimum must be smaller than color maximum")
    if int(style["efs"]["levels"]) < 1:
        raise ValueError("EFS levels must be >= 1")
    limits = [_optional_float(common[key]) for key in ("xmin", "xmax", "ymin", "ymax")]
    if limits[0] is not None and limits[1] is not None and limits[0] >= limits[1]:
        raise ValueError("x min must be smaller than x max")
    if limits[2] is not None and limits[3] is not None and limits[2] >= limits[3]:
        raise ValueError("y min must be smaller than y max")
    return style


def _optional_float(value):
    return None if value in (None, "") else float(value)


def common_kwargs(style: dict) -> dict:
    common = validate_plot_style(style)["common"]
    return {
        "figsize": (float(common["figure_width"]), float(common["figure_height"])),
        "dpi": int(common["dpi"]),
        "title": str(common["title"]) if common["title_enabled"] else "",
        "xlabel": str(common["xlabel"]) or None,
        "ylabel": str(common["ylabel"]) or None,
        "font_size": float(common["label_font_size"]),
        "tick_size": float(common["tick_font_size"]),
        "grid": bool(common["grid"]),
        "legend": bool(common["legend"]),
        "legend_kwargs": {"fontsize": float(common["legend_font_size"])},
    }


def band_kwargs(style: dict) -> tuple[bool, dict]:
    style = validate_plot_style(style)
    band = style["band"]
    kwargs = common_kwargs(style)
    kwargs.update(
        line=bool(band["line"]),
        scatter=bool(band["scatter"]),
        linewidth=float(band["linewidth"]),
        linestyle=str(band["linestyle"]),
        marker=str(band["marker"]),
        markersize=float(band["markersize"]),
        scatter_edgecolor=str(band["scatter_edgecolor"]),
        scatter_linewidth=float(band["scatter_linewidth"]),
        color_list=list(band["colors"]) if band["color_mode"] == "custom" else None,
        color_by_berry=bool(band["color_by_berry"]),
        bc_cmap=str(band["bc_cmap"]),
        bc_vmin=_optional_float(band["bc_vmin"]),
        bc_vmax=_optional_float(band["bc_vmax"]),
        bc_label=str(band["bc_label"]),
        colorbar=bool(band["bc_colorbar"]),
    )
    return bool(band["use_actual"]), kwargs


def berry_kwargs(style: dict) -> dict:
    style = validate_plot_style(style)
    berry = style["berry"]
    kwargs = common_kwargs(style)
    kwargs.pop("legend", None)
    kwargs.pop("legend_kwargs", None)
    kwargs.update(
        cmap=str(berry["cmap"]),
        render_mode=str(berry["render_mode"]),
        mesh_size=int(berry["interpolation_resolution"]),
        interpolation="linear",
        vmin=_optional_float(berry["vmin"]),
        vmax=_optional_float(berry["vmax"]),
        colorbar=bool(berry["colorbar"]),
        colorbar_label=str(berry["colorbar_label"]),
    )
    return kwargs


def efs_kwargs(style: dict) -> tuple[bool, dict]:
    style = validate_plot_style(style)
    efs = style["efs"]
    kwargs = common_kwargs(style)
    kwargs.pop("legend", None)
    kwargs.pop("legend_kwargs", None)
    kwargs.update(
        cmap=str(efs["cmap"]),
        mesh_size=int(efs["interpolation_resolution"]),
        levels=int(efs["levels"]),
        colorbar=bool(efs["colorbar"]),
        colorbar_label=str(efs["colorbar_label"]) or None,
    )
    return bool(efs["use_actual"]), kwargs


def finish_figure(figure, axes, style: dict):
    common = validate_plot_style(style)["common"]
    # Downstream plot helpers deliberately close their temporary pyplot
    # manager when ``show=False``.  The Figure itself remains valid and is
    # embedded into Studio with a fresh FigureCanvasTkAgg, so do not ask the
    # already-closed backend manager to resize its former Tk widget here.
    figure.set_size_inches(float(common["figure_width"]), float(common["figure_height"]), forward=False)
    figure.set_dpi(int(common["dpi"]))
    if common["title_enabled"]:
        axes.set_title(str(common["title"]), fontsize=float(common["title_font_size"]))
    else:
        axes.set_title("")
    axes.xaxis.label.set_fontsize(float(common["label_font_size"]))
    axes.yaxis.label.set_fontsize(float(common["label_font_size"]))
    axes.tick_params(labelsize=float(common["tick_font_size"]))
    limits = [_optional_float(common[key]) for key in ("xmin", "xmax", "ymin", "ymax")]
    if limits[0] is not None or limits[1] is not None:
        axes.set_xlim(left=limits[0], right=limits[1])
    if limits[2] is not None or limits[3] is not None:
        axes.set_ylim(bottom=limits[2], top=limits[3])
    figure.tight_layout()
    return figure, axes
