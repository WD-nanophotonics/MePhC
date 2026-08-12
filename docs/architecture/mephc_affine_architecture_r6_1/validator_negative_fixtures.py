#!/usr/bin/env python3
"""Negative checks proving the R6.1 validator rejects common residual-data faults."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import validate_r6_1

def main():
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        for name in validate_r6_1.REQUIRED:
            source = root / name
            target = fixture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        target = fixture / "corrected_benchmark_field.json"
        value = json.loads(target.read_text())
        value["formula"] = "pooled"
        target.write_text(json.dumps(value))
        if validate_r6_1.main(fixture) == 0:
            raise SystemExit("negative fixture unexpectedly passed")
    print("PASS_R6_1_NEGATIVE_FIXTURE")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
