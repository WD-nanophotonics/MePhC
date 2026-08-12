"""Capability queries and semantic guards for deformation-aware workflows."""

from __future__ import annotations

from .deformation import (
    DeformationCapability,
    DeformationField,
    SemanticCapabilityError,
    canonicalize_field,
)


def field_capabilities(field=None, *, verified_symmetry: str | None = None) -> dict[str, object]:
    field = canonicalize_field(field)
    mode = field.capability
    primitive = mode == DeformationCapability.GLOBAL_AFFINE_PERIODIC
    supercell = mode == DeformationCapability.SUPERCELL_PERIODIC and getattr(field, "verified", False)
    return {
        "field_kind": field.metadata().get("kind", "unknown"),
        "capability": mode.value,
        "primitive_reciprocal": primitive,
        "primitive_band": primitive,
        "primitive_berry": primitive,
        "primitive_efs": primitive,
        "supercell_reciprocal": bool(supercell),
        "supercell_band": bool(supercell),
        "primitive_symmetry_reduction": bool(primitive and verified_symmetry),
        "verified_symmetry": verified_symmetry if primitive else None,
        "semantic_label": "primitive" if primitive else ("supercell" if supercell else "local_preview"),
    }


def require_primitive(field, operation: str) -> DeformationField:
    field = canonicalize_field(field)
    field.require(operation)
    return field


def require_supercell(field, operation: str) -> DeformationField:
    field = canonicalize_field(field)
    if field.capability != DeformationCapability.SUPERCELL_PERIODIC:
        raise SemanticCapabilityError(
            f"E_R5_SUPERCELL_REQUIRED: {operation} requires a verified periodic-supercell field"
        )
    field.require(operation, allow_supercell=True)
    return field


__all__ = ["field_capabilities", "require_primitive", "require_supercell"]
