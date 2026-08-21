"""Geometry-aware entry point for the deterministic C1 reducer."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from reducer import normalize_mesh, reduce

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    args = parser.parse_args()
    geometry = json.loads(args.geometry.read_text())
    triangles, total_area = normalize_mesh(geometry["points_offset_K"], geometry["triangles"])
    if not all(sum(1 for _ in [t]) and (t[1][0]-t[0][0])*(t[2][1]-t[0][1])-(t[1][1]-t[0][1])*(t[2][0]-t[0][0]) > 0 for t in triangles):
        raise ValueError("mixed orientation after normalization")
    expected = 1 / math.sqrt(3)
    if not math.isclose(total_area, expected, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"signed exact-mesh area mismatch: {total_area} != {expected}")
    controls = json.loads(args.controls.read_text())
    controls["orientation"] = {"all_ccw": True, "normalized_total_area": total_area, "expected_total_area": expected}
    result = reduce(json.loads(args.trace.read_text()), controls)
    result["signed_mesh"] = {"triangle_count": len(triangles), "normalized_total_area": total_area, "expected_total_area": expected}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
