"""E9C bounded rank-1 Berry comparison at public K/K-prime with TRS control."""
from __future__ import annotations

import hashlib
import json
import math
import resource
import subprocess
import sys
import time
from pathlib import Path

import meep as mp
import numpy as np

from mephc.eigenspace import EigenSubspace
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
from mephc.plaquette_domain import (
    PlaquetteRefinementLevel,
    PlaquetteRefinementThresholds,
    qualify_plaquette_boundary,
    qualify_plaquette_interior,
    qualify_plaquette_refinement,
)
from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from mephc.valley_benchmark import build_triangular_coordinate_preflight, centered_ccw_plaquette_requests
from mephc.wilson_geometry import WILSON_LOOP_QUALIFIED, compose_wilson_transport

WORK_ORDER = "TRILATT-E9C-20260824-175"
R64, R96 = 64, 96
NUM_BANDS = 6
BANDS = (0, 1, 2)
SOLVER_TOLERANCE = 1e-7
MESH_SIZE = 3
K_PUBLIC = (2.0 / 3.0, 0.0)
KPRIME_PUBLIC = (-2.0 / 3.0, 0.0)
PRIMARY_SIDE = 1.0 / 36.0
REFERENCE_SIDE = 1.0 / 72.0
MIN_EXTERNAL_GAP = 0.02
REAL_BASIS = np.asarray(((0.5, 0.5), (math.sqrt(3.0) / 2.0, -math.sqrt(3.0) / 2.0)), dtype=float)
RADIUS = 0.4
EPSILON_BACKGROUND = 7.0225
PAPER_TARGETS = (-0.92, 0.72, 0.19)
REPRESENTATION = "mpb_energy_eh_v1"
TRANSPORT = SubspaceQualificationThresholds(0.9, 0.45, 0.3, MIN_EXTERNAL_GAP)
REFINEMENT = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)


def root():
    return Path(__file__).resolve().parents[2]


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root(), text=True).strip()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical_vertices():
    return np.asarray(
        [[0.0, RADIUS], [-math.sqrt(3.0) * RADIUS / 2.0, -RADIUS / 2.0],
         [math.sqrt(3.0) * RADIUS / 2.0, -RADIUS / 2.0]],
        dtype=float,
    )


def polygon_area(vertices):
    return abs(0.5 * sum(
        vertices[i, 0] * vertices[(i + 1) % len(vertices), 1]
        - vertices[i, 1] * vertices[(i + 1) % len(vertices), 0]
        for i in range(len(vertices))
    ))


def geometry_inputs():
    physical = physical_vertices()
    mpb = np.linalg.solve(REAL_BASIS, physical.T).T
    roundtrip = (REAL_BASIS @ mpb.T).T
    signed = 0.5 * sum(
        roundtrip[i, 0] * roundtrip[(i + 1) % 3, 1]
        - roundtrip[i, 1] * roundtrip[(i + 1) % 3, 0]
        for i in range(3)
    )
    return {
        "physical_vertices": physical,
        "mpb_vertices": mpb,
        "roundtrip_vertices": roundtrip,
        "max_roundtrip_error": float(np.max(np.linalg.norm(roundtrip - physical, axis=1))),
        "physical_area": float(polygon_area(roundtrip)),
        "cell_area": abs(float(np.linalg.det(REAL_BASIS))),
        "physical_fill_fraction": float(polygon_area(roundtrip) / abs(float(np.linalg.det(REAL_BASIS)))),
        "signed_area": float(signed),
        "orientation": "COUNTERCLOCKWISE" if signed > 0 else "CLOCKWISE",
    }


def build_inputs(geometry):
    preflight = build_triangular_coordinate_preflight()
    lattice = mp.Lattice(
        size=mp.Vector3(1, 1, 0),
        basis1=mp.Vector3(float(REAL_BASIS[0, 0]), float(REAL_BASIS[1, 0]), 0),
        basis2=mp.Vector3(float(REAL_BASIS[0, 1]), float(REAL_BASIS[1, 1]), 0),
    )
    prism = mp.Prism(
        vertices=[mp.Vector3(float(x), float(y), 0) for x, y in geometry["mpb_vertices"]],
        height=mp.inf,
        material=mp.air,
    )
    return preflight, lattice, (prism,), mp.Medium(epsilon=EPSILON_BACKGROUND)


def make_provider(resolution, lattice, solver_geometry, background):
    return MPBLiveEnergySpectralProvider(
        geometry=list(solver_geometry),
        geometry_lattice=lattice,
        resolution=resolution,
        num_bands=NUM_BANDS,
        polarization=mp.TE,
        default_material=background,
        eigensolver_tolerance=SOLVER_TOLERANCE,
        deterministic=True,
        mesh_size=MESH_SIZE,
    )


def excluded(frequencies, band):
    return tuple(float(value) for index, value in enumerate(frequencies) if index != band)


def external_contexts(vertex_frequencies, band):
    return tuple(
        ExternalIsolationContext(
            excluded(vertex_frequencies[index], band),
            excluded(vertex_frequencies[(index + 1) % 4], band),
            {"source": "E9C complete excluded six-band endpoint spectrum", "band": band},
        )
        for index in range(4)
    )


def nearest_external_gap(frequencies, band):
    target = float(frequencies[band])
    return min(abs(target - float(value)) for index, value in enumerate(frequencies) if index != band)


def frame_rank1(public_q, raw, band):
    vector = np.asarray(raw.normalized_vectors[band], dtype=np.complex128)
    norm_error = abs(float(np.vdot(vector, vector).real) - 1.0)
    if vector.ndim != 1 or not np.all(np.isfinite(vector)) or norm_error > 1e-8:
        raise RuntimeError(f"rank-1 normalization failure at {public_q}, band {band}")
    return EigenSubspace(
        k_point=tuple(float(x) for x in public_q),
        frame=vector.reshape((-1, 1)),
        eigenvalues=(float(raw.frequencies[band]),),
        solver_indices=(band,),
        metadata={
            "source": "E9C individually normalized MPB E+H state",
            "representation": REPRESENTATION,
            "selected_rank": 1,
            "band": band,
            "lowdin_mixing": False,
            "posthoc_sign_flip": False,
        },
    )


def solve_at(provider, preflight, public_q, resolution, cache, counters):
    q = tuple(float(x) for x in public_q)
    key = (int(resolution), q)
    if key in cache:
        counters["cache_hits"] += 1
        return cache[key]
    counters["solver_requests"] += 1
    raw = provider.solve(q)
    frequencies = tuple(float(x) for x in raw.frequencies)
    vectors = tuple(np.asarray(x, dtype=np.complex128) for x in raw.normalized_vectors)
    if len(frequencies) != NUM_BANDS or len(vectors) != NUM_BANDS:
        counters["solver_failures"] += 1
        raise RuntimeError(f"incomplete six-band snapshot at {q}")
    if not all(math.isfinite(x) for x in frequencies) or any(not np.all(np.isfinite(v)) for v in vectors):
        counters["solver_failures"] += 1
        raise RuntimeError(f"non-finite snapshot at {q}")
    value = {
        "raw": raw,
        "frequencies": frequencies,
        "record": {
            "public_q": list(q),
            "mpb_fractional_q": [float(x) for x in preflight.public_q_to_mpb(q)],
            "frequencies": list(frequencies),
            "provider_representation": raw.provenance.get("representation"),
        },
    }
    cache[key] = value
    return value


def status_dict(value):
    return {"status": value.status, "is_qualified": bool(value.is_qualified)}


def complex_pair(value):
    return {"real": float(np.real(value)), "imag": float(np.imag(value))}


def omega_over_a2(value):
    return None if value is None else float(value / (2.0 * math.pi) ** 2)


def stencil_evidence(center, side, band, resolution, provider, preflight, cache, counters):
    requests = centered_ccw_plaquette_requests(
        (center,), side,
        period_basis=preflight.public_period_basis,
        coordinate_mapping_digest=preflight.mapping_digest,
    )
    vertices = [tuple(float(x) for x in req.canonical_periodic_vertex_q) for req in requests]
    values = [solve_at(provider, preflight, q, resolution, cache, counters) for q in vertices]
    center_value = solve_at(provider, preflight, center, resolution, cache, counters)
    profile_rows = []
    for label, value, q in [(f"vertex_{i}", value, q) for i, (value, q) in enumerate(zip(values, vertices))] + [("center", center_value, center)]:
        gap = nearest_external_gap(value["frequencies"], band)
        profile_rows.append({
            "label": label,
            "q": list(q),
            "frequencies": list(value["frequencies"]),
            "external_gap": float(gap),
            "E3_PROFILE": "PASS" if gap >= MIN_EXTERNAL_GAP else "FAIL",
        })
    profile_passed = all(row["E3_PROFILE"] == "PASS" for row in profile_rows)
    frames = [frame_rank1(q, value["raw"], band) for q, value in zip(vertices, values)]
    center_frame = frame_rank1(center, center_value["raw"], band)
    contexts = external_contexts([value["frequencies"] for value in values], band)
    path = qualify_ordered_path(
        tuple(frames), contexts, thresholds=TRANSPORT, closed=True,
        provenance={"source": "E9C rank-1 E3 ordered square", "band": band, "resolution": resolution, "side": side},
    )
    wilson = compose_wilson_transport(path)
    boundary = qualify_plaquette_boundary(
        tuple(frames), contexts, thresholds=TRANSPORT,
        provenance={"source": "E9C rank-1 E4A square", "band": band, "resolution": resolution, "side": side},
    )
    spokes = tuple(
        ExternalIsolationContext(
            excluded(value["frequencies"], band),
            excluded(center_value["frequencies"], band),
            {"source": "E9C complete vertex-center excluded six-band spectrum", "band": band},
        )
        for value in values
    )
    interior = qualify_plaquette_interior(
        boundary, center_frame, spokes,
        provenance={"source": "E9C rank-1 E4B center spokes", "band": band, "resolution": resolution, "side": side},
    )
    determinant = None if wilson.determinant is None else complex(wilson.determinant)
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    path_ok = path.status in (PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED)
    basic_qualified = bool(
        profile_passed and path_ok and wilson.status == WILSON_LOOP_QUALIFIED
        and boundary.is_qualified and interior.is_qualified and determinant is not None and phase is not None
    )
    omega_literal_q = None if not basic_qualified else float(-determinant.imag / (side ** 2))
    omega_wilson_q = None if not basic_qualified else float(-phase / (side ** 2))
    return {
        "band": band,
        "resolution": resolution,
        "center": list(center),
        "side_q": float(side),
        "vertices": [list(q) for q in vertices],
        "profile_passed": profile_passed,
        "profile": profile_rows,
        "path": status_dict(path),
        "wilson": {
            "status": wilson.status,
            "rank": wilson.rank,
            "determinant": None if determinant is None else complex_pair(determinant),
            "product_matrix": None if wilson.product is None else [[complex_pair(x) for x in row] for row in np.asarray(wilson.product)],
            "determinant_phase": phase,
            "unitarity_residual": wilson.unitarity_residual,
        },
        "boundary": status_dict(boundary),
        "interior": status_dict(interior),
        "minimum_external_gap": float(min(row["external_gap"] for row in profile_rows)),
        "omega_q_paper_literal": omega_literal_q,
        "omega_q_wilson": omega_wilson_q,
        "omega_over_a2_paper_literal": omega_over_a2(omega_literal_q),
        "omega_over_a2_wilson": omega_over_a2(omega_wilson_q),
        "qualified_before_refinement": basic_qualified,
        "_boundary": boundary,
        "_interior": interior,
        "_basic_qualified": basic_qualified,
    }


def add_refinement(primary, reference, band, resolution, side, reference_side):
    l1 = PlaquetteRefinementLevel(
        boundary=primary["_boundary"], interior=primary["_interior"], step=side,
        provenance={"source": "E9C primary square", "band": band, "resolution": resolution},
    )
    l2 = PlaquetteRefinementLevel(
        boundary=reference["_boundary"], interior=reference["_interior"], step=reference_side,
        provenance={"source": "E9C reference refinement square", "band": band, "resolution": resolution},
    )
    result = qualify_plaquette_refinement(
        (l1, l2), thresholds=REFINEMENT,
        provenance={"source": "E9C E4C identity refinement", "band": band, "resolution": resolution},
    )
    metrics = result.to_dict()
    qualified = bool(primary["_basic_qualified"] and reference["_basic_qualified"] and result.is_qualified)
    return {
        "status": result.status,
        "authorization_granted": bool(result.authorization_granted),
        "metrics": metrics["metrics"],
        "thresholds": metrics["thresholds"],
        "levels": metrics["levels"],
        "qualified": qualified,
    }


def public_point_record(provider, preflight, q, resolution, cache, counters):
    value = solve_at(provider, preflight, q, resolution, cache, counters)
    return value["record"]


def self_checks(contract, preflight, geometry):
    mapped_k = tuple(float(x) for x in preflight.public_q_to_mpb(K_PUBLIC))
    mapped_kp = tuple(float(x) for x in preflight.public_q_to_mpb(KPRIME_PUBLIC))
    checks = {
        "CONTRACT_WORK_ORDER": contract["work_order_id"] == WORK_ORDER,
        "CONTRACT_NUM_BANDS": contract["model"]["num_bands"] == NUM_BANDS,
        "CONTRACT_TARGET_RANK1_ONLY": contract["model"]["rank"] == 1 and contract["model"]["composite_subspace_mixing"] is False,
        "CONTRACT_SCOPE_BOUNDED": all(contract[key] is False for key in ("berry_field_map_authorized", "valley_chern_authorized", "full_bz_chern_authorized", "full_path_berry_authorized")),
        "RESOLUTIONS_EXACT": contract["model"]["resolutions"] == [R64, R96],
        "PHYSICAL_GEOMETRY_ROUNDTRIP": geometry["max_roundtrip_error"] <= 1e-12,
        "PHYSICAL_FILL": abs(geometry["physical_fill_fraction"] - 0.24) <= 1e-12,
        "PHYSICAL_ORIENTATION": geometry["orientation"] == "COUNTERCLOCKWISE",
        "K_MAPPING": np.allclose(mapped_k, (1.0 / 3.0, 1.0 / 3.0), rtol=0.0, atol=1e-12),
        "KPRIME_MAPPING": np.allclose(mapped_kp, (-1.0 / 3.0, -1.0 / 3.0), rtol=0.0, atol=1e-12),
        "MAPPING_READY": bool(preflight.ready) and preflight.round_trip_residual <= 1e-12,
        "STENCIL_PRIMARY": math.isclose(PRIMARY_SIDE, 1.0 / 36.0) and math.isclose(PRIMARY_SIDE / 2.0, 1.0 / 72.0),
        "STENCIL_REFERENCE": math.isclose(REFERENCE_SIDE, 1.0 / 72.0) and math.isclose(REFERENCE_SIDE / 2.0, 1.0 / 144.0),
        "UNIT_CONVERSION": math.isclose(omega_over_a2((2.0 * math.pi) ** 2), 1.0, rel_tol=0.0, abs_tol=1e-15),
        "NO_POSTHOC_SIGN_FLIP": contract["valleys"]["posthoc_sign_flip"] is False,
        "OLD_E9A_C1_PRESENT": (root() / "audit/e9a/c1_result.json").exists(),
    }
    if not all(checks.values()):
        raise RuntimeError(f"E9C self-check failed: {checks}")
    return checks, mapped_k, mapped_kp


def run(output):
    started = time.monotonic()
    contract_path = root() / "audit/e9c/human_reference_berry_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    checks, mapped_k, mapped_kp = self_checks(contract, preflight, geometry)
    providers = {
        R64: make_provider(R64, lattice, solver_geometry, background),
        R96: make_provider(R96, lattice, solver_geometry, background),
    }
    centers = {"PUBLIC_K": K_PUBLIC, "PUBLIC_K_PRIME": KPRIME_PUBLIC}
    cache, counters = {}, {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    result_by_resolution = {}
    for resolution in (R64, R96):
        result_by_resolution[str(resolution)] = {}
        for center_name, center in centers.items():
            result_by_resolution[str(resolution)][center_name] = {}
            for band in BANDS:
                primary = stencil_evidence(center, PRIMARY_SIDE, band, resolution, providers[resolution], preflight, cache, counters)
                reference = stencil_evidence(center, REFERENCE_SIDE, band, resolution, providers[resolution], preflight, cache, counters)
                refinement = add_refinement(primary, reference, band, resolution, PRIMARY_SIDE, REFERENCE_SIDE)
                public = primary["omega_over_a2_wilson"]
                result_by_resolution[str(resolution)][center_name][str(band)] = {
                    "paper_band": band + 1,
                    "zero_based_band": band,
                    "primary": {key: value for key, value in primary.items() if not key.startswith("_")},
                    "reference": {key: value for key, value in reference.items() if not key.startswith("_")},
                    "E4C": refinement,
                    "qualified": bool(refinement["qualified"]),
                    "primary_reference_difference_omega_over_a2_wilson": None if primary["omega_over_a2_wilson"] is None or reference["omega_over_a2_wilson"] is None else float(abs(primary["omega_over_a2_wilson"] - reference["omega_over_a2_wilson"])),
                    "primary_reference_difference_omega_over_a2_literal": None if primary["omega_over_a2_paper_literal"] is None or reference["omega_over_a2_paper_literal"] is None else float(abs(primary["omega_over_a2_paper_literal"] - reference["omega_over_a2_paper_literal"])),
                    "primary_wilson_value_for_trs": public,
                    "primary_literal_value_for_trs": primary["omega_over_a2_paper_literal"],
                }
    trs = {}
    for resolution in (R64, R96):
        for stencil in ("primary", "reference"):
            for estimator in ("wilson", "literal"):
                key = f"R{resolution}_{stencil}_{estimator}"
                rows = []
                for band in BANDS:
                    k = result_by_resolution[str(resolution)]["PUBLIC_K"][str(band)][stencil]
                    kp = result_by_resolution[str(resolution)]["PUBLIC_K_PRIME"][str(band)][stencil]
                    field = "omega_over_a2_wilson" if estimator == "wilson" else "omega_over_a2_paper_literal"
                    left, right = k[field], kp[field]
                    total = None if left is None or right is None else float(left + right)
                    denom = None if left is None or right is None else max(abs(left), abs(right), 1e-15)
                    rows.append({"paper_band": band + 1, "K": left, "K_prime": right, "sum": total, "relative_residual": None if total is None else float(abs(total) / denom)})
                trs[key] = rows
    k_replay = result_by_resolution["64"]["PUBLIC_K"]
    replay_rows = []
    c1_k = (0.26833164396586207, 0.3134784445238986, 0.3563287763970286, 0.5644651267329948)
    # The replay is a six-band solve; only its first four values are compared to the sealed E9A.C1 anchor.
    k64_record = public_point_record(providers[R64], preflight, K_PUBLIC, R64, cache, counters)
    for index, expected in enumerate(c1_k):
        replay_rows.append({"band_index": index, "expected_e9a_c1_r64": expected, "actual": k64_record["frequencies"][index], "abs_error": abs(k64_record["frequencies"][index] - expected)})
    payload = {
        "schema": "trilatt_e9c_rank1_k_kprime_berry_result_v1",
        "work_order_id": WORK_ORDER,
        "base_sandbox_sha": contract["base_sandbox_sha"],
        "expected_main_head": contract["expected_main_head"],
        "calculation_code_git_sha": git_head(),
        "contract_sha256": file_sha(contract_path),
        "contract": contract,
        "geometry": {
            "physical_vertices": geometry["physical_vertices"].tolist(),
            "mpb_vertices": geometry["mpb_vertices"].tolist(),
            "roundtrip_vertices": geometry["roundtrip_vertices"].tolist(),
            "max_roundtrip_error": geometry["max_roundtrip_error"],
            "physical_area": geometry["physical_area"],
            "cell_area": geometry["cell_area"],
            "physical_fill_fraction": geometry["physical_fill_fraction"],
            "orientation": geometry["orientation"],
        },
        "self_checks": checks,
        "coordinate_preflight": {
            "ready": preflight.ready,
            "public_K": list(K_PUBLIC),
            "public_K_prime": list(KPRIME_PUBLIC),
            "mpb_K": list(mapped_k),
            "mpb_K_prime": list(mapped_kp),
            "round_trip_residual": preflight.round_trip_residual,
            "mapping_digest": preflight.mapping_digest,
        },
        "results": result_by_resolution,
        "TRS_control": trs,
        "paper_comparison_center": "PUBLIC_K_PRIME",
        "paper_targets_omega_over_a2": list(PAPER_TARGETS),
        "E9A_C1_R64_K_REPLAY": replay_rows,
        "E9A_C1_R64_K_REPLAY_STATUS": "PASSED" if all(row["abs_error"] <= 1e-12 for row in replay_rows) else "FAILED",
        "scope_gates": {
            "rank1_only": True,
            "berry_field_map": "NOT_AUTHORIZED",
            "valley_chern": "NOT_AUTHORIZED",
            "full_bz_chern": "NOT_AUTHORIZED",
            "full_path_berry": "NOT_AUTHORIZED",
            "parameter_sweep": "NOT_AUTHORIZED",
            "posthoc_sign_flip": "NOT_USED",
        },
        "production_code_changed": False,
        "telemetry": {
            "wall_time_seconds": time.monotonic() - started,
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            **counters,
        },
        "E9C_OVERALL": "RANK1_K_KPRIME_TWO_STENCIL_BERRY_EVIDENCE_READY_FOR_SUPERVISOR_AUDIT",
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    contract_path = root() / "audit/e9c/human_reference_berry_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    geometry = geometry_inputs()
    preflight, _, _, _ = build_inputs(geometry)
    if "--self-check" in sys.argv:
        checks, mapped_k, mapped_kp = self_checks(contract, preflight, geometry)
        print(json.dumps({"checks": checks, "mpb_K": mapped_k, "mpb_K_prime": mapped_kp}, sort_keys=True))
    else:
        output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else str(root() / "audit/e9c/result.json")
        payload = run(output)
        print(json.dumps({"schema": payload["schema"], "calculation_code_git_sha": payload["calculation_code_git_sha"], "telemetry": payload["telemetry"]}, sort_keys=True))


