"""Deterministic, non-pickle codec for periodic-H local-affine snapshots."""
from __future__ import annotations

from collections.abc import Mapping
import io
import json
import math
from typing import Any

import numpy as np

from mephc.eigenspace import RawEigenstate
from mephc.mpb_spectral import MPBHEnvelopeSnapshot


SCHEMA = "mephc-local-affine-periodic-h-snapshot-payload-v1"
_REQUIRED_ARRAY_FIELDS = frozenset({
    "h_fields", "frequencies", "raw_norms", "gram_matrix", "normalized_vectors",
    "raw_eigenstate_vectors", "metadata",
})
_OPTIONAL_ARRAY_FIELDS = frozenset({"e_fields"})
_ALLOWED_ARRAY_FIELDS = _REQUIRED_ARRAY_FIELDS | _OPTIONAL_ARRAY_FIELDS


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _json_safe(value: Any, *, path: str = "metadata") -> Any:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} mapping keys must be strings")
            result[key] = _json_safe(item, path=f"{path}.{key}")
        return result
    if isinstance(value, (tuple, list)):
        return [_json_safe(item, path=f"{path}[]") for item in value]
    raise ValueError(f"{path} contains unsupported value {type(value).__name__}")


def _numeric_array(value: Any, *, name: str, ndim: int | None = None) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind == "O" or array.dtype.kind not in "iufc":
        raise ValueError(f"{name} must be a numeric array")
    if ndim is not None and array.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _metadata_for(snapshot: MPBHEnvelopeSnapshot) -> dict[str, Any]:
    states = []
    for state in snapshot.raw_eigenstates:
        states.append({
            "k_point": list(state.k_point),
            "solver_index": state.solver_index,
            "eigenvalue": state.eigenvalue,
            "metadata": _json_safe(state.metadata, path="raw_eigenstates.metadata"),
        })
    return _json_safe({
        "schema": SCHEMA,
        "array_fields": sorted(_REQUIRED_ARRAY_FIELDS),
        "optional_array_fields": sorted(_OPTIONAL_ARRAY_FIELDS),
        "k_point": list(snapshot.k_point),
        "max_normalization_error": snapshot.max_normalization_error,
        "max_off_diagonal_gram": snapshot.max_off_diagonal_gram,
        "orthogonality_status": snapshot.orthogonality_status,
        "normalization_tolerance": snapshot.normalization_tolerance,
        "orthogonality_tolerance": snapshot.orthogonality_tolerance,
        "provenance": snapshot.provenance,
        "raw_eigenstates": states,
    })


def encode_snapshot(snapshot: MPBHEnvelopeSnapshot) -> bytes:
    """Encode one validated snapshot without pickle or unrestricted payload JSON."""
    if not isinstance(snapshot, MPBHEnvelopeSnapshot):
        raise TypeError("SNAPSHOT_TYPE_UNSUPPORTED")
    h_fields = _numeric_array(snapshot.h_fields, name="h_fields", ndim=4)
    if h_fields.shape[3] != 3:
        raise ValueError("h_fields must end with three components")
    frequencies = _numeric_array(snapshot.frequencies, name="frequencies", ndim=1)
    raw_norms = _numeric_array(snapshot.raw_norms, name="raw_norms", ndim=1)
    if np.any(raw_norms <= 0.0):
        raise ValueError("raw_norms must be positive")
    bands = h_fields.shape[0]
    if frequencies.size != bands or raw_norms.size != bands or len(snapshot.normalized_vectors) != bands or len(snapshot.raw_eigenstates) != bands:
        raise ValueError("snapshot band counts do not agree")
    gram = _numeric_array(snapshot.gram_matrix, name="gram_matrix", ndim=2)
    if gram.shape != (bands, bands):
        raise ValueError("gram_matrix shape does not match band count")
    normalized = _numeric_array(np.stack(snapshot.normalized_vectors), name="normalized_vectors", ndim=2)
    raw_vectors = _numeric_array(np.stack([state.vector for state in snapshot.raw_eigenstates]), name="raw_eigenstate_vectors", ndim=2)
    if normalized.shape != raw_vectors.shape:
        raise ValueError("normalized and raw eigenstate vector shapes differ")
    e_fields = None if snapshot.e_fields is None else _numeric_array(snapshot.e_fields, name="e_fields", ndim=4)
    if e_fields is not None and e_fields.shape != h_fields.shape:
        raise ValueError("e_fields shape must match h_fields")
    metadata = _canonical(_metadata_for(snapshot))
    buffer = io.BytesIO()
    arrays: dict[str, Any] = {
        "h_fields": np.asarray(h_fields, dtype=np.complex128),
        "frequencies": np.asarray(frequencies, dtype=float),
        "raw_norms": np.asarray(raw_norms, dtype=float),
        "gram_matrix": np.asarray(gram, dtype=np.complex128),
        "normalized_vectors": np.asarray(normalized, dtype=np.complex128),
        "raw_eigenstate_vectors": np.asarray(raw_vectors, dtype=np.complex128),
        "metadata": np.frombuffer(metadata, dtype=np.uint8),
    }
    if e_fields is not None:
        arrays["e_fields"] = np.asarray(e_fields, dtype=np.complex128)
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


def _read_metadata(value: np.ndarray) -> dict[str, Any]:
    if value.dtype.kind not in "iu" or value.ndim != 1:
        raise ValueError("CODEC_METADATA_ARRAY_INVALID")
    try:
        parsed = json.loads(bytes(np.asarray(value, dtype=np.uint8)).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("CODEC_METADATA_JSON_INVALID") from exc
    if not isinstance(parsed, dict) or parsed.get("schema") != SCHEMA:
        raise ValueError("CODEC_SCHEMA_INVALID")
    if (frozenset(parsed.get("array_fields", ())) != _REQUIRED_ARRAY_FIELDS
            or frozenset(parsed.get("optional_array_fields", ())) != _OPTIONAL_ARRAY_FIELDS):
        raise ValueError("CODEC_ARRAY_FIELD_SET_INVALID")
    return parsed


def decode_snapshot(payload: bytes) -> MPBHEnvelopeSnapshot:
    """Decode and validate one NPZ snapshot using ``allow_pickle=False``."""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("CODEC_PAYLOAD_TYPE_INVALID")
    try:
        archive = np.load(io.BytesIO(payload), allow_pickle=False)
    except Exception as exc:
        raise ValueError("CODEC_NPZ_INVALID") from exc
    with archive:
        fields = frozenset(archive.files)
        if not _REQUIRED_ARRAY_FIELDS.issubset(fields) or not fields.issubset(_ALLOWED_ARRAY_FIELDS):
            raise ValueError("CODEC_ARRAY_FIELD_SET_INVALID")
        metadata = _read_metadata(archive["metadata"])
        h_fields = _numeric_array(archive["h_fields"], name="h_fields", ndim=4)
        if h_fields.shape[3] != 3:
            raise ValueError("CODEC_H_FIELD_SHAPE_INVALID")
        bands = h_fields.shape[0]
        frequencies = _numeric_array(archive["frequencies"], name="frequencies", ndim=1)
        raw_norms = _numeric_array(archive["raw_norms"], name="raw_norms", ndim=1)
        gram = _numeric_array(archive["gram_matrix"], name="gram_matrix", ndim=2)
        normalized = _numeric_array(archive["normalized_vectors"], name="normalized_vectors", ndim=2)
        raw_vectors = _numeric_array(archive["raw_eigenstate_vectors"], name="raw_eigenstate_vectors", ndim=2)
        if np.any(raw_norms <= 0.0) or frequencies.size != bands or raw_norms.size != bands or gram.shape != (bands, bands):
            raise ValueError("CODEC_BAND_COUNT_INVALID")
        if normalized.shape[0] != bands or raw_vectors.shape != normalized.shape:
            raise ValueError("CODEC_VECTOR_SHAPE_INVALID")
        e_fields = None if "e_fields" not in archive.files else _numeric_array(archive["e_fields"], name="e_fields", ndim=4)
        if e_fields is not None and e_fields.shape != h_fields.shape:
            raise ValueError("CODEC_E_FIELD_SHAPE_INVALID")
        states = metadata.get("raw_eigenstates")
        if not isinstance(states, list) or len(states) != bands:
            raise ValueError("CODEC_RAW_EIGENSTATE_COUNT_INVALID")
        raw_eigenstates = []
        for index, state in enumerate(states):
            if not isinstance(state, dict):
                raise ValueError("CODEC_RAW_EIGENSTATE_METADATA_INVALID")
            raw_eigenstates.append(RawEigenstate(
                k_point=tuple(state["k_point"]), solver_index=state["solver_index"],
                eigenvalue=state["eigenvalue"], vector=raw_vectors[index], metadata=state["metadata"],
            ))
        return MPBHEnvelopeSnapshot(
            k_point=tuple(metadata["k_point"]), frequencies=frequencies, h_fields=h_fields,
            raw_norms=raw_norms, normalized_vectors=tuple(normalized[index] for index in range(bands)),
            gram_matrix=gram, max_normalization_error=metadata["max_normalization_error"],
            max_off_diagonal_gram=metadata["max_off_diagonal_gram"],
            orthogonality_status=metadata["orthogonality_status"],
            normalization_tolerance=metadata["normalization_tolerance"],
            orthogonality_tolerance=metadata["orthogonality_tolerance"],
            raw_eigenstates=tuple(raw_eigenstates), provenance=metadata["provenance"], e_fields=e_fields,
        )


__all__ = ["SCHEMA", "encode_snapshot", "decode_snapshot"]
