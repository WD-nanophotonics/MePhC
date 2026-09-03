from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
from copy import deepcopy
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import is_color_like
import numpy as np
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from PIL import Image, ImageTk

from .cases import CASES, default_profile, get_geometry_id, load_case_module, load_config
from .diagnostics import environment_report
from .plot_style import band_kwargs, berry_kwargs, efs_kwargs, finish_figure
from .previewing import build_preview_figures
from .profiles import ProfileStore, validate_profile
from .projects import PROJECT_EXTENSION, ProjectStore, new_project, resolve_result, snapshot_result
from .recording import browse_directory, browse_pattern, discover_records, validate_record
from .rendering import render_png, save_figure


_OPERATION_FIELDS = {
    "band_structure": (("resolution", int), ("num_bands", int), ("n_per_segment", int), ("compute_bc", bool), ("berry_step", float), ("run_mode", str)),
    "berry_curvature": (("resolution", int), ("grid_n", int), ("step", float), ("target_band", int), ("shrinking", float), ("run_mode", str)),
    "efs": (("resolution", int), ("grid_n", int), ("target_band", int), ("shrinking", float), ("run_mode", str)),
    "frequency_at_k": (("resolution", int), ("num_bands", int), ("kx", float), ("ky", float)),
}

_COMMON_STYLE_FIELDS = (
    ("figure_width", float), ("figure_height", float), ("dpi", int),
    ("title_enabled", bool), ("title", str), ("title_font_size", float),
    ("xlabel", str), ("ylabel", str), ("label_font_size", float),
    ("tick_font_size", float), ("grid", bool), ("legend", bool),
    ("legend_font_size", float), ("xmin", str), ("xmax", str),
    ("ymin", str), ("ymax", str),
)
_BAND_STYLE_FIELDS = (
    ("use_actual", bool), ("color_by_berry", bool), ("bc_cmap", str),
    ("bc_vmin", str), ("bc_vmax", str), ("bc_colorbar", bool),
    ("bc_label", str), ("line", bool), ("scatter", bool),
    ("linewidth", float), ("linestyle", str), ("marker", str),
    ("markersize", float), ("scatter_edgecolor", str),
    ("scatter_linewidth", float),
)
_BERRY_STYLE_FIELDS = (
    ("cmap", str), ("render_mode", str),
    ("interpolation_resolution", int), ("vmin", str), ("vmax", str),
    ("colorbar", bool), ("colorbar_label", str),
)
_EFS_STYLE_FIELDS = (("use_actual", bool), ("cmap", str), ("interpolation_resolution", int), ("levels", int), ("colorbar", bool), ("colorbar_label", str))
_RENDER_MODE_LABELS = {"sample_cells": "Sample-cell tiling", "linear": "Linear interpolation"}
_RENDER_MODE_VALUES = {label: value for value, label in _RENDER_MODE_LABELS.items()}
_COLOR_MODE_LABELS = {"default": "Matplotlib default", "custom": "Custom cycle"}
_COLOR_MODE_VALUES = {label: value for value, label in _COLOR_MODE_LABELS.items()}
_FIELD_LABELS = {
    "compute_bc": "Compute Berry coloring along band path",
    "color_by_berry": "Color by Berry curvature when available",
    "bc_cmap": "Berry colormap",
    "bc_vmin": "Berry color minimum",
    "bc_vmax": "Berry color maximum",
    "bc_colorbar": "Berry colorbar",
    "bc_label": "Berry colorbar label",
    "span": "Span (a)",
    "target_band": "Target band (1-based)",
    "shrinking": "Boundary inset",
}


def _coerce(value, kind: type):
    if kind is bool:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError(f"expected true or false, got {value!r}")
        return normalized in {"true", "1", "yes"}
    if kind is str:
        return str(value).strip()
    return kind(value)


def _record_data_value(record: dict, name: str, default=None):
    data = record.get("data")
    if isinstance(data, dict):
        return data.get(name, default)
    return getattr(data, name, default)


def record_band_choices(record: dict, operation: str) -> tuple[list[int], int, bool]:
    """Return 1-based display choices, default choice and single-band status."""
    task = record.get("task_params") or {}
    stored_band = task.get("band_index")
    requested = 1 if stored_band is None else int(stored_band) + 1
    if operation == "berry_curvature":
        values = np.asarray(_record_data_value(record, "bcs"))
        if values.ndim == 1:
            return [requested], requested, True
        if values.ndim == 2 and values.shape[1] > 0:
            choices = list(range(1, values.shape[1] + 1))
            return choices, requested if requested in choices else choices[0], len(choices) == 1
        raise ValueError("Berry record does not contain a one- or two-dimensional bcs array.")
    if operation == "efs":
        values = _record_data_value(record, "actual_freqs")
        if values is None:
            values = _record_data_value(record, "freqs")
        values = np.asarray(values)
        if values.ndim != 2 or values.shape[1] < 1:
            raise ValueError("EFS record does not contain a two-dimensional frequency array.")
        choices = list(range(1, values.shape[1] + 1))
        return choices, requested if requested in choices else choices[0], len(choices) == 1
    return [], 1, True


def record_plot_band_index(record: dict, operation: str, displayed_band: int) -> int:
    choices, _default, single = record_band_choices(record, operation)
    if displayed_band not in choices:
        raise ValueError(f"Displayed band must be one of {choices}.")
    # A single-band Berry record stores the requested band as a one-dimensional
    # array, so its local array index is zero even when the scientific band is 2+.
    if operation == "berry_curvature" and single:
        return 0
    return displayed_band - 1


def _record_domain_outline(record: dict):
    for container in (record, record.get("metadata") or {}, record.get("task_params") or {}):
        if isinstance(container, dict) and container.get("domain_outline") is not None:
            return container["domain_outline"]
    return _record_data_value(record, "domain_outline")


class FigurePane(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=4)
        self.figure = None
        self.canvas = None
        self.toolbar = None
        self.original_limits = []

    def show(self, figure, *, equal_data_aspect=False):
        self.clear()
        self.figure = figure
        self.equal_data_aspect = bool(equal_data_aspect)
        if self.equal_data_aspect:
            for axes in figure.axes:
                axes.set_aspect("equal", adjustable="box")
        self.original_limits = [(axes.get_xlim(), axes.get_ylim()) for axes in figure.axes]
        self.canvas = FigureCanvasTkAgg(figure, master=self)
        self.canvas.draw()
        self.toolbar = NavigationToolbar2Tk(self.canvas, self, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="bottom", fill="x")
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.canvas.get_tk_widget().bind("<Configure>", self._on_resize, add="+")

    def _on_resize(self, _event):
        if self.figure is None or not getattr(self, "equal_data_aspect", False):
            return
        for axes in self.figure.axes:
            axes.set_aspect("equal", adjustable="box")
        self.canvas.draw_idle()

    def clear(self):
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
        if self.toolbar is not None:
            self.toolbar.destroy()
        if self.figure is not None:
            plt.close(self.figure)
        self.figure = self.canvas = self.toolbar = None
        self.original_limits = []

    def reset_view(self):
        if self.figure is None:
            return
        for axes, (xlim, ylim) in zip(self.figure.axes, self.original_limits):
            axes.set_xlim(xlim)
            axes.set_ylim(ylim)
        self.canvas.draw_idle()


class ExportPreviewPane(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=4)
        self.info = tk.StringVar(value="Plot a record to create an export preview.")
        ttk.Label(self, textvariable=self.info, anchor="w").pack(fill="x", pady=(0, 4))
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, background="#777777", highlightthickness=0)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.image = None

    def show_png(self, payload: bytes, *, width: float, height: float, dpi: int):
        image = Image.open(BytesIO(payload)).copy()
        self.image = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.image, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, image.width, image.height))
        self.info.set(
            f"100% export preview — {image.width} × {image.height} px "
            f"({width:g} × {height:g} in at {dpi} DPI)"
        )


class StudioApp(ttk.Frame):
    def __init__(self, master: tk.Tk, *, initial_case: str = "triangular", project_root: str | None = None):
        super().__init__(master, padding=7)
        self.master = master
        self.master.title("MePhC Lattice Studio")
        self.master.geometry("1240x820")
        self.pack(fill="both", expand=True)
        self.store = ProfileStore()
        self.profile = default_profile(initial_case)
        self.profile["project_root"] = str(Path(project_root or CASES[initial_case].default_root).expanduser().resolve())
        self.project = new_project(self.profile, self.profile["project_root"])
        self.project_path = None
        self.project_dirty = False
        self.selected_result_id = None
        self.geometry_vars = {}
        self.preview_vars = {}
        self.operation_vars = {}
        self.style_vars = {"common": {}, "band": {}, "berry": {}, "efs": {}}
        self.record_paths = {operation: "" for operation in _OPERATION_FIELDS}
        self.active_operation = "band_structure"
        self.running_operation = None
        self.geometry_dirty = False
        self._loading_form = False
        self.process = None
        self.process_group = None
        self.work_dir = None
        self.output_queue = queue.Queue()
        self.last_record = None
        self.display_band_var = tk.StringVar(value="")
        self._display_band_record_path = None
        self.log_visible = tk.BooleanVar(value=True)
        self._build_menu()
        self._build()
        self._load_profile_into_form()
        self._refresh_project_tree()
        self._update_title()
        self.master.protocol("WM_DELETE_WINDOW", self.close)

    def _build_menu(self):
        menu = tk.Menu(self.master)
        file_menu = tk.Menu(menu, tearoff=False)
        project_menu = tk.Menu(file_menu, tearoff=False)
        project_menu.add_command(label="New", command=self.new_project)
        project_menu.add_command(label="Open…", command=self.open_project)
        project_menu.add_command(label="Save", command=self.save_project)
        project_menu.add_command(label="Save As…", command=self.save_project_as)
        file_menu.add_cascade(label="Project", menu=project_menu)
        preset_menu = tk.Menu(file_menu, tearoff=False)
        preset_menu.add_command(label="Save", command=self.save_profile)
        preset_menu.add_command(label="Import…", command=self.import_profile)
        preset_menu.add_command(label="Export…", command=self.export_profile)
        file_menu.add_cascade(label="Parameter Preset", menu=preset_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Save Figure…", command=self.save_current_figure)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file_menu)
        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Reset Current View", command=self.reset_current_view)
        view_menu.add_checkbutton(label="Show Run Log", variable=self.log_visible, command=self.toggle_log)
        menu.add_cascade(label="View", menu=view_menu)
        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="MPB Dielectric Preview", command=lambda: self.run("mpb_preview"))
        tools_menu.add_command(label="Environment Diagnostics", command=self.show_diagnostics)
        menu.add_cascade(label="Tools", menu=tools_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Projects and Parameter Presets", command=self.show_project_preset_help)
        menu.add_cascade(label="Help", menu=help_menu)
        self.master.configure(menu=menu)

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Case").pack(side="left")
        self.case_var = tk.StringVar(value=self.profile["case_id"])
        self.case_box = ttk.Combobox(header, textvariable=self.case_var, state="readonly", width=12, values=list(CASES))
        self.case_box.pack(side="left", padx=4)
        self.case_box.bind("<<ComboboxSelected>>", lambda _event: self.change_case())
        ttk.Label(header, text="Parameter preset").pack(side="left", padx=(10, 0))
        self.profile_name = tk.StringVar(value="default")
        self.profile_box = ttk.Combobox(header, textvariable=self.profile_name, width=18)
        self.profile_box.pack(side="left", padx=4)
        ttk.Button(header, text="Apply preset", command=self.load_profile).pack(side="left")
        ttk.Button(header, text="Save preset", command=self.save_profile).pack(side="left", padx=(2, 14))
        ttk.Button(header, text="Refresh", command=self.refresh_views).pack(side="left")
        self.cancel_button = ttk.Button(header, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=3)

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        controls = ttk.Frame(panes, padding=(0, 0, 4, 0))
        display = ttk.Frame(panes, padding=(4, 0, 0, 0))
        panes.add(controls, weight=1)
        panes.add(display, weight=3)

        explorer = ttk.LabelFrame(controls, text="Project Explorer", padding=4)
        explorer.pack(fill="x", pady=(0, 6))
        self.project_tree = ttk.Treeview(explorer, show="tree", height=8, selectmode="browse")
        self.project_tree.pack(fill="x", expand=True)
        self.project_tree.bind("<<TreeviewSelect>>", self._project_result_selected)

        self.control_tabs = ttk.Notebook(controls)
        self.control_tabs.pack(fill="both", expand=True)
        self.geometry_page = ttk.Frame(self.control_tabs, padding=8)
        self.calculation_page = ttk.Frame(self.control_tabs, padding=8)
        self.style_page = ttk.Frame(self.control_tabs, padding=5)
        self.control_tabs.add(self.geometry_page, text="Geometry")
        self.control_tabs.add(self.calculation_page, text="Calculation")
        self.control_tabs.add(self.style_page, text="Plot Style")

        self.geometry_fields_frame = ttk.Frame(self.geometry_page)
        self.geometry_fields_frame.pack(fill="x")
        preview_box = ttk.LabelFrame(self.geometry_page, text="Preview extent", padding=6)
        preview_box.pack(fill="x", pady=(10, 0))
        self.preview_vars["span"] = self._field(preview_box, 0, "span", 7, float)
        self.preview_vars["span"].trace_add("write", self._visual_setting_changed)

        self.operation_var = tk.StringVar(value="band_structure")
        self.operation_box = ttk.Combobox(self.calculation_page, textvariable=self.operation_var, state="readonly", values=list(_OPERATION_FIELDS))
        self.operation_box.pack(fill="x")
        self.operation_box.bind("<<ComboboxSelected>>", self._operation_changed)
        self.operation_fields_frame = ttk.Frame(self.calculation_page)
        self.operation_fields_frame.pack(fill="x", pady=(8, 0))
        actions = ttk.Frame(self.calculation_page)
        actions.pack(fill="x", pady=(10, 0))
        self.run_button = ttk.Button(actions, text="Run", command=self.run)
        self.run_button.pack(side="left")
        self.plot_button = ttk.Button(actions, text="Plot selected record", command=self.plot_record)
        self.plot_button.pack(side="left", padx=4)
        self.plot_after_run_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text="Plot after Run", variable=self.plot_after_run_var).pack(side="left", padx=(8, 0))
        self.plot_after_run_var.trace_add("write", self._project_setting_changed)

        self.record_box = ttk.LabelFrame(self.calculation_page, text="Band Structure record", padding=6)
        record_box = self.record_box
        record_box.pack(fill="x", pady=(12, 0))
        self.record_var = tk.StringVar()
        ttk.Entry(record_box, textvariable=self.record_var).pack(fill="x")
        record_actions = ttk.Frame(record_box)
        record_actions.pack(fill="x", pady=(4, 0))
        self.recent_button = ttk.Button(record_actions, text="Recent matching record", command=self.select_recent_record)
        self.recent_button.pack(side="left")
        self.browse_button = ttk.Button(record_actions, text="Browse…", command=self.browse_record)
        self.browse_button.pack(side="left", padx=4)
        self.display_band_frame = ttk.Frame(record_box)
        ttk.Label(self.display_band_frame, text="Displayed band").pack(side="left")
        self.display_band_box = ttk.Combobox(
            self.display_band_frame,
            textvariable=self.display_band_var,
            state="readonly",
            width=8,
        )
        self.display_band_box.pack(side="left", padx=6)
        self.display_band_box.bind("<<ComboboxSelected>>", self._display_band_changed)
        self.display_band_frame.pack(fill="x", pady=(5, 0))
        self.result_summary = tk.StringVar(value="No calculation result selected.")
        ttk.Label(record_box, textvariable=self.result_summary, wraplength=320, justify="left").pack(fill="x", pady=(6, 0))

        self.style_tabs = ttk.Notebook(self.style_page)
        self.style_tabs.pack(fill="both", expand=True)
        self.style_frames = {}
        for section, label in (("common", "Common"), ("band", "Band"), ("berry", "Berry"), ("efs", "EFS")):
            frame = ttk.Frame(self.style_tabs, padding=7)
            self.style_frames[section] = frame
            self.style_tabs.add(frame, text=label)
        self._build_style_fields()

        self.display_tabs = ttk.Notebook(display)
        self.display_tabs.pack(fill="both", expand=True)
        self.figure_panes = {}
        for key, label in (("unit", "Unit Cell"), ("motif", "Motif Array"), ("sites", "Lattice Sites")):
            pane = FigurePane(self.display_tabs)
            self.figure_panes[key] = pane
            self.display_tabs.add(pane, text=label)
        result_page = ttk.Frame(self.display_tabs)
        self.display_tabs.add(result_page, text="Result")
        self.result_tabs = ttk.Notebook(result_page)
        self.result_tabs.pack(fill="both", expand=True)
        result_interactive = FigurePane(self.result_tabs)
        self.figure_panes["result"] = result_interactive
        self.export_preview = ExportPreviewPane(self.result_tabs)
        self.result_tabs.add(result_interactive, text="Interactive")
        self.result_tabs.add(self.export_preview, text="Export Preview")
        self.result_tabs.bind("<<NotebookTabChanged>>", self._result_tab_changed)
        self.result_page = result_page

        self.log_frame = ttk.LabelFrame(self, text="Run log", padding=4)
        self.log_frame.pack(fill="x", pady=(6, 0))
        self.log = tk.Text(self.log_frame, height=8, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(self, textvariable=self.status_var, anchor="w")
        self.status_label.pack(fill="x", pady=(4, 0))

    def _field(self, parent, row, name, value, kind, *, choices=None):
        ttk.Label(parent, text=_FIELD_LABELS.get(name, name.replace("_", " "))).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        if kind is bool:
            variable = tk.BooleanVar(value=bool(value))
            widget = ttk.Checkbutton(parent, variable=variable)
            widget.grid(row=row, column=1, sticky="w", pady=2)
        else:
            variable = tk.StringVar(value=str(value))
            widget = ttk.Combobox(parent, textvariable=variable, state="readonly", values=choices, width=17) if choices else ttk.Entry(parent, textvariable=variable, width=19)
            widget.grid(row=row, column=1, sticky="ew", pady=2)
        variable._studio_widget = widget
        parent.columnconfigure(1, weight=1)
        return variable

    def _build_style_fields(self):
        profile_style = self.profile["plot"]
        for section, specs in (("common", _COMMON_STYLE_FIELDS), ("band", _BAND_STYLE_FIELDS), ("berry", _BERRY_STYLE_FIELDS), ("efs", _EFS_STYLE_FIELDS)):
            frame = self.style_frames[section]
            for row, (name, kind) in enumerate(specs):
                choices = ("-", "--", "-.", ":") if name == "linestyle" else (("o", "s", "^", "v", "D", ".", "x", "+") if name == "marker" else None)
                value = profile_style[section][name]
                if section == "berry" and name == "render_mode":
                    choices = tuple(_RENDER_MODE_LABELS.values())
                    value = _RENDER_MODE_LABELS[value]
                self.style_vars[section][name] = self._field(frame, row, name, value, kind, choices=choices)
                self.style_vars[section][name].trace_add("write", self._visual_setting_changed)
        self.style_vars["berry"]["render_mode"].trace_add("write", self._berry_render_mode_changed)
        self._berry_render_mode_changed()
        ttk.Label(
            self.style_frames["berry"],
            text=(
                "Sample-cell tiling assigns one clipped, non-overlapping Voronoi cell to each recorded point. "
                "Interpolation resolution is enabled only for Linear interpolation and never changes MPB or sample count."
            ),
            wraplength=290,
            justify="left",
        ).grid(row=len(_BERRY_STYLE_FIELDS), column=0, columnspan=2, sticky="w", pady=(7, 2))
        ttk.Label(
            self.style_frames["efs"],
            text="Interpolation resolution controls only the display grid used to draw contours.",
            wraplength=290,
            justify="left",
        ).grid(row=len(_EFS_STYLE_FIELDS), column=0, columnspan=2, sticky="w", pady=(7, 2))
        band_frame = self.style_frames["band"]
        start = len(_BAND_STYLE_FIELDS)
        self.color_mode_var = self._field(
            band_frame,
            start,
            "color mode",
            _COLOR_MODE_LABELS["default"],
            str,
            choices=tuple(_COLOR_MODE_LABELS.values()),
        )
        self.color_mode_var.trace_add("write", self._visual_setting_changed)
        color_entry_row = ttk.Frame(band_frame)
        color_entry_row.grid(row=start + 1, column=0, columnspan=2, sticky="ew", pady=(5, 2))
        self.color_entry = tk.StringVar()
        ttk.Entry(color_entry_row, textvariable=self.color_entry).pack(side="left", fill="x", expand=True)
        ttk.Button(color_entry_row, text="Add", command=self.add_color).pack(side="left", padx=2)
        ttk.Button(color_entry_row, text="Choose…", command=self.choose_color).pack(side="left")
        self.color_list = tk.Listbox(band_frame, height=5, exportselection=False)
        self.color_list.grid(row=start + 2, column=0, columnspan=2, sticky="nsew")
        ttk.Button(band_frame, text="Remove selected", command=self.remove_color).grid(row=start + 3, column=0, columnspan=2, sticky="w", pady=3)
        band_frame.rowconfigure(start + 2, weight=1)

    def _rebuild_geometry_fields(self):
        for child in self.geometry_fields_frame.winfo_children():
            child.destroy()
        self.geometry_vars.clear()
        for row, (name, kind, default) in enumerate(CASES[self.case_var.get()].geometry_fields):
            variable = self._field(self.geometry_fields_frame, row, name, self.profile["geometry"].get(name, default), kind)
            variable.trace_add("write", self._geometry_changed)
            self.geometry_vars[name] = variable

    def _berry_render_mode_changed(self, *_args):
        label = self.style_vars["berry"]["render_mode"].get()
        mode = _RENDER_MODE_VALUES.get(label, label)
        widget = self.style_vars["berry"]["interpolation_resolution"]._studio_widget
        widget.configure(state="normal" if mode == "linear" else "disabled")

    def _rebuild_operation_fields(self):
        for child in self.operation_fields_frame.winfo_children():
            child.destroy()
        self.operation_vars.clear()
        operation = self.operation_var.get()
        values = self.profile["operations"].setdefault(operation, {})
        for row, (name, kind) in enumerate(_OPERATION_FIELDS[operation]):
            if name == "shrinking" and self.case_var.get() == "square":
                continue
            choices = ("auto", "compute", "plot_only") if name == "run_mode" else None
            self.operation_vars[name] = self._field(self.operation_fields_frame, row, name, values.get(name, ""), kind, choices=choices)
            self.operation_vars[name].trace_add("write", self._project_setting_changed)
        if operation in {"berry_curvature", "efs"}:
            text = "Target band is 1-based; Studio automatically computes every band through the target."
            if self.case_var.get() == "triangular":
                text += " Boundary inset is optional and defaults to 0; it only avoids sensitive domain-edge points."
            ttk.Label(
                self.operation_fields_frame,
                text=text,
                wraplength=300,
                justify="left",
            ).grid(row=len(_OPERATION_FIELDS[operation]), column=0, columnspan=2, sticky="w", pady=(7, 2))

    def _save_operation_fields(self):
        operation = self.active_operation
        if operation not in _OPERATION_FIELDS or not self.operation_vars:
            return
        values = dict(self.profile["operations"].get(operation, {}))
        for name, kind in _OPERATION_FIELDS[operation]:
            if name in self.operation_vars:
                values[name] = _coerce(self.operation_vars[name].get(), kind)
        self.profile["operations"][operation] = values

    def _operation_changed(self, _event=None):
        try:
            self._save_operation_fields()
        except ValueError as exc:
            messagebox.showerror("Calculation parameter", str(exc))
            self.operation_var.set(self.active_operation)
            return
        self.record_paths[self.active_operation] = self.record_var.get().strip()
        self.active_operation = self.operation_var.get()
        self._rebuild_operation_fields()
        self.record_var.set(self.record_paths.get(self.active_operation, ""))
        labels = {"band_structure": "Band Structure", "berry_curvature": "Berry Curvature", "efs": "EFS", "frequency_at_k": "Frequency at k"}
        self.record_box.configure(text=f"{labels[self.active_operation]} record")
        record_state = "normal" if self.active_operation in {"band_structure", "berry_curvature", "efs"} else "disabled"
        self.plot_button.configure(state=record_state)
        self.recent_button.configure(state=record_state)
        self.browse_button.configure(state=record_state)
        self.result_summary.set("No calculation result selected for this operation.")
        self._clear_display_band()
        self._project_setting_changed()

    def _geometry_changed(self, *_args):
        if self._loading_form:
            return
        self.geometry_dirty = True
        self._mark_project_dirty()
        for operation in self.record_paths:
            self.record_paths[operation] = ""
        self.record_var.set("")
        self.result_summary.set("Geometry changed; old record selection was cleared.")
        self._clear_display_band()
        self.status_var.set("Geometry changed — Pending Refresh or Run")

    def _visual_setting_changed(self, *_args):
        if self._loading_form:
            return
        self._mark_project_dirty()
        self.status_var.set("Pending Refresh")

    def _project_setting_changed(self, *_args):
        if not self._loading_form:
            self._mark_project_dirty()

    def _mark_project_dirty(self):
        if not self.project_dirty:
            self.project_dirty = True
            self._update_title()

    def _load_profile_into_form(self):
        self._loading_form = True
        self.profile = validate_profile(self.profile)
        self.profile.setdefault("project_root", str(CASES[self.profile["case_id"]].default_root))
        self.case_var.set(self.profile["case_id"])
        self.profile_name.set(self.profile["name"])
        self.profile_box["values"] = self.store.list(self.profile["case_id"])
        self._rebuild_geometry_fields()
        self.active_operation = self.operation_var.get()
        self._rebuild_operation_fields()
        for key, variable in self.preview_vars.items():
            variable.set(str(self.profile["preview"][key]))
        for section, variables in self.style_vars.items():
            for name, variable in variables.items():
                value = self.profile["plot"][section][name]
                if section == "berry" and name == "render_mode":
                    value = _RENDER_MODE_LABELS[value]
                variable.set(value)
        self.color_mode_var.set(_COLOR_MODE_LABELS[self.profile["plot"]["band"]["color_mode"]])
        self.color_list.delete(0, "end")
        for color in self.profile["plot"]["band"]["colors"]:
            self.color_list.insert("end", color)
        self.plot_after_run_var.set(self.profile["ui"]["plot_after_run"])
        for operation in self.record_paths:
            self.record_paths[operation] = ""
        self.record_var.set("")
        self.result_summary.set("No calculation result selected.")
        self._clear_display_band()
        record_state = "normal" if self.active_operation in {"band_structure", "berry_curvature", "efs"} else "disabled"
        self.plot_button.configure(state=record_state)
        self.recent_button.configure(state=record_state)
        self.browse_button.configure(state=record_state)
        self.geometry_dirty = False
        self._loading_form = False

    def _collect(self):
        case_id = self.case_var.get()
        geometry = {}
        for name, kind, _default in CASES[case_id].geometry_fields:
            raw = self.geometry_vars[name].get()
            geometry[name] = None if name == "r2" and str(raw).strip().lower() in {"none", "null"} else _coerce(raw, kind)
        operation = self.operation_var.get()
        self._save_operation_fields()
        plot = {}
        for section, specs in (("common", _COMMON_STYLE_FIELDS), ("band", _BAND_STYLE_FIELDS), ("berry", _BERRY_STYLE_FIELDS), ("efs", _EFS_STYLE_FIELDS)):
            plot[section] = {name: _coerce(self.style_vars[section][name].get(), kind) for name, kind in specs}
        plot["berry"]["render_mode"] = _RENDER_MODE_VALUES.get(plot["berry"]["render_mode"], plot["berry"]["render_mode"])
        color_mode = _COLOR_MODE_VALUES.get(self.color_mode_var.get(), self.color_mode_var.get())
        plot["band"].update(color_mode=color_mode, colors=list(self.color_list.get(0, "end")))
        self.profile.update(
            schema="mephc-studio-profile-v3", case_id=case_id, name=self.profile_name.get().strip(), geometry=geometry,
            preview={"span": float(self.preview_vars["span"].get())}, plot=plot,
        )
        self.profile["ui"] = {"plot_after_run": bool(self.plot_after_run_var.get())}
        self.profile = validate_profile(self.profile)
        return self.profile

    def change_case(self):
        case_id = self.case_var.get()
        if self.project_dirty and not self._confirm_discard():
            self.case_var.set(self.project["case_id"])
            return
        self.profile = default_profile(case_id)
        self.profile["project_root"] = str(CASES[case_id].default_root)
        self.project = new_project(self.profile, self.profile["project_root"])
        self.project_path = None
        self.project_dirty = False
        self.selected_result_id = None
        self._load_profile_into_form()
        self._refresh_project_tree()
        self._update_title()

    def add_color(self):
        color = self.color_entry.get().strip()
        if not is_color_like(color):
            messagebox.showerror("Invalid color", f"Matplotlib does not recognize {color!r}.")
            return
        self.color_list.insert("end", color)
        self.color_entry.set("")
        self.color_mode_var.set(_COLOR_MODE_LABELS["custom"])
        self._visual_setting_changed()

    def choose_color(self):
        _rgb, color = colorchooser.askcolor(parent=self.master)
        if color:
            self.color_entry.set(color)
            self.add_color()

    def remove_color(self):
        selected = self.color_list.curselection()
        if selected:
            self.color_list.delete(selected[0])
            self._visual_setting_changed()

    def save_profile(self):
        try:
            path = self.store.save(self._collect())
            self.profile_box["values"] = self.store.list(self.profile["case_id"])
            self._write_log(f"Parameter preset saved: {path}\n")
        except Exception as exc:
            messagebox.showerror("Parameter preset error", str(exc))

    def load_profile(self):
        try:
            self.profile = self.store.load(self.case_var.get(), self.profile_name.get())
            self.profile["project_root"] = self.project["project_root"]
            self._load_profile_into_form()
            self._mark_project_dirty()
        except Exception as exc:
            messagebox.showerror("Parameter preset error", str(exc))

    def import_profile(self):
        source = filedialog.askopenfilename(filetypes=[("JSON parameter preset", "*.json"), ("All files", "*")])
        if source:
            try:
                self.profile = self.store.import_file(source)
                self.profile["project_root"] = self.project["project_root"]
                self._load_profile_into_form()
                self._mark_project_dirty()
            except Exception as exc:
                messagebox.showerror("Parameter preset error", str(exc))

    def export_profile(self):
        destination = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON parameter preset", "*.json")])
        if destination:
            try:
                self.store.export_file(self._collect(), destination)
            except Exception as exc:
                messagebox.showerror("Parameter preset error", str(exc))

    def _update_title(self):
        name = self.project_path.name if self.project_path else "Untitled"
        dirty = " *" if self.project_dirty else ""
        self.master.title(f"MePhC Lattice Studio — {name}{dirty}")

    def _sync_project_current(self):
        profile = deepcopy(self._collect())
        self.project["case_id"] = profile["case_id"]
        self.project["project_root"] = profile["project_root"]
        self.project["current"] = profile

    def _confirm_discard(self):
        if not self.project_dirty:
            return True
        choice = messagebox.askyesnocancel("Unsaved project", "Save changes to the current Studio project?")
        if choice is None:
            return False
        if choice:
            return self.save_project()
        return True

    def new_project(self):
        if not self._confirm_discard():
            return
        case_id = self.case_var.get()
        self.profile = default_profile(case_id)
        self.profile["project_root"] = str(CASES[case_id].default_root)
        self.project = new_project(self.profile, self.profile["project_root"])
        self.project_path = None
        self.project_dirty = False
        self.selected_result_id = None
        self._load_profile_into_form()
        self._refresh_project_tree()
        self._update_title()
        self.status_var.set("New empty project")

    def open_project(self):
        if not self._confirm_discard():
            return
        source = filedialog.askopenfilename(
            filetypes=[("MePhC Studio project", f"*{PROJECT_EXTENSION}"), ("JSON", "*.json")]
        )
        if not source:
            return
        try:
            document = ProjectStore.load(source)
            self.project = document
            self.project_path = Path(source).expanduser().resolve()
            self.project_dirty = False
            self.selected_result_id = document.get("selected_result_id")
            self.profile = deepcopy(document["current"])
            self.operation_var.set("band_structure")
            self._load_profile_into_form()
            self._refresh_project_tree()
            self._update_title()
            self.status_var.set(f"Opened project {self.project_path.name}")
            if self.selected_result_id:
                self._select_project_result(self.selected_result_id, mark_dirty=False)
        except Exception as exc:
            messagebox.showerror("Open project failed", str(exc))

    def save_project(self):
        if self.project_path is None:
            return self.save_project_as()
        try:
            self._sync_project_current()
            ProjectStore.save(self.project, self.project_path)
            self.project_dirty = False
            self._update_title()
            self.status_var.set(f"Saved project {self.project_path.name}")
            return True
        except Exception as exc:
            messagebox.showerror("Save project failed", str(exc))
            return False

    def save_project_as(self):
        destination = filedialog.asksaveasfilename(
            defaultextension=PROJECT_EXTENSION,
            filetypes=[("MePhC Studio project", f"*{PROJECT_EXTENSION}")],
        )
        if not destination:
            return False
        if not destination.endswith(PROJECT_EXTENSION):
            destination += PROJECT_EXTENSION
        self.project_path = Path(destination).expanduser().resolve()
        return self.save_project()

    def _refresh_project_tree(self):
        if not hasattr(self, "project_tree"):
            return
        self.project_tree.delete(*self.project_tree.get_children())
        self.project_tree.insert("", "end", iid="geometry", text="Geometry")
        groups = {
            "band_structure": ("results-band", "Results / Band Structure"),
            "berry_curvature": ("results-berry", "Results / Berry Curvature"),
            "efs": ("results-efs", "Results / EFS"),
        }
        for _operation, (identifier, label) in groups.items():
            self.project_tree.insert("", "end", iid=identifier, text=label, open=True)
        for item in self.project.get("results", []):
            _path, availability = resolve_result(self.project, item)
            suffix = "" if availability == "available" else f" [{availability}]"
            label = f"{item.get('geometry_id') or 'unknown'} — {item.get('created_at', '')[:19]}{suffix}"
            parent = groups[item["operation"]][0]
            self.project_tree.insert(parent, "end", iid=f"result:{item['id']}", text=label)
        selected = self.project.get("selected_result_id")
        if selected and self.project_tree.exists(f"result:{selected}"):
            self.project_tree.selection_set(f"result:{selected}")

    def _project_result_selected(self, _event=None):
        selection = self.project_tree.selection()
        if selection and self.project_tree.focus() == selection[0] and selection[0].startswith("result:"):
            self._select_project_result(selection[0].split(":", 1)[1])

    def _select_project_result(self, result_id, *, mark_dirty=True):
        item = next((value for value in self.project.get("results", []) if value["id"] == result_id), None)
        if item is None:
            return
        path, availability = resolve_result(self.project, item)
        if path is None:
            self.result_summary.set(
                f"Unavailable {item['operation']} result for {item.get('geometry_id')}: {availability}"
            )
            self.status_var.set(f"Project result unavailable: {availability}")
            return
        operation = item["operation"]
        loading_before = self._loading_form
        if not mark_dirty:
            self._loading_form = True
        try:
            self.operation_var.set(operation)
            self._operation_changed()
        finally:
            self._loading_form = loading_before
        self.record_paths[operation] = str(path)
        self.record_var.set(str(path))
        self.selected_result_id = result_id
        self.project["selected_result_id"] = result_id
        if mark_dirty:
            self._mark_project_dirty()
        self.plot_record(
            path=path,
            operation=operation,
            project_result_id=result_id,
            remember_style=mark_dirty,
        )
        parameters = ", ".join(f"{key}={value}" for key, value in item.get("calculation", {}).items())
        displayed = f"\nDisplayed band: {item['displayed_band']}" if item.get("displayed_band") else ""
        self.result_summary.set(
            f"Project result: {operation}\nGeometry: {item.get('geometry_id')}\n"
            f"Parameters: {parameters or 'none'}{displayed}\nRecord: {path}"
        )

    def current_figure_pane(self):
        return list(self.figure_panes.values())[self.display_tabs.index("current")]

    def save_current_figure(self):
        pane = self.current_figure_pane()
        if pane.figure is None:
            messagebox.showinfo("No figure", "The current view has no figure to save.")
            return
        destination = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")])
        if destination:
            try:
                common = self._collect()["plot"]["common"]
                save_figure(
                    pane.figure,
                    destination,
                    width=float(common["figure_width"]),
                    height=float(common["figure_height"]),
                    dpi=int(common["dpi"]),
                )
                self.status_var.set(f"Saved {destination}")
                if pane is self.figure_panes["result"]:
                    self.refresh_export_preview()
            except Exception as exc:
                messagebox.showerror("Save failed", str(exc))

    def _result_tab_changed(self, _event=None):
        if self.result_tabs.index("current") == 1:
            self.refresh_export_preview()

    def refresh_export_preview(self):
        figure = self.figure_panes["result"].figure
        if figure is None:
            return
        try:
            common = self._collect()["plot"]["common"]
            payload = render_png(
                figure,
                width=float(common["figure_width"]),
                height=float(common["figure_height"]),
                dpi=int(common["dpi"]),
            )
            self.export_preview.show_png(
                payload,
                width=float(common["figure_width"]),
                height=float(common["figure_height"]),
                dpi=int(common["dpi"]),
            )
        except Exception as exc:
            messagebox.showerror("Export preview failed", str(exc))

    def reset_current_view(self):
        self.current_figure_pane().reset_view()

    def toggle_log(self):
        if self.log_visible.get():
            self.log_frame.pack(fill="x", pady=(6, 0), before=self.status_label)
        else:
            self.log_frame.pack_forget()

    def show_diagnostics(self):
        report = json.dumps(environment_report(), indent=2, sort_keys=True)
        window = tk.Toplevel(self.master)
        window.title("MePhC environment diagnostics")
        text = tk.Text(window, width=90, height=28, wrap="none")
        text.insert("1.0", report)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

    def show_project_preset_help(self):
        messagebox.showinfo(
            "Projects and parameter presets",
            "A Project is the complete working file: it keeps the case, geometry, calculation settings, "
            "plot state, and immutable references to calculation results.\n\n"
            "A Parameter preset is only a reusable parameter template. It contains no calculation results. "
            "The name 'default' means the built-in defaults; other names appear after you save a preset.\n\n"
            "Apply preset copies those parameters into the current project. Import/Export exchanges a preset "
            "JSON file with another machine or project.",
            parent=self.master,
        )

    def _clear_display_band(self):
        if not hasattr(self, "display_band_frame"):
            return
        self.display_band_var.set("")
        self.display_band_box.configure(values=(), state="disabled")
        self.display_band_frame.pack_forget()
        self._display_band_record_path = None

    def _configure_display_band(self, record, operation, *, path=None, project_result_id=None):
        if operation not in {"berry_curvature", "efs"}:
            self._clear_display_band()
            return None
        choices, default, single = record_band_choices(record, operation)
        item = next(
            (value for value in self.project.get("results", []) if value["id"] == project_result_id),
            None,
        ) if project_result_id else None
        remembered = item.get("displayed_band") if item else None
        current = None
        if path is not None and self._display_band_record_path == str(Path(path)):
            try:
                current = int(self.display_band_var.get())
            except ValueError:
                pass
        selected = int(remembered) if remembered in choices else (current if current in choices else default)
        self.display_band_box.configure(values=[str(value) for value in choices])
        self.display_band_var.set(str(selected))
        self.display_band_box.configure(state="disabled" if single else "readonly")
        if not self.display_band_frame.winfo_manager():
            self.display_band_frame.pack(fill="x", pady=(5, 0))
        self._display_band_record_path = str(Path(path)) if path is not None else None
        return selected

    def _display_band_changed(self, _event=None):
        if self._loading_form:
            return
        if self.selected_result_id:
            item = next(
                (value for value in self.project.get("results", []) if value["id"] == self.selected_result_id),
                None,
            )
            if item is not None and self.display_band_var.get():
                item["displayed_band"] = int(self.display_band_var.get())
                self._mark_project_dirty()
        self.status_var.set("Displayed band changed — Pending Refresh")

    def refresh_views(self):
        """Refresh geometry and the selected result without running science."""
        try:
            profile = self._collect()
            figures = build_preview_figures(
                profile["case_id"], profile["geometry"], span=profile["preview"]["span"],
                root=profile.get("project_root"),
            )
            for key, figure in figures.items():
                self.figure_panes[key].show(figure, equal_data_aspect=True)
            config = load_config(profile["case_id"], profile["geometry"], profile.get("project_root"))
            geometry_id = get_geometry_id(profile["case_id"], config)
            self.geometry_dirty = False
            selected = next(
                (item for item in self.project.get("results", []) if item["id"] == self.selected_result_id),
                None,
            )
            if selected is not None:
                path, availability = resolve_result(self.project, selected)
                if path is not None:
                    self.plot_record(
                        path=path,
                        operation=selected["operation"],
                        project_result_id=selected["id"],
                    )
                else:
                    self.status_var.set(f"Geometry refreshed; selected result unavailable: {availability}")
                    return
            else:
                operation = self.operation_var.get()
                path = self.record_paths.get(operation) or self.record_var.get().strip()
                if path and Path(path).is_file() and operation in {"band_structure", "berry_curvature", "efs"}:
                    self.plot_record(path=path, operation=operation)
            self.status_var.set(f"Refreshed geometry and result — {geometry_id}")
        except Exception as exc:
            messagebox.showerror("Refresh failed", str(exc))

    def preview(self):
        """Backward-compatible name for callers; the UI uses unified refresh."""
        self.refresh_views()

    def _current_geometry_id(self, profile=None):
        profile = profile or self._collect()
        config = load_config(profile["case_id"], profile["geometry"], profile.get("project_root"))
        return get_geometry_id(profile["case_id"], config)

    def select_recent_record(self):
        operation = self.operation_var.get()
        if operation not in {"band_structure", "berry_curvature", "efs"}:
            messagebox.showinfo("No record", "Frequency-at-k does not create a plottable record.")
            return
        try:
            profile = self._collect()
            paths = discover_records(profile.get("project_root") or CASES[profile["case_id"]].default_root, self._current_geometry_id(profile), operation)
            if not paths:
                raise FileNotFoundError("No matching record exists for the current geometry and operation.")
            self.record_paths[operation] = str(paths[0])
            self.record_var.set(str(paths[0]))
            self.result_summary.set(f"Recent {operation} record: {paths[0]}")
        except Exception as exc:
            messagebox.showerror("Record lookup failed", str(exc))

    def browse_record(self):
        operation = self.operation_var.get()
        if operation not in {"band_structure", "berry_curvature", "efs"}:
            messagebox.showinfo("No record", "Frequency-at-k does not create a plottable record.")
            return
        try:
            profile = self._collect()
            geometry_id = self._current_geometry_id(profile)
            project_root = profile.get("project_root") or CASES[profile["case_id"]].default_root
            initialdir = browse_directory(project_root, geometry_id)
            pattern = browse_pattern(operation)
        except Exception as exc:
            messagebox.showerror("Record lookup failed", str(exc))
            return
        path = filedialog.askopenfilename(initialdir=initialdir, filetypes=[("Matching records", pattern), ("MePhC records", "*.pkl")])
        if path:
            try:
                record, _ = validate_record(path, operation)
                self.record_paths[operation] = path
                self.record_var.set(path)
                self.result_summary.set(f"Selected {record['kind']} record for {record['geometry_id']}: {path}")
            except Exception as exc:
                messagebox.showerror("Wrong record type", str(exc))

    def plot_record(self, *, path=None, operation=None, project_result_id=None, remember_style=True):
        try:
            profile = self._collect()
            operation = operation or self.operation_var.get()
            path = Path(path or self.record_paths.get(operation) or self.record_var.get())
            if not path.is_file():
                raise FileNotFoundError(path)
            if operation not in {"band_structure", "berry_curvature", "efs"}:
                raise ValueError("Select band_structure, berry_curvature, or efs before plotting a record.")
            record, _ = validate_record(path, operation)
            module = load_case_module(profile["case_id"], operation, profile.get("project_root"))
            displayed_band = self._configure_display_band(
                record,
                operation,
                path=path,
                project_result_id=project_result_id,
            )
            if operation == "band_structure":
                use_actual, kwargs = band_kwargs(profile["plot"])
                has_berry = isinstance(record.get("data"), dict) and record["data"].get("bcs") is not None
                kwargs["color_by_berry"] = bool(kwargs["color_by_berry"] and has_berry)
                figure, axes, _image = module.plot_band_record(path, show=False, save=False, use_actual=use_actual, plot_params=kwargs)
            elif operation == "berry_curvature":
                kwargs = berry_kwargs(profile["plot"])
                outline = _record_domain_outline(record)
                if outline is not None:
                    kwargs["domain_outline"] = outline
                band_index = record_plot_band_index(record, operation, int(displayed_band))
                figure, axes, _image = module.plot_berry_record(path, band_index=band_index, show=False, save=False, plot_params=kwargs)
            else:
                use_actual, kwargs = efs_kwargs(profile["plot"])
                band_index = record_plot_band_index(record, operation, int(displayed_band))
                figure, axes, _image = module.plot_efs_record(path, band_index=band_index, use_actual=use_actual, show=False, save=False, plot_params=kwargs)
            finish_figure(figure, axes, profile["plot"])
            self.figure_panes["result"].show(figure)
            self.display_tabs.select(self.result_page)
            self.result_tabs.select(self.figure_panes["result"])
            self.record_paths[operation] = str(path)
            if operation == self.operation_var.get():
                self.record_var.set(str(path))
            if project_result_id:
                item = next(
                    (value for value in self.project.get("results", []) if value["id"] == project_result_id),
                    None,
                )
                if item is not None and remember_style:
                    item["last_plot_style"] = deepcopy(profile["plot"])
                    if displayed_band is not None:
                        item["displayed_band"] = int(displayed_band)
                    self._mark_project_dirty()
            berry_note = " with Berry coloring" if operation == "band_structure" and kwargs.get("color_by_berry") else ""
            task = record.get("task_params") or {}
            domain = task.get("domain", _record_data_value(record, "domain", "unspecified"))
            symmetry = task.get("symmetry", _record_data_value(record, "symmetry", "unspecified"))
            points = _record_data_value(record, "k_points")
            detail = ""
            if operation in {"berry_curvature", "efs"}:
                detail = (
                    f"\nDisplayed band: {displayed_band}; sampling domain: {domain}; "
                    f"symmetry: {symmetry}; samples: {len(points) if points is not None else 'unspecified'}"
                )
            self.result_summary.set(f"Plotted {record['kind']} record{berry_note} for {record['geometry_id']}: {path}{detail}")
            self.status_var.set(f"Plotted {path.name}")
            if self.result_tabs.index("current") == 1:
                self.refresh_export_preview()
        except Exception as exc:
            messagebox.showerror("Plot failed", str(exc))

    def run(self, operation=None):
        if self.process is not None:
            messagebox.showinfo("Calculation active", "Only one Studio calculation can run at a time.")
            return
        try:
            profile = self._collect()
            operation = operation or self.operation_var.get()
            requested_geometry_id = self._current_geometry_id(profile)
            self.work_dir = tempfile.TemporaryDirectory(prefix="mephc-studio-")
            work = Path(self.work_dir.name)
            request_path, result_path = work / "request.json", work / "result.json"
            request = {"profile": profile, "operation": operation}
            request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            command = [sys.executable, "-m", "mephc.studio.worker", "--request", str(request_path), "--result", str(result_path)]
            self._write_log(f"$ {' '.join(command)}\n")
            self.process = subprocess.Popen(
                command, cwd=profile.get("project_root") or str(CASES[profile["case_id"]].default_root), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
            )
            self.process_group = self.process.pid
            self.running_operation = operation
            self.geometry_dirty = False
            self.run_button.configure(state="disabled")
            self.operation_box.configure(state="disabled")
            self.case_box.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self._write_log(f"Requested geometry: {requested_geometry_id}\n")
            self.status_var.set(f"Running {operation} for {requested_geometry_id}…")
            threading.Thread(target=self._read_process, args=(result_path,), daemon=True).start()
            self.after(100, self._poll_output)
        except Exception as exc:
            self._finish_process()
            messagebox.showerror("Run failed", str(exc))

    def _read_process(self, result_path):
        process = self.process
        if process is None:
            return
        for line in process.stdout:
            self.output_queue.put(("log", line))
        return_code = process.wait()
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception as exc:
            result = {"status": "failed", "error": f"result channel: {exc}"}
        self.output_queue.put(("done", return_code, result))

    def _poll_output(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item[0] == "log":
                    self._write_log(item[1])
                else:
                    self._on_done(item[1], item[2])
        except queue.Empty:
            pass
        if self.process is not None:
            self.after(100, self._poll_output)

    def _on_done(self, return_code, result):
        operation = result.get("operation") or self.running_operation
        if return_code == 0 and result.get("record_path") and operation in {"band_structure", "berry_curvature", "efs"}:
            path = Path(result["record_path"])
            project_result_id = None
            try:
                profile = self._collect()
                self.project["current"] = deepcopy(profile)
                self.project, item = snapshot_result(
                    self.project,
                    path,
                    operation=operation,
                    geometry=profile["geometry"],
                    calculation=profile["operations"][operation],
                    plot_style=profile["plot"],
                    execution_disposition=result.get("execution_disposition", "computed"),
                )
                if operation in {"berry_curvature", "efs"} and result.get("target_band") is not None:
                    item["displayed_band"] = int(result["target_band"])
                    existing_index = next(
                        index for index, value in enumerate(self.project["results"]) if value["id"] == item["id"]
                    )
                    self.project["results"][existing_index] = item
                project_result_id = item["id"]
                self.selected_result_id = item["id"]
                snapshot_path, availability = resolve_result(self.project, item)
                if snapshot_path is None:
                    raise OSError(f"new project snapshot is {availability}")
                path = snapshot_path
                self._mark_project_dirty()
                self._refresh_project_tree()
            except Exception as exc:
                self._write_log(f"Project snapshot failed; canonical result remains available: {exc}\n")
            self.record_paths[operation] = str(path)
            if operation == self.operation_var.get():
                self.record_var.set(str(path))
            self.last_record = path
            elapsed = float(result.get("elapsed_seconds", 0.0))
            disposition = result.get("execution_disposition", "completed")
            summary = (
                f"{disposition.capitalize()} {result.get('record_kind')} record in {elapsed:.3f} s\n"
                f"Geometry: {result.get('geometry_id')}\n"
                f"Target band: {result.get('target_band', 'n/a')}; domain: {result.get('sampling_domain', 'unspecified')}; "
                f"symmetry: {result.get('symmetry_used', 'unspecified')}; samples: {result.get('sample_count', 'unspecified')}\n"
                f"{path}"
            )
            self._write_log(
                f"Result: {disposition} {result.get('record_kind')} record; "
                f"geometry={result.get('geometry_id')}; elapsed={elapsed:.3f}s\n"
                f"Record: {path}\n"
            )
            if self.plot_after_run_var.get():
                self.plot_record(path=path, operation=operation, project_result_id=project_result_id)
            self.result_summary.set(summary)
        if result.get("operation") == "frequency_at_k" and result.get("status") == "succeeded":
            self._write_log("normalized frequencies: " + repr(result["freqs"]) + "\n")
            self._write_log("THz frequencies: " + repr(result["actual_freqs"]) + "\n")
        self.status_var.set("Completed" if return_code == 0 else f"Failed: {result.get('error', 'see log')}")
        self._finish_process()

    def _finish_process(self):
        self.process = self.process_group = None
        self.running_operation = None
        if hasattr(self, "run_button"):
            self.run_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.operation_box.configure(state="readonly")
            self.case_box.configure(state="readonly")
        if self.work_dir is not None:
            self.work_dir.cleanup()
            self.work_dir = None

    def cancel(self):
        if self.process is None:
            return
        try:
            if os.name == "posix" and self.process_group is not None:
                os.killpg(self.process_group, signal.SIGTERM)
            else:
                self.process.terminate()
            self.status_var.set("Cancellation requested")
        except ProcessLookupError:
            pass

    def _write_log(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def close(self):
        if self.process is not None:
            if not messagebox.askyesno("Calculation active", "Cancel the current calculation and close Studio?"):
                return
            self.cancel()
        if not self._confirm_discard():
            return
        for pane in self.figure_panes.values():
            pane.clear()
        self.master.destroy()


def launch(*, initial_case=None, project_root=None):
    root = tk.Tk()
    case_id = initial_case or os.environ.get("MEPHC_STUDIO_CASE", "triangular")
    StudioApp(root, initial_case=case_id, project_root=project_root)
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="MePhC local lattice studio")
    parser.add_argument("--case", choices=sorted(CASES), default=os.environ.get("MEPHC_STUDIO_CASE", "triangular"))
    parser.add_argument("--project-root")
    args = parser.parse_args(argv)
    launch(initial_case=args.case, project_root=args.project_root)
    return 0
