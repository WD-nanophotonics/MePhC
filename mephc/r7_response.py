"""R7 equivalence-aware differential Maxwell response qualification.

R6.1 compares a band ordinal directly.  R7 first matches each perturbed
Maxwell spectrum to the zero-amplitude spectrum, allowing a permutation of
the returned eigenvalue order while preserving solver semantics.  Differential
quantities are computed only after that matching step.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Mapping

import numpy as np

from .response import (
    RawSpectrum,
    R6_FREQUENCY_FLOOR,
    eligibility,
)


def _values(spectrum) -> np.ndarray:
    values = spectrum.frequencies if isinstance(spectrum, RawSpectrum) else spectrum
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not len(array) or not np.all(np.isfinite(array)):
        raise ValueError("spectrum must be a non-empty finite one-dimensional sequence")
    return array


def _identity(spectrum):
    if not isinstance(spectrum, RawSpectrum):
        return None
    return {
        "point": spectrum.point.metadata(),
        "solver": spectrum.solver,
        "resolution": spectrum.settings.resolution,
        "num_bands": spectrum.settings.num_bands,
        "polarization": spectrum.settings.polarization,
        "replication": list(spectrum.settings.replication),
        "semantic_domain": "supercell_bz",
    }


def _assignment(baseline: np.ndarray, candidate: np.ndarray):
    if baseline.shape != candidate.shape:
        raise ValueError("spectra must contain the same number of bands")
    cost = np.abs(baseline[:, None] - candidate[None, :])
    if len(baseline) <= 8:
        best = min(
            permutations(range(len(baseline))),
            key=lambda permutation: sum(cost[i, permutation[i]] for i in range(len(baseline))),
        )
        result = tuple(int(index) for index in best)
    else:
        # R7's small benchmark uses six bands.  Keep larger spectra usable
        # without adding a new mandatory runtime dependency.
        from scipy.optimize import linear_sum_assignment

        rows, columns = linear_sum_assignment(cost)
        result_array = np.empty(len(baseline), dtype=int)
        result_array[rows] = columns
        result = tuple(int(index) for index in result_array)
    maximum = float(max((cost[i, result[i]] for i in range(len(result))), default=0.0))
    return result, maximum


@dataclass(frozen=True, slots=True)
class SpectralEquivalence:
    """Equivalence result for two spectra, including the band assignment."""

    equivalent: bool
    reason: str
    assignment: tuple[int, ...]
    maximum_difference: float
    tolerance: float
    identity_match: bool

    def metadata(self) -> dict[str, object]:
        return {
            "equivalent": self.equivalent,
            "reason": self.reason,
            "assignment": list(self.assignment),
            "maximum_difference": self.maximum_difference,
            "tolerance": self.tolerance,
            "identity_match": self.identity_match,
        }


def match_equivalent_spectrum(baseline, candidate, *, tolerance: float = 1e-8) -> SpectralEquivalence:
    """Match candidate bands to baseline bands and classify numerical equivalence."""

    tolerance = float(tolerance)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("equivalence tolerance must be finite and non-negative")
    identity_match = _identity(baseline) == _identity(candidate) if isinstance(baseline, RawSpectrum) or isinstance(candidate, RawSpectrum) else True
    if not identity_match:
        return SpectralEquivalence(False, "semantic_identity_mismatch", tuple(), float("inf"), tolerance, False)
    left = _values(baseline)
    right = _values(candidate)
    if left.shape != right.shape:
        return SpectralEquivalence(False, "band_count_mismatch", tuple(), float("inf"), tolerance, True)
    assignment, maximum = _assignment(left, right)
    equivalent = bool(maximum <= tolerance)
    return SpectralEquivalence(equivalent, "EQUIVALENT" if equivalent else "frequency_difference", assignment, maximum, tolerance, True)


@dataclass(frozen=True, slots=True)
class DifferentialMaxwellResponse:
    """Central differential response after equivalence-aware band matching."""

    point_id: str
    band_ordinal: int
    status: str
    qualified: bool
    baseline_frequency: float
    odd_a: float
    even_a: float
    odd_half: float
    even_half: float
    odd_ratio: float | None
    even_ratio: float | None
    mapped_spectra: tuple[tuple[float, ...], ...]
    matches: tuple[SpectralEquivalence, ...]
    eligibility: object | None
    reason: str

    def metadata(self) -> dict[str, object]:
        return {
            "point_id": self.point_id,
            "band_ordinal": self.band_ordinal,
            "status": self.status,
            "qualified": self.qualified,
            "baseline_frequency": self.baseline_frequency,
            "odd_A": self.odd_a,
            "even_A": self.even_a,
            "odd_half": self.odd_half,
            "even_half": self.even_half,
            "odd_ratio": self.odd_ratio,
            "even_ratio": self.even_ratio,
            "mapped_spectra": [list(row) for row in self.mapped_spectra],
            "matches": [match.metadata() for match in self.matches],
            "eligibility": None if self.eligibility is None else self.eligibility.metadata(),
            "reason": self.reason,
        }


def qualify_differential_maxwell_response(
    point_id: str,
    band_ordinal: int,
    raw: Mapping[float, object],
    convergence_error_bound: float,
    *,
    equivalence_tolerance: float = 1e-8,
) -> DifferentialMaxwellResponse:
    """Qualify the fixed five-point Maxwell response ladder.

    A target band that is numerically equivalent to its baseline at every
    amplitude is reported as ``EQUIVALENT_NULL`` and is never qualified as a
    physical differential response.  Semantic identity mismatches are blocked
    before any arithmetic is performed.
    """

    required = (0.0, 0.005, -0.005, 0.0025, -0.0025)
    missing = [amplitude for amplitude in required if amplitude not in raw]
    if missing:
        raise ValueError(f"R7 response ladder is missing amplitudes: {missing}")
    baseline = _values(raw[0.0])
    index = int(band_ordinal)
    if index < 0 or index >= len(baseline):
        raise IndexError("band ordinal outside baseline spectrum")
    matches = []
    mapped = []
    for amplitude in required[1:]:
        match = match_equivalent_spectrum(raw[0.0], raw[amplitude], tolerance=equivalence_tolerance)
        matches.append(match)
        if not match.identity_match or not match.assignment:
            return DifferentialMaxwellResponse(
                point_id, index, "BLOCKED_SEMANTIC_IDENTITY", False, float(baseline[index]),
                0.0, 0.0, 0.0, 0.0, None, None, tuple(), tuple(matches), None, match.reason,
            )
        mapped.append(_values(raw[amplitude])[np.asarray(match.assignment, dtype=int)])
    spectra = np.asarray(mapped, dtype=float)
    result = eligibility(baseline, spectra, band_ordinal=index, convergence_error_bound=convergence_error_bound)
    plus, minus, half_plus, half_minus = spectra
    odd_a = float((plus[index] - minus[index]) / 2.0)
    even_a = float((plus[index] + minus[index]) / 2.0 - baseline[index])
    odd_half = float((half_plus[index] - half_minus[index]) / 2.0)
    even_half = float((half_plus[index] + half_minus[index]) / 2.0 - baseline[index])
    null_response = bool(np.all(np.abs(spectra[:, index] - baseline[index]) <= float(equivalence_tolerance)))
    if null_response:
        status, qualified, reason = "EQUIVALENT_NULL", False, "target_band_equivalent_to_baseline"
    elif result.eligible:
        status, qualified, reason = "PASS_DIFFERENTIAL", True, "PASS"
    else:
        status, qualified, reason = "BLOCKED_INELIGIBLE", False, result.reason
    return DifferentialMaxwellResponse(
        point_id, index, status, qualified, float(baseline[index]), odd_a, even_a,
        odd_half, even_half,
        odd_a / odd_half if abs(odd_half) > 1e-10 else None,
        even_a / even_half if abs(even_half) > 1e-10 else None,
        tuple(tuple(float(value) for value in row) for row in spectra),
        tuple(matches), result, reason,
    )


__all__ = [
    "DifferentialMaxwellResponse",
    "SpectralEquivalence",
    "match_equivalent_spectrum",
    "qualify_differential_maxwell_response",
]
