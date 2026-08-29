"""One fixed, minimal MPB environment smoke; not a scientific dataset."""
from __future__ import annotations

import json

import meep as mp
from meep import mpb


solver = mpb.ModeSolver(
    geometry_lattice=mp.Lattice(size=mp.Vector3(1, 1)),
    geometry=[],
    k_points=[mp.Vector3(0, 0)],
    resolution=4,
    num_bands=1,
)
solver.run()
print(json.dumps({
    "schema": "mephc-thin-mpb-smoke-v1",
    "k_point_count": 1,
    "num_bands": 1,
    "resolution": 4,
    "frequency_count": len(solver.all_freqs[0]),
}, sort_keys=True))
