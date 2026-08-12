"""Small public R5 orchestration helpers kept separate from legacy records."""

from __future__ import annotations

import numpy as np

from .capabilities import field_capabilities, require_primitive, require_supercell
from .deformation import (
    DeformationCapability,
    DeformationField,
    canonicalize_field,
)
from .deformation_geometry import replicated_rigid_pattern


def primitive_guard(field, operation: str):
    return require_primitive(field, operation)


def supercell_metadata(field, operation: str = "supercell reciprocal object") -> dict[str, object]:
    field = require_supercell(field, operation)
    return {
        "semantic_label": "supercell",
        "capability": field.capability.value,
        "direct_basis": np.asarray(field.direct_basis, dtype=float).tolist(),
        "reciprocal_basis_no_2pi": np.asarray(field.reciprocal_basis, dtype=float).tolist(),
        "primitive_labels_allowed": False,
        "primitive_symmetry_reduction": False,
        "field_fingerprint": field.fingerprint(),
    }


def finite_patch(pattern, lattice, field, replication=(3, 3)):
    """Return preview-only rigid motifs under any local field."""
    field = canonicalize_field(field)
    return replicated_rigid_pattern(pattern, lattice, replication=replication, field=field)


def record_identity(field, *, reference_lattice, replication=(1, 1), motif_policy="rigid_local_cartesian",
                    interpolation_policy=None) -> dict[str, object]:
    """Return stable provenance, rejecting anonymous callable persistence."""
    field = canonicalize_field(field)
    if not field.stable_identity:
        raise ValueError("E_R5_UNSTABLE_CALLABLE: field needs explicit stable_id before persistent record writes")
    metadata = field.metadata()
    legacy_collapse = metadata.get("kind") in {"zero", "constant_affine"}
    return {
        "schema": "mephc.r5.record_identity.v1",
        "namespace": "legacy_global_affine" if legacy_collapse else "r5_deformation_field",
        "legacy_identity_collapse": legacy_collapse,
        "field_kind": metadata.get("kind"),
        "field_fingerprint": field.fingerprint(),
        "field": metadata,
        "reference_lattice": reference_lattice.metadata(),
        "replication": [int(replication[0]), int(replication[1])],
        "motif_policy": motif_policy,
        "capability": field.capability.value,
        "interpolation_policy": interpolation_policy or metadata.get("interpolation", "analytic_or_exact"),
    }


__all__ = ["field_capabilities", "finite_patch", "primitive_guard", "record_identity", "supercell_metadata"]
