"""Fail-closed qualification of supplied eigenmode convergence evidence.

This module evaluates already-computed numerical evidence; it never runs MPB.
Passing this eigenmode certificate is necessary but not sufficient for Berry or
other observable validity. Missing required evidence is ``INCOMPLETE`` and
scientific failures remain explicit in the certificate instead of being
silently coerced.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, Iterable, Mapping


_SCHEMA = "mephc-eigenmode-convergence/v1"
_STATUSES = frozenset({"PASS", "FAIL", "INCOMPLETE"})


class NumericalConvergenceError(RuntimeError):
    """Raised when a convergence certificate is required but did not pass."""


def _real(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _nonempty_string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _json_safe(value: Any, *, path: str = "value") -> Any:
    """Validate and normalize a small JSON-safe value for structured checks."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Real) and not isinstance(value, bool):
        result = float(value)
        if math.isfinite(result):
            return result
        raise ValueError(f"{path} must contain only finite numbers")
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, path=f"{path}[]") for item in value]
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} mapping keys must be strings")
            normalized[key] = _json_safe(item, path=f"{path}.{key}")
        return normalized
    raise ValueError(f"{path} must be JSON-safe")


@dataclass(frozen=True)
class EigenmodeConvergenceThresholds:
    """The R6.6L/M gates, recorded per certificate rather than universal laws."""

    max_abs_frequency_change: float = 1e-5
    min_h_fidelity: float = 0.99999
    max_h_relative_l2_residual: float = 5e-3
    min_isolation_gap: float = 1e-8
    required_tail_pairs: int = 2

    def __post_init__(self) -> None:
        for name in (
            "max_abs_frequency_change",
            "max_h_relative_l2_residual",
            "min_isolation_gap",
        ):
            if _real(getattr(self, name), name=name) < 0:
                raise ValueError(f"{name} must be positive")
        fidelity = _real(self.min_h_fidelity, name="min_h_fidelity")
        if not 0 < fidelity <= 1:
            raise ValueError("min_h_fidelity must be in (0, 1]")
        _positive_int(self.required_tail_pairs, name="required_tail_pairs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_abs_frequency_change": float(self.max_abs_frequency_change),
            "min_h_fidelity": float(self.min_h_fidelity),
            "max_h_relative_l2_residual": float(self.max_h_relative_l2_residual),
            "min_isolation_gap": float(self.min_isolation_gap),
            "required_tail_pairs": self.required_tail_pairs,
        }


@dataclass(frozen=True)
class EigenmodePairEvidence:
    """Evidence for one adjacent resolution transition."""

    lower_resolution: int
    upper_resolution: int
    max_abs_frequency_change: float
    min_h_fidelity: float
    max_h_relative_l2_residual: float
    min_isolation_gap: float

    def __post_init__(self) -> None:
        lower = _positive_int(self.lower_resolution, name="lower_resolution")
        upper = _positive_int(self.upper_resolution, name="upper_resolution")
        if upper <= lower:
            raise ValueError("upper_resolution must exceed lower_resolution")
        for name in (
            "max_abs_frequency_change",
            "max_h_relative_l2_residual",
            "min_isolation_gap",
        ):
            if _real(getattr(self, name), name=name) < 0:
                raise ValueError(f"{name} must be non-negative")
        fidelity = _real(self.min_h_fidelity, name="min_h_fidelity")
        if not 0 <= fidelity <= 1:
            raise ValueError("min_h_fidelity must be in [0, 1]")


@dataclass(frozen=True)
class EigenmodeConvergenceProvenance:
    """Solver and field provenance associated with supplied evidence."""

    backend: str
    geometry_digest: str
    target_band: int
    num_bands: int
    polarization: str
    deterministic: bool
    eigensolver_tolerance: float
    mesh_size: int
    field_representation: str

    def __post_init__(self) -> None:
        _nonempty_string(self.backend, name="backend")
        _nonempty_string(self.geometry_digest, name="geometry_digest")
        _nonnegative_int(self.target_band, name="target_band")
        _positive_int(self.num_bands, name="num_bands")
        if self.target_band >= self.num_bands:
            raise ValueError("target_band must be a valid zero-based band index")
        _nonempty_string(self.polarization, name="polarization")
        if not isinstance(self.deterministic, bool):
            raise ValueError("deterministic must be a bool")
        if _real(self.eigensolver_tolerance, name="eigensolver_tolerance") <= 0:
            raise ValueError("eigensolver_tolerance must be positive")
        _positive_int(self.mesh_size, name="mesh_size")
        _nonempty_string(self.field_representation, name="field_representation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "geometry_digest": self.geometry_digest,
            "target_band": self.target_band,
            "num_bands": self.num_bands,
            "polarization": self.polarization,
            "deterministic": self.deterministic,
            "eigensolver_tolerance": float(self.eigensolver_tolerance),
            "mesh_size": self.mesh_size,
            "field_representation": self.field_representation,
        }


@dataclass(frozen=True)
class ConvergenceCheck:
    """One explicit PASS/FAIL/INCOMPLETE certificate check."""

    name: str
    status: str
    observed: Any
    criterion: Any
    message: str

    def __post_init__(self) -> None:
        _nonempty_string(self.name, name="name")
        if self.status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        _json_safe(self.observed, path="observed")
        _json_safe(self.criterion, path="criterion")
        _nonempty_string(self.message, name="message")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "observed": _json_safe(self.observed, path="observed"),
            "criterion": _json_safe(self.criterion, path="criterion"),
            "message": self.message,
        }


@dataclass(frozen=True)
class EigenmodeConvergenceCertificate:
    """Immutable, serializable result of supplied eigenmode evidence.

    PASS is necessary but not sufficient for Berry/observable validity.
    """

    status: str
    thresholds: EigenmodeConvergenceThresholds
    provenance: EigenmodeConvergenceProvenance
    evidence: tuple[EigenmodePairEvidence, ...]
    checks: tuple[ConvergenceCheck, ...]

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        if not isinstance(self.thresholds, EigenmodeConvergenceThresholds):
            raise TypeError("thresholds must be EigenmodeConvergenceThresholds")
        if not isinstance(self.provenance, EigenmodeConvergenceProvenance):
            raise TypeError("provenance must be EigenmodeConvergenceProvenance")
        if not isinstance(self.evidence, tuple):
            raise TypeError("evidence must be a tuple")
        if not isinstance(self.checks, tuple):
            raise TypeError("checks must be a tuple")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "status": self.status,
            "thresholds": self.thresholds.to_dict(),
            "provenance": self.provenance.to_dict(),
            "evidence": [
                {
                    "lower_resolution": pair.lower_resolution,
                    "upper_resolution": pair.upper_resolution,
                    "max_abs_frequency_change": float(pair.max_abs_frequency_change),
                    "min_h_fidelity": float(pair.min_h_fidelity),
                    "max_h_relative_l2_residual": float(pair.max_h_relative_l2_residual),
                    "min_isolation_gap": float(pair.min_isolation_gap),
                }
                for pair in self.evidence
            ],
            "checks": [check.to_dict() for check in self.checks],
        }

    def require_passed(self) -> "EigenmodeConvergenceCertificate":
        if self.status == "PASS":
            return self
        failed = [check.name for check in self.checks if check.status != "PASS"]
        names = ", ".join(failed) if failed else "unknown check"
        raise NumericalConvergenceError(
            f"eigenmode convergence certificate is {self.status}: {names}"
        )


def _check(
    name: str,
    observed: Any,
    criterion: Any,
    passed: bool,
    message: str,
    *,
    status: str | None = None,
) -> ConvergenceCheck:
    return ConvergenceCheck(
        name=name,
        status=status or ("PASS" if passed else "FAIL"),
        observed=observed,
        criterion=criterion,
        message=message,
    )


def _validate_chain(evidence: tuple[EigenmodePairEvidence, ...]) -> None:
    previous: EigenmodePairEvidence | None = None
    for pair in evidence:
        if not isinstance(pair, EigenmodePairEvidence):
            raise ValueError("evidence must contain EigenmodePairEvidence values")
        if previous is not None:
            if pair.lower_resolution != previous.upper_resolution:
                raise ValueError("evidence must form a coherent adjacent chain")
            if pair.lower_resolution <= previous.lower_resolution:
                raise ValueError("evidence resolutions must increase monotonically")
        previous = pair


def certify_eigenmode_convergence(
    evidence: Iterable[EigenmodePairEvidence],
    *,
    provenance: EigenmodeConvergenceProvenance,
    thresholds: EigenmodeConvergenceThresholds = EigenmodeConvergenceThresholds(),
) -> EigenmodeConvergenceCertificate:
    """Certify supplied eigenmode evidence without running MPB.

    Only the highest configured tail pairs are scientific PASS gates. Older
    evidence is retained for auditability. Missing required pairs produce an
    ``INCOMPLETE`` check rather than an implicit PASS.
    """
    if not isinstance(provenance, EigenmodeConvergenceProvenance):
        raise TypeError("provenance must be EigenmodeConvergenceProvenance")
    if not isinstance(thresholds, EigenmodeConvergenceThresholds):
        raise TypeError("thresholds must be EigenmodeConvergenceThresholds")
    try:
        evidence_tuple = tuple(evidence)
    except TypeError as exc:
        raise ValueError("evidence must be iterable") from exc
    _validate_chain(evidence_tuple)

    checks: list[ConvergenceCheck] = []
    required = thresholds.required_tail_pairs
    available = len(evidence_tuple)
    checks.append(_check(
        "required_tail_pairs_available",
        observed=available,
        criterion={"minimum": required},
        passed=available >= required,
        message=(
            f"{required} high-resolution tail pairs are available"
            if available >= required else
            f"{required} high-resolution tail pairs are required; only {available} supplied"
        ),
        status=None if available >= required else "INCOMPLETE",
    ))

    tail = evidence_tuple[-required:] if available else ()
    for pair in tail:
        label = f"{pair.lower_resolution}_to_{pair.upper_resolution}"
        checks.append(_check(
            f"{label}.frequency_change", float(pair.max_abs_frequency_change),
            {"max": float(thresholds.max_abs_frequency_change)},
            pair.max_abs_frequency_change <= thresholds.max_abs_frequency_change,
            "maximum frequency change is within the configured gate"
            if pair.max_abs_frequency_change <= thresholds.max_abs_frequency_change
            else "maximum frequency change exceeds the configured gate",
        ))
        checks.append(_check(
            f"{label}.h_fidelity", float(pair.min_h_fidelity),
            {"min": float(thresholds.min_h_fidelity)},
            pair.min_h_fidelity >= thresholds.min_h_fidelity,
            "minimum H fidelity meets the configured gate"
            if pair.min_h_fidelity >= thresholds.min_h_fidelity
            else "minimum H fidelity is below the configured gate",
        ))
        checks.append(_check(
            f"{label}.h_relative_l2_residual", float(pair.max_h_relative_l2_residual),
            {"max": float(thresholds.max_h_relative_l2_residual)},
            pair.max_h_relative_l2_residual <= thresholds.max_h_relative_l2_residual,
            "maximum H residual is within the configured gate"
            if pair.max_h_relative_l2_residual <= thresholds.max_h_relative_l2_residual
            else "maximum H residual exceeds the configured gate",
        ))
        checks.append(_check(
            f"{label}.isolation_gap", float(pair.min_isolation_gap),
            {"min": float(thresholds.min_isolation_gap)},
            pair.min_isolation_gap >= thresholds.min_isolation_gap,
            "minimum isolation gap meets the configured gate"
            if pair.min_isolation_gap >= thresholds.min_isolation_gap
            else "minimum isolation gap is below the configured gate",
        ))

    checks.append(_check(
        "provenance.deterministic", provenance.deterministic, True,
        provenance.deterministic is True,
        "deterministic solver provenance is present"
        if provenance.deterministic is True
        else "deterministic=True is required for a production-style certificate",
    ))

    check_tuple = tuple(checks)
    if any(check.status == "FAIL" for check in check_tuple):
        status = "FAIL"
    elif any(check.status == "INCOMPLETE" for check in check_tuple):
        status = "INCOMPLETE"
    else:
        status = "PASS"
    return EigenmodeConvergenceCertificate(
        status=status,
        thresholds=thresholds,
        provenance=provenance,
        evidence=evidence_tuple,
        checks=check_tuple,
    )


__all__ = [
    "ConvergenceCheck",
    "EigenmodeConvergenceCertificate",
    "EigenmodeConvergenceProvenance",
    "EigenmodeConvergenceThresholds",
    "EigenmodePairEvidence",
    "NumericalConvergenceError",
    "certify_eigenmode_convergence",
    "check_eigenmode_certificate_integrity",
    "revalidate_eigenmode_certificate",
]


def revalidate_eigenmode_certificate(
    certificate: EigenmodeConvergenceCertificate,
) -> EigenmodeConvergenceCertificate:
    """Recompute the canonical certificate without trusting stored status/checks."""
    if not isinstance(certificate, EigenmodeConvergenceCertificate):
        raise TypeError("certificate must be EigenmodeConvergenceCertificate")
    return certify_eigenmode_convergence(
        certificate.evidence,
        provenance=certificate.provenance,
        thresholds=certificate.thresholds,
    )


def check_eigenmode_certificate_integrity(
    certificate: EigenmodeConvergenceCertificate,
) -> ConvergenceCheck:
    """Compare a certificate with its fresh canonical deterministic serialization."""
    if not isinstance(certificate, EigenmodeConvergenceCertificate):
        raise TypeError("certificate must be EigenmodeConvergenceCertificate")
    canonical = revalidate_eigenmode_certificate(certificate)
    supplied_status = certificate.status
    canonical_status = canonical.status
    serialization_error = None
    try:
        supplied = certificate.to_dict()
        expected = canonical.to_dict()
        serialized_match = supplied == expected
    except (TypeError, ValueError, AttributeError) as exc:
        serialized_match = False
        serialization_error = type(exc).__name__
    observed = {
        "supplied_status": supplied_status,
        "canonical_status": canonical_status,
        "serialized_match": serialized_match,
    }
    if serialization_error is not None:
        observed["serialization_error"] = serialization_error
    return ConvergenceCheck(
        name="certificate.integrity",
        status="PASS" if serialized_match else "FAIL",
        observed=observed,
        criterion={
            "canonical_status": canonical_status,
            "serialized_match": True,
        },
        message=(
            "stored certificate exactly matches canonical revalidation"
            if serialized_match else
            "stored certificate differs from canonical revalidation"
        ),
    )
