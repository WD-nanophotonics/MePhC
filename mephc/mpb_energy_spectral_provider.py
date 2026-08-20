"""Live MPB provider for the additive full Maxwell E+H representation."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Sequence
from numbers import Real
from typing import Any

import numpy as np

from .mpb_energy_spectral import MPB_ENERGY_EH_REPRESENTATION, adapt_mpb_energy_eh_envelopes
from .mpb_spectral import MPBHEnvelopeSnapshot, _LIVE_PROVENANCE_TOKEN
from .mpb_spectral_provider import _callback_name, _canonical_field, _meep_modules, _spatial_shape, _vector3_tuple

MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION = "mpb_live_energy_eh_v1"


def _positive(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{name} must be a finite positive real number")
    return float(value)


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


@dataclass(frozen=True)
class MPBLiveEnergySpectralProvider:
    geometry: Any
    geometry_lattice: Any
    resolution: int
    num_bands: int
    polarization: Any = None
    default_material: Any = None
    eigensolver_tolerance: float = 1e-7
    deterministic: bool = False
    mesh_size: int = 3
    phase_callback: Callable[..., Any] | None = None
    norm_tolerance: float = 1e-14
    orthogonality_tolerance: float = 1e-10
    kpoint_tolerance: float = 1e-10

    def __post_init__(self) -> None:
        if self.geometry is None or self.geometry_lattice is None:
            raise ValueError("geometry and geometry_lattice must be supplied")
        object.__setattr__(self, "resolution", _positive_int(self.resolution, name="resolution"))
        object.__setattr__(self, "num_bands", _positive_int(self.num_bands, name="num_bands"))
        object.__setattr__(self, "eigensolver_tolerance", _positive(self.eigensolver_tolerance, name="eigensolver_tolerance"))
        object.__setattr__(self, "mesh_size", _positive_int(self.mesh_size, name="mesh_size"))
        if type(self.deterministic) is not bool:
            raise ValueError("deterministic must be bool")
        if self.phase_callback is not None and not callable(self.phase_callback):
            raise ValueError("phase_callback must be callable or None")
        object.__setattr__(self, "norm_tolerance", _positive(self.norm_tolerance, name="norm_tolerance"))
        object.__setattr__(self, "orthogonality_tolerance", _positive(self.orthogonality_tolerance, name="orthogonality_tolerance"))
        object.__setattr__(self, "kpoint_tolerance", _positive(self.kpoint_tolerance, name="kpoint_tolerance"))

    def _build_solver(self, reciprocal_k_point: Any):
        mp, mpb = _meep_modules()
        return mpb.ModeSolver(
            geometry=self.geometry,
            geometry_lattice=self.geometry_lattice,
            k_points=[reciprocal_k_point],
            resolution=self.resolution,
            num_bands=self.num_bands,
            default_material=self.default_material if self.default_material is not None else mp.air,
            tolerance=self.eigensolver_tolerance,
            deterministic=self.deterministic,
            mesh_size=self.mesh_size,
        )

    def solve(self, k_point: Sequence[float]) -> MPBHEnvelopeSnapshot:
        mp, mpb = _meep_modules()
        cartesian = np.asarray(k_point)
        if cartesian.ndim != 1 or cartesian.size not in {2, 3} or cartesian.dtype.kind not in "iuf" or not np.all(np.isfinite(cartesian)):
            raise ValueError("k_point must be a finite real 2D or 3D coordinate")
        z = float(cartesian[2]) if cartesian.size == 3 else 0.0
        public = tuple(float(item) for item in cartesian)
        reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(cartesian[0]), float(cartesian[1]), z), self.geometry_lattice)
        reciprocal_tuple = _vector3_tuple(reciprocal, name="reciprocal k_point")
        spatial_shape = _spatial_shape(self.geometry_lattice, self.resolution)
        solver = self._build_solver(reciprocal)
        polarization = self.polarization if self.polarization is not None else mp.TE
        if self.phase_callback is None:
            solver.run_parity(polarization, False)
        else:
            solver.run_parity(polarization, False, self.phase_callback)
        frequencies = np.asarray(solver.all_freqs)
        if frequencies.ndim != 2 or frequencies.shape[0] < 1 or frequencies.shape[1] != self.num_bands:
            raise RuntimeError("live MPB all_freqs does not match requested band count")
        frequencies = np.asarray(frequencies[0], dtype=float)
        epsilon = np.asarray(solver.get_epsilon(), dtype=float).reshape(spatial_shape)
        e_fields, h_fields = [], []
        for band in range(1, self.num_bands + 1):
            e_raw = solver.get_efield(band, bloch_phase=False)
            h_raw = solver.get_hfield(band, bloch_phase=False)
            for field, name in ((e_raw, "E"), (h_raw, "H")):
                if getattr(field, "bloch_phase", None) is not False:
                    raise RuntimeError(f"live MPB {name} field did not report bloch_phase=False")
                field_k = _vector3_tuple(getattr(field, "kpoint", None), name=f"live {name} field kpoint")
                if not np.allclose(field_k, reciprocal_tuple, rtol=0.0, atol=self.kpoint_tolerance):
                    raise RuntimeError(f"live MPB {name} field kpoint metadata disagrees with solved kpoint")
            e_fields.append(_canonical_field(e_raw, spatial_shape=spatial_shape, band=band))
            h_fields.append(_canonical_field(h_raw, spatial_shape=spatial_shape, band=band))
        e_batch, h_batch = np.stack(e_fields, axis=0), np.stack(h_fields, axis=0)
        provenance = {
            "live_provider": MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION,
            "representation": MPB_ENERGY_EH_REPRESENTATION,
            "solver_settings": {"resolution": self.resolution, "num_bands": self.num_bands, "mesh_size": self.mesh_size, "eigensolver_tolerance": self.eigensolver_tolerance, "deterministic": self.deterministic, "polarization": getattr(polarization, "__name__", None) or str(polarization), "phase_callback": _callback_name(self.phase_callback), "field_extraction": "get_efield/get_hfield(band, bloch_phase=False)", "epsilon_extraction": "get_epsilon() reshaped to spatial grid"},
            "mpb_reciprocal_k_point": list(reciprocal_tuple),
            "field_kpoint_metadata_validated": True,
            "phase_callback_is_gauge_choice": self.phase_callback is not None,
        }
        return adapt_mpb_energy_eh_envelopes(public, frequencies, e_batch, h_batch, epsilon, mpb_k_point=reciprocal_tuple, norm_tolerance=self.norm_tolerance, orthogonality_tolerance=self.orthogonality_tolerance, provenance=provenance, _trusted_live_provenance=_LIVE_PROVENANCE_TOKEN)


def solve_mpb_energy_eh_spectrum(k_point: Sequence[float], *, geometry: Any, geometry_lattice: Any, resolution: int, num_bands: int, polarization: Any = None, default_material: Any = None, eigensolver_tolerance: float = 1e-7, deterministic: bool = False, mesh_size: int = 3, phase_callback: Callable[..., Any] | None = None, norm_tolerance: float = 1e-14, orthogonality_tolerance: float = 1e-10, kpoint_tolerance: float = 1e-10) -> MPBHEnvelopeSnapshot:
    return MPBLiveEnergySpectralProvider(geometry=geometry, geometry_lattice=geometry_lattice, resolution=resolution, num_bands=num_bands, polarization=polarization, default_material=default_material, eigensolver_tolerance=eigensolver_tolerance, deterministic=deterministic, mesh_size=mesh_size, phase_callback=phase_callback, norm_tolerance=norm_tolerance, orthogonality_tolerance=orthogonality_tolerance, kpoint_tolerance=kpoint_tolerance).solve(k_point)


__all__ = ["MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION", "MPBLiveEnergySpectralProvider", "solve_mpb_energy_eh_spectrum"]
