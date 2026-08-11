from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from meep import mpb

from mephc.band import Band


def main():
    band = Band(a=400, r1=180, r2=80, n_eff=2.7, h=100, resolution=32)
    pattern = band.create_unitcell(3, 30, show=False)
    freqs = band.run_simulation_te(pattern, [band.K], num_b=2, show_dielectric=False)
    print("mpb available:", hasattr(mpb, "ModeSolver"))
    print("normalized frequencies:", freqs)
    print("actual frequencies THz:", band.calculate_actual_freqs(freqs))


if __name__ == "__main__":
    main()