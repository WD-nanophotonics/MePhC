from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from .path_domain import (
    PATH_INCOMPLETE,
    PATH_SINGLE_BAND_QUALIFIED,
    PATH_SUBSPACE_QUALIFIED,
    PATH_SUBSPACE_REQUIRED,
    PATH_UNQUALIFIED,
    PathQualificationResult,
)
from .subspace_transport import SubspaceTransportLink

WILSON_LINE_QUALIFIED = "WILSON_LINE_QUALIFIED"
WILSON_LOOP_QUALIFIED = "WILSON_LOOP_QUALIFIED"
WILSON_INPUT_INCOMPLETE = "WILSON_INPUT_INCOMPLETE"
WILSON_INPUT_UNQUALIFIED = "WILSON_INPUT_UNQUALIFIED"
WILSON_TRANSPORT_AUTHORIZATION_SCOPE = "wilson_transport_only"

_QUALIFIED = {PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED}
_ALLOWED = {
    WILSON_LINE_QUALIFIED,
    WILSON_LOOP_QUALIFIED,
    WILSON_INPUT_INCOMPLETE,
    WILSON_INPUT_UNQUALIFIED,
}


def _safe(value: Any) -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("provenance contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    raise ValueError("value must be JSON-safe")


def _freeze(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType({} if value is None else _safe(dict(value)))


def _matrix(value: Any, rank: int) -> np.ndarray:
    result = np.asarray(value, dtype=np.complex128)
    if result.shape != (rank, rank) or not np.all(np.isfinite(result)):
        raise ValueError("product must be a finite square matrix of the path rank")
    result = np.array(result, copy=True)
    result.setflags(write=False)
    return result


def _vector(value: Any, dtype: Any, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=dtype)
    if result.ndim != 1 or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite vector")
    result = np.array(result, copy=True)
    result.setflags(write=False)
    return result


def _scalar(value: complex | None) -> list[float] | None:
    if value is None:
        return None
    value = complex(value)
    if not math.isfinite(value.real) or not math.isfinite(value.imag):
        raise ValueError("complex scalar must be finite")
    return [float(value.real), float(value.imag)]


def _pairs(value: np.ndarray | None) -> list[list[list[float]]] | None:
    if value is None:
        return None
    return [[[float(z.real), float(z.imag)] for z in row] for row in value]


def _vector_pairs(value: np.ndarray | None) -> list[list[float]] | None:
    if value is None:
        return None
    return [[float(z.real), float(z.imag)] for z in value]


@dataclass(frozen=True)
class WilsonTransportResult:
    status: str
    closed: bool
    rank: int
    product: np.ndarray | None
    edge_links: tuple[SubspaceTransportLink, ...]
    unitarity_residual: float | None = None
    eigenvalues: np.ndarray | None = None
    eigenphases: np.ndarray | None = None
    trace: complex | None = None
    determinant: complex | None = None
    determinant_phase: float | None = None
    authorization_scope: str = WILSON_TRANSPORT_AUTHORIZATION_SCOPE
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED:
            raise ValueError(f"invalid Wilson transport status: {self.status}")
        if not isinstance(self.closed, bool):
            raise TypeError("closed must be bool")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        links = tuple(self.edge_links)
        if any(not isinstance(link, SubspaceTransportLink) for link in links):
            raise TypeError("edge_links must contain SubspaceTransportLink values")
        qualified = self.status in {WILSON_LINE_QUALIFIED, WILSON_LOOP_QUALIFIED}
        product = None if self.product is None else _matrix(self.product, self.rank)
        if qualified != (product is not None):
            raise ValueError("qualified results must expose exactly one product")
        if self.closed and self.status == WILSON_LINE_QUALIFIED:
            raise ValueError("closed results cannot have line status")
        if not self.closed and self.status == WILSON_LOOP_QUALIFIED:
            raise ValueError("open results cannot have loop status")
        loop_values = (self.eigenvalues, self.eigenphases, self.trace, self.determinant, self.determinant_phase)
        if not self.closed and any(value is not None for value in loop_values):
            raise ValueError("open Wilson lines must not expose loop invariants")
        eigenvalues = None if self.eigenvalues is None else _vector(self.eigenvalues, np.complex128, "eigenvalues")
        eigenphases = None if self.eigenphases is None else _vector(self.eigenphases, float, "eigenphases")
        if eigenvalues is not None and eigenvalues.size != self.rank:
            raise ValueError("eigenvalues must contain one value per rank")
        if eigenphases is not None and eigenphases.size != self.rank:
            raise ValueError("eigenphases must contain one value per rank")
        if eigenphases is not None and np.any(np.abs(eigenphases) > math.pi + 1e-14):
            raise ValueError("eigenphases must use the principal branch")
        residual = None if self.unitarity_residual is None else float(self.unitarity_residual)
        if residual is not None and (not math.isfinite(residual) or residual < 0):
            raise ValueError("unitarity_residual must be finite and non-negative")
        phase = None if self.determinant_phase is None else float(self.determinant_phase)
        if phase is not None and (not math.isfinite(phase) or abs(phase) > math.pi + 1e-14):
            raise ValueError("determinant_phase must use the principal branch")
        if self.authorization_scope != WILSON_TRANSPORT_AUTHORIZATION_SCOPE:
            raise ValueError("authorization scope must be wilson_transport_only")
        object.__setattr__(self, "edge_links", links)
        object.__setattr__(self, "product", product)
        object.__setattr__(self, "eigenvalues", eigenvalues)
        object.__setattr__(self, "eigenphases", eigenphases)
        object.__setattr__(self, "unitarity_residual", residual)
        object.__setattr__(self, "determinant_phase", phase)
        object.__setattr__(self, "evidence", tuple(str(item) for item in self.evidence))
        object.__setattr__(self, "provenance", _freeze(self.provenance))

    @property
    def matrix(self) -> np.ndarray | None:
        return self.product

    @property
    def wilson_matrix(self) -> np.ndarray | None:
        return self.product

    @property
    def transport_product(self) -> np.ndarray | None:
        return self.product

    @property
    def is_qualified(self) -> bool:
        return self.status in {WILSON_LINE_QUALIFIED, WILSON_LOOP_QUALIFIED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "closed": self.closed,
            "rank": self.rank,
            "product": _pairs(self.product),
            "edge_links": [link.to_dict(include_matrices=False) for link in self.edge_links],
            "unitarity_residual": self.unitarity_residual,
            "eigenvalues": _vector_pairs(self.eigenvalues),
            "eigenphases": None if self.eigenphases is None else [float(x) for x in self.eigenphases],
            "trace": _scalar(self.trace),
            "determinant": _scalar(self.determinant),
            "determinant_phase": self.determinant_phase,
            "authorization_scope": self.authorization_scope,
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
        }


def _failed(path: PathQualificationResult, status: str, reason: str, links=()):
    return WilsonTransportResult(
        status=status,
        closed=path.closed,
        rank=path.vertices[0].dimension,
        product=None,
        edge_links=tuple(links),
        evidence=(reason, "no transport product was exposed"),
        provenance=path.provenance,
    )


def compose_wilson_transport(path_result: PathQualificationResult) -> WilsonTransportResult:
    """Compose preserved E2 links as U_01 @ U_12 @ ... in path order."""

    if not isinstance(path_result, PathQualificationResult):
        raise TypeError("path_result must be a PathQualificationResult")
    rank = path_result.vertices[0].dimension
    if path_result.status == PATH_INCOMPLETE:
        return _failed(path_result, WILSON_INPUT_INCOMPLETE, "path qualification is numerically incomplete")
    if path_result.status in {PATH_SUBSPACE_REQUIRED, PATH_UNQUALIFIED} or path_result.status not in _QUALIFIED:
        return _failed(path_result, WILSON_INPUT_UNQUALIFIED, "path qualification did not authorize transport")

    links = []
    for index, edge in enumerate(path_result.edge_results):
        right_index = (index + 1) % len(path_result.vertices) if path_result.closed else index + 1
        expected = (path_result.vertices[index].k_point, path_result.vertices[right_index].k_point)
        link = edge.transport_link
        if not edge.is_qualified or link is None:
            return _failed(path_result, WILSON_INPUT_UNQUALIFIED, "qualified path is structurally missing an E2 transport link", links)
        if link.dimension != rank or link.ambient_dimension != path_result.vertices[0].ambient_dimension:
            return _failed(path_result, WILSON_INPUT_UNQUALIFIED, "E2 transport link dimensions do not match the path")
        if (link.left_k_point, link.right_k_point) != expected:
            return _failed(path_result, WILSON_INPUT_UNQUALIFIED, "E2 transport link endpoints do not match the ordered path")
        links.append(link)

    product = np.eye(rank, dtype=np.complex128)
    for link in links:
        product = product @ link.unitary
    product = _matrix(product, rank)
    residual = float(np.linalg.norm(product.conj().T @ product - np.eye(rank), ord="fro"))
    if path_result.closed:
        eigenvalues = np.linalg.eigvals(product)
        eigenphases = np.angle(eigenvalues)
        determinant = complex(np.linalg.det(product))
        return WilsonTransportResult(
            status=WILSON_LOOP_QUALIFIED,
            closed=True,
            rank=rank,
            product=product,
            edge_links=tuple(links),
            unitarity_residual=residual,
            eigenvalues=eigenvalues,
            eigenphases=eigenphases,
            trace=complex(np.trace(product)),
            determinant=determinant,
            determinant_phase=float(np.angle(determinant)),
            evidence=("all ordered E2 transport links were qualified", "closed-loop diagnostics use principal eigenphases without unwrapping", "authorization is limited to Wilson transport"),
            provenance=path_result.provenance,
        )
    return WilsonTransportResult(
        status=WILSON_LINE_QUALIFIED,
        closed=False,
        rank=rank,
        product=product,
        edge_links=tuple(links),
        unitarity_residual=residual,
        evidence=("all ordered E2 transport links were qualified", "open-line product is endpoint-covariant; loop invariants are not exposed", "authorization is limited to Wilson transport"),
        provenance=path_result.provenance,
    )


compose_wilson_line_or_loop = compose_wilson_transport

__all__ = [
    "WILSON_LINE_QUALIFIED",
    "WILSON_LOOP_QUALIFIED",
    "WILSON_INPUT_INCOMPLETE",
    "WILSON_INPUT_UNQUALIFIED",
    "WILSON_TRANSPORT_AUTHORIZATION_SCOPE",
    "WilsonTransportResult",
    "compose_wilson_transport",
    "compose_wilson_line_or_loop",
]
