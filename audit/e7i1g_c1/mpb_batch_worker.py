"""Solver worker for a bounded batch of C4 q points.

The provider is constructed once per child process and reused for the batch;
the process is still isolated from the supervisor and emits one JSON result
per requested point.  No cached value or interpolation is performed here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import meep as mp
from meep import mpb
import numpy as np

from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider


def solve(provider, lattice, point):
    qx, qy = float(point["qx"]), float(point["qy"])
    valley_center = (0.0, -2.0 / 3.0)
    target_k = np.asarray((valley_center[0] + qx, valley_center[1] + qy), dtype=float)
    half = 0.001 / 2.0
    vertices = [target_k + np.asarray(offset, dtype=float) for offset in ((-half, -half), (half, -half), (half, half), (-half, half))]
    snapshots = [provider.solve(tuple(vertex)) for vertex in vertices]
    frequencies = [list(map(float, snapshot.frequencies)) for snapshot in snapshots]
    phases, omega = [], []
    for band in range(6):
        links = []
        for index in range(4):
            overlap = np.vdot(snapshots[index].normalized_vectors[band], snapshots[(index + 1) % 4].normalized_vectors[band])
            magnitude = float(abs(overlap))
            if magnitude <= 0.0 or not np.isfinite(magnitude):
                raise RuntimeError("zero/non-finite Wilson link")
            links.append(overlap / magnitude)
        phase = float(np.angle(np.prod(links)))
        phases.append(phase)
        omega.append(float(-phase / (0.001 * 0.001)))
    anti, common = float((omega[0] - omega[1]) / 2.0), float((omega[0] + omega[1]) / 2.0)
    links = []
    for band in range(2):
        for index in range(4):
            overlap = np.vdot(snapshots[index].normalized_vectors[band], snapshots[(index + 1) % 4].normalized_vectors[band])
            links.append(float(abs(overlap)))
    min_singular = min(links)
    max_projector = max(math.sqrt(max(0.0, 1.0 - value * value)) for value in links)
    max_angle = max(math.acos(min(1.0, max(0.0, value))) for value in links)
    pair_gap = min(row[1] - row[0] for row in frequencies)
    external_gap = min(row[2] - row[1] for row in frequencies)
    ordered = all(all(row[index + 1] > row[index] for index in range(5)) for row in frequencies)
    qualified = ordered and pair_gap > 1e-8 and external_gap >= 0.05 and min_singular >= 0.9 and max_angle <= 0.45 and max_projector <= 0.3 and all(np.isfinite(value) for value in omega + phases)
    result = {"event": "result", "resolution": 64, "h": 0.001, "valley": "K", "target_q": [qx, qy], "radii": [0.15, 0.25], "representation": "mpb_live_energy_eh_v1", "plaquette": "CENTERED_CCW", "frequencies": frequencies, "pair_gap": float(pair_gap), "external_gap": float(external_gap), "band_identity": "ORDERED_LOCAL_BANDS" if ordered else "UNQUALIFIED_BAND_IDENTITY", "rank": 1, "selected_bands_one_based": [1, 2], "wilson_phases": phases, "omega_bands_q": omega if qualified else None, "omega_anti_q": anti if qualified else None, "omega_common_q": common if qualified else None, "diagnostic_raw_omega_anti_q": anti, "diagnostic_raw_omega_common_q": common, "min_singular_value": float(min_singular), "max_projector_distance": float(max_projector), "max_principal_angle": float(max_angle), "production_decision": "QUALIFIED_VALUE" if qualified else "MASKED", "mask_reason": None if qualified else "UNQUALIFIED_TRANSPORT", "provenance": {"live_mpb_extraction_validated": True, "solver_settings": {"resolution": 64, "num_bands": 6, "mesh_size": 3, "eigensolver_tolerance": 1e-7, "polarization": "TM", "deterministic": True}, "geometry": "d0500-minus-sealed-honeycomb", "coordinate_space": "public_q=k_phys*a/(2*pi)"}}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    lattice = mp.Lattice(size=mp.Vector3(1, 1), basis1=mp.Vector3(3**0.5 / 2, 0.5), basis2=mp.Vector3(3**0.5 / 2, -0.5))
    geometry = [mp.Cylinder(center=mp.Vector3(1 / 6, 1 / 6), radius=0.15, material=mp.Medium(epsilon=12)), mp.Cylinder(center=mp.Vector3(-1 / 6, -1 / 6), radius=0.25, material=mp.Medium(epsilon=12))]
    provider = MPBLiveEnergySpectralProvider(geometry=geometry, geometry_lattice=lattice, resolution=64, num_bands=6, polarization=mp.TM, default_material=mp.air, eigensolver_tolerance=1e-7, deterministic=True, mesh_size=3, phase_callback=mpb.fix_efield_phase)
    for point in json.loads(args.input.read_text()):
        try:
            print(json.dumps({"sample_key": point["sample_key"], "result": solve(provider, lattice, point)}), flush=True)
        except Exception as exc:
            print(json.dumps({"sample_key": point["sample_key"], "result": {"event": "runtime_failed", "error": repr(exc)}}), flush=True)


if __name__ == "__main__":
    main()
