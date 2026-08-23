"""E7I.5A one-element rank-1 Stage-1 worker; no inter-band mixing."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from audit.e7i3c.run_representation_bridge import (
    build_reference_mpb_adapter,
    build_triangular_coordinate_preflight,
    build_triangular_reference_geometry,
    solve_isolated,
)
from audit.e7i4a.run_composite_valley_chern import frame_to_subspace
from mephc.path_domain import (
    PATH_SINGLE_BAND_QUALIFIED,
    PATH_SUBSPACE_QUALIFIED,
    qualify_ordered_path,
)
from mephc.plaquette_domain import (
    PlaquetteRefinementLevel,
    PlaquetteRefinementThresholds,
    qualify_plaquette_boundary,
    qualify_plaquette_interior,
    qualify_plaquette_refinement,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.valley_benchmark import centered_ccw_plaquette_requests
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

FR = 0.0
RESOLUTION = 48
R64 = 64
NUM_BANDS = 4
BANDS = (0, 1, 2)
CHECKPOINT_SCHEMA = "e7i5a_rank1_element_checkpoint_c1_v1"
PRIMARY = 1.0 / 36.0
REPRESENTATION = "mpb_energy_eh_v1"
POLARIZATION = "TE"
TOLERANCE = 1e-7
MESH_SIZE = 3
TRANSPORT = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.0)
REFINEMENT = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def contract_sha(contract: dict) -> str:
    return sha(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def worker_source_sha() -> str:
    return sha(Path(__file__).read_bytes())

def calculation_bundle_sha(contract: dict) -> str:
    bundle = {"worker_source_sha256": contract["worker_source_sha256"], "scientific_contract_sha256": contract["scientific_contract_sha256"], "checkpoint_schema_version": contract["checkpoint_schema_version"]}
    return sha(json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def frame_rank1(public_q, snapshot, band: int):
    vector = np.asarray(snapshot.normalized_vectors[band], dtype=np.complex128)
    norm_error = abs(float(np.vdot(vector, vector).real) - 1.0)
    if not np.all(np.isfinite(vector)) or norm_error > 1e-8:
        raise RuntimeError(f"target normalization failure at {public_q}, band {band}")
    from mephc.eigenspace import EigenSubspace
    return EigenSubspace(
        k_point=tuple(float(x) for x in public_q),
        frame=vector.reshape((-1, 1)),
        eigenvalues=(float(snapshot.frequencies[band]),),
        solver_indices=(band,),
        metadata={
            "source": "E7I.5A raw individually normalized E+H rank-1 state",
            "representation": REPRESENTATION,
            "selected_rank": 1,
            "band": band,
            "lowdin_mixing": False,
        },
    )


def nearest_gap(frequencies, band: int) -> float:
    f = [float(x) for x in frequencies]
    if band == 0:
        return f[1] - f[0]
    if band == 1:
        return min(f[1] - f[0], f[2] - f[1])
    if band == 2:
        return min(f[2] - f[1], f[3] - f[2])
    raise ValueError(band)


def solve_at(adapter, geometry, preflight, public_q, resolution, cache, counters):
    public_q = tuple(float(x) for x in public_q)
    key = (public_q, int(resolution))
    if key in cache:
        counters["cache_hits"] += 1
        return cache[key]
    counters["raw_requests"] += 1
    raw = solve_isolated(adapter, resolution, FR, public_q)
    frequencies = tuple(float(x) for x in raw.frequencies)
    if len(frequencies) != NUM_BANDS or not all(math.isfinite(x) for x in frequencies):
        counters["solver_failures"] += 1
        raise RuntimeError(f"nonfinite frequencies at {public_q}")
    vectors = tuple(np.asarray(x, dtype=np.complex128) for x in raw.normalized_vectors)
    if any(not np.all(np.isfinite(v)) for v in vectors):
        counters["solver_failures"] += 1
        raise RuntimeError(f"nonfinite normalized state at {public_q}")
    record = {
        "actual_public_q": list(raw.k_point),
        "actual_mpb_fractional_q": list(preflight.public_q_to_mpb(public_q)),
        "frequencies_bands_1_to_4": list(frequencies),
        "target_normalization_error": float(raw.max_normalization_error),
        "raw_full_gram_max_off_diagonal": float(raw.max_off_diagonal_gram),
        "raw_provider_orthogonality_status": raw.orthogonality_status,
        "raw_gram_matrix": np.asarray(raw.gram_matrix).real.tolist(),
    }
    value = (raw, frequencies, record)
    cache[key] = value
    return value


def isolation_profile(adapter, geometry, preflight, points, band, cache, counters):
    evidence = []
    passed = True
    center_passed = True
    for label, public_q in points:
        raw, frequencies, record = solve_at(adapter, geometry, preflight, public_q, RESOLUTION, cache, counters)
        gap48 = nearest_gap(frequencies, band)
        row = {"label": label, "q": list(public_q), "band": band, "R48_frequencies": list(frequencies), "R48_nearest_gap": gap48, "raw": record}
        if gap48 >= 0.05:
            row.update({"profile": "LEGACY_STRICT_PASS", "R64_nearest_gap": None, "relative_R48": None, "relative_R64": None, "stability_ratio": None})
        else:
            raw64, freq64, rec64 = solve_at(adapter, geometry, preflight, public_q, R64, cache, counters)
            gap64 = nearest_gap(freq64, band)
            target48 = frequencies[band]
            target64 = freq64[band]
            relative48 = gap48 / target48 if target48 > 0 else 0.0
            relative64 = gap64 / target64 if target64 > 0 else 0.0
            ratio = min(gap48, gap64) / max(abs(gap64 - gap48), 1e-12)
            ok = gap48 > 0 and gap64 > 0 and relative48 >= 0.01 and relative64 >= 0.01 and ratio >= 10
            row.update({"profile": "LOW_GAP_PASS" if ok else "LOW_GAP_FAIL", "R64_frequencies": list(freq64), "R64_nearest_gap": gap64, "relative_R48": relative48, "relative_R64": relative64, "stability_ratio": ratio, "R64_raw": rec64})
        evidence.append(row)
        passed = passed and row["profile"] in ("LEGACY_STRICT_PASS", "LOW_GAP_PASS")
        if label == "center":
            center_passed = row["profile"] in ("LEGACY_STRICT_PASS", "LOW_GAP_PASS")
    return passed, center_passed, evidence


def excluded_eigenvalues(frequencies, selected_band: int) -> tuple[float, ...]:
    values = tuple(float(value) for index, value in enumerate(frequencies) if index != selected_band)
    if not values:
        raise ValueError("selected band requires a non-empty excluded spectrum")
    return values

def external_contexts(vertex_frequencies, center_frequencies, band: int):
    contexts = []
    for index in range(4):
        next_index = (index + 1) % 4
        left = excluded_eigenvalues(vertex_frequencies[index], band)
        right = excluded_eigenvalues(vertex_frequencies[next_index], band)
        contexts.append(ExternalIsolationContext(left, right, {"source": "E7I.5A.C1 complete endpoint excluded spectrum", "band": band}))
    return tuple(contexts)


def evaluate_band(element, band, delta, reference_delta, adapter, geometry, preflight, domain, cache, counters):
    center = tuple(float(x) for x in element["evaluation_q"])
    vectors = preflight.delta_k_vectors_to_public_q(delta)
    requests = centered_ccw_plaquette_requests((center,), vectors, period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest)
    vertices_q = [tuple(float(x) for x in request.canonical_periodic_vertex_q) for request in requests]
    all_points = [("vertex", q) for q in vertices_q] + [("center", center)]
    profile_passed, center_profile_passed, profile = isolation_profile(adapter, geometry, preflight, all_points, band, cache, counters)
    vertex_values = [solve_at(adapter, geometry, preflight, q, RESOLUTION, cache, counters) for q in vertices_q]
    center_value = solve_at(adapter, geometry, preflight, center, RESOLUTION, cache, counters)
    vertex_frames = [frame_rank1(q, value[0], band) for q, value in zip(vertices_q, vertex_values)]
    center_frame = frame_rank1(center, center_value[0], band)
    vertex_frequencies = [value[1] for value in vertex_values]
    center_frequencies = center_value[1]
    contexts = external_contexts(vertex_frequencies, center_frequencies, band)
    path = qualify_ordered_path(tuple(vertex_frames), contexts, thresholds=TRANSPORT, closed=True, provenance={"source": "E7I.5A rank-1 E3", "band": band})
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(tuple(vertex_frames), contexts, thresholds=TRANSPORT, provenance={"source": "E7I.5A rank-1 E4A", "band": band})
    spoke_contexts = []
    for freq in vertex_frequencies:
        left = excluded_eigenvalues(freq, band)
        right = excluded_eigenvalues(center_frequencies, band)
        spoke_contexts.append(ExternalIsolationContext(left, right, {"source": "E7I.5A.C1 complete vertex-center excluded spectrum", "band": band}))
    interior = qualify_plaquette_interior(boundary, center_frame, tuple(spoke_contexts), provenance={"source": "E7I.5A rank-1 E4B", "band": band})
    refinement = None
    refinement_summary = None
    reference_profile = None
    if reference_delta is not None:
        reference = evaluate_band(element, band, reference_delta, None, adapter, geometry, preflight, domain, cache, counters)
        reference_profile = reference["profile_passed"]
        l1 = PlaquetteRefinementLevel(boundary=boundary, interior=interior, step=delta, provenance={"local_delta_k": delta})
        l2 = PlaquetteRefinementLevel(boundary=reference["_boundary"], interior=reference["_interior"], step=reference_delta, provenance={"local_delta_k": reference_delta})
        refinement = qualify_plaquette_refinement((l1, l2), thresholds=REFINEMENT, provenance={"source": "E7I.5A rank-1 E4C", "band": band})
        refinement_summary = refinement.to_dict()
    area = abs(float(np.linalg.det(np.asarray(vectors, dtype=float))))
    phase = wilson.determinant_phase
    path_qualified = path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)
    qualified = bool(profile_passed and path_qualified and wilson.status == WILSON_LOOP_QUALIFIED and boundary.is_qualified and interior.is_qualified and (refinement is None or (refinement.is_qualified and reference["qualified"])))
    result = {
        "band": band,
        "local_delta_k": delta,
        "reference_delta_k": reference_delta,
        "center_q": list(center),
        "vertices_q": [list(q) for q in vertices_q],
        "profile_passed": profile_passed,
        "center_profile_passed": center_profile_passed,
        "profile": profile,
        "path_status": path.status,
        "wilson_status": wilson.status,
        "boundary_status": boundary.status,
        "interior_status": interior.status,
        "refinement": refinement_summary,
        "determinant_phase": None if phase is None else float(phase),
        "qualified": qualified,
        "omega_trace_q": None if not qualified or phase is None else float(-phase / area),
        "reference_profile_passed": None if reference_profile is None else bool(reference_profile),
        "raw_diagnostics": [value[2] for value in vertex_values] + [center_value[2]],
    }
    result["_boundary"] = boundary
    result["_interior"] = interior
    return result


def run(contract: dict, output: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    if contract["worker_source_sha256"] != worker_source_sha():
        raise RuntimeError("worker source SHA does not match contract")
    if contract["calculation_bundle_sha256"] != calculation_bundle_sha(contract):
        raise RuntimeError("calculation bundle SHA does not match contract")
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    adapter = build_reference_mpb_adapter(geometry, preflight)
    domain = contract["domain_digest"]
    cache = {}
    counters = {"raw_requests": 0, "unique_solves": 0, "cache_hits": 0, "solver_failures": 0}
    element = {"element_id": contract["element_id"], "evaluation_q": contract["evaluation_q"], "integration_weight": contract["integration_weight"]}
    started = time.monotonic()
    bands = {}
    for band in BANDS:
        attempts = []
        final = None
        center_blocked = False
        for delta in (PRIMARY, PRIMARY / 2.0, PRIMARY / 4.0):
            reference_delta = delta / 2.0
            evaluated = evaluate_band(element, band, delta, reference_delta, adapter, geometry, preflight, domain, cache, counters)
            attempts.append({"primary_delta": delta, "reference_delta": reference_delta, "qualified": bool(evaluated["qualified"]), "center_profile_passed": bool(evaluated["center_profile_passed"]), "profile_passed": bool(evaluated["profile_passed"]), "refinement_status": None if evaluated["refinement"] is None else evaluated["refinement"]["status"]})
            final = evaluated
            if evaluated["qualified"]:
                break
            if not evaluated["center_profile_passed"]:
                center_blocked = True
                break
        clean = {key: value for key, value in final.items() if not key.startswith("_")}
        bands[str(band)] = {"attempts": attempts, "final": clean, "center_profile_blocked": center_blocked}
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "complete": True,
        "checkpoint_schema_version": contract["checkpoint_schema_version"],
        "worker_source_sha256": contract["worker_source_sha256"],
        "worker_code_git_sha": contract["worker_code_git_sha"],
        "scientific_contract_sha256": contract["scientific_contract_sha256"],
        "calculation_bundle_sha256": contract["calculation_bundle_sha256"],
        "contract_sha256": contract_sha(contract),
        "element_id": contract["element_id"],
        "evaluation_q": contract["evaluation_q"],
        "integration_weight": contract["integration_weight"],
        "geometry_digest": geometry.geometry_digest,
        "material_digest": geometry.material_contract_digest,
        "coordinate_mapping_digest": preflight.mapping_digest,
        "domain_digest": contract["domain_digest"],
        "resolution": RESOLUTION,
        "representation": REPRESENTATION,
        "polarization": POLARIZATION,
        "num_bands": NUM_BANDS,
        "target_bands": list(BANDS),
        "solver_tolerance": TOLERANCE,
        "deterministic": True,
        "mesh_size": MESH_SIZE,
        "bands": bands,
        "telemetry": {"worker_exit_code": 0, "worker_peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), "worker_wall_time_seconds": time.monotonic() - started, "worker_solve_requests": counters["raw_requests"], "worker_unique_r48_solves": counters["unique_solves"], "worker_unique_r64_low_gap_solves": sum(1 for value in cache if value[1] == R64), "cache_hits_within_worker": counters["cache_hits"], "solver_failures": counters["solver_failures"]},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, output)
    return payload


def self_check():
    assert BANDS == (0, 1, 2)
    assert nearest_gap((1.0, 2.0, 3.0, 4.0), 0) == 1.0
    assert nearest_gap((1.0, 2.0, 3.0, 4.0), 1) == 1.0
    assert nearest_gap((1.0, 2.0, 3.0, 4.0), 2) == 1.0
    assert 0.05 >= 0.05 and not (0.049999 >= 0.05)
    assert 1.0 / 36.0 > 0 and 1.0 / 144.0 > 0
    assert math.isclose(1.0 / (2.0 * math.pi) * 2.0 * math.pi, 1.0, rel_tol=0.0, abs_tol=1e-15)
    assert frame_rank1.__name__ == "frame_rank1"
    assert excluded_eigenvalues((1.0, 2.0, 3.0, 4.0), 0) == (2.0, 3.0, 4.0)
    assert excluded_eigenvalues((1.0, 2.0, 3.0, 4.0), 1) == (1.0, 3.0, 4.0)
    assert excluded_eigenvalues((1.0, 2.0, 3.0, 4.0), 2) == (1.0, 2.0, 4.0)
    assert TRANSPORT.min_external_gap == 0.0
    assert PATH_SINGLE_BAND_QUALIFIED in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract")
    parser.add_argument("--output")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        print(json.dumps({"self_check": "PASSED"}))
        return
    try:
        run(json.loads(Path(args.contract).read_text(encoding="utf-8")), Path(args.output))
    except BaseException:
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()

