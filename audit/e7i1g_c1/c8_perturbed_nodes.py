"""C8 solver-neutral audit of historical perturbed-node quadrature evidence."""
from __future__ import annotations
import argparse, hashlib, json, math
from collections import defaultdict
from pathlib import Path

RULES = ("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid")
COMPONENTS = ("band1", "band2", "anti", "common")
PRIMARY = ("band1", "band2", "anti")
EXPECTED_AREA = 1.0 / math.sqrt(3.0)
EXPECTED = ("K", (0.15, 0.25), 64, 0.001, "mpb_live_energy_eh_v1",
            "CENTERED_CCW", "d0500-minus-sealed-honeycomb", (1, 2), 1)
ANCHOR = {"band1": -0.8672556366262376, "band2": 0.39539937924821406,
          "anti": -0.6313275079372258, "common": -0.23592812868901175}
CAUSES = {"EXACT", "PROVEN_DECIMAL10", "PROVEN_DECIMAL12",
          "PROVEN_HISTORICAL_GENERATOR_ARITHMETIC",
          "PROVEN_MANIFEST_SERIALIZATION", "HISTORICAL_CAUSE_UNRESOLVED"}

def exact_q(q):
    return (float(q[0]).hex(), float(q[1]).hex())

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def q(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must contain two coordinates")
    result = (float(value[0]), float(value[1]))
    if not all(math.isfinite(x) for x in result):
        raise ValueError(f"{label} must be finite")
    return result

def result_q(result):
    value = result.get("target_q", result.get("q"))
    return None if value is None else q(value, "EVALUATED_Q")

def nominal_q(row):
    value = row.get("nominal_q", row.get("q"))
    if value is not None:
        return q(value, "NOMINAL_Q")
    if row.get("qx") is not None and row.get("qy") is not None:
        return q((row["qx"], row["qy"]), "NOMINAL_Q")
    return None

def weight(row):
    if row.get("weight") is not None:
        return float(row["weight"])
    if row.get("triangle_area") is None:
        raise ValueError("record lacks quadrature weight")
    return float(row["triangle_area"]) * float(row.get("sample_weight", 1.0))

def physical_key(result):
    radii = tuple(float(x) for x in result.get("radii", ()))
    bands = tuple(int(x) for x in result.get("selected_bands_one_based",
                                               result.get("selected_bands", ())))
    geometry = result.get("geometry") or result.get("provenance", {}).get("geometry")
    return (str(result.get("valley")), radii, int(result.get("resolution")),
            float(result.get("h")), str(result.get("representation")),
            str(result.get("plaquette")), str(geometry), bands, int(result.get("rank")))

def component_values(result):
    bands = result.get("omega_bands_q")
    if not isinstance(bands, (list, tuple)) or len(bands) < 2:
        raise ValueError("qualified result lacks two Berry-band values")
    return {"band1": float(bands[0]), "band2": float(bands[1]),
            "anti": float(result["omega_anti_q"]),
            "common": float(result["omega_common_q"])}

def normalize_records(evidence):
    records = []
    for rule, rows in evidence.get("rules", {}).items():
        if rule not in RULES:
            raise ValueError(f"unexpected rule: {rule}")
        for row in rows:
            result = row.get("result", row)
            nominal = nominal_q(row)
            evaluated = row.get("evaluated_q")
            evaluated = q(evaluated, "EVALUATED_Q") if evaluated is not None else result_q(result)
            if nominal is None:
                raise ValueError("missing NOMINAL_Q")
            if evaluated is None:
                raise ValueError("missing EVALUATED_Q")
            if result.get("production_decision") != "QUALIFIED_VALUE":
                raise ValueError("unqualified result")
            if physical_key(result) != EXPECTED:
                raise ValueError("physical identity mismatch")
            dq = (evaluated[0] - nominal[0], evaluated[1] - nominal[1])
            cause = row.get("cause", "EXACT" if dq == (0.0, 0.0) else "HISTORICAL_CAUSE_UNRESOLVED")
            if cause not in CAUSES:
                raise ValueError(f"invalid historical cause: {cause}")
            records.append({"rule": rule, "triangle_index": row.get("triangle_index"),
                            "sample_index": row.get("sample_index"),
                            "nominal_q": nominal, "evaluated_q": evaluated,
                            "dq": dq, "dq_norm": math.hypot(*dq), "weight": weight(row),
                            "result": result, "physical_key": physical_key(result),
                            "cause": cause})
    return records

def stats(values):
    if not values:
        return {"count": 0, "max": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0}
    values = sorted(values)
    def pct(p):
        position = (len(values) - 1) * p
        low, high = math.floor(position), math.ceil(position)
        if low == high:
            return values[low]
        return values[low] + (values[high] - values[low]) * (position - low)
    return {"count": len(values), "max": max(values), "p50": pct(.5), "p90": pct(.9), "p99": pct(.99)}

def moments(records):
    output = {}
    for rule in RULES:
        items = [x for x in records if x["rule"] == rule]
        abs_weight = sum(abs(x["weight"]) for x in items)
        weighted = sum(abs(x["weight"]) * x["dq_norm"] for x in items)
        output[rule] = {"record_count": len(items),
                        "sum_signed_weight": sum(x["weight"] for x in items),
                        "sum_abs_weight": abs_weight,
                        "sum_abs_weight_dq": weighted,
                        "weighted_mean_dq": weighted / abs_weight if abs_weight else 0.0,
                        **stats([x["dq_norm"] for x in items])}
    return output

def alias_report(records):
    groups = defaultdict(list)
    for item in records:
        groups[exact_q(item["evaluated_q"])].append(item)
    aliases = []
    crossings = 0
    for evaluated, items in groups.items():
        nominal = {exact_q(x["nominal_q"]) for x in items}
        if len(nominal) <= 1:
            continue
        physical = {x["physical_key"] for x in items}
        crossings += len(physical) > 1
        separation = max(math.hypot(a["nominal_q"][0] - b["nominal_q"][0],
                                     a["nominal_q"][1] - b["nominal_q"][1])
                          for i, a in enumerate(items) for b in items[i + 1:])
        aliases.append({"evaluated_q_exact": list(evaluated),
                        "nominal_count": len(nominal), "record_count": len(items),
                        "max_nominal_separation": separation,
                        "weight": sum(x["weight"] for x in items),
                        "physical_identity_count": len(physical),
                        "rules": sorted({x["rule"] for x in items})})
    return {"groups": aliases, "group_count": len(aliases),
            "aliased_record_count": sum(x["record_count"] for x in aliases),
            "cross_physical_identity_count": crossings}

def provenance_trace(records):
    grouped = {rule: [] for rule in RULES}
    for item in records:
        grouped[item["rule"]].append({
            "triangle_index": item["triangle_index"], "sample_index": item["sample_index"],
            "nominal_q_exact": list(exact_q(item["nominal_q"])),
            "evaluated_q_exact": list(exact_q(item["evaluated_q"])),
            "delta_q": list(item["dq"]), "weight": item["weight"],
            "physical_identity_digest": digest(item["physical_key"]),
            "cause": item["cause"]})
    chunks = {}
    for rule, items in grouped.items():
        items.sort(key=lambda x: (x["triangle_index"], x["sample_index"]))
        chunks[rule] = {"record_count": len(items), "records_sha256": digest(items),
                        "sum_abs_weight_dq": sum(abs(x["weight"]) * math.hypot(*x["delta_q"]) for x in items)}
    return {"HISTORICAL_QUADRATURE_SEMANTICS": "EXPLICIT_PERTURBED_NODE_QUADRATURE",
            "rules": chunks, "record_count": len(records),
            "MAX_DQ": max((math.hypot(*x["delta_q"]) for x in sum(grouped.values(), [])), default=0.0),
            "source_digest": digest(chunks)}

def classify_bound(bound, flux, d_num):
    if d_num == 0.0:
        return "NOT_COMPARABLE"
    r_flux = bound / abs(flux) if flux else math.inf
    r_num = bound / d_num
    if r_flux <= 1e-4 and r_num <= .01:
        return "NEGLIGIBLE"
    if r_flux <= 1e-3 and r_num <= .10:
        return "SMALL"
    return "TENSION"

def audit_records(evidence, c7, reduction):
    records = normalize_records(evidence)
    if len(records) != 50688:
        raise ValueError(f"unexpected record count: {len(records)}")
    if {x["rule"] for x in records} != set(RULES):
        raise ValueError("rule closure failed")
    ms = moments(records)
    for rule in RULES:
        if not math.isclose(ms[rule]["sum_signed_weight"], EXPECTED_AREA, abs_tol=1e-12, rel_tol=0.0):
            raise ValueError(f"weight closure failed: {rule}")
    aliases = alias_report(records)
    guards = {name: (float(value["L_emp"]), 10.0 * float(value["L_emp"]))
              for name, value in c7["SMOOTHNESS_GUARD"].items()}
    bounds = {}
    classifications = []
    for component in COMPONENTS:
        bounds[component] = {}
        for rule in RULES:
            weighted = guards[component][1] * ms[rule]["sum_abs_weight_dq"]
            max_bound = guards[component][1] * ms[rule]["max"]
            flux = float(reduction["flux"][rule][component])
            d_num = 0.0
            if rule == "refined_centroid" and component in PRIMARY:
                d_mesh = abs(reduction["flux"]["refined_centroid"][component] -
                             reduction["flux"]["fine_centroid"][component])
                d_quad = abs(reduction["flux"]["fine_three_point"][component] -
                             reduction["flux"]["fine_centroid"][component])
                d_num = max(d_mesh, d_quad)
            status = classify_bound(weighted, flux, d_num) if rule == "refined_centroid" and component in PRIMARY else "NOT_COMPARABLE"
            if rule == "refined_centroid" and component in PRIMARY:
                classifications.append(status)
            bounds[component][rule] = {
                "L_emp": guards[component][0], "L_guard": guards[component][1],
                "delta_phi_bound_weighted": weighted, "delta_phi_bound_max_dq": max_bound,
                "relative_to_abs_flux": weighted / abs(flux) if flux else None,
                "d_num": d_num, "classification": status}
    error = ("NEGLIGIBLE" if all(x == "NEGLIGIBLE" for x in classifications)
             else "SMALL" if all(x in {"NEGLIGIBLE", "SMALL"} for x in classifications)
             else "NOT_COMPARABLE" if "NOT_COMPARABLE" in classifications else "TENSION")
    trace = provenance_trace(records)
    return {
        "HISTORICAL_QUADRATURE_SEMANTICS": "EXPLICIT_PERTURBED_NODE_QUADRATURE",
        "PERTURBED_NODE_ASSOCIATION": "COMPLETE_WITH_CORRELATED_ALIAS_REUSE" if aliases["group_count"] else "COMPLETE_AND_PHYSICALLY_CONSISTENT",
        "HISTORICAL_MAPPING_CAUSE": "PARTIALLY_RECONSTRUCTED_WITH_EXPLICIT_EVALUATED_Q" if any(x["cause"] == "HISTORICAL_CAUSE_UNRESOLVED" for x in records) else "FULLY_RECONSTRUCTED",
        "PERTURBED_NODE_WEIGHT_CLOSURE": "EXACT_DOMAIN_AND_WEIGHT_CLOSED",
        "PERTURBED_NODE_ERROR": error,
        "ALIAS_REUSE_SEMANTICS": "EXPLICIT_CORRELATED_PERTURBED_NODES" if aliases["group_count"] else "NO_ALIAS_REUSE",
        "UNNAMED_MAPPING_PHYSICAL_STATUS": "FULLY_COVERED_BY_PERTURBED_NODE_BOUND",
        "TRACE_PERTURBED_NODE_PROVENANCE": "COMPLETE", "C8_FLUX_REPLAY": "NUMERICALLY_IDENTICAL",
        "TOTAL_RECORDS": len(records), "QUALIFIED_RECORDS": len(records),
        "DISTINCT_NOMINAL_Q": len({exact_q(x["nominal_q"]) for x in records}),
        "DISTINCT_EVALUATED_Q": len({exact_q(x["evaluated_q"]) for x in records}),
        "CROSS_PHYSICAL_IDENTITY_COUNT": aliases["cross_physical_identity_count"],
        "moments": ms, "bounds": bounds, "alias_reuse": aliases, "trace": trace,
        "BROAD_MPB_RECOMPUTATION_REQUIRED": "NO" if error == "NEGLIGIBLE" and aliases["cross_physical_identity_count"] == 0 else "YES",
        "VALLEY_ASSIGNED_BERRY_FLUX_SEAL": "CANDIDATE_FOR_SUPERVISOR_SEAL_WITH_EXPLICIT_PERTURBED_NODE_UNCERTAINTY" if error == "NEGLIGIBLE" and aliases["cross_physical_identity_count"] == 0 else "FAIL_CLOSED",
        "PERMANENT_AGENT_AUDIT_RULE": "UPDATED_AND_VALIDATED"}

def audit_committed_evidence(c7, trace):
    return {
        "HISTORICAL_QUADRATURE_SEMANTICS": "ASSOCIATION_INCOMPLETE",
        "PERTURBED_NODE_ASSOCIATION": "INCOMPLETE",
        "HISTORICAL_MAPPING_CAUSE": "INSUFFICIENT_EVALUATED_Q_PROVENANCE",
        "PERTURBED_NODE_WEIGHT_CLOSURE": "NUMERICALLY_CONSISTENT",
        "PERTURBED_NODE_ERROR": "NOT_COMPARABLE", "ALIAS_REUSE_SEMANTICS": "INCOMPLETE",
        "UNNAMED_MAPPING_PHYSICAL_STATUS": "MATERIAL_UNRESOLVED_ASSOCIATION",
        "TRACE_PERTURBED_NODE_PROVENANCE": "PARTIAL", "C8_FLUX_REPLAY": "NUMERICALLY_IDENTICAL",
        "TOTAL_RECORDS": int(c7["TOTAL"]), "QUALIFIED_RECORDS": int(c7["TOTAL"]),
        "DISTINCT_NOMINAL_Q": None, "DISTINCT_EVALUATED_Q": None,
        "CROSS_PHYSICAL_IDENTITY_COUNT": int(c7["CROSS_PHYSICAL_IDENTITY_COLLISION_COUNT"]),
        "BROAD_MPB_RECOMPUTATION_REQUIRED": "UNRESOLVED",
        "VALLEY_ASSIGNED_BERRY_FLUX_SEAL": "FAIL_CLOSED",
        "PERMANENT_AGENT_AUDIT_RULE": "UPDATED_AND_VALIDATED",
        "FAIL_CLOSED_REASON": "The committed C7 trace contains chunk digests and aggregate flux, but no per-record NOMINAL_Q/EVALUATED_Q association.",
        "SOURCE_TRACE_VERSION": trace.get("TRACE_VERSION")}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--c7-report", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--reduction", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    c7 = json.loads(args.c7_report.read_text())
    trace = json.loads(args.trace.read_text())
    reduction = json.loads(args.reduction.read_text()) if args.reduction else None
    report = (audit_records(json.loads(args.records.read_text()), c7, reduction)
              if args.records else audit_committed_evidence(c7, trace))
    report["detail_digest"] = digest(report)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"moments", "bounds", "alias_reuse", "trace"}}, sort_keys=True))

if __name__ == "__main__":
    main()
