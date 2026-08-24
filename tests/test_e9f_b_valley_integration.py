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
    compare_plan_semantics,
    portable_plan_fingerprint,
    reduce_supplied_berry_rows,
    semantic_domain_id,
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


def test_semantic_identity_and_portable_fingerprint_bind_topology_only():
    domain_zero = build_source_bound_domain(0.0)
    domain_four = build_source_bound_domain(0.4)
    assert domain_zero.semantic_domain_id == semantic_domain_id("fr=0")
    assert domain_four.semantic_domain_id == semantic_domain_id("fr=0.4")
    assert domain_zero.semantic_domain_id != domain_four.semantic_domain_id
    plan = _plan(0.4, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)
    assert plan["PORTABLE_PLAN_FINGERPRINT"] == portable_plan_fingerprint(plan)
    for field, value in (("ESTIMATOR_ID", SOURCE_GRID_MIDPOINT_V1), ("SEMANTIC_DOMAIN_ID", "changed"), ("SOURCE_GRID_SPACING_ID", "1/18")):
        mutated = copy.deepcopy(plan)
        mutated[field] = value
        assert portable_plan_fingerprint(mutated) != plan["PORTABLE_PLAN_FINGERPRINT"]
    for field in ("SAMPLE_ID", "GRID_INDEX", "FRAGMENT_INDEX", "TRIANGLE_INDEX"):
        mutated = copy.deepcopy(plan)
        row = mutated["ROWS"][0]
        if field == "SAMPLE_ID": row[field] = row[field] + ";mutated"
        elif field == "GRID_INDEX": row[field] = (row[field][0] + 1, row[field][1])
        else: row[field] = (row[field] or 0) + 1
        assert portable_plan_fingerprint(mutated) != plan["PORTABLE_PLAN_FINGERPRINT"]


def test_plan_semantic_comparison_accepts_same_plan_and_reports_identity_layers():
    plan = _plan(0.4, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)
    result = compare_plan_semantics(plan, copy.deepcopy(plan))
    assert result["raw_plan_digest_equal"]
    assert result["portable_plan_fingerprint_equal"]
    assert result["semantic_domain_id_equal"]
    assert result["topology_equal"]
    assert result["numerically_equivalent"]


def test_portability_tolerance_cannot_be_relaxed_or_invalid():
    plan = _plan(0.4, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)
    for bad_tolerance in (1e-11, -1.0, float("nan"), float("inf"), None):
        with pytest.raises(IntegrationPlanError, match="PORTABILITY_TOLERANCE_INVALID"):
            compare_plan_semantics(plan, plan, tolerance=bad_tolerance)
    assert compare_plan_semantics(plan, copy.deepcopy(plan), tolerance=1e-12)["numerically_equivalent"]


def test_semantic_domain_case_binding_rejects_coherent_wrong_identity():
    plan = _plan(0.0)
    mutated = copy.deepcopy(plan)
    mutated["SEMANTIC_DOMAIN_ID"] = semantic_domain_id("fr=0.4")
    mutated["PORTABLE_PLAN_FINGERPRINT"] = portable_plan_fingerprint(mutated)
    with pytest.raises(IntegrationPlanError, match="SEMANTIC_DOMAIN_CASE_BINDING_INVALID"):
        validate_integration_plan(mutated)


def test_semantic_domain_case_binding_rejects_mixed_and_unsupported_rows():
    plan = _plan(0.0)
    mixed = copy.deepcopy(plan)
    first = dict(mixed["ROWS"][0])
    first["SAMPLE_ID"] = first["SAMPLE_ID"].replace("fr=0;", "fr=0.4;", 1)
    mixed["ROWS"] = (first,) + tuple(mixed["ROWS"][1:])
    mixed["PORTABLE_PLAN_FINGERPRINT"] = portable_plan_fingerprint(mixed)
    with pytest.raises(IntegrationPlanError, match="SEMANTIC_CASE_MIXED_OR_MISSING"):
        validate_integration_plan(mixed)
    unsupported = copy.deepcopy(plan)
    first = dict(unsupported["ROWS"][0])
    first["SAMPLE_ID"] = first["SAMPLE_ID"].replace("fr=0;", "fr=1;", 1)
    unsupported["ROWS"] = (first,) + tuple(unsupported["ROWS"][1:])
    unsupported["PORTABLE_PLAN_FINGERPRINT"] = portable_plan_fingerprint(unsupported)
    with pytest.raises(IntegrationPlanError, match="UNSUPPORTED_SEMANTIC_CASE"):
        validate_integration_plan(unsupported)
