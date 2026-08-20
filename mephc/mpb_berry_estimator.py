"""E7E local rank-one MPB plaquette Berry-curvature estimator."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections.abc import Mapping
import math
from types import MappingProxyType
from typing import Any

import numpy as np

from .eigenspace import EigenSubspace
from .mpb_plaquette_holonomy import MPBQualifiedPlaquetteHolonomyResult
from .path_domain import PATH_INCOMPLETE, PATH_SINGLE_BAND_QUALIFIED, PathQualificationResult
from .plaquette_domain import PlaquetteBoundaryQualificationResult
from .wilson_geometry import WILSON_INPUT_INCOMPLETE, WILSON_LOOP_QUALIFIED, WilsonTransportResult

E7E_MPB_BERRY_ESTIMATOR_SCOPE = "mpb_rank1_local_berry_estimator_only"
_BERRY_ESTIMATE_QUALIFIED = "BERRY_ESTIMATE_QUALIFIED"
_BERRY_INPUT_INCOMPLETE = "BERRY_INPUT_INCOMPLETE"
_BERRY_INPUT_UNQUALIFIED = "BERRY_INPUT_UNQUALIFIED"
_BERRY_UNSUPPORTED_RANK = "BERRY_UNSUPPORTED_RANK"
_BERRY_ZERO_AREA = "BERRY_ZERO_AREA"
_BERRY_MIXED_ORIENTATION = "BERRY_MIXED_ORIENTATION"
_BERRY_PHASE_BRANCH_AMBIGUOUS = "BERRY_PHASE_BRANCH_AMBIGUOUS"
_BERRY_DEGENERATE_POINT_UNQUALIFIED = "BERRY_DEGENERATE_POINT_UNQUALIFIED"

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

def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value

def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result

def _signed_area(vertices: tuple[EigenSubspace, ...]) -> float:
    if len(vertices) != 4:
        raise ValueError("E7E requires exactly four boundary vertices")
    points = []
    for vertex in vertices:
        if len(vertex.k_point) != 2:
            raise ValueError("E7E requires two-dimensional Cartesian k coordinates")
        point = tuple(float(item) for item in vertex.k_point)
        if not all(math.isfinite(item) for item in point):
            raise ValueError("boundary k coordinates must be finite")
        points.append(point)
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % 4][1]
        - points[(i + 1) % 4][0] * points[i][1]
        for i in range(4)
    )

@dataclass(frozen=True)
class MPBQualifiedBerryEstimateLevel:
    status: str
    step: float
    signed_area: float | None
    wilson_phase: float | None
    curvature_estimate: float | None
    path_result: PathQualificationResult
    wilson_result: WilsonTransportResult
    boundary_result: PlaquetteBoundaryQualificationResult
    boundary_vertices: tuple[EigenSubspace, ...]
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {
            _BERRY_ESTIMATE_QUALIFIED, _BERRY_INPUT_INCOMPLETE,
            _BERRY_INPUT_UNQUALIFIED, _BERRY_UNSUPPORTED_RANK,
            _BERRY_ZERO_AREA, _BERRY_MIXED_ORIENTATION,
            _BERRY_PHASE_BRANCH_AMBIGUOUS,
            _BERRY_DEGENERATE_POINT_UNQUALIFIED,
        }
        if self.status not in allowed:
            raise ValueError("invalid E7E level status")
        if not isinstance(self.path_result, PathQualificationResult):
            raise TypeError("path_result must be PathQualificationResult")
        if not isinstance(self.wilson_result, WilsonTransportResult):
            raise TypeError("wilson_result must be WilsonTransportResult")
        if not isinstance(self.boundary_result, PlaquetteBoundaryQualificationResult):
            raise TypeError("boundary_result must be PlaquetteBoundaryQualificationResult")
        vertices = tuple(self.boundary_vertices)
        if len(vertices) != 4 or any(not isinstance(x, EigenSubspace) for x in vertices):
            raise TypeError("boundary_vertices must contain four EigenSubspace values")
        step = _finite(self.step, "step")
        if step <= 0.0:
            raise ValueError("step must be positive")
        area = None if self.signed_area is None else _finite(self.signed_area, "signed_area")
        phase = None if self.wilson_phase is None else _finite(self.wilson_phase, "wilson_phase")
        estimate = None if self.curvature_estimate is None else _finite(self.curvature_estimate, "curvature_estimate")
        if phase is not None and abs(phase) > math.pi + 1e-14:
            raise ValueError("wilson_phase must use the principal branch")
        if self.status == _BERRY_ESTIMATE_QUALIFIED and (area is None or area == 0.0 or phase is None or estimate is None):
            raise ValueError("qualified E7E levels require area, phase, and estimate")
        if self.status != _BERRY_ESTIMATE_QUALIFIED and estimate is not None:
            raise ValueError("failed E7E levels must not expose curvature estimates")
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "signed_area", area)
        object.__setattr__(self, "wilson_phase", phase)
        object.__setattr__(self, "curvature_estimate", estimate)
        object.__setattr__(self, "boundary_vertices", vertices)
        object.__setattr__(self, "evidence", tuple(str(x) for x in self.evidence))
        object.__setattr__(self, "provenance", _freeze(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "step": self.step,
            "signed_area": self.signed_area, "wilson_phase": self.wilson_phase,
            "curvature_estimate": self.curvature_estimate,
            "source_e7d_path": self.path_result.to_dict(),
            "source_e7d_wilson": self.wilson_result.to_dict(),
            "source_e7c_boundary": self.boundary_result.to_dict(),
            "boundary_vertices": [x.to_dict() for x in self.boundary_vertices],
            "evidence": list(self.evidence), "provenance": dict(self.provenance),
        }

@dataclass(frozen=True)
class MPBQualifiedBerryEstimatorResult:
    source_result: MPBQualifiedPlaquetteHolonomyResult
    levels: tuple[MPBQualifiedBerryEstimateLevel, ...]
    require_live: bool = True
    branch_safety_margin: float = 1e-6
    authorization_scope: str = E7E_MPB_BERRY_ESTIMATOR_SCOPE
    coordinate_convention: str = "exact ordered two-dimensional Cartesian reciprocal k coordinates"
    sign_convention: str = "Omega_est = -phi_W / A_signed; A=i<u|grad_k u>"
    evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source_result, MPBQualifiedPlaquetteHolonomyResult):
            raise TypeError("source_result must be MPBQualifiedPlaquetteHolonomyResult")
        levels = tuple(self.levels)
        if not levels or any(not isinstance(x, MPBQualifiedBerryEstimateLevel) for x in levels):
            raise TypeError("levels must contain E7E level values")
        if type(self.require_live) is not bool:
            raise TypeError("require_live must be bool")
        margin = _finite(self.branch_safety_margin, "branch_safety_margin")
        if margin < 0.0 or margin >= math.pi:
            raise ValueError("branch_safety_margin must satisfy 0 <= margin < pi")
        if self.authorization_scope != E7E_MPB_BERRY_ESTIMATOR_SCOPE:
            raise ValueError("invalid E7E authorization scope")
        if len(levels) != len(self.source_result.wilson_results):
            raise ValueError("E7E level count must preserve E7D levels")
        object.__setattr__(self, "levels", levels)
        object.__setattr__(self, "branch_safety_margin", margin)
        object.__setattr__(self, "evidence", tuple(str(x) for x in self.evidence))
        object.__setattr__(self, "provenance", _freeze(self.provenance))

    @property
    def status(self) -> tuple[str, ...]:
        return tuple(x.status for x in self.levels)

    @property
    def curvature_estimates(self) -> tuple[float | None, ...]:
        return tuple(x.curvature_estimate for x in self.levels)

    @property
    def estimates(self) -> tuple[float | None, ...]:
        return self.curvature_estimates

    @property
    def is_qualified(self) -> bool:
        return all(x.status == _BERRY_ESTIMATE_QUALIFIED for x in self.levels)

    @property
    def is_live_qualified(self) -> bool:
        return self.require_live is True and self.source_result.is_live_qualified and self.is_qualified

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": list(self.status), "is_qualified": self.is_qualified,
            "is_live_qualified": self.is_live_qualified, "require_live": self.require_live,
            "branch_safety_margin": self.branch_safety_margin,
            "authorization_scope": self.authorization_scope,
            "coordinate_convention": self.coordinate_convention,
            "sign_convention": self.sign_convention,
            "levels": [x.to_dict() for x in self.levels],
            "evidence": list(self.evidence), "provenance": _thaw(self.provenance),
        }

def _input_status(path: PathQualificationResult, wilson: WilsonTransportResult) -> str:
    if path.status == PATH_INCOMPLETE or wilson.status == WILSON_INPUT_INCOMPLETE:
        return _BERRY_INPUT_INCOMPLETE
    return _BERRY_INPUT_UNQUALIFIED

def _center_rank_one_is_degenerate(source, level: int, selection: tuple[int, ...]) -> bool:
    """Fail closed when the sampled center has an exact or unresolved rank-one gap."""
    if len(selection) != 1:
        return False
    snapshot = source.snapshots[level][4]
    excluded = [index for index in range(snapshot.bands) if index not in selection]
    if not excluded:
        return False
    selected = selection[0]
    center_frequency = float(snapshot.frequencies[selected])
    gap = min(abs(center_frequency - float(snapshot.frequencies[index])) for index in excluded)
    tolerance = float(source.interior_results[level].thresholds.validation_tolerance)
    return gap <= max(tolerance, 1e-12)


def estimate_mpb_rank1_berry_curvature(
    source_result: MPBQualifiedPlaquetteHolonomyResult,
    *,
    require_live: bool = True,
    branch_safety_margin: float = 1e-6,
) -> MPBQualifiedBerryEstimatorResult:
    if not isinstance(source_result, MPBQualifiedPlaquetteHolonomyResult):
        raise TypeError("source_result must be MPBQualifiedPlaquetteHolonomyResult")
    if type(require_live) is not bool:
        raise TypeError("require_live must be bool")
    margin = _finite(branch_safety_margin, "branch_safety_margin")
    if margin < 0.0 or margin >= math.pi:
        raise ValueError("branch_safety_margin must satisfy 0 <= margin < pi")
    if require_live and source_result.is_qualified and not source_result.is_live_qualified:
        raise ValueError("live E7D-qualified holonomy is required")

    source = source_result.source_result
    levels = []
    area_signs = []
    for index, (path, wilson, boundary, step) in enumerate(zip(
        source_result.path_results, source_result.wilson_results,
        source.boundary_results, source.steps,
    )):
        vertices = tuple(path.vertices)
        area = None
        phase = None
        evidence = []
        rank = vertices[0].dimension if vertices else 0
        if rank != 1:
            status = _BERRY_UNSUPPORTED_RANK
            evidence.append("E7E supports rank-one plaquette estimates only")
        elif path.status != PATH_SINGLE_BAND_QUALIFIED or wilson.status != WILSON_LOOP_QUALIFIED or wilson.rank != 1 or wilson.determinant_phase is None:
            status = _input_status(path, wilson)
            evidence.append("E7D path and Wilson loop qualification are required")
        elif path.closed is not True or len(vertices) != 4:
            status = _BERRY_INPUT_UNQUALIFIED
            evidence.append("E7E requires one closed four-vertex E7D boundary")
        elif path.vertices is not boundary.vertices:
            status = _BERRY_INPUT_UNQUALIFIED
            evidence.append("exact E7C boundary vertices were not preserved through E7D")
        elif _center_rank_one_is_degenerate(source, index, source.selections[index][4]):
            status = _BERRY_DEGENERATE_POINT_UNQUALIFIED
            area = _signed_area(vertices)
            phase = float(wilson.determinant_phase)
            area_signs.append(math.copysign(1.0, area))
            evidence.append("rank-one curvature is withheld at an exact or unresolved center degeneracy")
        else:
            try:
                area = _signed_area(vertices)
            except (TypeError, ValueError):
                status = _BERRY_INPUT_UNQUALIFIED
                evidence.append("boundary coordinates are not finite two-dimensional Cartesian coordinates")
            else:
                phase = float(wilson.determinant_phase)
                area_signs.append(math.copysign(1.0, area) if area != 0.0 else 0.0)
                if area == 0.0:
                    status = _BERRY_ZERO_AREA
                    evidence.append("signed boundary area is zero")
                elif abs(phase) >= math.pi - margin:
                    status = _BERRY_PHASE_BRANCH_AMBIGUOUS
                    evidence.append("Wilson phase is within the branch-safety margin of pi")
                else:
                    status = _BERRY_ESTIMATE_QUALIFIED
                    evidence.extend((
                        "signed area uses the exact ordered E7C boundary vertices",
                        "Wilson phase is the exact sealed E7D determinant phase",
                        "local estimate uses Omega_est = -phi_W / A_signed",
                    ))
        estimate = None if status != _BERRY_ESTIMATE_QUALIFIED else -phase / area
        levels.append(MPBQualifiedBerryEstimateLevel(
            status=status, step=step, signed_area=area, wilson_phase=phase,
            curvature_estimate=estimate, path_result=path, wilson_result=wilson,
            boundary_result=boundary, boundary_vertices=tuple(boundary.vertices),
            evidence=tuple(evidence), provenance={
                "source": "E7E local rank-one MPB plaquette estimator",
                "level": index,
                "coordinate_convention": "exact ordered two-dimensional Cartesian reciprocal k coordinates",
                "sign_convention": "Omega_est = -phi_W / A_signed",
            },
        ))

    if len({sign for sign in area_signs if sign != 0.0}) > 1:
        levels = [
            replace(x, status=_BERRY_MIXED_ORIENTATION, curvature_estimate=None,
                    evidence=x.evidence + ("refinement levels have inconsistent signed-area orientation",))
            if x.signed_area is not None else x for x in levels
        ]
    return MPBQualifiedBerryEstimatorResult(
        source_result=source_result, levels=tuple(levels), require_live=require_live,
        branch_safety_margin=margin, evidence=(
            "E7E is limited to local rank-one plaquette curvature estimates",
            "no global topological claim is exposed",
            "exact E7D Wilson and E7C boundary evidence is preserved per level",
        ), provenance={
            "source": "E7E qualified rank-one Berry estimator",
            "live_required": require_live,
            "coordinate_convention": "exact ordered two-dimensional Cartesian reciprocal k coordinates",
        },
    )

__all__ = [
    "E7E_MPB_BERRY_ESTIMATOR_SCOPE",
    "MPBQualifiedBerryEstimateLevel",
    "MPBQualifiedBerryEstimatorResult",
    "estimate_mpb_rank1_berry_curvature",
]
