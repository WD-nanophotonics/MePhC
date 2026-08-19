"""Deterministic identity for the continuous geometry handed to MPB.

The identity is derived from actual post-rectification Meep objects and their
geometry lattice. It is not a rasterized field or caller-supplied metadata,
and unsupported geometry/material physics fails closed instead of falling
back to ``repr`` or object identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from numbers import Real
from typing import Any, Iterable, Mapping

import meep as mp


_SCHEMA = "mephc-supercell-geometry/v1"


class GeometryIdentityError(ValueError):
    """Raised when a live Meep geometry cannot be represented safely."""


def _number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise GeometryIdentityError(f"{name} must be a real scalar")
    result = float(value)
    if not math.isfinite(result):
        raise GeometryIdentityError(f"{name} must be finite")
    return result


def _vector(value: Any, *, name: str) -> list[float]:
    try:
        return [
            _number(value.x, name=f"{name}.x"),
            _number(value.y, name=f"{name}.y"),
            _number(value.z, name=f"{name}.z"),
        ]
    except AttributeError as exc:
        raise GeometryIdentityError(f"{name} must be a Meep Vector3") from exc


def _zero_vector(value: Any, *, name: str) -> None:
    components = _vector(value, name=name)
    if any(component != 0.0 for component in components):
        raise GeometryIdentityError(f"{name} must be zero for scalar isotropic material")


def _isotropic_vector(value: Any, *, name: str) -> float:
    components = _vector(value, name=name)
    if not (components[0] == components[1] == components[2]):
        raise GeometryIdentityError(f"{name} must be scalar isotropic")
    return components[0]


def _material(material: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(material, mp.Medium):
        raise GeometryIdentityError(f"{name} must be a Meep Medium")
    try:
        epsilon = _isotropic_vector(material.epsilon_diag, name=f"{name}.epsilon_diag")
        mu = _isotropic_vector(material.mu_diag, name=f"{name}.mu_diag")
        _zero_vector(material.epsilon_offdiag, name=f"{name}.epsilon_offdiag")
        _zero_vector(material.mu_offdiag, name=f"{name}.mu_offdiag")
        for attr in ("E_susceptibilities", "H_susceptibilities"):
            if getattr(material, attr):
                raise GeometryIdentityError(f"{name}.{attr} is dispersive")
        for attr in (
            "E_chi2_diag", "E_chi3_diag", "H_chi2_diag", "H_chi3_diag",
            "D_conductivity_diag", "D_conductivity_offdiag",
            "B_conductivity_diag", "B_conductivity_offdiag",
        ):
            _zero_vector(getattr(material, attr), name=f"{name}.{attr}")
    except AttributeError as exc:
        raise GeometryIdentityError(f"{name} has unsupported material physics") from exc
    return {
        "kind": "isotropic_nondispersive",
        "epsilon": epsilon,
        "mu": mu,
    }


def _lattice(geometry_lattice: Any) -> dict[str, Any]:
    required = ("basis1", "basis2", "basis3", "basis_size", "size")
    try:
        return {
            "basis1": _vector(geometry_lattice.basis1, name="geometry_lattice.basis1"),
            "basis2": _vector(geometry_lattice.basis2, name="geometry_lattice.basis2"),
            "basis3": _vector(geometry_lattice.basis3, name="geometry_lattice.basis3"),
            "basis_size": _vector(geometry_lattice.basis_size, name="geometry_lattice.basis_size"),
            "size": _vector(geometry_lattice.size, name="geometry_lattice.size"),
        }
    except AttributeError as exc:
        raise GeometryIdentityError(
            f"geometry_lattice lacks required fields: {', '.join(required)}"
        ) from exc


def _object(obj: Any, *, index: int) -> dict[str, Any]:
    name = f"objects[{index}]"
    if isinstance(obj, mp.Block):
        return {
            "type": "mp.Block",
            "center": _vector(obj.center, name=f"{name}.center"),
            "size": _vector(obj.size, name=f"{name}.size"),
            "e1": _vector(obj.e1, name=f"{name}.e1"),
            "e2": _vector(obj.e2, name=f"{name}.e2"),
            "e3": _vector(obj.e3, name=f"{name}.e3"),
            "material": _material(obj.material, name=f"{name}.material"),
        }
    if isinstance(obj, mp.Prism):
        return {
            "type": "mp.Prism",
            "center": _vector(obj.center, name=f"{name}.center"),
            "vertices": [_vector(vertex, name=f"{name}.vertices[{i}]") for i, vertex in enumerate(obj.vertices)],
            "height": _number(obj.height, name=f"{name}.height"),
            "axis": _vector(obj.axis, name=f"{name}.axis"),
            "sidewall_angle": _number(obj.sidewall_angle, name=f"{name}.sidewall_angle"),
            "material": _material(obj.material, name=f"{name}.material"),
        }
    if isinstance(obj, mp.Cylinder):
        return {
            "type": "mp.Cylinder",
            "center": _vector(obj.center, name=f"{name}.center"),
            "radius": _number(obj.radius, name=f"{name}.radius"),
            "height": _number(obj.height, name=f"{name}.height"),
            "axis": _vector(obj.axis, name=f"{name}.axis"),
            "material": _material(obj.material, name=f"{name}.material"),
        }
    raise GeometryIdentityError(
        f"{name} has unsupported geometry type {type(obj).__module__}.{type(obj).__name__}"
    )


def _replication(replication: Iterable[Any]) -> list[int]:
    values = list(replication)
    if len(values) != 2 or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
        raise GeometryIdentityError("replication must contain two positive integers")
    return values


def _payload(
    *,
    geometry_lattice: Any,
    geometry: Iterable[Any],
    replication: Iterable[Any],
    default_material: Any,
    periodicity_semantics: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if periodicity_semantics is None:
        periodicity_semantics = {
            "ensure_periodicity": True,
            "authority": "Band._prepare_supercell_geometry",
        }
    if not isinstance(periodicity_semantics, Mapping):
        raise GeometryIdentityError("periodicity_semantics must be a mapping")
    semantics = {}
    for key, value in periodicity_semantics.items():
        if not isinstance(key, str) or not isinstance(value, (str, bool, int, float)):
            raise GeometryIdentityError("periodicity_semantics must be JSON-safe scalars")
        if isinstance(value, float) and not math.isfinite(value):
            raise GeometryIdentityError("periodicity_semantics contains a non-finite float")
        semantics[key] = value
    return {
        "schema": _SCHEMA,
        "replication": _replication(replication),
        "geometry_lattice": _lattice(geometry_lattice),
        "objects": [_object(obj, index=index) for index, obj in enumerate(geometry)],
        "default_material": _material(default_material, name="default_material"),
        "periodicity_semantics": semantics,
    }


@dataclass(frozen=True)
class SupercellGeometryIdentity:
    """Frozen schema, digest, and JSON-safe payload for a continuous MPB geometry."""

    schema: str
    digest: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema != _SCHEMA:
            raise ValueError(f"schema must be { _SCHEMA }")
        if len(self.digest) != 64 or self.digest.lower() != self.digest:
            raise ValueError("digest must be lowercase SHA-256 hex")
        try:
            int(self.digest, 16)
        except ValueError as exc:
            raise ValueError("digest must be lowercase SHA-256 hex") from exc
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a JSON-safe dict")
        if self.payload.get("schema") != self.schema:
            raise ValueError("payload schema must match identity schema")
        try:
            canonical = json.dumps(
                self.payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON-safe") from exc
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if self.digest != expected:
            raise ValueError("digest does not match canonical payload")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "digest": self.digest, "payload": self.payload}


def build_supercell_geometry_identity(
    *,
    geometry_lattice: Any,
    geometry: Iterable[Any],
    replication: Iterable[Any],
    default_material: Any = mp.air,
    periodicity_semantics: Mapping[str, Any] | None = None,
) -> SupercellGeometryIdentity:
    """Build a canonical identity from the actual objects handed to MPB."""
    payload = _payload(
        geometry_lattice=geometry_lattice,
        geometry=geometry,
        replication=replication,
        default_material=default_material,
        periodicity_semantics=periodicity_semantics,
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return SupercellGeometryIdentity(schema=_SCHEMA, digest=digest, payload=payload)


identity_from_geometry = build_supercell_geometry_identity


__all__ = [
    "GeometryIdentityError",
    "SupercellGeometryIdentity",
    "build_supercell_geometry_identity",
    "identity_from_geometry",
]
