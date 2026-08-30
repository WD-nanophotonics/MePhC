from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_solver_free_reduction.py"


def _module():
    spec = importlib.util.spec_from_file_location("p78_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference():
    return {
        "representation": "mpb_periodic_h_l2_v1",
        "bloch_phase_excluded": True,
        "resolution": 64,
        "spatial_shape": [64, 64],
        "lattice_size": [1.0, 1.0],
        "component_order": "supplied final axis order",
        "component_basis": "LAB_CARTESIAN",
        "mu_contract": "MU1_NONMAGNETIC",
        "orientation_sign": 1,
        "fractional_material_indexing_identity": "same",
        "reference_cell_identity": "common",
    }


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _snapshot(reference, *, frozen=False, k_point=(0.17, 0.23)):
    provenance = {
        "representation": "mpb_periodic_h_l2_v1",
        "local_affine_reference_cell_contract": reference,
        "mpb_k_point": k_point,
    }
    if frozen:
        provenance = _freeze(provenance)
    return SimpleNamespace(
        spatial_shape=(64, 64),
        component_count=3,
        frequencies=np.ones(6),
        raw_norms=np.ones(6),
        normalized_vectors=tuple(np.asarray([1.0 + 0.0j, 0.0j]) for _ in range(6)),
        gram_matrix=np.eye(6, dtype=complex),
        provenance=provenance,
    )


def _valid_identity(module, snapshot, *, reference_sha=None, k_point=(0.17, 0.23)):
    canonical = {
        "public_q": [0.0, -0.6166666666666667],
        "s": 0.0,
        "derived_kappa": [0.0, 0.0],
        "A_s": [[1.0, 0.0], [0.0, 1.0]],
        "F_s": [[1.0, 0.0], [0.0, 1.0]],
        "geometry_digest": "geometry",
    }
    reference = _reference()
    reference_sha = reference_sha or hashlib.sha256(module._canonical(reference)).hexdigest()
    identity = {
        "state_id": "STATE_01",
        "role": "CENTER",
        "public_q": canonical["public_q"],
        "s": canonical["s"],
        "canonical_state_identity": canonical,
        "canonical_state_identity_sha256": hashlib.sha256(module._canonical(canonical)).hexdigest(),
        "solver_configuration": module._SOLVER_CONFIGURATION,
        "reciprocal_metadata": list(k_point),
        "reference_cell_contract_sha256": reference_sha,
        "frequencies": [1.0] * 6,
        "raw_norms": [1.0] * 6,
        "normalized_vector_digest": module._vector_digest(snapshot.normalized_vectors),
        "request_graph_sha256": hashlib.sha256((ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json").read_bytes()).hexdigest(),
        "science_source_commit": "1" * 40,
        "payload_sha256": "a" * 64,
    }
    binding = {"state_id": "STATE_01", "role": "CENTER", "public_q": canonical["public_q"], "s": 0.0}
    return snapshot, {"identity": identity, "payload_sha256": "a" * 64}, binding


def test_mappingproxy_and_frozen_tuples_match_dict_list_canonical_semantics():
    module = _module()
    plain = _snapshot(_reference(), frozen=False)
    frozen = _snapshot(_freeze(_reference()), frozen=True)

    module.validate_snapshot_structure(plain, state_id="STATE_01", role="CENTER")
    module.validate_snapshot_structure(frozen, state_id="STATE_01", role="CENTER")
    plain_view = module._normalize_runtime_provenance(plain.provenance)
    frozen_view = module._normalize_runtime_provenance(frozen.provenance)
    assert frozen_view == plain_view
    assert hashlib.sha256(module._canonical(frozen_view["local_affine_reference_cell_contract"])).hexdigest() == hashlib.sha256(module._canonical(plain_view["local_affine_reference_cell_contract"])).hexdigest()


def test_p77_state_01_tuple_spatial_shape_is_not_a_false_identity_mismatch():
    module = _module()
    reference = _freeze(_reference())
    snapshot = _snapshot(reference, frozen=True)
    module.validate_snapshot_structure(snapshot, state_id="STATE_01", role="CENTER")


@pytest.mark.parametrize(
    "field,observed",
    [
        ("spatial_shape", (64, 63)),
        ("representation", "other"),
        ("resolution", 63),
    ],
)
def test_genuine_identity_value_mismatches_remain_fail_closed(field, observed):
    module = _module()
    reference = _reference()
    reference[field] = observed
    with pytest.raises(module.ReferenceCellIdentityDiagnosticError) as caught:
        module.validate_snapshot_structure(_snapshot(reference), state_id="STATE_01", role="CENTER")
    assert field in caught.value.mismatch_fields


def test_reference_cell_sha_mismatch_remains_fail_closed():
    module = _module()
    snapshot, item, binding = _valid_identity(module, _snapshot(_reference()))
    item["identity"]["reference_cell_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="P71_REFERENCE_CELL_DIGEST_MISMATCH"):
        module._validate_snapshot_identity(snapshot, item, binding)


def test_numerical_mpb_k_point_mismatch_remains_fail_closed():
    module = _module()
    snapshot, item, binding = _valid_identity(module, _snapshot(_reference(), k_point=(0.17, 0.24)), k_point=(0.17, 0.23))
    with pytest.raises(ValueError, match="P71_RECIPROCAL_METADATA_MISMATCH"):
        module._validate_snapshot_identity(snapshot, item, binding)


def test_normalization_is_detached_and_does_not_mutate_frozen_provenance():
    module = _module()
    reference = _freeze(_reference())
    snapshot = _snapshot(reference, frozen=True)
    before = snapshot.provenance
    normalized = module._normalize_runtime_provenance(before)
    assert snapshot.provenance is before
    assert isinstance(snapshot.provenance["local_affine_reference_cell_contract"], MappingProxyType)
    assert isinstance(snapshot.provenance["local_affine_reference_cell_contract"]["spatial_shape"], tuple)
    assert isinstance(normalized["local_affine_reference_cell_contract"], dict)
    assert isinstance(normalized["local_affine_reference_cell_contract"]["spatial_shape"], list)


def test_static_runtime_guards_remain_solver_free():
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
