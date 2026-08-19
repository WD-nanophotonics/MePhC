"""Solver-neutral E4D ordered path-domain qualification.

The module qualifies caller-supplied directed edges only. It does not multiply
transport links or authorize Berry, Wilson, Chern, or persistent identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .eigenspace import EigenSubspace
from .spectral_association import (
    NUMERICALLY_INCOMPLETE,
    SUBSPACE_NOT_ISOLATED,
    ExternalIsolationContext,
    SubspaceQualificationResult,
    SubspaceQualificationThresholds,
    qualify_local_subspace,
)


PATH_SINGLE_BAND_QUALIFIED = "PATH_SINGLE_BAND_QUALIFIED"
PATH_SUBSPACE_QUALIFIED = "PATH_SUBSPACE_QUALIFIED"
PATH_SUBSPACE_REQUIRED = "PATH_SUBSPACE_REQUIRED"
PATH_UNQUALIFIED = "PATH_UNQUALIFIED"
PATH_INCOMPLETE = "PATH_INCOMPLETE"
PATH_AUTHORIZATION_SCOPE = "path_domain_only"


def _safe(value: Any) -> Any:
    if value is None or type(value) in {bool, str, int, float}:
        if type(value) is float and not math.isfinite(value):
            raise ValueError("provenance contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError("value must be JSON-safe")


def _freeze(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType({} if value is None else _safe(dict(value)))


def _context(value: ExternalIsolationContext | Mapping[str, Any] | None) -> ExternalIsolationContext | None:
    if value is None:
        return None
    if isinstance(value, ExternalIsolationContext):
        return value
    if isinstance(value, Mapping):
        return ExternalIsolationContext.from_mapping(value)
    raise TypeError("contexts must contain ExternalIsolationContext, mappings, or None")


def _vertex(vertex: EigenSubspace) -> dict[str, Any]:
    return {
        "k_point": list(vertex.k_point),
        "rank": vertex.dimension,
        "ambient_dimension": vertex.ambient_dimension,
        "solver_indices": list(vertex.solver_indices),
        "eigenvalues": list(vertex.eigenvalues),
        "metadata": _safe(vertex.metadata),
    }


@dataclass(frozen=True)
class PathQualificationResult:
    """Immutable evidence for an ordered open or closed path."""

    status: str
    vertices: tuple[EigenSubspace, ...]
    edge_results: tuple[SubspaceQualificationResult, ...]
    external_contexts: tuple[ExternalIsolationContext | None, ...]
    thresholds: SubspaceQualificationThresholds
    closed: bool
    authorization_scope: str = PATH_AUTHORIZATION_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, PATH_SUBSPACE_REQUIRED, PATH_UNQUALIFIED, PATH_INCOMPLETE}
        if self.status not in allowed:
            raise ValueError(f"invalid path status: {self.status}")
        vertices = tuple(self.vertices)
        edges = tuple(self.edge_results)
        contexts = tuple(self.external_contexts)
        expected = len(vertices) if self.closed else len(vertices) - 1
        if len(vertices) < 2 or len(edges) != expected or len(contexts) != expected:
            raise ValueError("path result does not preserve the expected ordered edge count")
        if any(not isinstance(vertex, EigenSubspace) for vertex in vertices):
            raise TypeError("vertices must contain EigenSubspace values")
        if any(not isinstance(edge, SubspaceQualificationResult) for edge in edges):
            raise TypeError("edge_results must contain SubspaceQualificationResult values")
        if self.authorization_scope != PATH_AUTHORIZATION_SCOPE:
            raise ValueError("path authorization scope must be path_domain_only")
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "edge_results", edges)
        object.__setattr__(self, "external_contexts", contexts)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze(self.provenance))

    @property
    def edges(self) -> tuple[SubspaceQualificationResult, ...]:
        return self.edge_results

    @property
    def is_qualified(self) -> bool:
        return self.status in {PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED}

    def to_dict(self, *, include_matrices: bool = False) -> dict[str, Any]:
        return {
            "status": self.status,
            "vertices": [_vertex(vertex) for vertex in self.vertices],
            "edges": [edge.to_dict(include_matrices=include_matrices) for edge in self.edge_results],
            "external_contexts": [None if item is None else item.to_dict() for item in self.external_contexts],
            "thresholds": self.thresholds.to_dict(),
            "closed": self.closed,
            "authorization_scope": self.authorization_scope,
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
        }


PathResult = PathQualificationResult


def qualify_ordered_path(
    vertices: Sequence[EigenSubspace],
    external_contexts: Sequence[ExternalIsolationContext | Mapping[str, Any] | None],
    *,
    thresholds: SubspaceQualificationThresholds,
    closed: bool,
    provenance: Mapping[str, Any] | None = None,
) -> PathQualificationResult:
    """Qualify every caller-supplied edge of an open or closed ordered path."""
    if not isinstance(thresholds, SubspaceQualificationThresholds):
        raise TypeError("thresholds must be SubspaceQualificationThresholds")
    if not isinstance(closed, bool):
        raise TypeError("closed must be bool")
    if isinstance(vertices, (str, bytes)) or not isinstance(vertices, Sequence) or len(vertices) < 2:
        raise ValueError("path requires at least two ordered vertices")
    expected = len(vertices) if closed else len(vertices) - 1
    if isinstance(external_contexts, (str, bytes)) or not isinstance(external_contexts, Sequence) or len(external_contexts) != expected:
        raise ValueError("context count does not match open or closed path edges")
    normalized_vertices = tuple(vertices)
    if any(not isinstance(vertex, EigenSubspace) for vertex in normalized_vertices):
        raise TypeError("vertices must contain EigenSubspace values")
    rank = normalized_vertices[0].dimension
    ambient = normalized_vertices[0].ambient_dimension
    coordinates = len(normalized_vertices[0].k_point)
    if any(vertex.dimension != rank for vertex in normalized_vertices):
        raise ValueError("path vertices must have one fixed rank")
    if any(vertex.ambient_dimension != ambient for vertex in normalized_vertices):
        raise ValueError("path vertices must have one ambient dimension")
    if any(len(vertex.k_point) != coordinates for vertex in normalized_vertices):
        raise ValueError("path vertices must share one k-point coordinate dimension")
    contexts = tuple(_context(item) for item in external_contexts)
    edge_results = tuple(
        qualify_local_subspace(
            normalized_vertices[index],
            normalized_vertices[(index + 1) % len(normalized_vertices)] if closed else normalized_vertices[index + 1],
            thresholds=thresholds,
            external_context=contexts[index],
        )
        for index in range(expected)
    )
    statuses = tuple(edge.status for edge in edge_results)
    if any(status == NUMERICALLY_INCOMPLETE for status in statuses):
        status, reason = PATH_INCOMPLETE, "at least one path edge is numerically incomplete"
    elif rank == 1 and any(status == SUBSPACE_NOT_ISOLATED for status in statuses):
        status, reason = PATH_SUBSPACE_REQUIRED, "rank-one path loses external isolation on an edge"
    elif all(edge.is_qualified for edge in edge_results):
        status = PATH_SINGLE_BAND_QUALIFIED if rank == 1 else PATH_SUBSPACE_QUALIFIED
        reason = "all ordered path edges qualified"
    else:
        status, reason = PATH_UNQUALIFIED, "at least one ordered path edge is unqualified"
    return PathQualificationResult(
        status=status,
        vertices=normalized_vertices,
        edge_results=edge_results,
        external_contexts=contexts,
        thresholds=thresholds,
        closed=closed,
        evidence=(reason, "authorization is limited to ordered path-domain evidence"),
        provenance=provenance or {},
    )


qualify_path = qualify_ordered_path
