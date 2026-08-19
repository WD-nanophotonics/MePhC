"""Eigenmode-qualified, fixed-configuration Berry execution wrapper.

This wrapper gates execution only on eigenmode qualification, exact live
geometry/provenance, and exact certified resolution. It does not certify Berry
observable convergence, topology, or production scientific validity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .berry import BerryCurvatureCalculator, BerryCurvatureResult
from .convergence import EigenmodeConvergenceProvenance
from .convergence_binding import EigenmodeCertificateScopeBinding
from .geometry_identity import SupercellGeometryIdentity


@dataclass(frozen=True)
class EigenmodeQualifiedSupercellBerryCalculator:
    """Fixed-band/fixed-settings Berry executor gated by eigenmode evidence only."""

    target_band: int
    resolution: int
    expected_provenance: EigenmodeConvergenceProvenance
    scope_binding: EigenmodeCertificateScopeBinding
    geometry_identity: SupercellGeometryIdentity
    _calculator: BerryCurvatureCalculator

    def __post_init__(self) -> None:
        if isinstance(self.target_band, bool) or not isinstance(self.target_band, int) or self.target_band < 0:
            raise ValueError("target_band must be a non-negative integer")
        if isinstance(self.resolution, bool) or not isinstance(self.resolution, int) or self.resolution < 1:
            raise ValueError("resolution must be a positive integer")
        if not isinstance(self.expected_provenance, EigenmodeConvergenceProvenance):
            raise TypeError("expected_provenance must be EigenmodeConvergenceProvenance")
        if not isinstance(self.scope_binding, EigenmodeCertificateScopeBinding):
            raise TypeError("scope_binding must be EigenmodeCertificateScopeBinding")
        if self.scope_binding.status != "PASS":
            raise ValueError("scope_binding must be PASS")
        if not isinstance(self.geometry_identity, SupercellGeometryIdentity):
            raise TypeError("geometry_identity must be SupercellGeometryIdentity")
        if not isinstance(self._calculator, BerryCurvatureCalculator):
            raise TypeError("_calculator must be BerryCurvatureCalculator")
        if self._calculator.overlap_formulation != "mpb_h":
            raise ValueError("qualified Berry execution requires overlap_formulation='mpb_h'")
        if self._calculator.resolution != self.resolution or self._calculator.num_bands <= self.target_band:
            raise ValueError("underlying calculator settings do not match the qualified wrapper")

    @property
    def calculator(self) -> BerryCurvatureCalculator:
        """Read-only access to the configured delegate for diagnostics and spies."""
        return self._calculator

    def calculate(self, k_point, step: float):
        """Calculate only the permanently bound target band."""
        return self._calculator.calculate(k_point, step=step, band_index=self.target_band)

    def calculate_grid(self, k_points: Iterable[Any], step: float) -> BerryCurvatureResult:
        """Calculate a grid using the permanently bound target band."""
        return self._calculator.calculate_grid(k_points, step=step, band_index=self.target_band)

    def qualification_dict(self) -> dict[str, Any]:
        """Return metadata describing eigenmode qualification, not Berry validation."""
        return {
            "kind": "eigenmode_qualification_only",
            "scope_status": self.scope_binding.status,
            "certified_resolution": self.scope_binding.certified_resolution,
            "target_band": self.target_band,
            "resolution": self.resolution,
            "geometry_digest": self.geometry_identity.digest,
            "expected_provenance": self.expected_provenance.to_dict(),
            "berry_observable_convergence_certified": False,
        }


__all__ = ["EigenmodeQualifiedSupercellBerryCalculator"]
