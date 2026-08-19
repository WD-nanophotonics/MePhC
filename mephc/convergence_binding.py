"""Exact provenance binding for eigenmode convergence certificates.

The binding protects against replaying a certificate across incompatible
numerical provenance. An exact provenance match plus a certificate PASS is
required, and binding PASS remains necessary but not sufficient for Berry or
other observable validity. This pure-data layer never runs or validates MPB.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .convergence import (
    ConvergenceCheck,
    EigenmodeConvergenceCertificate,
    EigenmodeConvergenceProvenance,
    NumericalConvergenceError,
)


_SCHEMA = "mephc-eigenmode-binding/v1"
_STATUSES = frozenset({"PASS", "FAIL", "INCOMPLETE"})
_PROVENANCE_FIELDS = (
    "backend",
    "geometry_digest",
    "target_band",
    "num_bands",
    "polarization",
    "deterministic",
    "eigensolver_tolerance",
    "mesh_size",
    "field_representation",
)


@dataclass(frozen=True)
class EigenmodeCertificateBinding:
    """Immutable result of exact certificate/provenance compatibility checks."""

    status: str
    certificate_status: str
    expected_provenance: EigenmodeConvergenceProvenance
    observed_provenance: EigenmodeConvergenceProvenance
    checks: tuple[ConvergenceCheck, ...]

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        if self.certificate_status not in _STATUSES:
            raise ValueError(f"certificate_status must be one of {sorted(_STATUSES)}")
        if not isinstance(self.expected_provenance, EigenmodeConvergenceProvenance):
            raise TypeError("expected_provenance must be EigenmodeConvergenceProvenance")
        if not isinstance(self.observed_provenance, EigenmodeConvergenceProvenance):
            raise TypeError("observed_provenance must be EigenmodeConvergenceProvenance")
        if not isinstance(self.checks, tuple):
            raise TypeError("checks must be a tuple")
        if any(not isinstance(check, ConvergenceCheck) for check in self.checks):
            raise TypeError("checks must contain ConvergenceCheck values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "status": self.status,
            "certificate_status": self.certificate_status,
            "expected_provenance": self.expected_provenance.to_dict(),
            "observed_provenance": self.observed_provenance.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
        }

    def require_passed(self) -> "EigenmodeCertificateBinding":
        if self.status == "PASS":
            return self
        blockers = [check.name for check in self.checks if check.status != "PASS"]
        names = ", ".join(blockers) if blockers else "unknown check"
        raise NumericalConvergenceError(
            f"eigenmode certificate binding is {self.status} "
            f"(certificate={self.certificate_status}): {names}"
        )


def _provenance_value(
    provenance: EigenmodeConvergenceProvenance,
    field: str,
) -> Any:
    return getattr(provenance, field)


def bind_eigenmode_certificate(
    certificate: EigenmodeConvergenceCertificate,
    *,
    expected_provenance: EigenmodeConvergenceProvenance,
) -> EigenmodeCertificateBinding:
    """Bind a certificate to exact expected numerical provenance.

    Every R6.6N provenance field is checked independently. No normalization or
    fuzzy tolerance is applied, and no live solver or geometry object is used.
    """
    if not isinstance(certificate, EigenmodeConvergenceCertificate):
        raise TypeError("certificate must be EigenmodeConvergenceCertificate")
    if not isinstance(expected_provenance, EigenmodeConvergenceProvenance):
        raise TypeError("expected_provenance must be EigenmodeConvergenceProvenance")

    checks = []
    certificate_status = certificate.status
    if certificate_status == "PASS":
        certificate_check_status = "PASS"
        certificate_message = "certificate status is PASS"
    elif certificate_status == "INCOMPLETE":
        certificate_check_status = "INCOMPLETE"
        certificate_message = "certificate lacks required convergence evidence"
    else:
        certificate_check_status = "FAIL"
        certificate_message = "certificate scientific checks failed"
    checks.append(ConvergenceCheck(
        name="certificate.status",
        status=certificate_check_status,
        observed=certificate_status,
        criterion="PASS",
        message=certificate_message,
    ))

    provenance_mismatch = False
    for field in _PROVENANCE_FIELDS:
        observed = _provenance_value(certificate.provenance, field)
        expected = _provenance_value(expected_provenance, field)
        matches = observed == expected
        provenance_mismatch |= not matches
        checks.append(ConvergenceCheck(
            name=f"provenance.{field}",
            status="PASS" if matches else "FAIL",
            observed=observed,
            criterion=expected,
            message=(
                f"{field} exactly matches expected provenance"
                if matches else
                f"{field} does not exactly match expected provenance"
            ),
        ))

    if provenance_mismatch or certificate_status == "FAIL":
        status = "FAIL"
    elif certificate_status == "INCOMPLETE":
        status = "INCOMPLETE"
    else:
        status = "PASS"
    return EigenmodeCertificateBinding(
        status=status,
        certificate_status=certificate_status,
        expected_provenance=expected_provenance,
        observed_provenance=certificate.provenance,
        checks=tuple(checks),
    )


__all__ = ["EigenmodeCertificateBinding", "bind_eigenmode_certificate"]
