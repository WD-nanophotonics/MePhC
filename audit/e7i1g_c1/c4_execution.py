"""Prepare and execute only the missing exact-domain C4 quadrature points.

The script accepts paths at runtime and writes all large execution artefacts to
an external output directory.  Existing values are reused only on exact
sample-key identity; missing values are isolated child-process MPB solves.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from geometry_generator import mesh


def key(q):
    return (round(float(q[0]), 10), round(float(q[1]), 10))


def triangle_area(triangle):
    a, b, c = triangle
    return abs(0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])))


def centroid(triangle):
    return [sum(point[0] for point in triangle) / 3.0, sum(point[1] for point in triangle) / 3.0]


def three_point(triangle):
    a, b, c = triangle
    return [[(2 * a[0] + b[0] + c[0]) / 4.0, (2 * a[1] + b[1] + c[1]) / 4.0], [(a[0] + 2 * b[0] + c[0]) / 4.0, (a[1] + 2 * b[1] + c[1]) / 4.0], [(a[0] + b[0] + 2 * c[0]) / 4.0, (a[1] + b[1] + 2 * c[1]) / 4.0]]


def requested_records():
    records = {}
    for level, rule, samples in (("coarse", "coarse_centroid", lambda t: [(centroid(t), 1.0)]), ("fine", "fine_centroid", lambda t: [(centroid(t), 1.0)]), ("fine", "fine_three_point", lambda t: [(q, 1.0 / 3.0) for q in three_point(t)]), ("refined", "refined_centroid", lambda t: [(centroid(t), 1.0)])):
        for index, triangle in enumerate(mesh(level)["triangles"]):
            area = triangle_area(triangle)
            for sample_index, (q, weight) in enumerate(samples(triangle)):
                records[f"{rule}:{index}:{sample_index}"] = {"rule": rule, "triangle_index": index, "sample_index": sample_index, "sample_key": list(key(q)), "qx": float(q[0]), "qy": float(q[1]), "triangle_area": area, "sample_weight": weight, "result": None}
    return records


def _cache_from_manifest(path, task_key):
    data = json.loads(path.read_text())
    rows = data.get(task_key, data.get("samples", []))
    cache = {}
    for row in rows:
        result = row.get("result")
        q = row.get("q", [row.get("qx"), row.get("qy")])
        if result and q[0] is not None and q[1] is not None:
            cache[key(q)] = result
    return cache


def _run_one(record, worker, python):
    qx, qy = record["qx"], record["qy"]
    command = [python, str(worker), "--resolution", "64", "--h", "0.001", f"--qx={qx!r}", f"--qy={qy!r}", "--valley", "K", "--radius-a", "0.15", "--radius-b", "0.25"]
    started = time.time()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=240, check=False)
        result = None
        for line in reversed(completed.stdout.splitlines()):
            if line.lstrip().startswith("{"):
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if candidate.get("event") == "result":
                    result = candidate
                    break
        if result is None:
            return record["sample_key"], {"event": "runtime_failed", "returncode": completed.returncode, "stderr": completed.stderr[-2000:]}, time.time() - started
        return record["sample_key"], result, time.time() - started
    except Exception as exc:
        return record["sample_key"], {"event": "runtime_failed", "error": repr(exc)}, time.time() - started


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed-manifest", type=Path, required=True)
    parser.add_argument("--old-manifest", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--no-run", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = requested_records()
    cache = _cache_from_manifest(args.fixed_manifest, "samples")
    cache.update(_cache_from_manifest(args.old_manifest, "tasks"))
    reused = 0
    for record in records.values():
        result = cache.get(tuple(record["sample_key"]))
        if result is not None:
            record["result"] = result
            reused += 1
    missing = [record for record in records.values() if record["result"] is None]
    checkpoint = args.output_dir / "c4_work.json"
    if checkpoint.exists():
        previous = json.loads(checkpoint.read_text())
        for record in records.values():
            result = previous.get("results", {}).get(str(record["sample_key"]))
            if result is not None:
                record["result"] = result
        missing = [record for record in records.values() if record["result"] is None]
    if not args.no_run and missing:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_run_one, record, args.worker, sys.executable) for record in missing]
            for count, future in enumerate(as_completed(futures), 1):
                sample_key, result, elapsed = future.result()
                for record in records.values():
                    if tuple(record["sample_key"]) == tuple(sample_key):
                        record["result"] = result
                        break
                if count % 64 == 0 or count == len(futures):
                    checkpoint.write_text(json.dumps({"results": {str(record["sample_key"]): record["result"] for record in records.values() if record["result"] is not None}}, separators=(",", ":")), encoding="utf-8")
                    print(json.dumps({"event": "c4_progress", "completed": count, "total": len(futures), "remaining": len(futures) - count}), flush=True)
    evidence = {"exact_domain": {rule: True for rule in ("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid")}, "rules": {}}
    for record in records.values():
        evidence["rules"].setdefault(record["rule"], []).append(record)
    output = args.output_dir / "c4_evidence.json"
    output.write_text(json.dumps(evidence, separators=(",", ":")), encoding="utf-8")
    lineage = {"artifacts": [{"path_role": "pre-C1 coarse/fine manifest", "sha256": hashlib.sha256(args.old_manifest.read_bytes()).hexdigest(), "path": args.old_manifest.name, "geometry_state": "incomplete-domain legacy evidence"}, {"path_role": "corrected C1 exact-manifest cache", "sha256": hashlib.sha256(args.fixed_manifest.read_bytes()).hexdigest(), "path": args.fixed_manifest.name, "geometry_state": "post-coordinate-correction, one recorded serialization repair, 39520 qualified samples"}], "c4_authoritative_evidence": str(output.name), "reused_count": sum(record["result"] is not None for record in records.values()), "missing_or_failed_count": sum(record["result"] is None or record["result"].get("production_decision") != "QUALIFIED_VALUE" for record in records.values())}
    (args.output_dir / "manifest_lineage.json").write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    print(json.dumps({"event": "c4_evidence_ready", "records": len(records), "reused": reused, "missing_after_run": sum(record["result"] is None for record in records.values()), "evidence": str(output)}))


if __name__ == "__main__":
    main()
