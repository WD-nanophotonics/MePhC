"""Generic local-affine provider boundary and immutable result binding."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

import numpy as np

from .mpb_spectral import MPBHEnvelopeSnapshot
from .mpb_spectral_provider import MPBLiveSpectralProvider, _spatial_shape


LOCAL_AFFINE_H_REPRESENTATION = "mpb_periodic_h_l2_v1"
LOCAL_AFFINE_COMPONENT_ORDER = "supplied final axis order"
LOCAL_AFFINE_COMPONENT_BASIS = "LAB_CARTESIAN"
LOCAL_AFFINE_MU_CONTRACT = "MU1_NONMAGNETIC"
LOCAL_AFFINE_ORIENTATION_SIGN = 1
LOCAL_AFFINE_FRACTIONAL_INDEXING = "SAME_FRACTIONAL_IX_IY_MATERIAL_COORDINATES"
LOCAL_AFFINE_BLOCH_CONVENTION = "EXCLUDED_PERIODIC_H_ENVELOPE"


class LocalAffineProviderError(RuntimeError):
    """Raised when a local-affine identity or provider result is unsafe."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _state_value(state: Any, name: str, *aliases: str) -> Any:
    for candidate in (name, *aliases):
        if hasattr(state, candidate):
            return getattr(state, candidate)
    raise LocalAffineProviderError(f"LOCAL_AFFINE_STATE_FIELD_MISSING:{name}")


def _matrix(value: Any, *, name: str) -> list[list[float]]:
    array = np.asarray(value, dtype=float)
    if array.shape != (2, 2) or not np.all(np.isfinite(array)):
        raise LocalAffineProviderError(f"LOCAL_AFFINE_STATE_FIELD_INVALID:{name}")
    return [[float(item) for item in row] for row in array]


def _vector(value: Any, *, name: str, size: int = 2) -> list[float]:
    array = np.asarray(value, dtype=float)
    if array.shape != (size,) or not np.all(np.isfinite(array)):
        raise LocalAffineProviderError(f"LOCAL_AFFINE_STATE_FIELD_INVALID:{name}")
    return [float(item) for item in array]


def _contract_value(state: Any, name: str, default: Any) -> Any:
    value = getattr(state, name, default)
    if value != default:
        raise LocalAffineProviderError(f"LOCAL_AFFINE_STATE_CONTRACT_MISMATCH:{name}")
    return value


def canonical_local_affine_state_identity(state: Any, *, resolution: int = 64,
                                           num_bands: int = 6,
                                           polarization_identity: str = "TM",
                                           eigensolver_tolerance: float = 1e-7,
                                           mesh_size: int = 3,
                                           deterministic: bool = True) -> dict[str, Any]:
    """Build the one identity shared by adapter, provider, and acquisition."""
    identity = {
        "model_id": str(_state_value(state, "model_id")),
        "reference_cell_id": str(_state_value(state, "reference_cell_id")),
        "public_q": _vector(_state_value(state, "public_q", "q"), name="public_q"),
        "s": float(_state_value(state, "s")),
        "F_s": _matrix(_state_value(state, "F_s"), name="F_s"),
        "A_s": _matrix(_state_value(state, "A_s"), name="A_s"),
        "derived_kappa": _vector(_state_value(state, "derived_kappa"), name="derived_kappa"),
        "geometry_digest": str(_state_value(state, "geometry_digest")),
        "resolution": int(resolution),
        "num_bands": int(num_bands),
        "polarization": polarization_identity,
        "eigensolver_tolerance": float(eigensolver_tolerance),
        "mesh_size": int(mesh_size),
        "deterministic": bool(deterministic),
        "h_representation": _contract_value(state, "h_representation", LOCAL_AFFINE_H_REPRESENTATION),
        "bloch_phase_excluded": _contract_value(state, "bloch_phase_excluded", True),
        "component_basis": _contract_value(state, "component_basis", LOCAL_AFFINE_COMPONENT_BASIS),
        "mu_contract": _contract_value(state, "mu_contract", LOCAL_AFFINE_MU_CONTRACT),
        "orientation_sign": _contract_value(state, "orientation_sign", LOCAL_AFFINE_ORIENTATION_SIGN),
        "fractional_material_indexing_identity": _contract_value(
            state, "fractional_material_indexing_identity", LOCAL_AFFINE_FRACTIONAL_INDEXING),
        "reference_cell_identity": str(_state_value(state, "reference_cell_identity")),
        "bloch_phase_convention": _contract_value(state, "bloch_phase_convention", LOCAL_AFFINE_BLOCH_CONVENTION),
    }
    if identity["reference_cell_id"] != identity["reference_cell_identity"]:
        raise LocalAffineProviderError("REFERENCE_CELL_IDENTITY_MISMATCH:reference_cell_identity")
    for name, expected in (("resolution", int(resolution)), ("num_bands", int(num_bands)),
                           ("polarization", polarization_identity), ("mesh_size", int(mesh_size)),
                           ("deterministic", bool(deterministic))):
        if hasattr(state, name) and getattr(state, name) != expected:
            raise LocalAffineProviderError(f"LOCAL_AFFINE_STATE_CONTRACT_MISMATCH:{name}")
    if hasattr(state, "eigensolver_tolerance") and float(getattr(state, "eigensolver_tolerance")) != float(eigensolver_tolerance):
        raise LocalAffineProviderError("LOCAL_AFFINE_STATE_CONTRACT_MISMATCH:eigensolver_tolerance")
    if not math.isfinite(identity["s"]) or not math.isfinite(identity["eigensolver_tolerance"]):
        raise LocalAffineProviderError("LOCAL_AFFINE_STATE_NONFINITE")
    return identity


def digest_local_affine_state_identity(identity: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(dict(identity))).hexdigest()


def local_affine_reference_cell_contract(state: Any, *, spatial_shape: tuple[int, int],
                                         identity: Mapping[str, Any],
                                         lattice_size: tuple[float, float] | None = None) -> dict[str, Any]:
    if lattice_size is None:
        lattice_size = (float(spatial_shape[0]) / identity["resolution"],
                        float(spatial_shape[1]) / identity["resolution"])
    expected_shape = np.asarray(lattice_size, dtype=float) * identity["resolution"]
    if expected_shape.shape != (2,) or not np.all(np.isfinite(expected_shape)):
        raise LocalAffineProviderError("REFERENCE_CELL_LATTICE_SIZE_INVALID")
    if not np.allclose(expected_shape, spatial_shape, rtol=0.0, atol=1e-12):
        raise LocalAffineProviderError("REFERENCE_CELL_LATTICE_SIZE_MISMATCH")
    return {
        "representation": identity["h_representation"],
        "bloch_phase_excluded": identity["bloch_phase_excluded"],
        "resolution": identity["resolution"],
        "spatial_shape": [int(spatial_shape[0]), int(spatial_shape[1])],
        "lattice_size": [float(lattice_size[0]), float(lattice_size[1])],
        "component_order": LOCAL_AFFINE_COMPONENT_ORDER,
        "component_basis": identity["component_basis"],
        "mu_contract": identity["mu_contract"],
        "orientation_sign": identity["orientation_sign"],
        "fractional_material_indexing_identity": identity["fractional_material_indexing_identity"],
        "reference_cell_identity": identity["reference_cell_identity"],
    }


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _metadata(snapshot: MPBHEnvelopeSnapshot) -> dict[str, Any]:
    result = dict(snapshot.provenance)
    caller = _mapping(result.get("caller_provenance"))
    if caller:
        result.update(caller)
    nested = _mapping(result.get("representation_provenance"))
    if nested:
        result.update(nested)
    settings = _mapping(result.get("solver_settings"))
    if settings:
        result.update(settings)
    contract = _mapping(result.get("local_affine_reference_cell_contract"))
    if contract:
        result.update(contract)
    return result


def _validate_reciprocal(snapshot: MPBHEnvelopeSnapshot, expected: tuple[float, float]) -> None:
    provenance = _mapping(snapshot.provenance)
    if provenance is None or "mpb_k_point" not in provenance:
        raise LocalAffineProviderError("CANONICAL_RECIPROCAL_METADATA_MISSING")
    top_level = np.asarray(provenance["mpb_k_point"], dtype=float)
    if top_level.shape != (3,) or not np.all(np.isfinite(top_level)):
        raise LocalAffineProviderError("CANONICAL_RECIPROCAL_METADATA_INVALID")
    if not np.allclose(top_level[:2], expected, rtol=0.0, atol=1e-9) or abs(float(top_level[2])) > 1e-12:
        raise LocalAffineProviderError("CANONICAL_RECIPROCAL_METADATA_MISMATCH")
    caller = _mapping(provenance.get("caller_provenance"))
    if caller is not None and "mpb_reciprocal_k_point" in caller:
        detail = np.asarray(caller["mpb_reciprocal_k_point"], dtype=float)
        if detail.shape != (3,) or not np.all(np.isfinite(detail)) or not np.allclose(detail, top_level, rtol=0.0, atol=1e-9):
            raise LocalAffineProviderError("CALLER_RECIPROCAL_METADATA_MISMATCH")


def _validate_snapshot(snapshot: MPBHEnvelopeSnapshot, *, expected_shape: tuple[int, int],
                       identity: Mapping[str, Any], expected_contract: Mapping[str, Any]) -> None:
    if not isinstance(snapshot, MPBHEnvelopeSnapshot):
        raise LocalAffineProviderError("PROVIDER_RESULT_TYPE_MISMATCH")
    metadata = _metadata(snapshot)
    provenance = _mapping(snapshot.provenance)
    if provenance is None:
        raise LocalAffineProviderError("PROVIDER_RESULT_PROVENANCE_MISSING")
    required = ("representation", "spatial_shape", "component_count", "component_order",
                "periodic_h_envelope", "bloch_phase_excluded", "mpb_k_point")
    if any(key not in provenance for key in required):
        raise LocalAffineProviderError("PROVIDER_RESULT_MANDATORY_METADATA_MISSING")
    caller = _mapping(provenance.get("caller_provenance"))
    settings = _mapping(provenance.get("solver_settings"))
    if settings is None and caller is not None:
        settings = _mapping(caller.get("solver_settings"))
    if settings is None or "resolution" not in settings:
        raise LocalAffineProviderError("PROVIDER_RESULT_SOLVER_RESOLUTION_MISSING")
    augmented_contract = snapshot.to_dict()["provenance"].get("local_affine_reference_cell_contract")
    if augmented_contract is not None and augmented_contract != dict(expected_contract):
        raise LocalAffineProviderError("PROVIDER_RESULT_REFERENCE_CELL_CONTRACT_MISMATCH")
    expected = {
        "representation": identity["h_representation"],
        "periodic_h_envelope": True,
        "bloch_phase_excluded": True,
        "component_count": 3,
        "spatial_shape": expected_shape,
        "component_order": LOCAL_AFFINE_COMPONENT_ORDER,
        "component_basis": identity["component_basis"],
        "mu_contract": identity["mu_contract"],
        "orientation_sign": identity["orientation_sign"],
        "resolution": identity["resolution"],
    }
    if snapshot.component_count != 3 or tuple(snapshot.spatial_shape) != expected_shape:
        raise LocalAffineProviderError("PROVIDER_RESULT_SHAPE_MISMATCH")
    for key, wanted in expected.items():
        observed = tuple(metadata[key]) if key == "spatial_shape" and key in metadata else metadata.get(key)
        if key in metadata and observed != wanted:
            raise LocalAffineProviderError(f"PROVIDER_RESULT_{key.upper()}_MISMATCH")
    if tuple(metadata.get("spatial_shape", expected["spatial_shape"])) != expected["spatial_shape"]:
        raise LocalAffineProviderError("PROVIDER_RESULT_SPATIAL_SHAPE_MISMATCH")
    if "local_affine_state_identity" in metadata and metadata["local_affine_state_identity"] != dict(identity):
        raise LocalAffineProviderError("PROVIDER_RESULT_STATE_IDENTITY_MISMATCH")
    if "local_affine_state_identity_sha256" in metadata and metadata["local_affine_state_identity_sha256"] != digest_local_affine_state_identity(identity):
        raise LocalAffineProviderError("PROVIDER_RESULT_STATE_IDENTITY_DIGEST_MISMATCH")
    _validate_reciprocal(snapshot, tuple(float(item) for item in identity["derived_kappa"]))
    frequencies = np.asarray(snapshot.frequencies, dtype=float)
    if frequencies.ndim != 1 or not np.all(np.isfinite(frequencies)):
        raise LocalAffineProviderError("PROVIDER_RESULT_FREQUENCIES_NONFINITE")
    for vector in snapshot.normalized_vectors:
        values = np.asarray(vector, dtype=np.complex128)
        if not np.all(np.isfinite(values)):
            raise LocalAffineProviderError("PROVIDER_RESULT_NORMALIZED_VECTOR_NONFINITE")
        norm = float(np.linalg.norm(values))
        if not math.isfinite(norm) or not np.isclose(norm, 1.0, rtol=0.0, atol=1e-10):
            raise LocalAffineProviderError("PROVIDER_RESULT_NORMALIZED_VECTOR_NONUNIT")


@dataclass(frozen=True)
class LocalAffineStateProvider:
    resolution: int = 64
    num_bands: int = 6
    eigensolver_tolerance: float = 1e-7
    mesh_size: int = 3
    deterministic: bool = True
    polarization: Any = None
    polarization_identity: str | None = None
    default_material: Any = None

    def solve(self, state: Any) -> MPBHEnvelopeSnapshot:
        if self.polarization is None:
            raise LocalAffineProviderError("SOLVER_POLARIZATION_HANDLE_MISSING")
        if not isinstance(self.polarization_identity, str) or not self.polarization_identity.strip():
            raise LocalAffineProviderError("POLARIZATION_IDENTITY_MISSING")
        state_polarization = _state_value(state, "polarization")
        if state_polarization != self.polarization_identity:
            raise LocalAffineProviderError("STATE_POLARIZATION_IDENTITY_MISMATCH")
        identity = canonical_local_affine_state_identity(
            state, resolution=self.resolution, num_bands=self.num_bands,
            polarization_identity=self.polarization_identity,
            eigensolver_tolerance=self.eigensolver_tolerance,
            mesh_size=self.mesh_size, deterministic=self.deterministic,
        )
        A = np.asarray(identity["A_s"], dtype=float)
        q = np.asarray(identity["public_q"], dtype=float)
        expected_kappa = A.T @ q
        if not np.allclose(expected_kappa, identity["derived_kappa"], rtol=0.0, atol=1e-14):
            raise LocalAffineProviderError("LOCAL_AFFINE_KAPPA_BINDING_MISMATCH:derived_kappa")
        lattice = _state_value(state, "geometry_lattice")
        expected_shape = _spatial_shape(lattice, self.resolution)
        size = getattr(lattice, "size", None)
        if size is None or not all(hasattr(size, axis) for axis in ("x", "y")):
            raise LocalAffineProviderError("REFERENCE_CELL_LATTICE_SIZE_MISSING")
        lattice_size = (float(size.x), float(size.y))
        contract = local_affine_reference_cell_contract(
            state, spatial_shape=expected_shape, identity=identity, lattice_size=lattice_size)
        provider = MPBLiveSpectralProvider(
            geometry=_state_value(state, "geometry"), geometry_lattice=lattice,
            resolution=self.resolution, num_bands=self.num_bands,
            polarization=self.polarization, default_material=self.default_material,
            eigensolver_tolerance=self.eigensolver_tolerance, deterministic=self.deterministic,
            mesh_size=self.mesh_size, phase_callback=None,
        )
        snapshot = provider.solve(tuple(identity["public_q"]))
        _validate_snapshot(snapshot, expected_shape=expected_shape, identity=identity, expected_contract=contract)
        provenance = dict(snapshot.provenance)
        provenance.update({
            "local_affine_state_identity": dict(identity),
            "local_affine_state_identity_sha256": digest_local_affine_state_identity(identity),
            "local_affine_reference_cell_contract": contract,
            "local_affine_solver_polarization_identity": self.polarization_identity,
        })
        return MPBHEnvelopeSnapshot(
            k_point=snapshot.k_point, frequencies=snapshot.frequencies, h_fields=snapshot.h_fields,
            raw_norms=snapshot.raw_norms, normalized_vectors=snapshot.normalized_vectors,
            gram_matrix=snapshot.gram_matrix, max_normalization_error=snapshot.max_normalization_error,
            max_off_diagonal_gram=snapshot.max_off_diagonal_gram,
            orthogonality_status=snapshot.orthogonality_status,
            normalization_tolerance=snapshot.normalization_tolerance,
            orthogonality_tolerance=snapshot.orthogonality_tolerance,
            raw_eigenstates=snapshot.raw_eigenstates, provenance=provenance, e_fields=snapshot.e_fields,
        )


__all__ = [
    "LOCAL_AFFINE_H_REPRESENTATION", "LocalAffineStateProvider", "LocalAffineProviderError",
    "canonical_local_affine_state_identity", "digest_local_affine_state_identity",
    "local_affine_reference_cell_contract",
]
