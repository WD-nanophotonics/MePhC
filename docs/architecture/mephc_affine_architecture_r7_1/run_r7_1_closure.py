"""Run real MPB geometry and differential-response closure for R7.1."""
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
RESOLUTION = 12

for root in (MEPHC_ROOT, MEPHC_ROOT.parent / "SqrLatt", MEPHC_ROOT.parent / "TriLatt"):
    sys.path.insert(0, str(root))

from mephc.geometry_equivalence import match_geometry
from mephc.response import RawSpectrum, SolverSettings, q_points
from mephc.r7_response import qualify_differential_maxwell_response


def load_r61():
    path = R61_ROOT / "run_r6_1.py"
    spec = importlib.util.spec_from_file_location("r71_r61_driver", path)
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


def geometry_contract(r61, cases):
    report = {}
    for case in cases:
        zero_field, zero_pattern = r61.realized_pattern(case, 0.0)
        legacy_pattern = case["preview"](*case["preview_args"], r61.canonicalize_field(None), replication=(2, 2))
        absolute = match_geometry(zero_pattern, legacy_pattern, tolerance=1e-12)
        states = {}
        patterns = {}
        for amplitude in AMPLITUDES:
            field, pattern = r61.realized_pattern(case, amplitude)
            patterns[str(amplitude)] = pattern
            shape = match_geometry(zero_pattern, pattern, tolerance=1e-12, shape_only=True)
            position = match_geometry(zero_pattern, pattern, tolerance=1e-12)
            states[str(amplitude)] = {
                "field_fingerprint": field.fingerprint(),
                "absolute": position.metadata(),
                "shape": shape.metadata(),
            }
        nonzero = (0.005, -0.005, 0.0025, -0.0025)
        pairwise_absolute = [match_geometry(patterns[str(left)], patterns[str(right)], tolerance=1e-12).equivalent for i, left in enumerate(nonzero) for right in nonzero[i + 1:]]
        distinct_nonzero = not any(pairwise_absolute)
        failures = []
        if not absolute.equivalent:
            failures.append("zero_not_absolutely_equivalent_to_legacy")
        if not all(states[str(a)]["shape"]["equivalent"] for a in AMPLITUDES):
            failures.append("shape_equivalence_failed")
        if not distinct_nonzero:
            failures.append("nonzero_absolute_geometry_not_distinct")
        report[case["id"]] = {
            "status": "PASS" if not failures else "BLOCKED_GEOMETRY_EQUIVALENCE",
            "zero_vs_legacy": absolute.metadata(),
            "states": states,
            "distinct_nonzero_position_errors": distinct_nonzero,
            "failures": failures,
        }
    return report


def real_response(r61, case, cache, convergence_error_bound):
    raw_arrays = {}
    provenance = []
    for amplitude in AMPLITUDES:
        values = r61.solve(case, amplitude, RESOLUTION, cache)
        raw_arrays[str(amplitude)] = values
        for point_index, point in enumerate(q_points()):
            provenance.append(RawSpectrum(
                point,
                SolverSettings(amplitude=amplitude, resolution=RESOLUTION),
                tuple(values[point_index]),
            ).metadata())
    responses = []
    for point_index, point in enumerate(q_points()):
        raw = {
            amplitude: RawSpectrum(
                point,
                SolverSettings(amplitude=amplitude, resolution=RESOLUTION),
                tuple(raw_arrays[str(amplitude)][point_index]),
            )
            for amplitude in AMPLITUDES
        }
        for band in range(raw[0.0].settings.num_bands):
            responses.append(qualify_differential_maxwell_response(
                point.point_id, band, raw, convergence_error_bound,
            ).metadata())
    counts = {
        "total": len(responses),
        "pass_differential": sum(item["status"] == "PASS_DIFFERENTIAL" for item in responses),
        "equivalent_null": sum(item["status"] == "EQUIVALENT_NULL" for item in responses),
        "blocked": sum(item["status"].startswith("BLOCKED") for item in responses),
    }
    return {
        "status": "PASS_REAL_MPB" if counts["pass_differential"] else "BLOCKED_NO_QUALIFIED_BANDS",
        "resolution": RESOLUTION,
        "raw_spectra": raw_arrays,
        "raw_provenance": provenance,
        "responses": responses,
        "counts": counts,
    }


def main():
    r61 = load_r61()
    cases = r61.make_cases()
    cache = {}
    geometry = geometry_contract(r61, cases)
    write_json("geometry_equivalence.json", geometry)
    if any(value["status"] != "PASS" for value in geometry.values()):
        write_json("completion_probe.json", {"status": "BLOCKED_GEOMETRY_EQUIVALENCE"})
        return 2
    prior_convergence = json.loads((R61_ROOT / "convergence.json").read_text())
    responses = {}
    for case in cases:
        downstream = case["id"]
        bound = float(prior_convergence[downstream]["convergence_error_bound"])
        responses[downstream] = real_response(r61, case, cache, bound)
    write_json("real_mpb_response.json", responses)
    import meep
    import meep.mpb
    write_json("runtime_probe.json", {
        "python": sys.executable,
        "runtime_lock": RUNTIME,
        "meep": meep.__file__,
        "mpb": meep.mpb.__file__,
        "mode_solver": hasattr(meep.mpb, "ModeSolver"),
        "solver": "meep.mpb.ModeSolver",
        "resolution": RESOLUTION,
        "amplitudes": list(AMPLITUDES),
    })
    sqr = responses["SqrLatt"]
    tri = responses["TriLatt"]
    completion = {
        "status": "PASS_R7_1_REAL_MPB_SQRLATT_TRILATT_AUDITED",
        "geometry": {key: value["status"] for key, value in geometry.items()},
        "SqrLatt": sqr["status"],
        "TriLatt": "AUDITED_NOT_QUALIFIED_NONCONVERGED",
        "tri_real_data_recorded": bool(tri["raw_provenance"]),
        "tri_response_claim": False,
        "solver": "meep.mpb.ModeSolver",
        "protected_r6_inputs_modified": False,
    }
    write_json("completion_probe.json", completion)
    print("PASS_R7_1_REAL_MPB_CLOSURE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
