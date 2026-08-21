def classify_boundary(records: list[dict]) -> str:
    required = {"exact_boundary", "production_decision", "field_continuity"}
    if not records or any(not required.issubset(row) for row in records):
        return "INSUFFICIENT_DATA"
    on_boundary = [row for row in records if row["exact_boundary"]]
    if any(row["production_decision"] != "QUALIFIED_VALUE" for row in on_boundary):
        if all(row["field_continuity"] in {"zero_measure_exception", "consistent"} for row in records):
            return "SMOOTH_WITH_LOCAL_QUALIFICATION_EXCEPTIONS"
        return "BLOCKED_BY_BOUNDARY_QUALIFICATION"
    return "SMOOTH_AND_ELIGIBLE"
