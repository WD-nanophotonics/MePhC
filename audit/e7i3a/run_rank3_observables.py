"""E7I.3A bounded live rank-3 Wilson-loop diagnostic."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import meep as mp
import numpy as np

from mephc.mpb_plaquette_holonomy import compose_mpb_plaquette_holonomy
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.mpb_reference_adapter import build_reference_mpb_adapter
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.plaquette_domain import PlaquetteRefinementThresholds
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.valley_reference_geometry import build_triangular_reference_geometry

K = (2.0 / 3.0, 0.0)
BANDS = 4
SELECTION = (0, 1, 2)
E3 = SubspaceQualificationThresholds(0.9, 0.45, 0.3, 0.05)
E4C = PlaquetteRefinementThresholds(0.9, 0.45, 0.3, 0.1)
UNITARITY_TOL = 1e-10
REVERSE_TOL = 1e-8
CYCLIC_TOL = 1e-8
REVERSE_ORDER = (3, 2, 1, 0, 4)
CYCLIC_ORDER = (1, 2, 3, 0, 4)


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


def pairs(value):
    if value is None:
        return None
    array = np.asarray(value)
    return [[float(np.real(item)), float(np.imag(item))] for item in array.ravel()]


def matrix_pairs(value):
    if value is None:
        return None
    array = np.asarray(value)
    return [[[float(np.real(item)), float(np.imag(item))] for item in row] for row in array]


def stable_eigenvalues(wilson):
    values = np.asarray(wilson.eigenvalues, dtype=np.complex128)
    values = sorted(values.tolist(), key=lambda value: (float(np.angle(value)), float(np.real(value)), float(np.imag(value))))
    return np.asarray(values, dtype=np.complex128)


def snapshot_status(snapshots):
    return {
        "all_orthogonality_qualified": all(item.is_orthogonality_qualified for item in snapshots),
        "max_off_diagonal": [float(item.max_off_diagonal_gram) for item in snapshots],
        "points": [list(item.k_point) for item in snapshots],
    }


def qualify(levels, steps, order):
    ordered_levels = tuple(tuple(level[index] for index in order) for level in levels)
    selections = tuple(((SELECTION,) * 5) for _ in levels)
    source = qualify_mpb_plaquette(
        ordered_levels, selections, steps,
        thresholds=E3, refinement_thresholds=E4C,
    )
    holonomy = compose_mpb_plaquette_holonomy(source)
    return source, holonomy


def wilson_record(wilson):
    values = stable_eigenvalues(wilson) if wilson.eigenvalues is not None else None
    return {
        "status": wilson.status,
        "closed": bool(wilson.closed),
        "rank": int(wilson.rank),
        "product_W": matrix_pairs(wilson.product),
        "det_W": None if wilson.determinant is None else [float(np.real(wilson.determinant)), float(np.imag(wilson.determinant))],
        "Arg_det_W": None if wilson.determinant_phase is None else float(wilson.determinant_phase),
        "eigenvalues_sorted": pairs(values),
        "eigenphases_sorted": None if values is None else [float(np.angle(value)) for value in values],
        "trace": None if wilson.trace is None else [float(np.real(wilson.trace)), float(np.imag(wilson.trace))],
        "unitarity_residual": None if wilson.unitarity_residual is None else float(wilson.unitarity_residual),
        "edge_link_count": len(wilson.edge_links),
    }


def loop_diagnostics(forward, reverse, cyclic):
    fwd = forward.wilson_results
    rev = reverse.wilson_results
    cyc = cyclic.wilson_results
    records = []
    max_unitarity = 0.0
    max_reverse_matrix = 0.0
    max_reverse_phase = 0.0
    max_cyclic = 0.0
    for level, (fwd_w, rev_w, cyc_w) in enumerate(zip(fwd, rev, cyc)):
        matrix_residual = float(np.max(np.abs(rev_w.product - fwd_w.product.conj().T)))
        phase_residual = float(abs(np.angle(np.exp(1j * (rev_w.determinant_phase + fwd_w.determinant_phase)))))
        fwd_values = stable_eigenvalues(fwd_w)
        cyc_values = stable_eigenvalues(cyc_w)
        cyclic_residual = float(max(
            np.max(np.abs(cyc_values - fwd_values)),
            abs(cyc_w.trace - fwd_w.trace),
            abs(cyc_w.determinant - fwd_w.determinant),
            abs(np.angle(np.exp(1j * (cyc_w.determinant_phase - fwd_w.determinant_phase)))),
        ))
        max_unitarity = max(max_unitarity, float(fwd_w.unitarity_residual), float(rev_w.unitarity_residual), float(cyc_w.unitarity_residual))
        max_reverse_matrix = max(max_reverse_matrix, matrix_residual)
        max_reverse_phase = max(max_reverse_phase, phase_residual)
        max_cyclic = max(max_cyclic, cyclic_residual)
        records.append({
            "level": level,
            "forward": wilson_record(fwd_w),
            "reverse": wilson_record(rev_w),
            "cyclic": wilson_record(cyc_w),
            "reverse_matrix_residual": matrix_residual,
            "reverse_det_phase_sign_residual": phase_residual,
            "cyclic_basepoint_residual": cyclic_residual,
        })
    return {
        "levels": records,
        "max_unitarity_residual": max_unitarity,
        "max_reverse_matrix_residual": max_reverse_matrix,
        "max_reverse_det_phase_sign_residual": max_reverse_phase,
        "max_cyclic_basepoint_residual": max_cyclic,
        "algebraic_checks_pass": (
            max_unitarity <= UNITARITY_TOL
            and max_reverse_matrix <= REVERSE_TOL
            and max_reverse_phase <= REVERSE_TOL
            and max_cyclic <= CYCLIC_TOL
        ),
    }


def endpoint(fr, label):
    adapter = build_reference_mpb_adapter(
        build_triangular_reference_geometry(fr), build_triangular_coordinate_preflight()
    )
    result = {"label": label, "spectra": {}, "cases": {}, "counters": []}
    for resolution in (32, 48, 64):
        cache = SolveCache(make_provider(adapter, resolution))
        snapshot = cache.solve(K)
        result["spectra"][f"R{resolution}"] = {
            "frequencies": [float(value) for value in snapshot.frequencies],
            "gaps": [float(snapshot.frequencies[i + 1] - snapshot.frequencies[i]) for i in range(3)],
        }
        result["counters"].append({"stage": f"K_R{resolution}", "unique_solves": cache.unique_solves, "cache_hits": cache.cache_hits})
    for resolution, delta in ((48, 1.0 / 36.0), (48, 1.0 / 72.0), (64, 1.0 / 36.0)):
        cache = SolveCache(make_provider(adapter, resolution))
        levels = []
        steps = (delta, delta / 2.0, delta / 4.0)
        for step in steps:
            levels.append(tuple(cache.solve(point) for point in points(step)))
        levels = tuple(levels)
        forward_source, forward = qualify(levels, steps, tuple(range(5)))
        reverse_source, reverse = qualify(levels, steps, REVERSE_ORDER)
        cyclic_source, cyclic = qualify(levels, steps, CYCLIC_ORDER)
        case = {
            "resolution": resolution,
            "delta_k": delta,
            "selection_zero_based": list(SELECTION),
            "snapshot": snapshot_status(levels[0]),
            "qualification": {
                "forward_status": forward_source.status,
                "reverse_status": reverse_source.status,
                "cyclic_status": cyclic_source.status,
                "forward_qualified": bool(forward_source.is_qualified),
                "reverse_qualified": bool(reverse_source.is_qualified),
                "cyclic_qualified": bool(cyclic_source.is_qualified),
            },
        }
        if forward_source.is_qualified and reverse_source.is_qualified and cyclic_source.is_qualified and forward.is_qualified and reverse.is_qualified and cyclic.is_qualified:
            case["wilson"] = loop_diagnostics(forward, reverse, cyclic)
        else:
            case["wilson"] = {"observable_produced": False, "reason": "rank3 qualification failed; fail-closed"}
        result["cases"][f"R{resolution}_dk_{delta:.8f}"] = case
        result["counters"].append({"stage": f"rank3_R{resolution}_dk_{delta:.8f}", "unique_solves": cache.unique_solves, "cache_hits": cache.cache_hits})
    return result


def closure_binding(root):
    closure_path = root / "audit" / "e7i2g" / "closure.json"
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    e7i2f_path = root / "audit" / "e7i2f" / "result.json"
    return {
        "path": "audit/e7i2g/closure.json",
        "sha256": hashlib.sha256(closure_path.read_bytes()).hexdigest(),
        "classification": closure["closure_classification"],
        "e7i2e_binding_verified": bool(closure["e7i2e_binding_verified"]),
        "e7i2f_binding_verified": bool(closure["e7i2f_binding_verified"]),
        "e7i2f_evidence_sha256": hashlib.sha256(e7i2f_path.read_bytes()).hexdigest(),
        "main_head": closure["main_head"],
        "production_semantics_changed": bool(closure["production_semantics_changed"]),
    }


def main():
    start = time.time()
    root = Path(__file__).resolve().parents[2]
    result = {
        "schema": "e7i3a_rank3_wilson_diagnostic_v1",
        "work_order": "E7I.3A",
        "expected_base_sandbox_sha": "4e2f3f7bfbbb499afcd1da73a9d9539f4cb150a4",
        "expected_main_head": "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5",
        "selection_zero_based": list(SELECTION),
        "endpoints": ["FR00", "FR050"],
        "plaquettes": ["R48_dk_1over36", "R48_dk_1over72", "R64_dk_1over36"],
        "thresholds": {"E3": E3.to_dict(), "E4C": E4C.to_dict()},
        "algebraic_tolerances": {"unitarity": UNITARITY_TOL, "reverse": REVERSE_TOL, "cyclic": CYCLIC_TOL},
        "rank2_observable_produced": False,
        "area_normalized_berry_curvature_authorized": False,
        "chern_authorized": False,
        "physical_hall_response_authorized": False,
    }
    try:
        result["closure_binding"] = closure_binding(root)
        if result["closure_binding"]["classification"] != "E7I2_CLOSED_RANK3_QUALIFIED_TARGET_RANK2_PHYSICALLY_BLOCKED":
            raise RuntimeError("E7I.2G closure classification mismatch")
        if not result["closure_binding"]["e7i2e_binding_verified"] or not result["closure_binding"]["e7i2f_binding_verified"]:
            raise RuntimeError("E7I.2G closure binding is not verified")
        endpoints = {"FR00": endpoint(0.0, "FR00_exact_triangle"), "FR050": endpoint(0.5, "FR050_exact_circle")}
        result["endpoint_results"] = endpoints
        cases = [case for endpoint_result in endpoints.values() for case in endpoint_result["cases"].values()]
        qualified = all(case["qualification"]["forward_qualified"] and case["qualification"]["reverse_qualified"] and case["qualification"]["cyclic_qualified"] for case in cases)
        checks = all(case["wilson"].get("algebraic_checks_pass", False) for case in cases)
        result["classification"] = "E7I3A_RANK3_OBSERVABLE_PIPELINE_QUALIFIED" if qualified and checks else "E7I3A_RANK3_OBSERVABLE_PIPELINE_UNQUALIFIED"
        result["all_rank3_qualification_gates_pass"] = qualified
        result["all_algebraic_checks_pass"] = checks
        result["overall"] = "E7I3A_REPORT_READY"
    except Exception as exc:
        result.update({"overall": "E7I3A_FAILED_CLEANLY", "classification": "E7I3A_RANK3_OBSERVABLE_PIPELINE_UNQUALIFIED", "error_type": type(exc).__name__, "error": str(exc)})
    result["elapsed_seconds"] = time.time() - start
    output = root / "audit" / "e7i3a" / "result.json"
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": result["overall"], "classification": result.get("classification"), "all_rank3_qualification_gates_pass": result.get("all_rank3_qualification_gates_pass"), "all_algebraic_checks_pass": result.get("all_algebraic_checks_pass"), "error": result.get("error"), "elapsed_seconds": result["elapsed_seconds"]}, sort_keys=True))
    if result["overall"] != "E7I3A_REPORT_READY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
