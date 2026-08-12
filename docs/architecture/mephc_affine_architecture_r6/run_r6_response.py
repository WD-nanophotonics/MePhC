"""R6 real MPB periodic-supercell spectral-response baseline driver."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

MEPHC_ROOT = Path(__file__).resolve().parents[3]
SQR_ROOT = MEPHC_ROOT.parent / "SqrLatt"
TRI_ROOT = MEPHC_ROOT.parent / "TriLatt"
OUT = Path(__file__).resolve().parent
RUNTIME = "/home/icy/miniconda3/envs/mp/bin/python"
for root in (MEPHC_ROOT, SQR_ROOT, TRI_ROOT):
    sys.path.insert(0, str(root))

from mephc.deformation import validate_jacobian
from mephc.response import (
    R6_AMPLITUDES, R6_NUM_BANDS, RawSpectrum, SolverSettings,
    benchmark_field, convergence_decision, fingerprint, q_points,
    sign_reversal, verify_q_points,
)

POINTS = q_points()
POINT_IDS = tuple(point.point_id for point in POINTS)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def jsonable(value):
    if callable(value):
        return getattr(value, "__qualname__", repr(value))
    if isinstance(value, Path):
        return str(value)
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
    (OUT / name).write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def freqs(solver):
    values = np.asarray(solver.all_freqs, dtype=float)
    if values.shape != (len(POINTS), R6_NUM_BANDS) or not np.all(np.isfinite(values)):
        raise RuntimeError(f"unexpected MPB frequencies: {values.shape}")
    return values


def field_invariants(lattice, amplitude):
    field = benchmark_field(lattice, amplitude)
    probes = np.asarray([[0, 0], [.17, .23], [.61, .37], [.91, .82],
                         [.41, 1.13], [1.27, .19], [1.73, 1.61], [2, 0], [0, 2]], dtype=float)
    return {
        "amplitude": amplitude,
        "capability": field.capability.value,
        "verified": field.verified,
        "boundary_verification": field.metadata()["boundary_policy"]["verification"],
        "jacobian": validate_jacobian(field, probes),
        "field_fingerprint": field.fingerprint(),
    }


def cases():
    sq_cfg = load_module(SQR_ROOT / "square_hole" / "config.py", "r6_sq_config")
    sq_adapter = load_module(SQR_ROOT / "square_hole" / "r5_deformation.py", "r6_sq_adapter")
    tri_cfg = load_module(TRI_ROOT / "config.py", "r6_tri_config")
    tri_adapter = load_module(TRI_ROOT / "r5_deformation.py", "r6_tri_adapter")
    sq = sq_cfg.canonical_structure()
    return [
        {
            "id": "SqrLatt", "lattice": sq.lattice, "adapter": sq_adapter.build_supercell_solver,
            "adapter_args": (sq,), "metadata": sq.metadata(),
        },
        {
            "id": "TriLatt", "lattice": tri_cfg.canonical_lattice(),
            "adapter": tri_adapter.build_supercell_solver, "adapter_args": (tri_cfg,),
            "metadata": {"geometry_id": tri_cfg.geometry_id,
                         "geometry_parameters": tri_cfg.geometry_parameters(),
                         "motif_policy": "canonical_rigid_pattern"},
        },
    ]


def solve(case, amplitude, resolution):
    field = benchmark_field(case["lattice"], amplitude)
    solver, context = case["adapter"](
        *case["adapter_args"], field, q_points=POINTS, resolution=resolution,
        num_bands=R6_NUM_BANDS,
    )
    if context["field"] is not field or not context["field"].verified:
        raise RuntimeError(f"{case['id']}: adapter changed or unverified field")
    return freqs(solver)


def run_case(case):
    membership = verify_q_points(
        type(case["lattice"])(benchmark_field(case["lattice"], 0).direct_basis,
                              kind="custom", reference_family="custom"),
        POINTS,
    )
    invariants = [field_invariants(case["lattice"], amplitude) for amplitude in R6_AMPLITUDES]
    ladder = {}
    for resolution in (8, 12):
        values = solve(case, 0, resolution)
        ladder[resolution] = {point_id: values[index].tolist()
                              for index, point_id in enumerate(POINT_IDS) if point_id != "q0"}
    convergence = convergence_decision(case["id"], ladder)
    if convergence.accepted_resolution is None:
        values = solve(case, 0, 16)
        ladder[16] = {point_id: values[index].tolist()
                      for index, point_id in enumerate(POINT_IDS) if point_id != "q0"}
        convergence = convergence_decision(case["id"], ladder)

    result = {
        "schema": "mephc.affine_architecture.r6.response.v1",
        "downstream": case["id"], "runtime": RUNTIME,
        "solver": "meep.mpb.ModeSolver", "polarization": "TE",
        "num_bands": R6_NUM_BANDS, "replication": [2, 2],
        "q_points": [point.metadata() for point in POINTS],
        "bz_membership": membership, "field_invariants": invariants,
        "convergence": convergence.metadata(), "fixed_ladder_raw": ladder,
        "structure_metadata": case["metadata"],
    }
    if convergence.accepted_resolution is None:
        result.update(status="BLOCKED_NONCONVERGED", raw_spectra={}, responses=[],
                      raw_provenance=[], eligible_count=0)
        return result

    accepted = int(convergence.accepted_resolution)
    raw = {}
    provenance = []
    for amplitude in R6_AMPLITUDES:
        values = solve(case, amplitude, accepted)
        raw[str(amplitude)] = values
        for index, point in enumerate(POINTS):
            provenance.append(RawSpectrum(
                point, SolverSettings(amplitude, accepted), tuple(values[index])).metadata())

    baseline = raw["0.0"]
    responses = []
    for point_index, point in enumerate(POINTS):
        by_amplitude = {amplitude: raw[str(amplitude)][point_index] for amplitude in R6_AMPLITUDES}
        envelope = np.max(np.vstack([by_amplitude[.005], by_amplitude[-.005],
                                      by_amplitude[.0025], by_amplitude[-.0025]]), axis=0)
        for band in range(R6_NUM_BANDS):
            response = sign_reversal(
                point.point_id, band, by_amplitude, convergence.convergence_error_bound,
                baseline_spectrum=baseline[point_index], perturbed_spectra=envelope,
            )
            row = response.metadata()
            row["structure"] = case["id"]
            row["frequency_units"] = "normalized_meep"
            responses.append(row)

    eligible_count = sum(1 for row in responses if row["eligibility"]["eligible"])
    result.update(
        status="PASS" if eligible_count >= 2 else "BLOCKED_BAND_IDENTITY_GUARD",
        raw_spectra={key: value.tolist() for key, value in raw.items()},
        raw_provenance=provenance, responses=responses,
        eligible_count=eligible_count, eligible_requirement=2,
    )
    result["response_fingerprint"] = fingerprint({
        "structure": case["id"], "q_points": result["q_points"],
        "solver": {"polarization": "TE", "resolution": accepted,
                   "num_bands": R6_NUM_BANDS, "replication": [2, 2]},
        "raw_spectra": result["raw_spectra"], "responses": responses,
    })
    return result


def main():
    results = {case["id"]: run_case(case) for case in cases()}
    write_json("sqrlatt_response.json", results["SqrLatt"])
    write_json("trilatt_response.json", results["TriLatt"])
    write_json("convergence.json", {key: value["convergence"] for key, value in results.items()})
    write_json("benchmark_field.json", {
        key: {"amplitudes": list(R6_AMPLITUDES), "invariants": value["field_invariants"],
              "q_points": value["q_points"], "bz_membership": value["bz_membership"]}
        for key, value in results.items()
    })
    rows = []
    for value in results.values():
        for response in value.get("responses", []):
            rows.append({
                "downstream": response["structure"], "point_id": response["point_id"],
                "band_ordinal": response["band_ordinal"], **response["eligibility"],
            })
    columns = ["downstream", "point_id", "band_ordinal", "eligible", "reason",
               "baseline_frequency", "nearest_neighbor_gap", "maximum_perturbation",
               "convergence_error_bound"]
    (OUT / "eligibility_matrix.csv").write_text(
        "\n".join([",".join(columns)] + [",".join(str(row[column]) for column in columns)
                                         for row in rows]) + "\n", encoding="utf-8")
    import meep
    import meep.mpb
    write_json("runtime_probe.json", {
        "python": sys.executable, "runtime_lock": RUNTIME,
        "meep": meep.__file__, "mpb": meep.mpb.__file__,
        "mode_solver": hasattr(meep.mpb, "ModeSolver"),
        "solver": "meep.mpb.ModeSolver",
    })
    return 0 if all(value["status"] == "PASS" for value in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())

