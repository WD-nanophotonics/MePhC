"""E9D audit-only Berry map plotter; numerical JSON remains authoritative."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def plot(result_path, output_dir):
    import matplotlib.pyplot as plt
    result = json.loads(Path(result_path).read_text(encoding="utf-8-sig"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    grid = result["map_grid"]
    values = {1: np.full((13, 13), np.nan), 2: np.full((13, 13), np.nan), 3: np.full((13, 13), np.nan)}
    for row in result["numerical_map"]:
        for band in (1, 2, 3):
            value = row["bands"][band - 1]["Omega_over_a2"]
            if value is not None:
                values[band][row["grid_j"] + 6, row["grid_i"] + 6] = value
    paths = []
    for band in (1, 2, 3):
        fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
        image = ax.imshow(values[band], origin="lower", extent=(-1/6, 1/6, -1/6, 1/6), aspect="equal", cmap="coolwarm")
        ax.set_title(f"E9D Berry curvature band {band} (R64, side 1/36)")
        ax.set_xlabel("q_x offset from public K-prime")
        ax.set_ylabel("q_y offset from public K-prime")
        fig.colorbar(image, ax=ax, label="Omega / a^2")
        path = output_dir / f"band{band}_berry_map.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(str(path))
    return paths


if __name__ == "__main__":
    result_path = sys.argv[sys.argv.index("--result") + 1] if "--result" in sys.argv else str(ROOT / "audit/e9d/result.json")
    output_dir = sys.argv[sys.argv.index("--output-dir") + 1] if "--output-dir" in sys.argv else str(ROOT / "audit/e9d/plots")
    print(json.dumps({"plots": plot(result_path, output_dir)}, sort_keys=True))

