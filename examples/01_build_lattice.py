from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mephc.lattice import Lattice
from mephc.patterns import pattern_summary


def main():
    lattice = Lattice(
        period=1,
        outline=[(-0.1, 0.6), (1, 0.6), (1, 0), (-0.1, 0)],
        orientation=0,
        lattice_type="hc",
    )
    pattern = lattice.PolygonPattern(3, 0.25, 30, 3, 0.18, 0)
    print("lattice layers:", len(lattice.points))
    print("points per layer:", [len(layer) for layer in lattice.points])
    print("pattern summary:", pattern_summary(pattern))


if __name__ == "__main__":
    main()