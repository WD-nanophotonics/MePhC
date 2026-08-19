"""E7F E7E-native local Berry-observable convergence certification.

This module consumes sealed E7E results and caller-supplied eigenmode
convergence certificates.  It never runs MPB and makes no global topological
claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from collections.abc import Mapping, Iterable
from types import MappingProxyType
from numbers import Real
from typing import Any

from .berry_convergence import BerryObservableThresholds
from .convergence import ConvergenceCheck, EigenmodeConvergenceCertificate
from .convergence_binding import bind_eigenmode_certificate_for_resolution
from .mpb_berry_estimator import (
    E7E_MPB_BERRY_ESTIMATOR_SCOPE,
    MPBQualifiedBerryEstimateLevel,
    MPBQualifiedBerryEstimatorResult,
)

E7F_BERRY_OBSERVABLE_SCOPE = (
    "e7e_native_local_berry_observable_convergence_certificate_only"
)
_SCHEMA = "mephc-e7f-berry-observable-convergence/v1"
_QUALIFIED = "BERRY_ESTIMATE_QUALIFIED"
_COORDINATES = "exact ordered two-dimensional Cartesian reciprocal k coordinates"
_SIGN = "Omega_est = -phi_W / A_signed; A=i<u|grad_k u>"
_ESTIMATOR_SCHEMA = "mephc-e7e-native-mpb-rank1-local-berry-estimator/v1"
_CENTER_PAIR_SEMANTICS = "centers are arithmetic means of the exact four preserved boundary vertices; center_tr = -center_plus within coordinate_tolerance"


def _freeze_json(value: Any, path: str = "provenance") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{path} must contain finite numbers")
        return number
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{path} mapping keys must be strings")
        return MappingProxyType({key: _freeze_json(item, f"{path}.{key}") for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{path}[]") for item in value)
    raise ValueError(f"{path} must be JSON-safe")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _check(name: str, status: str, observed: Any, criterion: Any, message: str) -> ConvergenceCheck:
    return ConvergenceCheck(name=name, status=status, observed=observed,
                            criterion=criterion, message=message)


def _within(left: float, right: float, absolute: float, relative: float) -> tuple[bool, float]:
    delta = abs(left - right)
    limit = max(absolute, relative * max(abs(left), abs(right)))
    return delta <= limit, limit


def _center(level: MPBQualifiedBerryEstimateLevel) -> tuple[float, float]:
    points = [tuple(float(x) for x in vertex.k_point) for vertex in level.boundary_vertices]
    if len(points) != 4 or any(len(point) != 2 for point in points):
        raise ValueError("E7F requires four two-dimensional boundary vertices")
    return (sum(point[0] for point in points) / 4.0,
            sum(point[1] for point in points) / 4.0)


def _area(level: MPBQualifiedBerryEstimateLevel) -> float:
    points = [tuple(float(x) for x in vertex.k_point) for vertex in level.boundary_vertices]
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % 4][1]
        - points[(i + 1) % 4][0] * points[i][1]
        for i in range(4)
    )


@dataclass(frozen=True)
class E7FBerryObservableSample:
    """One E7E value, its exact TR partner, and supplied solver evidence."""

    plus_result: MPBQualifiedBerryEstimatorResult
    tr_result: MPBQualifiedBerryEstimatorResult
    selected_level: int
    resolution: int
    step: float
    eigenmode_plus: EigenmodeConvergenceCertificate | None
    eigenmode_tr: EigenmodeConvergenceCertificate | None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.plus_result, MPBQualifiedBerryEstimatorResult):
            raise TypeError("plus_result must be an E7E estimator result")
        if not isinstance(self.tr_result, MPBQualifiedBerryEstimatorResult):
            raise TypeError("tr_result must be an E7E estimator result")
        if isinstance(self.selected_level, bool) or not isinstance(self.selected_level, int):
            raise ValueError("selected_level must be an integer")
        if not 0 <= self.selected_level < len(self.plus_result.levels):
            raise ValueError("selected_level is outside the E7E result")
        if self.selected_level >= len(self.tr_result.levels):
            raise ValueError("TR E7E result lacks the selected level")
        if isinstance(self.resolution, bool) or not isinstance(self.resolution, int) or self.resolution < 1:
            raise ValueError("resolution must be a positive integer")
        step = _finite(self.step, "step")
        if step <= 0.0:
            raise ValueError("step must be positive")
        plus = self.plus_result.levels[self.selected_level]
        tr = self.tr_result.levels[self.selected_level]
        if plus.step != step or tr.step != step:
            raise ValueError("sample step must exactly preserve both E7E levels")
        if self.eigenmode_plus is not None and not isinstance(self.eigenmode_plus, EigenmodeConvergenceCertificate):
            raise TypeError("eigenmode_plus must be an eigenmode certificate or None")
        if self.eigenmode_tr is not None and not isinstance(self.eigenmode_tr, EigenmodeConvergenceCertificate):
            raise TypeError("eigenmode_tr must be an eigenmode certificate or None")
        if not isinstance(self.provenance, Mapping):
            raise TypeError("provenance must be a mapping")
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "provenance", _freeze_json(self.provenance))

    @property
    def plus_level(self) -> MPBQualifiedBerryEstimateLevel:
        return self.plus_result.levels[self.selected_level]

    @property
    def tr_level(self) -> MPBQualifiedBerryEstimateLevel:
        return self.tr_result.levels[self.selected_level]

    @property
    def omega_plus(self) -> float | None:
        return self.plus_level.curvature_estimate

    @property
    def omega_tr(self) -> float | None:
        return self.tr_level.curvature_estimate

    @property
    def center_plus(self) -> tuple[float, float]:
        return _center(self.plus_level)

    @property
    def center_tr(self) -> tuple[float, float]:
        return _center(self.tr_level)

    @property
    def area_plus(self) -> float:
        return _area(self.plus_level)

    @property
    def area_tr(self) -> float:
        return _area(self.tr_level)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution,
            "step": self.step,
            "selected_level": self.selected_level,
            "plus_e7e": self.plus_result.to_dict(),
            "tr_e7e": self.tr_result.to_dict(),
            "omega_plus": self.omega_plus,
            "omega_tr": self.omega_tr,
            "center_plus": list(self.center_plus),
            "center_tr": list(self.center_tr),
            "area_plus": self.area_plus,
            "area_tr": self.area_tr,
            "eigenmode_plus": None if self.eigenmode_plus is None else self.eigenmode_plus.to_dict(),
            "eigenmode_tr": None if self.eigenmode_tr is None else self.eigenmode_tr.to_dict(),
            "provenance": _thaw_json(self.provenance),
        }


@dataclass(frozen=True)
class E7FBerryObservableCertificate:
    status: str
    thresholds: BerryObservableThresholds
    resolution_samples: tuple[E7FBerryObservableSample, ...]
    step_samples: tuple[E7FBerryObservableSample, ...]
    checks: tuple[ConvergenceCheck, ...]
    require_live: bool
    coordinate_tolerance: float
    qualified_resolution: int | None
    qualified_step: float | None
    authorization_scope: str = E7F_BERRY_OBSERVABLE_SCOPE

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "FAIL", "INCOMPLETE"}:
            raise ValueError("status must be PASS, FAIL, or INCOMPLETE")
        if not isinstance(self.thresholds, BerryObservableThresholds):
            raise TypeError("thresholds must be BerryObservableThresholds")
        resolutions = tuple(self.resolution_samples)
        steps = tuple(self.step_samples)
        if any(not isinstance(x, E7FBerryObservableSample) for x in resolutions + steps):
            raise TypeError("sample ladders must contain E7F samples")
        if any(not isinstance(x, ConvergenceCheck) for x in self.checks):
            raise TypeError("checks must contain ConvergenceCheck values")
        if type(self.require_live) is not bool:
            raise TypeError("require_live must be bool")
        tolerance = _finite(self.coordinate_tolerance, "coordinate_tolerance")
        if tolerance <= 0.0:
            raise ValueError("coordinate_tolerance must be positive")
        if self.authorization_scope != E7F_BERRY_OBSERVABLE_SCOPE:
            raise ValueError("invalid E7F authorization scope")
        if self.status == "PASS":
            if self.qualified_resolution is None or self.qualified_step is None:
                raise ValueError("PASS requires qualified endpoints")
        elif self.qualified_resolution is not None or self.qualified_step is not None:
            raise ValueError("FAIL/INCOMPLETE cannot expose qualified endpoints")
        object.__setattr__(self, "resolution_samples", resolutions)
        object.__setattr__(self, "step_samples", steps)
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "coordinate_tolerance", tolerance)

    @property
    def is_live_qualified(self) -> bool:
        return self.status == "PASS" and self.require_live and all(
            sample.plus_result.is_live_qualified and sample.tr_result.is_live_qualified
            for sample in self.resolution_samples + self.step_samples
        )

    def require_passed(self) -> "E7FBerryObservableCertificate":
        if self.status == "PASS":
            return self
        names = ", ".join(check.name for check in self.checks if check.status != "PASS") or "unknown check"
        raise RuntimeError(f"E7F Berry observable certificate is {self.status}: {names}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "status": self.status,
            "authorization_scope": self.authorization_scope,
            "e7e_scope": E7E_MPB_BERRY_ESTIMATOR_SCOPE,
            "estimator_schema": _ESTIMATOR_SCHEMA,
            "center_pair_semantics": _CENTER_PAIR_SEMANTICS,
            "coordinate_convention": _COORDINATES,
            "sign_convention": _SIGN,
            "thresholds": self.thresholds.to_dict(),
            "require_live": self.require_live,
            "is_live_qualified": self.is_live_qualified,
            "coordinate_tolerance": self.coordinate_tolerance,
            "resolution_samples": [x.to_dict() for x in self.resolution_samples],
            "step_samples": [x.to_dict() for x in self.step_samples],
            "checks": [x.to_dict() for x in self.checks],
            "qualified_resolution": self.qualified_resolution,
            "qualified_step": self.qualified_step,
        }


def _ladder_checks(resolutions: tuple[E7FBerryObservableSample, ...], steps: tuple[E7FBerryObservableSample, ...], checks: list[ConvergenceCheck], thresholds: BerryObservableThresholds) -> None:
    if not resolutions:
        checks.append(_check("resolution.completeness", "INCOMPLETE", {"count": 0}, {"minimum": 1}, "resolution ladder is missing"))
    if not steps:
        checks.append(_check("step.completeness", "INCOMPLETE", {"count": 0}, {"minimum": 1}, "step ladder is missing"))
    for left, right in zip(resolutions, resolutions[1:]):
        ok = right.resolution > left.resolution and right.step == left.step
        checks.append(_check("resolution.order", "PASS" if ok else "FAIL", [left.resolution, right.resolution], "strictly increasing resolution and fixed step", "resolution ladder contract"))
    for left, right in zip(steps, steps[1:]):
        ok = right.step < left.step and right.resolution == left.resolution
        checks.append(_check("step.order", "PASS" if ok else "FAIL", [left.step, right.step], "strictly decreasing step and fixed resolution", "step ladder contract"))
    resolution_minimum = thresholds.required_resolution_tail_pairs + 1
    step_minimum = thresholds.required_step_tail_pairs + 1
    if resolutions and len(resolutions) < resolution_minimum:
        checks.append(_check("resolution.completeness", "INCOMPLETE", {"count": len(resolutions)}, {"minimum": resolution_minimum}, "resolution ladder lacks a convergence tail"))
    if steps and len(steps) < step_minimum:
        checks.append(_check("step.completeness", "INCOMPLETE", {"count": len(steps)}, {"minimum": step_minimum}, "step ladder lacks a convergence tail"))
    if resolutions and steps:
        overlap = [x for x in steps if x.resolution == resolutions[-1].resolution and x.step == resolutions[-1].step]
        exact = len(overlap) == 1 and overlap[0].omega_plus == resolutions[-1].omega_plus and overlap[0].omega_tr == resolutions[-1].omega_tr
        overlap_status = "PASS" if exact else ("INCOMPLETE" if len(resolutions) < 3 or len(steps) < 3 else "FAIL")
        checks.append(_check("ladder.overlap", overlap_status, {"count": len(overlap)}, {"exactly_one_and_exact_values": True}, "the final resolution and nominal-step sample must be identical"))


def certify_e7e_berry_observable_convergence(
    resolution_samples: Iterable[E7FBerryObservableSample],
    step_samples: Iterable[E7FBerryObservableSample],
    *,
    thresholds: BerryObservableThresholds = BerryObservableThresholds(),
    require_live: bool = True,
    coordinate_tolerance: float = 1e-9,
) -> E7FBerryObservableCertificate:
    """Certify one E7E observable and its exact time-reversal partner."""
    if not isinstance(thresholds, BerryObservableThresholds):
        raise TypeError("thresholds must be BerryObservableThresholds")
    if type(require_live) is not bool:
        raise TypeError("require_live must be bool")
    tolerance = _finite(coordinate_tolerance, "coordinate_tolerance")
    if tolerance <= 0.0:
        raise ValueError("coordinate_tolerance must be positive")
    resolutions = tuple(resolution_samples)
    steps = tuple(step_samples)
    if any(not isinstance(x, E7FBerryObservableSample) for x in resolutions + steps):
        raise TypeError("sample ladders must contain E7F samples")
    checks: list[ConvergenceCheck] = []
    _ladder_checks(resolutions, steps, checks, thresholds)
    def sample_key(sample: E7FBerryObservableSample) -> tuple[Any, ...]:
        return (sample.resolution, sample.step, sample.omega_plus, sample.omega_tr, sample.selected_level)
    all_samples = list(resolutions + steps)
    anchor_center: tuple[float, float] | None = None
    anchor_provenance: dict[str, Any] | None = None
    expected_eigenmode = None
    for index, sample in enumerate(all_samples):
        plus = sample.plus_level
        tr = sample.tr_level
        if plus.path_result.authorization_scope != "path_domain_only" or plus.wilson_result.authorization_scope != "wilson_transport_only":
            checks.append(_check(f"sample.{index}.e7e_scope", "FAIL", {"path": plus.path_result.authorization_scope, "wilson": plus.wilson_result.authorization_scope}, "sealed E7E/E7D scopes", "E7E source scope is not preserved"))
        if plus.status != _QUALIFIED or tr.status != _QUALIFIED:
            incomplete = "INCOMPLETE" in plus.status or "INCOMPLETE" in tr.status
            checks.append(_check(f"sample.{index}.qualification", "INCOMPLETE" if incomplete else "FAIL", [plus.status, tr.status], [_QUALIFIED, _QUALIFIED], "both selected E7E values must be rank-one qualified"))
        rank_ok = plus.boundary_vertices[0].dimension == 1 and tr.boundary_vertices[0].dimension == 1
        checks.append(_check(f"sample.{index}.rank", "PASS" if rank_ok else "FAIL", [plus.boundary_vertices[0].dimension, tr.boundary_vertices[0].dimension], [1, 1], "E7F is rank-one only"))
        convention_ok = sample.plus_result.coordinate_convention == _COORDINATES == sample.tr_result.coordinate_convention and sample.plus_result.sign_convention == _SIGN == sample.tr_result.sign_convention
        checks.append(_check(f"sample.{index}.conventions", "PASS" if convention_ok else "FAIL", [sample.plus_result.coordinate_convention, sample.plus_result.sign_convention], [_COORDINATES, _SIGN], "exact E7E coordinate and sign conventions are required"))
        center = sample.center_plus
        center_ok = max(abs(center[0] + sample.center_tr[0]), abs(center[1] + sample.center_tr[1])) <= tolerance
        checks.append(_check(f"sample.{index}.center_tr", "PASS" if center_ok else "FAIL", [list(center), list(sample.center_tr)], "center_tr == -center_plus", "exact four-vertex centers must be time-reversal partners"))
        area_ok = abs(abs(sample.area_plus) - abs(sample.area_tr)) <= tolerance
        orientation_ok = sample.area_plus != 0.0 and sample.area_tr != 0.0 and math.copysign(1.0, sample.area_plus) == math.copysign(1.0, sample.area_tr)
        checks.append(_check(f"sample.{index}.area", "PASS" if area_ok else "FAIL", [sample.area_plus, sample.area_tr], "equal absolute area", "TR pair must preserve plaquette area magnitude"))
        checks.append(_check(f"sample.{index}.orientation", "PASS" if orientation_ok else "FAIL", [sample.area_plus, sample.area_tr], "same orientation", "TRS does not reverse the E7E orientation"))
        if anchor_center is None:
            anchor_center = center
        else:
            fixed = max(abs(center[0] - anchor_center[0]), abs(center[1] - anchor_center[1])) <= tolerance
            checks.append(_check(f"sample.{index}.fixed_center", "PASS" if fixed else "FAIL", list(center), list(anchor_center), "all ladder samples preserve the same plus center"))
        if anchor_provenance is None:
            anchor_provenance = dict(sample.provenance)
        else:
            checks.append(_check(f"sample.{index}.fixed_provenance", "PASS" if dict(sample.provenance) == anchor_provenance else "FAIL", dict(sample.provenance), anchor_provenance, "all ladder samples preserve provenance"))
        if require_live and not (sample.plus_result.is_live_qualified and sample.tr_result.is_live_qualified):
            checks.append(_check(f"sample.{index}.live", "INCOMPLETE", [sample.plus_result.is_live_qualified, sample.tr_result.is_live_qualified], [True, True], "live E7E qualification is required by this certificate"))
        for label, certificate in (("plus", sample.eigenmode_plus), ("tr", sample.eigenmode_tr)):
            if certificate is None:
                checks.append(_check(f"sample.{index}.eigenmode.{label}", "INCOMPLETE", None, "PASS certificate", "caller-supplied eigenmode evidence is missing"))
                continue
            if certificate.status != "PASS":
                checks.append(_check(f"sample.{index}.eigenmode.{label}.certificate", "INCOMPLETE", certificate.status, "PASS", "non-PASS eigenmode evidence keeps E7F incomplete"))
            if expected_eigenmode is None:
                expected_eigenmode = certificate.provenance
            same = certificate.provenance == expected_eigenmode
            if not same:
                checks.append(_check(f"sample.{index}.eigenmode.{label}.provenance", "FAIL", certificate.provenance.to_dict(), expected_eigenmode.to_dict(), "all eigenmode evidence must share exact provenance"))
                continue
            binding = bind_eigenmode_certificate_for_resolution(certificate, expected_provenance=expected_eigenmode, expected_resolution=sample.resolution)
            binding_status = binding.status if certificate.status == "PASS" else "INCOMPLETE"
            checks.append(_check(f"sample.{index}.eigenmode.{label}.binding", binding_status, binding.to_dict(), "PASS", "eigenmode evidence must bind to the exact resolution; non-PASS supplied evidence remains INCOMPLETE"))
    def certificate_scope(certificate: EigenmodeConvergenceCertificate | None) -> Any:
        if certificate is None:
            return None
        certified_resolution = None
        if certificate.status == "PASS" and certificate.evidence:
            certified_resolution = certificate.evidence[-1].upper_resolution
        return (certificate.status, certificate.provenance.to_dict(), certified_resolution)

    if resolutions and steps:
        final = resolutions[-1]
        overlap = [sample for sample in steps
                   if sample.resolution == final.resolution
                   and sample.step == final.step]
        if len(overlap) == 1:
            candidate = overlap[0]
            center_match = (
                max(abs(candidate.center_plus[i] - final.center_plus[i]) for i in (0, 1)) <= tolerance
                and max(abs(candidate.center_tr[i] - final.center_tr[i]) for i in (0, 1)) <= tolerance
            )
            area_match = (
                abs(candidate.area_plus - final.area_plus) <= tolerance
                and abs(candidate.area_tr - final.area_tr) <= tolerance
            )
            convention_match = (
                candidate.plus_result.coordinate_convention == final.plus_result.coordinate_convention
                and candidate.tr_result.coordinate_convention == final.tr_result.coordinate_convention
                and candidate.plus_result.sign_convention == final.plus_result.sign_convention
                and candidate.tr_result.sign_convention == final.tr_result.sign_convention
            )
            evidence_match = (
                candidate.selected_level == final.selected_level
                and dict(candidate.provenance) == dict(final.provenance)
                and certificate_scope(candidate.eigenmode_plus) == certificate_scope(final.eigenmode_plus)
                and certificate_scope(candidate.eigenmode_tr) == certificate_scope(final.eigenmode_tr)
            )
            semantic_match = center_match and area_match and convention_match and evidence_match
            checks.append(_check(
                "ladder.overlap.semantic", "PASS" if semantic_match else "FAIL",
                {"center": center_match, "area": area_match,
                 "convention": convention_match, "evidence": evidence_match},
                {"exact_semantic_identity": True},
                "separately supplied overlap must preserve all E7F semantic evidence",
            ))

    def tail(items: tuple[E7FBerryObservableSample, ...], required: int) -> tuple[E7FBerryObservableSample, ...]:
        if len(items) < required + 1:
            checks.append(_check("tail.completeness", "INCOMPLETE", {"count": len(items)}, {"minimum": required + 1}, "required convergence tail is missing"))
        return items[max(0, len(items) - required - 1):]
    resolution_tail = tail(resolutions, thresholds.required_resolution_tail_pairs)
    step_tail = tail(steps, thresholds.required_step_tail_pairs)
    gating: list[E7FBerryObservableSample] = []
    gating_keys: set[tuple[Any, ...]] = set()
    for sample in resolution_tail + step_tail:
        key = (sample.resolution, sample.step, sample.omega_plus, sample.omega_tr, sample.selected_level)
        if key not in gating_keys:
            gating_keys.add(key)
            gating.append(sample)
    for left, right in zip(resolution_tail, resolution_tail[1:]):
        for label, a, b in (("plus", left.omega_plus, right.omega_plus), ("tr", left.omega_tr, right.omega_tr)):
            if a is None or b is None:
                continue
            ok, limit = _within(a, b, thresholds.max_resolution_abs_change, thresholds.max_resolution_relative_change)
            checks.append(_check(f"resolution.{label}", "PASS" if ok else "FAIL", {"left": a, "right": b}, {"limit": limit}, "resolution convergence gate"))
    for left, right in zip(step_tail, step_tail[1:]):
        for label, a, b in (("plus", left.omega_plus, right.omega_plus), ("tr", left.omega_tr, right.omega_tr)):
            if a is None or b is None:
                continue
            ok, limit = _within(a, b, thresholds.max_step_abs_change, thresholds.max_step_relative_change)
            checks.append(_check(f"step.{label}", "PASS" if ok else "FAIL", {"left": a, "right": b}, {"limit": limit}, "step convergence gate"))
    for index, sample in enumerate(gating):
        if sample.omega_plus is None or sample.omega_tr is None:
            continue
        signal = 0.5 * (abs(sample.omega_plus) + abs(sample.omega_tr))
        residual = abs(sample.omega_plus + sample.omega_tr)
        limit = max(thresholds.max_trs_abs_residual, thresholds.max_trs_relative_residual * signal)
        checks.append(_check(f"trs.{index}", "PASS" if residual <= limit else "FAIL", {"residual": residual, "omega_plus": sample.omega_plus, "omega_tr": sample.omega_tr}, {"limit": limit}, "TRS compares Omega(+) + Omega(-)"))
    if any(x.status == "INCOMPLETE" for x in checks):
        status = "INCOMPLETE"
    elif any(x.status == "FAIL" for x in checks):
        status = "FAIL"
    else:
        status = "PASS"
    qualified_resolution = resolutions[-1].resolution if status == "PASS" and resolutions else None
    qualified_step = steps[-1].step if status == "PASS" and steps else None
    return E7FBerryObservableCertificate(
        status=status, thresholds=thresholds, resolution_samples=resolutions,
        step_samples=steps, checks=tuple(checks), require_live=require_live,
        coordinate_tolerance=tolerance, qualified_resolution=qualified_resolution,
        qualified_step=qualified_step,
    )


__all__ = [
    "E7F_BERRY_OBSERVABLE_SCOPE",
    "E7FBerryObservableSample",
    "E7FBerryObservableCertificate",
    "certify_e7e_berry_observable_convergence",
]
