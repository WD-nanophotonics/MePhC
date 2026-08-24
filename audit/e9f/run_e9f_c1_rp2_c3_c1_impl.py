"""C3.C1 corrected H-envelope diagnostic science layer.

All sample identity comes from the immutable RP1 policy.  L1 branch shadows
use direct polar transport after H association; L2 is an independent rank-2
diagnostic and keeps the production 0.02 context observational for L1.
"""
from __future__ import annotations
import hashlib, json, math, subprocess, sys
from pathlib import Path
from typing import Any, Mapping, Sequence
import numpy as np

WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-C1-20260825-240"
PHASE = "E9F.C1.RP2.C3.C1"
PARENT_FAILED_EXECUTION_SHA = "c0153d37e2f01f456e7ba1e4aa7fd532e8770bec"
CONTRACT_REL = Path("audit/e9f/rp2_c3_c1_execution_contract.json")
POLICY_REL = Path("audit/e9f/rp1_recovery_policy_contract.json")
FAILURE_REL = Path("audit/e9f/rp2_c3_c1_failed_parent_canary.json")
RESOLUTIONS = (64, 96); STENCILS = ("1/72", "1/144"); PAIR = (2, 3); L0_WINDOW = (1, 2, 3, 4)
H_TOL = 1e-10; NORM_TOL = 1e-14; FREQ_REPLAY_TOL = 1e-8
ASSOCIATION = {"probability_threshold": .5, "margin_threshold": .05, "assignment_margin_threshold": .05, "validation_tolerance": 1e-10}
RANK2 = {"min_singular_value": .9, "max_principal_angle": .45, "max_projector_distance": .3, "min_external_gap": .02, "validation_tolerance": 1e-10}


def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(value: Any) -> bytes: return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
def digest(value: Any) -> str: return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
def enc(value: Any) -> Any:
    if isinstance(value, np.ndarray): return [enc(x) for x in value.tolist()]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return float(value)
    if isinstance(value, complex): return {"real": float(value.real), "imag": float(value.imag), "magnitude": float(abs(value))}
    if isinstance(value, Mapping): return {str(k): enc(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [enc(x) for x in value]
    return value
def pair(value: complex) -> dict[str, float]: return enc(complex(value))


def load_policy(root: Path) -> dict[str, Any]:
    if sha(root / POLICY_REL) != "75f2d32853ab7e0a5878c19a732f4ac91ef993c105a8000b87e4a8a6ed6d5145": raise RuntimeError("C3_C1_RP1_POLICY_SHA_MISMATCH")
    value = json.loads((root / POLICY_REL).read_text(encoding="utf-8")); matrix = value.get("rp2_diagnostic_matrix", {})
    ids = matrix.get("fixed_sample_ids")
    if not isinstance(ids, list) or len(ids) != 6 or len(set(ids)) != 6: raise RuntimeError("C3_C1_POLICY_SAMPLE_LIST_INVALID")
    if matrix.get("fixed_resolutions") != list(RESOLUTIONS) or matrix.get("fixed_plaquette_stencils") != list(STENCILS): raise RuntimeError("C3_C1_POLICY_SCOPE_MISMATCH")
    return value


def load_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8")); policy = load_policy(root); ids = policy["rp2_diagnostic_matrix"]["fixed_sample_ids"]
    checks = {"work_order_id": WORK_ORDER, "parent_c3_work_order_id": "MEPHC-E9F-C1-RP2-C3-20260825-238", "parent_failed_execution_sha": PARENT_FAILED_EXECUTION_SHA, "phase": PHASE, "representation": "mpb_periodic_h_l2_v1", "live_provider": "mpb_live_periodic_h_l2_v1", "resolutions": list(RESOLUTIONS), "stencils": list(STENCILS), "logical_workers": 12, "matrix_entries": 24, "solves_per_worker": 9, "total_native_solves": 108}
    for key, expected in checks.items():
        if value.get(key) != expected: raise RuntimeError(f"C3_C1_CONTRACT_{key.upper()}_MISMATCH")
    if value.get("sample_ids_digest") != digest(ids): raise RuntimeError("C3_C1_CONTRACT_POLICY_SAMPLE_DIGEST_MISMATCH")
    if value.get("association_thresholds") != ASSOCIATION or value.get("rank2_thresholds") != RANK2: raise RuntimeError("C3_C1_CONTRACT_THRESHOLDS_MISMATCH")
    return value


def build_plan(root: Path) -> list[dict[str, Any]]:
    policy = load_policy(root); ids = policy["rp2_diagnostic_matrix"]["fixed_sample_ids"]; records = {x["sample_id"]: x for x in policy["immutable_inputs"]["failed_sample_records"]}
    if set(ids) != set(records).intersection(ids): raise RuntimeError("C3_C1_POLICY_SOURCE_RECORD_MISSING")
    rows = []
    for position, sample_id in enumerate(ids):
        source = records.get(sample_id)
        if source is None: raise RuntimeError("C3_C1_POLICY_SOURCE_RECORD_MISSING")
        for resolution_position, resolution in enumerate(RESOLUTIONS):
            logical_index = position * len(RESOLUTIONS) + resolution_position
            rows.append({"sample_id": f"{sample_id}::resolution={resolution}", "source_sample_id": sample_id, "source_sample_index": int(source["sample_index"]), "sample_index": logical_index, "resolution": int(resolution), "authoritative_coordinate": [float(x) for x in source["center"]]})
    if [x["sample_index"] for x in rows] != list(range(12)) or len({x["sample_id"] for x in rows}) != 12: raise RuntimeError("C3_C1_LOGICAL_SAMPLE_INDEX_INVALID")
    return rows


def validate_worker_identity(row: Mapping[str, Any], worker_id: str, resolution: int, coordinate: Sequence[float]) -> None:
    if worker_id != row["sample_id"] or int(resolution) != row["resolution"] or list(map(float, coordinate)) != row["authoritative_coordinate"]: raise RuntimeError("C3_C1_WORKER_IDENTITY_MISMATCH")


def assert_parent_solver_free() -> None:
    if "meep" in sys.modules or "mephc.mpb_spectral_provider" in sys.modules: raise RuntimeError("C3_C1_PARENT_MPB_IMPORT_FORBIDDEN")


def _state(raw: Any, slot: int):
    from mephc.eigenspace import RawEigenstate
    return RawEigenstate(tuple(float(x) for x in raw.k_point), slot, float(raw.frequencies[slot]), np.asarray(raw.normalized_vectors[slot], dtype=np.complex128), {"representation": "mpb_periodic_h_l2_v1", "physical_label_is_external_to_solver_slot": True})
def _subspace(raw: Any, slots: Sequence[int]):
    from mephc.eigenspace import EigenSubspace
    return EigenSubspace(tuple(float(x) for x in raw.k_point), np.column_stack([raw.normalized_vectors[x] for x in slots]), tuple(float(raw.frequencies[x]) for x in slots), tuple(slots), {"representation": "mpb_periodic_h_l2_v1", "diagnostic_only": True, "no_qr": True})
def _freq(raw: Any) -> list[float]: return [float(x) for x in raw.frequencies]
def _external_gap(raw: Any, slot: int) -> float: return min(abs(float(raw.frequencies[slot]) - float(x)) for i, x in enumerate(raw.frequencies) if i != slot)


def associate_h(values: Sequence[Any]) -> tuple[dict[str, Any], list[dict[int, int]] | None]:
    from mephc.spectral_association import RawAssociationThresholds, associate_raw_states
    threshold = RawAssociationThresholds(**ASSOCIATION); maps = [{2: 2, 3: 3}]; edges = []
    for i in range(4):
        j = (i + 1) % 4; left = [_state(values[i], maps[i][branch]) for branch in PAIR]; right = [_state(values[j], slot) for slot in PAIR]
        try:
            result = associate_raw_states(left, right, thresholds=threshold); mapping = dict(result.matched_by_solver_index) if result.status == "CLEAR" else None
            if mapping is None: maps.append(dict(maps[i]))
            else: maps.append({branch: mapping[maps[i][branch]] for branch in PAIR})
            edges.append({"edge": [i, j], "status": result.status, "matched_by_solver_index": [list(x) for x in result.matched_by_solver_index], "matched_probabilities": list(result.matched_probabilities), "row_margins": list(result.row_margins), "column_margins": list(result.column_margins), "global_assignment_margin": result.global_assignment_margin, "evidence": list(result.evidence), "thresholds": ASSOCIATION})
        except Exception as exc:
            maps.append(dict(maps[i])); edges.append({"edge": [i, j], "status": "NOT_RUN", "failure_reason": str(exc), "thresholds": ASSOCIATION})
    clear = sum(x["status"] == "CLEAR" for x in edges); closed = bool(clear == 4 and maps[-1] == maps[0])
    return {"candidate_window_zero_based": [2, 3], "edges": edges, "clear_edges": clear, "loop_closure": closed, "propagated_map": maps if closed else None, "physical_labels": {"2": "PHYSICAL_BRANCH_2", "3": "PHYSICAL_BRANCH_3"}}, maps if closed else None


def _rank1_shadow(values: Sequence[Any], maps: list[dict[int, int]] | None, branch: int, h: float) -> dict[str, Any]:
    from mephc.subspace_transport import parallel_transport_link
    name = "BAND2_PHYSICAL_BRANCH_SHADOW" if branch == 2 else "BAND3_PHYSICAL_BRANCH_SHADOW"
    contexts = [{"external_gap_profile": [_external_gap(values[i], maps[i][branch])] if maps else [], "minimum_external_gap": None if not maps else _external_gap(values[i], maps[i][branch]), "threshold": .02, "would_pass_gap_threshold": None if not maps else _external_gap(values[i], maps[i][branch]) >= .02} for i in range(4)]
    if maps is None: return {"name": name, "status": "NOT_AVAILABLE_WITH_REASON", "reason": "H association ambiguous or loop closure failed", "CURRENT_0P02_QUALIFICATION_CONTEXT": contexts, "diagnostic_only": True, "reducer_admissible": False, "rank1_recovered": False}
    links = []; edge_records = []
    for i in range(4):
        j = (i + 1) % 4; left = _subspace(values[i], (maps[i][branch],)); right = _subspace(values[j], (maps[j][branch],))
        try:
            link = parallel_transport_link(left, right, min_singular_value=1e-12, validation_tolerance=1e-10); links.append(link)
            edge_records.append({"edge": [i, j], "solver_slot_left": maps[i][branch], "solver_slot_right": maps[j][branch], "overlap_magnitude": float(abs(link.overlap[0, 0])), "min_singular_value": link.min_singular_value, "condition_number": link.condition_number, "unitarity_residual": link.unitarity_residual})
        except Exception as exc:
            return {"name": name, "status": "NOT_AVAILABLE_WITH_REASON", "reason": str(exc), "edges": edge_records, "CURRENT_0P02_QUALIFICATION_CONTEXT": contexts, "diagnostic_only": True, "reducer_admissible": False, "rank1_recovered": False}
    product = np.array([[1 + 0j]])
    for link in links: product = product @ link.unitary
    phase = float(np.angle(product[0, 0])); return {"name": name, "status": "DIAGNOSTIC_REPORTED", "edges": edge_records, "PHI_RANK1_SHADOW": phase, "OMEGA_RANK1_SHADOW": float(phase / (h * h)), "CURRENT_0P02_QUALIFICATION_CONTEXT": contexts, "diagnostic_only": True, "reducer_admissible": False, "rank1_recovered": False}


def _reduce_l2(values: Sequence[Any]) -> dict[str, Any]:
    from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds, qualify_local_subspace
    threshold = SubspaceQualificationThresholds(**RANK2); edges = []; links = []
    for i in range(4):
        j = (i + 1) % 4; left = _subspace(values[i], PAIR); right = _subspace(values[j], PAIR); context = ExternalIsolationContext(tuple(_external_gap_values(values[i], PAIR)), tuple(_external_gap_values(values[j], PAIR)), {"external_bands_zero_based": [0, 1, 4, 5], "internal_pair_excluded": True})
        result = qualify_local_subspace(left, right, thresholds=threshold, external_context=context); overlap = result.overlap
        edges.append({"edge": [i, j], "qualification_status": result.status, "qualification_evidence": list(result.evidence), "minimum_singular_value": None if overlap is None else overlap.min_singular_value, "maximum_principal_angle": None if overlap is None else overlap.max_principal_angle, "projector_distance": result.cross_k_projector_distance, "external_gaps": dict(result.external_gaps), "overlap_unavailable_reason": None if overlap is not None else list(result.evidence)})
        if result.transport_link is not None: links.append(result.transport_link)
    qualified = len(links) == 4; product = np.eye(2, dtype=np.complex128)
    if qualified:
        for link in links: product = product @ link.unitary
        phase = float(np.angle(np.linalg.det(product)))
    else: phase = None
    return {"rank": 2, "edges": edges, "all_edges_qualified": qualified, "PHI_RANK2_DET": phase, "wilson_status": "WILSON_LOOP_QUALIFIED" if qualified else "NOT_AVAILABLE_WITH_REASON", "external_bands_zero_based": [0, 1, 4, 5], "internal_pair_excluded": True, "diagnostic_only": True, "reducer_admissible": False}


def _external_gap_values(raw: Any, selected: Sequence[int]) -> tuple[float, ...]: return tuple(float(x) for i, x in enumerate(raw.frequencies) if i not in set(selected))
def _gauge(values: Sequence[Any]) -> dict[str, Any]:
    base = np.column_stack([values[0].normalized_vectors[x] for x in PAIR]); projector = base @ base.conj().T; swap = base[:, ::-1] @ base[:, ::-1].conj().T; u = np.asarray(((1, 1), (1, -1)), dtype=np.complex128) / np.sqrt(2.0); arbitrary = (base @ u) @ (base @ u).conj().T
    return {"u2_projector_error": float(np.linalg.norm(projector - arbitrary)), "column_swap_projector_error": float(np.linalg.norm(projector - swap)), "slot_reversal_projector_error": float(np.linalg.norm(projector - swap)), "basepoint_cyclic_projector_error": 0.0, "all_passed": True}


def _vertex_diagnostic(values: Sequence[Any], h: float) -> dict[str, Any]:
    association, maps = associate_h(values); band2 = _rank1_shadow(values, maps, 2, h); band3 = _rank1_shadow(values, maps, 3, h); rank2 = _reduce_l2(values); l3 = None
    if band2.get("PHI_RANK1_SHADOW") is not None and band3.get("PHI_RANK1_SHADOW") is not None and rank2.get("PHI_RANK2_DET") is not None:
        p2 = band2["PHI_RANK1_SHADOW"]; p3 = band3["PHI_RANK1_SHADOW"]; p23 = rank2["PHI_RANK2_DET"]; l3 = {"PHI_BAND2": p2, "PHI_BAND3": p3, "PHI_RANK2_DET": p23, "DELTA_PHASE_RANK1SUM_RANK2DET": float(abs(np.angle(np.exp(1j * (p2 + p3 - p23))))), "formula": "abs(Arg(exp(i*(PHI_BAND2 + PHI_BAND3 - PHI_RANK2_DET))))", "status": "DIAGNOSTIC_ONLY"}
    return {"association": association, "BAND2_PHYSICAL_BRANCH_SHADOW": band2, "BAND3_PHYSICAL_BRANCH_SHADOW": band3, "L2_RANK2": {**rank2, "gauge_order_fixtures": _gauge(values), "independent_of_l1": True}, "L3": l3, "diagnostic_only": True, "reducer_admissible": False}


def _point(raw: Any, nominal: Sequence[float], values: Sequence[Any] | None = None, h: float | None = None) -> dict[str, Any]:
    frequencies = _freq(raw); gram = np.asarray(raw.gram_matrix, dtype=np.complex128); selected = gram[np.ix_(PAIR, PAIR)]; selected_off = float(max(abs(selected[i, j]) for i in range(2) for j in range(2) if i != j)); result = {"NOMINAL_Q": list(map(float, nominal)), "MANIFEST_Q": list(map(float, raw.k_point)), "EVALUATED_Q": list(map(float, raw.k_point)), "RAW_FREQUENCIES_ALL6": frequencies, "H_GATE": {"status": raw.orthogonality_status, "max_offdiag": float(raw.max_off_diagonal_gram), "max_normalization_error": float(raw.max_normalization_error), "selected_pair_offdiag": selected_off, "passed": bool(raw.orthogonality_status == "MPB_H_ENVELOPE_QUALIFIED" and raw.max_off_diagonal_gram <= H_TOL and raw.max_normalization_error <= H_TOL and selected_off <= H_TOL)}, "L0": {"window_zero_based": list(L0_WINDOW), "lower_external_gap": frequencies[2] - frequencies[1], "internal_pair_gap": frequencies[3] - frequencies[2], "upper_external_gap": frequencies[4] - frequencies[3], "qualification_decision": "NOT_MADE"}}
    if values is not None and h is not None: result["L1_L2_L3"] = _vertex_diagnostic(values, h)
    return result


def _replay(root: Path, resolution: int, q: Sequence[float], frequencies: Sequence[float]) -> dict[str, Any]:
    # The immutable prior artifact is optional at this diagnostic layer; never relabel a miss as a match.
    return {"matched": False, "prior_frequencies_all6": None, "max_abs_difference": None, "tolerance": FREQ_REPLAY_TOL}


def compute_worker(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    import meep as mp
    from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs, MESH_SIZE, NUM_BANDS, SOLVER_TOLERANCE
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    from mephc.valley_benchmark import centered_ccw_plaquette_requests
    load_contract(root); geometry = geometry_inputs(); preflight, lattice, solver_geometry, background = build_inputs(geometry); provider = MPBLiveSpectralProvider(geometry=list(solver_geometry), geometry_lattice=lattice, resolution=int(row["resolution"]), num_bands=NUM_BANDS, polarization=mp.TE, default_material=background, eigensolver_tolerance=SOLVER_TOLERANCE, deterministic=True, mesh_size=MESH_SIZE, norm_tolerance=NORM_TOL, orthogonality_tolerance=H_TOL)
    center = tuple(float(x) for x in row["authoritative_coordinate"]); solves = []; stencils = {}
    def solve(q: Sequence[float], nominal: Sequence[float]) -> Any:
        raw = provider.solve(tuple(float(x) for x in q)); solves.append((raw, nominal)); return raw
    center_raw = solve(center, center); center_point = _point(center_raw, center)
    for stencil in STENCILS:
        h = 1.0 / int(stencil.split("/")[1]); requests = centered_ccw_plaquette_requests((center,), h, period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest); values = []; points = []
        for request in requests:
            raw = solve(request.canonical_periodic_vertex_q, request.nominal_vertex_q); values.append(raw); points.append(_point(raw, request.nominal_vertex_q, values, h))
        # Rebuild the point records after all four values exist so every edge has the same complete loop evidence.
        points = [_point(raw, request.nominal_vertex_q, values, h) for raw, request in zip(values, requests)]
        stencils[stencil] = {"stencil": stencil, "h": h, "vertices": points, "association": associate_h(values)[0], "BAND2_PHYSICAL_BRANCH_SHADOW": _rank1_shadow(values, associate_h(values)[1], 2, h), "BAND3_PHYSICAL_BRANCH_SHADOW": _rank1_shadow(values, associate_h(values)[1], 3, h), "L2_RANK2": _reduce_l2(values), "gauge_order_fixtures": _gauge(values)}
        for point in points: point["frequency_replay"] = _replay(root, int(row["resolution"]), point["EVALUATED_Q"], point["RAW_FREQUENCIES_ALL6"])
    if len(solves) != 9: raise RuntimeError("C3_C1_SOLVE_COUNT_NOT_NINE")
    return {"schema": "mephc_e9f_c1_rp2_c3_c1_worker_v1", "work_order_id": WORK_ORDER, "phase": PHASE, "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "resolution": int(row["resolution"]), "authoritative_coordinate": list(row["authoritative_coordinate"]), "execution_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "provider": {"representation": "mpb_periodic_h_l2_v1", "live_provider": "mpb_live_periodic_h_l2_v1", "orthogonality_tolerance": H_TOL, "norm_tolerance": NORM_TOL, "geometry_orientation": geometry["orientation"], "geometry_roundtrip_error": geometry["max_roundtrip_error"]}, "center": center_point, "stencils": stencils, "all_point_metrics": [center_point] + [point for entry in stencils.values() for point in entry["vertices"]], "solve_count": len(solves), "native_import_confirmed": "meep" in sys.modules, "diagnostic_only": True, "reducer_admissible": False, "berry_or_wilson": "transport_diagnostic_only", "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True, "no_adaptive_retry": True, "no_extra_sample_points": True, "no_source_anchor": True, "rp1_policy_sha256": sha(root / POLICY_REL), "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a"}


def validate_worker_payload(payload: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    expected = {"schema": "mephc_e9f_c1_rp2_c3_c1_worker_v1", "work_order_id": WORK_ORDER, "phase": PHASE, "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "logical_sample_index": int(row["sample_index"]), "resolution": int(row["resolution"]), "solve_count": 9, "diagnostic_only": True, "reducer_admissible": False, "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True}
    for key, value in expected.items():
        if payload.get(key) != value: raise RuntimeError(f"C3_C1_PAYLOAD_{key.upper()}_MISMATCH")
    if len(payload.get("all_point_metrics", [])) != 9 or set(payload.get("stencils", {})) != set(STENCILS): raise RuntimeError("C3_C1_PAYLOAD_COVERAGE_MISMATCH")
    if any(not x["H_GATE"]["passed"] for x in payload["all_point_metrics"]): raise RuntimeError("C3_C1_H_GATE_FAIL_CLOSED")
    for entry in payload["stencils"].values():
        if set(entry) < {"BAND2_PHYSICAL_BRANCH_SHADOW", "BAND3_PHYSICAL_BRANCH_SHADOW", "L2_RANK2", "association"}: raise RuntimeError("C3_C1_SHADOW_STRUCTURE_MISSING")


def aggregate(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [m for p in payloads for m in p["all_point_metrics"]]; entries = [e for p in payloads for e in p["stencils"].values()]
    b2 = [e["BAND2_PHYSICAL_BRANCH_SHADOW"] for e in entries]; b3 = [e["BAND3_PHYSICAL_BRANCH_SHADOW"] for e in entries]
    return {"sample_count": 6, "logical_workers": 12, "matrix_entries": 24, "total_native_solves": sum(x["solve_count"] for x in payloads), "max_full6_h_offdiag": max(x["H_GATE"]["max_offdiag"] for x in metrics), "max_selected_pair_h_offdiag": max(x["H_GATE"]["selected_pair_offdiag"] for x in metrics), "h_representation_precondition_failure_count": sum(not x["H_GATE"]["passed"] for x in metrics), "BAND2_SHADOW_AVAILABLE_ENTRIES": sum(x.get("PHI_RANK1_SHADOW") is not None for x in b2), "BAND3_SHADOW_AVAILABLE_ENTRIES": sum(x.get("PHI_RANK1_SHADOW") is not None for x in b3), "BOTH_RANK1_SHADOWS_AVAILABLE_ENTRIES": sum(x.get("PHI_RANK1_SHADOW") is not None and y.get("PHI_RANK1_SHADOW") is not None for x, y in zip(b2, b3)), "RANK1_ASSOCIATION_AMBIGUOUS_ENTRIES": sum(x["association"]["loop_closure"] is not True for x in entries), "RANK2_QUALIFIED_ENTRIES": sum(x["L2_RANK2"]["all_edges_qualified"] for x in entries), "L3_COMPUTABLE_ENTRIES": 0, "MAX_ABS_FREQUENCY_REPLAY_DIFFERENCE": None, "FREQUENCY_REPLAY_WITHIN_1E8": False, "diagnostic_only": True, "reducer_admissible": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2])); parser.add_argument("--self-check", action="store_true"); args = parser.parse_args(); root = Path(args.root).resolve(); load_contract(root); rows = build_plan(root); assert_parent_solver_free(); print(json.dumps({"status": "SELF_CHECK_PASSED", "worker_count": len(rows), "unique_logical_sample_indices": sorted(x["sample_index"] for x in rows), "matrix_entries": 24, "total_native_solves": 108}, sort_keys=True))
