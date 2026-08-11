from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import meep as mp

from mephc.geometry import to_meep_geometry
from mephc.lattice import Lattice


def main():
    lattice = Lattice(
        period=1,
        outline=[(-0.1, 0.6), (1, 0.6), (1, 0), (-0.1, 0)],
        orientation=0,
        lattice_type="t",
    )
    pattern = lattice.PolygonPattern(6, 0.2, 0)
    geometry = to_meep_geometry(pattern, material=mp.air, height=1, shape="prism")
    print("geometry objects:", len(geometry))
    print("geometry types:", sorted({type(obj).__name__ for obj in geometry}))

    radius_geometry = to_meep_geometry({(0, 0): 0.1, (0.5, 0.5): 0.2}, height=1)
    print("radius geometry objects:", len(radius_geometry))
    print("radius geometry types:", sorted({type(obj).__name__ for obj in radius_geometry}))


if __name__ == "__main__":
    main()