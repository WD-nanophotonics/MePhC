"""C3.C5 dynamic-resolution matrix runtime and closed-world process gates."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from audit.e9f import c3_c2_hardening as c2
from audit.e9f import run_e9f_c1_rp2_c3_c2_impl as c2science

WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-C5-20260825-248"
PHASE = "E9F.C1.RP2.C3.C5"
FAILED_PARENT_EXECUTION_SHA = "98a37d3e29b9c070b0523e9fa897a03aee7cf94c"
RUNNER_RELATIVE_PATH = Path("audit/e9f/run_e9f_c1_rp2_c3_c5.py")
PAYLOAD_SCHEMA = "mephc_e9f_c1_rp2_c3_c5_worker_v1"
CHECKPOINT_SCHEMA = "mephc_e9f_c1_rp2_c3_c5_matrix_checkpoint_v1"
H_ORTHOGONALITY_TOLERANCE = 1e-10
H_NORM_TOLERANCE = 1e-14
CANONICAL_IDENTITY_FIELDS = ("project_id", "work_order_id", "phase", "execution_sha", "source_sample_id", "source_sample_index", "logical_sample_index", "worker_id", "resolution", "contract_sha256", "rp1_policy_file_sha256", "rp1_policy_canonical_semantic_sha256", "payload_transport")
REQUIRED_INCIDENT_IDS = tuple(f"REL-{index:03d}" for index in range(21, 50))
OPEN_P1 = ("REL-021", "REL-026", "REL-027", "REL-028", "REL-029")


def canonical(value: object) -> bytes: return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as handle: handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())
    os.replace(tmp, path)


def runner_path(root: Path, file_path: Path) -> Path:
    actual = file_path.resolve(); expected = (root / "audit/e9f").resolve()
    if expected not in actual.parents or actual.name != RUNNER_RELATIVE_PATH.name: raise ValueError("C3_C5_RUNNER_PATH_INVALID")
    return actual


def build_plan(root: Path) -> list[dict[str, Any]]:
    rows = c2science.base.build_plan(root)
    if len(rows) != 12 or [row["sample_index"] for row in rows] != list(range(12)): raise ValueError("C3_C5_PLAN_WORKER_INDEX_INVALID")
    if {row["source_sample_id"] for row in rows} != set(c2science.load_policy(root)["rp2_diagnostic_matrix"]["fixed_sample_ids"]): raise ValueError("C3_C5_PLAN_POLICY_SAMPLE_MISMATCH")
    return rows


def make_provider(*, geometry: Any, lattice: Any, solver_geometry: Any, background: Any, resolution: int, mp: Any, provider_cls: Any, num_bands: int, mesh_size: int, solver_tolerance: float) -> Any:
    return provider_cls(geometry=list(solver_geometry), geometry_lattice=lattice, resolution=int(resolution), num_bands=num_bands, polarization=mp.TE, default_material=background, eigensolver_tolerance=solver_tolerance, deterministic=True, mesh_size=mesh_size, norm_tolerance=H_NORM_TOLERANCE, orthogonality_tolerance=H_ORTHOGONALITY_TOLERANCE)


def compute_worker(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    import meep as mp
    from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs, MESH_SIZE, NUM_BANDS, SOLVER_TOLERANCE
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    from mephc.valley_benchmark import centered_ccw_plaquette_requests
    geometry = geometry_inputs(); preflight, lattice, solver_geometry, background = build_inputs(geometry); provider = make_provider(geometry=geometry, lattice=lattice, solver_geometry=solver_geometry, background=background, resolution=int(row["resolution"]), mp=mp, provider_cls=MPBLiveSpectralProvider, num_bands=NUM_BANDS, mesh_size=MESH_SIZE, solver_tolerance=SOLVER_TOLERANCE)
    center = tuple(float(x) for x in row["authoritative_coordinate"]); replay = c2science.replay_index(root, row["source_sample_id"], int(row["resolution"])); solves = []; center_raw = provider.solve(center); solves.append(center_raw); center_point = c2science.point(center_raw, center, replay); stencils = {}
    for stencil in ("1/72", "1/144"):
        h = 1.0 / int(stencil.split("/")[1]); requests = centered_ccw_plaquette_requests((center,), h, period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest); values = []; vertices = []
        for request in requests:
            raw = provider.solve(request.canonical_periodic_vertex_q); solves.append(raw); values.append(raw); vertices.append(c2science.point(raw, request.nominal_vertex_q, replay))
        stencils[stencil] = {"stencil": stencil, "h": h, "vertices": vertices, **c2science.analyze_plaquette(values, h)}
    if len(solves) != 9: raise RuntimeError("C3_C5_SOLVE_COUNT_NOT_NINE")
    return {"schema": "mephc_e9f_c1_rp2_c3_c2_raw_science_v1", "project_id": "MEPHC", "work_order_id": "MEPHC-E9F-C1-RP2-C3-C2-20260825-242", "phase": "E9F.C1.RP2.C3.C2", "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "resolution": int(row["resolution"]), "execution_git_sha": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "provider": {"representation": "mpb_periodic_h_l2_v1", "live_provider": "mpb_live_periodic_h_l2_v1", "resolution": int(row["resolution"]), "orthogonality_tolerance": H_ORTHOGONALITY_TOLERANCE, "norm_tolerance": H_NORM_TOLERANCE}, "center": center_point, "stencils": stencils, "all_point_metrics": [center_point] + [point for entry in stencils.values() for point in entry["vertices"]], "solve_count": 9, "replay_matched_point_count": sum(point["frequency_replay"]["matched"] for point in [center_point] + [q for entry in stencils.values() for q in entry["vertices"]]), "replay_unmatched_point_count": sum(not point["frequency_replay"]["matched"] for point in [center_point] + [q for entry in stencils.values() for q in entry["vertices"]]), "diagnostic_only": True, "reducer_admissible": False, "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True, "no_extra_sample_points": True, "rp1_policy_sha256": sha(root / c2science.POLICY_REL), "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a", "original_rp2_execution_sha": "8121dbfba352b1a77551213771694d25c1bf3f01"}


def identity_for(*, row: Mapping[str, Any], execution_sha: str, contract_sha256: str, policy_sha256: str) -> dict[str, Any]:
    return {"project_id": "MEPHC", "work_order_id": WORK_ORDER, "phase": PHASE, "execution_sha": execution_sha, "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "worker_id": row["sample_id"], "resolution": int(row["resolution"]), "contract_sha256": contract_sha256, "rp1_policy_file_sha256": policy_sha256, "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a", "payload_transport": "ATOMIC_FILE"}


def body_hash(payload: Mapping[str, Any]) -> str:
    body = dict(payload); body.pop("payload_body_sha256", None); body.pop("payload_file_sha256", None); return hashlib.sha256(canonical(body)).hexdigest()


def finalize_payload(raw: Mapping[str, Any], *, row: Mapping[str, Any], expected_identity: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    for key in ("execution_git_sha", "payload_sha256", "c3_c2_transport_binding", "c3_c3_transport_binding", "c3_c4_transport_binding", "rp1_policy_sha256"): payload.pop(key, None)
    payload["schema"] = PAYLOAD_SCHEMA
    for key in CANONICAL_IDENTITY_FIELDS: payload[key] = expected_identity[key]
    payload["c3_c5_transport_binding"] = dict(expected_identity); payload["h_gate_tolerances"] = {"orthogonality_tolerance": H_ORTHOGONALITY_TOLERANCE, "normalization_tolerance": H_NORM_TOLERANCE}
    for point in payload.get("all_point_metrics", []): point.setdefault("H_GATE", {}).update({"orthogonality_tolerance": H_ORTHOGONALITY_TOLERANCE, "normalization_tolerance": H_NORM_TOLERANCE})
    payload["payload_body_sha256"] = body_hash(payload); validate_payload(payload, row=row, expected_identity=expected_identity); return payload


def validate_h(payload: Mapping[str, Any]) -> None:
    if len(payload.get("all_point_metrics", [])) != 9: raise ValueError("C3_C5_H_POINT_COUNT")
    for point in payload["all_point_metrics"]:
        gate = point.get("H_GATE", {})
        if gate.get("status") != "MPB_H_ENVELOPE_QUALIFIED" or float(gate.get("max_offdiag", 9)) > H_ORTHOGONALITY_TOLERANCE or float(gate.get("selected_pair_offdiag", 9)) > H_ORTHOGONALITY_TOLERANCE or float(gate.get("max_normalization_error", 9)) > H_NORM_TOLERANCE or float(gate.get("orthogonality_tolerance", 9)) != H_ORTHOGONALITY_TOLERANCE or float(gate.get("normalization_tolerance", 9)) != H_NORM_TOLERANCE: raise ValueError("C3_C5_H_REPRESENTATION_PRECONDITION_FAIL_CLOSED")


def validate_payload(payload: Mapping[str, Any], *, row: Mapping[str, Any], expected_identity: Mapping[str, Any]) -> None:
    if payload.get("schema") != PAYLOAD_SCHEMA or payload.get("solve_count") != 9 or payload.get("resolution") != row["resolution"] or payload.get("provider", {}).get("resolution") != row["resolution"]: raise ValueError("C3_C5_PAYLOAD_RESOLUTION")
    if payload.get("source_sample_id") != row["source_sample_id"] or payload.get("worker_id") != row["sample_id"]: raise ValueError("C3_C5_PAYLOAD_ROW_IDENTITY")
    if payload.get("diagnostic_only") is not True or payload.get("reducer_admissible") is not False or len(payload.get("stencils", {})) != 2: raise ValueError("C3_C5_PAYLOAD_SCHEMA")
    binding = payload.get("c3_c5_transport_binding")
    for key in CANONICAL_IDENTITY_FIELDS:
        if payload.get(key) != expected_identity[key] or not isinstance(binding, Mapping) or binding.get(key) != expected_identity[key] or payload.get(key) != binding.get(key): raise ValueError(f"C3_C5_IDENTITY:{key}")
    validate_h(payload)
    if payload.get("payload_body_sha256") != body_hash(payload): raise ValueError("C3_C5_BODY_HASH")


def validate_process_review(review: Mapping[str, Any]) -> None:
    c2.validate_process_review(review)
    ids = [item["incident_id"] for item in review["incidents"]]
    if set(ids) != set(REQUIRED_INCIDENT_IDS) or len(ids) != len(set(ids)): raise ValueError("C3_C5_PROCESS_REGISTRY")


def construct_checkpoint(*, completed: Sequence[Mapping[str, Any]], execution_sha: str, contract_sha256: str, policy_sha256: str, generation: int) -> dict[str, Any]:
    return {"schema": CHECKPOINT_SCHEMA, "work_order_id": WORK_ORDER, "phase": PHASE, "execution_sha": execution_sha, "contract_sha256": contract_sha256, "rp1_policy_file_sha256": policy_sha256, "generation": generation, "completed_workers": [dict(item) for item in completed]}


def validate_checkpoint(checkpoint: Mapping[str, Any], *, root: Path, rows: Mapping[str, Mapping[str, Any]]) -> None:
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA or checkpoint.get("work_order_id") != WORK_ORDER: raise ValueError("C3_C5_CHECKPOINT_IDENTITY")
    for item in checkpoint.get("completed_workers", []):
        row = rows.get(item["worker_id"])
        if row is None or item.get("resolution") != row["resolution"] or not Path(item["payload_path"]).is_file() or sha(Path(item["payload_path"])) != item.get("payload_file_sha256"): raise ValueError("C3_C5_CHECKPOINT_BINDING")


def matrix_summary(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    entries = [entry for payload in payloads for entry in payload["stencils"].values()]; points = [point for payload in payloads for point in payload["all_point_metrics"]]; replay = [point["frequency_replay"]["max_abs_difference"] for point in points]
    return {"worker_count": len(payloads), "matrix_entry_count": len(entries), "total_native_solves": sum(payload["solve_count"] for payload in payloads), "max_full6_h_offdiag": max(point["H_GATE"]["max_offdiag"] for point in points), "max_selected_pair_h_offdiag": max(point["H_GATE"]["selected_pair_offdiag"] for point in points), "max_h_normalization_error": max(point["H_GATE"]["max_normalization_error"] for point in points), "h_representation_precondition_failure_count": sum(not point["H_GATE"].get("passed", True) for point in points), "replay_matched_point_count": sum(payload["replay_matched_point_count"] for payload in payloads), "replay_unmatched_point_count": sum(payload["replay_unmatched_point_count"] for payload in payloads), "max_abs_frequency_replay_difference": max(replay), "frequency_replay_within_1e8": max(replay) <= 1e-8, "band2_shadow_available_entries": sum(entry["BAND2_PHYSICAL_BRANCH_SHADOW"].get("PHI_RANK1_SHADOW") is not None for entry in entries), "band3_shadow_available_entries": sum(entry["BAND3_PHYSICAL_BRANCH_SHADOW"].get("PHI_RANK1_SHADOW") is not None for entry in entries), "both_rank1_shadows_available_entries": sum(entry["BAND2_PHYSICAL_BRANCH_SHADOW"].get("PHI_RANK1_SHADOW") is not None and entry["BAND3_PHYSICAL_BRANCH_SHADOW"].get("PHI_RANK1_SHADOW") is not None for entry in entries), "rank1_association_ambiguous_entries": sum(entry["association"]["loop_closure"] is not True for entry in entries), "rank2_qualified_entries": sum(entry["L2_RANK2"]["all_edges_qualified"] for entry in entries), "l3_computable_entries": sum(entry.get("L3") is not None for entry in entries)}
