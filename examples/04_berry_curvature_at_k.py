from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mephc.band import Band


def main():
    band = Band(a=400, r1=90, r2=None, n_eff=2.7, h=1, resolution=12)
    pattern = band.create_unitcell(3, 30, show=False)

    k_point = (2.0 / 3.0 + 0.01, 0.01)
    values = band.calculate_berry_curvature(
        pattern=pattern,
        k_point=k_point,
        step=0.01,
        num_bands=2,
    )

    print("k point:", k_point)
    print("berry curvature all bands:", values)
    print("berry curvature band 1:", values[0])


if __name__ == "__main__":
    main()