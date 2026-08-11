from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

import meep as mp
import numpy as np

from .patterns import convert_to_one_layer_pattern_list


GeometryShape = Literal["auto", "prism", "cylinder"]


def regular_polygon_vertices(center: tuple[float, float], radius: float, sides: int, rotation: float = 0.0) -> np.ndarray:
    if sides < 3:
        raise ValueError("A polygon needs at least three sides.")
    cx, cy = center
    angles = rotation + 2 * math.pi * np.arange(sides) / sides
    return np.column_stack((cx + radius * np.cos(angles), cy + radius * np.sin(angles)))


def _vector3(point: Any) -> mp.Vector3:
    return mp.Vector3(float(point[0]), float(point[1]), 0)


def _rectify(vector: mp.Vector3, geometry_lattice=None, rectify: bool = False) -> mp.Vector3:
    if rectify:
        if geometry_lattice is None:
            raise ValueError("geometry_lattice is required when rectify=True.")
        return mp.cartesian_to_lattice(vector, geometry_lattice)
    return vector


def _polygon_radius(poly: np.ndarray) -> tuple[np.ndarray, float]:
    center = np.mean(poly, axis=0)
    distances = np.linalg.norm(poly - center, axis=1)
    return center, float(np.mean(distances))


def pattern_to_meep_geometry(
    pattern,
    material=mp.air,
    height: float = 1000,
    geometry_lattice=None,
    rectify: bool = False,
    shape: GeometryShape = "auto",
    circle_vertex_threshold: int = 10,
):
    """Convert polygon pattern data to Meep geometry objects."""
    result = []
    for poly in convert_to_one_layer_pattern_list(pattern):
        poly = np.asarray(poly, dtype=float)
        use_cylinder = shape == "cylinder" or (shape == "auto" and len(poly) > circle_vertex_threshold)

        if use_cylinder:
            center, radius = _polygon_radius(poly)
            result.append(
                mp.Cylinder(
                    center=_rectify(_vector3(center), geometry_lattice, rectify),
                    radius=radius,
                    material=material,
                    height=height,
                )
            )
            continue

        vertices = [_rectify(_vector3(vertex), geometry_lattice, rectify) for vertex in poly]
        result.append(mp.Prism(vertices, height=height, material=material))
    return result


def radius_dict_to_meep_geometry(
    radius_by_position: Mapping[Any, float],
    material=mp.air,
    height: float = 1000,
    geometry_lattice=None,
    rectify: bool = False,
    shape: Literal["prism", "cylinder"] = "cylinder",
    polygon_sides: int = 3,
    polygon_rotation: float = math.radians(30),
):
    """Convert {(x, y): radius} lattice data to Meep geometry objects."""
    result = []
    for pos, radius in radius_by_position.items():
        center = tuple(pos)
        if shape == "cylinder":
            result.append(
                mp.Cylinder(
                    center=_rectify(_vector3(center), geometry_lattice, rectify),
                    radius=float(radius),
                    material=material,
                    height=height,
                )
            )
            continue

        poly = regular_polygon_vertices(center, float(radius), polygon_sides, polygon_rotation)
        vertices = [_rectify(_vector3(vertex), geometry_lattice, rectify) for vertex in poly]
        result.append(mp.Prism(vertices=vertices, height=height, material=material))
    return result


def to_meep_geometry(
    data,
    material=mp.air,
    height: float = 1000,
    geometry_lattice=None,
    rectify: bool = False,
    shape: GeometryShape = "auto",
    circle_vertex_threshold: int = 10,
    dict_shape: Literal["prism", "cylinder"] = "cylinder",
    polygon_sides: int = 3,
    polygon_rotation: float = math.radians(30),
):
    """Generic converter for pattern lists or {(x, y): radius} dictionaries."""
    if isinstance(data, Mapping):
        if shape in ["prism", "cylinder"]:
            dict_shape = shape
        return radius_dict_to_meep_geometry(
            data,
            material=material,
            height=height,
            geometry_lattice=geometry_lattice,
            rectify=rectify,
            shape=dict_shape,
            polygon_sides=polygon_sides,
            polygon_rotation=polygon_rotation,
        )

    return pattern_to_meep_geometry(
        data,
        material=material,
        height=height,
        geometry_lattice=geometry_lattice,
        rectify=rectify,
        shape=shape,
        circle_vertex_threshold=circle_vertex_threshold,
    )


def convert_ndarray_to_meep_geo(*args, **kwargs):
    """Backward-compatible alias for older scripts."""
    return to_meep_geometry(*args, **kwargs)