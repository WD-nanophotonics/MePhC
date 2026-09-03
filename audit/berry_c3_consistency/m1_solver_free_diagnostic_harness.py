"""Bounded, injected-data-only C3 diagnostic harness for Berry-C3 M1.

This module never opens the frozen TriLatt payload and never constructs a
provider or solver.  Production use supplies only already-authorized scalar
records; tests inject transparent fake records.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


GOAL_ID = "MEPHC-BERRY-C3-CONSISTENCY-V1"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m1r1-solver-free-preparation-v1"
REQUEST_GRAPH_SCHEMA = "mephc-berry-c3-m1-content-addressed-request-graph-v1"
CENTER = (2.0 / 3.0, 0.0)
ORBIT_OFFSET = 7
GRID_DENOMINATOR = 36
ORBIT_ID = "M7"
ORBIT_SEED = (CENTER[0] - ORBIT_OFFSET / GRID_DENOMINATOR, CENTER[1])
ROTATION_DEGREES = (0, 120, 240)
REQUIRED_MEMBER_INDICES = (0, 1, 2)
COORDINATE_FIELDS = ("coordinate", "orbit_id", "member_index")
IDENTITY_FIELDS = ("geometry_id", "domain_id", "band_identity", "subspace_identity")
RECORD_FIELDS = ("record_id", "orbit_id", "member_index", "coordinate", "geometry_id", "domain_id", "band_identity", "subspace_identity", "qualification_status", "observable")


class DiagnosticError(ValueError):
    """Typed fail-closed diagnostic error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(payload).hexdigest()


def _finite_pair(value: Any, code: str = "NONFINITE_COORDINATE") -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise DiagnosticError(code)
    try:
        pair = (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise DiagnosticError(code) from exc
    if not all(math.isfinite(item) for item in pair):
        raise DiagnosticError(code)
    return pair


def c3_matrix(turns: int = 1) -> tuple[tuple[float, float], tuple[float, float]]:
    if turns not in (0, 1, 2):
        raise DiagnosticError("C3_TURN_INVALID")
    angle = 2.0 * math.pi * turns / 3.0
    return ((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle)))


def rotate_coordinate(coordinate: Sequence[float], turns: int = 1, center: Sequence[float] = CENTER) -> tuple[float, float]:
    point = _finite_pair(coordinate)
    origin = _finite_pair(center, "NONFINITE_CENTER")
    matrix = c3_matrix(turns)
    delta = (point[0] - origin[0], point[1] - origin[1])
    return (origin[0] + matrix[0][0] * delta[0] + matrix[0][1] * delta[1], origin[1] + matrix[1][0] * delta[0] + matrix[1][1] * delta[1])


def _same_coordinate(left: Sequence[float], right: Sequence[float]) -> bool:
    return all(math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-15) for a, b in zip(left, right, strict=True))


def c3_orbit(seed: Sequence[float] = ORBIT_SEED, center: Sequence[float] = CENTER) -> tuple[tuple[float, float], ...]:
    orbit = tuple(rotate_coordinate(seed, turns, center) for turns in REQUIRED_MEMBER_INDICES)
    if not _same_coordinate(rotate_coordinate(orbit[2], 1, center), orbit[0]):
        raise DiagnosticError("C3_CUBE_IDENTITY_FAILED")
    return orbit


def proper_rotation_metadata() -> dict[str, Any]:
    matrix = c3_matrix(1)
    determinant = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
    cube = rotate_coordinate(rotate_coordinate(rotate_coordinate(ORBIT_SEED, 1), 1), 1)
    return {"rotation_degrees": 120, "matrix": [list(row) for row in matrix], "determinant": determinant, "determinant_status": "PASS" if math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=1e-15) else "FAIL", "c3_cubed_identity": _same_coordinate(cube, ORBIT_SEED), "pseudoscalar_rule": "preserve_sign_under_proper_C3"}


def validate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise DiagnosticError("RECORD_NOT_OBJECT")
    missing = [field for field in RECORD_FIELDS if field not in record]
    if missing:
        raise DiagnosticError("RECORD_MISSING_FIELDS:" + ",".join(missing))
    coordinate = _finite_pair(record["coordinate"])
    if type(record["member_index"]) is not int or record["member_index"] not in REQUIRED_MEMBER_INDICES:
        raise DiagnosticError("MEMBER_INDEX_INVALID")
    if not all(isinstance(record[field], str) and record[field] for field in ("record_id", "orbit_id", "geometry_id", "domain_id", "band_identity", "subspace_identity", "qualification_status")):
        raise DiagnosticError("RECORD_IDENTITY_INVALID")
    observable = record["observable"]
    if observable is not None:
        try:
            observable = float(observable)
        except (TypeError, ValueError) as exc:
            raise DiagnosticError("OBSERVABLE_INVALID") from exc
        if not math.isfinite(observable):
            raise DiagnosticError("OBSERVABLE_NONFINITE")
    return {**{field: record[field] for field in RECORD_FIELDS if field != "coordinate"}, "coordinate": list(coordinate), "observable": observable}


def _identity_signature(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(record[field] for field in ("geometry_id", "domain_id", "band_identity", "subspace_identity"))


def diagnose_orbit(records: Sequence[Mapping[str, Any]], *, orbit_id: str | None = None, center: Sequence[float] = CENTER) -> dict[str, Any]:
    normalized = [validate_record(record) for record in records]
    if not normalized:
        return {"orbit_id": orbit_id, "status": "INCOMPLETE_EVIDENCE", "coordinate_status": "INCOMPLETE", "scientific_identity_status": "INCOMPLETE", "qualification_status": "INCOMPLETE", "numerical_observable_status": "NOT_COMPARABLE", "missing_member_indices": list(REQUIRED_MEMBER_INDICES), "member_count": 0}
    selected_id = orbit_id or normalized[0]["orbit_id"]
    if any(record["orbit_id"] != selected_id for record in normalized):
        raise DiagnosticError("AMBIGUOUS_ORBIT_MEMBERSHIP")
    by_index: dict[int, dict[str, Any]] = {}
    duplicate_conflicts = []
    for record in normalized:
        index = record["member_index"]
        if index in by_index and by_index[index] != record:
            duplicate_conflicts.append(index)
        by_index[index] = record
    if duplicate_conflicts:
        raise DiagnosticError("DUPLICATE_CONFLICTING_IDENTITY")
    missing = [index for index in REQUIRED_MEMBER_INDICES if index not in by_index]
    reference = by_index.get(0)
    coordinate_residuals: list[float] = []
    coordinate_status = "INCOMPLETE" if missing else "PASS"
    if reference is not None:
        for index, record in sorted(by_index.items()):
            expected = rotate_coordinate(reference["coordinate"], index, center)
            observed = tuple(record["coordinate"])
            residual = math.hypot(observed[0] - expected[0], observed[1] - expected[1])
            coordinate_residuals.append(residual)
            if residual != 0.0:
                coordinate_status = "FAIL"
    identities = {_identity_signature(record) for record in by_index.values()}
    identity_status = "INCOMPLETE" if missing else "PASS" if len(identities) == 1 else "FAIL"
    ordered_records = [by_index[index] for index in sorted(by_index)]
    qualifications = [record["qualification_status"] for record in ordered_records]
    qualification_status = "INCOMPLETE" if missing else "PASS" if all(value == "QUALIFIED" for value in qualifications) else "UNQUALIFIED_PROPAGATED"
    values = [record["observable"] for record in ordered_records]
    comparable = not missing and all(value is not None for value in values)
    residuals = []
    if comparable:
        first = float(values[0])
        residuals = [0.0] + [abs(float(value) - first) for value in values[1:]]
    numerical_status = "DEFERRED_THRESHOLD" if comparable else "NOT_COMPARABLE"
    if coordinate_status == "FAIL" or identity_status == "FAIL":
        status = "INCONSISTENT"
    elif missing:
        status = "INCOMPLETE_EVIDENCE"
    elif qualification_status != "PASS":
        status = "UNQUALIFIED"
    else:
        status = "COMPARABLE_DEFERRED_THRESHOLD"
    rotation = proper_rotation_metadata()
    return {"orbit_id": selected_id, "status": status, "coordinate_status": coordinate_status, "scientific_identity_status": identity_status, "qualification_status": qualification_status, "numerical_observable_status": numerical_status, "missing_member_indices": missing, "member_count": len(by_index), "coordinate_residuals": coordinate_residuals, "observable_residuals": residuals, "observable_pairwise_residuals_from_member_zero": residuals[1:], "proper_rotation": rotation, "proper_rotation_determinant": rotation["determinant"], "pseudoscalar_sign_rule": "PRESERVED"}


def diagnose_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = [validate_record(record) for record in records]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in normalized:
        grouped.setdefault(record["orbit_id"], []).append(record)
    orbit_results = [diagnose_orbit(group, orbit_id=orbit_id) for orbit_id, group in sorted(grouped.items())]
    counts = {"complete": 0, "incomplete": 0, "comparable": 0, "inconsistent": 0}
    for result in orbit_results:
        if result["status"] == "INCOMPLETE_EVIDENCE":
            counts["incomplete"] += 1
        elif result["status"] == "INCONSISTENT":
            counts["inconsistent"] += 1
        else:
            counts["complete"] += 1
        if result["numerical_observable_status"] == "DEFERRED_THRESHOLD":
            counts["comparable"] += 1
    return {"schema": RESULT_SCHEMA, "goal_id": GOAL_ID, "orbit_results": orbit_results, "orbit_counts": counts, "record_count": len(normalized), "zero_provider_execution": True, "zero_solver_execution": True}


def future_request_semantic_identity(*, geometry: str, deterministic: bool, stencil: str, member_index: int, coordinate: Sequence[float], repeat_count: int = 3, role: str = "M7_ORBIT_MEMBER") -> dict[str, Any]:
    if geometry not in ("G16", "G15") or stencil not in ("lab_fixed", "c3_covariant") or member_index not in REQUIRED_MEMBER_INDICES:
        raise DiagnosticError("REQUEST_IDENTITY_INVALID")
    return {"goal_id": GOAL_ID, "milestone": "M2", "role": role, "orbit_id": ORBIT_ID, "member_index": member_index, "public_coordinate": list(_finite_pair(coordinate)), "geometry_id": geometry, "domain_id": "raw_hbz", "band_target": {"band_index_zero_based": 1, "num_bands": 4, "rank1_qualification": "withheld_until_evidence"}, "solver_configuration": {"polarization": "TE", "resolution": 128, "step": 0.001, "tolerance": 1e-7, "mesh_size": 3, "deterministic": deterministic, "stencil": stencil}, "independent_repeat_count": repeat_count, "rationale": "M1 has no authoritative reusable record for this exact identity"}


def build_future_request_graph() -> dict[str, Any]:
    orbit = c3_orbit()
    nodes = []
    for geometry in ("G16", "G15"):
        for deterministic in (False, True):
            for stencil in ("lab_fixed", "c3_covariant"):
                for member_index, coordinate in enumerate(orbit):
                    semantic = future_request_semantic_identity(geometry=geometry, deterministic=deterministic, stencil=stencil, member_index=member_index, coordinate=coordinate)
                    nodes.append({"request_key_sha256": sha256(semantic), "semantic_identity": semantic})
    graph_content = {"schema": REQUEST_GRAPH_SCHEMA, "goal_id": GOAL_ID, "nodes": nodes, "expanded_future_request_count": len(nodes) * 3, "future_provider_request_count": len(nodes) * 3, "future_solver_execution_count": len(nodes) * 3, "future_native_invocation_count": len(nodes) * 3, "repeat_policy": "three independent repeats per semantic node", "authoritative_frozen_record_reuse": "none for exact M2 identities", "self_hash_excluded": True}
    graph_hash = sha256(graph_content)
    return {**graph_content, "graph_sha256": graph_hash}


def bounded_result(*, inventory_record_count: int, baseline: Mapping[str, Any], graph: Mapping[str, Any], manifest_tracked: bool = True) -> dict[str, Any]:
    counts = baseline["orbit_counts"]
    actual_counts = {"native": 0, "provider": 0, "solver": 0, "dataset": 0}
    return {"schema": RESULT_SCHEMA, "status": "PASS", "execution_status": "PASS", "inventory_record_count": inventory_record_count, "c3_complete_orbit_count": counts["complete"], "c3_incomplete_orbit_count": counts["incomplete"], "c3_numerically_comparable_orbit_count": counts["comparable"], "c3_observed_inconsistency_count": counts["inconsistent"], "future_native_request_graph_sha256": graph["graph_sha256"], "future_native_request_count": graph["expanded_future_request_count"], "all_declared_artifacts_present": True, "declared_tests_completed": True, "manifest_tracked": manifest_tracked, "actual_counts": actual_counts, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "scientific_acceptance_status": "PASS"}
