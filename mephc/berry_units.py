"""Central coordinate/unit contract for local Berry curvature values."""
from __future__ import annotations

import math
from numbers import Real
from typing import Any, Mapping

OMEGA_Q = "OMEGA_Q"
OMEGA_PHYS_OVER_A2 = "OMEGA_PHYS_OVER_A2"
Q_COORDINATE_SPACE = "q=k_phys*a/(2*pi)"
PHYSICAL_K_COORDINATE_SPACE = "physical_cartesian_k"
_VALID_UNIT_SPACES = frozenset({OMEGA_Q, OMEGA_PHYS_OVER_A2})


def validate_unit_space(value: Any) -> str:
    if not isinstance(value, str) or value not in _VALID_UNIT_SPACES:
        raise ValueError(f"curvature unit space must be one of {sorted(_VALID_UNIT_SPACES)!r}")
    return value


def _finite_real(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite real number")
    return result


def omega_q_to_phys_over_a2(value: Any) -> float:
    """Convert curvature in q coordinates to Omega_k/a^2."""
    return _finite_real(value, "omega_q") / (2.0 * math.pi) ** 2


def omega_phys_over_a2_to_q(value: Any) -> float:
    """Convert Omega_k/a^2 to curvature in q coordinates."""
    return _finite_real(value, "omega_phys_over_a2") * (2.0 * math.pi) ** 2


def convert_curvature(value: Any, source: str, target: str) -> float:
    validate_unit_space(source)
    validate_unit_space(target)
    number = _finite_real(value, "curvature")
    if source == target:
        return number
    if source == OMEGA_Q:
        return omega_q_to_phys_over_a2(number)
    return omega_phys_over_a2_to_q(number)


def curvature_unit_provenance(*, unit_space: str, requested_k_space: str = Q_COORDINATE_SPACE,
                              plaquette_vertex_space: str = Q_COORDINATE_SPACE,
                              signed_area_space: str = Q_COORDINATE_SPACE,
                              conversion_applied: bool | None = None,
                              plaquette_convention: str | None = None,
                              orientation: str | None = None,
                              representation: str | None = None,
                              wilson_phase: float | list[float] | None = None) -> dict[str, Any]:
    validate_unit_space(unit_space)
    if conversion_applied is None:
        conversion_applied = unit_space == OMEGA_PHYS_OVER_A2
    if type(conversion_applied) is not bool:
        raise ValueError("conversion_applied must be a bool")
    result: dict[str, Any] = {
        "curvature_unit_space": unit_space,
        "requested_k_coordinate_space": requested_k_space,
        "plaquette_vertex_coordinate_space": plaquette_vertex_space,
        "signed_area_coordinate_space": signed_area_space,
        "two_pi_squared_conversion_applied": conversion_applied,
        "lattice_period_normalization": "a",
        "coordinate_relation": Q_COORDINATE_SPACE,
    }
    if plaquette_convention is not None:
        result["plaquette_convention"] = plaquette_convention
    if orientation is not None:
        result["orientation"] = orientation
    if representation is not None:
        result["representation_identifier"] = representation
    if wilson_phase is not None:
        result["wilson_phase"] = wilson_phase
    return result


__all__ = [
    "OMEGA_Q", "OMEGA_PHYS_OVER_A2", "Q_COORDINATE_SPACE", "PHYSICAL_K_COORDINATE_SPACE",
    "validate_unit_space", "convert_curvature", "omega_q_to_phys_over_a2",
    "omega_phys_over_a2_to_q", "curvature_unit_provenance",
]
