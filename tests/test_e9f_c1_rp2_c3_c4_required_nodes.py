from pathlib import Path

from audit.e9f import c3_c4_runtime as runtime
from audit.e9f import run_e9f_c1_rp2_c3_c4_worker as worker


def test_worker_uses_shared_finalizer():
    source = Path(worker.__file__).read_text()
    assert "runtime.finalize_payload" in source and "runtime.validate_payload" in source


def test_h_norm_metadata_is_exactly_1e14():
    assert runtime.H_NORM_TOLERANCE == 1e-14


def test_identity_field_registry_is_single_canonical_tuple():
    assert runtime.CANONICAL_IDENTITY_FIELDS == tuple(dict.fromkeys(runtime.CANONICAL_IDENTITY_FIELDS))
