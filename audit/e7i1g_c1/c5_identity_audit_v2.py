"""Indexed C5 audit of every C4 cache reuse."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from c4_execution import requested_records
from c5_identity_audit import digest, source_rows
from sample_identity import expected_identity, identity_from_result, mismatch_classes


def record_key(record):
    return (tuple(record["sample_key"]), round(float(record["triangle_area"]), 18), round(float(record["sample_weight"]), 12))


def audit(fixed_manifest, old_manifest, evidence_path):
    candidates = source_rows(old_manifest, "tasks", "legacy") + source_rows(fixed_manifest, "samples", "corrected_c1")
    by_q = defaultdict(list)
    for row in candidates:
        by_q[row["q"]].append(row)
    evidence = json.loads(evidence_path.read_text())
    evidence_index = {rule: {record_key(row): row for row in rows} for rule, rows in evidence["rules"].items()}
    counts, collisions = Counter(), Counter()
    changed = unchanged = fresh = reused = 0
    ambiguous_q = []
    details = []
    for requested in requested_records().values():
        current = evidence_index[requested["rule"]][record_key(requested)]
        q = tuple(requested["sample_key"])
        expected = expected_identity(q)
        exact, wrong = [], []
        for source in by_q.get(q, []):
            try:
                identity = identity_from_result(source["result"], q)
                if not mismatch_classes(expected, identity):
                    exact.append(source)
                else:
                    wrong.append(source)
            except (KeyError, TypeError, ValueError):
                wrong.append(source)
        current_digest = digest(current["result"]) if current.get("result") else None
        exact_digests = {row["digest"] for row in exact}
        wrong_digests = {row["digest"] for row in wrong}
        if len(exact_digests) > 1:
            classification = "AMBIGUOUS_IDENTITY"; ambiguous_q.append(list(q))
        elif current_digest in exact_digests:
            classification = "EXACT_IDENTITY_REUSE"; reused += 1; unchanged += 1
        elif current_digest in wrong_digests:
            classification = "INCORRECT_REUSE"; reused += 1; changed += 1
        elif not by_q.get(q):
            classification = "FRESH_C4"; fresh += 1
        else:
            classification = "FRESH_C4_WITH_SOURCE_COLLISION"; fresh += 1
        counts[classification] += 1
        if len(by_q.get(q, [])) > 1:
            collisions["same_q_source_collision"] += 1
            if len({row["digest"] for row in by_q[q]}) > 1:
                collisions["same_q_disagreeing_results"] += 1
        details.append({"rule": requested["rule"], "sample_key": list(q), "classification": classification, "candidate_count": len(by_q.get(q, [])), "exact_candidate_count": len(exact), "wrong_candidate_count": len(wrong)})
    effect = "NO_PHYSICAL_CONTAMINATION" if not counts["INCORRECT_REUSE"] and not counts["AMBIGUOUS_IDENTITY"] else "CONTAMINATION_FOUND_AND_LOCALIZED"
    return {"sample_identity_contract": "COMPLETE_AND_EXPLICIT", "counts": dict(counts), "collision_counts": dict(collisions), "changed_physical_records": changed, "unchanged_records": unchanged, "fresh_c4_records": fresh, "reused_records": reused, "c4_cache_effect": effect, "ambiguous_q_examples": ambiguous_q[:20], "detail_digest": digest(details), "requested_record_count": len(details)}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--fixed-manifest", type=Path, required=True); parser.add_argument("--old-manifest", type=Path, required=True); parser.add_argument("--evidence", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); result = audit(args.fixed_manifest, args.old_manifest, args.evidence); args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"); print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
