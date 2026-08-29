"""Explicit E8B affine geometry-state adapter for the E10F acquisition."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import numpy as np

from audit.e8b.e8b_geometry import solver_geometry, state
from mephc.local_affine_state_provider import (
    canonical_local_affine_state_identity,
    digest_local_affine_state_identity,
)


MODEL_ID = "E8B_TWO_INCLUSION_AREA_PRESERVING_AFFINE_V1"
REFERENCE_CELL_ID = "E8B_TWO_INCLUSION_REFERENCE_FRACTIONAL_CELL_V1"
ANCHOR_DIGESTS = {
    -0.02: "463f20e9719bd23e59eb4f4c5facfd56388c6c51a6d0b8ed67af1164b8e5cf12",
    0.0: "490de1f8197dbd5117dfec5d3bf2e4de4dcfb28480b6e5a195658d7c9b42954a",
    0.02: "5f81cab8c65ad7e66b1656c79b964a919947b68fade39a77458e125144cdd720",
}


def geometry_anchor_status() -> bool:
    return all(state(s)["geometry_digest"] == digest for s, digest in ANCHOR_DIGESTS.items())


@dataclass(frozen=True)
class AffineGeometryState:
    model_id: str
    reference_cell_id: str
    q: tuple[float, float]
    s: float
    F_s: tuple[tuple[float, float], tuple[float, float]]
    A_s: tuple[tuple[float, float], tuple[float, float]]
    derived_kappa: tuple[float, float]
    geometry_digest: str
    geometry: tuple[Any, ...]
    geometry_lattice: Any

    resolution: int = 64
    num_bands: int = 6
    polarization: str = "TM"
    eigensolver_tolerance: float = 1e-7
    mesh_size: int = 3
    deterministic: bool = True
    h_representation: str = "mpb_periodic_h_l2_v1"
    bloch_phase_excluded: bool = True
    component_basis: str = "LAB_CARTESIAN"
    mu_contract: str = "MU1_NONMAGNETIC"
    orientation_sign: int = 1
    fractional_material_indexing_identity: str = "SAME_FRACTIONAL_IX_IY_MATERIAL_COORDINATES"
    reference_cell_identity: str = REFERENCE_CELL_ID
    bloch_phase_convention: str = "EXCLUDED_PERIODIC_H_ENVELOPE"

    @property
    def public_q(self) -> tuple[float, float]:
        return self.q


def make_state(q: tuple[float, float], s: float) -> AffineGeometryState:
    raw = state(float(s))
    q_array = np.asarray(q, dtype=float)
    A = np.asarray(raw["A"], dtype=float)
    if q_array.shape != (2,) or not np.all(np.isfinite(q_array)):
        raise ValueError("public q must be a finite 2D vector")
    geometry, lattice = solver_geometry(raw)
    return AffineGeometryState(
        MODEL_ID, REFERENCE_CELL_ID, tuple(float(x) for x in q_array), float(s),
        tuple(tuple(float(x) for x in row) for row in raw["F"]),
        tuple(tuple(float(x) for x in row) for row in raw["A"]),
        tuple(float(x) for x in (A.T @ q_array)), raw["geometry_digest"],
        tuple(geometry), lattice,
    )


def canonical_state_identity(spec: AffineGeometryState, *, resolution: int = 64) -> dict[str, Any]:
    return canonical_local_affine_state_identity(spec, resolution=resolution)


def digest_state_identity(identity: dict[str, Any]) -> str:
    return digest_local_affine_state_identity(identity)
