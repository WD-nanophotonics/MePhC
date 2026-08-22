"""Solver-neutral contracts for the triangular valley-reference benchmark.

The module deliberately stops before MPB.  It defines geometry/mapping
identity, explicit paper and project domains, deterministic sampling, centered
plaquette requests, cache identity, anchor specifications, and trend reduction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.ops import triangulate, unary_union

from .valley_reference_geometry import build_triangular_reference_geometry


PAPER_STYLE_TRUNCATED_K_HBZ = "PAPER_STYLE_TRUNCATED_K_HBZ"
MEPHC_PERIODIC_VORONOI_K_BASIN = "MEPHC_PERIODIC_VORONOI_K_BASIN"
DOMAIN_SYSTEMATIC = "delta_C_domain"
DELTA_K_VALUES = (1.0 / 72.0, 1.0 / 36.0, 1.0 / 18.0)
INTEGRATION_SPACING_Q = (1.0 / 18.0, 1.0 / 36.0, 1.0 / 72.0)
K_POINT = (2.0 / 3.0, 0.0)
VORONOI_AREA_Q = 1.0 / math.sqrt(3.0)


def _finite_vector(value: Iterable[float], name: str) -> np.ndarray:
    result = np.asarray(tuple(value), dtype=float)
    if result.shape != (2,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite two-vector")
    return result


def _matrix(value: Iterable[Iterable[float]], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (2, 2) or not np.all(np.isfinite(result)) or abs(float(np.linalg.det(result))) <= 1e-14:
        raise ValueError(f"{name} must be a finite nonsingular 2x2 matrix")
    return result


def reciprocal_basis_from_real_space(real_space_basis: Iterable[Iterable[float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return Cartesian reciprocal vectors as matrix columns in q=ka/(2pi) units."""
    real = _matrix(real_space_basis, "real_space_basis")
    reciprocal = np.linalg.inv(real).T
    return tuple(tuple(float(x) for x in row) for row in reciprocal)


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _signed_area(vertices: np.ndarray) -> float:
    return 0.5 * float(np.sum(vertices[:, 0] * np.roll(vertices[:, 1], -1) - vertices[:, 1] * np.roll(vertices[:, 0], -1)))


def _regular_polygon(center: Iterable[float], radius: float, sides: int, rotation: float = 0.0) -> tuple[tuple[float, float], ...]:
    c = _finite_vector(center, "center")
    if radius <= 0.0 or sides < 3:
        raise ValueError("radius and sides must be valid")
    angles = rotation + np.arange(sides, dtype=float) * (2.0 * math.pi / sides)
    points = c + float(radius) * np.column_stack((np.cos(angles), np.sin(angles)))
    if _signed_area(points) < 0.0:
        points = points[::-1]
    return tuple(tuple(float(x) for x in point) for point in points)


def _periodic_canonical(point: np.ndarray, period_basis: np.ndarray) -> tuple[float, float]:
    fractional = np.linalg.solve(period_basis, point)
    reduced = fractional - np.floor(fractional)
    canonical = period_basis @ reduced
    return tuple(float(x) for x in canonical)


def periodic_equivalent(left: Iterable[float], right: Iterable[float], period_basis: Iterable[Iterable[float]], tolerance: float = 1e-10) -> bool:
    a = _finite_vector(left, "left")
    b = _finite_vector(right, "right")
    basis = _matrix(period_basis, "period_basis")
    coefficients = np.linalg.solve(basis, a - b)
    return bool(np.allclose(coefficients, np.rint(coefficients), rtol=0.0, atol=tolerance))

def fractional_periodic_equivalent(left: Iterable[float], right: Iterable[float], tolerance: float = 1e-10) -> bool:
    a = _finite_vector(left, "left_fractional")
    b = _finite_vector(right, "right_fractional")
    difference = a - b
    return bool(np.allclose(difference, np.rint(difference), rtol=0.0, atol=tolerance))


@dataclass(frozen=True, slots=True)
class ReferenceCoordinatePreflight:
    """Bound public q, physical Cartesian k, and MPB reciprocal coordinates."""

    real_space_basis: tuple[tuple[float, float], tuple[float, float]]
    public_to_physical: tuple[tuple[float, float], tuple[float, float]]
    public_period_basis: tuple[tuple[float, float], tuple[float, float]]
    mpb_reciprocal_basis: tuple[tuple[float, float], tuple[float, float]]
    public_k: tuple[float, float]
    public_kp: tuple[float, float]
    mpb_k: tuple[float, float]
    mpb_kp: tuple[float, float]
    tolerance: float = 1e-10

    def __post_init__(self) -> None:
        _matrix(self.real_space_basis, "real_space_basis")
        _matrix(self.public_to_physical, "public_to_physical")
        _matrix(self.public_period_basis, "public_period_basis")
        _matrix(self.mpb_reciprocal_basis, "mpb_reciprocal_basis")
        if self.tolerance <= 0.0 or not math.isfinite(self.tolerance):
            raise ValueError("tolerance must be positive and finite")

    @property
    def public_k_physical(self) -> np.ndarray:
        return _matrix(self.public_to_physical, "public_to_physical") @ _finite_vector(self.public_k, "public_k")

    @property
    def public_kp_physical(self) -> np.ndarray:
        return _matrix(self.public_to_physical, "public_to_physical") @ _finite_vector(self.public_kp, "public_kp")

    def public_q_to_mpb(self, q: Iterable[float]) -> tuple[float, float]:
        physical = _matrix(self.public_to_physical, "public_to_physical") @ _finite_vector(q, "q")
        fractional = np.linalg.solve(_matrix(self.mpb_reciprocal_basis, "mpb_reciprocal_basis"), physical)
        return tuple(float(x) for x in fractional)

    def mpb_to_public_q(self, fractional: Iterable[float]) -> tuple[float, float]:
        physical = _matrix(self.mpb_reciprocal_basis, "mpb_reciprocal_basis") @ _finite_vector(fractional, "fractional")
        q = np.linalg.solve(_matrix(self.public_to_physical, "public_to_physical"), physical)
        return tuple(float(x) for x in q)

    @property
    def round_trip_residual(self) -> float:
        mapped = self.mpb_to_public_q(self.public_q_to_mpb(self.public_k))
        return float(np.linalg.norm(np.asarray(mapped) - np.asarray(self.public_k)))

    @property
    def k_label_mapping_bound(self) -> bool:
        return fractional_periodic_equivalent(self.public_q_to_mpb(self.public_k), self.mpb_k, self.tolerance) and fractional_periodic_equivalent(self.public_q_to_mpb(self.public_kp), self.mpb_kp, self.tolerance)

    @property
    def kp_time_reversal_bound(self) -> bool:
        return periodic_equivalent(self.public_kp, -np.asarray(self.public_k), self.public_period_basis, self.tolerance)

    @property
    def positive_orientation(self) -> bool:
        return float(np.linalg.det(_matrix(self.public_to_physical, "public_to_physical"))) > 0.0

    @property
    def ready(self) -> bool:
        return self.round_trip_residual <= self.tolerance and self.k_label_mapping_bound and self.kp_time_reversal_bound and self.positive_orientation

    def delta_k_vectors_to_public_q(self, delta_k: float) -> tuple[tuple[float, float], tuple[float, float]]:
        if not math.isfinite(float(delta_k)) or float(delta_k) <= 0.0:
            raise ValueError("delta_k must be positive and finite")
        inverse = np.linalg.inv(_matrix(self.public_to_physical, "public_to_physical"))
        vectors = (
            inverse @ np.asarray((float(delta_k), 0.0)),
            inverse @ np.asarray((0.0, float(delta_k))),
        )
        return tuple(tuple(float(x) for x in vector) for vector in vectors)

    def delta_k_to_public_q(self, delta_k: float) -> tuple[float, float]:
        return self.delta_k_vectors_to_public_q(delta_k)[0]

    @property
    def mapping_digest(self) -> str:
        return _json_digest({
            "schema": "reference_coordinate_preflight_v2",
            "real_space_basis": self.real_space_basis,
            "public_to_physical": self.public_to_physical,
            "public_period_basis": self.public_period_basis,
            "mpb_reciprocal_basis": self.mpb_reciprocal_basis,
            "public_k": self.public_k,
            "public_kp": self.public_kp,
            "mpb_k": self.mpb_k,
            "mpb_kp": self.mpb_kp,
            "orientation": "positive" if self.positive_orientation else "negative",
            "ready": self.ready,
        })


def build_triangular_coordinate_preflight() -> ReferenceCoordinatePreflight:
    identity = ((1.0, 0.0), (0.0, 1.0))
    reciprocal = reciprocal_basis_from_real_space(((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0)))
    return ReferenceCoordinatePreflight(
        real_space_basis=((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0)),
        public_to_physical=identity,
        public_period_basis=identity,
        mpb_reciprocal_basis=reciprocal,
        public_k=K_POINT,
        public_kp=(-K_POINT[0], -K_POINT[1]),
        mpb_k=(1.0 / 3.0, 1.0 / 3.0),
        mpb_kp=(-1.0 / 3.0, -1.0 / 3.0),
    )


def build_identity_coordinate_preflight() -> ReferenceCoordinatePreflight:
    """Return a small analytic identity mapping for solver-neutral tests."""
    identity = ((1.0, 0.0), (0.0, 1.0))
    return ReferenceCoordinatePreflight(
        real_space_basis=identity,
        public_to_physical=identity,
        public_period_basis=identity,
        mpb_reciprocal_basis=identity,
        public_k=K_POINT,
        public_kp=(-K_POINT[0], -K_POINT[1]),
        mpb_k=K_POINT,
        mpb_kp=(-K_POINT[0], -K_POINT[1]),
    )


@dataclass(frozen=True, slots=True)
class ValleyDomain:
    domain_id: str
    vertices: tuple[tuple[float, float], ...]
    exclusions: tuple[tuple[tuple[float, float], ...], ...] = ()
    orientation: str = "POSITIVE_PUBLIC_CARTESIAN_QX_QY"
    normalization: str = "FLUX_OVER_2PI"
    metadata: tuple[tuple[str, Any], ...] = ()

    @property
    def polygon(self) -> Polygon:
        outer = Polygon(self.vertices)
        if not outer.is_valid or outer.area <= 0.0:
            raise ValueError("domain outer polygon is invalid")
        if not self.exclusions:
            return outer
        return outer.difference(unary_union([Polygon(hole) for hole in self.exclusions]))

    @property
    def area_q(self) -> float:
        return float(self.polygon.area)

    @property
    def digest(self) -> str:
        return _json_digest(self.to_dict())

    def classify(self, point: Iterable[float]) -> str:
        candidate = Point(tuple(_finite_vector(point, "point")))
        outer = Polygon(self.vertices)
        if not outer.covers(candidate):
            return "OUTSIDE"
        if any(Polygon(hole).covers(candidate) for hole in self.exclusions):
            return "DECLARED_EXCLUSION"
        if self.polygon.covers(candidate):
            return "RETAINED"
        return "DECLARED_EXCLUSION"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "valley_domain_v2",
            "domain_id": self.domain_id,
            "vertices": [list(point) for point in self.vertices],
            "exclusions": [[list(point) for point in hole] for hole in self.exclusions],
            "orientation": self.orientation,
            "normalization": self.normalization,
            "metadata": dict(self.metadata),
        }


def _paper_hbz(radius: float) -> tuple[tuple[float, float], ...]:
    return _regular_polygon(K_POINT, radius, 3, rotation=math.pi / 3.0)


def _gamma_hexagons(radius: float, *, outer_radius: float = 2.0 / 3.0) -> tuple[tuple[tuple[float, float], ...], ...]:
    # These are the three explicit Gamma-centered exclusions at the vertices
    # of the reference K-HBZ.  Their locations are part of the domain digest.
    centers = np.asarray(_paper_hbz(outer_radius), dtype=float)
    return tuple(_regular_polygon(center, radius, 6, rotation=0.0) for center in centers)


def paper_style_truncated_k_hbz(*, fr: float, delta_k: float, delta_gamma: float) -> ValleyDomain:
    """Build the paper-style shrunken triangle plus three hex exclusions."""
    if fr not in {0.0, 0.4}:
        raise ValueError("paper presets are supported only for fr=0.0 and fr=0.4")
    if delta_k <= 0.0 or delta_gamma <= 0.0:
        raise ValueError("paper truncation radii must be positive")
    expected = {0.0: (0.10, 0.10), 0.4: (0.05, 0.13)}[float(fr)]
    if not math.isclose(delta_k, expected[0], rel_tol=0.0, abs_tol=1e-12) or not math.isclose(delta_gamma, expected[1], rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("delta_K and delta_Gamma must match the source-supported preset")
    return ValleyDomain(
        domain_id=f"{PAPER_STYLE_TRUNCATED_K_HBZ}:fr={fr:g}:deltaK={delta_k:g}:deltaGamma={delta_gamma:g}",
        vertices=_paper_hbz(2.0 / 3.0 - float(delta_k)),
        exclusions=_gamma_hexagons(float(delta_gamma)),
        metadata=(
            ("family", "Tri-TPC"),
            ("fr", float(fr)),
            ("delta_K", float(delta_k)),
            ("delta_Gamma", float(delta_gamma)),
            ("boundary_convention", "explicit_triangle_shrink_and_three_gamma_hexagons"),
            ("source_role", "paper_style_reference_observable"),
        ),
    )


def _clip_half_plane(vertices: list[np.ndarray], normal: np.ndarray, bound: float) -> list[np.ndarray]:
    if not vertices:
        return []
    result = []
    for left, right in zip(vertices, vertices[1:] + vertices[:1]):
        left_value = float(np.dot(normal, left) - bound)
        right_value = float(np.dot(normal, right) - bound)
        left_inside = left_value <= 1e-12
        right_inside = right_value <= 1e-12
        if left_inside:
            result.append(left)
        if left_inside != right_inside:
            fraction = left_value / (left_value - right_value)
            result.append(left + fraction * (right - left))
    return result


def _periodic_voronoi_cell(center: Iterable[float], competitor: Iterable[float], period_basis: Iterable[Iterable[float]], image_radius: int = 3) -> tuple[tuple[float, float], ...]:
    c = _finite_vector(center, "center")
    other = _finite_vector(competitor, "competitor")
    basis = _matrix(period_basis, "period_basis")
    translations = [basis @ np.asarray((i, j), dtype=float) for i in range(-image_radius, image_radius + 1) for j in range(-image_radius, image_radius + 1)]
    extent = 4.0 * max(float(np.linalg.norm(row)) for row in basis) + float(np.linalg.norm(other - c))
    vertices = [c + np.asarray((extent, extent)), c + np.asarray((-extent, extent)), c + np.asarray((-extent, -extent)), c + np.asarray((extent, -extent))]
    points = [c + t for t in translations if np.linalg.norm(t) > 1e-14]
    points.extend(other + t for t in translations)
    for point in points:
        normal = point - c
        bound = 0.5 * (float(np.dot(point, point)) - float(np.dot(c, c)))
        vertices = _clip_half_plane(vertices, normal, bound)
    if len(vertices) < 3:
        raise ValueError("periodic Voronoi construction produced no bounded cell")
    cleaned = []
    for point in vertices:
        if not cleaned or float(np.linalg.norm(point - cleaned[-1])) > 1e-10:
            cleaned.append(point)
    if len(cleaned) > 1 and float(np.linalg.norm(cleaned[0] - cleaned[-1])) <= 1e-10:
        cleaned.pop()
    array = np.asarray(cleaned, dtype=float)
    if _signed_area(array) < 0.0:
        array = array[::-1]
    return tuple(tuple(float(x) for x in point) for point in array)


def mephc_periodic_voronoi_k_basin(
    *,
    period_basis: Iterable[Iterable[float]] = ((1.0, 1.0), (1.0 / math.sqrt(3.0), -1.0 / math.sqrt(3.0))),
    k: Iterable[float] = K_POINT,
    kp: Iterable[float] = (-K_POINT[0], -K_POINT[1]),
) -> ValleyDomain:
    basis = _matrix(period_basis, "period_basis")
    center = _finite_vector(k, "k")
    competitor = _finite_vector(kp, "kp")
    vertices = _periodic_voronoi_cell(center, competitor, basis)
    return ValleyDomain(
        domain_id="PERIODIC_RECIPROCAL_METRIC_VORONOI_BASIN_K",
        vertices=vertices,
        metadata=(
            ("definition", "periodic reciprocal-metric Voronoi basin d_K<d_Kp with periodic images"),
            ("period_basis", tuple(tuple(float(x) for x in row) for row in basis)),
            ("K", tuple(float(x) for x in center)),
            ("Kp", tuple(float(x) for x in competitor)),
            ("boundary_convention", "zero_measure_boundary"),
            ("algorithm", "periodic_image_half_plane_intersection_v1"),
            ("source_role", "stable_project_internal_observable"),
        ),
    )

@dataclass(frozen=True, slots=True)
class DomainSample:
    spacing_q: float
    centers: tuple[tuple[float, float], ...]
    weights: tuple[float, ...]
    declared_exclusion_count: int
    retained_area_q: float
    domain_digest: str
    quadrature_scheme: str = "CLIPPED_SQUARE_CELL_TRIANGULATED_ELEMENTS_V2"
    element_ids: tuple[str, ...] = ()
    element_vertices: tuple[tuple[tuple[float, float], ...], ...] = ()
    spacing_provenance: tuple[str, ...] = ()

    @property
    def center_count(self) -> int:
        return len(self.centers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "valley_domain_sample_v2",
            "spacing_q": self.spacing_q,
            "centers": [list(point) for point in self.centers],
            "weights": list(self.weights),
            "declared_exclusion_count": self.declared_exclusion_count,
            "retained_area_q": self.retained_area_q,
            "domain_digest": self.domain_digest,
            "quadrature_scheme": self.quadrature_scheme,
            "element_ids": list(self.element_ids),
            "element_vertices": [[list(point) for point in vertices] for vertices in self.element_vertices],
            "spacing_provenance": list(self.spacing_provenance),
        }


def integrate_sampled_field(
    sample: DomainSample,
    values: Iterable[float],
    *,
    orientation_sign: int = 1,
    unexpected_mask_reasons: Iterable[str] = (),
) -> float:
    """Integrate a sampled scalar field with explicit mask fail-closed rules."""
    if orientation_sign not in {-1, 1}:
        raise ValueError("orientation_sign must be +1 or -1")
    reasons = tuple(str(reason) for reason in unexpected_mask_reasons)
    if reasons:
        raise ValueError(f"unexpected interior mask: {sorted(set(reasons))}")
    numbers = np.asarray(tuple(values), dtype=float)
    weights = np.asarray(sample.weights, dtype=float)
    if numbers.shape != weights.shape or not np.all(np.isfinite(numbers)):
        raise ValueError("values must be finite and match the sample center count")
    return float(orientation_sign * np.dot(numbers, weights))
def _connected_quadrature_elements(geometry: Any) -> list[Polygon]:
    components = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    elements: list[Polygon] = []
    for component in components:
        if not isinstance(component, Polygon) or component.area <= 1e-15:
            continue
        for candidate in triangulate(component):
            if candidate.area <= 1e-15 or not component.covers(candidate):
                continue
            elements.append(candidate)
    return elements


def sample_domain(domain: ValleyDomain, spacing_q: float) -> DomainSample:
    """Build connected, area-faithful elements with in-domain evaluation points."""
    if spacing_q <= 0.0 or not math.isfinite(float(spacing_q)):
        raise ValueError("spacing_q must be positive and finite")
    spacing = float(spacing_q)
    polygon = domain.polygon
    min_x, min_y, max_x, max_y = polygon.bounds
    i_min, i_max = math.floor(min_x / spacing) - 1, math.ceil(max_x / spacing) + 1
    j_min, j_max = math.floor(min_y / spacing) - 1, math.ceil(max_y / spacing) + 1
    centers: list[tuple[float, float]] = []
    weights: list[float] = []
    element_ids: list[str] = []
    element_vertices: list[tuple[tuple[float, float], ...]] = []
    provenance: list[str] = []
    for i in range(i_min, i_max + 1):
        for j in range(j_min, j_max + 1):
            x, y = i * spacing, j * spacing
            cell = box(x - spacing / 2.0, y - spacing / 2.0, x + spacing / 2.0, y + spacing / 2.0)
            clipped = polygon.intersection(cell)
            for local_index, element in enumerate(_connected_quadrature_elements(clipped)):
                evaluation = element.representative_point()
                if not domain.polygon.covers(evaluation):
                    raise ValueError("quadrature evaluation point lies outside retained domain")
                vertices = tuple((float(px), float(py)) for px, py in element.exterior.coords[:-1])
                centers.append((float(evaluation.x), float(evaluation.y)))
                weights.append(float(element.area))
                element_ids.append(f"cell:{i}:{j}:element:{local_index}")
                element_vertices.append(vertices)
                provenance.append(f"spacing_q={spacing!r};cell_index=({i},{j});element_index={local_index}")
    if not centers:
        raise ValueError("spacing produced no retained domain elements")
    area_error = abs(float(sum(weights)) - float(polygon.area))
    if area_error > 1e-10:
        raise ValueError(f"quadrature element area mismatch: {area_error}")
    return DomainSample(
        spacing_q=spacing,
        centers=tuple(centers),
        weights=tuple(weights),
        declared_exclusion_count=len(domain.exclusions),
        retained_area_q=float(polygon.area),
        domain_digest=domain.digest,
        element_ids=tuple(element_ids),
        element_vertices=tuple(element_vertices),
        spacing_provenance=tuple(provenance),
    )

@dataclass(frozen=True, slots=True)
class PlaquetteRequest:
    nominal_center_q: tuple[float, float]
    nominal_vertex_q: tuple[float, float]
    canonical_periodic_vertex_q: tuple[float, float]
    delta_k_q: tuple[float, float]
    vertex_index: int
    delta_k_vectors_q: tuple[tuple[float, float], tuple[float, float]] = ((1.0, 0.0), (0.0, 1.0))


def centered_ccw_plaquette_requests(
    centers: Iterable[Iterable[float]],
    delta_k_q: float | Iterable[Iterable[float]],
    *,
    period_basis: Iterable[Iterable[float]] = ((1.0, 0.0), (0.0, 1.0)),
) -> tuple[PlaquetteRequest, ...]:
    basis = _matrix(period_basis, "period_basis")
    if np.isscalar(delta_k_q):
        h = float(delta_k_q)
        if h <= 0.0 or not math.isfinite(h):
            raise ValueError("delta_k_q must be positive and finite")
        vectors = (np.asarray((h, 0.0)), np.asarray((0.0, h)))
    else:
        raw = tuple(tuple(vector) for vector in delta_k_q)
        if len(raw) != 2:
            raise ValueError("delta_k_q must contain two independent vectors")
        vectors = (_finite_vector(raw[0], "delta_k_x_q"), _finite_vector(raw[1], "delta_k_y_q"))
        if abs(float(vectors[0][0] * vectors[1][1] - vectors[0][1] * vectors[1][0])) <= 1e-14:
            raise ValueError("delta-k vectors must span a nonzero area")
    offsets = ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5))
    result = []
    delta_pair = (float(np.linalg.norm(vectors[0])), float(np.linalg.norm(vectors[1])))
    for center in centers:
        c = _finite_vector(center, "center")
        for index, (ox, oy) in enumerate(offsets):
            nominal = c + ox * vectors[0] + oy * vectors[1]
            result.append(PlaquetteRequest(
                nominal_center_q=tuple(float(x) for x in c),
                nominal_vertex_q=tuple(float(x) for x in nominal),
                canonical_periodic_vertex_q=_periodic_canonical(nominal, basis),
                delta_k_q=delta_pair,
                vertex_index=index,
                delta_k_vectors_q=tuple(tuple(float(x) for x in vector) for vector in vectors),
            ))
    return tuple(result)

@dataclass(frozen=True, slots=True)
class PhysicalSolveIdentity:
    geometry_digest: str
    material_reference_digest: str
    coordinate_mapping_digest: str
    evaluated_q: tuple[float, float]
    resolution: int
    num_bands: int
    polarization: str
    provider_representation: str
    eigensolver_tolerance: float
    deterministic: bool
    mesh_size: int

    def __post_init__(self) -> None:
        if self.resolution < 1 or self.num_bands < 1 or self.mesh_size < 1:
            raise ValueError("resolution, num_bands, and mesh_size must be positive")
        if len(self.evaluated_q) != 2 or not np.all(np.isfinite(self.evaluated_q)):
            raise ValueError("evaluated_q must be finite")
        if self.eigensolver_tolerance <= 0.0 or not math.isfinite(self.eigensolver_tolerance):
            raise ValueError("eigensolver_tolerance must be positive and finite")

    @property
    def cache_key(self) -> str:
        return _json_digest({
            "schema": "physical_mpb_solve_identity_v1",
            "geometry_digest": self.geometry_digest,
            "material_reference_digest": self.material_reference_digest,
            "coordinate_mapping_digest": self.coordinate_mapping_digest,
            "evaluated_q": list(self.evaluated_q),
            "resolution": self.resolution,
            "num_bands": self.num_bands,
            "polarization": self.polarization,
            "provider_representation": self.provider_representation,
            "eigensolver_tolerance": self.eigensolver_tolerance,
            "deterministic": self.deterministic,
            "mesh_size": self.mesh_size,
        })


@dataclass(slots=True)
class PhysicalSolveCache:
    """Small fail-closed registry for physical solve identities."""

    entries: dict[str, PhysicalSolveIdentity] = field(default_factory=dict)

    def register(self, identity: PhysicalSolveIdentity, *, claimed_key: str | None = None) -> str:
        key = identity.cache_key if claimed_key is None else str(claimed_key)
        existing = self.entries.get(key)
        if existing is not None and existing != identity:
            raise ValueError("ambiguous physical solve cache identity collision")
        self.entries[key] = identity
        return key
@dataclass(frozen=True, slots=True)
class CachePlan:
    raw_vertex_requests: int
    canonical_unique_vertices: int
    cache_hits: int

    @property
    def cache_hit_fraction(self) -> float:
        return self.cache_hits / self.raw_vertex_requests if self.raw_vertex_requests else 0.0


def plan_cache_requests(requests: Iterable[PlaquetteRequest]) -> CachePlan:
    rows = tuple(requests)
    unique = {request.canonical_periodic_vertex_q for request in rows}
    return CachePlan(len(rows), len(unique), len(rows) - len(unique))


@dataclass(frozen=True, slots=True)
class TrendReduction:
    status: str
    observed_change: float
    envelope: float
    direction_stable: bool
    identity_or_qualification_status: str
    delta_C_delta_k: float
    delta_C_integration: float
    delta_C_resolution: float
    delta_C_domain: float


def reduce_trend(
    before: float,
    after: float,
    *,
    delta_C_delta_k: float,
    delta_C_integration: float,
    delta_C_resolution: float,
    delta_C_domain: float,
    direction_stable: bool,
    identity_or_qualification_status: str = "QUALIFIED",
) -> TrendReduction:
    values = (delta_C_delta_k, delta_C_integration, delta_C_resolution, delta_C_domain)
    if any(value < 0.0 or not math.isfinite(float(value)) for value in values):
        raise ValueError("trend envelopes must be finite and nonnegative")
    observed = float(after) - float(before)
    envelope = float(sum(values))
    if identity_or_qualification_status != "QUALIFIED":
        status = "PHYSICALLY_UNQUALIFIED"
    elif not direction_stable or math.isclose(observed, 0.0, abs_tol=1e-15):
        status = "NUMERICALLY_UNRESOLVED"
    elif abs(observed) > envelope:
        status = "TREND_CONFIRMED"
    else:
        status = "TREND_QUALIFIED"
    return TrendReduction(status, observed, envelope, bool(direction_stable), identity_or_qualification_status, *map(float, values))


@dataclass(frozen=True, slots=True)
class BenchmarkAnchorSpec:
    anchor_id: str
    family: str
    parameter: float
    target_bands: tuple[int, ...]
    paper_domain_available: bool
    mephc_domain_available: bool
    rank1_prohibited_at_target: bool
    role: str


def triangular_benchmark_anchors() -> tuple[BenchmarkAnchorSpec, ...]:
    return (
        BenchmarkAnchorSpec("TRI_TPC_FR00", "Tri-TPC", 0.0, (1, 2, 3), True, True, False, "paper-comparison-anchor"),
        BenchmarkAnchorSpec("TRI_TPC_FR04", "Tri-TPC", 0.4, (1, 2, 3), True, True, False, "accidental-band3-band4-stress"),
        BenchmarkAnchorSpec("TRI_TPC_NEAR_SYMMETRY_FR049", "Tri-TPC", 0.49, (1, 2, 3), False, True, False, "near-degeneracy-stress"),
        BenchmarkAnchorSpec("CIR_TPC_EXACT_SYMMETRY_FR050", "Cir-TPC", 0.5, (2, 3), False, False, True, "exact-degeneracy-negative-control"),
    )


@dataclass(frozen=True, slots=True)
class AnchorReadiness:
    anchor_id: str
    status: str
    reasons: tuple[str, ...]


def reduce_anchor_readiness(
    anchor: BenchmarkAnchorSpec,
    geometry: Any,
    *,
    coordinate_preflight_ready: bool,
    domain_available: bool,
    rank_qualified: bool = True,
) -> AnchorReadiness:
    if anchor.rank1_prohibited_at_target:
        return AnchorReadiness(anchor.anchor_id, "RANK1_PROHIBITED", ("exact_symmetry_rank1_target_forbidden",))
    if not rank_qualified:
        return AnchorReadiness(anchor.anchor_id, "RANK_UNQUALIFIED", ("target_band_or_rank_policy_unqualified",))
    if not coordinate_preflight_ready:
        return AnchorReadiness(anchor.anchor_id, "COORDINATE_UNRESOLVED", ("coordinate_preflight_not_ready",))
    if not domain_available:
        return AnchorReadiness(anchor.anchor_id, "DOMAIN_UNAVAILABLE", ("requested_reference_domain_unavailable",))
    if getattr(geometry, "paper_parameter_equivalence", "UNRESOLVED") not in {"BOUND", "PAPER_PARAMETER_BOUND"}:
        return AnchorReadiness(anchor.anchor_id, "GEOMETRY_UNRESOLVED", ("paper_parameter_equivalence_unresolved",))
    if getattr(geometry, "material_contract_status", "UNRESOLVED") != "REFERENCE_BOUND":
        return AnchorReadiness(anchor.anchor_id, "MATERIAL_UNRESOLVED", ("source_material_contract_not_bound",))
    if anchor.paper_domain_available:
        return AnchorReadiness(anchor.anchor_id, "REFERENCE_READY", ())
    return AnchorReadiness(anchor.anchor_id, "PROJECT_STRESS_ONLY", ("project_domain_or_stress_anchor_only",))


@dataclass(frozen=True, slots=True)
class PerformanceDiagnostics:
    unique_mpb_solves: int = 0
    cache_hit_count: int = 0
    cache_hit_fraction: float = 0.0
    qualified_point_fraction: float = 0.0
    masked_point_fraction_by_reason: tuple[tuple[str, float], ...] = ()
    solver_failure_count: int = 0
    total_wall_time: float = 0.0
    result_artifact_size: int = 0
    center_count: int = 0
    raw_plaquette_vertex_request_count: int = 0
    unique_plaquette_vertex_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "UNIQUE_MPB_SOLVES": self.unique_mpb_solves,
            "CACHE_HIT_COUNT": self.cache_hit_count,
            "CACHE_HIT_FRACTION": self.cache_hit_fraction,
            "QUALIFIED_POINT_FRACTION": self.qualified_point_fraction,
            "MASKED_POINT_FRACTION_BY_REASON": dict(self.masked_point_fraction_by_reason),
            "SOLVER_FAILURE_COUNT": self.solver_failure_count,
            "TOTAL_WALL_TIME": self.total_wall_time,
            "RESULT_ARTIFACT_SIZE": self.result_artifact_size,
            "CENTER_COUNT": self.center_count,
            "RAW_PLAQUETTE_VERTEX_REQUEST_COUNT": self.raw_plaquette_vertex_request_count,
            "UNIQUE_PLAQUETTE_VERTEX_COUNT": self.unique_plaquette_vertex_count,
        }


__all__ = [
    "PAPER_STYLE_TRUNCATED_K_HBZ", "MEPHC_PERIODIC_VORONOI_K_BASIN", "DOMAIN_SYSTEMATIC",
    "DELTA_K_VALUES", "INTEGRATION_SPACING_Q", "ReferenceCoordinatePreflight", "build_triangular_coordinate_preflight", "reciprocal_basis_from_real_space", "fractional_periodic_equivalent",
    "build_identity_coordinate_preflight", "periodic_equivalent", "ValleyDomain",
    "paper_style_truncated_k_hbz", "mephc_periodic_voronoi_k_basin", "DomainSample",
    "sample_domain", "integrate_sampled_field", "PlaquetteRequest", "centered_ccw_plaquette_requests",
    "PhysicalSolveIdentity", "PhysicalSolveCache", "CachePlan", "plan_cache_requests", "TrendReduction",
    "reduce_trend", "BenchmarkAnchorSpec", "triangular_benchmark_anchors", "AnchorReadiness", "reduce_anchor_readiness",
    "PerformanceDiagnostics", "build_triangular_reference_geometry",
]
