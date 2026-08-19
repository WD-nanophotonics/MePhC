"""E7A bridge from live MPB snapshots into E4D path qualification.

This module selects caller-specified local solver-order entries from already
adapted MPB snapshots, constructs solver-neutral EigenSubspace vertices, and
delegates all edge qualification to E4D. It does not assign identities or
compute observables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

import numpy as np

from .eigenspace import EigenSubspace
from .mpb_spectral import MPBHEnvelopeSnapshot
from .path_domain import (
    PATH_SINGLE_BAND_QUALIFIED,
    PATH_SUBSPACE_QUALIFIED,
    PathQualificationResult,
    qualify_ordered_path,
)
from .spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds


MPB_PATH_AUTHORIZATION_SCOPE = "mpb_path_domain_only"


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _safe(value: Any, *, path: str = "value") -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if not np.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe(item, path=f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} must be JSON-safe")


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-safe evidence kept by a frozen result."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _selection(value: Any, *, index: int) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"selection {index} must be a non-empty sequence of local solver indices")
    values = tuple(value)
    if not values:
        raise ValueError(f"selection {index} must not be empty")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in values):
        raise ValueError(f"selection {index} must contain non-negative integer indices")
    if len(set(values)) != len(values):
        raise ValueError(f"selection {index} must not contain duplicate indices")
    return values


@dataclass(frozen=True)
class MPBQualifiedPathInput:
    """Immutable source snapshots and local solver-order selections."""

    snapshots: tuple[MPBHEnvelopeSnapshot, ...]
    selected_solver_indices: tuple[tuple[int, ...], ...]
    thresholds: SubspaceQualificationThresholds
    closed: bool
    require_live: bool = True

    def __post_init__(self) -> None:
        snapshots = tuple(self.snapshots)
        selections = tuple(_selection(value, index=index) for index, value in enumerate(self.selected_solver_indices))
        if len(snapshots) < 2:
            raise ValueError("path requires at least two MPB snapshots")
        if len(selections) != len(snapshots):
            raise ValueError("one local selection is required per snapshot")
        if not isinstance(self.thresholds, SubspaceQualificationThresholds):
            raise TypeError("thresholds must be SubspaceQualificationThresholds")
        if type(self.closed) is not bool or type(self.require_live) is not bool:
            raise TypeError("closed and require_live must be bool")
        if any(not isinstance(snapshot, MPBHEnvelopeSnapshot) for snapshot in snapshots):
            raise TypeError("snapshots must contain MPBHEnvelopeSnapshot values")
        object.__setattr__(self, "snapshots", snapshots)
        object.__setattr__(self, "selected_solver_indices", selections)

    @property
    def rank(self) -> int:
        return len(self.selected_solver_indices[0])


@dataclass(frozen=True)
class MPBQualifiedPathResult:
    """Immutable E7A source evidence plus the exact delegated E4D result."""

    input: MPBQualifiedPathInput
    vertices: tuple[EigenSubspace, ...]
    external_contexts: tuple[ExternalIsolationContext | None, ...]
    path_result: PathQualificationResult
    authorization_scope: str = MPB_PATH_AUTHORIZATION_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.input, MPBQualifiedPathInput):
            raise TypeError("input must be MPBQualifiedPathInput")
        vertices = tuple(self.vertices)
        contexts = tuple(self.external_contexts)
        if len(vertices) != len(self.input.snapshots):
            raise ValueError("vertices must preserve one entry per source snapshot")
        expected_edges = len(vertices) if self.input.closed else len(vertices) - 1
        if len(contexts) != expected_edges:
            raise ValueError("external_contexts must preserve E4D edge order")
        if not isinstance(self.path_result, PathQualificationResult):
            raise TypeError("path_result must be PathQualificationResult")
        if self.authorization_scope != MPB_PATH_AUTHORIZATION_SCOPE:
            raise ValueError("invalid E7A authorization scope")
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "external_contexts", contexts)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze(_safe(dict(self.provenance), path="provenance")))

    @property
    def status(self) -> str:
        return self.path_result.status

    @property
    def is_qualified(self) -> bool:
        return self.path_result.status in {PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED}

    @property
    def is_live_qualified(self) -> bool:
        return self.is_qualified and all(
            snapshot.provenance.get("live_mpb_extraction_validated") is True
            for snapshot in self.input.snapshots
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "is_qualified": self.is_qualified,
            "is_live_qualified": self.is_live_qualified,
            "authorization_scope": self.authorization_scope,
            "closed": self.input.closed,
            "require_live": self.input.require_live,
            "selected_solver_indices": [list(item) for item in self.input.selected_solver_indices],
            "thresholds": self.input.thresholds.to_dict(),
            "source_snapshots": [snapshot.to_dict() for snapshot in self.input.snapshots],
            "vertices": [
                {
                    "k_point": list(vertex.k_point),
                    "rank": vertex.dimension,
                    "ambient_dimension": vertex.ambient_dimension,
                    "solver_indices": list(vertex.solver_indices),
                    "eigenvalues": list(vertex.eigenvalues),
                }
                for vertex in self.vertices
            ],
            "external_contexts": [None if item is None else item.to_dict() for item in self.external_contexts],
            "path_result": self.path_result.to_dict(),
            "evidence": list(self.evidence),
            "provenance": _thaw(dict(self.provenance)),
        }


def _validate_snapshots(path_input: MPBQualifiedPathInput) -> tuple[str, tuple[int, int], int, int]:
    snapshots = path_input.snapshots
    representation = snapshots[0].provenance.get("representation")
    spatial_shape = snapshots[0].spatial_shape
    ambient_dimension = snapshots[0][0].dimension
    coordinate_dimension = len(snapshots[0].k_point)
    if not isinstance(representation, str) or not representation:
        raise ValueError("snapshots must expose one representation identifier")
    for index, snapshot in enumerate(snapshots):
        if snapshot.provenance.get("representation") != representation:
            raise ValueError(f"snapshot {index} has a mismatched representation identifier")
        if snapshot.spatial_shape != spatial_shape or snapshot.component_count != 3:
            raise ValueError(f"snapshot {index} has mismatched spatial representation")
        if snapshot[0].dimension != ambient_dimension:
            raise ValueError(f"snapshot {index} has mismatched ambient vector dimension")
        if len(snapshot.k_point) != coordinate_dimension:
            raise ValueError(f"snapshot {index} has mismatched public k-point dimension")
        if path_input.require_live and snapshot.provenance.get("live_mpb_extraction_validated") is not True:
            raise ValueError(f"snapshot {index} is not live-extraction validated")
        if not snapshot.is_orthogonality_qualified:
            raise ValueError(f"snapshot {index} is not orthogonality-qualified")
    return representation, spatial_shape, ambient_dimension, coordinate_dimension


def _build_vertex(snapshot: MPBHEnvelopeSnapshot, selection: tuple[int, ...], *, vertex_index: int) -> EigenSubspace:
    if any(index >= snapshot.bands for index in selection):
        raise ValueError(f"selection {vertex_index} contains an out-of-range local solver index")
    states = [snapshot[index] for index in selection]
    frame = np.column_stack([state.vector for state in states])
    return EigenSubspace(
        k_point=snapshot.k_point,
        frame=frame,
        eigenvalues=tuple(state.eigenvalue for state in states),
        solver_indices=tuple(state.solver_index for state in states),
        metadata={
            "source": "E7A MPB qualified path bridge",
            "snapshot_representation": snapshot.provenance.get("representation"),
            "local_solver_indices": list(selection),
            "solver_index_semantics": "ordering metadata only",
            "snapshot_index": vertex_index,
        },
    )


def _build_contexts(
    snapshots: tuple[MPBHEnvelopeSnapshot, ...],
    selections: tuple[tuple[int, ...], ...],
    *,
    closed: bool,
) -> tuple[ExternalIsolationContext, ...]:
    expected = len(snapshots) if closed else len(snapshots) - 1
    contexts = []
    for index in range(expected):
        right = (index + 1) % len(snapshots) if closed else index + 1
        left_excluded = tuple(
            float(snapshots[index].frequencies[local])
            for local in range(snapshots[index].bands)
            if local not in selections[index]
        )
        right_excluded = tuple(
            float(snapshots[right].frequencies[local])
            for local in range(snapshots[right].bands)
            if local not in selections[right]
        )
        contexts.append(
            ExternalIsolationContext(
                left_excluded_eigenvalues=left_excluded,
                right_excluded_eigenvalues=right_excluded,
                provenance={
                    "source": "E7A live MPB excluded-spectrum context",
                    "left_snapshot_index": index,
                    "right_snapshot_index": right,
                    "left_snapshot_provenance": _thaw(snapshots[index].provenance),
                    "right_snapshot_provenance": _thaw(snapshots[right].provenance),
                    "selection_semantics": "local solver ordering only",
                },
            )
        )
    return tuple(contexts)


def qualify_mpb_spectral_path(
    snapshots: Sequence[MPBHEnvelopeSnapshot],
    selected_solver_indices: Sequence[Sequence[int]],
    *,
    thresholds: SubspaceQualificationThresholds,
    closed: bool,
    require_live: bool = True,
) -> MPBQualifiedPathResult:
    path_input = MPBQualifiedPathInput(
        snapshots=tuple(snapshots),
        selected_solver_indices=tuple(tuple(value) for value in selected_solver_indices),
        thresholds=thresholds,
        closed=closed,
        require_live=require_live,
    )
    representation, spatial_shape, ambient_dimension, coordinate_dimension = _validate_snapshots(path_input)
    if any(len(selection) != path_input.rank for selection in path_input.selected_solver_indices):
        raise ValueError("selected rank must remain constant across all path vertices")
    vertices = tuple(
        _build_vertex(snapshot, selection, vertex_index=index)
        for index, (snapshot, selection) in enumerate(zip(path_input.snapshots, path_input.selected_solver_indices))
    )
    contexts = _build_contexts(path_input.snapshots, path_input.selected_solver_indices, closed=closed)
    path_result = qualify_ordered_path(
        vertices,
        contexts,
        thresholds=thresholds,
        closed=closed,
        provenance={
            "source": "E7A MPB qualified path bridge",
            "representation": representation,
            "spatial_shape": list(spatial_shape),
            "ambient_dimension": ambient_dimension,
            "public_k_point_dimension": coordinate_dimension,
            "live_required": require_live,
            "local_selection_semantics": "solver ordering metadata only",
        },
    )
    return MPBQualifiedPathResult(
        input=path_input,
        vertices=vertices,
        external_contexts=contexts,
        path_result=path_result,
        evidence=(
            "selected RawEigenstate values were converted directly to EigenSubspace vertices",
            "excluded eigenvalues came from the same endpoint snapshots",
            "all edge qualification was delegated to E4D",
            "authorization is limited to MPB path-domain qualification",
        ),
        provenance={
            "representation": representation,
            "live_mpb_extraction_validated": all(
                snapshot.provenance.get("live_mpb_extraction_validated") is True
                for snapshot in path_input.snapshots
            ),
            "selection_semantics": "local solver ordering metadata only",
        },
    )


qualify_mpb_path = qualify_mpb_spectral_path

__all__ = [
    "MPB_PATH_AUTHORIZATION_SCOPE",
    "MPBQualifiedPathInput",
    "MPBQualifiedPathResult",
    "qualify_mpb_spectral_path",
    "qualify_mpb_path",
]
