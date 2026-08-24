import math
import pytest

from mephc.valley_chern import (
    IntegrationPlanError,
    MEPHC_CLIPPED_RETAINED_DOMAIN_V1,
    SOURCE_GRID_MIDPOINT_V1,
    build_berry_row,
    build_integration_plan,
    build_source_bound_domain,
    reduce_supplied_berry_rows,
)


@pytest.mark.parametrize("fr,source_count,clipped_count", [(0.0, 551, 752), (0.4, 641, 872)])
def test_source_and_clipped_plans_match_sealed_counts(fr, source_count, clipped_count):
    domain = build_source_bound_domain(fr)
    source = build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)
    clipped = build_integration_plan(domain, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)
    assert source["SAMPLE_COUNT"] == source_count
    assert clipped["SAMPLE_COUNT"] == clipped_count
    assert source["ESTIMATOR_ID"] != clipped["ESTIMATOR_ID"]
    assert source["PLAN_DIGEST"] == build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)["PLAN_DIGEST"]
    assert clipped["PLAN_DIGEST"] == build_integration_plan(domain, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)["PLAN_DIGEST"]
    assert all(r["WEIGHT_Q2"] > 0 and all(math.isfinite(x) for x in r["PUBLIC_Q"]) for r in source["ROWS"] + clipped["ROWS"])


def test_constant_field_and_coordinate_normalization():
    domain = build_source_bound_domain(0.4)
    plan = build_integration_plan(domain, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)
    rows = [build_berry_row(r, 1, "QUALIFIED_REPORTED", omega_q=3.25) for r in plan["ROWS"]]
    result = reduce_supplied_berry_rows(plan, rows, 1)
    assert math.isclose(result["FLUX_Q"], 3.25 * plan["TOTAL_WEIGHT_Q2"], rel_tol=0, abs_tol=1e-13)
    assert math.isclose(result["VALLEY_CHERN"], result["FLUX_Q"] / (2 * math.pi), rel_tol=0, abs_tol=1e-13)


def test_permutation_invariance_and_mixed_estimator_rejection():
    domain = build_source_bound_domain(0.0)
    plan = build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)
    rows = [build_berry_row(r, 1, "QUALIFIED_REPORTED", omega_q=1.0) for r in plan["ROWS"]]
    a = reduce_supplied_berry_rows(plan, rows, 1)
    b = reduce_supplied_berry_rows(plan, list(reversed(rows)), 1)
    assert a["STATUS_DIGEST"] == b["STATUS_DIGEST"]
    mixed = list(rows)
    mixed[0] = {**mixed[0], "ESTIMATOR_ID": MEPHC_CLIPPED_RETAINED_DOMAIN_V1}
    with pytest.raises(IntegrationPlanError, match="MIXED_ESTIMATOR"):
        reduce_supplied_berry_rows(plan, mixed, 1)


def test_incomplete_and_status_fail_closed():
    domain = build_source_bound_domain(0.0)
    plan = build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)
    first, second = plan["ROWS"][:2]
    good = build_berry_row(first, 1, "QUALIFIED_REPORTED", omega_q=1.0)
    missing = build_berry_row(second, 1, "NOT_REPORTED_WITH_REASON", reason="synthetic")
    incomplete = reduce_supplied_berry_rows(plan, [good, missing] + [build_berry_row(r, 1, "QUALIFIED_REPORTED", omega_q=1.0) for r in plan["ROWS"][2:]], 1)
    assert incomplete["COMPLETE_STATUS"] == "INCOMPLETE_NOT_REPORTED"
    assert incomplete["FLUX_Q"] == "NOT_EMITTED"
    assert incomplete["VALLEY_CHERN"] == "NOT_EMITTED"
    with pytest.raises(IntegrationPlanError, match="MISSING_ROW"):
        reduce_supplied_berry_rows(plan, [good] + [build_berry_row(r, 1, "QUALIFIED_REPORTED", omega_q=1.0) for r in plan["ROWS"][2:]], 1)
    with pytest.raises(IntegrationPlanError, match="DUPLICATE_ROW"):
        reduce_supplied_berry_rows(plan, [build_berry_row(r, 1, "QUALIFIED_REPORTED", omega_q=1.0) for r in plan["ROWS"]] + [good], 1)


@pytest.mark.parametrize("bad", ["nan", "zero_fill", "silent_drop", "renormalize"])
def test_bad_status_or_weight_rejected(bad):
    domain = build_source_bound_domain(0.0)
    plan = build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)
    rows = [build_berry_row(r, 1, "QUALIFIED_REPORTED", omega_q=1.0) for r in plan["ROWS"]]
    if bad == "nan": rows[0]["OMEGA_Q"] = float("nan")
    if bad == "zero_fill": rows[0] = {**build_berry_row(plan["ROWS"][0], 1, "NOT_REPORTED_WITH_REASON", omega_q=0.0, reason="bad"), "OMEGA_Q": 0.0}
    if bad == "silent_drop": rows = rows[1:]
    if bad == "renormalize": rows[0]["WEIGHT_Q2"] *= 0.5
    with pytest.raises(IntegrationPlanError):
        reduce_supplied_berry_rows(plan, rows, 1)
