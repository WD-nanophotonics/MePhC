"""C3.C2 hardening layer: pure four-vertex analysis and real replay."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
from typing import Any, Mapping, Sequence
import numpy as np
from audit.e9f import run_e9f_c1_rp2_c3_c1_impl as base

WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-C2-20260825-242"
PHASE = "E9F.C1.RP2.C3.C2"
PARENT_FAILED_EXECUTION_SHA = "2fb27d9394147f1215f93c153cb3d776af89e768"
CONTRACT_REL = Path("audit/e9f/rp2_c3_c2_execution_contract.json")
FAILURE_REL = Path("audit/e9f/rp2_c3_c2_failed_parent_record.json")
POLICY_REL = base.POLICY_REL
RESOLUTIONS = (64, 96); STENCILS = ("1/72", "1/144"); CANARY_SAMPLE_ID = "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID"
H_TOL = base.H_TOL; NORM_TOL = base.NORM_TOL; FREQ_REPLAY_TOL = 1e-8


def sha(path: Path) -> str: return base.sha(path)
def load_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8")); policy = base.load_policy(root); ids = policy["rp2_diagnostic_matrix"]["fixed_sample_ids"]
    for key, expected in {"work_order_id": WORK_ORDER, "phase": PHASE, "parent_failed_execution_sha": PARENT_FAILED_EXECUTION_SHA, "representation": "mpb_periodic_h_l2_v1", "live_provider": "mpb_live_periodic_h_l2_v1", "canary_sample_id": CANARY_SAMPLE_ID, "canary_resolution": 64, "expected_native_solves": 9, "stencils": list(STENCILS)}.items():
        if value.get(key) != expected: raise RuntimeError(f"C3_C2_CONTRACT_{key.upper()}_MISMATCH")
    if value.get("sample_ids_digest") != base.digest(ids): raise RuntimeError("C3_C2_POLICY_SAMPLE_DIGEST_MISMATCH")
    return value
def load_policy(root: Path) -> dict[str, Any]: return base.load_policy(root)
def build_plan(root: Path) -> list[dict[str, Any]]:
    return [row for row in base.build_plan(root) if row["source_sample_id"] == CANARY_SAMPLE_ID and row["resolution"] == 64]
def assert_parent_solver_free() -> None: base.assert_parent_solver_free()
def validate_worker_identity(row: Mapping[str, Any], worker_id: str, resolution: int, coordinate: Sequence[float]) -> None: base.validate_worker_identity(row, worker_id, resolution, coordinate)


def replay_index(root: Path, source_sample_id: str, resolution: int) -> dict[tuple[float, ...], dict[str, Any]]:
    result: dict[tuple[float, ...], dict[str, Any]] = {}; directory = root / "audit/e9f/rp2_evidence/workers"
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("execution_git_sha") != "8121dbfba352b1a77551213771694d25c1bf3f01" or payload.get("source_sample_id") != source_sample_id or int(payload.get("resolution", -1)) != int(resolution): continue
        for entry in payload.get("stencils", {}).values():
            for record in [entry.get("center_sampling", {}), *entry.get("vertex_sampling", [])]:
                q = record.get("EVALUATED_Q")
                if q is not None and record.get("frequencies") is not None: result[tuple(float(x) for x in q)] = {"frequencies": [float(x) for x in record["frequencies"]], "source_path": str(path)}
    return result


def point(raw: Any, nominal: Sequence[float], replay: Mapping[tuple[float, ...], dict[str, Any]]) -> dict[str, Any]:
    result = base._point(raw, nominal); q = tuple(float(x) for x in raw.k_point); prior = replay.get(q)
    if prior is None: result["frequency_replay"] = {"matched": False, "reason": "exact EVALUATED_Q not present in immutable original RP2 worker evidence", "prior_frequencies_all6": None, "current_frequencies_all6": base._freq(raw), "max_abs_difference": None, "tolerance": FREQ_REPLAY_TOL}
    else:
        difference = float(max(abs(a - b) for a, b in zip(base._freq(raw), prior["frequencies"]))); result["frequency_replay"] = {"matched": True, "reason": None, "prior_frequencies_all6": prior["frequencies"], "current_frequencies_all6": base._freq(raw), "max_abs_difference": difference, "tolerance": FREQ_REPLAY_TOL, "source_path": prior["source_path"]}
    return result


def analyze_plaquette(values: Sequence[Any], h: float) -> dict[str, Any]:
    if len(values) != 4: raise ValueError(f"C3_C2_PLAQUETTE_REQUIRES_FOUR_VERTICES:{len(values)}")
    association, maps = base.associate_h(values); b2 = base._rank1_shadow(values, maps, 2, h); b3 = base._rank1_shadow(values, maps, 3, h); rank2 = base._reduce_l2(values); l3 = None
    if b2.get("PHI_RANK1_SHADOW") is not None and b3.get("PHI_RANK1_SHADOW") is not None and rank2.get("PHI_RANK2_DET") is not None:
        p2 = b2["PHI_RANK1_SHADOW"]; p3 = b3["PHI_RANK1_SHADOW"]; p23 = rank2["PHI_RANK2_DET"]; l3 = {"PHI_BAND2": p2, "PHI_BAND3": p3, "PHI_RANK2_DET": p23, "DELTA_PHASE_RANK1SUM_RANK2DET": float(abs(np.angle(np.exp(1j * (p2 + p3 - p23))))), "formula": "abs(Arg(exp(i*(PHI_BAND2 + PHI_BAND3 - PHI_RANK2_DET))))", "status": "DIAGNOSTIC_ONLY"}
    return {"association": association, "BAND2_PHYSICAL_BRANCH_SHADOW": b2, "BAND3_PHYSICAL_BRANCH_SHADOW": b3, "L2_RANK2": {**rank2, "gauge_order_fixtures": base._gauge(values), "independent_of_l1": True}, "L3": l3, "diagnostic_only": True, "reducer_admissible": False}


def compute_worker(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    import meep as mp
    from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs, MESH_SIZE, NUM_BANDS, SOLVER_TOLERANCE
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    from mephc.valley_benchmark import centered_ccw_plaquette_requests
    load_contract(root); geometry = geometry_inputs(); preflight, lattice, solver_geometry, background = build_inputs(geometry); provider = MPBLiveSpectralProvider(geometry=list(solver_geometry), geometry_lattice=lattice, resolution=64, num_bands=NUM_BANDS, polarization=mp.TE, default_material=background, eigensolver_tolerance=SOLVER_TOLERANCE, deterministic=True, mesh_size=MESH_SIZE, norm_tolerance=NORM_TOL, orthogonality_tolerance=H_TOL); center = tuple(float(x) for x in row["authoritative_coordinate"]); replay = replay_index(root, row["source_sample_id"], 64); solves = []; center_raw = provider.solve(center); solves.append(center_raw); center_point = point(center_raw, center, replay); stencils = {}
    for stencil in STENCILS:
        h = 1.0 / int(stencil.split("/")[1]); requests = centered_ccw_plaquette_requests((center,), h, period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest); values = []; vertex_points = []
        for request in requests:
            raw = provider.solve(request.canonical_periodic_vertex_q); solves.append(raw); values.append(raw); vertex_points.append(point(raw, request.nominal_vertex_q, replay))
        analysis = analyze_plaquette(values, h); stencils[stencil] = {"stencil": stencil, "h": h, "vertices": vertex_points, **analysis}
    if len(solves) != 9: raise RuntimeError("C3_C2_CANARY_SOLVE_COUNT_NOT_NINE")
    return {"schema": "mephc_e9f_c1_rp2_c3_c2_worker_v1", "project_id": "MEPHC", "work_order_id": WORK_ORDER, "phase": PHASE, "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "resolution": 64, "authoritative_coordinate": list(row["authoritative_coordinate"]), "execution_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "provider": {"representation": "mpb_periodic_h_l2_v1", "live_provider": "mpb_live_periodic_h_l2_v1", "orthogonality_tolerance": H_TOL, "norm_tolerance": NORM_TOL}, "center": center_point, "stencils": stencils, "all_point_metrics": [center_point] + [p for entry in stencils.values() for p in entry["vertices"]], "solve_count": 9, "replay_matched_point_count": sum(p["frequency_replay"]["matched"] for p in [center_point] + [q for e in stencils.values() for q in e["vertices"]]), "replay_unmatched_point_count": sum(not p["frequency_replay"]["matched"] for p in [center_point] + [q for e in stencils.values() for q in e["vertices"]]), "diagnostic_only": True, "reducer_admissible": False, "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True, "no_extra_sample_points": True, "rp1_policy_sha256": sha(root / POLICY_REL), "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a", "original_rp2_execution_sha": "8121dbfba352b1a77551213771694d25c1bf3f01"}


def validate_worker_payload(payload: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    for key, expected in {"schema": "mephc_e9f_c1_rp2_c3_c2_worker_v1", "project_id": "MEPHC", "work_order_id": WORK_ORDER, "phase": PHASE, "worker_id": row["sample_id"], "resolution": 64, "solve_count": 9, "diagnostic_only": True, "reducer_admissible": False, "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True}.items():
        if payload.get(key) != expected: raise RuntimeError(f"C3_C2_PAYLOAD_{key.upper()}_MISMATCH")
    if len(payload.get("all_point_metrics", [])) != 9 or set(payload.get("stencils", {})) != set(STENCILS): raise RuntimeError("C3_C2_PAYLOAD_COVERAGE_MISMATCH")


def aggregate(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    entries = [e for p in payloads for e in p["stencils"].values()]; b2 = [e["BAND2_PHYSICAL_BRANCH_SHADOW"] for e in entries]; b3 = [e["BAND3_PHYSICAL_BRANCH_SHADOW"] for e in entries]; l3 = [e.get("L3") for e in entries]; replay = [x["frequency_replay"]["max_abs_difference"] for p in payloads for x in p["all_point_metrics"] if x["frequency_replay"]["max_abs_difference"] is not None]
    return {"BAND2_SHADOW_AVAILABLE_ENTRIES": sum(x.get("PHI_RANK1_SHADOW") is not None for x in b2), "BAND3_SHADOW_AVAILABLE_ENTRIES": sum(x.get("PHI_RANK1_SHADOW") is not None for x in b3), "BOTH_RANK1_SHADOWS_AVAILABLE_ENTRIES": sum(x.get("PHI_RANK1_SHADOW") is not None and y.get("PHI_RANK1_SHADOW") is not None for x, y in zip(b2, b3)), "RANK1_ASSOCIATION_AMBIGUOUS_ENTRIES": sum(e["association"]["loop_closure"] is not True for e in entries), "RANK2_QUALIFIED_ENTRIES": sum(e["L2_RANK2"]["all_edges_qualified"] for e in entries), "L3_COMPUTABLE_ENTRIES": sum(x is not None for x in l3), "REPLAY_MATCHED_POINT_COUNT": sum(p["replay_matched_point_count"] for p in payloads), "REPLAY_UNMATCHED_POINT_COUNT": sum(p["replay_unmatched_point_count"] for p in payloads), "MAX_ABS_FREQUENCY_REPLAY_DIFFERENCE": None if not replay else max(replay), "FREQUENCY_REPLAY_WITHIN_1E8": bool(replay) and max(replay) <= FREQ_REPLAY_TOL, "total_native_solves": sum(p["solve_count"] for p in payloads)}
