"""Solver-neutral E4A plaquette boundary qualification.

E4A qualifies only the four directed boundary edges supplied by the caller.
It deliberately does not multiply transport links, qualify an interior, or
authorize Berry, Wilson, Chern, or persistent band identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .eigenspace import EigenSubspace
from .spectral_association import (
    NUMERICALLY_INCOMPLETE,
    SUBSPACE_NOT_ISOLATED,
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


PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED = "PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED"
PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED = "PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED"
PLAQUETTE_SUBSPACE_REQUIRED = "PLAQUETTE_SUBSPACE_REQUIRED"
PLAQUETTE_BOUNDARY_ONLY = "PLAQUETTE_BOUNDARY_ONLY"
PLAQUETTE_INTERIOR_INCOMPLETE = "PLAQUETTE_INTERIOR_INCOMPLETE"
PLAQUETTE_INTERIOR_UNQUALIFIED = "PLAQUETTE_INTERIOR_UNQUALIFIED"
SAMPLED_INTERIOR_AUTHORIZATION_SCOPE = "sampled_interior_only"


@dataclass(frozen=True)
class PlaquetteInteriorQualificationResult:
    """Immutable sampled spoke evidence; never a full-interior certificate."""

    status: str
    boundary_status: str
    center: EigenSubspace
    spoke_results: tuple[SubspaceQualificationResult, ...]
    thresholds: SubspaceQualificationThresholds
    geometry_tolerance: float
    authorization_scope: str = SAMPLED_INTERIOR_AUTHORIZATION_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {
            PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED,
            PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED,
            PLAQUETTE_SUBSPACE_REQUIRED,
            PLAQUETTE_BOUNDARY_ONLY,
            PLAQUETTE_INTERIOR_INCOMPLETE,
            PLAQUETTE_INTERIOR_UNQUALIFIED,
        }
        if self.status not in allowed:
            raise ValueError(f"invalid plaquette interior status: {self.status}")
        spokes = tuple(self.spoke_results)
        if len(spokes) != 4 or any(not isinstance(item, SubspaceQualificationResult) for item in spokes):
            raise ValueError("E4B must preserve exactly four spoke results")
        if not isinstance(self.center, EigenSubspace):
            raise TypeError("center must be an EigenSubspace")
        if self.geometry_tolerance < 0.0:
            raise ValueError("geometry_tolerance must be non-negative")
        if self.authorization_scope != SAMPLED_INTERIOR_AUTHORIZATION_SCOPE:
            raise ValueError("E4B authorization scope is sampled_interior_only")
        object.__setattr__(self, "spoke_results", spokes)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))

    @property
    def is_qualified(self) -> bool:
        return self.status in {
            PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED,
            PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED,
        }

    @property
    def spokes(self) -> tuple[SubspaceQualificationResult, ...]:
        return self.spoke_results

    def to_dict(self, *, include_matrices: bool = False) -> dict[str, Any]:
        return {
            "status": self.status,
            "boundary_status": self.boundary_status,
            "center": _vertex_summary(self.center),
            "spokes": [item.to_dict(include_matrices=include_matrices) for item in self.spoke_results],
            "thresholds": self.thresholds.to_dict(),
            "geometry_tolerance": self.geometry_tolerance,
            "authorization_scope": self.authorization_scope,
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
        }


PlaquetteInteriorResult = PlaquetteInteriorQualificationResult


def _validate_e4b_geometry(boundary, center: EigenSubspace, tolerance: float) -> None:
    vertices = tuple(boundary.vertices)
    if len(vertices) != 4 or any(len(vertex.k_point) != 2 for vertex in vertices):
        raise ValueError("E4B requires a two-dimensional four-vertex plaquette")
    if len(center.k_point) != 2:
        raise ValueError("E4B center must have two k-point coordinates")
    points = np.asarray([vertex.k_point for vertex in vertices], dtype=float)
    expected = np.mean(points, axis=0)
    if float(np.linalg.norm(np.asarray(center.k_point) - expected)) > tolerance:
        raise ValueError("center k point must equal the four-vertex arithmetic mean")
    area = 0.5 * abs(float(np.sum(points[:, 0] * np.roll(points[:, 1], -1) - points[:, 1] * np.roll(points[:, 0], -1))))
    if not math.isfinite(area) or area <= tolerance:
        raise ValueError("plaquette vertices must form a nondegenerate ordered polygon")


def qualify_plaquette_interior(
    boundary,
    center: EigenSubspace,
    spoke_contexts: Sequence[ExternalIsolationContext | Mapping[str, Any] | None],
    *,
    geometry_tolerance: float = 1e-10,
    provenance: Mapping[str, Any] | None = None,
) -> PlaquetteInteriorQualificationResult:
    """Qualify four caller-supplied vertex-to-center spokes only."""
    from .plaquette_domain import PlaquetteBoundaryQualificationResult

    if not isinstance(boundary, PlaquetteBoundaryQualificationResult):
        raise TypeError("boundary must be a PlaquetteBoundaryQualificationResult")
    if not isinstance(center, EigenSubspace):
        raise TypeError("center must be an EigenSubspace")
    if isinstance(geometry_tolerance, bool) or not isinstance(geometry_tolerance, Real):
        raise TypeError("geometry_tolerance must be a finite real scalar")
    geometry_tolerance = float(geometry_tolerance)
    if not math.isfinite(geometry_tolerance) or geometry_tolerance < 0.0:
        raise ValueError("geometry_tolerance must be finite and non-negative")
    if isinstance(spoke_contexts, (str, bytes)) or not isinstance(spoke_contexts, Sequence) or len(spoke_contexts) != 4:
        raise ValueError("E4B requires exactly four aligned spoke contexts")
    _validate_e4b_geometry(boundary, center, geometry_tolerance)
    if center.dimension != boundary.rank:
        raise ValueError("center rank must match the E4A boundary rank")
    if center.ambient_dimension != boundary.vertices[0].ambient_dimension:
        raise ValueError("center ambient dimension must match the E4A boundary")
    contexts = tuple(_context(value) for value in spoke_contexts)
    spokes = tuple(
        qualify_local_subspace(
            boundary.vertices[index],
            center,
            thresholds=boundary.thresholds,
            external_context=contexts[index],
        )
        for index in range(4)
    )
    if boundary.status == PLAQUETTE_BOUNDARY_INCOMPLETE:
        status, reason = PLAQUETTE_INTERIOR_INCOMPLETE, "E4A boundary is incomplete"
    elif not boundary.is_qualified:
        status, reason = PLAQUETTE_BOUNDARY_ONLY, "E4A boundary is not qualified"
    elif any(item.status == NUMERICALLY_INCOMPLETE for item in spokes):
        status, reason = PLAQUETTE_INTERIOR_INCOMPLETE, "at least one spoke is numerically incomplete"
    elif all(item.is_qualified for item in spokes):
        status = (
            PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED
            if boundary.rank == 1
            else PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED
        )
        reason = "all four sampled vertex-to-center spokes qualified"
    elif boundary.rank == 1 and any(item.status == SUBSPACE_NOT_ISOLATED for item in spokes):
        status, reason = PLAQUETTE_SUBSPACE_REQUIRED, "sampled center loses rank-one external isolation"
    else:
        status, reason = PLAQUETTE_BOUNDARY_ONLY, "sampled spokes do not qualify the interior sample"
    return PlaquetteInteriorQualificationResult(
        status=status,
        boundary_status=boundary.status,
        center=center,
        spoke_results=spokes,
        thresholds=boundary.thresholds,
        geometry_tolerance=geometry_tolerance,
        evidence=(reason, "authorization is limited to sampled vertex-to-center spokes"),
        provenance=provenance or {},
    )


qualify_plaquette_interior_boundary = qualify_plaquette_interior


qualify_plaquette = qualify_plaquette_boundary
