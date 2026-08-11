from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mephc.band import Band


def main():
    band = Band(a=400, r1=90, r2=None, n_eff=2.7, h=1, resolution=10)
    pattern = band.create_unitcell(3, 30, show=False)

    fast = band.compute_band_path_with_berry(
        pattern=pattern,
        n_per_segment=1,
        step=0.02,
        num_bands=2,
        compute_bc=False,
    )
    print("fast path k_points shape:", fast["k_points"].shape)
    print("fast path freqs shape:", fast["freqs"].shape)
    print("fast path bcs:", fast["bcs"])

    with_bc = band.compute_band_path_with_berry(
        pattern=pattern,
        n_per_segment=1,
        step=0.02,
        num_bands=2,
        compute_bc=True,
    )
    print("with BC freqs shape:", with_bc["freqs"].shape)
    print("with BC bcs shape:", with_bc["bcs"].shape)
    print("first k/freq/bc:", with_bc["k_points"][0], with_bc["freqs"][0], with_bc["bcs"][0])


if __name__ == "__main__":
    main()