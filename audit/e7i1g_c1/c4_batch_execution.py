"""Bounded batch execution for missing C4 exact-domain samples."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from c4_execution import _cache_from_manifest, key, requested_records


def run_batch(records, worker, input_dir, index):
    input_path = input_dir / f"batch_{index:05d}.json"
    input_path.write_text(json.dumps([{"sample_key": r["sample_key"], "qx": r["qx"], "qy": r["qy"]} for r in records], separators=(",", ":")), encoding="utf-8")
    command = [sys.executable, str(worker), "--input", str(input_path)]
    started = time.time()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
        results = {}
        for line in completed.stdout.splitlines():
            if not line.lstrip().startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("sample_key") is not None and row.get("result") is not None:
                results[tuple(row["sample_key"])] = row["result"]
        return index, results, {"returncode": completed.returncode, "elapsed_seconds": time.time() - started, "stderr_tail": completed.stderr[-1000:]}
    except Exception as exc:
        return index, {}, {"error": repr(exc), "elapsed_seconds": time.time() - started}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed-manifest", type=Path, required=True)
    parser.add_argument("--old-manifest", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit-batches", type=int)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    batch_dir = args.output_dir / "batches"
    batch_dir.mkdir(exist_ok=True)
    records = requested_records()
    cache = _cache_from_manifest(args.old_manifest, "tasks")
    cache.update(_cache_from_manifest(args.fixed_manifest, "samples"))
    checkpoint = args.output_dir / "c4_batch_checkpoint.json"
    if checkpoint.exists():
        cache.update({tuple(json.loads(k)): value for k, value in json.loads(checkpoint.read_text()).get("results", {}).items()})
    for record in records.values():
        if tuple(record["sample_key"]) in cache:
            record["result"] = cache[tuple(record["sample_key"])]
    missing_by_key = {}
    for record in records.values():
        if record["result"] is None:
            missing_by_key.setdefault(tuple(record["sample_key"]), record)
    missing = list(missing_by_key.values())
    batches = [missing[start:start + args.batch_size] for start in range(0, len(missing), args.batch_size)]
    if args.limit_batches is not None:
        batches = batches[:args.limit_batches]
    print(json.dumps({"event": "c4_batch_start", "total_records": len(records), "cached_unique": len(cache), "missing_unique": len(missing), "batches": len(batches), "batch_size": args.batch_size}), flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_batch, batch, args.worker, batch_dir, index) for index, batch in enumerate(batches)]
        for count, future in enumerate(as_completed(futures), 1):
            index, result_map, meta = future.result()
            cache.update(result_map)
            checkpoint.write_text(json.dumps({"results": {json.dumps(list(k)): value for k, value in cache.items()}}, separators=(",", ":")), encoding="utf-8")
            print(json.dumps({"event": "c4_batch_progress", "completed_batches": count, "total_batches": len(batches), "batch_index": index, "results_received": len(result_map), "elapsed_seconds": meta.get("elapsed_seconds"), "returncode": meta.get("returncode")}), flush=True)
    for record in records.values():
        record["result"] = cache.get(tuple(record["sample_key"]))
    evidence = {"exact_domain": {rule: True for rule in ("coarse_centroid", "fine_centroid", "fine_three_point", "refined_centroid")}, "rules": {}}
    for record in records.values():
        evidence["rules"].setdefault(record["rule"], []).append(record)
    evidence_path = args.output_dir / "c4_evidence.json"
    evidence_path.write_text(json.dumps(evidence, separators=(",", ":")), encoding="utf-8")
    lineage = {"artifacts": [{"path_role": "pre-C1 coarse/fine manifest", "sha256": hashlib.sha256(args.old_manifest.read_bytes()).hexdigest(), "geometry_state": "incomplete-domain legacy evidence"}, {"path_role": "corrected C1 exact-manifest cache", "sha256": hashlib.sha256(args.fixed_manifest.read_bytes()).hexdigest(), "geometry_state": "post-coordinate-correction, one recorded serialization repair"}], "c4_evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(), "evidence_path": evidence_path.name, "all_required_qualified": all(record["result"] and record["result"].get("production_decision") == "QUALIFIED_VALUE" for record in records.values())}
    (args.output_dir / "manifest_lineage.json").write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    print(json.dumps({"event": "c4_batch_complete", "records": len(records), "unique_results": len(cache), "missing": sum(record["result"] is None for record in records.values()), "evidence": str(evidence_path), "all_required_qualified": lineage["all_required_qualified"]}), flush=True)


if __name__ == "__main__":
    main()
