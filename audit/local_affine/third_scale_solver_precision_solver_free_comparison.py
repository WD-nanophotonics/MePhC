"""Future solver-free comparison of the baseline and tight third-scale records."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from audit.local_affine.local_affine_snapshot_codec import decode_snapshot
from mephc.phase_space_geometry import (
    HState, PhaseSpaceStateIdentity, ReferenceCellIdentity,
    fixed_q_frequency_derivative, h_state_from_normalized_vectors,
    make_mixed_diamond, rank1_mixed_curvature, reverse_mixed_curvature,
)


ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "audit" / "local_affine" / "p98_third_scale_solver_precision_12_record_binding_plan.json"
GRAPH_PATH = ROOT / "audit" / "local_affine" / "p84_third_scale_6_state_request_graph.json"
P85_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P85-THIRD-SCALE-SIX-STATE-LIVE-ACQUISITION-20260830-449"
P97_WORK_ORDER_ID = "MEPHC-LOCALAFFINE-P97-THIRD-SCALE-TIGHT-EIGENSOLVER-LIVE-ACQUISITION-RETRY-20260830-461"
RESULT_SCHEMA = "mephc-local-affine-third-scale-solver-precision-comparison-v1"
PREPARATION_SCHEMA = "mephc-local-affine-p98-third-scale-solver-precision-reduction-preparation-v1"
THIN_BUNDLE_SCHEMA = "mephc-thin-input-bundle-v1"
BASELINE_CONFIGURATION = {"resolution": 64, "num_bands": 6, "polarization": "TM", "eigensolver_tolerance": 1e-7, "mesh_size": 3, "deterministic": True, "phase_callback": None}
TIGHT_CONFIGURATION = {"resolution": 64, "num_bands": 6, "polarization": "TM", "eigensolver_tolerance": 1e-9, "mesh_size": 3, "deterministic": True, "phase_callback": None}
_HEX64 = frozenset("0123456789abcdef")
_PAIR_FIELDS = ("state_id", "role", "public_q", "s", "canonical_state_identity", "reciprocal_metadata", "reference_cell_contract_sha256")
_P91_REFERENCE = {
    "omega_qx_s_third": -0.19123609378280565,
    "omega_qy_s_third": 0.00023419912224820208,
    "domega_ds_third": 0.009029822613718097,
    "forward_wilson_phase_third_qx": 4.780902344570142e-07,
    "forward_wilson_phase_third_qy": -5.854978056205052e-10,
}
_P91_REFINEMENT = {"qx_s": 3.221056743732409e-05, "qy_s": 0.00019836212412222, "domega_ds": 2.313728213187982e-06}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize_json(item) for item in value]
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(f"P98_UNSAFE_JSON_VALUE:{type(value).__name__}")


def canonical_sha256_hex(value: Any) -> str:
    require(isinstance(value, str) and len(value) == 64 and set(value.lower()) <= _HEX64, "P98_GRAPH_SHA256_INVALID")
    return value.lower()


def graph_sha256() -> str:
    return hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()


def derive_record_key_sha256(work_order_id: str, record: Mapping[str, Any]) -> str:
    identity = {"work_order_id": work_order_id, "state_id": record["state_id"], "role": record["role"], "public_q": list(record["public_q"]), "s": float(record["s"])}
    return hashlib.sha256(canonical(identity)).hexdigest()


def load_binding_plan() -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    require(plan.get("record_count") == 12 and plan.get("unique_record_key_count") == 12, "P98_BINDING_COUNT_INVALID")
    require(canonical_sha256_hex(plan.get("request_graph_sha256")) == graph_sha256(), "P98_GRAPH_SHA_MISMATCH")
    groups = plan.get("groups")
    require(isinstance(groups, dict) and set(groups) == {"baseline_1e7", "tight_1e9"}, "P98_GROUP_SET_INVALID")
    seen: set[str] = set()
    for name, expected_work_order, expected_tolerance in (("baseline_1e7", P85_WORK_ORDER_ID, 1e-7), ("tight_1e9", P97_WORK_ORDER_ID, 1e-9)):
        group = groups[name]
        require(group.get("work_order_id") == expected_work_order, f"P98_{name.upper()}_WORK_ORDER_INVALID")
        require(group.get("solver_configuration", {}).get("eigensolver_tolerance") == expected_tolerance, f"P98_{name.upper()}_TOLERANCE_INVALID")
        records = group.get("records")
        require(isinstance(records, list) and len(records) == 6, f"P98_{name.upper()}_RECORD_COUNT_INVALID")
        require([item.get("state_id") for item in records] == [f"STATE_{index:02d}" for index in range(14, 20)], f"P98_{name.upper()}_STATE_ORDER_INVALID")
        for record in records:
            key = record.get("record_key_sha256")
            require(isinstance(key, str) and len(key) == 64 and set(key.lower()) <= _HEX64, "P98_RECORD_KEY_INVALID")
            require(key.lower() == derive_record_key_sha256(group["work_order_id"], record), "P98_RECORD_KEY_DERIVATION_INVALID")
            require(key.lower() not in seen, "P98_RECORD_KEY_DUPLICATE")
            seen.add(key.lower())
    return plan


def load_bundle() -> tuple[dict[str, Any], Path]:
    raw = os.environ.get("MEPHC_INPUT_BUNDLE")
    require(isinstance(raw, str) and raw, "P98_INPUT_BUNDLE_MISSING")
    path = Path(raw)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    require(bundle.get("schema") == THIN_BUNDLE_SCHEMA, "P98_INPUT_BUNDLE_SCHEMA_INVALID")
    datasets = bundle.get("datasets")
    require(isinstance(datasets, list) and len(datasets) == 12, "P98_DESCRIPTOR_COUNT_INVALID")
    return bundle, path


def validate_runtime_contract(bundle: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    expected = {record["record_key_sha256"]: (name, group, record) for name, group in plan["groups"].items() for record in group["records"]}
    descriptors = bundle["datasets"]
    keys = [item.get("record_key_sha256") for item in descriptors if isinstance(item, Mapping)]
    require(len(keys) == len(set(keys)) == 12 and set(keys) == set(expected), "P98_DESCRIPTOR_BINDING_SET_INVALID")
    identities: dict[tuple[str, str], Mapping[str, Any]] = {}
    for descriptor in descriptors:
        require(isinstance(descriptor, Mapping), "P98_DESCRIPTOR_INVALID")
        binding_name, group, record = expected[descriptor.get("record_key_sha256")]
        for field in ("dataset_id", "manifest_sha256", "record_key_sha256", "payload_sha256", "payload_size_bytes", "identity", "payload_file"):
            require(field in descriptor, f"P98_DESCRIPTOR_MISSING:{field}")
        require(descriptor["dataset_id"] == group["dataset_id"] and descriptor["manifest_sha256"] == group["manifest_sha256"], "P98_DESCRIPTOR_DATASET_MISMATCH")
        identity = descriptor["identity"]
        require(isinstance(identity, Mapping), "P98_DESCRIPTOR_IDENTITY_INVALID")
        require(canonical_sha256_hex(identity.get("request_graph_sha256")) == graph_sha256(), "P98_DESCRIPTOR_GRAPH_MISMATCH")
        require(identity.get("solver_configuration") == group["solver_configuration"], "P98_SOLVER_CONFIGURATION_MISMATCH")
        require(identity.get("science_source_commit") == group["science_source_commit"], "P98_SOURCE_COMMIT_MISMATCH")
        require(all(identity.get(field) == record.get(field) for field in ("state_id", "role", "public_q", "s")), "P98_STATE_IDENTITY_BINDING_MISMATCH")
        require(isinstance(descriptor["payload_file"], str) and Path(descriptor["payload_file"]).name == descriptor["payload_file"], "P98_PAYLOAD_DESCRIPTOR_INVALID")
        require(binding_name in {"baseline_1e7", "tight_1e9"}, "P98_GROUP_NAME_INVALID")
        identities[(binding_name, record["state_id"])] = identity
    for state_id in (f"STATE_{index:02d}" for index in range(14, 20)):
        baseline = identities[("baseline_1e7", state_id)]
        tight = identities[("tight_1e9", state_id)]
        for field in _PAIR_FIELDS:
            left = baseline.get(field)
            right = tight.get(field)
            if field == "canonical_state_identity" and isinstance(left, Mapping) and isinstance(right, Mapping):
                left = {key: value for key, value in left.items() if key != "eigensolver_tolerance"}
                right = {key: value for key, value in right.items() if key != "eigensolver_tolerance"}
            require(left == right, f"P98_PAIRED_IDENTITY_MISMATCH:{state_id}:{field}")


def payload_bytes(bundle_path: Path, descriptor: Mapping[str, Any]) -> bytes:
    payload = (bundle_path.parent / descriptor["payload_file"]).read_bytes()
    require(len(payload) == descriptor["payload_size_bytes"], "P98_PAYLOAD_LENGTH_MISMATCH")
    require(hashlib.sha256(payload).hexdigest() == descriptor["payload_sha256"], "P98_PAYLOAD_HASH_MISMATCH")
    return payload


def vector_digest(vectors: Any) -> str:
    values = [[[float(value.real), float(value.imag)] for value in np.asarray(vector, dtype=np.complex128)] for vector in vectors]
    return hashlib.sha256(canonical(values)).hexdigest()


def _phase_identity(identity: Mapping[str, Any], reference: Mapping[str, Any], configuration: Mapping[str, Any]) -> PhaseSpaceStateIdentity:
    ref = ReferenceCellIdentity(
        resolution=int(reference["resolution"]), spatial_shape=tuple(int(x) for x in reference["spatial_shape"]), lattice_size=tuple(reference["lattice_size"]),
        component_order=str(reference["component_order"]), component_basis=str(reference["component_basis"]), mu_contract=str(reference["mu_contract"]),
        orientation_sign=int(reference["orientation_sign"]), fractional_material_indexing_identity=str(reference["fractional_material_indexing_identity"]), reference_cell_identity=str(reference["reference_cell_identity"]),
    )
    canonical_identity = identity["canonical_state_identity"]
    return PhaseSpaceStateIdentity(
        public_q=tuple(float(x) for x in canonical_identity["public_q"]), s=float(canonical_identity["s"]),
        derived_kappa=tuple(float(x) for x in canonical_identity["derived_kappa"]),
        A_s=tuple(tuple(float(x) for x in row) for row in canonical_identity["A_s"]), F_s=tuple(tuple(float(x) for x in row) for row in canonical_identity["F_s"]),
        geometry_identity=str(canonical_identity["geometry_digest"]), reference_cell=ref,
        solver_configuration_identity=hashlib.sha256(canonical(dict(configuration))).hexdigest(),
    )


def resolve_group(bundle: Mapping[str, Any], bundle_path: Path, plan: Mapping[str, Any], name: str) -> dict[str, HState]:
    group = plan["groups"][name]
    by_key = {item["record_key_sha256"]: item for item in bundle["datasets"]}
    states: dict[str, HState] = {}
    for record in group["records"]:
        descriptor = by_key[record["record_key_sha256"]]
        identity = descriptor["identity"]
        snapshot = decode_snapshot(payload_bytes(bundle_path, descriptor))
        provenance = normalize_json(snapshot.provenance)
        require(isinstance(provenance, dict), "P98_PROVENANCE_INVALID")
        reference = provenance["local_affine_reference_cell_contract"]
        require(hashlib.sha256(canonical(reference)).hexdigest() == identity["reference_cell_contract_sha256"], "P98_REFERENCE_CELL_SHA_MISMATCH")
        require(identity["payload_sha256"] == descriptor["payload_sha256"], "P98_IDENTITY_PAYLOAD_HASH_MISMATCH")
        require(vector_digest(snapshot.normalized_vectors) == identity["normalized_vector_digest"], "P98_VECTOR_DIGEST_MISMATCH")
        phase_identity = _phase_identity(identity, reference, group["solver_configuration"])
        vectors = np.asarray(snapshot.normalized_vectors[0], dtype=np.complex128)
        require(vectors.ndim == 1 and bool(np.all(np.isfinite(vectors))) and math.isclose(float(np.linalg.norm(vectors)), 1.0, rel_tol=0.0, abs_tol=1e-10), "P98_BAND0_VECTOR_INVALID")
        states[record["role"]] = h_state_from_normalized_vectors(phase_identity, vectors, frequencies=(float(snapshot.frequencies[0]),), band_indices=(0,))
    require(set(states) == {record["role"] for record in group["records"]}, f"P98_{name.upper()}_ROLE_SET_INVALID")
    require(len({state.identity.reference_cell.compatibility_key() for state in states.values()}) == 1, "P98_REFERENCE_CELL_CROSS_STATE_MISMATCH")
    return states


def _third_diamond(states: Mapping[str, HState], axis: int) -> Any:
    suffix = "QX" if axis == 0 else "QY"
    return make_mixed_diamond(
        plus_q=states[f"THIRD_PLUS_{suffix}"], minus_q=states[f"THIRD_MINUS_{suffix}"],
        plus_s=states["THIRD_PLUS_S"], minus_s=states["THIRD_MINUS_S"], axis=axis,
        h_q=0.00025, h_s=0.005, q_center=(0.0, -0.6166666666666667), s_center=0.0,
    )


def _reverse_diagnostics(name: str, forward: Any, reverse: Any) -> dict[str, float]:
    require(all(math.isfinite(float(getattr(item, field))) for item in (forward, reverse) for field in ("phase", "omega_qs", "signed_area_qs", "minimum_link_singular_value", "maximum_link_principal_angle")), "P98_NONFINITE_WILSON_RESULT")
    require(forward.signed_area_qs == reverse.signed_area_qs and forward.signed_area_qs != 0.0, "P98_SIGNED_AREA_INVALID")
    require(math.isclose(forward.phase, -reverse.phase, rel_tol=0.0, abs_tol=1e-12), f"P98_REVERSE_PHASE_MISMATCH:{name}")
    omega_tolerance = 1e-12 / abs(float(forward.signed_area_qs))
    require(math.isclose(forward.omega_qs, -reverse.omega_qs, rel_tol=0.0, abs_tol=omega_tolerance), f"P98_REVERSE_OMEGA_MISMATCH:{name}")
    for curvature in (forward, reverse):
        derived = -float(curvature.phase) / float(curvature.signed_area_qs)
        tolerance = math.ulp(float(curvature.omega_qs)) + math.ulp(float(derived))
        require(abs(float(curvature.omega_qs) - derived) <= tolerance, f"P98_OMEGA_PHASE_CONSISTENCY_MISMATCH:{name}")
    return {
        f"forward_wilson_phase_{name}": float(forward.phase), f"reverse_wilson_phase_{name}": float(reverse.phase),
        f"minimum_link_singular_value_{name}": float(forward.minimum_link_singular_value), f"minimum_link_singular_value_reverse_{name}": float(reverse.minimum_link_singular_value),
        f"maximum_link_principal_angle_{name}": float(forward.maximum_link_principal_angle), f"maximum_link_principal_angle_reverse_{name}": float(reverse.maximum_link_principal_angle),
    }


def _group_reduction(states: Mapping[str, HState], prefix: str) -> dict[str, Any]:
    diamonds = {f"{prefix}_qx": _third_diamond(states, 0), f"{prefix}_qy": _third_diamond(states, 1)}
    forward = {name: rank1_mixed_curvature(diamond) for name, diamond in diamonds.items()}
    reverse = {name: reverse_mixed_curvature(diamond) for name, diamond in diamonds.items()}
    diagnostics: dict[str, Any] = {}
    for name in diamonds:
        diagnostics.update(_reverse_diagnostics(name, forward[name], reverse[name]))
    derivative = fixed_q_frequency_derivative(states["THIRD_PLUS_S"], states["THIRD_MINUS_S"], band_index=0, h_s=0.005)
    return {"omega_qx_s": float(forward[f"{prefix}_qx"].omega_qs), "omega_qy_s": float(forward[f"{prefix}_qy"].omega_qs), "domega_ds": float(derivative), **diagnostics}


def _fidelity(left: HState, right: HState) -> tuple[float, float]:
    require(left.ambient_dimension == right.ambient_dimension and left.rank == right.rank == 1, "P98_FIDELITY_DIMENSION_MISMATCH")
    require(left.identity.reference_cell.compatibility_key() == right.identity.reference_cell.compatibility_key(), "P98_FIDELITY_REFERENCE_CELL_MISMATCH")
    fidelity = min(1.0, max(0.0, abs(np.vdot(left.vector_for_band(0), right.vector_for_band(0)))))
    return float(fidelity), float(1.0 - fidelity * fidelity)


def compare_groups(baseline: Mapping[str, HState], tight: Mapping[str, HState], baseline_plan: Mapping[str, Any], tight_plan: Mapping[str, Any]) -> dict[str, Any]:
    for role in ("THIRD_PLUS_QX", "THIRD_MINUS_QX", "THIRD_PLUS_QY", "THIRD_MINUS_QY", "THIRD_PLUS_S", "THIRD_MINUS_S"):
        require(baseline[role].identity.public_q == tight[role].identity.public_q and baseline[role].identity.s == tight[role].identity.s, "P98_PAIR_COORDINATE_MISMATCH")
    baseline_reduction = _group_reduction(baseline, "baseline")
    tight_reduction = _group_reduction(tight, "tight")
    require(math.isclose(baseline_reduction["omega_qx_s"], _P91_REFERENCE["omega_qx_s_third"], rel_tol=0.0, abs_tol=1e-12), "P98_P91_BASELINE_QX_REPRODUCTION")
    require(math.isclose(baseline_reduction["omega_qy_s"], _P91_REFERENCE["omega_qy_s_third"], rel_tol=0.0, abs_tol=1e-12), "P98_P91_BASELINE_QY_REPRODUCTION")
    require(math.isclose(baseline_reduction["domega_ds"], _P91_REFERENCE["domega_ds_third"], rel_tol=0.0, abs_tol=1e-12), "P98_P91_BASELINE_DERIVATIVE_REPRODUCTION")
    require(math.isclose(baseline_reduction["forward_wilson_phase_baseline_qx"], _P91_REFERENCE["forward_wilson_phase_third_qx"], rel_tol=0.0, abs_tol=1e-12), "P98_P91_BASELINE_QX_PHASE_REPRODUCTION")
    require(math.isclose(baseline_reduction["forward_wilson_phase_baseline_qy"], _P91_REFERENCE["forward_wilson_phase_third_qy"], rel_tol=0.0, abs_tol=1e-12), "P98_P91_BASELINE_QY_PHASE_REPRODUCTION")
    fidelities: dict[str, float] = {}
    infidelities: dict[str, float] = {}
    frequency_differences: dict[str, float] = {}
    by_role = {record["role"]: record for record in baseline_plan["records"]}
    for role in by_role:
        fidelity, infidelity = _fidelity(baseline[role], tight[role])
        fidelities[role] = fidelity
        infidelities[role] = infidelity
        frequency_differences[role] = tight[role].frequency_for_band(0) - baseline[role].frequency_for_band(0)
    differences = {label: abs(tight_reduction[label] - baseline_reduction[label]) for label in ("omega_qx_s", "omega_qy_s", "domega_ds")}
    relative = {label: (None if abs(tight_reduction[label]) + abs(baseline_reduction[label]) == 0.0 else 2.0 * differences[label] / (abs(tight_reduction[label]) + abs(baseline_reduction[label]))) for label in differences}
    refinement = {"omega_qx_s": _P91_REFINEMENT["qx_s"], "omega_qy_s": _P91_REFINEMENT["qy_s"], "domega_ds": _P91_REFINEMENT["domega_ds"]}
    ratios = {label: (None if refinement[label] <= 0.0 else differences[label] / refinement[label]) for label in differences}
    labels = {"qx_s": "omega_qx_s", "qy_s": "omega_qy_s", "domega_ds": "domega_ds"}
    return {
        "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "state_pair_count": 6, "configuration_count": 2, "rank1_band_index": 0,
        "native_invocation_count": 1, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "mpb_execution": False, "field_payload_retained": False,
        "baseline": baseline_reduction, "tight": tight_reduction, "frequency_difference_tight_minus_baseline": frequency_differences,
        "frequency_difference_absolute": {key: abs(value) for key, value in frequency_differences.items()}, "statewise_fidelity": fidelities, "statewise_infidelity": infidelities,
        "minimum_statewise_fidelity": min(fidelities.values()), "maximum_statewise_infidelity": max(infidelities.values()), "maximum_absolute_band0_frequency_difference": max(abs(value) for value in frequency_differences.values()),
        "solver_precision_absolute_difference": {name: differences[source] for name, source in labels.items()},
        "solver_precision_symmetric_relative_difference": {name: relative[source] for name, source in labels.items()},
        "solver_sensitivity_to_geometric_refinement_ratio": {name: ratios[source] for name, source in labels.items()},
    }


def failure_result(exc: Exception, *, provider_count: int = 0, solver_count: int = 0, dataset_count: int = 0) -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "FAIL", "failed_stage": "bundle-or-reduction", "failure_code": str(exc), "exception_type": type(exc).__name__, "native_invocation_count": 1, "provider_execution_count": provider_count, "solver_execution_count": solver_count, "dataset_record_count": dataset_count, "mpb_execution": False, "field_payload_retained": False}


def main() -> int:
    result_path = os.environ.get("MEPHC_RESULT_PATH")
    require(isinstance(result_path, str) and result_path, "P98_RESULT_PATH_MISSING")
    try:
        bundle, bundle_path = load_bundle()
        plan = load_binding_plan()
        validate_runtime_contract(bundle, plan)
        baseline = resolve_group(bundle, bundle_path, plan, "baseline_1e7")
        tight = resolve_group(bundle, bundle_path, plan, "tight_1e9")
        result = compare_groups(baseline, tight, plan["groups"]["baseline_1e7"], plan["groups"]["tight_1e9"])
    except Exception as exc:
        result = failure_result(exc)
    Path(result_path).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
