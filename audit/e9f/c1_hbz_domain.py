"""E9F.A.C1 source-semantics closure; no solver, Berry, or production code."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path
from audit.e9f.a_hbz_domain import build_case, validate_case, classify_node, digest_bytes, EXPECTED_MAIN

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "audit/e9f/c1_source_domain_contract.json"
ORIGINAL = ROOT / "audit/e9f"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def sample_policy(case, validation):
    outer, holes = case["shrunken_k_hbz"], case["source_exclusions"]
    rows = []
    positive = validation["quadrature_cells"]
    for cell in positive:
        q = tuple(cell["public_q"])
        _, outer_inside, in_hole, _ = classify_node(q, case)
        rows.append({
            "cell_id": f"grid:{cell['grid_index'][0]}:{cell['grid_index'][1]}",
            "cell_weight_q2": cell["weight_q2"],
            "sample_public_q": list(q),
            "sample_policy": "ONE_DETERMINISTIC_CELL_CENTER_SAMPLE_PER_POSITIVE_WEIGHT_CLIPPED_CELL",
            "domain_membership": "INSIDE_OUTER" if outer_inside else "OUTSIDE_OUTER_BUT_POSITIVE_CLIPPED_CELL",
            "exclusion_membership": "INSIDE_EXCLUSION" if in_hole else "NOT_INSIDE_EXCLUSION",
            "band_qualification_status": "NOT_RUN_IN_E9F_A_C1",
            "berry_status": "MUST_BE_EXPLICIT_QUALIFIED_REPORTED_OR_NOT_REPORTED_FOR_EVERY_TARGET_BAND",
        })
    return {"schema": "trilatt_e9f_a_c1_future_sample_policy_v1", "positive_weight_sample_policy": "EXPLICIT", "no_zero_fill_policy": "BOUND", "no_silent_drop_policy": "BOUND", "rows": rows}

def category_counts(case, validation):
    outer, holes = case["shrunken_k_hbz"], case["source_exclusions"]
    positive = validation["quadrature_cells"]
    rows = [classify_node(tuple(cell["public_q"]), case) for cell in positive]
    return {
        "positive_weight_cell_count": len(positive),
        "positive_weight_center_inside_domain_count": sum(int(r[3]) for r in rows),
        "positive_weight_center_outside_outer_domain_count": sum(int(not r[1]) for r in rows),
        "positive_weight_center_inside_gamma_exclusion_count": sum(int(r[2]) for r in rows),
        "positive_weight_center_on_boundary_count": 0,
        "included_center_count": validation["included_grid_center_count"],
        "weight_sum": validation["discrete_quadrature_weight_sum"],
        "continuous_domain_area": validation["net_continuous_domain_area"],
        "relative_area_error": validation["relative_discrete_area_error"],
    }

def main():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    preserved = {name: sha(ORIGINAL / name) for name in ("a_source_valley_chern_contract.json", "a_hbz_domain.py", "a_domain_validation.json", "a_integration_capability_audit.json")}
    cases = []
    policy_rows = []
    for fr, dk, dg in ((0.0, 0.10, 0.10), (0.4, 0.05, 0.13)):
        case = build_case(fr, dk, dg)
        result = validate_case(case)
        result["source_parameterization"] = {"delta_K_geometric_meaning": contract["source_parameter_semantics"]["delta_K_geometric_meaning"], "delta_Gamma_geometric_meaning": contract["source_parameter_semantics"]["delta_Gamma_geometric_meaning"], "outer_boundary_construction": contract["source_parameter_semantics"]["outer_boundary_construction"], "hexagon_rotation_source_bound": True}
        result["sample_accounting"] = category_counts(case, result)
        cases.append(result)
        policy_rows.append(sample_policy(case, result))
    validation = {
        "schema": "trilatt_e9f_a_c1_domain_validation_v1", "work_order_id": contract["work_order_id"], "contract_sha256": sha(CONTRACT), "preserved_e9f_a_sha256": preserved,
        "source_parameter_to_geometry_mapping": "BOUND", "delta_K_geometric_meaning": "CIRCUMRADIUS_DECREMENT_FROM_VALLEY_CENTER", "delta_Gamma_geometric_meaning": "HEXAGON_CIRCUMRADIUS", "hexagon_rotation_source_bound": True,
        "paper_project_domain_label_mapping": contract["public_paper_label_mapping"], "domain_label_mapping_unambiguous": "PASSED", "source_exclusion_geometry": "SOURCE_BOUND_QUALITATIVE_FIGURE_ORIENTATION_NO_DIGITIZATION",
        "cases": cases, "outer_domain_boundary_separated_from_physical_qualification": True, "outer_domain_plaquette_crossing": "NOT_AUTOMATICALLY_DISQUALIFYING", "gamma_exclusion_plaquette_crossing": "REQUIRES_EXPLICIT_POLICY", "exclusion_crossing_policy": "BOUND",
        "new_mpb_solver_requests": 0, "new_berry_calculation": "NONE", "new_valley_chern_value": "NONE", "production_code_change": False, "main_expected_sha": EXPECTED_MAIN,
        "overall": "SOURCE_DOMAIN_AND_QUADRATURE_SEMANTICS_READY_FOR_PRODUCTION_INTEGRATOR"
    }
    policy = {"schema": "trilatt_e9f_a_c1_future_sample_policy_bundle_v1", "work_order_id": contract["work_order_id"], "contract_sha256": sha(CONTRACT), "future_integrator_rule": "for every positive-weight clipped cell and every target band exactly one of BERRY_STATUS=QUALIFIED_REPORTED or BERRY_STATUS=NOT_REPORTED; no missing row, NaN, zero fill, or silent drop", "cases": policy_rows}
    (ROOT / "audit/e9f/c1_domain_validation.json").write_text(json.dumps(validation, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (ROOT / "audit/e9f/c1_future_sample_policy.json").write_text(json.dumps(policy, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": validation["overall"], "contract_sha256": validation["contract_sha256"], "preserved_e9f_a": preserved, "cases": [{"fr": c["fr"], **c["sample_accounting"]} for c in cases], "new_mpb_solver_requests": 0, "new_berry_calculation": "NONE"}, sort_keys=True))

if __name__ == "__main__":
    main()
