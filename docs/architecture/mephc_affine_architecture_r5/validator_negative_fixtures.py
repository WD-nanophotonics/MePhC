"""Stable-code negative fixtures for R5 validator review."""

from __future__ import annotations

from mephc.bravais import BravaisLattice2D
from mephc.deformation import AnalyticDeformationField, PeriodicityError, periodic_supercell_field
from mephc.r5 import primitive_guard, record_identity


def run():
    results = {}
    try:
        primitive_guard(AnalyticDeformationField(lambda p: p * 0.0), "primitive Band")
    except RuntimeError as exc:
        results["E_R5_PRIMITIVE_SEMANTICS"] = "PASS" if "E_R5_PRIMITIVE_SEMANTICS" in str(exc) else "FAIL"
    try:
        periodic_supercell_field(AnalyticDeformationField(lambda p: p * 0.01, stable_id="false-periodic"), BravaisLattice2D.square(), (2, 1))
    except PeriodicityError as exc:
        results["E_R5_SUPERCELL_BOUNDARY"] = "PASS" if "E_R5_SUPERCELL_BOUNDARY" in str(exc) else "FAIL"
    try:
        record_identity(AnalyticDeformationField(lambda p: p * 0.0), reference_lattice=BravaisLattice2D.square())
    except ValueError as exc:
        results["E_R5_UNSTABLE_CALLABLE"] = "PASS" if "E_R5_UNSTABLE_CALLABLE" in str(exc) else "FAIL"
    return results


if __name__ == "__main__":
    result = run()
    print(result)
    raise SystemExit(0 if all(value == "PASS" for value in result.values()) else 1)
