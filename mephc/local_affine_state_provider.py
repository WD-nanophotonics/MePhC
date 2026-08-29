"""Narrow live bridge from an explicit affine state to one MPB H solve."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .mpb_spectral_provider import MPBLiveSpectralProvider


class LocalAffineProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalAffineStateProvider:
    resolution: int = 64
    num_bands: int = 6
    eigensolver_tolerance: float = 1e-7
    mesh_size: int = 3
    deterministic: bool = True
    polarization: Any = None
    default_material: Any = None

    def solve(self, state: Any):
        if state.model_id != "E8B_TWO_INCLUSION_AREA_PRESERVING_AFFINE_V1":
            raise LocalAffineProviderError("MODEL_ID_MISMATCH")
        if state.reference_cell_id != "E8B_TWO_INCLUSION_REFERENCE_FRACTIONAL_CELL_V1":
            raise LocalAffineProviderError("REFERENCE_CELL_ID_MISMATCH")
        A = np.asarray(state.A_s, dtype=float)
        expected = A.T @ np.asarray(state.q, dtype=float)
        if not np.allclose(expected, state.derived_kappa, rtol=0.0, atol=1e-14):
            raise LocalAffineProviderError("LOCAL_AFFINE_KAPPA_BINDING_MISMATCH")
        provider = MPBLiveSpectralProvider(
            geometry=list(state.geometry), geometry_lattice=state.geometry_lattice,
            resolution=self.resolution, num_bands=self.num_bands,
            polarization=self.polarization, default_material=self.default_material,
            eigensolver_tolerance=self.eigensolver_tolerance, deterministic=self.deterministic,
            mesh_size=self.mesh_size, phase_callback=None,
        )
        snapshot = provider.solve(state.q)
        reciprocal = snapshot.provenance.get("mpb_reciprocal_k_point")
        if reciprocal is None or len(reciprocal) != 3 or not np.allclose(reciprocal[:2], expected, rtol=0.0, atol=1e-9) or abs(float(reciprocal[2])) > 1e-12:
            raise LocalAffineProviderError("LOCAL_AFFINE_KAPPA_BINDING_MISMATCH")
        if snapshot.provenance.get("representation") != "mpb_periodic_h_l2_v1":
            raise LocalAffineProviderError("PERIODIC_H_REPRESENTATION_MISMATCH")
        return snapshot


__all__ = ["LocalAffineStateProvider", "LocalAffineProviderError"]
