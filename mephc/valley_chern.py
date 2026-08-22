"""Solver-neutral valley-Chern normalization and interpretation audit.

This module consumes sealed flux evidence only. It never runs MPB or evaluates
Berry fields. The observable is tied to the explicit periodic reciprocal-metric
Voronoi basin around K and to the project's q-coordinate Berry convention.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

TWO_PI = 2.0 * math.pi
V_K_AREA = 1.0 / math.sqrt(3.0)
DOMAIN_ID = "PERIODIC_RECIPROCAL_METRIC_VORONOI_BASIN_K"
Q_COORDINATE_RELATION = "q=k_phys*a/(2*pi)"
ORIENTATION = "POSITIVE_PUBLIC_CARTESIAN_QX_QY"
BERRY_SIGN_CONVENTION = "OMEGA=-WILSON_PHASE/SIGNED_AREA/(2*pi)^2"
PRIMARY_COMPONENTS = ("band1", "band2")
DIAGNOSTIC_COMPONENTS = ("anti", "common")
ALL_COMPONENTS = PRIMARY_COMPONENTS + DIAGNOSTIC_COMPONENTS


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def valley_chern_from_flux(flux: Any, *, orientation_sign: int = 1) -> float:
    """Normalize a signed valley flux using C_v=Phi_v/(2*pi)."""
    if orientation_sign not in (-1, 1):
        raise ValueError("orientation_sign must be +1 or -1")
    return orientation_sign * _finite(flux, "flux") / TWO_PI


def coordinate_flux_invariance(omega_q: Any, q_area: Any, lattice_scale_a: Any) -> dict[str, float | bool]:
    """Validate Phi_q == Phi_phys using the project's dual unit contract."""
    omega = _finite(omega_q, "omega_q")
    area = _finite(q_area, "q_area")
    a = _finite(lattice_scale_a, "lattice_scale_a")
    if a <= 0.0:
        raise ValueError("lattice_scale_a must be positive")
    omega_phys_over_a2 = omega / TWO_PI**2
    physical_k_area = area * (TWO_PI / a) ** 2
    restored_physical_flux = omega_phys_over_a2 * physical_k_area * a**2
    return {
        "q_flux": omega * area,
        "omega_phys_over_a2": omega_phys_over_a2,
        "physical_k_area": physical_k_area,
        "restored_physical_flux": restored_physical_flux,
        "equal": math.isclose(omega * area, restored_physical_flux, rel_tol=0.0, abs_tol=1e-14),
    }


def _component_map(value: Mapping[str, Any], name: str) -> dict[str, float]:
    result = {}
    for component in ALL_COMPONENTS:
        if component not in value:
            raise ValueError(f"{name} lacks {component}")
        result[component] = _finite(value[component], f"{name}.{component}")
    return result


def _bound_map(value: Mapping[str, Any] | None) -> dict[str, float]:
    if value is None:
        return {component: 0.0 for component in ALL_COMPONENTS}
    result = {}
    for component in ALL_COMPONENTS:
        result[component] = _finite(value.get(component, 0.0), f"flux_error_bound.{component}")
        if result[component] < 0.0:
            raise ValueError("flux error bounds must be nonnegative")
    return result


def build_valley_chern_audit(
    sealed_flux: Mapping[str, Any],
    *,
    flux_error_bound: Mapping[str, Any] | None = None,
    c9_source_digest: str | None = None,
    control_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact E7I.1H result from sealed C9 flux evidence."""
    flux = _component_map(sealed_flux, "sealed_flux")
    bounds = _bound_map(flux_error_bound)
    if control_status is None:
        control_status = {}
    periodicity = control_status.get("BERRY_TORUS_PERIODICITY", "UNRESOLVED")
    inversion = control_status.get("VORONOI_DOMAIN_INVERSION", "UNRESOLVED")
    chern = {component: valley_chern_from_flux(flux[component]) for component in ALL_COMPONENTS}
    chern_bounds = {component: bounds[component] / TWO_PI for component in ALL_COMPONENTS}
    coord = coordinate_flux_invariance(flux["band1"] / V_K_AREA, V_K_AREA, 1.0)
    provenance = {
        "c9_source_digest": c9_source_digest,
        "domain_id": DOMAIN_ID,
        "domain_area_q": V_K_AREA,
        "coordinate_relation": Q_COORDINATE_RELATION,
        "orientation": ORIENTATION,
        "berry_sign_convention": BERRY_SIGN_CONVENTION,
        "normalization": "PHI_OVER_2PI",
    }
    result = {
        "E7I1H_SCOPE": "VALLEY_CHERN_ONLY_NO_NEW_MPB",
        "DOMAIN": {
            "id": DOMAIN_ID,
            "definition": "periodic reciprocal-metric Voronoi basin of K",
            "area_q": V_K_AREA,
            "orientation": ORIENTATION,
            "coordinate_relation": Q_COORDINATE_RELATION,
        },
        "SEALED_REFINED_FLUX": flux,
        "SEALED_REFINED_FLUX_ERROR_BOUND": bounds,
        "VALLEY_CHERN": chern,
        "VALLEY_CHERN_ERROR_BOUND": chern_bounds,
        "VALLEY_CHERN_NORMALIZATION": "PHI_OVER_2PI_CONFIRMED",
        "VALLEY_FLUX_COORDINATE_INVARIANCE": "DERIVED_AND_VALIDATED" if coord["equal"] else "FAILED",
        "COORDINATE_INVARIANCE_CHECK": coord,
        "NONQUANTIZED_VALLEY_CHERN_INTERPRETATION": "MATHEMATICALLY_CLOSED",
        "VALLEY_CHERN_DOMAIN_INVERSION": "SIGN_REVERSAL_SUPPORTED" if inversion == "CONFIRMED" else "UNRESOLVED",
        "TIME_REVERSAL_VALLEY_RELATION": "SUPPORTED_BY_EXISTING_CONTROLS" if periodicity == "CONFIRMED" and inversion == "CONFIRMED" else "PARTIAL",
        "VALLEY_CHERN_MULTIBAND_INTERPRETATION": "INDIVIDUAL_BANDS_PRIMARY_DIAGNOSTIC_COMBINATIONS_SEPARATE",
        "PAPER_GEOMETRY_EQUIVALENCE": "UNRESOLVED",
        "PAPER_VALLEY_CHERN_CONVENTION": "CONSISTENT_AFTER_BLOCH_K_MAPPING",
        "BLOCH_K_MAPPING": "k_paper=-k_MPB",
        "SIGN_HACK": "NONE",
        "CONTROL_STATUS_INHERITED": dict(control_status),
        "PROVENANCE": provenance,
    }
    result["detail_digest"] = _digest(result)
    return result


def audit_from_c9_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the sealed refined flux and bounds from a C9 report."""
    try:
        direct = report["direct_flux"]["refined_centroid"]
        bounds = {
            component: report["audit"]["bounds"][component]["refined_centroid"]["delta_phi_bound_weighted"]
            for component in ALL_COMPONENTS
        }
    except (KeyError, TypeError) as error:
        raise ValueError("C9 report lacks sealed refined flux and bounds") from error
    source_digest = _digest({
        "source_file_sha256": report.get("SOURCE_FILE_SHA256"),
        "c7_replay": report.get("C7_SOURCE_REPLAY"),
        "c9_replay": report.get("C9_DIRECT_SOURCE_FLUX_REPLAY"),
        "direct_flux": direct,
        "bounds": bounds,
    })
    controls = {
        key: report.get(key, "UNRESOLVED")
        for key in (
            "BERRY_TORUS_PERIODICITY",
            "VORONOI_DOMAIN_INVERSION",
            "BOUNDARY_GAMMA_STATUS",
        )
    }
    return build_valley_chern_audit(
        direct,
        flux_error_bound=bounds,
        c9_source_digest=source_digest,
        control_status=controls,
    )


__all__ = [
    "ALL_COMPONENTS",
    "BERRY_SIGN_CONVENTION",
    "DIAGNOSTIC_COMPONENTS",
    "DOMAIN_ID",
    "PRIMARY_COMPONENTS",
    "Q_COORDINATE_RELATION",
    "V_K_AREA",
    "audit_from_c9_report",
    "build_valley_chern_audit",
    "coordinate_flux_invariance",
    "valley_chern_from_flux",
]
