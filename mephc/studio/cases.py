from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from mephc.preview import preview_pattern

from .plot_style import default_plot_style


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    label: str
    default_root: Path
    config_path: str
    geometry_fields: tuple[tuple[str, type, Any], ...]


CASES = {
    "triangular": CaseDefinition(
        "triangular", "TriLatt", Path("/home/icy/TriLatt"), "config.py",
        (("a", float, 400), ("r1", float, 75), ("r2", float, 75),
         ("n1", int, 16), ("theta1", float, 0), ("n2", int, 16),
         ("theta2", float, 60), ("n_eff", float, 2.7), ("height", float, 100),
         ("stretch_factor", float, 1.0), ("stretch_angle_degrees", float, 0.0)),
    ),
    "square": CaseDefinition(
        "square", "SqrLatt", Path("/home/icy/SqrLatt"), "square_hole/config.py",
        (("a", float, 400), ("d", float, 200), ("n_eff", float, 2.7),
         ("height", float, 1), ("polygon_sides", int, 4),
         ("polygon_rotation_degrees", float, 45), ("stretch_factor", float, 1.0),
         ("stretch_angle_degrees", float, 0.0)),
    ),
}


def case_root(case_id: str, override: str | Path | None = None) -> Path:
    if case_id not in CASES:
        raise ValueError(f"unknown case: {case_id}")
    return Path(override) if override is not None else CASES[case_id].default_root


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_config(case_id: str, geometry: dict[str, Any], root: str | Path | None = None) -> ModuleType:
    definition = CASES[case_id]
    root_path = case_root(case_id, root).resolve()
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))
    if case_id == "square":
        config = __import__("square_hole.config", fromlist=["config"])
    else:
        config = _load_module(root_path / definition.config_path, f"mephc_studio_tri_config_{id(geometry)}")
    allowed = {name: (kind, default) for name, kind, default in definition.geometry_fields}
    for key, value in geometry.items():
        if key not in allowed:
            raise ValueError(f"unknown geometry field for {case_id}: {key}")
        kind, _ = allowed[key]
        if key == "r2" and value is None:
            setattr(config, key, None)
        else:
            setattr(config, key, kind(value))
    config.validate_geometry()
    return config


def load_case_module(case_id: str, operation: str, root: str | Path | None = None) -> ModuleType:
    root_path = case_root(case_id, root).resolve()
    path = root_path / f"{operation}.py"
    if not path.is_file():
        raise FileNotFoundError(path)
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))
    return _load_module(path, f"mephc_studio_{case_id}_{operation}_{id(path)}")


def preview_geometry(case_id: str, geometry: dict[str, Any], root: str | Path | None = None):
    config = load_config(case_id, geometry, root)
    pattern = config.build_pattern()
    if case_id == "square":
        outline = config.unit_cell_outline()
        preview_data = config.preview_pattern_data()
    else:
        outer = getattr(pattern, "outer_instance", None)
        outline = getattr(outer, "outline", None)
        preview_data = pattern
    figure, axes = preview_pattern(preview_data, outline=outline, show=False)
    axes.set_title(f"{CASES[case_id].label}: {get_geometry_id(case_id, config)}")
    return figure


def get_geometry_id(case_id: str, config: ModuleType) -> str:
    return config.get_geometry_id() if case_id == "square" else config.geometry_id()


def default_profile(case_id: str) -> dict:
    definition = CASES[case_id]
    return {
        "schema": "mephc-studio-profile-v3",
        "case_id": case_id,
        "name": "default",
        "geometry": {name: default for name, _, default in definition.geometry_fields},
        "preview": {"span": 7.0},
        "ui": {"plot_after_run": True},
        "operations": {
            "band_structure": {"resolution": 32, "num_bands": 3, "n_per_segment": 8, "compute_bc": False, "berry_step": 0.0005, "run_mode": "auto"},
            "berry_curvature": {"resolution": 32, "grid_n": 6, "step": 0.0005, "target_band": 1, "shrinking": 0.0, "run_mode": "auto"},
            "efs": {"resolution": 32, "grid_n": 8, "target_band": 1, "shrinking": 0.0, "run_mode": "auto"},
            "frequency_at_k": {"resolution": 32, "num_bands": 3, "kx": 0.0, "ky": 0.0},
        },
        "plot": default_plot_style(),
    }
