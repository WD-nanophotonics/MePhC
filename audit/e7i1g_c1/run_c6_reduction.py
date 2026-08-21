"""Replay C6 using only committed trace and compact controls."""
from __future__ import annotations
import argparse,copy,json,statistics
from pathlib import Path
from geometry_generator import EXPECTED_AREA,mesh
from reducer_c6_scaled import reduce
def normalize(record):
    result=copy.deepcopy(record)
    if "omega_bands_q" not in result and "omega_band1" in result and "omega_band2" in result: result["omega_bands_q"]=[result["omega_band1"],result["omega_band2"]]
    return result
def controls(path):
    value=json.loads(path.read_text()); sentinels=[item["r64"] for item in value["resolution_sentinels"]]
    s1=statistics.median(abs(float(item["omega_band1"])) for item in sentinels); s2=statistics.median(abs(float(item["omega_band2"])) for item in sentinels)
    for row in value["seam_pairs"]: row["a"],row["b"]=normalize(row["a"]),normalize(row["b"]); row["scale_band1"],row["scale_band2"]=s1,s2
    for row in value["inversion_pairs"]: row["base"],row["plus"]=normalize(row["base"]),normalize(row["plus"]); row["scale_band1"],row["scale_band2"]=s1,s2
    value["orientation"]={"all_ccw":True,"normalized_total_area":mesh("refined")["signed_area"],"expected_total_area":EXPECTED_AREA}; value["hybrid_scale_definition"]="R64_SENTINEL_MEDIAN_ABS"; value["scale_band1"]=s1; value["scale_band2"]=s2
    return value
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--trace",type=Path,required=True); parser.add_argument("--controls",type=Path,required=True); args=parser.parse_args(); print(json.dumps(reduce(json.loads(args.trace.read_text()),controls(args.controls)),indent=2,sort_keys=True))
if __name__=="__main__": main()
