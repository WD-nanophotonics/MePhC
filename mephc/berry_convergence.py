"""Pure-data qualification of local Berry-observable convergence.

A PASS certificate is local to one plaquette and its exact time-reversal
partner, geometry, band, solver provenance, final resolution, and finest step.
It does not establish a global Berry map, a Brillouin-zone integral, topology,
Chern or valley-Chern numbers, BCD, non-Abelian validity, transport, far-field
consequences, or publication-grade production authorization.

This module never runs MPB and does not change Berry/Wilson mathematics.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, Iterable

from .convergence import (
    ConvergenceCheck,
    EigenmodeConvergenceCertificate,
    EigenmodeConvergenceProvenance,
    NumericalConvergenceError,
)
from .convergence_binding import bind_eigenmode_certificate_for_resolution


_SCHEMA = "mephc-berry-observable-convergence/v1"
_SEMANTIC_VALUES = {
    "backend": "mpb",
    "field_representation": "periodic_h_bloch_envelope",
    "overlap_formulation": "mpb_h",
    "coordinate_system": "cartesian_reciprocal",
    "plaquette_semantics": "counterclockwise_square_lower_left",
    "trs_partner_semantics": "k_tr_lower_left=-k_plus-(step,step)",
    "estimator_schema": "mephc-abelian-square-wilson-mpb-h/v1",
}


def _finite_real(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonnegative_real(value: Any, *, name: str) -> float:
    result = _finite_real(value, name=name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class BerryObservableThresholds:
    """Configured local Berry numerical gates, not universal physical laws."""

    max_resolution_abs_change: float = 1e-5
    max_resolution_relative_change: float = 0.05
    max_step_abs_change: float = 1e-5
    max_step_relative_change: float = 0.05
    max_trs_abs_residual: float = 1e-5
    max_trs_relative_residual: float = 0.05
    required_resolution_tail_pairs: int = 2
    required_step_tail_pairs: int = 2

    def __post_init__(self) -> None:
        for name in (
            "max_resolution_abs_change",
            "max_step_abs_change",
            "max_trs_abs_residual",
        ):
            normalized = _nonnegative_real(getattr(self, name), name=name)
            object.__setattr__(self, name, normalized)
        for name in (
            "max_resolution_relative_change",
            "max_step_relative_change",
            "max_trs_relative_residual",
        ):
            normalized = _nonnegative_real(getattr(self, name), name=name)
            if normalized > 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, normalized)
        _positive_int(self.required_resolution_tail_pairs, name="required_resolution_tail_pairs")
        _positive_int(self.required_step_tail_pairs, name="required_step_tail_pairs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_resolution_abs_change": self.max_resolution_abs_change,
            "max_resolution_relative_change": self.max_resolution_relative_change,
            "max_step_abs_change": self.max_step_abs_change,
            "max_step_relative_change": self.max_step_relative_change,
            "max_trs_abs_residual": self.max_trs_abs_residual,
            "max_trs_relative_residual": self.max_trs_relative_residual,
            "required_resolution_tail_pairs": self.required_resolution_tail_pairs,
            "required_step_tail_pairs": self.required_step_tail_pairs,
        }


@dataclass(frozen=True)
class BerryObservableProvenance:
    """Exact local definition of the Berry observable being certified."""

    backend: str
    geometry_digest: str
    target_band: int
    num_bands: int
    polarization: str
    deterministic: bool
    eigensolver_tolerance: float
    mesh_size: int
    field_representation: str
    overlap_formulation: str
    k_plus: tuple[float, float]
    coordinate_system: str
    plaquette_semantics: str
    trs_partner_semantics: str
    estimator_schema: str

    def __post_init__(self) -> None:
        for name, expected in _SEMANTIC_VALUES.items():
            value = getattr(self, name)
            _string(value, name=name)
            if value != expected:
                raise ValueError(f"{name} must be exactly {expected!r}")
        _string(self.geometry_digest, name="geometry_digest")
        _nonnegative_int(self.target_band, name="target_band")
        _positive_int(self.num_bands, name="num_bands")
        if self.target_band >= self.num_bands:
            raise ValueError("target_band must be a valid zero-based band index")
        if self.polarization not in {"TE", "TM"}:
            raise ValueError("polarization must be exactly 'TE' or 'TM'")
        if type(self.deterministic) is not bool:
            raise ValueError("deterministic must be a bool")
        tolerance = _finite_real(self.eigensolver_tolerance, name="eigensolver_tolerance")
        if tolerance <= 0.0:
            raise ValueError("eigensolver_tolerance must be positive")
        object.__setattr__(self, "eigensolver_tolerance", tolerance)
        _positive_int(self.mesh_size, name="mesh_size")
        try:
            values = tuple(self.k_plus)
        except TypeError as exc:
            raise ValueError("k_plus must be a finite 2-vector") from exc
        if len(values) != 2:
            raise ValueError("k_plus must be a finite 2-vector")
        normalized = tuple(_finite_real(value, name="k_plus") for value in values)
        object.__setattr__(self, "k_plus", normalized)
        EigenmodeConvergenceProvenance(
            backend=self.backend,
            geometry_digest=self.geometry_digest,
            target_band=self.target_band,
            num_bands=self.num_bands,
            polarization=self.polarization,
            deterministic=self.deterministic,
            eigensolver_tolerance=self.eigensolver_tolerance,
            mesh_size=self.mesh_size,
            field_representation=self.field_representation,
        )

    def eigenmode_provenance(self) -> EigenmodeConvergenceProvenance:
        """Return the exact R6.6Q provenance scope for this observable."""
        return EigenmodeConvergenceProvenance(
            backend=self.backend,
            geometry_digest=self.geometry_digest,
            target_band=self.target_band,
            num_bands=self.num_bands,
            polarization=self.polarization,
            deterministic=self.deterministic,
            eigensolver_tolerance=self.eigensolver_tolerance,
            mesh_size=self.mesh_size,
            field_representation=self.field_representation,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "geometry_digest": self.geometry_digest,
            "target_band": self.target_band,
            "num_bands": self.num_bands,
            "polarization": self.polarization,
            "deterministic": self.deterministic,
            "eigensolver_tolerance": self.eigensolver_tolerance,
            "mesh_size": self.mesh_size,
            "field_representation": self.field_representation,
            "overlap_formulation": self.overlap_formulation,
            "k_plus": list(self.k_plus),
            "coordinate_system": self.coordinate_system,
            "plaquette_semantics": self.plaquette_semantics,
            "trs_partner_semantics": self.trs_partner_semantics,
            "estimator_schema": self.estimator_schema,
        }


@dataclass(frozen=True)
class QualifiedBerrySample:
    """One exact local Berry sample and its supplied eigenmode certificate."""

    resolution: int
    step: float
    omega_plus: float
    omega_tr: float
    eigenmode_certificate: EigenmodeConvergenceCertificate

    def __post_init__(self) -> None:
        _positive_int(self.resolution, name="resolution")
        step = _finite_real(self.step, name="step")
        if step <= 0.0:
            raise ValueError("step must be positive")
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "omega_plus", _finite_real(self.omega_plus, name="omega_plus"))
        object.__setattr__(self, "omega_tr", _finite_real(self.omega_tr, name="omega_tr"))
        if not isinstance(self.eigenmode_certificate, EigenmodeConvergenceCertificate):
            raise TypeError("eigenmode_certificate must be EigenmodeConvergenceCertificate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution,
            "step": self.step,
            "omega_plus": self.omega_plus,
            "omega_tr": self.omega_tr,
            "eigenmode_certificate": self.eigenmode_certificate.to_dict(),
        }


@dataclass(frozen=True)
class BerryObservableConvergenceCertificate:
    """Local, pure-data Berry convergence result with explicit audit checks."""

    status: str
    thresholds: BerryObservableThresholds
    provenance: BerryObservableProvenance
    resolution_samples: tuple[QualifiedBerrySample, ...]
    step_samples: tuple[QualifiedBerrySample, ...]
    checks: tuple[ConvergenceCheck, ...]
    qualified_resolution: int | None
    qualified_step: float | None

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "FAIL", "INCOMPLETE"}:
            raise ValueError("status must be PASS, FAIL, or INCOMPLETE")
        if not isinstance(self.thresholds, BerryObservableThresholds):
            raise TypeError("thresholds must be BerryObservableThresholds")
        if not isinstance(self.provenance, BerryObservableProvenance):
            raise TypeError("provenance must be BerryObservableProvenance")
        if not isinstance(self.resolution_samples, tuple) or any(
            not isinstance(sample, QualifiedBerrySample) for sample in self.resolution_samples
        ):
            raise TypeError("resolution_samples must be a tuple of QualifiedBerrySample")
        if not isinstance(self.step_samples, tuple) or any(
            not isinstance(sample, QualifiedBerrySample) for sample in self.step_samples
        ):
            raise TypeError("step_samples must be a tuple of QualifiedBerrySample")
        if not isinstance(self.checks, tuple) or any(
            not isinstance(check, ConvergenceCheck) for check in self.checks
        ):
            raise TypeError("checks must be a tuple of ConvergenceCheck")
        if self.qualified_resolution is not None:
            _positive_int(self.qualified_resolution, name="qualified_resolution")
        if self.qualified_step is not None:
            step = _finite_real(self.qualified_step, name="qualified_step")
            if step <= 0.0:
                raise ValueError("qualified_step must be positive")
            object.__setattr__(self, "qualified_step", step)
        if self.status == "PASS":
            if self.qualified_resolution is None or self.qualified_step is None:
                raise ValueError("PASS requires qualified resolution and step")
        elif self.qualified_resolution is not None or self.qualified_step is not None:
            raise ValueError("FAIL/INCOMPLETE cannot have qualified endpoints")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "status": self.status,
            "thresholds": self.thresholds.to_dict(),
            "provenance": self.provenance.to_dict(),
            "resolution_samples": [sample.to_dict() for sample in self.resolution_samples],
            "step_samples": [sample.to_dict() for sample in self.step_samples],
            "checks": [check.to_dict() for check in self.checks],
            "qualified_resolution": self.qualified_resolution,
            "qualified_step": self.qualified_step,
        }

    def require_passed(self) -> "BerryObservableConvergenceCertificate":
        if self.status == "PASS":
            return self
        blockers = [check.name for check in self.checks if check.status != "PASS"]
        names = ", ".join(blockers) if blockers else "unknown check"
        raise NumericalConvergenceError(
            f"Berry observable convergence certificate is {self.status}: {names}"
        )


def _check(name: str, status: str, observed: Any, criterion: Any, message: str) -> ConvergenceCheck:
    return ConvergenceCheck(
        name=name,
        status=status,
        observed=observed,
        criterion=criterion,
        message=message,
    )


def _tail_pair_indices(length: int, required_pairs: int) -> range:
    return range(max(0, length - required_pairs - 1), max(0, length - 1))


def _within(value_a: float, value_b: float, abs_tol: float, rel_tol: float) -> tuple[bool, float]:
    delta = abs(value_a - value_b)
    limit = max(abs_tol, rel_tol * max(abs(value_a), abs(value_b)))
    return delta <= limit, limit


def _sample_key(sample: QualifiedBerrySample) -> tuple[int, float]:
    return sample.resolution, sample.step


def _validate_ladders(
    resolution_samples: tuple[QualifiedBerrySample, ...],
    step_samples: tuple[QualifiedBerrySample, ...],
) -> None:
    for left, right in zip(resolution_samples, resolution_samples[1:]):
        if right.resolution <= left.resolution:
            raise ValueError("resolution_samples must have strictly increasing resolutions")
        if right.step != left.step:
            raise ValueError("resolution_samples must use exactly one nominal step")
    for left, right in zip(step_samples, step_samples[1:]):
        if right.step >= left.step:
            raise ValueError("step_samples must have strictly decreasing positive steps")
        if right.resolution != left.resolution:
            raise ValueError("step_samples must use exactly one resolution")
    if resolution_samples and step_samples:
        final_resolution = resolution_samples[-1]
        shared_resolution = step_samples[0].resolution
        if shared_resolution != final_resolution.resolution:
            raise ValueError("step_samples resolution must equal final resolution sample")
        nominal_step = final_resolution.step
        overlap = [sample for sample in step_samples if sample.step == nominal_step]
        if len(overlap) != 1:
            raise ValueError("step_samples must contain exactly one nominal-step overlap sample")
        duplicate = overlap[0]
        if duplicate.omega_plus != final_resolution.omega_plus or duplicate.omega_tr != final_resolution.omega_tr:
            raise ValueError("nominal-step overlap sample disagrees with final resolution sample")


def certify_berry_observable_convergence(
    resolution_samples: Iterable[QualifiedBerrySample],
    step_samples: Iterable[QualifiedBerrySample],
    *,
    provenance: BerryObservableProvenance,
    thresholds: BerryObservableThresholds = BerryObservableThresholds(),
) -> BerryObservableConvergenceCertificate:
    """Certify one local Berry plaquette/TR pair from supplied numerical data.

    No solver is run. PASS means only that the configured high-resolution and
    finest-step tails, TRS checks, and R6.6Q eigenmode qualification pass for
    this exact local observable definition.
    """
    if not isinstance(provenance, BerryObservableProvenance):
        raise TypeError("provenance must be BerryObservableProvenance")
    if not isinstance(thresholds, BerryObservableThresholds):
        raise TypeError("thresholds must be BerryObservableThresholds")
    try:
        resolution_samples = tuple(resolution_samples)
        step_samples = tuple(step_samples)
    except TypeError as exc:
        raise TypeError("sample ladders must be iterable") from exc
    if any(not isinstance(sample, QualifiedBerrySample) for sample in resolution_samples):
        raise TypeError("resolution_samples must contain QualifiedBerrySample values")
    if any(not isinstance(sample, QualifiedBerrySample) for sample in step_samples):
        raise TypeError("step_samples must contain QualifiedBerrySample values")
    _validate_ladders(resolution_samples, step_samples)

    checks: list[ConvergenceCheck] = []
    if len(resolution_samples) < thresholds.required_resolution_tail_pairs + 1:
        checks.append(_check(
            "resolution.completeness", "INCOMPLETE",
            {"sample_count": len(resolution_samples)},
            {"minimum_samples": thresholds.required_resolution_tail_pairs + 1},
            "resolution ladder lacks the required tail pairs",
        ))
    if len(step_samples) < thresholds.required_step_tail_pairs + 1:
        checks.append(_check(
            "step.completeness", "INCOMPLETE",
            {"sample_count": len(step_samples)},
            {"minimum_samples": thresholds.required_step_tail_pairs + 1},
            "step ladder lacks the required tail pairs",
        ))

    resolution_pair_indices = tuple(_tail_pair_indices(
        len(resolution_samples), thresholds.required_resolution_tail_pairs
    ))
    step_pair_indices = tuple(_tail_pair_indices(
        len(step_samples), thresholds.required_step_tail_pairs
    ))
    gating_samples: list[QualifiedBerrySample] = []
    gating_keys: set[tuple[int, float]] = set()

    def add_gating(sample: QualifiedBerrySample) -> None:
        key = _sample_key(sample)
        if key not in gating_keys:
            gating_keys.add(key)
            gating_samples.append(sample)

    for index in resolution_pair_indices:
        add_gating(resolution_samples[index])
        add_gating(resolution_samples[index + 1])
    for index in step_pair_indices:
        add_gating(step_samples[index])
        add_gating(step_samples[index + 1])
    if resolution_samples:
        add_gating(resolution_samples[-1])
    if step_samples:
        add_gating(step_samples[-1])

    expected_eigenmode = provenance.eigenmode_provenance()
    for sample in gating_samples:
        binding = bind_eigenmode_certificate_for_resolution(
            sample.eigenmode_certificate,
            expected_provenance=expected_eigenmode,
            expected_resolution=sample.resolution,
        )
        checks.append(_check(
            f"eigenmode.scope.r{sample.resolution}.step{sample.step:g}",
            binding.status,
            {
                "resolution": sample.resolution,
                "step": sample.step,
                "binding": binding.to_dict(),
            },
            {"status": "PASS"},
            "R6.6Q scoped eigenmode binding must pass for every gating sample",
        ))

    for index in resolution_pair_indices:
        lower = resolution_samples[index]
        upper = resolution_samples[index + 1]
        for label, value_lower, value_upper in (
            ("omega_plus", lower.omega_plus, upper.omega_plus),
            ("omega_tr", lower.omega_tr, upper.omega_tr),
        ):
            passed, limit = _within(
                value_lower, value_upper,
                thresholds.max_resolution_abs_change,
                thresholds.max_resolution_relative_change,
            )
            checks.append(_check(
                f"resolution.r{lower.resolution}-r{upper.resolution}.{label}",
                "PASS" if passed else "FAIL",
                {
                    "lower": value_lower,
                    "upper": value_upper,
                    "abs_change": abs(value_upper - value_lower),
                },
                {
                    "max_abs_change": thresholds.max_resolution_abs_change,
                    "max_relative_change": thresholds.max_resolution_relative_change,
                    "combined_limit": limit,
                },
                "adjacent resolution Berry values must satisfy the configured gate",
            ))

    for index in step_pair_indices:
        coarse = step_samples[index]
        fine = step_samples[index + 1]
        for label, value_coarse, value_fine in (
            ("omega_plus", coarse.omega_plus, fine.omega_plus),
            ("omega_tr", coarse.omega_tr, fine.omega_tr),
        ):
            passed, limit = _within(
                value_coarse, value_fine,
                thresholds.max_step_abs_change,
                thresholds.max_step_relative_change,
            )
            checks.append(_check(
                f"step.{coarse.step:g}-{fine.step:g}.{label}",
                "PASS" if passed else "FAIL",
                {
                    "coarse": value_coarse,
                    "fine": value_fine,
                    "abs_change": abs(value_fine - value_coarse),
                },
                {
                    "max_abs_change": thresholds.max_step_abs_change,
                    "max_relative_change": thresholds.max_step_relative_change,
                    "combined_limit": limit,
                },
                "adjacent step Berry values must satisfy the configured gate",
            ))

    for sample in gating_samples:
        signal = 0.5 * (abs(sample.omega_plus) + abs(sample.omega_tr))
        residual = abs(sample.omega_plus + sample.omega_tr)
        limit = max(
            thresholds.max_trs_abs_residual,
            thresholds.max_trs_relative_residual * signal,
        )
        passed = residual <= limit
        checks.append(_check(
            f"trs.r{sample.resolution}.step{sample.step:g}",
            "PASS" if passed else "FAIL",
            {"omega_plus": sample.omega_plus, "omega_tr": sample.omega_tr,
             "signal": signal, "trs_residual": residual},
            {"max_abs_residual": thresholds.max_trs_abs_residual,
             "max_relative_residual": thresholds.max_trs_relative_residual,
             "combined_limit": limit},
            "the local TR pair must satisfy the configured residual gate",
        ))

    if any(check.status == "FAIL" for check in checks):
        status = "FAIL"
    elif any(check.status == "INCOMPLETE" for check in checks):
        status = "INCOMPLETE"
    else:
        status = "PASS"
    if status == "PASS":
        qualified_resolution = resolution_samples[-1].resolution
        qualified_step = step_samples[-1].step
    else:
        qualified_resolution = None
        qualified_step = None
    return BerryObservableConvergenceCertificate(
        status=status,
        thresholds=thresholds,
        provenance=provenance,
        resolution_samples=resolution_samples,
        step_samples=step_samples,
        checks=tuple(checks),
        qualified_resolution=qualified_resolution,
        qualified_step=qualified_step,
    )


__all__ = [
    "BerryObservableThresholds",
    "BerryObservableProvenance",
    "QualifiedBerrySample",
    "BerryObservableConvergenceCertificate",
    "certify_berry_observable_convergence",
]
