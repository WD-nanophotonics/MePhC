"""R7.2 sign-equivalence and differential-resolution qualification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np

from .geometry_equivalence import GeometryEquivalence, match_geometry
from .r7_response import DifferentialMaxwellResponse, SpectralEquivalence, match_equivalent_spectrum


@dataclass(frozen=True, slots=True)
class SignEquivalence:
    """Verified relation between +A and -A geometry/spectrum realizations."""

    equivalent: bool
    reason: str
    translation: tuple[float, float] | None
    geometry: GeometryEquivalence | None
    spectrum: SpectralEquivalence | None
    tolerance: float

    def metadata(self) -> dict[str, object]:
        return {
            "equivalent": self.equivalent,
            "reason": self.reason,
            "translation": None if self.translation is None else list(self.translation),
            "geometry": None if self.geometry is None else self.geometry.metadata(),
            "spectrum": None if self.spectrum is None else self.spectrum.metadata(),
            "tolerance": self.tolerance,
        }


def _periodic_normalize(pattern, supercell_basis, translation=(0.0, 0.0)):
    basis = np.asarray(supercell_basis, dtype=float)
    if basis.shape != (2, 2) or not np.all(np.isfinite(basis)) or abs(np.linalg.det(basis)) <= 0:
        raise ValueError("supercell_basis must be a nonsingular finite (2, 2) matrix")
    shift = np.asarray(translation, dtype=float)
    if shift.shape != (2,) or not np.all(np.isfinite(shift)):
        raise ValueError("translation must be a finite Cartesian 2-vector")
    inverse = np.linalg.inv(basis)
    normalized = []
    for polygon in pattern:
        values = np.asarray(polygon, dtype=float)
        center = np.mean(values, axis=0)
        shifted = values + shift
        fractional = (center + shift) @ inverse.T
        nearest_integer = np.rint(fractional)
        fractional = np.where(np.abs(fractional - nearest_integer) <= 1e-12, nearest_integer, fractional)
        wrap = np.floor(fractional)
        normalized.append(shifted - wrap @ basis.T)
    return normalized


def verify_periodic_sign_geometry(
    positive,
    negative,
    supercell_basis,
    translations: Iterable[Iterable[float]],
    *,
    tolerance: float = 1e-9,
) -> SignEquivalence:
    """Verify +A/-A geometry equivalence under a declared periodic translation.

    The input translation vectors are Cartesian. Each candidate is applied to
    the positive pattern and wrapped into the same supercell fundamental
    domain before order-invariant polygon matching against the negative
    pattern. Absolute coordinates are therefore not silently treated as equal.
    """

    tolerance = float(tolerance)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("sign-equivalence tolerance must be finite and non-negative")
    negative_normalized = _periodic_normalize(negative, supercell_basis)
    for translation in translations:
        vector = tuple(float(value) for value in translation)
        candidate = _periodic_normalize(positive, supercell_basis, vector)
        geometry = match_geometry(candidate, negative_normalized, tolerance=tolerance)
        if geometry.equivalent:
            return SignEquivalence(True, "EQUIVALENT_PERIODIC_TRANSLATION", vector, geometry, None, tolerance)
    return SignEquivalence(False, "NO_PERIODIC_SIGN_TRANSLATION", None, geometry if 'geometry' in locals() else None, None, tolerance)


def verify_sign_spectrum(positive, negative, *, tolerance: float = 1e-7) -> SignEquivalence:
    """Verify that +A and -A have equivalent Maxwell spectra at one resolution."""

    match = match_equivalent_spectrum(positive, negative, tolerance=tolerance)
    return SignEquivalence(match.equivalent, "EQUIVALENT_SPECTRUM" if match.equivalent else match.reason, None, None, match, float(tolerance))


@dataclass(frozen=True, slots=True)
class DifferentialResolutionComparison:
    low: int
    high: int
    passed: bool
    maximum_difference: float
    tolerance: float
    records: int

    def metadata(self) -> dict[str, object]:
        return {
            "low": self.low,
            "high": self.high,
            "passed": self.passed,
            "maximum_difference": self.maximum_difference,
            "tolerance": self.tolerance,
            "records": self.records,
        }


@dataclass(frozen=True, slots=True)
class DifferentialResolutionLadder:
    comparisons: tuple[DifferentialResolutionComparison, ...]
    accepted_resolution: int | None
    convergence_error_bound: float
    status: str

    def metadata(self) -> dict[str, object]:
        return {
            "comparisons": [item.metadata() for item in self.comparisons],
            "accepted_resolution": self.accepted_resolution,
            "convergence_error_bound": self.convergence_error_bound,
            "status": self.status,
        }


def compare_differential_resolution_ladder(
    responses_by_resolution: Mapping[int, Mapping[tuple[str, int], DifferentialMaxwellResponse]],
    *,
    resolutions: tuple[int, ...] = (8, 12, 16),
    absolute_tolerance: float = 2e-3,
    relative_tolerance: float = 0.02,
) -> DifferentialResolutionLadder:
    """Compare odd/even differential responses across adjacent resolutions."""

    absolute_tolerance = float(absolute_tolerance)
    relative_tolerance = float(relative_tolerance)
    comparisons = []
    accepted = None
    error_bound = 0.0
    fields = ("odd_a", "even_a", "odd_half", "even_half")
    for low, high in zip(resolutions[:-1], resolutions[1:]):
        if low not in responses_by_resolution or high not in responses_by_resolution:
            continue
        left = responses_by_resolution[low]
        right = responses_by_resolution[high]
        keys = sorted(set(left) & set(right))
        differences = []
        passed = bool(keys) and len(keys) == len(left) == len(right)
        for key in keys:
            for field in fields:
                a = float(getattr(left[key], field))
                b = float(getattr(right[key], field))
                difference = abs(a - b)
                differences.append(difference)
                passed = passed and difference <= max(absolute_tolerance, relative_tolerance * abs(b))
        maximum = float(max(differences, default=float("inf")))
        tolerance = max(absolute_tolerance, relative_tolerance * maximum) if differences else float("inf")
        comparison = DifferentialResolutionComparison(low, high, bool(passed), maximum, tolerance, len(keys))
        comparisons.append(comparison)
        error_bound = max(error_bound, maximum if np.isfinite(maximum) else 0.0)
        if passed and accepted is None:
            accepted = high
    return DifferentialResolutionLadder(
        tuple(comparisons), accepted, error_bound,
        "PASS" if accepted is not None else "BLOCKED_DIFFERENTIAL_NONCONVERGED",
    )


__all__ = [
    "DifferentialResolutionComparison",
    "DifferentialResolutionLadder",
    "SignEquivalence",
    "compare_differential_resolution_ladder",
    "verify_periodic_sign_geometry",
    "verify_sign_spectrum",
]
