"""E7I.2F bounded rank-3 H-space subspace diagnosis."""
from __future__ import annotations

import json
import time
from pathlib import Path

import meep as mp
import numpy as np

from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_reference_adapter import build_reference_mpb_adapter
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.plaquette_domain import PlaquetteRefinementThresholds
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.valley_reference_geometry import build_triangular_reference_geometry

K = (2.0 / 3.0, 0.0)
BANDS = 4
RANK3 = (0, 1, 2)
RANK2 = (1, 2)
E3 = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.05)
E4C = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)


def points(step):
    x, y = K
    d = step / 2.0
    return ((x - d, y - d), (x + d, y - d), (x + d, y + d), (x - d, y + d), (x, y))


class SolveCache:
    def __init__(self, provider):
        self.provider = provider
        self.values = {}
        self.unique_solves = 0
        self.cache_hits = 0

    def solve(self, point):
        key = tuple(float(value) for value in point)
        if key in self.values:
            self.cache_hits += 1
            return self.values[key]
        self.unique_solves += 1
        self.values[key] = self.provider.solve(key)
        return self.values[key]


def make_provider(adapter, resolution):
    return MPBLiveSpectralProvider(
        geometry=list(adapter.geometry), geometry_lattice=adapter.geometry_lattice,
        resolution=resolution, num_bands=BANDS, polarization=mp.TE,
        default_material=adapter.background_material, eigensolver_tolerance=1e-7,
        deterministic=True, mesh_size=3,
    )


def snapshot_status(snapshots):
    return {
        "all_orthogonality_qualified": all(item.is_orthogonality_qualified for item in snapshots),
        "points": [list(item.k_point) for item in snapshots],
        "statuses": [item.orthogonality_status for item in snapshots],
        "max_off_diagonal": [float(item.max_off_diagonal_gram) for item in snapshots],
    }


def raw_edge(left, right, selection, authoritative=None):
    left_frame = np.column_stack([left[index].vector for index in selection])
    right_frame = np.column_stack([right[index].vector for index in selection])
    overlap = left_frame.conj().T @ right_frame
    singular_values = np.asarray(np.linalg.svd(overlap, compute_uv=False), dtype=float)
    angles = np.arccos(np.clip(singular_values, 0.0, 1.0))
    # For orthonormal frames, ||P_left-P_right||_2 = sin(theta_max).
    # Avoid materializing the ambient-space projectors.
    projector_distance = float(np.sqrt(max(0.0, 1.0 - float(np.min(singular_values)) ** 2)))
    left_freq = [float(value) for value in left.frequencies]
    right_freq = [float(value) for value in right.frequencies]
    result = {
        "diagnostic_label": "UNQUALIFIED_RAW_DIAGNOSTIC",
        "left_k_point": list(left.k_point), "right_k_point": list(right.k_point),
        "selection_zero_based": list(selection),
        "raw_overlap_singular_values": [float(value) for value in singular_values],
        "sigma_min": float(np.min(singular_values)),
        "principal_angles": [float(value) for value in angles],
        "theta_max": float(np.max(angles)), "projector_distance": projector_distance,
        "endpoint_ordinal_frequencies": {"left": left_freq, "right": right_freq},
        "internal_adjacent_gaps": {
            "left_1_2": left_freq[1] - left_freq[0], "left_2_3": left_freq[2] - left_freq[1],
            "right_1_2": right_freq[1] - right_freq[0], "right_2_3": right_freq[2] - right_freq[1],
        },
        "lower_external_gap": None,
        "upper_external_gap_to_band_4": {
            "left": left_freq[3] - left_freq[2], "right": right_freq[3] - right_freq[2],
            "minimum": min(left_freq[3] - left_freq[2], right_freq[3] - right_freq[2]),
        },
    }
    if authoritative is not None:
        authoritative_dict = authoritative.to_dict(include_matrices=False)
        result["authoritative_external_isolation_decision"] = authoritative_dict["status"] != "SUBSPACE_NOT_ISOLATED"
        result["authoritative_continuity_decision"] = authoritative_dict["status"] == "SUBSPACE_QUALIFIED"
        result["authoritative_edge"] = authoritative_dict
    return result


def chain(cache, delta, selection):
    steps = (float(delta), float(delta) / 2.0, float(delta) / 4.0)
    levels = []
    selections = []
    raw_levels = []
    for step in steps:
        snapshots = tuple(cache.solve(point) for point in points(step))
        levels.append(snapshots)
        selections.append((selection,) * 5)
        raw_levels.append({
            "snapshot": snapshot_status(snapshots),
            "edges": [raw_edge(snapshots[i], snapshots[(i + 1) % 4], selection) for i in range(4)],
        })
    try:
        source = qualify_mpb_plaquette(
            tuple(levels), tuple(selections), steps, thresholds=E3, refinement_thresholds=E4C,
        )
    except Exception as exc:
        return {
            "status": "SNAPSHOT_OR_ASSOCIATION_GATE_FAILED", "qualified": False,
            "rank": len(selection), "selection_zero_based": list(selection), "steps": list(steps),
            "raw_diagnostic": raw_levels, "error_type": type(exc).__name__, "error": str(exc),
        }
    for level_index, boundary in enumerate(source.boundary_results):
        for edge_index, authoritative in enumerate(boundary.edge_results):
            raw_levels[level_index]["edges"][edge_index] = raw_edge(
                levels[level_index][edge_index], levels[level_index][(edge_index + 1) % 4],
                selection, authoritative,
            )
    levels_data = []
    for boundary, interior, metric in zip(source.boundary_results, source.interior_results, source.refinement_result.metrics):
        levels_data.append({
            "boundary_status": boundary.status, "interior_status": interior.status,
            "edges": [item.to_dict(include_matrices=False) for item in boundary.edge_results],
            "spokes": [item.to_dict(include_matrices=False) for item in interior.spoke_results],
            "refinement_metric": metric.to_dict(),
        })
    return {
        "status": source.status, "qualified": bool(source.is_qualified), "rank": len(selection),
        "selection_zero_based": list(selection), "steps": list(steps),
        "snapshot": snapshot_status(levels[0]), "raw_diagnostic": raw_levels,
        "levels": levels_data, "authoritative_thresholds": E3.to_dict(),
        "refinement_thresholds": E4C.to_dict(),
        "first_failing_gate": None if source.is_qualified else (
            f"{levels_data[-1]['boundary_status']} / {levels_data[-1]['interior_status']} / {source.refinement_result.status}"
        ),
    }


def endpoint(fr, label):
    adapter = build_reference_mpb_adapter(
        build_triangular_reference_geometry(fr), build_triangular_coordinate_preflight()
    )
    result = {"label": label, "K_spectra": {}, "K_orthogonality": {}, "rank3": {}, "rank2_reference": None, "counters": []}
    for resolution in (32, 48, 64):
        cache = SolveCache(make_provider(adapter, resolution))
        snapshot = cache.solve(K)
        result["K_spectra"][f"R{resolution}"] = {
            "frequencies": [float(value) for value in snapshot.frequencies],
            "gaps": [float(snapshot.frequencies[i + 1] - snapshot.frequencies[i]) for i in range(3)],
        }
        result["K_orthogonality"][f"R{resolution}"] = snapshot_status((snapshot,))
        result["counters"].append({"stage": f"K_R{resolution}", "unique_solves": cache.unique_solves, "cache_hits": cache.cache_hits})
    for resolution, delta in ((48, 1.0 / 36.0), (48, 1.0 / 72.0), (64, 1.0 / 36.0)):
        cache = SolveCache(make_provider(adapter, resolution))
        result["rank3"][f"R{resolution}_dk_{delta:.8f}"] = chain(cache, delta, RANK3)
        result["counters"].append({"stage": f"rank3_R{resolution}_dk_{delta:.8f}", "unique_solves": cache.unique_solves, "cache_hits": cache.cache_hits})
    if fr == 0.5:
        cache = SolveCache(make_provider(adapter, 48))
        result["rank2_reference"] = chain(cache, 1.0 / 36.0, RANK2)
        result["counters"].append({"stage": "rank2_R48_dk_1_36_reference", "unique_solves": cache.unique_solves, "cache_hits": cache.cache_hits})
    return result


def external_isolation_ok(case):
    for level in case.get("levels", []):
        for edge in list(level.get("edges", [])) + list(level.get("spokes", [])):
            gaps = edge.get("external_gaps") or {}
            if gaps.get("minimum") is None or float(gaps["minimum"]) < E3.min_external_gap:
                return False
    return True


def continuity_failed(case):
    return any(
        edge.get("status") == "SUBSPACE_CONTINUITY_UNQUALIFIED"
        for level in case.get("levels", [])
        for edge in list(level.get("edges", [])) + list(level.get("spokes", []))
    )


def main():
    start = time.time()
    result = {
        "schema": "e7i2f_rank3_hspace_diagnosis_v1", "work_order": "E7I.2F",
        "primary_selection_zero_based": list(RANK3), "comparison_selection_zero_based": list(RANK2),
        "main_unchanged": True, "production_qualification_semantics_unchanged": True,
        "authorized_values": None, "observables": "NONE",
        "conditional_fine_step": {"triggered": False, "reason": None},
    }
    try:
        endpoints = {"FR00": endpoint(0.0, "FR00_exact_triangle"), "FR050": endpoint(0.5, "FR050_exact_circle")}
        result["endpoints"] = endpoints
        target = endpoints["FR00"]["rank3"]["R48_dk_0.01388889"]
        if external_isolation_ok(target) and continuity_failed(target):
            adapter = build_reference_mpb_adapter(build_triangular_reference_geometry(0.0), build_triangular_coordinate_preflight())
            cache = SolveCache(make_provider(adapter, 48))
            endpoints["FR00"]["rank3"]["R48_dk_0.00694444"] = chain(cache, 1.0 / 144.0, RANK3)
            endpoints["FR00"]["counters"].append({"stage": "rank3_R48_dk_1_144_conditional", "unique_solves": cache.unique_solves, "cache_hits": cache.cache_hits})
            result["conditional_fine_step"] = {"triggered": True, "reason": "R48 dk=1/72 rank-3 external isolation passed but continuity failed"}
        cases = [case for endpoint_data in endpoints.values() for case in endpoint_data["rank3"].values()]
        if any(case.get("qualified") for case in cases):
            classification = "E7I2F_RANK3_MANIFOLD_QUALIFIED_PAIR_PHYSICALLY_BLOCKED"
        elif any(external_isolation_ok(case) and continuity_failed(case) for case in cases):
            classification = "E7I2F_RANK3_CONTINUITY_BLOCKED"
        elif any(not external_isolation_ok(case) for case in cases):
            classification = "E7I2F_RANK3_ISOLATION_BLOCKED"
        else:
            classification = "E7I2F_DIAGNOSTIC_INCOMPLETE"
        result["classification"] = classification
        result["overall"] = "E7I2F_REPORT_READY"
    except Exception as exc:
        result.update({"overall": "E7I2F_FAILED_CLEANLY", "classification": "E7I2F_DIAGNOSTIC_INCOMPLETE", "error_type": type(exc).__name__, "error": str(exc)})
    result["elapsed_seconds"] = time.time() - start
    Path(__file__).with_name("result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": result["overall"], "classification": result.get("classification"), "error": result.get("error"), "elapsed_seconds": result["elapsed_seconds"]}, sort_keys=True))
    if result["overall"] != "E7I2F_REPORT_READY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
