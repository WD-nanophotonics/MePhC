"""Additive two-dimensional local Berry convergence data model.

The existing E7F certificate remains authoritative for its historical
resolution/step semantics.  This module records a richer resolution-by-step
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
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'valid'}")
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


def annotate_neighbor_changes(
    observations: Iterable[LocalBerryConvergenceSample],
) -> tuple[LocalBerryConvergenceSample, ...]:
    """Return samples with same-resolution and same-step neighbor deltas.

    Missing neighbors remain ``None``; no sample is promoted based on being
    the finest resolution or smallest step.
    """
    samples = tuple(observations)
    by_key = {(sample.resolution, sample.step): sample for sample in samples}
    result = []
    for sample in samples:
        step_values = [
            other.result for (resolution, step), other in by_key.items()
            if resolution == sample.resolution and step != sample.step
            and other.result is not None
        ]
        resolution_values = [
            other.result for (resolution, step), other in by_key.items()
            if step == sample.step and resolution != sample.resolution
            and other.result is not None
        ]
        step_change = None if sample.result is None or not step_values else min(
            abs(sample.result - value) for value in step_values
        )
        resolution_change = None if sample.result is None or not resolution_values else min(
            abs(sample.result - value) for value in resolution_values
        )
        result.append(LocalBerryConvergenceSample(
            resolution=sample.resolution,
            step=sample.step,
            result=sample.result,
            qualification=sample.qualification,
            neighboring_step_change=step_change,
            neighboring_resolution_change=resolution_change,
            stability_window_membership=sample.stability_window_membership,
            provenance=sample.provenance,
        ))
    return tuple(result)


__all__ = [
    "LocalBerryConvergenceSample",
    "LocalBerryConvergenceGrid",
    "annotate_neighbor_changes",
]
