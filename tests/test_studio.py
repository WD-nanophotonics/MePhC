from __future__ import annotations

import json
import pickle
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pytest

from mephc.studio.app import (
    _BERRY_STYLE_FIELDS,
    _EFS_STYLE_FIELDS,
    _OPERATION_FIELDS,
    _coerce,
    record_band_choices,
    record_plot_band_index,
)
from mephc.studio.cases import default_profile, load_config
from mephc.studio.plot_style import band_kwargs, berry_kwargs, finish_figure, validate_plot_style
from mephc.studio.previewing import _set_square_limits, _square_translations, _translations
from mephc.studio.profiles import LEGACY_PROFILE_SCHEMA, PREVIOUS_PROFILE_SCHEMA, PROFILE_SCHEMA, ProfileStore, validate_profile
from mephc.studio.projects import PROJECT_SCHEMA, ProjectStore, new_project, resolve_result, snapshot_result
from mephc.studio.recording import browse_directory, discover_records, validate_record
from mephc.studio.rendering import render_png, save_figure
from mephc.studio import worker
from mephc.plotting import plot_band_path, plot_scalar_field, sample_cell_polygons


def test_profile_round_trip_is_atomic_and_case_scoped(tmp_path):
    store = ProfileStore(tmp_path)
    profile = default_profile("triangular")
    profile["name"] = "stretched-demo"
    profile["geometry"]["stretch_factor"] = 1.2
    path = store.save(profile)

    assert path == tmp_path / "triangular" / "stretched-demo.json"
    assert store.list("triangular") == ["stretched-demo"]
    assert store.load("triangular", "stretched-demo") == profile
    assert not list(path.parent.glob(".*.tmp"))


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".hidden"])
def test_profile_name_rejects_path_traversal(tmp_path, name):
    store = ProfileStore(tmp_path)
    profile = default_profile("square")
    profile["name"] = name
    with pytest.raises(ValueError):
        store.save(profile)


def test_profile_import_rejects_wrong_schema(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(ValueError):
        ProfileStore(tmp_path / "profiles").import_file(source)


def test_v1_profile_migrates_once_to_v3(tmp_path):
    profile = default_profile("triangular")
    profile["schema"] = LEGACY_PROFILE_SCHEMA
    profile["plot"] = {
        "band_index": 2,
        "use_actual": False,
        "cmap": "plasma",
        "levels": 5,
        "mesh_size": 80,
    }
    profile["preview"] = {"cells_x": 7, "cells_y": 5}
    profile["operations"]["berry_curvature"].update(num_bands=3, band_index=2, shrinking=0.95)
    profile["operations"]["berry_curvature"].pop("target_band", None)
    profile["operations"]["efs"].update(num_bands=2, band_index=1, shrinking=0.2)
    profile["operations"]["efs"].pop("target_band", None)
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps(profile), encoding="utf-8")

    store = ProfileStore(tmp_path / "profiles")
    migrated = store.import_file(source)

    assert migrated["schema"] == PROFILE_SCHEMA
    assert migrated["preview"] == {"span": 7.0}
    assert migrated["plot"]["common"]["title_enabled"] is False
    assert migrated["plot"]["band"]["use_actual"] is False
    assert "band_index" not in migrated["plot"]["berry"]
    assert migrated["plot"]["berry"]["render_mode"] == "sample_cells"
    assert migrated["plot"]["berry"]["interpolation_resolution"] == 80
    assert migrated["plot"]["efs"]["interpolation_resolution"] == 80
    assert migrated["plot"]["efs"]["levels"] == 5
    assert migrated["operations"]["berry_curvature"]["target_band"] == 3
    assert migrated["operations"]["berry_curvature"]["shrinking"] == 0.0
    assert migrated["operations"]["efs"]["target_band"] == 2
    assert migrated["operations"]["efs"]["shrinking"] == pytest.approx(0.2)
    assert store.load("triangular", "default") == migrated


def test_v2_profile_migrates_native_mode_and_band_parameters_to_v3():
    profile = default_profile("triangular")
    profile["schema"] = PREVIOUS_PROFILE_SCHEMA
    profile["plot"]["berry"]["render_mode"] = "native"
    profile["plot"]["berry"]["band_index"] = 2
    profile["operations"]["berry_curvature"] = {
        "resolution": 32, "num_bands": 3, "grid_n": 6, "step": 0.001,
        "band_index": 2, "shrinking": 0.1, "run_mode": "auto",
    }

    migrated = validate_profile(profile)

    assert migrated["schema"] == PROFILE_SCHEMA
    assert migrated["plot"]["berry"]["render_mode"] == "sample_cells"
    assert "band_index" not in migrated["plot"]["berry"]
    assert migrated["operations"]["berry_curvature"]["target_band"] == 3
    assert "num_bands" not in migrated["operations"]["berry_curvature"]


def test_v2_common_and_operation_specific_styles_remain_isolated():
    profile = default_profile("square")
    profile["plot"]["common"]["tick_font_size"] = 15
    profile["plot"]["band"]["colors"] = ["tab:purple"]
    profile["plot"]["band"]["color_mode"] = "custom"
    profile["plot"]["band"]["bc_cmap"] = "RdBu_r"
    profile["plot"]["berry"]["cmap"] = "coolwarm"
    profile["plot"]["efs"]["cmap"] = "magma"

    checked = validate_profile(profile)

    assert checked["plot"]["common"]["tick_font_size"] == 15
    assert checked["plot"]["band"]["colors"] == ["tab:purple"]
    assert checked["plot"]["band"]["bc_cmap"] == "RdBu_r"
    assert checked["plot"]["berry"]["cmap"] == "coolwarm"
    assert checked["plot"]["efs"]["cmap"] == "magma"


def test_in_memory_config_overlay_does_not_rewrite_source(tmp_path):
    source = tmp_path / "config.py"
    source.write_text(
        "a = 1\n"
        "stretch_factor = 1.0\n"
        "stretch_angle_degrees = 0.0\n"
        "def validate_geometry():\n"
        "    assert a > 0 and stretch_factor > 0\n",
        encoding="utf-8",
    )
    before = source.read_bytes()
    config = load_config("triangular", {"a": 2, "stretch_factor": 1.3, "stretch_angle_degrees": 15}, tmp_path)
    assert config.a == 2
    assert config.stretch_factor == 1.3
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [("12", int, 12), ("1.25", float, 1.25), ("yes", bool, True), ("false", bool, False), (" auto ", str, "auto")],
)
def test_ui_parameter_coercion(text, kind, expected):
    assert _coerce(text, kind) == expected


def test_worker_band_delegates_to_case_function_without_copying_science(monkeypatch, tmp_path):
    profile = default_profile("triangular")
    profile["project_root"] = str(tmp_path)
    fake_config = SimpleNamespace(geometry_id=lambda: "fake-geometry")
    fake_record = {"kind": "band", "geometry_id": "fake-geometry"}
    calls = []

    def compute(config, **kwargs):
        calls.append((config, kwargs))
        path = tmp_path / "record.pkl"
        path.write_bytes(pickle.dumps(fake_record))
        return fake_record, path, None

    fake_module = SimpleNamespace(compute_band_structure=compute)
    monkeypatch.setattr(worker, "load_config", lambda *_args, **_kwargs: fake_config)
    monkeypatch.setattr(worker, "_common", lambda *_args, **_kwargs: (fake_config, fake_module, dict(profile["operations"]["band_structure"]), tmp_path))

    result = worker.run_request({"profile": profile, "operation": "band_structure", "record_path": tmp_path / "wrong.pkl"})

    assert result["status"] == "succeeded"
    assert result["record_path"].endswith("record.pkl")
    assert len(calls) == 1
    assert calls[0][1]["resolution"] == 32
    assert calls[0][1]["source_case"] == str(tmp_path)
    assert calls[0][1]["record_path"] is None
    assert result["record_kind"] == "band"
    assert result["execution_disposition"] == "computed"


def test_worker_rejects_wrong_record_kind_before_success(monkeypatch, tmp_path):
    profile = default_profile("triangular")
    profile["project_root"] = str(tmp_path)
    fake_config = SimpleNamespace(geometry_id=lambda: "fake-geometry")
    wrong = {"kind": "band", "geometry_id": "fake-geometry"}

    def compute(_config, **_kwargs):
        path = tmp_path / "wrong.pkl"
        path.write_bytes(pickle.dumps(wrong))
        return wrong, path, None

    fake_module = SimpleNamespace(compute_berry_curvature=compute)
    parameters = dict(profile["operations"]["berry_curvature"])
    monkeypatch.setattr(worker, "load_config", lambda *_args, **_kwargs: fake_config)
    monkeypatch.setattr(worker, "_common", lambda *_args, **_kwargs: (fake_config, fake_module, parameters, tmp_path))

    with pytest.raises(ValueError, match="requires 'bc'"):
        worker.run_request({"profile": profile, "operation": "berry_curvature"})


@pytest.mark.parametrize("operation,kind,function_name", [
    ("berry_curvature", "bc", "compute_berry_curvature"),
    ("efs", "efs", "compute_efs"),
])
@pytest.mark.parametrize("target_band", [1, 2, 3])
def test_worker_maps_one_based_target_band_to_minimum_internal_band_count(
    monkeypatch, tmp_path, operation, kind, function_name, target_band,
):
    profile = default_profile("triangular")
    profile["project_root"] = str(tmp_path)
    profile["operations"][operation]["target_band"] = target_band
    fake_config = SimpleNamespace(geometry_id=lambda: "fake-geometry")
    calls = []

    def compute(_config, **kwargs):
        calls.append(kwargs)
        data = {"k_points": np.asarray([[0, 0], [1, 0], [0, 1]], dtype=float)}
        if operation == "berry_curvature":
            data["bcs"] = np.asarray([0.0, 1.0, -1.0])
        else:
            data["freqs"] = np.ones((3, target_band))
        record = {
            "kind": kind,
            "geometry_id": "fake-geometry",
            "task_params": {"band_index": target_band - 1, "domain": "test-domain", "symmetry": "none"},
            "data": data,
        }
        path = tmp_path / f"{kind}.pkl"
        path.write_bytes(pickle.dumps(record))
        return record, path, None

    fake_module = SimpleNamespace(**{function_name: compute})
    parameters = dict(profile["operations"][operation])
    monkeypatch.setattr(worker, "load_config", lambda *_args, **_kwargs: fake_config)
    monkeypatch.setattr(worker, "_common", lambda *_args, **_kwargs: (fake_config, fake_module, parameters, tmp_path))

    result = worker.run_request({"profile": profile, "operation": operation})

    assert calls[0]["band_index"] == target_band - 1
    assert calls[0]["num_bands"] == target_band
    assert result["target_band"] == target_band
    assert result["sampling_domain"] == "test-domain"
    assert result["symmetry_used"] == "none"
    assert result["sample_count"] == 3


def test_worker_snapshot_ignores_project_record_archive(tmp_path):
    canonical = tmp_path / "data" / "geometry" / "band.pkl"
    archived = tmp_path / "data" / ".studio" / "records" / "hash.pkl"
    canonical.parent.mkdir(parents=True)
    archived.parent.mkdir(parents=True)
    canonical.write_bytes(b"canonical")
    archived.write_bytes(b"immutable")

    snapshot = worker._record_snapshot(tmp_path)

    assert canonical.resolve() in snapshot
    assert archived.resolve() not in snapshot


def test_validate_profile_requires_operation_and_plot_objects():
    profile = default_profile("square")
    profile["operations"] = []
    with pytest.raises(ValueError, match="operations"):
        validate_profile(profile)


def test_boundary_inset_defaults_to_zero_and_is_validated_before_worker():
    profile = default_profile("triangular")
    assert profile["operations"]["berry_curvature"]["shrinking"] == 0.0
    assert profile["operations"]["efs"]["shrinking"] == 0.0
    profile["operations"]["berry_curvature"]["shrinking"] = 2.0 / 3.0
    with pytest.raises(ValueError, match="boundary inset"):
        validate_profile(profile)


def test_record_display_band_choices_separate_scientific_band_from_array_index():
    single = {"task_params": {"band_index": 2}, "data": {"bcs": np.asarray([1.0, 2.0])}}
    multi = {"task_params": {"band_index": None}, "data": {"bcs": np.ones((4, 3))}}
    efs = {"task_params": {"band_index": 2}, "data": {"freqs": np.ones((4, 4))}}

    assert record_band_choices(single, "berry_curvature") == ([3], 3, True)
    assert record_plot_band_index(single, "berry_curvature", 3) == 0
    assert record_band_choices(multi, "berry_curvature") == ([1, 2, 3], 1, False)
    assert record_plot_band_index(multi, "berry_curvature", 2) == 1
    assert record_band_choices(efs, "efs") == ([1, 2, 3, 4], 3, False)
    assert record_plot_band_index(efs, "efs", 4) == 3


def test_ui_exposes_target_band_only_in_calculation_and_no_band_in_plot_style():
    for operation in ("berry_curvature", "efs"):
        operation_names = [name for name, _kind in _OPERATION_FIELDS[operation]]
        assert "target_band" in operation_names
        assert "band_index" not in operation_names
        assert "num_bands" not in operation_names
    assert "band_index" not in [name for name, _kind in _BERRY_STYLE_FIELDS]
    assert "band_index" not in [name for name, _kind in _EFS_STYLE_FIELDS]


def test_band_plot_style_controls_and_custom_color_cycle(tmp_path):
    style = default_profile("triangular")["plot"]
    style["common"].update(
        figure_width=4.0,
        figure_height=3.0,
        dpi=100,
        title_enabled=False,
        xlabel="wave vector",
        ylabel="frequency",
        label_font_size=13,
        tick_font_size=8,
        legend_font_size=7,
        xmin=0.0,
        xmax=1.0,
        ymin=0.0,
        ymax=5.0,
    )
    style["band"].update(
        line=True,
        scatter=True,
        marker="s",
        markersize=25,
        color_mode="custom",
        colors=["red", "green", "blue"],
    )
    distances = np.linspace(0.0, 1.0, 5)
    result = {"distances": distances, "freqs": np.column_stack([distances + index for index in range(7)])}
    _use_actual, kwargs = band_kwargs(style)
    kwargs.pop("color_by_berry")
    figure, axes = plot_band_path(result, use_actual=False, show=False, **kwargs)
    finish_figure(figure, axes, style)

    assert axes.get_title() == ""
    assert axes.get_xlabel() == "wave vector"
    assert axes.get_ylabel() == "frequency"
    assert axes.xaxis.label.get_fontsize() == 13
    assert axes.get_xticklabels()[0].get_fontsize() == 8
    assert axes.get_legend().get_texts()[0].get_fontsize() == 7
    assert tuple(round(value, 6) for value in figure.get_size_inches()) == (4.0, 3.0)
    assert figure.dpi == 100
    assert len(axes.lines) == 7
    assert len(axes.collections) == 7
    assert [line.get_color() for line in axes.lines[:4]] == ["red", "green", "blue", "red"]
    assert axes.get_xlim() == pytest.approx((0.0, 1.0))
    assert axes.get_ylim() == pytest.approx((0.0, 5.0))
    assert any(line.get_visible() for line in axes.get_xgridlines())

    image_path = tmp_path / "styled.png"
    figure.savefig(image_path, dpi=100)
    pixels = mpimg.imread(image_path)
    assert pixels.shape[:2] == (300, 400)
    plt.close(figure)


def test_plot_style_rejects_no_band_marks_and_invalid_color():
    style = default_profile("square")["plot"]
    style["band"].update(line=False, scatter=False)
    with pytest.raises(ValueError, match="line, scatter"):
        validate_plot_style(style)
    style["band"].update(line=True, color_mode="custom", colors=["not-a-real-color"])
    with pytest.raises(ValueError, match="Invalid Matplotlib color"):
        validate_plot_style(style)


def test_plot_style_rejects_invalid_numeric_range_locally():
    style = default_profile("triangular")["plot"]
    style["common"].update(xmin="2", xmax="1")
    with pytest.raises(ValueError, match="x min"):
        validate_plot_style(style)
    style["common"].update(xmin="", xmax="")
    style["band"]["markersize"] = 0
    with pytest.raises(ValueError, match="marker size"):
        validate_plot_style(style)
    style["band"]["markersize"] = 10
    style["band"].update(bc_vmin="1", bc_vmax="-1")
    with pytest.raises(ValueError, match="Band Berry color minimum"):
        validate_plot_style(style)


def test_berry_style_exposes_sample_cell_rendering_and_color_limits():
    style = default_profile("triangular")["plot"]
    style["berry"].update(vmin="-0.25", vmax="0.75", interpolation_resolution=37)
    kwargs = berry_kwargs(style)

    assert kwargs["render_mode"] == "sample_cells"
    assert kwargs["mesh_size"] == 37
    assert kwargs["vmin"] == pytest.approx(-0.25)
    assert kwargs["vmax"] == pytest.approx(0.75)

    style["berry"].update(vmin="2", vmax="1")
    with pytest.raises(ValueError, match="color minimum"):
        validate_plot_style(style)


def test_native_scalar_field_does_not_interpolate_scattered_samples(monkeypatch):
    points = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.2, 1.0], [0.9, 0.8]])
    values = np.asarray([-1.0, 0.25, 0.75, 1.5])
    monkeypatch.setattr("mephc.plotting.griddata", lambda *_args, **_kwargs: pytest.fail("griddata called"))

    figure, axes = plot_scalar_field(
        points, values, render_mode="native", mesh_size=999,
        vmin=-2.0, vmax=2.0, show=False,
    )

    assert axes.collections[0].get_clim() == pytest.approx((-2.0, 2.0))
    plt.close(figure)


def test_sample_cell_scalar_field_does_not_interpolate_and_has_one_cell_per_sample(monkeypatch):
    points = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.2, 1.0], [0.9, 0.8]])
    values = np.asarray([-1.0, 0.25, 0.75, 1.5])
    monkeypatch.setattr("mephc.plotting.griddata", lambda *_args, **_kwargs: pytest.fail("griddata called"))

    figure, axes = plot_scalar_field(
        points, values, render_mode="sample_cells", mesh_size=999,
        vmin=-2.0, vmax=2.0, show=False,
    )

    assert axes.collections[0].get_clim() == pytest.approx((-2.0, 2.0))
    assert len(axes.collections[0].get_paths()) == len(points)
    plt.close(figure)


@pytest.mark.parametrize(
    "transform",
    [
        np.eye(2),
        np.asarray([[0.0, -1.0], [1.0, 0.0]]),
        np.asarray([[1.3, 0.35], [0.0, 0.75]]),
    ],
)
def test_sample_cell_polygons_tile_clipped_domain_without_overlap(transform):
    base = np.asarray([(x, y) for x in range(-2, 3) for y in range(-2, 3)], dtype=float)
    points = base @ transform.T
    domain_outline = np.asarray([[-1.25, -1.1], [1.25, -1.1], [1.25, 1.1], [-1.25, 1.1]]) @ transform.T
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    domain = Polygon(domain_outline)
    inside = np.asarray([point for point in points if domain.buffer(1e-10).covers(Point(point))])
    polygons, indices, clipped_domain = sample_cell_polygons(inside, domain_outline)
    cells = [Polygon(vertices) for vertices in polygons]

    assert len(set(indices)) == len(inside)
    assert sum(cell.area for cell in cells) == pytest.approx(clipped_domain.area, abs=1e-9)
    assert unary_union(cells).area == pytest.approx(clipped_domain.area, abs=1e-9)
    for index, left in enumerate(cells):
        for right in cells[index + 1:]:
            assert left.intersection(right).area == pytest.approx(0.0, abs=1e-10)


def test_sample_cell_polygons_tile_triangular_sampling_domain():
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    basis = 0.22 * np.asarray([[1.0, 0.5], [0.0, np.sqrt(3) / 2]])
    outline = np.asarray([[-1.0, -0.65], [1.0, -0.65], [0.0, 1.15]])
    domain = Polygon(outline)
    points = np.asarray([
        basis @ np.asarray([i, j], dtype=float)
        for i in range(-10, 11)
        for j in range(-10, 11)
        if domain.buffer(1e-10).covers(Point(basis @ np.asarray([i, j], dtype=float)))
    ])

    polygons, indices, clipped_domain = sample_cell_polygons(points, outline)
    cells = [Polygon(vertices) for vertices in polygons]

    assert len(set(indices)) == len(points)
    assert sum(cell.area for cell in cells) == pytest.approx(clipped_domain.area, abs=1e-9)
    assert unary_union(cells).area == pytest.approx(clipped_domain.area, abs=1e-9)


def test_sample_cell_plot_coalesces_equal_duplicates_and_rejects_conflicts():
    points = np.asarray([[0, 0], [1, 0], [0, 1], [0, 0]], dtype=float)
    same = np.asarray([1.0, 2.0, 3.0, 1.0])
    figure, axes = plot_scalar_field(points, same, render_mode="sample_cells", show=False)
    assert len(axes.collections[0].get_paths()) == 3
    plt.close(figure)

    with pytest.raises(ValueError, match="conflicting"):
        plot_scalar_field(points, np.asarray([1.0, 2.0, 3.0, 9.0]), render_mode="sample_cells", show=False)


def test_linear_scalar_field_uses_requested_interpolation_resolution():
    points = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.2, 1.0], [0.9, 0.8]])
    values = np.asarray([-1.0, 0.25, 0.75, 1.5])

    figure, axes = plot_scalar_field(
        points, values, render_mode="linear", mesh_size=17,
        interpolation="linear", show=False,
    )

    assert np.asarray(axes.collections[0].get_array()).size == 17 * 17
    plt.close(figure)


def test_regular_native_scalar_field_ignores_interpolation_resolution(monkeypatch):
    points = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    values = np.asarray([0.0, 1.0, 2.0, 3.0])
    monkeypatch.setattr("mephc.plotting.griddata", lambda *_args, **_kwargs: pytest.fail("griddata called"))

    first, first_axes = plot_scalar_field(points, values, render_mode="native", mesh_size=2, show=False)
    second, second_axes = plot_scalar_field(points, values, render_mode="native", mesh_size=500, show=False)

    assert np.asarray(first_axes.collections[0].get_array()).shape == np.asarray(second_axes.collections[0].get_array()).shape
    plt.close(first)
    plt.close(second)


def test_preview_site_positions_come_from_affine_direct_basis():
    basis = np.array([[2.0, -0.5], [0.25, 1.5]])
    positions = _translations(basis, 3, 2)
    expected = np.asarray(
        [basis @ np.array([i, j]) for i in (-1.0, 0.0, 1.0) for j in (-0.5, 0.5)]
    )
    assert np.allclose(positions, expected)


def test_square_preview_enumerates_physical_square_not_index_parallelogram():
    basis = np.asarray([[1.0, 0.5], [0.0, np.sqrt(3) / 2]])
    points = _square_translations(basis, 7)
    brute_force = np.asarray(
        [
            basis @ np.asarray([i, j], dtype=float)
            for i in range(-20, 21)
            for j in range(-20, 21)
            if np.max(np.abs(basis @ np.asarray([i, j], dtype=float))) <= 3.5 + 1e-10
        ]
    )

    assert {tuple(np.round(point, 10)) for point in points} == {
        tuple(np.round(point, 10)) for point in brute_force
    }
    assert np.ptp(points[:, 0]) >= 6.0
    assert np.ptp(points[:, 1]) >= 6.0


def test_preview_square_limits_contain_all_points_with_equal_span():
    points = np.asarray([[-3.0, -0.5], [2.0, 0.75], [0.0, 1.0]])
    figure, axes = plt.subplots(figsize=(10, 3))
    _set_square_limits(axes, points)
    xlim, ylim = axes.get_xlim(), axes.get_ylim()

    assert xlim[1] - xlim[0] == pytest.approx(ylim[1] - ylim[0])
    assert points[:, 0].min() >= xlim[0] and points[:, 0].max() <= xlim[1]
    assert points[:, 1].min() >= ylim[0] and points[:, 1].max() <= ylim[1]
    plt.close(figure)


@pytest.mark.parametrize("figsize", [(12, 3), (3, 10)])
def test_equal_aspect_keeps_x_and_y_pixel_scale_under_resize(figsize):
    figure, axes = plt.subplots(figsize=figsize)
    axes.set_xlim(-2, 2)
    axes.set_ylim(-1, 1)
    axes.set_aspect("equal", adjustable="box")
    figure.canvas.draw()
    origin = axes.transData.transform((0, 0))
    x_unit = axes.transData.transform((1, 0))
    y_unit = axes.transData.transform((0, 1))
    assert np.linalg.norm(x_unit - origin) == pytest.approx(np.linalg.norm(y_unit - origin))
    plt.close(figure)


def test_record_selection_is_operation_specific_and_geometry_filtered(tmp_path):
    geometry_id = "geometry-a"
    directory = tmp_path / "data" / geometry_id
    directory.mkdir(parents=True)
    band_path = directory / "band_nb3.pkl"
    bc_path = directory / "bc_nb3.pkl"
    wrong_geometry = directory / "efs_b1.pkl"
    band_path.write_bytes(pickle.dumps({"kind": "band", "geometry_id": geometry_id}))
    bc_path.write_bytes(pickle.dumps({"kind": "bc", "geometry_id": geometry_id}))
    wrong_geometry.write_bytes(pickle.dumps({"kind": "efs", "geometry_id": "geometry-b"}))

    assert browse_directory(tmp_path, geometry_id) == directory
    assert discover_records(tmp_path, geometry_id, "band_structure") == [band_path.resolve()]
    assert discover_records(tmp_path, geometry_id, "berry_curvature") == [bc_path.resolve()]
    assert discover_records(tmp_path, geometry_id, "efs") == []
    with pytest.raises(ValueError, match="requires 'bc'"):
        validate_record(band_path, "berry_curvature")


def test_exact_export_render_preserves_interactive_size_and_zoom(tmp_path):
    figure, axes = plt.subplots(figsize=(9, 4), dpi=80)
    axes.plot([0, 1, 2], [0, 1, 4])
    axes.set_xlim(0.4, 1.6)
    axes.set_ylim(0.2, 3.2)
    before_size = tuple(figure.get_size_inches())
    before_limits = (axes.get_xlim(), axes.get_ylim())

    payload = render_png(figure, width=4, height=3, dpi=100)
    output = tmp_path / "exact.png"
    output.write_bytes(payload)
    pixels = mpimg.imread(output)
    assert pixels.shape[:2] == (300, 400)
    assert tuple(figure.get_size_inches()) == pytest.approx(before_size)
    assert axes.get_xlim() == pytest.approx(before_limits[0])
    assert axes.get_ylim() == pytest.approx(before_limits[1])

    vector = save_figure(figure, tmp_path / "exact.svg", width=5, height=2.5, dpi=120)
    assert vector.is_file()
    assert tuple(figure.get_size_inches()) == pytest.approx(before_size)
    plt.close(figure)


def test_band_berry_style_uses_symmetric_automatic_scale_and_colorbar():
    style = default_profile("triangular")["plot"]
    style["band"].update(line=True, scatter=True, bc_vmin="", bc_vmax="", bc_colorbar=True)
    distances = np.linspace(0.0, 1.0, 5)
    result = {
        "distances": distances,
        "freqs": np.column_stack((distances, distances + 1)),
    }
    bcs = np.column_stack((np.linspace(-2, 1, 5), np.linspace(-0.5, 0.5, 5)))
    _use_actual, kwargs = band_kwargs(style)
    kwargs.pop("color_by_berry")
    figure, axes = plot_band_path(result, use_actual=False, bc_values=bcs, show=False, **kwargs)

    assert len(figure.axes) == 2
    assert axes.collections[-1].norm.vmin == pytest.approx(-2.0)
    assert axes.collections[-1].norm.vmax == pytest.approx(2.0)
    assert figure.axes[1].get_ylabel() == "Berry curvature"
    plt.close(figure)


def test_project_round_trip_and_content_addressed_record_survive_source_overwrite(tmp_path):
    profile = default_profile("triangular")
    profile["project_root"] = str(tmp_path)
    document = new_project(profile, tmp_path)
    source = tmp_path / "data" / "geometry-a" / "band.pkl"
    source.parent.mkdir(parents=True)
    source.write_bytes(pickle.dumps({"kind": "band", "geometry_id": "geometry-a", "data": {"freqs": [[1.0]]}}))

    document, item = snapshot_result(
        document,
        source,
        operation="band_structure",
        geometry=profile["geometry"],
        calculation=profile["operations"]["band_structure"],
        plot_style=profile["plot"],
    )
    project_path = ProjectStore.save(document, tmp_path / "example.mephc-studio.json")
    loaded = ProjectStore.load(project_path)
    immutable_path, state = resolve_result(loaded, loaded["results"][0])

    assert loaded["schema"] == PROJECT_SCHEMA
    assert state == "available"
    assert immutable_path != source
    before = immutable_path.read_bytes()
    source.write_bytes(pickle.dumps({"kind": "band", "geometry_id": "geometry-a", "data": {"freqs": [[9.0]]}}))
    recovered, state = resolve_result(loaded, item)
    assert state == "available"
    assert recovered.read_bytes() == before
    assert not list(project_path.parent.glob(f".{project_path.name}.*"))


def test_existing_project_v1_opens_with_embedded_v2_profile_migrated(tmp_path):
    profile = default_profile("square")
    profile["project_root"] = str(tmp_path)
    profile["schema"] = PREVIOUS_PROFILE_SCHEMA
    profile["plot"]["berry"]["render_mode"] = "native"
    profile["plot"]["berry"]["band_index"] = 1
    profile["operations"]["efs"] = {
        "resolution": 32, "num_bands": 3, "grid_n": 8,
        "band_index": 2, "shrinking": 0.0, "run_mode": "auto",
    }
    document = {
        "schema": PROJECT_SCHEMA,
        "case_id": "square",
        "project_root": str(tmp_path),
        "current": profile,
        "results": [{
            "id": "legacy-result",
            "operation": "berry_curvature",
            "record": {"path": "data/.studio/records/legacy.pkl", "sha256": "0" * 64, "size": 0},
            "last_plot_style": deepcopy(profile["plot"]),
        }],
        "selected_result_id": "legacy-result",
    }
    path = tmp_path / "old.mephc-studio.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    loaded = ProjectStore.load(path)

    assert loaded["schema"] == PROJECT_SCHEMA
    assert loaded["current"]["schema"] == PROFILE_SCHEMA
    assert loaded["current"]["plot"]["berry"]["render_mode"] == "sample_cells"
    assert loaded["current"]["operations"]["efs"]["target_band"] == 3
    assert loaded["results"][0]["displayed_band"] == 2
    assert "band_index" not in loaded["results"][0]["last_plot_style"]["berry"]


def test_project_missing_or_changed_record_is_localized_to_one_result(tmp_path):
    profile = default_profile("square")
    profile["project_root"] = str(tmp_path)
    document = new_project(profile, tmp_path)
    source = tmp_path / "data" / "geometry-a" / "bc.pkl"
    source.parent.mkdir(parents=True)
    source.write_bytes(pickle.dumps({"kind": "bc", "geometry_id": "geometry-a", "data": {}}))
    document, item = snapshot_result(
        document,
        source,
        operation="berry_curvature",
        geometry=profile["geometry"],
        calculation=profile["operations"]["berry_curvature"],
        plot_style=profile["plot"],
    )
    item["displayed_band"] = 2
    document["results"][0]["displayed_band"] = 2
    saved = ProjectStore.save(document, tmp_path / "bands.mephc-studio.json")
    assert ProjectStore.load(saved)["results"][0]["displayed_band"] == 2
    path, state = resolve_result(document, item)
    assert state == "available"
    path.write_bytes(b"changed")
    assert resolve_result(document, item) == (None, "hash_mismatch")
    path.unlink()
    assert resolve_result(document, item) == (None, "missing")


def test_project_rejects_record_path_escape(tmp_path):
    profile = default_profile("triangular")
    profile["project_root"] = str(tmp_path)
    document = new_project(profile, tmp_path)
    document["results"] = [{
        "id": "bad",
        "operation": "band_structure",
        "record": {"path": "../outside.pkl", "sha256": "0" * 64, "size": 1},
    }]
    with pytest.raises(ValueError, match="stay inside"):
        ProjectStore.save(document, tmp_path / "bad.mephc-studio.json")
