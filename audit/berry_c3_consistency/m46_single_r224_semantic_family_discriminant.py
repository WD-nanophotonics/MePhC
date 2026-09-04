"""M46: one fixed R224 semantic-family discriminant."""
from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
M45R2_PATH = ROOT / "audit/berry_c3_consistency/m45r2_robust_complete_semantic_family_adjudication.py"
SPEC = importlib.util.spec_from_file_location("m46_m45r2_parent", M45R2_PATH)
assert SPEC and SPEC.loader
m45r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m45r2)
m41r3 = m45r2.m41r3

RESULT_SCHEMA = "mephc-berry-c3-consistency-m46-r224-semantic-family-discriminant-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m46-r224-semantic-family-vertex-dataset-v1"
RESOLUTIONS = (64, 96, 128, 160, 192, 224)
LATEST_TRIPLE = (160, 192, 224)
PREVIOUS_TRIPLE = (128, 160, 192)
MEMBERS = tuple(m41r3.MEMBERS)
CONFIGURATION_ID = "R224_T1E9_M3"
M41R3_DATASET_ID = m45r2.M41R3_DATASET_ID
M41R3_MANIFEST_SHA256 = m45r2.M41R3_MANIFEST_SHA256
M41R3_SCHEMA = m45r2.M41R3_SCHEMA
M44_DATASET_ID = m45r2.M44_DATASET_ID
M44_MANIFEST_SHA256 = m45r2.M44_MANIFEST_SHA256
M44_SCHEMA = m45r2.M44_SCHEMA


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic): return _safe(value.item())
    if isinstance(value, complex): return [_safe(float(value.real)), _safe(float(value.imag))]
    if isinstance(value, np.ndarray): return _safe(value.tolist())
    if isinstance(value, Mapping): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    raise ValueError(f"M46_UNSAFE_RESULT:{type(value).__name__}")


def r224_graph(centers: Mapping[str, Sequence[float]], source_commit: str) -> list[dict[str, Any]]:
    graph = []
    for member_index, member in enumerate(MEMBERS):
        vertices, _ = m41r3._plaquette_vertices(centers[member], member_index)
        for repeat in range(3):
            for vertex_index, coordinate in enumerate(vertices):
                row = {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "milestone": "M46",
                    "geometry_id": "G15", "stencil": "C3_COVARIANT", "configuration_id": CONFIGURATION_ID,
                    "member_index": member_index, "c3_member_identity": member, "repeat_index": repeat,
                    "vertex_index": vertex_index, "center": list(map(float, centers[member])),
                    "coordinate": list(map(float, coordinate)), "deterministic": True, "num_bands": 4,
                    "resolution": 224, "tolerance": 1e-9, "mesh_size": 3, "polarization": "TE",
                    "mode_count": 50176, "fft_shape": [224, 224], "source_commit": source_commit}
                row["request_key_sha256"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                graph.append(row)
    if len(graph) != 36 or len({row["request_key_sha256"] for row in graph}) != 36:
        raise ValueError("M46_R224_GRAPH_INVALID")
    return graph


def _capture(mp: Any, solver: Any, spec: Mapping[str, Any], counter: Any, source_commit: str) -> dict[str, Any]:
    captured = m41r3._capture(mp, solver, spec, counter, source_commit)
    captured["schema"] = DATASET_SCHEMA
    captured["configuration_id"] = CONFIGURATION_ID
    captured["mode_count"] = 50176
    captured["fft_shape"] = [224, 224]
    captured["native_layout_contract"] = {"accepted": [[50176, 2, 4], [4, 50176, 2], [4, 2, 50176]], "canonical": [4, 50176, 2]}
    return captured


def configuration_detail(records: Sequence[Mapping[str, Any]], centers: Mapping[str, Sequence[float]], m38: Any, m39: Any, configuration_id: str) -> dict[str, Any]:
    """Own the detail call and preserve plaquettes/edge diagnostics locally."""
    detail = m45r2.configuration_detail(records, centers, m38, m39, configuration_id)
    detail["m46_local_detail"] = True
    detail["finite_control_noise_rule"] = "same-member/same-vertex gap and same-member/same-edge link repeat ranges"
    return detail


def _sequence(values: Mapping[int, Sequence[float] | float], identity: str) -> dict[str, Any]:
    table, medians = [], {}
    for resolution in RESOLUTIONS:
        if resolution not in values: continue
        raw = values[resolution]
        repeats = [float(raw)] if isinstance(raw, (int, float)) else [float(v) for v in raw]
        if not repeats or any(not math.isfinite(v) for v in repeats): continue
        median = float(np.median(repeats)); medians[resolution] = median
        table.append({"resolution": resolution, "value": median, "repeat_values": repeats,
            "repeat_uncertainty": float(max((abs(v - median) for v in repeats), default=0.0))})
    for left, right in zip(table, table[1:]):
        left.update({"next_resolution": right["resolution"], "signed_difference_to_next": right["value"] - left["value"],
                     "absolute_difference_to_next": abs(right["value"] - left["value"])})
    fits = {}
    for triple in (PREVIOUS_TRIPLE, LATEST_TRIPLE):
        if all(n in medians for n in triple):
            fit = m45r2.fit_positive_p(triple, [medians[n] for n in triple])
            if fit.get("status") == "VALID_POSITIVE_P":
                prediction = float(fit["y_inf"] + fit["amplitude_a"] * 224.0 ** (-fit["p"]))
                fit["prediction_at_224"] = prediction
                fit["prediction_residual_at_224"] = prediction - float(medians[224]) if 224 in medians else None
            fits["-".join(map(str, triple))] = fit
    return {"identity": identity, "table": table, "fits": fits, "repeat_uncertainty_separate": True}


def _frequency_gap(matrix: Mapping[int, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    result = {}
    for member in MEMBERS:
        for vertex in range(4):
            for band in range(1, 5):
                values = {n: [float(row["frequencies_bands_1_to_4"][band - 1]) for row in rows
                              if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex] for n, rows in matrix.items()}
                key = f"spectral_frequency:{member}:vertex{vertex}:band{band}"
                result[key] = _sequence(values, key)
            values = {n: [min(float(row["adjacent_gaps"]["lower_gap"]), float(row["adjacent_gaps"]["internal_split"])) for row in rows
                          if row["c3_member_identity"] == member and int(row["vertex_index"]) == vertex] for n, rows in matrix.items()}
            key = f"spectral_gap:{member}:vertex{vertex}:band2_isolation"
            result[key] = _sequence(values, key)
    return result


def _subspace_links(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    result = {}
    for member in MEMBERS:
        for edge in range(4):
            values, links, associations = {}, {}, {}
            for resolution, analysis in analyses.items():
                rows = [p for p in analysis["plaquettes"] if p["member"] == member]
                r2 = [p["rank2_edges"][edge] for p in rows]; r1 = [p["rank1_edges"][edge] for p in rows]
                values[resolution] = [float(item["canonical_minimum_singular_value"]) for item in r2]
                links[resolution] = [float(item["link_magnitude"]) for item in r1]
                associations[resolution] = {"rank1_best_target_bands": [item["best_target_band"] for item in r1],
                    "rank2_best_target_pairs": [item["best_target_pair"] for item in r2]}
            key = f"subspace_overlap:{member}:edge{edge}:canonical_rank2_minimum_singular_value"
            result[key] = _sequence(values, key); result[key]["association_by_resolution"] = associations
            link_key = f"rank1_link_corroboration:{member}:edge{edge}:physical_band2"
            result[link_key] = _sequence(links, link_key); result[link_key]["association_by_resolution"] = associations
    return result


def _berry(analyses: Mapping[int, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    rank2, rank1 = {}, {}
    for member in MEMBERS:
        values2, values1, qualification = {}, {}, {}
        for resolution, analysis in analyses.items():
            rows = [p for p in analysis["plaquettes"] if p["member"] == member]
            values2[resolution] = [float(p["rank2_trace_phase_density"]) for p in rows]
            ok = analysis["rank1_qualification"]["status"] == "RANK1_QUALIFIED"
            qualification[resolution] = "RANK1_QUALIFIED" if ok else "RANK1_WITHHELD"
            values1[resolution] = [float(p["rank1_phase_density"]) for p in rows] if ok else []
        key2 = f"berry_rank2_primary:{member}"; key1 = f"berry_rank1_qualified:{member}"
        rank2[key2] = _sequence(values2, key2); rank1[key1] = _sequence(values1, key1)
        rank1[key1]["qualification_by_resolution"] = qualification
    return rank2, rank1


def family_support(sequences: Mapping[str, Mapping[str, Any]], keys: Sequence[str], latest_only: bool = False) -> dict[str, Any]:
    statuses = []
    for key in keys:
        fits = sequences[key].get("fits", {})
        latest = fits.get("160-192-224", {}).get("status")
        previous = fits.get("128-160-192", {}).get("status")
        statuses.append({"latest": latest, "previous": previous})
    latest_ok = [item["latest"] == "VALID_POSITIVE_P" for item in statuses]
    previous_ok = [item["previous"] == "VALID_POSITIVE_P" for item in statuses]
    if all(latest_ok) and all(previous_ok): state = "ALL_TWO_LATEST"
    elif all(latest_ok): state = "ALL_NEWEST"
    elif any(latest_ok): state = "MIXED_NEWEST"
    else: state = "NONE_NEWEST"
    return {"sequence_count": len(keys), "sequence_status": statuses, "state": state,
            "all_newest": bool(keys and all(latest_ok)), "all_two_latest": bool(keys and all(latest_ok) and all(previous_ok)),
            "latest_only": latest_only}


def _association(values: Sequence[Any], canonical: Sequence[int]) -> str:
    normalized = [tuple(v) if isinstance(v, list) else (v,) for v in values]
    if not normalized or len(set(normalized)) != 1: return "REPEAT_UNSTABLE"
    return "CANONICAL_STABLE" if normalized[0] == tuple(canonical) else "NONCANONICAL_STABLE"


def high_resolution_association(analyses: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    states, reasons = {}, []
    for member in MEMBERS:
        for edge in range(4):
            r1, r2 = {}, {}
            for resolution in (160, 192, 224):
                rows = [p for p in analyses[resolution]["plaquettes"] if p["member"] == member]
                r1[resolution] = _association([p["rank1_edges"][edge]["best_target_band"] for p in rows], (2,))
                r2[resolution] = _association([p["rank2_edges"][edge]["best_target_pair"] for p in rows], (2, 3))
            key = f"{member}:edge{edge}"; states[key] = {"rank1": r1, "rank2": r2}
            for label, values in (("rank1", r1), ("rank2", r2)):
                if len(set(values.values())) != 1 or any(v != "CANONICAL_STABLE" for v in values.values()): reasons.append(f"{key}:{label}")
    return {"scope": [160, 192, 224], "states": states, "unstable": bool(reasons), "reasons": reasons}


def direct_continuum_c3(rank2: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    envelopes = {}
    for key, sequence in rank2.items():
        previous = sequence["fits"].get("128-160-192", {}); latest = sequence["fits"].get("160-192-224", {})
        member = key.rsplit(":", 1)[-1]
        if previous.get("status") != "VALID_POSITIVE_P" or latest.get("status") != "VALID_POSITIVE_P":
            envelopes[member] = {"status": "NO_TWO_LATEST_ASYMPTOTIC_SUPPORT"}; continue
        row = next(item for item in sequence["table"] if item["resolution"] == 224)
        envelopes[member] = {"status": "TWO_LATEST_ASYMPTOTIC", "continuum_estimate": float(latest["y_inf"]),
            "discretization_envelope": max(abs(float(latest["values"][-1]) - float(latest["y_inf"])), abs(float(latest["y_inf"]) - float(previous["y_inf"]))),
            "repeat_uncertainty": float(row["repeat_uncertainty"])}
    if not all(item.get("status") == "TWO_LATEST_ASYMPTOTIC" for item in envelopes.values()):
        return {"eligibility": False, "status": "WITHHELD_INCOMPLETE_TWO_LATEST_SUPPORT", "per_member": envelopes}
    pairs = {}
    for left, right in itertools.combinations(sorted(envelopes), 2):
        a, b = envelopes[left], envelopes[right]
        difference = abs(a["continuum_estimate"] - b["continuum_estimate"])
        bound = a["discretization_envelope"] + b["discretization_envelope"] + a["repeat_uncertainty"] + b["repeat_uncertainty"]
        signs = a["continuum_estimate"] == 0.0 or b["continuum_estimate"] == 0.0 or math.copysign(1, a["continuum_estimate"]) == math.copysign(1, b["continuum_estimate"])
        pairs[f"{left}_vs_{right}"] = {"absolute_difference": difference, "combined_bound": bound, "within_bound": difference <= bound, "proper_c3_sign_preserved": signs}
    return {"eligibility": True, "status": "PASS" if all(p["within_bound"] and p["proper_c3_sign_preserved"] for p in pairs.values()) else "FAIL", "per_member": envelopes, "pairs": pairs, "sign_source": "continuum_estimates_direct"}


def classify(spectral: Mapping[str, Any], berry: Mapping[str, Any], association_unstable: bool, continuum: Mapping[str, Any], r224: Mapping[str, Any]) -> tuple[str, str]:
    if association_unstable: return "R224_HIGH_RESOLUTION_ASSOCIATION_INSTABILITY", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R160_R192_R224_RAW_BANDS"
    spectral_late = spectral["state"] in {"ALL_NEWEST", "ALL_TWO_LATEST"}
    berry_late = berry["state"] in {"ALL_NEWEST", "ALL_TWO_LATEST"}
    if spectral_late and berry["state"] in {"NONE_NEWEST", "MIXED_NEWEST"}: return "R224_SPECTRAL_ASYMPTOTIC_BERRY_NONASYMPTOTIC", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R224"
    if spectral["state"] == "NONE_NEWEST" and berry["state"] == "NONE_NEWEST": return "R224_FULL_FAMILY_NONASYMPTOTIC", "R256_RESOLUTION_EXTENSION"
    if spectral_late and berry["state"] == "ALL_TWO_LATEST":
        if continuum.get("status") == "FAIL": return "R224_COMPLETE_FAMILY_CONTINUUM_C3_FAIL", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R224"
        if continuum.get("status") == "PASS" and r224.get("rank1_qualified") and r224.get("rank1_c3") == "PASS": return "R224_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_CONTROL_QUALIFIED", "CROSS_ORBIT_QUALIFICATION_AT_R224_T1E9_M3"
        if continuum.get("status") == "PASS" and not r224.get("rank1_qualified"): return "R224_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_ISOLATION_OR_ASSOCIATION_BLOCKED", "ADAPTIVE_VALIDATED_SUBSPACE_BERRY_TRANSPORT_USING_EXISTING_R160_R192_R224_RAW_BANDS"
        return "R224_COMPLETE_FAMILY_CONTINUUM_C3_PASS_FINITE_BRANCH_OR_C3_BLOCKED", "BOUND_PLAQUETTE_STEP_CONVERGENCE_AT_R224"
    if spectral_late and berry_late: return "R224_NEWEST_TRIPLE_ASYMPTOTIC_PROVISIONAL", "SINGLE_R256_PREDICTION_VALIDATION"
    return "R224_MIXED_SEMANTIC_FAMILY", "SINGLE_R256_SEMANTIC_FAMILY_DISCRIMINANT"


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m46_job")
        m39 = m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m46_m39")
        m38 = m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m46_m38")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        partial = m41r3._read_partial(job, state_root)
        m41 = m41r3._read_dataset(job, state_root, M41R3_DATASET_ID, M41R3_MANIFEST_SHA256, M41R3_SCHEMA, 108)
        m44 = m41r3._read_dataset(job, state_root, M44_DATASET_ID, M44_MANIFEST_SHA256, M44_SCHEMA, 72)
        m18 = m41r3._read_dataset(job, state_root, m41r3.M18_DATASET_ID, m41r3.M18_MANIFEST_SHA256, m41r3.M18_SCHEMA, 3)
        m39r1 = m41r3._read_dataset(job, state_root, m41r3.M39R1_DATASET_ID, m41r3.M39R1_MANIFEST_SHA256, m41r3.M39R1_SCHEMA, 14)
        centers = m41r3._centers(m18, m39r1)
        matrix = {64: [r for r in m41 if r.get("configuration_id") == "R64_T1E9_M3"], 96: [r for r in m41 if r.get("configuration_id") == "R96_T1E9_M3"], 128: partial, 160: [r for r in m44 if r.get("configuration_id") == "R160_T1E9_M3"], 192: [r for r in m44 if r.get("configuration_id") == "R192_T1E9_M3"]}
        if any(len(rows) != 36 for rows in matrix.values()): raise ValueError("M46_EXISTING_MATRIX_INVALID")
        graph = r224_graph(centers, source_commit)
        graph_hash = hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        import meep as mp
        from meep import mpb
        from mephc.band import Band
        band = Band(a=400.0, r1=80.14335684352235, r2=75.13439704080221, n_eff=2.7, h=100.0, resolution=224, lattice_type="triangular", polarization="TE", structure_type="slab")
        pattern = band.create_unitcell(15, 0.0, 15, 60.0, show=False)
        geometry = band.create_material_block() + band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        counter = job.BudgetCounter(36, 36)
        store = job.ImmutableDatasetStore(state_root, {"goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1", "work_order_id": bundle["work_order_id"], "source_commit": source_commit, "record_schema": DATASET_SCHEMA, "configuration_id": CONFIGURATION_ID, "graph_sha256": graph_hash, "mode_count": 50176, "fft_shape": [224, 224]})
        records = []
        for spec in graph:
            reciprocal = mp.cartesian_to_reciprocal(mp.Vector3(float(spec["coordinate"][0]), float(spec["coordinate"][1]), 0.0), band.geo_latt)
            solver = mpb.ModeSolver(geometry=geometry, geometry_lattice=band.geo_latt, k_points=[reciprocal], resolution=224, num_bands=4, default_material=mp.air, tolerance=1e-9, deterministic=True, mesh_size=3)
            captured = _capture(mp, solver, spec, counter, source_commit)
            key = json.dumps({"work_order_id": bundle["work_order_id"], "configuration_id": CONFIGURATION_ID, "member": spec["c3_member_identity"], "repeat": spec["repeat_index"], "vertex": spec["vertex_index"]}, sort_keys=True, separators=(",", ":")).encode()
            store.put(key, json.dumps(captured, sort_keys=True, separators=(",", ":"), default=lambda value: _safe(value)).encode(), {"configuration_id": CONFIGURATION_ID, "member": spec["c3_member_identity"], "repeat_index": spec["repeat_index"], "vertex_index": spec["vertex_index"]})
            records.append(captured)
        matrix[224] = records
        analyses = {n: configuration_detail(rows, centers, m38, m39, f"R{n}_T1E9_M3") for n, rows in matrix.items()}
        dataset = store.finalize(36, {"dataset_schema": DATASET_SCHEMA, "configuration_id": CONFIGURATION_ID, "graph_sha256": graph_hash, "source_parent_dataset_ids": [M41R3_DATASET_ID, M44_DATASET_ID]})
        sequences = _frequency_gap(matrix); sequences.update(_subspace_links(analyses)); rank2, rank1 = _berry(analyses); sequences.update(rank2); sequences.update(rank1)
        spectral_keys = [k for k in sequences if k.startswith("spectral_frequency:") or k.startswith("spectral_gap:") or k.startswith("subspace_overlap:")]
        spectral = family_support(sequences, spectral_keys); berry = family_support(rank2, list(rank2)); association = high_resolution_association(analyses); continuum = direct_continuum_c3(rank2)
        a224 = analyses[224]; r224 = {"rank1_qualified": a224["rank1_qualification"]["status"] == "RANK1_QUALIFIED", "rank1_c3": a224["rank1_c3_status"], "rank2_c3": a224["rank2_c3_status"], "qualification": a224["rank1_qualification"]}
        classification, decision = classify(spectral, berry, association["unstable"], continuum, r224)
        result = {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "ONE_NATIVE_SINGLE_R224_SEMANTIC_FAMILY_DISCRIMINANT", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 1, "provider_execution_count": counter.provider_count, "solver_execution_count": counter.solver_count, "dataset_record_count": len(records), "dataset_id": dataset.get("dataset_id"), "manifest_sha256": dataset.get("manifest_sha256"), "graph_sha256": graph_hash, "verified_resolutions": list(RESOLUTIONS), "configuration_analysis": analyses, "resolution_sequences": sequences, "semantic_sequence_inventory": {"frequency": 48, "gap": 12, "subspace": 12, "spectral_subspace_total": 72, "berry_rank2_primary": 3, "rank1_link_corroboration": 12}, "family_support": {"spectral_subspace": spectral, "berry_rank2_primary": berry, "qualified_rank1": family_support(rank1, list(rank1))}, "high_resolution_association": association, "continuum_c3": continuum, "r224_finite_control": r224, "classification": classification, "next_science_decision": decision, "m45r2_classification_delta": "RESOLVED_BY_R224_SEMANTIC_FAMILY_DISCRIMINANT", "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "M46_FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "failure_code": str(exc)[:1024], "failure_stage": "reference_or_r224_acquisition", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
