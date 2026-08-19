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


from .convergence import (
    check_eigenmode_certificate_integrity,
    revalidate_eigenmode_certificate,
)


def bind_eigenmode_certificate(
    certificate: EigenmodeConvergenceCertificate,
    *,
    expected_provenance: EigenmodeConvergenceProvenance,
) -> EigenmodeCertificateBinding:
    """Bind only a canonically revalidated certificate to exact provenance."""
    if not isinstance(certificate, EigenmodeConvergenceCertificate):
        raise TypeError("certificate must be EigenmodeConvergenceCertificate")
    if not isinstance(expected_provenance, EigenmodeConvergenceProvenance):
        raise TypeError("expected_provenance must be EigenmodeConvergenceProvenance")

    integrity = check_eigenmode_certificate_integrity(certificate)
    canonical = revalidate_eigenmode_certificate(certificate)
    checks = [integrity]
    certificate_status = certificate.status
    canonical_status = canonical.status
    if canonical_status == "PASS":
        certificate_check_status = "PASS"
        certificate_message = "canonical certificate status is PASS"
    elif canonical_status == "INCOMPLETE":
        certificate_check_status = "INCOMPLETE"
        certificate_message = "canonical certificate lacks required convergence evidence"
    else:
        certificate_check_status = "FAIL"
        certificate_message = "canonical certificate scientific checks failed"
    checks.append(ConvergenceCheck(
        name="certificate.status",
        status=certificate_check_status,
        observed={"supplied": certificate_status, "canonical": canonical_status},
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

    if integrity.status == "FAIL" or provenance_mismatch or canonical_status == "FAIL":
        status = "FAIL"
    elif canonical_status == "INCOMPLETE":
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


@dataclass(frozen=True)
class EigenmodeCertificateScopeBinding:
    """Exact provenance binding additionally scoped to one certified resolution."""

    status: str
    provenance_binding: EigenmodeCertificateBinding
    expected_resolution: int
    certified_resolution: int | None
    checks: tuple[ConvergenceCheck, ...]

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        if not isinstance(self.provenance_binding, EigenmodeCertificateBinding):
            raise TypeError("provenance_binding must be EigenmodeCertificateBinding")
        if isinstance(self.expected_resolution, bool) or not isinstance(self.expected_resolution, int) or self.expected_resolution < 1:
            raise ValueError("expected_resolution must be a positive integer")
        if self.certified_resolution is not None and (isinstance(self.certified_resolution, bool) or not isinstance(self.certified_resolution, int) or self.certified_resolution < 1):
            raise ValueError("certified_resolution must be a positive integer or None")
        if not isinstance(self.checks, tuple) or any(not isinstance(check, ConvergenceCheck) for check in self.checks):
            raise TypeError("checks must contain ConvergenceCheck values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mephc-eigenmode-scope-binding/v1",
            "status": self.status,
            "provenance_binding": self.provenance_binding.to_dict(),
            "expected_resolution": self.expected_resolution,
            "certified_resolution": self.certified_resolution,
            "checks": [check.to_dict() for check in self.checks],
        }

    def require_passed(self) -> "EigenmodeCertificateScopeBinding":
        if self.status == "PASS":
            return self
        blockers = [check.name for check in self.checks if check.status != "PASS"]
        names = ", ".join(blockers) if blockers else "unknown check"
        raise NumericalConvergenceError(
            f"eigenmode certificate scope binding is {self.status}: {names}"
        )


def bind_eigenmode_certificate_for_resolution(
    certificate: EigenmodeConvergenceCertificate,
    *,
    expected_provenance: EigenmodeConvergenceProvenance,
    expected_resolution: int,
) -> EigenmodeCertificateScopeBinding:
    """Bind a canonically valid certificate to its exact final resolution."""
    if not isinstance(certificate, EigenmodeConvergenceCertificate):
        raise TypeError("certificate must be EigenmodeConvergenceCertificate")
    if not isinstance(expected_provenance, EigenmodeConvergenceProvenance):
        raise TypeError("expected_provenance must be EigenmodeConvergenceProvenance")
    if isinstance(expected_resolution, bool) or not isinstance(expected_resolution, int) or expected_resolution < 1:
        raise ValueError("expected_resolution must be a positive integer")

    provenance_binding = bind_eigenmode_certificate(
        certificate, expected_provenance=expected_provenance
    )
    canonical = revalidate_eigenmode_certificate(certificate)
    certified_resolution = None
    if canonical.status == "PASS":
        certified_resolution = canonical.evidence[-1].upper_resolution

    if provenance_binding.status == "FAIL":
        scope_status = "FAIL"
        scope_check_status = "FAIL"
        message = "underlying certificate/provenance binding failed"
    elif provenance_binding.status == "INCOMPLETE":
        scope_status = "INCOMPLETE"
        scope_check_status = "INCOMPLETE"
        message = "canonical certificate has no certified resolution"
    elif certified_resolution != expected_resolution:
        scope_status = "FAIL"
        scope_check_status = "FAIL"
        message = "expected resolution is not the certificate's exact certified resolution"
    else:
        scope_status = "PASS"
        scope_check_status = "PASS"
        message = "expected resolution exactly matches the certified resolution"

    scope_check = ConvergenceCheck(
        name="certificate.resolution_scope",
        status=scope_check_status,
        observed={
            "expected_resolution": expected_resolution,
            "certified_resolution": certified_resolution,
        },
        criterion={"exact_match": True},
        message=message,
    )
    return EigenmodeCertificateScopeBinding(
        status=scope_status,
        provenance_binding=provenance_binding,
        expected_resolution=expected_resolution,
        certified_resolution=certified_resolution,
        checks=provenance_binding.checks + (scope_check,),
    )


__all__ = [
    "EigenmodeCertificateBinding",
    "EigenmodeCertificateScopeBinding",
    "bind_eigenmode_certificate",
    "bind_eigenmode_certificate_for_resolution",
]
