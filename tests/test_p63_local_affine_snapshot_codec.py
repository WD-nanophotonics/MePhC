"""Zero-MPB round-trip and rejection tests for the active snapshot codec."""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest

from mephc.eigenspace import RawEigenstate
from mephc.mpb_spectral import MPBHEnvelopeSnapshot, MPB_H_ENVELOPE_QUALIFIED
from audit.local_affine.local_affine_snapshot_codec import SCHEMA, decode_snapshot, encode_snapshot


def synthetic_snapshot(*, with_e_fields: bool = False) -> MPBHEnvelopeSnapshot:
    bands, nx, ny = 2, 2, 2
    h_fields = np.arange(bands * nx * ny * 3, dtype=float).reshape(bands, nx, ny, 3) + 1.0
    h_fields = h_fields.astype(np.complex128) + 1j * h_fields / 10.0
    e_fields = None
    vector_size = nx * ny * 3
    if with_e_fields:
        e_fields = (h_fields * (2.0 + 1.0j)).astype(np.complex128)
        vector_size *= 2
    vectors = tuple(np.eye(vector_size, dtype=np.complex128)[index] for index in range(bands))
    k_point = (0.1, -0.2, 0.0)
    raw_states = tuple(RawEigenstate(k_point=k_point, solver_index=index, eigenvalue=0.5 + index, vector=vectors[index], metadata={"band": index, "kind": "synthetic"}) for index in range(bands))
    return MPBHEnvelopeSnapshot(
        k_point=k_point, frequencies=np.array([0.5, 0.8]), h_fields=h_fields,
        e_fields=e_fields, raw_norms=np.array([1.0, 2.0]), normalized_vectors=vectors,
        gram_matrix=np.eye(bands, dtype=np.complex128), max_normalization_error=0.0,
        max_off_diagonal_gram=0.0, orthogonality_status=MPB_H_ENVELOPE_QUALIFIED,
        normalization_tolerance=1e-14, orthogonality_tolerance=1e-10,
        raw_eigenstates=raw_states, provenance={"representation": "mpb_periodic_h_l2_v1", "nested": {"value": 7}},
    )


def repack(payload: bytes, **replacements: np.ndarray) -> bytes:
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    arrays.update(replacements)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


@pytest.mark.parametrize("with_e_fields", [False, True])
def test_round_trip_preserves_numeric_snapshot_and_provenance(with_e_fields):
    source = synthetic_snapshot(with_e_fields=with_e_fields)
    restored = decode_snapshot(encode_snapshot(source))
    np.testing.assert_array_equal(restored.frequencies, source.frequencies)
    np.testing.assert_array_equal(restored.h_fields, source.h_fields)
    np.testing.assert_array_equal(restored.raw_norms, source.raw_norms)
    np.testing.assert_array_equal(restored.gram_matrix, source.gram_matrix)
    for actual, expected in zip(restored.normalized_vectors, source.normalized_vectors):
        np.testing.assert_array_equal(actual, expected)
    assert (restored.e_fields is not None) is with_e_fields
    if with_e_fields:
        np.testing.assert_array_equal(restored.e_fields, source.e_fields)
    assert restored.provenance == source.provenance
    assert [state.to_dict() for state in restored.raw_eigenstates] == [state.to_dict() for state in source.raw_eigenstates]


def test_rejects_object_array_nonfinite_array_and_invalid_shape():
    payload = encode_snapshot(synthetic_snapshot())
    with pytest.raises(ValueError):
        decode_snapshot(repack(payload, h_fields=np.array([[object()]], dtype=object)))
    with pytest.raises(ValueError):
        decode_snapshot(repack(payload, frequencies=np.array([np.nan, 0.8])))
    with pytest.raises(ValueError):
        decode_snapshot(repack(payload, h_fields=np.zeros((2, 2, 3), dtype=np.complex128)))


def test_rejects_malformed_metadata_schema_and_unsupported_snapshot():
    payload = encode_snapshot(synthetic_snapshot())
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    arrays["metadata"] = np.frombuffer(json.dumps({"schema": "wrong"}).encode(), dtype=np.uint8)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    with pytest.raises(ValueError):
        decode_snapshot(buffer.getvalue())
    with pytest.raises(TypeError):
        encode_snapshot(object())
    assert SCHEMA == "mephc-local-affine-periodic-h-snapshot-payload-v1"


def test_acquisition_uses_current_runtime_and_active_codec_only():
    source = (Path(__file__).parents[1] / "audit" / "local_affine" / "frozen_13_state_live_acquisition_v2.py").read_text(encoding="utf-8")
    assert "mephc_runtime.py" in source
    assert "SCIENCE_STATE" in source
    assert "encode_snapshot" in source
    for forbidden in ("mephc_science_runtime.py", "mephc_science_runtime_legacy.py", "tools/mephc-flow/archive", "runtime.encode_snapshot", "runtime._trusted_science_state_root"):
        assert forbidden not in source
