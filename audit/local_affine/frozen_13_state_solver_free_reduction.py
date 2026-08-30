"""Solver-free reduction of the bound 13-state local-affine snapshots.

The entrypoint consumes only a framework-provided input bundle.  It verifies
record identity and payload hashes, decodes the active snapshot codec, then
uses the solver-neutral phase-space geometry API for rank-one estimates.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from audit.local_affine.local_affine_snapshot_codec import decode_snapshot
from mephc.phase_space_geometry import (
    HState,
    PhaseSpaceStateIdentity,
    ReferenceCellIdentity,
    fixed_q_frequency_derivative,
    h_state_from_normalized_vectors,
    make_mixed_diamond,
    rank1_mixed_curvature,
    reverse_mixed_curvature,
)


ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "audit" / "local_affine" / "p66_p64_v2_binding_plan.json"
GRAPH_PATH = ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json"
PLAN_SCHEMA = "mephc-local-affine-p66-p64-v2-binding-plan-v1"
SOURCE_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P64-FROZEN-13-STATE-LIVE-ACQUISITION-20260830-428"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _finite_vector(value: Any, size: int, code: str) -> tuple[float, ...]:
    array = np.asarray(value, dtype=float)
    _require(array.shape == (size,) and bool(np.all(np.isfinite(array))), code)
    return tuple(float(item) for item in array)


def load_binding_plan() -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    _require(plan.get("schema") == PLAN_SCHEMA, "P66_BINDING_PLAN_SCHEMA_INVALID")
    _require(plan.get("source_work_order_id") == SOURCE_WORK_ORDER_ID, "P66_SOURCE_WORK_ORDER_ID_INVALID")
    bindings = plan.get("bindings")
    _require(isinstance(bindings, list) and len(bindings) == 13, "P66_BINDING_COUNT_INVALID")
    _require(len({item.get("record_key_sha256") for item in bindings}) == 13, "P66_RECORD_KEYS_NOT_UNIQUE")
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    graph_states = graph.get("states")
    _require(graph.get("state_count") == 13 and isinstance(graph_states, list) and len(graph_states) == 13, "P66_GRAPH_INVALID")
    for binding, state in zip(bindings, graph_states):
        _require(
            all(binding.get(key) == state.get(key) for key in ("state_id", "role", "public_q", "s")),
            "P66_BINDING_GRAPH_MISMATCH",
        )
        key_identity = {
            "work_order_id": SOURCE_WORK_ORDER_ID,
            "state_id": binding["state_id"],
            "role": binding["role"],
            "public_q": binding["public_q"],
            "s": binding["s"],
        }
        _require(hashlib.sha256(_canonical(key_identity)).hexdigest() == binding["record_key_sha256"], "P66_RECORD_KEY_DERIVATION_INVALID")
    return plan


def load_bundle() -> tuple[dict[str, Any], Path]:
    raw_path = os.environ.get("MEPHC_INPUT_BUNDLE")
    _require(isinstance(raw_path, str) and raw_path, "P66_INPUT_BUNDLE_MISSING")
    bundle_path = Path(raw_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    _require(bundle.get("schema") == "mephc-input-bundle-v1", "P66_INPUT_BUNDLE_SCHEMA_INVALID")
    datasets = bundle.get("datasets")
    _require(isinstance(datasets, list) and len(datasets) == 13, "P66_DATASET_BINDINGS_COUNT_INVALID")
    return bundle, bundle_path


def _payload_bytes(bundle_path: Path, item: dict[str, Any]) -> bytes:
    relative = item.get("payload_file")
    _require(isinstance(relative, str) and relative and Path(relative).name == relative, "P66_PAYLOAD_PATH_INVALID")
    payload_path = bundle_path.parent / relative
    payload = payload_path.read_bytes()
    if "payload_size" in item:
        _require(len(payload) == int(item["payload_size"]), "P66_PAYLOAD_SIZE_INVALID")
    if "payload_sha256" in item:
        _require(hashlib.sha256(payload).hexdigest() == item["payload_sha256"], "P66_PAYLOAD_HASH_INVALID")
    return payload


def _identity(item: dict[str, Any], snapshot: Any, binding: dict[str, Any]) -> PhaseSpaceStateIdentity:
    supplied = item.get("identity", item)
    _require(isinstance(supplied, dict), "P66_STATE_IDENTITY_MISSING")
    provenance = dict(getattr(snapshot, "provenance", {}))
    state_identity = supplied.get("state_identity", provenance.get("local_affine_state_identity", {}))
    _require(isinstance(state_identity, dict), "P66_CANONICAL_STATE_IDENTITY_MISSING")
    public_q = _finite_vector(supplied.get("public_q", state_identity.get("public_q")), 2, "P66_PUBLIC_Q_INVALID")
    s = float(supplied.get("s", state_identity.get("s")))
    _require(public_q == tuple(float(x) for x in binding["public_q"]) and s == float(binding["s"]), "P66_STATE_ROLE_COORDINATE_MISMATCH")
    derived = _finite_vector(supplied.get("derived_kappa", state_identity.get("derived_kappa")), 2, "P66_DERIVED_KAPPA_INVALID")

    def matrix(key: str) -> tuple[tuple[float, ...], ...]:
        value = supplied.get(key, state_identity.get(key))
        array = np.asarray(value, dtype=float)
        _require(array.shape == (2, 2) and bool(np.all(np.isfinite(array))), f"P66_{key.upper()}_INVALID")
        return tuple(tuple(float(x) for x in row) for row in array)

    A_s = matrix("A_s")
    F_s = matrix("F_s")
    reference = provenance.get("local_affine_reference_cell_contract", {})
    _require(isinstance(reference, dict), "P66_REFERENCE_CELL_CONTRACT_MISSING")
    _require(reference.get("spatial_shape") == list(getattr(snapshot, "spatial_shape", ())), "P66_REFERENCE_CELL_SHAPE_MISMATCH")
    _require(reference.get("representation") == "mpb_periodic_h_l2_v1", "P66_REFERENCE_CELL_REPRESENTATION_INVALID")
    _require(reference.get("bloch_phase_excluded") is True, "P66_REFERENCE_CELL_PHASE_INVALID")
    _require(reference.get("component_basis") == "LAB_CARTESIAN" and reference.get("mu_contract") == "MU1_NONMAGNETIC", "P66_REFERENCE_CELL_METRIC_INVALID")
    _require(reference.get("orientation_sign") == 1, "P66_REFERENCE_CELL_ORIENTATION_INVALID")
    geometry_identity = supplied.get("geometry_identity", state_identity.get("geometry_digest"))
    solver_identity = supplied.get("solver_configuration_identity", state_identity.get("solver_configuration_identity"))
    _require(isinstance(geometry_identity, str) and geometry_identity, "P66_GEOMETRY_IDENTITY_MISSING")
    _require(isinstance(solver_identity, str) and solver_identity, "P66_SOLVER_CONFIGURATION_IDENTITY_MISSING")
    ref = ReferenceCellIdentity(
        resolution=int(reference["resolution"]),
        spatial_shape=tuple(int(x) for x in getattr(snapshot, "spatial_shape", (64, 64))),
        lattice_size=tuple(reference["lattice_size"]),
        component_order=str(reference["component_order"]),
        component_basis=str(reference["component_basis"]),
        mu_contract=str(reference["mu_contract"]),
        orientation_sign=int(reference["orientation_sign"]),
        fractional_material_indexing_identity=str(reference["fractional_material_indexing_identity"]),
        reference_cell_identity=str(reference["reference_cell_identity"]),
    )
    return PhaseSpaceStateIdentity(
        public_q=public_q, s=s, derived_kappa=derived, A_s=A_s, F_s=F_s,
        geometry_identity=geometry_identity,
        reference_cell=ref,
        solver_configuration_identity=solver_identity,
    )


def resolve_states(bundle: dict[str, Any], bundle_path: Path, plan: dict[str, Any]) -> dict[str, HState]:
    datasets = bundle["datasets"]
    _require(all(isinstance(item, dict) and isinstance(item.get("record_key_sha256"), str) for item in datasets), "P66_DATASET_BINDING_RECORD_KEY_INVALID")
    by_key = {item.get("record_key_sha256"): item for item in datasets if isinstance(item, dict)}
    _require(len(by_key) == 13, "P66_DATASET_RECORD_KEYS_NOT_UNIQUE")
    states: dict[str, HState] = {}
    for binding in plan["bindings"]:
        item = by_key.get(binding["record_key_sha256"])
        _require(item is not None, "P66_RECORD_BINDING_MISSING")
        _require(item.get("dataset_id") == plan["source_dataset_id"], "P66_DATASET_ID_MISMATCH")
        _require(item.get("manifest_sha256") == plan["source_manifest_sha256"], "P66_MANIFEST_HASH_MISMATCH")
        payload = _payload_bytes(bundle_path, item)
        snapshot = decode_snapshot(payload)
        identity = _identity(item, snapshot, binding)
        vector = snapshot.normalized_vectors[0]
        frequency = float(snapshot.frequencies[0])
        states[binding["role"]] = h_state_from_normalized_vectors(identity, vector, frequencies=(frequency,), band_indices=(0,))
    _require(len(states) == 13, "P66_STATE_ROLE_SET_INVALID")
    return states


def _diamond(states: dict[str, HState], prefix: str, axis: int, h_q: float, h_s: float) -> Any:
    return make_mixed_diamond(
        plus_q=states[f"{prefix}_PLUS_Q{'X' if axis == 0 else 'Y'}"],
        minus_q=states[f"{prefix}_MINUS_Q{'X' if axis == 0 else 'Y'}"],
        plus_s=states[f"{prefix}_PLUS_S"],
        minus_s=states[f"{prefix}_MINUS_S"],
        axis=axis, h_q=h_q, h_s=h_s,
        q_center=states["CENTER"].identity.public_q, s_center=states["CENTER"].identity.s,
    )


def reduce_states(states: dict[str, HState]) -> dict[str, Any]:
    _require(set(states) == {"CENTER", "PRIMARY_PLUS_QX", "PRIMARY_MINUS_QX", "PRIMARY_PLUS_QY", "PRIMARY_MINUS_QY", "PRIMARY_PLUS_S", "PRIMARY_MINUS_S", "REFINED_PLUS_QX", "REFINED_MINUS_QX", "REFINED_PLUS_QY", "REFINED_MINUS_QY", "REFINED_PLUS_S", "REFINED_MINUS_S"}, "P66_STATE_ROLE_SET_INVALID")
    primary = {axis: rank1_mixed_curvature(_diamond(states, "PRIMARY", axis, 0.001, 0.02)) for axis in (0, 1)}
    refined = {axis: rank1_mixed_curvature(_diamond(states, "REFINED", axis, 0.0005, 0.01)) for axis in (0, 1)}
    reverse = {axis: reverse_mixed_curvature(_diamond(states, "PRIMARY", axis, 0.001, 0.02)) for axis in (0, 1)}
    derivative_primary = fixed_q_frequency_derivative(states["PRIMARY_PLUS_S"], states["PRIMARY_MINUS_S"], band_index=0, h_s=0.02)
    derivative_refined = fixed_q_frequency_derivative(states["REFINED_PLUS_S"], states["REFINED_MINUS_S"], band_index=0, h_s=0.01)
    primary_out = {f"q{axis}": value.to_dict() for axis, value in primary.items()}
    refined_out = {f"q{axis}": value.to_dict() for axis, value in refined.items()}
    deltas = {f"q{axis}": abs(primary[axis].omega_qs - refined[axis].omega_qs) for axis in (0, 1)}
    reverse_ok = all(math.isclose(reverse[axis].omega_qs, -primary[axis].omega_qs, rel_tol=0.0, abs_tol=1e-12) for axis in (0, 1))
    return {
        "schema": "mephc-local-affine-p66-solver-free-reduction-v1",
        "state_count": len(states),
        "rank1_band_index": 0,
        "primary": primary_out,
        "refined": refined_out,
        "primary_refined_abs_delta_omega_qs": deltas,
        "fixed_q_frequency_derivative": {"primary": derivative_primary, "refined": derivative_refined},
        "reverse_sign_check": {"status": "PASS" if reverse_ok else "FAIL", "expected": "reverse omega_qs = -forward omega_qs"},
        "finite_result": all(math.isfinite(float(value)) for value in (*deltas.values(), derivative_primary, derivative_refined)),
        "scientific_acceptance_status": "PASS" if reverse_ok else "FAIL",
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "solver_execution_count": 0,
        "mpb_execution": False,
    }


def main() -> int:
    result_path = os.environ.get("MEPHC_RESULT_PATH")
    _require(isinstance(result_path, str) and result_path, "P66_RESULT_PATH_MISSING")
    try:
        bundle, bundle_path = load_bundle()
        plan = load_binding_plan()
        _require(bundle.get("work_order_id"), "P66_WORK_ORDER_ID_MISSING")
        result = reduce_states(resolve_states(bundle, bundle_path, plan))
    except Exception as exc:
        result = {
            "schema": "mephc-local-affine-p66-solver-free-reduction-v1",
            "scientific_acceptance_status": "FAIL",
            "failure_code": type(exc).__name__ + ":" + str(exc),
            "native_invocation_count": 0, "provider_request_count": 0,
            "solver_execution_count": 0, "mpb_execution": False,
        }
    Path(result_path).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
