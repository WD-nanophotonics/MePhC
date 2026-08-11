from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from mephc.band import Band
from mephc.efs import EFSInterpolator


def main():
    band = Band(a=400, r1=90, r2=None, n_eff=2.7, h=1, resolution=8)
    pattern = band.create_unitcell(3, 30, show=False)

    xs = np.linspace(0.0, 0.7, 3)
    ys = np.linspace(-0.25, 0.25, 3)
    k_points = np.array([(x, y) for x in xs for y in ys], dtype=float)
    result = band.compute_efs(pattern, k_points=k_points, num_bands=2)
    print("k_points shape:", result.k_points.shape)
    print("freqs shape:", result.freqs.shape)
    print("actual freqs shape:", result.actual_freqs.shape)

    fig, ax = band.plot_efs(
        result,
        band_index=0,
        use_actual=True,
        mesh_size=40,
        interpolation="linear",
        levels=6,
        show=True,
    )
    print("plot axes title:", ax.get_title())

    interpolator = EFSInterpolator(result.k_points, result.actual_freqs[:, 0], mesh_size=40, method="linear")
    freqs, angles = interpolator.cutline(ky=0.0, kx_values=np.linspace(0.1, 0.6, 4))
    print("cutline freqs:", freqs)
    print("cutline angles:", angles)


if __name__ == "__main__":
    main()