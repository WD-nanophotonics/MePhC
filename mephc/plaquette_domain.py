"""Solver-neutral E4A plaquette boundary qualification.

E4A qualifies only the four directed boundary edges supplied by the caller.
It deliberately does not multiply transport links, qualify an interior, or
authorize Berry, Wilson, Chern, or persistent band identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .eigenspace import EigenSubspace
from .spectral_association import (
    NUMERICALLY_INCOMPLETE,
    SINGLE_BAND_QUALIFIED,
    SUBSPACE_QUALIFIED,
    ExternalIsolationContext,
    SubspaceQualificationResult,
    SubspaceQualificationThresholds,
    qualify_local_subspace,
)


PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED = "PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED"
PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED = "PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED"
PLAQUETTE_BOUNDARY_UNQUALIFIED = "PLAQUETTE_BOUNDARY_UNQUALIFIED"
PLAQUETTE_BOUNDARY_INCOMPLETE = "PLAQUETTE_BOUNDARY_INCOMPLETE"
BOUNDARY_AUTHORIZATION_SCOPE = "boundary_only"


def _json_safe(value: Any, *, path: str = "value") -> Any:
    if value is None or type(value) in {bool, str, int, float}:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, path=f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} must be JSON-safe")


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType(_json_safe(dict(value), path="provenance"))


def _context(value: ExternalIsolationContext | Mapping[str, Any] | None) -> ExternalIsolationContext | None:
    if value is None:
        return None
    if isinstance(value, ExternalIsolationContext):
        return value
    if isinstance(value, Mapping):
        return ExternalIsolationContext.from_mapping(value)
    raise TypeError("external_contexts must contain ExternalIsolationContext, mappings, or None")


def _vertex_summary(vertex: EigenSubspace) -> dict[str, Any]:
    return {
        "k_point": list(vertex.k_point),
        "rank": vertex.dimension,
        "ambient_dimension": vertex.ambient_dimension,
        "solver_indices": list(vertex.solver_indices),
        "eigenvalues": list(vertex.eigenvalues),
        "metadata": _json_safe(vertex.metadata, path="vertex.metadata"),
    }


@dataclass(frozen=True)
class PlaquetteBoundaryQualificationResult:
    """Immutable evidence for the four-edge E4A boundary only."""

    status: str
    rank: int
    vertices: tuple[EigenSubspace, ...]
    edge_results: tuple[SubspaceQualificationResult, ...]
    external_contexts: tuple[ExternalIsolationContext | None, ...]
    thresholds: SubspaceQualificationThresholds
    authorization_scope: str = BOUNDARY_AUTHORIZATION_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {
            PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED,
            PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED,
            PLAQUETTE_BOUNDARY_UNQUALIFIED,
            PLAQUETTE_BOUNDARY_INCOMPLETE,
        }
        if self.status not in allowed:
            raise ValueError(f"invalid plaquette boundary status: {self.status}")
        vertices = tuple(self.vertices)
        edges = tuple(self.edge_results)
        contexts = tuple(self.external_contexts)
        if len(vertices) != 4 or len(edges) != 4 or len(contexts) != 4:
            raise ValueError("E4A result must preserve exactly four vertices, edges, and contexts")
        if any(not isinstance(vertex, EigenSubspace) for vertex in vertices):
            raise TypeError("vertices must contain EigenSubspace values")
        if any(not isinstance(edge, SubspaceQualificationResult) for edge in edges):
            raise TypeError("edge_results must contain SubspaceQualificationResult values")
        if any(context is not None and not isinstance(context, ExternalIsolationContext) for context in contexts):
            raise TypeError("external_contexts must be normalized contexts")
        if self.rank < 1 or any(vertex.dimension != self.rank for vertex in vertices):
            raise ValueError("all vertices must have the fixed result rank")
        if self.authorization_scope != BOUNDARY_AUTHORIZATION_SCOPE:
            raise ValueError("E4A authorization scope is boundary_only")
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "edge_results", edges)
        object.__setattr__(self, "external_contexts", contexts)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))

    @property
    def edges(self) -> tuple[SubspaceQualificationResult, ...]:
        return self.edge_results

    @property
    def is_qualified(self) -> bool:
        return self.status in {
            PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED,
            PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED,
        }

    def to_dict(self, *, include_matrices: bool = False) -> dict[str, Any]:
        return {
            "status": self.status,
            "rank": self.rank,
            "vertices": [_vertex_summary(vertex) for vertex in self.vertices],
            "edges": [edge.to_dict(include_matrices=include_matrices) for edge in self.edge_results],
            "external_contexts": [
                None if context is None else context.to_dict()
                for context in self.external_contexts
            ],
            "thresholds": self.thresholds.to_dict(),
            "authorization_scope": self.authorization_scope,
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
        }


PlaquetteBoundaryResult = PlaquetteBoundaryQualificationResult


def qualify_plaquette_boundary(
    vertices: Sequence[EigenSubspace],
    external_contexts: Sequence[ExternalIsolationContext | Mapping[str, Any] | None],
    *,
    thresholds: SubspaceQualificationThresholds,
    provenance: Mapping[str, Any] | None = None,
) -> PlaquetteBoundaryQualificationResult:
    """Qualify exactly four caller-ordered cyclic boundary edges."""
    if not isinstance(thresholds, SubspaceQualificationThresholds):
        raise TypeError("thresholds must be SubspaceQualificationThresholds")
    if isinstance(vertices, (str, bytes)) or not isinstance(vertices, Sequence) or len(vertices) != 4:
        raise ValueError("E4A requires exactly four ordered EigenSubspace vertices")
    if isinstance(external_contexts, (str, bytes)) or not isinstance(external_contexts, Sequence) or len(external_contexts) != 4:
        raise ValueError("E4A requires exactly four aligned ExternalIsolationContext values")
    normalized_vertices = tuple(vertices)
    if any(not isinstance(vertex, EigenSubspace) for vertex in normalized_vertices):
        raise TypeError("vertices must contain EigenSubspace values")
    coordinate_dimension = len(normalized_vertices[0].k_point)
    ambient_dimension = normalized_vertices[0].ambient_dimension
    rank = normalized_vertices[0].dimension
    if any(len(vertex.k_point) != coordinate_dimension for vertex in normalized_vertices):
        raise ValueError("all vertices must share one k-point coordinate dimension")
    if any(vertex.ambient_dimension != ambient_dimension for vertex in normalized_vertices):
        raise ValueError("all vertices must share one ambient dimension")
    if any(vertex.dimension != rank for vertex in normalized_vertices):
        raise ValueError("all vertices must have one fixed rank")
    normalized_contexts = tuple(_context(value) for value in external_contexts)
    edge_results = tuple(
        qualify_local_subspace(
            normalized_vertices[index],
            normalized_vertices[(index + 1) % 4],
            thresholds=thresholds,
            external_context=normalized_contexts[index],
        )
        for index in range(4)
    )
    statuses = tuple(edge.status for edge in edge_results)
    if any(status == NUMERICALLY_INCOMPLETE for status in statuses):
        status = PLAQUETTE_BOUNDARY_INCOMPLETE
        reason = "at least one directed boundary edge is numerically incomplete"
    elif all(edge.is_qualified for edge in edge_results):
        status = (
            PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED
            if rank == 1
            else PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED
        )
        reason = "all four directed boundary edges qualified"
    else:
        status = PLAQUETTE_BOUNDARY_UNQUALIFIED
        reason = "at least one directed boundary edge is unqualified"
    return PlaquetteBoundaryQualificationResult(
        status=status,
        rank=rank,
        vertices=normalized_vertices,
        edge_results=edge_results,
        external_contexts=normalized_contexts,
        thresholds=thresholds,
        evidence=(reason, "loop closure uses the fourth edge against the exact first vertex"),
        provenance=provenance or {},
    )


qualify_plaquette = qualify_plaquette_boundary
