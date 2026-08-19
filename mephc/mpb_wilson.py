
"""E7B bridge from E7A qualified MPB paths into the E5A Wilson kernel.

The bridge preserves E7A source evidence and delegates the exact solver-neutral
path result to E5A. It does not recompute subspaces, links, or path decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .mpb_qualified_path import MPBQualifiedPathResult
from .wilson_geometry import (
    WILSON_TRANSPORT_AUTHORIZATION_SCOPE,
    WilsonTransportResult,
    compose_wilson_transport,
)


MPB_WILSON_AUTHORIZATION_SCOPE = "mpb_wilson_transport_only"


def _safe(value: Any, *, path: str = "value") -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe(item, path=f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} must be JSON-safe")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class MPBQualifiedWilsonResult:
    """E7B evidence wrapper around one exact E5A Wilson result."""

    mpb_path_result: MPBQualifiedPathResult
    wilson_result: WilsonTransportResult
    require_live: bool = True
    authorization_scope: str = MPB_WILSON_AUTHORIZATION_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.mpb_path_result, MPBQualifiedPathResult):
            raise TypeError("mpb_path_result must be MPBQualifiedPathResult")
        if not isinstance(self.wilson_result, WilsonTransportResult):
            raise TypeError("wilson_result must be WilsonTransportResult")
        if self.wilson_result.provenance != self.mpb_path_result.path_result.provenance:
            raise ValueError("wilson result provenance must preserve the exact E7A path provenance")
        if type(self.require_live) is not bool:
            raise TypeError("require_live must be bool")
        if self.authorization_scope != MPB_WILSON_AUTHORIZATION_SCOPE:
            raise ValueError("invalid E7B authorization scope")
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze(_safe(dict(self.provenance), path="provenance")))

    @property
    def status(self) -> str:
        return self.wilson_result.status

    @property
    def closed(self) -> bool:
        return self.wilson_result.closed

    @property
    def rank(self) -> int:
        return self.wilson_result.rank

    @property
    def is_qualified(self) -> bool:
        return self.wilson_result.is_qualified

    @property
    def is_live_qualified(self) -> bool:
        return self.mpb_path_result.is_live_qualified and self.wilson_result.is_qualified

    @property
    def product(self):
        return self.wilson_result.product

    @property
    def matrix(self):
        return self.wilson_result.product

    @property
    def wilson_matrix(self):
        return self.wilson_result.product

    @property
    def unitarity_residual(self):
        return self.wilson_result.unitarity_residual

    @property
    def eigenvalues(self):
        return self.wilson_result.eigenvalues

    @property
    def eigenphases(self):
        return self.wilson_result.eigenphases

    @property
    def trace(self):
        return self.wilson_result.trace

    @property
    def determinant(self):
        return self.wilson_result.determinant

    @property
    def determinant_phase(self):
        return self.wilson_result.determinant_phase

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "closed": self.closed,
            "rank": self.rank,
            "is_qualified": self.is_qualified,
            "is_live_qualified": self.is_live_qualified,
            "require_live": self.require_live,
            "authorization_scope": self.authorization_scope,
            "mpb_path_result": self.mpb_path_result.to_dict(),
            "wilson_result": self.wilson_result.to_dict(),
            "evidence": list(self.evidence),
            "provenance": _thaw(self.provenance),
        }


def compose_mpb_wilson_transport(
    mpb_path_result: MPBQualifiedPathResult,
    *,
    require_live: bool = True,
) -> MPBQualifiedWilsonResult:
    """Delegate an E7A path result to E5A without rebuilding any evidence."""
    if not isinstance(mpb_path_result, MPBQualifiedPathResult):
        raise TypeError("mpb_path_result must be MPBQualifiedPathResult")
    if type(require_live) is not bool:
        raise TypeError("require_live must be bool")
    if require_live and mpb_path_result.is_qualified and not mpb_path_result.is_live_qualified:
        raise ValueError("live MPB-qualified E7A path is required for the primary E7B API")

    wilson_result = compose_wilson_transport(mpb_path_result.path_result)
    return MPBQualifiedWilsonResult(
        mpb_path_result=mpb_path_result,
        wilson_result=wilson_result,
        require_live=require_live,
        evidence=(
            "the exact E7A MPBQualifiedPathResult was preserved",
            "the exact E4D PathQualificationResult was delegated to E5A",
            "the exact E5A WilsonTransportResult was preserved",
            "authorization is limited to MPB Wilson transport",
        ),
        provenance={
            "source": "E7B MPB qualified Wilson transport bridge",
            "e7a_authorization_scope": mpb_path_result.authorization_scope,
            "e5a_authorization_scope": WILSON_TRANSPORT_AUTHORIZATION_SCOPE,
            "live_required": require_live,
        },
    )


__all__ = [
    "MPB_WILSON_AUTHORIZATION_SCOPE",
    "MPBQualifiedWilsonResult",
    "compose_mpb_wilson_transport",
]
