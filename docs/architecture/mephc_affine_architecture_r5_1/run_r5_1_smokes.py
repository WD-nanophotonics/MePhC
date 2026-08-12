"""Run deterministic real R5.1 supercell MPB smokes for both downstreams."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import time

import meep as mp
from meep import mpb
import numpy as np


BUNDLE = Path(__file__).resolve().parent
REPLICATION = (2, 2)
AMPLITUDE = 0.012
PYTHON = "/home/icy/miniconda3/envs/mp/bin/python"
PYTHONPATH = "/home/icy/MePhC:/home/icy/SqrLatt:/home/icy/TriLatt"
COMMAND = (
    "PYTHONPATH=/home/icy/MePhC:/home/icy/SqrLatt:/home/icy/TriLatt "
    "/home/icy/miniconda3/envs/mp/bin/python "
    "docs/architecture/mephc_affine_architecture_r5_1/run_r5_1_smokes.py"
)


def wave_field(reference_lattice, stable_id: str):
    from mephc.deformation import AnalyticDeformationField, periodic_supercell_field

    super_direct = reference_lattice.direct_basis @ np.diag(REPLICATION)
    inverse = np.linalg.inv(super_direct)

    def displacement(points):
        fractional = np.asarray(points, dtype=float) @ inverse.T
        return np.column_stack(
            (
                AMPLITUDE * np.sin(2.0 * np.pi * fractional[:, 0]),
                AMPLITUDE * np.cos(2.0 * np.pi * fractional[:, 1]),
            )
        )

    base = AnalyticDeformationField(
        displacement,
        stable_id=stable_id,
        parameters={"amplitude": AMPLITUDE, "replication": list(REPLICATION)},
    )
    return periodic_supercell_field(base, reference_lattice, REPLICATION)


def run_case(case_name: str, config_module, integration_module) -> dict[str, object]:
    started = time.monotonic()
    structure = (
        config_module.canonical_structure()
        if case_name == "SqrLatt"
        else config_module
    )
    reference_lattice = structure.lattice if case_name == "SqrLatt" else structure.canonical_lattice()
    field = wave_field(reference_lattice, f"r5.1-{case_name.lower()}-periodic-wave-v1")
    preview = integration_module.periodic_supercell_preview(
        structure,
        field,
        replication=REPLICATION,
    )
    from mephc.bravais import BravaisLattice2D

    supercell_lattice = BravaisLattice2D(
        field.direct_basis,
        kind="custom",
        reference_family="custom",
        deformation_matrix=np.diag(REPLICATION),
    )
    band = config_module.make_band(resolution=2)
    band.geo_latt = supercell_lattice.to_meep_lattice()
    band.deformation_field = field
    geometry = band.convert_ndarray_to_meep_geo(preview["pattern"], rectify=True)
    solver = mpb.ModeSolver(
        geometry_lattice=band.geo_latt,
        geometry=band.create_material_block() + geometry,
        default_material=mp.air,
        resolution=2,
        num_bands=1,
        k_points=[mp.Vector3()],
        verbose=False,
    )
    solver.run_te()
    frequencies = np.asarray(solver.freqs, dtype=float)
    elapsed = round(time.monotonic() - started, 6)
    if frequencies.shape != (1,) or not np.all(np.isfinite(frequencies)):
        raise AssertionError(f"unexpected frequencies shape/values: {frequencies.shape} {frequencies}")
    if not field.verified or np.max(np.abs(field.displacement(np.array([[0.0, 0.0], [0.4, 0.2]])))) <= 0:
        raise AssertionError("field is not verified, nonzero, and spatially varying")
    return {
        "id": f"R5.1-SMOKE-{case_name.upper()}",
        "status": "PASS",
        "case": case_name,
        "solver": "meep.mpb.ModeSolver",
        "interpreter": PYTHON,
        "pythonpath": PYTHONPATH,
        "command": COMMAND,
        "parameters": {
            "replication": list(REPLICATION),
            "amplitude": AMPLITUDE,
            "resolution": 2,
            "num_bands": 1,
            "k_points": [[0.0, 0.0, 0.0]],
            "semantic_label": "supercell_gamma_only",
            "primitive_labels_allowed": False,
            "primitive_symmetry_reduction": False,
            "unfolding": False,
            "berry_or_efs_interpretation": False,
        },
        "field": {
            "capability": field.capability.value,
            "verified": field.verified,
            "stable_id": field.field.stable_id,
            "fingerprint": field.fingerprint(),
        },
        "supercell": preview["supercell"],
        "record_identity": preview["record_identity"],
        "pattern_polygon_count": len(preview["pattern"]),
        "frequencies": frequencies.tolist(),
        "frequencies_shape": list(frequencies.shape),
        "finite_output": bool(np.all(np.isfinite(frequencies))),
        "import_origins": {
            "meep": importlib.import_module("meep").__file__,
            "meep.mpb": importlib.import_module("meep.mpb").__file__,
            "mephc": importlib.import_module("mephc").__file__,
            case_name: str(Path(config_module.__file__).resolve()),
            f"{case_name}.r5_deformation": str(Path(integration_module.__file__).resolve()),
        },
        "log_path": f"logs/{case_name.lower()}_supercell_smoke.log",
        "exit_code": 0,
        "duration_seconds": elapsed,
    }


def main() -> int:
    sys.path[:0] = ["/home/icy/MePhC", "/home/icy/SqrLatt", "/home/icy/TriLatt"]
    import square_hole.config as sqr_config
    import square_hole.r5_deformation as sqr_integration
    import importlib.util

    def load_module(name: str, path: str):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError("cannot load " + path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    tri_config = load_module("r5_1_trilatt_config", "/home/icy/TriLatt/config.py")
    tri_integration = load_module("r5_1_trilatt_integration", "/home/icy/TriLatt/r5_deformation.py")

    cases = []
    for case_name, config_module, integration_module in (
        ("SqrLatt", sqr_config, sqr_integration),
        ("TriLatt", tri_config, tri_integration),
    ):
        try:
            cases.append(run_case(case_name, config_module, integration_module))
            print(case_name, "PASS")
        except Exception as exc:
            cases.append(
                {
                    "id": f"R5.1-SMOKE-{case_name.upper()}",
                    "status": "FAIL",
                    "case": case_name,
                    "command": COMMAND,
                    "interpreter": PYTHON,
                    "pythonpath": PYTHONPATH,
                    "error": f"{type(exc).__name__}: {exc}",
                    "log_path": f"logs/{case_name.lower()}_supercell_smoke.log",
                    "exit_code": 1,
                }
            )
            print(case_name, "FAIL", type(exc).__name__, exc)
    result = {
        "schema": "mephc.r5_1.solver_smokes.v1",
        "status": "PASS" if all(item["status"] == "PASS" for item in cases) else "FAIL",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "interpreter": PYTHON,
            "pythonpath": PYTHONPATH,
            "meep_origin": importlib.import_module("meep").__file__,
            "mpb_origin": importlib.import_module("meep.mpb").__file__,
            "modesolver_available": hasattr(mpb, "ModeSolver"),
        },
        "smokes": cases,
    }
    (BUNDLE / "solver_smokes.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("R5.1 solver smokes", result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
