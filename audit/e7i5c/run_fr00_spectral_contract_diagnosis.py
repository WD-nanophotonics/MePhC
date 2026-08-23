"""E7I.5C source-contract and exact-K spectral diagnosis.

Audit-only.  This module has no Berry, Wilson, Chern, integration, sweep, or
optimization path.  It reuses the committed E7I.5B K spectrum and performs a
bounded exact-K symmetry check only.
"""
from __future__ import annotations

import hashlib
import json
import math
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

WORK_ORDER = "TRILATT-E7I5C-20260824-152"
FR = 0.0
R48 = 48
R64 = 64
PAPER_GAP21 = 0.045
PAPER_GAP32 = 0.044
PAPER_FILL = 0.107
PAPER_EPSILON = 2.65
PAPER_BERRY = (-0.92, 0.72, 0.19)
MAIN_BASELINE = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"
E7I5B_EVIDENCE = "72ef3b58d6b890e19c381380d1101d9229f957c7"
E7I5B_RESULT_SHA = "6159e1de96d99772f3fe86631ca70dc8e22e73490350bbdae556826fe44e7eea"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def finite(value) -> bool:
    return math.isfinite(float(value))


def gap_pair(frequencies):
    values = [float(x) for x in frequencies]
    return values[1] - values[0], values[2] - values[1]


def source_binding(geometry, preflight, adapter):
    cell_area = float(geometry.cell_area)
    air_area = float(geometry.air_area)
    intended = geometry.to_dict()
    actual = {
        "adapter_schema": "e7i2c_reference_mpb_adapter_v1",
        "primitive": adapter.provenance.get("primitive"),
        "geometry_type": adapter.provenance.get("mpb_geometry_type"),
        "vertices_passed_to_mpb": [list(point) for point in geometry.vertices],
        "height": "inf",
        "inclusion_epsilon": 1.0,
        "background_relative_permittivity": float(PAPER_EPSILON),
        "polarization": "TE",
        "lattice_basis": [list(row) for row in preflight.real_space_basis],
        "coordinate_mapping_digest": preflight.mapping_digest,
    }
    source = {
        "schema": "e7i5c_source_binding_v1",
        "work_order": WORK_ORDER,
        "paper_sources": {
            "arxiv": "https://arxiv.org/abs/2603.27244v1",
            "arxiv_html": "https://arxiv.org/html/2603.27244v1",
            "published_doi": "10.1103/1sq1-3168",
            "figshare_doi": "10.6084/m9.figshare.31076839",
            "figure_1": "https://arxiv.org/html/2603.27244v1/pic/f1.png",
            "source_version": "arXiv v1, submitted 2026-03-28",
        },
        "source_facts": {
            "fr": 0.0,
            "shape": "regular triangular air hole",
            "two_dimensional_model": True,
            "polarization": "TE",
            "effective_permittivity": PAPER_EPSILON,
            "air_hole_filling_factor": PAPER_FILL,
            "air_hole_area_held_fixed": True,
            "paper_gap21": PAPER_GAP21,
            "paper_gap32": PAPER_GAP32,
            "paper_berry_omega_over_a2": list(PAPER_BERRY),
            "paper_stencil_delta_kx_a_over_2pi": 1.0 / 36.0,
            "paper_stencil_delta_ky_a_over_2pi": 1.0 / 36.0,
            "evidence_notes": [
                "The paper text states regular triangular shape at fr=0.",
                "The paper states the lattice constant and air-hole area are kept the same.",
                "The paper states effective permittivity 2.65 and air-hole filling factor 10.7 percent.",
                "The paper reports the two K gaps and three at-K Berry values for fr=0.",
            ],
        },
        "fill_factor_check": {
            "paper_air_area_per_primitive_cell": None,
            "mephc_air_area_per_primitive_cell": air_area,
            "mephc_cell_area": cell_area,
            "mephc_ratio": air_area / cell_area,
            "paper_fill_factor_semantics": "UNRESOLVED",
            "mephc_fill_factor_semantics": "TOTAL_AIR_HOLE_AREA_DIVIDED_BY_PRIMITIVE_CELL_AREA",
            "mephc_fill_factor_matches_numeric_contract": abs(air_area / cell_area - PAPER_FILL) <= 5e-13,
            "status": "UNRESOLVED",
        },
        "orientation_check": {
            "current_triangle_orientation_degrees": geometry.triangle_orientation_degrees,
            "current_orientation_source_status": geometry.orientation_source_status,
            "paper_triangle_orientation_source": "FIGURE_BOUND",
            "paper_triangle_orientation_relative_to_current": "UNRESOLVED",
            "source_compatible_discrete_orientation_representatives": [],
            "status": "UNRESOLVED",
        },
        "polarization_check": {
            "paper_te_field_content": "UNRESOLVED_FROM_SOURCE_DEFINITIONS",
            "mpb_te_field_content": "MPB_TE_MODE",
            "te_convention_match": "UNRESOLVED",
        },
        "mapping_check": {
            "public_K": list(preflight.public_k),
            "public_Kp": list(preflight.public_kp),
            "expected_mpb_K": list(preflight.mpb_k),
            "expected_mpb_Kp": list(preflight.mpb_kp),
            "actual_mpb_K": list(preflight.public_q_to_mpb(preflight.public_k)),
            "actual_mpb_Kp": list(preflight.public_q_to_mpb(preflight.public_kp)),
            "round_trip_residual": preflight.round_trip_residual,
            "mapping_digest": preflight.mapping_digest,
            "status": "VERIFIED" if preflight.ready else "FAILED",
        },
        "intended_geometry": intended,
        "actual_mpb_geometry": actual,
        "intended_geometry_digest": digest(intended),
        "actual_mpb_geometry_digest": digest(actual),
        "intended_vs_actual_mpb_geometry": "MATCH" if actual["vertices_passed_to_mpb"] == intended["vertices"] and actual["background_relative_permittivity"] == intended["mpb_epsilon_value"] and actual["inclusion_epsilon"] == 1.0 else "MISMATCH",
    }
    source["source_binding_digest"] = digest(source)
    return source


def symmetry_fractional_points():
    return (
        (1.0 / 3.0, 1.0 / 3.0),
        (-1.0 / 3.0, 2.0 / 3.0),
        (-2.0 / 3.0, 1.0 / 3.0),
        (-1.0 / 3.0, -1.0 / 3.0),
        (1.0 / 3.0, -2.0 / 3.0),
        (2.0 / 3.0, -1.0 / 3.0),
    )


def solve_symmetry_points(adapter, preflight, counters):
    records = []
    for index, fractional in enumerate(symmetry_fractional_points()):
        public_q = tuple(float(x) for x in preflight.mpb_to_public_q(fractional))
        by_resolution = {}
        for resolution in (R48, R64):
            counters["raw_requests"] += 1
            raw = solve_isolated(adapter, resolution, FR, public_q)
            frequencies = [float(x) for x in raw.frequencies]
            gap21, gap32 = gap_pair(frequencies)
            by_resolution[str(resolution)] = {
                "frequencies": frequencies,
                "gap21": gap21,
                "gap32": gap32,
                "gap21_abs_error_from_paper": abs(gap21 - PAPER_GAP21),
                "gap32_abs_error_from_paper": abs(gap32 - PAPER_GAP32),
            }
        records.append({"symmetry_index": index, "mpb_fractional_q": list(fractional), "public_q": list(public_q), "by_resolution": by_resolution})
    return records


def result_payload(root: Path):
    geometry = build_triangular_reference_geometry(FR)
    preflight = build_triangular_coordinate_preflight()
    adapter = build_reference_mpb_adapter(geometry, preflight)
    binding = source_binding(geometry, preflight, adapter)
    counters = {"raw_requests": 0, "solver_failures": 0}
    started = time.monotonic()
    symmetry = solve_symmetry_points(adapter, preflight, counters)
    current = json.loads((root / "audit/e7i5b/result.json").read_text(encoding="utf-8"))
    current_k = current["K_preflight"]
    current_reuse = {
        "evidence_commit": E7I5B_EVIDENCE,
        "result_sha256": E7I5B_RESULT_SHA,
        "R48_frequencies": current_k[0]["R48_frequencies"],
        "R64_frequencies": current_k[0]["R64_frequencies"],
        "R48_gap21": current_k[0]["R48_nearest_gap"],
        "R48_gap32": current_k[1]["R48_nearest_gap"],
        "R64_gap21": current_k[0]["R64_nearest_gap"],
        "R64_gap32": current_k[1]["R64_nearest_gap"],
        "R48_R64_drift_gap21": abs(current_k[0]["R48_nearest_gap"] - current_k[0]["R64_nearest_gap"]),
        "R48_R64_drift_gap32": abs(current_k[1]["R48_nearest_gap"] - current_k[1]["R64_nearest_gap"]),
    }
    gap21_values = [item["by_resolution"]["48"]["gap21"] for item in symmetry]
    gap32_values = [item["by_resolution"]["48"]["gap32"] for item in symmetry]
    payload = {
        "schema": "e7i5c_fr00_spectral_contract_diagnosis_v1",
        "complete": True,
        "work_order": WORK_ORDER,
        "calculation_code_git_sha": git_head(root),
        "main_baseline": MAIN_BASELINE,
        "expected_main_head": MAIN_BASELINE,
        "source_binding": binding,
        "current_contract_reused": current_reuse,
        "symmetry_equivalent_K_diagnostic": {
            "candidate_count": len(symmetry),
            "records": symmetry,
            "R48_gap21_range": [min(gap21_values), max(gap21_values)],
            "R48_gap32_range": [min(gap32_values), max(gap32_values)],
            "R48_frequency_symmetry_status": "STABLE_WITHIN_NUMERICAL_PRECISION" if max(gap21_values) - min(gap21_values) < 1e-8 and max(gap32_values) - min(gap32_values) < 1e-8 else "MISMATCH",
        },
        "classifications": {
            "code_change": "SANDBOX_AUDIT_ONLY",
            "source_paper_binding": "PARTIAL",
            "paper_fill_factor_semantics": "UNRESOLVED",
            "paper_triangle_orientation_source": "FIGURE_BOUND",
            "te_convention_match": "UNRESOLVED",
            "K_mapping": "VERIFIED" if preflight.ready else "FAILED",
            "intended_vs_actual_mpb_geometry": binding["intended_vs_actual_mpb_geometry"],
            "current_fr00_spectral_reference_status": "MISMATCH_CONFIRMED",
            "source_justified_candidate_count": 1,
            "best_source_justified_gap21": current_reuse["R48_gap21"],
            "best_source_justified_gap32": current_reuse["R48_gap32"],
            "paper_gap21": PAPER_GAP21,
            "paper_gap32": PAPER_GAP32,
            "spectral_mismatch_root_cause": "SOURCE_GEOMETRY_UNRESOLVED",
            "paper_reference_model_recovered": "UNRESOLVED",
            "new_berry_calculation": "NOT_AUTHORIZED",
            "new_chern_calculation": "NOT_AUTHORIZED",
            "full_domain_run": "FALSE",
            "parameter_fitting": "FALSE",
            "production_code_changed": "FALSE",
            "main_push": "FALSE",
            "E7I5C_overall": "SOURCE_GEOMETRY_REMAINS_UNRESOLVED",
        },
        "telemetry": {"wall_time_seconds": time.monotonic() - started, **counters},
    }
    return payload


def run(output: Path, source_output: Path):
    root = Path(__file__).resolve().parents[2]
    payload = result_payload(root)
    source_output.parent.mkdir(parents=True, exist_ok=True)
    source_output.write_text(json.dumps(payload["source_binding"], sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    payload["source_binding_sha256"] = sha(source_output.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    if "--self-check" in sys.argv:
        p = build_triangular_coordinate_preflight()
        assert p.ready
        assert len(symmetry_fractional_points()) == 6
        assert all(finite(x) for point in symmetry_fractional_points() for x in point)
        assert not any(name in globals() for name in ("compose_wilson_transport", "qualify_ordered_path"))
        print("E7I5C_SELF_CHECK=PASS")
    else:
        output = Path(sys.argv[sys.argv.index("--output") + 1]) if "--output" in sys.argv else root / "audit/e7i5c/result.json"
        source_output = Path(sys.argv[sys.argv.index("--source-output") + 1]) if "--source-output" in sys.argv else root / "audit/e7i5c/source_binding.json"
        payload = run(output, source_output)
        print(json.dumps({"schema": payload["schema"], "current_git_head": payload["calculation_code_git_sha"], "telemetry": payload["telemetry"]}, sort_keys=True))
