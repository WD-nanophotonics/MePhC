"""Live MPB periodic H-envelope spectral provider.

The provider owns only one-k-point MPB solving and explicit H-envelope
extraction. It delegates normalization and RawEigenstate conversion to the
E6A adapter and does not compute observables.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
import math
from numbers import Real
from typing import Any

import numpy as np

from .mpb_spectral import MPBHEnvelopeSnapshot, _LIVE_PROVENANCE_TOKEN, adapt_mpb_h_envelopes


MPB_LIVE_H_PROVIDER_REPRESENTATION = "mpb_live_periodic_h_l2_v1"


def _meep_modules():
    try:
        import meep as mp
        from meep import mpb
    except ImportError as exc:
        raise RuntimeError("live MPB provider requires meep and meep.mpb in the canonical environment") from exc
    return mp, mpb


def _positive(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive real number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a finite positive real number")
    return result


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _cartesian_point(value: Any, *, name: str) -> tuple[float, ...]:
    array = np.asarray(value)
    if array.ndim != 1 or array.size not in {2, 3} or array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must be a finite real 2D or 3D coordinate")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite")
    return tuple(float(item) for item in array)


def _vector3_tuple(value: Any, *, name: str) -> tuple[float, float, float]:
    if not all(hasattr(value, axis) for axis in ("x", "y", "z")):
        raise ValueError(f"{name} must expose x, y, and z coordinates")
    result = tuple(float(getattr(value, axis)) for axis in ("x", "y", "z"))
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain finite coordinates")
    return result


def _spatial_shape(lattice: Any, resolution: int) -> tuple[int, int]:
    size = getattr(lattice, "size", None)
    if size is None or not all(hasattr(size, axis) for axis in ("x", "y")):
        raise ValueError("geometry_lattice must expose a 2D size")
    values = np.asarray([float(size.x), float(size.y)], dtype=float)
    scaled = values * resolution
    rounded = np.rint(scaled).astype(int)
    if not np.all(np.isfinite(values)) or np.any(values <= 0) or not np.allclose(scaled, rounded, rtol=0.0, atol=1e-12) or np.any(rounded < 1):
        raise ValueError("geometry_lattice size and resolution must define positive integral grid dimensions")
    return int(rounded[0]), int(rounded[1])


def _callback_name(callback: Callable[..., Any] | None) -> str | None:
    if callback is None:
        return None
    return f"{getattr(callback, '__module__', type(callback).__module__)}.{getattr(callback, '__qualname__', type(callback).__qualname__)}"


def _canonical_field(field: Any, *, spatial_shape: tuple[int, int], band: int) -> np.ndarray:
    array = np.asarray(field)
    if array.dtype.kind not in "iufc" or not np.all(np.isfinite(array)):
        raise ValueError(f"live H field for band {band} must be finite numeric data")
    nx, ny = spatial_shape
    if array.ndim == 4 and array.shape == (nx, ny, 1, 3):
        result = np.asarray(array[:, :, 0, :], dtype=np.complex128)
    elif array.ndim == 3 and array.shape == (nx, ny, 3):
        result = np.asarray(array, dtype=np.complex128)
    else:
        raise ValueError(
            f"live H field for band {band} has unsupported shape {array.shape}; "
            f"expected {(nx, ny, 1, 3)} or {(nx, ny, 3)}"
        )
    result = np.array(result, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class MPBLiveSpectralProvider:
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
        if self.geometry is None:
            raise ValueError("geometry must be supplied")
        if self.geometry_lattice is None:
            raise ValueError("geometry_lattice must be supplied")
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

    def _settings(self, *, reciprocal_k_point: tuple[float, float, float]) -> Mapping[str, Any]:
        return {
            "representation": MPB_LIVE_H_PROVIDER_REPRESENTATION,
            "mpb_reciprocal_k_point": list(reciprocal_k_point),
            "resolution": self.resolution,
            "num_bands": self.num_bands,
            "mesh_size": self.mesh_size,
            "eigensolver_tolerance": self.eigensolver_tolerance,
            "deterministic": self.deterministic,
            "polarization": getattr(self.polarization, "__name__", None) or str(self.polarization),
            "default_material_type": type(self.default_material).__name__ if self.default_material is not None else "mp.air",
            "phase_callback": _callback_name(self.phase_callback),
            "field_extraction": "get_hfield(band, bloch_phase=False)",
            "live_mpb_extraction_validated": True,
        }

    def _build_solver(self, reciprocal_k_point: Any):
        mp, mpb = _meep_modules()
        polarization = self.polarization if self.polarization is not None else mp.TE
        default_material = self.default_material if self.default_material is not None else mp.air
        return mpb.ModeSolver(
            geometry=self.geometry,
            geometry_lattice=self.geometry_lattice,
            k_points=[reciprocal_k_point],
            resolution=self.resolution,
            num_bands=self.num_bands,
            default_material=default_material,
            tolerance=self.eigensolver_tolerance,
            deterministic=self.deterministic,
            mesh_size=self.mesh_size,
        )

    def solve(self, k_point: Sequence[float]) -> MPBHEnvelopeSnapshot:
        mp, _ = _meep_modules()
        cartesian = _cartesian_point(k_point, name="k_point")
        z = cartesian[2] if len(cartesian) == 3 else 0.0
        public_k_point = tuple(cartesian)
        reciprocal = mp.cartesian_to_reciprocal(
            mp.Vector3(cartesian[0], cartesian[1], z),
            self.geometry_lattice,
        )
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
            raise RuntimeError("live MPB all_freqs does not match the requested one-k-point band count")
        frequencies = np.asarray(frequencies[0], dtype=float)
        if not np.all(np.isfinite(frequencies)):
            raise RuntimeError("live MPB frequencies are not finite")
        fields = []
        for band in range(1, self.num_bands + 1):
            field = solver.get_hfield(band, bloch_phase=False)
            if getattr(field, "bloch_phase", None) is not False:
                raise RuntimeError("live MPB H field did not report bloch_phase=False")
            field_k_point = _vector3_tuple(getattr(field, "kpoint", None), name="live H field kpoint")
            if not np.allclose(field_k_point, reciprocal_tuple, rtol=0.0, atol=self.kpoint_tolerance):
                raise RuntimeError("live MPB H field kpoint metadata disagrees with the solved reciprocal kpoint")
            fields.append(_canonical_field(field, spatial_shape=spatial_shape, band=band))
        h_batch = np.stack(fields, axis=0)
        provenance = {
            "live_provider": MPB_LIVE_H_PROVIDER_REPRESENTATION,
            "solver_settings": self._settings(reciprocal_k_point=reciprocal_tuple),
            "mpb_reciprocal_k_point": list(reciprocal_tuple),
            "field_kpoint_metadata_validated": True,
            "phase_callback_is_gauge_choice": self.phase_callback is not None,
        }
        return adapt_mpb_h_envelopes(
            public_k_point,
            frequencies,
            h_batch,
            mpb_k_point=reciprocal_tuple,
            norm_tolerance=self.norm_tolerance,
            orthogonality_tolerance=self.orthogonality_tolerance,
            provenance=provenance,
            _trusted_live_provenance=_LIVE_PROVENANCE_TOKEN,
        )


def solve_mpb_h_spectrum(
    k_point: Sequence[float],
    *,
    geometry: Any,
    geometry_lattice: Any,
    resolution: int,
    num_bands: int,
    polarization: Any = None,
    default_material: Any = None,
    eigensolver_tolerance: float = 1e-7,
    deterministic: bool = False,
    mesh_size: int = 3,
    phase_callback: Callable[..., Any] | None = None,
    norm_tolerance: float = 1e-14,
    orthogonality_tolerance: float = 1e-10,
    kpoint_tolerance: float = 1e-10,
) -> MPBHEnvelopeSnapshot:
    provider = MPBLiveSpectralProvider(
        geometry=geometry,
        geometry_lattice=geometry_lattice,
        resolution=resolution,
        num_bands=num_bands,
        polarization=polarization,
        default_material=default_material,
        eigensolver_tolerance=eigensolver_tolerance,
        deterministic=deterministic,
        mesh_size=mesh_size,
        phase_callback=phase_callback,
        norm_tolerance=norm_tolerance,
        orthogonality_tolerance=orthogonality_tolerance,
        kpoint_tolerance=kpoint_tolerance,
    )
    return provider.solve(k_point)


__all__ = [
    "MPB_LIVE_H_PROVIDER_REPRESENTATION",
    "MPBLiveSpectralProvider",
    "solve_mpb_h_spectrum",
]
