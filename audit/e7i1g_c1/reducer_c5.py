"""C5 strict wrapper around the deterministic C4 reducer."""
from __future__ import annotations

import math

import reducer_c4 as core


def validate_trace(trace, expected_area=1.0 / math.sqrt(3.0)):
    checked = core.validate_trace(trace, expected_area)
    for rule, payload in trace.get("rules", {}).items():
        if payload.get("exact_domain") and int(payload["qualified_count"]) != int(payload["total_record_count"]):
            raise ValueError(f"strict qualification failure: {rule}")
        for chunk in payload.get("chunks", []):
            if int(chunk["qualified_count"]) != int(chunk["input_record_count"]):
                raise ValueError(f"strict chunk qualification failure: {rule}")
    return checked


def reduce(trace, controls):
    validate_trace(trace)
    return core.reduce(trace, controls)
