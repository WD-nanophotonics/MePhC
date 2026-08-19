"""Solver-neutral E3A spectral association and local subspace qualification.

E3A deliberately separates two kinds of evidence:

* raw rank-1 association, which uses solver-index provenance and the complete
  raw overlap/probability matrices but never invents a physical branch label;
* local rank-N qualification, which uses basis-independent E2 subspace overlap
  diagnostics, cross-k projector distance, and explicit external isolation
  context before exposing an E2 polar transport link.

No solver, Meep, MPB, branch-tracking, or global disentanglement logic lives
in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from .eigenspace import EigenSubspace, RawEigenstate
from .subspace_transport import (
    DEFAULT_VALIDATION_TOLERANCE,
    SubspaceOverlap,
    SubspaceTransportError,
    SubspaceTransportLink,
    parallel_transport_link,
    subspace_overlap,
)


CLEAR = "CLEAR"
AMBIGUOUS = "AMBIGUOUS"
INCOMPLETE = "INCOMPLETE"

SINGLE_BAND_QUALIFIED = "SINGLE_BAND_QUALIFIED"
SUBSPACE_QUALIFIED = "SUBSPACE_QUALIFIED"
SUBSPACE_NOT_ISOLATED = "SUBSPACE_NOT_ISOLATED"
SUBSPACE_CONTINUITY_UNQUALIFIED = "SUBSPACE_CONTINUITY_UNQUALIFIED"
NUMERICALLY_INCOMPLETE = "NUMERICALLY_INCOMPLETE"
SUBSPACE_REQUIRES_ENLARGEMENT = "SUBSPACE_REQUIRES_ENLARGEMENT"
DISENTANGLEMENT_REQUIRED = "DISENTANGLEMENT_REQUIRED"
RANK_QUALIFIED = SUBSPACE_QUALIFIED


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonnegative(value: Any, *, name: str) -> float:
    result = _finite(value, name=name)
    if result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _positive(value: Any, *, name: str) -> float:
    result = _finite(value, name=name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _readonly_array(value: Any, *, name: str, dtype: Any, ndim: int) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if array.ndim != ndim:
        raise ValueError(f"{name} must have exactly {ndim} dimensions")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    result = np.array(array, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _json_value(value: Any, *, path: str = "value") -> Any:
    if value is None or type(value) is bool or type(value) is str or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item, path=f"{path}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} must contain JSON-safe values")


def _complex_pairs(matrix: np.ndarray) -> list[list[list[float]]]:
    return [
        [[float(value.real), float(value.imag)] for value in row]
        for row in matrix
    ]


def _validate_threshold_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType(_json_value(dict(value), path="provenance"))


@dataclass(frozen=True)
class RawAssociationThresholds:
    """Caller-supplied evidence thresholds for raw-state association."""

    probability_threshold: float
    margin_threshold: float
    assignment_margin_threshold: float
    validation_tolerance: float = DEFAULT_VALIDATION_TOLERANCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "probability_threshold", _nonnegative(self.probability_threshold, name="probability_threshold"))
        object.__setattr__(self, "margin_threshold", _nonnegative(self.margin_threshold, name="margin_threshold"))
        object.__setattr__(self, "assignment_margin_threshold", _nonnegative(self.assignment_margin_threshold, name="assignment_margin_threshold"))
        object.__setattr__(self, "validation_tolerance", _nonnegative(self.validation_tolerance, name="validation_tolerance"))

    @property
    def min_matched_probability(self) -> float:
        return self.probability_threshold

    @property
    def min_pair_margin(self) -> float:
        return self.margin_threshold

    @property
    def min_assignment_margin(self) -> float:
        return self.assignment_margin_threshold

    def to_dict(self) -> dict[str, float]:
        return {
            "probability_threshold": self.probability_threshold,
            "margin_threshold": self.margin_threshold,
            "assignment_margin_threshold": self.assignment_margin_threshold,
            "validation_tolerance": self.validation_tolerance,
        }


@dataclass(frozen=True)
class RawStateAssociation:
    """Complete rank-1 association evidence between two raw candidate sets."""

    status: str
    left_k_point: tuple[float, ...]
    right_k_point: tuple[float, ...]
    left_solver_indices: tuple[int, ...]
    right_solver_indices: tuple[int, ...]
    overlap_matrix: np.ndarray
    probability_matrix: np.ndarray
    assignment: tuple[tuple[int, int], ...]
    matched_probabilities: tuple[float, ...]
    row_margins: tuple[float | None, ...]
    column_margins: tuple[float | None, ...]
    best_assignment_score: float
    second_best_assignment_score: float | None
    global_assignment_margin: float | None
    thresholds: RawAssociationThresholds
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {CLEAR, AMBIGUOUS, INCOMPLETE}:
            raise ValueError(f"invalid raw association status: {self.status}")
        overlap = _readonly_array(self.overlap_matrix, name="overlap_matrix", dtype=np.complex128, ndim=2)
        probability = _readonly_array(self.probability_matrix, name="probability_matrix", dtype=float, ndim=2)
        if overlap.shape != probability.shape:
            raise ValueError("overlap_matrix and probability_matrix must have equal shapes")
        if len(self.left_solver_indices) != overlap.shape[0] or len(self.right_solver_indices) != overlap.shape[1]:
            raise ValueError("solver-index provenance does not match matrix shape")
        if len(self.assignment) != min(overlap.shape):
            raise ValueError("assignment must contain one pair per matched row/column")
        if len(self.matched_probabilities) != len(self.assignment):
            raise ValueError("matched_probabilities must match assignment length")
        if len(self.row_margins) != overlap.shape[0] or len(self.column_margins) != overlap.shape[1]:
            raise ValueError("winner margins must match matrix shape")
        if any(not isinstance(item, int) or item < 0 for pair in self.assignment for item in pair):
            raise ValueError("assignment positions must be non-negative integers")
        object.__setattr__(self, "overlap_matrix", overlap)
        object.__setattr__(self, "probability_matrix", probability)
        object.__setattr__(self, "left_k_point", tuple(float(item) for item in self.left_k_point))
        object.__setattr__(self, "right_k_point", tuple(float(item) for item in self.right_k_point))
        object.__setattr__(self, "left_solver_indices", tuple(int(item) for item in self.left_solver_indices))
        object.__setattr__(self, "right_solver_indices", tuple(int(item) for item in self.right_solver_indices))
        object.__setattr__(self, "matched_probabilities", tuple(float(item) for item in self.matched_probabilities))
        object.__setattr__(self, "best_assignment_score", _finite(self.best_assignment_score, name="best_assignment_score"))
        if self.second_best_assignment_score is not None:
            object.__setattr__(self, "second_best_assignment_score", _finite(self.second_best_assignment_score, name="second_best_assignment_score"))
        if self.global_assignment_margin is not None:
            object.__setattr__(self, "global_assignment_margin", _nonnegative(self.global_assignment_margin, name="global_assignment_margin"))
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))

    @property
    def overlap(self) -> np.ndarray:
        return self.overlap_matrix

    @property
    def probabilities(self) -> np.ndarray:
        return self.probability_matrix

    @property
    def matched_by_solver_index(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (self.left_solver_indices[row], self.right_solver_indices[column])
            for row, column in self.assignment
        )

    def to_dict(self, *, include_matrices: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "left_k_point": list(self.left_k_point),
            "right_k_point": list(self.right_k_point),
            "left_solver_indices": list(self.left_solver_indices),
            "right_solver_indices": list(self.right_solver_indices),
            "assignment": [list(pair) for pair in self.assignment],
            "matched_by_solver_index": [list(pair) for pair in self.matched_by_solver_index],
            "matched_probabilities": list(self.matched_probabilities),
            "row_margins": list(self.row_margins),
            "column_margins": list(self.column_margins),
            "best_assignment_score": self.best_assignment_score,
            "second_best_assignment_score": self.second_best_assignment_score,
            "global_assignment_margin": self.global_assignment_margin,
            "thresholds": self.thresholds.to_dict(),
            "evidence": list(self.evidence),
        }
        if include_matrices:
            result["overlap_matrix"] = _complex_pairs(self.overlap_matrix)
            result["probability_matrix"] = self.probability_matrix.tolist()
        return result


def _raw_candidates(states: Iterable[RawEigenstate], *, side: str, tolerance: float) -> tuple[tuple[RawEigenstate, ...], np.ndarray]:
    values = tuple(states)
    if not values:
        raise ValueError(f"{side} candidate set must not be empty")
    if any(not isinstance(item, RawEigenstate) for item in values):
        raise TypeError(f"{side} candidate set must contain RawEigenstate values")
    k_point = values[0].k_point
    if any(item.k_point != k_point for item in values[1:]):
        raise ValueError(f"{side} candidate set must contain exactly one k point")
    indices = [item.solver_index for item in values]
    if len(set(indices)) != len(indices):
        raise ValueError(f"{side} candidate set must have unique solver indices")
    dimension = values[0].dimension
    if any(item.dimension != dimension for item in values):
        raise ValueError(f"{side} candidate set must have equal ambient dimensions")
    vectors = np.column_stack([item.vector for item in values]).astype(np.complex128, copy=False)
    norms = np.linalg.norm(vectors, axis=0)
    if not np.all(np.isfinite(norms)) or not np.allclose(norms, 1.0, atol=tolerance, rtol=0.0):
        raise ValueError(f"{side} candidate vectors must be normalized and finite")
    gram = vectors.conj().T @ vectors
    identity = np.eye(len(values), dtype=np.complex128)
    if not np.allclose(gram, identity, atol=tolerance, rtol=0.0):
        raise ValueError(f"{side} raw candidate frame must be within-k Gram orthonormal")
    return values, vectors


def _margins(matrix: np.ndarray, *, axis: int) -> tuple[float | None, ...]:
    margins: list[float | None] = []
    count = matrix.shape[axis]
    for index in range(count):
        values = np.sort(np.asarray(np.take(matrix, index, axis=axis), dtype=float))[::-1]
        margins.append(None if values.size < 2 else float(values[0] - values[1]))
    return tuple(margins)


def _best_assignment(probability: np.ndarray, *, forbidden: tuple[int, int] | None = None) -> tuple[float, tuple[tuple[int, int], ...]] | None:
    scores = np.array(probability, dtype=float, copy=True)
    if forbidden is not None:
        scores[forbidden] = -np.inf
    try:
        rows, columns = linear_sum_assignment(-scores)
    except ValueError:
        return None
    if any(not math.isfinite(float(scores[row, column])) for row, column in zip(rows, columns)):
        return None
    assignment = tuple((int(row), int(column)) for row, column in zip(rows, columns))
    return float(sum(scores[row, column] for row, column in assignment)), assignment


def associate_raw_states(
    left: Iterable[RawEigenstate],
    right: Iterable[RawEigenstate],
    *,
    thresholds: RawAssociationThresholds,
) -> RawStateAssociation:
    """Associate two raw candidate windows while preserving ambiguity evidence."""
    if not isinstance(thresholds, RawAssociationThresholds):
        raise TypeError("thresholds must be RawAssociationThresholds")
    left_states, left_vectors = _raw_candidates(left, side="left", tolerance=thresholds.validation_tolerance)
    right_states, right_vectors = _raw_candidates(right, side="right", tolerance=thresholds.validation_tolerance)
    if left_vectors.shape[0] != right_vectors.shape[0]:
        raise ValueError("left and right candidate sets must have equal ambient dimensions")
    overlap = np.asarray(left_vectors.conj().T @ right_vectors, dtype=np.complex128)
    probability = np.abs(overlap) ** 2
    best = _best_assignment(probability)
    if best is None:
        raise ValueError("unable to form a finite maximum-weight assignment")
    best_score, assignment = best
    alternatives = [
        candidate
        for pair in assignment
        if (candidate := _best_assignment(probability, forbidden=pair)) is not None
    ]
    second_score = max((candidate[0] for candidate in alternatives), default=None)
    global_margin = None if second_score is None else float(best_score - second_score)
    row_margins = _margins(probability, axis=0)
    column_margins = _margins(probability, axis=1)
    matched = tuple(float(probability[row, column]) for row, column in assignment)
    evidence: list[str] = []
    complete = len(left_states) == len(right_states)
    if not complete:
        evidence.append("rectangular candidate sets cannot establish complete one-to-one evidence")
    if any(value < thresholds.probability_threshold for value in matched):
        evidence.append("a matched probability is below the caller threshold")
    finite_row_margins = [value for value in row_margins if value is not None]
    finite_column_margins = [value for value in column_margins if value is not None]
    if any(value < thresholds.margin_threshold for value in finite_row_margins + finite_column_margins):
        evidence.append("a row or column winner margin is below the caller threshold")
    if global_margin is not None and global_margin < thresholds.assignment_margin_threshold:
        evidence.append("the best and second-best assignment scores are too close")
    clear = (
        complete
        and all(value >= thresholds.probability_threshold for value in matched)
        and all(value >= thresholds.margin_threshold for value in finite_row_margins + finite_column_margins)
        and (global_margin is None or global_margin >= thresholds.assignment_margin_threshold)
    )
    status = CLEAR if clear else (INCOMPLETE if not complete else AMBIGUOUS)
    if not evidence:
        evidence.append("all caller-supplied association thresholds passed")
    return RawStateAssociation(
        status=status,
        left_k_point=left_states[0].k_point,
        right_k_point=right_states[0].k_point,
        left_solver_indices=tuple(item.solver_index for item in left_states),
        right_solver_indices=tuple(item.solver_index for item in right_states),
        overlap_matrix=overlap,
        probability_matrix=probability,
        assignment=assignment,
        matched_probabilities=matched,
        row_margins=row_margins,
        column_margins=column_margins,
        best_assignment_score=best_score,
        second_best_assignment_score=second_score,
        global_assignment_margin=global_margin,
        thresholds=thresholds,
        evidence=tuple(evidence),
    )


associate_raw_eigenstates = associate_raw_states
raw_state_association = associate_raw_states


@dataclass(frozen=True)
class ExternalIsolationContext:
    """Excluded-state context required to establish local isolation."""

    left_excluded_eigenvalues: tuple[float, ...]
    right_excluded_eigenvalues: tuple[float, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        left = tuple(_finite(item, name="left_excluded_eigenvalue") for item in self.left_excluded_eigenvalues)
        right = tuple(_finite(item, name="right_excluded_eigenvalue") for item in self.right_excluded_eigenvalues)
        object.__setattr__(self, "left_excluded_eigenvalues", left)
        object.__setattr__(self, "right_excluded_eigenvalues", right)
        object.__setattr__(self, "provenance", _validate_threshold_mapping(self.provenance))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExternalIsolationContext":
        if not isinstance(value, Mapping):
            raise TypeError("external_context must be a mapping or ExternalIsolationContext")
        left = value.get("left_excluded_eigenvalues", value.get("left"))
        right = value.get("right_excluded_eigenvalues", value.get("right"))
        if left is None or right is None:
            raise ValueError("external_context must provide left and right excluded eigenvalues")
        provenance = value.get("provenance", {})
        return cls(tuple(left), tuple(right), provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_excluded_eigenvalues": list(self.left_excluded_eigenvalues),
            "right_excluded_eigenvalues": list(self.right_excluded_eigenvalues),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class SubspaceQualificationThresholds:
    """Caller-supplied scientific thresholds for local qualification."""

    min_singular_value: float
    max_principal_angle: float
    max_projector_distance: float
    min_external_gap: float
    validation_tolerance: float = DEFAULT_VALIDATION_TOLERANCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_singular_value", _positive(self.min_singular_value, name="min_singular_value"))
        object.__setattr__(self, "max_principal_angle", _nonnegative(self.max_principal_angle, name="max_principal_angle"))
        object.__setattr__(self, "max_projector_distance", _nonnegative(self.max_projector_distance, name="max_projector_distance"))
        object.__setattr__(self, "min_external_gap", _nonnegative(self.min_external_gap, name="min_external_gap"))
        object.__setattr__(self, "validation_tolerance", _nonnegative(self.validation_tolerance, name="validation_tolerance"))

    def to_dict(self) -> dict[str, float]:
        return {
            "min_singular_value": self.min_singular_value,
            "max_principal_angle": self.max_principal_angle,
            "max_projector_distance": self.max_projector_distance,
            "min_external_gap": self.min_external_gap,
            "validation_tolerance": self.validation_tolerance,
        }


@dataclass(frozen=True)
class SubspaceQualificationResult:
    """Evidence and optional authorized E2 link for one local pair."""

    status: str
    left_k_point: tuple[float, ...]
    right_k_point: tuple[float, ...]
    left_dimension: int
    right_dimension: int
    overlap: SubspaceOverlap | None
    cross_k_projector_distance: float | None
    external_gaps: Mapping[str, float | None]
    thresholds: SubspaceQualificationThresholds
    transport_link: SubspaceTransportLink | None = None
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {
            SINGLE_BAND_QUALIFIED,
            SUBSPACE_QUALIFIED,
            SUBSPACE_NOT_ISOLATED,
            SUBSPACE_CONTINUITY_UNQUALIFIED,
            NUMERICALLY_INCOMPLETE,
        }
        if self.status not in allowed:
            raise ValueError(f"invalid local qualification status: {self.status}")
        if self.cross_k_projector_distance is not None:
            object.__setattr__(self, "cross_k_projector_distance", _nonnegative(self.cross_k_projector_distance, name="cross_k_projector_distance"))
        gaps = {
            str(key): None if value is None else _nonnegative(value, name=f"external_gaps.{key}")
            for key, value in self.external_gaps.items()
        }
        object.__setattr__(self, "external_gaps", MappingProxyType(gaps))
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _validate_threshold_mapping(self.provenance))

    @property
    def projector_distance(self) -> float | None:
        return self.cross_k_projector_distance

    @property
    def external_gap(self) -> float | None:
        values = [value for value in self.external_gaps.values() if value is not None]
        return None if not values else min(values)

    @property
    def is_qualified(self) -> bool:
        return self.status in {SINGLE_BAND_QUALIFIED, SUBSPACE_QUALIFIED} and self.transport_link is not None

    def to_dict(self, *, include_matrices: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "left_k_point": list(self.left_k_point),
            "right_k_point": list(self.right_k_point),
            "left_dimension": self.left_dimension,
            "right_dimension": self.right_dimension,
            "cross_k_projector_distance": self.cross_k_projector_distance,
            "projector_distance": self.cross_k_projector_distance,
            "external_gaps": dict(self.external_gaps),
            "thresholds": self.thresholds.to_dict(),
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
            "transport_link": None if self.transport_link is None else self.transport_link.to_dict(include_matrices=include_matrices),
            "overlap": None if self.overlap is None else self.overlap.to_dict(include_matrix=include_matrices),
        }
        return result


def _external_gap(targets: Sequence[float], excluded: Sequence[float]) -> float | None:
    if not targets or not excluded:
        return None
    return float(min(abs(float(external) - float(target)) for external in excluded for target in targets))


def _qualification_incomplete(left: EigenSubspace, right: EigenSubspace, thresholds: SubspaceQualificationThresholds, *, evidence: Sequence[str], overlap: SubspaceOverlap | None = None, distance: float | None = None, gaps: Mapping[str, float | None] | None = None, provenance: Mapping[str, Any] | None = None) -> SubspaceQualificationResult:
    return SubspaceQualificationResult(
        status=NUMERICALLY_INCOMPLETE,
        left_k_point=left.k_point,
        right_k_point=right.k_point,
        left_dimension=left.dimension,
        right_dimension=right.dimension,
        overlap=overlap,
        cross_k_projector_distance=distance,
        external_gaps=gaps or {"left": None, "right": None, "minimum": None},
        thresholds=thresholds,
        evidence=tuple(evidence),
        provenance=provenance or {},
    )


def qualify_local_subspace(
    left: EigenSubspace,
    right: EigenSubspace,
    *,
    thresholds: SubspaceQualificationThresholds,
    external_context: ExternalIsolationContext | Mapping[str, Any] | None = None,
    left_excluded_eigenvalues: Sequence[float] | None = None,
    right_excluded_eigenvalues: Sequence[float] | None = None,
) -> SubspaceQualificationResult:
    """Qualify one local E2 pair and expose a link only after all checks pass."""
    if not isinstance(left, EigenSubspace) or not isinstance(right, EigenSubspace):
        raise TypeError("left and right must be EigenSubspace values")
    if not isinstance(thresholds, SubspaceQualificationThresholds):
        raise TypeError("thresholds must be SubspaceQualificationThresholds")
    try:
        overlap = subspace_overlap(left, right, validation_tolerance=thresholds.validation_tolerance)
    except (ValueError, SubspaceTransportError) as exc:
        return _qualification_incomplete(left, right, thresholds, evidence=(f"overlap validation failed: {exc}",))
    distance = float(np.linalg.norm(left.projector_matrix() - right.projector_matrix(), ord="fro"))
    if not math.isfinite(distance):
        return _qualification_incomplete(left, right, thresholds, evidence=("cross-k projector distance is not finite",), overlap=overlap)
    if external_context is None and (left_excluded_eigenvalues is not None or right_excluded_eigenvalues is not None):
        if left_excluded_eigenvalues is None or right_excluded_eigenvalues is None:
            context = None
        else:
            context = ExternalIsolationContext(tuple(left_excluded_eigenvalues), tuple(right_excluded_eigenvalues))
    elif isinstance(external_context, ExternalIsolationContext):
        context = external_context
    elif isinstance(external_context, Mapping):
        context = ExternalIsolationContext.from_mapping(external_context)
    else:
        context = None
    if context is None:
        return _qualification_incomplete(left, right, thresholds, evidence=("external isolation context is required",), overlap=overlap, distance=distance)
    left_gap = _external_gap(left.eigenvalues, context.left_excluded_eigenvalues)
    right_gap = _external_gap(right.eigenvalues, context.right_excluded_eigenvalues)
    gaps = {"left": left_gap, "right": right_gap, "minimum": None if left_gap is None or right_gap is None else min(left_gap, right_gap)}
    if left_gap is None or right_gap is None:
        return _qualification_incomplete(left, right, thresholds, evidence=("both endpoint external isolation gaps are required",), overlap=overlap, distance=distance, gaps=gaps, provenance=context.provenance)
    continuity_reasons: list[str] = []
    if left.dimension != right.dimension:
        continuity_reasons.append("left and right subspace dimensions differ")
    if overlap.min_singular_value < thresholds.min_singular_value:
        continuity_reasons.append("minimum singular value is below threshold")
    if overlap.max_principal_angle > thresholds.max_principal_angle:
        continuity_reasons.append("maximum principal angle is above threshold")
    if distance > thresholds.max_projector_distance:
        continuity_reasons.append("cross-k projector distance is above threshold")
    if continuity_reasons:
        return SubspaceQualificationResult(
            status=SUBSPACE_CONTINUITY_UNQUALIFIED,
            left_k_point=left.k_point,
            right_k_point=right.k_point,
            left_dimension=left.dimension,
            right_dimension=right.dimension,
            overlap=overlap,
            cross_k_projector_distance=distance,
            external_gaps=gaps,
            thresholds=thresholds,
            evidence=tuple(continuity_reasons),
            provenance=context.provenance,
        )
    minimum_gap = min(left_gap, right_gap)
    if minimum_gap < thresholds.min_external_gap:
        return SubspaceQualificationResult(
            status=SUBSPACE_NOT_ISOLATED,
            left_k_point=left.k_point,
            right_k_point=right.k_point,
            left_dimension=left.dimension,
            right_dimension=right.dimension,
            overlap=overlap,
            cross_k_projector_distance=distance,
            external_gaps=gaps,
            thresholds=thresholds,
            evidence=("external isolation gap is below threshold",),
            provenance=context.provenance,
        )
    try:
        link = parallel_transport_link(
            left,
            right,
            min_singular_value=thresholds.min_singular_value,
            validation_tolerance=thresholds.validation_tolerance,
        )
    except (ValueError, SubspaceTransportError) as exc:
        return SubspaceQualificationResult(
            status=SUBSPACE_CONTINUITY_UNQUALIFIED,
            left_k_point=left.k_point,
            right_k_point=right.k_point,
            left_dimension=left.dimension,
            right_dimension=right.dimension,
            overlap=overlap,
            cross_k_projector_distance=distance,
            external_gaps=gaps,
            thresholds=thresholds,
            evidence=(f"transport link failed closed: {exc}",),
            provenance=context.provenance,
        )
    status = SINGLE_BAND_QUALIFIED if left.dimension == 1 else SUBSPACE_QUALIFIED
    return SubspaceQualificationResult(
        status=status,
        left_k_point=left.k_point,
        right_k_point=right.k_point,
        left_dimension=left.dimension,
        right_dimension=right.dimension,
        overlap=overlap,
        cross_k_projector_distance=distance,
        external_gaps=gaps,
        thresholds=thresholds,
        transport_link=link,
        evidence=("continuity and external isolation thresholds passed",),
        provenance=context.provenance,
    )


qualify_subspace_pair = qualify_local_subspace


@dataclass(frozen=True)
class RankAdaptiveCandidate:
    """One explicit left/right subspace pair at a stated rank."""

    rank: int
    left: EigenSubspace
    right: EigenSubspace
    external_context: ExternalIsolationContext | Mapping[str, Any] | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        if not isinstance(self.left, EigenSubspace) or not isinstance(self.right, EigenSubspace):
            raise TypeError("left and right must be EigenSubspace values")
        if self.left.dimension != self.rank or self.right.dimension != self.rank:
            raise ValueError("candidate rank must equal both subspace dimensions")
        if self.left.ambient_dimension != self.right.ambient_dimension:
            raise ValueError("candidate endpoints must have equal ambient dimensions")
        context = self.external_context
        if isinstance(context, Mapping):
            context = ExternalIsolationContext.from_mapping(context)
        elif context is not None and not isinstance(context, ExternalIsolationContext):
            raise TypeError("external_context must be an ExternalIsolationContext, mapping, or None")
        object.__setattr__(self, "external_context", context)
        object.__setattr__(self, "provenance", _validate_threshold_mapping(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "left_k_point": list(self.left.k_point),
            "right_k_point": list(self.right.k_point),
            "ambient_dimension": self.left.ambient_dimension,
            "left_solver_indices": list(self.left.solver_indices),
            "right_solver_indices": list(self.right.solver_indices),
            "left_eigenvalues": list(self.left.eigenvalues),
            "right_eigenvalues": list(self.right.eigenvalues),
            "external_context": None if self.external_context is None else self.external_context.to_dict(),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class RankAdaptiveAttempt:
    """Immutable E3A evidence for every candidate evaluated at one rank."""

    rank: int
    results: tuple[SubspaceQualificationResult, ...]
    candidate_provenance: tuple[Mapping[str, Any], ...] = ()
    selected_index: int | None = None
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        results = tuple(self.results)
        if not results:
            raise ValueError("an attempt must preserve at least one result")
        if self.selected_index is not None and not 0 <= self.selected_index < len(results):
            raise ValueError("selected_index must identify one result")
        provenance = tuple(_validate_threshold_mapping(item) for item in self.candidate_provenance)
        if provenance and len(provenance) != len(results):
            raise ValueError("candidate_provenance must align with results")
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "candidate_provenance", provenance)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))

    @property
    def selected_result(self) -> SubspaceQualificationResult | None:
        return None if self.selected_index is None else self.results[self.selected_index]

    def to_dict(self, *, include_matrices: bool = False) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "results": [item.to_dict(include_matrices=include_matrices) for item in self.results],
            "candidate_provenance": [dict(item) for item in self.candidate_provenance],
            "selected_index": self.selected_index,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class RankAdaptiveSubspaceResult:
    """Rank-level E3B decision retaining every attempted E3A result."""

    status: str
    initial_rank: int
    attempted_ranks: tuple[int, ...]
    attempts: tuple[RankAdaptiveAttempt, ...]
    recommended_rank: int | None
    candidate_family_complete: bool
    thresholds: SubspaceQualificationThresholds
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    transport_link: SubspaceTransportLink | None = None

    def __post_init__(self) -> None:
        allowed = {SUBSPACE_QUALIFIED, SUBSPACE_REQUIRES_ENLARGEMENT, DISENTANGLEMENT_REQUIRED,
                   NUMERICALLY_INCOMPLETE, SUBSPACE_NOT_ISOLATED, SUBSPACE_CONTINUITY_UNQUALIFIED}
        if self.status not in allowed:
            raise ValueError(f"invalid rank-adaptive status: {self.status}")
        attempts = tuple(self.attempts)
        ranks = tuple(item.rank for item in attempts)
        if not ranks or ranks[0] != self.initial_rank or tuple(self.attempted_ranks) != ranks:
            raise ValueError("attempted_ranks must match ordered attempts")
        if any(a >= b for a, b in zip(ranks, ranks[1:])):
            raise ValueError("attempt ranks must be strictly increasing")
        if not isinstance(self.candidate_family_complete, bool):
            raise TypeError("candidate_family_complete must be bool")
        if self.recommended_rank is not None and self.recommended_rank not in ranks:
            raise ValueError("recommended_rank must be one of the attempted ranks")
        if self.status == DISENTANGLEMENT_REQUIRED and self.transport_link is not None:
            raise ValueError("disentanglement-required results cannot expose transport")
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(self, "attempted_ranks", ranks)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _validate_threshold_mapping(self.provenance))

    @property
    def rank_evidence(self) -> tuple[RankAdaptiveAttempt, ...]:
        return self.attempts

    @property
    def per_rank_evidence(self) -> tuple[RankAdaptiveAttempt, ...]:
        return self.attempts

    @property
    def rank_results(self) -> Mapping[int, tuple[SubspaceQualificationResult, ...]]:
        return MappingProxyType({item.rank: item.results for item in self.attempts})

    @property
    def selected_result(self) -> SubspaceQualificationResult | None:
        if self.recommended_rank is None:
            return None
        for attempt in self.attempts:
            if attempt.rank == self.recommended_rank:
                return attempt.selected_result
        return None

    def to_dict(self, *, include_matrices: bool = False) -> dict[str, Any]:
        return {
            "status": self.status,
            "initial_rank": self.initial_rank,
            "attempted_ranks": list(self.attempted_ranks),
            "attempts": [item.to_dict(include_matrices=include_matrices) for item in self.attempts],
            "recommended_rank": self.recommended_rank,
            "candidate_family_complete": self.candidate_family_complete,
            "thresholds": self.thresholds.to_dict(),
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
            "transport_link": None if self.transport_link is None else self.transport_link.to_dict(include_matrices=include_matrices),
        }


RankAdaptiveSubspaceCandidate = RankAdaptiveCandidate
RankAdaptiveResult = RankAdaptiveSubspaceResult


def _rank_candidate(value: Any) -> RankAdaptiveCandidate:
    if isinstance(value, RankAdaptiveCandidate):
        return value
    if isinstance(value, Mapping):
        return RankAdaptiveCandidate(value["rank"], value["left"], value["right"],
                                     value.get("external_context"), value.get("provenance", {}))
    if isinstance(value, (tuple, list)) and len(value) == 3 and isinstance(value[0], int):
        return RankAdaptiveCandidate(value[0], value[1], value[2])
    raise TypeError("candidate must be RankAdaptiveCandidate, mapping, or (rank, left, right)")


def _rank_groups(candidates: Iterable[Any]) -> tuple[tuple[RankAdaptiveCandidate, ...], ...]:
    values = tuple(candidates)
    if not values:
        raise ValueError("at least one candidate is required")
    groups: list[list[RankAdaptiveCandidate]] = []
    for value in values:
        is_one = isinstance(value, (RankAdaptiveCandidate, Mapping)) or (
            isinstance(value, (tuple, list)) and len(value) == 3 and isinstance(value[0], int)
        )
        group = [_rank_candidate(value)] if is_one else [_rank_candidate(item) for item in value]
        if not group:
            raise ValueError("candidate groups cannot be empty")
        rank = group[0].rank
        if any(item.rank != rank for item in group):
            raise ValueError("a candidate group must contain one rank")
        if groups and groups[-1][0].rank == rank:
            groups[-1].extend(group)
        else:
            if groups and rank <= groups[-1][0].rank:
                raise ValueError("candidate ranks must be strictly increasing")
            groups.append(group)
    return tuple(tuple(group) for group in groups)


def _rank_nested(smaller: EigenSubspace, larger: EigenSubspace, tolerance: float) -> bool:
    if smaller.ambient_dimension != larger.ambient_dimension or smaller.dimension >= larger.dimension:
        return False
    identity = np.eye(larger.ambient_dimension, dtype=np.complex128)
    residual = np.linalg.norm((identity - larger.projector_matrix()) @ smaller.frame, ord="fro")
    return bool(math.isfinite(float(residual)) and residual <= tolerance)


def _validate_rank_ladder(groups: Sequence[Sequence[RankAdaptiveCandidate]], tolerance: float) -> None:
    first = groups[0][0]
    for group in groups:
        for candidate in group:
            if candidate.left.k_point != first.left.k_point or candidate.right.k_point != first.right.k_point:
                raise ValueError("all candidates must share identical endpoints")
            if candidate.left.ambient_dimension != first.left.ambient_dimension:
                raise ValueError("all candidates must share one ambient dimension")
    for previous, current in zip(groups, groups[1:]):
        for low in previous:
            for high in current:
                if not _rank_nested(low.left, high.left, tolerance) or not _rank_nested(low.right, high.right, tolerance):
                    raise ValueError("candidate rank ladder is not nested at both endpoints")


def _select_rank_candidate(group, results, policy):
    qualified = [i for i, result in enumerate(results) if result.is_qualified]
    if not qualified:
        return None, False
    if policy is not None:
        choice = policy(tuple(group), tuple(results))
        if isinstance(choice, int) and not isinstance(choice, bool):
            if choice not in qualified:
                raise ValueError("selection_policy chose a non-qualified candidate")
            return choice, False
        if isinstance(choice, RankAdaptiveCandidate):
            for i in qualified:
                if group[i] is choice:
                    return i, False
        raise ValueError("selection_policy must return a qualified index or candidate")
    return (qualified[0], False) if len(qualified) == 1 else (None, True)


def qualify_rank_adaptive_subspace(
    candidates: Iterable[Any],
    *,
    thresholds: SubspaceQualificationThresholds,
    candidate_family_complete: bool,
    external_context: ExternalIsolationContext | Mapping[str, Any] | None = None,
    selection_policy: Callable | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> RankAdaptiveSubspaceResult:
    """Evaluate an explicit nested rank ladder using E3A evidence only."""
    if not isinstance(thresholds, SubspaceQualificationThresholds):
        raise TypeError("thresholds must be SubspaceQualificationThresholds")
    if not isinstance(candidate_family_complete, bool):
        raise TypeError("candidate_family_complete must be bool")
    context = external_context
    if isinstance(context, Mapping):
        context = ExternalIsolationContext.from_mapping(context)
    elif context is not None and not isinstance(context, ExternalIsolationContext):
        raise TypeError("external_context must be an ExternalIsolationContext, mapping, or None")
    groups = _rank_groups(candidates)
    _validate_rank_ladder(groups, thresholds.validation_tolerance)
    attempts: list[RankAdaptiveAttempt] = []
    initial_rank = groups[0][0].rank
    for group in groups:
        results = tuple(qualify_local_subspace(
            item.left, item.right, thresholds=thresholds,
            external_context=item.external_context if item.external_context is not None else context,
        ) for item in group)
        selected, ambiguous = _select_rank_candidate(group, results, selection_policy)
        reason = "qualified candidate selected" if selected is not None else (
            "multiple qualified same-rank candidates require a caller selection policy" if ambiguous else
            "no qualified candidate at this rank")
        attempts.append(RankAdaptiveAttempt(group[0].rank, results,
                                            tuple(item.provenance for item in group),
                                            selected, (reason,)))
        if ambiguous:
            return RankAdaptiveSubspaceResult(
                DISENTANGLEMENT_REQUIRED, initial_rank, tuple(x.rank for x in attempts),
                tuple(attempts), None, candidate_family_complete, thresholds,
                ("multiple equally admissible same-rank candidate manifolds remain unresolved",),
                provenance or {}, None)
        if selected is not None:
            status = SUBSPACE_QUALIFIED if group[0].rank == initial_rank else SUBSPACE_REQUIRES_ENLARGEMENT
            return RankAdaptiveSubspaceResult(
                status, initial_rank, tuple(x.rank for x in attempts), tuple(attempts),
                group[0].rank, candidate_family_complete, thresholds,
                ("initial rank is qualified" if status == SUBSPACE_QUALIFIED else
                 "smallest larger qualified rank selected",), provenance or {},
                results[selected].transport_link)
    statuses = [result.status for attempt in attempts for result in attempt.results]
    if NUMERICALLY_INCOMPLETE in statuses:
        status, reason = NUMERICALLY_INCOMPLETE, "required evidence is numerically incomplete"
    elif SUBSPACE_CONTINUITY_UNQUALIFIED in statuses:
        status, reason = SUBSPACE_CONTINUITY_UNQUALIFIED, "continuity failed closed"
    elif candidate_family_complete and statuses and all(x == SUBSPACE_NOT_ISOLATED for x in statuses):
        status, reason = DISENTANGLEMENT_REQUIRED, "complete supplied family remains externally entangled"
    elif SUBSPACE_NOT_ISOLATED in statuses:
        status, reason = SUBSPACE_NOT_ISOLATED, "no supplied rank establishes external isolation"
    else:
        status, reason = NUMERICALLY_INCOMPLETE, "no supplied rank produced complete qualification evidence"
    return RankAdaptiveSubspaceResult(
        status, initial_rank, tuple(x.rank for x in attempts), tuple(attempts),
        None, candidate_family_complete, thresholds, (reason,), provenance or {}, None)


evaluate_rank_adaptive_subspace = qualify_rank_adaptive_subspace
rank_adaptive_subspace_qualification = qualify_rank_adaptive_subspace


__all__ = [
    "CLEAR",
    "AMBIGUOUS",
    "INCOMPLETE",
    "SINGLE_BAND_QUALIFIED",
    "SUBSPACE_QUALIFIED",
    "SUBSPACE_NOT_ISOLATED",
    "SUBSPACE_CONTINUITY_UNQUALIFIED",
    "NUMERICALLY_INCOMPLETE",
    "SUBSPACE_REQUIRES_ENLARGEMENT",
    "DISENTANGLEMENT_REQUIRED",
    "RANK_QUALIFIED",
    "RankAdaptiveCandidate",
    "RankAdaptiveSubspaceCandidate",
    "RankAdaptiveAttempt",
    "RankAdaptiveSubspaceResult",
    "RankAdaptiveResult",
    "qualify_rank_adaptive_subspace",
    "evaluate_rank_adaptive_subspace",
    "rank_adaptive_subspace_qualification",
    "RawAssociationThresholds",
    "RawStateAssociation",
    "associate_raw_states",
    "associate_raw_eigenstates",
    "raw_state_association",
    "ExternalIsolationContext",
    "SubspaceQualificationThresholds",
    "SubspaceQualificationResult",
    "qualify_local_subspace",
    "qualify_subspace_pair",
]
