"""Strict qualification plus predeclared R64-median scale reduction."""
from __future__ import annotations

from reducer_c4_scaled import reduce as scaled_reduce
from reducer_c5 import validate_trace


def reduce(trace, controls):
    validate_trace(trace)
    return scaled_reduce(trace, controls)
