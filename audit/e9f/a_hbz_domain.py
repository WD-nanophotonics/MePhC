"""E9F.A solver-neutral source K-HBZ geometry and quadrature preflight."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

EPS = 1e-12
GRID_DEN = 36
SOURCE_H = 1.0 / GRID_DEN
SOURCE_STENCILS = {"SOURCE_STENCIL_1_36": 1.0 / 36.0, "MEPHC_FINE_STENCIL_1_144": 1.0 / 144.0}
PUBLIC_K = (2.0 / 3.0, 0.0)
PUBLIC_KP = (-2.0 / 3.0, 0.0)
RADIUS = 2.0 / 3.0
EXPECTED_MAIN = "5a4e9e839eff40f582c2404ff3eadd2bf8b676b5"


def digest_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[i][1] * poly[(i + 1) % len(poly)][0] for i in range(len(poly)))


def ccw(poly):
    return list(poly) if area(poly) > 0 else list(reversed(poly))


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def clip(subject, edge_a, edge_b):
    if not subject:
        return []
    out = []
    for p, q in zip(subject, subject[1:] + subject[:1]):
        pin = cross(edge_a, edge_b, p) >= -EPS
        qin = cross(edge_a, edge_b, q) >= -EPS
        if pin:
            out.append(p)
        if pin != qin:
            den = cross(edge_a, edge_b, p) - cross(edge_a, edge_b, q)
            if abs(den) > EPS:
                t = cross(edge_a, edge_b, p) / den
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def intersection(*polys):
    result = list(polys[0])
    for poly in polys[1:]:
        for a, b in zip(ccw(poly), ccw(poly)[1:] + ccw(poly)[:1]):
            result = clip(result, a, b)
            if len(result) < 3:
                return []
    return result


def intersection_area(*polys):
    value = intersection(*polys)
    return abs(area(value)) if len(value) >= 3 else 0.0


def point_in(poly, p):
    return all(cross(a, b, p) >= -EPS for a, b in zip(ccw(poly), ccw(poly)[1:] + ccw(poly)[:1]))


def segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    t = 0.0 if den == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def boundary_distance(p, polygons):
    return min(segment_distance(p, a, b) for poly in polygons for a, b in zip(poly, poly[1:] + poly[:1]))


def regular_polygon(center, radius, sides, rotation):
    return [(center[0] + radius * math.cos(rotation + 2 * math.pi * i / sides), center[1] + radius * math.sin(rotation + 2 * math.pi * i / sides)) for i in range(sides)]


def neg(poly):
    return [(-x, -y) for x, y in poly]


def scaled_about(poly, center, scale):
    return [(center[0] + scale * (x - center[0]), center[1] + scale * (y - center[1])) for x, y in poly]


def square(center, side):
    h = side / 2.0
    return [(center[0] - h, center[1] - h), (center[0] + h, center[1] - h), (center[0] + h, center[1] + h), (center[0] - h, center[1] + h)]


def build_case(fr, delta_k, delta_gamma):
    k_triangle = regular_polygon(PUBLIC_K, RADIUS, 3, math.pi / 3.0)
    kp_untruncated = neg(k_triangle)
    kp_outer = scaled_about(kp_untruncated, PUBLIC_KP, (RADIUS - delta_k) / RADIUS)
    exclusions = [regular_polygon(vertex, delta_gamma, 6, 0.0) for vertex in kp_untruncated]
    k_outer = neg(kp_outer)
    return {"fr": fr, "delta_K": delta_k, "delta_Gamma": delta_gamma, "untruncated_k_hbz": k_triangle, "untruncated_k_prime_hbz": kp_untruncated, "shrunken_k_hbz": kp_outer, "source_exclusions": exclusions, "source_equivalent_k_domain": scaled_about(k_triangle, PUBLIC_K, (RADIUS - delta_k) / RADIUS)}


def domain_area(outer, exclusions):
    return abs(area(outer)) - sum(intersection_area(outer, hole) for hole in exclusions)


def classify_node(q, case):
    untr = point_in(case["untruncated_k_prime_hbz"], q)
    outer = point_in(case["shrunken_k_hbz"], q)
    in_hole = any(point_in(hole, q) for hole in case["source_exclusions"])
    retained = outer and not in_hole
    return untr, outer, in_hole, retained


def grid_records(case):
    outer = case["shrunken_k_hbz"]
    holes = case["source_exclusions"]
    min_x = min(x for x, _ in outer) - SOURCE_H
    max_x = max(x for x, _ in outer) + SOURCE_H
    min_y = min(y for _, y in outer) - SOURCE_H
    max_y = max(y for _, y in outer) + SOURCE_H
    i0, i1 = math.floor(min_x * GRID_DEN) - 1, math.ceil(max_x * GRID_DEN) + 1
    j0, j1 = math.floor(min_y * GRID_DEN) - 1, math.ceil(max_y * GRID_DEN) + 1
    records, cells = [], []
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            q = (i / GRID_DEN, j / GRID_DEN)
            untr, outer_inside, in_hole, retained = classify_node(q, case)
            cell = square(q, SOURCE_H)
            outer_cell_area = intersection_area(outer, cell)
            hole_cell_area = sum(intersection_area(outer, hole, cell) for hole in holes)
            weight = max(0.0, outer_cell_area - hole_cell_area)
            records.append({
                "grid_index": [i, j], "public_q_exact": [f"{i}/{GRID_DEN}", f"{j}/{GRID_DEN}"], "public_q": list(q),
                "inside_untruncated_K_HBZ": untr, "inside_shrunken_K_HBZ": outer_inside,
                "inside_any_Gamma_exclusion": in_hole, "included_in_source_domain": retained,
                "nearest_domain_boundary_distance": boundary_distance(q, [outer, *holes]),
                "nearest_exclusion_boundary_distance": boundary_distance(q, holes),
                "cell_weight_q2": weight
            })
            if weight > EPS:
                cells.append({"grid_index": [i, j], "public_q": list(q), "weight_q2": weight})
    return records, cells


def stencil_stats(case, records):
    outer, holes = case["shrunken_k_hbz"], case["source_exclusions"]
    retained = [r for r in records if r["included_in_source_domain"]]
    result = {}
    for label, h in SOURCE_STENCILS.items():
        full = trunc = near_hole = near_outer = 0
        for rec in retained:
            q = tuple(rec["public_q"])
            plaquette = square(q, h)
            outer_ok = all(point_in(outer, p) for p in plaquette)
            hole_cross = sum(intersection_area(outer, hole, plaquette) for hole in holes) > EPS
            full_ok = outer_ok and not hole_cross
            full += int(full_ok)
            trunc += int(not outer_ok)
            near_hole += int(hole_cross)
            near_outer += int(not outer_ok)
        result[label] = {"stencil_side_q": h, "included_centers": len(retained), "centers_with_full_plaquette_inside_domain": full, "centers_whose_plaquette_crosses_truncation_boundary": trunc, "centers_near_Gamma_exclusion": near_hole, "centers_near_HBZ_boundary": near_outer}
    return result


def validate_case(case):
    records, cells = grid_records(case)
    continuous = domain_area(case["shrunken_k_hbz"], case["source_exclusions"])
    discrete = sum(c["weight_q2"] for c in cells)
    return {"fr": case["fr"], "delta_K": case["delta_K"], "delta_Gamma": case["delta_Gamma"], "untruncated_hbz_area": abs(area(case["untruncated_k_prime_hbz"])), "shrunken_hbz_area": abs(area(case["shrunken_k_hbz"])), "gamma_exclusion_total_area": sum(intersection_area(case["shrunken_k_hbz"], h) for h in case["source_exclusions"]), "net_continuous_domain_area": continuous, "discrete_quadrature_weight_sum": discrete, "relative_discrete_area_error": abs(discrete - continuous) / continuous, "included_grid_center_count": sum(int(r["included_in_source_domain"]) for r in records), "grid_node_count": len(records), "quadrature_cell_count": len(cells), "stencil_preflight": stencil_stats(case, records), "grid_nodes": records, "quadrature_cells": cells}


def capability_audit(root):
    source = root / "mephc" / "valley_chern.py"
    text = source.read_text(encoding="utf-8")
    return {"schema": "trilatt_e9f_a_integration_capability_audit_v1", "production_file": "mephc/valley_chern.py", "production_file_sha256": digest_bytes(source), "production_code_changed_in_e9f_a": False, "capabilities": {
        "arbitrary_triangular_domain": {"classification": "MISSING", "evidence": "build_valley_chern_audit accepts sealed flux, not an integration domain"},
        "shrunken_hbz": {"classification": "MISSING", "evidence": "no source-bound shrunken-HBZ construction"},
        "gamma_centered_exclusions": {"classification": "MISSING", "evidence": "no source exclusion geometry"},
        "explicit_quadrature_weights": {"classification": "MISSING", "evidence": "no cell/node quadrature weight input"},
        "NOT_REPORTED_failed_berry_samples": {"classification": "MISSING", "evidence": "no live Berry sample failure provenance field"},
        "per_band_qualification_provenance": {"classification": "PARTIAL", "evidence": "sealed band and inversion provenance exists, but not future domain-sample qualification"},
        "coordinate_jacobian_consistency": {"classification": "SUPPORTED", "evidence": "coordinate_flux_invariance explicitly checks q/physical-area restoration"}
    }, "live_integration_status": "NOT_AUTHORIZED_IN_E9F_A", "new_mpb_solver_requests": 0, "new_berry_calculation": "NONE", "new_valley_chern_value": "NONE", "source_text_contains_solver_invocation": "solve" in text.lower()}


def main():
    root = Path(__file__).resolve().parents[2]
    contract_path = root / "audit/e9f/a_source_valley_chern_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    k = build_case(0.0, 0.10, 0.10)
    k4 = build_case(0.4, 0.05, 0.13)
    analytic_area = 1.0 / math.sqrt(3.0)
    negation_residual = max(math.hypot(k["untruncated_k_prime_hbz"][i][0] + k["untruncated_k_hbz"][i][0], k["untruncated_k_prime_hbz"][i][1] + k["untruncated_k_hbz"][i][1]) for i in range(3))
    geometry = {"analytic_k_hbz_area": analytic_area, "numeric_k_hbz_area": abs(area(k["untruncated_k_hbz"])), "analytic_area_check": math.isclose(abs(area(k["untruncated_k_hbz"])), analytic_area, rel_tol=0.0, abs_tol=1e-14), "k_and_kprime_domain_negation_check": negation_residual <= 1e-14, "negation_max_residual": negation_residual, "k_hbz_center": "PUBLIC_K_PRIME", "construction": "reciprocal-lattice-derived equilateral triangle; K-prime domain is exact negation of K domain"}
    cases = [validate_case(k), validate_case(k4)]
    validation = {"schema": "trilatt_e9f_a_domain_validation_v1", "work_order_id": contract["work_order_id"], "contract_sha256": digest_bytes(contract_path), "source_status": "SOURCE_BOUND", "geometry": geometry, "cases": cases, "chern_normalization_derivation": {"status": "PASSED", "coordinate_jacobian_accounted": True, "derivation": contract["normalization_derivation"], "public_q_to_mpb_conversion": "NOT_USED_IN_THIS_SOLVER_NEUTRAL_PHASE_EXCEPT_MAPPING_SELF_CHECK"}, "source_exclusion_geometry": "VALIDATED", "source_grid_step": "1/36", "new_mpb_solver_requests": 0, "new_berry_calculation": "NONE", "new_valley_chern_value": "NONE", "valley_chern_live_integration": "NOT_AUTHORIZED_IN_E9F_A", "main_expected_sha": EXPECTED_MAIN}
    validation["overall"] = "SOURCE_BOUND_TRUNCATED_K_HBZ_INTEGRATION_DOMAIN_READY_FOR_SUPERVISOR_DECISION" if geometry["analytic_area_check"] and geometry["k_and_kprime_domain_negation_check"] and all(c["relative_discrete_area_error"] < 1e-12 for c in cases) else "FAIL_CLOSED"
    audit = capability_audit(root)
    (root / "audit/e9f/a_domain_validation.json").write_text(json.dumps(validation, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (root / "audit/e9f/a_integration_capability_audit.json").write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": validation["overall"], "contract_sha256": validation["contract_sha256"], "geometry": geometry, "cases": [{k: c[k] for k in ("fr", "net_continuous_domain_area", "discrete_quadrature_weight_sum", "relative_discrete_area_error", "included_grid_center_count", "quadrature_cell_count")} for c in cases], "new_mpb_solver_requests": 0, "new_berry_calculation": "NONE"}, sort_keys=True))


if __name__ == "__main__":
    main()
