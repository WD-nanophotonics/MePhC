"""Value-semantic R6 supercell spectral-response primitives.

This module deliberately contains no downstream imports and no primitive-band
or topological interpretation.  It stores generic supercell q-point and raw
response provenance, plus the sign-reversal algebra and numerical eligibility
guard required by the R6 contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Mapping

import numpy as np
from shapely.geometry import Point, Polygon

from .bravais import BravaisLattice2D
from .bz import first_brillouin_zone
from .deformation import AnalyticDeformationField, PeriodicSupercellField, periodic_supercell_field


R6_AMPLITUDES = (0.0, 0.005, -0.005, 0.0025, -0.0025)
R6_Q_POINTS = {
    "q0": (0.0, 0.0),
    "q1": (0.12, 0.07),
    "q2": (-0.09, 0.14),
}
R6_REPLICATION = (2, 2)
R6_NUM_BANDS = 6
R6_CONVERGENCE_ABSOLUTE = 2e-3
R6_CONVERGENCE_RELATIVE = 0.02
R6_FREQUENCY_FLOOR = 1e-8
R6_GAP_MIN = 5e-3
R6_GAP_MULTIPLIER = 5.0
R6_PERTURBATION_GAP_FRACTION = 0.25


def _finite_array(values, shape_tail: tuple[int, ...] | None = None) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if shape_tail is not None and array.shape[-len(shape_tail):] != shape_tail:
        raise ValueError(f"expected trailing shape {shape_tail}, got {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError("values must be finite")
    return array


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SupercellQPoint:
    """A generic reciprocal-fractional supercell q-point."""

    point_id: str
    fractional: tuple[float, float]

    def __post_init__(self):
        if not self.point_id or self.point_id in {"Gamma", "K", "M", "X"}:
            raise ValueError("R6 q-point IDs must be non-primitive generic IDs")
        values = tuple(float(value) for value in self.fractional)
        if len(values) != 2 or not np.all(np.isfinite(values)):
            raise ValueError("q-point fractional coordinates must be finite 2D values")
        object.__setattr__(self, "fractional", values)

    def metadata(self) -> dict[str, object]:
        return {
            "id": self.point_id,
            "fractional": list(self.fractional),
            "semantic_domain": "supercell_bz",
            "primitive_labels_allowed": False,
        }


@dataclass(frozen=True, slots=True)
class SolverSettings:
    """Scientific solver identity fields; presentation settings are excluded."""

    amplitude: float
    resolution: int
    num_bands: int = R6_NUM_BANDS
    polarization: str = "TE"
    replication: tuple[int, int] = R6_REPLICATION

    def metadata(self) -> dict[str, object]:
        return {
            "amplitude": float(self.amplitude),
            "resolution": int(self.resolution),
            "num_bands": int(self.num_bands),
            "polarization": self.polarization,
            "replication": list(self.replication),
            "semantic_domain": "supercell_bz",
            "primitive_labels_allowed": False,
            "primitive_symmetry_reduction": False,
            "unfolding": False,
            "berry_or_efs_interpretation": False,
        }


@dataclass(frozen=True, slots=True)
class RawSpectrum:
    """One raw ordered MPB spectrum before any eligibility filtering."""

    point: SupercellQPoint
    settings: SolverSettings
    frequencies: tuple[float, ...]
    solver: str = "meep.mpb.ModeSolver"

    def __post_init__(self):
        values = tuple(float(value) for value in self.frequencies)
        if not values or not np.all(np.isfinite(values)):
            raise ValueError("raw spectrum must be non-empty and finite")
        object.__setattr__(self, "frequencies", values)

    def metadata(self) -> dict[str, object]:
        return {
            "point": self.point.metadata(),
            "settings": self.settings.metadata(),
            "frequencies": list(self.frequencies),
            "solver": self.solver,
        }


@dataclass(frozen=True, slots=True)
class ConvergenceEvidence:
    """Fixed-ladder convergence result for one downstream."""

    downstream: str
    comparisons: tuple[dict[str, object], ...]
    accepted_resolution: int | None
    convergence_error_bound: float
    status: str

    def metadata(self) -> dict[str, object]:
        return {
            "downstream": self.downstream,
            "comparisons": [_jsonable(item) for item in self.comparisons],
            "accepted_resolution": self.accepted_resolution,
            "convergence_error_bound": float(self.convergence_error_bound),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reason: str
    baseline_frequency: float
    nearest_neighbor_gap: float
    maximum_perturbation: float
    convergence_error_bound: float

    def metadata(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "baseline_frequency": self.baseline_frequency,
            "nearest_neighbor_gap": self.nearest_neighbor_gap,
            "delta_max": self.maximum_perturbation,
            "maximum_perturbation": self.maximum_perturbation,
            "convergence_error_bound": self.convergence_error_bound,
        }


@dataclass(frozen=True, slots=True)
class SignReversalResponse:
    point_id: str
    band_ordinal: int
    w0: float
    wp: float
    wm: float
    whp: float
    whm: float
    odd_a: float
    even_a: float
    odd_half: float
    even_half: float
    odd_ratio: float | None
    even_ratio: float | None
    eligibility: EligibilityResult

    def metadata(self) -> dict[str, object]:
        return _jsonable({
            "point_id": self.point_id,
            "band_ordinal": self.band_ordinal,
            "raw": {"w0": self.w0, "wp": self.wp, "wm": self.wm, "whp": self.whp, "whm": self.whm},
            "odd_A": self.odd_a,
            "even_A": self.even_a,
            "odd_half": self.odd_half,
            "even_half": self.even_half,
            "odd_ratio": self.odd_ratio,
            "even_ratio": self.even_ratio,
            "eligibility": self.eligibility.metadata(),
        })


def q_points() -> tuple[SupercellQPoint, ...]:
    return tuple(SupercellQPoint(point_id, fractional) for point_id, fractional in R6_Q_POINTS.items())


def benchmark_field(reference_lattice: BravaisLattice2D, amplitude: float, *, stable_id_prefix: str = "r6.1") -> PeriodicSupercellField:
    """Create the canonical R6 field ``A*sin(2πξ1)*sin(πξ2)^2*e_x``."""

    amplitude = float(amplitude)
    if not np.isfinite(amplitude) or amplitude not in R6_AMPLITUDES:
        raise ValueError("R6 amplitude must be one of the fixed contract values")
    super_direct = reference_lattice.direct_basis @ np.diag(R6_REPLICATION)
    inverse = np.linalg.inv(super_direct)

    def displacement(points):
        values = _finite_array(points, (2,))
        xi = values @ inverse.T
        shape = np.cos(2.0 * np.pi * xi[:, 0]) * np.cos(2.0 * np.pi * xi[:, 1])
        return np.column_stack((amplitude * shape, np.zeros(len(values))))

    base = AnalyticDeformationField(
        displacement,
        stable_id=f"{stable_id_prefix}-benchmark-A{amplitude:g}",
        parameters={"amplitude": amplitude, "shape": "cos(2*pi*xi1)*cos(2*pi*xi2)", "replication": list(R6_REPLICATION)},
    )
    return periodic_supercell_field(reference_lattice=reference_lattice, field=base, replication_matrix=R6_REPLICATION, tolerance=1e-9, boundary_samples=9)


def verify_q_points(lattice: BravaisLattice2D, points: Iterable[SupercellQPoint], *, tolerance: float = 1e-9) -> dict[str, object]:
    bz = first_brillouin_zone(lattice, tolerance=1e-10)
    polygon = Polygon(bz.vertices)
    results = {}
    for point in points:
        cartesian = lattice.reciprocal_to_cartesian(point.fractional)
        inside = polygon.buffer(tolerance).covers(Point(float(cartesian[0]), float(cartesian[1])))
        results[point.point_id] = {"fractional": list(point.fractional), "cartesian": cartesian.tolist(), "inside": bool(inside)}
        if not inside:
            raise ValueError(f"R6 q-point {point.point_id} is outside the current supercell BZ")
    return {"semantic_domain": "supercell_bz", "bz": bz.metadata(), "points": results}


def convergence_decision(downstream: str, spectra_by_resolution: Mapping[int, Mapping[str, Iterable[float]]]) -> ConvergenceEvidence:
    comparisons = []
    error_bound = 0.0
    accepted = None
    for low, high in ((8, 12), (12, 16)):
        if low not in spectra_by_resolution or high not in spectra_by_resolution:
            continue
        diffs = []
        passed = True
        for point_id in ("q1", "q2"):
            lower = _finite_array(spectra_by_resolution[low][point_id])
            upper = _finite_array(spectra_by_resolution[high][point_id])
            if lower.shape != upper.shape:
                passed = False
                comparisons.append({"low": low, "high": high, "point_id": point_id, "passed": False, "reason": "shape_mismatch"})
                continue
            active = upper > R6_FREQUENCY_FLOOR
            point_diffs = np.abs(upper[active] - lower[active])
            diffs.extend(point_diffs.tolist())
            local_pass = bool(np.all(point_diffs <= np.maximum(R6_CONVERGENCE_ABSOLUTE, R6_CONVERGENCE_RELATIVE * np.abs(upper[active]))))
            passed = passed and local_pass
            comparisons.append({"low": low, "high": high, "point_id": point_id, "passed": local_pass, "max_abs_difference": float(np.max(point_diffs)) if len(point_diffs) else 0.0})
        error_bound = max(error_bound, max(diffs, default=0.0))
        if passed and accepted is None:
            accepted = high
            break
    return ConvergenceEvidence(downstream, tuple(comparisons), accepted, error_bound, "PASS" if accepted is not None else "BLOCKED_NONCONVERGED")


def band_local_delta_max(baseline: Iterable[float], perturbed_spectra: Iterable[Iterable[float]], band_ordinal: int) -> float:
    """Return max |omega_b(a)-omega_b(0)| for one band only."""
    values = _finite_array(baseline)
    spectra = _finite_array(perturbed_spectra)
    index = int(band_ordinal)
    if index < 0 or index >= len(values):
        raise IndexError("band ordinal outside baseline spectrum")
    if spectra.ndim == 1:
        spectra = spectra.reshape(1, -1)
    if spectra.ndim != 2 or spectra.shape[1] != len(values):
        raise ValueError("perturbed_spectra must have shape (N, number_of_bands)")
    return float(np.max(np.abs(spectra[:, index] - values[index])))


def eligibility(baseline: Iterable[float], perturbed: Iterable[Iterable[float]], *, band_ordinal: int, convergence_error_bound: float) -> EligibilityResult:
    values = _finite_array(baseline)
    perturbed_values = _finite_array(perturbed)
    index = int(band_ordinal)
    if index < 0 or index >= len(values):
        raise IndexError("band ordinal outside baseline spectrum")
    neighbors = []
    if index > 0:
        neighbors.append(abs(values[index] - values[index - 1]))
    if index + 1 < len(values):
        neighbors.append(abs(values[index + 1] - values[index]))
    gap = float(min(neighbors)) if neighbors else 0.0
    maximum = band_local_delta_max(values, perturbed_values, index)
    reasons = []
    if values[index] <= R6_FREQUENCY_FLOOR:
        reasons.append("baseline_frequency_floor")
    required_gap = max(R6_GAP_MIN, R6_GAP_MULTIPLIER * float(convergence_error_bound))
    if gap <= required_gap:
        reasons.append("nearest_neighbor_gap")
    if maximum >= R6_PERTURBATION_GAP_FRACTION * gap:
        reasons.append("perturbation_fraction_of_gap")
    if not np.all(np.isfinite(perturbed_values)):
        reasons.append("nonfinite_frequency")
    return EligibilityResult(not reasons, "PASS" if not reasons else ";".join(reasons), float(values[index]), gap, maximum, float(convergence_error_bound))


def sign_reversal(
    point_id: str,
    band_ordinal: int,
    raw: Mapping[float, Iterable[float]],
    convergence_error_bound: float,
    *,
    baseline_spectrum: Iterable[float] | None = None,
    perturbed_spectra: Iterable[Iterable[float]] | None = None,
) -> SignReversalResponse:
    w0 = float(np.asarray(raw[0.0], dtype=float)[band_ordinal])
    wp = float(np.asarray(raw[0.005], dtype=float)[band_ordinal])
    wm = float(np.asarray(raw[-0.005], dtype=float)[band_ordinal])
    whp = float(np.asarray(raw[0.0025], dtype=float)[band_ordinal])
    whm = float(np.asarray(raw[-0.0025], dtype=float)[band_ordinal])
    baseline = [w0] if baseline_spectrum is None else baseline_spectrum
    if perturbed_spectra is None:
        if baseline_spectrum is None:
            perturbed_for_guard = np.asarray([[wp], [wm], [whp], [whm]], dtype=float)
            guard_band = 0
        else:
            perturbed_for_guard = np.vstack([raw[0.005], raw[-0.005], raw[0.0025], raw[-0.0025]])
            guard_band = band_ordinal
    else:
        perturbed_for_guard = perturbed_spectra
        guard_band = band_ordinal
    eligible_result = eligibility(
        baseline,
        perturbed_for_guard,
        band_ordinal=guard_band,
        convergence_error_bound=convergence_error_bound,
    )
    odd_a = (wp - wm) / 2.0
    even_a = (wp + wm) / 2.0 - w0
    odd_half = (whp - whm) / 2.0
    even_half = (whp + whm) / 2.0 - w0
    return SignReversalResponse(point_id, band_ordinal, w0, wp, wm, whp, whm, odd_a, even_a, odd_half, even_half, odd_a / odd_half if abs(odd_half) > 1e-10 else None, even_a / even_half if abs(even_half) > 1e-10 else None, eligible_result)


def fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ConvergenceEvidence", "EligibilityResult", "RawSpectrum", "SignReversalResponse", "SolverSettings",
    "SupercellQPoint", "R6_AMPLITUDES", "R6_CONVERGENCE_ABSOLUTE", "R6_CONVERGENCE_RELATIVE",
    "R6_FREQUENCY_FLOOR", "R6_REPLICATION", "R6_Q_POINTS", "benchmark_field", "convergence_decision",
    "band_local_delta_max", "eligibility", "fingerprint", "q_points", "sign_reversal", "verify_q_points",
]
