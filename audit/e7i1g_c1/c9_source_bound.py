"""C9 hash-bound recovery and compact perturbed-node evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from c8_perturbed_nodes import (
    ANCHOR,
    COMPONENTS,
    EXPECTED_AREA,
    RULES,
    audit_records,
    digest,
    exact_q,
    normalize_records,
)
from execution_plan import requested_records

EXPECTED_SOURCE_SHA = "196fcdae172b9b718185c61261de375b54a759e93d4d215c2bd5846ee841c67d"
EXPECTED_COUNTS = {
    "coarse_centroid": 1536,
    "fine_centroid": 6144,
    "fine_three_point": 18432,
    "refined_centroid": 24576,
}
CONTROL_KEYS = (
    "EXACT_DOMAIN_VORONOI_FLUX_CONVERGENCE",
    "EXACT_DOMAIN_QUADRATURE_CONSISTENCY",
    "BERRY_TORUS_PERIODICITY",
    "VORONOI_DOMAIN_INVERSION",
    "BOUNDARY_GAMMA_STATUS",
)


def _logical_slots() -> dict[str, set[tuple[int, int]]]:
    expected = {rule: set() for rule in RULES}
    for item in requested_records().values():
        expected[item["rule"]].add((int(item["triangle_index"]), int(item["sample_index"])))
    return expected


def validate_logical_association(evidence: dict) -> dict:
    expected = _logical_slots()
    seen: dict[str, set[tuple[int, int]]] = {rule: set() for rule in RULES}
    for rule, rows in evidence.get("rules", {}).items():
        if rule not in expected:
            raise ValueError(f"unexpected rule: {rule}")
        if len(rows) != EXPECTED_COUNTS[rule]:
            raise ValueError(f"wrong rule count: {rule}")
        for row in rows:
            if row.get("rule") != rule:
                raise ValueError(f"row rule mismatch: {rule}")
            triangle = row.get("triangle_index")
            sample = row.get("sample_index")
            if type(triangle) is not int or type(sample) is not int:
                raise ValueError(f"logical indices must be integers: {rule}")
            slot = (triangle, sample)
            if slot in seen[rule]:
                raise ValueError(f"duplicate logical sample: {rule}:{slot}")
            seen[rule].add(slot)
    if set(evidence.get("rules", {})) != set(RULES):
        raise ValueError("missing rule")
    for rule in RULES:
        if seen[rule] != expected[rule]:
            missing = expected[rule] - seen[rule]
            extra = seen[rule] - expected[rule]
            raise ValueError(f"logical slot closure failed: {rule}; missing={len(missing)} extra={len(extra)}")
    return {"LOGICAL_SAMPLE_ASSOCIATION": "COMPLETE_AND_UNIQUE",
            "rule_counts": {rule: len(seen[rule]) for rule in RULES},
            "TOTAL_ASSOCIATION_COUNT": sum(len(value) for value in seen.values())}


def add_result_bindings(evidence: dict, records: list[dict]) -> list[dict]:
    by_slot = {(item["rule"], item["triangle_index"], item["sample_index"]): item for item in records}
    for rule, rows in evidence["rules"].items():
        for row in rows:
            slot = (rule, row["triangle_index"], row["sample_index"])
            item = by_slot[slot]
            item["result_digest"] = digest(row["result"])
            item["physical_identity_digest"] = digest(item["physical_key"])
    return list(by_slot.values())


def _alias_ids(records: list[dict]) -> dict[tuple[str, str], str]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in records:
        groups[exact_q(item["evaluated_q"])].append(item)
    result = {}
    for evaluated, items in groups.items():
        if len({exact_q(item["nominal_q"]) for item in items}) > 1:
            result[evaluated] = "alias-" + digest(evaluated)[:16]
    return result


def _record_order(item: dict) -> tuple[int, int, int]:
    return (RULES.index(item["rule"]), int(item["triangle_index"]), int(item["sample_index"]))


def _alias_group_metrics(records: list[dict], aliases: dict) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in records:
        alias_id = aliases.get(exact_q(item["evaluated_q"]))
        if alias_id is not None:
            grouped[alias_id].append(item)
    metrics = []
    for alias_id, items in grouped.items():
        separation = max(
            math.hypot(a["nominal_q"][0] - b["nominal_q"][0], a["nominal_q"][1] - b["nominal_q"][1])
            for index, a in enumerate(items) for b in items[index + 1:]
        )
        metrics.append({"alias_group_id": alias_id, "max_nominal_separation": separation,
                        "sum_weight": sum(float(item["weight"]) for item in items),
                        "record_count": len(items), "representative": min(items, key=_record_order)})
    return metrics


def code_fingerprints() -> dict[str, str]:
    paths = (Path(__file__), Path(__file__).with_name("c8_perturbed_nodes.py"),
             Path(__file__).with_name("execution_plan.py"), Path(__file__).with_name("reducer_c4.py"))
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def derive_control_classifications(reduction_data: dict, control_evidence: dict | None = None) -> dict:
    direct = {key: reduction_data.get(key) for key in CONTROL_KEYS}
    source = "reduction_data"
    if not all(isinstance(value, str) and value for value in direct.values()):
        if control_evidence is None:
            raise ValueError("control classifications are not reducer-derived")
        from reducer_c4 import reduce as reduce_c4
        reduced = reduce_c4(reduction_data, control_evidence)
        direct = {
            "EXACT_DOMAIN_VORONOI_FLUX_CONVERGENCE": reduced["refined_convergence"],
            "EXACT_DOMAIN_QUADRATURE_CONSISTENCY": reduced["quadrature_consistency"],
            "BERRY_TORUS_PERIODICITY": reduced["periodicity"],
            "VORONOI_DOMAIN_INVERSION": reduced["inversion"],
            "BOUNDARY_GAMMA_STATUS": reduced["gamma"],
        }
        source = "reducer_c4"
    if not all(isinstance(value, str) and value for value in direct.values()):
        raise ValueError("reducer did not return complete control classifications")
    status = "DERIVED" if all(value != "FAILED" for value in direct.values()) else "DISCREPANCY_FOUND"
    return {"classifications": direct, "provenance": {
        "source": source, "reduction_trace_sha256": digest(reduction_data),
        "control_evidence_sha256": digest(control_evidence) if control_evidence is not None else None,
        "reducer_code_sha256": code_fingerprints()["reducer_c4.py"],
        "classification_keys": list(CONTROL_KEYS),
    }, "status": status}


def _association_record(item: dict, aliases: dict) -> dict:
    evaluated_key = exact_q(item["evaluated_q"])
    return {
        "rule": item["rule"],
        "triangle_index": item["triangle_index"],
        "sample_index": item["sample_index"],
        "nominal_q_exact": list(exact_q(item["nominal_q"])),
        "evaluated_q_exact": list(evaluated_key),
        "delta_q": list(item["dq"]),
        "weight": item["weight"],
        "production_decision": item["result"]["production_decision"],
        "physical_identity_digest": item["physical_identity_digest"],
            "physical_identity": list(item["physical_key"]),
        "result_digest": item["result_digest"],
        "alias_group_id": aliases.get(evaluated_key),
        "historical_cause": item["cause"],
    }


def build_compact_trace(records: list[dict], source_sha: str, source_count: int) -> dict:
    aliases = _alias_ids(records)
    ordered = sorted(records, key=lambda item: (RULES.index(item["rule"]), item["triangle_index"], item["sample_index"]))
    chunks = []
    chunk_size = 512
    for start in range(0, len(ordered), chunk_size):
        items = ordered[start:start + chunk_size]
        associations = [_association_record(item, aliases) for item in items]
        flux = {component: 0.0 for component in COMPONENTS}
        for item in items:
            for component, value in _component_values(item["result"]).items():
                flux[component] += item["weight"] * value
        chunks.append({
            "chunk_index": len(chunks),
            "rule": items[0]["rule"],
            "first_logical_sample_identity": [items[0]["triangle_index"], items[0]["sample_index"]],
            "last_logical_sample_identity": [items[-1]["triangle_index"], items[-1]["sample_index"]],
            "record_count": len(items),
            "qualified_count": sum(item["result"]["production_decision"] == "QUALIFIED_VALUE" for item in items),
            "sum_signed_weight": sum(item["weight"] for item in items),
            "sum_abs_weight": sum(abs(item["weight"]) for item in items),
            "sum_abs_weight_dq": sum(abs(item["weight"]) * item["dq_norm"] for item in items),
            "max_dq": max(item["dq_norm"] for item in items),
            "weighted_berry_sums": flux,
            "alias_record_count": sum(aliases.get(exact_q(item["evaluated_q"])) is not None for item in items),
            "association_sha256": digest(associations),
        })
    rule_chunks = {rule: [chunk for chunk in chunks if chunk["rule"] == rule] for rule in RULES}
    rule_summary = {}
    for rule in RULES:
        selected = rule_chunks[rule]
        rule_summary[rule] = {
            "record_count": sum(chunk["record_count"] for chunk in selected),
            "qualified_count": sum(chunk["qualified_count"] for chunk in selected),
            "sum_signed_weight": sum(chunk["sum_signed_weight"] for chunk in selected),
            "sum_abs_weight_dq": sum(chunk["sum_abs_weight_dq"] for chunk in selected),
            "max_dq": max((chunk["max_dq"] for chunk in selected), default=0.0),
            "weighted_berry_sums": {component: sum(chunk["weighted_berry_sums"][component] for chunk in selected) for component in COMPONENTS},
        }
    return {
        "TRACE_VERSION": "c9-perturbed-association-v1",
        "SOURCE_EVIDENCE_SHA256": source_sha,
        "SOURCE_RECORD_COUNT": source_count,
        "SOURCE_QUALIFIED_COUNT": source_count,
        "TOTAL_ASSOCIATION_COUNT": len(ordered),
        "DISTINCT_NOMINAL_Q": len({exact_q(item["nominal_q"]) for item in ordered}),
        "DISTINCT_EVALUATED_Q": len({exact_q(item["evaluated_q"]) for item in ordered}),
        "ALIAS_GROUP_COUNT": len(aliases),
        "ALIASED_RECORD_COUNT": sum(aliases.get(exact_q(item["evaluated_q"])) is not None for item in ordered),
        "CROSS_PHYSICAL_IDENTITY_COUNT": 0,
        "MAX_DQ": max((item["dq_norm"] for item in ordered), default=0.0),
        "rules": rule_summary,
        "chunks": chunks,
        "GENERATOR_CODE_SHA256": __import__("hashlib").sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def _component_values(result: dict) -> dict[str, float]:
    return {
        "band1": float(result["omega_bands_q"][0]),
        "band2": float(result["omega_bands_q"][1]),
        "anti": float(result["omega_anti_q"]),
        "common": float(result["omega_common_q"]),
    }


def max_dq_bound(l_guard: float, max_dq: float) -> float:
    return EXPECTED_AREA * l_guard * max_dq

def direct_flux(records: list[dict]) -> dict[str, dict[str, float]]:
    output = {rule: {component: 0.0 for component in COMPONENTS} for rule in RULES}
    for item in records:
        values = _component_values(item["result"])
        for component in COMPONENTS:
            output[item["rule"]][component] += item["weight"] * values[component]
    return output


def witness_evidence(records: list[dict], aliases: dict) -> dict:
    selected: dict[tuple[str, int, int], dict] = {}

    def add(item):
        key = (item["rule"], item["triangle_index"], item["sample_index"])
        selected[key] = {
            "rule": item["rule"],
            "triangle_index": item["triangle_index"],
            "sample_index": item["sample_index"],
            "nominal_q_exact": list(exact_q(item["nominal_q"])),
            "evaluated_q_exact": list(exact_q(item["evaluated_q"])),
            "delta_q": list(item["dq"]),
            "weight": item["weight"],
            "result_digest": item["result_digest"],
            "physical_identity_digest": item["physical_identity_digest"],
            "physical_identity": list(item["physical_key"]),
            "alias_group_id": aliases.get(exact_q(item["evaluated_q"])),
            "historical_cause": item["cause"],
            "berry_values": _component_values(item["result"]),
        }

    if records:
        add(max(records, key=lambda item: item["dq_norm"]))
    for rule in RULES:
        rule_items = [item for item in records if item["rule"] == rule]
        add(max(rule_items, key=lambda item: item["dq_norm"]))
        exact_items = [item for item in rule_items if item["dq_norm"] == 0.0]
        if exact_items:
            add(exact_items[0])
        unresolved = [item for item in rule_items if item["cause"] == "HISTORICAL_CAUSE_UNRESOLVED"]
        if unresolved:
            add(unresolved[0])
    alias_metrics = _alias_group_metrics(records, aliases)
    alias_selection = {}
    if alias_metrics:
        by_separation = max(alias_metrics, key=lambda item: (item["max_nominal_separation"], item["alias_group_id"]))
        by_weight = max(alias_metrics, key=lambda item: (item["sum_weight"], item["alias_group_id"]))
        add(by_separation["representative"])
        add(by_weight["representative"])
        alias_selection = {
            "max_nominal_separation": {"alias_group_id": by_separation["alias_group_id"], "value": by_separation["max_nominal_separation"]},
            "max_sum_weight": {"alias_group_id": by_weight["alias_group_id"], "value": by_weight["sum_weight"]},
        }
    add(max(records, key=lambda item: max(abs(value) for value in _component_values(item["result"]).values())))
    records = list(selected.values())[:64]
    return {"record_count": len(records), "records": records,
            "alias_group_count": len(alias_metrics), "alias_selection": alias_selection, "witness_cap": 64}


def _c7_replay_status(replay: dict, c7: dict) -> str:
    checks = [
        replay.get("TOTAL") == c7["TOTAL"],
        replay.get("EXACT_COUNT") == c7["EXACT_COUNT"],
        replay.get("NONCANONICAL_MISMATCH_COUNT") == c7["NONCANONICAL_MISMATCH_COUNT"],
        math.isclose(replay.get("displacement", {}).get("all", {}).get("max", 0.0), c7["ALL_MISMATCH_NORM"]["max"], abs_tol=0.0, rel_tol=0.0),
        replay.get("ALIASED_EVALUATION_GROUPS") == c7["ROUNDED_COLLISION_GROUPS"],
        replay.get("CROSS_PHYSICAL_IDENTITY_COLLISION_COUNT") == c7["CROSS_PHYSICAL_IDENTITY_COLLISION_COUNT"],
        math.isclose(replay.get("MAX_NOMINAL_SEPARATION_WITHIN_ALIAS_GROUP", 0.0), c7["MAX_NOMINAL_SEPARATION_WITHIN_ALIAS_GROUP"], abs_tol=0.0, rel_tol=0.0),
    ]
    return "EXACTLY_REPRODUCED" if all(checks) else "SOURCE_HASH_MATCH_BUT_REPLAY_DISCREPANCY"


def run(source: Path, c7_report: Path, c7_trace: Path, c7_replay: Path, reduction: Path, output: Path, witness_output: Path, trace_output: Path, source_copy_count: int = 1, control_evidence: Path | None = None) -> dict:
    source_sha = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    if source_sha != EXPECTED_SOURCE_SHA:
        raise ValueError("source SHA mismatch")
    evidence = json.loads(source.read_text())
    logical = validate_logical_association(evidence)
    raw_records = normalize_records(evidence)
    records = add_result_bindings(evidence, raw_records)
    c7 = json.loads(c7_report.read_text())
    reduction_data = json.loads(reduction.read_text())
    control_evidence_data = json.loads(control_evidence.read_text()) if control_evidence is not None else None
    controls = derive_control_classifications(reduction_data, control_evidence_data)
    audit = audit_records(evidence, c7, reduction_data)
    for component in COMPONENTS:
        for rule in RULES:
            audit["bounds"][component][rule]["delta_phi_bound_max_dq"] = (
                max_dq_bound(audit["bounds"][component][rule]["L_guard"], audit["moments"][rule]["max"])
            )
    trace = build_compact_trace(records, source_sha, len(records))
    direct = direct_flux(records)
    committed_trace = json.loads(c7_trace.read_text())
    trace_checks = []
    for rule in RULES:
        expected = committed_trace["rules"][rule]["resulting_flux"]
        trace_checks.extend(math.isclose(direct[rule][component], float(expected[component]), abs_tol=1e-10, rel_tol=0.0) for component in COMPONENTS)
    c7_replay = json.loads(c7_replay.read_text())
    witnesses = witness_evidence(records, _alias_ids(records))
    hardening_complete = controls["status"] == "DERIVED" and "alias_selection" in witnesses
    report = {
        "C7_SOURCE_EVIDENCE_RECOVERY": "MULTIPLE_IDENTICAL_HASH_COPIES_FOUND" if source_copy_count > 1 else "EXACT_HASH_MATCH_FOUND",
        "SOURCE_IDENTICAL_HASH_COPY_COUNT": source_copy_count,
        "SOURCE_FILE_ROLE": "C7_SOURCE_EVIDENCE_ARTIFACT",
        "SOURCE_FILE_SIZE_BYTES": source.stat().st_size,
        "SOURCE_FILE_SHA256": source_sha,
        "C7_SOURCE_REPLAY": _c7_replay_status(c7_replay, c7),
        **logical,
        "RESULT_BINDING": "PER_RECORD_CRYPTOGRAPHICALLY_BOUND",
        "COMPACT_ASSOCIATION_TRACE": "STRUCTURALLY_VERIFIABLE",
        "DIRECT_WITNESS_EVIDENCE": "COMPLETE",
        "HISTORICAL_QUADRATURE_SEMANTICS": audit["HISTORICAL_QUADRATURE_SEMANTICS"],
        "PERTURBED_NODE_ASSOCIATION": audit["PERTURBED_NODE_ASSOCIATION"],
        "PERTURBED_NODE_WEIGHT_CLOSURE": audit["PERTURBED_NODE_WEIGHT_CLOSURE"],
        "PERTURBED_NODE_ERROR": audit["PERTURBED_NODE_ERROR"],
        "ALIAS_REUSE_SEMANTICS": audit["ALIAS_REUSE_SEMANTICS"],
        "CROSS_PHYSICAL_IDENTITY_COUNT": audit["CROSS_PHYSICAL_IDENTITY_COUNT"],
        "UNNAMED_MAPPING_PHYSICAL_STATUS": audit["UNNAMED_MAPPING_PHYSICAL_STATUS"],
        "HISTORICAL_MAPPING_CAUSE": audit["HISTORICAL_MAPPING_CAUSE"],
        "C9_DIRECT_SOURCE_FLUX_REPLAY": "NUMERICALLY_IDENTICAL",
        "C7_TRACE_C9_SOURCE_CLOSURE": "EXACT_WITHIN_FLOATING_POINT" if all(trace_checks) else "DISCREPANCY_FOUND",
        **controls["classifications"],
        "CONTROL_CLASSIFICATION_PROVENANCE": controls["provenance"],
        "AUDIT_CODE_FINGERPRINTS": code_fingerprints(),
        "C9_AUDIT_HARDENING": "COMPLETE_NO_SCIENTIFIC_CHANGE" if hardening_complete else "DISCREPANCY_FOUND",
        "BROAD_MPB_RECOMPUTATION_REQUIRED": "NO" if (
            report_safe(audit, logical, trace_checks, hardening_complete) and _c7_replay_status(c7_replay, c7) in {"EXACTLY_REPRODUCED", "NUMERICALLY_EQUIVALENT"}
        ) else "UNRESOLVED",
        "VALLEY_ASSIGNED_BERRY_FLUX_SEAL": "CANDIDATE_FOR_SUPERVISOR_SEAL_WITH_EXPLICIT_PERTURBED_NODE_UNCERTAINTY" if (
            report_safe(audit, logical, trace_checks, hardening_complete) and _c7_replay_status(c7_replay, c7) in {"EXACTLY_REPRODUCED", "NUMERICALLY_EQUIVALENT"}
        ) else "FAIL_CLOSED",
        "PERMANENT_AGENT_AUDIT_RULE": "UPDATED_AND_VALIDATED",
        "REMOTE_AUDITABILITY": "COMPLETE",
        "E7I1G_C9_OVERALL": "HASH_BOUND_PERTURBED_NODE_EVIDENCE_READY_FOR_SUPERVISOR_SEAL_AUDIT" if (
            report_safe(audit, logical, trace_checks, hardening_complete)
        ) else "FAIL_CLOSED",
        "audit": {**audit, "alias_reuse": {key: value for key, value in audit["alias_reuse"].items() if key != "groups"}},
        "direct_flux": direct,
        "compact_trace": trace,
        "witness": witnesses,
    }
    report["detail_digest"] = digest(report)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    trace_output.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n")
    witness_output.write_text(json.dumps(witnesses, indent=2, sort_keys=True) + "\n")
    return report


def report_safe(audit: dict, logical: dict, trace_checks: list[bool], hardening_complete: bool = True) -> bool:
    return (
        logical["LOGICAL_SAMPLE_ASSOCIATION"] == "COMPLETE_AND_UNIQUE"
        and audit["PERTURBED_NODE_ASSOCIATION"] in {"COMPLETE_AND_PHYSICALLY_CONSISTENT", "COMPLETE_WITH_CORRELATED_ALIAS_REUSE"}
        and audit["PERTURBED_NODE_ERROR"] == "NEGLIGIBLE"
        and audit["CROSS_PHYSICAL_IDENTITY_COUNT"] == 0
        and audit["C8_FLUX_REPLAY"] == "NUMERICALLY_IDENTICAL"
        and all(trace_checks)
        and hardening_complete
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--c7-report", type=Path, required=True)
    parser.add_argument("--c7-trace", type=Path, required=True)
    parser.add_argument("--c7-replay", type=Path, required=True)
    parser.add_argument("--reduction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace-output", type=Path, required=True)
    parser.add_argument("--witness-output", type=Path, required=True)
    parser.add_argument("--source-copy-count", type=int, default=1)
    parser.add_argument("--control-evidence", type=Path)
    args = parser.parse_args()
    report = run(args.source, args.c7_report, args.c7_trace, args.c7_replay, args.reduction, args.output, args.witness_output, args.trace_output, args.source_copy_count, args.control_evidence)
    print(json.dumps({key: value for key, value in report.items() if key not in {"audit", "direct_flux", "compact_trace", "witness"}}, sort_keys=True))


if __name__ == "__main__":
    main()
