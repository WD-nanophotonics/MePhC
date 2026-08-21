"""Run the scale-aware C4 reducer on compact control evidence."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from geometry_generator import EXPECTED_AREA, mesh
from reducer_c4_scaled import reduce


def normalize_record(record):
    result = copy.deepcopy(record)
    if "omega_bands_q" not in result and "omega_band1" in result and "omega_band2" in result:
        result["omega_bands_q"] = [result["omega_band1"], result["omega_band2"]]
    return result


def controls_with_contract(path: Path) -> dict:
    controls = json.loads(path.read_text())
    for row in controls.get("seam_pairs", []):
        row["a"], row["b"] = normalize_record(row["a"]), normalize_record(row["b"])
    sentinel_values = [item[side] for item in controls.get("resolution_sentinels", []) for side in ("r64", "r96")]
    band1 = max(abs(float(item["omega_band1"])) for item in sentinel_values)
    band2 = max(abs(float(item["omega_band2"])) for item in sentinel_values)
    for row in controls.get("seam_pairs", []):
        row["scale_band1"], row["scale_band2"] = band1, band2
    for row in controls.get("inversion_pairs", []):
        row["base"], row["plus"] = normalize_record(row["base"]), normalize_record(row["plus"])
        row["scale_band1"], row["scale_band2"] = band1, band2
    controls["orientation"] = {"all_ccw": True, "normalized_total_area": mesh("refined")["signed_area"], "expected_total_area": EXPECTED_AREA}
    return controls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reduce(json.loads(args.trace.read_text()), controls_with_contract(args.controls)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
