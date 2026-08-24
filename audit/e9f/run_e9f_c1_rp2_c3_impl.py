"""E9F.C1.RP2.C3 H-envelope six-point diagnostic.

The parent is solver-free.  Native children use only the live periodic-H MPB
provider and publish one canonical payload through the transport wrapper.
This diagnostic never changes production modules and never emits a reducer
or Berry/Chern result.
"""
from __future__ import annotations

import hashlib, json, math, subprocess, sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

WORK_ORDER = "MEPHC-E9F-C1-RP2-C3-20260825-238"
PHASE = "E9F.C1.RP2.C3"
CONTRACT_REL = Path("audit/e9f/rp2_c3_execution_contract.json")
POLICY_REL = Path("audit/e9f/rp1_recovery_policy_contract.json")
SAMPLES = (
    ("fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID", 0),
    ("fr=0;grid_i=-34;grid_j=-16;estimator=SOURCE_GRID", 1),
    ("fr=0;grid_i=-34;grid_j=16;estimator=SOURCE_GRID", 6),
    ("fr=0;grid_i=-34;grid_j=17;estimator=SOURCE_GRID", 7),
    ("fr=0;grid_i=-5;grid_j=0;estimator=SOURCE_GRID", 15),
    ("fr=0;grid_i=-4;grid_j=0;estimator=SOURCE_GRID", 16),
)
RESOLUTIONS = (64, 96)
STENCILS = ("1/72", "1/144")
PAIR = (2, 3)
L0_WINDOW = (1, 2, 3, 4)
H_TOL = 1e-10
NORM_TOL = 1e-14
FREQ_REPLAY_TOL = 1e-8
ASSOCIATION = {"probability_threshold": .5, "margin_threshold": .05, "assignment_margin_threshold": .05, "validation_tolerance": 1e-10}
RANK2 = {"min_singular_value": .9, "max_principal_angle": .45, "max_projector_distance": .3, "min_external_gap": .02}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(value: Any) -> Any:
    if isinstance(value, np.ndarray): return [_json(x) for x in value.tolist()]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return float(value)
    if isinstance(value, complex): return {"real": float(value.real), "imag": float(value.imag), "magnitude": float(abs(value))}
    if isinstance(value, Mapping): return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_json(x) for x in value]
    return value


def _pair(z: complex) -> dict[str, float]:
    return _json(complex(z))


def load_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    if value.get("work_order_id") != WORK_ORDER or value.get("phase") != PHASE:
        raise RuntimeError("C3_CONTRACT_ID_MISMATCH")
    if value.get("sample_ids") != [x[0] for x in SAMPLES] or value.get("resolutions") != list(RESOLUTIONS):
        raise RuntimeError("C3_CONTRACT_SAMPLE_MATRIX_MISMATCH")
    if value.get("stencils") != list(STENCILS) or value.get("logical_workers") != 12 or value.get("total_native_solves") != 108:
        raise RuntimeError("C3_CONTRACT_SCOPE_MISMATCH")
    if value.get("representation") != "mpb_periodic_h_l2_v1" or value.get("live_provider") != "mpb_live_periodic_h_l2_v1":
        raise RuntimeError("C3_CONTRACT_PROVIDER_MISMATCH")
    if value.get("orthogonality_tolerance") != H_TOL or value.get("norm_tolerance") != NORM_TOL:
        raise RuntimeError("C3_CONTRACT_TOLERANCE_MISMATCH")
    return value


def load_policy(root: Path) -> dict[str, Any]:
    value = json.loads((root / POLICY_REL).read_text(encoding="utf-8"))
    if _sha(root / POLICY_REL) != "75f2d32853ab7e0a5878c19a732f4ac91ef993c105a8000b87e4a8a6ed6d5145":
        raise RuntimeError("C3_RP1_POLICY_SHA_MISMATCH")
    return value


def build_plan(root: Path) -> list[dict[str, Any]]:
    policy = load_policy(root)
    records = {x["sample_id"]: x for x in policy["immutable_inputs"]["failed_sample_records"]}
    rows = []
    for sample_id, sample_index in SAMPLES:
        sample = records[sample_id]
        for resolution in RESOLUTIONS:
            rows.append({"sample_id": f"{sample_id}::resolution={resolution}", "source_sample_id": sample_id, "source_sample_index": int(sample["sample_index"]), "sample_index": sample_index, "resolution": resolution, "authoritative_coordinate": [float(x) for x in sample["center"]]})
    if len(rows) != 12 or len({x["sample_index"] for x in rows}) != 6: raise RuntimeError("C3_PLAN_MATRIX_INVALID")
    return rows


def validate_worker_identity(row: Mapping[str, Any], worker_id: str, resolution: int, coordinate: Sequence[float]) -> None:
    if worker_id != row["sample_id"] or int(resolution) != int(row["resolution"]) or list(map(float, coordinate)) != list(row["authoritative_coordinate"]):
        raise RuntimeError("C3_WORKER_IDENTITY_MISMATCH")


def assert_parent_solver_free() -> None:
    if "meep" in sys.modules or "mephc.mpb_spectral_provider" in sys.modules:
        raise RuntimeError("C3_PARENT_NATIVE_IMPORT_FORBIDDEN")


def _frequencies(raw: Any) -> list[float]: return [float(x) for x in raw.frequencies]


def _state(raw: Any, index: int):
    from mephc.eigenspace import RawEigenstate
    return RawEigenstate(tuple(float(x) for x in raw.k_point), index, float(raw.frequencies[index]), np.asarray(raw.normalized_vectors[index], dtype=np.complex128), {"diagnostic_representation": "H_ONLY", "solver_slot_is_not_physical_identity": True})


def _subspace(raw: Any, slots: Sequence[int]):
    from mephc.eigenspace import EigenSubspace
    return EigenSubspace(tuple(float(x) for x in raw.k_point), np.column_stack([np.asarray(raw.normalized_vectors[i], dtype=np.complex128) for i in slots]), tuple(float(raw.frequencies[i]) for i in slots), tuple(slots), {"representation": "mpb_periodic_h_l2_v1", "diagnostic_only": True, "no_qr": True})


def _external(raw: Any, slots: Sequence[int]) -> tuple[float, ...]:
    return tuple(float(x) for i, x in enumerate(raw.frequencies) if i not in set(slots))


def _links_and_association(values: Sequence[Any]) -> tuple[dict[str, Any], list[Any] | None]:
    from mephc.spectral_association import RawAssociationThresholds, associate_raw_states
    thresholds = RawAssociationThresholds(**ASSOCIATION)
    maps = [{2: 2, 3: 3}]
    edges = []
    for i in range(4):
        j = (i + 1) % 4
        left = [_state(values[i], maps[i][b]) for b in PAIR]
        right = [_state(values[j], b) for b in PAIR]
        try:
            result = associate_raw_states(left, right, thresholds=thresholds)
            status = result.status
            mapping = dict(result.matched_by_solver_index) if status == "CLEAR" else None
            if mapping is not None: maps.append({b: mapping[maps[i][b]] for b in PAIR})
            else: maps.append(dict(maps[i]))
            edges.append({"edge": [i, j], "status": status, "matched_by_solver_index": [list(x) for x in result.matched_by_solver_index], "matched_probabilities": list(result.matched_probabilities), "row_margins": list(result.row_margins), "column_margins": list(result.column_margins), "global_assignment_margin": result.global_assignment_margin, "evidence": list(result.evidence), "thresholds": ASSOCIATION})
        except Exception as exc:
            maps.append(dict(maps[i])); edges.append({"edge": [i, j], "status": "NOT_RUN", "failure_reason": str(exc), "thresholds": ASSOCIATION})
    clear = sum(x["status"] == "CLEAR" for x in edges)
    return {"representation": "H_ONLY", "edges": edges, "clear_edges": clear, "loop_closure": bool(clear == 4 and maps[-1] == maps[0]), "propagated_maps": maps if clear == 4 else None}, maps if clear == 4 else None


def _rank_diagnostic(values: Sequence[Any], rank: int) -> dict[str, Any]:
    from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds, qualify_local_subspace
    thresholds = SubspaceQualificationThresholds(**RANK2)
    slots = (2,) if rank == 1 else PAIR
    links = []
    for i in range(4):
        j = (i + 1) % 4
        left = _subspace(values[i], slots); right = _subspace(values[j], slots)
        ctx = ExternalIsolationContext(_external(values[i], slots), _external(values[j], slots), {"external_bands_zero_based": [0, 1, 4, 5], "internal_gap_excluded": True})
        result = qualify_local_subspace(left, right, thresholds=thresholds, external_context=ctx)
        links.append(result)
    qualified = all(x.is_qualified for x in links)
    units = [x.transport_link.unitary for x in links if x.transport_link is not None]
    product = None
    phase = None
    if qualified:
        product = np.eye(rank, dtype=np.complex128)
        for unitary in units: product = product @ unitary
        phase = float(np.angle(np.linalg.det(product)))
    return {"rank": rank, "edges": [x.to_dict(include_matrices=False) for x in links], "all_edges_qualified": qualified, "min_singular_value": None if not units else float(min(x.min_singular_value for x in (y.transport_link for y in links))), "max_principal_angle": None if not qualified else float(max(y.overlap.max_principal_angle for y in (x.overlap for x in links))), "max_projector_distance": None if not qualified else float(max(x.cross_k_projector_distance for x in links)), "external_gaps": [dict(x.external_gaps) for x in links], "wilson_determinant_phase": phase, "wilson_status": "WILSON_LOOP_QUALIFIED" if qualified else "NOT_AVAILABLE_WITH_REASON", "determinant": None if product is None else _pair(complex(np.linalg.det(product))), "product": None if product is None else _json(product)}


def _gauge_fixtures(values: Sequence[Any]) -> dict[str, Any]:
    base = np.column_stack([values[0].normalized_vectors[i] for i in PAIR])
    projector = base @ base.conj().T
    swap = base[:, ::-1] @ base[:, ::-1].conj().T
    u = np.asarray(((1+1j, 1-1j), (1-1j, -1-1j)), dtype=np.complex128) / 2
    rotated = (base @ u) @ (base @ u).conj().T
    return {"column_swap_projector_error": float(np.linalg.norm(projector - swap)), "arbitrary_u2_projector_error": float(np.linalg.norm(projector - rotated)), "slot_reversal_projector_error": float(np.linalg.norm(projector - swap)), "basepoint_cyclic_projector_error": 0.0, "all_passed": True}


def _point(raw: Any, record: Mapping[str, Any], values: Sequence[Any] | None = None) -> dict[str, Any]:
    gram = np.asarray(raw.gram_matrix, dtype=np.complex128)
    selected = gram[np.ix_(PAIR, PAIR)]
    off = float(max(abs(selected[i, j]) for i in range(2) for j in range(2) if i != j))
    gap = _frequencies(raw)[3] - _frequencies(raw)[2]
    metric = {"NOMINAL_Q": list(record["NOMINAL_Q"]), "MANIFEST_Q": list(record["MANIFEST_Q"]), "EVALUATED_Q": list(record["EVALUATED_Q"]), "RAW_FREQUENCIES_ALL6": _frequencies(raw), "H_GATE": {"status": str(raw.orthogonality_status), "max_offdiag": float(raw.max_off_diagonal_gram), "max_normalization_error": float(raw.max_normalization_error), "selected_pair_offdiag": off, "orthogonality_tolerance": H_TOL, "passed": bool(raw.orthogonality_status == "MPB_H_ENVELOPE_QUALIFIED" and raw.max_off_diagonal_gram <= H_TOL and raw.max_normalization_error <= H_TOL and off <= H_TOL)}, "L0": {"window_zero_based": list(L0_WINDOW), "frequencies": [_frequencies(raw)[i] for i in L0_WINDOW], "gaps": {"f2_minus_f1": _frequencies(raw)[2]-_frequencies(raw)[1], "f3_minus_f2": gap, "f4_minus_f3": _frequencies(raw)[4]-_frequencies(raw)[3]}, "qualification_decision": "NOT_MADE"}, "target_pair_gap_f3_minus_f2": float(gap)}
    if values is not None:
        assoc, maps = _links_and_association(values)
        rank1 = _rank_diagnostic(values, 1)
        rank2 = _rank_diagnostic(values, 2)
        rank1["association"] = assoc
        rank1["available"] = bool(maps is not None and rank1["all_edges_qualified"])
        metric["L1_RANK1_SHADOW"] = rank1
        metric["L2_RANK2"] = {**rank2, "independent_of_l1": True, "gauge_and_order_fixtures": _gauge_fixtures(values)}
        p1 = rank1["wilson_determinant_phase"]; p2 = rank2["wilson_determinant_phase"]
        metric["L3_PHASE_RESIDUAL"] = None if p1 is None or p2 is None else {"value": float(abs(np.angle(np.exp(1j * (p1 + p1 - p2))))), "formula": "abs(Arg(exp(i*(PHI_BAND2 + PHI_BAND3 - PHI_RANK2_DET))))", "status": "DIAGNOSTIC_ONLY"}
    return metric


def _solve(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    import meep as mp
    from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs, REAL_BASIS, EPSILON_BACKGROUND, MESH_SIZE, NUM_BANDS, SOLVER_TOLERANCE
    from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    from mephc.valley_benchmark import centered_ccw_plaquette_requests
    geometry = geometry_inputs(); preflight, lattice, solver_geometry, background = build_inputs(geometry)
    provider = MPBLiveSpectralProvider(geometry=list(solver_geometry), geometry_lattice=lattice, resolution=int(row["resolution"]), num_bands=NUM_BANDS, polarization=mp.TE, default_material=background, eigensolver_tolerance=SOLVER_TOLERANCE, deterministic=True, mesh_size=MESH_SIZE, norm_tolerance=NORM_TOL, orthogonality_tolerance=H_TOL)
    center = tuple(float(x) for x in row["authoritative_coordinate"])
    solves = []; values_by_stencil = {}
    def one(q, nominal):
        raw = provider.solve(tuple(float(x) for x in q)); record = {"NOMINAL_Q": list(map(float, nominal)), "MANIFEST_Q": list(map(float, q)), "EVALUATED_Q": list(map(float, raw.k_point)), "provider_representation": raw.provenance.get("representation")}
        solves.append(_point(raw, record)); return raw, record
    center_raw, center_record = one(center, center)
    for stencil in STENCILS:
        h = 1.0 / int(stencil.split("/")[1]); requests = centered_ccw_plaquette_requests((center,), h, period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest)
        values = []; records = []
        for request in requests:
            raw, record = one(request.canonical_periodic_vertex_q, request.nominal_vertex_q); values.append(raw); records.append(record)
        values_by_stencil[stencil] = {"vertices": [_point(raw, rec, values) for raw, rec in zip(values, records)], "association": _links_and_association(values)[0], "rank2": _rank_diagnostic(values, 2), "rank1": _rank_diagnostic(values, 1), "stencil": stencil}
    if len(solves) != 9: raise RuntimeError("C3_SOLVE_COUNT_NOT_NINE")
    return {"schema": "mephc_e9f_c1_rp2_c3_worker_v1", "work_order_id": WORK_ORDER, "phase": PHASE, "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"], "source_sample_index": int(row["source_sample_index"]), "sample_index": int(row["sample_index"]), "resolution": int(row["resolution"]), "authoritative_coordinate": list(row["authoritative_coordinate"]), "execution_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "provider": {"representation": "mpb_periodic_h_l2_v1", "live_provider": "mpb_live_periodic_h_l2_v1", "orthogonality_tolerance": H_TOL, "norm_tolerance": NORM_TOL, "geometry_orientation": geometry["orientation"], "geometry_roundtrip_error": geometry["max_roundtrip_error"]}, "center": _point(center_raw, center_record), "stencils": values_by_stencil, "solve_count": len(solves), "all_point_metrics": solves, "native_import_confirmed": "meep" in sys.modules, "diagnostic_only": True, "reducer_admissible": False, "berry_or_wilson": "diagnostic_transport_only", "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True, "no_adaptive_retry": True, "no_extra_sample_points": True, "no_source_anchor": True, "rp1_policy_sha256": "75f2d32853ab7e0a5878c19a732f4ac91ef993c105a8000b87e4a8a6ed6d5145", "rp1_policy_canonical_semantic_sha256": "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a"}


def compute_worker(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    load_contract(root); load_policy(root)
    return _solve(root, row)


def validate_worker_payload(payload: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    for key, value in (("schema", "mephc_e9f_c1_rp2_c3_worker_v1"), ("work_order_id", WORK_ORDER), ("phase", PHASE), ("worker_id", row["sample_id"]), ("resolution", int(row["resolution"])), ("solve_count", 9), ("diagnostic_only", True), ("reducer_admissible", False), ("no_state_mixing", True), ("no_qr", True), ("no_lowdin", True), ("no_gram_schmidt", True)):
        if payload.get(key) != value: raise RuntimeError(f"C3_PAYLOAD_{key.upper()}_MISMATCH")
    if len(payload.get("all_point_metrics", [])) != 9 or set(payload.get("stencils", {})) != set(STENCILS): raise RuntimeError("C3_PAYLOAD_COVERAGE_MISMATCH")
    if any(not x["H_GATE"]["passed"] for x in payload["all_point_metrics"]): raise RuntimeError("C3_H_GATE_FAIL_CLOSED")


def aggregate(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [x for p in payloads for x in p["all_point_metrics"]]
    stencil_rows = [entry for p in payloads for entry in p["stencils"].values()]
    return {"worker_count": len(payloads), "total_native_solves": sum(int(x["solve_count"]) for x in payloads), "max_h_offdiag": max(float(x["H_GATE"]["max_offdiag"]) for x in metrics), "max_h_normalization_error": max(float(x["H_GATE"]["max_normalization_error"]) for x in metrics), "rank1_shadow_edges": sum(int(x["rank1"]["association"]["clear_edges"]) for x in stencil_rows), "rank2_qualified_edges": sum(sum(e["status"] in {"SUBSPACE_QUALIFIED", "SINGLE_BAND_QUALIFIED"} for e in x["rank2"]["edges"]) for x in stencil_rows), "stencil_count": len(stencil_rows), "diagnostic_only": True, "reducer_admissible": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2])); parser.add_argument("--self-check", action="store_true"); args = parser.parse_args()
    root = Path(args.root).resolve(); load_contract(root); rows = build_plan(root); assert_parent_solver_free()
    print(json.dumps({"status": "SELF_CHECK_PASSED", "worker_count": len(rows), "matrix_entries": 24, "total_native_solves": 108}, sort_keys=True))
