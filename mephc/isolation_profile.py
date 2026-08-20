"""Additive scale-aware isolation metrics and candidate policy.

The historical absolute-gap gates remain unchanged and authoritative.  The
profile here is deliberately explicit and opt-in: it reports scale-aware
evidence but never silently changes a production default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Mapping
import math


def _finite(value: Any, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0.0):
        raise ValueError(f"{name} must be finite and non-negative")
    return result


@dataclass(frozen=True)
class ScaleAwareIsolationMetrics:
    absolute_gap: float
    reference_frequency: float
    local_spectral_motion: float
    solver_uncertainty: float
    min_singular_value: float | None = None
    max_principal_angle: float | None = None
    max_projector_distance: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "absolute_gap", "reference_frequency", "local_spectral_motion",
            "solver_uncertainty", "min_singular_value", "max_principal_angle",
            "max_projector_distance",
        ):
            value = getattr(self, name)
            if value is not None:
                _finite(value, name, nonnegative=True)
        if self.reference_frequency == 0.0:
            raise ValueError("reference_frequency must be non-zero")

    @property
    def relative_gap(self) -> float:
        return self.absolute_gap / max(abs(self.reference_frequency), 1e-300)

    @property
    def motion_ratio(self) -> float:
        return self.absolute_gap / max(self.local_spectral_motion, 1e-300)

    @property
    def solver_uncertainty_ratio(self) -> float:
        return self.absolute_gap / max(self.solver_uncertainty, 1e-300)

    def to_dict(self) -> dict[str, float | None]:
        return {
            "absolute_gap": self.absolute_gap,
            "reference_frequency": self.reference_frequency,
            "local_spectral_motion": self.local_spectral_motion,
            "solver_uncertainty": self.solver_uncertainty,
            "relative_gap": self.relative_gap,
            "motion_ratio": self.motion_ratio,
            "solver_uncertainty_ratio": self.solver_uncertainty_ratio,
            "min_singular_value": self.min_singular_value,
            "max_principal_angle": self.max_principal_angle,
            "max_projector_distance": self.max_projector_distance,
        }


@dataclass(frozen=True)
class ScaleAwareIsolationProfile:
    """Versioned candidate thresholds; not the default qualification policy."""

    name: str = "scale_aware_isolation_v1"
    min_relative_gap: float = 0.0
    min_motion_ratio: float = 1.0
    min_solver_uncertainty_ratio: float = 1.0
    min_singular_value: float | None = None
    max_principal_angle: float | None = None
    max_projector_distance: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be non-empty")
        for name in ("min_relative_gap", "min_motion_ratio", "min_solver_uncertainty_ratio"):
            _finite(getattr(self, name), name, nonnegative=True)
        for name in ("min_singular_value", "max_principal_angle", "max_projector_distance"):
            value = getattr(self, name)
            if value is not None:
                _finite(value, name, nonnegative=True)

    def evaluate(self, metrics: ScaleAwareIsolationMetrics) -> "ScaleAwareIsolationEvaluation":
        checks = {
            "relative_gap": metrics.relative_gap >= self.min_relative_gap,
            "motion_ratio": metrics.motion_ratio >= self.min_motion_ratio,
            "solver_uncertainty_ratio": metrics.solver_uncertainty_ratio >= self.min_solver_uncertainty_ratio,
        }
        if self.min_singular_value is not None:
            checks["min_singular_value"] = metrics.min_singular_value is not None and metrics.min_singular_value >= self.min_singular_value
        if self.max_principal_angle is not None:
            checks["max_principal_angle"] = metrics.max_principal_angle is not None and metrics.max_principal_angle <= self.max_principal_angle
        if self.max_projector_distance is not None:
            checks["max_projector_distance"] = metrics.max_projector_distance is not None and metrics.max_projector_distance <= self.max_projector_distance
        return ScaleAwareIsolationEvaluation(
            profile=self.name, passed=all(checks.values()), checks=checks,
            metrics=metrics.to_dict(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "versioned_candidate": True,
            "min_relative_gap": self.min_relative_gap,
            "min_motion_ratio": self.min_motion_ratio,
            "min_solver_uncertainty_ratio": self.min_solver_uncertainty_ratio,
            "min_singular_value": self.min_singular_value,
            "max_principal_angle": self.max_principal_angle,
            "max_projector_distance": self.max_projector_distance,
        }


@dataclass(frozen=True)
class ScaleAwareIsolationEvaluation:
    profile: str
    passed: bool
    checks: Mapping[str, bool]
    metrics: Mapping[str, float | None]

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", dict(self.checks))
        object.__setattr__(self, "metrics", dict(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "passed": self.passed,
            "checks": dict(self.checks),
            "metrics": dict(self.metrics),
        }


__all__ = [
    "ScaleAwareIsolationMetrics",
    "ScaleAwareIsolationProfile",
    "ScaleAwareIsolationEvaluation",
]
