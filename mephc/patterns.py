from __future__ import annotations

from typing import Any

import numpy as np


def is_one_layer_pattern_list(data: Any) -> bool:
    """Return True for the canonical one-layer pattern format: list[np.ndarray]."""
    return isinstance(data, list) and all(isinstance(item, np.ndarray) for item in data)


def is_two_layer_pattern_list(data: Any) -> bool:
    """Return True for list[list[np.ndarray]], used for multi-sublattice patterns."""
    return isinstance(data, list) and all(is_one_layer_pattern_list(item) for item in data)


def _as_pattern_array(data: Any) -> np.ndarray:
    array = np.asarray(data, dtype=float)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError("Pattern arrays must have shape (N, 2).")
    return array


def convert_to_two_layer_pattern_list(data: Any) -> list[list[np.ndarray]]:
    """Normalize ndarray/list/nested-list pattern input to list[list[np.ndarray]]."""
    if hasattr(data, "pattern"):
        data = data.pattern

    if isinstance(data, np.ndarray):
        return [[_as_pattern_array(data)]]

    if is_two_layer_pattern_list(data):
        return data

    if is_one_layer_pattern_list(data):
        return [data]

    if isinstance(data, list):
        result: list[list[np.ndarray]] = []
        for item in data:
            result += convert_to_two_layer_pattern_list(item)
        return result

    raise ValueError("Invalid pattern data type.")


def convert_to_one_layer_pattern_list(data: Any) -> list[np.ndarray]:
    """Normalize ndarray/list/nested-list pattern input to list[np.ndarray]."""
    if hasattr(data, "pattern"):
        data = data.pattern

    if isinstance(data, np.ndarray):
        return [_as_pattern_array(data)]

    if is_one_layer_pattern_list(data):
        return data

    if is_two_layer_pattern_list(data):
        return [item for sublist in data for item in sublist]

    if isinstance(data, list):
        result: list[np.ndarray] = []
        for item in data:
            result += convert_to_one_layer_pattern_list(item)
        return result

    raise ValueError("Invalid pattern data type.")


def pattern_summary(data: Any) -> dict[str, int]:
    """Return a small summary useful for click-run examples and smoke tests."""
    layers = convert_to_two_layer_pattern_list(data)
    return {
        "layers": len(layers),
        "polygons": sum(len(layer) for layer in layers),
        "vertices": sum(len(poly) for layer in layers for poly in layer),
    }


def numpy_array_to_tuples(numpy_array: np.ndarray) -> list[tuple[float, float]]:
    array = _as_pattern_array(numpy_array)
    return [tuple(row) for row in array]