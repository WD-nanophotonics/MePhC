"""Rebuild C4 evidence using complete physical sample identity."""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from c4_execution import requested_records
from identity_cache import build_cache, lookup, source_row_entries
from sample_identity import expected_identity, identity_from_result


def key(record):
    return (tuple(record["sample_key"]), round(float(record["triangle_area"]), 18), round(float(record["sample_weight"]), 12))


def rebuild(fixed_path, old_path, evidence_path):
    fixed, old, prior = json.loads(fixed_path.read_text()), json.loads(old_path.read_text()), json.loads(evidence_path.read_text())
    source_rows = source_row_entries(old, "tasks", "legacy") + source_row_entries(fixed, "samples", "corrected_c1")
    cache = build_cache(source_rows)
    prior_index = {rule: {key(row): row for row in rows} for rule, rows in prior["rules"].items()}
    records = requested_records()
    counts = Counter()
    changed = 0
    for record in records.values():
        current = prior_index[record["rule"]][key(record)]
        safe = lookup(cache, record["sample_key"])
        if safe is not None:
            result, source = safe["result"], "EXACT_IDENTITY_REUSE"
            if json.dumps(result, sort_keys=True, separators=(",", ":")) != json.dumps(current.get("result"), sort_keys=True, separators=(",", ":")):
                changed += 1
        else:
            result, source = current.get("result"), "FRESH_C4"
            if result is None:
                source = "MISSING_REQUIRED_PROVENANCE"
            else:
                try:
                    if identity_from_result(result, record["sample_key"]).canonical_key() != expected_identity(record["sample_key"]).canonical_key():
                        result, source = None, "AMBIGUOUS_IDENTITY"
                except (KeyError, TypeError, ValueError):
                    result, source = None, "MISSING_REQUIRED_PROVENANCE"
        record["result"], record["source_classification"] = result, source
        counts[source] += 1
    return {"exact_domain": prior["exact_domain"], "rules": {rule: [record for record in records.values() if record["rule"] == rule] for rule in prior["rules"]}}, {"cache_collision_policy": "EXPLICIT_AND_FAIL_CLOSED", "counts": dict(counts), "changed_physical_records": changed, "source_identity_count": len(cache), "all_results_present": all(record["result"] is not None for record in records.values())}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--fixed-manifest", type=Path, required=True); parser.add_argument("--old-manifest", type=Path, required=True); parser.add_argument("--evidence", type=Path, required=True); parser.add_argument("--output-evidence", type=Path, required=True); parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(); evidence, report = rebuild(args.fixed_manifest, args.old_manifest, args.evidence); args.output_evidence.write_text(json.dumps(evidence, separators=(",", ":")), encoding="utf-8"); args.output_report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"); print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
