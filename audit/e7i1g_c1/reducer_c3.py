from __future__ import annotations
import argparse, json
from pathlib import Path
from boundary_gate import classify_boundary
from reducer import normalize_mesh, reduce, signed_area

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument('--trace', type=Path, required=True); p.add_argument('--controls', type=Path, required=True); p.add_argument('--geometry', type=Path, required=True); a = p.parse_args()
    controls = json.loads(a.controls.read_text()); geom = json.loads(a.geometry.read_text())
    triangles, area = normalize_mesh(geom['points_offset_K'], geom['triangles'])
    expected = 1 / 3.**0.5
    if not all(signed_area(t) > 0 for t in triangles) or abs(area - expected) > 1e-9: raise ValueError('signed mesh contract failed')
    controls['orientation'] = {'all_ccw': True, 'normalized_total_area': area, 'expected_total_area': expected}
    result = reduce(json.loads(a.trace.read_text()), controls)
    result['boundary'] = classify_boundary(controls['boundary_controls'])
    result['signed_mesh'] = {'triangle_count': len(triangles), 'normalized_total_area': area, 'expected_total_area': expected}
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == '__main__': main()
