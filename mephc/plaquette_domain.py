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


PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED = "PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED"
PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED = "PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED"
PLAQUETTE_REFINEMENT_INCOMPLETE = "PLAQUETTE_REFINEMENT_INCOMPLETE"
PLAQUETTE_REFINEMENT_UNQUALIFIED = "PLAQUETTE_REFINEMENT_UNQUALIFIED"
PLAQUETTE_REFINEMENT_RANK_UNSTABLE = "PLAQUETTE_REFINEMENT_RANK_UNSTABLE"
PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED = "PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED"
IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE = "identity_refinement_only"


def _finite_nonnegative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite real scalar")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


@dataclass(frozen=True)
class PlaquetteRefinementThresholds:
    """Caller-visible final quality and final-pair convergence thresholds."""

    min_singular_value: float
    max_principal_angle: float
    max_projector_distance: float
    max_metric_delta: float
    geometry_tolerance: float = 1e-10

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_singular_value", _finite_nonnegative(self.min_singular_value, "min_singular_value"))
        object.__setattr__(self, "max_principal_angle", _finite_nonnegative(self.max_principal_angle, "max_principal_angle"))
        object.__setattr__(self, "max_projector_distance", _finite_nonnegative(self.max_projector_distance, "max_projector_distance"))
        object.__setattr__(self, "max_metric_delta", _finite_nonnegative(self.max_metric_delta, "max_metric_delta"))
        object.__setattr__(self, "geometry_tolerance", _finite_nonnegative(self.geometry_tolerance, "geometry_tolerance"))

    def to_dict(self) -> dict[str, float]:
        return {
            "min_singular_value": self.min_singular_value,
            "max_principal_angle": self.max_principal_angle,
            "max_projector_distance": self.max_projector_distance,
            "max_metric_delta": self.max_metric_delta,
            "geometry_tolerance": self.geometry_tolerance,
        }


@dataclass(frozen=True)
class PlaquetteRefinementLevel:
    """One explicit E4A/E4B evidence level and its positive step value."""

    boundary: Any
    interior: Any
    step: float
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from .plaquette_domain import PlaquetteBoundaryQualificationResult, PlaquetteInteriorQualificationResult

        if not isinstance(self.boundary, PlaquetteBoundaryQualificationResult):
            raise TypeError("boundary must be a PlaquetteBoundaryQualificationResult")
        if not isinstance(self.interior, PlaquetteInteriorQualificationResult):
            raise TypeError("interior must be a PlaquetteInteriorQualificationResult")
        if isinstance(self.step, bool) or not isinstance(self.step, Real):
            raise TypeError("step must be a positive finite real scalar")
        step = float(self.step)
        if not math.isfinite(step) or step <= 0.0:
            raise ValueError("step must be a positive finite real scalar")
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))


@dataclass(frozen=True)
class PlaquetteRefinementMetrics:
    """Worst-case E3 evidence over one boundary plus sampled-interior level."""

    step: float
    rank: int
    minimum_singular_value: float | None
    maximum_principal_angle: float | None
    maximum_projector_distance: float | None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("minimum_singular_value", "maximum_principal_angle", "maximum_projector_distance"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite_nonnegative(value, name))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "rank": self.rank,
            "minimum_singular_value": self.minimum_singular_value,
            "maximum_principal_angle": self.maximum_principal_angle,
            "maximum_projector_distance": self.maximum_projector_distance,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class PlaquetteRefinementQualificationResult:
    """Immutable refinement evidence with identity-refinement scope only."""

    status: str
    rank: int | None
    levels: tuple[PlaquetteRefinementLevel, ...]
    metrics: tuple[PlaquetteRefinementMetrics, ...]
    thresholds: PlaquetteRefinementThresholds
    authorization_scope: str = IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {
            PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED,
            PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED,
            PLAQUETTE_REFINEMENT_INCOMPLETE,
            PLAQUETTE_REFINEMENT_UNQUALIFIED,
            PLAQUETTE_REFINEMENT_RANK_UNSTABLE,
            PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED,
        }
        if self.status not in allowed:
            raise ValueError(f"invalid refinement status: {self.status}")
        levels = tuple(self.levels)
        metrics = tuple(self.metrics)
        if len(levels) < 2 or len(metrics) != len(levels):
            raise ValueError("refinement results must preserve all levels and metrics")
        if self.rank is not None and self.rank < 1:
            raise ValueError("rank must be positive or None")
        if self.authorization_scope != IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE:
            raise ValueError("E4C authorization scope must be identity_refinement_only")
        object.__setattr__(self, "levels", levels)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))

    @property
    def is_qualified(self) -> bool:
        return self.status in {
            PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED,
            PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED,
        }

    @property
    def authorization_granted(self) -> bool:
        return self.is_qualified

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rank": self.rank,
            "levels": [
                {
                    "step": level.step,
                    "boundary_status": level.boundary.status,
                    "interior_status": level.interior.status,
                    "provenance": dict(level.provenance),
                }
                for level in self.levels
            ],
            "metrics": [metric.to_dict() for metric in self.metrics],
            "thresholds": self.thresholds.to_dict(),
            "authorization_scope": self.authorization_scope,
            "authorization_granted": self.authorization_granted,
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
        }


PlaquetteRefinementResult = PlaquetteRefinementQualificationResult


def _refinement_metrics(level: PlaquetteRefinementLevel) -> PlaquetteRefinementMetrics:
    evidence = tuple(level.boundary.edge_results) + tuple(level.interior.spoke_results)
    if not evidence or any(
        item.overlap is None or item.projector_distance is None or not item.is_qualified
        for item in evidence
    ):
        return PlaquetteRefinementMetrics(level.step, level.boundary.rank, None, None, None, level.provenance)
    return PlaquetteRefinementMetrics(
        step=level.step,
        rank=level.boundary.rank,
        minimum_singular_value=min(item.overlap.min_singular_value for item in evidence),
        maximum_principal_angle=max(item.overlap.max_principal_angle for item in evidence),
        maximum_projector_distance=max(float(item.projector_distance) for item in evidence),
        provenance=level.provenance,
    )


def _validate_refinement_geometry(levels: Sequence[PlaquetteRefinementLevel], tolerance: float) -> None:
    reference = np.asarray(levels[0].interior.center.k_point, dtype=float)
    if reference.size != 2:
        raise ValueError("E4C requires a common two-dimensional center")
    base_points = np.asarray([vertex.k_point for vertex in levels[0].boundary.vertices], dtype=float)
    base_vectors = base_points - reference
    base_norms = np.linalg.norm(base_vectors, axis=1)
    if np.any(base_norms <= tolerance):
        raise ValueError("refinement corners must not coincide with the center")
    base_directions = base_vectors / base_norms[:, None]
    base_step = levels[0].step
    for level in levels:
        center = np.asarray(level.interior.center.k_point, dtype=float)
        points = np.asarray([vertex.k_point for vertex in level.boundary.vertices], dtype=float)
        if center.size != 2 or np.linalg.norm(center - reference) > tolerance:
            raise ValueError("refinement levels must share one center")
        vectors = points - reference
        norms = np.linalg.norm(vectors, axis=1)
        if np.any(norms <= tolerance):
            raise ValueError("refinement corners must not coincide with the center")
        directions = vectors / norms[:, None]
        if float(np.max(np.linalg.norm(directions - base_directions, axis=1))) > tolerance:
            raise ValueError("refinement geometry is not homothetic about the common center")
        expected = level.step / base_step
        actual = norms / base_norms
        if float(np.max(np.abs(actual - expected))) > tolerance:
            raise ValueError("corner displacement does not match declared refinement step")


def qualify_plaquette_refinement(
    levels: Sequence[PlaquetteRefinementLevel],
    *,
    thresholds: PlaquetteRefinementThresholds,
    provenance: Mapping[str, Any] | None = None,
) -> PlaquetteRefinementQualificationResult:
    """Qualify identity refinement from explicit E4A/E4B evidence levels."""
    if not isinstance(thresholds, PlaquetteRefinementThresholds):
        raise TypeError("thresholds must be PlaquetteRefinementThresholds")
    if isinstance(levels, (str, bytes)) or not isinstance(levels, Sequence) or len(levels) < 2:
        raise ValueError("E4C requires at least two ordered refinement levels")
    normalized = tuple(levels)
    if any(not isinstance(level, PlaquetteRefinementLevel) for level in normalized):
        raise TypeError("levels must contain PlaquetteRefinementLevel values")
    if any(left.step <= right.step for left, right in zip(normalized, normalized[1:])):
        raise ValueError("refinement step values must be strictly decreasing")
    first_boundary = normalized[0].boundary
    base_e3_thresholds = first_boundary.thresholds.to_dict()
    for level in normalized:
        if level.boundary.thresholds.to_dict() != base_e3_thresholds or level.interior.thresholds.to_dict() != base_e3_thresholds:
            raise ValueError("E4A and E4B thresholds must remain compatible across levels")
    _validate_refinement_geometry(normalized, thresholds.geometry_tolerance)
    ranks = tuple(level.boundary.rank for level in normalized)
    ambient = tuple(level.boundary.vertices[0].ambient_dimension for level in normalized)
    if any(level.interior.center.dimension != ranks[0] or level.interior.center.ambient_dimension != ambient[0] for level in normalized):
        return PlaquetteRefinementQualificationResult(
            PLAQUETTE_REFINEMENT_RANK_UNSTABLE, None, normalized,
            tuple(_refinement_metrics(level) for level in normalized), thresholds,
            evidence=("boundary and sampled-interior rank or ambient dimension is inconsistent",),
            provenance=provenance or {},
        )
    if any(rank != ranks[0] or dimension != ambient[0] for rank, dimension in zip(ranks, ambient)):
        return PlaquetteRefinementQualificationResult(
            PLAQUETTE_REFINEMENT_RANK_UNSTABLE, None, normalized,
            tuple(_refinement_metrics(level) for level in normalized), thresholds,
            evidence=("refinement rank or ambient dimension changes across levels",),
            provenance=provenance or {},
        )
    metrics = tuple(_refinement_metrics(level) for level in normalized)
    if any(level.boundary.status == PLAQUETTE_BOUNDARY_INCOMPLETE or level.interior.status == PLAQUETTE_INTERIOR_INCOMPLETE for level in normalized):
        status, reason = PLAQUETTE_REFINEMENT_INCOMPLETE, "a required refinement level is incomplete"
    elif any(not level.boundary.is_qualified or not level.interior.is_qualified for level in normalized):
        status = (
            PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED
            if any(level.interior.status == PLAQUETTE_SUBSPACE_REQUIRED for level in normalized)
            else PLAQUETTE_REFINEMENT_UNQUALIFIED
        )
        reason = "a required boundary or sampled-interior level is not qualified"
    elif any(metric.minimum_singular_value is None for metric in metrics):
        status, reason = PLAQUETTE_REFINEMENT_INCOMPLETE, "a level lacks required E3 metric evidence"
    else:
        final = metrics[-1]
        previous = metrics[-2]
        quality_ok = (
            final.minimum_singular_value >= thresholds.min_singular_value
            and final.maximum_principal_angle <= thresholds.max_principal_angle
            and final.maximum_projector_distance <= thresholds.max_projector_distance
        )
        deltas = (
            abs(final.minimum_singular_value - previous.minimum_singular_value),
            abs(final.maximum_principal_angle - previous.maximum_principal_angle),
            abs(final.maximum_projector_distance - previous.maximum_projector_distance),
        )
        stable = all(delta <= thresholds.max_metric_delta for delta in deltas)
        if not quality_ok or not stable:
            status, reason = PLAQUETTE_REFINEMENT_UNQUALIFIED, "final identity quality or final-pair stability thresholds failed"
        else:
            status = (
                PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED
                if ranks[0] == 1
                else PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED
            )
            reason = "final identity quality and final-pair stability thresholds passed"
    return PlaquetteRefinementQualificationResult(
        status=status,
        rank=ranks[0] if all(rank == ranks[0] for rank in ranks) else None,
        levels=normalized,
        metrics=metrics,
        thresholds=thresholds,
        evidence=(reason, "authorization is limited to identity refinement evidence"),
        provenance=provenance or {},
    )


qualify_plaquette_identity_refinement = qualify_plaquette_refinement


qualify_plaquette = qualify_plaquette_boundary
