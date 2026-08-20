"""Additive two-dimensional local Berry convergence data model.

The existing E7F certificate remains authoritative for its historical
resolution/step semantics. This module records a richer resolution-by-step
grid without choosing the smallest step as an automatic winner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Iterable, Mapping
import math


def _real(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise ValueError(f"{name} must be finite and valid")
    return result


def _json_value(value: Any) -> Any:
    if value is None or type(value) in {bool, str, int, float}:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("provenance values must be finite")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise ValueError("provenance must be JSON-safe")


@dataclass(frozen=True)
class LocalBerryNeighborDelta:
    """One coordinate-adjacent comparison, including its direction and key."""

    axis: str
    direction: int
    resolution: int
    step: float
    result: float | None
    absolute_change: float | None

    def __post_init__(self) -> None:
        if self.axis not in {"step", "resolution"}:
            raise ValueError("axis must be step or resolution")
        if self.direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        if isinstance(self.resolution, bool) or not isinstance(self.resolution, int) or self.resolution < 1:
            raise ValueError("resolution must be a positive integer")
        _real(self.step, "step", positive=True)
        if self.result is not None:
            _real(self.result, "result")
        if self.absolute_change is not None:
            _real(self.absolute_change, "absolute_change")
        object.__setattr__(self, "step", float(self.step))
        if self.result is not None:
            object.__setattr__(self, "result", float(self.result))

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "direction": self.direction,
            "resolution": self.resolution,
            "step": self.step,
            "result": self.result,
            "absolute_change": self.absolute_change,
        }


@dataclass(frozen=True)
class LocalBerryConvergenceSample:
    """One observation at a specific resolution and plaquette displacement."""

    resolution: int
    step: float
    result: float | None
    qualification: str
    neighboring_step_change: float | None = None
    neighboring_resolution_change: float | None = None
    stability_window_membership: str = "NOT_ASSESSED"
    provenance: Mapping[str, Any] = field(default_factory=dict)
    neighboring_step_deltas: tuple[LocalBerryNeighborDelta, ...] = ()
    neighboring_resolution_deltas: tuple[LocalBerryNeighborDelta, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.resolution, bool) or not isinstance(self.resolution, int) or self.resolution < 1:
            raise ValueError("resolution must be a positive integer")
        _real(self.step, "step", positive=True)
        if self.result is not None:
            _real(self.result, "result")
        if not isinstance(self.qualification, str) or not self.qualification.strip():
            raise ValueError("qualification must be non-empty")
        for name in ("neighboring_step_change", "neighboring_resolution_change"):
            value = getattr(self, name)
            if value is not None:
                _real(value, name)
        if not isinstance(self.stability_window_membership, str) or not self.stability_window_membership.strip():
            raise ValueError("stability_window_membership must be non-empty")
        for name in ("neighboring_step_deltas", "neighboring_resolution_deltas"):
            values = tuple(getattr(self, name))
            if any(not isinstance(value, LocalBerryNeighborDelta) for value in values):
                raise ValueError(f"{name} must contain LocalBerryNeighborDelta values")
            object.__setattr__(self, name, values)
        object.__setattr__(self, "step", float(self.step))
        if self.result is not None:
            object.__setattr__(self, "result", float(self.result))
        object.__setattr__(self, "provenance", _json_value(dict(self.provenance)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution,
            "step": self.step,
            "result": self.result,
            "qualification": self.qualification,
            "neighboring_step_change": self.neighboring_step_change,
            "neighboring_resolution_change": self.neighboring_resolution_change,
            "neighboring_step_deltas": [item.to_dict() for item in self.neighboring_step_deltas],
            "neighboring_resolution_deltas": [item.to_dict() for item in self.neighboring_resolution_deltas],
            "stability_window_membership": self.stability_window_membership,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class LocalBerryConvergenceGrid:
    """A labeled 2-D resolution x step grid with explicit neighbor deltas."""

    samples: tuple[LocalBerryConvergenceSample, ...]
    convention: str
    field_representation: str
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        samples = tuple(self.samples)
        if not samples or any(not isinstance(x, LocalBerryConvergenceSample) for x in samples):
            raise ValueError("samples must contain LocalBerryConvergenceSample values")
        keys = [(x.resolution, x.step) for x in samples]
        if len(set(keys)) != len(keys):
            raise ValueError("resolution and step pairs must be unique")
        for name in ("convention", "field_representation"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "provenance", _json_value(dict(self.provenance)))

    @property
    def resolutions(self) -> tuple[int, ...]:
        return tuple(sorted({sample.resolution for sample in self.samples}))

    @property
    def steps(self) -> tuple[float, ...]:
        return tuple(sorted({sample.step for sample in self.samples}, reverse=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mephc-local-berry-convergence-grid/v1",
            "resolutions": list(self.resolutions),
            "steps": list(self.steps),
            "convention": self.convention,
            "field_representation": self.field_representation,
            "samples": [sample.to_dict() for sample in self.samples],
            "provenance": dict(self.provenance),
        }


def _neighbor_delta(sample: LocalBerryConvergenceSample, neighbor: LocalBerryConvergenceSample, axis: str, direction: int) -> LocalBerryNeighborDelta:
    change = None if sample.result is None or neighbor.result is None else abs(sample.result - neighbor.result)
    return LocalBerryNeighborDelta(
        axis=axis, direction=direction, resolution=neighbor.resolution,
        step=neighbor.step, result=neighbor.result, absolute_change=change,
    )


def annotate_neighbor_changes(
    observations: Iterable[LocalBerryConvergenceSample],
) -> tuple[LocalBerryConvergenceSample, ...]:
    """Annotate only immediate coordinate neighbors on each grid axis.

    The direction and neighbor coordinate are preserved. No minimum numerical
    difference is used, and no farther point is substituted when an adjacent
    observation is absent from the supplied grid.
    """
    samples = tuple(observations)
    result = []
    for sample in samples:
        same_resolution = sorted(
            (item for item in samples if item.resolution == sample.resolution),
            key=lambda item: item.step,
        )
        same_step = sorted(
            (item for item in samples if item.step == sample.step),
            key=lambda item: item.resolution,
        )
        step_index = next(index for index, item in enumerate(same_resolution) if item is sample)
        resolution_index = next(index for index, item in enumerate(same_step) if item is sample)
        step_neighbors = []
        if step_index > 0:
            step_neighbors.append(_neighbor_delta(sample, same_resolution[step_index - 1], "step", -1))
        if step_index + 1 < len(same_resolution):
            step_neighbors.append(_neighbor_delta(sample, same_resolution[step_index + 1], "step", 1))
        resolution_neighbors = []
        if resolution_index > 0:
            resolution_neighbors.append(_neighbor_delta(sample, same_step[resolution_index - 1], "resolution", -1))
        if resolution_index + 1 < len(same_step):
            resolution_neighbors.append(_neighbor_delta(sample, same_step[resolution_index + 1], "resolution", 1))
        step_changes = [item.absolute_change for item in step_neighbors if item.absolute_change is not None]
        resolution_changes = [item.absolute_change for item in resolution_neighbors if item.absolute_change is not None]
        result.append(LocalBerryConvergenceSample(
            resolution=sample.resolution, step=sample.step, result=sample.result,
            qualification=sample.qualification,
            neighboring_step_change=step_changes[0] if len(step_changes) == 1 else None,
            neighboring_resolution_change=resolution_changes[0] if len(resolution_changes) == 1 else None,
            stability_window_membership=sample.stability_window_membership,
            provenance={**dict(sample.provenance), "neighbor_selection": "coordinate_adjacent_only"},
            neighboring_step_deltas=tuple(step_neighbors),
            neighboring_resolution_deltas=tuple(resolution_neighbors),
        ))
    return tuple(result)


__all__ = [
    "LocalBerryNeighborDelta",
    "LocalBerryNeighborDelta",
    "LocalBerryConvergenceSample",
    "LocalBerryConvergenceGrid",
    "annotate_neighbor_changes",
]
