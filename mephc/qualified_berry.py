"""Eigenmode-qualified, fixed-configuration Berry execution wrapper.

This wrapper gates execution only on eigenmode qualification, exact live
geometry/provenance, and exact certified resolution. It does not certify Berry
observable convergence, topology, or production scientific validity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .berry import BerryCurvatureCalculator, BerryCurvatureResult
from .convergence import EigenmodeConvergenceProvenance, NumericalConvergenceError
from .convergence_binding import EigenmodeCertificateScopeBinding
from .geometry_identity import (
    GeometryIdentityError,
    SupercellGeometryIdentity,
    build_supercell_geometry_identity,
)


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
        if not isinstance(self.geometry_identity, SupercellGeometryIdentity):
            raise TypeError("geometry_identity must be SupercellGeometryIdentity")
        if not isinstance(self._calculator, BerryCurvatureCalculator):
            raise TypeError("_calculator must be BerryCurvatureCalculator")
        self._require_bound_semantics()

    def _require_bound_semantics(self) -> None:
        """Require the immutable wrapper metadata and delegate to agree."""
        self.scope_binding.require_passed()
        if self.scope_binding.expected_resolution != self.resolution:
            raise NumericalConvergenceError(
                "qualified Berry scope expected_resolution does not match wrapper resolution"
            )
        if self.scope_binding.certified_resolution != self.resolution:
            raise NumericalConvergenceError(
                "qualified Berry scope certified_resolution does not match wrapper resolution"
            )
        binding_provenance = self.scope_binding.provenance_binding.expected_provenance
        if binding_provenance != self.expected_provenance:
            raise NumericalConvergenceError(
                "qualified Berry scope provenance does not match expected provenance"
            )
        if self.expected_provenance.geometry_digest != self.geometry_identity.digest:
            raise NumericalConvergenceError(
                "qualified Berry geometry identity does not match expected provenance"
            )
        if self.expected_provenance.backend != "mpb":
            raise NumericalConvergenceError("qualified Berry execution requires backend='mpb'")
        if self.expected_provenance.field_representation != "periodic_h_bloch_envelope":
            raise NumericalConvergenceError(
                "qualified Berry execution requires periodic_h_bloch_envelope fields"
            )
        if self.expected_provenance.target_band != self.target_band:
            raise NumericalConvergenceError(
                "qualified Berry target band does not match expected provenance"
            )
        if self.expected_provenance.polarization not in {"TE", "TM"}:
            raise NumericalConvergenceError(
                "qualified Berry provenance polarization must be normalized to TE or TM"
            )
        calculator_polarization = self._normalize_mpb_polarization(self._calculator.polarization)
        if calculator_polarization != self.expected_provenance.polarization:
            raise NumericalConvergenceError(
                "qualified Berry calculator polarization does not match expected provenance"
            )
        if self._calculator.resolution != self.resolution:
            raise NumericalConvergenceError(
                "qualified Berry calculator resolution does not match wrapper resolution"
            )
        if self._calculator.num_bands != self.expected_provenance.num_bands:
            raise NumericalConvergenceError(
                "qualified Berry calculator num_bands does not match expected provenance"
            )
        if self._calculator.num_bands <= self.target_band:
            raise NumericalConvergenceError(
                "qualified Berry target band is outside the calculator band range"
            )
        if self._calculator.deterministic != self.expected_provenance.deterministic:
            raise NumericalConvergenceError(
                "qualified Berry calculator deterministic setting does not match expected provenance"
            )
        if self._calculator.eigensolver_tolerance != self.expected_provenance.eigensolver_tolerance:
            raise NumericalConvergenceError(
                "qualified Berry calculator eigensolver tolerance does not match expected provenance"
            )
        if self._calculator.mesh_size != self.expected_provenance.mesh_size:
            raise NumericalConvergenceError(
                "qualified Berry calculator mesh size does not match expected provenance"
            )
        if self._calculator.overlap_formulation != "mpb_h":
            raise NumericalConvergenceError(
                "qualified Berry execution requires overlap_formulation='mpb_h'"
            )

    @staticmethod
    def _normalize_mpb_polarization(value: Any) -> str:
        """Map only the exact supported MPB parity constants to public names."""
        import meep as mp

        if type(value) is type(mp.TE) and value == mp.TE:
            return "TE"
        if type(value) is type(mp.TM) and value == mp.TM:
            return "TM"
        raise NumericalConvergenceError(
            "qualified Berry calculator polarization is not an exact MPB TE/TM parity"
        )

    def _live_geometry_identity(self) -> SupercellGeometryIdentity:
        try:
            payload = self.geometry_identity.payload
            replication = payload["replication"]
            periodicity_semantics = payload["periodicity_semantics"]
            return build_supercell_geometry_identity(
                geometry_lattice=self._calculator.geometry_lattice,
                geometry=self._calculator.geometry,
                replication=replication,
                default_material=self._calculator.default_material,
                periodicity_semantics=periodicity_semantics,
            )
        except (GeometryIdentityError, KeyError, TypeError, ValueError) as exc:
            raise NumericalConvergenceError(
                "qualified Berry live geometry identity could not be recomputed"
            ) from exc

    def _require_live_qualified_state(self) -> None:
        """Fail closed if the live delegate drifted after qualification binding."""
        self._require_bound_semantics()
        live_identity = self._live_geometry_identity()
        if live_identity.digest != self.geometry_identity.digest:
            raise NumericalConvergenceError(
                "qualified Berry live geometry digest differs from bound geometry identity"
            )
        if live_identity.digest != self.expected_provenance.geometry_digest:
            raise NumericalConvergenceError(
                "qualified Berry live geometry digest differs from expected provenance"
            )
        try:
            live_provenance = EigenmodeConvergenceProvenance(
                backend="mpb",
                geometry_digest=live_identity.digest,
                target_band=self.target_band,
                num_bands=self._calculator.num_bands,
                polarization=self._normalize_mpb_polarization(self._calculator.polarization),
                deterministic=self._calculator.deterministic,
                eigensolver_tolerance=self._calculator.eigensolver_tolerance,
                mesh_size=self._calculator.mesh_size,
                field_representation="periodic_h_bloch_envelope",
            )
        except (NumericalConvergenceError, TypeError, ValueError) as exc:
            raise NumericalConvergenceError(
                "qualified Berry live calculator provenance is malformed"
            ) from exc
        if live_provenance != self.expected_provenance:
            raise NumericalConvergenceError(
                "qualified Berry live calculator provenance differs from bound provenance"
            )
        if self._calculator.resolution != self.resolution:
            raise NumericalConvergenceError(
                "qualified Berry live calculator resolution differs from bound resolution"
            )
        if self._calculator.overlap_formulation != "mpb_h":
            raise NumericalConvergenceError(
                "qualified Berry live calculator overlap formulation is not mpb_h"
            )

    def calculate(self, k_point, step: float):
        """Calculate only the permanently bound target band."""
        self._require_live_qualified_state()
        return self._calculator.calculate(k_point, step=step, band_index=self.target_band)

    def calculate_grid(self, k_points: Iterable[Any], step: float) -> BerryCurvatureResult:
        """Calculate a grid using the permanently bound target band."""
        self._require_live_qualified_state()
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
