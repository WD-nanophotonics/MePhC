from __future__ import annotations

import argparse
import gc
import json
import os
import sys
from math import pi

import numpy as np

sys.path.insert(0, "/home/icy/MePhC")
import meep as mp
from meep import mpb
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider


def rss_mb():
    try:
        for line in open("/proc/self/status", encoding="ascii"):
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except OSError:
        return None
    return None


def finite_or_none(value):
    value = float(value)
    return value if np.isfinite(value) else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolution", type=int, required=True)
    parser.add_argument("--h", type=float, required=True)
    parser.add_argument("--qx", type=float, required=True)
    parser.add_argument("--qy", type=float, required=True)
    parser.add_argument("--valley", choices=("K", "Kp"), default="K")
    parser.add_argument("--radius-a", type=float, default=0.15)
    parser.add_argument("--radius-b", type=float, default=0.25)
    args = parser.parse_args()

    lattice = mp.Lattice(
        size=mp.Vector3(1, 1),
        basis1=mp.Vector3(3**0.5 / 2, 0.5),
        basis2=mp.Vector3(3**0.5 / 2, -0.5),
    )
    geometry = [
        mp.Cylinder(
            center=mp.Vector3(1 / 6, 1 / 6),
            radius=args.radius_a,
            material=mp.Medium(epsilon=12),
        ),
        mp.Cylinder(
            center=mp.Vector3(-1 / 6, -1 / 6),
            radius=args.radius_b,
            material=mp.Medium(epsilon=12),
        ),
    ]
    valley_center = (0.0, -2 / 3) if args.valley == "K" else (0.0, 2 / 3)
    target_q = np.asarray((args.qx, args.qy), dtype=float)
    target_k = np.asarray(valley_center, dtype=float) + target_q
    half = float(args.h) / 2.0
    offsets = ((-half, -half), (half, -half), (half, half), (-half, half))
    vertices = [target_k + np.asarray(offset, dtype=float) for offset in offsets]

    print(
        json.dumps(
            {
                "event": "started",
                "pid": os.getpid(),
                "rss_mb": rss_mb(),
                "resolution": args.resolution,
                "h": args.h,
                "valley": args.valley,
                "target_q": target_q.tolist(),
                "target_k": target_k.tolist(),
            }
        ),
        flush=True,
    )

    provider = MPBLiveEnergySpectralProvider(
        geometry=geometry,
        geometry_lattice=lattice,
        resolution=args.resolution,
        num_bands=6,
        polarization=mp.TM,
        default_material=mp.air,
        eigensolver_tolerance=1e-7,
        deterministic=True,
        mesh_size=3,
        phase_callback=mpb.fix_efield_phase,
    )
    snapshots = [provider.solve(tuple(point)) for point in vertices]
    frequencies = [list(map(float, snapshot.frequencies)) for snapshot in snapshots]
    mpb_vertices = []
    for point in vertices:
        reciprocal = mp.cartesian_to_reciprocal(
            mp.Vector3(float(point[0]), float(point[1])), lattice
        )
        mpb_vertices.append([float(reciprocal.x), float(reciprocal.y)])

    phases = []
    omega = []
    link_abs = {band: [] for band in range(6)}
    for band in range(6):
        links = []
        for index in range(4):
            overlap = np.vdot(
                snapshots[index].normalized_vectors[band],
                snapshots[(index + 1) % 4].normalized_vectors[band],
            )
            magnitude = float(abs(overlap))
            if magnitude <= 0.0 or not np.isfinite(magnitude):
                raise RuntimeError(f"zero/non-finite Wilson link for band {band + 1}")
            link_abs[band].append(magnitude)
            links.append(overlap / magnitude)
        phase = float(np.angle(np.prod(links)))
        phases.append(phase)
        omega.append(float(-phase / (args.h * args.h)))

    anti = float((omega[0] - omega[1]) / 2.0)
    common = float((omega[0] + omega[1]) / 2.0)
    relevant_links = link_abs[0] + link_abs[1]
    min_singular = float(min(relevant_links))
    max_projector = float(
        max(np.sqrt(max(0.0, 1.0 - value * value)) for value in relevant_links)
    )
    max_angle = float(max(np.arccos(min(1.0, max(0.0, value))) for value in relevant_links))

    pair_gaps = [row[1] - row[0] for row in frequencies]
    external_gaps = [row[2] - row[1] for row in frequencies]
    ordered = all(
        all(row[index + 1] > row[index] for index in range(5))
        for row in frequencies
    )
    pair_gap = float(min(pair_gaps))
    external_gap = float(min(external_gaps))
    band_identity = "ORDERED_LOCAL_BANDS" if ordered and pair_gap > 1e-8 else "UNQUALIFIED_BAND_IDENTITY"

    spectral_pass = external_gap >= 0.05
    identity_pass = band_identity == "ORDERED_LOCAL_BANDS"
    transport_pass = (
        min_singular >= 0.9 and max_angle <= 0.45 and max_projector <= 0.3
    )
    finite_pass = all(np.isfinite(value) for value in omega + phases)
    qualified = spectral_pass and identity_pass and transport_pass and finite_pass
    mask_reason = None
    if not finite_pass:
        mask_reason = "NUMERICALLY_INCOMPLETE"
    elif not identity_pass:
        mask_reason = "UNQUALIFIED_BAND_IDENTITY"
    elif not spectral_pass:
        mask_reason = "UNQUALIFIED_EXTERNAL_ISOLATION"
    elif not transport_pass:
        mask_reason = "UNQUALIFIED_TRANSPORT"

    result = {
        "event": "result",
        "pid": os.getpid(),
        "resolution": args.resolution,
        "h": float(args.h),
        "valley": args.valley,
        "target_q": target_q.tolist(),
        "target_k": target_k.tolist(),
        "vertices": [list(map(float, point)) for point in vertices],
        "mpb_vertices": mpb_vertices,
        "radii": [args.radius_a, args.radius_b],
        "representation": "mpb_live_energy_eh_v1",
        "plaquette": "CENTERED_CCW",
        "frequencies": frequencies,
        "pair_gap": pair_gap,
        "external_gap": external_gap,
        "band_identity": band_identity,
        "selected_bands_one_based": [1, 2],
        "rank": 1,
        "wilson_phases": phases,
        "omega_bands_q": omega if qualified else None,
        "omega_bands_phys_over_a2": [value / (2 * pi) ** 2 for value in omega] if qualified else None,
        "omega_anti_q": anti if qualified else None,
        "omega_anti_phys_over_a2": anti / (2 * pi) ** 2 if qualified else None,
        "omega_common_q": common if qualified else None,
        "omega_common_phys_over_a2": common / (2 * pi) ** 2 if qualified else None,
        "common_ratio": abs(common) / max(abs(anti), 1e-300) if qualified else None,
        "diagnostic_raw_omega_anti_q": anti,
        "diagnostic_raw_omega_common_q": common,
        "min_singular_value": min_singular,
        "max_projector_distance": max_projector,
        "max_principal_angle": max_angle,
        "spectral_isolation": {
            "absolute_external_gap": external_gap,
            "relative_gap": external_gap / max(min(row[2] for row in frequencies), 1e-300),
            "pair_gap": pair_gap,
            "local_spectral_motion_ratio": None,
        },
        "solver_repeatability": {
            "status": "UNMEASURED",
            "conservative_uncertainty": None,
            "definition": "CONSERVATIVE_SPECTRAL_ENVELOPE",
        },
        "transport_quality": {
            "min_singular_value": min_singular,
            "max_principal_angle": max_angle,
            "max_projector_distance": max_projector,
            "plaquette_h": float(args.h),
        },
        "band_identity_evidence": {
            "status": band_identity,
            "rank": 1,
            "selected_bands_one_based": [1, 2],
            "ordered_at_all_vertices": ordered,
        },
        "production_decision": "QUALIFIED_VALUE" if qualified else "MASKED",
        "mask_reason": mask_reason,
        "qualification_axes": {
            "spectral_isolation": "PASS" if spectral_pass else "FAIL",
            "solver_repeatability": "UNMEASURED",
            "transport_quality": "PASS" if transport_pass else "FAIL",
            "band_identity": "PASS" if identity_pass else "FAIL",
            "production_authority": "CURRENT_E7C_E7E_LOCAL_AUTHORITY",
        },
        "provenance": {
            "live_mpb_extraction_validated": True,
            "solver_settings": {
                "resolution": args.resolution,
                "num_bands": 6,
                "mesh_size": 3,
                "eigensolver_tolerance": 1e-7,
                "polarization": "TM",
                "default_material": "air",
                "deterministic": True,
                "phase_callback": "meep.mpb.fix_efield_phase",
            },
            "geometry": "d0500-minus-sealed-honeycomb",
            "coordinate_space": "public_q=k_phys*a/(2*pi)",
            "curvature_units": {
                "omega_q": "OMEGA_Q",
                "omega_phys_over_a2": "OMEGA_PHYS_OVER_A2",
                "relation": "OMEGA_PHYS_OVER_A2=OMEGA_Q/(2*pi)^2",
            },
        },
        "rss_peak_mb": rss_mb(),
    }
    del snapshots, provider, geometry, lattice
    gc.collect()
    result["rss_end_before_exit_mb"] = rss_mb()
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"event": "runtime_failed", "error": repr(exc), "pid": os.getpid()}), flush=True)
        raise
