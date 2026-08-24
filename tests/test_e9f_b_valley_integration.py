import copy
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
    validate_integration_plan,
)


def _plan(fr=0.0, estimator=SOURCE_GRID_MIDPOINT_V1):
    return build_integration_plan(build_source_bound_domain(fr), estimator)


def _qualified(plan, value=1.0):
    return [build_berry_row(plan, row, 1, "QUALIFIED_REPORTED", omega_q=value) for row in plan["ROWS"]]


@pytest.mark.parametrize("fr,source_count,clipped_count", [(0.0, 551, 752), (0.4, 641, 872)])
def test_c2_c3_geometry_counts_weights_and_digests_are_unchanged(fr, source_count, clipped_count):
    domain = build_source_bound_domain(fr)
    source = build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)
    clipped = build_integration_plan(domain, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)
    assert source["SAMPLE_COUNT"] == source_count
    assert clipped["SAMPLE_COUNT"] == clipped_count
    assert source["TOTAL_WEIGHT_Q2"] == pytest.approx(
        0.4251543209876543 if fr == 0.0 else 0.49459876543209874
    )
    assert clipped["TOTAL_WEIGHT_Q2"] == pytest.approx(
        0.41713556948950337 if fr == 0.0 else 0.48568148019904134
    )
    assert source["ESTIMATOR_ID"] != clipped["ESTIMATOR_ID"]
    assert source["PLAN_DIGEST"] == build_integration_plan(domain, SOURCE_GRID_MIDPOINT_V1)["PLAN_DIGEST"]
    assert clipped["PLAN_DIGEST"] == build_integration_plan(domain, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)["PLAN_DIGEST"]


def test_constant_field_normalization_and_binding_schema():
    plan = _plan(0.4, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)
    rows = _qualified(plan, 3.25)
    assert all(
        set(("PLAN_DIGEST", "DOMAIN_DIGEST", "PUBLIC_Q_HEX_FLOATS")) <= set(row)
        for row in rows
    )
    result = reduce_supplied_berry_rows(plan, rows, 1)
    assert math.isclose(result["FLUX_Q"], 3.25 * plan["TOTAL_WEIGHT_Q2"], abs_tol=1e-13)
    assert math.isclose(result["VALLEY_CHERN"], result["FLUX_Q"] / (2 * math.pi), abs_tol=1e-13)


def test_permutation_invariance_and_mixed_estimator_rejection():
    plan = _plan()
    rows = _qualified(plan)
    first = reduce_supplied_berry_rows(plan, rows, 1)
    second = reduce_supplied_berry_rows(plan, list(reversed(rows)), 1)
    assert first["STATUS_DIGEST"] == second["STATUS_DIGEST"]
    mixed = list(rows)
    mixed[0] = {**mixed[0], "ESTIMATOR_ID": MEPHC_CLIPPED_RETAINED_DOMAIN_V1}
    with pytest.raises(IntegrationPlanError, match="MIXED_ESTIMATOR"):
        reduce_supplied_berry_rows(plan, mixed, 1)


def test_valid_incomplete_result_suppresses_numeric_aggregate():
    plan = _plan()
    rows = _qualified(plan)
    rows[1] = build_berry_row(plan, plan["ROWS"][1], 1, "NOT_REPORTED_WITH_REASON", reason="synthetic unavailable")
    result = reduce_supplied_berry_rows(plan, rows, 1)
    assert result["COMPLETE_STATUS"] == "INCOMPLETE_NOT_REPORTED"
    assert result["FLUX_Q"] == "NOT_EMITTED"
    assert result["VALLEY_CHERN"] == "NOT_EMITTED"


def test_missing_and_duplicate_rows_fail_closed():
    plan = _plan()
    rows = _qualified(plan)
    with pytest.raises(IntegrationPlanError, match="MISSING_ROW"):
        reduce_supplied_berry_rows(plan, rows[1:], 1)
    with pytest.raises(IntegrationPlanError, match="DUPLICATE_ROW"):
        reduce_supplied_berry_rows(plan, rows + [rows[0]], 1)


@pytest.mark.parametrize("mutation", ["SAMPLE_COUNT", "TOTAL_WEIGHT_Q2", "PLAN_DIGEST", "ROW_DOMAIN", "ROW_Q"])
def test_plan_tampering_rejected_before_integration(mutation):
    plan = copy.deepcopy(_plan())
    if mutation == "SAMPLE_COUNT":
        plan["SAMPLE_COUNT"] += 1
    elif mutation == "TOTAL_WEIGHT_Q2":
        plan["TOTAL_WEIGHT_Q2"] += 1e-6
    elif mutation == "PLAN_DIGEST":
        plan["PLAN_DIGEST"] = "tampered"
    elif mutation == "ROW_DOMAIN":
        plan["ROWS"][0]["DOMAIN_ID_OR_DIGEST"] = "tampered"
    elif mutation == "ROW_Q":
        plan["ROWS"][0]["PUBLIC_Q"] = (99.0, 99.0)
    with pytest.raises(IntegrationPlanError):
        validate_integration_plan(plan)
    with pytest.raises(IntegrationPlanError):
        reduce_supplied_berry_rows(plan, [], 1)


@pytest.mark.parametrize("field", ["PLAN_DIGEST", "DOMAIN_DIGEST", "PUBLIC_Q_HEX_FLOATS", "WEIGHT_Q2"])
def test_cross_plan_binding_field_transplant_rejected(field):
    plan = _plan(0.0)
    other = _plan(0.4)
    rows = _qualified(plan)
    foreign = _qualified(other)[0]
    if field == "PLAN_DIGEST":
        rows[0][field] = foreign[field]
    elif field == "DOMAIN_DIGEST":
        rows[0][field] = foreign[field]
    elif field == "PUBLIC_Q_HEX_FLOATS":
        rows[0][field] = foreign[field]
    else:
        rows[0][field] = plan["ROWS"][0]["WEIGHT_Q2"] * 0.5
    with pytest.raises(IntegrationPlanError):
        reduce_supplied_berry_rows(plan, rows, 1)


def test_real_cross_plan_row_transplant_rejected():
    plan = _plan(0.0)
    other = _plan(0.4)
    rows = _qualified(plan)
    rows[0] = _qualified(other)[0]
    with pytest.raises(IntegrationPlanError):
        reduce_supplied_berry_rows(plan, rows, 1)


@pytest.mark.parametrize("variant", [
    "missing_reason", "blank_reason", "failed_zero", "failed_nonzero", "failed_nan", "failed_inf",
    "qualified_missing", "qualified_nan", "qualified_inf", "qualified_reason",
])
def test_terminal_status_payloads_fail_closed(variant):
    plan = _plan()
    rows = _qualified(plan)
    row = dict(rows[0])
    if variant == "missing_reason":
        row["STATUS"] = "NOT_REPORTED_WITH_REASON"
    elif variant == "blank_reason":
        row["STATUS"] = "NOT_REPORTED_WITH_REASON"
        row["REASON"] = "   "
    elif variant in {"failed_zero", "failed_nonzero", "failed_nan", "failed_inf"}:
        row["STATUS"] = "NOT_REPORTED_WITH_REASON"
        row["REASON"] = "failed"
        row["OMEGA_Q"] = {
            "failed_zero": 0.0,
            "failed_nonzero": 2.0,
            "failed_nan": float("nan"),
            "failed_inf": float("inf"),
        }[variant]
    elif variant == "qualified_missing":
        del row["OMEGA_Q"]
    elif variant in {"qualified_nan", "qualified_inf"}:
        row["OMEGA_Q"] = float("nan") if variant.endswith("nan") else float("inf")
    elif variant == "qualified_reason":
        row["REASON"] = "unexpected"
    rows[0] = row
    with pytest.raises(IntegrationPlanError):
        reduce_supplied_berry_rows(plan, rows, 1)


@pytest.mark.parametrize("bad", ["zero_fill", "silent_drop", "renormalize"])
def test_legacy_fail_closed_guards_remain(bad):
    plan = _plan()
    rows = _qualified(plan)
    if bad == "zero_fill":
        rows[0]["STATUS"] = "NOT_REPORTED_WITH_REASON"
        rows[0]["REASON"] = "failed"
        rows[0]["OMEGA_Q"] = 0.0
    elif bad == "silent_drop":
        rows = rows[1:]
    else:
        rows[0]["WEIGHT_Q2"] *= 0.5
    with pytest.raises(IntegrationPlanError):
        reduce_supplied_berry_rows(plan, rows, 1)
