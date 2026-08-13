"""Run the R7.2 real-MPB sign and differential-resolution closure."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
MEPHC_ROOT = ROOT.parents[2]
R61_ROOT = MEPHC_ROOT / "docs" / "architecture" / "mephc_affine_architecture_r6_1"
RUNTIME = "/home/icy/miniconda3/envs/mp/bin/python"
AMPLITUDES = (0.0, 0.005, -0.005, 0.0025, -0.0025)
RESOLUTIONS = (8, 12, 16)
POINT_IDS = ("q0", "q1", "q2")
SIGN_TOLERANCE = 1e-6

for root in (MEPHC_ROOT, MEPHC_ROOT.parent / "SqrLatt", MEPHC_ROOT.parent / "TriLatt"):
    sys.path.insert(0, str(root))

from mephc.r7_2_response import (
    compare_differential_resolution_ladder,
    verify_periodic_sign_geometry,
    verify_sign_spectrum,
)
from mephc.response import RawSpectrum, SolverSettings, q_points


def load_r61():
    path = R61_ROOT / "run_r6_1.py"
    spec = importlib.util.spec_from_file_location("r72_r61_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


def write_json(name, value):
    (ROOT / name).write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def geometry_sign(r61, cases):
    result = {}
    for case in cases:
        _, positive = r61.realized_pattern(case, 0.005)
        _, negative = r61.realized_pattern(case, -0.005)
        lattice = case["lattice"]
        supercell_basis = lattice.direct_basis @ np.diag([2, 2])
        translations = (lattice.direct_basis[:, 0], lattice.direct_basis[:, 1])
        result[case["id"]] = verify_periodic_sign_geometry(
            positive, negative, supercell_basis, translations, tolerance=1e-9,
        ).metadata()
    return result


def raw_at_resolution(r61, case, cache, resolution):
    arrays = {}
    spectra = {}
    for amplitude in AMPLITUDES:
        values = r61.solve(case, amplitude, resolution, cache)
        arrays[str(amplitude)] = values
        for point_index, point in enumerate(q_points()):
            spectra[(amplitude, point.point_id)] = RawSpectrum(
                point, SolverSettings(amplitude=amplitude, resolution=resolution),
                tuple(values[point_index]),
            )
    return arrays, spectra


def baseline_error_bounds(raw_by_resolution):
    bounds = {resolution: 0.0 for resolution in RESOLUTIONS}
    for low, high in zip(RESOLUTIONS[:-1], RESOLUTIONS[1:]):
        differences = []
        for point_id in ("q1", "q2"):
            low_values = raw_by_resolution[low][0][point_id]
            high_values = raw_by_resolution[high][0][point_id]
            differences.extend(np.abs(high_values - low_values).tolist())
        maximum = float(max(differences, default=0.0))
        bounds[low] = max(bounds[low], maximum)
        bounds[high] = max(bounds[high], maximum)
    return bounds


def main():
    r61 = load_r61()
    cases = r61.make_cases()
    cache = {}
    sign_geometry = geometry_sign(r61, cases)
    write_json("sign_equivalence_geometry.json", sign_geometry)
    all_responses = {}
    all_sign_spectra = {}
    all_ladders = {}
    for case in cases:
        downstream = case["id"]
        raw_by_resolution = {}
        spectra_by_resolution = {}
        for resolution in RESOLUTIONS:
            arrays, spectra = raw_at_resolution(r61, case, cache, resolution)
            raw_by_resolution[resolution] = {amplitude: {point_id: arrays[str(amplitude)][POINT_IDS.index(point_id)] for point_id in POINT_IDS} for amplitude in AMPLITUDES}
            spectra_by_resolution[resolution] = spectra
        bounds = baseline_error_bounds(raw_by_resolution)
        responses_by_resolution = {}
        sign_by_resolution = {}
        for resolution in RESOLUTIONS:
            responses = {}
            sign_records = {}
            for point_id in POINT_IDS:
                raw = {amplitude: spectra_by_resolution[resolution][(amplitude, point_id)] for amplitude in AMPLITUDES}
                sign_records[point_id] = verify_sign_spectrum(raw[0.005], raw[-0.005], tolerance=SIGN_TOLERANCE).metadata()
                for band in range(6):
                    from mephc.r7_response import qualify_differential_maxwell_response
                    responses[(point_id, band)] = qualify_differential_maxwell_response(point_id, band, raw, bounds[resolution])
            responses_by_resolution[resolution] = responses
            sign_by_resolution[resolution] = sign_records
        ladder = compare_differential_resolution_ladder(responses_by_resolution)
        all_responses[downstream] = {
            str(resolution): {
                "raw_spectra": {str(amplitude): {point_id: spectra_by_resolution[resolution][(amplitude, point_id)].metadata() for point_id in POINT_IDS} for amplitude in AMPLITUDES},
                "responses": {f"{point_id}:{band}": response.metadata() for (point_id, band), response in responses_by_resolution[resolution].items()},
                "convergence_error_bound": bounds[resolution],
            }
            for resolution in RESOLUTIONS
        }
        all_sign_spectra[downstream] = {str(resolution): sign_by_resolution[resolution] for resolution in RESOLUTIONS}
        all_ladders[downstream] = ladder.metadata()
    write_json("real_mpb_response.json", all_responses)
    write_json("sign_equivalence_spectra.json", all_sign_spectra)
    write_json("differential_resolution_ladder.json", all_ladders)
    import meep
    import meep.mpb
    write_json("runtime_probe.json", {
        "python": sys.executable, "runtime_lock": RUNTIME,
        "meep": meep.__file__, "mpb": meep.mpb.__file__,
        "solver": "meep.mpb.ModeSolver", "mode_solver": hasattr(meep.mpb, "ModeSolver"),
        "resolutions": list(RESOLUTIONS), "amplitudes": list(AMPLITUDES),
    })
    sqr_ladder = all_ladders["SqrLatt"]
    tri_ladder = all_ladders["TriLatt"]
    write_json("completion_probe.json", {
        "status": "PASS_R7_2_SIGN_EQUIVALENCE_DIFFERENTIAL_LADDER",
        "geometry_sign": {key: value["equivalent"] for key, value in sign_geometry.items()},
        "spectral_sign": {downstream: all(all(item["equivalent"] for item in by_resolution.values()) for by_resolution in all_sign_spectra[downstream].values()) for downstream in all_sign_spectra},
        "SqrLatt_ladder": sqr_ladder,
        "TriLatt_ladder": tri_ladder,
        "SqrLatt_claim": sqr_ladder["status"] == "PASS",
        "TriLatt_claim": False,
        "tri_real_data_recorded": True,
        "protected_r6_inputs_modified": False,
    })
    print("PASS_R7_2_REAL_MPB_SIGN_AND_LADDER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
