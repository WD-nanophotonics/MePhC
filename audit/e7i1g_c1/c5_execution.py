"""Identity-safe planning for C5 reuse and narrowly scoped fresh solves."""
from __future__ import annotations

from identity_cache import build_cache, lookup, source_row_entries
from execution_plan import requested_records


def build_identity_safe_plan(fixed_manifest, old_manifest):
    """Return records tagged as exact reuse or requiring fresh execution.

    Cache construction is keyed by the complete SampleIdentity.  A disagreeing
    result for the same complete identity raises CacheCollisionError instead
    of applying last-record-wins semantics.
    """
    source_rows = source_row_entries(old_manifest, "tasks", "legacy")
    source_rows += source_row_entries(fixed_manifest, "samples", "corrected_c1")
    cache = build_cache(source_rows)
    records = requested_records()
    exact_reuse = 0
    fresh_required = 0
    for record in records.values():
        hit = lookup(cache, record["sample_key"])
        if hit is None:
            record["reuse_classification"] = "FRESH_C5_REQUIRED"
            fresh_required += 1
        else:
            record["result"] = hit["result"]
            record["reuse_classification"] = "EXACT_IDENTITY_REUSE"
            exact_reuse += 1
    return {
        "records": records,
        "exact_reuse_count": exact_reuse,
        "fresh_required_count": fresh_required,
        "cache_identity_count": len(cache),
    }
