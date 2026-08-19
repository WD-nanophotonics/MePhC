"""E7D live MPB qualified plaquette holonomy bridge.

This module preserves sealed E7C boundary evidence, adapts it to E4D closed
paths, and delegates exactly once per level to the E5A Wilson kernel. It does
not solve MPB, requalify edges, divide by area, or compute observables.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .mpb_qualified_plaquette import MPBQualifiedPlaquetteResult
from .path_domain import (
    PATH_INCOMPLETE,
    PATH_SINGLE_BAND_QUALIFIED,
    PATH_SUBSPACE_QUALIFIED,
    PATH_UNQUALIFIED,
    PathQualificationResult,
)
from .plaquette_domain import (
    PLAQUETTE_BOUNDARY_INCOMPLETE,
    PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED,
    PLAQUETTE_BOUNDARY_UNQUALIFIED,
)
from .wilson_geometry import (
    WILSON_INPUT_INCOMPLETE,
    WILSON_INPUT_UNQUALIFIED,
    WilsonTransportResult,
    compose_wilson_transport,
)

E7D_MPB_PLAQUETTE_HOLONOMY_SCOPE = "mpb_plaquette_holonomy_only"

_BOUNDARY_TO_PATH = {
    PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED: PATH_SINGLE_BAND_QUALIFIED,
    PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED: PATH_SUBSPACE_QUALIFIED,
    PLAQUETTE_BOUNDARY_INCOMPLETE: PATH_INCOMPLETE,
    PLAQUETTE_BOUNDARY_UNQUALIFIED: PATH_UNQUALIFIED,
}


def _safe(value: Any) -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("provenance contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError("value must be JSON-safe")


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


def _path_adapter(source: MPBQualifiedPlaquetteResult, index: int) -> PathQualificationResult:
    boundary = source.boundary_results[index]
    status = _BOUNDARY_TO_PATH.get(boundary.status, PATH_UNQUALIFIED)
    return PathQualificationResult(
        status=status,
        vertices=boundary.vertices,
        edge_results=boundary.edge_results,
        external_contexts=boundary.external_contexts,
        thresholds=boundary.thresholds,
        closed=True,
        evidence=(
            "exact E7C boundary vertices, edge results, and external contexts were reused",
            "E7D maps E4A boundary status for E4D adapter compatibility only",
            "edges were not requalified",
        ),
        provenance={
            "source": "E7D E7C-to-E4D closed boundary adapter",
            "e7c_level": index,
            "e7c_boundary_status": boundary.status,
            "authorization_scope": E7D_MPB_PLAQUETTE_HOLONOMY_SCOPE,
        },
    )


def _blocked_wilson(path: PathQualificationResult, reason: str) -> WilsonTransportResult:
    status = WILSON_INPUT_INCOMPLETE if path.status == PATH_INCOMPLETE else WILSON_INPUT_UNQUALIFIED
    return WilsonTransportResult(
        status=status,
        closed=True,
        rank=path.vertices[0].dimension,
        product=None,
        edge_links=(),
        evidence=(reason, "no Wilson product was exposed"),
        provenance=path.provenance,
    )


@dataclass(frozen=True)
class MPBQualifiedPlaquetteHolonomyResult:
    source_result: MPBQualifiedPlaquetteResult
    path_results: tuple[PathQualificationResult, ...]
    wilson_results: tuple[WilsonTransportResult, ...]
    require_live: bool = True
    authorization_scope: str = E7D_MPB_PLAQUETTE_HOLONOMY_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source_result, MPBQualifiedPlaquetteResult):
            raise TypeError("source_result must be MPBQualifiedPlaquetteResult")
        paths = tuple(self.path_results)
        wilsons = tuple(self.wilson_results)
        if len(paths) != len(self.source_result.boundary_results) or len(wilsons) != len(paths):
            raise ValueError("E7D must preserve one path and Wilson result per E7C level")
        if any(not isinstance(path, PathQualificationResult) for path in paths):
            raise TypeError("path_results must contain PathQualificationResult values")
        if any(not isinstance(result, WilsonTransportResult) for result in wilsons):
            raise TypeError("wilson_results must contain WilsonTransportResult values")
        if type(self.require_live) is not bool:
            raise TypeError("require_live must be bool")
        if self.authorization_scope != E7D_MPB_PLAQUETTE_HOLONOMY_SCOPE:
            raise ValueError("invalid E7D authorization scope")
        if not self.source_result.is_qualified and any(result.product is not None for result in wilsons):
            raise ValueError("unqualified E7C results must not expose Wilson products")
        object.__setattr__(self, "path_results", paths)
        object.__setattr__(self, "wilson_results", wilsons)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze(_safe(dict(self.provenance))))

    @property
    def status(self) -> tuple[str, ...]:
        return tuple(result.status for result in self.wilson_results)

    @property
    def is_qualified(self) -> bool:
        return self.source_result.is_qualified and all(result.is_qualified for result in self.wilson_results)

    @property
    def is_live_qualified(self) -> bool:
        return (
            self.require_live is True
            and self.source_result.is_live_qualified
            and self.is_qualified
        )

    @property
    def products(self) -> tuple[Any, ...]:
        return tuple(result.product for result in self.wilson_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": list(self.status),
            "is_qualified": self.is_qualified,
            "is_live_qualified": self.is_live_qualified,
            "require_live": self.require_live,
            "authorization_scope": self.authorization_scope,
            "source_result": self.source_result.to_dict(),
            "path_results": [path.to_dict() for path in self.path_results],
            "wilson_results": [result.to_dict() for result in self.wilson_results],
            "evidence": list(self.evidence),
            "provenance": _thaw(self.provenance),
        }


def compose_mpb_plaquette_holonomy(
    source_result: MPBQualifiedPlaquetteResult,
    *,
    require_live: bool = True,
) -> MPBQualifiedPlaquetteHolonomyResult:
    """Compose one exact E5A Wilson result for each E7C refinement level."""
    if not isinstance(source_result, MPBQualifiedPlaquetteResult):
        raise TypeError("source_result must be MPBQualifiedPlaquetteResult")
    if type(require_live) is not bool:
        raise TypeError("require_live must be bool")
    if require_live and source_result.is_qualified and not source_result.is_live_qualified:
        raise ValueError("live E7C-qualified plaquette result is required")

    paths = tuple(_path_adapter(source_result, index) for index in range(len(source_result.boundary_results)))
    if not source_result.is_qualified:
        wilsons = tuple(
            _blocked_wilson(path, "E7C refinement is not qualified")
            for path in paths
        )
    else:
        wilsons = tuple(compose_wilson_transport(path) for path in paths)
    return MPBQualifiedPlaquetteHolonomyResult(
        source_result=source_result,
        path_results=paths,
        wilson_results=wilsons,
        require_live=require_live,
        evidence=(
            "the exact sealed E7C MPBQualifiedPlaquetteResult was preserved",
            "each exact E4A boundary was adapted to one closed E4D PathQualificationResult",
            "each closed path was passed exactly once to E5A compose_wilson_transport",
            "authorization is limited to qualified MPB plaquette Wilson holonomy",
        ),
        provenance={
            "source": "E7D live MPB qualified plaquette holonomy bridge",
            "e7c_authorization_scope": source_result.authorization_scope,
            "live_required": require_live,
        },
    )


__all__ = [
    "E7D_MPB_PLAQUETTE_HOLONOMY_SCOPE",
    "MPBQualifiedPlaquetteHolonomyResult",
    "compose_mpb_plaquette_holonomy",
]
