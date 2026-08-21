"""C4 scale-aware seam wrapper for near-zero Berry values.

The core reducer remains responsible for trace closure and all other gates.
This module supplies the fixed R64 sentinel scale floor required to make the
individual-band seam hybrid metric well-conditioned near Omega=0.
"""
from __future__ import annotations

import copy
import math

import reducer_c4 as core


def _hybrid(left, right, scale):
    return abs(left - right) / max(abs(left), abs(right), 0.1 * abs(scale), 1e-300)


def periodicity_metrics(row):
    metrics = core._periodicity_metrics(row)
    for band in (1, 2):
        left = core._omega(row["a"], band)
        right = core._omega(row["b"], band)
        metrics[f"hybrid_band{band}"] = _hybrid(left, right, row.get(f"scale_band{band}", 1.0))
    return metrics


def classify_periodicity(records, spectral_tolerance=core.SPECTRAL_TOL):
    try:
        metrics = [periodicity_metrics(row) for row in records]
    except (KeyError, TypeError, ValueError):
        return "FAILED"
    if not metrics:
        return "FAILED"
    if not all(row["reciprocal_identity"] and row["rank_compatible"] and row["qualification_compatible"] for row in metrics):
        return "PARTIALLY_CONFIRMED"
    if any(max(row["frequency_disagreement"], row["pair_gap_disagreement"], row["external_gap_disagreement"]) > spectral_tolerance for row in metrics):
        return "PARTIALLY_CONFIRMED"
    if core._p90([row["hybrid_band1"] for row in metrics]) > core.HYBRID_TOL or core._p90([row["hybrid_band2"] for row in metrics]) > core.HYBRID_TOL:
        return "PARTIALLY_CONFIRMED"
    return "CONFIRMED"


def reduce(trace, controls):
    result = core.reduce(trace, controls)
    result["periodicity"] = classify_periodicity(controls["seam_pairs"])
    result["periodicity_hybrid_metric"] = "FIXED_SENTINEL_SCALE_FLOOR"
    return result
